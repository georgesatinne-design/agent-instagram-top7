"""Recherche de couvertures EXACTES, multi-fournisseurs, sans génération IA.

Module additionnel compatible avec sources.couvertures.cover_path et les 3 pipelines
historiques. Les couvertures ne sont pas des données de vente.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from PIL import Image
from bs4 import BeautifulSoup

GOOGLE = 'https://www.googleapis.com/books/v1/volumes'
OPEN_LIBRARY = 'https://covers.openlibrary.org/b/isbn/'
BNF = 'https://openapi.bnf.fr/couverture/image/image/recupererImage'
SAFE_IMAGE_HOSTS = {
    'covers.openlibrary.org', 'openapi.bnf.fr', 'books.google.com',
    'books.google.fr', 'books.googleusercontent.com', 'books.google.co.uk',
    'books.google.de', 'books.googleusercontent.fr',
    'media.hachette.fr', 'cdn.bede.fr', 'static.fnac-static.com',
    'www.dargaud.com', 'www.dupuis.com', 'www.urban-comics.com', 'www.editions-delcourt.fr',
}
USER_AGENT = 'Illyadera-CoverResearch/1.0 (metadata cross-check; modest requests)'
OFFICIAL_PUBLISHERS = {'www.dargaud.com','www.dupuis.com','www.urban-comics.com','www.editions-delcourt.fr'}


def isbn13(book):
    for key in ('ean', 'EAN', 'isbn13', 'isbn', 'ISBN', 'code_ean'):
        raw = str(book.get(key) or '').replace('-', '').replace(' ', '')
        if len(raw) == 13 and raw.isdigit() and raw.startswith(('978', '979')):
            if sum(int(c)*(1 if i % 2 == 0 else 3) for i,c in enumerate(raw[:12])) % 10 == (10-int(raw[-1])) % 10:
                return raw
    return ''


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s).casefold())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def _tome(s):
    m = re.search(r'\b(?:tome|vol(?:ume)?|t)\s*[.:-]?\s*0*(\d+)\b', _norm(s))
    return int(m.group(1)) if m else None


def title_agrees(expected, discovered):
    a, b = _norm(expected), _norm(discovered)
    if not a or not b:
        return False
    av, bv = _tome(expected), _tome(discovered)
    if av is not None and bv is not None and av != bv:
        return False
    ignored = {'de', 'la', 'les', 'le', 'des', 'du', 'un', 'une', 'tome', 'vol', 'volume', 't', 'edition', 'editions', 'originale', 'francaise', 'bd', 'manga', 'comics'}
    def toks(s):
        return set(x for x in s.split() if len(x) > 1 and x not in ignored and not x.isdigit() and not re.fullmatch(r"(?:t|tome|vol|volume)\d+", x))
    x,y=toks(a),toks(b)
    return bool(x) and bool(y) and len(x & y) / max(1,len(x)) >= .80


def _safe(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname in SAFE_IMAGE_HOSTS and not p.username and not p.password


def _get(get, url, *, params=None, timeout=12):
    r=get(url, params=params, timeout=timeout, headers={'User-Agent':USER_AGENT}, allow_redirects=True)
    r.raise_for_status()
    return r


def _save_image(response, target):
    final_url=getattr(response,'url','')
    if not _safe(final_url):
        raise ValueError('Hôte image de redirection non autorisé')
    raw=response.content
    if len(raw)>5_000_000 or len(raw)<1500:
        raise ValueError('Image absente, miniature fictive ou taille excessive')
    if not response.headers.get('Content-Type','').lower().startswith('image/'):
        raise ValueError('La réponse n’est pas une image')
    image=Image.open(io.BytesIO(raw)); image.load()
    if image.width<180 or image.height<250 or not 1.1 < image.height/image.width < 2.6:
        raise ValueError('Dimensions et forme incompatibles avec une couverture')
    if image.width*image.height>17_000_000:
        raise ValueError('Image trop grande')
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    image.convert('RGB').save(target,format='PNG',optimize=True)
    return {'width':image.width,'height':image.height,'sha256':hashlib.sha256(raw).hexdigest()}


def _candidates(book,get):
    """Renvoie (fournisseur, url, preuve). Google vérifie le n° d'édition."""
    ean=isbn13(book)
    title=book.get('titre') or book.get('title') or ''
    if ean:
        # Vérification bibliographique avant même de demander une image à Open Library.
        try:
            meta=_get(get,'https://openlibrary.org/isbn/'+ean+'.json').json()
            registered=(meta or {}).get('title','')
            registered_ids=[str(x).replace('-','') for k in ('isbn_13','isbn_10') for x in ((meta or {}).get(k) or [])]
            if title_agrees(title,registered) and (ean in registered_ids or not registered_ids):
                yield ('Open Library — ISBN exact', OPEN_LIBRARY+ean+'-L.jpg?default=false',
                       {'ean':ean,'reference':registered,'mode':'isbn+edition'})
        except (requests.RequestException,ValueError,TypeError,KeyError):
            pass
        try:
            d=_get(get,GOOGLE,params={'q':'isbn:'+ean,'maxResults':15,'printType':'books'}).json()
            for item in d.get('items',[]):
                meta=item.get('volumeInfo') or {}
                ids=[str(x.get('identifier','')).replace('-','') for x in meta.get('industryIdentifiers',[]) if isinstance(x,dict)]
                if ean not in ids: continue
                label=' '.join(filter(None,[meta.get('title'),meta.get('subtitle')]))
                if not title_agrees(title,label): continue
                images=meta.get('imageLinks') or {}
                url=next((images[k] for k in ('extraLarge','large','medium','small','thumbnail','smallThumbnail') if images.get(k)),None)
                if url:
                    url=url.replace('http://','https://',1)
                    yield ('Google Books — ISBN et titre confirmés',url,{'ean':ean,'reference':label,'mode':'isbn+title'})
        except (ValueError,requests.RequestException,KeyError,TypeError):
            pass
        # BnF est officielle mais demande provenance + date de récupération.
        # En mode sans crédit public Illiyadera, NE PAS publier ce visuel par défaut.
        if os.environ.get('ILLYADERA_BNF_ATTRIBUTION_AUTORISEE')=='1':
            yield ('BnF — EAN exact',BNF+'?EAN='+ean+'&couverture=1&taille=originale',{'ean':ean,'attribution':'BnF + date publique obligatoire'})
    # Fiche éditeur explicitement connue : ISBN présent dans le HTML ET titre conforme.
    page_url=book.get('url_produit') or book.get('url_editeur') or book.get('publisher_url') or ''
    parsed=urlparse(page_url)
    if parsed.scheme=='https' and parsed.hostname in OFFICIAL_PUBLISHERS:
        try:
            response=_get(get,page_url)
            if urlparse(getattr(response,'url','')).hostname==parsed.hostname and len(response.content)<2_000_000:
                html=response.content.decode('utf-8',errors='ignore')
                soup=BeautifulSoup(html,'html.parser')
                h=soup.find('h1')
                product_title=h.get_text(' ',strip=True) if h else ''
                if title_agrees(title,product_title) and (not ean or ean in html.replace(' ','').replace('-','')):
                    meta=soup.find('meta',attrs={'property':'og:image'})
                    image=urljoin(page_url,meta.get('content','')) if meta else ''
                    if _safe(image):
                        yield ('Page éditeur — album et EAN confirmés',image,
                               {'ean':ean,'reference':product_title,'page':page_url})
        except (requests.RequestException,ValueError,TypeError,KeyError):
            pass
    if not ean:
        # Uniquement à défaut d'ISBN : titre ET tome cohérents ; pas de recherche images floue.
        try:
            d=_get(get,GOOGLE,params={'q':'intitle:'+title,'maxResults':30,'langRestrict':'fr','printType':'books'}).json()
            for item in d.get('items',[]):
                meta=item.get('volumeInfo') or {}
                label=' '.join(filter(None,[meta.get('title'),meta.get('subtitle')]))
                if not title_agrees(title,label): continue
                images=meta.get('imageLinks') or {}
                url=next((images[k] for k in ('extraLarge','large','medium','small','thumbnail') if images.get(k)),None)
                if url:
                    yield ('Google Books — titre vérifié, édition non certaine',url.replace('http://','https://',1),{'reference':label,'mode':'title_only'})
        except (requests.RequestException,ValueError,KeyError,TypeError):
            pass


