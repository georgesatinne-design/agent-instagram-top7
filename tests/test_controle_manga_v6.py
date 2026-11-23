"""Tests V6: anti-date inventée, changement de semaine, couvertures, non-publication."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from controle_manga_v6 import (explicit_week_ranges, article_published_on, matched_titles,
    validate_period, evaluate_change, cover_kind, openlibrary_cover, execute, sha_ranking)
from bs4 import BeautifulSoup

BASE=Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, text='', status=200, url='https://actualitte.com/article/135341/exemple', content_type='text/html'):
        self.text=text
        self.content=text.encode('utf-8') if isinstance(text,str) else text
        self.status_code=status
        self.url=url
        self.headers={'Content-Type':content_type}
    def raise_for_status(self):
        if self.status_code >= 400: raise ValueError('HTTP '+str(self.status_code))


def fixtures():
    rows=[(1,'Lucky Luke'),(2,'Instinct - Tome 3'),(3,'Gaston'),(4,'Spy x Family - tome 17'),
          (11,'L Atelier des Sorciers T16 Collector'),(13,'One Piece T113'),(18,'Kagurabachi T11'),
          (19,'Blue Lock T35'),(20,'L Atelier des Sorciers T06')]
    audit={'categorie':'MANGA','sources':[
        {'source':'bede_bd_manga','inspection':{'date_palmares_affichee':'20/11/2026',
            'premieres_entrees_a_verifier':[{'rang_bd_manga':r,'titre_affiche':t} for r,t in rows]}},
        {'source':'actualitte_edistat','articles_detectes':[{'url':'https://actualitte.com/article/135341/exemple'}]}
    ]}
    v={'categorie':'MANGA','date_palmares_bede':'20/11/2026',
       'candidats_non_certifies':[{'titre':'Instinct - Tome 3'}, {'titre':'Spy x Family - tome 17'}]}
    article='''<html><head><meta property="article:published_time" content="2026-11-20T11:52:00+01:00" /></head>
    <body><article><h1>Le Goncourt fait tomber Mélenchon</h1><p>Du 9 au 15 novembre 2026, les ventes sont mesurées.</p>
    <p>Instinct, tome 3 de Inoxtag atteint la troisième place.</p>
    <p>Spy × Family, tome 17 entre à la huitième place.</p></article></body></html>'''
    return audit,v,article


class TestsControleMangaV6(unittest.TestCase):
    def test_semaine_explicite_lundi_dimanche(self):
        self.assertEqual(explicit_week_ranges('du 9 au 15 novembre 2026',2026),
                         [(dt.date(2026,11,9),dt.date(2026,11,15))])
        self.assertEqual(explicit_week_ranges('du 26 octobre au 1er novembre 2026',2026),
                         [(dt.date(2026,10,26),dt.date(2026,11,1))])
        self.assertEqual(explicit_week_ranges('du 10 au 15 novembre 2026',2026),[])

    def test_date_article_explicitement_lue(self):
        a,v,html=fixtures()
        self.assertEqual(article_published_on(BeautifulSoup(html,'html.parser')),dt.date(2026,11,20))
        self.assertIsNone(article_published_on(BeautifulSoup('<p>palmarès 20/11/2026</p>','html.parser')))

    def test_indices_2_titres_mais_pas_semaine_certifiee(self):
        a,v,html=fixtures()
        r=validate_period(a,v,getter=lambda *x,**k:Response(html),today=dt.date(2026,11,23))
        self.assertEqual(r['etat'],'CORROBOREE_PARTIELLEMENT')
        self.assertEqual(r['periode_candidate'],{'debut':'2026-11-09','fin':'2026-11-15'})
        self.assertEqual(set(r['recoupements']),{'instinct','spy x family'})
        self.assertFalse(r['periode_ventes_validee'])

    def test_une_date_publication_ne_devient_pas_ventes(self):
        a,v,html=fixtures()
        html=html.replace('Du 9 au 15 novembre 2026, les ventes sont mesurées.','Palmarès du 20 novembre 2026.')
        r=validate_period(a,v,getter=lambda *x,**k:Response(html),today=dt.date(2026,11,23))
        self.assertIsNone(r['periode_candidate'])
        self.assertEqual(r['etat'],'NON_ETABLIE')

    def test_mauvais_tomes_ne_sont_pas_comptes(self):
        a,v,html=fixtures()
        html=html.replace('tome 3','tome 2').replace('tome 17','tome 16')
        r=validate_period(a,v,getter=lambda *x,**k:Response(html),today=dt.date(2026,11,23))
        self.assertEqual(r['recoupements'],[])

    def test_article_ancien_autre_semaine_refuse(self):
        a,v,html=fixtures()
        html=html.replace('2026-11-20T','2026-11-11T')
        r=validate_period(a,v,getter=lambda *x,**k:Response(html),today=dt.date(2026,11,23))
        self.assertEqual(r['etat'],'NON_ETABLIE')
        self.assertFalse(r['periode_ventes_validee'])

    def test_pas_de_date_future(self):
        a,v,html=fixtures()
        a['sources'][0]['inspection']['date_palmares_affichee']='30/11/2026'
        v['date_palmares_bede']='30/11/2026'
        r=validate_period(a,v,today=dt.date(2026,11,23))
        self.assertEqual(r['etat'],'NON_ETABLIE')
        self.assertIn('future',r['motifs'][0])

    def test_changement_semaine_et_revision_memes_semaines(self):
        week={'periode_candidate':{'fin':'2026-11-15'}}
        self.assertEqual(evaluate_change('a',week,{}),'PREMIERE_OBSERVATION')
        self.assertEqual(evaluate_change('a',week,{'derniere_empreinte':'a'}),'CLASSEMENT_INCHANGE')
        self.assertEqual(evaluate_change('b',week,{'derniere_empreinte':'a','derniere_periode_candidate':'2026-11-15'}),
                         'REVISION_DU_CLASSEMENT_DE_LA_MEME_SEMAINE')
        self.assertEqual(evaluate_change('b',{'periode_candidate':{'fin':'2026-11-22'}},
                         {'derniere_empreinte':'a','derniere_periode_candidate':'2026-11-15'}),
                         'NOUVELLE_SEMAINE_CANDIDATE_NON_CERTIFIEE')

    def test_image_collector_signalee_packshot(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'i.png'
            im=Image.new('RGB',(500,700),'white')
            for x in range(140,380):
                for y in range(90,510): im.putpixel((x,y),(100,20,40))
            im.save(p)
            c=cover_kind(p,edition={'titre':'Atelier des Sorciers T16 Collector'})
            self.assertEqual(c['type'],'PACKSHOT_COLLECTOR_PROBABLE')

    def test_openlibrary_ean_invalide_refuse(self):
        with tempfile.TemporaryDirectory() as td:
            r=openlibrary_cover('9781234567890',Path(td)/'x.png')
            self.assertFalse(r['ok'])

    def test_openlibrary_image_via_isbn_exclusivement(self):
        image=Image.new('RGB',(600,900),'red')
        out=io.BytesIO();image.save(out,format='PNG')
        def getter(url,**kw):
            self.assertTrue(url.startswith('https://covers.openlibrary.org/b/isbn/9782505144656-L.jpg'))
            return Response(out.getvalue(),url=url,content_type='image/png')
        with tempfile.TemporaryDirectory() as td:
            r=openlibrary_cover('9782505144656',Path(td)/'x.png',getter=getter)
            self.assertTrue(r['ok'])

    def test_rapport_complet_ne_publie_jamais(self):
        a,v,html=fixtures()
        a['sources'][0]['inspection']['premieres_entrees_a_verifier'].extend(
            {'rang_bd_manga':i,'titre_affiche':f'Titre {i}'} for i in range(21,27))
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'maquette_v5').mkdir()
            (d/'audit_manga.json').write_text(json.dumps(a))
            (d/'verification_manga.json').write_text(json.dumps(v))
            (d/'maquette_v5'/'rapport_enrichissement_v5.json').write_text(json.dumps({'etat':'A_REEXAMINER_NOUVELLE_EDITION',
                'date_palmares':'27/11/2026','editions':[]}))
            result=execute(d,Path(td)/'.cache_manga_v6'/'etat.json',getter=lambda *x,**k:Response(html),
                           today=dt.date(2026,11,23))
            self.assertFalse(result['publication_manga_autorisee'])
            self.assertEqual(result['queue_buffer'],'NON_MODIFIEE')
            self.assertTrue((d/'CONTROLE_V6_LIRE.md').is_file())
            self.assertEqual(result['couvertures']['etat'],'CATALOGUE_V5_HORS_PERIODE')

if __name__=='__main__': unittest.main()
