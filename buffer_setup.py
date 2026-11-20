"""En lecture seule : liste des comptes Instagram Buffer pour obtenir leur identifiant.
Ne crée et ne modifie aucune publication. Définir BUFFER_API_KEY dans l'environnement.
"""
from __future__ import annotations
import json,os
import requests

URL='https://api.buffer.com'

def query(text,api_key,variables=None):
    r=requests.post(URL,headers={'Content-Type':'application/json','Authorization':f'Bearer {api_key}'},json={'query':text,'variables':variables or {}},timeout=30)
    r.raise_for_status()
    result=r.json()
    if result.get('errors'):raise RuntimeError(str(result['errors'])[:400])
    return result['data']

def main():
    api_key=os.environ.get('BUFFER_API_KEY')
    if not api_key:raise SystemExit('Définir BUFFER_API_KEY dans les variables d’environnement (ne jamais le coller dans le code).')
    organizations=query('query { account { organizations { id name } } }',api_key)['account']['organizations']
    for org in organizations:
        channels=query('query ($organization: OrganizationId!) { channels(input: {organizationId: $organization}) { id name service } }',api_key,{'organization':org['id']})['channels']
        for ch in channels:
            if str(ch['service']).lower()=='instagram':
                print(f'Instagram : {ch["name"]} — BUFFER_CHANNEL_ID={ch["id"]} (organisation {org["name"]})')
if __name__=='__main__':main()
