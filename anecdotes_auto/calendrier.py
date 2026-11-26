"""Les anecdotes occupent les créneaux libres, provisoirement sur les jours de Top."""
from __future__ import annotations
import datetime as dt
from .catalogue import CONFIG
from calendrier_editorial import PARIS,aware,reserved_kind,slot_on,ANECDOTE_MARGIN

def is_second_sunday(date):return reserved_kind(date)=='COMICS_MENSUEL'

def target_date_time(day):return slot_on(day)

def eligible(day,now,scheduled):
    now=aware(now)
    if scheduled:return False,'POST_DEJA_DANS_BUFFER'
    if target_date_time(day)-now<=dt.timedelta(minutes=ANECDOTE_MARGIN):
        return False,'CRENEAU_TROP_PROCHE'
    return True,'PROVISOIRE_TOP' if reserved_kind(day) else 'JOUR_LIBRE'

def next_days(now):
    local=aware(now)
    for i in range(CONFIG['horizon_jours']+1):
        yield local.date()+dt.timedelta(days=i)
