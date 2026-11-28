import unittest,datetime as dt,tempfile
from pathlib import Path
from PIL import Image
from reels_illyadera import next_wednesday,exact_post,chunks,canvas
from calendrier_editorial import PARIS
class ReelTests(unittest.TestCase):
    def test_date(self):
        self.assertEqual(next_wednesday(dt.datetime(2026,11,28,10,tzinfo=PARIS)),dt.date(2026,12,2))
        self.assertEqual(next_wednesday(dt.datetime(2026,12,2,17,tzinfo=PARIS)),dt.date(2026,12,9))
    def test_exact(self):
        day=dt.date(2026,12,2);due='2026-12-02T17:00:00Z';text='📚 ANECDOTE DU 9e ART — Exemple'
        rec={'id_buffer':'ours','due_at':due,'texte_public':text}
        p={'id':'ours','dueAt':due,'text':text,'status':'scheduled','metadata':{'type':'post'}}
        self.assertEqual(exact_post([p],rec,day),p)
        self.assertIsNone(exact_post([dict(p,id='autre')],rec,day))
        self.assertIsNone(exact_post([p,dict(p,id='autre')],rec,day))
        self.assertIsNone(exact_post([dict(p,text='autre')],rec,day))
    def test_subtitles(self):
        text="Dans Krazy Kat, la souris Ignatz lance des briques au personnage principal, qui y voit une marque d'affection."
        self.assertEqual(' '.join(chunks(text)),text)
        self.assertTrue(all(len(s)<=66 for s in chunks(text)))
    def test_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'slide.png';Image.new('RGB',(1080,1350),'white').save(src)
            im=canvas(src,'Un fait à découvrir.');self.assertEqual(im.size,(1080,1920))
            self.assertEqual(im.getpixel((540,300)),(255,255,255))
