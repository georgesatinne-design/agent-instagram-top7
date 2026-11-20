"""Récupération prudente de couvertures BD depuis des catalogues publics et Google Books.

N'accepte jamais un tome contradictoire ou une correspondance ambigüe.
Une couverture incertaine reste vide, et bloque automatiquement le brouillon Buffer.
"""
from __future__ import annotations
import hashlib
import io
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image
from .collecte import norm

ALLOWED_IMAGE_HOSTS={
    'cdn.bede.fr', 'media.hachette.fr', 'static.fnac-static.com',
    'books.google.com', 'books.google.fr', 'books.googleusercontent.com',
    'books.google.co.uk', 'books.google.de', 'books.googleusercontent.fr',
}
GOOGLE_API='https://www.googleapis.com/books/v1/volumes'
BEDE_CATALOG_PAGES=(
    'https://www.bede.fr/meilleures-ventes',
    'https://www.bede.fr/meilleures-bd-2026',
    'https://www.bede.fr/nouveautes-bd',
    'https://www.bede.fr/sorties-bd-novembre-2026',
    'https://www.bede.fr/sorties-bd-2026',
)
STOPWORDS={
    'le','la','les','l','de','des','du','d','et','en','un','une','au','aux','a','par',
    'bd','manga','comics','tome','t','volume','vol','edition','editions','originale',
    'album','hors','serie','hs','depuis','apres','pour','avec','tous','toutes',
    'couv','editeur','t01','t02','t03',
}

def core_title(value):
    return ' '.join(re.sub(r'[^a-z0-9]+',' ',norm(value)).split())

def volume(value):
    v=norm(value)
    m=re.search(r'\b(?:tome|t|vol\.?|volume)\s*[\.:\-]?\s*0*(\d{1,3})\b',v)
    return int(m.group(1)) if m else None

def key_tokens(value):
    # Numéros de tome, ponctuation, mentions marketing et mots-outils ignorés.
    v=re.sub(r'\b(?:tome|t|vol|volume)\s*[\.:\-]?\s*0*\d{1,3}\b',' ',norm(value))
    words=re.findall(r'[a-z0-9]+',v)
    return {w for w in words if len(w)>1 and w not in STOPWORDS and not w.isdigit()}

def title_score(title,reference):
    t,ref=key_tokens(title),key_tokens(reference)
    if not t or not ref:return 0.0
    v1,v2=volume(title),volume(reference)
    if v1 is not None and v2 is not None and v1!=v2:return 0.0
    shared=len(t & ref)
    if shared<2 and len(t)>=3:return 0.0
    # Mesure la couverture des mots du titre de classement (l'alt peut contenir l'éditeur).
    overlap=shared/len(t)
    if overlap<0.78:return 0.0
    anchor=next(iter([x for x in re.findall(r'[a-z0-9]+',norm(title)) if len(x)>2 and x not in STOPWORDS]),'')
    if anchor and anchor not in ref:return 0.0
    return overlap + (0.10 if v1 is not None and v1==v2 else 0.0)

def meme_livre(titre,alt):
    return title_score(titre,alt)>=0.78

def lookup_bede(titres,index):
    """Compatible avec la collecte Bédé.fr déjà effectuée et ses 52+ entrées."""
    return match_catalog(titres,index.get('classement_general',[]))

def match_catalog(titres,candidates):
    selected={}
    for book in titres:
        ranked=[]
        for cand in candidates:
            ref=cand.get('alt') or cand.get('titre') or cand.get('reference') or ''
            url=cand.get('couverture_url') or cand.get('url') or ''
            if not url or not ref:continue
            score=title_score(book['titre'],ref)
            if score>=0.78:ranked.append((score,ref,url))
        ranked.sort(key=lambda x:x[0],reverse=True)
        if not ranked:continue
        top=ranked[0]
        # Si deux couvertures peuvent représenter des éditions différentes, aucune sélection automatique.
        if len(ranked)>1 and ranked[1][2]!=top[2] and ranked[1][0]>=top[0]-0.08:
            continue
        selected[book['rang']]={'url':top[2],'reference':top[1]}
    return selected

