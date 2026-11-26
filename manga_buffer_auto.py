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
from manga_score_publication import evaluer, SEUIL
from calendrier_editorial import next_weekly, frozen_slot, assert_arbitrated

# Réutilisation des fonctions GraphQL testées du projet BD, sans modifier leur code.
from buffer_client import (_graphql, _mutation_result, _parse_due,
                           MUTATION, EDIT_MUTATION, ORG_QUERY, SLOT_QUERY)

VERSION_PUBLIQUE='manga_sans_sources_v1'
SOURCE_PUBLIQUE=re.compile(r'(?i)(?:edistat|actualitt[ée]|b[ée]d[ée]\.fr|nielseniq|nielsen|\bbnf\b|reconstitu[ée]|reconstitution)')

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
    if (weekday,hour,minute)==(1,18,0):return next_weekly('MANGA',now)
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
    if m.get('category')!='MANGA' or not m.get('ready_to_stage'):
        raise ValueError('Classement manga pas suffisamment vérifié pour programmation')
    if len(data.get('titres',[]))!=7:
        raise ValueError('Sept mangas exacts requis')
    # Ne jamais se fier au seul booléen écrit dans le manifest : recomposer
    # le score depuis les preuves et l'audit des couvertures générés en amont.
    preuves=json.loads((folder.parent/'preuves_manga.json').read_text(encoding='utf8'))
    aud_couv=json.loads((folder/'AUDIT_COUVERTURES.json').read_text(encoding='utf8'))
    quality=evaluer(data,preuves,aud_couv.get('controles') or [])
    stored=m.get('qualite_editoriale') or {}
    if not quality['autorise_publication'] or quality['valeur']<SEUIL:
        raise ValueError('Score documentaire inférieur à 70/100 : aucun envoi Buffer')
    if quality['valeur']!=stored.get('valeur') or quality['mode']!=m.get('mode_publication'):
        raise ValueError('Score manga incohérent entre source et manifest')
    # Ne jamais transmettre le mode ni les sources bibliographiques au public.
    if m.get('version_contenu') != VERSION_PUBLIQUE:
        raise ValueError('Version publique sans sources non installée')
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
    if SOURCE_PUBLIQUE.search(caption):
        raise ValueError('La légende publique contient un nom de source ou une mention technique')
    expected_date=dt.date.fromisoformat(data['fin_ventes'])
    if date_periode_captation(caption)!=expected_date:
        raise ValueError('Période de ventes différente entre données et légende')
    now=now or dt.datetime.now(dt.timezone.utc)
    age=(now.date()-expected_date).days
    if age<0 or age>21:
        raise ValueError('Classement trop ancien ou futur : aucun dépôt Buffer')
    if not channel_id:raise ValueError('Identifiant canal Buffer absent')
    return {'text':caption,'channelId':channel_id,'schedulingType':'automatic',
            'mode':'customScheduled','dueAt':frozen_slot('MANGA',mardi_suivant(now=now),now=now),
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
                get=requests.get,now=None,previous_receipt=None)->dict:
    """Déposer rapidement le carrousel et corriger une édition déjà en queue.

    Un reçu versionné permet l'idempotence, y compris quand GitHub relance
    le workflow plusieurs fois dans la même journée. Les posts publiés ou
    dont la date est passée ne sont jamais remis en queue automatiquement.
    """
    folder=Path(folder)
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError('Date courante sans fuseau horaire')
    payload=construire(folder,base_url,channel_id,now=now)
    edition='MANGA_'+str(date_periode_captation(payload['text']))
    if not send:
        return {'statut':'SIMULATION','edition':edition,'images':8,
                'date_programmee_utc':payload['dueAt']}
    if not api_key:raise ValueError('Accès Buffer absent')
    receipt=folder/'RECU_BUFFER.json'
    old_path=Path(previous_receipt) if previous_receipt else receipt
    prior=json.loads(old_path.read_text(encoding='utf8')) if old_path.is_file() else None
    if prior:
        if prior.get('edition')!=edition or prior.get('statut')!='POST_PROGRAMME' or not prior.get('id_buffer'):
            raise RuntimeError('Ancien reçu Buffer incompatible : vérification manuelle requise')
        planned=_parse_due(prior['date_programmee_utc'])
        if planned <= now+dt.timedelta(minutes=10):
            # Le post peut être en cours de publication : ne pas le dupliquer.
            result={**prior,'action':'DEJA_TRANSMIS_NON_MODIFIABLE'}
            receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            return result
        if prior.get('version_contenu')==VERSION_PUBLIQUE:
            receipt.write_text(json.dumps(prior,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            return prior
    # Publier les images sur GitHub AVANT cette vérification d'accessibilité.
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
    from intentions_tops import enabled,lookup
    intent=lookup(edition) if enabled() and not prior else None
    if intent and _parse_due(intent['due_at'])<=now:
        raise RuntimeError('Création Manga ancienne sans reçu : contrôle humain, aucun renvoi')
    posts=_list_manga_programmes(api_key,channel_id,intent['due_at'] if intent else payload['dueAt'],post=post)
    current=date_periode_captation(payload['text'])
    same=[p for p in posts if date_periode_captation(p['text'])==current]
    if len(same)>1:raise RuntimeError('Plusieurs posts manga pour la même période existent dans Buffer')
    action='CREATION'
    effective_due=payload['dueAt']
    if prior and not same:
        # Ne pas créer de doublon si l'ancien post ne ressort pas dans l'API.
        raise RuntimeError('Post Buffer déjà identifié par reçu mais non retrouvé : création interdite')
    if same:
        old=same[0]
        if not prior:
            from intentions_tops import enabled,lookup,recoverable,confirm
            if enabled() and (not lookup(edition) or not recoverable(edition,old,payload)):
                raise RuntimeError('Post Manga sans intention correspondante : vérification nécessaire')
            if (old.get('text') or '').strip()!=payload['text'].strip():
                raise RuntimeError('Post manga sans reçu correspondant : modification interdite')
            result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':'RECU_RECONSTRUIT',
                    'id_buffer':old['id'],'status_buffer':old['status'],'edition':edition,
                    'date_programmee_utc':old['dueAt'],'pages':8,'version_contenu':VERSION_PUBLIQUE}
            receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            if enabled():confirm(edition,old['id'],old['dueAt'])
            return result
        if prior and old['id']!=prior['id_buffer']:
            raise RuntimeError('ID Buffer différent du reçu : création et modification interdites')
        # Préserver le créneau du post déjà programmé, même si le prochain
        # mardi calculé serait désormais le mardi de la semaine suivante.
        effective_due=old['dueAt']
        if _parse_due(effective_due)<=now+dt.timedelta(minutes=10):
            raise RuntimeError('Publication imminente : modification refusée pour ne pas créer de doublon')
        edited={'id':old['id'],'text':payload['text'],'assets':payload['assets'],
                'metadata':payload['metadata'],'schedulingType':'automatic',
                'mode':'customScheduled','dueAt':effective_due}
        if os.environ.get('ILLYADERA_SLOT_PLAN'):
            from controle_file import final_guard
            final_guard('MANGA',effective_due,api_key=api_key,channel_id=channel_id,post=post,expected_id=old['id'])
            if _parse_due(effective_due)!=_parse_due(prior['date_programmee_utc']):raise RuntimeError('Créneau du reçu modifié')
        response=_graphql(post,api_key,EDIT_MUTATION,{'input':edited})
        ident,status=_mutation_result(api_key,response,'editPost',effective_due,expected_id=old['id'])
        action='CORRECTION_PROGRAMMEE'
    else:
        same_slot=[p for p in posts if abs((_parse_due(p['dueAt'])-_parse_due(payload['dueAt'])).total_seconds())<90]
        if len(same_slot)>1:raise RuntimeError('Plusieurs posts manga sur le même créneau')
        if same_slot:
            raise RuntimeError('Créneau manga occupé par une autre édition sans reçu correspondant')
        else:
            if os.environ.get('ILLYADERA_SLOT_PLAN'):
                from controle_file import final_guard
                assert_arbitrated('MANGA',payload['dueAt'])
                final_guard('MANGA',payload['dueAt'],api_key=api_key,channel_id=channel_id,post=post)
            from intentions_tops import enabled,reserve
            if enabled():reserve(edition,payload)
            response=_graphql(post,api_key,MUTATION,{'input':payload})
            ident,status=_mutation_result(api_key,response,'createPost',payload['dueAt'])
    result={'statut':'POST_PROGRAMME','publication':'QUEUE_BUFFER','action':action,
            'id_buffer':ident,'status_buffer':status,'edition':edition,
            'date_programmee_utc':effective_due,'pages':8,'version_contenu':VERSION_PUBLIQUE}
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    from intentions_tops import enabled,confirm
    if enabled() and action=='CREATION':confirm(edition,ident,effective_due)
    return result


def main():
    p=argparse.ArgumentParser(description='Programme uniquement un manga contrôlé dans Buffer')
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--public-base-url',required=True)
    p.add_argument('--send',action='store_true',help='Sans --send : simulation sans API')
    p.add_argument('--previous-receipt',type=Path,help='Reçu GitHub dune édition déjà programmée')
    args=p.parse_args()
    print(json.dumps(transmettre(args.folder,args.public_base_url,
      api_key=os.getenv('BUFFER_API_KEY',''),channel_id=os.getenv('BUFFER_CHANNEL_ID',''),
      send=args.send,previous_receipt=args.previous_receipt),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
