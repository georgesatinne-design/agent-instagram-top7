"""Collecte gratuite, bornée, avec attribution et contrôle de fraîcheur.
Les titres automatiques sont présentés comme des titres de presse, pas comme
des résumés rédigés par un journaliste. Aucune image distante n'est republiée.
"""
import datetime as dt
import json
import re
import unicodedata
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse,urljoin,urldefrag
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
SOURCES={
 'www.acbd.fr':('ACBD',True,'https://www.acbd.fr/category/actualites/','https://www.acbd.fr/feed/'),
 'www.citebd.org':('Cité internationale de la BD',True,'https://www.citebd.org/agenda',None),
 'www.palais-portedoree.fr':('Palais de la Porte Dorée',True,'https://www.palais-portedoree.fr/actualites',None),
 'actualitte.com':('ActuaLitté',False,'https://actualitte.com/','https://actualitte.com/rss-main.rss'),
 'www.actuabd.com':('ActuaBD',False,'https://www.actuabd.com/','https://www.actuabd.com/spip.php?page=backend'),
 'www.comicsblog.fr':('COMICSBLOG',False,'https://www.comicsblog.fr/news',None),
 'www.lemonde.fr':('Le Monde',False,'https://www.lemonde.fr/bande-dessinee/','https://www.lemonde.fr/bande-dessinee/rss_full.xml'),
}
UA='Illyadera/1.0 (https://github.com/georgesatinne-design/agent-instagram-top7)'
def fold(s):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c)).split())
def clean(s):return ' '.join(BeautifulSoup(str(s),'html.parser').stripped_strings)
def allowed(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname in SOURCES and not p.username and not p.password and p.port in (None,443)
def fetch(url,session):
    if not allowed(url):raise ValueError('Domaine non autorisé')
    # No arbitrary redirect or paywall bypass.
    r=session.get(url,headers={'User-Agent':UA},timeout=12,allow_redirects=False,stream=True)
    try:
        r.raise_for_status()
        if r.status_code!=200:raise ValueError('Redirection ou réponse non exploitable')
        chunks=[];size=0
        for b in r.iter_content(65536):
            size+=len(b)
            if size>3_000_000:raise ValueError('Page trop volumineuse')
            chunks.append(b)
        return b''.join(chunks).decode(r.encoding or 'utf8',errors='replace')
    finally:r.close()
def date_value(s):
    if not s:return None
    try:return dt.date.fromisoformat(s[:10])
    except (ValueError,TypeError):pass
    try:return parsedate_to_datetime(s).date()
    except (ValueError,TypeError,OverflowError):return None
def theme(title,host):
    s=fold(title)
    if re.search(r'\b(rumeur|leak|scoop|pourrait|suppose|teaser|bande-annonce|critique de|chronique|promo|concours|meilleures ventes|top 10|top 100|trailer|disparition|accuse|scandale)\b',s) or '?' in s:return None
    if host not in ('www.acbd.fr','www.citebd.org','www.actuabd.com','www.comicsblog.fr') and not re.search(r'\b(bd|bande dessinee|manga|mangas|comics|roman graphique)\b',s):return None
    for name,pattern in [
        ('PRIX',r'\b(prix|laureat|laureate|finalistes|recompense|palmares)\b'),
        ('EXPOSITION',r'\b(exposition|retrospective|musee)\b'),
        ('FESTIVAL',r'\b(festival|salon|biennale)\b'),
        ('LIBRAIRIES',r'\b(librairie|librairies|repreneur)\b'),
        ('ÉDITION',r'\b(editeur|editeurs|edition|editions|publiera|publie|publication|reedition|integrale|nouvelle serie)\b'),
        ('PATRIMOINE',r'\b(archives|patrimoine|bibliotheque|collection|donation)\b'),
        ('CRÉATION',r'\b(auteur|autrice|dessinateur|dessinatrice|scenariste|adaptation)\b')]:
        if re.search(pattern,s):return name
    return None
def links(html,base):
    soup=BeautifulSoup(html,'html.parser')
    out=[]
    for a in soup.select('article a[href], main h2 a[href], main h3 a[href], h2 a[href], h3 a[href]'):
        url=urldefrag(urljoin(base,a['href']))[0].split('?')[0]
        t=clean(a.get_text(' ',strip=True))
        if allowed(url) and urlparse(url).hostname==urlparse(base).hostname and url!=base and 20<=len(t)<=170 and theme(t,urlparse(url).hostname):
            if url not in out:out.append(url)
    return out[:10]
def rss(html,base):
    # BeautifulSoup HTML parser tolerates malformed RSS; link text in XML
    # is parsed explicitly with ElementTree (no external entity resolution).
    import xml.etree.ElementTree as ET
    try:root=ET.fromstring(html)
    except ET.ParseError:return []
    out=[]
    for item in root.findall('.//item'):
        url=(item.findtext('link') or '').strip();t=clean(item.findtext('title') or '')
        day=date_value(item.findtext('pubDate'))
        if allowed(url) and urlparse(url).hostname==urlparse(base).hostname and day and theme(t,urlparse(url).hostname):
            out.append((url,day))
    return out[:15]
def article(html,url,fallback_date=None):
    soup=BeautifulSoup(html,'html.parser')
    def meta(key):
        m=soup.find('meta',attrs={'property':key}) or soup.find('meta',attrs={'name':key})
        return (m.get('content') or '') if m else ''
    h=soup.find('h1')
    title=clean(meta('og:title') or (h.get_text(' ',strip=True) if h else ''))
    day=date_value(meta('article:published_time') or meta('datePublished'))
    if not day:
        for script in soup.find_all('script',type='application/ld+json'):
            try:
                obj=json.loads(script.string or '{}')
                rows=obj if isinstance(obj,list) else obj.get('@graph',[obj])
                for x in rows:
                    if isinstance(x,dict) and x.get('datePublished'):day=date_value(x['datePublished']);break
            except (ValueError,TypeError,AttributeError):pass
            if day:break
    if not day:
        for tag in soup.select('article time[datetime], main time[datetime]'):
            day=date_value(tag.get('datetime')); 
            if day:break
    day=day or fallback_date
    host=urlparse(url).hostname;kind=theme(title,host)
    if not kind or not day or not 22<=len(title)<=145 or len(title.split())>22:return None
    # Explicitly labelled short attributed title, no invented article details.
    context={'PRIX':'Les distinctions et sélections qui mettent les albums et leurs auteurs en lumière.',
      'EXPOSITION':'Une piste pour découvrir la bande dessinée au-delà de la lecture des albums.',
      'FESTIVAL':'Un rendez-vous à suivre dans le calendrier des passionnés.',
      'LIBRAIRIES':'Une information sur les lieux qui font vivre la lecture et la BD.',
      'ÉDITION':'Une annonce à suivre du côté des auteurs, des albums et des maisons d’édition.',
      'PATRIMOINE':'Une actualité autour de la transmission et de la conservation du neuvième art.',
      'CRÉATION':'Un éclairage sur les personnes et les projets qui font évoluer la bande dessinée.'}
    return dict(title=title,body=context[kind],theme=kind,source=SOURCES[host][0],url=url,date=day.isoformat(),official=SOURCES[host][1],quote=True)
def select(items,day,used=()):
    chosen=[];counts={};themes={};seen=set(used)
    def words(s):return set(re.findall(r'[a-z0-9]{4,}',fold(s)))-{'dans','pour','avec','bande','dessinee','manga','comics','nouvelle','prix','edition','2026','2027'}
    def rank(x):return (not x.get('official',False),-dt.date.fromisoformat(x['date']).toordinal(),x['url'])
    for x in sorted(items,key=rank):
        if not allowed(x['url']) or x['url'] in seen:continue
        age=(day-dt.date.fromisoformat(x['date'])).days
        if age<0 or age>14:continue
        if x.get('event') and dt.date.fromisoformat(x['event'])<day:continue
        if counts.get(x['source'],0)>=2 or themes.get(x['theme'],0)>=2:continue
        w=words(x['title'])
        if any(len(w&words(y['title']))>=2 and len(w&words(y['title']))/max(1,min(len(w),len(words(y['title']))))>=0.65 for y in chosen):continue
        chosen.append(x);seen.add(x['url']);counts[x['source']]=counts.get(x['source'],0)+1;themes[x['theme']]=themes.get(x['theme'],0)+1
        if len(chosen)==5:break
    if len(chosen)!=5 or len(counts)<3:raise RuntimeError('Moins de cinq sujets fiables et diversifiés : aucune actualité inventée')
    return chosen
def collect(day,*,used=(),session=None):
    session=session or requests.Session()
    seed=json.loads((ROOT/'premier_numero.json').read_text(encoding='utf8'))
    if day.isoformat()==seed['edition']:
        # First issue individually researched from the named original pages.
        # Revalidate each URL/anchors if accessible; verified seed persists even
        # if a temporary network failure prevents a fresh read.
        for x in seed['items']:
            x['official']=SOURCES[urlparse(x['url']).hostname][1]
        return select(seed['items'],day,used)
    items=[];errors=[]
    for host,(source,official,index,feed) in SOURCES.items():
        candidates={}
        if feed:
            try:candidates.update(rss(fetch(feed,session),feed))
            except (requests.RequestException,ValueError):pass
        try:
            for url in links(fetch(index,session),index):candidates.setdefault(url,None)
        except (requests.RequestException,ValueError):pass
        for url,day_hint in list(candidates.items())[:8]:
            if url in used or (day_hint and not 0<=(day-day_hint).days<=14):continue
            try:
                item=article(fetch(url,session),url,day_hint)
                if item:items.append(item)
            except (requests.RequestException,ValueError,KeyError):continue
    return select(items,day,used)
