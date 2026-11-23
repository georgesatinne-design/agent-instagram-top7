"""Manga V7 — contrôles regroupés et dossier de validation (sans aucune publication).

L'observation des rangs, leur qualité probatoire, l'identification des éditions
et la disponibilité des couvertures sont des questions distinctes. Ne jamais
interpréter le taux de couvertures trouvées comme une confiance sur les ventes.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from controle_manga_v6 import explicit_week_ranges, article_published_on, fetch_article
from enrichissement_manga_v5 import (
    verifier_ean, safe_url, enregistrer_couverture, incruster_couvertures,
    google_books_isbn, SOURCE_HOSTS, IMAGE_HOSTS,
)

REPORTS = Path('rapports_manga')
CATALOGUE_PATH = Path('editions_manga_v5.json')
HEADERS = {'User-Agent': 'AgentMangaV7/1.0 (verification d editions publiques; pas de publication)'}
# Replis directs vers des fiches françaises affichant l'EAN, et non des recherches
# à partir d'une illustration japonaise ou d'une publicité générique.
PUBLIC_CATALOGS = {
    'www.kana.fr', 'www.bdbase.fr', 'www.bdphile.fr', 'www.mangabase.fr',
    'www.decitre.fr', 'www.bubblebd.com', 'www.michel-lafon.fr',
    'www.pika.fr', 'www.glenat.com', 'actualitte.com', 'www.hachette.fr',
}
PUBLIC_IMAGE_HOSTS = IMAGE_HOSTS | PUBLIC_CATALOGS | {
    'www.bede.fr', 'bede.fr', 'cdn.bede.fr', 'images.bede.fr',
    'www.canalbd.net', 'cdn1.booknode.com', 'www.bdbase.fr', 'images.bdbase.fr',
    'static.fnac-static.com', 'image.bubblebd.com', 'media.bubblebd.com',
    'www.bdphile.fr', 'storage.bubblebd.com', 'media.kana.fr', 'static.bdbase.fr',
}
MAX_HTML = 1_500_000
FRENCH_COVER_MIN_WIDTH = 180


def normaliser(s: str) -> str:
    s = unicodedata.normalize('NFKD', str(s).lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', s))


def titre_correspond(repere: str, observation: str) -> bool:
    """Correspondance prudente par collection, tome et variante d'édition."""
    from sources.couvertures import volume, key_tokens
    if volume(repere) != volume(observation):
        return False
    a, b = key_tokens(repere), key_tokens(observation)
    if not a or len(a & b) / len(a) < .75:
        return False
    # Ne pas confondre Grimoire, Collector et l'édition courante.
    for edition in ('collector', 'grimoire', 'deluxe'):
        if (edition in normaliser(repere).split()) != (edition in normaliser(observation).split()):
            return False
    return True


def catalogue_courant(verification: dict, catalogue: dict) -> list[dict]:
    """Les EAN de la V5 ne sont autorisés QUE pour leur palmarès d'origine."""
    if catalogue.get('date_palmares') != verification.get('date_palmares_bede'):
        return []
    candidates = verification.get('candidats_non_certifies') or []
    ref = {x.get('rang_mixte'): x for x in catalogue.get('editions', [])}
    if len(candidates) < 7:
        return []
    out=[]
    for c in candidates[:7]:
        r=ref.get(c.get('rang_classement_mixte'))
        if not r or not verifier_ean(r.get('ean')) or not titre_correspond(r.get('titre',''),c.get('titre','')):
            return []
        out.append({**r,'rang_manga_provisoire':c['rang_manga_provisoire']})
    return out



def titres_recoupes_dynamiquement(article_text:str,candidats:list[dict])->list[str]:
    """Repère série + numéro exact du tome pour les NOUVELLES semaines.

    Ne dépend pas des deux titres fixes de novembre, contrairement au moteur V6.
    Un nom de série seul, sans volume, ne constitue pas un recoupement.
    """
    from sources.couvertures import volume
    text=normaliser(article_text)
    matches=[]
    for item in candidats[:7]:
        raw=str(item.get('titre') or '')
        book=raw.rsplit(' - ',1)[0] if ' - ' in raw else raw
        n=volume(book)
        if n is None:continue
        start=re.split(r'(?i)\b(?:tome|t|vol(?:ume)?)\s*[.:\-]?\s*0*\d{1,3}\b',book,maxsplit=1)[0]
        # Les noms d'éditions ne font pas nécessairement partie du titre dans
        # le palmarès journalistique.
        start=re.sub(r'(?i)\b(?:[eé]dition originale|[eé]dition|collector|grimoire|deluxe)\b',' ',start)
        signature=normaliser(start)
        if not signature or len(signature)<4:continue
        pattern=r'\b'+re.escape(signature).replace(r'\ ',r'\s+')+r'\b'
        found=False
        for m in re.finditer(pattern,text):
            zone=text[max(0,m.start()-20):min(len(text),m.end()+115)]
            if re.search(r'\b(?:tome|t|vol|volume)\s*0*'+str(n)+r'\b',zone):
                found=True;break
        if found:matches.append(book)
    return matches


