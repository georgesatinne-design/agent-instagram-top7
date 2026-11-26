import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from anecdotes_auto.migration_9e_art import rebrand
from anecdotes_auto.visuels import NIGHT,YELLOW
class MigrationTests(unittest.TestCase):
    def test_preserve_content(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'old.png';dest=Path(td)/'new.png'
            for n in range(1,6):
                im=Image.new('RGB',(1080,1350),'#abcdef')
                d=ImageDraw.Draw(im)
                d.rectangle((0,0,1079,197 if n==1 else 100),fill=YELLOW if n==1 else NIGHT)
                d.rectangle((0,1270,1079,1349),fill=NIGHT)
                im.save(src)
                rebrand(src,dest,n)
                with Image.open(dest) as new:
                    self.assertEqual(new.crop((0,220,1080,1260)).tobytes(),im.crop((0,220,1080,1260)).tobytes())
