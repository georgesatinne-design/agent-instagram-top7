"""Source unique des créneaux de production Illyadera (heure de Paris).

Aucun accès réseau, aucun appel Buffer. Le calendrier historique BD est conservé
pour compatibilité, mais ses clients de production utilisent ces règles.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG=json.loads((Path(__file__).resolve().parent/'calendrier_publication.json').read_text(encoding='utf8'))
PARIS=ZoneInfo(CONFIG['fuseau'])
RULES=CONFIG['calendrier_editorial']
TOP_MARGIN=RULES['marge_top_minutes']
ANECDOTE_MARGIN=RULES['marge_anecdote_minutes']

def aware(now=None):
    now=now if now is not None else dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('Date sans fuseau horaire')
    return now.astimezone(PARIS)

def parse_due(value):
    if isinstance(value,str):value=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    return aware(value)

def utc(value):
    return aware(value).astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def reserved_kind(day):
    for kind,rule in RULES['regles'].items():
        if day.weekday()!=rule['jour']:continue
        if rule['frequence']=='mensuelle' and (day.day-1)//7+1!=rule['occurrence']:continue
        return kind
    return None

def slot_on(day):
    kind=reserved_kind(day)
    clock=RULES['regles'][kind]['heure'] if kind else RULES['heure_anecdote']
    return dt.datetime.combine(day,dt.time.fromisoformat(clock),tzinfo=PARIS)

def validate_slot(kind,value,*,now=None,check_margin=True):
    due=parse_due(value)
    if due!=slot_on(due.date()):raise ValueError('Heure de publication hors calendrier')
    if kind!='ANECDOTE' and reserved_kind(due.date())!=kind:
        raise ValueError('Catégorie hors de son créneau réservé')
    margin=ANECDOTE_MARGIN if kind=='ANECDOTE' else TOP_MARGIN
    if check_margin and due<=aware(now)+dt.timedelta(minutes=margin):
        raise ValueError('Créneau trop proche ou passé : aucune nouvelle programmation')
    return utc(due)

def next_weekly(kind,now=None):
    local=aware(now)
    if kind not in ('BD','MANGA','COMICS_HEBDO','ACTUS'):raise ValueError('Catégorie hebdomadaire inconnue')
    for i in range(15):
        day=local.date()+dt.timedelta(days=i)
        if reserved_kind(day)==kind and slot_on(day)>local+dt.timedelta(minutes=TOP_MARGIN):
            return utc(slot_on(day))
    raise RuntimeError('Aucun créneau hebdomadaire')

def monthly_slot(year,month,now=None):
    # Bilan du mois précédent : deuxième dimanche uniquement.
    year,month=year+month//12,month%12+1
    for day in range(8,15):
        date=dt.date(year,month,day)
        if reserved_kind(date)=='COMICS_MENSUEL':
            return validate_slot('COMICS_MENSUEL',slot_on(date),now=now)
    raise RuntimeError('Dimanche mensuel absent')

def assert_arbitrated(kind,due,*,now=None):
    """En production, une nouvelle mutation doit viser le créneau arbitré.
    Aucune date de remplacement n'est calculée si le délai a expiré.
    Hors workflow, le contrôle du calendrier reste applicable au client.
    """
    exact=validate_slot(kind,due,now=now)
    path=os.environ.get('ILLYADERA_SLOT_PLAN')
    if path:
        plan=json.loads(Path(path).read_text(encoding='utf8'))
        if exact not in plan.get('slots',[]):
            raise RuntimeError('Créneau non arbitré ou modifié : aucun envoi')
    return exact

def frozen_slot(kind,computed,*,now=None):
    path=os.environ.get('ILLYADERA_SLOT_PLAN')
    if not path:return computed
    plan=json.loads(Path(path).read_text(encoding='utf8'))
    matches=[d for d in plan.get('slots',[]) if reserved_kind(parse_due(d).date())==kind]
    if len(matches)>1:raise RuntimeError('Plusieurs créneaux arbitrés pour cette catégorie')
    if matches:return validate_slot(kind,matches[0],now=now)
    # Une correction avec reçu peut ne pas avoir d'arbitrage ; la création
    # reste interdite par assert_arbitrated.
    return computed
