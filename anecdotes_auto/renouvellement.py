"""Renouvellement éditorial ponctuel des six sujets répétitifs.
Ne touche ni aux tops, ni aux actus, ni au Yellow Kid déjà validé.
Prépare tous les nouveaux médias avant édition, avec sujets de repli.
"""
import argparse
import datetime as dt
import os
from . import run
from .catalogue import bank
from .storytelling import editorial_eligible
from .buffer import Buffer,is_story,is_anecdote,parse
from calendrier_editorial import validate_slot
from controle_file import final_guard
from journal_publication import checkpoint

DATES={
 '2026-11-28':('topffer-geneve','saphir-theatre-takarazuka'),
 '2026-11-29':('bruxelles-centre-doc','verbeek-bd-a-retourner'),
 '2026-12-02':('lucky-luke-80','fenouillard-feuilleton'),
 '2026-12-05':('bruxelles-horta','mccay-pseudonyme-silas'),
 '2026-12-06':('topffer-professeur','hokusai-manga-carnets'),
 '2026-12-07':('lucky-luke-morris','dore-cinq-cents-gravures'),
}
CANDIDATES=list(dict.fromkeys([x[1] for x in DATES.values()]+['dore-cinq-cents-gravures','krazykat-brique-amour']))
PLAN=run.REPORT/'RENOUVELLEMENT.json'

def match(posts,date,old):
    same=[p for p in posts if not is_story(p) and parse(p['dueAt']).astimezone(run.PARIS).date().isoformat()==date]
    if len(same)!=1:return None
    p=same[0]
    if p['id']!=old.get('id_buffer') or p['status']!='scheduled' or not is_anecdote(p):return None
    if parse(p['dueAt'])!=parse(old['due_at']):return None
    return p

def prepare(repo,*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);buffer=buffer or Buffer()
    registry=run.get_registry();posts=buffer.list_scheduled()
    facts={f['id']:f for f in bank() if editorial_eligible(f)}
    used={r.get('fact_id') for r in registry.values() if isinstance(r,dict)}
    reserved=set();failed=set();plans=[];errors=[]
    from .recherche_images import reinitialiser_quota
    reinitialiser_quota(50)
    for date,(original,preferred) in DATES.items():
        old=registry.get(date,{})
        if old.get('fact_id')!=original:
            if old.get('etat')=='PROGRAMME' and old.get('fact_id') in CANDIDATES:
                p=match(posts,date,old)
                if p and p['text'].strip()==old['texte_public'].strip():continue
            if old.get('renouvellement_original') and old.get('etat')=='EN_ATTENTE_MAJ':
                plans.append({'date':date,'old':old['renouvellement_original'],'new':old});reserved.add(old['fact_id']);continue
            errors.append(date+': registre inattendu');continue
        p=match(posts,date,old)
        if not p or old.get('etat')!='PROGRAMME' or p['text'].strip()!=old['texte_public'].strip():
            # A higher priority may have legitimately replaced a provisional slot.
            if old.get('etat','').startswith(('SUPPLANTE','LIBERE_')):continue
            errors.append(date+': ancien post non retrouvé');continue
        try:validate_slot('ANECDOTE',old['due_at'],now=now)
        except ValueError as exc:errors.append(date+': '+str(exc));continue
        # Prefer the assigned topic, then the dedicated spare, then remaining
        # unused topics; no old stories or already published fact is eligible.
        order=[preferred,'dore-cinq-cents-gravures',*[x for x in CANDIDATES if x!=preferred]]
        for fid in dict.fromkeys(order):
            if fid in used or fid in reserved or fid in failed or fid not in facts:continue
            try:
                new=run.stage_fact(facts[fid],dt.date.fromisoformat(date),repo,now)
                new.update(etat='EN_ATTENTE_MAJ',id_buffer=old['id_buffer'],due_at=old['due_at'],
                    ancien_texte_public=old['texte_public'],ancien_fact_id=original,
                    version_visuelle=run.VERSION_VISUELLE)
                plans.append({'date':date,'old':old,'new':new})
                reserved.add(fid);print('NOUVEAU_CARROUSEL_PRET',date,fid);break
            except Exception as exc:
                failed.add(fid);print('ARCHIVES_INDISPONIBLES',fid,str(exc)[:500])
        else:errors.append(date+': aucun sujet inédit illustré disponible')
    run.write(PLAN,{'plans':plans,'erreurs':errors})
    print('PREPARATION',len(plans),errors)

def send(*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);buffer=buffer or Buffer()
    report=run.read(PLAN);errors=list(report['erreurs']);done=[]
    for row in report['plans']:
        date,old,new=row['date'],row['old'],row['new']
        try:
            registry=run.get_registry()
            p=match(buffer.list_scheduled(),date,old)
            if not p:raise RuntimeError('Identité/heure non confirmée')
            if p['text'].strip()!=new['texte_public'].strip():
                if p['text'].strip()!=old['texte_public'].strip():raise RuntimeError('Ancien texte différent')
                if registry.get(date)!=old and registry.get(date)!=new:raise RuntimeError('Registre modifié')
                validate_slot('ANECDOTE',new['due_at'],now=now)
                assets=buffer.verify_images(new['base_url'],new['images'],run.ROOT_REPO/new['dossier'])
                final_guard('ANECDOTE',new['due_at'],api_key='',channel_id='',post=None,buffer=buffer,expected_id=old['id_buffer'],now=now)
                if match(buffer.list_scheduled(),date,old)!=p:raise RuntimeError('File modifiée')
                new['renouvellement_original']=old
                registry[date]=new;run.persist(registry);checkpoint(run.REGISTRY)
                buffer.edit_own(old['id_buffer'],new['texte_public'],new['due_at'],assets)
                p=match(buffer.list_scheduled(),date,old)
                if not p or p['text'].strip()!=new['texte_public'].strip():raise RuntimeError('Relecture Buffer non confirmée')
            new.update(etat='PROGRAMME',date_confirmation=dt.datetime.now(dt.timezone.utc).isoformat())
            new.pop('renouvellement_original',None);new.pop('ancien_texte_public',None)
            registry[date]=new;run.persist(registry);checkpoint(run.REGISTRY)
            done.append([date,new['fact_id']]);print('POST_PROGRAMME NOUVEAU_SUJET',date,new['fact_id'])
        except Exception as exc:errors.append(date+': '+str(exc)[:300])
    registry=run.get_registry();posts=buffer.list_scheduled()
    remaining=[]
    for date,(original,preferred) in DATES.items():
        r=registry.get(date,{})
        if r.get('etat','').startswith(('SUPPLANTE','LIBERE_')):continue
        p=match(posts,date,r)
        if not p or r.get('fact_id') not in CANDIDATES or r.get('etat')!='PROGRAMME' or p['text'].strip()!=r.get('texte_public','').strip():
            remaining.append(date)
    print('RENOUVELLEMENT_BUFFER',done,'RESTANTES',remaining,'ERREURS',errors)
    if remaining or errors:raise SystemExit(1)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','send']);a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
