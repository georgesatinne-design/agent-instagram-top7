"""Enquête complémentaire manga V3 — comparaison de sources publiques.

Ne fabrique jamais de Top 7, ne touche ni à Buffer ni à l'agent BD.
Edistat répondait 403 sur palmares.php lors de l'audit GitHub V1 :
on teste simplement sa page d'accueil publique, sans contourner la restriction.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "edistat_accueil": "https://www.edistat.com/",
    "mangactu_classements": "https://mang-actu.com/classements-des-ventes/",
    "glenat_gfk": "https://www.glenat.com/manga/meilleures-ventes/",
}
TIMEOUT = 15
MAX_BYTES = 2_000_000
USER_AGENT = "AgentTop7MangaDiagnostic/3.0 (verification de pages publiques; pas d'indexation)"
RE_FR = re.compile(r"(?:les\s+)?5\s+mangas\s+les\s+plus\s+vendus\s+en\s+France\s+du\s+(\d{2}/\d{2})\s+au\s+(\d{2}/\d{2})", re.I)
RE_DAY = re.compile(r"\b(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre)\s+(20\d{2})", re.I)
MONTHS = {"janvier":1, "fevrier":2, "mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}


def safe_get(url, *, session=None):
    """Requêtes limitées aux URL fixes publiques. Pas de login/bypass."""
    host = urlparse(url).hostname
    if host not in {urlparse(u).hostname for u in SOURCES.values()} or urlparse(url).scheme != "https":
        raise ValueError("URL non autorisée")
    client = session if session is not None else requests
    resp = client.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    if urlparse(resp.url).hostname != host:
        raise ValueError("Redirection externe non autorisée")
    resp.raise_for_status()
    if len(resp.content) > MAX_BYTES:
        raise ValueError("Page trop volumineuse")
    return resp.text


def _normalize(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize('NFKD', s.lower())
    return ''.join(x for x in s if not unicodedata.combining(x))


def date_du_libelle(s):
    m = RE_DAY.search(s)
    if not m:
        return None
    return dt.date(int(m.group(3)), MONTHS[_normalize(m.group(2))], int(m.group(1)))


def analyser_mangactu(html, *, aujourd_hui=None):
    """Détecte un classement top5 *France*, sans le prendre pour un top7."""
    today = aujourd_hui or dt.date.today()
    soup = BeautifulSoup(html, 'html.parser')
    trouves = []
    for a in soup.find_all('a', href=True):
        text = a.get_text(' ', strip=True)
        m = RE_FR.search(text)
        if not m:
            continue
        # Année prise dans l'horodatage de l'article, sinon ne pas présumer.
        publication = date_du_libelle(text)
        if not publication:
            # URL d'articles Mang'Actu sans année explicite, impossible de
            # déterminer avec certitude la période : on le note.
            publication = None
        period = None
        if publication:
            annee = publication.year
            try:
                debut = dt.datetime.strptime(m.group(1)+f'/{annee}', '%d/%m/%Y').date()
                fin = dt.datetime.strptime(m.group(2)+f'/{annee}', '%d/%m/%Y').date()
                if fin < debut:
                    debut = debut.replace(year=annee-1)
                period = {"debut": str(debut), "fin": str(fin)}
            except ValueError:
                pass
        url = urljoin(SOURCES['mangactu_classements'], a.get('href'))
        if urlparse(url).hostname != urlparse(SOURCES['mangactu_classements']).hostname:
            continue
        trouves.append({"article":text[:180], "url":url,
                       "publication": str(publication) if publication else None,
                       "periode":period})
    # Si des dates sont reconnues, la plus récente l'emporte.
    trouves.sort(key=lambda t:t['publication'] or '', reverse=True)
    item = trouves[0] if trouves else None
    age = (today - dt.date.fromisoformat(item['publication'])).days if item and item['publication'] else None
    return {"top5_france_detectes":len(trouves), "dernier_top5_france":item,
            "age_derniere_publication_jours":age,
            "a_jour_moins_14_jours": age is not None and 0 <= age <= 14,
            "permet_top7_france":False,
            "note":"Un Top 5 (même récent) ne permet pas de prouver les rangs 6 et 7."}


def analyser_glenat(html):
    soup = BeautifulSoup(html, 'html.parser')
    txt = soup.get_text(' ', strip=True)
    return {"source_affirme_gfk": bool(re.search(r"\bGfK\b", txt, re.I)),
            "mention_mise_a_jour_mercredi": bool(re.search(r"mise\s+à\s+jour\s+le\s+mercredi",txt,re.I)),
            "portee":"catalogue d'un seul éditeur : Glénat",
            "permet_top7_france":False}


def etudier(audit, verification, *, session=None, aujourd_hui=None):
    """Refuse de certifier une édition lorsque la preuve d'exhaustivité manque."""
    if audit.get('categorie') != 'MANGA' or verification.get('categorie') != 'MANGA':
        raise ValueError('Le diagnostic et la vérification V2 doivent concerner MANGA')
    today = aujourd_hui or dt.date.today()
    s = {v.get('source'):v for v in audit.get('sources', [])}
    probes = {}
    for key,url in SOURCES.items():
        item = {"url":url,"accessible":False}
        try:
            html = safe_get(url,session=session)
            item['accessible'] = True
            item['status_http'] = 200
            if key == 'mangactu_classements':
                item['analyse'] = analyser_mangactu(html,aujourd_hui=today)
            elif key == 'glenat_gfk':
                item['analyse'] = analyser_glenat(html)
            elif key == 'edistat_accueil':
                item['analyse'] = {"page_accueil_visible":True,"palmares_protege":not s.get('edistat_top200',{}).get('accessible',False),
                                   "note":"La page d'accueil publique ne donne pas accès à un Top 7 manga complet."}
        except (requests.RequestException, ValueError) as e:
            item['erreur'] = str(e)[:220]
            item['status_http'] = getattr(getattr(e,'response',None),'status_code',None)
        probes[key] = item
    bede = s.get('bede_bd_manga',{})
    insp = bede.get('inspection',{})
    manquants = insp.get('rangs_manquants_jusqu_au_max', [])
    points = [
      {"critere":"Palmarès national complet par catégorie MANGA", "valide":False,
       "preuve":"Aucune des sources testées ne fournit 7 rangs manga nationaux complets sur une semaine précise."},
      {"critere":"Période hebdomadaire de ventes explicitement rattachée aux 7 rangs", "valide":False,
       "preuve":"La date de mise à jour Bédé.fr et la date de période de ventes ne sont pas équivalentes."},
      {"critere":"Absence démontrable d'omissions de titres avant le 7e rang", "valide":False,
       "preuve":"Bédé.fr avertit que des ouvrages absents du catalogue ou sans couverture peuvent être omis."},
      {"critere":"Identification de tous les titres précédant le 7e manga", "valide":False,
       "preuve":"Des rangs mixtes précédant le 7e candidat restent de catégorie inconnue."},
    ]
    return {
      "version":3,"controle_date":today.isoformat(), "categorie":"MANGA",
      "sources_complementaires":probes,
      "palmares_bede":{"date_affichee":insp.get('date_palmares_affichee'),
                         "nombre_rangs_detectes":insp.get('nb_rangs_detectes'),
                         "rangs_num_manquants":manquants,
                         "attention":"Rangs continus ne signifient pas exhaustivité : des titres peuvent manquer avant extraction."},
      "candidats_provisoires_v2":verification.get('candidats_non_certifies', []),
      "indetermines_avant_septieme":verification.get('indetermines_avant_7e', []),
      "preuves_requises":points,
      "top7_national_certifie":False,
      "publication_manga_autorisee":False,
      "buffer":"AUCUNE_ACTION",
      "decision":"SOURCE_INSUFFISANTE — attendre un palmarès MANGA français hebdomadaire complet et vérifiable",
      "autre_piste":"Demander au détenteur des données (Edistat/NielsenIQ) une publication gratuite exploitable et autorisée, sans supposer de droit d'accès ni contourner un blocage."
    }


