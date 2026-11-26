import datetime as dt
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from actus_9e_art.collecte import collect,select,theme
from actus_9e_art.run import render,caption
from anecdotes_auto.buffer import is_anecdote
from audit_buffer import category
from calendrier_editorial import reserved_kind
class ActusTests(unittest.TestCase):
    def test_seed_and_render(self):
        day=dt.date(2026,11,30)
        items=collect(day)
        self.assertEqual(len(items),5)
        self.assertGreaterEqual(len({x['source'] for x in items}),3)
        self.assertLessEqual(len(caption(items,day)),2200)
        with tempfile.TemporaryDirectory() as td:
            names=render(items,Path(td),day)
            self.assertEqual(len(names),6)
            for name in names:
                with Image.open(Path(td)/name) as im:self.assertEqual(im.size,(1080,1350))
    def test_no_rumor_or_non_bd(self):
        self.assertIsNone(theme('Une librairie manga trouve un repreneur à Morlaix','actualitte.com'))
        self.assertEqual(theme('C’est fini pour Sakamoto Days','www.manga-news.com'),'MANGA')
        self.assertEqual(theme('Star Wars et Marvel dévoilent leur crossover','www.comicsblog.fr'),'COMICS')
        self.assertIsNone(theme('Rumeur : nouveau manga','www.actuabd.com'))
        self.assertIsNone(theme('Prix du roman historique','actualitte.com'))
    def test_calendar_and_legacy(self):
        self.assertEqual(reserved_kind(dt.date(2026,11,30)),'ACTUS')
        self.assertTrue(is_anecdote({'text':'📚 ANECDOTE BD — test'}))
        self.assertTrue(is_anecdote({'text':'📚 ANECDOTE DU 9e ART — test'}))
        self.assertEqual(category('📰 LES 5 ACTUS DU 9e ART — test'),'ACTUS')
if __name__=='__main__':unittest.main()
