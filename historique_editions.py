"""Contrôle monotone des éditions déjà réservées ou programmées, hors réseau."""
import datetime as dt
import json
import re
from pathlib import Path

def edition_key(edition):
    m=re.fullmatch(r'(BD|MANGA)_(\d{4}-\d{2}-\d{2})',edition)
    if m:return m[1],dt.date.fromisoformat(m[2])
    m=re.fullmatch(r'COMICS_HEBDO_(\d{4})_W(\d{2})',edition)
    if m:return 'COMICS_HEBDO',dt.date.fromisocalendar(int(m[1]),int(m[2]),1)
    m=re.fullmatch(r'COMICS_MENSUEL_(\d{4})_(\d{2})',edition)
    if m:return 'COMICS_MENSUEL',dt.date(int(m[1]),int(m[2]),1)
    raise ValueError('Identifiant d’édition inconnu : '+str(edition))

def newer_receipt(directory,edition):
    """Ne compare jamais deux cadences distinctes ni les anciens identifiants hashés."""
    kind,period=edition_key(edition)
    for path in sorted(Path(directory).glob(kind+'_*.json'),reverse=True):
        try:other_kind,other=edition_key(path.stem)
        except ValueError:continue
        if other_kind!=kind or other<=period:continue
        rec=json.loads(path.read_text(encoding='utf8'))
        if rec.get('statut') not in ('POST_PROGRAMME','RESERVATION_AVANT_ENVOI'):
            raise ValueError('Reçu plus récent non interprétable : '+path.name)
        if rec.get('edition',path.stem)!=path.stem:raise ValueError('Reçu incohérent : '+path.name)
        return path.stem
    return None
