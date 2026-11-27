"""Migration des carrousels déjà approuvés, sans nouvelle recherche de droits.
Conserve tous les pixels des illustrations et textes narratifs ; remplace
uniquement les bandeaux de série du studio V5/V6/V7. Aucune suppression.
Un échec sur un post ne bloque pas les autres.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from PIL import Image,ImageDraw
from . import run
from .buffer import Buffer,is_anecdote,parse
from .visuels import font,NIGHT,YELLOW,_footer,_mini_brand
from calendrier_editorial import validate_slot
from controle_file import final_guard
from journal_publication import checkpoint

OLD='📚 ANECDOTE BD'
NEW='📚 ANECDOTE DU 9e ART'
PLAN=run.REPORT/'MIGRATION_9E_ART.json'
TITLES={2:'LE FAIT',3:'LE CONTEXTE',4:'LE DÉTAIL',5:'À TON TOUR'}

def rebrand(source,dest,number):
    with Image.open(source) as original:
        if original.size!=(1080,1350) or original.format!='PNG':raise ValueError('Format source invalide')
        im=original.convert('RGB')
    # Only overwrite the existing solid brand regions, never the artwork.
    from PIL import ImageColor
    night=ImageColor.getrgb(NIGHT);yellow=ImageColor.getrgb(YELLOW)
    if im.getpixel((500,1340))!=night:raise ValueError('Pied de page source inconnu')
    if number==1:
        if im.getpixel((10,10))!=yellow or im.getpixel((1000,180))!=yellow:
            raise ValueError('Bandeau source inconnu')
        d=ImageDraw.Draw(im);d.rectangle((0,0,1079,189),fill=YELLOW)
        d.text((35,83),'ANECDOTE DU 9e ART',font=font(68),fill=NIGHT,anchor='lm')
        _footer(im,1)
    else:
        if im.getpixel((1000,10))!=night:raise ValueError('En-tête source inconnu')
        _mini_brand(im,number,TITLES[number])
    im.save(dest,optimize=True)

def matching(posts,date,old):
    same=[p for p in posts if parse(p['dueAt']).astimezone(run.PARIS).date().isoformat()==date]
    if len(same)!=1:return None
    p=same[0]
    if p['id']!=old.get('id_buffer') or p['status']!='scheduled' or not is_anecdote(p):return None
    if parse(p['dueAt'])!=parse(old['due_at']):return None
    return p

def prepare(repo,*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);buffer=buffer or Buffer()
    posts=buffer.list_scheduled();plans=[];errors=[]
    for date,old in sorted(run.get_registry().items()):
        if old.get('etat') not in ('PROGRAMME','EN_ATTENTE_MAJ'):continue
        if not old.get('due_at') or parse(old['due_at'])<=now+dt.timedelta(minutes=30):continue
        if not old.get('texte_public','').startswith(OLD):
            # Recover our specific pending migration, if any.
            if old.get('migration_9e_art') and old.get('etat')=='EN_ATTENTE_MAJ':
                plans.append({'date':date,'old':old['migration_9e_art'],'new':old})
            continue
        p=matching(posts,date,old)
        if not p or p['text'].strip()!=old['texte_public'].strip():continue
        try:
            validate_slot('ANECDOTE',old['due_at'],now=now)
            if len(old['images'])!=5:raise ValueError('Cinq pages sources requises')
            src=run.ROOT_REPO/old['dossier']
            if not src.is_relative_to(run.PUBLIC):raise ValueError('Chemin source invalide')
            text=old['texte_public'].replace(OLD,NEW,1)
            import tempfile,shutil
            with tempfile.TemporaryDirectory() as td:
                tmp=Path(td)
                for i,name in enumerate(old['images'],1):
                    if Path(name).name!=name:raise ValueError('Nom de média invalide')
                    rebrand(src/name,tmp/name,i)
                digest=hashlib.sha256(text.encode()+b''.join((tmp/n).read_bytes() for n in old['images'])).hexdigest()[:18]
                dst=run.PUBLIC/date/(old['fact_id']+'_'+digest)
                dst.mkdir(parents=True,exist_ok=True)
                for name in old['images']:shutil.copyfile(tmp/name,dst/name)
            (dst/'legende_instagram.txt').write_text(text+'\n',encoding='utf8')
            new={**old,'etat':'EN_ATTENTE_MAJ','texte_public':text,'ancien_texte_public':old['texte_public'],
                 'version_visuelle':run.VERSION_VISUELLE,'revision':digest,
                 'dossier':dst.relative_to(run.ROOT_REPO).as_posix(),
                 'base_url':f'https://raw.githubusercontent.com/{repo}/main/{dst.relative_to(run.ROOT_REPO).as_posix()}/'}
            plans.append({'date':date,'old':old,'new':new})
        except Exception as exc:errors.append({'date':date,'raison':str(exc)[:180]})
    run.write(PLAN,{'plans':plans,'erreurs':errors})
    print('Migration préparée',len(plans),'erreurs',errors)

def send(*,buffer=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);buffer=buffer or Buffer()
    report=run.read(PLAN,{'plans':[],'erreurs':[]});done=[];errors=report['erreurs']
    for item in report['plans']:
        date,old,new=item['date'],item['old'],item['new']
        try:
            registry=run.get_registry()
            p=matching(buffer.list_scheduled(),date,old)
            if not p:raise RuntimeError('Identité ou horaire différent')
            if p['text'].strip()==new['texte_public'].strip():
                pass # response previously lost, live post is definitive
            else:
                if p['text'].strip()!=old['texte_public'].strip():raise RuntimeError('Texte source modifié')
                if registry.get(date)!=old and registry.get(date)!=new:raise RuntimeError('Registre modifié')
                validate_slot('ANECDOTE',new['due_at'],now=now)
                assets=buffer.verify_images(new['base_url'],new['images'],run.ROOT_REPO/new['dossier'])
                final_guard('ANECDOTE',new['due_at'],api_key='',channel_id='',post=None,buffer=buffer,expected_id=old['id_buffer'])
                if matching(buffer.list_scheduled(),date,old)!=p:raise RuntimeError('File modifiée')
                new['migration_9e_art']=old
                registry[date]=new;run.persist(registry);checkpoint(run.REGISTRY)
                buffer.edit_own(old['id_buffer'],new['texte_public'],new['due_at'],assets)
                live=matching(buffer.list_scheduled(),date,old)
                if not live or live['text'].strip()!=new['texte_public'].strip():raise RuntimeError('Relecture Buffer non confirmée')
            new.update(etat='PROGRAMME',date_confirmation=dt.datetime.now(dt.timezone.utc).isoformat())
            new.pop('migration_9e_art',None);new.pop('ancien_texte_public',None)
            registry[date]=new;run.persist(registry);checkpoint(run.REGISTRY)
            done.append(date);print('POST_PROGRAMME ANECDOTE DU 9e ART',date)
        except Exception as exc:errors.append({'date':date,'raison':str(exc)[:180]})
    remaining=[p['dueAt'] for p in buffer.list_scheduled() if p['text'].startswith(OLD)]
    print(json.dumps({'confirmes':done,'anciennes_anecdotes_restantes':remaining,'erreurs':errors},ensure_ascii=False))
    if errors or remaining:raise SystemExit(1)
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','send']);a=p.parse_args()
    if a.action=='prepare':prepare(os.environ['GITHUB_REPOSITORY'])
    else:send()
if __name__=='__main__':main()
