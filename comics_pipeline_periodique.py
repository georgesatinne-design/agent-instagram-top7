"""Comics autonomes: hebdo Top 5, mensuel Top 7 conditionnel.
Les fichiers BD/MANGA et le moteur graphique partagé ne sont jamais modifiés.
"""
from __future__ import annotations
import os
import argparse, datetime as dt, io, json
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import requests
from PIL import Image
from comics_sources_periodiques import collect_one,fetch,image_url,SourceError,HEADERS,IMAGE_HOSTS,normal,parse_monthly_bdfugue
from comics_score_periodique import calculer
from comics_visual_periodique import render
from sources.couvertures import cover_path,search_google_books,meme_livre
from illyadera_covers import resolve_cover

VERSION='comics_top5_top7_2026_v1'

def save(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def load(path):
    try:return json.loads(Path(path).read_text(encoding='utf8'))
    except (ValueError,OSError):return None

def update_evolution(data,previous):
    for item in data['titres']:item['mouvement']='NON DOCUMENTÉ'
    data['variations_verifiees']=False
    if not previous or previous.get('cadence')!=data['cadence'] or previous.get('mode_interne')!=data.get('mode_interne'):
        return
    current=data.get('edition','');prior=previous.get('edition','')
    if data['cadence']=='HEBDO':
        expected=dt.date.fromisocalendar(data['annee'],data['semaine'],1)-dt.timedelta(days=7)
        a=expected.isocalendar()
        if prior!=f'COMICS_HEBDO_{a.year}_W{a.week:02d}':return
    else:
        first=dt.date(data['annee'],data['mois'],1)-dt.timedelta(days=1)
        if prior!=f'COMICS_MENSUEL_{first:%Y_%m}':return
    prior_map={normal(b['titre']):b['rang'] for b in previous.get('titres',[])}
    for item in data['titres']:
        old=prior_map.get(normal(item['titre']))
        if old is None:item['mouvement']='NOUVEAU'
        elif old==item['rang']:item['mouvement']='STABLE'
        else:item['mouvement']=f'{old-item["rang"]:+d} PL.'
    data['variations_verifiees']=True

def _download_one(book,folder,*,getter=requests.get,searcher=search_google_books):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=cover_path(folder,book['titre'])
    if path.exists():
        try:
            with Image.open(path) as im:
                if im.width>=180 and im.height>=250:return {'rang':book['rang'],'ok':True,'origine':'cache_local'}
        except OSError:path.unlink(missing_ok=True)
    url=book.get('couverture_candidate_url') or ''
    urls=[]
    if image_url(url,url) and meme_livre(book['titre'],book.get('couverture_reference',book['titre'])):
        urls.append((url,book['titre']))

    allowed=IMAGE_HOSTS|{'books.google.com','books.google.fr','books.googleusercontent.com',
        'books.google.co.uk','books.google.de','books.googleusercontent.fr','media.hachette.fr'}
    for url,reference in urls:
        u=urlparse(url)
        if u.scheme!='https' or u.hostname not in allowed:continue
        try:
            r=getter(url,headers=HEADERS,timeout=25,allow_redirects=True)
            r.raise_for_status()
            dest=urlparse(getattr(r,'url',url))
            if dest.scheme!='https' or dest.hostname not in allowed:continue
            if len(r.content)>4_000_000:continue
            if not r.headers.get('Content-Type','').lower().startswith('image/'):continue
            im=Image.open(io.BytesIO(r.content));im.load()
            if im.width<180 or im.height<250 or im.width*im.height>16_000_000:continue
            im.convert('RGB').save(path,optimize=True)
            return {'rang':book['rang'],'ok':True,'origine':url}
        except (requests.RequestException,OSError,ValueError):continue
    # Dernière chance: une couverture de catalogue avec titre et édition conformes.
    try:alternate=searcher(book)
    except Exception:alternate=None
    if alternate and alternate.get('url') and meme_livre(book['titre'],alternate.get('reference','')):
        url=alternate['url'];u=urlparse(url)
        if u.scheme=='https' and u.hostname in allowed:
            try:
                r=getter(url,headers=HEADERS,timeout=22,allow_redirects=True);r.raise_for_status()
                dest=urlparse(getattr(r,'url',url))
                if dest.scheme=='https' and dest.hostname in allowed and len(r.content)<4_000_000 and r.headers.get('Content-Type','').lower().startswith('image/'):
                    im=Image.open(io.BytesIO(r.content));im.load()
                    if im.width>=180 and im.height>=250 and im.width*im.height<=16_000_000:
                        im.convert('RGB').save(path,optimize=True)
                        return {'rang':book['rang'],'ok':True,'origine':url}
            except (requests.RequestException,OSError,ValueError):pass
    if os.environ.get('ILLYADERA_MULTI_COVER_ON')=='1':
        extra=resolve_cover(book,folder)
        if extra['ok']:
            return {'rang':book['rang'],'ok':True,'origine':extra['source']}
        return {'rang':book['rang'],'ok':False,'origine':extra['raison'],'tentatives':extra['essais']}
    return {'rang':book['rang'],'ok':False,'origine':'Couverture exacte indisponible ou trop petite'}

def _enrich_monthly(data,fetcher=fetch):
    if data['mode_interne']!='BDFUGUE_30J':return
    from comics_pipeline_auto import enrich_product
    for b in data['titres']:
        try:enrich_product(b,fetcher=fetcher)
        except (requests.RequestException,SourceError):pass

def run_one(cadence,*,output=Path('sorties/comics_periodique'),history=Path('comics_history'),
            now=None,prebuilt=None,fetcher=fetch,covers_fn=None):
    now=now or dt.datetime.now(ZoneInfo('Europe/Paris'));today=now.astimezone(ZoneInfo('Europe/Paris')).date()
    n=5 if cadence=='HEBDO' else 7
    try:
        data,proofs=prebuilt if prebuilt is not None else collect_one(cadence,now=now,fetcher=fetcher)
        if data['cadence']!=cadence or len(data['titres'])!=n:raise SourceError('Top incomplet')
    except (requests.RequestException,ValueError,SourceError) as exc:
        target=Path(output)/f'SANS_TOP{n}_{cadence}'
        state={'categorie':'COMICS','cadence':cadence,'pret_buffer':False,
            'motif':str(exc),'action':'AUCUN_POST_ENVOYE'}
        save(target/'ETAT.json',state)
        (target/'RAPPORT.md').write_text('# Comics: aucune publication\n\n'+str(exc)+'\n',encoding='utf8')
        return target
    _enrich_monthly(data,fetcher=fetcher)
    previous=load(Path(history)/cadence.lower()/'dernier_classement.json')
    update_evolution(data,previous)
    out=Path(output)/data['edition'];vis=out/'COMICS';folder=vis/'couvertures'
    cover_checks=[(covers_fn or _download_one)(b,folder) for b in data['titres']]
    score=calculer(data,proofs,cover_checks,today=today)
    data['qualite_editoriale']=score
    save(out/'classement_comics.json',data)
    save(out/'preuves_comics.json',proofs)
    save(out/'SCORE_PUBLICATION.json',score)
    save(vis/'AUDIT_COUVERTURES.json',{'controles':cover_checks})
    drawing=render(data,vis,folder,watermark=not score['autorise_publication'])
    ready=bool(score['autorise_publication'] and not drawing['missing'])
    state={'categorie':'COMICS','cadence':cadence,'edition':data['edition'],
        'pret_buffer':ready,'score_qualite_editoriale':score['valeur'],'seuil':70.0,
        'pages':drawing['pages'],'couvertures':sum(bool(x['ok']) for x in cover_checks),
        'action':'CARROUSEL_PRET' if ready else 'NON_PUBLIABLE'}
    save(out/'ETAT.json',state)
    save(vis/'post_manifest.json',{'category':'COMICS','cadence':cadence,'edition':data['edition'],
        'version_contenu':VERSION,'pages':drawing['files'],'quality':score,
        'ready_to_stage':ready,'source_validated':ready})
    (out/'RAPPORT.md').write_text(
        f'# Audit interne comics {cadence}\n\n- Édition : {data["edition"]}\n'
        f'- Score : {score["valeur"]}/100 (non probabiliste)\n'
        f'- Sources : {data["url_source"]}\n- Couvertures : {state["couvertures"]}/{n}\n'
        f'- Pages : {state["pages"]}/{n+1}\n- Buffer autorisé : {ready}\n',encoding='utf8')
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cadence',choices=('HEBDO','MENSUEL','TOUS'),default='TOUS')
    p.add_argument('--sortie',type=Path,default=Path('sorties/comics_periodique'))
    p.add_argument('--historique',type=Path,default=Path('comics_history'))
    a=p.parse_args()
    for cad in (('HEBDO','MENSUEL') if a.cadence=='TOUS' else (a.cadence,)):
        out=run_one(cad,output=a.sortie,history=a.historique)
        print((out/'ETAT.json').read_text(encoding='utf8'))

if __name__=='__main__':main()
