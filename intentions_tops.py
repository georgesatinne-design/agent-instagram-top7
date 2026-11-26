"""Réservation persistante d'une édition avant la création d'un post Buffer.
Après une réponse perdue, on ne renvoie jamais à l'aveugle. Un post exact
encore programmé peut être réconcilié ; une absence exige un contrôle humain.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from calendrier_editorial import parse_due,utc
from historique_editions import edition_key
from journal_publication import TOP_INTENTS,checkpoint

def enabled():
    return os.environ.get('ILLYADERA_DURABLE_JOURNAL')=='1'

def read(path=None):
    p=Path(path or TOP_INTENTS)
    if not p.exists():return {}
    data=json.loads(p.read_text(encoding='utf8'))
    if not isinstance(data,dict):raise ValueError('Journal des Tops corrompu')
    return data

def lookup(edition,path=None):
    edition_key(edition)
    return read(path).get(edition)

def write(data,path=None):
    p=Path(path or TOP_INTENTS)
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    tmp.replace(p)
    checkpoint(p)

def fingerprint(text):
    return hashlib.sha256(text.strip().encode('utf8')).hexdigest()

def reserve(edition,payload,*,path=None,now=None):
    edition_key(edition)
    data=read(path)
    if edition in data:
        raise RuntimeError('Création déjà réservée pour '+edition+' : aucun nouvel envoi automatique')
    rec={'etat':'CREATION_EN_COURS','edition':edition,
         'due_at':utc(parse_due(payload['dueAt'])),
         'empreinte_texte':fingerprint(payload['text']),
         'date_utc':(now or dt.datetime.now(dt.timezone.utc)).isoformat()}
    data[edition]=rec
    write(data,path)
    return rec

def recoverable(edition,post,payload,*,path=None):
    rec=lookup(edition,path)
    if not rec:return False
    return bool(post.get('id') and post.get('status')=='scheduled'
                and fingerprint(post.get('text',''))==rec.get('empreinte_texte')==fingerprint(payload['text'])
                and parse_due(post['dueAt'])==parse_due(rec['due_at'])
                and (not rec.get('id_buffer') or rec['id_buffer']==post['id']))

def confirm(edition,identifier,due,*,path=None):
    data=read(path)
    rec=data.get(edition)
    if not rec:return
    if not identifier or parse_due(rec['due_at'])!=parse_due(due):
        raise RuntimeError('Confirmation du Top différente de la réservation')
    rec.update(etat='CONFIRME',id_buffer=identifier)
    write(data,path)
