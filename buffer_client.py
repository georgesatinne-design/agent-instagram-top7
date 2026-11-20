"""Buffer GraphQL Free : crée uniquement un BROUILLON, jamais une publication programmée.
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

API_URL='https://api.buffer.com'
MUTATION='''mutation CreateDraftPost($input: CreatePostInput!) {
 createPost(input: $input) {
   __typename
   ... on PostActionSuccess { post { id text dueAt } }
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
    return {'text':caption,'schedulingType':'automatic','mode':'addToQueue','saveToDraft':True,'assets':media}

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
    if not send:return {'statut':'SIMULATION','publication':'INTERDITE','images':8,'texte':len(payload['variables']['input']['text']),'urls':[x['image']['url'] for x in payload['variables']['input']['assets']]}
    if not api_key:raise ValueError('BUFFER_API_KEY manquant')
    receipt=folder/'RECU_BUFFER.json'
    if receipt.exists():return {'statut':'DEJA_DEPOSE','recu':json.loads(receipt.read_text(encoding='utf-8'))}
    if check_images:check_urls(payload)
    r=post(API_URL,json=payload,headers={'Content-Type':'application/json','Authorization':f'Bearer {api_key}'},timeout=35)
    r.raise_for_status()
    ans=r.json()
    if ans.get('errors'):raise RuntimeError('Erreur GraphQL : '+str(ans['errors'])[:300])
    entry=(ans.get('data') or {}).get('createPost') or {}
    if entry.get('__typename')=='MutationError':raise RuntimeError('Buffer a refusé le brouillon : '+str(entry.get('message')))
    identifier=(entry.get('post') or {}).get('id')
    if not identifier:raise RuntimeError('Buffer ne confirme pas la création du brouillon')
    # Réception d'une preuve concrète, sans jamais programmer ou publier.
    out={'statut':'BROUILLON_DEPOSE','id_buffer':identifier,'publication':'NON','pages':8}
    receipt.write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Déposer un carrousel Top 7 comme BROUILLON Buffer seulement')
    parser.add_argument('--folder',required=True)
    parser.add_argument('--public-base-url',required=True)
    parser.add_argument('--send',action='store_true',help='Effectuer réellement le dépôt; sans ce drapeau simulation uniquement')
    args=parser.parse_args()
    result=deposit_draft(args.folder,args.public_base_url,os.getenv('BUFFER_CHANNEL_ID','DEMO_CHANNEL'),os.getenv('BUFFER_API_KEY',''),send=args.send)
    print(json.dumps(result,ensure_ascii=False,indent=2))
