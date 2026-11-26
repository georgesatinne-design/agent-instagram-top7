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
        if 'zoom sur les meilleures ventes de bd du' in title and urlparse(href).hostname in ('www.bdzoom.com','bdzoom.com'):
            match=re.search(r'zoom-sur-les-meilleures-ventes-de-bd-du-(\d{1,2})-([a-z]+)-(20\d{2})',norm(href))
            published=None
            if match:
                day,month,year=match.groups()
                if month in MONTHS:
                    try: published=dt.date(int(year),MONTHS[month],int(day))
                    except ValueError:pass
            if href not in [u for _,u in links]:
                links.append((published,href))
    if not links: raise SourceError('Aucun lien vers le dernier classement BD sur la page source')
    dated=[(date,url) for date,url in links if date is not None and date<=dt.date.today()]
    if dated:return max(dated,key=lambda item:item[0])[1]
    return links[0][1]

def dates_semaine(s):
    """Cherche une période de VENTES explicite, jamais la date de publication.

    Tolère les paragraphes, espaces insécables et légendes WordPress.
    """
    cleaned=' '.join(norm(str(s)).replace('\xa0',' ').replace('1er','1').replace('1 er','1').split())
    # Variantes réelles : "Top 20 BD (copyright GfK/Livres Hebdo) du 2 au 8 novembre 2026"
    # et "Top 20 BD du 26 octobre au 1er novembre 2026".
    patterns=(
        r'top\s*20\s*(?:des\s*ventes\s*de\s*)?bd\b.{0,220}?\bdu\s+(\d{1,2})(?:\s+([a-z]+))?\s+au\s+(\d{1,2})\s+([a-z]+)\s+(20\d{2})',
        r'(?:gfk\s*/\s*livres\s*hebdo|palmares\s+bd).{0,180}?\bdu\s+(\d{1,2})(?:\s+([a-z]+))?\s+au\s+(\d{1,2})\s+([a-z]+)\s+(20\d{2})'
    )
    matches=[]
    for pattern in patterns:
        for m in re.finditer(pattern,cleaned,re.I):
            sday,smonth,eday,emonth,year=m.groups()
            smonth=smonth or emonth
            if smonth not in MONTHS or emonth not in MONTHS:
                continue
            try:
                end=dt.date(int(year),MONTHS[emonth],int(eday))
                start=dt.date(int(year)-(MONTHS[smonth]>MONTHS[emonth]),MONTHS[smonth],int(sday))
            except ValueError:
                continue
            if (end-start).days==6:  # semaine complète de 7 jours
                matches.append((start.isoformat(),end.isoformat()))
    unique=list(dict.fromkeys(matches))
    if len(unique)==1:return unique[0]
    if not unique:
        raise SourceError('Impossible de lire les dates EXACTES des ventes du Top 20 BD')
    raise SourceError('Plusieurs périodes de ventes BD différentes détectées : vérification humaine nécessaire')

