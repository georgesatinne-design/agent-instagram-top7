"""Chaîne intégrée MANGA. AUCUNE modification des workflows BD.

Collecte publique -> audit des catégories -> historique fiable -> couvertures
ISBN -> 8 PNG selon la charte existante -> manifest strict -> livraison
GitHub Actions/Buffer effectuée dans le workflow (jamais dans cette étape).
"""
from __future__ import annotations
import os
import argparse
import datetime as dt
import io
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse
import requests
from PIL import Image

from manga_sources_hebdo import collect, EvidenceError
from manga_qualite import auditer,read_cache,write_json
from manga_score_publication import evaluer
from sources.couvertures import download_cover,search_google_books,cover_path, GOOGLE_API
from illyadera_covers import resolve_cover
from visual_top7 import render_top7

ROOT=Path(__file__).resolve().parent
COVER_API='https://covers.openlibrary.org/b/isbn/'
HEADERS={'User-Agent':'AgentMangaFrance/2.0 (couvertures ISBN)' }


def _cover_openlibrary(book:dict, folder:Path, *, getter=requests.get) -> tuple[bool,str]:
    """Repli par ISBN exact : n'utilise jamais une recherche d'image par titre seul."""
    ean=str(book.get('ean') or '')
    if not ean.isdigit() or len(ean)!=13:
        return False,'EAN-13 absent ou invalide'
    url=COVER_API+ean+'-L.jpg?default=false'
    try:
        r=getter(url,timeout=18,headers=HEADERS,allow_redirects=True)
        r.raise_for_status()
        parsed=urlparse(getattr(r,'url',url))
        if parsed.scheme!='https' or parsed.hostname not in ('covers.openlibrary.org',):
            return False,'Hôte de couverture non autorisé'
        if not r.headers.get('Content-Type','').startswith('image/') or len(r.content)>3_500_000:
            return False,'Réponse Open Library non image ou trop lourde'
        im=Image.open(io.BytesIO(r.content));im.load()
        if im.width<180 or im.height<250 or im.height/im.width<1.16 or im.height/im.width>2.25:
            return False,'Couverture Open Library non portrait / trop petite'
        dest=cover_path(folder,book['titre']);dest.parent.mkdir(parents=True,exist_ok=True)
        im.convert('RGB').save(dest,format='PNG')
        return True,url
    except (requests.RequestException,ValueError,OSError):
        return False,'Couverture ISBN absente d’Open Library'


def verifier_couvertures(data:dict, folder:Path, *, downloader=download_cover,
                         google=search_google_books, ol=_cover_openlibrary) -> list[dict]:
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    checks=[]
    for row in data['titres']:
        target=cover_path(folder,row['titre'])
        if target.is_file():
            checks.append({'rang':row['rang'],'ean':row.get('ean'), 'ok':True,'origine':'cache local'})
            continue
        selected={}
        if row.get('couverture_candidate_url') and row.get('couverture_reference'):
            selected[row['rang']]={'url':row['couverture_candidate_url'],'reference':row['couverture_reference']}
        success,info=downloader(row,selected,folder)
        if not success:
            # La recherche par titre existante exige la correspondance exacte
            # titre/tome, et ne force pas un candidat approximatif.
            try:alt=google(row)
            except Exception:alt=None
            if alt:success,info=downloader(row,{row['rang']:alt},folder)
        if not success:success,info=ol(row,folder)
        if not success and os.environ.get('ILLYADERA_MULTI_COVER_ON') == '1':
            result=resolve_cover(row,folder)
            if result['ok']:success,info=True,result['source']
            else:info='; '.join(str(a.get('source'))+': '+str(a.get('raison')) for a in result['essais'])[:450]
        checks.append({'rang':row['rang'],'ean':row.get('ean'),'ok':success,'origine':info})
    return checks