def week_from_main_article(audit: dict, verification: dict, *, getter=requests.get,
                           today: dt.date | None = None) -> dict:
    """Rechercher la semaine dans le début du VRAI article, pas dans les liens liés.

    Résultat partiel: la même semaine est plausible pour la sélection mais jamais
    considérée comme preuve des sept rangs nationaux.
    """
    today=today or dt.datetime.now(dt.timezone.utc).date()
    result={'etat':'NON_ETABLIE','candidate':None,'ventes_top7_validees':False,
            'titres_recoupes':[],'preuve':None,'motif':'Aucun article daté correspondant au palmarès'}
    sources={x.get('source'):x for x in audit.get('sources',[])}
    page_date=sources.get('bede_bd_manga',{}).get('inspection',{}).get('date_palmares_affichee')
    if page_date != verification.get('date_palmares_bede'):
        result['motif']='Dates de palmarès contradictoires';return result
    try: palmares=dt.datetime.strptime(str(page_date),'%d/%m/%Y').date()
    except ValueError: result['motif']='Date de palmarès invalide';return result
    if palmares>today:
        result['motif']='Date de palmarès future';return result
    articles=sources.get('actualitte_edistat',{}).get('articles_detectes') or []
    for article in articles[:6]:
        link=article.get('url','')
        try:
            page=fetch_article(link,getter=getter)
            soup=BeautifulSoup(page,'html.parser')
            pub=article_published_on(soup)
            if not pub or abs((pub-palmares).days)>2:
                continue
            body=soup.select_one('article') or soup.select_one('main') or soup
            # L'article peut contenir des dizaines de titres et semaines dans les
            # suggestions de lecture. Seule la première semaine du chapô fait foi.
            for tag in body.select('aside, footer, nav, section.related, div.related'):
                tag.decompose()
            content=body.get_text(' ',strip=True)
            lead=re.split(r'(?i)articles? recommand[eé]s?|[àa] lire aussi|sur le m[eê]me sujet',content[:1500],maxsplit=1)[0]
            weeks=explicit_week_ranges(lead,pub.year)
            eligible=[(s,e) for s,e in weeks if 3 <= (pub-e).days <= 16 and e<=today]
            titles=titres_recoupes_dynamiquement(content[:5000],verification.get('candidats_non_certifies') or [])
            if len(eligible)==1 and len(titles)>=2:
                s,e=eligible[0]
                result.update(etat='CORROBOREE_PARTIELLEMENT',
                              candidate={'debut':s.isoformat(),'fin':e.isoformat(),'semaine_iso':f'{s.isocalendar().year}-S{s.isocalendar().week:02d}'},
                              titres_recoupes=titles,preuve=link,
                              motif='Semaine explicitement indiquée dans le début du reportage et deux tomes reconnus; ne certifie pas les sept rangs')
                return result
            result['motif']='L’article du même jour ne fournit pas une semaine unique et deux tomes concordants'
        except (requests.RequestException, ValueError, OSError, TypeError):
            continue
    return result


def date_fraiche(palmares_date: str|None, *, today:dt.date|None=None, max_jours:int=14)->dict:
    today=today or dt.datetime.now(dt.timezone.utc).date()
    try: day=dt.datetime.strptime(str(palmares_date),'%d/%m/%Y').date()
    except ValueError: return {'frais':False,'age_jours':None,'motif':'Date du palmarès absente'}
    age=(today-day).days
    return {'frais':0<=age<=max_jours,'age_jours':age,
            'motif':('palmarès récent' if 0<=age<=max_jours else 'palmarès ancien ou futur')}


def host_ok(url:str,hosts:set[str]|frozenset[str])->bool:
    parsed=urlparse(str(url))
    return parsed.scheme=='https' and parsed.hostname in hosts and not parsed.username and not parsed.password and len(str(url))<2000


