"""Actualités du lundi : création -> médias publics -> confirmation Buffer.
Une seule édition à la fois, pas de création à l'aveugle après interruption.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from PIL import Image,ImageDraw
from anecdotes_auto.visuels import font,text_fit,NIGHT,CREAM,YELLOW,PURPLE
from anecdotes_auto.buffer import Buffer,CREATE,EDIT,is_anecdote,is_story,parse
from calendrier_editorial import next_weekly,parse_due,validate_slot
from illyadera_queue import free_capacity_for_priority,read_registry,save_registry,REGISTRY
from journal_publication import checkpoint
from controle_file import final_guard
from media_preflight import verify_public_assets
from .collecte import collect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'sorties'/'actus_9e_art'
STATE=ROOT/'actus_state'
PREFIX='📰 LES 5 ACTUS DU 9e ART'
def read(p,default=None):
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else default
def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8');tmp.replace(p)
def render(items,folder,day):
    folder.mkdir(parents=True,exist_ok=True)
    names=[]
    for i in range(6):
        im=Image.new('RGB',(1080,1350),CREAM);d=ImageDraw.Draw(im)
        d.rectangle((0,0,1080,180),fill=NIGHT)
        d.text((56,55),'ILLYADERA  /  ACTUALITÉS',font=font(37),fill=YELLOW)
        d.text((56,117),day.strftime('%d.%m.%Y'),font=font(29),fill=CREAM)
        if i==0:
            d.rectangle((0,180,1080,1260),fill=PURPLE)
            d.text((54,235),'05',font=font(250),fill=YELLOW)
            text_fit(d,'LES ACTUS DU 9e ART',(60,520,960,365),size=110,min_size=60,max_lines=4,color=CREAM)
            text_fit(d,'La semaine BD, manga et comics en cinq informations.',(64,950,940,180),size=47,min_size=36,max_lines=4,color=CREAM)
        else:
            x=items[i-1]
            d.rectangle((56,225,1024,320),fill=YELLOW)
            d.text((79,272),f"{i:02d}  /  {x['theme']}",font=font(40),fill=NIGHT,anchor='lm')
            text_fit(d,x['title'],(62,370,956,405),size=76,min_size=36,max_lines=6,color=NIGHT)
            d.line((65,795,1015,795),fill=PURPLE,width=5)
            text_fit(d,x['body'],(65,840,950,270),size=43,min_size=30,max_lines=6,color=NIGHT)
            text_fit(d,('Titre relayé · ' if x.get('quote') else 'Source · ')+x['source'],(65,1150,950,95),size=30,min_size=24,max_lines=2,color=PURPLE)
        d.rectangle((0,1260,1080,1350),fill=NIGHT)
        d.text((55,1305),'LES 5 ACTUS DU 9e ART',font=font(28),fill=YELLOW,anchor='lm')
        d.text((1020,1305),f'{i+1}/6',font=font(28),fill=CREAM,anchor='rm')
        name=f'{i+1:02d}_actus.png';im.save(folder/name,optimize=True);names.append(name)
    return names
def caption(items,day):
    t=PREFIX+' — '+day.strftime('%d/%m/%Y')+'\n\n'
    for i,x in enumerate(items,1):t+=f"{i}. {x['title']}\nSource : {x['source']} — {x['url']}\n\n"
    from marketing_illyadera import cta,tags
    if len(t)+len(cta('ACTUS'))+len(tags('ACTUS'))+4<=2200:t+=cta('ACTUS')+'\n\n'
    t+=tags('ACTUS')
    if len(t)>2200:raise ValueError('Légende trop longue')
    return t
def prepare(repo,*,now=None,buffer=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    due=next_weekly('ACTUS',now);day=parse_due(due).date()
    if (day-parse_due(now).date()).days>4:raise RuntimeError('Hors fenêtre de collecte du lundi')
    receipt=STATE/(day.isoformat()+'.json');old=read(receipt,{})
    # Explicit, one-time editorial correction of the first issue only.
    revision=2 if day.isoformat()=='2026-11-30' else 1
    revising=old.get('etat')=='PROGRAMME' and old.get('revision',1)<revision
    if old.get('etat')=='PROGRAMME' and not revising:write(OUT/'plan.json',{'skip':True});return
    # A persisted intent is reused exactly, never recreated with new content.
    if old.get('etat')=='EN_COURS':
        write(OUT/'plan.json',old);return
    used=[u for p in STATE.glob('*.json') if not (revising and p==receipt) for u in (read(p,{}) or {}).get('urls',[])]
    items=collect(day,used=used)
    text=caption(items,day)
    digest=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:18]
    folder=ROOT/'public_media'/'actus_9e_art'/day.isoformat()/digest
    names=render(items,folder,day)
    plan={'date':day.isoformat(),'due':due,'etat':'PRET','text':text,'urls':[x['url'] for x in items],
          'folder':str(folder.relative_to(ROOT)),'names':names,'base_url':f'https://raw.githubusercontent.com/{repo}/main/{folder.relative_to(ROOT).as_posix()}/'}
    plan['revision']=revision
    if revising:plan['previous']={k:old[k] for k in ('id_buffer','text','due')}
    write(OUT/'plan.json',plan)
def send(*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);buffer=buffer or Buffer()
    plan=read(OUT/'plan.json',{})
    if plan.get('skip'):return
    due=validate_slot('ACTUS',plan['due'],now=now);date=plan['date']
    path=STATE/(date+'.json');prior=read(path,{})
    posts=buffer.list_scheduled()
    same=[p for p in posts if not is_story(p) and parse_due(p['dueAt']).date().isoformat()==date]
    exact=[p for p in same if p['text'].strip()==plan['text'].strip() and parse(p['dueAt'])==parse(due)]
    if len(exact)==1 and len(same)==1:
        plan.update(etat='PROGRAMME',id_buffer=exact[0]['id']);write(path,plan)
        registry=read_registry();target=registry.get(date,{})
        if target.get('id_buffer')==exact[0]['id'] and target.get('etat')=='PROGRAMME':
            target['etat']='SUPPLANTE_PAR_ACTUS';save_registry(registry)
        print('POST_PROGRAMME ACTUS',date);return
    if prior.get('etat')=='EN_COURS':raise RuntimeError('Mutation incertaine, aucune répétition')
    assets=[{'image':{'url':plan['base_url']+n}} for n in plan['names']]
    if len(assets)!=6:raise ValueError('Six pages requises')
    for n in plan['names']:
        with Image.open(ROOT/plan['folder']/n) as im:
            if im.size!=(1080,1350) or im.format!='PNG':raise ValueError('Image invalide')
    verify_public_assets(assets)
    registry=read_registry()
    target=registry.get(date,{})
    owned=(len(same)==1 and is_anecdote(same[0]) and target.get('etat')=='PROGRAMME' and
           target.get('id_buffer')==same[0]['id'] and target.get('texte_public','').strip()==same[0]['text'].strip() and
           parse(target['due_at'])==parse(due))
    # A Monday anecdote can be replaced in place (no delete, no extra capacity).
    previous=plan.get('previous') or {}
    revision_owned=(len(same)==1 and prior.get('etat')=='PROGRAMME'
        and previous.get('id_buffer')==same[0]['id']==prior.get('id_buffer')
        and previous.get('text','').strip()==same[0]['text'].strip()==prior.get('text','').strip()
        and parse(previous['due'])==parse(due)) if previous else False
    if owned or revision_owned:
        identifier=same[0]['id']
        final_guard('ACTUS',due,api_key='',channel_id='',post=None,buffer=buffer,expected_id=identifier,now=now)
        if not any(p==same[0] for p in buffer.list_scheduled()):raise RuntimeError('Post modifié')
        query=EDIT;key='editPost';payload={'id':identifier}
    elif same:raise RuntimeError('Créneau occupé par une publication non identifiée')
    else:
        free_capacity_for_priority(due,buffer=buffer,registry=registry,now=now,priority='ACTUS')
        final_guard('ACTUS',due,api_key='',channel_id='',post=None,buffer=buffer,now=now)
        query=CREATE;key='createPost';payload={'channelId':buffer.channel_id,'needsApproval':False}
    payload.update(text=plan['text'],assets=assets,schedulingType='automatic',mode='customScheduled',dueAt=due,
                   metadata={'instagram':{'type':'post','shouldShareToFeed':True}})
    plan.update(etat='EN_COURS');write(path,plan)
    # Persist intent in main before contacting Buffer.
    import subprocess
    def git(*args):subprocess.run(['git',*args],cwd=ROOT,check=True,timeout=60)
    if os.environ.get('ILLYADERA_DURABLE_JOURNAL')=='1':
        git('add','--',str(path.relative_to(ROOT)))
        git('commit','-m','Réservation actus '+date)
        git('push','origin','HEAD:main')
    result=(buffer.call(query,{'input':payload}).get(key) or {})
    post=result.get('post') or {}
    if result.get('message') or not post.get('id') or post.get('status')!='scheduled' or parse(post['dueAt'])!=parse(due):raise RuntimeError('Buffer sans confirmation')
    live=[p for p in buffer.list_scheduled() if not is_story(p) and parse_due(p['dueAt']).date().isoformat()==date]
    if len(live)!=1 or live[0]['id']!=post['id'] or live[0]['text'].strip()!=plan['text'].strip():raise RuntimeError('Relecture Buffer non confirmée')
    plan.update(etat='PROGRAMME',id_buffer=post['id'],confirmation_utc=dt.datetime.now(dt.timezone.utc).isoformat());write(path,plan)
    if owned:
        target['etat']='SUPPLANTE_PAR_ACTUS';save_registry(registry)
    print('POST_PROGRAMME ACTUS',date,'6 pages, relecture Buffer confirmée, revision',plan.get('revision',1))
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','send']);a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
