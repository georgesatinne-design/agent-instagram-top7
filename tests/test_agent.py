import json, tempfile, unittest
from pathlib import Path
from sources.collecte import parse_bdzoom, dates_semaine, SourceError
from sources.couvertures import meme_livre
from studio import verifier
from agent import run, ROOT

class AgentTests(unittest.TestCase):
    def test_period(self):
        self.assertEqual(dates_semaine('Top 20 BD du 2 au 8 novembre 2026'),('2026-11-02','2026-11-08'))
    def test_cover_rejects_wrong_volume(self):
        self.assertFalse(meme_livre('One Piece tome 112','One Piece tome 113'))
    def test_duplicate_ranks_rejected(self):
        d=json.loads((ROOT/'donnees/demo_bd_2026.json').read_text());d['titres'][1]['rang']=1
        with self.assertRaises(ValueError):verifier(d)
    def test_parser_uses_table_and_dates(self):
        rows=''.join(f'<tr><td>{i}</td><td>=</td><td>Titre vérifiable {i}</td><td>Auteur</td><td>Éditeur</td></tr>' for i in range(1,11))
        html='<h1>Zoom sur les meilleures ventes de BD</h1><article><p>Top 20 BD du 2 au 8 novembre 2026</p><table>'+rows+'</table></article>'
        d=parse_bdzoom(html,'https://www.bdzoom.com/test/')
        self.assertEqual(len(d['titres']),10)
        self.assertEqual(d['fin_ventes'],'2026-11-08')
    def test_unicode_variations_do_not_become_album_titles(self):
        from surveillance_bd import identifier_edition
        import datetime as dt
        movements=['(=)','(=)','(=)','nouveau','(–1)','(–1)','(−2)']
        names=['Album distinct '+str(i) for i in range(1,8)]
        rows=''.join(f'<tr><td>{i}<sup>e</sup></td><td>{m}</td><td>{title}</td><td>Auteur</td><td>Editeur</td></tr>'
                     for i,(m,title) in enumerate(zip(movements,names),1))
        html='<h1>Zoom sur les meilleures ventes de BD</h1><article><p>Top 20 BD du 9 au 15 novembre 2026</p><table>'+rows+'</table></article>'
        data=parse_bdzoom(html,'https://www.bdzoom.com/test/')
        self.assertEqual([b['titre'] for b in data['titres']],names)
        self.assertEqual([b['mouvement'] for b in data['titres']][4:],['−1 PL.','−1 PL.','−2 PL.'])
        self.assertEqual(verifier(data),7)
        self.assertEqual(identifier_edition(data,now=dt.datetime(2026,11,26,tzinfo=dt.timezone.utc))['edition'],'BD_2026-11-15')
    def test_empty_variation_preserves_title(self):
        rows=''.join(f'<tr><td>{i}</td><td></td><td>Album distinct {i}</td><td>Auteur</td><td>Editeur</td></tr>' for i in range(1,8))
        html='<h1>Zoom sur les meilleures ventes de BD</h1><article><p>Top 20 BD du 9 au 15 novembre 2026</p><table>'+rows+'</table></article>'
        data=parse_bdzoom(html,'https://www.bdzoom.com/test/')
        self.assertEqual(verifier(data),7)
        self.assertFalse(data['variations_verifiees'])
    def test_incomplete_table_rejected(self):
        rows=''.join(f'<tr><td>{i}</td><td>=</td><td>Titre {i} complet</td><td>Auteur</td><td>Éditeur</td></tr>' for i in range(1,7))
        html='<h1>Zoom sur les meilleures ventes de BD</h1><article><p>Top 20 BD du 2 au 8 novembre 2026</p><table>'+rows+'</table></article>'
        with self.assertRaises(SourceError):parse_bdzoom(html,'https://www.bdzoom.com/test/')
    def test_full_pipeline_from_supplied_data(self):
        with tempfile.TemporaryDirectory() as t:
            result=run(Path(t),ROOT/'donnees/demo_bd_2026.json')
            self.assertEqual(result['dossiers'][0]['diapositives'],8)
            self.assertTrue((Path(t)/'DOSSIER_A_VALIDER.zip').exists())
            self.assertTrue((Path(t)/'BD/REVUE.html').exists())

if __name__=='__main__':unittest.main()
