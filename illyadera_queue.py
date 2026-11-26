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
        if rec.get('due_at') and abs((_dt(rec['due_at'])-_dt(post['dueAt'])).total_seconds())>90:
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
    now=_dt(now or dt.datetime.now(dt.timezone.utc))
    due=_dt(due_at)
    if due<=now+dt.timedelta(minutes=35):
        raise RuntimeError('Créneau trop proche : arbitrage automatique suspendu')
    posts=buffer.list_scheduled()
    if not isinstance(posts,list):raise RuntimeError('File Buffer illisible')
    if any(not isinstance(p,dict) or not all(p.get(k) for k in ('id','status','dueAt','text','channelId')) for p in posts):
        raise RuntimeError('Post Buffer incomplet, arbitrage suspendu')
    registry=registry if registry is not None else read_registry(registry_path)
    target=due.astimezone(PARIS).date().isoformat()
    existing_top=[p for p in posts if p['status']=='scheduled' and
                  _dt(p['dueAt']).astimezone(PARIS).date().isoformat()==target and
                  p['text'].lstrip('📚 ').upper().startswith(('TOP 7 BD','TOP 7 MANGA','TOP 5 COMICS','TOP 7 COMICS'))]
    if existing_top:
        return {'action':'TOP_DEJA_PREVU','file':len(posts),'date':target}
    owned=_eligible_owned(posts,registry,now)
    owned_ids={item[2]['id'] for item in owned}
    unknown_at_target=[p for p in posts if
        _dt(p['dueAt']).astimezone(PARIS).date().isoformat()==target
        and p['id'] not in owned_ids]
    if unknown_at_target:
        raise RuntimeError('Créneau du Top déjà occupé par une publication non gérée : aucun remplacement ni doublon automatique')
    at_target=[x for x in owned if x[0]==target]
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
    result=buffer.delete_own(post['id'])
    if not isinstance(result,dict) or result.get('id')!=post['id']:
        raise RuntimeError('Suppression non confirmée par Buffer, état inchangé')
    rec['etat']='LIBERE_POUR_'+priority
    rec['date_liberation_utc']=now.isoformat()
    rec['raison_liberation']=f'Priorité {priority} pour {target}'
    rec['ancien_id_buffer']=rec.get('id_buffer')
    registry[key]=rec
    save_registry(registry,registry_path)
    return {'action':'ANECDOTE_LIBEREE','date_liberation':key,'id_buffer':post['id'],'file_avant':len(posts),'priorite':priority}


def planned_slots(kind, now=None):
    """Déduit les horaires des clients existants, sans calendrier inventé."""
    now=now or dt.datetime.now(dt.timezone.utc)
    if kind=='BD':
        from calendrier import prochain_creneau
        suggestion=prochain_creneau('BD', now=now)
        if not suggestion:raise RuntimeError('Créneau BD absent')
        return [suggestion['dueAt']]
    if kind=='MANGA':
        from manga_buffer_auto import mardi_suivant
        return [mardi_suivant(now)]
    if kind=='COMICS':
        from comics_pipeline_periodique import load
        from comics_buffer_periodique import next_slot
        slots=[]
        for row in load(ROOT/'sorties'/'comics_periodique'/'PLAN_BUFFER.json') or []:
            folder=Path(row.get('folder',''))
            if not folder.is_absolute():folder=ROOT/folder
            data=load(folder.parent/'classement_comics.json')
            if data:slots.append(next_slot(data,now=now))
        return list(dict.fromkeys(slots))
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
        slots=planned_slots(args.kind)
        out={'kind':args.kind,'slots':slots,'actions':[]}
        for slot in slots:
            out['actions'].append(free_capacity_for_priority(slot,buffer=buf,max_posts=args.max_posts,priority=args.kind))
    print(json.dumps(out,ensure_ascii=False,indent=2))
    # Un rapport reste consultable depuis Actions; aucune clé n'est écrite.
    dest=ROOT/'sorties'/'queue_illyadera'
    dest.mkdir(exist_ok=True,parents=True)
    (dest/'ARBITRAGE_TOP.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
