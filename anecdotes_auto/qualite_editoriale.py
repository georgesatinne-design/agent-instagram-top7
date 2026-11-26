"""Ordonne les anecdotes vérifiées selon leur pouvoir narratif, sans en inventer.

N'affecte ni les règles de preuve ni les contrôles photographiques.
"""
from __future__ import annotations
import re,unicodedata

def _norm(t):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(t).lower()) if not unicodedata.combining(c))

def score(fact):
    hook=_norm(fact.get('hook',''))
    body=' '.join(_norm(fact.get(k,'')) for k in ('fait','contexte','detail'))
    score=35
    if len(hook)<=62:score+=8
    if hook.endswith('?') or 'pourquoi' in hook or 'comment' in hook:score+=10
    if any(x in hook for x in ('cache','secret','coulisse','inattendu','personne','avant','derriere','mystere','sans savoir','vrai')):score+=13
    if re.search(r'\b(?:18|19|20)\d\d\b',body):score+=6
    if len(set(re.findall(r'[a-z]{5,}',body)))>=13:score+=6
    if fact.get('theme') in ('COULISSES','PERSONNAGES','HISTOIRE','PATRIMOINE'):score+=5
    if fact.get('theme') in ('COULISSES','PERSONNAGES'):score+=8
    if any(x in hook for x in ('lecteurs','chien','incendie','secondaire','concours','origine','inspire')):score+=8
    if fact.get('type_preuve') in ('SOURCE_PRIMAIRE_OFFICIELLE','SOURCE_INSTITUTIONNELLE_CORROBOREE'):score+=7
    if fact.get('type_preuve')=='METADONNEES_EDITEUR_OFFICIEL':score-=25
    if any(x in hook for x in ('trois details','pages','date de sortie','cette edition','ce tome')):score-=22
    if body.count('pages')>=1 and 'para' in body:score-=7
    if len(hook)<15:score-=6
    return max(0,min(100,score))
