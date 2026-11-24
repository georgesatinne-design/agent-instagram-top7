"""Deux phases pour GitHub Actions: média publiquement disponible AVANT envoi Buffer.
Signale chaque erreur dans l'artifact; ne touche jamais aux reçus BD ou MANGA.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,sys,traceback
from pathlib import Path
from comics_pipeline_periodique import save,load

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

def send():
    from comics_buffer_periodique import transmettre
    import requests
    plan=load(PLAN) or []
    errors=[];success=[]
    for item in plan:
        dest=Path(item['folder']);edition=item['edition'];parent=dest.parent
        try:
            receipt_file=Path('comics_buffer_receipts')/(edition+'.json')
            receipt=transmettre(dest,item['base_url'],send=True,
                api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''),
                previous_receipt=receipt_file)
            receipt_file.parent.mkdir(exist_ok=True)
            shutil.copyfile(dest/'RECU_BUFFER.json',receipt_file)
            if receipt.get('statut')!='POST_PROGRAMME':raise RuntimeError('Buffer sans confirmation POST_PROGRAMME')
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
    save(OUT/'RESULTATS_BUFFER.json',{'programmes':success,'erreurs':errors})
    print('Programmés:',success,'Erreurs:',errors)
    if errors:raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',choices=('prepare','send'))
    ap.add_argument('--repo',default=os.getenv('GITHUB_REPOSITORY',''))
    args=ap.parse_args()
    if args.action=='prepare':
        if not args.repo or '/' not in args.repo:raise SystemExit('GITHUB_REPOSITORY manquant')
        prepare(args.repo)
    else:send()

if __name__=='__main__':main()
