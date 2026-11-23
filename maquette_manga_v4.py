"""V4 manga : produire 8 diapositives de MAQUETTE à partir du diagnostic.

IMPORTANT: les candidats ne sont PAS un Top 7 de ventes certifié.
Ce programme n'importe pas Buffer et ne peut rien programmer/publier.
Les périodes de ventes ne sont jamais déduites de la date du palmarès.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

from visual_top7 import (
    W, H, DESIGN, base_image, draw_text_center, draw_top_rank_circle,
    font, label, pill, style_for_category,
)

WARNING = 'MAQUETTE NON CERTIFIÉE'
FOOTER = 'NON PUBLIABLE • VENTES À VÉRIFIER'


def choisir_candidats(verification: dict, enquete: dict) -> list[dict]:
    """Choisit les sept rangs *PROVISOIRES* de la V2 sans les certifier."""
    if verification.get('categorie') != 'MANGA' or enquete.get('categorie') != 'MANGA':
        raise ValueError('Rapports manga incompatibles')
    # Ce générateur est uniquement pour les rapports refusés, pas un raccourci
    # pour publier le jour où une source fiable sera enfin trouvée.
    if verification.get('publication_manga_autorisee') or enquete.get('publication_manga_autorisee'):
        raise ValueError('Cette maquette ne traite pas les éditions certifiées; utiliser le pipeline validé')
    rows = verification.get('candidats_non_certifies', [])
    if len(rows) < 7:
        raise ValueError(f'Seulement {len(rows)} candidats manga; impossible de faire une maquette de 7 rangs')
    out, seen = [], set()
    for expected, row in enumerate(rows[:7], 1):
        rang = row.get('rang_manga_provisoire')
        mix = row.get('rang_classement_mixte')
        title = str(row.get('titre') or '').strip()
        if type(rang) is not int or rang != expected or type(mix) is not int or mix in seen or not title:
            raise ValueError('Rang provisoire, rang mixte ou titre invalide')
        if not title.strip() or len(title) > 350:
            raise ValueError('Titre trop long')
        seen.add(mix)
        # Le libellé peut contenir l'éditeur après le dernier " - ".
        # Cette valeur reste PROVISOIRE et devra être confrontée à la fiche éditeur.
        if ' - ' in title:
            nom, editeur = title.rsplit(' - ', 1)
            if not 1 <= len(editeur) <= 35:
                nom, editeur = title, ''
        else:
            nom, editeur = title, ''
        out.append({'rang': expected, 'rang_mixte': mix, 'titre': nom.strip(),
                    'editeur_indicatif': editeur.strip() or 'À VÉRIFIER'})
    if any(out[i]['rang_mixte'] >= out[i+1]['rang_mixte'] for i in range(6)):
        raise ValueError('Les rangs mixtes ne sont pas dans le même ordre')
    return out


def palmares_date(verification: dict, audit: dict) -> str:
    """La date de publication n'est pas une période de ventes."""
    a = verification.get('date_palmares_bede')
    sources = {s.get('source'): s for s in audit.get('sources', [])}
    b = sources.get('bede_bd_manga', {}).get('inspection', {}).get('date_palmares_affichee')
    if not a or a != b:
        raise ValueError('Dates du palmarès Bédé.fr absentes ou contradictoires')
    return dt.datetime.strptime(a, '%d/%m/%Y').date().strftime('%d/%m/%Y')


def _fitted_lines(draw, text: str, width: int, height: int, *, initial=42, minimum=19):
    rows, f, lh = label(text, width, height, start=initial, minimum=minimum, draw=draw)
    return rows, f, lh


