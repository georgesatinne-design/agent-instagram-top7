"""Source vérifiée: articles de palmarès MDCU/BDFugue, sans collecte directe Fnac.

HEBDO: MDCU publie 5 rangs explicites sur les sept derniers jours.
MENSUEL: sept rangs explicites OU classement de sept comics des 30 derniers jours.
Si une source refuse une requête ou fournit seulement cinq titres mensuels: aucun Top7.
"""
from __future__ import annotations
import datetime as dt
import re
import unicodedata
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

MDCU_HOSTS=('mdcu-comics.fr','www.mdcu-comics.fr','mdcu.fr','www.mdcu.fr')
BDFUGUE_HOSTS=('www.bdfugue.com','bdfugue.com','api.bdfugue.com')
ALL_HOSTS=set(MDCU_HOSTS+BDFUGUE_HOSTS)
MDCU_INDEX='https://mdcu-comics.fr/'
MDCU_NEWS='https://mdcu-comics.fr/news'
BDFUGUE_CHART='https://www.bdfugue.com/meilleures-ventes/comics'
IMAGE_HOSTS=ALL_HOSTS|{'cdn.bede.fr','static.fnac-static.com'}
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; TopComicsHebdoFrance/1.0; lecture de classements publics)','Accept-Language':'fr-FR,fr;q=0.9'}
PUBLISHERS=['Urban Comics','Panini Comics','Delcourt','Hi Comics','Bliss Comics','Black River',
    'Ankama','Huginn & Muninn','Vestron','Akileos','Komics Initiative','404 Comics',
    'Glénat','Soleil','Futuropolis','Dargaud','Graph Zeppelin','Moutons électriques',
    'Réflexions','Presque Lune','Drakoo','Mana Books','Label 619','Soleil Comics',
    'Astrolabe','Morgen','Caurette','Black Box','Manga Nova','Soleil BD']

class SourceError(Exception): pass

def fold(s):
    s=unicodedata.normalize('NFKD',str(s or ''))
    return re.sub(r'\s+',' ',''.join(c for c in s if not unicodedata.combining(c)).casefold()).strip()

def normal(s):
    return re.sub(r'[^a-z0-9]+',' ',fold(s)).strip()

def safe_url(raw,base,allowed=ALL_HOSTS):
    if not raw:return ''
    if raw.startswith('//'):raw='https:'+raw
    url=urljoin(base,raw)
    p=urlparse(url)
    return url if p.scheme=='https' and p.hostname in allowed else ''

def image_url(raw,base):return safe_url(raw,base,IMAGE_HOSTS)

def fetch(url,*,getter=requests.get):
    if not safe_url(url,url):raise SourceError('URL source non autorisée')
    r=getter(url,headers=HEADERS,timeout=23,allow_redirects=True)
    r.raise_for_status()
    if not safe_url(getattr(r,'url',url),url):raise SourceError('Redirection non autorisée')
    if len(r.content)>8_000_000:raise SourceError('Page trop volumineuse')
    return r.text

def article_urls(html,base=MDCU_INDEX,mode='HEBDO'):
    s=BeautifulSoup(html,'html.parser');found=[]
    token='semaine' if mode=='HEBDO' else ''
    for a in s.select('a[href]'):
        title=fold(a.get_text(' ',strip=True));href=a.get('href','')
        url=safe_url(href,base,set(MDCU_HOSTS))
        if not url:continue
        combined=fold(title+' '+url)
        if 'meilleures ventes comics bdfugue' not in combined.replace('-',' '):continue
        if mode=='HEBDO' and 'semaine' not in combined:continue
        if mode=='MENSUEL' and ('semaine' in combined or not re.search(r'(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\W*20\d{2}',combined)):
            continue
        if url not in found:found.append(url)
    return found

def date_article(soup):
    for node in soup.select('time[datetime],meta[property="article:published_time"],meta[name="datePublished"]'):
        v=node.get('datetime') or node.get('content','')
        if v:
            try:return dt.date.fromisoformat(v[:10])
            except ValueError:pass
    h1=soup.find('h1')
    if not h1:return None
    # À proximité du titre, ne pas retenir les dates de sortie des albums.
    text=' '.join(str(x) for x in h1.parent.stripped_strings)[:400]
    m=re.search(r'(?<!\d)(\d{2}/\d{2}/20\d{2})(?!\d)',text)
    if not m:
        text=soup.get_text(' ',strip=True)[:350]
        m=re.search(r'(?<!\d)(\d{2}/\d{2}/20\d{2})(?!\d)',text)
    return dt.datetime.strptime(m.group(1),'%d/%m/%Y').date() if m else None

