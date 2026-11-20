"""Collecteurs gratuits de classements français. Des échecs explicites, jamais des rangs inventés."""
from __future__ import annotations
import datetime as dt
import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests

BDZOOM = 'https://www.bdzoom.com/meilleures-ventes/'
BEDE = 'https://www.bede.fr/meilleures-ventes'
MDCU = 'https://mdcu-comics.fr/'
HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; ClassementsFranceInstagram/1.0; research)'}
MONTHS = dict(zip(('janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre'),range(1,13)))

class SourceError(RuntimeError): pass

def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value).lower()) if not unicodedata.combining(c))

def fetch(url, *, session=None, timeout=25):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in {'www.bdzoom.com','bdzoom.com','www.bede.fr','bede.fr','mdcu-comics.fr','www.mdcu-comics.fr','www.mdcu.fr','mdcu.fr'}:
        raise SourceError(f'Domaine de collecte non autorisé: {url}')
    response=(session or requests).get(url,headers=HEADERS,timeout=timeout)
    response.raise_for_status()
    if len(response.content)>8_000_000: raise SourceError('Page HTML trop volumineuse')
    return response.text

def latest_bdzoom_url(html):
    soup=BeautifulSoup(html,'html.parser')
    links=[]
    for a in soup.select('a[href]'):
        title=norm(a.get_text(' ',strip=True))
        href=urljoin(BDZOOM,a['href'])
        if re.search(r'zoom sur les meilleures ventes de bd du',title) and urlparse(href).hostname in ('www.bdzoom.com','bdzoom.com'):
            links.append(href)
    if not links: raise SourceError('Aucun lien vers le dernier classement BD sur la page source')
    # L'archive est chronologique : ne pas classer par texte de date où les années peuvent être différentes.
    return links[0]

def dates_semaine(s):
    cleaned=norm(s.replace('\xa0',' ').replace('1er','1')).replace('1 er','1')
    # La date de publication n'est PAS utilisée comme période de ventes.
    p=r'top\s*20\s*bd.{0,160}?du\s+(\d{1,2})\s*([a-z]+)?\s+au\s+(\d{1,2})\s+([a-z]+)\s+(20\d{2})'
    m=re.search(p,cleaned,re.I|re.S)
    if not m: raise SourceError('Impossible de lire les dates EXACTES des ventes du Top 20 BD')
    sday,smonth,eday,emonth,year=m.groups()
    smonth=smonth or emonth
    if smonth not in MONTHS or emonth not in MONTHS: raise SourceError('Mois inconnu dans la période de ventes')
    end=dt.date(int(year),MONTHS[emonth],int(eday))
    start=dt.date(int(year)-(MONTHS[smonth]>MONTHS[emonth]),MONTHS[smonth],int(sday))
    if not 0<=(end-start).days<=14: raise SourceError('Période de ventes incohérente')
    return start.isoformat(),end.isoformat()

def mouvement(s):
    s=norm(s).strip(' ()')
    if 'nouveau' in s or 'new'==s: return 'NOUVEAU'
    if 'retour' in s: return 'RETOUR'
    if s in ('=', 'stable', 'idem'):return 'STABLE'
    m=re.fullmatch(r'([+-])\s*(\d+)',s)
    if m:return ('+' if m.group(1)=='+' else '−')+m.group(2)+' PL.'
    return 'NON DOCUMENTÉ'

def parse_bdzoom(html,url):
    soup=BeautifulSoup(html,'html.parser')
    headline=soup.find('h1')
    if headline and 'meilleures ventes' not in norm(headline.get_text(' ',strip=True)):
        raise SourceError('L’article lu ne semble pas être un classement des ventes')
    article=soup.select_one('article .entry-content') or soup.select_one('.entry-content') or soup.select_one('article') or soup
    text=article.get_text(' ',strip=True)
    beginning,end=dates_semaine(text)
    best=[]
    for table in article.find_all('table'):
        possible=[]
        for row in table.select('tr'):
            cells=row.find_all(['td','th'],recursive=False)
            values=[c.get_text(' ',strip=True) for c in cells]
            if len(values)<5:continue
            match=re.match(r'^\s*(\d{1,2})\s*(?:er|e|ème|eme|re)?\s*$',norm(values[0]))
            if not match: continue
            rank=int(match.group(1))
            if not 1<=rank<=20:continue
            title=values[2].strip()
            if not 3<len(title)<220:continue
            possible.append({'rang':rank,'titre':title,'auteurs':values[3],'editeur':values[4], 'mouvement':mouvement(values[1])})
        ranked=sorted(possible,key=lambda x:x['rang'])
        if len(ranked)>=10 and [v['rang'] for v in ranked[:10]]==list(range(1,11)):
            best=ranked[:10];break
    if not best:raise SourceError('Tableau national Top 10 BD absent ou HTML modifié')
    return {'categorie':'BD','perimetre':'Top 20 BD GfK / Livres Hebdo — rangs 1 à 10, France',
        'debut_ventes':beginning,'fin_ventes':end, 'source':'BDZoom / GfK-Livres Hebdo','url_source':url,
        'statut':'À VALIDER — extraction du tableau original', 'variations_verifiees':True, 'titres':best}

