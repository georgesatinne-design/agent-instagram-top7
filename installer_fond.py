"""Enregistre EXACTEMENT un fond fourni et active la charte de la catégorie.
Aucun algorithme ne recompose ni ne remplace le fond.
Exemple : python installer_fond.py --categorie MANGA --image fond_manga.jpeg --bandeau '#123456' --titre '#FEDCBA' --rond '#FEDCBA' --encre '#123456'
"""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parent
STYLES=ROOT/'templates/charte_top7.json'

def installer(category,image,bar,title,circle,ink):
    if category not in ('MANGA','COMICS'):
        raise ValueError('BD déjà configurée à partir du fond original; ne pas remplacer')
    source=Path(image)
    if not source.is_file():raise FileNotFoundError(source)
    with Image.open(source) as img:
        if img.width<300 or img.height<300:raise ValueError('Fond source trop petit')
        kind=img.format
    ext='.png' if kind=='PNG' else '.jpeg' if kind=='JPEG' else None
    if not ext:raise ValueError('Fond requis au format PNG ou JPEG')
    colors={'violet':bar,'jaune':title,'rond':circle,'blanc':'#FFFFFF','encre':ink}
    for label,v in colors.items():
        if len(v)!=7 or not v.startswith('#') or any(c not in '0123456789ABCDEFabcdef' for c in v[1:]):
            raise ValueError('Couleur HEX invalide : '+label)
    config=json.loads(STYLES.read_text(encoding='utf8'))
    destination=ROOT/'assets'/('fond_'+category.lower()+'_original'+ext)
    shutil.copyfile(source,destination)
    config['categorie_styles'][category]={**colors,'fond_original':'assets/'+destination.name,'statut':'APPROUVABLE'}
    STYLES.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Charte '+category+' activée. Fond original copié sans modification : '+str(destination))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--categorie',choices=['MANGA','COMICS'],required=True)
    p.add_argument('--image',required=True);p.add_argument('--bandeau',required=True);p.add_argument('--titre',required=True);p.add_argument('--rond',required=True);p.add_argument('--encre',required=True)
    args=p.parse_args()
    installer(args.categorie,args.image,args.bandeau,args.titre,args.rond,args.encre)
