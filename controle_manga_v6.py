"""Manga V6: traçabilité de période, actualisation hebdomadaire, qualité de couvertures.

Ne publie jamais sur Buffer. La date de Bédé.fr est celle du palmarès,
PAS une preuve de la période de ventes. Une comparaison partielle d'ActuaLitté
fournit un indice, et non une validation nationale des sept rangs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

REPORT_DIR = Path('rapports_manga')
STATE_PATH = Path('.cache_manga_v6/etat_manga_v6.json')
MAX_PAGE_BYTES = 1_500_000
MAX_COVER_BYTES = 3_500_000
UA = {'User-Agent': 'Top7MangaAuditV6/1.0 (classements publics; aucune publication)'}
MONTHS = {'janvier':1,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,
          'aout':8,'septembre':9,'octobre':10,'novembre':11,'decembre':12}
MANGA_KEYS = {
  'instinct': (r'\binstinct\b', r'\b(?:tome|vol(?:ume)?)[ .,:\-]*0?3\b'),
  'spy x family': (r'\bspy\s*x\s*family\b', r'\b(?:tome|vol(?:ume)?)[ .,:\-]*0?17\b'),
}


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text).lower())
    text = ''.join(x for x in text if not unicodedata.combining(x))
    return re.sub(r'\s+', ' ', text.replace('×', 'x')).strip()


def date_palmares(date_fr: str) -> dt.date:
    return dt.datetime.strptime(date_fr, '%d/%m/%Y').date()


def explicit_week_ranges(text: str, year: int) -> list[tuple[dt.date, dt.date]]:
    """Lit UNIQUEMENT des dates de ventes explicitement présentes dans le texte."""
    s = normalize(text)
    found = []
    month_names = '|'.join(MONTHS)
    patterns = [
      # du 9 au 15 novembre 2026
      rf'\bdu\s+(\d{{1,2}})(?:er)?\s+au\s+(\d{{1,2}})(?:er)?\s+({month_names})(?:\s+(20\d{{2}}))?\b',
      # du 26 octobre au 1er novembre 2026
      rf'\bdu\s+(\d{{1,2}})(?:er)?\s+({month_names})\s+au\s+(\d{{1,2}})(?:er)?\s+({month_names})(?:\s+(20\d{{2}}))?\b',
    ]
    for p_index, pattern in enumerate(patterns):
        for m in re.finditer(pattern, s, re.I):
            try:
                if p_index == 0:
                    d1, d2, mon, y = m.groups()
                    end = dt.date(int(y or year), MONTHS[mon], int(d2))
                    start = dt.date(end.year, end.month, int(d1))
                else:
                    d1, mon1, d2, mon2, y = m.groups()
                    end = dt.date(int(y or year), MONTHS[mon2], int(d2))
                    sy = end.year - (1 if MONTHS[mon1] > MONTHS[mon2] else 0)
                    start = dt.date(sy, MONTHS[mon1], int(d1))
                if (end-start).days == 6 and start.weekday() == 0 and end.weekday() == 6:
                    if (start, end) not in found:
                        found.append((start,end))
            except (ValueError, TypeError):
                continue
    return found


def article_published_on(soup: BeautifulSoup) -> dt.date | None:
    """N'utilise pas la date du classement ni la date actuelle comme substitut."""
    for tag in soup.select('meta[property="article:published_time"], meta[name="date"], time[datetime]'):
        raw = tag.get('content') or tag.get('datetime') or ''
        m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})(?!\d)', raw)
        if m:
            try: return dt.date(*map(int, m.groups()))
            except ValueError: pass
    # ActuaLitté peut afficher "Le 20/11/2026 à 11:52" dans le texte.
    m = re.search(r'\ble\s+(\d{2})/(\d{2})/(20\d{2})\b', normalize(soup.get_text(' ', strip=True)))
    if m:
        try: return dt.date(int(m[3]),int(m[2]),int(m[1]))
        except ValueError: return None
    return None


def matched_titles(article_text: str, top: list[dict]) -> list[str]:
    """Exige série et tome exact dans un même voisinage; pas un nom isolé."""
    txt = normalize(article_text)
    found = []
    top_names = normalize(' '.join(str(r.get('titre','')) for r in top))
    for title, (series, tome) in MANGA_KEYS.items():
        if not re.search(series, top_names):
            continue
        for m in re.finditer(series, txt):
            if re.search(tome, txt[max(0,m.start()-25):m.end()+95]):
                found.append(title)
                break
    return found