def locate_cover(soup,title,url):
    from difflib import SequenceMatcher
    matches=[]
    for im in soup.find_all('img'):
        alt=normal(im.get('alt',''))
        wanted=normal(title)
        if not alt or not wanted:continue
        score=SequenceMatcher(None,alt,wanted).ratio()
        if alt==wanted:score=1
        if score<0.79:continue
        for attr in ('data-src','data-original','data-lazy-src','src'):
            found=image_url(im.get(attr,''),url)
            if found:
                matches.append((score,found));break
        else:
            # Plusieurs templates utilisent uniquement un srcset responsive.
            srcset=im.get('data-srcset') or im.get('srcset') or ''
            for part in srcset.split(','):
                candidate=part.strip().split(' ')[0]
                found=image_url(candidate,url)
                if found:
                    matches.append((score,found));break
    return max(matches,key=lambda x:x[0])[1] if matches else ''

def parse_mdcu_article(html,url,*,cadence):
    """N'utilise que les marqueurs #1, #2... de la section meilleures ventes.
    On ne prend jamais des suggestions commerciales ou les actualités du pied de page.
    """
    soup=BeautifulSoup(html,'html.parser');h1=soup.find('h1')
    headline=fold(h1.get_text(' ',strip=True) if h1 else '')
    if 'meilleures ventes comics bdfugue' not in headline:raise SourceError('Article sans palmarès comics MDCU')
    if cadence=='HEBDO' and 'semaine' not in headline:raise SourceError('Pas un palmarès de semaine')
    if cadence=='MENSUEL' and 'semaine' in headline:raise SourceError('Pas un palmarès mensuel')
    published=date_article(soup)
    if not published:raise SourceError('Date de publication introuvable')
    if cadence=='HEBDO':
        wm=re.search(r'\bsemaine\s*(\d{1,2})\b',headline)
        if not wm:raise SourceError('Numéro de semaine absent')
        week=int(wm.group(1))
        # En décembre/janvier, le numéro ISO peut appartenir à une autre année.
        years=(published.year-1,published.year,published.year+1)
        choices=[]
        for year in years:
            try:
                mon=dt.date.fromisocalendar(year,week,1)
                sun=mon+dt.timedelta(days=6)
                choices.append((abs((published-sun).days),year,mon,sun))
            except ValueError:pass
        if not choices:raise SourceError('Semaine ISO invalide')
        _,year,start,end=min(choices)
        if abs((published-end).days)>8:raise SourceError('Date de classement incompatible avec la semaine')
        period={'annee':year,'semaine':week,'debut_ventes':start.isoformat(),'fin_ventes':end.isoformat(),
                'periode_label':f'SEMAINE {week:02d} • {year}'}
    else:
        months={'janvier':1,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'aout':8,'septembre':9,'octobre':10,'novembre':11,'decembre':12}
        mm=re.search(r'\b('+'|'.join(months.keys())+r')\s+(20\d{2})\b',headline)
        if not mm:raise SourceError('Mois de ventes non identifié')
        m,y=months[mm.group(1)],int(mm.group(2))
        period={'annee':y,'mois':m,'periode_label':f'{mm.group(1).upper()} {y}'}
    # Section seulement, avant les commentaires et les recommandations.
    sections=[h for h in soup.find_all(['h2','h3']) if 'meilleures ventes bdfugue' in fold(h.get_text(' ',strip=True))]
    if not sections:raise SourceError('Section classée introuvable')
    section=sections[0]
    pieces=[]
    for node in section.next_elements:
        if getattr(node,'name',None) in ('h2','h3') and node is not section:
            if fold(node.get_text(' ',strip=True)).startswith(('commentaire','captainmdcu','derniere','nous soutenir','la redac')):break
        if isinstance(node,str):pieces.append(node.strip())
        if len(pieces)>2500:break
    raw='\n'.join(x for x in pieces if x)
    markers=list(re.finditer(r'(?m)^\s*#\s*([1-9]\d?)\s*$',raw))
    expected=5 if cadence=='HEBDO' else 7
    rows=[]
    for k,m in enumerate(markers):
        rank=int(m.group(1))
        if rank>expected:continue
        chunk=raw[m.end():markers[k+1].start() if k+1<len(markers) else len(raw)]
        lines=[x.strip() for x in chunk.splitlines() if x.strip()]
        if not lines:continue
        title=lines[0]
        if len(title)>220 or len(title)<3:continue
        publisher=next((p for p in PUBLISHERS if any(fold(p)==fold(x.strip('- :')) for x in lines[:18])), '')
        # Les maisons moins connues peuvent apparaître à la même place après
        # la date de sortie et les notes. Ne pas interpréter un résumé comme éditeur.
        if not publisher:
            for j,x in enumerate(lines[:8]):
                if re.match(r'^\d{2}/\d{2}/20\d{2}',x):
                    for candidate in lines[j+1:j+4]:
                        candidate=candidate.strip('- :')
                        if re.search(r'\bnote\b',fold(candidate)):continue
                        if 3<=len(candidate)<=40 and len(candidate.split())<=5 and not re.search(r'\d|€|\.',candidate):
                            publisher=candidate;break
                    break
        cover=locate_cover(soup,title,url)
        rows.append({'rang':rank,'titre':title,'editeur':publisher,
            'couverture_candidate_url':cover,'couverture_reference':title,
            'preuve_genre':'mdcu_palmares_comics','source_url':url})
    rows=sorted(rows,key=lambda x:x['rang'])
    if [b['rang'] for b in rows]!=list(range(1,expected+1)):
        raise SourceError(f'Classement MDCU incomplet: {len(rows)}/{expected} rangs')
    if len({normal(r['titre']) for r in rows})!=expected:raise SourceError('Rangs ou titres dupliqués')
    data={'categorie':'COMICS','cadence':cadence,'mode_interne':'MDCU_HEBDO' if cadence=='HEBDO' else 'MDCU_MENSUEL',
          'source':'MDCU / BDFugue','url_source':url,'date_article':published.isoformat(),
          'titres':rows,'variations_verifiees':False,**period}
    if cadence=='HEBDO':data['edition']=f'COMICS_HEBDO_{period["annee"]}_W{period["semaine"]:02d}'
    else:data['edition']=f'COMICS_MENSUEL_{period["annee"]}_{period["mois"]:02d}'
    return data