def render_maquette(verification: dict, enquete: dict, audit: dict, dossier: Path,
                    *, background: Path | None = None, chart_path: Path | None = None) -> dict:
    if audit.get('categorie') != 'MANGA':
        raise ValueError('Source de diagnostic non manga')
    date = palmares_date(verification, audit)
    top = choisir_candidats(verification, enquete)
    dest = Path(dossier)
    dest.mkdir(parents=True, exist_ok=True)
    if chart_path is None:
        chart_path = DESIGN
    chart = json.loads(Path(chart_path).read_text(encoding='utf-8'))
    style, source_bg = style_for_category('MANGA', chart)
    fond = Path(background) if background else source_bg
    if not fond.exists():
        raise FileNotFoundError(f'Fond manga original introuvable : {fond}')
    noir = style['violet']; blanc = style['blanc']; jaune = style['rond']
    out = []

    def footer(img, index: int) -> None:
        pill(img, (16, 1261, 1064, 1343), noir, radius=10)
        d = ImageDraw.Draw(img)
        d.text((34, 1270), 'TOP 7 MANGA • PROJET', font=font(28, True), fill=blanc)
        d.text((34, 1311), f'PALMARÈS DU {date} • VENTES NON DATÉES', font=font(21, True), fill=blanc)
        d.text((1040, 1285), f'{index}/8', font=font(24, True), fill=jaune, anchor='ra')

    for index, book in enumerate(reversed(top), 1):
        im = base_image(fond)
        pill(im, (16, 55, 1064, 179), noir, radius=6)
        d = ImageDraw.Draw(im)
        title = book['titre']
        rows, f, lh = _fitted_lines(d, title, 960, 94, initial=52, minimum=25)
        first_y = 115 - (len(rows) * lh / 2) + lh/2
        for j, line in enumerate(rows):
            draw_text_center(d, (540, first_y+j*lh), line, f.size, blanc)
        pill(im, (170, 184, 910, 235), blanc, stroke=noir, radius=12)
        editeur = 'ÉDITEUR À VÉRIFIER' if book['editeur_indicatif'] == 'À VÉRIFIER' else f'ÉDITEUR INDICATIF : {book["editeur_indicatif"]}'
        rows, f, lh = _fitted_lines(ImageDraw.Draw(im), editeur, 680, 38, initial=22, minimum=16)
        draw_text_center(ImageDraw.Draw(im), (540, 209), rows[0], f.size, noir)
        pill(im, (148, 239, 939, 1143), blanc, stroke=noir, radius=8)
        d = ImageDraw.Draw(im)
        draw_text_center(d, (565, 580), 'COUVERTURE À CONFIRMER', 35, noir)
        draw_text_center(d, (565, 634), 'ÉDITION FRANÇAISE EXACTE', 27, noir)
        # Ce filigrane empêche l'utilisation accidentelle comme vrai classement.
        draw_text_center(d, (565, 735), 'MAQUETTE NON CERTIFIÉE', 32, '#B42318')
        draw_top_rank_circle(d, (20, 555, 330, 865), book['rang'], jaune, noir)
        pill(im, (540, 1159, 1064, 1240), blanc, stroke=noir, radius=16)
        draw_text_center(ImageDraw.Draw(im), (805, 1196), 'RANG PROVISOIRE', 26, noir)
        footer(im, index)
        path = dest / f'{index:02d}_rang_{book["rang"]}_MAQUETTE.png'
        im.save(path, optimize=True)
        out.append(path)

    im = base_image(fond)
    pill(im, (16, 50, 1064, 192), noir, radius=8)
    draw_text_center(ImageDraw.Draw(im), (540, 121), 'TOP 7 • MAQUETTE', 57, blanc)
    pill(im, (42, 211, 1038, 1214), noir, radius=23)
    for i, book in enumerate(top):
        y = 237 + i*135
        pill(im, (67, y, 1013, y+115), blanc, radius=13)
        draw_top_rank_circle(ImageDraw.Draw(im), (84, y+12, 175, y+103), book['rang'], jaune, noir)
        d = ImageDraw.Draw(im)
        rows, f, lh = _fitted_lines(d, book['titre'], 570, 63, initial=34, minimum=17)
        for j, row in enumerate(rows):
            d.text((204, y+32 - ((len(rows)-1)*lh/2)+j*lh), row, font=f, fill=noir)
        d.text((205, y+87), f'Éditeur indicatif : {book["editeur_indicatif"]}', font=font(17), fill=noir)
        pill(im, (794, y+33, 998, y+87), blanc, stroke=noir, radius=12)
        draw_text_center(ImageDraw.Draw(im), (895, y+60), 'À VÉRIFIER', 18, noir)
    footer(im, 8)
    path = dest / '08_recapitulatif_MAQUETTE.png'
    im.save(path, optimize=True)
    out.append(path)

    preview = Image.new('RGB', (4*282, 2*365), '#DDDDE3')
    for i, p in enumerate(out):
        with Image.open(p) as slide:
            slide.thumbnail((270, 338))
            preview.paste(slide, ((i % 4)*282+6, (i // 4)*365+6))
    preview.save(dest/'apercu_MAQUETTE.png', optimize=True)

    caption = ('MAQUETTE INTERNE — NE PAS PUBLIER\n'
               'Top 7 manga provisoire, non certifié.\n'
               'La période de ventes et les couvertures restent à vérifier.\n')
    (dest/'legende_MAQUETTE.txt').write_text(caption, encoding='utf-8')
    info = {
        'version': 4, 'categorie': 'MANGA', 'date_palmares_observe': date,
        'periode_de_ventes': None, 'top7_national_certifie': False,
        'publication_instagram_autorisee': False, 'queue_buffer': 'NON_MODIFIEE',
        'couvertures_verifiees': False, 'images': [p.name for p in out],
        'rangs_candidats_non_certifies': top,
        'motif': 'Source incomplète, catégorie et période non prouvées; ces images sont une maquette uniquement.'
    }
    (dest/'rapport_MAQUETTE.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest/'A_LIRE_AVANT_USAGE.md').write_text(
        '# Maquette manga V4 — NON PUBLIABLE\n\n'
        'Ces huit images utilisent le fond manga original et la structure 7 → 1 + récapitulatif.\n'
        'Elles ne sont **pas** un Top 7 national certifié. Ne pas les transférer dans Buffer.\n\n'
        f'Palmarès Bédé.fr observé le **{date}** ; période de ventes exacte **inconnue**.\n'
        'Les rangs sont uniquement l’ordre des 7 candidats reconnus par la V2.\n'
        'Les couvertures et éditeurs sont à vérifier avec les éditions françaises exactes.\n'
        'La source est conservée dans le rapport technique V1/V2/V3, non dans le texte public.\n', encoding='utf-8')
    return info


def main() -> int:
    folder = Path('rapports_manga')
    required = ['verification_manga.json', 'enquete_manga_v3.json', 'audit_manga.json']
    try:
        v, e, a = [json.loads((folder/name).read_text(encoding='utf-8')) for name in required]
        info = render_maquette(v, e, a, folder/'maquette_v4')
    except (OSError, ValueError, KeyError, TypeError) as ex:
        print('MAQUETTE MANGA V4 : impossible de créer un aperçu, Buffer inchangé :', ex)
        return 1
    print('MAQUETTE MANGA V4 :', len(info['images']), 'images non certifiées; aucune publication, aucun Buffer.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
