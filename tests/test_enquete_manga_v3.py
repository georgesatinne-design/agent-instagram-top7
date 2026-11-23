import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from enquete_manga_v3 import (analyser_glenat, analyser_mangactu, etudier, sauvegarder, safe_get)


class Response:
    status_code=200
    def __init__(self,url,html,code=200):
        self.url=url
        self.text=html
        self.status_code=code
        self.content=html.encode('utf-8')
    def raise_for_status(self):
        if self.status_code != 200:
            import requests
            e=requests.HTTPError('Erreur 403')
            e.response=self
            raise e

class Session:
    def __init__(self, pages):
        self.pages=pages
        self.calls=[]
    def get(self,url,**kwargs):
        self.calls.append(url)
        return Response(url,*(self.pages[url] if isinstance(self.pages[url],tuple) else (self.pages[url],)))

URL1='https://www.edistat.com/'
URL2='https://mang-actu.com/classements-des-ventes/'
URL3='https://www.glenat.com/manga/meilleures-ventes/'
HTML2='''<a href="/les-5-mangas-les-plus-vendus-en-france-du-10-08-au-16-08/">FR 23 août 2026 Les 5 mangas les plus vendus en France du 10/08 au 16/08 !</a>
<a href="/japon/">Japon 22 novembre 2026 Top Oricon</a>'''


def audit():
    return {'categorie':'MANGA','sources':[
        {'source':'edistat_top200','accessible':False,'status_http':403},
        {'source':'bede_bd_manga','accessible':True,'inspection':{'date_palmares_affichee':'20/11/2026','nb_rangs_detectes':52,'rangs_manquants_jusqu_au_max':[]}},
    ]}


def verif():
    return {'categorie':'MANGA','candidats_non_certifies':[{'titre':'Instinct','rang_classement_mixte':2}],
            'indetermines_avant_7e':[{'titre':'un titre inconnu','rang_classement_mixte':8}]}


class MangaV3Tests(unittest.TestCase):
    def test_detecte_top_francais_meme_si_japon_plus_recent(self):
        x=analyser_mangactu(HTML2, aujourd_hui=dt.date(2026,11,23))
        self.assertEqual(x['dernier_top5_france']['publication'], '2026-08-23')
        self.assertEqual(x['dernier_top5_france']['periode'], {'debut':'2026-08-10','fin':'2026-08-16'})
        self.assertFalse(x['a_jour_moins_14_jours'])
        self.assertFalse(x['permet_top7_france'])

    def test_texte_incomplet_ne_force_pas_date(self):
        x=analyser_mangactu('<a href="/test/">Les 5 mangas les plus vendus en France du 10/08 au 16/08</a>',aujourd_hui=dt.date(2026,11,23))
        self.assertIsNone(x['dernier_top5_france']['publication'])
        self.assertIsNone(x['dernier_top5_france']['periode'])

    def test_glenat_est_seulement_un_editeur(self):
        x=analyser_glenat('<h1>Nos meilleures ventes Mangas</h1><h2>Source GFK - Meilleures ventes de la semaine. Mise à jour le mercredi</h2>')
        self.assertTrue(x['source_affirme_gfk'])
        self.assertTrue(x['mention_mise_a_jour_mercredi'])
        self.assertFalse(x['permet_top7_france'])

    def test_ne_pas_acceder_domaine_non_autorise(self):
        with self.assertRaises(ValueError): safe_get('https://example.net/api/')

    def test_v3_ne_certifie_ni_ne_poste(self):
        client=Session({URL1:'<h1>Edistat accès gratuit</h1>',URL2:HTML2,URL3:'Source GFK'})
        report=etudier(audit(),verif(),session=client,aujourd_hui=dt.date(2026,11,23))
        self.assertEqual(set(client.calls), {URL1, URL2, URL3})
        self.assertEqual(len(client.calls),3)
        self.assertFalse(report['top7_national_certifie'])
        self.assertFalse(report['publication_manga_autorisee'])
        self.assertEqual(report['buffer'],'AUCUNE_ACTION')
        self.assertFalse(report['preuves_requises'][2]['valide'])
        self.assertEqual(report['indetermines_avant_septieme'][0]['titre'],'un titre inconnu')

    def test_erreur_http_403_ne_bloque_pas_rapport(self):
        client=Session({URL1:('<h1>Forbidden</h1>',403),URL2:HTML2,URL3:'GFK'})
        report=etudier(audit(),verif(),session=client,aujourd_hui=dt.date(2026,11,23))
        self.assertFalse(report['sources_complementaires']['edistat_accueil']['accessible'])
        self.assertEqual(report['sources_complementaires']['edistat_accueil']['status_http'], 403)
        self.assertFalse(report['top7_national_certifie'])

    def test_sauvegarde_juste_des_rapports(self):
        report=etudier(audit(),verif(),session=Session({URL1:'OK', URL2:HTML2, URL3:'OK'}),aujourd_hui=dt.date(2026,11,23))
        with tempfile.TemporaryDirectory() as d:
            sauvegarder(d,report)
            self.assertTrue((Path(d)/'enquete_manga_v3.json').exists())
            self.assertTrue((Path(d)/'ENQUETE_MANGA_V3_LIRE.md').exists())
            self.assertFalse((Path(d)/'legende_instagram.txt').exists())
            self.assertFalse((Path(d)/'RECU_BUFFER.json').exists())
            self.assertFalse(json.loads((Path(d)/'enquete_manga_v3.json').read_text())['publication_manga_autorisee'])

    def test_refuse_categorie_differente(self):
        with self.assertRaises(ValueError):
            etudier({'categorie':'BD'},verif())

if __name__=='__main__': unittest.main()