def parse_monthly_bdfugue(html,*,as_of):
    """Source optionnelle réellement sur 30 jours, au relevé d'un mois nouveau.
    La source ne répondait pas depuis GitHub (403) lors des essais utilisateur.
    """
    from comics_sources_hebdo import parse_bdfugue
    rows=parse_bdfugue(html,min_count=7)[:7]
    # Pas de mois calendaire inventé: c'est un relevé glissant à date exacte.
    previous=(as_of.replace(day=1)-dt.timedelta(days=1))
    titles=[]
    for i,b in enumerate(rows,1):titles.append({**b,'rang':i,'preuve_genre':'bdfugue_rubrique_comics'})
    return {'categorie':'COMICS','cadence':'MENSUEL','mode_interne':'BDFUGUE_30J',
            'edition':f'COMICS_MENSUEL_{previous:%Y_%m}',
            'source':'BDFugue, 30 jours glissants','url_source':BDFUGUE_CHART,
            'periode_label':f'30 DERNIERS JOURS • RELEVÉ LE {as_of:%d/%m/%Y}',
            'date_releve':as_of.isoformat(),'annee':previous.year,'mois':previous.month,
            'titres':titles,'variations_verifiees':False}

def collect_one(cadence,*,now=None,fetcher=fetch):
    if cadence not in ('HEBDO','MENSUEL'):raise ValueError('cadence inconnue')
    now=now or dt.datetime.now(ZoneInfo('Europe/Paris'))
    today=now.astimezone(ZoneInfo('Europe/Paris')).date();errors=[]
    if cadence=='MENSUEL' and today.day>10:raise SourceError('Mensuel: vérification seulement les 10 premiers jours du mois')
    urls=[]
    for listing in (MDCU_INDEX,MDCU_NEWS):
        try:
            for candidate in article_urls(fetcher(listing),listing,cadence):
                if candidate not in urls:urls.append(candidate)
        except (requests.RequestException,SourceError) as exc:errors.append(f'Index MDCU: {str(exc)[:110]}')
    for url in urls[:12]:
        try:
            data=parse_mdcu_article(fetcher(url),url,cadence=cadence)
            date=dt.date.fromisoformat(data['date_article'])
            if cadence=='HEBDO':
                if not 0<=(today-date).days<=9:continue
            else:
                last= (today.replace(day=1)-dt.timedelta(days=1))
                if (data['annee'],data['mois'])!=(last.year,last.month):continue
                if not -1<=(date-last).days<=13:continue
            return data,{'source_principale':url,'echelle':'ventes dune enseigne francaise','mode_interne':data['mode_interne'],'erreurs_sources':errors}
        except (SourceError,requests.RequestException,ValueError) as exc:errors.append(f'MDCU {url}: {str(exc)[:160]}')
    if cadence=='MENSUEL':
        # Dernier recours seulement si le palmarès comporte une fenêtre de 30 jours attestée.
        try:
            html=fetcher(BDFUGUE_CHART)
            data=parse_monthly_bdfugue(html,as_of=today)
            return data,{'source_principale':BDFUGUE_CHART,'echelle':'ventes 30 jours enseigne','mode_interne':'BDFUGUE_30J','erreurs_sources':errors}
        except (SourceError,requests.RequestException,ValueError) as exc:errors.append('BDFugue 30 jours: '+str(exc)[:160])
    raise SourceError('Aucun classement '+cadence+' exploitable; '+' ; '.join(errors[:7]))
