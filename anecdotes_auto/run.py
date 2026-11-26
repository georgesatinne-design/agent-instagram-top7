"""Exécution GitHub en deux phases : prepare -> git push médias -> send -> git push reçus.
La programmation d'une anecdote n'intervient qu'après vérification du vrai agenda Buffer.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,os,re,traceback
from pathlib import Path
from zoneinfo import ZoneInfo
from .catalogue import ROOT_REPO,STATE,CONFIG,bank,read,write,select,topic,ROOT
from .qualite_editoriale import score as score_anecdote
from .calendrier import PARIS,next_days,eligible,reserved_kind,target_date_time
from .visuels import render,caption
from .storytelling import editorial_eligible
from .photos_reelles import PhotosIndisponibles
from .recherche_images import resolve_avance as resolve
from .buffer import Buffer,BufferError,is_top,is_anecdote,utc,parse

PUBLIC=ROOT_REPO/'public_media'/'anecdotes_bd'
REPORT=ROOT_REPO/'sorties'/'anecdotes_bd'
REGISTRY=STATE/'programmes.json'
VERSION_VISUELLE='BD_STORY_PHOTOS_V7_MULTI_SOURCES_2026_11'
# Une V5 déjà mise à jour et validée ne doit pas être rééditée inutilement.
VERSIONS_DEJA_VALIDES={VERSION_VISUELLE, 'BD_STORY_PHOTOS_V6_RECUPERATION_CONTROLEE_2026_11', 'BD_STORY_PHOTOS_V5_NARRATION_SEMANTIQUE_2026_11'}

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

def sujets_par_disponibilite(facts,registry,day,exclude_ids=()):
    """Choisit les faits PROUVES ayant des images disponibles AVANT les autres.

    Priorité à la diversité; si une série de thèmes n'a aucune photo autorisée,
    les autres sujets non publiés restent éligibles, plutôt que de bloquer Buffer.
    """
    reserve=read(STATE/'stock_photos_verifiees.json',{}) or {}
    scenarios=(read(ROOT/'photos_scenes.json',{}) or {}).get('scenarios',{})
    excluded=set(exclude_ids)
    used_topics=[]
    for date_s,record in registry.items():
        if not isinstance(record,dict) or record.get('etat') not in ('PROGRAMME','EN_ATTENTE','EN_ATTENTE_MAJ'):
            continue
        if record.get('sujet') and abs((dt.date.fromisoformat(date_s)-day).days)<CONFIG.get('intervalle_sujet_jours',5):
            used_topics.append(record['sujet'])
    candidates=[f for f in facts if f['id'] not in excluded]
    candidates.sort(key=lambda f:(
        reserve.get(f['id'],{}).get('statut')!='PRET',
        topic(f) in used_topics,
        f['id'] not in scenarios,
        -score_anecdote(f),
        hashlib.sha256((day.isoformat()+f['id']).encode()).hexdigest()))
    return candidates


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

def _day_snapshot(buffer, now):
    """Une seule lecture paginée de la file ; les tests anciens restent compatibles."""
    if not hasattr(buffer, 'list_scheduled'):
        return None, None
    posts=buffer.list_scheduled()
    if not isinstance(posts, list):
        raise RuntimeError('Queue Buffer illisible')
    byday={}
    for p in posts:
        day=parse(p['dueAt']).astimezone(PARIS).date().isoformat()
        byday.setdefault(day, []).append(p)
    return posts, byday

def prepare(repo,*,now=None,buffer=None,collect=True):
    now=now or dt.datetime.now(dt.timezone.utc)
    buffer=buffer or Buffer()
    from .recherche_images import reinitialiser_quota
    reinitialiser_quota(30)
    REPORT.mkdir(parents=True,exist_ok=True)
    results={'date_utc':now.isoformat(),'candidats':len(bank()),'collecte':None,'plans':[],
             'jours':[],'erreurs':[],'remplacements_non_effectues':[]}
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
    try:
        all_scheduled, byday = _day_snapshot(buffer,now)
        if byday is not None:
            dayposts={d.isoformat():list(byday.get(d.isoformat(),[])) for d in next_days(now)}
            scheduled_count=len(all_scheduled)  # y compris au-delà de l'horizon éditorial
        else:
            for day in next_days(now):
                dayposts[day.isoformat()]=buffer.day(day)
            scheduled_count=sum(len(posts) for posts in dayposts.values())
    except Exception as exc:
        results['erreurs'].append('BUFFER_QUEUE: '+str(exc)[:230])
        write(REPORT/'ETAT.json',{'statut':'ERREUR_CONTROLE_BUFFER','erreurs':results['erreurs']})
        write(REPORT/'PLAN_BUFFER.json',[])
        write(REPORT/'REPRISES_A_FAIRE.json',[])
        raise
    max_count=CONFIG['max_posts_programmes_canal']
    results['queue_avant']=scheduled_count
    results['capacite_buffer']=max_count
    results['places_initiales']=max(0,max_count-scheduled_count)
    if scheduled_count>=max_count:
        results['jours'].append({'date':'FILE_BUFFER','resultat':'CAPACITE_ATTEINTE',
                                 'en_queue':scheduled_count,'plafond':max_count})
    photos_indisponibles=set()
    for day in next_days(now):
        key=day.isoformat();posts=dayposts[key]
        item=registry.get(key) or {}
        if item.get('etat')=='PROGRAMME' and item.get('version_visuelle') not in VERSIONS_DEJA_VALIDES:
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
                # Première passe : meilleure diversité éditoriale. Si aucune photo
                # n'est disponible, on élargit légèrement la distance entre sujets
                # (4 jours au lieu de 5) pour éviter de garder une ancienne DA.
                for f in facts:
                    if (f['id'] not in used_ids and topic(f) not in used_recent_topics and
                        (not original or f['id']!=original['id'])):
                        candidates.append(f)
                candidates_strict_ids={f['id'] for f in candidates}
                for f in facts:
                    if f['id'] in used_ids or f['id'] in candidates_strict_ids:
                        continue
                    if original and f['id']==original['id']:
                        continue
                    conflicts=[abs((dt.date.fromisoformat(d)-day).days) for d,r in registry.items()
                        if d!=key and isinstance(r,dict) and
                        r.get('etat') in ('EN_ATTENTE','PROGRAMME','EN_ATTENTE_MAJ') and
                        r.get('fact_id') in facts_by_id and
                        topic(facts_by_id[r['fact_id']])==topic(f)]
                    if not conflicts or min(conflicts)>=4:
                        candidates.append(f)
                # Ultime passe: un sujet différent mais du même thème vaut mieux
                # qu'un ancien carrousel pauvre et figé. On n'utilise JAMAIS deux
                # fois le même fait, ni une image décorative sans rapport.
                reserved_ids={f['id'] for f in candidates}
                fallbacks=[f for f in facts if f['id'] not in used_ids and
                           f['id'] not in reserved_ids and
                           (not original or f['id']!=original['id'])]
                fallbacks.sort(key=lambda f:(topic(f)==topic(original) if original else False,f['id']))
                candidates.extend(fallbacks)
                reserve=read(STATE/'stock_photos_verifiees.json',{}) or {}
                if original:
                    head=candidates[:1];tail=candidates[1:]
                else:
                    head=[];tail=candidates
                tail.sort(key=lambda f:(reserve.get(f['id'],{}).get('statut')!='PRET',
                                         topic(f) in used_recent_topics,f['id']))
                candidates=head+tail
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
                        errors_local.append(f['id']+': '+str(exc)[:210])
                if not done:
                    reason='Aucun sujet illustrable vérifié : '+' ; '.join(errors_local[:5])[:520]
                    failure={'date':key,'id_buffer':item.get('id_buffer'),
                        'version_actuelle':item.get('version_visuelle'),
                        'fact_id':item.get('fact_id'),'raison':reason,
                        'nouvelle_tentative':'au prochain lancement automatique',
                        'priorite':'HAUTE'}
                    results['remplacements_non_effectues'].append(failure)
                    results['jours'].append({'date':key,'resultat':'REMPLACEMENT_NON_EFFECTUE',
                        'raison':reason})
            else:
                failure={'date':key,'id_buffer':item.get('id_buffer'),
                  'version_actuelle':item.get('version_visuelle'),
                  'fact_id':item.get('fact_id'),
                  'raison':'Post absent, texte différent ou horaire trop proche',
                  'nouvelle_tentative':'controle a la prochaine execution',
                  'priorite':'HAUTE'}
                results['remplacements_non_effectues'].append(failure)
                results['jours'].append({'date':key,'resultat':'POST_ANCIEN_NON_MODIFIABLE',
                     'raison':failure['raison']})
            continue
        if item.get('etat') in ('PROGRAMME','SUPPLANTE_PAR_TOP','EN_ATTENTE_MAJ'):
            results['jours'].append({'date':key,'resultat':'DEJA_TRAITE'});continue
        ok,reason=eligible(day,now,posts)
        results['jours'].append({'date':key,'resultat':reason,'reservation':reserved_kind(day)})
        if not ok:continue
        creations_pretes=sum(registry[d].get('etat')=='EN_ATTENTE' for d in results['plans'])
        if scheduled_count+creations_pretes>=max_count and reserved_kind(day) is None:
            continue
        # Si le TOP ne sort pas et que le délai de repli est atteint, on peut
        # préparer son anecdote malgré la Queue pleine : la place sera libérée
        # UNIQUEMENT juste avant l'envoi, après vérification des cinq médias.
        if len(results['plans'])>=CONFIG['max_posts_par_execution']:continue
        if item.get('etat')=='EN_ATTENTE':
            # Retry only if the files are still present and the slot still free.
            if (ROOT_REPO/item.get('dossier','')).is_dir():
                results['plans'].append(key);continue
        exclude=[rec.get('fact_id') for rec in registry.values() if isinstance(rec,dict) and rec.get('etat') in ('EN_ATTENTE','PROGRAMME','EN_ATTENTE_MAJ')]
        # Regarder d'abord les anecdotes ayant déjà une preuve et trois photos
        # distinctes en stock. Aucune répétition du même fait, même sous un autre nom.
        accepted=False
        candidates=sujets_par_disponibilite(facts,registry,day,exclude_ids=[*exclude,*photos_indisponibles])
        for selected in candidates[:min(len(candidates),18)]:
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
    results['places_potentiellement_remplies']=sum(registry[d].get('etat')=='EN_ATTENTE' for d in results['plans'])
    results['places_restantes_prevues']=max(0,max_count-scheduled_count-results['places_potentiellement_remplies'])
    write(REPORT/'PREPARATION.json',results)
    write(REPORT/'REPRISES_A_FAIRE.json',results['remplacements_non_effectues'])
    write(REPORT/'ETAT.json',{'statut':'MEDIA_PREPARES','date':now.isoformat(),
        'futurs_carrousels':len(results['plans']),'anecdotes_en_banque':len(facts),
        'remplacements_non_effectues':len(results['remplacements_non_effectues']),
        'erreurs':results['erreurs']})
    return results

def _is_our_exact(post,rec):
    return is_anecdote(post) and (post.get('text') or '').strip()==(rec.get('texte_public') or '').strip()

def reconcile(buffer,registry,now,results,dayposts=None):
    for key,rec in registry.items():
        if rec.get('etat') not in ('PROGRAMME','EN_ATTENTE_MAJ'):continue
        day=dt.date.fromisoformat(key)
        if dt.datetime.combine(day,dt.time(23,59),tzinfo=PARIS)<now.astimezone(PARIS):continue
        posts=(dayposts.get(key,[]) if dayposts is not None else buffer.day(day))
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
                                   'deja_programmes':[],'ignores':[],'supprimes_pour_top':[],'erreurs':[],
                                   'remplacements_non_effectues':[]}
    # Une lecture complète au début pour limiter la consommation du quota API.
    try:
        snapshot,dayposts=_day_snapshot(buffer,now)
    except Exception as exc:
        results['erreurs'].append('QUEUE_BUFFER: '+str(exc)[:260])
        snapshot,dayposts=None,None
    # Priority: if a Top arrives after a fallback, remove only our own scheduled anecdote.
    try:reconcile(buffer,registry,now,results,dayposts)
    except Exception as exc:results['erreurs'].append('RECONCILIATION: '+str(exc)[:300])
    for key in sorted(registry):
        rec=registry[key]
        if rec.get('etat') not in ('EN_ATTENTE','EN_ATTENTE_MAJ'):continue
        day=dt.date.fromisoformat(key)
        try:
            posts=(dayposts.get(key,[]) if dayposts is not None else buffer.day(day))
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
            # Les images sont vérifiées AVANT toute éventuelle libération de place.
            if hasattr(buffer,'list_scheduled'):
                live=buffer.list_scheduled()
                if any(parse(p['dueAt']).astimezone(PARIS).date()==day for p in live):
                    rec['etat']='ANNULE_OCCUPE'
                    results['ignores'].append(key+' : UN_POST_A_PRIS_LE_CRENEAU')
                    continue
                if len(live)>=CONFIG['max_posts_programmes_canal']:
                    if reserved_kind(day):
                        from illyadera_queue import free_capacity_for_priority
                        free_capacity_for_priority(rec['due_at'],buffer=buffer,registry=registry,
                            max_posts=CONFIG['max_posts_programmes_canal'],priority='REPLI_TOP')
                    else:
                        results['ignores'].append(key+' : QUEUE_PLEINE (attente prochaine place)')
                        continue
            post=buffer.create(rec['texte_public'],rec['due_at'],assets)
            if dayposts is not None:
                dayposts.setdefault(key,[]).append({'id':post['id'],'status':'scheduled',
                    'channelId':getattr(buffer,'channel_id',''), 'dueAt':post.get('dueAt') or rec['due_at'],
                    'text':rec['texte_public']})
            rec.update({'etat':'PROGRAMME','id_buffer':post['id'],'date_confirmation':now.isoformat(),
                        'due_at':post.get('dueAt') or rec['due_at'],'version_visuelle':VERSION_VISUELLE})
            results['programmes'].append({'date':key,'id_buffer':post['id'],'pages':len(rec['images'])})
        except Exception as exc:
            results['erreurs'].append(key+': '+type(exc).__name__+' '+str(exc)[:260])
    # Vérification post-envoi : ne pas annoncer une exécution saine si un post
    # en ancienne DA est resté dans Buffer sans remplacement effectif.
    backlog=read(REPORT/'REPRISES_A_FAIRE.json',[]) or []
    unresolved=[]
    for rec in backlog:
        key=rec.get('date')
        actuel=registry.get(key) or {}
        if (actuel.get('version_visuelle') not in VERSIONS_DEJA_VALIDES and
                actuel.get('etat')=='PROGRAMME'):
            unresolved.append(rec)
    results['remplacements_non_effectues']=unresolved
    try:
        if hasattr(buffer,'list_scheduled'):
            remaining_posts=buffer.list_scheduled()
            results['queue_apres']=len(remaining_posts)
            results['capacite_buffer']=CONFIG['max_posts_programmes_canal']
            results['places_libres']=max(0,results['capacite_buffer']-len(remaining_posts))
        else:
            results['queue_apres']=None
    except Exception as exc:
        results['erreurs'].append('QUEUE_APRES: '+str(exc)[:240])
    persist(registry)
    write(REPORT/'REPRISES_A_FAIRE.json',unresolved)
    write(REPORT/'RESULTATS_BUFFER.json',results)
    write(REPORT/'ETAT.json',{'statut':('REPRISES_A_FAIRE' if unresolved else 'EXECUTION_TERMINEE'),
          'buffer_ok':len(results['programmes']),
          'deja_programmes':len(results['deja_programmes']),
          'supprimes_pour_top':len(results['supprimes_pour_top']),
          'remplacements_non_effectues':len(unresolved),
          'erreurs':results['erreurs'],'queue_apres':results.get('queue_apres'),
          'capacite_buffer':results.get('capacite_buffer'),
          'places_libres':results.get('places_libres')})
    summary='# Anecdotes BD — audit interne\n\n'+f'Programmés: {len(results["programmes"])}\n\n'
    if results.get('queue_apres') is not None:
        summary+=f'File Buffer: {results["queue_apres"]}/{results["capacite_buffer"]} ; places disponibles: {results["places_libres"]}\n\n'
        if results['places_libres']>0:
            summary+='Les places restantes ne sont pas remplies sans contenu sourcé, images réelles et créneau admissible.\n\n'
    summary+=f'Réconciliés avec des TOP: {len(results["supprimes_pour_top"])}\n\n'
    summary+=f'Remplacements encore nécessaires: {len(unresolved)}\n\n'
    for warning in unresolved:
        summary+=f"- ⚠ {warning['date']} — {warning['fact_id']} : {warning['raison']}\n"
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