def sha_ranking(audit: dict) -> str:
    inspection = next((x.get('inspection',{}) for x in audit.get('sources', [])
                       if x.get('source')=='bede_bd_manga'), {})
    ranks = inspection.get('premieres_entrees_a_verifier') or []
    if len(ranks) < 7:
        raise ValueError('Palmarès Bédé.fr trop court pour déterminer une empreinte')
    payload = {'date_palmares':inspection.get('date_palmares_affichee'),
               'rangs':[(r.get('rang_bd_manga'),r.get('titre_affiche')) for r in ranks]}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def fetch_article(url: str, *, getter=requests.get) -> str:
    p = urlparse(url)
    if p.scheme!='https' or p.hostname!='actualitte.com' or not p.path.startswith('/article/'):
        raise ValueError('Article hors de la source ActuaLitté autorisée')
    response = getter(url,timeout=15,headers=UA,allow_redirects=True)
    response.raise_for_status()
    final = urlparse(getattr(response,'url',url))
    if final.scheme!='https' or final.hostname!='actualitte.com' or not final.path.startswith('/article/'):
        raise ValueError('Redirection article non autorisée')
    if len(response.content)>MAX_PAGE_BYTES:
        raise ValueError('Article trop volumineux')
    return response.text


def validate_period(audit: dict, verification: dict, *, getter=requests.get,
                    today: dt.date | None=None) -> dict:
    """Confrontation ActuaLitté/Bédé.fr sans déduire une date de ventes du jour MAJ."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    result = {'etat':'NON_ETABLIE', 'periode_candidate':None, 'periode_ventes_validee':False,
              'sources_lues':[], 'recoupements':[], 'motifs':[]}
    source = {x.get('source'):x for x in audit.get('sources',[])}
    bede = source.get('bede_bd_manga',{}).get('inspection',{})
    bdate = bede.get('date_palmares_affichee')
    if not bdate or bdate != verification.get('date_palmares_bede'):
        result['motifs'].append('Date du palmarès Bédé.fr absente ou contradictoire avec la V2')
        return result
    try: bday = date_palmares(bdate)
    except ValueError:
        result['motifs'].append('Date du palmarès invalide'); return result
    if bday > today:
        result['motifs'].append('Date du palmarès future'); return result
    article_src = source.get('actualitte_edistat',{})
    urls = [x.get('url','') for x in article_src.get('articles_detectes',[])][:5]
    for url in urls:
        try:
            page = fetch_article(url,getter=getter)
            soup = BeautifulSoup(page,'html.parser')
            pub = article_published_on(soup)
            if pub is None:
                result['sources_lues'].append({'url':url,'etat':'DATE_PUBLICATION_ABSENTE'})
                continue
            if abs((pub-bday).days)>2:
                result['sources_lues'].append({'url':url,'etat':'AUTRE_EDITION','date_publication':pub.isoformat()})
                continue
            main = soup.select_one('article') or soup.select_one('main') or soup
            text = main.get_text(' ',strip=True)
            dates = explicit_week_ranges(text,pub.year)
            # L'article peut évoquer PLUSIEURS semaines : on retient seulement
            # l'intervalle hebdomadaire terminant entre 4 et 16 jours avant la date.
            eligible = [p for p in dates if 4 <= (pub-p[1]).days <= 16 and p[1] <= today]
            matches = matched_titles(text,verification.get('candidats_non_certifies') or [])
            result['sources_lues'].append({'url':url,'date_publication':pub.isoformat(),
                                          'periodes_explicitement_lues':[[x.isoformat(),y.isoformat()] for x,y in dates],
                                          'titres_reconnus':matches})
            if len(matches)>=2 and len(eligible)==1:
                candidate = eligible[0]
                result['etat']='CORROBOREE_PARTIELLEMENT'
                result['periode_candidate']={'debut':candidate[0].isoformat(), 'fin':candidate[1].isoformat()}
                result['recoupements']=matches
                result['motifs'].append('Deux titres/volumes cohérents dans un article daté de la même édition; les 7 rangs ne sont pas prouvés')
                break
        except (requests.RequestException, ValueError, OSError) as err:
            result['sources_lues'].append({'url':url,'etat':'ERREUR','detail':type(err).__name__})
    if not result['periode_candidate']:
        result['motifs'].append('Aucun article daté ne relie une semaine explicite à au moins deux titres du palmarès')
    # Jusqu'à une preuve exhaustive portant sur les 7 rangs, ce champ reste false.
    result['periode_ventes_validee'] = False
    return result


def cover_kind(image_path: Path, *, edition: dict | None=None) -> dict:
    """Heuristique : une image portrait ne prouve pas que c'est une couverture seule."""
    ed = edition or {}
    with Image.open(image_path) as image:
        im = image.convert('RGB')
        im.thumbnail((250,330))
        w,h = im.size
        pix=list(im.getdata())
        white=sum(1 for r,g,b in pix if min(r,g,b)>239)/max(1,len(pix))
        # Les produits collector sont souvent photographiés comme des coffrets.
        if 'collector' in normalize(ed.get('titre','')) and white > .20:
            kind='PACKSHOT_COLLECTOR_PROBABLE'
        elif white>.45:
            kind='PACKSHOT_OU_COUVERTURE_AVEC_MARGES'
        else:
            kind='COUVERTURE_CANDIDATE'
        return {'type':kind,'part_fond_blanc':round(white,3),
                'controle_visuel_recommande':True,'taille_image':[w,h]}


