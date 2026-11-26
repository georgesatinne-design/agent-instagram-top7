"""Réduire le travail sans supprimer les relances automatiques."""
import datetime as dt
import json
from pathlib import Path
from calendrier_editorial import aware,monthly_slot
from historique_editions import newer_receipt,edition_key

def finalized(edition,*,root=Path('.'),version=None,now=None):
    """Un reçu exact ou une intention persistante bloque le rendu répété.
    Une observation non publiée ne bloque jamais les tentatives suivantes.
    Une correction de version reste possible sur un post futur.
    """
    kind,_=edition_key(edition)
    root=Path(root)
    folder=root/({'BD':'buffer_receipts','MANGA':'manga_buffer_receipts',
                   'COMICS_HEBDO':'comics_buffer_receipts','COMICS_MENSUEL':'comics_buffer_receipts'}[kind])
    if newer_receipt(folder,edition):return 'EDITION_DEPASSEE'
    p=folder/(edition+'.json')
    if p.exists():
        rec=json.loads(p.read_text(encoding='utf8'))
        if rec.get('statut')!='POST_PROGRAMME' or rec.get('edition')!=edition or not rec.get('id_buffer'):
            return 'RECU_NON_INTERPRETABLE'
        from calendrier_editorial import parse_due
        if version and rec.get('version_contenu')!=version and parse_due(rec['date_programmee_utc'])>aware(now)+dt.timedelta(minutes=10):
            return None
        return 'EDITION_DEJA_PROGRAMMEE'
    journal=root/'anecdotes_state'/'intentions_tops.json'
    if journal.is_file() and edition in json.loads(journal.read_text(encoding='utf8')):
        return 'EDITION_RESERVEE'
    return None

def monthly_open(now=None):
    local=aware(now)
    last=local.date().replace(day=1)-dt.timedelta(days=1)
    try:monthly_slot(last.year,last.month,local)
    except ValueError:return False
    return True
