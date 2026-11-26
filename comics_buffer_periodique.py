"""Poste immédiatement dans Buffer Queue; Instagram jeudi 18 h (Top5) / 2e dimanche 18 h (Top7).
Les postes BD/MANGA sont ignorés. N'utilise pas de sources dans la légende.
"""
from __future__ import annotations
import argparse,datetime as dt,json,os,re,time
from pathlib import Path
from urllib.parse import quote,urlparse
from zoneinfo import ZoneInfo
import requests
from PIL import Image
from buffer_client import _graphql,_mutation_result,_parse_due,MUTATION,EDIT_MUTATION,ORG_QUERY,SLOT_QUERY
from comics_score_periodique import calculer,SEUIL
from comics_visual_periodique import ordered_names
from comics_pipeline_periodique import VERSION
from calendrier_editorial import next_weekly,monthly_slot,frozen_slot,assert_arbitrated

HEADER=re.compile(r'^\s*(?:📚\s*)?TOP\s*(?:5|7)\s*COMICS\b',re.I)
PUBLIC_SOURCE=re.compile(r'(?i)(?:edistat|actualitt[ée]|nielseniq|\bbnf\b|b[ée]d[ée]\.fr|fnac|bdfugue|mdcu|reconstitu[ée]|reconstitution)')

