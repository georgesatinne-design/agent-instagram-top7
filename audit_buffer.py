"""Lecture seule. Rapport agrégé : aucun texte, identifiant ou secret dans les logs."""
import json
from collections import Counter
import re
from calendrier_editorial import parse_due,reserved_kind,slot_on
from anecdotes_auto.buffer import Buffer

def category(text):
    m=re.match(r'^\s*(?:📚\s*)?TOP\s*(5|7)\s*(BD|MANGA|COMICS)\b',text,re.I)
    if m:
        n,k=m.groups();k=k.upper()
        if k=='COMICS':return 'COMICS_HEBDO' if n=='5' else 'COMICS_MENSUEL'
        return k if n=='7' else 'AUTRE'
    if text.startswith(('📚 ANECDOTE BD','📚 ANECDOTE DU 9e ART')):return 'ANECDOTE'
    if text.startswith('📰 LES 5 ACTUS DU 9e ART'):return 'ACTUS'
    return 'AUTRE'

def report(posts):
    dates=Counter();categories=Counter();off_calendar=0
    for p in posts:
        due=parse_due(p['dueAt']);kind=category(p['text'])
        dates[due.date()]+=1;categories[kind]+=1
        if kind!='AUTRE' and (due!=slot_on(due.date()) or (kind!='ANECDOTE' and reserved_kind(due.date())!=kind)):
            off_calendar+=1
    return {'lecture':'BUFFER_DIRECT','total':len(posts),'limite_gratuite':10,
            'par_categorie':dict(categories),'jours_avec_plusieurs_posts':sum(n>1 for n in dates.values()),
            'contenus_hors_calendrier':off_calendar,'plafond_depasse':len(posts)>10}

def main():
    # Aucun appel de mutation. En cas d'erreur, ne pas publier le corps de l'API.
    try:result=report(Buffer().list_scheduled())
    except Exception as exc:
        print('Lecture Buffer impossible : '+type(exc).__name__)
        raise SystemExit(1) from None
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['plafond_depasse'] or result['contenus_hors_calendrier'] or result['jours_avec_plusieurs_posts']:
        raise SystemExit(2)
if __name__=='__main__':main()
