"""Audit de fin de workflow. Les manques de photographies sont des avertissements,
les erreurs techniques de Buffer et les rapports manquants restent des échecs.
N'autorise jamais de publication et ne modifie aucun post Buffer.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _load_json(path: Path, expected_type):
    if not path.is_file():
        raise ValueError(f"Rapport obligatoire absent : {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"Rapport illisible : {path.name} : {exc}") from exc
    if not isinstance(value, expected_type):
        raise ValueError(f"Format invalide pour {path.name}")
    return value


def _short(value, limit=220):
    # Prevent untrusted report data from breaking the GitHub summary or annotations.
    text = str(value or "").replace("\r", " " ).replace("\n", " " )
    text = re.sub(r"[\x00-\x1f]+", " ", text)
    return text[:limit].replace("|", "/").replace("`", "'")


def inspect_reports(report_dir: Path):
    """Returns (problems, pending, updates) without treating editorial gaps as failures."""
    problems=[]
    try:
        pending = _load_json(report_dir / "REPRISES_A_FAIRE.json", list)
        etat = _load_json(report_dir / "ETAT.json", dict)
        buffer = _load_json(report_dir / "RESULTATS_BUFFER.json", dict)
    except ValueError as exc:
        return [str(exc)], [], 0
    pending=[p for p in pending if isinstance(p, dict)]
    updates=buffer.get("programmes", [])
    if not isinstance(updates, list):
        problems.append("RESULTATS_BUFFER.json : programmes doit être une liste")
        updates=[]
    if not isinstance(buffer.get("erreurs", []), list):
        problems.append("RESULTATS_BUFFER.json : erreurs doit être une liste")
    else:
        problems.extend("Buffer : "+_short(e) for e in buffer.get("erreurs", []))
    if not isinstance(etat.get("erreurs", []), list):
        problems.append("ETAT.json : erreurs doit être une liste")
    else:
        problems.extend("Exécution : "+_short(e) for e in etat.get("erreurs", []))
    if etat.get("statut") not in ("REPRISES_A_FAIRE", "EXECUTION_TERMINEE"):
        problems.append("Statut de fin inattendu : " + _short(etat.get("statut")))
    reported=etat.get("remplacements_non_effectues")
    if reported is not None and (not isinstance(reported,int) or reported!=len(pending)):
        problems.append("Incohérence des rapports : nombre de reprises différent")
    return problems,pending,len(updates)


def render_summary(problems, pending, updates):
    lines=["## Anecdotes BD — contrôle final","", f"**Publications créées ou modifiées dans Buffer : {updates}.**", ""]
    if problems:
        lines.extend(["### ❌ Problème technique", "L'automatisation doit être corrigée ; ne pas supposer que Buffer a accepté tous les changements.",""])
        lines.extend("- "+_short(s) for s in problems)
        lines.append("")
    if pending:
        lines.extend([f"### ⚠️ {len(pending)} anecdote(s) avec ancienne présentation",
            "Il manque des visuels authentiques et pertinents ou le post n'est plus modifiable.",
            "Les posts existants sont conservés, aucun doublon n'est créé ; l'agent réessaiera lors d'un prochain contrôle tant que le créneau est modifiable.",""])
        for item in pending:
            lines.append("- **"+_short(item.get('date'),22)+"** — "+_short(item.get('fact_id'),72)+" : "+_short(item.get('raison'),200))
        lines.extend(["","Détail : artifact **rapport-anecdotes-bd**, fichier `REPRISES_A_FAIRE.json`.",""])
    if not problems and not pending:
        lines.extend(["### ✅ Contrôle terminé","Aucune anecdote en attente de reprise et aucune erreur technique détectée.",""])
    return "\n".join(lines)+"\n"


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=Path("sorties/anecdotes_bd"))
    args=parser.parse_args(argv)
    problems,pending,updates=inspect_reports(args.report_dir)
    summary=render_summary(problems,pending,updates)
    print(summary)
    dest=os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with Path(dest).open("a",encoding="utf-8") as f:
            f.write(summary)
    for p in pending:
        message=_short(f"{p.get('date')}: {p.get('fact_id')} : {p.get('raison')}",300)
        print("::warning title=Anecdote à moderniser::"+message)
    for problem in problems:
        print("::error title=Incident technique anecdotes::"+_short(problem,300))
    return 1 if problems else 0


if __name__=="__main__":
    sys.exit(main())
