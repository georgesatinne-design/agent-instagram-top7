"""Tests de non-régression V3 : création avec 1 vraie photo et remplacement sans doublon."""
import datetime as dt, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image
from anecdotes_auto import catalogue, run, photos_reelles, visuels
from anecdotes_auto.storytelling import story

PARIS=ZoneInfo('Europe/Paris')
BASE=Path(__file__).resolve().parents[1]/'anecdotes_assets'/'fond_bd_original.jpeg'

class TestStoryV3(unittest.TestCase):
    def test_un_visuel_suffit_sans_ia(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample=next(x for x in catalogue.bank() if x['id']=='bruxelles-horta')
            files=visuels.render(sample,tmp,[BASE])
            self.assertEqual(len(files),5)
            for name in files:
                with Image.open(Path(tmp)/name) as im:
                    self.assertEqual(im.size,(1080,1350))
    def test_story_conserve_les_faits(self):
        for fact in catalogue.bank():
            s=story(fact)
            self.assertEqual(s['revelation'],fact['fait'])
            self.assertEqual(s['contexte'],fact['contexte'])
            self.assertEqual(s['detail'],fact['detail'])
    def test_redirect_externe_interdit(self):
        self.assertFalse(photos_reelles._valid_image_url('https://malicious.example.org/sample.jpg'))
        self.assertTrue(photos_reelles._valid_image_url('https://upload.wikimedia.org/wikipedia/commons/a/a9/x.jpg'))
        self.assertTrue(photos_reelles._valid_image_url('https://commons.wikimedia.org/wiki/Special:Redirect/file/test.jpg'))
        self.assertFalse(photos_reelles._valid_image_url('http://commons.wikimedia.org/wiki/Special:Redirect/file/test.jpg'))
    def test_sources_visibles_exclues(self):
        sample=next(x for x in catalogue.bank() if x['id']=='bruxelles-horta')
        t=visuels.caption(sample)
        self.assertTrue(t.startswith('📚 ANECDOTE DU 9e ART'))
        for forbidden in ('http://','https://','Edistat','Source :','Wikimedia Commons'):
            self.assertNotIn(forbidden,t)
    def test_remplacement_different_sujet_meme_post(self):
        old='📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncienne anecdote'
        class FakeBuffer:
            def __init__(self):
                self.edits=[];self.creates=[];self.posts={}
            def day(self,day):
                if day.isoformat()=='2026-11-25':
                    return [dict(id='original-post',text=old,dueAt='2026-11-25T17:00:00Z',status='scheduled',channelId='c')]
                return []
            def verify_images(self,base,names,folder):
                assert all((folder/n).is_file() for n in names)
                return [{'image':{'url':base+n}} for n in names]
            def edit_own(self,pid,caption,due,assets):
                self.edits.append((pid,due,caption,len(assets)))
                return {'id':pid,'status':'scheduled','dueAt':due}
            def create(self,*args):
                self.creates.append(args)
                raise AssertionError('Ne jamais créer un nouveau post au lieu de modifier l’ancien')
        fake=FakeBuffer()
        now=dt.datetime(2026,11,24,10,tzinfo=PARIS)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state=root/'anecdotes_state';state.mkdir()
            current={'2026-11-25':{'etat':'PROGRAMME','fact_id':'urban-superman-vo',
                'sujet':'urban','id_buffer':'original-post','texte_public':old,
                'version_visuelle':'PHOTOS_REELLES_V2_2026_11'}}
            catalogue.write(state/'programmes.json',current)
            def photo(fact,*args,**kwargs):
                # l’ancienne anecdote n’a pas de photo validée ; une autre en a une
                if fact['id']=='saphir-theatre-takarazuka':return [BASE],[{'licence':'CC0 1.0','titre_commons':'sample'}]
                raise photos_reelles.PhotosIndisponibles('Pas de photo approuvée pour cet album')
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),\
                 patch.object(run,'REGISTRY',state/'programmes.json'),\
                 patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                 patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                 patch.object(run,'resolve',side_effect=photo),\
                 patch.dict(run.CONFIG,{'horizon_jours':1,'max_posts_par_execution':1}):
                plan=run.prepare('owner/repository',now=now,buffer=fake,collect=False)
                self.assertEqual(plan['plans'],['2026-11-25'])
                receipt=json.loads((state/'programmes.json').read_text())['2026-11-25']
                self.assertEqual(receipt['etat'],'EN_ATTENTE_MAJ')
                self.assertEqual(receipt['ancien_fact_id'],'urban-superman-vo')
                self.assertEqual(receipt['fact_id'],'saphir-theatre-takarazuka')
                end=run.send(now=now,buffer=fake)
                self.assertEqual(len(end['programmes']),1)
                self.assertEqual(len(fake.edits),1)
                self.assertEqual(fake.edits[0][0],'original-post')
                self.assertEqual(fake.edits[0][1],'2026-11-25T17:00:00Z')
                self.assertEqual(fake.creates,[])
    def test_ne_supprime_pas_post_sans_nouvelle_photo(self):
        self.assertTrue(photos_reelles._license({'LicenseShortName':{'value':'CC0 1.0'}},'Genuine image.jpg',{}))
        with self.assertRaises(photos_reelles.PhotosIndisponibles):
            photos_reelles._license({'LicenseShortName':{'value':'CC BY-SA 4.0'}},'Other image.jpg',{})

if __name__=='__main__':unittest.main()
