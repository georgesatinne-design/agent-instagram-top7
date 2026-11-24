"""Audit de genre pour les livres mieux vendus que le septième manga.

Ne confond pas : apparier un ISBN, reconnaître un genre, et établir le rang.
Une réponse API absente/ambiguë ne prouve JAMAIS qu'un livre n'est pas manga.
Aucune mutation Buffer. Aucun changement aux scripts BD.
"""
from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

from manga_sources_hebdo import norm, EvidenceError, match_titles

GOOGLE = 'https://www.googleapis.com/books/v1/volumes'
OPENLIBRARY = 'https://openlibrary.org/api/books'
HEADERS = {'User-Agent': 'AgentMangaFrance/2.0 (verification bibliographique)' }
# Ne jamais considérer « roman graphique » comme preuve que le livre n'est pas manga.
MANGA_WORDS = ('manga', 'shonen', 'shonen', 'shojo', 'shoujo', 'seinen', 'josei', 'manhwa')
NON_MANGA_GENRES = (
    'fiction', 'romance', 'thriller', 'biography', 'biographie', 'political science',
    'politique', 'history', 'histoire', 'cooking', 'cuisine', 'travel', 'voyage',
    'self help', 'développement personnel', 'psychology', 'psychologie', 'religion',
    'science', 'business', 'essays', 'essais', 'novel', 'roman', 'young adult fiction',
    'philosophy', 'philosophie', 'poetry', 'poésie', 'poesie',
)


def _matches_isbn(info: dict, ean: str) -> bool:
    ids = info.get('industryIdentifiers') or []
    return any(str(x.get('identifier','')).replace('-','') == ean for x in ids if isinstance(x,dict))


def _genre_from_tokens(categories: list[str], *, exclusive=False) -> tuple[str,str]:
    """Return MANGA, NON_MANGA or INCERTAIN. Genre != statistical sales proof."""
    cleaned = [norm(c) for c in categories if isinstance(c,str)]
    joined = ' | '.join(cleaned)
    if any(re.search(r'\b'+re.escape(w)+r'\b',joined) for w in MANGA_WORDS):
        return 'MANGA', 'mention explicite manga dans catégories bibliographiques'
    # Comics, bande dessinée et graphic novel ne suffisent pas à EXCLURE manga.
    if re.search(r'comic|graphic novel|bande dessinee|bd|sequential art|illustrated',joined):
        return 'INCERTAIN', 'BD/comics non spécifique : peut être manga'
    # Parent genre book categories can include non-manga comics in some catalogs;
    # require clearly non-graphic subject and precise bibliographic ISBN.
    if cleaned and any(re.search(r'\b'+re.escape(w)+r'\b',joined) for w in NON_MANGA_GENRES):
        return 'NON_MANGA', 'catégories bibliographiques non graphiques explicites'
    return 'INCERTAIN', 'aucune catégorie suffisamment discriminante'


def google_isbn(ean: str, *, getter=requests.get) -> dict:
    try:
        r=getter(GOOGLE, params={'q':'isbn:'+ean,'maxResults':10, 'printType':'books'},headers=HEADERS,timeout=12)
        r.raise_for_status()
        raw=r.json()
        for hit in raw.get('items',[])[:10]:
            info=hit.get('volumeInfo') or {}
            if not _matches_isbn(info,ean):continue
            categories=info.get('categories') or []
            status,reason=_genre_from_tokens(categories)
            return {'statut':status,'raison':reason,'titres_catalogue':[info.get('title','')],
                    'categories':categories,'source':'Google Books ISBN',
                    'url':'https://books.google.com/books?vid=ISBN'+ean}
    except (requests.RequestException,ValueError,KeyError,TypeError):pass
    return {'statut':'INCERTAIN','raison':'ISBN exact non trouvé ou service indisponible','source':'Google Books ISBN'}


