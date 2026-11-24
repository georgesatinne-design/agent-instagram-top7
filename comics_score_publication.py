"""Score interne documentaire comics. Un score /100 n'est PAS une probabilité d'exactitude.

La preuve d'un palmarès national et la preuve du classement d'une enseigne
sont des notions différentes; on n'emploie jamais la seconde pour affirmer la
première. Seuil de publication utilisateur = 70/100.
"""
from __future__ import annotations
import datetime as dt
SEUIL=70.0

def calculer(data,evidence,covers,*,today=None):
    today=today or dt.datetime.now(dt.timezone.utc).date()
    titles=data.get('titres',[])
    mode=data.get('mode_interne')
    complete=len(titles)==7 and [x.get('rang') for x in titles]==list(range(1,8))
    distinct=len({x.get('url_produit') or x.get('ean') or x.get('titre') for x in titles})==7
    typed=all(x.get('preuve_genre') in ('rubrique_comics_et_licence_ou_label','bede_categorie_comics','fnac_categorie_comics','bdfugue_rubrique_comics') for x in titles)
    covers_ok=len(covers)==7 and all(x.get('ok') for x in covers)
    dated=False
    try:
        stamp=dt.date.fromisoformat(data['date_releve'])
        dated=0<=(today-stamp).days<=7
    except (KeyError,ValueError):pass
    edition=bool(data.get('edition','').startswith('COMICS_'))
    publisher=all(2<len(str(x.get('editeur','')).strip())<90 for x in titles)
    sources=len(evidence.get('comparaison_comics_bdfugue') or [])>0
    cross=0
    if sources:
        from manga_sources_hebdo import match_titles
        mdcu=evidence['comparaison_comics_bdfugue']
        cross=sum(bool(any(match_titles(x['titre'],r['titre']) for r in mdcu)) for x in titles)
    # Score observable : les critères indispensables sont bloquants.
    points={
        'palmares_explicite':20 if mode in ('RELEVE_ENSEIGNE','NATIONAL_HEBDO') else 0,
        'sept_comics_rangs_distincts':20 if (complete and distinct and typed) else 0,
        'sept_couvertures':20 if covers_ok else 0,
        'releve_actuel':10 if dated else 0,
        'editeurs_et_livres_identifies':10 if publisher else 0,
        'historisation':5 if edition else 0,
        'classement_national':10 if mode=='NATIONAL_HEBDO' else 0,
        'confirmation_complementaire':min(10,cross*2),
        'references_nationales':5 if mode=='NATIONAL_HEBDO' and all(x.get('ean') for x in titles) else 0,
    }
    score=sum(points.values())
    # Score Fnac sans recoupement : 85/100 si 7 livres et 7 couvertures.
    # Interne uniquement : ne constitue pas une couverture du marché français.
    passed=bool(score>=SEUIL and complete and distinct and typed and covers_ok and dated and publisher and edition)
    return {'valeur':round(score,2),'seuil':SEUIL,'unite':'points_sur_100_non_probabiliste',
        'mode':mode,'autorise_publication':passed,'details_points':points,
        'comics_identifies':len(titles),'couvertures':sum(bool(x.get('ok')) for x in covers),
        'perimetre_reel':('Palmarès national général avec sept comics identifiés' if mode=='NATIONAL_HEBDO' else 'Classement des meilleures ventes de l’enseigne '+('BDFugue (30 jours)' if data.get('releve_source')=='BDFUGUE' else 'Fnac')+', relevé le '+str(data.get('date_releve'))),
        'limite':'Ce score évalue des contrôles techniques et éditoriaux, PAS une probabilité de vérité du Top 7 national; un relevé d’enseigne n’est pas un Top national hebdomadaire'}
