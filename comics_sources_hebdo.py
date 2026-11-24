"""Sources COMICS — collecte prudente, deux modes de provenance distincts.

NATIONAL_HEBDO : Top200 Edistat du lundi au dimanche; sept comics identifiés
                   par les références et/ou catalogues, sans mélanger les rangs.
RELEVE_ENSEIGNE : classement de meilleures ventes comics sur Fnac, relevé
                   cette semaine; ne prétend PAS être un classement national ni
                   mesurer exactement les sept derniers jours.

Aucune information n'est inventée pour remplir un Top 7. Tout URL utilisé est
public, HTTPS, explicitement autorisé. Les diagnostics mentionnent les sources
uniquement dans les artefacts privés de GitHub.
"""
from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urljoin,urlparse
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from manga_sources_hebdo import (ACTUALITTE_INDEX, BEDE, EvidenceError,
    latest_article_urls,parse_top200,parse_bede_current,pub_date,_period_for_article,
    match_titles,norm)

FNAC='https://www.fnac.com/l36505/Meilleures-ventes-Comics/Comics/BD-et-Humour'
BDFUGUE='https://www.bdfugue.com/meilleures-ventes/comics'
MDCU='https://www.mdcu-comics.fr/'
HTTP_HEADERS={'User-Agent':'Mozilla/5.0 (compatible; ComicsHebdoFrance/1.0; collecte de palmares publics)'}
COMIC_LABELS=('urban comics','panini comics','huginn','hi comics','delcourt comics',
              'bliss comics','404 comics','komics initiative','black river','akileos',
              'vestron','graph zeppelin','label 619')
US_FRANCHISES=('batman','superman','wonder woman','absolute ','spider man','spiderman',
    'avengers','x men','venom','hellboy','bprd','conan','spawn','hulk','thor','deadpool',
    'daredevil','fantastic four','quatre fantastiques','iron man','wolverine',
    'harley quinn','green lantern','nightwing','flash','martian manhunter',
    'invincible','walking dead','saga','sandman','transmetropolitan','tmnt',
    'tortues ninja','justice league','moon knight','punisher','star wars',
    'conan le barbare','locke key','hellblazer','doom wars','little nightmares',
    'lady mechanika','godzilla','watchmen','cyberpunk 2077')

class CollectError(EvidenceError): pass

def fetch(url,*,getter=requests.get,allowed=('www.fnac.com','fnac.com','actualitte.com',
        'www.actualitte.com','bede.fr','www.bede.fr','www.mdcu-comics.fr','mdcu-comics.fr',
        'www.bdfugue.com','bdfugue.com','api.bdfugue.com')):
    target=urlparse(url)
    if target.scheme!='https' or target.hostname not in allowed:raise CollectError('URL source non autorisée')
    r=getter(url,headers=HTTP_HEADERS,timeout=28,allow_redirects=True)
    r.raise_for_status()
    final=urlparse(getattr(r,'url',url))
    if final.scheme!='https' or final.hostname not in allowed:raise CollectError('Redirection vers un site non approuvé')
    if len(r.content)>7_500_000:raise CollectError('Page trop volumineuse')
    return r.text

def week_bounds(date:dt.date) -> tuple[str,str]:
    a=date-dt.timedelta(days=date.weekday())
    return a.isoformat(),(a+dt.timedelta(days=6)).isoformat()

def validate_cover_url(u:str)->str:
    p=urlparse(u or '')
    if p.scheme=='https' and (p.hostname in ('static.fnac-static.com','cdn.bede.fr') or
        (p.hostname and (p.hostname=='bdfugue.com' or p.hostname.endswith('.bdfugue.com')))):
        return u
    return ''

def _img_src(img):
    if img is None:return ''
    for field in ('data-src','data-original','data-lazy-src','src'):
        s=img.get(field) or ''
        if s.startswith('//'):s='https:'+s
        if validate_cover_url(s):return s
    srcset=img.get('data-srcset') or img.get('srcset') or ''
    for entry in srcset.split(','):
        s=entry.strip().split(' ')[0]
        if s.startswith('//'):s='https:'+s
        if validate_cover_url(s):return s
    return ''