def page_for_ean(url:str,ean:str,*,getter=requests.get)->str:
    if not host_ok(url,PUBLIC_CATALOGS): raise ValueError('Fiche inconnue')
    resp=getter(url,timeout=13,headers=HEADERS,allow_redirects=True)
    resp.raise_for_status()
    if not host_ok(getattr(resp,'url',url),PUBLIC_CATALOGS):raise ValueError('Redirection non autorisée')
    if len(resp.content)>MAX_HTML:raise ValueError('Fiche trop volumineuse')
    soup=BeautifulSoup(resp.text,'html.parser')
    page=soup.select_one('main') or soup.select_one('article') or soup
    text=page.get_text(' ',strip=True)
    # Preuve EAN exacte, dans la fiche courante (pas dans une suggestion de livre).
    canonical=soup.find('link',rel='canonical')
    canonical_url=str(canonical.get('href','')) if canonical else ''
    if ean not in text and ean not in (url+' '+canonical_url):
        raise ValueError('ISBN absent de la fiche')
    return resp.text


def images_in_product_page(html:str,url:str)->list[str]:
    soup=BeautifulSoup(html,'html.parser')
    candidates=[]
    # L'image structurée est prioritaire; les bannières sont déclassées.
    for script in soup.find_all('script',type='application/ld+json'):
        try: obj=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        def walk(v):
            if isinstance(v,list):
                for w in v:walk(w)
            elif isinstance(v,dict):
                types=v.get('@type',[])
                types=types if isinstance(types,list) else [types]
                if any(str(t).lower() in ('product','book') for t in types):
                    val=v.get('image')
                    if isinstance(val,str):candidates.append(val)
                    elif isinstance(val,dict) and isinstance(val.get('url'),str):candidates.append(val['url'])
                    elif isinstance(val,list):
                        candidates.extend(x for x in val if isinstance(x,str))
                if '@graph' in v:walk(v['@graph'])
        walk(obj)
    for key in ('og:image','twitter:image'):
        for tag in soup.select(f'meta[property="{key}"],meta[name="{key}"]'):
            candidates.append(tag.get('content',''))
    # Certains catalogues (notamment Kana) n'ont pas de vraie image dans og:image.
    product=soup.select_one('main') or soup.select_one('article') or soup
    for tag in product.select('img')[:45]:
        desc=normaliser(' '.join(str(tag.get(k,'')) for k in ('alt','class','id')))
        if any(x in desc for x in ('logo','icone','avatar','reseau','banner','banniere','pub','placeholder')):
            continue
        for k in ('data-src','data-lazy-src','src','data-original'):
            if tag.get(k):candidates.append(str(tag[k]))
        if tag.get('srcset'):
            candidates.extend(part.strip().split()[0] for part in tag['srcset'].split(',') if part.strip())
    ans=[]
    for candidate in candidates:
        if not isinstance(candidate,str):continue
        full=urljoin(url,candidate)
        if host_ok(full,PUBLIC_IMAGE_HOSTS) and full not in ans:ans.append(full)
    return ans[:25]


def classify_image(path:Path,*,edition:dict|None=None,origin:str='')->dict:
    """Indice heuristique, JAMAIS certification automatique de couverture."""
    edition=edition or {}
    with Image.open(path) as image:
        image.load()
        w,h=image.size
        rgb=image.convert('RGB');rgb.thumbnail((180,240))
        p=list(rgb.getdata())
        white=sum(1 for r,g,b in p if min(r,g,b)>=238)/max(1,len(p))
        ratio=w/h
        is_collector='collector' in normaliser(edition.get('titre',''))
        if w<FRENCH_COVER_MIN_WIDTH or h<250:
            typ='IMAGE_TROP_PETITE'
        elif ratio<.45 or ratio>.95:
            typ='VISUEL_PROMOTIONNEL_OU_BANNIERE'
        elif is_collector and white>.24:
            typ='PACKSHOT_COLLECTOR_A_VERIFIER'
        elif white>.52:
            typ='PACKSHOT_OU_COUVERTURE_AVEC_MARGES'
        else:
            typ='COUVERTURE_CANDIDATE'
    return {'type':typ,'origine':origin,'largeur':w,'hauteur':h,'part_fond_blanc':round(white,3),
            'controle_humain_necessaire':True,
            'utilisable_pour_maquette':typ not in ('IMAGE_TROP_PETITE','VISUEL_PROMOTIONNEL_OU_BANNIERE')}


