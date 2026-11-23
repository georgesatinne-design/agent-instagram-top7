"""V5 manga: rapprochement d'editions et couvertures pour la MAQUETTE V4.

IMPORTANT: n'affirme JAMAIS que les ventes sont exhaustives. Aucun acces a Buffer,
aucune publication ni programmation. Le palmares et la periode restent a certifier.
Les images proviennent de fiches identifiees par EAN, mais leur usage public
peut necessiter une autorisation du titulaire des droits.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageOps

SOURCE_HOSTS = frozenset({
    "www.michel-lafon.fr", "www.pika.fr", "www.kana.fr", "www.glenat.com",
    "actualitte.com", "www.hachette.fr"
})
IMAGE_HOSTS = SOURCE_HOSTS | frozenset({
    "media.hachette.fr", "static.fnac-static.com", "cdn.bede.fr",
    "books.google.com", "books.google.fr", "books.googleusercontent.com",
    "storage.googleapis.com", "cdn.prod.website-files.com", "images.squarespace-cdn.com",
    "m.media-amazon.com", "www.google.com", "media.glenat.com"
})
MAX_HTML = 1_200_000
MAX_IMAGE = 3_500_000
HEADERS = {"User-Agent": "Top7MangaValidation/1.0 (catalogues publics; aucune connexion)"}


def safe_url(url: str, allowed: frozenset[str]) -> bool:
    if not isinstance(url, str) or len(url) > 1800:
        return False
    p = urlparse(url)
    return p.scheme == "https" and p.hostname in allowed and not p.username and not p.password


def fetch_page(url: str, *, getter=requests.get) -> str:
    if not safe_url(url, SOURCE_HOSTS):
        raise ValueError("Domaine de fiche non autorise")
    r = getter(url, timeout=12, headers=HEADERS, allow_redirects=True)
    r.raise_for_status()
    if not safe_url(getattr(r, 'url', url), SOURCE_HOSTS):
        raise ValueError("Redirection non autorisee")
    if len(r.content) > MAX_HTML:
        raise ValueError("Page trop volumineuse")
    return r.text


def verifier_ean(ean: str) -> bool:
    if not isinstance(ean, str) or not re.fullmatch(r"\d{13}", ean):
        return False
    chiffres = [int(x) for x in ean]
    checksum = (10 - sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(chiffres[:-1])) % 10) % 10
    return chiffres[-1] == checksum


def extraire_image_fiche(html: str, url: str, ean: str) -> str | None:
    """Image issue de la fiche exacte; jamais une simple recherche d'image approximative.

    Certains editeurs publient un og:image generique. Le ratio reel et les
    dimensions sont controles avant d'accepter le fichier.
    """
    if not verifier_ean(ean):
        return None
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    # L'ISBN doit correspondre a la fiche et pas seulement a un lien 'vous aimerez'.
    # Un EAN present dans l'URL canonique de l'edition est suffisamment distinctif.
    canonical = soup.find('link', rel='canonical')
    canonical_url = str(canonical.get('href') or '') if canonical else url
    if ean not in url and ean not in canonical_url:
        # Accepter les fiches editeurs sans EAN dans l'URL UNIQUEMENT si le corps
        # de la fiche mentionne cet EAN (pas si absent du HTML nettoye).
        if ean not in page_text:
            return None
    candidates: list[str] = []
    for tag in soup.find_all('meta'):
        key = str(tag.get('property') or tag.get('name') or '').lower()
        if key in {'og:image', 'twitter:image', 'twitter:image:src'}:
            candidates.append(str(tag.get('content') or ''))
    # schema.org Product image dans la fiche precise, pas les suggestions en bas.
    for node in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(node.string or node.get_text())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        for item in nodes:
            if not isinstance(item, dict):
                continue
            if str(item.get('@type', '')).lower() in {'product', 'book'}:
                im = item.get('image')
                if isinstance(im, str):
                    candidates.insert(0, im)
                elif isinstance(im, list):
                    candidates = [x for x in im if isinstance(x, str)] + candidates
    for candidate in candidates:
        u = urljoin(url, candidate)
        if safe_url(u, IMAGE_HOSTS):
            return u
    return None



def google_books_isbn(ean: str, *, getter=requests.get) -> str | None:
    """Recherche par ISBN exact uniquement ; jamais une suggestion par titre.

    Le controle du ISBN retourne par l'API evite les editions/collectors
    similaires. Pas de cle Google requise pour l'endpoint public.
    """
    if not verifier_ean(ean):
        return None
    endpoint = 'https://www.googleapis.com/books/v1/volumes'
    try:
        r = getter(endpoint, params={'q': 'isbn:'+ean, 'maxResults': 10},
                   timeout=12, headers=HEADERS, allow_redirects=True)
        r.raise_for_status()
        if urlparse(getattr(r, 'url', endpoint)).hostname != 'www.googleapis.com':
            return None
        if len(r.content) > MAX_HTML:
            return None
        for record in (r.json().get('items') or []):
            book = record.get('volumeInfo') or {}
            identifiers = book.get('industryIdentifiers') or []
            if not any(str(x.get('identifier', '')).replace('-', '') == ean for x in identifiers if isinstance(x, dict)):
                continue
            links = book.get('imageLinks') or {}
            for attr in ('extraLarge', 'large', 'medium', 'small', 'thumbnail'):
                url = links.get(attr)
                if isinstance(url, str):
                    if url.startswith('http://'):
                        url='https://'+url[7:]
                    if safe_url(url, IMAGE_HOSTS):
                        return url
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    return None


def enregistrer_couverture(url: str, dest: Path, *, getter=requests.get) -> tuple[bool, str]:
    if not safe_url(url, IMAGE_HOSTS):
        return False, 'Hote de couverture non autorise'
    try:
        r = getter(url, timeout=18, headers=HEADERS, allow_redirects=True)
        r.raise_for_status()
        if not safe_url(getattr(r, 'url', url), IMAGE_HOSTS):
            return False, 'Redirection image non autorisee'
        if len(r.content) > MAX_IMAGE:
            return False, 'Image trop lourde'
        if not r.headers.get('Content-Type', '').lower().startswith('image/'):
            return False, 'La reponse ne contient pas une image'
        with Image.open(io.BytesIO(r.content)) as im:
            im.load()
            if im.width < 180 or im.height < 250 or im.width * im.height > 12_000_000:
                return False, 'Dimensions incompatibles avec une couverture'
            ratio = im.width / im.height
            if not 0.48 <= ratio <= 0.90:
                return False, 'Image non portrait (probablement une banniere ou une maquette)'
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.convert('RGB').save(dest, format='PNG', optimize=True)
        return True, 'Couverture candidate issue de la fiche EAN — controle visuel conseille'
    except (requests.RequestException, ValueError, OSError) as exc:
        return False, f'{type(exc).__name__}: {str(exc)[:110]}'


def rapprocher(verification: dict, enquete: dict, catalogue: dict) -> dict:
    if verification.get('categorie') != 'MANGA' or enquete.get('categorie') != 'MANGA':
        raise ValueError('Rapports incompatibles')
    if verification.get('date_palmares_bede') != catalogue.get('date_palmares'):
        raise ValueError('Le catalogue fixe V5 ne correspond pas a la date du palmares actuel')
    candidates = verification.get('candidats_non_certifies') or []
    if len(candidates) < 7:
        raise ValueError('Moins de 7 titres candidats')
    refs = catalogue.get('editions') or []
    if len(refs) != 7 or len({v['rang_mixte'] for v in refs}) != 7:
        raise ValueError('Catalogue EAN incomplet ou duplique')
    refs_by_rank = {row['rang_mixte']: row for row in refs}
    out = []
    for rank, cand in enumerate(candidates[:7], 1):
        if cand.get('rang_manga_provisoire') != rank:
            raise ValueError('Rangs provisoires incoherents')
        match = refs_by_rank.get(cand.get('rang_classement_mixte'))
        if not match:
            raise ValueError('Le catalogue ne correspond pas a ces 7 rangs')
        # Faire correspondre serie, volume et edition, et non le seul rang.
        from sources.couvertures import volume, key_tokens
        src, ref = cand.get('titre', ''), match['titre']
        if volume(src) != volume(ref):
            raise ValueError('Numero de tome different : ' + str(src))
        a, b = key_tokens(src), key_tokens(ref)
        if not b or len(a & b) / len(b) < .75:
            raise ValueError('Titre ou edition differente : ' + str(src))
        if not verifier_ean(match.get('ean', '')) or not safe_url(match.get('url'), SOURCE_HOSTS):
            raise ValueError('EAN ou URL de fiche invalide')
        out.append({**match, 'rang_manga_provisoire': rank, 'titre_palmares': src})
    return {'date_palmares': catalogue['date_palmares'], 'editions': out}


def incruster_couvertures(maquette_dir: Path, output_dir: Path, editions: list[dict]) -> list[str]:
    """Ajoute les vraies couvertures au visuel existant, SANS effacer l'alerte de maquette."""
    from visual_top7 import draw_top_rank_circle, paste_cover_fit, font
    files = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for ed in reversed(editions):
        rank = ed['rang_manga_provisoire']
        number = 8 - rank
        origin = maquette_dir / f'{number:02d}_rang_{rank}_MAQUETTE.png'
        if not origin.is_file():
            raise FileNotFoundError(f'Maquette absente: {origin.name}')
        with Image.open(origin) as base:
            slide = base.convert('RGB')
        cover = output_dir / 'couvertures' / f"{ed['ean']}.png"
        if cover.is_file():
            with Image.open(cover) as pic:
                paste_cover_fit(slide, pic.convert('RGB'), (155, 245, 930, 1138), '#FFFFFF')
            d = ImageDraw.Draw(slide)
            draw_top_rank_circle(d, (20, 555, 330, 865), rank, '#F7E952', '#171717')
            d.rounded_rectangle((366, 1070, 916, 1125), radius=9, fill='#FFFFFF', outline='#B42318', width=3)
            d.text((640, 1096), 'MAQUETTE • NON CERTIFIÉE', anchor='mm', font=font(23, True), fill='#B42318')
        path = output_dir / origin.name
        slide.save(path, optimize=True)
        files.append(path.name)
    recap = maquette_dir / '08_recapitulatif_MAQUETTE.png'
    if recap.is_file():
        from shutil import copy2
        copy2(recap, output_dir / recap.name)
        files.append(recap.name)
    preview = Image.new('RGB', (1128, 730), '#E8E8E8')
    for i, name in enumerate(files):
        with Image.open(output_dir / name) as im:
            slide = im.copy()
            slide.thumbnail((270, 338))
            preview.paste(slide, ((i % 4)*282+6, (i//4)*365+6))
    preview.save(output_dir / 'apercu_V5.png', optimize=True)
    return files


def executer(rep: Path, *, getter=requests.get) -> dict:
    v = json.loads((rep/'verification_manga.json').read_text(encoding='utf-8'))
    e = json.loads((rep/'enquete_manga_v3.json').read_text(encoding='utf-8'))
    catalogue = json.loads(Path(__file__).with_name('editions_manga_v5.json').read_text(encoding='utf-8'))
    dest = rep/'maquette_v5'
    dest.mkdir(parents=True, exist_ok=True)
    data = {'version': 5, 'categorie': 'MANGA', 'execution_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'publication_instagram_autorisee': False, 'buffer': 'AUCUNE_ACTION',
            'avertissements': [], 'date_palmares': v.get('date_palmares_bede'),
            'periode_ventes': None, 'etat': 'MAQUETTE_NON_CERTIFIEE'}
    try:
        matching = rapprocher(v, e, catalogue)
        editions = matching['editions']
        infos = []
        for ed in editions:
            status = {'rang_manga_provisoire': ed['rang_manga_provisoire'], 'titre': ed['titre'],
                      'ean': ed['ean'], 'editeur': ed['editeur'], 'url_fiche': ed['url'],
                      'fiche_accessible': False, 'couverture_disponible': False}
            try:
                html = fetch_page(ed['url'], getter=getter)
                status['fiche_accessible'] = True
                image_url = extraire_image_fiche(html, ed['url'], ed['ean'])
                if not image_url:
                    status['diagnostic'] = 'Fiche sans image fiable ou EAN absent'
                else:
                    ok, msg = enregistrer_couverture(image_url, dest/'couvertures'/f"{ed['ean']}.png", getter=getter)
                    status['couverture_disponible'] = ok
                    status['diagnostic'] = msg
                    if ok:
                        status['url_image'] = image_url
            except (requests.RequestException, ValueError, OSError) as ex:
                status['diagnostic'] = f'{type(ex).__name__}: {str(ex)[:150]}'
            # Ce repli fonctionne aussi si la fiche editeur refuse GitHub (403).
            # L'ISBN exact retourne par Google Books reste obligatoire.
            if not status['couverture_disponible']:
                alt_image = google_books_isbn(ed['ean'], getter=getter)
                if alt_image:
                    ok, msg = enregistrer_couverture(alt_image, dest/'couvertures'/f"{ed['ean']}.png", getter=getter)
                    if ok:
                        status['couverture_disponible'] = True
                        status['url_image'] = alt_image
                        status['diagnostic'] = 'Google Books: ISBN exact confirme; ' + msg
            infos.append(status)
        data['editions'] = infos
        data['fiches_accessibles'] = sum(x['fiche_accessible'] for x in infos)
        data['couvertures_candidates'] = sum(x['couverture_disponible'] for x in infos)
        if (rep/'maquette_v4').is_dir():
            data['images'] = incruster_couvertures(rep/'maquette_v4', dest, editions)
        else:
            data['avertissements'].append('La maquette V4 est absente : pas de diapositives enrichies')
    except (KeyError, ValueError, FileNotFoundError) as ex:
        data['etat'] = 'A_REEXAMINER_NOUVELLE_EDITION'
        data['avertissements'].append(str(ex))
    data['recoupements_ventes'] = [
        {"titre":"Instinct - Tome 3", "periode":"2026-11-09 au 2026-11-15",
         "rang_livres_tous_genres":3,
         "preuve":"https://actualitte.com/article/135341/meilleures-ventes/le-goncourt-fait-tomber-melenchon-jaenada-prend-la-tete"},
        {"titre":"Spy x Family - tome 17", "periode":"2026-11-09 au 2026-11-15",
         "rang_livres_tous_genres":8,
         "preuve":"https://actualitte.com/article/135341/meilleures-ventes/le-goncourt-fait-tomber-melenchon-jaenada-prend-la-tete"}
    ] if data['date_palmares']=='20/11/2026' else []
    data['avertissements'].append("Deux reprises d’Edistat ne constituent pas deux panels de ventes independants.")
    data['justification'] = ('Les ISBN renseignent les editions, pas la verification du Top 7 de ventes. '
                              'Ni la periode des ventes ni une liste nationale exhaustive ne sont prouvees.')
    data['publication_instagram_autorisee'] = False
    data['buffer'] = 'AUCUNE_ACTION'
    (dest/'rapport_enrichissement_v5.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Manga V5 — edition et couverture', '',
             '**AUCUNE PUBLICATION : le classement national complet reste non certifie.**', '',
             f"Date du palmares : {data.get('date_palmares')}",
             f"Fiches accessibles : {data.get('fiches_accessibles', 0)}/7",
             f"Couvertures candidates obtenues : {data.get('couvertures_candidates', 0)}/7", '',
             'Attention : les couvertures doivent encore etre verifiees visuellement et leur droit de reproduction examine.',
             'Les sept EAN ont ete recoupes sur des fiches commerciales/editeurs; cela ne prouve pas les ventes.', '',
             '## Points en attente', '- Palmarès national exhaustif et dates des ventes',
             '- Comparaison independante des sept rangs sur la meme periode',
             '- Aucun envoi a Buffer dans cette version', '']
    for item in data.get('editions', []):
        lines.append(f"- Rang provisoire {item['rang_manga_provisoire']} : {item['titre']} — EAN {item['ean']} — "
                     f"couverture {'candidate' if item['couverture_disponible'] else 'NON RECUPEREE'}")
    (dest/'RAPPORT_V5_LIRE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"V5 manga : {data.get('fiches_accessibles', 0)}/7 fiches, {data.get('couvertures_candidates', 0)}/7 couvertures. Buffer inchange.")
    return data


def main() -> int:
    try:
        executer(Path('rapports_manga'))
    except (OSError, ValueError, KeyError) as ex:
        print('V5 : echec de la verification des editions (aucun envoi Buffer) :', ex)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
