"""V7 : couvertures, semaine exacte, certificat non inventé, aucune Queue."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from manga_v7_complet import (
    titre_correspond, week_from_main_article, date_fraiche, classify_image,
    page_for_ean, images_in_product_page, reessayer_couverture,
    catalogue_courant, editions_dynamique, medias_report, bilan_preparation,
    execute, image_bede_pour_titre, titres_recoupes_dynamiquement,
)

class Response:
    def __init__(self,url,content=b'',ctype='text/html',status=200,js=None):
        self.url=url;self.content=content;self.text=(content.decode('utf-8') if isinstance(content,bytes) else content) if ctype.startswith('text/') else ''
        self.status_code=status;self.headers={'Content-Type':ctype};self._json=js or {}
    def raise_for_status(self):
        if self.status_code>=400:raise ValueError('HTTP '+str(self.status_code))
    def json(self):return self._json


def example():
    a={'categorie':'MANGA','sources':[
        {'source':'bede_bd_manga','inspection':{'date_palmares_affichee':'20/11/2026'}},
        {'source':'actualitte_edistat','articles_detectes':[
            {'url':'https://actualitte.com/article/135341/test'}]}]}
    v={'categorie':'MANGA','date_palmares_bede':'20/11/2026',
       'candidats_non_certifies':[
           {'rang_manga_provisoire':1,'rang_classement_mixte':2,'titre':'Instinct - Tome 3 - Michel Lafon'},
           {'rang_manga_provisoire':2,'rang_classement_mixte':4,'titre':'Spy x Family - tome 17 - Kurokawa Eds'},
           {'rang_manga_provisoire':3,'rang_classement_mixte':11,'titre':"L'Atelier des Sorciers T16 - Collector - Pika"},
           {'rang_manga_provisoire':4,'rang_classement_mixte':13,'titre':'One Piece - Édition originale - Tome 113 - Glénat'},
           {'rang_manga_provisoire':5,'rang_classement_mixte':18,'titre':'Kagurabachi T11 - Kana Eds'},
           {'rang_manga_provisoire':6,'rang_classement_mixte':19,'titre':'Blue Lock T35 - Pika'},
           {'rang_manga_provisoire':7,'rang_classement_mixte':20,'titre':"L'Atelier des Sorciers T06 Edition Grimoire - Pika"}
       ]}
    art='''<html><head><meta property="article:published_time" content="2026-11-20T11:52:00+01:00"></head>
    <body><article><p>Les ventes du 9 au 15 novembre 2026 constituent ce palmarès.</p>
    <p>Instinct tome 3 se classe bien, Spy x Family tome 17 se classe bien.</p>
    <p>Articles recommandés du 2 au 8 novembre 2026.</p></article></body></html>'''
    return a,v,art

class TestMangaV7(unittest.TestCase):
    def test_numero_tome_edition_doivent_correspondre(self):
        self.assertTrue(titre_correspond('Kagurabachi T11','Kagurabachi T11 - Kana Eds'))
        self.assertFalse(titre_correspond('Kagurabachi T10','Kagurabachi T11 - Kana Eds'))
        self.assertFalse(titre_correspond('Atelier des Sorciers T16 Collector','Atelier des Sorciers T16'))
        self.assertFalse(titre_correspond('Atelier des Sorciers T06 Grimoire','Atelier des Sorciers T06'))

    def test_suivi_nouvelles_semaines_sans_titres_figes(self):
        candidats=[{'titre':'Kagurabachi T12 - Kana Eds'},
                   {'titre':'Blue Lock T36 - Pika'}]
        texte='Kagurabachi tome 12 se classe ici et Blue Lock tome 36 monte au classement.'
        self.assertEqual(len(titres_recoupes_dynamiquement(texte,candidats)),2)
        self.assertEqual(titres_recoupes_dynamiquement('Kagurabachi tome 11 et Blue Lock tome 35',candidats),[])

    def test_article_garde_semaine_chapeau_pas_article_lie(self):
        a,v,html=example()
        r=week_from_main_article(a,v,getter=lambda url,**kw:Response(url,html.encode()),today=dt.date(2026,11,23))
        self.assertEqual(r['etat'],'CORROBOREE_PARTIELLEMENT')
        self.assertEqual(r['candidate']['debut'],'2026-11-09')
        self.assertEqual(r['candidate']['fin'],'2026-11-15')
        self.assertFalse(r['ventes_top7_validees'])

    def test_periode_du_palmares_n_est_pas_deduite(self):
        a,v,html=example()
        html=html.replace('du 9 au 15 novembre 2026','le 20 novembre 2026')
        r=week_from_main_article(a,v,getter=lambda url,**kw:Response(url,html.encode()),today=dt.date(2026,11,23))
        self.assertIsNone(r['candidate'])

    def test_classement_ancien_ou_futur_refuse(self):
        self.assertTrue(date_fraiche('20/11/2026',today=dt.date(2026,11,23))['frais'])
        self.assertFalse(date_fraiche('20/10/2026',today=dt.date(2026,11,23))['frais'])
        self.assertFalse(date_fraiche('24/11/2026',today=dt.date(2026,11,23))['frais'])

    def test_classification_distincte_couverture_packshot_promo(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.png';Image.new('RGB',(400,600),'red').save(p)
            self.assertEqual(classify_image(p,edition={'titre':'One Piece tome 113'})['type'],'COUVERTURE_CANDIDATE')
            Image.new('RGB',(400,600),'white').save(p)
            self.assertEqual(classify_image(p,edition={'titre':'Atelier des Sorciers Collector'})['type'],'PACKSHOT_COLLECTOR_A_VERIFIER')
            Image.new('RGB',(1000,400),'blue').save(p)
            self.assertEqual(classify_image(p)['type'],'VISUEL_PROMOTIONNEL_OU_BANNIERE')

    def test_extraction_images_de_fiche_ignorant_logo(self):
        page='''<main><img class="logo" src="https://www.kana.fr/logo.png"/>
        <img data-src="https://www.kana.fr/visuels/kagurabachi-t11.jpg"/></main>'''
        urls=images_in_product_page(page,'https://www.kana.fr/produit/kagurabachi-t11/')
        self.assertEqual(urls,['https://www.kana.fr/visuels/kagurabachi-t11.jpg'])

    def test_page_requiert_isbn_edition(self):
        page=b'<html><main>Kagurabachi tome 11 sans EAN</main></html>'
        with self.assertRaises(ValueError):
            page_for_ean('https://www.bdbase.fr/manga/kagurabachi-11','9782505144656',
                         getter=lambda u,**k:Response(u,page))

    def test_repli_couverture_depuis_rang_exact_bede(self):
        good='''<div><span># 18</span><img alt="Kagurabachi T11 - Kana Eds" src="https://cdn.bede.fr/covers/kagurabachi11.jpg" /></div>'''
        self.assertEqual(image_bede_pour_titre({'titre':'Kagurabachi T11','rang_mixte':18},good),
                         'https://cdn.bede.fr/covers/kagurabachi11.jpg')
        self.assertIsNone(image_bede_pour_titre({'titre':'Kagurabachi T11','rang_mixte':19},good))
        self.assertIsNone(image_bede_pour_titre({'titre':'Kagurabachi T10','rang_mixte':18},good))

    def test_kagurabachi_repli_fiche_francaise_avec_ean(self):
        p=Image.new('RGB',(300,450),'darkblue');bio=io.BytesIO();p.save(bio,'PNG');b=bio.getvalue()
        ean='9782505144656';ed={'ean':ean,'titre':'Kagurabachi T11','url':'https://www.kana.fr/produit/kagurabachi-t11/'}
        def getter(u,**kw):
            if u=='https://www.kana.fr/produit/kagurabachi-t11/':return Response(u,status=403)
            if u=='https://www.bdbase.fr/manga/kagurabachi-11':
                return Response(u,f'<main><p>ISBN {ean}</p><img src="https://www.bdbase.fr/img/couv11.jpg" /></main>'.encode())
            if u=='https://www.bdbase.fr/img/couv11.jpg':return Response(u,b,ctype='image/png')
            return Response(u,status=404)
        with tempfile.TemporaryDirectory() as td:
            r=reessayer_couverture(ed,Path(td)/'couverture.png',getter=getter)
            self.assertTrue(r['ok'])
            self.assertEqual(r['classification']['type'],'COUVERTURE_CANDIDATE')

    def test_ean_catalogue_v5_ne_s_applique_pas_nouvelle_semaine(self):
        catalogue=json.loads((Path(__file__).resolve().parents[1]/'editions_manga_v5.json').read_text())
        a,v,_=example()
        self.assertEqual(len(catalogue_courant(v,catalogue)),7)
        v['date_palmares_bede']='27/11/2026'
        self.assertEqual(catalogue_courant(v,catalogue),[])

    def test_nouveaux_isbn_rendus_provisoires_sans_valider_les_ventes(self):
        a,v,_=example()
        fake=lambda u,**kw:Response(u,b'{}',js={'items':[]})
        ed=editions_dynamique(v,getter=fake)
        self.assertEqual(len(ed),7)
        self.assertTrue(all(x['ean'] is None for x in ed))
        self.assertTrue(all(x['etat_edition']=='EDITION_A_IDENTIFIER' for x in ed))

    def test_rapport_decision_ne_confond_pas_couvertures_et_ventes(self):
        a,v,_=example()
        medias={'trouvees':7,'sur':7,'packshots':0,
                'couvertures':[{'ean':'123','etat_edition':'CATALOGUE_EDITEUR_V5'}]*7}
        period={'etat':'CORROBOREE_PARTIELLEMENT'}
        verdict=bilan_preparation({},period,medias,v,today=dt.date(2026,11,23))
        self.assertEqual(verdict['statut'],'VISUELS_PRETS_A_CONTROLER')
        self.assertFalse(verdict['publication_manga_autorisee'])
        self.assertFalse(verdict['indicateurs']['classement_national_7_rangs_prouve'])

    def test_execute_cree_trois_rapports_et_ne_publie_pas(self):
        a,v,html=example()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'audit_manga.json').write_text(json.dumps(a))
            (root/'verification_manga.json').write_text(json.dumps(v))
            (root/'controle_manga_v6.json').write_text(json.dumps({'evolution_detectee':'PREMIERE_OBSERVATION'}))
            # 7 couvertures prêtes évitent les accès réseau pendant le test.
            cat=json.loads((Path(__file__).resolve().parents[1]/'editions_manga_v5.json').read_text())
            (root/'maquette_v5'/'couvertures').mkdir(parents=True)
            for ed in cat['editions']:
                Image.new('RGB',(250,350),'red').save(root/'maquette_v5'/'couvertures'/f"{ed['ean']}.png")
            cp=root/'catalogue.json';cp.write_text(json.dumps(cat))
            r=execute(root,getter=lambda u,**k:Response(u,html.encode()),today=dt.date(2026,11,23),catalogue_path=cp)
            self.assertEqual(r['medias']['trouvees'],7)
            self.assertFalse(r['publication_manga_autorisee'])
            self.assertEqual(r['queue_buffer'],'NON_MODIFIEE')
            for f in ('TABLEAU_DE_BORD_MANGA_V7.md','manga_v7_rapport.json','CHECKLIST_VALIDATION_MANGA_V7.md'):
                self.assertTrue((root/f).exists(),f)

if __name__=='__main__':unittest.main()