def compute_movements(data:dict, previous:dict | None) -> None:
    """Ne calcule la variation que contre une semaine précédente également validée."""
    for row in data['titres']:row['mouvement']='NON DOCUMENTÉ'
    data['variations_verifiees']=False
    if not previous or (previous.get('certification')!='TOP7_EDISTAT_VERIFIE'
                       and not (previous.get('qualite_editoriale') or {}).get('autorise_publication')):return
    try:
        end=dt.date.fromisoformat(previous['fin_ventes'])
        start=dt.date.fromisoformat(data['debut_ventes'])
    except (ValueError,KeyError):return
    if start != end+dt.timedelta(days=1):return
    old={str(x.get('ean')):x['rang'] for x in previous.get('titres',[]) if x.get('ean')}
    for book in data['titres']:
        earlier=old.get(str(book['ean']))
        if earlier is None:book['mouvement']='NOUVEAU'
        else:
            diff=earlier-book['rang']
            book['mouvement']=(f'+{diff} PL.' if diff>0 else f'−{-diff} PL.' if diff<0 else 'STABLE')
    data['variations_verifiees']=True


def produire(*,root=ROOT, sortie=Path('sorties/manga_production'),
             precedent=Path('manga_history/dernier_classement.json'),
             cache=Path('manga_history/genres_ebooks.json'),
             article_url=None, html_actualitte=None, html_bede=None, html_annuel=None,
             resolver=None, covers=None, skip_finalized=False) -> Path:
    root=Path(root);sortie=Path(sortie)
    previous=None
    if Path(precedent).exists():
        previous=json.loads(Path(precedent).read_text(encoding='utf8'))
    from cadence_collecte import finalized
    from manga_buffer_auto import VERSION_PUBLIQUE
    def skipped(data,reason):
        edition='MANGA_'+data['fin_ventes']
        dest=sortie/edition;dest.mkdir(parents=True,exist_ok=True)
        write_json(dest/'ETAT.json',{'edition':edition,'categorie':'MANGA','pret_buffer':False,
            'skip_history':True,'statut_ventes':data.get('certification','NON_RECALCULE'),
            'couvertures':0,'action':reason})
        return dest
    # Le recoupement Bédé.fr a une date de palmarès : une seule lecture légère
    # suffit si la même observation a déjà un reçu, sinon collecte complète.
    if skip_finalized and previous and article_url is None and html_actualitte is None:
        from manga_sources_hebdo import get_html,parse_bede_current,BEDE
        if html_bede is None:html_bede=get_html(BEDE)
        date=dt.datetime.strptime(parse_bede_current(html_bede)['date_palmares'],'%d/%m/%Y').date().isoformat()
        if previous.get('date_publication')==date:
            reason=finalized('MANGA_'+previous['fin_ventes'],root=root,version=VERSION_PUBLIQUE)
            if reason:return skipped(previous,reason)
    dest=collect(root,sortie,article_url=article_url,actualitte_html=html_actualitte,
                 bede_html=html_bede,annual_html=html_annuel,previous_file=None)
    data=json.loads((dest/'classement_manga.json').read_text(encoding='utf8'))
    if skip_finalized:
        reason=finalized('MANGA_'+data['fin_ventes'],root=root,version=VERSION_PUBLIQUE)
        if reason:return skipped(data,reason)
    proofs=json.loads((dest/'preuves_manga.json').read_text(encoding='utf8'))
    kwargs={'cache':read_cache(cache)}
    if resolver is not None:kwargs['resolver']=resolver
    data,proofs,new_cache=auditer(data,proofs,**kwargs)
    # L'audit conserve ses incertitudes : il n'est JAMAIS converti en « certifié ».
    write_json(dest/'preuves_manga.json',proofs)
    write_json(dest/'cache_genre_a_conserver.json',new_cache)
    results=covers(data,dest/'MANGA'/'couvertures') if covers else verifier_couvertures(data,dest/'MANGA'/'couvertures')
    score=evaluer(data,proofs,results)
    data['qualite_editoriale']=score
    compute_movements(data,previous if score['autorise_publication'] else None)
    write_json(dest/'classement_manga.json',data)
    # Le filigrane « PAS POUR PUBLICATION » ne peut jamais être diffusé vers Buffer.
    visual=render_top7(data,dest/'MANGA',dest/'MANGA'/'couvertures',
                         use_watermark=not score['autorise_publication'])
    folder=dest/'MANGA'
    manifest=folder/'post_manifest.json'
    m=json.loads(manifest.read_text(encoding='utf8'))
    m['certification_manga']=data['certification']
    m['qualite_editoriale']=score
    m['mode_publication']=score['mode']
    m['ready_to_stage']=bool(score['autorise_publication'] and not visual['missing_covers'])
    # « source_validated » signifie ici que le palmarès source est vérifié,
    # et non que tous les genres des 200 ouvrages ont été certifiés.
    m['source_validated']=score['source_ok']
    # Le classement reconstitué reste identifié dans les rapports internes,
    # mais aucune source ou mention technique n'apparait dans les publications.
    # Cette version est exigée et recontrôlée dans manga_buffer_auto.py.
    from manga_buffer_auto import VERSION_PUBLIQUE, SOURCE_PUBLIQUE
    m['version_contenu']=VERSION_PUBLIQUE
    legende=(folder/m['caption_file']).read_text(encoding='utf8')
    if SOURCE_PUBLIQUE.search(legende):
        raise ValueError('Sources ou mentions techniques dans la légende publique Manga')
    manifest.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    write_json(folder/'AUDIT_COUVERTURES.json',{'controles':results})
    write_json(dest/'SCORE_PUBLICATION.json',score)
    (folder/'A_VALIDER.md').write_text(
        '# MANGA — décision éditoriale\n\n'
        +f'- Publication Buffer autorisée : **{m["ready_to_stage"]}**\n'
        +f'- Score de contrôle : **{score["valeur"]}/100** (seuil {score["seuil"]})\n'
        +f'- Mode : **{score["mode"]}**\n'
        +f'- Incertitudes bibliographiques : **{score["ouvrages_avant_top7_non_qualifies"]}**\n'
        +'- Ceci n’est PAS une probabilité statistique de classement exact.\n'
        +'- Si le post est accepté par Buffer, il est programmé sans approbation manuelle.\n',
        encoding='utf8')
    status={
       'categorie':'MANGA','edition':'MANGA_'+data['fin_ventes'],
       'periode':[data['debut_ventes'],data['fin_ventes']],
       'statut_ventes':data['certification'],
       'genres_incertains':len(proofs['audit_genre']['indetermines']),
       'mangas_rattrapes':len(proofs['audit_genre']['mangas_possiblement_omis']),
       'couvertures':sum(bool(x.get('ok')) for x in results),
       'pages':visual['pages'],
       'pret_buffer':m['ready_to_stage'],
       'score_qualite_editoriale':score['valeur'],
       'seuil_publication':score['seuil'],
       'mode_publication':score['mode'],
       'actions':('CARROUSEL_PRET' if m['ready_to_stage'] else 'REVUE_AUTOMATIQUE_BLOQUEE'),
    }
    write_json(dest/'ETAT.json',status)
    (dest/'RAPPORT.md').write_text(
       '# Top 7 manga — '+data['fin_ventes']+'\n\n'
       f'- Période : {data["debut_ventes"]} au {data["fin_ventes"]}\n'
       f'- Contrôle des genres : **{data["certification"]}**\n'
       f'- Livres non qualifiés avant le septième manga : {status["genres_incertains"]}\n'
       f'- Couvertures : {status["couvertures"]}/7\n'
       f'- Diapositives : {visual["pages"]}/8\n'
       f'- Score de contrôle éditorial : **{score["valeur"]}/100** (seuil {score["seuil"]})\n'
       f'- Mode de publication : **{score["mode"]}**\n'
       f'- Programmation automatique autorisée : **{status["pret_buffer"]}**\n\n'
       'L’indice ne mesure PAS une probabilité statistique. Un Top reconstitué est clairement identifié, et les incertitudes sont conservées.\n',encoding='utf8')
    return dest


def main():
    p=argparse.ArgumentParser(description='Collecte, audit et carrousel Manga (BD inchangé)')
    p.add_argument('--sortie',default='sorties/manga_production')
    p.add_argument('--precedent',default='manga_history/dernier_classement.json')
    p.add_argument('--cache',default='manga_history/genres_ebooks.json')
    p.add_argument('--article-url')
    p.add_argument('--skip-finalized',action='store_true')
    args=p.parse_args()
    dest=produire(root=ROOT,sortie=Path(args.sortie),precedent=Path(args.precedent),
                 cache=Path(args.cache),article_url=args.article_url,skip_finalized=args.skip_finalized)
    print((dest/'ETAT.json').read_text(encoding='utf8'))

if __name__=='__main__':main()