def openlibrary_cover(ean: str, dest: Path, *, getter=requests.get) -> dict:
    """Plan B exact ISBN, sans recherche par titre ni image japonaise substituée."""
    from enrichissement_manga_v5 import verifier_ean
    if not verifier_ean(ean):
        return {'ok':False,'motif':'EAN invalide'}
    url=f'https://covers.openlibrary.org/b/isbn/{ean}-L.jpg?default=false'
    try:
        r=getter(url,timeout=12,headers=UA,allow_redirects=True)
        r.raise_for_status()
        p=urlparse(getattr(r,'url',url))
        if p.scheme!='https' or p.hostname!='covers.openlibrary.org':
            raise ValueError('Redirection hors Open Library')
        if len(r.content)>MAX_COVER_BYTES or not r.headers.get('Content-Type','').lower().startswith('image/'):
            raise ValueError('Format de réponse invalide')
        with Image.open(io.BytesIO(r.content)) as picture:
            picture.load()
            if not (200<=picture.width<=2500 and 290<=picture.height<=3500 and .48<=picture.width/picture.height<=.90):
                raise ValueError('Dimensions incompatibles')
            dest.parent.mkdir(parents=True,exist_ok=True)
            picture.convert('RGB').save(dest,'PNG')
        return {'ok':True,'motif':'Image fournie par Open Library via EAN exact; contrôler l’édition française', 'url':url}
    except (requests.RequestException, ValueError, OSError) as exc:
        return {'ok':False,'motif':type(exc).__name__}


def cover_summary(v5: dict, root: Path, *, getter=requests.get) -> dict:
    """Exploite V5 (et non un catalogue fixe pour les semaines futures)."""
    rows=[]
    rescued_any=False
    if v5.get('etat')!='MAQUETTE_NON_CERTIFIEE' or v5.get('date_palmares')!='20/11/2026':
        return {'etat':'CATALOGUE_V5_HORS_PERIODE','editions':[], 'covers_found':0,
                'motif':'Le catalogue V5 est limité au palmarès du 20/11/2026; identification dynamique encore requise'}
    existing={str(x.get('ean')):x for x in v5.get('editions',[])}
    all_refs=json.loads(Path(__file__).with_name('editions_manga_v5.json').read_text(encoding='utf-8'))['editions']
    for ed in all_refs:
        ean=ed['ean']; actual=existing.get(ean,{})
        dest=root/'couvertures'/f'{ean}.png'
        rescue=None
        if not dest.is_file() and not actual.get('couverture_disponible'):
            rescue=openlibrary_cover(ean,dest,getter=getter)
            if rescue.get('ok'):
                rescued_any=True
        good=dest.is_file()
        item={'rang_provisoire':(list(all_refs).index(ed)+1),'titre':ed['titre'], 'ean':ean,
              'couverture_presente':good, 'origine':('V5' if actual.get('couverture_disponible') else 'OPEN_LIBRARY' if rescue and rescue.get('ok') else 'ABSENTE')}
        if rescue and not rescue.get('ok'): item['diagnostic_repli']=rescue.get('motif')
        if good:
            try: item.update(cover_kind(dest,edition=ed))
            except OSError: item['type']='FICHIER_INVALIDE';item['couverture_presente']=False
        rows.append(item)
    # Un téléchargement complémentaire doit apparaître dans les huit images,
    # pas seulement dans le dossier /couvertures. Aucun effacement des avertissements.
    if rescued_any:
        from enrichissement_manga_v5 import incruster_couvertures
        source_v4=root.parent/'maquette_v4'
        if source_v4.is_dir():
            editions=[{**ed,'rang_manga_provisoire':i} for i,ed in enumerate(all_refs,1)]
            incruster_couvertures(source_v4,root,editions)
    return {'etat':'CONTROLE_COUVERTURES','editions':rows,
            'covers_found':sum(1 for x in rows if x.get('couverture_presente')),
            'packshots_a_verifier':sum(1 for x in rows if x.get('type','').startswith('PACKSHOT'))}


