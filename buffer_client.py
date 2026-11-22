"""Buffer GraphQL Free : programme directement le post dans la Queue Buffer.
Aucun passage par les brouillons : l'agent dépose un carrousel programmé au créneau calculé.
Documentation : https://developers.buffer.com/examples/create-draft-post.html
Media : https://developers.buffer.com/guides/hosting-media.html
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from PIL import Image
from calendrier import prochain_creneau

API_URL='https://api.buffer.com'
MUTATION='''mutation CreatePost($input: CreatePostInput!) {
 createPost(input: $input) {
   __typename
   ... on PostActionSuccess { post { id text dueAt status } }
   ... on MutationError { message }
 }
}'''

def construct_draft(folder,public_base_url):
    folder=Path(folder)
    manifest=json.loads((folder/'post_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status')!='DRAFT_ONLY':raise ValueError('Manifest non sécurisé')
    if not manifest.get('ready_to_stage'):raise ValueError('Carrousel incomplet ou démonstration, dépôt Buffer refusé')
    slides=manifest.get('pages',[])
    if len(slides)!=8:raise ValueError('Un carrousel Top 7 doit avoir exactement 8 pages')
    if [x[:2] for x in slides]!=[f'{i:02d}' for i in range(1,9)]:raise ValueError('Ordre des images incorrect')
    u=urlparse(public_base_url)
    if u.scheme!='https' or not u.netloc or u.username or u.password or not public_base_url.endswith('/'):
        raise ValueError('URL de médias publique HTTPS et terminée par / obligatoire')
    media=[]
    for name in slides:
        p=folder/name
        if not p.is_file():raise FileNotFoundError(p)
        with Image.open(p) as im:
            if im.size!=(1080,1350) or im.format!='PNG':raise ValueError(f'Fichier PNG Instagram invalide : {name}')
        media.append({'image':{'url':public_base_url+quote(name)}})
    caption=(folder/manifest['caption_file']).read_text(encoding='utf-8').strip()
    if not caption or len(caption)>2200:raise ValueError('Légende manquante ou trop longue pour Instagram')
    # Instagram exige explicitement le type de publication dans ses metadata.
    # Huit images = carrousel dans le flux; saveToDraft=True garantit le brouillon.
    payload = {
        'text':caption,
        'schedulingType':'automatic',
        'mode':'addToQueue',
        'assets':media,
        'metadata':{'instagram':{'type':'post','shouldShareToFeed':True}},
    }
    # Créneau décidé par le calendrier interne : le post est envoyé directement
    # dans la file Buffer au lieu d'être laissé en brouillon.
    suggestion = prochain_creneau(manifest.get('category', 'BD'))
    if suggestion:
        payload['mode']='customScheduled'
        payload['dueAt']=suggestion['dueAt']
    return payload

def draft_payload(folder,public_base_url,channel_id):
    if not channel_id:raise ValueError('BUFFER_CHANNEL_ID manquant')
    data=construct_draft(folder,public_base_url)
    data['channelId']=channel_id
    return {'query':MUTATION,'variables':{'input':data}}

def check_urls(payload,*,getter=requests.get):
    for a in payload['variables']['input']['assets']:
        url=a['image']['url']
        response=getter(url,timeout=15,headers={'User-Agent':'AgentInstagramTop7/3.0'},stream=True)
        try:
            response.raise_for_status()
            if 'image/' not in response.headers.get('Content-Type','').lower():raise RuntimeError('Média public non reconnu : '+url)
        finally:
            response.close()

def deposit_draft(folder,public_base_url,channel_id,api_key,*,send=False,check_images=True,post=requests.post):
    folder=Path(folder)
    payload=draft_payload(folder,public_base_url,channel_id)
    if not send:return {'statut':'SIMULATION','publication':'QUEUE_BUFFER','images':8,'texte':len(payload['variables']['input']['text']),'date_programmee_utc':payload['variables']['input'].get('dueAt'),'urls':[x['image']['url'] for x in payload['variables']['input']['assets']]}
    if not api_key:raise ValueError('BUFFER_API_KEY manquant')
    receipt=folder/'RECU_BUFFER.json'
    if receipt.exists():return {'statut':'DEJA_DEPOSE','recu':json.loads(receipt.read_text(encoding='utf-8'))}
    if check_images:check_urls(payload)
    r=post(API_URL,json=payload,headers={'Content-Type':'application/json','Authorization':f'Bearer {api_key}'},timeout=35)
    r.raise_for_status()
    ans=r.json()
    # Les erreurs sont des types CONCRETS : InvalidInputError, UnauthorizedError,
    # LimitReachedError... ; leur __typename n'est jamais 'MutationError'
    # (MutationError est une interface). Ne jamais masquer le motif du refus.
    def safe_message(message):
        return str(message or '').replace(api_key,'[CLE_MASQUEE]')[:750]
    if ans.get('errors'):
        messages='; '.join(safe_message(x.get('message')) for x in ans['errors'] if isinstance(x,dict))
        raise RuntimeError('Buffer GraphQL : '+(messages or 'Erreur non détaillée'))
    entry=(ans.get('data') or {}).get('createPost') or {}
    response_type=entry.get('__typename','inconnu')
    if entry.get('message'):
        raise RuntimeError(f'Buffer refuse le brouillon ({response_type}) : {safe_message(entry["message"])}')
    post_record=entry.get('post') or {}
    status=str(post_record.get('status') or '').lower()
    identifier=post_record.get('id')
    if not identifier:
        raise RuntimeError(
            'Buffer ne confirme pas la création du post programmé; '
            f'type de réponse : {response_type}. '
            'Vérifier la Queue Buffer avant toute nouvelle tentative.'
        )
    if status == 'draft':
        raise RuntimeError("Buffer a créé un brouillon au lieu d'un post en queue. Vérifier immédiatement la configuration.")
    out={
        'statut':'POST_PROGRAMME',
        'id_buffer':identifier,
        'publication':'QUEUE_BUFFER',
        'status_buffer':status or 'inconnu',
        'pages':8,
        'date_programmee_utc':payload['variables']['input'].get('dueAt')
    }
    receipt.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Déposer un carrousel Top 7 directement dans la Queue Buffer')
    parser.add_argument('--folder',required=True)
    parser.add_argument('--public-base-url',required=True)
    parser.add_argument('--send',action='store_true',help='Effectuer réellement le dépôt; sans ce drapeau simulation uniquement')
    args=parser.parse_args()
    result=deposit_draft(args.folder,args.public_base_url,os.getenv('BUFFER_CHANNEL_ID','DEMO_CHANNEL'),os.getenv('BUFFER_API_KEY',''),send=args.send)
    print(json.dumps(result,ensure_ascii=False,indent=2))
