"""Arbitrage central pour le canal Buffer d'Illyadera.

Le module n'invente aucun contenu. Il n'autorise une reprise de place que si
une publication ANECDOTE, enregistrée par notre agent, est retrouvée à l'ID,
au texte ET au créneau exacts dans la file Buffer.

À appeler UNIQUEMENT quand un Top est entièrement prêt à publier, juste avant
son envoi à Buffer. Le registre est sauvegardé avant le prochain appel.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo('Europe/Paris')
ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'anecdotes_state' / 'programmes.json'
MAX_DEFAULT = 10


def read_registry(path=REGISTRY):
    if not Path(path).is_file():
        return {}
    contents = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(contents, dict):
        raise ValueError('Registre d\'anecdotes corrompu : suppression interdite')
    return contents


def save_registry(registry,path=REGISTRY):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)


def _dt(value):
    from anecdotes_auto.buffer import parse
    if isinstance(value,dt.datetime):
        if value.tzinfo is None:raise ValueError('Date sans fuseau')
        return value.astimezone(dt.timezone.utc)
    return parse(value)


def _eligible_owned(posts,registry,now):
    """Aucune publication étrangère ou déjà publiée n'est jamais modifiée."""
    by_id={p['id']:p for p in posts if p.get('id')}
    candidates=[]
    for key,rec in registry.items():
        if not isinstance(rec,dict) or rec.get('etat')!='PROGRAMME':continue
        post=by_id.get(rec.get('id_buffer'))
        if not post:continue
        if post.get('status')!='scheduled' or not str(post.get('text','')).startswith('📚 ANECDOTE BD'):
            continue
        if (post.get('text') or '').strip()!=(rec.get('texte_public') or '').strip():continue
        if not post.get('dueAt') or _dt(post['dueAt'])<=now+dt.timedelta(minutes=40):continue
        if key!=_dt(post['dueAt']).astimezone(PARIS).date().isoformat():continue
        if not rec.get('due_at') or abs((_dt(rec['due_at'])-_dt(post['dueAt'])).total_seconds())>90:
            continue
        candidates.append((key,rec,post))
    return candidates


