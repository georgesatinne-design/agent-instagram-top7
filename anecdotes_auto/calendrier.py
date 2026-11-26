"""Programmer les anecdotes en avance, avec priorité aux classements vérifiés."""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo
from .catalogue import CONFIG

PARIS=ZoneInfo('Europe/Paris')

def is_second_sunday(date):return date.weekday()==6 and 8<=date.day<=14

def reserved_kind(day):
    if day.weekday()==1:return 'MANGA'
    if day.weekday()==3:return 'COMICS_HEBDO'
    if day.weekday()==4:return 'BD'
    if is_second_sunday(day):return 'COMICS_MENSUEL'
    return None

def target_date_time(day):
    hour=17 if day.weekday()==4 else 18
    return dt.datetime.combine(day,dt.time(hour,0),tzinfo=PARIS)

def eligible(day,now,scheduled):
    """Un créneau libre peut recevoir une anecdote provisoire, même un jour de Top."""
    now=now.astimezone(PARIS)
    due=target_date_time(day)
    if scheduled:return False,'POST_DEJA_DANS_BUFFER'
    if due-now<dt.timedelta(minutes=CONFIG['marge_programmation_minutes']):
        return False,'CRENEAU_TROP_PROCHE'
    return True, 'PROVISOIRE_TOP' if reserved_kind(day) else 'JOUR_LIBRE'

def next_days(now):
    local=now.astimezone(PARIS)
    for i in range(CONFIG['horizon_jours']+1):
        yield local.date()+dt.timedelta(days=i)
