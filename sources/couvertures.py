"""Téléchargements gratuits de couvertures EXACTEMENT appariées; manque => emplacement vide."""
from __future__ import annotations
import difflib
import hashlib
import io
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image
from .collecte import norm

ALLOW={'cdn.bede.fr','media.hachette.fr','static.fnac-static.com'}

def core_title(s):
    s=norm(s)
    s=re.sub(r'^\s*(bd|manga|comics)\s+', '',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

def volume(s):
    s=norm(s)
    m=re.search(r'\b(?:tome|t)\s*0*(\d{1,3})\b',s)
    return int(m.group(1)) if m else None

def meme_livre(titre,alt):
    a,b=core_title(titre),core_title(alt)
    v1,v2=volume(titre),volume(alt)
    if v1 is not None and v2 is not None and v1!=v2:return False
    if not a or not b:return False
    similarity=difflib.SequenceMatcher(None,a,b).ratio()
    # Si un titre a un suffixe ajouté chez l'éditeur, exiger aussi les mêmes premiers mots.
    common=len(set(a.split()) & set(b.split()))/max(1,len(set(a.split())))
    return similarity>=0.91 and common>=0.75

def lookup_bede(titres,index):
    """Appariement conservateur au listing général Bédé.fr, avec vérification de titre/tome."""
    found={}
    for book in titres:
        matches=[c for c in index.get('classement_general',[]) if meme_livre(book['titre'],c.get('alt',''))]
        if len(matches)==1:
            found[book['rang']]={'url':matches[0]['couverture_url'],'reference':matches[0]['alt']}
    return found

def cover_path(directory,titre):
    return Path(directory)/(hashlib.sha256(core_title(titre).encode()).hexdigest()[:20]+'.png')

def download_cover(book,found,directory,*,getter=requests.get):
    rank=book['rang']; item=found.get(rank)
    if not item:return False,'Pas de couverture sûre trouvée'
    url=item['url'];domain=urlparse(url)
    if domain.scheme!='https' or domain.hostname not in ALLOW:return False,'Hôte image non autorisé'
    if not meme_livre(book['titre'],item['reference']):return False,'Correspondance titre/tome rejetée'
    path=cover_path(directory,book['titre'])
    if path.exists():return True,'Cache local vérifié'
    try:
        r=getter(url,headers={'User-Agent':'Mozilla/5.0'},timeout=18)
        r.raise_for_status()
        if len(r.content)>3_500_000:return False,'Image trop lourde'
        if not r.headers.get('Content-Type','').lower().startswith('image/'):
            return False,'Contenu non image'
        im=Image.open(io.BytesIO(r.content));im.load()
        if im.width<100 or im.height<100:return False,'Image trop petite'
        if im.width*im.height>15_000_000:return False,'Image trop grande'
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        im.convert('RGB').save(path,optimize=True)
        return True,url
    except Exception as e:
        return False,f'Échec du téléchargement : {str(e)[:95]}'