def free_capacity_for_priority(due_at, *, buffer, registry=None, registry_path=REGISTRY,
                               max_posts=MAX_DEFAULT, now=None, priority='TOP'):
    """Supprime au plus UNE anecdote nous appartenant si nécessaire.

    Pour un Top : une anecdote au même jour est libérée même quand la Queue
    est sous la limite. Si elle est pleine, on libère la plus lointaine.
    Toujours reconsulter Buffer avant la suppression (dans le même workflow
    GitHub avec verrou de concurrence partagé entre tous les agents).
    """
    if not 1<=max_posts<=MAX_DEFAULT:
        raise ValueError('Capacité Buffer Free : maximum 10 posts par canal')
    now=_dt(now or dt.datetime.now(dt.timezone.utc))
    due=_dt(due_at)
    if due<=now+dt.timedelta(minutes=35):
        raise RuntimeError('Créneau trop proche : arbitrage automatique suspendu')
    posts=buffer.list_scheduled()
    if not isinstance(posts,list):raise RuntimeError('File Buffer illisible')
    if any(not isinstance(p,dict) or not all(p.get(k) for k in ('id','status','dueAt','text','channelId')) for p in posts):
        raise RuntimeError('Post Buffer incomplet, arbitrage suspendu')
    registry=registry if registry is not None else read_registry(registry_path)
    from journal_publication import reconcile_intents,checkpoint
    if reconcile_intents(registry,posts,now):
        save_registry(registry,registry_path)
        checkpoint(registry_path)
    # Les entrées incertaines ne sont jamais éligibles à une suppression.
    # La vérification du créneau et de la capacité reste locale : les autres jours continuent.
    target=due.astimezone(PARIS).date().isoformat()
    existing_top=[p for p in posts if p['status']=='scheduled' and
                  _dt(p['dueAt']).astimezone(PARIS).date().isoformat()==target and
                  p['text'].lstrip('📚 ').upper().startswith(('TOP 7 BD','TOP 7 MANGA','TOP 5 COMICS','TOP 7 COMICS'))]
    if existing_top:
        prefixes={'BD':('TOP 7 BD',),'MANGA':('TOP 7 MANGA',),'COMICS':('TOP 5 COMICS','TOP 7 COMICS'),
                  'COMICS_HEBDO':('TOP 5 COMICS',),'COMICS_MENSUEL':('TOP 7 COMICS',)}
        same_day=[p for p in posts if _dt(p['dueAt']).astimezone(PARIS).date().isoformat()==target]
        if len(same_day)!=1 or len(existing_top)!=1 or priority=='REMPLISSAGE' or (priority in prefixes and not existing_top[0]['text'].lstrip('📚 ').upper().startswith(prefixes[priority])):
            raise RuntimeError('Créneau occupé par un autre classement : arbitrage interdit')
        return {'action':'TOP_DEJA_PREVU','file':len(posts),'date':target}
    if len(posts)>max_posts:
        raise RuntimeError('File au-delà du plafond gratuit : aucune suppression automatique')
    owned=_eligible_owned(posts,registry,now)
    owned_ids={item[2]['id'] for item in owned}
    unknown_at_target=[p for p in posts if
        _dt(p['dueAt']).astimezone(PARIS).date().isoformat()==target
        and p['id'] not in owned_ids]
    if unknown_at_target:
        raise RuntimeError('Créneau du Top déjà occupé par une publication non gérée : aucun remplacement ni doublon automatique')
    at_target=[x for x in owned if x[0]==target]
    if len(at_target)>1:
        raise RuntimeError('Plusieurs anecdotes le même jour : arbitrage suspendu')
    if at_target:
        selected=at_target[0]
    elif len(posts)>=max_posts:
        candidates = [x for x in owned if _dt(x[2]['dueAt']) > due] if priority == 'REMPLISSAGE' else owned
        selected=max(candidates,key=lambda x:_dt(x[2]['dueAt'])) if candidates else None
        if selected is None and priority == 'REMPLISSAGE':
            return {'action':'AUCUNE_ANECDOTE_PLUS_LOINTAINE','date':target,'file':len(posts)}
    else:
        return {'action':'PLACE_DISPONIBLE','file':len(posts),'date':target}
    if selected is None:
        raise RuntimeError(f'Buffer plein ({len(posts)}/{max_posts}), mais aucune anecdote future appartenant à Illiyadera ne peut être libérée sans risque')
    key,rec,post=selected
    # Vérifier une seconde fois le post exact avant l'opération irréversible.
    fresh=buffer.list_scheduled()
    if len(fresh)>max_posts or fresh!=posts:
        raise RuntimeError('File Buffer modifiée pendant le contrôle : aucune suppression')
    if not any(k==key and p['id']==post['id'] for k,_,p in _eligible_owned(fresh,registry,now)):
        raise RuntimeError('Identité ou créneau de l’anecdote non confirmé')
    rec['etat']='LIBERATION_EN_COURS'
    rec['intention_liberation']={'id_buffer':post['id'],'due_at':post['dueAt'],'priorite':priority,
                               'cible':target,'date_utc':now.isoformat()}
    registry[key]=rec
    save_registry(registry,registry_path)
    checkpoint(registry_path)
    result=buffer.delete_own(post['id'])
    if not isinstance(result,dict) or result.get('id')!=post['id']:
        raise RuntimeError('Suppression non confirmée par Buffer, intention conservée')
    rec['etat']='LIBERE_POUR_'+priority
    rec['date_liberation_utc']=now.isoformat()
    rec['raison_liberation']=f'Priorité {priority} pour {target}'
    rec['ancien_id_buffer']=rec.get('id_buffer')
    registry[key]=rec
    save_registry(registry,registry_path)
    checkpoint(registry_path)
    return {'action':'ANECDOTE_LIBEREE','date_liberation':key,'id_buffer':post['id'],'file_avant':len(posts),'priorite':priority}


def _receipt_exists(path, edition):
    path=Path(path)
    if not path.is_file():return False
    rec=json.loads(path.read_text(encoding='utf-8'))
    if rec.get('statut')!='POST_PROGRAMME' or rec.get('edition')!=edition or not rec.get('id_buffer'):
        raise RuntimeError('Reçu de classement incohérent : arbitrage suspendu')
    return True