def _fnac_card_data(node):
    """Interprète un seul produit, jamais un conteneur entier de liste.

    Repère les métadonnées produit 'Type Comics' et 'Editeur'. Sans indication
    de type, le produit ne constitue PAS une preuve comics.
    """
    text=' '.join(node.stripped_strings)
    if len(text)>5000 or not re.search(r'\bType\s+Comics\b',text,re.I):return None
    if re.search(r'\bFormat\s+(?:eBook|ePub|num[ée]rique)\b',text,re.I):return None
    pub=re.search(r'\bEditeur\s+(.{2,75}?)(?:\s+Parution\b|\s+En stock\b|$)',text,re.I)
    publisher=(pub.group(1).strip() if pub else '')
    if not publisher:return None
    links=[a for a in node.find_all('a',href=True)
           if re.search(r'^/a\d+|fnac\.com/a\d+',a['href'])]
    if not links:return None
    # Lien primaire avec texte livre, pas la marque ou l'avis client.
    a=next((x for x in links if len(x.get_text(' ',strip=True))>=8),None)
    if a is None:a=links[0]
    title=a.get_text(' ',strip=True)
    imgs=node.find_all('img')
    if len(title)<5:
        title=next((x.get('alt','') for x in imgs if len(x.get('alt',''))>8),'')
    if len(title)<5 or len(title)>230:return None
    url=urljoin(FNAC,a['href'])
    if urlparse(url).hostname not in ('www.fnac.com','fnac.com'):return None
    cover=''
    for im in imgs:
        cover=_img_src(im)
        if cover:break
    # Exclure des BD européennes / mangas parfois classés génériquement Comics
    # dans le catalogue, tout en acceptant les comics indépendants du bon label.
    n=norm(title+' '+publisher)
    is_comic=any(k in n for k in COMIC_LABELS) or any(k in norm(title) for k in US_FRANCHISES)
    if not is_comic:return None
    release=re.search(r'\bParution\s+(\d{2}/\d{2}/20\d{2})',text,re.I)
    return {'titre':title,'editeur':publisher,'url_produit':url,
            'couverture_candidate_url':cover,'couverture_reference':title,
            'date_sortie':release.group(1) if release else '',
            'preuve_genre':'rubrique_comics_et_licence_ou_label',
            'origine_classement':'FNAC'}

def parse_fnac(html:str,*,min_count=7)->list[dict]:
    """Conserve l'ordre d'affichage des produits du palmarès « Meilleures ventes Comics ».

    Les emplacements publicitaires, produits non-comics, ebooks et notices
    sans métadonnées produit sont ignorés. Aucun résultat n'est promu au rang
    national; les rangs décrivent un relevé de cette seule enseigne.
    """
    soup=BeautifulSoup(html,'html.parser')
    heading=next((x for x in soup.find_all(['h1','h2']) if 'meilleures ventes comics' in norm(x.get_text())),None)
    if heading is None:raise CollectError('Page Fnac sans titre palmarès comics')
    candidates=[]
    # En priorité les cartes produits, pour respecter exactement l'ordre DOM.
    for selector in ('article', 'li.Article-item', 'div.Article-item', 'div.productListArticle',
                     'div[class*="Article-item"]', 'div[class*="product-card"]'):
        nodes=soup.select(selector)
        found=[]
        for node in nodes:
            if len(node.get_text(' ',strip=True))>3500:continue
            info=_fnac_card_data(node)
            if info:found.append(info)
        if len({x['url_produit'] for x in found})>=min_count:
            candidates=found;break
    if len({x['url_produit'] for x in candidates})<min_count:
        # Repli : à partir des liens produit et de leur plus petit conteneur
        # présentant Type Comics et Editeur. Accepte de légères modifications HTML.
        found=[]
        for link in soup.select('a[href]'):
            if not re.search(r'^/a\d+|fnac\.com/a\d+',link.get('href','')):continue
            parent=link
            for _ in range(7):
                parent=parent.parent
                if parent is None or parent.name in ('body','html'):break
                raw=parent.get_text(' ',strip=True)
                if len(raw)>3500:break
                if re.search(r'\bType\s+Comics\b',raw,re.I) and re.search(r'\bEditeur\b',raw,re.I):
                    info=_fnac_card_data(parent)
                    if info:found.append(info)
                    break
        candidates=found
    unique=[];seen=set()
    for item in candidates:
        if item['url_produit'] in seen:continue
        seen.add(item['url_produit']);unique.append(item)
    if len(unique)<min_count:raise CollectError(f'Palmarès Fnac insuffisant : {len(unique)} fiches comics classées')
    for i,item in enumerate(unique,1):item['rang_enseigne']=i
    return unique[:30]

