import unittest
import datetime as dt
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
from stories_illyadera import render,select
from anecdotes_auto.buffer import is_story
from audit_buffer import report
from calendrier_editorial import PARIS,utc
class StoryTests(unittest.TestCase):
    def test_render(self):
        with TemporaryDirectory() as tmp:
            dest=Path(tmp)/'story.png'
            render({'text':'📚 TOP 7 BD — test'},('',''),dest)
            with Image.open(dest) as im:self.assertEqual(im.size,(1080,1920))
    def test_story_distincte(self):
        self.assertTrue(is_story({'text':'','metadata':{'type':'story'}}))
        feed={'dueAt':'2026-11-27T16:00:00.000Z','text':'📚 TOP 7 BD'}
        story={'dueAt':'2026-11-27T19:00:00.000Z','text':'','metadata':{'type':'story'}}
        r=report([feed,story])
        self.assertEqual(r['total'],2)
        self.assertEqual(r['jours_avec_plusieurs_posts'],0)
        self.assertEqual(r['par_categorie']['STORY'],1)
    def test_pas_de_story_si_post_absent(self):
        now=dt.datetime(2026,11,27,18,45,tzinfo=PARIS)
        self.assertIsNone(select([],now.date(),now))