def openlibrary_isbn(ean: str, *, getter=requests.get) -> dict:
    try:
        r=getter(OPENLIBRARY,params={'bibkeys':'ISBN:'+ean,'jscmd':'data','format':'json'},headers=HEADERS,timeout=12)
        r.raise_for_status()
        v=r.json().get('ISBN:'+ean) or {}
        # Une absence du fichier ISBN = preuve insuffisante.
        if not v:return {'statut':'INCERTAIN','raison':'ISBN absent','source':'Open Library'}
        subjects=[x.get('name','') for x in (v.get('subjects') or []) if isinstance(x,dict)]
        status,reason=_genre_from_tokens(subjects)
        return {'statut':status,'raison':reason,'categories':subjects[:15],
                'source':'Open Library ISBN','url':v.get('url','')}
    except (requests.RequestException,ValueError,KeyError,TypeError):pass
    return {'statut':'INCERTAIN','raison':'Métadonnées non disponibles','source':'Open Library ISBN'}


def merger(ean: str, candidates: list[dict]) -> dict:
    statuses={c['statut'] for c in candidates}
    if 'MANGA' in statuses and 'NON_MANGA' in statuses:
        return {'statut':'INCERTAIN','raison':'Sources bibliographiques contradictoires','sources':candidates}
    if 'MANGA' in statuses:return {'statut':'MANGA','raison':'Genre manga confirmé','sources':candidates}
    if 'NON_MANGA' in statuses:return {'statut':'NON_MANGA','raison':'Genre non-manga confirmé via ISBN','sources':candidates}
    return {'statut':'INCERTAIN','raison':'Catégorie bibliographique inconnue','sources':candidates}


def catalog_status(row: dict, *, google=google_isbn, openlibrary=openlibrary_isbn) -> dict:
    ean = str(row['ean'])
    a=google(ean)
    if a.get('statut') == 'MANGA':
        return merger(ean,[a])
    b=openlibrary(ean)
    return merger(ean,[a,b])


def genre_bede(row:dict, rows:list[dict]) -> dict | None:
    """Genre éditorial dans le chemin de couverture, titre/tome concordants.

    Bédé.fr n'est PAS la source de rang; nous n'employons ici que sa rubrique
    iconographique si elle est explicite et univoque.
    """
    matches=[x for x in rows if match_titles(row['titre_article'],x.get('alt',''))]
    if len(matches)!=1:return None
    url=(matches[0].get('cover_url') or '').lower()
    if '/media/manga/' in url:
        stat='MANGA'
    elif '/media/bd/' in url or '/media/comics/' in url:
        stat='NON_MANGA'
    else:return None
    return {'statut':stat,'raison':'Catégorie du catalogue Bédé.fr + édition concordante',
            'source':'Bédé.fr / type de couverture','url':url}