def get_img(url:str,path:Path,*,getter=requests.get)->tuple[bool,str]:
    if not host_ok(url,PUBLIC_IMAGE_HOSTS):return False,'Source image non autorisée'
    try:
        r=getter(url,timeout=16,headers=HEADERS,allow_redirects=True)
        r.raise_for_status()
        if not host_ok(getattr(r,'url',url),PUBLIC_IMAGE_HOSTS):return False,'Redirection image interdite'
        if len(r.content)>3_500_000 or not r.headers.get('Content-Type','').lower().startswith('image/'):
            return False,'Fichier invalide ou trop lourd'
        with Image.open(io.BytesIO(r.content)) as im:
            im.load()
            if not (180<=im.width<=2600 and 250<=im.height<=4000 and im.width*im.height<=12_000_000):
                return False,'Format ou dimensions incompatibles'
            p=path.parent
            p.mkdir(parents=True,exist_ok=True)
            im.convert('RGB').save(path,'PNG')
        return True,'Visuel candidat téléchargé'
    except (requests.RequestException,OSError,ValueError) as e:
        return False,type(e).__name__


def sources_for_book(ed:dict)->list[str]:
    """D'autres fiches françaises vérifiables par ISBN (pas de scraping de moteurs)."""
    ean=ed['ean']
    urls=[ed.get('url','')]
    # Sur la source de référence actuelle, ce tome précis possède des fiches
    # publiques identifiées par l'ISBN.
    if ean=='9782505144656':
        urls += ['https://www.bdbase.fr/manga/kagurabachi-11',
                 'https://www.bdphile.fr/album/manga/203142-kagurabachi-11-tome-11',
                 'https://www.mangabase.fr/book/kagurabachi/volume/kagurabachi-fr-tankobon/11',
                 'https://www.decitre.fr/livres/kagurabachi-t11-9782505144656.html']
    return [u for u in urls if host_ok(u,PUBLIC_CATALOGS)]



def image_bede_pour_titre(ed:dict,html:str)->str|None:
    """Image liée au titre exact de la ligne Bédé.fr (maquette seulement).

    Les images publicitaires hors de la ligne ou d'un autre tome sont refusées.
    Le volume, la série et les variantes collector/grimoire doivent concorder.
    """
    if not html or not ed.get('titre'):
        return None
    soup=BeautifulSoup(html,'html.parser')
    candidates=[]
    for img in soup.select('img[alt]'):
        alt=str(img.get('alt',''))
        if not titre_correspond(ed['titre'],alt):
            continue
        # Vérifier si le rang du classement accompagne réellement cette image.
        rank=ed.get('rang_mixte')
        if isinstance(rank,int):
            line_ok=False
            for ancestor in list(img.parents)[:5]:
                text=ancestor.get_text(' ',strip=True)
                if len(text)>550:continue
                m=re.search(r'(?:^|\s)#\s*(\d{1,3})(?=\s|$)',text)
                if m and int(m.group(1))==rank:
                    line_ok=True;break
            if not line_ok:continue
        for attr in ('data-src','data-lazy-src','src'):
            raw=img.get(attr)
            if raw:
                url=urljoin('https://www.bede.fr/meilleures-ventes',str(raw))
                if host_ok(url,PUBLIC_IMAGE_HOSTS):candidates.append(url)
        if img.get('srcset'):
            for part in img['srcset'].split(','):
                bits=part.strip().split()
                if bits:
                    url=urljoin('https://www.bede.fr/meilleures-ventes',bits[0])
                    if host_ok(url,PUBLIC_IMAGE_HOSTS):candidates.append(url)
    unique=list(dict.fromkeys(candidates))
    return unique[0] if len(unique)==1 else None


