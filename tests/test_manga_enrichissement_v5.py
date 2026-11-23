import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from enrichissement_manga_v5 import (
    safe_url, verifier_ean, extraire_image_fiche, enregistrer_couverture,
    rapprocher, incruster_couvertures,
)

BASE = Path(__file__).resolve().parents[1]


class MockResponse:
    def __init__(self, body=b'', status=200, url='https://media.hachette.fr/couv.png', content_type='image/png'):
        self.content, self.url, self.status_code = body, url, status
        self.headers = {'Content-Type': content_type}
        try: self.text = body.decode('utf-8')
        except UnicodeDecodeError: self.text = ''
    def raise_for_status(self):
        if self.status_code >= 400: raise ValueError('HTTP '+str(self.status_code))


class MangaV5Tests(unittest.TestCase):
    def test_ean_valides(self):
        for e in json.loads((BASE/'editions_manga_v5.json').read_text())['editions']:
            self.assertTrue(verifier_ean(e['ean']), e)
        self.assertFalse(verifier_ean('9782749958201'))

    def test_block_private_and_unapproved_hosts(self):
        self.assertFalse(safe_url('http://www.pika.fr/abc', frozenset({'www.pika.fr'})))
        self.assertFalse(safe_url('https://127.0.0.1/private', frozenset({'www.pika.fr'})))
        self.assertFalse(safe_url('https://www.pika.fr.evil.test/x', frozenset({'www.pika.fr'})))

    def test_ean_required_before_meta_image(self):
        html = '<html><head><meta property="og:image" content="https://media.hachette.fr/cover.png"></head><body>ISBN ABSENT</body></html>'
        url = 'https://www.pika.fr/livre/autre-volume/'
        self.assertIsNone(extraire_image_fiche(html,url,'9791043306617'))
        self.assertEqual(extraire_image_fiche(html,'https://www.pika.fr/livre/blue-lock-t35-9791043306617/','9791043306617'), 'https://media.hachette.fr/cover.png')

    def test_rejet_image_carree_ou_publicite(self):
        image = Image.new('RGB',(640,640), 'red')
        raw = io.BytesIO(); image.save(raw,format='PNG')
        with tempfile.TemporaryDirectory() as td:
            good, err=enregistrer_couverture('https://media.hachette.fr/photo.png',Path(td)/'x.png', getter=lambda *a,**k: MockResponse(raw.getvalue()))
            self.assertFalse(good);self.assertIn('portrait',err)

    def test_telechargement_couverture_portrait(self):
        image = Image.new('RGB',(500,700), 'blue')
        raw = io.BytesIO(); image.save(raw,format='PNG')
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'v.png'
            good,_=enregistrer_couverture('https://media.hachette.fr/couv.png',target,getter=lambda *a,**k: MockResponse(raw.getvalue()))
            self.assertTrue(good);self.assertTrue(target.exists())

    def test_correspondance_des_7_editions(self):
        # Les donnees correspondent au rapport utilisateur, pas a un Top7 certifie.
        candidats = [
            (2,'Instinct - Tome 3 - Michel Lafon'),
            (4,'Spy x Family - tome 17 - Kurokawa Eds'),
            (11,"L'Atelier des Sorciers T16 - Collector - Pika"),
            (13,'One Piece - Édition originale - Tome 113 - Glénat'),
            (18,'Kagurabachi T11 - Kana Eds'),
            (19,'Blue Lock T35 - Pika'),
            (20,"L'Atelier des Sorciers T06 Edition Grimoire - Pika"),
        ]
        verification={'categorie':'MANGA','date_palmares_bede':'20/11/2026',
                      'candidats_non_certifies':[{'rang_manga_provisoire':i,'rang_classement_mixte':r,'titre':t} for i,(r,t) in enumerate(candidats,1)]}
        catalogue=json.loads((BASE/'editions_manga_v5.json').read_text())
        resultat=rapprocher(verification,{'categorie':'MANGA'},catalogue)
        self.assertEqual(len(resultat['editions']),7)
        with self.assertRaises(ValueError):
            rapprocher({**verification,'date_palmares_bede':'27/11/2026'}, {'categorie':'MANGA'},catalogue)
        with self.assertRaises(ValueError):
            rang_modifie=[dict(x) for x in verification['candidats_non_certifies']]
            rang_modifie[2]['titre']="L'Atelier des Sorciers T15 - Collector - Pika"
            rapprocher({**verification,'candidats_non_certifies':rang_modifie},{'categorie':'MANGA'},catalogue)

    def test_droit_et_ventes_non_certifies_par_catalogue(self):
        # Une fiche edition valide ne constitue jamais une preuve des ventes.
        data=json.loads((BASE/'editions_manga_v5.json').read_text())
        self.assertNotIn('publication_manga_autorisee',data)
        self.assertNotIn('debut_ventes',data)


if __name__ == '__main__': unittest.main()
