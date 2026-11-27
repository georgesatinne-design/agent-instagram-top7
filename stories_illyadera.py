"""Une story Instagram par jour à 20 h Paris, promotion du post réel.
Aucune création sans publication principale identifiée par reçu + API Buffer.
Aucun changement de date, aucune suppression de post principal.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
from anecdotes_auto.buffer import Buffer,CREATE,EDIT,is_story,parse
from anecdotes_auto.visuels import font,text_fit,NIGHT,PURPLE,CREAM,YELLOW
from audit_buffer import category
from calendrier_editorial import aware,PARIS,utc,slot_on
from media_preflight import verify_public_assets

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'stories_state'
PLAN=ROOT/'sorties'/'stories_illyadera'/'plan.json'
PUBLIC=ROOT/'public_media'/'stories_illyadera'
PREFIX='📲 STORY ILLYADERA'
# Query the exact day including the published feed; status 'sent' and automatic
# distinguishes actually published content from reminders.
QUERY="""query StoryDay($organizationId: OrganizationId!, $channelId: ChannelId!, $start: DateTime!, $end: DateTime!) {
 posts(first: 80,input:{organizationId:$organizationId,filter:{channelIds:[$channelId],status:[scheduled,sent,error,sending],dueAt:{start:$start,end:$end}}}) {
 pageInfo {hasNextPage} edges {node {id text dueAt status channelId schedulingType metadata {... on InstagramPostMetadata {type}}}}
 }
}"""
def read(p,default=None):
    return json.loads(p.read_text(encoding='utf8')) if p.is_file() else default
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix('.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8');t.replace(p)
def checkpoint(p):
    if os.environ.get('ILLYADERA_DURABLE_JOURNAL')!='1':return
    if os.environ.get('GITHUB_REF')!='refs/heads/main':raise RuntimeError('Journal hors main')
    rel=p.relative_to(ROOT).as_posix()
    def git(*args):return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True,text=True,timeout=60)
    git('add','--',rel)
    if git('status','--porcelain','--',rel).stdout.strip():git('commit','--only','-m','Journal story Illyadera','--',rel)
    git('push','origin','HEAD:main')
def today_posts(buffer,day):
    start=dt.datetime.combine(day,dt.time.min,tzinfo=PARIS)
    result=buffer.call(QUERY,{'organizationId':buffer.organization(),'channelId':buffer.channel_id,'start':utc(start),'end':utc(start+dt.timedelta(days=1))}).get('posts')
    if not isinstance(result,dict) or (result.get('pageInfo') or {}).get('hasNextPage') is not False:raise RuntimeError('Lecture du jour incomplète')
    out=[]
    for edge in result.get('edges',[]):
        p=edge.get('node') or {}
        if p.get('channelId')!=buffer.channel_id or not p.get('dueAt'):continue
        if parse(p['dueAt']).astimezone(PARIS).date()==day:out.append(p)
    return out
def source_record(post,day):
    k=category(post.get('text',''));d=day.isoformat();pid=post['id']
    if k=='ANECDOTE':
        r=(read(ROOT/'anecdotes_state'/'programmes.json',{}) or {}).get(d,{})
        if r.get('etat')!='PROGRAMME' or r.get('id_buffer')!=pid or r.get('texte_public','').strip()!=post['text'].strip():return None
        return r['dossier'],r['images'][0]
    if k=='ACTUS':
        r=read(ROOT/'actus_state'/(d+'.json'),{}) or {}
        if r.get('etat')!='PROGRAMME' or r.get('id_buffer')!=pid or r.get('text','').strip()!=post['text'].strip():return None
        return r['folder'],r['names'][0]
    roots={'BD':'buffer_receipts','MANGA':'manga_buffer_receipts','COMICS_HEBDO':'comics_buffer_receipts','COMICS_MENSUEL':'comics_buffer_receipts'}
    if k not in roots:return None
    for file in (ROOT/roots[k]).glob('*.json'):
        r=read(file,{})
        if r.get('statut')!='POST_PROGRAMME' or r.get('id_buffer')!=pid or not r.get('date_programmee_utc') or parse(r['date_programmee_utc'])!=parse(post['dueAt']):continue
        folder=ROOT/'public_media'/r['edition']
        if k=='BD':choices=[folder/'BD']
        elif k=='MANGA':choices=[folder/(r.get('version_contenu') and 'MANGA_sans_sources_v1' or 'MANGA')]
        else:choices=sorted(folder.glob('COMICS_*'))
        # If multiple revisions cannot be resolved, use the actual caption
        # without copying an unverified old visual.
        if len(choices)!=1:return ('','')
        recaps=sorted(choices[0].glob('*recap*.png'))
        images=recaps or sorted(choices[0].glob('*.png'))
        if not images:return ('','')
        return choices[0].relative_to(ROOT).as_posix(),images[-1 if recaps else 0].name
    return None
def select(posts,day,now):
    main=[p for p in posts if not is_story(p) and category(p.get('text',''))!='AUTRE' and parse(p['dueAt']).astimezone(PARIS)==slot_on(day)]
    if len(main)!=1:return None
    p=main[0]
    if now>=slot_on(day)+dt.timedelta(minutes=30):
        if p.get('status')!='sent' or p.get('schedulingType')!='automatic':return None
    elif p.get('status') not in ('scheduled','sent'):return None
    r=source_record(p,day)
    return (p,r) if r is not None else None
def title(post):
    k=category(post['text'])
    if k=='ANECDOTE':
        lines=[x.strip() for x in post['text'].splitlines() if x.strip()]
        return ('ANECDOTE DU 9e ART',lines[1] if len(lines)>1 else 'Le savais-tu ?')
    if k=='ACTUS':return ('LES 5 ACTUS DU 9e ART','Cinq informations à découvrir')
    return ({'BD':'TOP 7 BD','MANGA':'TOP 7 MANGA','COMICS_HEBDO':'TOP 5 COMICS','COMICS_MENSUEL':'TOP 7 COMICS'}[k],'Les meilleures ventes')
def render(post,source,dest):
    series,hook=title(post)
    im=Image.new('RGB',(1080,1920),NIGHT);d=ImageDraw.Draw(im)
    d.rectangle((0,0,1080,420),fill=PURPLE)
    d.text((540,250),'ILLYADERA',font=font(42),fill=YELLOW,anchor='mm')
    text_fit(d,'LE POST DU JOUR',(64,320,952,100),size=57,min_size=40,max_lines=2,color=CREAM,align='center')
    if source[0] and source[1]:
        src=(ROOT/source[0]/source[1]).resolve()
        if not src.is_relative_to((ROOT/'public_media').resolve()):raise ValueError('Média hors dépôt')
        with Image.open(src) as original:art=ImageOps.contain(original.convert('RGB'),(820,1025))
        im.paste(art,((1080-art.width)//2,440))
    else:
        d.rounded_rectangle((85,480,995,1410),radius=40,fill=PURPLE)
        text_fit(d,series,(135,670,810,330),size=104,min_size=48,max_lines=4,color=YELLOW,align='center')
        text_fit(d,hook,(135,1050,810,220),size=62,min_size=38,max_lines=4,color=CREAM,align='center')
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((75,1510,1005,1690),radius=32,fill=YELLOW)
    text_fit(d,'À DÉCOUVRIR SUR LE PROFIL',(108,1560,864,100),size=48,min_size=34,max_lines=2,color=NIGHT,align='center')
    dest.parent.mkdir(parents=True,exist_ok=True);im.save(dest,optimize=True)
def prepare(repo,*,buffer=None,now=None):
    now=aware(now);day=now.date();due=utc(dt.datetime.combine(day,dt.time(20),tzinfo=PARIS))
    if parse(due)<=now+dt.timedelta(minutes=15):write(PLAN,{'skip':'créneau trop proche'});return
    buffer=buffer or Buffer();posts=today_posts(buffer,day);candidate=select(posts,day,now)
    rec=read(STATE/(day.isoformat()+'.json'),{}) or {}
    if not candidate:
        write(PLAN,{'skip':'aucun post principal confirmé','date':day.isoformat(),'cancel':bool(rec.get('etat')=='PROGRAMME' and now>=slot_on(day)+dt.timedelta(minutes=30))});return
    post,source=candidate
    digest=hashlib.sha256((post['id']+'|'+post['text']+'|'+str(source)).encode()).hexdigest()[:18]
    if rec.get('etat')=='PROGRAMME' and rec.get('revision')==digest:
        if any(is_story(p) and p['id']==rec.get('id_buffer') and p['status']=='scheduled' and parse(p['dueAt'])==parse(due) for p in posts):
            write(PLAN,{'skip':'story déjà confirmée'});print('STORY_DEJA_PROGRAMMEE',day);return
        if any(p['id']==rec.get('id_buffer') and p['status']=='sent' for p in posts):
            write(PLAN,{'skip':'story déjà publiée'});return
        raise RuntimeError('Story antérieure absente : pas de doublon')
    if rec.get('etat')=='EN_COURS':
        write(PLAN,rec);return
    dest=PUBLIC/day.isoformat()/digest/'story.png';render(post,source,dest)
    text=PREFIX+' — '+day.isoformat()+' — '+title(post)[0]
    plan={'date':day.isoformat(),'due':due,'etat':'PRET','id_post_principal':post['id'],'revision':digest,'text':text,
          'file':dest.relative_to(ROOT).as_posix(),'url':f'https://raw.githubusercontent.com/{repo}/main/{dest.relative_to(ROOT).as_posix()}'}
    if rec.get('etat')=='PROGRAMME':plan['previous']={k:rec[k] for k in ('id_buffer','text','due')}
    write(PLAN,plan)
def send(*,buffer=None,now=None):
    now=aware(now);buffer=buffer or Buffer();plan=read(PLAN,{})
    if plan.get('skip'):
        if plan.get('cancel'):
            path=STATE/(plan['date']+'.json');r=read(path,{})
            q=buffer.list_scheduled()
            matching=[p for p in q if is_story(p) and p['id']==r.get('id_buffer') and parse(p['dueAt'])==parse(r['due']) and p['text'] in ('',r['text'])]
            if len(matching)==1:
                r['etat']='ANNULATION_EN_COURS';write(path,r);checkpoint(path)
                buffer.delete_own(matching[0]['id']);r['etat']='ANNULE_POST_PRINCIPAL_NON_CONFIRME';write(path,r);checkpoint(path)
        print('STORY_SKIP',plan['skip']);return
    day=dt.date.fromisoformat(plan['date']);due=plan['due'];path=STATE/(plan['date']+'.json')
    if day!=now.date() or parse(due)<=now+dt.timedelta(minutes=15):raise RuntimeError('Créneau story expiré')
    current=today_posts(buffer,day);candidate=select(current,day,now)
    if not candidate or candidate[0]['id']!=plan['id_post_principal']:raise RuntimeError('Post principal modifié')
    post,source=candidate
    revision=hashlib.sha256((post['id']+'|'+post['text']+'|'+str(source)).encode()).hexdigest()[:18]
    if revision!=plan['revision']:raise RuntimeError('Contenu principal modifié')
    prior=read(path,{}) or {};queue=buffer.list_scheduled()
    stories=[p for p in queue if is_story(p) and parse(p['dueAt']).astimezone(PARIS).date()==day]
    # Real story metadata is mandatory; no duplicates even if text is stripped.
    if prior.get('etat')=='EN_COURS':
        exact=[p for p in stories if parse(p['dueAt'])==parse(due) and p['text']==plan['text']]
        if len(exact)==1 and not plan.get('previous'):
            plan.update(etat='PROGRAMME',id_buffer=exact[0]['id']);write(path,plan);checkpoint(path);print('STORY_PROGRAMMEE_RECONCILIEE',day);return
        raise RuntimeError('Mutation incertaine : aucun doublon')
    assets=[{'image':{'url':plan['url']}}]
    with Image.open(ROOT/plan['file']) as img:
        if img.size!=(1080,1920) or img.format!='PNG':raise ValueError('Dimensions story incorrectes')
    verify_public_assets(assets)
    previous=plan.get('previous')
    if previous:
        owned=[p for p in stories if p['id']==previous['id_buffer'] and parse(p['dueAt'])==parse(previous['due']) and p['text'] in ('',previous['text'])]
        if len(stories)!=1 or len(owned)!=1:raise RuntimeError('Story à modifier non identifiée')
        payload={'id':owned[0]['id']};query=EDIT;key='editPost'
    else:
        if stories:raise RuntimeError('Une story existe déjà aujourd’hui')
        if len(queue)>=10:print('STORY_SKIP plafond gratuit, réessai après le post');return
        payload={'channelId':buffer.channel_id,'needsApproval':False};query=CREATE;key='createPost'
    payload.update(text=plan['text'],assets=assets,mode='customScheduled',dueAt=due,schedulingType='automatic',metadata={'instagram':{'type':'story','shouldShareToFeed':False}})
    if buffer.list_scheduled()!=queue:raise RuntimeError('File modifiée pendant le contrôle')
    plan['etat']='EN_COURS';write(path,plan);checkpoint(path)
    result=buffer.call(query,{'input':payload}).get(key) or {};saved=result.get('post') or {}
    if result.get('message') or saved.get('status')!='scheduled' or not saved.get('id') or parse(saved['dueAt'])!=parse(due):raise RuntimeError('Buffer story refusée : '+str(result.get('message','réponse incomplète'))[:180])
    live=[p for p in buffer.list_scheduled() if p['id']==saved['id'] and is_story(p) and parse(p['dueAt'])==parse(due)]
    if len(live)!=1:raise RuntimeError('Story non confirmée par relecture Buffer')
    plan.update(etat='PROGRAMME',id_buffer=saved['id'],confirmation_utc=dt.datetime.now(dt.timezone.utc).isoformat());write(path,plan);checkpoint(path)
    print('STORY_PROGRAMMEE',day,'20h Paris','type story vérifié dans Buffer')
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','send']);a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