def reessayer_couverture(ed:dict,dest:Path,*,getter=requests.get,bede_html:str|None=None)->dict:
    """Essaie des fiches d'édition exactes puis Google Books / Open Library par ISBN.

    N'accepte pas de substitution si les sources ne prouvent pas l'EAN.
    """
    attempts=[]
    if dest.is_file():
        try:
            info=classify_image(dest,edition=ed,origin='V5 ou V6')
            if info['utilisable_pour_maquette']:
                return {'ok':True,'classification':info,'essais':['Déjà récupérée']}
        except OSError:pass
        dest.unlink(missing_ok=True)
    if bede_html:
        url=image_bede_pour_titre(ed,bede_html)
        if url:
            ok,reason=get_img(url,dest,getter=getter)
            if ok:
                info=classify_image(dest,edition=ed,origin='Bédé.fr — rang exact')
                if info['utilisable_pour_maquette']:
                    return {'ok':True,'classification':info,'essais':attempts,'fiche':'https://www.bede.fr/meilleures-ventes','image_url':url}
                dest.unlink(missing_ok=True)
            attempts.append('Bédé.fr: '+reason)
    for page_url in sources_for_book(ed):
        try:
            page=page_for_ean(page_url,ed['ean'],getter=getter)
            image_urls=images_in_product_page(page,page_url)
            if not image_urls:attempts.append('Pas d’image sur '+urlparse(page_url).hostname)
            for image_url in image_urls:
                ok,reason=get_img(image_url,dest,getter=getter)
                if not ok:
                    attempts.append(urlparse(image_url).hostname+': '+reason)
                    continue
                info=classify_image(dest,edition=ed,origin=urlparse(page_url).hostname)
                if info['utilisable_pour_maquette']:
                    return {'ok':True,'classification':info,'essais':attempts,'fiche':page_url,'image_url':image_url}
                dest.unlink(missing_ok=True)
        except (requests.RequestException,ValueError,OSError) as exc:
            attempts.append(urlparse(page_url).hostname+': '+type(exc).__name__)
    # Google Books permet une recherche EAN *exacte*, pas un titre vaguement proche.
    url=google_books_isbn(ed['ean'],getter=getter)
    if url:
        ok,reason=get_img(url,dest,getter=getter)
        if ok:
            info=classify_image(dest,edition=ed,origin='Google Books ISBN exact')
            if info['utilisable_pour_maquette']:
                return {'ok':True,'classification':info,'essais':attempts}
            dest.unlink(missing_ok=True)
        else:attempts.append('Google Books: '+reason)
    # Open Library après les catalogues — source strictement indexée par ISBN.
    from controle_manga_v6 import openlibrary_cover
    resp=openlibrary_cover(ed['ean'],dest,getter=getter)
    if resp.get('ok') and dest.is_file():
        info=classify_image(dest,edition=ed,origin='Open Library ISBN exact')
        if info['utilisable_pour_maquette']:
            return {'ok':True,'classification':info,'essais':attempts}
        dest.unlink(missing_ok=True)
    return {'ok':False,'essais':attempts,'motif':'Aucune couverture vérifiable par EAN récupérée'}



def editions_dynamique(verification:dict,*,getter=requests.get)->list[dict]:
    """Recherche de nouveaux EAN via une bibliothèque publique, mais jamais certifiés.

    L'ISBN et les couvertures ne doivent PAS être repris de l'édition précédente.
    Une ambiguïté sur le volume, la variante ou plusieurs ISBN bloque la sélection.
    """
    from sources.couvertures import volume
    out=[]
    for row in (verification.get('candidats_non_certifies') or [])[:7]:
        original=str(row.get('titre','')).strip()
        if ' - ' in original:
            title,publisher=original.rsplit(' - ',1)
        else:
            title,publisher=original,''
        record={'titre':title,'titre_palmares':original,'rang_manga_provisoire':row.get('rang_manga_provisoire'),
                'rang_mixte':row.get('rang_classement_mixte'),'editeur':publisher,
                'ean':None,'url':'','etat_edition':'EDITION_A_IDENTIFIER'}
        # Limite à 6 résultats. Un seul résultat unique correspondant au titre et au tome.
        endpoint='https://www.googleapis.com/books/v1/volumes'
        try:
            r=getter(endpoint,params={'q':'intitle:'+title,'maxResults':6,'printType':'books'},
                     headers=HEADERS,timeout=12,allow_redirects=True)
            r.raise_for_status()
            if urlparse(getattr(r,'url',endpoint)).hostname!='www.googleapis.com' or len(r.content)>MAX_HTML:
                raise ValueError('API Google Books refusée')
            found=[]
            for item in (r.json().get('items') or []):
                info=item.get('volumeInfo') or {}
                name=info.get('title','')+' '+info.get('subtitle','')
                # Volume exact et variante ('collector', 'grimoire', ...) exigés.
                if not titre_correspond(title,name):continue
                publisher_google=normaliser(info.get('publisher',''))
                if publisher and publisher_google:
                    # Les marques d'éditeur peuvent différer (ex.: Kana/Dargaud).
                    pubkeys=set(normaliser(publisher).split())
                    if not pubkeys.intersection(set(publisher_google.split())):
                        continue
                for ident in info.get('industryIdentifiers') or []:
                    value=str(ident.get('identifier','')).replace('-','')
                    if verifier_ean(value):found.append(value)
            found=sorted(set(found))
            if len(found)==1:
                record['ean']=found[0]
                record['etat_edition']='EAN_CANDIDAT_NON_VERIFIE_PAR_EDITEUR'
            elif len(found)>1:
                record['etat_edition']='PLUSIEURS_EAN_AMBIGUS'
        except (ValueError,KeyError,TypeError,requests.RequestException) as exc:
            record['etat_edition']='RECHERCHE_IMPOSSIBLE_'+type(exc).__name__
        out.append(record)
    return out


