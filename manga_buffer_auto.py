"""Programmation contrôlée MANGA dans Buffer, indépendante de l'agent BD.

Un seul Top 7 manga par période de vente. Ne publie pas un diagnostic ni
une maquette. Contrôle Buffer avant toute mutation pour limiter les doublons.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse,quote
from zoneinfo import ZoneInfo
import requests
from PIL import Image

# Réutilisation des fonctions GraphQL testées du projet BD, sans modifier leur code.
from buffer_client import (_graphql, _mutation_result, _parse_due,
                           MUTATION, EDIT_MUTATION, ORG_QUERY, SLOT_QUERY)

MANGA_HEADER=re.compile(r'^\s*(?:📚\s*)?TOP\s*7\s*MANGA\b',re.I)
PERIOD_END=re.compile(r'\bAU\s+(\d{2}/\d{2}/\d{4})\b',re.I)


def date_periode_captation(text:str)->dt.date:
    m=PERIOD_END.search(text or '')
    if not m:raise ValueError('Date de ventes non vérifiable dans la légende')
    return dt.datetime.strptime(m.group(1),'%d/%m/%Y').date()


def mardi_suivant(now=None,*,weekday=1,hour=18,minute=0) -> str:
    """Mardi 18 h Paris, après les contrôles du vendredi au lundi.

    Ne dépend pas du calendrier BD. La valeur peut être personnalisée dans
    les variables du workflow sans modifier la production BD.
    """
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError('Date courante sans timezone')
    paris=ZoneInfo('Europe/Paris')
    local=now.astimezone(paris)
    minimum=local+dt.timedelta(minutes=45)
    for i in range(15):
        day=local.date()+dt.timedelta(days=i)
        if day.weekday()!=weekday:continue
        candidate=dt.datetime.combine(day,dt.time(hour,minute),tzinfo=paris)
        if candidate>minimum:
            return candidate.astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    raise RuntimeError('Prochaine date manga introuvable')


def construire(folder,base_url,channel_id,*,now=None):
    folder=Path(folder)
    m=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
    data=json.loads((folder.parent/'classement_manga.json').read_text(encoding='utf8'))
    if m.get('category')!='MANGA' or m.get('certification_manga')!='TOP7_EDISTAT_VERIFIE' or not m.get('ready_to_stage'):
        raise ValueError('Classement manga pas suffisamment vérifié pour programmation')
    if data.get('certification')!='TOP7_EDISTAT_VERIFIE' or len(data.get('titres',[]))!=7:
        raise ValueError('Classement manga source non validé')
    pages=m.get('pages') or []
    if pages!=[f'{i:02d}_rang_{8-i}.png' for i in range(1,8)]+['08_recapitulatif.png']:
        raise ValueError('Ordre du Top 7 incorrect')
    u=urlparse(base_url)
    if u.scheme!='https' or u.hostname not in ('raw.githubusercontent.com',) or not base_url.endswith('/'):
        raise ValueError('Les médias doivent être servis depuis GitHub public HTTPS')
    media=[]
    for name in pages:
        path=folder/name
        with Image.open(path) as im:
            if im.format!='PNG' or im.size!=(1080,1350):raise ValueError('Visuel Instagram incorrect : '+name)
        media.append({'image':{'url':base_url+quote(name)}})
    caption=(folder/m['caption_file']).read_text(encoding='utf8').strip()
    if not MANGA_HEADER.match(caption) or len(caption)>2200:raise ValueError('Légende manga absente/incorrecte')
    expected_date=dt.date.fromisoformat(data['fin_ventes'])
    if date_periode_captation(caption)!=expected_date:
        raise ValueError('Période de ventes différente entre données et légende')
    now=now or dt.datetime.now(dt.timezone.utc)
    age=(now.date()-expected_date).days
    if age<0 or age>21:
        raise ValueError('Classement trop ancien ou futur : aucun dépôt Buffer')
    if not channel_id:raise ValueError('Identifiant canal Buffer absent')
    return {'text':caption,'channelId':channel_id,'schedulingType':'automatic',
            'mode':'customScheduled','dueAt':mardi_suivant(now=now),
            'needsApproval':False, 'assets':media,
            'metadata':{'instagram':{'type':'post','shouldShareToFeed':True}}}


def _list_manga_programmes(api_key,channel_id,due_at,*,post=requests.post):
    orgs=((_graphql(post,api_key,ORG_QUERY).get('account') or {}).get('organizations') or [])
    ids=[str(x.get('id')) for x in orgs if isinstance(x,dict) and x.get('id')]
    selected=os.environ.get('BUFFER_ORGANIZATION_ID','').strip()
    if selected:
        if selected not in ids:raise RuntimeError('Organisation Buffer non reconnue')
        org=selected
    elif len(ids)==1:org=ids[0]
    else:raise RuntimeError('Organisation Buffer indéterminée')
    due=_parse_due(due_at)
    # Recherche sur 14 jours au lieu du seul créneau : détection des mêmes
    # classements programmés un autre jour.
    now=dt.datetime.now(dt.timezone.utc)
    start=(now-dt.timedelta(minutes=3)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    end=(due+dt.timedelta(days=14)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    lst=_graphql(post,api_key,SLOT_QUERY,{'organizationId':org,'channelId':channel_id,
        'slotStart':start,'slotEnd':end}).get('posts')
    if not isinstance(lst,dict) or not isinstance(lst.get('edges'),list) or (lst.get('pageInfo') or {}).get('hasNextPage') is not False:
        raise RuntimeError('Liste Buffer partielle : aucune nouvelle publication envoyée')
    records=[]
    for edge in lst['edges']:
        b=(edge or {}).get('node') or {}
        if b.get('status')!='scheduled' or b.get('channelId')!=channel_id:continue
        if not MANGA_HEADER.match(b.get('text') or ''):continue
        if not b.get('id') or not b.get('dueAt'):
            raise RuntimeError('Post Buffer impossible à identifier : envoi arrêté')
        records.append(b)
    return records


def transmettre(folder,base_url,*,api_key,channel_id,send=False,post=requests.post,
                get=requests.get,now=None)->dict:
    payload=construire(folder,base_url,channel_id,now=now)
    edition='MANGA_'+str(date_periode_captation(payload['text']))
    if not send:
        return {'statut':'SIMULATION','edition':edition,'images':8,
                'date_programmee_utc':payload['dueAt']}
    if not api_key:raise ValueError('Accès Buffer absent')
    receipt=Path(folder)/'RECU_BUFFER.json'
    if receipt.exists():
        return json.loads(receipt.read_text(encoding='utf8'))
    # Confirmer les 8 URL avant d appeler l API Buffer.
    for asset in payload['assets']:
        url=asset['image']['url']
        confirmed=False
        for attempt in range(6):
            try:
                r=get(url,timeout=15,stream=True)
                try:
                    r.raise_for_status()
                    confirmed=r.headers.get('Content-Type','').lower().startswith('image/')
                finally:r.close()
                if confirmed:break
            except requests.RequestException:
                pass
            if attempt<5:time.sleep(8)
        if not confirmed:
            raise RuntimeError('Image non encore accessible publiquement : '+url)
    posts=_list_manga_programmes(api_key,channel_id,payload['dueAt'],post=post)
    current=date_periode_captation(payload['text'])
    same=[p for p in posts if date_periode_captation(p['text'])==current]
    if len(same)>1:raise RuntimeError('Plusieurs posts manga pour la même période existent dans Buffer')
    action='CREATION'
    if same:
        ident,status=same[0]['id'],'scheduled';action='DEJA_PROGRAMME'
    else:
        same_slot=[p for p in posts if abs((_parse_due(p['dueAt'])-_parse_due(payload['dueAt'])).total_seconds())<90]
        if len(same_slot)>1:raise RuntimeError('Plusieurs posts manga sur le même créneau')
        if same_slot:
            old=same_slot[0]
            if date_periode_captation(old['text'])>current:
                raise RuntimeError('Une édition manga plus récente est déjà planifiée')
            edited={'id':old['id'],'text':payload['text'],'assets':payload['assets'],
                    'metadata':payload['metadata'],'schedulingType':'automatic',
                    'mode':'customScheduled','dueAt':payload['dueAt']}
            response=_graphql(post,api_key,EDIT_MUTATION,{'input':edited})
            ident,status=_mutation_result(api_key,response,'editPost',payload['dueAt'],expected_id=old['id'])
            action='REMPLACEMENT'
        else:
            response=_graphql(post,api_key,MUTATION,{'input':payload})
            ident,status=_mutation_result(api_key,response,'createPost',payload['dueAt'])
    result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':action,
            'id_buffer':ident,'status_buffer':status,'edition':edition,
            'date_programmee_utc':payload['dueAt'],'pages':8}
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return result


def main():
    p=argparse.ArgumentParser(description='Programme uniquement un manga contrôlé dans Buffer')
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--public-base-url',required=True)
    p.add_argument('--send',action='store_true',help='Sans --send : simulation sans API')
    args=p.parse_args()
    print(json.dumps(transmettre(args.folder,args.public_base_url,
      api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''),
      send=args.send),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
