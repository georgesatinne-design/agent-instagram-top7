"""Préparation des huit pages manga, indépendante de la production BD.

Sans preuve complète de catégorie/ventes et sans couvertures sûres, on produit
une MAQUETTE FILIGRANÉE. Aucun dépôt Buffer ni publication ici.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from sources.couvertures import download_cover, search_google_books
from visual_top7 import render_top7


def preparer(classement_path: Path, sortie: Path) -> dict:
    data=json.loads(Path(classement_path).read_text(encoding='utf-8'))
    if data.get('categorie') != 'MANGA' or len(data.get('titres',[]))!=7:
        raise ValueError('Top 7 manga complet obligatoire')
    folder=Path(sortie)
    cover_dir=folder/'couvertures'
    cover_dir.mkdir(parents=True,exist_ok=True)
    checks=[]
    for row in data['titres']:
        sources={}
        if row.get('couverture_candidate_url') and row.get('couverture_reference'):
            sources[row['rang']]={'url':row['couverture_candidate_url'],
                                  'reference':row['couverture_reference']}
        ok,message=download_cover(row,sources,cover_dir)
        if not ok:
            alternative=search_google_books(row)
            if alternative:
                ok,message=download_cover(row,{row['rang']:alternative},cover_dir)
        checks.append({'rang':row['rang'],'titre':row['titre'],'couverture_validee':ok,'detail':message})
    # La classification des mangas issus du classement GENERAL reste à valider
    # pour ne jamais donner l'apparence d'une certitude qu'on n'a pas démontrée.
    result=render_top7(data,folder,cover_dir,use_watermark=True)
    (folder/'COUVERTURES_CONTROLES.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return {'pages':result['pages'],'couvertures_valides':sum(x['couverture_validee'] for x in checks),
            'publication_autorisee':False,'motif':'Classement reconstitué non encore certifié exhaustif'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--classement',type=Path,required=True)
    p.add_argument('--sortie',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(preparer(args.classement,args.sortie),ensure_ascii=False))

if __name__=='__main__':main()
