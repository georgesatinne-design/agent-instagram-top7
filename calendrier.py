"""Planification automatique des nouvelles éditions BD vers la Queue Buffer.
Les posts programmés peuvent être publiés par Buffer à leur échéance.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CALENDRIER = ROOT / 'calendrier_publication.json'
JOURS = {'lundi':0,'mardi':1,'mercredi':2,'jeudi':3,'vendredi':4,'samedi':5,'dimanche':6}


def prochain_creneau(categorie: str, *, now: dt.datetime | None = None, configuration: dict | None = None):
    """Retourne la prochaine heure locale et UTC. Rien si le calendrier n'est pas activé."""
    if configuration is None:
        configuration=json.loads(CALENDRIER.read_text(encoding='utf-8'))
    if configuration.get('mode_validation') != 'programmation_automatique_en_queue':
        raise ValueError('Mode de programmation automatique non activé')
    zone=ZoneInfo(configuration.get('fuseau', 'Europe/Paris'))
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None: raise ValueError('Date actuelle sans fuseau non autorisée')
    local=now.astimezone(zone)
    rule=configuration.get('publications',{}).get(categorie,{})
    if not rule.get('active',False):return None
    clock=rule.get('heure')
    try:
        hour,minute=(int(x) for x in clock.split(':'))
        if not (0<=hour<24 and 0<=minute<60):raise ValueError()
    except (TypeError,AttributeError,ValueError):
        raise ValueError(f'Heure non définie ou invalide pour {categorie} : HH:MM attendu')
    cadence=rule.get('frequence')
    if cadence not in ('quotidienne','hebdomadaire'):
        raise ValueError(f'Fréquence inconnue pour {categorie}')
    day=None
    if cadence=='hebdomadaire':
        day=JOURS.get(str(rule.get('jour','')).lower())
        if day is None: raise ValueError(f'Jour de publication manquant pour {categorie}')
    marge=int(configuration.get('delai_minimum_minutes',10))
    if not 5<=marge<=1440:raise ValueError('Délai minimum doit être entre 5 et 1440 minutes')
    minimum=local+dt.timedelta(minutes=marge)
    for ahead in range(0,16):
        date=local.date()+dt.timedelta(days=ahead)
        if day is not None and date.weekday()!=day: continue
        candidate=dt.datetime.combine(date,dt.time(hour,minute),tzinfo=zone)
        # Refuser les heures inexistantes lors des changements d'heure.
        if candidate.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None)!=candidate.replace(tzinfo=None):
            continue
        if candidate > minimum:
            return {'categorie':categorie,'date_heure_paris':candidate.isoformat(),
                    'dueAt':candidate.astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
                    'validation':'PROGRAMMATION_AUTOMATIQUE'}
    raise ValueError('Aucun créneau valide trouvé dans les 16 prochains jours')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Prévisualiser la prochaine programmation du Top 7')
    parser.add_argument('--categorie',default='BD')
    args=parser.parse_args()
    print(json.dumps(prochain_creneau(args.categorie),ensure_ascii=False,indent=2))