def resolve_cover(book,folder,*,get=requests.get):
    """Sauvegarde à chemin COMPATIBLE avec les anciens rendus; audit de toutes les tentatives."""
    from sources.couvertures import cover_path
    title=book.get('titre') or book.get('title') or ''
    output=cover_path(folder,title)
    if output.is_file():
        try:
            with Image.open(output) as image:
                if image.width>=180 and image.height>=250:
                    return {'ok':True,'rang':book.get('rang'),'ean':isbn13(book),'source':'cache local','chemin':str(output),'essais':[]}
        except OSError:
            pass
    attempts=[]
    for provider,url,proof in _candidates(book,get):
        if not _safe(url):
            attempts.append({'source':provider,'raison':'hôte non autorisé'});continue
        try:
            res=_get(get,url,timeout=16)
            meta=_save_image(res,output)
            return {'ok':True,'rang':book.get('rang'),'ean':isbn13(book),'source':provider,
                    'url':url,'preuve':proof,'dimensions':meta,'chemin':str(output),'essais':attempts}
        except (requests.RequestException,ValueError,OSError) as exc:
            attempts.append({'source':provider,'raison':str(exc)[:150]})
    return {'ok':False,'rang':book.get('rang'),'ean':isbn13(book),'titre':title,'essais':attempts,
            'raison':'Aucune couverture d’édition suffisamment vérifiée; ne pas inventer de visuel'}