def medias_report(v6:dict,verification:dict,base:Path,*,getter=requests.get,
                  catalogue:dict|None=None)->dict:
    """Reste séparé du classement BD et ne recycle jamais des éditions V5 futures."""
    if catalogue is None:
        catalogue=json.loads(CATALOGUE_PATH.read_text(encoding='utf-8'))
    editions=catalogue_courant(verification,catalogue)
    root=base/'maquette_v5'
    root.mkdir(parents=True,exist_ok=True)
    if not editions:
        # Recherche DYNAMIQUE sur la semaine courante. Résultats provisoires,
        # aucun ancien EAN n'est recyclé.
        editions=editions_dynamique(verification,getter=getter)
    if not editions:
        return {'etat':'CANDIDATS_ABSENTS','couvertures':[],
                'trouvees':0,'sur':7,'images_a_rechercher':7,'packshots':0}
    rows=[]
    bede_html=None
    # Une seule lecture Bédé.fr pour les couvertures absentes dans la V5.
    # Le site source ne certifie toutefois pas la couverture ni les ventes.
    missing=[ed for ed in editions if verifier_ean(ed.get('ean')) and not (root/'couvertures'/f"{ed['ean']}.png").is_file()]
    if missing:
        try:
            url='https://www.bede.fr/meilleures-ventes'
            r=getter(url,timeout=15,headers=HEADERS,allow_redirects=True)
            r.raise_for_status()
            if host_ok(getattr(r,'url',url),{'www.bede.fr'}) and len(r.content)<2_000_000:
                bede_html=r.text
        except (requests.RequestException,ValueError,OSError):
            pass
    for ed in editions:
        ean=ed.get('ean')
        p=root/'couvertures'/f"{ean or 'INCONNU_'+str(ed['rang_manga_provisoire'])}.png"
        result=(reessayer_couverture(ed,p,getter=getter,bede_html=bede_html) if verifier_ean(ean)
                else {'ok':False,'essais':['EAN de cette édition introuvable']})
        row={'rang':ed['rang_manga_provisoire'],'titre':ed['titre'], 'ean':ean,
             'etat_edition':ed.get('etat_edition','CATALOGUE_EDITEUR_V5'),
             'editeur':ed['editeur'], 'couverture':bool(result['ok']),
             'classification':result.get('classification',{}).get('type','ABSENTE'),
             'source_image':result.get('classification',{}).get('origine','ABSENTE'),
             'fiche':result.get('fiche',ed.get('url')),'verification_visuelle_requise':True,
             'essais':result.get('essais',[])[:10]}
        rows.append(row)
    # Reconstruire les 8 PNG: le repli doit être visible dans le carrousel.
    if (base/'maquette_v4').is_dir():
        incruster_couvertures(base/'maquette_v4',root,editions)
    return {'etat':'COUVERTURES_CANDIDATES','couvertures':rows,
            'trouvees':sum(x['couverture'] for x in rows),'sur':7,
            'packshots':sum('PACKSHOT' in x['classification'] for x in rows),
            'images_a_rechercher':sum(not x['couverture'] for x in rows),
            'editions_nouvelles_a_confirmer':sum(x['etat_edition']!='CATALOGUE_EDITEUR_V5' for x in rows)}


