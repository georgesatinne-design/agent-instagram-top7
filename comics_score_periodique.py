"""Seuil utilisateur 70/100; score DOCUMENTAIRE, pas probabilité statistique."""
import datetime as dt

SEUIL=70.0

def calculer(data,preuves,couvertures,*,today=None):
    today=today or dt.date.today()
    cad=data.get('cadence');n=5 if cad=='HEBDO' else 7
    rows=data.get('titres') or []
    ranks=len(rows)==n and [r.get('rang') for r in rows]==list(range(1,n+1))
    distinct=len({str(r.get('titre','')).strip().casefold() for r in rows})==n
    valid=all(r.get('titre') and r.get('preuve_genre') in ('mdcu_palmares_comics','bdfugue_rubrique_comics') for r in rows)
    publisher=all(2<len(str(r.get('editeur') or ''))<=85 for r in rows)
    covers_ok=len(couvertures)==n and all(r.get('ok') for r in couvertures)
    time_ok=False
    try:
        if data.get('mode_interne')=='BDFUGUE_30J':
            stamp=dt.date.fromisoformat(data['date_releve'])
            time_ok=0<=(today-stamp).days<=7
        else:
            stamp=dt.date.fromisoformat(data['date_article'])
            time_ok=0<=(today-stamp).days<=(9 if cad=='HEBDO' else 45)
    except (KeyError,ValueError):pass
    provenance=bool(str(data.get('url_source','')).startswith('https://'))
    period=bool(data.get('periode_label'))
    points={
        'rang_source_date_et_fenetre':25 if (time_ok and period and provenance) else 0,
        'ordre_et_identites':25 if ranks and distinct and valid else 0,
        'couvertures_verifiees':20 if covers_ok else 0,
        'editeurs':10 if publisher else 0,
        'palmares_explicitement_comics':10 if data.get('mode_interne') in ('MDCU_HEBDO','MDCU_MENSUEL','BDFUGUE_30J') else 0,
        'methode_non_melangee':10 if preuves.get('mode_interne')==data.get('mode_interne') else 0,
    }
    total=sum(points.values())
    gates=ranks and distinct and valid and publisher and covers_ok and time_ok and provenance and period
    return {'valeur':round(total,2),'seuil':SEUIL,'unite':'points_sur_100_non_probabiliste',
            'autorise_publication':bool(total>=SEUIL and gates),
            'points':points,'n':n,'cadence':cad,'limite':'Classement de ventes au sein d une enseigne, pas un Top national France'}
