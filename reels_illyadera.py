"""Convertit une anecdote du mercredi en Réel, sans créer ni supprimer de post.
Voix française locale, images déjà validées, sous-titres intégrés, MP4 public
immuable. Si une étape échoue, le carrousel demeure le repli éditorial.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, os, re, subprocess, tempfile, textwrap, time, wave
from pathlib import Path
import requests
from PIL import Image,ImageDraw,ImageOps
from anecdotes_auto.buffer import Buffer,EDIT,is_story,is_anecdote,parse
from anecdotes_auto.catalogue import bank,fingerprint
from anecdotes_auto.storytelling import story
from anecdotes_auto.run import editorial_eligible
from anecdotes_auto.visuels import font,text_fit,NIGHT,CREAM,YELLOW
from calendrier_editorial import aware,slot_on,PARIS
from stories_illyadera import read,write,checkpoint
ROOT=Path(__file__).resolve().parent
REG=ROOT/'anecdotes_state'/'programmes.json'
STATE=ROOT/'reels_state'
PUBLIC=ROOT/'public_media'/'reels_illyadera'
PLAN=ROOT/'sorties'/'reels_illyadera'/'plan.json'
VERSION='REEL_FR_LOCAL_V1'
def run(*args):
    return subprocess.run([str(x) for x in args],check=True,capture_output=True,timeout=120).stdout
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def kind(p):return (p.get('metadata') or {}).get('type')
def next_wednesday(now):
    n=aware(now)
    for i in range(8):
        d=n.date()+dt.timedelta(days=i)
        if d.weekday()==2 and slot_on(d)>n+dt.timedelta(minutes=90):return d
    raise RuntimeError('Mercredi introuvable')
def exact_post(posts,record,day):
    due=slot_on(day)
    same=[p for p in posts if not is_story(p) and parse(p['dueAt']).astimezone(PARIS).date()==day]
    if len(same)!=1:return None
    p=same[0]
    if (p.get('id')!=record.get('id_buffer') or p.get('text','').strip()!=record.get('texte_public','').strip()
        or parse(p['dueAt'])!=parse(record['due_at']) or parse(p['dueAt']).astimezone(PARIS)!=due
        or not is_anecdote(p) or p.get('status')!='scheduled' or kind(p) not in ('post','reel','reels')):
        return None
    return p
def source_files(record):
    folder=(ROOT/record['dossier']).resolve()
    if not folder.is_relative_to((ROOT/'public_media'/'anecdotes_bd').resolve()):raise ValueError('Dossier non autorisé')
    names=record.get('images') or []
    if len(names)!=5 or len(set(names))!=5:raise ValueError('Cinq pages originales requises')
    files=[]
    for name in names:
        p=(folder/name).resolve()
        if p.parent!=folder:raise ValueError('Chemin interdit')
        with Image.open(p) as im:
            if im.format!='PNG' or im.size!=(1080,1350):raise ValueError('Page source invalide')
        files.append(p)
    return files
def chunks(text):
    # Captions remain verbatim and each chunk is spoken in order.
    return textwrap.wrap(re.sub(r'\s+',' ',text).strip(),width=66,break_long_words=False,break_on_hyphens=False)
def scene_script(fact):
    s=story(fact)
    return [s['hook'],s['revelation'],s['contexte'],s['detail'],s['question']]
def canvas(src,subtitle):
    im=Image.new('RGB',(1080,1920),NIGHT)
    with Image.open(src) as raw:art=ImageOps.contain(raw.convert('RGB'),(870,1088))
    im.paste(art,((1080-art.width)//2,236))
    d=ImageDraw.Draw(im)
    d.text((540,153),'ILLYADERA',font=font(38),fill=YELLOW,anchor='mm')
    d.rounded_rectangle((104,1360,976,1660),radius=30,fill='#1B1422')
    text_fit(d,subtitle,(140,1400,800,216),size=56,min_size=38,max_lines=4,color=CREAM,align='center')
    return im
def inspect_video(path):
    p=json.loads(run('ffprobe','-v','error','-show_streams','-show_format','-of','json',path))
    video=[s for s in p['streams'] if s['codec_type']=='video'];audio=[s for s in p['streams'] if s['codec_type']=='audio']
    dur=float(p['format']['duration'])
    if len(video)!=1 or len(audio)!=1 or (video[0]['width'],video[0]['height'])!=(1080,1920) or video[0]['codec_name']!='h264' or audio[0]['codec_name']!='aac' or not 18<=dur<=60 or not 10000<path.stat().st_size<35_000_000:raise RuntimeError('Vidéo hors spécification')
    return round(dur,2)
def render(files,fact,dest):
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);clips=[]
        for idx,(src,line) in enumerate(zip(files,scene_script(fact))):
            for j,subtitle in enumerate(chunks(line)):
                stem=tmp/f'{idx:02d}-{j:02d}';wav=stem.with_suffix('.wav');png=stem.with_suffix('.png');clip=stem.with_suffix('.mp4')
                run('espeak-ng','-v','fr-fr','-s','178','-p','48','-w',wav,'--',subtitle)
                with wave.open(str(wav),'rb') as f:seconds=f.getnframes()/f.getframerate()
                # Align each subtitle with its own voice segment. Minimal pause
                # for reading, not a static 5-slide slideshow at fixed intervals.
                duration=max(1.9,seconds+.18);frames=math.ceil(duration*25);duration=frames/25
                canvas(src,subtitle).save(png)
                vf="scale=2160:3840,zoompan=z='1+0.024*on/"+str(max(1,frames-1))+"':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d="+str(frames)+":s=1080x1920:fps=25,format=yuv420p"
                run('ffmpeg','-hide_banner','-loglevel','error','-y','-i',png,'-i',wav,'-vf',vf,'-af','apad','-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','25','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','1','-b:a','96k',clip)
                clips.append(clip)
        listing=tmp/'concat.txt';listing.write_text(''.join("file '"+str(p)+"'\n" for p in clips),encoding='utf8')
        run('ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart',dest)
    return inspect_video(dest)
def prepare(repo,buffer=None,now=None):
    now=aware(now);day=next_wednesday(now);key=day.isoformat()
    buffer=buffer or Buffer();record=(read(REG,{}) or {}).get(key,{})
    old=read(STATE/(key+'.json'),{}) or {}
    if record.get('etat')!='PROGRAMME':
        write(PLAN,{'skip':'Aucune anecdote du mercredi validée','date':key});return
    post=exact_post(buffer.list_scheduled(),record,day)
    if not post:write(PLAN,{'skip':'Carrousel du mercredi non identifié','date':key});return
    if kind(post) in ('reel','reels'):
        if old.get('id_buffer')==post['id'] and old.get('etat') in ('EN_COURS','PROGRAMME'):
            old['etat']='PROGRAMME';old['confirmation_utc']=now.isoformat()
            write(STATE/(key+'.json'),old);checkpoint(STATE/(key+'.json'))
        write(PLAN,{'skip':'Réel déjà présent','date':key});return
    if old.get('etat')=='EN_COURS':
        # An unresolved request can only be reconciled, not repeated blindly.
        raise RuntimeError('Édition précédente incertaine, carrousel préservé')
    fact=next((x for x in bank() if x['id']==record.get('fact_id')),None)
    if not fact or not editorial_eligible(fact) or fingerprint(fact)!=record.get('empreinte_fait'):raise RuntimeError('Fait non éligible ou modifié')
    files=source_files(record)
    revision=hashlib.sha256((VERSION+'|'+post['id']+'|'+json.dumps(scene_script(fact),ensure_ascii=False)+'|'+','.join(sha(p) for p in files)).encode()).hexdigest()[:18]
    dest=PUBLIC/key/revision/'reel.mp4'
    duration=inspect_video(dest) if dest.is_file() else render(files,fact,dest)
    plan={'date':key,'due':post['dueAt'],'id_buffer':post['id'],'text':post['text'],'fact_id':fact['id'],
          'record_revision':record['revision'],'revision':revision,'file':dest.relative_to(ROOT).as_posix(),
          'sha256':sha(dest),'duration':duration,'url':f'https://raw.githubusercontent.com/{repo}/main/{dest.relative_to(ROOT).as_posix()}','etat':'PRET','version':VERSION}
    write(PLAN,plan);print('REEL_PRET',key,fact['id'],duration,'s',dest.stat().st_size,'octets')
def verify_remote(plan):
    from urllib.parse import urlparse
    url=plan['url'];p=urlparse(url)
    if p.scheme!='https' or p.hostname!='raw.githubusercontent.com' or not p.path.endswith('/reel.mp4'):raise ValueError('URL vidéo non autorisée')
    for i in range(4):
        try:
            with requests.get(url,stream=True,timeout=25,allow_redirects=False) as r:
                if r.status_code==200:
                    h=hashlib.sha256();n=0
                    for chunk in r.iter_content(131072):
                        n+=len(chunk)
                        if n>35_000_000:raise RuntimeError('Vidéo distante trop grande')
                        h.update(chunk)
                    if h.hexdigest()==plan['sha256']:return
        except requests.RequestException:pass
        if i<3:time.sleep(5)
    raise RuntimeError('Vidéo publique non vérifiée : aucune édition')
def send(buffer=None,now=None):
    now=aware(now);plan=read(PLAN,{})
    if plan.get('skip'):print('REEL_SKIP',plan['date'],plan['skip']);return
    day=dt.date.fromisoformat(plan['date']);path=STATE/(plan['date']+'.json')
    if day.weekday()!=2 or parse(plan['due'])<=now+dt.timedelta(minutes=90):raise RuntimeError('Créneau expiré')
    record=(read(REG,{}) or {}).get(plan['date'],{})
    if record.get('revision')!=plan['record_revision'] or record.get('id_buffer')!=plan['id_buffer'] or record.get('etat')!='PROGRAMME':raise RuntimeError('Registre modifié')
    buffer=buffer or Buffer();q=buffer.list_scheduled();post=exact_post(q,record,day)
    if not post or kind(post)!='post' or post['id']!=plan['id_buffer'] or post['text']!=plan['text'] or len(q)>10:raise RuntimeError('Post modifié ou file non conforme')
    dest=ROOT/plan['file']
    if sha(dest)!=plan['sha256']:raise RuntimeError('Vidéo modifiée')
    inspect_video(dest);verify_remote(plan)
    if buffer.list_scheduled()!=q:raise RuntimeError('File modifiée')
    plan['etat']='EN_COURS';write(path,plan);checkpoint(path)
    payload={'id':post['id'],'text':post['text'],'assets':[{'video':{'url':plan['url'],'metadata':{'thumbnailOffset':500}}}],
             'metadata':{'instagram':{'type':'reel','shouldShareToFeed':True}},'schedulingType':'automatic','mode':'customScheduled','dueAt':plan['due']}
    result=buffer.call(EDIT,{'input':payload}).get('editPost') or {}
    saved=result.get('post') or {}
    if result.get('message'):
        # Explicit rejection can be retried; ambiguous failures remain EN_COURS.
        fresh=exact_post(buffer.list_scheduled(),record,day)
        if fresh and kind(fresh)=='post':plan['etat']='REFUSE_CARROUSEL_CONSERVE';write(path,plan);checkpoint(path)
        raise RuntimeError('Buffer refuse le Réel: '+str(result['message'])[:180])
    if saved.get('id')!=post['id'] or saved.get('status')!='scheduled' or parse(saved['dueAt'])!=parse(plan['due']):raise RuntimeError('Édition non confirmée')
    live=exact_post(buffer.list_scheduled(),record,day)
    if not live or kind(live) not in ('reel','reels'):raise RuntimeError('Type Réel non confirmé')
    plan.update(etat='PROGRAMME',confirmation_utc=now.isoformat());write(path,plan);checkpoint(path)
    print('REEL_PROGRAMME',day,post['id'],plan['duration'],'s','type reel vérifié, même créneau')
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','send']);a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