def mouvement(s):
    s=norm(s).strip(' ()').replace('−','-').replace('–','-').replace('—','-')
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
    # Certaines pages WordPress placent le titre de tableau hors .entry-content.
    # On essaie d'abord l'article, puis le texte complet, mais sans mélanger
    # des périodes différentes. Aucun rang n'est supposé.
    regions=[]
    for part in (soup.select_one('main article'),soup.select_one('article .entry-content'),
                 soup.select_one('.entry-content'),soup.select_one('main'),soup):
        if part is not None and all(id(part)!=id(x) for x in regions):regions.append(part)
    beginning=end=None
    for part in regions:
        try:
            beginning,end=dates_semaine(part.get_text(' ',strip=True))
            break
        except SourceError:
            continue
    if not beginning:
        raise SourceError('Période du Top 20 BD introuvable, même après recherche dans toute la page')

    tables=[]
    for part in regions:
        for table in part.find_all('table'):
            if id(table) not in {id(t) for t in tables}:tables.append(table)
    best=[]
    for table in tables:
        possible=[]
        for row in table.select('tr'):
            cells=row.find_all(['td','th'],recursive=False)
            vals=[c.get_text(' ',strip=True).replace('\xa0',' ').strip() for c in cells]
            if len(vals)<4:continue
            matched=re.match(r'^\s*(\d{1,2})\s*(?:er|e|eme|re)?\s*$',norm(vals[0]))
            if not matched:continue
            rank=int(matched.group(1))
            if not 1<=rank<=20:continue
            # La variation peut être dans une cellule séparée OU avec le rang.
            if len(vals)>=5:
                m=norm(vals[1]).strip(' ()')
                has_variation=bool(re.fullmatch(r'[+\-−–—]\s*\d+|=|nouveau|retour|stable|idem',m))
                offset=2 if has_variation else 1
                change=vals[1] if has_variation else ''
            else:
                offset=1;change=''
            if len(vals)<offset+3:continue
            title=vals[offset]
            if not 3<len(title)<220:continue
            possible.append({'rang':rank,'titre':title,'auteurs':vals[offset+1],
                             'editeur':vals[offset+2],'mouvement':mouvement(change)})
        ranked=sorted(possible,key=lambda x:x['rang'])
        # Validation stricte : 7 premiers obligatoires, sans doublon de rang.
        if len(ranked)>=7 and [v['rang'] for v in ranked[:7]]==list(range(1,8)):
            best=ranked[:10] if len(ranked)>=10 and [v['rang'] for v in ranked[:10]]==list(range(1,11)) else ranked[:7]
            break
    if not best:raise SourceError('Tableau national Top 7 BD absent ou HTML modifié')
    confirmed=all(b['mouvement']!='NON DOCUMENTÉ' for b in best[:7])
    return {'categorie':'BD','perimetre':'Top 20 BD GfK / Livres Hebdo — rangs 1 à '+str(len(best))+', France',
        'debut_ventes':beginning,'fin_ventes':end, 'source':'BDZoom / GfK-Livres Hebdo','url_source':url,
        'statut':'À VALIDER — extraction du tableau original', 'variations_verifiees':confirmed,'titres':best}

def rangs_bede(html):
    """Lit les rangs EXPLICITES de l'index général Bédé.fr, sans les renuméroter."""
    soup=BeautifulSoup(html,'html.parser')
    headline=soup.get_text(' ',strip=True)
    md=re.search(r'palmar[eè]s\s+du\s+(\d{2}/\d{2}/\d{4})',headline,re.I)
    palmares=md.group(1) if md else ''
    out={}
    # Les blocs modernes sont parfois des <div>, pas des <li>.
    for container in soup.find_all(['li','article','div']):
        imgs=container.find_all('img',alt=True)
        if not imgs or len(imgs)>2:continue
        img=next((i for i in imgs if i.get('alt','').strip()),None)
        if not img:continue
        direct=container.get_text(' ',strip=True)
        if len(direct)>700:continue
        # Exiger #n comme sur l'index Edistat ; un numéro de tome n'est pas un rang.
        m=re.search(r'(?:^|\s)#\s*(\d{1,3})\b',direct)
        if not m:continue
        rank=int(m.group(1))
        if not 1<=rank<=600:continue
        alt=img.get('alt','').strip()
        cover=urljoin(BEDE,img.get('data-src') or img.get('data-lazy-src') or img.get('src') or '')
        links=[urljoin(BEDE,a['href']) for a in container.select('a[href]')
               if urlparse(urljoin(BEDE,a.get('href',''))).hostname in ('bede.fr','www.bede.fr')
               and urljoin(BEDE,a.get('href','')).rstrip('/')!=BEDE.rstrip('/')]
        link=next((u for u in links if urlparse(u).path not in ('/meilleures-ventes','/')), '')
        candidate={'rang_general':rank,'titre_candidat':re.sub(r'^(BD|Manga|Comics)\s+','',alt,flags=re.I),
                   'alt':alt,'couverture_url':cover,'fiche_url':link}
        if rank not in out or (not out[rank]['fiche_url'] and link):out[rank]=candidate
    return {'source':'Bédé.fr / palmarès général Edistat','url_source':BEDE, 'date_palmares':palmares,
            'classement_general':[out[k] for k in sorted(out)]}

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
