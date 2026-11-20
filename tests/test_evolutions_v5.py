"""Vérifie le contrat éditorial ET la couleur des vrais pixels rendus."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from agent import ROOT
from visual_top7 import render_top7, movement_state, style_for_category, DESIGN

class EvolutionsV5(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'donnees/demo_bd_2026.json').read_text(encoding='utf8'))
        self.data['variations_verifiees']=True
        self.data['titres'][0]['mouvement']='+3 PL.'
        self.data['titres'][1]['mouvement']='−2 PL.'
        self.data['titres'][2]['mouvement']='= STABLE'
        self.data['titres'][3]['mouvement']='NOUVEAU'
        self.chart=json.loads(DESIGN.read_text(encoding='utf8'))

    def test_green_arrow_up_and_red_arrow_down(self):
        self.assertEqual(movement_state({'mouvement':'+3 PL.'},True),('↑ 3 PLACES','↑ 3','progression'))
        self.assertEqual(movement_state({'mouvement':'−2 PL.'},True),('↓ 2 PLACES','↓ 2','recul'))
        self.assertEqual(movement_state({'mouvement':'+1 PL.'},True),('↑ 1 PLACE','↑ 1','progression'))
        self.assertEqual(movement_state({'mouvement':'-1 PL.'},True),('↓ 1 PLACE','↓ 1','recul'))

    def test_no_unverified_delta(self):
        self.assertEqual(movement_state({'mouvement':'+3 PL.'},False)[2],'indisponible')
        self.assertEqual(movement_state({'mouvement':'NON DOCUMENTÉ'},True)[2],'indisponible')

    def test_three_original_backgrounds_are_present_and_exact(self):
        refs=json.loads((ROOT/'assets/fonds_provenance.json').read_text(encoding='utf8'))
        for category in ('BD','MANGA','COMICS'):
            style,filename=style_for_category(category,self.chart)
            self.assertTrue(filename.is_file(),category)
            self.assertEqual(filename,ROOT/refs[category]['fichier'])
            self.assertEqual(hashlib.sha256(filename.read_bytes()).hexdigest(),refs[category]['sha256'])
            self.assertNotEqual(style['violet'],None)
        self.assertEqual(self.chart['categorie_styles']['MANGA']['violet'],'#171717')
        self.assertEqual(self.chart['categorie_styles']['COMICS']['violet'],'#970017')

    def test_visual_identity_requires_unique_backgrounds(self):
        names=[style_for_category(cat,self.chart)[1].name for cat in ('BD','MANGA','COMICS')]
        self.assertEqual(len(set(names)),3)

    def test_background_on_each_category_untouched_by_renderer(self):
        before={cat:hashlib.sha256(style_for_category(cat,self.chart)[1].read_bytes()).hexdigest() for cat in ('BD','MANGA','COMICS')}
        with tempfile.TemporaryDirectory() as tmp:
            for cat in ('BD','MANGA','COMICS'):
                data=copy.deepcopy(self.data)
                data['categorie']=cat
                data['perimetre']='MAQUETTE FICTIVE — NON PUBLIABLE'
                data['source']='DONNÉES FICTIVES'
                data['url_source']='https://example.org/maquette'
                folder=Path(tmp)/cat
                result=render_top7(data,folder,Path(tmp)/'aucune_couverture',use_watermark=True)
                self.assertEqual(result['pages'],8)
                self.assertEqual(len(list(folder.glob('0[1-8]_*.png'))),8)
                with Image.open(folder/'01_rang_7.png') as image:
                    self.assertEqual(image.size,(1080,1350))
                manifest=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
                self.assertFalse(manifest['ready_to_stage'])
        for cat in ('BD','MANGA','COMICS'):
            self.assertEqual(hashlib.sha256(style_for_category(cat,self.chart)[1].read_bytes()).hexdigest(),before[cat])

    def test_graphic_colors_on_slide_and_recap_next_to_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'BD'
            render_top7(self.data,folder,Path(tmp)/'no_covers',use_watermark=True)
            manifest=json.loads((folder/'post_manifest.json').read_text(encoding='utf8'))
            self.assertEqual(len(manifest['pages']),8)
            self.assertFalse(manifest['ready_to_stage'])
            self.assertEqual(manifest['indicateurs_evolution']['1'],{'texte':'↑ 3','etat':'progression','couleur':'#13853C'})
            self.assertEqual(manifest['indicateurs_evolution']['2'],{'texte':'↓ 2','etat':'recul','couleur':'#CB2434'})
            green=(19,133,60);red=(203,36,52)
            # rank 1 is slide 7; rank 2 is slide 6
            for picture,expected in [(folder/'07_rang_1.png',green),(folder/'06_rang_2.png',red)]:
                with Image.open(picture) as im:
                    self.assertEqual(im.size,(1080,1350))
                    # crop excludes border: checks colored text (arrow and number)
                    region=im.crop((685,1173,940,1225))
                    self.assertGreater(sum(1 for p in region.getdata() if p==expected),15,picture)
            # In recap, each title's movement occupies the same row, next to the title.
            with Image.open(folder/'08_recapitulatif.png') as im:
                for y,color in [(238,green),(373,red)]:
                    badge=im.crop((835,y+36,974,y+80))
                    self.assertGreater(sum(1 for p in badge.getdata() if p==color),4,(y,color))

if __name__=='__main__':unittest.main()