def parse_bdfugue(html:str,*,min_count=7)->list[dict]:
    """Top comics d'une enseigne, dans son ordre affiché (ventes 30 derniers jours).

    Ne prend que les cartes de la grille de produits; ne déduit jamais des rangs
    depuis les menus, recommandations ou prix. Le site peut changer son HTML:
    dans ce cas, on échoue explicitement plutôt que de publier un faux classement.
    """
    soup=BeautifulSoup(html,'html.parser')
    heading=next((h for h in soup.find_all(['h1','h2'])
                  if 'meilleures ventes comics' in norm(h.get_text(' ',strip=True))),None)
    if heading is None:raise CollectError('BDFugue : titre du Top comics introuvable')
    text=soup.get_text(' ',strip=True)
    if not re.search(r'30\s+derniers?\s+jours',text,re.I):
        raise CollectError('BDFugue : fenêtre de ventes (30 jours) non attestée')

    # Les templates Magento utilisent des cartes product-item dans une grille.
    selectors=(
        'ol.products.list.items.product-items > li.product-item',
        '.products-grid li.product-item',
        '.products-grid .product-item',
        'li.product-item',
        '.products-grid .product-item-info',
    )
    def extract(nodes):
        output=[]; seen=set()
        for node in nodes:
            a=node.select_one('a.product-item-link[href], h3.product-item-name a[href], h2.product-item-name a[href], a.product-item-photo[href]')
            if a is None:continue
            url=urljoin(BDFUGUE,a.get('href',''))
            parsed=urlparse(url)
            if parsed.scheme!='https' or parsed.hostname not in ('www.bdfugue.com','bdfugue.com') or parsed.path.startswith('/meilleures-ventes'):
                continue
            url=url.split('?',1)[0]
            if url in seen:continue
            title=a.get_text(' ',strip=True)
            if not title:
                name=node.select_one('.product-item-name')
                title=name.get_text(' ',strip=True) if name else ''
            img=node.select_one('img[alt]') or node.find('img')
            if not title and img is not None:title=img.get('alt','').strip()
            if not (5<=len(title)<=240):continue
            cover=_img_src(img)
            seen.add(url)
            output.append({'titre':title,'editeur':'','url_produit':url,
                'couverture_candidate_url':cover,'couverture_reference':title,
                'preuve_genre':'bdfugue_rubrique_comics',
                'origine_classement':'BDFUGUE'})
        return output
    candidates=[]
    for selector in selectors:
        candidates=extract(soup.select(selector))
        if len(candidates)>=min_count:break
    if len(candidates)<min_count:
        # Autre structure HTML : liste de produits uniquement sous la grille.
        for grid in soup.select('.products-grid, ol.product-items'):
            candidates=extract(grid.select('.product-item, .product-item-info'))
            if len(candidates)>=min_count:break
    if len(candidates)<min_count:
        raise CollectError(f'BDFugue : palmarès incomplet ({len(candidates)} produits reconnus)')
    for i,book in enumerate(candidates,1):book['rang_enseigne']=i
    return candidates[:30]


def parse_mdcu_top(html):
    soup=BeautifulSoup(html,'html.parser')
    headline=soup.find('h1')
    text=headline.get_text(' ',strip=True) if headline else ''
    if 'meilleures ventes comics bdfugue semaine' not in norm(text):
        raise CollectError('Article MDCU sans classement hebdomadaire clairement annoncé')
    result=[]
    for heading in soup.find_all(['h4','h5']):
        title=heading.get_text(' ',strip=True)
        if not title:continue
        # Les titres sont introduits par un marqueur #1..#5
        before=heading.find_previous(string=re.compile(r'^\s*#\s*[1-5]\s*$'))
        if not before:continue
        rank=int(re.search(r'\d',str(before)).group())
        if rank not in {x['rang'] for x in result}:
            result.append({'rang':rank,'titre':title})
    return sorted(result,key=lambda x:x['rang'])[:5]

