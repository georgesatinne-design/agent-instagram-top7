"""Veille publique, limitée, en lecture seule. Aucun scraping Instagram.
Les formats constatés sur les sites éditoriaux ne prouvent pas leur efficacité
sur Instagram. Seuls les signaux agrégés sont conservés.
"""
from __future__ import annotations
import datetime as dt,re,unicodedata,urllib.robotparser
from urllib.parse import urlparse
from collections import Counter
import requests
from bs4 import BeautifulSoup
UA='IllyaderaEditorialWatch/1.0'
SOURCES={
 'Bubble BD':('https://www.bubblebd.com/9emeart/bd','lectures'),
 'Bubble Manga':('https://www.bubblebd.com/9emeart/mangas','manga'),
 'ActuaBD':('https://www.actuabd.com/','actualites'),
 'Manga-news':('https://www.manga-news.com/','manga'),
 'Comicsblog':('https://www.comicsblog.fr/','comics'),
}
PATTERNS={
 'selection':r'\b(top|meilleurs?|meilleures?|selection|incontournables?|albums? (?:les plus )?attendus?|conseils?)\b',
 'analyse':r'\b(dossiers?|critiques?|chroniques?|analyses?|decryptage|edito)\b',
 'entretien':r'\b(interviews?|entretiens?|rencontres?)\b',
 'actualite':r'\b(actualites?|news|nouveautes?|sorties?|annonce[rs]?|lancement)\b',
 'video':r'\b(videos?|podcasts?|bandes?[- ]annonces?)\b',
 'curiosite':r'\b(secrets?|anecdotes?|saviez|origine[s]?|histoire)\b',
}
def normalized(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))
def counts(html):
    soup=BeautifulSoup(html,'html.parser');seen=set();result=Counter()
    # Avoid treating navigation, footer or repeated menu labels as posts.
    for section in soup.select('nav,header,footer,aside,script,style'):section.decompose()
    for h in soup.select('h1,h2,h3,h4'):
        title=' '.join(h.stripped_strings)
        if not 22<=len(title)<=240:continue
        title=normalized(title)
        if title in seen:continue
        seen.add(title)
        for k,p in PATTERNS.items():
            if re.search(p,title):result[k]+=1
        if len(seen)>=40:break
    return len(seen),dict(result)
def bounded_get(session,url,limit):
    with session.get(url,headers={'User-Agent':UA},timeout=(5,10),stream=True,allow_redirects=False) as r:
        status=r.status_code
        if status!=200:return status,b''
        body=bytearray()
        for chunk in r.iter_content(16384):
            body.extend(chunk)
            if len(body)>limit:raise ValueError('Réponse trop grande')
        return status,bytes(body)
def observe(session,name,url,domain):
    u=urlparse(url);root=u.scheme+'://'+u.netloc
    status,robots=bounded_get(session,root+'/robots.txt',200000)
    if status==200:
        rp=urllib.robotparser.RobotFileParser();rp.parse(robots.decode('utf8','replace').splitlines())
        if not rp.can_fetch(UA,url):return {'source':name,'url':url,'segment':domain,'etat':'ROBOTS_INTERDIT'}
    elif status not in (404,410):return {'source':name,'url':url,'segment':domain,'etat':'ROBOTS_NON_VERIFIABLE'}
    status,html=bounded_get(session,url,2_500_000)
    if status!=200:return {'source':name,'url':url,'segment':domain,'etat':'HTTP_'+str(status)}
    n,features=counts(html)
    return {'source':name,'url':url,'segment':domain,'etat':'OBSERVE' if n else 'NON_LISIBLE','titres_analyses':n,'formats_visibles':features}
def collect_watch():
    results=[]
    with requests.Session() as session:
        for name,(url,domain) in SOURCES.items():
            try:results.append(observe(session,name,url,domain))
            except (requests.RequestException,ValueError) as exc:results.append({'source':name,'url':url,'segment':domain,'etat':'INDISPONIBLE','cause':type(exc).__name__})
    observed=[r for r in results if r['etat']=='OBSERVE']
    totals=Counter()
    for r in observed:totals.update(r['formats_visibles'])
    return {'date':dt.date.today().isoformat(),'etat':'OBSERVATIONS_PUBLIQUES' if observed else 'INDISPONIBLE',
            'sources_observees':len(observed),'sources':results,'formats_visibles':dict(totals),
            'limites':'Pages éditoriales publiques, pas de statistiques privées, pas de prétention à mesurer la performance Instagram des concurrents.',
            'positionnement':'Découvrir, comprendre et choisir ses lectures BD, manga et comics. Des faits sourcés, des classements avec périmètre exact et des récits courts originaux.',
            'pistes': [{'format':'classements','objectif':'aide au choix et enregistrement'},
                       {'format':'actus','objectif':'sélection utile, diversité et source explicite'},
                       {'format':'reels','objectif':'curiosité, révélation rapide et partage'},
                       {'format':'anecdotes','objectif':'récit précis et mémorable'}]}
