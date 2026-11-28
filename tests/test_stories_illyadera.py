import unittest
import datetime as dt
from stories_illyadera import original_media,select,safe_canvas
from PIL import Image
from anecdotes_auto.buffer import is_story
from audit_buffer import report
from calendrier_editorial import PARIS
class StoryTests(unittest.TestCase):
    def test_no_overflow(self):
        for size in [(1080,1350),(1920,1080),(1080,1920),(200,300)]:
            canvas=safe_canvas(Image.new('RGB',size,'#ffffff'))
            self.assertEqual(canvas.size,(1080,1920))
            from PIL import ImageChops
            bounds=ImageChops.difference(canvas,Image.new('RGB',canvas.size,'#181818')).getbbox()
            self.assertGreaterEqual(bounds[0],80);self.assertLessEqual(bounds[2],1000)
            self.assertGreaterEqual(bounds[1],200);self.assertLessEqual(bounds[3],1720)
            self.assertAlmostEqual((bounds[2]-bounds[0])/(bounds[3]-bounds[1]),size[0]/size[1],places=2)
    def test_no_artificial_media(self):
        with self.assertRaises(RuntimeError):original_media(('',''))
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
