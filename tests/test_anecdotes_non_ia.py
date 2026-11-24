"""Tests du moteur non génératif, y compris remplacement Buffer sans doublon."""
import datetime as dt
import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image
from anecdotes_auto import visuels, photos_reelles, run, catalogue

PARIS=ZoneInfo('Europe/Paris')
BASE=Path(__file__).resolve().parents[1]/'anecdotes_assets'/'fond_bd_original.jpeg'

class TestCarrouselsAuthentiques(unittest.TestCase):
    def test_aucune_ia_dans_pipeline(self):
        p=Path(photos_reelles.__file__).read_text(encoding='utf8')
        self.assertNotIn('image_gen.text2im(',p)
        self.assertNotIn('openai.images.generate(',p)
    def test_cc0_accepte(self):
        m={'LicenseShortName':{'value':'CC0 1.0'}}
        self.assertEqual(photos_reelles._license(m,'Une vraie photo.jpg',{}),'CC0 1.0')
    def test_attribution_obligatoire_refusee(self):
        m={'LicenseShortName':{'value':'CC BY-SA 4.0'}}
        with self.assertRaises(photos_reelles.PhotosIndisponibles):
            photos_reelles._license(m,'Photo.jpg',{})
    def test_image_generee_refusee(self):
        m={'LicenseShortName':{'value':'CC0 1.0'},'ImageDescription':{'value':'AI-generated synthetic image'}}
        with self.assertRaises(photos_reelles.PhotosIndisponibles):
            photos_reelles._license(m,'Photo.jpg',{})
    def test_pas_de_carrousel_sans_photo_reelle(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError,'photos réelles'):
                visuels.render(catalogue.bank()[0],t,photos=[])
    def test_les_5_pages_avec_photographies_sourcees(self):
        with tempfile.TemporaryDirectory() as t:
            paths=visuels.render(catalogue.bank()[0],t,photos=[BASE,BASE])
            self.assertEqual(len(paths),5)
            for f in paths:
                with Image.open(Path(t)/f) as im:
                    self.assertEqual(im.size,(1080,1350))
            self.assertTrue((Path(t)/'apercu.png').is_file())
    def test_titre_commons_preapprouve(self):
        scenarios=json.loads(photos_reelles.CATALOGUE.read_text())['scenarios']
        self.assertTrue(scenarios['bruxelles-horta']['visuels'])
        self.assertTrue(all('titre' in p and 'pertinence' in p and 'page' in p for sc in scenarios.values() for p in sc['visuels']))
    def test_url_media_securisee(self):
        self.assertTrue(photos_reelles._valid_image_url('https://upload.wikimedia.org/wikipedia/commons/test.jpg'))
        self.assertFalse(photos_reelles._valid_image_url('https://upload.wikimedia.org.evil.com/test.jpg'))
    def test_edit_buffer_ne_deplace_pas_horaire(self):
        from anecdotes_auto.buffer import Buffer
        call=[]
        def post(url,**kw):
            variables=kw['json']['variables'];call.append(variables['input'])
            class Response:
                def raise_for_status(self):pass
                def json(self):return {'data':{'editPost':{'__typename':'PostActionSuccess','post':{'id':'old-23','dueAt':'2026-11-29T17:00:00.000Z','status':'scheduled'}}}}
            return Response()
        b=Buffer(api_key='test',channel_id='c',organization_id='o',post=post)
        due='2026-11-29T17:00:00.000Z'
        assets=[{'image':{'url':'https://raw.githubusercontent.com/test/r/main/one.png'}}]*5
        r=b.edit_own('old-23','📚 ANECDOTE BD nouvelle version',due,assets)
        self.assertEqual(r['id'],'old-23')
        self.assertEqual(call[0]['dueAt'],due)
        self.assertEqual(call[0]['id'],'old-23')
    def test_existing_post_mis_a_jour_sans_creation(self):
        old='📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncien texte'
        class Fake:
            def __init__(self):self.edits=[];self.creates=[]
            def day(self,day):return [{'id':'id-deja-buffer','text':old,'dueAt':'2026-11-29T17:00:00Z',
                                       'status':'scheduled','channelId':'c'}]
            def verify_images(self,base,names,folder):return [{'image':{'url':base+name}} for name in names]
            def edit_own(self,ident,txt,due,assets):
                self.edits.append((ident,due,txt,len(assets)))
                return {'id':ident,'dueAt':due,'status':'scheduled'}
            def create(self,*args):self.creates.append(args);raise AssertionError('Jamais créer un second post')
        fake=Fake()
        when=dt.datetime(2026,11,24,9,tzinfo=PARIS)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            folder=root/'public_media'/'anecdotes_bd'/'exemple';folder.mkdir(parents=True)
            names=[]
            for n in range(5):
                name=f'{n+1:02d}_anecdote.png'
                Image.new('RGB',(1080,1350),'purple').save(folder/name);names.append(name)
            rec={'2026-11-29':{'etat':'EN_ATTENTE_MAJ','date':'2026-11-29',
                 'id_buffer':'id-deja-buffer','ancien_texte_public':old,
                 'texte_public':'📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nNouveau texte',
                 'dossier':'public_media/anecdotes_bd/exemple','images':names,
                 'base_url':'https://raw.githubusercontent.com/owner/repo/main/public_media/anecdotes_bd/exemple/',
                 'due_at':'2026-11-29T17:00:00Z'}}
            state=root/'anecdotes_state';state.mkdir()
            (state/'programmes.json').write_text(json.dumps(rec),encoding='utf8')
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),\
                patch.object(run,'REGISTRY',state/'programmes.json'),\
                patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'):
                # Test only the sending path, all actual network operations mocked.
                r=run.send(now=when,buffer=fake)
                self.assertEqual(len(r['programmes']),1)
                self.assertEqual(fake.creates,[])
                self.assertEqual(fake.edits[0][0],'id-deja-buffer')
                after=json.loads((state/'programmes.json').read_text())
                self.assertEqual(after['2026-11-29']['etat'],'PROGRAMME')
                self.assertEqual(after['2026-11-29']['id_buffer'],'id-deja-buffer')

if __name__=='__main__':unittest.main()
