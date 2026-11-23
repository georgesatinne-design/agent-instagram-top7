import datetime as dt
import tempfile
import unittest
from pathlib import Path
from audit_manga_sources import audit, bede_report, write_audit, fetch_source

SAMPLE = '''<html><title>Meilleures ventes</title><h2>Le Top des ventes de la semaine (palmarès du 20/11/2026)</h2>
<div class="result"><span>#1</span><img alt="Lucky Luke T12"><p>Lucky Comics</p></div>
<div class="result"><span>#13</span><img alt="One Piece T113"><p>Glénat</p></div>
<div class="result"><span>#18</span><img alt="Kagurabachi T11"><p>Kana</p></div>
</html>'''

class Response:
    def __init__(self, html, url):
        self.text = html
        self.url = url
        self.content = html.encode('utf-8')
        self.status_code = 200
    def raise_for_status(self): pass

class Session:
    def get(self, url, **kw):
        return Response(SAMPLE, url)

class TestsSources(unittest.TestCase):
    def test_bede_detecte_les_rangs_et_les_trous_sans_inventer(self):
        result = bede_report(SAMPLE)
        self.assertEqual(result['date_palmares_affichee'], '20/11/2026')
        self.assertEqual(result['nb_rangs_detectes'], 3)
        self.assertEqual([i['rang_bd_manga'] for i in result['premieres_entrees_a_verifier']], [1, 13, 18])
        self.assertFalse(result['exhaustivite_mangas'] == 'OUI')
        self.assertIn(2, result['rangs_manquants_jusqu_au_max'])
    def test_sources_web_simulees_et_pas_de_publication(self):
        report = audit(session=Session(), timestamp=dt.datetime(2026,11,23,tzinfo=dt.timezone.utc))
        self.assertEqual(len(report['sources']), 4)
        self.assertTrue(all(item['accessible'] for item in report['sources']))
        self.assertFalse(report['top7_national_certifie'])
        self.assertEqual(report['queue_buffer'], 'NON_MODIFIEE')
    def test_dossier_rapport_seulement(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            write_audit(out, audit(session=Session()))
            self.assertTrue((out/'audit_manga.json').is_file())
            self.assertFalse((out/'legende_instagram.txt').exists())
            self.assertFalse((out/'RECU_BUFFER.json').exists())
    def test_refuse_site_non_autorise(self):
        with self.assertRaises(ValueError):
            fetch_source('test', 'https://evil.example.com/')

if __name__ == '__main__':
    unittest.main()
