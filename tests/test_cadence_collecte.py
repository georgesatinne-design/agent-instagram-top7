import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from cadence_collecte import finalized,monthly_open

NOW=dt.datetime(2026,11,26,10,tzinfo=dt.timezone.utc)
class CadenceTests(unittest.TestCase):
    def test_observation_seule_ne_bloque_pas(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.assertIsNone(finalized('MANGA_2026-11-15',root=root,now=NOW))
            hist=root/'manga_history';hist.mkdir()
            (hist/'dernier_classement.json').write_text('{}')
            self.assertIsNone(finalized('MANGA_2026-11-15',root=root,now=NOW))

    def test_recu_et_correction(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'manga_buffer_receipts';p.mkdir()
            edition='MANGA_2026-11-22'
            (p/(edition+'.json')).write_text(json.dumps({'statut':'POST_PROGRAMME','edition':edition,
                'id_buffer':'1','date_programmee_utc':'2026-12-01T17:00:00Z','version_contenu':'v1'}))
            self.assertEqual(finalized(edition,root=root,version='v1',now=NOW),'EDITION_DEJA_PROGRAMMEE')
            self.assertIsNone(finalized(edition,root=root,version='v2',now=NOW))
            self.assertEqual(finalized('MANGA_2026-11-15',root=root,now=NOW),'EDITION_DEPASSEE')

    def test_fenetre_mensuelle_jusqu_au_deuxieme_dimanche(self):
        self.assertTrue(monthly_open(dt.datetime(2026,12,13,10,tzinfo=dt.timezone.utc)))
        self.assertFalse(monthly_open(dt.datetime(2026,12,13,17,tzinfo=dt.timezone.utc)))
        self.assertFalse(monthly_open(dt.datetime(2026,12,14,10,tzinfo=dt.timezone.utc)))

    def test_reserve_et_horizon_bornes(self):
        root=Path(__file__).resolve().parents[1]
        cfg=json.loads((root/'anecdotes_auto'/'config.json').read_text())
        self.assertLessEqual(cfg['horizon_jours'],14)
        self.assertLessEqual(cfg['max_posts_par_execution'],4)
        self.assertEqual(cfg['max_posts_programmes_canal'],10)
        self.assertEqual(cfg['stock_cible'],10)

if __name__=='__main__':unittest.main()
