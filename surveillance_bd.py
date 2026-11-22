"""Surveillance d'un classement hebdomadaire BDZoom.

Chaque semaine de ventes devient une édition unique. Si une édition a déjà
été réservée ou programmée dans Buffer, elle ne sera pas envoyée une 2e fois.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sources.collecte import collect_bd

ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / 'buffer_receipts'


def identifier_edition(data: dict, *, now: dt.datetime | None = None, max_age_days: int = 28) -> dict:
    """Valide le Top 7 et renvoie son identifiant stable à travers les exécutions."""
    if data.get('categorie') != 'BD':
        raise ValueError('Cette surveillance concerne uniquement les BD.')
    start = dt.date.fromisoformat(data['debut_ventes'])
    end = dt.date.fromisoformat(data['fin_ventes'])
    if (end - start).days != 6:
        raise ValueError('Période BD non hebdomadaire ou ambiguë.')
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ZoneInfo('Europe/Paris')).date()
    age = (today - end).days
    if age < 0:
        raise ValueError('La date de fin des ventes est dans le futur : vérifier la source.')
    if age > max_age_days:
        raise ValueError(f'Classement trop ancien ({age} jours) : aucun dépôt dans Buffer.')
    books = sorted(data['titres'], key=lambda b: b['rang'])[:7]
    if [b['rang'] for b in books] != list(range(1, 8)):
        raise ValueError('Classement incomplet : rangs 1 à 7 obligatoires.')
    digest_source = {
        'periode': [start.isoformat(), end.isoformat()],
        'rangs': [[b['rang'], ' '.join(b['titre'].strip().lower().split())] for b in books],
    }
    signature = hashlib.sha256(json.dumps(digest_source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {
        'categorie': 'BD', 'debut_ventes': start.isoformat(), 'fin_ventes': end.isoformat(),
        'edition': 'BD_' + end.isoformat(),
        'empreinte_classement': signature,
    }


def already_processed(info: dict, *, receipts: Path = STATE_DIR) -> tuple[bool, str]:
    path = receipts / (info['edition'] + '.json')
    if not path.is_file():
        return False, 'Nouveau classement détecté'
    previous = json.loads(path.read_text(encoding='utf-8'))
    status = previous.get('statut')
    if status == 'RESERVATION_AVANT_ENVOI':
        return True, 'Envoi antérieur incertain : contrôle humain de Buffer requis avant toute nouvelle tentative'
    if status == 'POST_PROGRAMME':
        if previous.get('empreinte_classement') != info['empreinte_classement']:
            return True, 'Classement de cette semaine modifié après programmation : aucune deuxième publication créée'
        return True, 'Classement déjà programmé : pas de doublon'
    raise ValueError('Registre inconnu : programmation suspendue pour éviter un doublon')


def probe(*, collect=collect_bd, receipts: Path = STATE_DIR, output: Path, now: dt.datetime | None = None) -> dict:
    data = collect()
    info = identifier_edition(data, now=now)
    seen, reason = already_processed(info, receipts=receipts)
    result = {'nouveau': not seen, 'raison': reason, **info}
    output.parent.mkdir(parents=True, exist_ok=True)
    if not seen:
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description='Vérifie si une nouvelle période BDZoom est disponible')
    parser.add_argument('--output', default='sorties/snapshot_bd_verifie.json')
    parser.add_argument('--github-output', default=os.getenv('GITHUB_OUTPUT'))
    args = parser.parse_args()
    info = probe(output=Path(args.output))
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if args.github_output:
        with open(args.github_output, 'a', encoding='utf-8') as handle:
            handle.write('new=' + str(info['nouveau']).lower() + '\n')
            handle.write('edition=' + info['edition'] + '\n')
            handle.write('signature=' + info['empreinte_classement'] + '\n')


if __name__ == '__main__':
    main()
