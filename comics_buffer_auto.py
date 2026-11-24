"""Buffer COMICS, sans action sur les posts BD/MANGA. Envoi dès disponibilité,
publication programmée jeudi 18h (Paris), protection idempotente.

Les identifiants, les médias et les sources restent dans les reçus GitHub.
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
from buffer_client import (_graphql,_mutation_result,_parse_due,
                           MUTATION,EDIT_MUTATION,ORG_QUERY,SLOT_QUERY)
from comics_score_publication import calculer,SEUIL

VERSION='comics_auto_v1'
HEADER=re.compile(r'^\s*(?:📚\s*)?TOP\s*7\s*COMICS\b',re.I)
PUBLIC_SOURCE=re.compile(r'(?i)(?:edistat|actualitt[ée]|nielseniq|\bbnf\b|b[ée]d[ée]\.fr|fnac|bdfugue|mdcu|top reconstitu[ée]|reconstitution)')
PAGES=[f'{i:02d}_rang_{8-i}.png' for i in range(1,8)]+['08_recapitulatif.png']

def utc_string(t):return t.astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def next_comics_slot(now=None,*,weekday=3,hour=18,minute=0):
    """Jeudi 18 h Paris, 45 minutes min après la validation.
    BD vendredi et mangas mardi: aucun changement de leurs créneaux.
    """
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError('Date sans fuseau horaire')
    local=now.astimezone(ZoneInfo('Europe/Paris'))
    for offset in range(15):
        target=local.date()+dt.timedelta(days=offset)
        if target.weekday()!=weekday:continue
        t=dt.datetime.combine(target,dt.time(hour,minute),tzinfo=ZoneInfo('Europe/Paris'))
        if t>=local+dt.timedelta(minutes=45):return utc_string(t)
    raise RuntimeError('Créneau comics suivant introuvable')

def construire(folder,base_url,channel_id,*,now=None):
    folder=Path(folder)
    m=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
    data=json.loads((folder.parent/'classement_comics.json').read_text(encoding='utf8'))
    proofs=json.loads((folder.parent/'preuves_comics.json').read_text(encoding='utf8'))
    audit=json.loads((folder/'AUDIT_COUVERTURES.json').read_text(encoding='utf8'))
    if m.get('category')!='COMICS' or m.get('version_contenu')!=VERSION or not m.get('ready_to_stage'):
        raise ValueError('Edition comics non prête à être programmée')
    if m.get('edition')!=data.get('edition') or not str(m['edition']).startswith('COMICS_'):
        raise ValueError('Edition comics incohérente')
    now=now or dt.datetime.now(dt.timezone.utc)
    quality=calculer(data,proofs,audit.get('controles') or [],today=now.astimezone(ZoneInfo('Europe/Paris')).date())
    if not quality['autorise_publication'] or quality['valeur']<SEUIL or quality['valeur']!=m['qualite_editoriale'].get('valeur'):
        raise ValueError('Score comics incorrect ou sous seuil 70/100')
    if m.get('pages')!=PAGES:raise ValueError('Huit images et ordre 7 vers 1 requis')
    u=urlparse(base_url)
    if u.scheme!='https' or u.hostname!='raw.githubusercontent.com' or not base_url.endswith('/'):
        raise ValueError('Médias publiquement accessibles via GitHub requis')
    media=[]
    for filename in PAGES:
        p=folder/filename
        with Image.open(p) as im:
            if im.format!='PNG' or im.size!=(1080,1350):
                raise ValueError('Visuel comics incorrect '+filename)
        media.append({'image':{'url':base_url+quote(filename)}})
    caption=(folder/'legende_instagram.txt').read_text(encoding='utf8').strip()
    if not HEADER.match(caption) or len(caption)>2200 or PUBLIC_SOURCE.search(caption):
        raise ValueError('Légende comics invalide, trop longue ou avec source publique')
    try:
        observed=dt.date.fromisoformat(data['date_releve'])
    except (KeyError,ValueError):raise ValueError('Date de relevé invalide')
    if not (0<=(now.astimezone(ZoneInfo('Europe/Paris')).date()-observed).days<=7):
        raise ValueError('Relevé de ventes trop ancien')
    if data['mode_interne']=='RELEVE_ENSEIGNE':
        if 'Classement relevé le '+observed.strftime('%d/%m/%Y') not in caption:
            raise ValueError('La légende doit mentionner la date de relevé (pas des ventes hebdomadaires inventées)')
    elif data['mode_interne']=='NATIONAL_HEBDO':
        if 'Ventes DU ' not in caption:raise ValueError('Période nationale absente')
    else:raise ValueError('Mode comics inconnu')
    if not channel_id:raise ValueError('Buffer Channel ID manquant')
    return {'text':caption,'channelId':channel_id,'schedulingType':'automatic',
            'mode':'customScheduled','dueAt':next_comics_slot(now=now),
            'needsApproval':False,'assets':media,
            'metadata':{'instagram':{'type':'post','shouldShareToFeed':True}}}

def _listed(api_key,channel_id,due,*,post=requests.post,now=None):
    orgs=((_graphql(post,api_key,ORG_QUERY).get('account') or {}).get('organizations') or [])
    ids=[str(x.get('id')) for x in orgs if isinstance(x,dict) and x.get('id')]
    preferred=os.getenv('BUFFER_ORGANIZATION_ID','').strip()
    if preferred:
        if preferred not in ids:raise RuntimeError('Organisation Buffer non reconnue')
        org=preferred
    elif len(ids)==1:org=ids[0]
    else:raise RuntimeError('Organisation Buffer ambiguë')
    now=now or dt.datetime.now(dt.timezone.utc)
    start=utc_string(now-dt.timedelta(minutes=3))
    end=utc_string(_parse_due(due)+dt.timedelta(days=7))
    result=_graphql(post,api_key,SLOT_QUERY,{'organizationId':org,'channelId':channel_id,
        'slotStart':start,'slotEnd':end}).get('posts')
    if not isinstance(result,dict) or (result.get('pageInfo') or {}).get('hasNextPage') is not False:
        raise RuntimeError('Recherche Buffer partielle; création bloquée pour éviter doublons')
    edges=result.get('edges')
    if not isinstance(edges,list):raise RuntimeError('Buffer ne retourne pas les posts')
    selected=[]
    for e in edges:
        node=(e or {}).get('node') or {}
        if node.get('status')!='scheduled' or node.get('channelId')!=channel_id:continue
        if not HEADER.match(node.get('text') or ''):continue
        if not node.get('id') or not node.get('dueAt'):
            raise RuntimeError('Post comics existant mais identifiant ou date manquant')
        selected.append(node)
    return selected

def transmettre(folder,base_url,*,api_key,channel_id,send=False,
                 now=None,post=requests.post,get=requests.get,previous_receipt=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    folder=Path(folder);m=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
    edition=m['edition']
    payload=construire(folder,base_url,channel_id,now=now)
    if not send:
        return {'statut':'SIMULATION','edition':edition,'images':8,'date_programmee_utc':payload['dueAt']}
    if not api_key:raise ValueError('Clé Buffer manquante')
    receipt_path=folder/'RECU_BUFFER.json'
    prior_path=Path(previous_receipt) if previous_receipt else receipt_path
    prior=json.loads(prior_path.read_text(encoding='utf8')) if prior_path.is_file() else None
    if prior:
        if prior.get('statut')!='POST_PROGRAMME' or prior.get('edition')!=edition or not prior.get('id_buffer'):
            raise RuntimeError('Reçu incompatible: opération interdite')
        due=_parse_due(prior['date_programmee_utc'])
        if due<=now+dt.timedelta(minutes=10):
            result={**prior,'action':'DEJA_TRANSMIS_NON_MODIFIABLE'}
            receipt_path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
            return result
        if prior.get('version_contenu')==VERSION and prior.get('texte_public')==payload['text']:
            receipt_path.write_text(json.dumps(prior,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
            return prior
    # Buffer récupère les images au moment de leur publication future. Les
    # huit URLs doivent être accessibles EN DEHORS de la session GitHub.
    for asset in payload['assets']:
        url=asset['image']['url'];valid=False
        for attempt in range(5):
            try:
                r=get(url,timeout=15,stream=True)
                try:
                    r.raise_for_status()
                    valid=r.headers.get('Content-Type','').lower().startswith('image/')
                finally:r.close()
            except requests.RequestException:pass
            if valid:break
            if attempt<4:time.sleep(6)
        if not valid:raise RuntimeError('Visuel inaccessible publiquement par Buffer : '+url)
    current=_listed(api_key,channel_id,payload['dueAt'],post=post,now=now)
    due=_parse_due(payload['dueAt'])
    # Un seul post comics pour le créneau du jeudi. Ne jamais modifier les
    # posts manga ou BD : ils sont filtrés par en-tête avant cette étape.
    candidates=[p for p in current if abs((_parse_due(p['dueAt'])-due).total_seconds())<90]
    if prior:
        candidates=[p for p in current if p['id']==prior['id_buffer']]
        if len(candidates)!=1:raise RuntimeError('Reçu comics existant mais post absent de Buffer')
    if len(candidates)>1:raise RuntimeError('Plusieurs posts comics au même créneau')
    action='CREATION';effective_due=payload['dueAt']
    if candidates:
        old=candidates[0]
        if _parse_due(old['dueAt'])<=now+dt.timedelta(minutes=10):
            raise RuntimeError('Post imminent: mise à jour refusée')
        effective_due=old['dueAt']
        mutation={'id':old['id'],'text':payload['text'],'assets':payload['assets'],
                  'metadata':payload['metadata'],'schedulingType':'automatic',
                  'mode':'customScheduled','dueAt':effective_due}
        answer=_graphql(post,api_key,EDIT_MUTATION,{'input':mutation})
        ident,status=_mutation_result(api_key,answer,'editPost',effective_due,expected_id=old['id'])
        action='MISE_A_JOUR'
    else:
        answer=_graphql(post,api_key,MUTATION,{'input':payload})
        ident,status=_mutation_result(api_key,answer,'createPost',payload['dueAt'])
    result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':action,
        'id_buffer':ident,'status_buffer':status,'edition':edition,
        'date_programmee_utc':effective_due,'pages':8,'version_contenu':VERSION,
        'texte_public':payload['text']}
    receipt_path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--public-base-url',required=True)
    p.add_argument('--send',action='store_true')
    p.add_argument('--previous-receipt',type=Path)
    a=p.parse_args()
    result=transmettre(a.folder,a.public_base_url,send=a.send,previous_receipt=a.previous_receipt,
         api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''))
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