def evaluate_change(fingerprint: str, period: dict, previous: dict) -> str:
    prev_hash=previous.get('derniere_empreinte')
    prev_candidate=previous.get('derniere_periode_candidate')
    new_period=(period.get('periode_candidate') or {}).get('fin')
    if not prev_hash:
        return 'PREMIERE_OBSERVATION'
    if fingerprint==prev_hash:
        return 'CLASSEMENT_INCHANGE'
    if new_period is None:
        return 'PALMARES_MODIFIE_SANS_SEMAINE_VERIFIABLE'
    if new_period!=prev_candidate:
        return 'NOUVELLE_SEMAINE_CANDIDATE_NON_CERTIFIEE'
    return 'REVISION_DU_CLASSEMENT_DE_LA_MEME_SEMAINE'


def execute(reports: Path=REPORT_DIR, state: Path=STATE_PATH, *, getter=requests.get,
            today: dt.date | None=None) -> dict:
    audit=json.loads((reports/'audit_manga.json').read_text(encoding='utf-8'))
    verification=json.loads((reports/'verification_manga.json').read_text(encoding='utf-8'))
    v5_path=reports/'maquette_v5'/'rapport_enrichissement_v5.json'
    v5=json.loads(v5_path.read_text(encoding='utf-8')) if v5_path.is_file() else {}
    previous=json.loads(state.read_text(encoding='utf-8')) if state.is_file() else {}
    today=today or dt.datetime.now(dt.timezone.utc).date()
    period=validate_period(audit,verification,getter=getter,today=today)
    fingerprint=sha_ranking(audit)
    change=evaluate_change(fingerprint,period,previous)
    covers=cover_summary(v5,reports/'maquette_v5',getter=getter)
    report={'version':6,'categorie':'MANGA','date_controle':today.isoformat(),
            'date_palmares':verification.get('date_palmares_bede'),
            'periode':period,'evolution_detectee':change,
            'empreinte_palmares':fingerprint,'couvertures':covers,
            'top7_national_complet':False,'publication_manga_autorisee':False,
            'queue_buffer':'NON_MODIFIEE',
            'raisons_blocage':[]}
    if not period['periode_ventes_validee']:
        report['raisons_blocage'].append('La semaine de ventes du TOP 7 complet n’est pas certifiée')
    report['raisons_blocage'].append('Aucune source exhaustive prouvant les 7 premiers mangas nationaux')
    if covers.get('covers_found',0)!=7:
        report['raisons_blocage'].append('Sept couvertures françaises exploitables non récupérées')
    if covers.get('packshots_a_verifier'):
        report['raisons_blocage'].append('Packshot(s) de collector à contrôler visuellement')
    reports.mkdir(parents=True,exist_ok=True)
    (reports/'controle_manga_v6.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    # Pour éviter de confondre observation nouvelle et publication validée : état d'audit uniquement.
    state.parent.mkdir(parents=True,exist_ok=True)
    state.write_text(json.dumps({'derniere_empreinte':fingerprint,
                                 'derniere_periode_candidate':(period.get('periode_candidate') or {}).get('fin'),
                                 'date_observation':today.isoformat()},indent=2),encoding='utf-8')
    lines=['# Manga V6 — période des ventes et couvertures','',
           '**Mode contrôle uniquement : aucune action Buffer.**','',
           f"- Palmarès Bédé.fr : **{report['date_palmares']}** (date de mise à jour, pas semaine de ventes)",
           f"- Période : **{period['etat']}**",
           f"- Édition observée : **{change}**",
           f"- Couvertures disponibles : **{covers.get('covers_found',0)}/7**",
           f"- Packshots suspects : **{covers.get('packshots_a_verifier',0)}**",'']
    if period['periode_candidate']:
        p=period['periode_candidate']
        lines += [f"- Indice de période (NON certifiée pour 7 rangs) : **{p['debut']} au {p['fin']}**",'']
    lines += ['## Pourquoi aucune publication n’a lieu', ''] + [f'- {x}' for x in report['raisons_blocage']]
    lines += ['', '## Contrôle des images', '']
    for ed in covers.get('editions',[]):
        lines.append(f"- {ed['titre']} : {'OK' if ed.get('couverture_presente') else 'MANQUANTE'} — {ed.get('type','image non trouvée')}")
    lines += ['', 'Important : lorsque la période est seulement corroborée, ne pas l’imprimer sur le carrousel public.',
              'Un véritable Top 7 hebdomadaire nécessitera une source de rangs complète datée et un anti-doublon durable avant l’activation de Buffer.','']
    (reports/'CONTROLE_V6_LIRE.md').write_text('\n'.join(lines),encoding='utf-8')
    return report


def main():
    try:
        report=execute()
        print('V6 manga:',report['periode']['etat'], report['evolution_detectee'],
              str(report['couvertures'].get('covers_found',0))+'/7 couvertures; aucune publication')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('Diagnostic V6 non terminé (sans aucun envoi Buffer):',str(exc))
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
