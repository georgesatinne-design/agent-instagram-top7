"""Archives éditoriales pré-identifiées, sans dépendre du moteur de recherche Commons.

Les œuvres sont authentiques et anciennes. Les notices de la NGA et du Met
attestent l'accès libre ; les notices de la LOC identifient l'auteur et l'année.
Les reproductions de Doré proviennent de la collection Polona (1854).
Aucune image synthétique ou image de substitution générique.
"""
from __future__ import annotations
import hashlib,io,time
from urllib.parse import quote,urlparse
from pathlib import Path
import requests
from PIL import Image,ImageOps
from .catalogue import STATE,read,write
from .photos_reelles import PhotosIndisponibles,_phash

CACHE=STATE/'photos_authentiques'/'archives_institutionnelles'
UA='Illyadera/2.0 (public GitHub repository; archival research)'
ALLOWED={'images.metmuseum.org','collectionapi.metmuseum.org','www.metmuseum.org','api.nga.gov',
         'tile.loc.gov','cdn.loc.gov','upload.wikimedia.org','www.loc.gov'}
FACTS={'mccay-pseudonyme-silas','hokusai-manga-carnets','dore-cinq-cents-gravures'}
def commons(title):
    # Standard Wikimedia original path, from the exact file title in the notice.
    name=title.replace(' ','_');key=hashlib.md5(name.encode('utf8')).hexdigest()
    return 'https://upload.wikimedia.org/wikipedia/commons/'+key[0]+'/'+key[:2]+'/'+quote(name,safe='()')