def match_fnac_bede(top200:list[dict],bede_rows:list[dict],fnac_rows:list[dict]):
    """Extraction de rangs NATIONAUX seulement si les 7 peuvent être prouvés
    dans le même palmarès par une correspondance sans ambiguïté.
    """
    recognized=[]
    for book in top200:
        references=[]
        for x in bede_rows:
            if '/media/comics/' in x.get('cover_url','') and match_titles(book['titre_article'],x['alt']):
                references.append((x['alt'],x['cover_url'],'bede_categorie_comics'))
        for x in fnac_rows:
            if match_titles(book['titre_article'],x['titre']):
                references.append((x['titre'],x['couverture_candidate_url'],'fnac_categorie_comics'))
        if len(references)>1 and not all(match_titles(references[0][0],r[0]) for r in references[1:]):
            # Editions différentes ou correspondance contradictoire.
            continue
        if not references:continue
        ref,cover,proof=references[0]
        # Un vrai classement national ne mélange pas de classements de magasins.
        recognized.append({'titre':book['titre_article'],'editeur':next((x['editeur'] for x in fnac_rows if match_titles(book['titre_article'],x['titre'])),'Comics'),
            'ean':book['ean'],'rang_general_livres':book['rang_general'],
            'couverture_candidate_url':cover,'couverture_reference':ref,
            'preuve_genre':proof})
    recognized.sort(key=lambda x:x['rang_general_livres'])
    return recognized

def build_candidate(*,fnac_html=None,bdfugue_html=None,now=None,actualitte_html=None,bede_html=None,article_url=None,mdcu_html=None):
    now=now or dt.datetime.now(ZoneInfo('Europe/Paris'))
    day=now.astimezone(ZoneInfo('Europe/Paris')).date()
    fnac=[];bdfugue=[];errors=[]
    if fnac_html:
        try:fnac=parse_fnac(fnac_html)
        except CollectError as exc:errors.append('Fnac : '+str(exc))
    if bdfugue_html:
        try:bdfugue=parse_bdfugue(bdfugue_html)
        except CollectError as exc:errors.append(str(exc))
    # Le Top 200 national et les magasins ne sont pas fusionnés.
    evidence={'sources':{'fnac':FNAC if fnac else None,'bdfugue':BDFUGUE if bdfugue else None},
        'releve_le':day.isoformat(),'source_secondaire':None,'rangs_nationaux':0,
        'avertissements':errors}
    mdcu=[]
    if mdcu_html:
        try:mdcu=parse_mdcu_top(mdcu_html)
        except CollectError:pass
    evidence['comparaison_comics_bdfugue']=mdcu
    national=[];start=end=None
    if actualitte_html and bede_html:
        try:
            p=pub_date(actualitte_html)
            start,end=_period_for_article(actualitte_html,p)
            if (day-dt.date.fromisoformat(end)).days>10:
                raise CollectError('Top national moins récent que la fenêtre acceptée')
            rank=parse_top200(actualitte_html)
            bede=parse_bede_current(bede_html)['lignes']
            national=match_fnac_bede(rank,bede,fnac)
            evidence['sources'].update({'actuaLitte':article_url or ACTUALITTE_INDEX,'bede':BEDE})
            evidence['rangs_nationaux']=len(national)
        except (EvidenceError,KeyError,ValueError) as exc:
            evidence['avertissements'].append('Voie nationale non exploitable : '+str(exc)[:190])
    if len(national)>=7:
        mode='NATIONAL_HEBDO'
        selected=national[:7]
        for i,b in enumerate(selected,1):b['rang']=i
        display='DU '+dt.date.fromisoformat(start).strftime('%d/%m')+' AU '+dt.date.fromisoformat(end).strftime('%d/%m/%Y')
        edition='COMICS_'+end
        period={'debut_ventes':start,'fin_ventes':end,'date_palmares':None,'periode_label':display}
        merchant='NATIONAL'
    else:
        if not fnac and not bdfugue:
            raise CollectError('Aucun Top 7 comics exploitable dans les sources disponibles. '+' ; '.join(errors))
        # Palmarès d'enseigne (fenêtre de 30 jours pour BDFugue).
        # On ne prétend jamais avoir les sept meilleures ventes nationales de la semaine.
        mode='RELEVE_ENSEIGNE'
        merchant='BDFUGUE' if bdfugue else 'FNAC'
        base=bdfugue if bdfugue else fnac
        selected=[{**x,'rang':i} for i,x in enumerate(base[:7],1)]
        monday,sunday=week_bounds(day)
        edition='COMICS_'+sunday
        period={'date_palmares':day.strftime('%d/%m/%Y'),
                'periode_label':'RELEVÉ LE '+day.strftime('%d/%m/%Y')}
        evidence['avertissements'].append(
            'Relevé BDFugue, ventes sur 30 jours glissants; pas un Top national hebdomadaire'
            if bdfugue else
            'Relevé Fnac, période des ventes non publiée; pas un Top national hebdomadaire')
    data={'categorie':'COMICS','edition':edition,
          'perimetre':'Classement comics national hebdomadaire si 7 rangs attestés; sinon classement d’enseigne daté',
          'source':('ActuaLitté / Edistat' if mode=='NATIONAL_HEBDO' else
                    'BDFugue — 30 derniers jours' if merchant=='BDFUGUE' else
                    'Fnac — meilleures ventes comics'),
          'url_source':(article_url if mode=='NATIONAL_HEBDO' and article_url else
                        BDFUGUE if merchant=='BDFUGUE' else FNAC),
          'mode_interne':mode,'releve_source':merchant,'date_releve':day.isoformat(),
          'titres':selected,'variations_verifiees':False,
          'semaine_reference':list(week_bounds(day)),**period}
    evidence['mode_interne']=mode
    evidence['releve_source']=merchant
    return data,evidence

