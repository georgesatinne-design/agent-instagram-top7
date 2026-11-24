"""Tests de la continuité comics quand Fnac renvoie 403 (hors ligne)."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image
import requests
import comics_sources_hebdo as source
import comics_pipeline_auto as pipeline
import comics_score_publication as scoring
import comics_buffer_auto as buffer

NOW=dt.datetime(2026,11,24,12,tzinfo=ZoneInfo('Europe/Paris'))
TITLES=['Absolute Batman tome 2', 'Batman - Le dernier Halloween',
    'Batman - Le dernier Halloween (couverture Guarnido)',
    'Superman - Les derniers jours de Lex Luthor',
    'Batman - Le dernier Halloween (couverture Marini)',
    'Minor arcana tome 1 + ex-libris offert', 'Exquisite corpses - coffret tome 1']

def bdfugue_html():
    items=[]
    for i,title in enumerate(TITLES):
        items.append(f'<li class="product-item"><div class="product-item-info">'
            f'<a class="product-item-photo" href="https://www.bdfugue.com/comics-example-{i}">'
            f'<img src="https://www.bdfugue.com/media/catalog/product/comics-{i}.jpg" alt="{title}"></a>'
            f'<h3 class="product-item-name"><a class="product-item-link" '
            f'href="https://www.bdfugue.com/comics-example-{i}">{title}</a></h3>'
            f'</div></li>')
    return '<html><main><h1>Meilleures ventes Comics</h1><p>Top des ventes sur les 30 derniers jours</p><ol class="products list items product-items">' + ''.join(items) + '</ol></main></html>'

def product_html(url):
    index=int(url.rsplit('-',1)[-1])
    return ('<html><main><h1>'+TITLES[index]+'</h1><div>Éditeur</div><div>Urban Comics</div>'
      f'<div>Référence 9791026824{index:03d}</div>'
      f'<meta property="og:image" content="https://www.bdfugue.com/media/catalog/product/comics-{index}.jpg">'
      '</main></html>')

def fake_fetch(url):
    if url==source.BDFUGUE:return bdfugue_html()
    if url.startswith('https://www.bdfugue.com/comics-example-'):return product_html(url)
    if url==source.FNAC:raise requests.HTTPError('403 Client Error: Forbidden (Fnac)')
    raise requests.HTTPError('404 (site facultatif pour test)')

class TestBdfugue(unittest.TestCase):
    def test_parse_order_meme_si_fnac_refuse(self):
        data,evidence=source.collect_live(now=NOW,fetcher=fake_fetch)
        self.assertEqual(data['releve_source'],'BDFUGUE')
        self.assertEqual(data['mode_interne'],'RELEVE_ENSEIGNE')
        self.assertEqual([x['titre'] for x in data['titres']],TITLES)
        self.assertIn('Fnac',str(evidence['avertissements']))
        self.assertNotIn('fin_ventes',data)
    def test_ne_pas_inventer_top_depuis_menu(self):
        html='<h1>Meilleures ventes Comics</h1><p>30 derniers jours</p>'
        html+=''.join(f'<nav><a href="/produit-{i}">Comic {i}</a></nav>' for i in range(20))
        with self.assertRaises(source.CollectError):source.parse_bdfugue(html)
    def test_rejette_fausse_page(self):
        with self.assertRaises(source.CollectError):source.parse_bdfugue(bdfugue_html().replace('30 derniers jours','Nouveautés'))
    def test_couvre_urls_uniquement_autorisees(self):
        self.assertTrue(source.validate_cover_url('https://www.bdfugue.com/media/catalog/product/p.png'))
        self.assertFalse(source.validate_cover_url('https://bdfugue.com.example.net/image.png'))
        self.assertFalse(source.validate_cover_url('http://www.bdfugue.com/image.png'))
    def test_enrichissement_fiche_bdfugue(self):
        data,_=source.collect_live(now=NOW,fetcher=fake_fetch)
        book=data['titres'][0]
        pipeline.enrich_product(book,fetcher=fake_fetch)
        self.assertEqual(book['editeur'],'Urban Comics')
        self.assertEqual(book['ean'],'9791026824000')
    def test_mouvements_pas_comparables_entre_enseignes(self):
        data,_=source.collect_live(now=NOW,fetcher=fake_fetch)
        previous=json.loads(json.dumps(data))
        previous['releve_source']='FNAC'
        previous['semaine_reference']=['2026-11-16','2026-11-22']
        pipeline.update_previous(data,previous)
        self.assertFalse(data['variations_verifiees'])
    def test_fallback_7_comics_rendu_et_score(self):
        def fake_covers(data,folder):
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            for book in data['titres']:
                Image.new('RGB',(300,420),'white').save(pipeline.cover_path(folder,book['titre']))
            return [{'rang':book['rang'],'ok':True,'origine':'test'} for book in data['titres']]
        with tempfile.TemporaryDirectory() as d:
            path=pipeline.produire(output=Path(d)/'out',previous=Path(d)/'prior.json',
                                   now=NOW,fetcher=fake_fetch,covers=fake_covers)
            state=json.loads((path/'ETAT.json').read_text())
            self.assertTrue(state['pret_buffer'])
            self.assertEqual(state['couvertures'],7)
            self.assertEqual(state['pages'],8)
            manifest=json.loads((path/'COMICS'/'post_manifest.json').read_text())
            self.assertEqual(manifest['pages'][0],'01_rang_7.png')
            payload=buffer.construire(path/'COMICS','https://raw.githubusercontent.com/owner/repo/main/public_media/COMICS_2026-11-29/COMICS_abcd/',
                'comics-channel',now=NOW)
            self.assertEqual(len(payload['assets']),8)
            self.assertNotIn('BDFugue',payload['text'])
            self.assertIn('Classement relevé le 24/11/2026',payload['text'])

class TestBdfugueImages(unittest.TestCase):
    def test_download_image_domaine_bdfugue(self):
        pic=io.BytesIO();Image.new('RGB',(340,480),'white').save(pic,format='PNG')
        class Response:
            url='https://www.bdfugue.com/media/catalog/product/image.png'
            headers={'Content-Type':'image/png'}
            content=pic.getvalue()
            def raise_for_status(self):pass
        with tempfile.TemporaryDirectory() as d:
            book={'titre':'Absolute Batman tome 2','rang':1}
            ok,info=pipeline._download_comics_cover(book,{1:{'url':Response.url,'reference':book['titre']}},Path(d),getter=lambda url,**kwargs:Response())
            self.assertTrue(ok,info)
            self.assertTrue(pipeline.cover_path(Path(d),book['titre']).exists())

if __name__=='__main__':unittest.main()