def utc(t):return t.astimezone(dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def next_slot(data,*,now=None):
    if data['cadence']=='HEBDO':
        return next_weekly('COMICS_HEBDO',now)
    if data['cadence']=='MENSUEL':
        return monthly_slot(data['annee'],data['mois'],now)
    raise ValueError('Cadence Comics inconnue')

def construire(folder,base_url,channel_id,*,now=None):
    folder=Path(folder);now=now or dt.datetime.now(dt.timezone.utc)
    manifest=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
    data=json.loads((folder.parent/'classement_comics.json').read_text(encoding='utf8'))
    proof=json.loads((folder.parent/'preuves_comics.json').read_text(encoding='utf8'))
    audit=json.loads((folder/'AUDIT_COUVERTURES.json').read_text(encoding='utf8'))
    n=5 if data.get('cadence')=='HEBDO' else 7
    files=ordered_names(n)
    if manifest.get('category')!='COMICS' or manifest.get('version_contenu')!=VERSION or not manifest.get('ready_to_stage'):
        raise ValueError('Carrousel non prêt')
    if manifest.get('cadence')!=data.get('cadence') or manifest.get('edition')!=data.get('edition'):
        raise ValueError('Cadence ou édition incompatible')
    if manifest.get('pages')!=files:raise ValueError('Pages incorrectes / ordre incorrect')
    policy=calculer(data,proof,audit['controles'],today=now.astimezone(ZoneInfo('Europe/Paris')).date())
    if not policy['autorise_publication'] or policy['valeur']<SEUIL or policy['valeur']!=manifest['quality']['valeur']:
        raise ValueError('Seuil comics non atteint')
    p=urlparse(base_url)
    if p.scheme!='https' or p.hostname!='raw.githubusercontent.com' or not base_url.endswith('/'):
        raise ValueError('Hébergement public des images Github requis')
    assets=[]
    for file in files:
        with Image.open(folder/file) as im:
            if im.format!='PNG' or im.size!=(1080,1350):raise ValueError('PNG de format invalide')
        assets.append({'image':{'url':base_url+quote(file)}})
    text=(folder/'legende_instagram.txt').read_text(encoding='utf8').strip()
    if not HEADER.match(text) or PUBLIC_SOURCE.search(text) or data['periode_label'] not in text or len(text)>2200:
        raise ValueError('Légende publique interdite ou incomplète')
    if not channel_id:raise ValueError('Identifiant canal Buffer manquant')
    return {'text':text,'channelId':channel_id,'schedulingType':'automatic',
            'mode':'customScheduled','dueAt':frozen_slot('COMICS_HEBDO' if n==5 else 'COMICS_MENSUEL',next_slot(data,now=now),now=now),'needsApproval':False,
            'assets':assets,'metadata':{'instagram':{'type':'post','shouldShareToFeed':True}}}

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
    result=_graphql(post,api_key,SLOT_QUERY,{'organizationId':org,'channelId':channel_id,
        'slotStart':utc(now-dt.timedelta(minutes=3)),
        'slotEnd':utc(_parse_due(due)+dt.timedelta(days=8))}).get('posts')
    if not isinstance(result,dict) or (result.get('pageInfo') or {}).get('hasNextPage') is not False:
        raise RuntimeError('Recherche Buffer partielle, création bloquée')
    if not isinstance(result.get('edges'),list):raise RuntimeError('Buffer ne retourne pas les posts')
    found=[]
    for e in result['edges']:
        node=(e or {}).get('node') or {}
        if node.get('status')!='scheduled' or node.get('channelId')!=channel_id:continue
        if not HEADER.match(node.get('text') or ''):continue
        if not node.get('id') or not node.get('dueAt'):raise RuntimeError('Post comics non identifiable')
        found.append(node)
    return found

def transmettre(folder,base_url,*,api_key,channel_id,send=False,now=None,
                 post=requests.post,get=requests.get,previous_receipt=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    folder=Path(folder)
    manifest=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
    edition=manifest['edition'];cadence=manifest['cadence']
    payload=construire(folder,base_url,channel_id,now=now)
    if not send:return {'statut':'SIMULATION','edition':edition,'pages':len(payload['assets']),
                       'date_programmee_utc':payload['dueAt']}
    if not api_key:raise ValueError('Secret Buffer manquant')
    receipt=folder/'RECU_BUFFER.json'
    previous=Path(previous_receipt) if previous_receipt else receipt
    prior=json.loads(previous.read_text(encoding='utf8')) if previous.is_file() else None
    if prior:
        if prior.get('statut')!='POST_PROGRAMME' or prior.get('edition')!=edition or prior.get('cadence')!=cadence:
            raise RuntimeError('Reçu d une autre édition, arrêt pour sécurité')
        due=_parse_due(prior['date_programmee_utc'])
        if due<=now+dt.timedelta(minutes=10):
            result={**prior,'action':'DEJA_TRANSMIS_NON_MODIFIABLE'}
            receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            return result
        if prior.get('version_contenu')==VERSION and prior.get('texte_public')==payload['text']:
            receipt.write_text(json.dumps(prior,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            return prior
    for item in payload['assets']:
        url=item['image']['url'];valid=False
        for attempt in range(5):
            try:
                r=get(url,timeout=15,stream=True)
                try:r.raise_for_status();valid=r.headers.get('Content-Type','').lower().startswith('image/')
                finally:r.close()
            except requests.RequestException:pass
            if valid:break
            if attempt<4:time.sleep(5)
        if not valid:raise RuntimeError('Image inaccessible depuis Buffer: '+url)
    current=_listed(api_key,channel_id,payload['dueAt'],post=post,now=now)
    due=_parse_due(payload['dueAt'])
    matches=[p for p in current if abs((_parse_due(p['dueAt'])-due).total_seconds())<90]
    if prior:matches=[p for p in current if p['id']==prior['id_buffer']]
    if len(matches)>1 or (prior and not matches):raise RuntimeError('Post comics ambigu dans Buffer')
    if matches and not prior:
        if (matches[0].get('text') or '').strip()!=payload['text'].strip():
            raise RuntimeError('Post Comics sans reçu correspondant : modification interdite')
        # Récupération en lecture seule après une confirmation perdue.
        old=matches[0]
        result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':'RECU_RECONSTRUIT',
                'id_buffer':old['id'],'status_buffer':old['status'],'edition':edition,'cadence':cadence,
                'date_programmee_utc':old['dueAt'],'pages':len(payload['assets']),
                'version_contenu':VERSION,'texte_public':payload['text']}
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        return result
    action='CREATION';effective=payload['dueAt']
    if matches:
        old=matches[0]
        if _parse_due(old['dueAt'])<=now+dt.timedelta(minutes=10):raise RuntimeError('Post imminent; non modifiable')
        effective=old['dueAt']
        fields={'id':old['id'],'text':payload['text'],'assets':payload['assets'],
                'metadata':payload['metadata'],'schedulingType':'automatic',
                'mode':'customScheduled','dueAt':effective}
        ans=_graphql(post,api_key,EDIT_MUTATION,{'input':fields})
        ident,status=_mutation_result(api_key,ans,'editPost',effective,expected_id=old['id'])
        action='MISE_A_JOUR'
    else:
        if os.environ.get('ILLYADERA_SLOT_PLAN'):assert_arbitrated('COMICS_HEBDO' if cadence=='HEBDO' else 'COMICS_MENSUEL',payload['dueAt'],now=now)
        ans=_graphql(post,api_key,MUTATION,{'input':payload})
        ident,status=_mutation_result(api_key,ans,'createPost',effective)
    result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':action,
            'id_buffer':ident,'status_buffer':status,'edition':edition,'cadence':cadence,
            'date_programmee_utc':effective,'pages':len(payload['assets']),
            'version_contenu':VERSION,'texte_public':payload['text']}
    receipt.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--folder',type=Path,required=True)
    ap.add_argument('--public-base-url',required=True)
    ap.add_argument('--send',action='store_true')
    ap.add_argument('--previous-receipt',type=Path)
    args=ap.parse_args()
    r=transmettre(args.folder,args.public_base_url,send=args.send,previous_receipt=args.previous_receipt,
       api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''))
    print(json.dumps(r,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
