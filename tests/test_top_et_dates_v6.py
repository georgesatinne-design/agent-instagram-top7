import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from visual_top7 import ROOT, render_top7

class TopEtDates(unittest.TestCase):
    def test_band_sur_all_eight_slides_three_categories(self):
        fixture=json.loads((ROOT/'donnees'/'maquette_couleurs_fictive.json').read_text(encoding='utf8'))
        for cat in ('BD',):
            with self.subTest(cat=cat), tempfile.TemporaryDirectory() as tmp:
                data=copy.deepcopy(fixture)
                data['categorie']=cat
                data['perimetre']='MAQUETTE FICTIVE - NON PUBLIABLE'
                data['source']='DONNEES FICTIVES'
                data['url_source']='https://example.org/maquette'
                drawn=[]
                original=ImageDraw.ImageDraw.text
                def spy(self,xy,text,*args,**kwargs):
                    if text.startswith('TOP DES VENTES') or text.startswith('PÉRIODE DES VENTES'):
                        drawn.append(text)
                    return original(self,xy,text,*args,**kwargs)
                with patch.object(ImageDraw.ImageDraw,'text',new=spy):
                    render_top7(data,Path(tmp)/'output',Path(tmp)/'covers',use_watermark=True)
                assert len([x for x in drawn if x.startswith('TOP DES VENTES')])==8
                assert len([x for x in drawn if x.startswith('PÉRIODE DES VENTES')])==8
                assert all('DU 02/11 AU 08/11/2026' in x for x in drawn if x.startswith('PÉRIODE DES VENTES'))
                assert len(list((Path(tmp)/'output').glob('*.png')))>=9

if __name__ == '__main__':
    unittest.main()