def parse_catalogue_images(html,base_url):
    soup=BeautifulSoup(html,'html.parser');found=[];seen=set()
    for img in soup.select('img[alt]'):
        alt=img.get('alt','').strip()
        if len(alt)<8:continue
        raw=img.get('data-src') or img.get('data-lazy-src') or img.get('src') or ''
        if not raw:continue
        url=urljoin(base_url,raw)
        if urlparse(url).hostname not in ALLOWED_IMAGE_HOSTS:continue
        if (alt,url) in seen:continue
        seen.add((alt,url));found.append({'alt':alt,'couverture_url':url})
    return found

def search_bede_catalog(titres,*,fetcher=None,index=None):
    """Parcours quelques pages publiques Bédé.fr, sans interpréter leurs rangs comme des ventes."""
    from .collecte import fetch
    fetcher=fetcher or fetch
    candidates=list((index or {}).get('classement_general',[]));errors=[]
    matched=match_catalog(titres,candidates)
    for page in BEDE_CATALOG_PAGES:
        if len(matched)==len(titres):break
        try:
            candidates.extend(parse_catalogue_images(fetcher(page),page))
            matched=match_catalog(titres,candidates)
        except Exception as exc:
            errors.append(f'{page}: {type(exc).__name__}: {str(exc)[:90]}')
    return matched,errors

def search_google_books(book,*,getter=requests.get):
    """Repli facultatif : métadonnées publiques Google Books avec validation stricte du titre/tome."""
    title=book['titre']
    # Le libellé long du tableau peut contenir un préfixe de collection; garder le sous-titre.
    subtitle=title.rsplit(':',1)[-1].strip()
    q=subtitle if len(key_tokens(subtitle))>=2 else title
    try:
        response=getter(GOOGLE_API,params={'q':q,'maxResults':15,'langRestrict':'fr'},timeout=12,
                        headers={'User-Agent':'ClassementsFranceInstagram/1.0'})
        response.raise_for_status();data=response.json()
        candidates=[]
        for item in data.get('items',[]):
            meta=item.get('volumeInfo') or {}
            ref=' : '.join(x for x in [meta.get('title',''),meta.get('subtitle','')] if x)
            links=meta.get('imageLinks') or {}
            img=links.get('extraLarge') or links.get('large') or links.get('medium') or links.get('small') or links.get('thumbnail')
            if img and ref:
                if img.startswith('http://'):img='https://'+img[7:]
                candidates.append({'alt':ref,'couverture_url':img})
        return match_catalog([book],candidates).get(book['rang'])
    except Exception:
        return None

def cover_path(directory,titre):
    return Path(directory)/(hashlib.sha256(core_title(titre).encode()).hexdigest()[:20]+'.png')

def download_cover(book,found,directory,*,getter=requests.get):
    rank=book['rang'];item=found.get(rank)
    if not item:return False,'Pas de couverture sûre trouvée'
    url=item['url'];parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        return False,'Domaine image non autorisé'
    if not meme_livre(book['titre'],item['reference']):
        return False,'Correspondance titre/tome rejetée'
    path=cover_path(directory,book['titre'])
    if path.exists():return True,'Cache local vérifié'
    try:
        r=getter(url,headers={'User-Agent':'Mozilla/5.0'},timeout=18)
        r.raise_for_status()
        effective=urlparse(getattr(r,'url',url))
        if effective.scheme!='https' or effective.hostname not in ALLOWED_IMAGE_HOSTS:
            return False,'Redirection vers un hôte non autorisé'
        if len(r.content)>3_500_000:return False,'Image trop lourde'
        if not r.headers.get('Content-Type','').lower().startswith('image/'):
            return False,'Contenu non image'
        im=Image.open(io.BytesIO(r.content));im.load()
        if im.width<180 or im.height<250:return False,'Couverture trop petite pour un post lisible'
        if im.width*im.height>15_000_000:return False,'Image trop grande'
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        im.convert('RGB').save(path,optimize=True)
        return True,url
    except Exception as exc:
        return False,f'Échec du téléchargement : {str(exc)[:95]}'
