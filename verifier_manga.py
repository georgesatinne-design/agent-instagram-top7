"""V2: contrôle prudent du classement manga extrait par audit_manga_sources.py.

À installer à côté du diagnostic V1. Fonctionne hors ligne depuis son fichier
JSON, n'appelle aucune API de publication, ne certifie pas un Top 7 à partir
seulement des données mélangées/incomplètes de Bédé.fr.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path

# Repères internes, NON une base exhaustive des ouvrages manga.
# Un titre reconnu par ce lexique doit encore être confirmé dans une fiche
# éditeur / ISBN avant toute publication.
REPERES_MANGA = (
    "instinct", "spy x family", "atelier des sorciers", "one piece",
    "kagurabachi", "blue lock", "boruto", "bleach", "dragon ball",
    "moi quand je me reincarne en slime", "tsugai", "bloom",
    "sakamoto days", "hellsing", "jujutsu kaisen", "berserk",
    "shangri la frontier", "ruridragon", "naruto", "chainsaw man",
    "frieren", "solo leveling", "kaiju no 8", "dandadan",
    "les carnets de l apothicaire", "one punch man", "dreamland",
)


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(x for x in texte if not unicodedata.combining(x))
    return " ".join(re.findall(r"[a-z0-9]+", texte))


def repertoire_manga(titre: str) -> bool:
    t = f" {normaliser(titre)} "
    return any(f" {normaliser(nom)} " in t for nom in REPERES_MANGA)


def controle(rapport: dict) -> dict:
    if rapport.get("categorie") != "MANGA":
        raise ValueError("Le rapport ne concerne pas la categorie MANGA")
    sources = {x.get("source"): x for x in rapport.get("sources", [])}
    edistat = sources.get("edistat_top200", {})
    bede = sources.get("bede_bd_manga", {})
    actualitte = sources.get("actualitte_edistat", {})
    inspection = bede.get("inspection", {})
    entrees = inspection.get("premieres_entrees_a_verifier", [])
    rangs = []
    vus = set()
    for ligne in entrees:
        try:
            numero = int(ligne["rang_bd_manga"])
        except (TypeError, ValueError, KeyError):
            continue
        titre = str(ligne.get("titre_affiche", "")).strip()
        if numero < 1 or numero in vus or not titre:
            continue
        vus.add(numero)
        rangs.append({"rang_classement_mixte": numero, "titre": titre,
                      "categorie": "MANGA_POSSIBLE" if repertoire_manga(titre) else "NON_DETERMINEE"})
    rangs.sort(key=lambda x: x["rang_classement_mixte"])
    mangas = [x for x in rangs if x["categorie"] == "MANGA_POSSIBLE"]
    premiers = []
    for numero_manga, entree in enumerate(mangas[:7], start=1):
        premiers.append({"rang_manga_provisoire": numero_manga, **entree})
    septieme_rang_mixte = premiers[-1]["rang_classement_mixte"] if len(premiers) == 7 else None
    indetermines_avant_septieme = [x for x in rangs if x["categorie"] == "NON_DETERMINEE"
                                 and (septieme_rang_mixte is None or x["rang_classement_mixte"] < septieme_rang_mixte)]

    # Bloqué par construction : la liste Bédé ne prouve pas son exhaustivité ;
    # ActuaLitté et le Top200 général ne sont pas des classements manga complets.
    alertes = []
    if not edistat.get("accessible"):
        alertes.append("Edistat indisponible depuis GitHub (HTTP %s)" % edistat.get("status_http", "inconnu"))
    alertes.append("Bede.fr indique exclure de son affichage certains albums sans couverture/catalogue ; exhaustivite manga non prouvee")
    alertes.append("Le rapport Bede.fr indique la date du palmares, pas la periode exacte des ventes")
    if not actualitte.get("accessible"):
        alertes.append("ActuaLitte indisponible ; verification secondaire impossible")
    else:
        alertes.append("ActuaLitte fournit un classement general ou des articles, pas la preuve d'un Top 7 manga exhaustif")
    if len(premiers) < 7:
        alertes.append("Moins de sept candidats manga reconnus dans les entrees relevees")
    if indetermines_avant_septieme:
        alertes.append("Titres de categorie inconnue situes avant le septieme manga presume : classement a verifier")
    if inspection.get("rangs_manquants_jusqu_au_max"):
        alertes.append("Rangs numeriques manquants dans la liste mixte")

    return {
        "cree_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "categorie": "MANGA",
        "date_palmares_bede": inspection.get("date_palmares_affichee"),
        "periode_ventes_exacte": None,
        "source": bede.get("url"),
        "nombre_entrees_mixtes_examinees": len(rangs),
        "nombre_candidats_manga_reperes": len(mangas),
        "candidats_non_certifies": premiers,
        "indetermines_avant_7e": indetermines_avant_septieme[:30],
        "top7_national_certifie": False,
        "publication_manga_autorisee": False,
        "action_buffer": "AUCUNE",
        "decision": "NE_PAS_PUBLIER — source manga nationale exhaustive indisponible ou non verifiee",
        "alertes": alertes,
        "note": "Les numeros provisoires sont de simples rangs entre titres reconnus dans la page mixte, et NON des positions de ventes nationales certifiees. Les classifications internes sont indicatives."
    }


def sauvegarder(dossier: Path, resultat: dict) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "verification_manga.json").write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")
    lignes = ["# Vérification de fiabilité manga — V2", "", "**Publication : BLOQUÉE. Aucune action Buffer.**", "",
              f"Palmarès Bédé.fr daté : {resultat['date_palmares_bede'] or 'inconnue'}", "",
              "## Candidats reconnus (NON certifiés)", ""]
    if not resultat["candidats_non_certifies"]:
        lignes.append("Aucun candidat identifié.")
    for x in resultat["candidats_non_certifies"]:
        lignes.append(f"- Manga présumé n°{x['rang_manga_provisoire']} : rang mixte #{x['rang_classement_mixte']} — {x['titre']}")
    lignes += ["", "## Bloqueurs", ""] + [f"- {x}" for x in resultat["alertes"]]
    lignes += ["", "**Conclusion : ce rapport ne permet pas d'affirmer un véritable Top 7 des mangas les plus vendus en France.**", ""]
    (dossier / "VERIFICATION_MANGA_LIRE.md").write_text("\n".join(lignes), encoding="utf-8")


def main() -> int:
    chemin = Path(sys.argv[1] if len(sys.argv) > 1 else "rapports_manga/audit_manga.json")
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        resultat = controle(data)
        sauvegarder(chemin.parent, resultat)
        print(json.dumps({"candidats": len(resultat["candidats_non_certifies"]),
                          "top7_certifie": False, "publication": "INTERDITE",
                          "rapport": str(chemin.parent / 'verification_manga.json')}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Erreur de vérification manga (aucune publication) : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
