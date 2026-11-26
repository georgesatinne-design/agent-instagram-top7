"""Buffer GraphQL : 1 seul Top 7 BD par créneau hebdomadaire.

Si un ancien Top 7 BD est déjà programmé à la même heure, le nouveau le
remplace via editPost au lieu de créer une deuxième publication.
Aucune approbation manuelle ni passage par les brouillons.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from PIL import Image

from calendrier import prochain_creneau
from calendrier_editorial import next_weekly,frozen_slot,assert_arbitrated

API_URL = 'https://api.buffer.com'

MUTATION = '''mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id text dueAt status } }
    ... on MutationError { message }
  }
}'''

EDIT_MUTATION = '''mutation EditExistingPost($input: EditPostInput!) {
  editPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id text dueAt status } }
    ... on MutationError { message }
  }
}'''

ORG_QUERY = '''query GetOrganizations {
  account { organizations { id } }
}'''

SLOT_QUERY = '''query CheckScheduledSlot(
  $organizationId: OrganizationId!, $channelId: ChannelId!,
  $slotStart: DateTime!, $slotEnd: DateTime!
) {
  posts(first: 40, input: {
    organizationId: $organizationId,
    filter: {
      status: [scheduled], channelIds: [$channelId],
      dueAt: {start: $slotStart, end: $slotEnd}
    }
  }) {
    pageInfo { hasNextPage }
    edges { node { id text dueAt status channelId } }
  }
}'''

BD_HEADER = re.compile(r'^\s*(?:📚\s*)?TOP\s*7\s*BD\b', re.IGNORECASE)
PERIOD_END = re.compile(r'\bAU\s+(\d{2}/\d{2}/\d{4})\b', re.IGNORECASE)


def construct_draft(folder, public_base_url):
    """Historical name kept to avoid breaking workflow and existing tests."""
    folder = Path(folder)
    manifest = json.loads((folder / 'post_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'READY_FOR_QUEUE':
        raise ValueError('Manifest non autorisé pour programmation en Queue')
    if not manifest.get('ready_to_stage'):
        raise ValueError('Carrousel incomplet ou démonstration, dépôt Buffer refusé')
    slides = manifest.get('pages', [])
    if len(slides) != 8:
        raise ValueError('Un carrousel Top 7 doit avoir exactement 8 pages')
    if [x[:2] for x in slides] != [f'{i:02d}' for i in range(1, 9)]:
        raise ValueError('Ordre des images incorrect')
    u = urlparse(public_base_url)
    if u.scheme != 'https' or not u.netloc or u.username or u.password or not public_base_url.endswith('/'):
        raise ValueError('URL de médias publique HTTPS et terminée par / obligatoire')
    media = []
    for name in slides:
        p = folder / name
        if not p.is_file():
            raise FileNotFoundError(p)
        with Image.open(p) as im:
            if im.size != (1080, 1350) or im.format != 'PNG':
                raise ValueError(f'Fichier PNG Instagram invalide : {name}')
        media.append({'image': {'url': public_base_url + quote(name)}})
    caption = (folder / manifest['caption_file']).read_text(encoding='utf-8').strip()
    if not caption or len(caption) > 2200:
        raise ValueError('Légende manquante ou trop longue pour Instagram')
    payload = {
        'text': caption,
        'schedulingType': 'automatic',
        'mode': 'addToQueue',
        'needsApproval': False,
        'assets': media,
        'metadata': {'instagram': {'type': 'post', 'shouldShareToFeed': True}},
    }
    suggestion = prochain_creneau(manifest.get('category', 'BD'))
    if not suggestion:
        raise ValueError('Aucune règle de programmation active pour cette catégorie : dépôt interdit')
    payload['mode'] = 'customScheduled'
    payload['dueAt'] = (frozen_slot('BD',next_weekly('BD')) if os.environ.get('ILLYADERA_SLOT_PLAN') else suggestion['dueAt'])
    return payload


def draft_payload(folder, public_base_url, channel_id):
    if not channel_id:
        raise ValueError('BUFFER_CHANNEL_ID manquant')
    data = construct_draft(folder, public_base_url)
    data['channelId'] = channel_id
    return {'query': MUTATION, 'variables': {'input': data}}


def check_urls(payload, *, getter=requests.get):
    for asset in payload['variables']['input']['assets']:
        url = asset['image']['url']
        response = getter(url, timeout=15, headers={'User-Agent': 'AgentInstagramTop7/3.0'}, stream=True)
        try:
            response.raise_for_status()
            if 'image/' not in response.headers.get('Content-Type', '').lower():
                raise RuntimeError('Média public non reconnu : ' + url)
        finally:
            response.close()


def _graphql(post, api_key, query, variables=None):
    request = {'query': query}
    if variables is not None:
        request['variables'] = variables
    response = post(
        API_URL, json=request,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        timeout=35,
    )
    response.raise_for_status()
    ans = response.json()
    if not isinstance(ans, dict):
        raise RuntimeError('Réponse Buffer illisible')
    if ans.get('errors'):
        messages = '; '.join(str(e.get('message', '')) for e in ans['errors'] if isinstance(e, dict))
        raise RuntimeError('Buffer GraphQL : ' + (messages or 'Erreur inconnue').replace(api_key, '[CLE_MASQUEE]')[:700])
    data = ans.get('data')
    if not isinstance(data, dict):
        raise RuntimeError('Buffer ne renvoie aucune donnée GraphQL')
    return data


def _parse_due(value):
    if not value:
        raise ValueError('Date de publication Buffer absente')
    result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Date Buffer sans fuseau horaire')
    return result.astimezone(dt.timezone.utc)


def _period_end(text):
    match = PERIOD_END.search(text or '')
    if not match:
        raise ValueError('Période du classement non vérifiable : remplacement automatique interdit')
    return dt.datetime.strptime(match.group(1), '%d/%m/%Y').date()


def _find_scheduled_bd_slot(api_key, channel_id, due_at, *, post):
    """Check Buffer itself, not GitHub receipts, so older V15-V17 posts are found too."""
    organizations = (_graphql(post, api_key, ORG_QUERY).get('account') or {}).get('organizations') or []
    selected = os.environ.get('BUFFER_ORGANIZATION_ID', '').strip()
    org_ids = [str(o.get('id', '')) for o in organizations if isinstance(o, dict) and o.get('id')]
    if selected:
        if selected not in org_ids:
            raise RuntimeError('BUFFER_ORGANIZATION_ID ne correspond pas à l’organisation connectée à Buffer')
        org_id = selected
    elif len(org_ids) == 1:
        org_id = org_ids[0]
    else:
        raise RuntimeError('Organisation Buffer ambiguë : impossible de vérifier les créneaux sans risque de doublon')
    due = _parse_due(due_at)
    start = (due - dt.timedelta(seconds=90)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    end = (due + dt.timedelta(seconds=90)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    listing = _graphql(post, api_key, SLOT_QUERY, {
        'organizationId': org_id, 'channelId': channel_id, 'slotStart': start, 'slotEnd': end,
    }).get('posts')
    # Fail closed: malformed/partial API responses are NOT proof the slot is free.
    if not isinstance(listing, dict) or not isinstance(listing.get('edges'), list):
        raise RuntimeError('Lecture de la Queue Buffer incomplète : dépôt refusé pour éviter un doublon')
    page_info = listing.get('pageInfo') or {}
    if page_info.get('hasNextPage') is not False:
        raise RuntimeError('Pagination Buffer incomplète : impossible de garantir un seul Top 7 BD')
    matched = []
    for edge in listing['edges']:
        item = (edge or {}).get('node') or {}
        if not isinstance(item, dict) or not item.get('text') or not item.get('dueAt'):
            raise RuntimeError('Une publication Buffer ne peut pas être identifiée : aucune création autorisée')
        if item.get('channelId') != channel_id or item.get('status') != 'scheduled':
            continue
        if not BD_HEADER.match(item['text']):
            continue
        if abs((_parse_due(item['dueAt']) - due).total_seconds()) > 90:
            continue
        matched.append(item)
    if len(matched) > 1:
        raise RuntimeError('Plusieurs Top 7 BD existent déjà au même horaire : intervention requise, aucun envoi supplémentaire')
    return matched[0] if matched else None


def _mutation_result(api_key, response, op, due_at, expected_id=None):
    entry = response.get(op) or {}
    response_type = entry.get('__typename', 'inconnu')
    if entry.get('message'):
        msg = str(entry['message']).replace(api_key, '[CLE_MASQUEE]')[:700]
        raise RuntimeError(f'Buffer refuse la programmation ({response_type}) : {msg}')
    record = entry.get('post') or {}
    identifier = record.get('id')
    if not identifier:
        raise RuntimeError(f'Buffer ne confirme pas le post ({op}, type {response_type}). Vérifier Buffer avant de réessayer.')
    if expected_id and identifier != expected_id:
        raise RuntimeError('Buffer a renvoyé un autre ID après modification : contrôle nécessaire')
    status = str(record.get('status') or '').lower()
    if status not in ('scheduled', 'buffer'):
        raise RuntimeError(f'Buffer ne confirme pas un post programmé (statut : {status or "absent"})')
    if record.get('dueAt') and _parse_due(record['dueAt']) != _parse_due(due_at):
        raise RuntimeError('Buffer a confirmé un horaire différent : contrôler la Queue')
    return identifier, status


def deposit_draft(folder, public_base_url, channel_id, api_key, *, send=False, check_images=True, post=requests.post):
    folder = Path(folder)
    payload = draft_payload(folder, public_base_url, channel_id)
    request_data = payload['variables']['input']
    if not send:
        return {
            'statut': 'SIMULATION', 'publication': 'QUEUE_BUFFER', 'images': 8,
            'texte': len(request_data['text']), 'date_programmee_utc': request_data['dueAt'],
            'urls': [x['image']['url'] for x in request_data['assets']],
        }
    if not api_key:
        raise ValueError('BUFFER_API_KEY manquant')
    receipt = folder / 'RECU_BUFFER.json'
    if receipt.exists():
        return {'statut': 'DEJA_DEPOSE', 'recu': json.loads(receipt.read_text(encoding='utf-8'))}
    if check_images:
        check_urls(payload)
    # Crucial: BEFORE creating anything, read Buffer to detect a post created
    # by an older version, even when it is absent from GitHub's receipts.
    if os.environ.get('ILLYADERA_SLOT_PLAN'):assert_arbitrated('BD',request_data['dueAt'])
    existing = _find_scheduled_bd_slot(api_key, channel_id, request_data['dueAt'], post=post)
    action = 'CREATION'
    previous_period = None
    if existing:
        old_date = _period_end(existing['text'])
        new_date = _period_end(request_data['text'])
        if old_date > new_date:
            raise RuntimeError('Buffer contient déjà un classement plus récent pour ce vendredi : publication ancienne refusée')
        if old_date == new_date:
            # Same edition, possibly a previous execution that timed out.
            identifier = existing['id']
            status = 'scheduled'
            action = 'DEJA_PROGRAMME'
        else:
            previous_period = old_date.isoformat()
            action = 'REMPLACEMENT'
            edited = {
                'id': existing['id'],
                'text': request_data['text'],
                'assets': request_data['assets'],
                'metadata': request_data['metadata'],
                # Explicit schedule makes the intent independent of Buffer defaults.
                'mode': 'customScheduled',
                'dueAt': request_data['dueAt'],
                'schedulingType': 'automatic',
            }
            if os.environ.get('ILLYADERA_SLOT_PLAN'):
                from controle_file import final_guard
                final_guard('BD',request_data['dueAt'],api_key=api_key,channel_id=channel_id,post=post,expected_id=existing['id'])
            result = _graphql(post, api_key, EDIT_MUTATION, {'input': edited})
            identifier, status = _mutation_result(api_key, result, 'editPost', request_data['dueAt'], expected_id=existing['id'])
    else:
        if os.environ.get('ILLYADERA_SLOT_PLAN'):
            from controle_file import final_guard
            final_guard('BD',request_data['dueAt'],api_key=api_key,channel_id=channel_id,post=post)
        result = _graphql(post, api_key, MUTATION, payload['variables'])
        identifier, status = _mutation_result(api_key, result, 'createPost', request_data['dueAt'])
    out = {
        'statut': 'POST_PROGRAMME', 'action': action, 'id_buffer': identifier,
        'publication': 'QUEUE_BUFFER', 'status_buffer': status,
        'pages': 8, 'date_programmee_utc': request_data['dueAt'],
    }
    if previous_period:
        out['ancienne_fin_ventes'] = previous_period
    receipt.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Programmer le classement BD le plus récent, 1 post par vendredi')
    parser.add_argument('--folder', required=True)
    parser.add_argument('--public-base-url', required=True)
    parser.add_argument('--send', action='store_true', help='Déposer réellement; sinon simulation')
    args = parser.parse_args()
    result = deposit_draft(
        args.folder, args.public_base_url,
        os.getenv('BUFFER_CHANNEL_ID', 'DEMO_CHANNEL'),
        os.getenv('BUFFER_API_KEY', ''), send=args.send,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
