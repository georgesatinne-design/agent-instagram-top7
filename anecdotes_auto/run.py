"""Exécution GitHub en deux phases : prepare -> git push médias -> send -> git push reçus.
La programmation d'une anecdote n'intervient qu'après vérification du vrai agenda Buffer.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,os,re,traceback
from pathlib import Path
from zoneinfo import ZoneInfo
from .catalogue import ROOT_REPO,STATE,CONFIG,bank,read,write,select,topic
from .calendrier import PARIS,next_days,eligible,reserved_kind,target_date_time
from .visuels import render,caption
from .storytelling import editorial_eligible
from .photos_reelles import resolve,PhotosIndisponibles
from .buffer import Buffer,BufferError,is_top,is_anecdote,utc,parse

PUBLIC=ROOT_REPO/'public_media'/'anecdotes_bd'
REPORT=ROOT_REPO/'sorties'/'anecdotes_bd'
REGISTRY=STATE/'programmes.json'
VERSION_VISUELLE='BD_STORY_PHOTOS_V5_NARRATION_SEMANTIQUE_2026_11'

def get_registry():
    registry=read(REGISTRY,{}) or {}
    if not isinstance(registry,dict):raise ValueError('Registre anecdotes corrompu')
    return registry

def persist(registry):write(REGISTRY,registry)

def proof(fact,now):
    output={k:fact.get(k) for k in ('id','url_source','preuve_courte','type_preuve',
        'controle_editorial','empreinte_page_sha256','controle_date_utc') if fact.get(k)}
    output.update({'consultation_interne':now.isoformat(),'note':'Les sources ne sont jamais envoyées dans les images ou légendes.'})
    write(STATE/'preuves'/f'{fact["id"]}.json',output)

def used_info(registry,day):
    completed={}
    topics={}
    for date_s,rec in registry.items():
        if not isinstance(rec,dict) or rec.get('etat') not in ('PROGRAMME','EN_ATTENTE'):continue
        if date_s>day.isoformat():continue
        fid=rec.get('fact_id')
        if fid:completed[fid]=date_s
        if rec.get('sujet'):
            topics[rec['sujet']]=max(date_s,topics.get(rec['sujet'],'0000-00-00'))
    return completed,topics

def stage_fact(fact,day,repo,now):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise RuntimeError('GITHUB_REPOSITORY invalide')
    folder=PUBLIC/day.isoformat()/fact['id']
    # Aucun visuel synthétique : recherches de photos préapprouvées et licences vérifiées.
    photos,media_proofs=resolve(fact)
    # Les preuves contiennent la page cible ET pourquoi l'image illustre ce passage.
    # Le mode sans scènes reste uniquement pour les anciens tests d'intégration mockés.
    scene_plan=(media_proofs if all(m.get('page') for m in media_proofs) else None)
    images=render(fact,folder,photos=photos,scenes=scene_plan,
        audit_path=STATE/'audit_compositions'/f'{day.isoformat()}_{fact["id"]}.json')
    text=caption(fact)
    (folder/'legende_instagram.txt').write_text(text+'\n',encoding='utf8')
    digest=hashlib.sha256(text.encode()+b''.join((folder/name).read_bytes() for name in images)).hexdigest()[:18]
    # Immutable publication URL for that fact/day/content revision.
    version_folder=PUBLIC/day.isoformat()/(fact['id']+'_'+digest)
    if version_folder!=folder:
        version_folder.mkdir(parents=True,exist_ok=True)
        import shutil
        for img in images:shutil.copyfile(folder/img,version_folder/img)
        shutil.copyfile(folder/'legende_instagram.txt',version_folder/'legende_instagram.txt')
        shutil.copyfile(folder/'apercu.png',version_folder/'apercu.png')
        shutil.rmtree(folder)
    proof(fact,now)
    # L'audit photo reste privé dans anecdotes_state, pas dans le texte public.
    write(STATE/'preuves_photos'/f'{fact["id"]}.json',{'photos':media_proofs})
    base=f'https://raw.githubusercontent.com/{repo}/main/{version_folder.relative_to(ROOT_REPO).as_posix()}/'
    return {'fact_id':fact['id'],'sujet':topic(fact),'etat':'EN_ATTENTE','date':day.isoformat(),
            'due_at':utc(target_date_time(day)),'dossier':str(version_folder.relative_to(ROOT_REPO)),
            'base_url':base,'images':images,'revision':digest,'date_preparation':now.isoformat(),
            'texte_public':text}

def prepare(repo,*,now=None,buffer=None,collect=True):
    now=now or dt.datetime.now(dt.timezone.utc)
    buffer=buffer or Buffer()
    REPORT.mkdir(parents=True,exist_ok=True)
    results={'date_utc':now.isoformat(),'candidats':len(bank()),'collecte':None,'plans':[],
             'jours':[],'erreurs':[]}
    if collect and CONFIG.get('collecte',{}).get('actif'):
        from .decouverte import discover
        try:results['collecte']=discover(now=now)
        except Exception as exc:results['erreurs'].append('COLLECTE: '+str(exc)[:250])
    all_facts=bank();facts=[f for f in all_facts if editorial_eligible(f)]
    results['candidats']=len(all_facts)
    results['creatifs_eligibles']=len(facts)
    registry=get_registry()
    facts_by_id={fact['id']:fact for fact in all_facts}
    dayposts={}
    for day in next_days(now):
        try:dayposts[day.isoformat()]=buffer.day(day)
        except Exception as exc:
            # Fail closed. A blind Buffer create could double a scheduled Top.
            results['erreurs'].append('BUFFER_JOUR '+str(day)+' : '+str(exc)[:200])
            write(REPORT/'ETAT.json',{'statut':'ERREUR_CONTROLE_BUFFER','erreurs':results['erreurs']})
            write(REPORT/'PLAN_BUFFER.json',[])
            raise
    scheduled_count=sum(len(posts) for posts in dayposts.values())
    max_count=CONFIG['max_posts_programmes_canal']
    if scheduled_count>=max_count:
        results['erreurs'].append(f'Queue Buffer déjà remplie: {scheduled_count} posts sur fenêtre (plafond prudent {max_count})')
    photos_indisponibles=set()
    for day in next_days(now):
        key=day.isoformat();posts=dayposts[key]
        item=registry.get(key) or {}
        if item.get('etat')=='PROGRAMME' and item.get('version_visuelle')!=VERSION_VISUELLE:
            # Un post ancien peut être remplacé par une anecdote mieux illustrable.
            # Sécurité : seul l'identifiant connu + notre légende exacte autorisent editPost.
            same=[p for p in posts if p.get('id')==item.get('id_buffer') and
                  is_anecdote(p) and p.get('text','').strip()==item.get('texte_public','').strip()]
            if len(same)==1 and parse(same[0]['dueAt'])>now+dt.timedelta(minutes=35):
                original=facts_by_id.get(item.get('fact_id'))
                candidates=[]
                if original:candidates.append(original)
                # Si le sujet original n'a aucun visuel réel admissible, trouver
                # une autre anecdote *prouvée* et illustrable, sans inventer d'image.
                used_ids={r.get('fact_id') for d,r in registry.items()
                          if d!=key and isinstance(r,dict) and r.get('etat') in ('EN_ATTENTE','PROGRAMME','EN_ATTENTE_MAJ')}
                used_recent_topics={topic(facts_by_id[r.get('fact_id')]) for d,r in registry.items()
                    if d!=key and isinstance(r,dict) and r.get('etat') in ('EN_ATTENTE','PROGRAMME','EN_ATTENTE_MAJ')
                    and r.get('fact_id') in facts_by_id and abs((dt.date.fromisoformat(d)-day).days)<CONFIG.get('intervalle_sujet_jours',5)}
                for f in facts:
                    if (f['id'] not in used_ids and topic(f) not in used_recent_topics and
                        (not original or f['id']!=original['id'])):
                        candidates.append(f)
                done=False;errors_local=[]
                for f in candidates:
                    if f['id'] in photos_indisponibles:continue
                    try:
                        upgraded=stage_fact(f,day,repo,now)
                        upgraded.update({'etat':'EN_ATTENTE_MAJ','id_buffer':item['id_buffer'],
                            'due_at':same[0]['dueAt'],'ancien_texte_public':item['texte_public'],
                            'ancien_fact_id':item.get('fact_id'),
                            'version_visuelle':VERSION_VISUELLE})
                        registry[key]=upgraded;results['plans'].append(key)
                        results['jours'].append({'date':key,'resultat':'MISE_A_JOUR_VISUELLE_PREPAREE',
                            'sujet_initial':item.get('fact_id'),'sujet_retenu':f['id']})
                        done=True;break
                    except (PhotosIndisponibles,ValueError) as exc:
                        photos_indisponibles.add(f['id'])
                        errors_local.append(f['id']+': '+str(exc)[:100])
                if not done:
                    results['jours'].append({'date':key,'resultat':'ANCIEN_POST_CONSERVE',
                        'raison':'Aucun sujet illustrable vérifié : '+' ; '.join(errors_local[:3])[:220]})
            else:
                results['jours'].append({'date':key,'resultat':'POST_ANCIEN_NON_MODIFIABLE',
                     'raison':'Post absent, texte différent ou horaire trop proche'})
            continue
        if item.get('etat') in ('PROGRAMME','SUPPLANTE_PAR_TOP','EN_ATTENTE_MAJ'):
            results['jours'].append({'date':key,'resultat':'DEJA_TRAITE'});continue
        ok,reason=eligible(day,now,posts)
        results['jours'].append({'date':key,'resultat':reason,'reservation':reserved_kind(day)})
        if not ok:continue
        if scheduled_count+len(results['plans'])>=max_count:continue
        if len(results['plans'])>=CONFIG['max_posts_par_execution']:continue
        if item.get('etat')=='EN_ATTENTE':
            # Retry only if the files are still present and the slot still free.
            if (ROOT_REPO/item.get('dossier','')).is_dir():
                results['plans'].append(key);continue
        completed,topics=used_info(registry,day)
        exclude=[rec.get('fact_id') for rec in registry.values() if isinstance(rec,dict) and rec.get('etat') in ('EN_ATTENTE','PROGRAMME')]
        # Certains sujets n'ont pas encore deux photos vérifiées. On essaie
        # les candidats suivants, sans bloquer les autres jours.
        accepted=False
        for _attempt in range(min(len(facts),12)):
            selected=select(facts,completed,topics,day,
                exclude_ids=[*exclude,*photos_indisponibles])
            if selected is None:break
            try:
                registry[key]=stage_fact(selected,day,repo,now)
                results['plans'].append(key)
                accepted=True
                break
            except (PhotosIndisponibles,ValueError) as exc:
                photos_indisponibles.add(selected['id'])
                results['erreurs'].append('PHOTO_REFUSEE '+selected['id']+': '+str(exc)[:190])
        if not accepted:
            results['erreurs'].append(f'PAS_DE_PHOTO_VERIFIEE pour {key}: aucune publication inventée')
    persist(registry)
    write(REPORT/'PLAN_BUFFER.json',[registry[d] for d in results['plans']])
    write(REPORT/'PREPARATION.json',results)
    write(REPORT/'ETAT.json',{'statut':'MEDIA_PREPARES','date':now.isoformat(),
        'futurs_carrousels':len(results['plans']),'anecdotes_en_banque':len(facts),
        'erreurs':results['erreurs']})
    return results

def _is_our_exact(post,rec):
    return is_anecdote(post) and (post.get('text') or '').strip()==(rec.get('texte_public') or '').strip()

def reconcile(buffer,registry,now,results):
    for key,rec in registry.items():
        if rec.get('etat') not in ('PROGRAMME','EN_ATTENTE_MAJ'):continue
        day=dt.date.fromisoformat(key)
        if dt.datetime.combine(day,dt.time(23,59),tzinfo=PARIS)<now.astimezone(PARIS):continue
        posts=buffer.day(day)
        tops=[p for p in posts if is_top(p)]
        ours=[p for p in posts if p.get('id')==rec.get('id_buffer') and is_anecdote(p) and
              (p.get('text','').strip() in ((rec.get('texte_public') or '').strip(), (rec.get('ancien_texte_public') or '').strip()))]
        if not tops or not ours:continue
        if parse(ours[0]['dueAt'])<=now+dt.timedelta(minutes=10):
            results['erreurs'].append(f'Top arrive tardivement {key}: anecdote imminente, suppression automatique refusée')
            continue
        buffer.delete_own(rec['id_buffer'])
        rec['etat']='SUPPLANTE_PAR_TOP'
        rec['top_detecte_le']=now.isoformat()
        results['supprimes_pour_top'].append({'jour':key,'id':rec['id_buffer']})

def send(*,now=None,buffer=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    buffer=buffer or Buffer()
    registry=get_registry();results={'date_utc':now.isoformat(),'programmes':[],
                                   'deja_programmes':[],'ignores':[],'supprimes_pour_top':[],'erreurs':[]}
    # Priority: if a Top arrives after a fallback, remove only our own scheduled anecdote.
    try:reconcile(buffer,registry,now,results)
    except Exception as exc:results['erreurs'].append('RECONCILIATION: '+str(exc)[:300])
    for key in sorted(registry):
        rec=registry[key]
        if rec.get('etat') not in ('EN_ATTENTE','EN_ATTENTE_MAJ'):continue
        day=dt.date.fromisoformat(key)
        try:
            posts=buffer.day(day)
            if rec.get('etat')=='EN_ATTENTE_MAJ':
                existing=[p for p in posts if p.get('id')==rec.get('id_buffer') and
                    is_anecdote(p) and p.get('text','').strip()==rec.get('ancien_texte_public','').strip()]
                if len(existing)!=1 or len(posts)!=1:
                    # Aucun remplacement aveugle, jamais de nouvelle publication.
                    results['erreurs'].append(key+': ancienne publication introuvable ou concurrence')
                    continue
                if parse(existing[0]['dueAt'])<=now+dt.timedelta(minutes=30):
                    results['ignores'].append(key+' : publication imminente');continue
                folder=ROOT_REPO/rec['dossier']
                assets=buffer.verify_images(rec['base_url'],rec['images'],folder)
                updated=buffer.edit_own(rec['id_buffer'],rec['texte_public'],existing[0]['dueAt'],assets)
                rec.update({'etat':'PROGRAMME','date_confirmation':now.isoformat(),
                            'due_at':updated.get('dueAt') or existing[0]['dueAt'],
                            'version_visuelle':VERSION_VISUELLE})
                rec.pop('ancien_texte_public',None)
                results['programmes'].append({'date':key,'id_buffer':updated['id'],
                                             'pages':len(rec['images']),'action':'MISE_A_JOUR_SANS_DOUBLON'})
                continue
            if posts:
                exact=[p for p in posts if _is_our_exact(p,rec)]
                if len(exact)==1:
                    rec.update({'etat':'PROGRAMME','id_buffer':exact[0]['id'],'date_confirmation':now.isoformat(),
                                'due_at':exact[0]['dueAt']})
                    results['deja_programmes'].append(key)
                    continue
                if len(exact)>1:raise BufferError('Plusieurs anecdotes identiques dans Buffer')
                rec['etat']='ANNULE_OCCUPE';results['ignores'].append(key);continue
            ok,why=eligible(day,now,posts)
            if not ok:
                if why=='CRENEAU_TROP_PROCHE':rec['etat']='EXPIRE'
                results['ignores'].append(key+' : '+why);continue
            folder=ROOT_REPO/rec['dossier']
            for file in rec['images']:
                if not (folder/file).is_file():raise RuntimeError('Media absent: '+file)
            assets=buffer.verify_images(rec['base_url'],rec['images'],folder)
            post=buffer.create(rec['texte_public'],rec['due_at'],assets)
            rec.update({'etat':'PROGRAMME','id_buffer':post['id'],'date_confirmation':now.isoformat(),
                        'due_at':post.get('dueAt') or rec['due_at'],'version_visuelle':VERSION_VISUELLE})
            results['programmes'].append({'date':key,'id_buffer':post['id'],'pages':len(rec['images'])})
        except Exception as exc:
            results['erreurs'].append(key+': '+type(exc).__name__+' '+str(exc)[:260])
    persist(registry)
    write(REPORT/'RESULTATS_BUFFER.json',results)
    write(REPORT/'ETAT.json',{'statut':'EXECUTION_TERMINEE','buffer_ok':len(results['programmes']),
          'deja_programmes':len(results['deja_programmes']),'supprimes_pour_top':len(results['supprimes_pour_top']),
          'erreurs':results['erreurs']})
    summary='# Anecdotes BD — audit interne\n\n'+f'Programmés: {len(results["programmes"])}\n\n'
    summary+=f'Réconciliés avec des TOP: {len(results["supprimes_pour_top"])}\n\n'
    summary+=f'Erreurs: {len(results["erreurs"])}\n\n'
    if results['erreurs']:summary+='\n'.join('- '+m for m in results['erreurs'])+'\n'
    (REPORT/'RAPPORT.md').write_text(summary,encoding='utf8')
    return results

def main():
    p=argparse.ArgumentParser(description='Collecte, fabrique et programme les anecdotes BD dans Buffer')
    p.add_argument('action',choices=('prepare','send'))
    p.add_argument('--repo',default=os.environ.get('GITHUB_REPOSITORY',''))
    p.add_argument('--sans-collecte',action='store_true')
    args=p.parse_args()
    if os.environ.get('GITHUB_REPOSITORY_PRIVATE','').lower()=='true':
        raise SystemExit('Dépôt GitHub privé: images Buffer non accessibles, arrêt sans publication')
    if args.action=='prepare':
        if not args.repo:raise SystemExit('GITHUB_REPOSITORY requis')
        res=prepare(args.repo,collect=not args.sans_collecte)
        print('Plans préparés :',res['plans'],'Stock:',res['candidats'])
    else:
        res=send()
        print('Buffer :',res['programmes'],'Erreurs:',res['erreurs'])
        if res['erreurs']:raise SystemExit(1)

if __name__=='__main__':main()