def collect_live(*,now=None,fetcher=fetch):
    """Chaque source est indépendante : un 403 Fnac ne bloque plus BDFugue.

    Ne tente ni proxy de contournement ni automatisation cachée des CAPTCHA.
    Si les sources publiques accessibles sont insuffisantes, ne programme rien.
    """
    now=now or dt.datetime.now(ZoneInfo('Europe/Paris'))
    failures=[];fnac=bdfugue=None
    for key,url in (('BDFugue',BDFUGUE),('Fnac',FNAC)):
        try:
            html=fetcher(url)
            if key=='BDFugue':
                parse_bdfugue(html)
                bdfugue=html
            else:
                parse_fnac(html)
                fnac=html
        except (CollectError,requests.RequestException,ValueError) as exc:
            failures.append(f'{key} : {str(exc)[:180]}')
    ahtml=bhtml=None;url=None
    try:
        index=fetcher(ACTUALITTE_INDEX)
        urls=latest_article_urls(index,limit=5)
        for candidate in urls:
            try:
                h=fetcher(candidate)
                p=pub_date(h);start,end=_period_for_article(h,p)
                age=(now.astimezone(ZoneInfo('Europe/Paris')).date()-dt.date.fromisoformat(end)).days
                if 0<=age<=10:
                    ahtml=h;url=candidate;break
            except (EvidenceError,requests.RequestException):continue
    except (EvidenceError,requests.RequestException) as exc:
        failures.append(f'ActuaLitté : {str(exc)[:180]}')
    if ahtml:
        try:bhtml=fetcher(BEDE)
        except (EvidenceError,requests.RequestException) as exc:
            failures.append(f'Bédé.fr : {str(exc)[:180]}')
    # Top5 de l'enseigne BDFugue publié par MDCU : recoupement seulement.
    mdcu_html=None
    try:
        listing=fetcher('https://www.mdcu-comics.fr/news')
        soup=BeautifulSoup(listing,'html.parser')
        urls=[]
        for a in soup.select('a[href]'):
            dest=urljoin(MDCU,a['href']);host=urlparse(dest).hostname
            if host in ('www.mdcu-comics.fr','mdcu-comics.fr') and 'meilleures-ventes-comics-bdfugue-semaine' in dest.lower():
                if dest not in urls:urls.append(dest)
        for dest in urls[:5]:
            try:
                candidate=fetcher(dest)
                if len(parse_mdcu_top(candidate))>=4:
                    m=re.search(r'\b(\d{2}/\d{2}/20\d{2})\b',
                        BeautifulSoup(candidate,'html.parser').get_text(' ',strip=True)[:550])
                    if m:
                        published=dt.datetime.strptime(m.group(1),'%d/%m/%Y').date()
                        if 0<=(now.astimezone(ZoneInfo('Europe/Paris')).date()-published).days<=10:
                            mdcu_html=candidate;break
            except (CollectError,requests.RequestException,ValueError):continue
    except (CollectError,requests.RequestException):pass
    try:
        data,evidence=build_candidate(fnac_html=fnac,bdfugue_html=bdfugue,
            actualitte_html=ahtml,bede_html=bhtml,article_url=url,mdcu_html=mdcu_html,now=now)
    except CollectError as exc:
        raise CollectError(str(exc)+' ; '+' ; '.join(failures)) from exc
    evidence['avertissements']+=failures
    return data,evidence