def rangs_bede(html):
    """Extrait le classement GÉNÉRAL, pas un classement manga/comics artificiel."""
    soup=BeautifulSoup(html,'html.parser')
    headline=soup.get_text(' ',strip=True)
    md=re.search(r'palmar[eè]s\s+du\s+(\d{2}/\d{2}/\d{4})',headline,re.I)
    palmares=md.group(1) if md else ''
    out=[];seen=set()
    for li in soup.find_all('li'):
        direct=li.get_text(' ',strip=True)
        m=re.match(r'#?\s*(\d{1,3})\b',direct)
        if not m: continue
        rank=int(m.group(1))
        if rank>600 or rank in seen:continue
        img=li.find('img',alt=True)
        if not img:continue
        alt=img.get('alt','').strip()
        if not alt:continue
        cover=urljoin(BEDE,img.get('data-src') or img.get('data-lazy-src') or img.get('src') or '')
        link=next((urljoin(BEDE,a.get('href','')) for a in li.select('a[href]') if 'bede.fr' in urljoin(BEDE,a['href']) and '/meilleures-ventes' not in a['href']), '')
        out.append({'rang_general':rank,'titre_candidat':re.sub(r'^(BD|Manga|Comics)\s+','',alt,flags=re.I),
                    'alt':alt,'couverture_url':cover,'fiche_url':link})
        seen.add(rank)
    return {'source':'Bédé.fr / palmarès général Edistat','url_source':BEDE, 'date_palmares':palmares,
            'classement_general':sorted(out,key=lambda v:v['rang_general'])}

def categorie_fiche(html):
    """Ne reconnaît le genre que dans des breadcrumbs structurés, pas le menu du site."""
    soup=BeautifulSoup(html,'html.parser')
    names=[]
    for script in soup.select('script[type="application/ld+json"]'):
        try: js=json.loads(script.string or script.get_text())
        except (ValueError,TypeError):continue
        blocks=js if isinstance(js,list) else [js]
        for block in blocks:
            if isinstance(block,dict) and ('BreadcrumbList' in str(block.get('@type',''))):
                for item in block.get('itemListElement',[]):
                    if not isinstance(item,dict):continue
                    v=item.get('name') or (item.get('item',{}).get('name') if isinstance(item.get('item'),dict) else '')
                    names.append(str(v))
    for breadcrumb in soup.select('nav.breadcrumb, nav[aria-label*="readcrumb"], nav[aria-label*="ariane"], .breadcrumb, ol.breadcrumb'):
        names.append(breadcrumb.get_text(' ',strip=True))
    s=' | '.join(norm(v) for v in names)
    hits=[]
    if re.search(r'\bmangas?\b',s):hits.append('MANGA')
    if re.search(r'\bcomics?\b',s):hits.append('COMICS')
    if re.search(r'\b(bandes? dessinees?|bd franco.belge)\b',s):hits.append('BD')
    return hits[0] if len(hits)==1 else ''

def top_par_genre_bede(index, *, fetcher=fetch, limite=110, maximum=10):
    """Rangs *internes au sous-ensemble reconnu*, non les rangs du Top Edistat officiel.

    Évite d'appeler cela un «Top 10 national» puisque le site omet des albums.
    """
    groupes={'BD':[],'MANGA':[],'COMICS':[]}
    checks=[]
    for candidate in index['classement_general'][:limite]:
        if all(len(v)>=maximum for v in groupes.values()):break
        if not candidate['fiche_url']:continue
        try: cat=categorie_fiche(fetcher(candidate['fiche_url']))
        except Exception as e: checks.append(f"#{candidate['rang_general']}: {type(e).__name__}");continue
        if cat not in groupes:continue
        if len(groupes[cat])>=maximum:continue
        groupes[cat].append({'rang':len(groupes[cat])+1,'rang_general':candidate['rang_general'],
            'titre':candidate['titre_candidat'],'editeur':'Éditeur non confirmé',
            'mouvement':'NON DOCUMENTÉ', 'couverture_url':candidate['couverture_url'],
            'couverture_titre':candidate['alt'], 'fiche_url':candidate['fiche_url']})
    return groupes,checks


def collect_bd(*,fetcher=fetch):
    url=latest_bdzoom_url(fetcher(BDZOOM))
    return parse_bdzoom(fetcher(url),url)
