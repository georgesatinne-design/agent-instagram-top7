"""Prépare chaque jour des sujets déjà illustrables AVANT que Buffer en ait besoin.

Stock de preuves hors publication, dans anecdotes_state. Le classement, les
carrousels déjà présents dans Buffer et les secrets des TOP ne sont pas modifiés.
"""
from __future__ import annotations
import argparse
import datetime as dt
from pathlib import Path

from .catalogue import STATE, bank, read, write
from .storytelling import editorial_eligible
from .recherche_images import resolve_avance, PhotosIndisponibles

STOCK = STATE/'stock_photos_verifiees.json'

def limiter_cache_images(directory=None,*,max_photos=180,max_total_mb=130):
    """Empêche une croissance illimitée du cache media dans le dépôt.

    Les PNG publics déjà déposés pour Buffer sont complètement séparés et ne
    sont jamais effacés ici. Les fichiers perdus peuvent être re-téléchargés.
    """
    from .recherche_images import CACHE
    root=Path(directory or CACHE)
    imgs=sorted(root.glob('*.jpg'),key=lambda p:p.stat().st_mtime if p.exists() else 0)
    total=sum(p.stat().st_size for p in imgs)
    limit=max_total_mb*1024*1024
    count=0
    while imgs and (len(imgs)>max_photos or total>limit):
        older=imgs.pop(0)
        size=older.stat().st_size
        proof=older.with_suffix('.json')
        older.unlink(missing_ok=True);proof.unlink(missing_ok=True)
        total-=size;count+=1
    # Le cache de résultats de recherche n'est pas une preuve ni un média public.
    # Conserver les 250 plus récents, pendant 30 jours maximum.
    import time
    cache=sorted((root/'recherches').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for i,p in enumerate(cache):
        if i>=250 or time.time()-p.stat().st_mtime>30*86400:
            p.unlink(missing_ok=True)
    return count


def preparer_stock(*,limit=5,now=None,resolver=resolve_avance):
    now=now or dt.datetime.now(dt.timezone.utc)
    from .recherche_images import reinitialiser_quota
    from .catalogue import CONFIG
    reinitialiser_quota(28)
    book=read(STOCK,{}) or {}
    registry=read(STATE/'programmes.json',{}) or {}
    used={r.get('fact_id') for r in registry.values() if isinstance(r,dict) and r.get('etat') in
        ('PROGRAMME','EN_ATTENTE','EN_ATTENTE_MAJ','EXPIRE_INCERTAIN')}
    eligible=[f for f in bank() if editorial_eligible(f) and f['id'] not in used]
    valid_ids={f['id'] for f in eligible}
    book={k:v for k,v in book.items() if k in valid_ids}
    pending=[];ready_count=0
    for f in eligible:
        rec=book.get(f['id'],{})
        try:
            age=now-dt.datetime.fromisoformat(rec['date_controle'])
        except (ValueError,KeyError,TypeError):age=dt.timedelta(days=1000)
        # A successful set lives in the shared image-cache; refresh on new week.
        if rec.get('statut')=='PRET' and age<dt.timedelta(days=CONFIG.get('stock_validite_jours',21)):
            ready_count+=1;continue
        if rec.get('statut')=='INDISPONIBLE' and age<dt.timedelta(hours=20):continue
        pending.append(f)
    # Priority to facts already scenarized / and those with broad public-domain corpus.
    from .catalogue import ROOT
    scenarios=(read(ROOT/'photos_scenes.json',{}) or {}).get('scenarios',{})
    from .qualite_editoriale import score
    from .catalogue import topic
    pending.sort(key=lambda f:(-score(f), f['id'] not in scenarios, f['id']))
    # Un premier tour par univers avant de réessayer un deuxième sujet du même univers.
    first=[]; rest=[]; seen_topics=set()
    for f in pending:
        key=topic(f)
        (rest if key in seen_topics else first).append(f)
        seen_topics.add(key)
    pending=first+rest
    attempts=[]
    target=CONFIG.get('stock_cible',10)
    for f in pending[:max(0,int(limit))]:
        if ready_count>=target:break
        try:
            files,proofs=resolver(f)
            if len(files)<3 or len({p.get('page') for p in proofs})<3:
                raise PhotosIndisponibles('Moins de 3 scènes photographiques')
            # Images already cached: the pipeline will verify them again at use.
            book[f['id']]={'statut':'PRET','date_controle':now.isoformat(),
                           'photos':len(proofs),'pages_illustrees':[p.get('page') for p in proofs]}
            ready_count+=1
            attempts.append({'fait':f['id'],'statut':'PRET','photos':len(proofs)})
        except (PhotosIndisponibles,ValueError,KeyError,OSError) as exc:
            waiting='Budget de recherches atteint' in str(exc)
            book[f['id']]={'statut':'A_REPORTER' if waiting else 'INDISPONIBLE',
                           'date_controle':now.isoformat(),'raison':str(exc)[:400]}
            attempts.append({'fait':f['id'],'statut':'INDISPONIBLE','raison':str(exc)[:180]})
        # Persistence after each attempt, even if a subsequent API times out.
        write(STOCK,book)
    write(STOCK,book)
    purges=limiter_cache_images()
    report={'date':now.isoformat(),'fichiers_cache_purges':purges,'nombre_en_banque':len(eligible),
      'prets_en_stock':ready_count,'stock_cible':target,
      'tentatives':attempts}
    write(STATE/'stock_photos_rapport.json',report)
    return report

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('--limit',type=int,default=5)
    args=cli.parse_args()
    report=preparer_stock(limit=args.limit)
    print('Photothèque :',report['prets_en_stock'],'faits prêts ; tentatives:',len(report['tentatives']))
    for t in report['tentatives']:print(t['fait'],t['statut'])

if __name__=='__main__':main()
