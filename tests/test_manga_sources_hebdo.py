"""Tests 100% hors ligne : aucun appel réseau ni publication Buffer."""
import json
import tempfile
import unittest
from pathlib import Path
from manga_sources_hebdo import (
    _explicit_period, EvidenceError, parse_top200, parse_bede_current,
    source_report, collect, match_titles, latest_article_urls,
)

KNOWN=[
    ('Instinct Tome 3','9782749958200','Michel Lafon',2),
    ('Spy x Family tome 17','9791042021870','Kurokawa',4),
    ("L'Atelier des Sorciers Tome 16 Edition collector",'9791043311772','Pika',11),
    ('One Piece Edition originale Tome 113','9782344071120','Glénat',13),
    ('Kagurabachi Tome 11','9782505144656','Dargaud',18),
    ('Blue Lock Tome 35','9791043306617','Pika',19),
    ("L'Atelier des Sorciers Tome 06 Edition Grimoire",'9791043301445','Pika',20),
]
LOCATIONS=[3,8,34,38,54,55,61]  # positions FICTIVES pour les tests, pas une publication de rangs generaux

def article(week='du 9 au 15 novembre 2026', size=200, include=True):
    intro=(f'<html><article><h1>Classement</h1><p>Le 20/11/2026 à 11:52</p>'
           f'<p>Le marché de la semaine {week}. Ventes en France; toutes catégories confondues.</p>'
           '<p>Source Edistat, 200 ouvrages tous segments confondus.</p>')
    parts=[intro]
    for i in range(1,size+1):
        hit=LOCATIONS.index(i) if i in LOCATIONS and include else None
        if hit is None:
            name,ean,publisher=f'Roman numéro {i}',f'97812345{i:05d}', 'Roman Editions'
        else:name,ean,publisher,_=KNOWN[hit]
        parts.append(f'<h2>{name}</h2><p>Paru le 10/11/2026 210 pages {publisher} 7,30 €</p>'
                     f'<p>Scannez le code barre {ean} En partenariat avec Edistat</p>')
    return ''.join(parts)+'</article></html>'

def bede():
    parts=['<html><h2>Le Top des ventes de la semaine (palmarès du 20/11/2026)</h2>']
    for name,ean,publisher,mixed in KNOWN:
        parts.append(f'<div class="book"><span>#{mixed}</span>'
                     f'<img alt="{name} - {publisher}" src="https://cdn.bede.fr/{ean}.jpg"></div>')
    return ''.join(parts)+'</html>'

class MangaSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        original=Path(__file__).resolve().parents[2]/'editions_manga_v5.json'
        if not original.exists():original=Path(__file__).resolve().parents[1]/'editions_manga_v5.json'
        (self.root/'editions_manga_v5.json').write_bytes(original.read_bytes())
    def tearDown(self):self.temp.cleanup()
    def test_period_dates_exactes(self):
        self.assertEqual(_explicit_period('du 9 au 15 novembre 2026',2026),[('2026-11-09','2026-11-15')])
        self.assertEqual(_explicit_period('du 26 octobre au 1er novembre 2026',2026),[('2026-10-26','2026-11-01')])
        self.assertEqual(_explicit_period('du 10 au 15 novembre 2026',2026),[])
    def test_200_ouvrages_et_eans(self):
        items=parse_top200(article())
        self.assertEqual(len(items),200)
        self.assertEqual(items[2]['ean'],KNOWN[0][1])
        self.assertEqual(items[33]['ean'],KNOWN[2][1])
    def test_refus_html_incomplet(self):
        with self.assertRaises(EvidenceError):parse_top200(article(size=40))
    def test_bede_n_est_pas_liste_generale_complete(self):
        rows=parse_bede_current(bede())
        self.assertEqual(len(rows['lignes']),7)
        self.assertEqual(rows['lignes'][2]['rang_mixte'],11)
    def test_tomes_et_editions_restent_distincts(self):
        self.assertFalse(match_titles('Blue Lock tome 35','Blue Lock tome 34'))
        self.assertFalse(match_titles('Atelier des Sorciers tome 16 Collector','Atelier des Sorciers tome 16 Standard'))
        self.assertTrue(match_titles('Kagurabachi tome 11','Kagurabachi tome 11 - Kana'))
    def test_top7_sur_fixtures_synthetiques(self):
        data,evidence=source_report(article(),bede(),root=self.root,source_url='https://actualitte.com/article/135341/meilleures-ventes/test')
        self.assertEqual([x['ean'] for x in data['titres']],[x[1] for x in KNOWN])
        self.assertEqual([x['rang'] for x in data['titres']],list(range(1,8)))
        self.assertEqual([x['rang_general_livres'] for x in data['titres']],LOCATIONS)
        self.assertEqual(data['fin_ventes'],'2026-11-15')
        self.assertFalse(data['variations_verifiees'])
        self.assertEqual(data['certification'],'TOP7_RECONSTITUE_A_VALIDER')
    def test_ne_pas_inventer_la_progression_premiere_semaine(self):
        d,_=source_report(article(),bede(),root=self.root,source_url='https://actualitte.com/article/135341/meilleures-ventes/test')
        self.assertEqual([x['mouvement'] for x in d['titres']],['NON DOCUMENTÉ']*7)
    def test_genere_dossier_sans_toucher_bd_ou_buffer(self):
        d=collect(self.root,self.root/'sorties',actualitte_html=article(),bede_html=bede(),annual_html='')
        self.assertEqual(d.name,'MANGA_2026-11-15')
        self.assertTrue((d/'preuves_manga.json').exists())
        self.assertFalse((d/'RECU_BUFFER.json').exists())
        self.assertFalse((d/'08_recapitulatif.png').exists())
    def test_liens_articles_seulement(self):
        index='<a href="/article/135341/meilleures-ventes/top">Dernier</a>'
        self.assertEqual(len(latest_article_urls(index)),1)

if __name__=='__main__':unittest.main()
