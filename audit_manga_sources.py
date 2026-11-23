"""Diagnostic des sources gratuites de ventes manga en France.

Aucune publication, aucun appel Buffer, aucun classement manga inventé.
Le but est de vérifier quelles pages sont lisibles par GitHub Actions,
leurs dates et les éventuels rangs manquants avant d'activer un agent.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "edistat_top200": "https://www.edistat.com/palmares.php",
    "bede_bd_manga": "https://www.bede.fr/meilleures-ventes",
    "actualitte_edistat": "https://actualitte.com/thematique/70/meilleures-ventes",
    "bdzoom_manga": "https://www.bdzoom.com/mangas/",
}
ALLOWED = {urlparse(u).hostname for u in SOURCES.values()}
USER_AGENT = "Mozilla/5.0 (compatible; AgentTop7MangaDiagnostic/1.0; sources publiques)"
MAX_BYTES = 3_000_000


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def bede_report(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    raw_text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"palmar[eè]s\s+du\s+(\d{2}/\d{2}/\d{4})", raw_text, re.I)
    date = m.group(1) if m else None
    ranks = {}
    for img in soup.find_all("img", alt=True):
        alt = clean(img.get("alt", ""))
        if not alt or len(alt) > 240:
            continue
        for ancestor in list(img.parents)[:5]:
            if ancestor.name not in ("div", "article", "li"):
                continue
            content = clean(ancestor.get_text(" ", strip=True))
            if len(content) > 450:
                continue
            rank = re.search(r"(?:^|\s)#\s*(\d{1,3})(?=\s|$)", content)
            if rank:
                num = int(rank.group(1))
                if 1 <= num <= 200 and num not in ranks:
                    ranks[num] = {"rang_bd_manga": num, "titre_affiche": alt}
                break
    highest = max(ranks) if ranks else 0
    return {
        "date_palmares_affichee": date,
        "nb_rangs_detectes": len(ranks),
        "rangs_manquants_jusqu_au_max": [i for i in range(1, highest + 1) if i not in ranks][:50],
        "premieres_entrees_a_verifier": [ranks[k] for k in sorted(ranks)[:65]],
        "exhaustivite_mangas": "NON_VERIFIEE",
        "avertissement": "Bédé.fr peut omettre des albums absents de son catalogue ou sans couverture. Ces rangs sont ceux de son Top BD/manga/comics, PAS un Top 7 manga certifié.",
    }


def article_links(html: str, base_url: str, *, limit: int = 8) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for link in soup.find_all("a", href=True):
        title = clean(link.get_text(" ", strip=True))
        url = urljoin(base_url, link["href"])
        if url in seen or urlparse(url).hostname != urlparse(base_url).hostname:
            continue
        if "/article/" in url and title and len(title) >= 18:
            seen.add(url)
            links.append({"titre": title[:170], "url": url})
        elif "bdzoom.com" in base_url and "meilleures ventes de mangas" in title.lower():
            seen.add(url)
            links.append({"titre": title[:170], "url": url})
        if len(links) >= limit:
            break
    return links


def fetch_source(name: str, url: str, *, session=None) -> dict:
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED:
        raise ValueError("Domaine non autorisé")
    session = session or requests
    result = {"source": name, "url": url, "accessible": False}
    try:
        response = session.get(url, timeout=20, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        result["status_http"] = response.status_code
        final_host = urlparse(response.url).hostname
        if final_host not in ALLOWED:
            raise ValueError("Redirection inattendue vers un autre domaine")
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError("Page trop volumineuse")
        body = response.text
        soup = BeautifulSoup(body, "html.parser")
        result["accessible"] = True
        result["titre_page"] = clean((soup.title.get_text(' ', strip=True) if soup.title else ''))[:160]
        result["taille_html_octets"] = len(response.content)
        if name == "bede_bd_manga":
            result["inspection"] = bede_report(body)
        elif name in ("actualitte_edistat", "bdzoom_manga"):
            result["articles_detectes"] = article_links(body, url)
        elif name == "edistat_top200":
            result["inspection"] = {
                "presence_rangs": bool(re.search(r"\b(?:palmar[eè]s|top\s*200)\b", soup.get_text(" ", strip=True), re.I)),
                "note": "La disponibilité de la page ne suffit pas : il faut encore vérifier la présence effective des 200 lignes, de leurs identifiants et des dates de ventes."
            }
    except (requests.RequestException, ValueError) as exc:
        result["erreur"] = f"{type(exc).__name__}: {str(exc)[:250]}"
    return result


def audit(*, session=None, timestamp=None) -> dict:
    stamp = timestamp or dt.datetime.now(dt.timezone.utc)
    sources = [fetch_source(k, v, session=session) for k, v in SOURCES.items()]
    return {
        "date_controle_utc": stamp.isoformat(),
        "categorie": "MANGA",
        "publication_instagram": "DESACTIVEE",
        "queue_buffer": "NON_MODIFIEE",
        "top7_national_certifie": False,
        "sources": sources,
        "decision": "AUDIT_UNIQUEMENT : vérifier les 7 meilleurs mangas sur un palmarès complet, les dates exactes et l'identité des volumes avant toute activation.",
    }


def write_audit(folder: Path, report: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'audit_manga.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ["# Audit des sources manga", "", f"Date UTC : {report['date_controle_utc']}", "", "**Aucune publication ni programmation Buffer.**", ""]
    for src in report['sources']:
        lines.append(f"## {src['source']}")
        lines.append(f"- Accessibilité : {'OK' if src['accessible'] else 'ÉCHEC'}")
        lines.append(f"- Adresse : {src['url']}")
        if 'status_http' in src:
            lines.append(f"- Réponse HTTP : {src['status_http']}")
        if src.get('erreur'):
            lines.append(f"- Erreur : {src['erreur']}")
        if 'inspection' in src:
            for k,v in src['inspection'].items():
                if k != 'premieres_entrees_a_verifier':
                    lines.append(f"- {k} : {v}")
        if 'articles_detectes' in src:
            for link in src['articles_detectes'][:4]:
                lines.append(f"- Article repéré : {link['titre']} — {link['url']}")
        lines.append('')
    lines.append('**Résultat : il faut examiner les sources avant de certifier un Top 7 manga national.**')
    (folder / 'LIRE_LE_RAPPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    report = audit()
    write_audit(Path('rapports_manga'), report)
    print(json.dumps({"controle": report['date_controle_utc'], "sources": {x['source']: x['status_http'] if 'status_http' in x else x.get('erreur') for x in report['sources']}, "publication": "DESACTIVEE"}, ensure_ascii=False, indent=2))
