"""Nouveaux candidats UNIQUEMENT depuis des fiches éditeur structurées.
Pas d'IA externe, pas d'inférence narrative: les champs sont cités et archivés.
Une panne du web n'empêche pas l'utilisation de la banque historique sourcée.
"""
from __future__ import annotations
import datetime as dt,hashlib,json,re,time
from pathlib import Path
from urllib.parse import urljoin,urlparse,urldefrag
from bs4 import BeautifulSoup
import requests
from .catalogue import ROOT,STATE,CONFIG,SOURCES,read,write,valid_url,normalized,valid_fact

UA='AgentEditorialBD/1.0 (+usage raisonnable; contact via repository GitHub)'

PUBLISHERS={'www.dargaud.com','www.dupuis.com','www.urban-comics.com','www.editions-delcourt.fr'}

def html_get(url,session,timeout=12):
    if not valid_url(url):raise ValueError('Domaine interdit')
    response=session.get(url,headers={'User-Agent':UA},timeout=timeout,allow_redirects=False)
    if response.status_code in (301,302,303,307,308):
        dest=urljoin(url,response.headers.get('Location',''))
        if not valid_url(dest):raise ValueError('Redirection hors source primaire')
        response=session.get(dest,headers={'User-Agent':UA},timeout=timeout,allow_redirects=False)
    response.raise_for_status()
    if 'text/html' not in response.headers.get('Content-Type','').lower():raise ValueError('Pas HTML')
    if len(response.content)>2_000_000:raise ValueError('Page trop volumineuse')
    return response.text

def candidate_links(soup,base):
    host=urlparse(base).hostname
    out=[]
    for a in soup.select('a[href]'):
        href=urldefrag(urljoin(base,a['href']))[0].split('?')[0]
        p=urlparse(href)
        if p.hostname!=host or not valid_url(href):continue
        path=p.path.lower()
        if host=='www.urban-comics.com':
            ok=bool(re.fullmatch(r'/[a-z0-9-]+-tome-[0-9]+/',path))
        elif host=='www.dargaud.com':
            ok=path.startswith('/bd/') and len(path.split('/'))>=4
        elif host=='www.dupuis.com':
            ok=path.startswith('/bd/') or ('/bd/' in path)
        else:
            ok='/album-' in path
        if ok and href not in out:out.append(href)
    return out

def _ld_books(soup):
    records=[]
    for s in soup.find_all('script',type='application/ld+json'):
        try:blob=json.loads(s.string or s.get_text())
        except (ValueError,TypeError):continue
        nodes=blob if isinstance(blob,list) else [blob]
        for obj in nodes:
            if isinstance(obj,dict) and isinstance(obj.get('@graph'),list):nodes.extend(obj['@graph'])
            if isinstance(obj,dict) and 'Book' in str(obj.get('@type','')):records.append(obj)
    return records

def _text(soup):
    for tag in soup(['script','style','noscript']):tag.decompose()
    return ' '.join(soup.stripped_strings)

