"""Extension additive MANGA ; ne modifie ni les fichiers BD ni Buffer.

Source maîtresse: Top 200 hebdomadaire Edistat publié par ActuaLitté.
Contrôle: palmarès BD/manga/comics Edistat repris par Bédé.fr.
Référence indépendante, si accessible: top général NielsenIQ/Livres Hebdo.

Aucune donnée de ventes n'est fabriquée. Une extraction incomplète est refusée.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ACTUALITTE_INDEX = 'https://actualitte.com/thematique/70/meilleures-ventes'
BEDE = 'https://www.bede.fr/meilleures-ventes'
BEDE_MANGA = 'https://www.bede.fr/meilleurs-manga-2026'
LIVRES_HEBDO = 'https://www.livreshebdo.fr/meilleuresVentes'
ALLOWED = {'actualitte.com','www.actualitte.com','www.bede.fr','bede.fr','www.livreshebdo.fr','livreshebdo.fr'}
MONTHS = {n:i for i,n in enumerate('janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre'.split(),1)}
HEADERS = {'User-Agent':'ClassementMangaFrance/1.0 (controle de sources publiques, sans publication)'}

class EvidenceError(ValueError):
    pass

def norm(s):
    v=''.join(c for c in unicodedata.normalize('NFKD',str(s).casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+',v.replace('×','x')))

def get_html(url, *, getter=requests.get):
    u=urlparse(url)
    if u.scheme!='https' or u.hostname not in ALLOWED:
        raise EvidenceError('Adresse non autorisee pour la collecte')
    r=getter(url,headers=HEADERS,timeout=25,allow_redirects=True)
    r.raise_for_status()
    final=urlparse(getattr(r,'url',url))
    if final.scheme!='https' or final.hostname not in ALLOWED:
        raise EvidenceError('Redirection externe non autorisee')
    if len(r.content)>7_500_000:
        raise EvidenceError('Page trop volumineuse')
    return r.text

def pub_date(html):
    soup=BeautifulSoup(html,'html.parser')
    for meta in soup.select('meta[property="article:published_time"], meta[property="og:article:published_time"], meta[name="date"], time[datetime]'):
        value=meta.get('content') or meta.get('datetime') or ''
        m=re.search(r'(20\d{2})-(\d{2})-(\d{2})',value)
        if m:
            try:return dt.date(*map(int,m.groups()))
            except ValueError:pass
    # Texte courant « Le 20/11/2026 à 11:52 » dans l'introduction de l'article.
    start=soup.find('h1')
    text=' '.join(str(x).strip() for x in start.next_elements if isinstance(x,NavigableString))[:3500] if start else soup.get_text(' ',strip=True)[:3500]
    m=re.search(r'\b(?:Le\s+)?(\d{1,2})/(\d{1,2})/(20\d{2})\b',text)
    if m:
        day,month,year=map(int,m.groups())
        return dt.date(year,month,day)
    raise EvidenceError('Date de publication non prouvee')

def _explicit_period(s,year):
    """Lit une semaine explicite et complète, jamais une date de publication."""
    s=norm(s).replace('1er ', '1 ')
    month='|'.join(MONTHS)
    patterns=(
      rf'\bdu (\d{{1,2}}) au (\d{{1,2}}) ({month})(?: (20\d{{2}}))?\b',
      rf'\bdu (\d{{1,2}}) ({month}) au (\d{{1,2}}) ({month})(?: (20\d{{2}}))?\b',
    )
    answers=[]
    for pattern_index,pattern in enumerate(patterns):
        for match in re.finditer(pattern,s):
            try:
                if pattern_index==0:
                    first,last,month_name,explicit_year=match.groups()
                    year_end=int(explicit_year or year)
                    end=dt.date(year_end,MONTHS[month_name],int(last))
                    # Le début peut être le mois précédent si le titre concerne
                    # une semaine qui chevauche deux mois; jamais le deviner.
                    start=dt.date(year_end,MONTHS[month_name],int(first))
                else:
                    first,first_month,last,last_month,explicit_year=match.groups()
                    year_end=int(explicit_year or year)
                    end=dt.date(year_end,MONTHS[last_month],int(last))
                    year_start=year_end-(MONTHS[first_month]>MONTHS[last_month])
                    start=dt.date(year_start,MONTHS[first_month],int(first))
                if (end-start).days==6 and start.weekday()==0 and end.weekday()==6:
                    pair=(start.isoformat(),end.isoformat())
                    if pair not in answers: answers.append(pair)
            except (ValueError,TypeError):
                pass
    return answers

def _period_for_article(html, publication):
    soup=BeautifulSoup(html,'html.parser')
    h1=soup.find('h1')
    if h1 is None:raise EvidenceError('Titre de l article absent')
    # Limiter à l'introduction éditoriale; exclure les nombreux articles recommandés.
    content=[]
    for elem in h1.next_elements:
        if isinstance(elem,Tag) and elem.name in ('h2','h3'):
            if len(' '.join(content))>300:break
        if isinstance(elem,NavigableString):content.append(str(elem))
        if len(' '.join(content))>13000:break
    first=' '.join(content)
    results=_explicit_period(first,publication.year)
    if len(results)!=1:
        raise EvidenceError('Semaine de ventes non explicite ou contradictoire dans l article')
    start,end=map(dt.date.fromisoformat,results[0])
    if (publication-end).days<0 or (publication-end).days>14:
        raise EvidenceError('Date de publication incompatible avec la semaine de ventes')
    return start.isoformat(),end.isoformat()

def _card_text_after_heading(heading, max_chars=3500):
    texts=[];count=0
    for element in heading.next_elements:
        if element is heading:continue
        if isinstance(element,Tag) and element.name in ('h1','h2','h3'):
            break
        if isinstance(element,NavigableString):
            value=str(element).strip()
            if value:
                texts.append(value);count+=len(value)
                if count>=max_chars:break
    return ' '.join(texts)

def parse_top200(html, *, min_required=200):
    """Ordre des fiches Edistat, jamais ordre d'une sélection éditoriale.

    Seules les fiches avec EAN-13 et mention partenaire sont comptées. Si
    moins de 200 fiches, on REFUSE de traiter comme Top200 exhaustif.
    """
    soup=BeautifulSoup(html,'html.parser')
    items=[];seen=set()
    for h in soup.find_all(['h2','h3']):
        title=h.get_text(' ',strip=True)
        if not (2<len(title)<=250):continue
        block=_card_text_after_heading(h)
        if 'edistat' not in norm(block):continue
        eans=re.findall(r'\b(?:978|979)\d{10}\b',block)
        if not eans:continue
        ean=eans[-1]
        if ean in seen:continue
        # La liste générale de livres est ordonnée par rang de vente.
        # Les sections d'article n'ont pas le bloc ISBN + Edistat et sont exclues.
        publisher=''
        match=re.search(r'\bParu le \d{2}/\d{2}/\d{4}\b\s*(?:\d+ pages?\s*)?(.{2,70}?)\s+\d+[,.]\d{2}\s*€',block,re.I)
        if match:publisher=match.group(1).strip()
        seen.add(ean)
        items.append({'rang_general':len(items)+1,'titre_article':title,'ean':ean,'editeur_article':publisher})
        if len(items)==200:break
    if len(items)!=200 or len(items)<min_required:
        raise EvidenceError(f'Top 200 incomplet : seulement {len(items)} fiches avec EAN/Edistat')
    return items

def latest_article_urls(index_html, limit=6):
    soup=BeautifulSoup(index_html,'html.parser');urls=[]
    for a in soup.select('a[href]'):
        u=urljoin(ACTUALITTE_INDEX,a['href'])
        p=urlparse(u)
        if p.hostname in ('actualitte.com','www.actualitte.com') and re.search(r'/article/\d+/meilleures-ventes/',p.path):
            if u not in urls:urls.append(u)
        if len(urls)>=limit:break
    return urls

def parse_bede_current(html):
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    m=re.search(r'palmar[eè]s du (\d{2}/\d{2}/20\d{2})',text,re.I)
    if not m:raise EvidenceError('Date Bédé.fr non trouvée')
    rows=[];seen=set()
    for img in soup.select('img[alt]'):
        alt=(img.get('alt') or '').strip()
        if not alt:continue
        for node in list(img.parents)[:6]:
            if node.name not in ('li','article','div'):continue
            raw=node.get_text(' ',strip=True)
            if not (1<len(raw)<900):continue
            mr=re.search(r'(?:^|\s)#\s*(\d{1,3})\b',raw)
            if mr and 1<=int(mr.group(1))<=200:
                rang=int(mr.group(1))
                if rang not in seen:
                    seen.add(rang)
                    src=img.get('data-src') or img.get('data-lazy-src') or img.get('src') or ''
                    rows.append({'rang_mixte':rang,'alt':alt,'cover_url':urljoin(BEDE,src)})
                break
    rows.sort(key=lambda x:x['rang_mixte'])
    return {'date_palmares':m.group(1),'lignes':rows}

def _edition_marker(s):
    n=norm(s)
    return tuple(k for k in ('collector','grimoire','prestige','deluxe','coffre') if k in n)

def _volume(s):
    m=re.search(r'\b(?:tome|t|vol|volume)\s*0*(\d{1,3})\b',norm(s))
    return int(m.group(1)) if m else None

def match_titles(a,b):
    # Éviter de confondre tome 16 standard avec collector.
    av,bv=_volume(a),_volume(b)
    if av is not None and bv is not None and av!=bv:return False
    if _edition_marker(a)!=_edition_marker(b):return False
    aw=set(norm(a).split());bw=set(norm(b).split())
    stop={'tome','vol','volume','edition','les','la','le','de','des','du','the','et','d','l','t'}
    aw={x for x in aw if x not in stop and len(x)>1 and not x.isdigit()}
    bw={x for x in bw if x not in stop and len(x)>1 and not x.isdigit()}
    shared=len(aw & bw)
    # La comparaison doit rester symétrique : un seul mot commun ne suffit
    # pas à confondre une série avec une autre dont le titre est plus long.
    return bool(aw and bw) and shared>=min(2,len(aw),len(bw)) and shared/len(aw)>=0.65 and shared/len(bw)>=0.5

def _load_known_editions(root):
    fn=root/'editions_manga_v5.json'
    if not fn.exists():return {}
    raw=json.loads(fn.read_text(encoding='utf-8'))
    return {str(x['ean']):x for x in raw.get('editions',[]) if x.get('ean')}

def known_series(item):
    """Repères de genre, JAMAIS utilisés comme preuve de rang ou de ventes."""
    keywords=('instinct','spy x family','atelier des sorciers','one piece','kagurabachi',
       'blue lock','boruto','bleach','dragon ball','sakamoto days','berserk',
       'jujutsu kaisen','chainsaw man','ruridragon','les carnets de l apothicaire',
       'frieren','dandadan','gachiakuta','one punch man','solo leveling','tsugai',
       'ichi the witch','bloom','shangri la frontier','kaiju no 8','soul eater',
       'sword art online','fairy tail','naruto','demon slayer','my hero academia')
    n=norm(item['titre_article']);return any(x in n for x in keywords)

def classify_item(item,known,bede_rows,annual_titles=()):
    if item['ean'] in known:
        return True,known[item['ean']]['titre'],'ean_identifie',None
    # Les collections Bédé.fr sont segmentées : /media/manga/ correspond
    # à la rubrique MANGA. Ici on l'utilise pour détecter les nouveautés,
    # jamais comme preuve indépendante des rangs de ventes Edistat.
    matches=[r for r in bede_rows
             if '/media/manga/' in (r.get('cover_url') or '').lower()
             and match_titles(item['titre_article'],r.get('alt',''))]
    if len(matches)==1:
        return True,item['titre_article'],'bede_categorie_manga',None
    # Un nom de série (même célèbre) n'est pas une preuve de la bonne édition.
    # Pas de validation par simple mot-clé, qui pourrait sélectionner un homonyme.
    for name in annual_titles:
        if match_titles(item['titre_article'],name):
            return True,item['titre_article'],'catalogue_manga_annuel',None
    # Marques éditoriales dont le catalogue est manga ; la catégorie reste
    # corroborée par les fiches d'édition avant diffusion définitive.
    e=norm(item.get('editeur_article') or '')
    manga_publishers=('pika','kurokawa','ki oon','kana','crunchyroll','nobi nobi','mangetsu',
                      'ototo','vega dupuis','akata','komikku','doki doki','soleil manga')
    if any(token in e for token in manga_publishers):
        return True,item['titre_article'],'editeur_manga',None
    # Les titres sans indice de manga restent classés NON CONFIRMÉS comme mangas.
    # On ne les élimine pas silencieusement de l'audit.
    return False,item['titre_article'],'aucune_preuve_de_genre',None

def annual_titles_from_html(html):
    soup=BeautifulSoup(html,'html.parser')
    return [img.get('alt','').strip() for img in soup.select('img[alt]') if img.get('alt','').strip()]

def attach_bede(entry,bede_rows):
    title=entry['titre']
    matches=[r for r in bede_rows if match_titles(title,r['alt'])]
    if not matches:return entry
    if len(matches)>1:
        return entry
    r=matches[0]
    entry['rang_bd_manga_comics']=r['rang_mixte']
    entry['couverture_candidate_url']=r['cover_url']
    entry['couverture_reference']=r['alt']
    return entry

def source_report(article_html,bede_html,annual_html='', *, root=Path('.'),source_url='',previous=None, min_books=200):
    published=pub_date(article_html)
    start,end=_period_for_article(article_html,published)
    books=parse_top200(article_html,min_required=min_books)
    current=parse_bede_current(bede_html)
    if current['date_palmares'] != published.strftime('%d/%m/%Y'):
        raise EvidenceError('Le palmarès Bédé.fr ne correspond pas à la publication ActuaLitté')
    known=_load_known_editions(root)
    annual=annual_titles_from_html(annual_html) if annual_html else []
    candidates=[];unconfirmed=[]
    for row in books:
        is_manga,title,why,_=classify_item(row,known,current['lignes'],annual)
        if is_manga:
            item={'rang_general_livres':row['rang_general'],'titre':title,
                  'ean':row['ean'],'editeur':known.get(row['ean'],{}).get('editeur') or row['editeur_article'],
                  'preuve_genre':why,'mouvement':'NON DOCUMENTÉ'}
            candidates.append(attach_bede(item,current['lignes']))
        elif len(candidates)<7:
            unconfirmed.append({'rang_general_livres':row['rang_general'],
                                'titre_article':row['titre_article'],'ean':row['ean'],
                                'editeur_article':row.get('editeur_article','')})
        if len(candidates)>=7:
            break
    if len(candidates)<7:raise EvidenceError(f'Seulement {len(candidates)} mangas reconnus dans le Top 200')
    # La présence de sept candidats dans le Top200 est prouvée, la classification
    # de tout le catalogue ne l'est pas. Éviter le label « classement national certifié ».
    previous_map={b['ean']:b['rang'] for b in (previous or {}).get('titres',[]) if b.get('ean')}
    previous_is_valid=bool(previous and previous.get('fin_ventes') == (dt.date.fromisoformat(start)-dt.timedelta(days=1)).isoformat())
    top=[]
    for i,b in enumerate(candidates[:7],start=1):
        b['rang']=i
        if previous_is_valid:
            if b['ean'] in previous_map:
                delta=previous_map[b['ean']]-i
                b['mouvement']=f'+{delta} PL.' if delta>0 else f'−{-delta} PL.' if delta<0 else 'STABLE'
            else:b['mouvement']='NOUVEAU'
        top.append(b)
    data={'categorie':'MANGA','perimetre':'Reconstitution depuis Top 200 Edistat/ActuaLitté (livres papier en France), classification manga; non certifié exhaustif du segment manga',
          'debut_ventes':start,'fin_ventes':end,'date_publication':published.isoformat(),
          'source':'ActuaLitté / Edistat, contrôlé avec Bédé.fr',
          'url_source':source_url,'variations_verifiees':previous_is_valid,
          'certification':'TOP7_RECONSTITUE_A_VALIDER',
          'methode':'Rangs du Top 200 général; 7 premiers ouvrages identifiés comme mangas. Bédé.fr a des omissions et n est pas la preuve exhaustive.',
          'titres':top}
    evidence={'source_principale':source_url,'date_palmares_bede':current['date_palmares'],
              'url_secondaire':BEDE,'periode_ventes':[start,end],
              'articles_dans_top200':len(books),'rangs_bede_trouves':len(current['lignes']),
              'bede_lignes':current['lignes'],
              'mangas_reconnus_avant_septieme':len(top),
              'titres_anterieurs_sans_preuve_genre':unconfirmed,
              'sources_supplementaires':[
                 {'nom':'Livres Hebdo / NielsenIQ BookData','url':LIVRES_HEBDO,'role':'comparaison indépendante de la tête des ventes, pas de Top 7 manga publié'},
                 {'nom':'Bédé.fr / palmarès Edistat','url':BEDE,'role':'recoupement même source primaire Edistat, avec omission possible'},
                 {'nom':'Bédé.fr manga (catalogue annuel)','url':f'https://www.bede.fr/meilleurs-manga-{published.year}','role':'catalogue de reconnaissance des genres, pas de preuve de ventes hebdomadaires'}],
              'limites':['Top 200 général plafonné à 200 ouvrages',
                         'Classification manga hors catalogue parfois incertaine',
                         'Pas de volume de ventes individuel de chaque ouvrage dans les 200 fiches',
                         'Bédé.fr et ActuaLitté reprennent une même source Edistat, non deux panels indépendants']}
    return data,evidence

def collect(root, dest, *, article_url=None, actualitte_html=None,bede_html=None,annual_html=None,previous_file=None, min_books=200):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    if actualitte_html is not None and not article_url:
        article_url='https://actualitte.com/article/000000/meilleures-ventes/test-local'
    if bede_html is None:bede_html=get_html(BEDE)
    if article_url is None:
        expected_date=parse_bede_current(bede_html)['date_palmares']
        urls=latest_article_urls(get_html(ACTUALITTE_INDEX))
        if not urls:raise EvidenceError('Aucun nouvel article de classement identifié')
        errors=[]
        for url in urls:
            try:
                html=get_html(url)
                dates=pub_date(html);_period_for_article(html,dates)
                parse_top200(html,min_required=min_books)
                if dates.strftime('%d/%m/%Y')!=expected_date:
                    raise EvidenceError('Date différente du palmarès Bédé.fr')
                article_url=url;actualitte_html=html;break
            except Exception as exc:errors.append(f'{url}: {type(exc).__name__}')
        if article_url is None:raise EvidenceError('Aucun article avec Top 200 complet: '+' | '.join(errors))
    if actualitte_html is None:actualitte_html=get_html(article_url)
    if annual_html is None:
        # Année de publication réelle, afin de ne pas réutiliser le catalogue 2026
        # pour classifier automatiquement les titres en 2027 et au-delà.
        annual_url=f'https://www.bede.fr/meilleurs-manga-{pub_date(actualitte_html).year}'
        try:annual_html=get_html(annual_url)
        except (requests.RequestException,EvidenceError):annual_html=''
    previous=None
    if previous_file and Path(previous_file).is_file():
        previous=json.loads(Path(previous_file).read_text(encoding='utf8'))
    data,evidence=source_report(actualitte_html,bede_html,annual_html or '',root=Path(root),source_url=article_url,previous=previous,min_books=min_books)
    if previous and previous.get('fin_ventes') == data['fin_ventes']:
        old_order=[(x.get('rang'),x.get('ean')) for x in previous.get('titres',[])]
        new_order=[(x['rang'],x['ean']) for x in data['titres']]
        if old_order != new_order:
            raise EvidenceError('La source a modifie les rangs d une semaine deja traitee : revision manuelle, pas de remplacement automatique')
        # Une seconde consultation de la même semaine NE doit pas supprimer les
        # évolutions calculées à partir de la semaine antérieure.
        data=previous
        evidence['nouvelle_edition']=False
    else:
        evidence['nouvelle_edition']=True
    edition='MANGA_'+data['fin_ventes']
    target=dest/edition;target.mkdir(parents=True,exist_ok=True)
    for name,obj in (('classement_manga.json',data),('preuves_manga.json',evidence)):
        (target/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    (target/'BILAN.md').write_text(
        f'# {edition}\n\nSemaine de ventes : {data["debut_ventes"]} au {data["fin_ventes"]}\n\n'
        'Top 7 reconstruit d’après le palmarès Edistat/ActuaLitté, recoupé avec Bédé.fr.\n\n'
        + '\n'.join(f'{x["rang"]}. {x["titre"]} (EAN {x["ean"]}, rang général {x["rang_general_livres"]})' for x in data['titres'])
        + '\n\nATTENTION : reconstitution sérieuse, pas certification du Top 7 exhaustif de tous les mangas distribués.\n',
        encoding='utf8')
    return target

def main(argv=None):
    p=argparse.ArgumentParser(description='Reconstituer le Top 7 manga France sans modifier le pipeline BD')
    p.add_argument('--sortie',default='sorties/manga_hebdo')
    p.add_argument('--article-url')
    p.add_argument('--html-actualitte',type=Path)
    p.add_argument('--html-bede',type=Path)
    p.add_argument('--html-manga-annuel',type=Path)
    p.add_argument('--precedent',type=Path)
    args=p.parse_args(argv)
    folder=collect(Path(__file__).resolve().parent,Path(args.sortie),article_url=args.article_url,
        actualitte_html=args.html_actualitte.read_text(encoding='utf8') if args.html_actualitte else None,
        bede_html=args.html_bede.read_text(encoding='utf8') if args.html_bede else None,
        annual_html=args.html_manga_annuel.read_text(encoding='utf8') if args.html_manga_annuel else None,
        previous_file=args.precedent)
    print(folder)

if __name__=='__main__':main()