def auditer(classement: dict, preuves: dict, *, cache: dict | None=None,
            resolver=catalog_status, limite_en_ligne=125) -> tuple[dict,dict,dict]:
    """N'audit que les inconnus AVANT le rang du 7e manga.

    Exception: un ISBN auparavant non-manga mais nouvellement manga doit être
    recontrôlé avant d'écarter le livre. Les entrées du cache sont datées,
    renouvelées après 90 jours. Ne préjuge pas des classements futurs.
    """
    if len(classement.get('titres',[]))!=7:
        raise EvidenceError('Sept mangas candidats requis')
    cache=dict(cache or {})
    bede_rows=preuves.get('bede_lignes') or []
    unknown=preuves.get('titres_anterieurs_sans_preuve_genre') or []
    if len(unknown)>limite_en_ligne:
        raise EvidenceError('Nombre d ouvrages non qualifiés anormal')
    details=[]
    now=dt.date.today()
    def resolve_one(book):
        ean=str(book['ean'])
        cached=cache.get(ean) if isinstance(cache.get(ean),dict) else None
        fresh=False
        if cached and cached.get('statut') in ('MANGA','NON_MANGA'):
            try:fresh=(now-dt.date.fromisoformat(cached.get('verifie_le',''))).days<=90
            except ValueError:pass
        bede_evidence=genre_bede(book,bede_rows)
        result=merger(ean,[bede_evidence, resolver(book)]) if bede_evidence and not fresh else (cached if fresh else resolver(book))
        if not isinstance(result,dict) or result.get('statut') not in ('MANGA','NON_MANGA','INCERTAIN'):
            raise EvidenceError('Réponse du classificateur bibliographique invalide')
        return {'rang_general_livres':book['rang_general_livres'],
                'titre_article':book['titre_article'],'ean':ean, **result}
    # Les requêtes Google/Open Library sont indépendantes; borne stricte.
    with ThreadPoolExecutor(max_workers=5) as workers:
        details=list(workers.map(resolve_one, unknown))
    for item in details:
        cache[item['ean']]={key:value for key,value in item.items()
                            if key not in ('rang_general_livres','titre_article','ean')}
        cache[item['ean']]['verifie_le']=now.isoformat()
    missed=[x for x in details if x['statut']=='MANGA']
    unresolved=[x for x in details if x['statut']=='INCERTAIN']
    if missed:
        # Correction automatique des oublis; aucune renumérotation fictive.
        combined=list(classement['titres'])
        for item in missed:
            combined.append({'rang_general_livres':item['rang_general_livres'],
                 'titre':item['titre_article'], 'ean':item['ean'],
                 'editeur':item.get('editeur',''),
                 'preuve_genre':'isbn_manga_confirme', 'mouvement':'NON DOCUMENTÉ'})
        combined=sorted(combined,key=lambda x:x['rang_general_livres'])
        # Conserver une seule fois chaque édition EAN.
        unique={}
        for book in combined:unique.setdefault(book['ean'],book)
        top=sorted(unique.values(),key=lambda x:x['rang_general_livres'])[:7]
        for index,item in enumerate(top,1):item['rang']=index
        classement['titres']=top
    if unresolved:
        status='A_VERIFIER'
        reason=f'{len(unresolved)} ouvrage(s) avant le rang 7 restent non classifiés avec certitude'
    else:
        status='TOP7_EDISTAT_VERIFIE'
        reason='Toutes les entrées mieux classées ont été catégorisées avec une preuve'
    # Ne pas prétendre qu un Top200 est une représentation parfaite de tous les
    # circuits de vente français. Il s agit du champ mesuré par Edistat.
    if missed:
        classement['variations_verifiees']=False
    classement['certification']=status
    classement['perimetre']='Sept premiers mangas identifiés dans le Top 200 Edistat/ActuaLitté en France'
    classement['methode']='Extraction Top 200, ISBN exact, classement des 7 premiers manga, vérification bibliographique des ouvrages précédents'
    classement['controle_genre_complet']=(status=='TOP7_EDISTAT_VERIFIE')
    classement['variations_verifiees']=bool(classement.get('variations_verifiees') and classement['controle_genre_complet'])
    if not classement['variations_verifiees']:
        for x in classement['titres']:x['mouvement']='NON DOCUMENTÉ'
    preuves['audit_genre']={
        'statut':status,'motif':reason,'avant_septieme_examines':len(details),
        'non_mangas_confirmes':sum(x['statut']=='NON_MANGA' for x in details),
        'mangas_possiblement_omis':missed,'indetermines':unresolved,
        'details':details,
        'limites':['Top 200 général (pas tout le marché)', 'Métadonnées publiques parfois incomplètes',
                   'Catégories bibliographiques non équivalentes aux ventes en caisse']}
    return classement,preuves,cache


def read_cache(path: Path) -> dict:
    try:
        p=Path(path)
        if p.exists():return json.loads(p.read_text(encoding='utf8'))
    except (ValueError,OSError):pass
    return {}


def write_json(path:Path,obj:dict):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
