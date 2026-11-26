import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from historique_editions import newer_receipt, edition_key
from surveillance_bd import already_processed
from illyadera_queue import free_capacity_for_priority
from test_illyadera_queue import FakeBuffer, make_post, TODAY, at

class OrdreEditionsTests(unittest.TestCase):
    def test_refuse_regression_bd_et_manga(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for edition in ('BD_2026-11-15','MANGA_2026-11-15'):
                (p/(edition+'.json')).write_text(json.dumps({'statut':'POST_PROGRAMME','edition':edition}))
            self.assertTrue(already_processed({'edition':'BD_2026-11-08'},receipts=p)[0])
            self.assertEqual(newer_receipt(p,'MANGA_2026-11-08'),'MANGA_2026-11-15')
            self.assertIsNone(newer_receipt(p,'MANGA_2026-11-22'))

    def test_cadences_distinctes_et_annees(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            edition='COMICS_HEBDO_2027_W01'
            (p/(edition+'.json')).write_text(json.dumps({'statut':'POST_PROGRAMME','edition':edition}))
            self.assertEqual(newer_receipt(p,'COMICS_HEBDO_2026_W53'),edition)
            self.assertIsNone(newer_receipt(p,'COMICS_MENSUEL_2026_11'))
            self.assertEqual(edition_key(edition)[1],dt.date(2027,1,4))

    def test_top_mensuel_ne_prend_pas_hebdo(self):
        b=FakeBuffer([make_post(1,2,'📚 TOP 5 COMICS')])
        with self.assertRaises(RuntimeError):
            free_capacity_for_priority(at(2),buffer=b,registry={},now=TODAY,priority='COMICS_MENSUEL')
        self.assertEqual(b.deleted,[])

    def test_autre_post_avec_top_interdit(self):
        b=FakeBuffer([make_post(1,2,'📚 TOP 5 COMICS'),make_post(2,2)])
        with self.assertRaises(RuntimeError):
            free_capacity_for_priority(at(2),buffer=b,registry={},now=TODAY,priority='COMICS_HEBDO')

if __name__=='__main__':unittest.main()
