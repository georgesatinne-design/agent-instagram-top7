"""COMICS: vente -> contrôle -> couvertures exactes -> 8 images -> Buffer par workflow.

Tout est additionnel: aucun script de production BD ni manga n'est modifié.
"""
from __future__ import annotations
import os
import argparse
import io
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw
from manga_sources_hebdo import match_titles
from sources.couvertures import cover_path,download_cover,search_google_books,meme_livre
from illyadera_covers import resolve_cover
from visual_top7 import render_top7,font,pill
from comics_sources_hebdo import collect_live,build_candidate,validate_cover_url,fetch,CollectError
from comics_score_publication import calculer

ROOT=Path(__file__).resolve().parent
VERSION='comics_auto_v1'

def save(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def read(path):
    try:return json.loads(Path(path).read_text(encoding='utf8'))
    except (OSError,ValueError,TypeError):return None

def normalize_title(title):
    title=' '.join(str(title or '').split())
    if ' - : ' in title:
        first,second=title.split(' - : ',1)
        if len(second)>6:title=second
    return title

def update_previous(data,prev):
    """Calcul de flèche seulement si même mesure, semaine précédente réelle."""
    for x in data['titres']:x['mouvement']='NON DOCUMENTÉ'
    data['variations_verifiees']=False
    if not prev or data['mode_interne']!=prev.get('mode_interne'):return
    if data.get('releve_source')!=prev.get('releve_source'):return
    try:
        old=dt.date.fromisoformat(prev['semaine_reference'][0]);new=dt.date.fromisoformat(data['semaine_reference'][0])
    except (KeyError,ValueError,TypeError):return
    if (new-old).days!=7:return
    def key(book):return str(book.get('ean') or book.get('url_produit') or '').split('?')[0]
    oldr={key(x):x['rang'] for x in prev.get('titres',[]) if key(x)}
    for x in data['titres']:
        previous_rank=oldr.get(key(x))
        if previous_rank is None:x['mouvement']='NOUVEAU'
        else:
            diff=previous_rank-x['rang']
            x['mouvement']='STABLE' if diff==0 else f'{diff:+d} PL.'
    data['variations_verifiees']=True

def enrich_product(book,*,fetcher=fetch):
    """Récupère éditeur, ISBN et couverture depuis la fiche produit exacte.

    BDFugue est la source de classement de repli; une fiche différente du titre
    attendu n'est jamais acceptée pour enrichir le contenu.
    """
    u=book.get('url_produit','')
    host=urlparse(u).hostname
    if host not in ('www.fnac.com','fnac.com','www.bdfugue.com','bdfugue.com'):
        return book
    try:soup=BeautifulSoup(fetcher(u),'html.parser')
    except (requests.RequestException,CollectError):return book
    title_tag=soup.select_one('h1')
    page_title=title_tag.get_text(' ',strip=True) if title_tag else ''
    if page_title and not match_titles(book['titre'],page_title):return book
    if host in ('bdfugue.com','www.bdfugue.com'):
        # Sur les fiches BDFugue, on trouve « Éditeur Urban Comics » et « Référence 979... ».
        root=soup.select_one('main') or soup
        texts=[t.strip() for t in root.stripped_strings]
        pub=''
        for i,t in enumerate(texts[:-1]):
            if re.fullmatch(r'(?:[ÉE]diteur|[ÉE]diteur\s*:)',t,re.I):
                candidate=texts[i+1].strip()
                if 3<=len(candidate)<=80 and not candidate.lower().startswith(('voir','genre','resume','résumé')):
                    pub=candidate;break
        if not pub:
            match=re.search(r'\b[ÉE]diteur\s*:?\s*(Urban Comics|Panini Comics|Panini|Delcourt|Huginn\s*&\s*Muninn|Bliss Comics|Hi Comics|Black River|Vestron|404 Comics|Komics Initiative|Akileos|Glénat|Dargaud|Soleil|Ankama|Futuropolis)\b',root.get_text(' ',strip=True),re.I)
            if match:pub=match.group(1)
        if pub:book['editeur']=pub
    else:
        text=soup.get_text(' ',strip=True)
        match=re.search(r'\bEditeur\s+(.{2,70}?)(?:\s+Parution\b|\s+En stock\b)',text,re.I)
        if match and not book.get('editeur'):book['editeur']=match.group(1).strip()
    nums=[]
    for sel in ('meta[itemprop="isbn"]','meta[property="product:ean"]',
                'meta[itemprop="gtin13"]','meta[itemprop="sku"]'):
        for el in soup.select(sel):nums+=re.findall(r'\b(?:978|979)\d{10}\b',el.get('content',''))
    for script in soup.select('script[type="application/ld+json"]'):
        nums+=re.findall(r'\b(?:978|979)\d{10}\b',script.get_text())[:5]
    if host in ('bdfugue.com','www.bdfugue.com'):
        nums+=re.findall(r'(?:R[ée]f[ée]rence|SKU)[.\s:]*((?:978|979)\d{10})',
                         soup.get_text(' ',strip=True),re.I)[:5]
    if len(set(nums))==1:book['ean']=nums[0]
    og=soup.select_one('meta[property="og:image"]')
    if og and validate_cover_url(og.get('content','')):
        book['couverture_candidate_url']=og['content']
        book['couverture_reference']=book['titre']
    return book


def _download_comics_cover(book,found,directory,*,getter=requests.get):
    """Autorise UNIQUEMENT une image BDFugue HTTPS pour cette chaîne comics.

    Aucune modification des domaines autorisés dans les collecteurs BD/manga.
    """
    rank=book['rang'];item=found.get(rank)
    if not item:return False,'Pas de couverture'
    url=item['url']
    if not validate_cover_url(url):return False,'URL couverture non autorisée'
    if not meme_livre(book['titre'],item['reference']):return False,'Titre / édition discordants'
    path=cover_path(directory,book['titre'])
    if path.exists():return True,'Cache comics vérifié'
    try:
        response=getter(url,headers={'User-Agent':'Mozilla/5.0'},timeout=22)
        response.raise_for_status()
        final=urlparse(getattr(response,'url',url))
        if not validate_cover_url(final.geturl()):return False,'Redirection image non autorisée'
        if not response.headers.get('Content-Type','').lower().startswith('image/'):
            return False,'Ressource non image'
        if len(response.content)>3_500_000:return False,'Couverture trop lourde'
        im=Image.open(io.BytesIO(response.content));im.load()
        if im.width<180 or im.height<250 or im.width*im.height>15_000_000:
            return False,'Résolution de couverture invalide'
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        im.convert('RGB').save(path,optimize=True)
        return True,url
    except (requests.RequestException,OSError,ValueError) as exc:
        return False,str(exc)[:110]


def _download_cover_comics(book,found,directory):
    item=found.get(book['rang'])
    if item and 'bdfugue.com' in (urlparse(item['url']).hostname or ''):
        return _download_comics_cover(book,found,directory)
    return download_cover(book,found,directory)

def covers_get(data,folder,*,downloader=download_cover,google=search_google_books,fetcher=fetch):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    res=[]
    for b in data['titres']:
        p=cover_path(folder,b['titre'])
        if p.exists():
            res.append({'rang':b['rang'],'ok':True,'origine':'cache_versionne'});continue
        cand=validate_cover_url(b.get('couverture_candidate_url',''))
        if not cand and b.get('url_produit'):
            enrich_product(b,fetcher=fetcher)
            cand=validate_cover_url(b.get('couverture_candidate_url',''))
        found={b['rang']:{'url':cand,'reference':b.get('couverture_reference') or b['titre']}} if cand else {}
        ok,why=(_download_cover_comics(b,found,folder) if downloader is download_cover else downloader(b,found,folder))
        if not ok and b.get('url_produit'):
            # Le visuel de liste Fnac est parfois trop petit. Essayer l'og:image
            # de la FICHE EXACTE avant de chercher une couverture alternative.
            enrich_product(b,fetcher=fetcher)
            candidate2=validate_cover_url(b.get('couverture_candidate_url',''))
            if candidate2:
                ok,why=(_download_cover_comics(b,{b['rang']:{'url':candidate2,
                    'reference':b.get('couverture_reference') or b['titre']}},folder) if downloader is download_cover else downloader(b,{b['rang']:{'url':candidate2,'reference':b.get('couverture_reference') or b['titre']}},folder))
        if not ok:
            try:alternative=google(b)
            except Exception:alternative=None
            if alternative:ok,why=(_download_cover_comics(b,{b['rang']:alternative},folder) if downloader is download_cover else downloader(b,{b['rang']:alternative},folder))
        if not ok and os.environ.get('ILLYADERA_MULTI_COVER_ON') == '1':
            multi=resolve_cover(b,folder)
            if multi['ok']:ok,why=True,multi['source']
            else:why='; '.join(str(a.get('source'))+': '+str(a.get('raison')) for a in multi['essais'])[:450]
        res.append({'rang':b['rang'],'ok':bool(ok),'origine':why})
    return res

def footer_releve(folder,data):
    """Ne PAS appeler « ventes du ... au ... » une liste Fnac sans fenêtre datée.

    Le rendu partagé est conservé intact pour les BD et les mangas. Seules les
    images comics fraîchement produites sont retouchées dans le dossier comics.
    """
    if data['mode_interne']!='RELEVE_ENSEIGNE':return
    text='CLASSEMENT RELEVÉ LE '+dt.date.fromisoformat(data['date_releve']).strftime('%d/%m/%Y')
    from PIL import ImageDraw
    for index,name in enumerate([f'{i:02d}_rang_{8-i}.png' for i in range(1,8)]+['08_recapitulatif.png'],1):
        p=Path(folder)/name
        im=Image.open(p).convert('RGB')
        d=ImageDraw.Draw(im)
        d.rounded_rectangle((16,1261,1064,1343),radius=10,fill='#970017')
        d.text((34,1267),'TOP DES VENTES • COMICS',font=font(32,True),fill='#FFF9F0')
        d.text((35,1308),text,font=font(23,True),fill='#FFF9F0')
        d.text((1045,1280),f'{index}/8',font=font(26,True),fill='#FFF9F0',anchor='ra')
        im.save(p,optimize=True)
    # Générer la prévisualisation depuis les images corrigées.
    preview=Image.new('RGB',(4*282,2*364),'#e6e3ec')
    for i,name in enumerate([f'{i:02d}_rang_{8-i}.png' for i in range(1,8)]+['08_recapitulatif.png']):
        im=Image.open(Path(folder)/name).convert('RGB');im.thumbnail((270,338))
        preview.paste(im,((i%4)*282+6,(i//4)*364+6))
    preview.save(Path(folder)/'apercu.png')
    caption=(Path(folder)/'legende_instagram.txt')
    original=caption.read_text(encoding='utf8')
    lines=original.splitlines()
    if len(lines)<2:raise ValueError('Légende du carrousel invalide')
    lines[1]='📅 Classement relevé le '+dt.date.fromisoformat(data['date_releve']).strftime('%d/%m/%Y')
    caption.write_text('\n'.join(lines)+'\n',encoding='utf8')

def produire(*,root=ROOT,output=Path('sorties/comics_production'),previous=Path('comics_history/dernier_classement.json'),
           now=None,fnac_html=None,actualitte_html=None,bede_html=None,
           covers=None,fetcher=fetch,prebuilt=None):
    now=now or dt.datetime.now(ZoneInfo('Europe/Paris'))
    output=Path(output)
    try:
        if prebuilt is not None:data,evidence=prebuilt
        elif fnac_html is not None:
            data,evidence=build_candidate(fnac_html=fnac_html,actualitte_html=actualitte_html,bede_html=bede_html,now=now)
        else:data,evidence=collect_live(now=now,fetcher=fetcher)
    except (CollectError,requests.RequestException,ValueError) as e:
        folder=output/'CONTROLE_SANS_TOP7';folder.mkdir(parents=True,exist_ok=True)
        state={'categorie':'COMICS','pret_buffer':False,'motif':str(e),'action':'AUCUN_POST_ENVOYE'}
        save(folder/'ETAT.json',state)
        (folder/'RAPPORT.md').write_text('Aucun carrousel publié : '+str(e)+'\n',encoding='utf8')
        return folder
    for b in data['titres']:
        b['titre']=normalize_title(b['titre'])
        if b.get('origine_classement')=='BDFUGUE':enrich_product(b,fetcher=fetcher)
    prior=read(previous)
    update_previous(data,prior)
    folder=output/data['edition'];folder.mkdir(parents=True,exist_ok=True)
    path=folder/'COMICS';path.mkdir(parents=True,exist_ok=True)
    found=covers(data,path/'couvertures') if covers else covers_get(data,path/'couvertures',fetcher=fetcher)
    policy=calculer(data,evidence,found,today=now.astimezone(ZoneInfo('Europe/Paris')).date())
    data['qualite_editoriale']=policy
    save(folder/'classement_comics.json',data);save(folder/'preuves_comics.json',evidence)
    save(folder/'SCORE_PUBLICATION.json',policy)
    save(path/'AUDIT_COUVERTURES.json',{'controles':found})
    generated=render_top7(data,path,path/'couvertures',use_watermark=not policy['autorise_publication'])
    # Éviter d'exporter 8 pages « pas pour publication » comme prêtes.
    if policy['autorise_publication']:
        footer_releve(path,data)
    manifest=read(path/'post_manifest.json')
    manifest.update({'edition':data['edition'],'qualite_editoriale':policy,
                     'mode_publication':data['mode_interne'],'version_contenu':VERSION,
                     'ready_to_stage':bool(policy['autorise_publication'] and not generated['missing_covers'])})
    save(path/'post_manifest.json',manifest)
    state={'categorie':'COMICS','edition':data['edition'],'mode':data['mode_interne'],
        'pret_buffer':manifest['ready_to_stage'],'couvertures':sum(x['ok'] for x in found),
        'pages':generated['pages'],'score_qualite_editoriale':policy['valeur'],
        'seuil':70,'action':'CARROUSEL_PRET' if manifest['ready_to_stage'] else 'NON_PUBLIABLE'}
    save(folder/'ETAT.json',state)
    (folder/'RAPPORT.md').write_text(
       '# Rapport interne comics\n\n'
       f"- Edition : {data['edition']}\n- Mode : {data['mode_interne']}\n"
       f"- Score éditorial : {policy['valeur']}/100 (pas une probabilité)\n"
       f"- Couvertures : {state['couvertures']}/7 ; pages : {state['pages']}/8\n"
       f"- Programmation autorisée : {state['pret_buffer']}\n"
       '- Références et incertitudes uniquement dans les fichiers internes.\n',encoding='utf8')
    return folder

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sortie',default='sorties/comics_production')
    p.add_argument('--precedent',default='comics_history/dernier_classement.json')
    args=p.parse_args()
    output=produire(output=Path(args.sortie),previous=Path(args.precedent))
    print((output/'ETAT.json').read_text(encoding='utf8'))

if __name__=='__main__':main()