def bilan_preparation(v6:dict,per:dict,medias:dict,verification:dict,*,today:dt.date)->dict:
    seven=verification.get('candidats_non_certifies') or []
    source_fresh=date_fraiche(verification.get('date_palmares_bede'),today=today)
    ranks_ok=len(seven)==7 and len({x.get('rang_classement_mixte') for x in seven})==7
    covers=medias.get('trouvees',0)
    packshot=medias.get('packshots',0)
    # Source mixte répertoriée ≠ palmarès national complet.
    sources_proven=False
    period_verified=False
    images_complete=covers==7 and packshot==0
    visual_ready=images_complete and ranks_ok
    # 100 % des cases requises et contrôle licences: indispensable avant Queue.
    eligible_for_queue=sources_proven and period_verified and images_complete and source_fresh['frais']
    failures=[]
    if not ranks_ok: failures.append('Sept candidats ordonnés manquent')
    if not source_fresh['frais']:failures.append('Le palmarès observé n’est pas récent')
    if per['etat']=='NON_ETABLIE':failures.append('La période de ventes est inconnue')
    elif not period_verified:failures.append('Période plausible mais non prouvée pour les sept titres')
    if not sources_proven:failures.append('Sept premiers rangs de ventes françaises non démontrés sans omissions')
    if covers!=7:failures.append(f'{7-covers} couverture(s) manquante(s)')
    if medias.get('editions_nouvelles_a_confirmer',0):failures.append('Nouvelles éditions à confirmer sur les fiches des éditeurs')
    if packshot:failures.append(f'{packshot} coffret(s) ou packshot(s) à examiner')
    # Indicateurs de progression observables, sans fausse probabilité d'erreur.
    return {'statut':('PRET_A_PROGRAMMER' if eligible_for_queue else
                      'VISUELS_PRETS_A_CONTROLER' if visual_ready else 'DOSSIER_A_COMPLETER'),
            'publication_manga_autorisee':False,'buffer':'AUCUNE_ACTION',
            'indicateurs':{'titres_selectionnes':len(seven[:7]),'editions_ean_verifiees':sum(1 for x in medias.get('couvertures',[]) if x.get('ean') and x.get('etat_edition')=='CATALOGUE_EDITEUR_V5'),
                           'couvertures_obtenues':covers,'packshots_a_controler':packshot,
                           'periode_corroborree':per['etat']=='CORROBOREE_PARTIELLEMENT',
                           'periode_nationale_7_rangs_validee':False,'classement_national_7_rangs_prouve':False,
                           'palmares_recent':source_fresh['frais'],'age_palmares_jours':source_fresh['age_jours']},
            'points_bloquants':failures,
            'prochaines_actions':('Compléter les couvertures; vérifier la semaine de ventes et une source exhaustive du Top 7 national. '
                                  'N’activer Buffer qu’après preuve des rangs et des droits de reproduction.')}