def sauvegarder(folder,report):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'enquete_manga_v3.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ["# Enquête complémentaire manga V3", "", "**Aucune publication Instagram ou Buffer.**", "",
             f"Date du contrôle : {report['controle_date']}", "", "## Sources françaises supplémentaires", ""]
    for name,x in report['sources_complementaires'].items():
        lines += [f"- **{name}** : {'accessible' if x['accessible'] else 'inaccessible'} — {x['url']}"]
        if x.get('erreur'):lines.append(f"  - Erreur : {x['erreur']}")
        if name=='mangactu_classements' and x.get('analyse'):
            a=x['analyse'];last=a['dernier_top5_france'];
            lines.append("  - Dernier Top 5 France : " + (last['article'] if last else 'non détecté'))
            lines.append("  - Récent : " + ('oui' if a['a_jour_moins_14_jours'] else 'non / non datable'))
        if name=='glenat_gfk':lines.append("  - Limite : uniquement les livres de Glénat, pas tout le marché français")
    lines += ["","## Conditions avant certification", ""]
    for p in report['preuves_requises']:
        lines.append(f"- {'OK' if p['valide'] else 'NON DÉMONTRÉ'} — {p['critere']} : {p['preuve']}")
    lines += ["","**Verdict : classement manga national Top 7 non certifié.**", "La BD et la Queue Buffer ne sont pas modifiées.",""]
    (folder/'ENQUETE_MANGA_V3_LIRE.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    folder=Path('rapports_manga')
    try:
        audit=json.loads((folder/'audit_manga.json').read_text(encoding='utf-8'))
        verification=json.loads((folder/'verification_manga.json').read_text(encoding='utf-8'))
        report=etudier(audit,verification)
        sauvegarder(folder,report)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print('Enquête V3 échouée, publication manga désactivée :',e)
        return 1
    print('Enquête V3 :',len(report['sources_complementaires']),'sources complémentaires. Publication manga désactivée.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
