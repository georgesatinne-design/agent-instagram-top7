"""Remplacement demandé pour le 9 décembre 2026 uniquement.
Conserve le post existant jusqu'à confirmation des cinq médias.
Ne crée et ne supprime aucun post, ne traite aucune autre date.
"""
import argparse
import datetime as dt
import os
from pathlib import Path
from . import run
from .catalogue import bank,read,write
from .storytelling import editorial_eligible
from .buffer import Buffer,is_story,parse,is_anecdote
from calendrier_editorial import validate_slot
from controle_file import final_guard

DATE='2026-12-09'
DUE='2026-12-09T17:00:00.000Z'
ORIGINAL='bruxelles-textile'
TARGET='yellowkid-guerre-journaux'
POST_ID='6b080d9ab56cc066e5bdbba3'
PLAN=run.REPORT/'EXEMPLE_9_DECEMBRE.json'

def matching(buffer,old):
    posts=buffer.list_scheduled()
    same=[p for p in posts if not is_story(p) and parse(p['dueAt']).astimezone(run.PARIS).date().isoformat()==DATE]
    if len(same)!=1:raise RuntimeError('Créneau absent ou en conflit')
    p=same[0]
    if p['id']!=POST_ID or p['status']!='scheduled' or not is_anecdote(p) or parse(p['dueAt'])!=parse(DUE):
        raise RuntimeError('Identité ou horaire inattendu : aucun changement')
    return p

def prepare(repo,*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    buffer=buffer or Buffer()
    validate_slot('ANECDOTE',DUE,now=now)
    registry=run.get_registry()
    old=registry.get(DATE,{})
    p=matching(buffer,old)
    if old.get('fact_id')==TARGET and p['text'].strip()==old.get('texte_public','').strip():
        write(PLAN,{'already':True});return
    if old.get('etat')!='PROGRAMME' or old.get('fact_id')!=ORIGINAL or old.get('id_buffer')!=POST_ID or p['text'].strip()!=old.get('texte_public','').strip():
        raise RuntimeError('Anecdote initiale non identifiée')
    facts={f['id']:f for f in bank()}
    fact=facts[TARGET]
    if not editorial_eligible(fact) or any(r.get('fact_id')==TARGET for d,r in registry.items() if d!=DATE and isinstance(r,dict)):
        raise RuntimeError('Sujet déjà utilisé ou non admissible')
    # Archive originale authentifiée par empreinte, alternatives documentées.
    new=run.stage_fact(fact,dt.date.fromisoformat(DATE),repo,now)
    new.update(etat='EN_ATTENTE_MAJ',id_buffer=POST_ID,due_at=DUE,ancien_texte_public=old['texte_public'],
               ancien_fact_id=ORIGINAL,version_visuelle=run.VERSION_VISUELLE)
    write(PLAN,{'old':old,'new':new})
    print('Exemple préparé :',TARGET)

def send(*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    buffer=buffer or Buffer()
    plan=read(PLAN)
    if plan.get('already'):print('Exemple déjà programmé');return
    old,new=plan['old'],plan['new']
    registry=run.get_registry()
    if registry.get(DATE)!=old:raise RuntimeError('Registre modifié depuis la préparation')
    p=matching(buffer,old)
    if p['text'].strip()!=old['texte_public'].strip():raise RuntimeError('Ancien texte modifié')
    validate_slot('ANECDOTE',DUE,now=now)
    assets=buffer.verify_images(new['base_url'],new['images'],run.ROOT_REPO/new['dossier'])
    final_guard('ANECDOTE',DUE,api_key='',channel_id='',post=None,buffer=buffer,expected_id=POST_ID,now=now)
    if matching(buffer,old)['text'].strip()!=old['texte_public'].strip():raise RuntimeError('Ancien texte modifié')
    # Persist the recovery intent before the remote edit.
    from journal_publication import checkpoint
    registry[DATE]=new
    run.persist(registry)
    checkpoint(run.REGISTRY)
    result=buffer.edit_own(POST_ID,new['texte_public'],DUE,assets)
    live=matching(buffer,old)
    if live['text'].strip()!=new['texte_public'].strip():raise RuntimeError('Nouveau texte non confirmé dans Buffer')
    new.update(etat='PROGRAMME',date_confirmation=now.isoformat(),due_at=DUE)
    new.pop('ancien_texte_public',None)
    run.persist(registry)
    checkpoint(run.REGISTRY)
    print('POST_PROGRAMME',DATE,TARGET,'5 pages, même identifiant et même horaire')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['prepare','send'])
    a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
