"""Agent hebdomadaire: collecte gratuite -> validation -> carrousels -> livrables.
Ne publie jamais. Échec explicite si une source n'est pas exploitable.
"""
from __future__ import annotations
import argparse, datetime as dt, json, shutil, traceback, zipfile
from pathlib import Path
from sources.collecte import collect_bd, fetch, rangs_bede, top_par_genre_bede, BEDE
from sources.couvertures import lookup_bede, download_cover
from studio import verifier, render
from visual_top7 import render_top7

ROOT=Path(__file__).resolve().parent

def run(output:Path, input_file:Path|None=None, *, allow_demo=False):
    output.mkdir(parents=True,exist_ok=True)
    log=[];data=[];index=None
    if input_file:
        supplied=json.loads(input_file.read_text(encoding='utf-8'))
        data=supplied if isinstance(supplied,list) else [supplied]
        log.append('Mode fichier fourni : la source du fichier n’est pas vérifiée par le collecteur.')
    else:
        try:
            data.append(collect_bd())
            log.append('BDZoom : collecte du Top BD réussie.')
        except Exception as exc:
            log.append(f'BDZoom : échec explicite ({type(exc).__name__}: {exc}).')
        try:
            index=rangs_bede(fetch(BEDE))
            log.append(f'Bédé.fr : {len(index["classement_general"])} entrées générales repérées.')
            groups,errors=top_par_genre_bede(index)
            log.append(f'Bédé.fr : {len(errors)} fiches non vérifiées.')
            for cat in ('MANGA','COMICS'):
                books=groups[cat]
                if books and index.get('date_palmares'):
                    data.append({'categorie':cat,'perimetre':f'Sous-ensemble {cat} identifié dans le palmarès général Bédé.fr, NON certifié Top 10 national exhaustif',
                    'date_palmares':index['date_palmares'],'source':'Bédé.fr / Edistat (classement général filtré)',
                    'url_source':BEDE,'titres':books})
                else:log.append(f'{cat}: aucune série de rangs vérifiables et datés; pas de carrousel inventé.')
        except Exception as exc:
            log.append(f'Bédé.fr : échec explicite ({type(exc).__name__}: {exc}).')
    seen=set();result=[]
    for entry in data:
        cat=entry.get('categorie','INCONNUE')
        if cat in seen:
            log.append(f'{cat}: catégorie dupliquée ignorée.');continue
        seen.add(cat)
        try:
            count=verifier(entry)
            folder=output/cat
            coverdir=folder/'couvertures'
            covers={}
            if index and cat=='BD':covers=lookup_bede(entry['titres'],index)
            elif index:
                for book in entry['titres']:
                    if book.get('couverture_url') and book.get('couverture_titre'):
                        covers[book['rang']]={'url':book['couverture_url'],'reference':book['couverture_titre']}
            for book in entry['titres']:
                ok,message=download_cover(book,covers,coverdir)
                if not ok:log.append(f'{cat} #{book["rang"]}: couverture absente : {message}')
            # Un seul moteur graphique pour BD / MANGA / COMICS, trois fonds indépendants.
            # Sans les fichiers et couleurs transmis pour le genre, la génération est bloquée.
            info=render_top7(entry,folder,cover_directory=coverdir,use_watermark=bool(input_file))
            covers_found=7 - len(info['missing_covers'])
            checksum=info['visual_fingerprint']
            result.append({'categorie':cat,'titres':count,'diapositives':info['pages'],'couvertures':covers_found,
                           'source':entry['url_source'],'perimetre':entry['perimetre'],'charte_sha256':checksum})
        except Exception as exc:
            log.append(f'{cat}: génération refusée : {type(exc).__name__}: {exc}')
    summary={'date_execution':dt.datetime.now(dt.timezone.utc).isoformat(),'mode':'fichier' if input_file else 'collecte_live',
             'dossiers':result,'journal':log,'publication':'INTERDITE SANS VALIDATION'}
    (output/'rapport.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'A_LIRE.md').write_text('# Rapport de l’agent\n\n'+ '\n'.join(f'- {line}' for line in log)+ '\n\n'+ '\n'.join(f'- {x["categorie"]}: {x["titres"]} rangs; {x["diapositives"]} images; {x["couvertures"]} couvertures.' for x in result)+'\n\nAucune publication Instagram automatique.\n',encoding='utf-8')
    with zipfile.ZipFile(output/'DOSSIER_A_VALIDER.zip','w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.name!='DOSSIER_A_VALIDER.zip':z.write(path,path.relative_to(output))
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Agent Instagram BD/Manga/Comics gratuit et sans publication')
    parser.add_argument('--sortie',default='sorties/hebdomadaire')
    parser.add_argument('--fichier',type=Path,help='Fichier JSON vérifié à transformer sans accès réseau')
    args=parser.parse_args()
    summary=run(ROOT/args.sortie,args.fichier)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