def planned_slots(kind, now=None, *, preflight=False, edition=None, repo=None):
    """Déduit les horaires des clients existants, sans calendrier inventé."""
    now=now or dt.datetime.now(dt.timezone.utc)
    if kind=='BD':
        from calendrier_editorial import next_weekly
        return [next_weekly('BD',now)]
    if kind=='MANGA':
        from manga_buffer_auto import mardi_suivant, construire
        if preflight:
            from media_preflight import verify_public_assets
            import re
            if not edition or not re.fullmatch(r'MANGA_\d{4}-\d{2}-\d{2}',edition):raise RuntimeError('Edition manga absente')
            if _receipt_exists(ROOT/'manga_buffer_receipts'/(edition+'.json'),edition):return []
            from intentions_tops import lookup
            if lookup(edition):return []  # lecture/reprise uniquement ; aucune nouvelle suppression
            folder=ROOT/'sorties'/'manga_production'/edition/'MANGA'
            base=f'https://raw.githubusercontent.com/{repo}/main/public_media/{edition}/MANGA_sans_sources_v1/'
            payload=construire(folder,base,os.environ.get('BUFFER_CHANNEL_ID',''),now=now)
            verify_public_assets(payload['assets'])
            return [payload['dueAt']]
        return [mardi_suivant(now)]
    if kind=='COMICS':
        from comics_pipeline_periodique import load
        from comics_buffer_periodique import next_slot, construire
        from media_preflight import verify_public_assets
        slots=[]
        for row in load(ROOT/'sorties'/'comics_periodique'/'PLAN_BUFFER.json') or []:
            folder=Path(row.get('folder',''))
            if not folder.is_absolute():folder=ROOT/folder
            data=load(folder.parent/'classement_comics.json')
            if not data:raise RuntimeError('Classement Comics du plan absent')
            if preflight:
                if row.get('edition')!=data.get('edition'):raise RuntimeError('Edition Comics incohérente')
                if _receipt_exists(ROOT/'comics_buffer_receipts'/(data['edition']+'.json'),data['edition']):continue
                payload=construire(folder,row['base_url'],os.environ.get('BUFFER_CHANNEL_ID',''),now=now)
                verify_public_assets(payload['assets'])
                slots.append(payload['dueAt'])
            else:slots.append(next_slot(data,now=now))
        return sorted(set(slots),key=_dt)
    raise ValueError('Catégorie non reconnue')


def main():
    parser=argparse.ArgumentParser(description='Libérer une place vérifiée pour un TOP publié immédiatement après')
    parser.add_argument('action',choices=('before-top','audit'))
    parser.add_argument('--kind',choices=('BD','MANGA','COMICS'))
    parser.add_argument('--max-posts',type=int,default=int(os.environ.get('BUFFER_MAX_SCHEDULED','10')))
    args=parser.parse_args()
    from anecdotes_auto.buffer import Buffer
    buf=Buffer()
    if args.action=='audit':
        posts=buf.list_scheduled();out={'scheduled':len(posts),'limit':args.max_posts,'free':max(0,args.max_posts-len(posts))}
    else:
        if os.environ.get('ILLYADERA_TOP_VERIFIED','').lower()!='true':
            raise SystemExit('Arbitrage interdit hors du workflow ayant deja verifie un TOP complet')
        if not args.kind:parser.error('--kind obligatoire pour before-top')
        slots=planned_slots(args.kind,preflight=True,edition=os.environ.get('EDITION'),repo=os.environ.get('GITHUB_REPOSITORY'))
        out={'kind':args.kind,'slots':slots,'actions':[]}
        from calendrier_editorial import validate_slot,reserved_kind,parse_due
        for slot in slots:
            category=reserved_kind(parse_due(slot).date())
            if args.kind=='COMICS':
                if category not in ('COMICS_HEBDO','COMICS_MENSUEL'):raise RuntimeError('Créneau Comics invalide')
            elif category!=args.kind:raise RuntimeError('Créneau incompatible')
            validate_slot(category,slot)
            out['actions'].append(free_capacity_for_priority(slot,buffer=buf,max_posts=args.max_posts,priority=args.kind))
    print(json.dumps(out,ensure_ascii=False,indent=2))
    # Un rapport reste consultable depuis Actions; aucune clé n'est écrite.
    dest=ROOT/'sorties'/'queue_illyadera'
    dest.mkdir(exist_ok=True,parents=True)
    (dest/'ARBITRAGE_TOP.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
