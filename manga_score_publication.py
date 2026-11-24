"""Politique de mise en ligne du Top 7 MANGA.

Le score est un INDICE DE QUALITÉ DOCUMENTAIRE interne sur 100 points,
PAS une probabilité statistique que les sept rangs nationaux soient exacts.
Le score est reconstructible depuis classement, preuves et audit des images.
Ne jamais convertir les incertitudes bibliographiques en certitudes.
Ne modifie aucun élément BD.
"""
from __future__ import annotations
import datetime as dt
import re
from urllib.parse import urlparse

SEUIL=70.0
COUVERTURE_MIN=0.20


def ean_valide(s: str) -> bool:
    if not isinstance(s,str) or not re.fullmatch(r'(?:978|979)\d{10}',s):return False
    d=[int(x) for x in s]
    return (10 - sum(x*(1 if i%2==0 else 3) for i,x in enumerate(d[:-1]))%10)%10 == d[-1]


def evaluer(classement:dict,preuves:dict,couvertures:list[dict]) -> dict:
    """Évaluation prudente avec des poids publics et auditables.

    30 pts palmarès complet sourcé + semaine cohérente ; 25 pts ISBN/rangs
    des sept candidats ; 15 pts les sept couvertures ; 30 pts exhaustivité
    des catégories parmi les livres avant le 7e manga.

    Avec 46 livres inconnus parmi 62 ouvrages précédant ou occupant le Top7,
    le score n'est PAS « 78 % de chances que le classement soit exact ».
    """
    books=classement.get('titres') or []
    audit=preuves.get('audit_genre') or {}
    details=audit.get('details') or []
    p=preuves.get('periode_ventes') or []
    src=urlparse(str(classement.get('url_source') or ''))
    try:
        debut=dt.date.fromisoformat(classement['debut_ventes'])
        fin=dt.date.fromisoformat(classement['fin_ventes'])
        parution=dt.date.fromisoformat(classement['date_publication'])
        date_bede=dt.datetime.strptime(preuves['date_palmares_bede'],'%d/%m/%Y').date()
        bon_calendrier=(fin-debut).days==6 and debut.weekday()==0 and 0 <= (parution-fin).days <= 14 and date_bede==parution
    except (ValueError,KeyError,TypeError):
        bon_calendrier=False
    source_ok=(src.scheme=='https' and src.hostname in ('actualitte.com','www.actualitte.com')
               and '/article/' in src.path and preuves.get('articles_dans_top200')==200
               and p==[classement.get('debut_ventes'),classement.get('fin_ventes')]
               and bon_calendrier)
    ranks=[x.get('rang') for x in books]
    positions=[x.get('rang_general_livres') for x in books]
    eans=[x.get('ean') for x in books]
    allowed={'ean_identifie','bede_categorie_manga','catalogue_manga_annuel','editeur_manga','isbn_manga_confirme'}
    candidats_ok=(len(books)==7 and ranks==list(range(1,8))
        and len(set(eans))==7 and all(ean_valide(e) for e in eans)
        and len(set(positions))==7 and all(type(v) is int and 1<=v<=200 for v in positions)
        and positions==sorted(positions)
        and all(x.get('preuve_genre') in allowed for x in books))
    allowed_cover_eans=set(eans)
    cover_set={x.get('ean') for x in couvertures if x.get('ok') and x.get('ean') in allowed_cover_eans}
    couverture_ok=bool(candidats_ok and len(cover_set)==7 and len(couvertures)==7)
    # N'utiliser le décompte que si l'audit décrit bien la même population
    # de livres : le TOP7 et tous les ouvrages incertains situés avant le #7.
    # L'ordre de grandeur de l'incertitude ne sera jamais masqué.
    details_valid=(isinstance(details,list) and audit.get('avant_septieme_examines')==len(details)
        and len({x.get('ean') for x in details})==len(details)
        and all(x.get('statut') in ('NON_MANGA','MANGA','INCERTAIN') for x in details))
    # Le nombre total de livres vérifiés/candidats est celui des 7 titres
    # candidats et des ouvrages ayant requis une enquête de genre.
    known_non=sum(x.get('statut')=='NON_MANGA' for x in details) if details_valid else 0
    coverage=(7+known_non)/(7+len(details)) if details_valid and candidats_ok else 0.0
    genre_points=round(30*coverage,2)
    score=round((30 if source_ok else 0)+(25 if candidats_ok else 0)
                +(15 if couverture_ok else 0)+genre_points,2)
    approved=bool(source_ok and candidats_ok and couverture_ok and details_valid
                  and coverage>=COUVERTURE_MIN and score>=SEUIL)
    regime=('VERIFIE' if approved and not any(x.get('statut')=='INCERTAIN' for x in details)
            else 'RECONSTITUE' if approved else 'NON_AUTORISE')
    return {
        'valeur':score,'seuil':SEUIL,'unite':'points_sur_100_non_probabiliste',
        'mode':regime,'autorise_publication':approved,
        'source_ok':source_ok,'sept_ouvrages_ok':candidats_ok,
        'sept_couvertures_ok':couverture_ok,'audit_genre_ok':details_valid,
        'taux_ouvrages_qualifies':round(100*coverage,2),
        'ouvrages_avant_top7_non_qualifies':sum(x.get('statut')=='INCERTAIN' for x in details),
        'details_points':{'palmares_et_periode':30 if source_ok else 0,
            'mangas_ean_et_rangs':25 if candidats_ok else 0,
            'couvertures':15 if couverture_ok else 0,
            'controle_genre':genre_points},
        'limite':'Indice de contrôle éditorial, PAS une probabilité de rangs exacts ou un Top manga national exhaustif',
    }
