"""Deux phases pour GitHub Actions: média publiquement disponible AVANT envoi Buffer.
Signale chaque erreur dans l'artifact; ne touche jamais aux reçus BD ou MANGA.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sys,traceback
from pathlib import Path
from comics_pipeline_periodique import save,load,VERSION
from historique_editions import newer_receipt
from calendrier_editorial import parse_due
import datetime as dt

OUT=Path('sorties/comics_periodique')
PLAN=OUT/'PLAN_BUFFER.json'

def available():
    for folder in sorted(OUT.glob('COMICS_*')):
        state=load(folder/'ETAT.json') or {}
        if state.get('pret_buffer') and (folder/'COMICS'/'post_manifest.json').is_file():yield folder,state

def prepare(repo):
    ready=list(available())
    if ready and os.environ.get('GITHUB_REPOSITORY_PRIVATE','').lower()=='true':
        raise RuntimeError('Le dépôt est privé: Buffer ne peut pas lire les images depuis raw.githubusercontent.com')
    plan=[]
    for folder,state in ready:
        edition=state['edition'];manifest=load(folder/'COMICS'/'post_manifest.json')
        if newer_receipt(Path('comics_buffer_receipts'),edition):continue
        receipt=Path('comics_buffer_receipts')/(edition+'.json')
        if receipt.is_file():
            previous=json.loads(receipt.read_text(encoding='utf8'))
            if previous.get('statut')!='POST_PROGRAMME' or previous.get('edition')!=edition:
                raise RuntimeError('Reçu Comics incohérent : '+edition)
            if parse_due(previous['date_programmee_utc'])<=dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=10):continue
            caption=(folder/'COMICS'/'legende_instagram.txt').read_text(encoding='utf8').strip()
            if previous.get('version_contenu')==VERSION and previous.get('texte_public')==caption:continue
        required=manifest['pages'];n=5 if state['cadence']=='HEBDO' else 7
        if len(required)!=n+1 or len(set(required))!=n+1:raise RuntimeError('Liste pages non valide')
        h=hashlib.sha256()
        for filename in required:
            src=folder/'COMICS'/filename
            if not src.is_file():raise RuntimeError('Image absente: '+str(src))
            h.update(src.read_bytes())
        h.update((folder/'COMICS'/'legende_instagram.txt').read_bytes())
        revision=h.hexdigest()[:16]
        dest=Path('public_media')/edition/('COMICS_'+revision)
        dest.mkdir(parents=True,exist_ok=True)
        for filename in required:shutil.copyfile(folder/'COMICS'/filename,dest/filename)
        plan.append({'edition':edition,'cadence':state['cadence'],'folder':str(folder/'COMICS'),
            'base_url':f'https://raw.githubusercontent.com/{repo}/main/{dest.as_posix()}/'})
    save(PLAN,plan)
    print('Editions prêtes :',len(plan))

def send(*,arbitrate=False,buffer=None,now=None):
    """Un arbitrage par édition, immédiatement suivi de sa programmation.

    Le verrou du workflow est partagé avec les autres agents. Si une mutation
    échoue, arrêter les nouveaux arbitrages au lieu de retirer d'autres posts.
    """
    from comics_buffer_periodique import transmettre,construire,next_slot
    from calendrier_editorial import validate_slot
    from media_preflight import verify_public_assets
    from illyadera_queue import free_capacity_for_priority
    from anecdotes_auto.buffer import Buffer
    plan=load(PLAN) or []
    errors=[];success=[];ordered=[];actions=[]
    old_plan=os.environ.get('ILLYADERA_SLOT_PLAN')
    slot_plan=OUT/'ARBITRAGE_COMICS.json'
    for item in plan:
        try:
            data=load(Path(item['folder']).parent/'classement_comics.json')
            receipt_file=Path('comics_buffer_receipts')/(item['edition']+'.json')
            if newer_receipt(receipt_file.parent,item['edition']):continue
            if receipt_file.exists():
                prior=json.loads(receipt_file.read_text(encoding='utf8'))
                if prior.get('statut')!='POST_PROGRAMME' or prior.get('edition')!=item['edition']:
                    raise RuntimeError('Reçu non interprétable')
                due=prior['date_programmee_utc']
            else:
                due=next_slot(data,now=now)
            ordered.append((parse_due(due),item))
        except Exception as exc:
            errors.append({'edition':item['edition'],'erreur':str(exc)[:250]})
    for due,item in sorted(ordered,key=lambda x:(x[0],x[1]['edition'])):
        dest=Path(item['folder']);edition=item['edition'];parent=dest.parent
        try:
            receipt_file=Path('comics_buffer_receipts')/(edition+'.json')
            if arbitrate:
                os.environ.pop('ILLYADERA_SLOT_PLAN',None)
                if not receipt_file.exists():
                    current=now or dt.datetime.now(dt.timezone.utc)
                    payload=construire(dest,item['base_url'],os.environ.get('BUFFER_CHANNEL_ID',''),now=current)
                    kind='COMICS_HEBDO' if item['cadence']=='HEBDO' else 'COMICS_MENSUEL'
                    slot=validate_slot(kind,due,now=current)
                    if payload['dueAt']!=slot:raise RuntimeError('Créneau modifié depuis le plan')
                    verify_public_assets(payload['assets'])
                    if buffer is None:buffer=Buffer()
                    action=free_capacity_for_priority(slot,buffer=buffer,now=current,priority=kind)
                    actions.append({'edition':edition,'slot':slot,**action})
                    save(slot_plan,{'slots':[slot],'actions':actions})
                else:
                    save(slot_plan,{'slots':[],'actions':actions})
                os.environ['ILLYADERA_SLOT_PLAN']=str(slot_plan)
            receipt=transmettre(dest,item['base_url'],send=True,
                api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''),
                previous_receipt=receipt_file,now=now)
            if receipt.get('statut')!='POST_PROGRAMME':raise RuntimeError('Buffer sans confirmation POST_PROGRAMME')
            receipt_file.parent.mkdir(exist_ok=True)
            shutil.copyfile(dest/'RECU_BUFFER.json',receipt_file)
            history=Path('comics_history')/item['cadence'].lower()/'dernier_classement.json'
            history.parent.mkdir(parents=True,exist_ok=True)
            current=load(parent/'classement_comics.json')
            previous=load(history) or {}
            if not previous or current['edition']>=previous.get('edition',''):
                save(history,current)
            success.append(edition)
        except Exception as exc:
            message=f'{type(exc).__name__}: {str(exc)[:250]}'
            errors.append({'edition':edition,'erreur':message})
            save(parent/'ERREUR_BUFFER.json',{'edition':edition,'statut':'ECHEC','raison':message})
            # Après une panne, ne pas libérer un deuxième créneau.
            if arbitrate:break
        finally:
            if old_plan is None:os.environ.pop('ILLYADERA_SLOT_PLAN',None)
            else:os.environ['ILLYADERA_SLOT_PLAN']=old_plan
    save(OUT/'RESULTATS_BUFFER.json',{'programmes':success,'erreurs':errors,'arbitrages':actions})
    print('Programmés:',success,'Erreurs:',errors)
    if errors:raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=('prepare','send'))
    ap.add_argument('--repo',default=os.getenv('GITHUB_REPOSITORY',''))
    ap.add_argument('--arbitrate',action='store_true',help='Arbitrage en production pour chaque édition')
    args=ap.parse_args()
    if args.action=='prepare':
        if not args.repo or '/' not in args.repo:raise SystemExit('GITHUB_REPOSITORY manquant')
        prepare(args.repo)
    else:send(arbitrate=args.arbitrate)

if __name__=='__main__':main()