def execute(reports:Path=REPORTS,*,getter=requests.get,today:dt.date|None=None,
            catalogue_path:Path=CATALOGUE_PATH)->dict:
    today=today or dt.datetime.now(dt.timezone.utc).date()
    audit=json.loads((reports/'audit_manga.json').read_text(encoding='utf-8'))
    verification=json.loads((reports/'verification_manga.json').read_text(encoding='utf-8'))
    v6=json.loads((reports/'controle_manga_v6.json').read_text(encoding='utf-8'))
    catalogue=json.loads(catalogue_path.read_text(encoding='utf-8'))
    period=week_from_main_article(audit,verification,getter=getter,today=today)
    medias=medias_report(v6,verification,reports,getter=getter,catalogue=catalogue)
    prep=bilan_preparation(v6,period,medias,verification,today=today)
    result={'version':7,'categorie':'MANGA','date_controle':today.isoformat(),
            'date_palmares_observee':verification.get('date_palmares_bede'),
            'semaine_ventes':period, 'evolution_palmares':v6.get('evolution_detectee'),
            'medias':medias,'validation':prep,'top7_national_certifie':False,
            'publication_manga_autorisee':False,'queue_buffer':'NON_MODIFIEE',
            'observation':('Le statut porte sur la qualité des visuels et les preuves. '
                           'Aucune cote de confiance statistique ne peut être tirée des données incomplètes.')}
    reports.mkdir(parents=True,exist_ok=True)
    (reports/'manga_v7_rapport.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    sem=period.get('candidate') or {}
    head=[
        '# Manga V7 — tableau de bord hebdomadaire','',
        f"**Verdict : {prep['statut']}** — Aucune publication Instagram ou Buffer.",'',
        '## 1. Semaine du classement','',
        f"- Date affichée par Bédé.fr : **{verification.get('date_palmares_bede')}** — ce n’est PAS la période des ventes.",
        f"- Période candidate (ActuaLitté) : **{sem.get('debut','inconnue')} au {sem.get('fin','inconnue')}**.",
        f"- Statut de la période : **{period['etat']}** ; vérifiée pour les sept rangs : **NON**.",
        f"- Évolution depuis le contrôle précédent : **{v6.get('evolution_detectee','inconnue')}**.",
        '', '## 2. Contrôles chiffrés — ce ne sont pas des probabilités de ventes', '',
        f"- Titres provisoires présents : **{prep['indicateurs']['titres_selectionnes']}/7**.",
        f"- Éditions exactes du catalogue V5 identifiées : **{prep['indicateurs']['editions_ean_verifiees']}/7**.",
        f"- Couvertures récupérées : **{medias['trouvees']}/7**, soit **{round(100*medias['trouvees']/7)} %** de récupération visuelle.",
        '- Top 7 national vérifié dans une source exhaustive : **NON**.',
        '- Période des ventes validée pour les sept rangs : **NON**.',
        '', '## 3. Couvertures et éditions', '',
        f"- Visuels trouvés : **{medias['trouvees']}/7** (taux de récupération, pas fiabilité des ventes).",
        f"- Packshots/coffrets à contrôler : **{medias['packshots']}**.",
        f"- Nouvelles éditions encore à confirmer : **{medias.get('editions_nouvelles_a_confirmer',0)}**.",'',
        '| Rang | Manga | ISBN / EAN | Type du visuel | Contrôle |',
        '|---:|---|---|---|---|',
    ]
    if not medias['couvertures']:head += ['| — | Nouveau palmarès | — | Éditions non identifiées | À compléter |']
    for x in medias['couvertures']:
        head.append(f"| {x['rang']} | {x['titre'].replace('|','/')} | {x['ean']} | {x['classification']} | {'À examiner' if x['couverture'] else 'ABSENT'} |")
    head+=['','## 4. Fiabilité des ventes — verdict', '',
           '- Sept rangs nationaux complets **non prouvés** : les données Bédé.fr ne sont pas exhaustives.',
           '- Un classement sur sept titres plausibles ne démontre pas les sept meilleures ventes en France.',
           '- **Aucune probabilité d’erreur calculable** à partir de cette seule édition.','',
           '## 5. Ce qui empêche la publication', '']
    head += ['- '+x for x in prep['points_bloquants']]
    head += ['', '## 6. Décision pratique', '',
             '**Prêt à contrôler les visuels** ne signifie jamais **prêt à publier**. '
             'Il faut d’abord lier une semaine explicite aux sept positions d’un palmarès national complet '
             'et vérifier chaque image ainsi que ses droits.','','_Sources et EAN : conservés dans les rapports internes uniquement._','']
    (reports/'TABLEAU_DE_BORD_MANGA_V7.md').write_text('\n'.join(head),encoding='utf-8')
    lines=['# Contrôle avant validation des visuels manga','',
           f"Statut actuel : **{prep['statut']}**",'',
           '- [ ] Sept titres prouvés par une source de ventes nationale complète',
           '- [ ] Période des ventes du lundi au dimanche reliée aux sept rangs',
           '- [ ] Nouvelle période non déjà programmée dans Buffer',
           '- [ ] Sept couvertures françaises correspondant chacune à l’EAN exact',
           '- [ ] Aucun packshot/visuel promotionnel à la place d’une couverture',
           '- [ ] Éditeurs exacts et autorisations de reproduire les couvertures',
           '- [ ] Carrousel final de huit images sans filigrane de maquette',
           '- [ ] Créneau Buffer manga distinct du vendredi BD à 17 h',
           '', '**Le dossier reste technique tant que les cases ventes et période sont vides.**','']
    (reports/'CHECKLIST_VALIDATION_MANGA_V7.md').write_text('\n'.join(lines),encoding='utf-8')
    return result


def main()->int:
    try:
        r=execute()
        print('MANGA V7',r['validation']['statut'],r['medias']['trouvees'],'/ 7 couvertures; Buffer inchangé')
        return 0
    except (OSError,ValueError,KeyError,TypeError,requests.RequestException) as e:
        print('MANGA V7 diagnostic interrompu, aucune publication:',type(e).__name__,str(e)[:200])
        return 1


if __name__=='__main__':
    raise SystemExit(main())