def structured_fact(url,html,stamp=None):
    """Aucune anecdote générée sur une phrase libre. Exige 3 faits structurés."""
    if not valid_url(url) or urlparse(url).hostname not in PUBLISHERS:return None
    soup=BeautifulSoup(html,'html.parser')
    h1=soup.find('h1')
    title=h1.get_text(' ',strip=True) if h1 else ''
    if not (6<=len(title)<=90):return None
    books=_ld_books(soup)
    plain=_text(soup)
    if len(plain)<150:return None
    # Les valeurs structurées sont prises de la fiche officielle, jamais d'un moteur IA.
    date_text=None;pages=None;creator=None
    for item in books:
        name=item.get('name')
        if isinstance(name,str) and normalized(name) in normalized(title):
            d=item.get('datePublished') or item.get('dateCreated')
            if isinstance(d,str):date_text=d[:10]
            p=item.get('numberOfPages')
            if isinstance(p,int) and 24<=p<=1200:pages=p
            author=item.get('author')
            if isinstance(author,list):author=author[0] if author else None
            creator=author.get('name') if isinstance(author,dict) else author if isinstance(author,str) else None
    # Urban: les informations sont exposées par la fiche elle-même.
    if not pages:
        m=re.search(r'Pagination\s*[:：]?\s*(\d{2,4})\s*pages',plain,re.I)
        if m and 24<=int(m.group(1))<=1200:pages=int(m.group(1))
    if not date_text:
        month={'janvier':1,'février':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12}
        m=re.search(r'Date de sortie\s*[:：]?\s*(\d{1,2})\s+(\w+)\s+(20\d{2})',plain,re.I)
        if m and m.group(2).lower() in month:
            try:date_text=dt.date(int(m.group(3)),month[m.group(2).lower()],int(m.group(1))).isoformat()
            except ValueError:pass
    if not creator:
        m=re.search(r'scénariste\s*[:：]?\s*([A-ZÀ-Ý][^:]{4,55}?)\s+(?:dessinateurs?|traducteur|Date de sortie)',plain,re.I)
        if m:creator=m.group(1).strip(' ,;-')
    if not(pages and date_text and creator):return None
    try:published=dt.date.fromisoformat(date_text)
    except (TypeError,ValueError):return None
    if published.year<1900 or published>dt.date.today()+dt.timedelta(days=400):return None
    creator=re.sub(r'\s+',' ',str(creator)).strip()
    if len(creator)>70 or len(creator)<3:return None
    fid='edition-'+hashlib.sha256((url+'|'+date_text).encode()).hexdigest()[:18]
    fact={
      'id':fid,'theme':'EDITION','url_source':url,'hook':f'{title[:60]} : trois détails !',
      'fait':f'Cette édition de « {title} » compte {pages} pages.',
      'contexte':f'Sa fiche officielle indique une date de parution au {published.strftime("%d/%m/%Y")}.',
      'detail':f'Elle mentionne également {creator} parmi les auteurs.',
      'preuve_courte':f'{title} — {pages} pages — {date_text} — {creator}'[:350],
      'question':'Tu connaissais cette édition ?',
      'type_preuve':'METADONNEES_EDITEUR_OFFICIEL',
      'controle_editorial':'EXTRACTION_STRUCTUREE_AUTOMATIQUE',
      'empreinte_page_sha256':hashlib.sha256(html.encode('utf8')).hexdigest(),
      'controle_date_utc':stamp or dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return fact if valid_fact(fact) else None

def discover(session=None,*,limit=None,now=None):
    session=session or requests.Session()
    now=now or dt.datetime.now(dt.timezone.utc)
    # Les contrôles Buffer sont fréquents, pas la lecture des sites éditeurs.
    last=read(STATE/'collecte_rapport.json',{}) or {}
    if last.get('controle_date_utc'):
        try:
            previous=dt.datetime.fromisoformat(last['controle_date_utc'])
            if previous.tzinfo and now-previous<dt.timedelta(hours=20):
                return {**last,'rapport_reutilise':True}
        except (TypeError,ValueError):pass
    cfg=CONFIG['collecte'];max_pages=limit or cfg['max_pages_par_execution']
    errors=[];saved=[];seen=set();pages=0
    cached=(read(STATE/'decouvertes.json',{}) or {}).get('faits',[])
    ids={r['id'] for r in cached if isinstance(r,dict) and 'id' in r}
    for portal in SOURCES['points_entree_decouverte']:
        if pages>=max_pages or len(saved)>=cfg['max_nouveaux_faits']:break
        try:
            content=html_get(portal,session,cfg['timeout_secondes']);pages+=1
            links=candidate_links(BeautifulSoup(content,'html.parser'),portal)[:cfg['max_liens_par_source']]
        except Exception as exc:
            errors.append(f'{urlparse(portal).hostname}: {type(exc).__name__}');continue
        for url in links:
            if pages>=max_pages or len(saved)>=cfg['max_nouveaux_faits']:break
            if url in seen:continue
            seen.add(url)
            try:
                body=html_get(url,session,cfg['timeout_secondes']);pages+=1
                fact=structured_fact(url,body,now.isoformat())
                if fact and fact['id'] not in ids:
                    saved.append(fact);ids.add(fact['id'])
            except Exception as exc:
                errors.append(f'{urlparse(url).hostname}: {type(exc).__name__}')
            time.sleep(.2)
    if saved:write(STATE/'decouvertes.json',{'faits':cached+saved})
    report={'pages_consultees':pages,'nouveaux_faits':len(saved),'total_decouvertes':len(cached)+len(saved),'erreurs':errors[:40],
            'controle_date_utc':now.isoformat()}
    write(STATE/'collecte_rapport.json',report)
    return report
