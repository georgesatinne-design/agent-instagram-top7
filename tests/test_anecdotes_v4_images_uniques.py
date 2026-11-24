"""Tests V4 : identification immédiate du format + zéro photo répétée.
Aucune photo de test n'est envoyée sur Instagram ou Buffer.
"""
from __future__ import annotations
import datetime as dt
import json,random,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image,ImageDraw
from anecdotes_auto import catalogue,run,visuels

PARIS=ZoneInfo('Europe/Paris')


def sample(seed):
    rnd=random.Random(seed)
    im=Image.new('RGB',(830,700),'#f8f0e0')
    d=ImageDraw.Draw(im)
    for i in range(48):
        x,y=rnd.randrange(800),rnd.randrange(660)
        r=rnd.randrange(9,100)
        c=(rnd.randrange(45,240),rnd.randrange(45,240),rnd.randrange(45,240))
        if i%2:d.ellipse((x,y,x+r,y+r),fill=c)
        else:d.line((x,y,x+r,y+2*r),fill=c,width=rnd.randrange(6,18))
    return im


class TestVisuelsUniques(unittest.TestCase):
    def setUp(self):
        self.fact=next(f for f in catalogue.bank() if f['id']=='bruxelles-horta')

    def test_plan_sans_reutilisation(self):
        self.assertEqual(visuels.photo_allocation(1),{1:0})
        self.assertEqual(visuels.photo_allocation(2),{1:0,3:1})
        self.assertEqual(visuels.photo_allocation(3),{1:0,3:1,4:2})
        self.assertEqual(visuels.photo_allocation(5),{1:0,3:1,4:2,5:3,2:4})
        for count in range(1,6):
            values=list(visuels.photo_allocation(count).values())
            self.assertEqual(len(values),len(set(values)))

    def test_photos_exactement_identiques_sont_eliminees(self):
        img=sample(1)
        photos,ids=visuels.load_photos([img,img.copy()])
        self.assertEqual(len(photos),1)
        self.assertEqual(len(ids),1)

    def test_jpeg_reexporte_meme_photo_est_elimine(self):
        import io
        original=sample(11)
        buf=io.BytesIO();original.save(buf,'JPEG',quality=94)
        buf.seek(0)
        with Image.open(buf) as recompressed:second=recompressed.copy()
        clean,_=visuels.load_photos([original,second])
        self.assertEqual(len(clean),1)

    def test_cinq_pages_cinq_images_distinctes(self):
        photos=[sample(i+42) for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            audit=Path(tmp)/'audit.json'
            results=visuels.render(self.fact,Path(tmp)/'media',photos,audit_path=audit)
            self.assertEqual(len(results),5)
            state=json.loads(audit.read_text('utf8'))
            unique=[r['image_source_sha256'] for r in state['pages']]
            self.assertTrue(all(unique))
            self.assertEqual(len(set(unique)),5)
            self.assertEqual(state['photos_repetees'],0)
            for name in results:
                with Image.open(Path(tmp)/'media'/name) as img:self.assertEqual(img.size,(1080,1350))

    def test_deux_photos_differentes_pour_cinq_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit=Path(tmp)/'audit.json'
            visuels.render(self.fact,Path(tmp)/'media',[sample(20),sample(21)],audit_path=audit)
            proof=json.loads(audit.read_text('utf8'))
            by_page={r['page']:r['image_source_sha256'] for r in proof['pages']}
            self.assertTrue(by_page[1]);self.assertTrue(by_page[3])
            self.assertNotEqual(by_page[1],by_page[3])
            self.assertIsNone(by_page[2]);self.assertIsNone(by_page[4]);self.assertIsNone(by_page[5])
            self.assertEqual(proof['photos_repetees'],0)

    def test_un_fichier_duplique_ne_genere_pas_plus_d_une_apparition(self):
        pic=sample(8)
        with tempfile.TemporaryDirectory() as tmp:
            audit=Path(tmp)/'audit.json'
            visuels.render(self.fact,Path(tmp)/'media',[pic,pic.copy(),pic.copy()],audit_path=audit)
            proof=json.loads(audit.read_text('utf8'))
            self.assertEqual(proof['photos_recues'],3)
            self.assertEqual(proof['photos_dedoublonnees'],1)
            self.assertEqual(proof['photos_utilisees'],1)

    def test_rejet_allocation_repetee(self):
        with self.assertRaisesRegex(ValueError,'PHOTO_REPETEE'):
            visuels.page(self.fact,1,[sample(1)],allocation={1:0,3:0})

    def test_identification_serie_garantie_par_code(self):
        import inspect
        src=inspect.getsource(visuels.page)
        self.assertIn("'ANECDOTE BD'",src)
        self.assertIn('font(93)',src)
        self.assertEqual(visuels.VERSION,'BD_ANECDOTE_V4_IMAGES_UNIQUES')
        self.assertIn('ANECDOTE BD',visuels.caption(self.fact))

    def test_la_v4_est_identifiee_comme_nouvelle_revision(self):
        self.assertIn('V4_IMAGES_UNIQUES',run.VERSION_VISUELLE)

if __name__=='__main__':unittest.main()