def safe(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname in ALLOWED and not p.username and not p.password and p.port in (None,443)
def request(session,url):
    if not safe(url):raise PhotosIndisponibles('Origine interdite')
    # Retry only short transient outages; no hammering a rate-limited provider.
    for i in range(2):
        r=session.get(url,headers={'User-Agent':UA},timeout=(8,22),stream=True)
        if r.status_code not in (429,502,503,504):break
        delay=r.headers.get('Retry-After','2');r.close()
        if i or (delay.isdigit() and int(delay)>8):raise PhotosIndisponibles('Source temporairement indisponible')
        time.sleep(max(1,int(delay)) if delay.isdigit() else 2)
    try:
        if not safe(r.url):raise PhotosIndisponibles('Redirection interdite')
        r.raise_for_status()
        data=bytearray()
        for c in r.iter_content(65536):
            data.extend(c)
            if len(data)>35_000_000:raise PhotosIndisponibles('Archive trop volumineuse')
        return bytes(data)
    finally:r.close()
def file_for(session,url,notice,licence,author,label,cache):
    key=hashlib.sha256(url.encode()).hexdigest()[:24]
    dest=cache/(key+'.jpg');proof=cache/(key+'.json')
    meta=read(proof,{}) or {}
    if dest.exists() and meta.get('sha256')==hashlib.sha256(dest.read_bytes()).hexdigest() and meta.get('url_commons')==notice and meta.get('licence')==licence:
        return dest,meta
    raw=request(session,url)
    with Image.open(io.BytesIO(raw)) as src:
        if min(src.size)<340 or src.width*src.height>85_000_000:raise PhotosIndisponibles('Résolution inadmissible')
        im=ImageOps.exif_transpose(src).convert('RGB');im.thumbnail((1800,1800),Image.Resampling.LANCZOS)
        out=io.BytesIO();im.save(out,'JPEG',quality=88,optimize=True)
    data=out.getvalue();dest.write_bytes(data)
    meta={'titre_commons':label,'url_commons':notice,'image_url':url,'licence':licence,'auteur':author,
          'description':label,'sha256':hashlib.sha256(data).hexdigest(),'illustration_IA':False}
    write(proof,meta);return dest,meta
def sources(fact_id,session):
    if fact_id=='hokusai-manga-carnets':
        import json
        for oid,vol,direct in [
            (57679,1,'https://collectionapi.metmuseum.org/api/collection/v1/iiif/57679/165413/main-image'),
            (57682,4,'https://collectionapi.metmuseum.org/api/collection/v1/iiif/57682/202758/main-image'),
            (57687,10,'https://collectionapi.metmuseum.org/api/collection/v1/iiif/57687/202837/main-image'),
            (57686,9,''),(57685,8,''),(57804,'1–11','')]:
            notice='https://www.metmuseum.org/art/collection/search/'+str(oid)
            label='Hokusai Manga — volume '+str(vol)
            try:
                obj=json.loads(request(session,'https://collectionapi.metmuseum.org/public/collection/v1/objects/'+str(oid)))
                if not obj.get('isPublicDomain') or 'Hokusai' not in obj.get('artistDisplayName',''):continue
                urls=[obj.get('primaryImageSmall'),obj.get('primaryImage'),direct,*obj.get('additionalImages',[])[:4]]
            except Exception:
                # These three image URLs are explicitly linked from the checked
                # museum notices, all marked Public Domain.
                urls=[direct] if direct else []
            for url in dict.fromkeys(x for x in urls if x):
                yield url,notice,'Domaine public — Met Open Access (CC0)','Katsushika Hokusai (1760–1849)',label
        for title in ('Hokusaimanga vol1 okuzuke.jpg','Hokusaimanga vol3 title.jpg','Hokusaimangapas.png'):
            yield commons(title),'https://commons.wikimedia.org/wiki/File:'+quote(title.replace(' ','_')),'Domaine public — Hokusai (mort en 1849)','Katsushika Hokusai (1760–1849)',title
    elif fact_id=='mccay-pseudonyme-silas':
        # LOC notices contain exact reproduction identifiers and confirm Silas.
        for digital,notice,label in [
            ('07860','https://www.loc.gov/pictures/item/2005680624/','Le tramway — Dream of the Rarebit Fiend'),
            ('09520','https://www.loc.gov/pictures/item/2016684823/','La mère et son enfant — planche de 1907')]:
            for size in ('v','r'):
                yield ('https://tile.loc.gov/storage-services/service/pnp/ppmsca/'+digital[:3]+'00/'+digital+size+'.jpg',notice,
                       'Domaine public — œuvre publiée avant 1931, auteur mort en 1934; LOC sans restriction connue','Winsor McCay (1869–1934)',label)
        for uuid,notice,label in [
            ('b9502787-6dca-4a68-a925-ad0676150976','https://www.nga.gov/artworks/142155-dream-rarebit-fiend-bucking-automobile','Bucking Automobile, 1907'),
            ('244f37c4-bf6b-4f8e-b132-5a47a45de546','https://www.nga.gov/artworks/142157-dream-rarebit-fiend-here-comes-washington','Here Comes Washington, 1908')]:
            for size in ('1600,','full'):
                yield 'https://api.nga.gov/iiif/'+uuid+'/full/'+size+'/0/default.jpg',notice,'Domaine public — NGA Open Access','Winsor McCay (1869–1934)',label
        for title in ('Winsor McCay - Dream of the Rarebit Fiend - Flying Bed.png','Dream of the Rarebit Fiend 1905-01-07.jpg','Dream of the Rarebit Fiend 1905-01-28.jpg','Dream of the Rarebit Fiend 1905-02-25.jpg','Cauchemars de l\'amateur de fondue au Chester2.jpg'):
            yield commons(title),'https://commons.wikimedia.org/wiki/File:'+quote(title.replace(' ','_')),'Domaine public — publication 1904–1905; auteur mort en 1934','Winsor McCay (1869–1934)',title
    elif fact_id=='dore-cinq-cents-gravures':
        # Exact original page titles from Polona/GLAM Commons notices.
        for number in ('142927547','142927589','142927599','142927969','142927737','142927672','142927558'):
            title='Histoire pittoresque, dramatique et caricaturale de la Sainte Russie 1854 ('+number+').jpg'
            yield commons(title),'https://commons.wikimedia.org/wiki/File:'+quote(title.replace(' ','_')),'Domaine public — œuvre publiée en 1854, auteur mort en 1883','Gustave Doré (1832–1883)','Gravures de 1854 — exemplaire Polona '+number
        for number in ('2010645853','2010645854'):
            title='Histoire de la Sainte Russie LCCN'+number+'.jpg'
            yield commons(title),'https://www.loc.gov/item/'+number+'/','Domaine public — gravures de 1854; auteur mort en 1883','Gustave Doré (1832–1883)','Gravures de 1854 — exemplaire LOC '+number
def resolve(fact,*,session=None,cache=None):
    if fact['id'] not in FACTS:raise PhotosIndisponibles('Pas de corpus institutionnel pré-identifié')
    session=session or requests.Session();cache=Path(cache or CACHE);cache.mkdir(parents=True,exist_ok=True)
    picked=[];proofs=[];hashes=[];origins=set();errors=[]
    for url,notice,licence,author,label in sources(fact['id'],session):
        if notice in origins:continue
        try:
            file,meta=file_for(session,url,notice,licence,author,label,cache)
            h=_phash(file)
            if any((h-x).bit_count()<=6 for x in hashes):continue
            page=(1,3,4)[len(picked)]
            picked.append(file);hashes.append(h);origins.add(notice)
            proofs.append({**meta,'page':page,'role':label[:29],'pertinence':'Archive de l’œuvre précisément citée dans le récit : '+label,
                           'epoque':'historique','famille_source':notice,'fact_id':fact['id'],'intention_editoriale':fact['hook']})
            if len(picked)==3:return picked,proofs
        except Exception as exc:
            errors.append(type(exc).__name__+': '+str(exc)[:110])
            print('ARCHIVE_REPLI',label,type(exc).__name__,str(exc)[:130],flush=True)
    raise PhotosIndisponibles('Corpus institutionnel '+fact['id']+' : '+str(len(picked))+'/3 ; '+'; '.join(errors[-5:]))
