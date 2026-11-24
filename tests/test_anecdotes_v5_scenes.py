"""Scénarios V5 : images fidèles à leur rôle, pas de répétition, mise à jour Buffer."""
import datetime as dt
import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw
from anecdotes_auto import catalogue, photos_reelles, visuels, run

PARIS=ZoneInfo('Europe/Paris')
FACT=next(f for f in catalogue.bank() if f['id']=='bruxelles-horta')

def img(seed):
    rd=random.Random(seed)
    x=Image.new('RGB',(780,650),'#eeeedc');d=ImageDraw.Draw(x)
    for i in range(75):
        a,b=rd.randint(0,700),rd.randint(0,600)
        fill=(rd.randint(0,230),rd.randint(0,230),rd.randint(0,230))
        d.rectangle((a,b,a+rd.randint(8,70),b+rd.randint(8,45)),fill=fill)
    return x

class TestScenesV5(unittest.TestCase):
    def test_config_narratif_explicite(self):
        cfg=json.loads(photos_reelles.CATALOGUE.read_text('utf8'))
        self.assertEqual(cfg['minimum_images_distinctes'],3)
        for ident,sc in cfg['scenarios'].items():
            self.assertIn(ident,{x['id'] for x in catalogue.bank()})
            pages=[x['page'] for x in sc['visuels']]
            self.assertEqual(len(pages),len(set(pages)))
            self.assertIn(1,pages)
            self.assertGreaterEqual(len(pages),3)
            self.assertTrue(all(x.get('pertinence') and x.get('role') and x.get('titre') for x in sc['visuels']))
            self.assertEqual(len({x['famille_source'] for x in sc['visuels']}),len(sc['visuels']))

    def test_nouveau_domaine_thumb_wikimedia_autorise_sans_ouvrir_autre_domaine(self):
        self.assertTrue(photos_reelles._valid_image_url(
            'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/aa/photo.jpg/1600px-photo.jpg'))
        self.assertFalse(photos_reelles._valid_image_url(
            'https://thumb.wikimedia.org.evil.example/wikipedia/commons/thumb/a/photo.jpg'))
        self.assertFalse(photos_reelles._valid_image_url(
            'https://thumb.wikimedia.org/evil/image.jpg'))

    def test_aucune_source_generique_pour_anecdote_sans_scenes(self):
        x=next(f for f in catalogue.bank() if f['id']=='spirou-robvel')
        with self.assertRaisesRegex(photos_reelles.PhotosIndisponibles,'Aucun scénario'):
            photos_reelles.resolve(x)

    def test_license_cc_by_refusee_et_ancien_pd_explicitement_declare(self):
        meta={'LicenseShortName':{'value':'CC BY-SA 4.0'}}
        with self.assertRaises(photos_reelles.PhotosIndisponibles):
            photos_reelles._license(meta,'photo.jpg',{})
        pd={'LicenseShortName':{'value':'Public domain'}}
        with self.assertRaises(photos_reelles.PhotosIndisponibles):
            photos_reelles._license(pd,'photo.jpg',{})
        self.assertIn('Domaine public',photos_reelles._license(pd,'portrait.png',{
           'domaine_public_ancien':True,'artiste_mort_avant_1900':True}))

    def test_fichiers_de_photos_uniques_et_roles_correspondants(self):
        with tempfile.TemporaryDirectory() as td:
            paths=[];docs=[]
            for i,p in enumerate([1,2,3,4]):
                f=Path(td)/f'image-{p}.jpg';img(111+i).save(f)
                paths.append(f)
                docs.append({'page':p,'role':f'ETAPE {p}','pertinence':f'Image {p} montre la scene {p}',
                      'titre_commons':f'Fichier {p}.jpg','licence':'CC0 1.0',
                      'famille_source':f'famille-{p}','epoque':'actuelle'})
            out=Path(td)/'pages';audit=Path(td)/'controle.json'
            imgs=visuels.render(FACT,out,paths,audit_path=audit,scenes=docs)
            self.assertEqual(len(imgs),5)
            report=json.loads(audit.read_text('utf8'))
            self.assertEqual(report['photos_repetees'],0)
            self.assertTrue(report['narration_verifiee'])
            self.assertEqual(report['etapes_avec_photographie'],[1,2,3,4])
            self.assertEqual(report['pages'][1]['role_visuel'],'ETAPE 2')
            self.assertIsNone(report['pages'][4]['image_source_sha256'])
            self.assertEqual(len({r['image_source_sha256'] for r in report['pages'] if r['image_source_sha256']}),4)

    def test_rejet_de_une_meme_photo_sous_deux_etapes(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'source.jpg';img(5).save(f)
            scenes=[{'page':1,'role':'VUE'}, {'page':3,'role':'VUE COPIE'}]
            with self.assertRaisesRegex(ValueError,'PHOTO_REPETEE'):
                visuels.render(FACT,Path(td)/'out',[f,f],scenes=scenes)

    def test_meme_source_famille_refusee_sans_fabriquer_des_photos(self):
        with tempfile.TemporaryDirectory() as td:
            fs=[];ps=[]
            for i in range(3):
                f=Path(td)/f'img{i}.jpg';img(i+80).save(f);fs.append(f)
                ps.append({'famille_source':'original' if i!=2 else 'autre',
                           'titre_commons':f'Fichier{i}.jpg','page':i+1})
            photos,proof=photos_reelles._maximise_diversite(fs,ps)
            self.assertEqual(len(photos),2)

    def test_download_uniquement_sur_une_scene_documentee(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def fake_fetch(session,title,option):
                calls.append(title)
                seed=sum(ord(c) for c in title)%100000
                import io
                mem=io.BytesIO();img(seed).save(mem,format='JPEG')
                data=mem.getvalue()
                return data,{'titre_commons':title,'licence':'CC0 1.0',
                    'sha256':hashlib.sha256(data).hexdigest()}
            with patch.object(photos_reelles,'_fetch_file',side_effect=fake_fetch):
                pics,docs=photos_reelles.resolve(FACT,cache=Path(td))
                self.assertGreaterEqual(len(pics),3)
                self.assertTrue(all(d['pertinence'] for d in docs))
                self.assertTrue(all(d['fact_id']=='bruxelles-horta' for d in docs))
                self.assertEqual(len({d['page'] for d in docs}),len(docs))
                self.assertEqual(len({d['famille_source'] for d in docs}),len(docs))
                self.assertEqual(len(calls),len(pics))

    def test_mise_a_jour_v4_avec_id_buffer_conserve_et_3_images_pertinentes(self):
        old='📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncien rendu V4'
        class FakeBuffer:
            def __init__(self):self.edits=[];self.creates=[]
            def day(self,day):
                if day.isoformat()=='2026-11-25':
                    return [{'id':'buffer-anecdote-existant','text':old,'dueAt':'2026-11-25T17:00:00Z',
                         'status':'scheduled','channelId':'channel-test'}]
                return []
            def verify_images(self,base,names,folder):
                self.assert_files=[str(folder / x) for x in names]
                assert all((folder/x).is_file() for x in names)
                return [{'image':{'url':base+x}} for x in names]
            def edit_own(self,ident,caption,due,assets):
                self.edits.append((ident,due,len(assets)))
                return {'id':ident,'dueAt':due,'status':'scheduled'}
            def create(self,*args):self.creates.append(args);raise AssertionError('Doublon interdit')
        fake=FakeBuffer()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'anecdotes_state';state.mkdir()
            folder=root/'fixtures';folder.mkdir()
            images=[];docs=[]
            for i,p in enumerate([1,2,4]):
                f=folder/f'{p}.jpg';img(220+i).save(f)
                images.append(f)
                docs.append({'page':p,'role':f'ETAPE {p}','pertinence':'Le visuel représente le fait',
                            'licence':'CC0 1.0','titre_commons':f'photo{p}', 'famille_source':f'source{p}'})
            registry={'2026-11-25':{'etat':'PROGRAMME','fact_id':'bruxelles-horta',
                 'sujet':'bruxelles','id_buffer':'buffer-anecdote-existant','texte_public':old,
                 'version_visuelle':'BD_STORY_PHOTOS_V4_IMAGES_UNIQUES_2026_11'}}
            catalogue.write(state/'programmes.json',registry)
            now=dt.datetime(2026,11,24,9,tzinfo=PARIS)
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),\
                 patch.object(run,'REGISTRY',state/'programmes.json'),\
                 patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                 patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                 patch.object(run,'resolve',return_value=(images,docs)),\
                 patch.dict(run.CONFIG,{'horizon_jours':1,'max_posts_par_execution':1}):
                outcome=run.prepare('owner/public-repo',now=now,buffer=fake,collect=False)
                self.assertEqual(outcome['plans'],['2026-11-25'])
                self.assertEqual(outcome['jours'][1]['resultat'],'MISE_A_JOUR_VISUELLE_PREPAREE')
                got=json.loads((state/'programmes.json').read_text())['2026-11-25']
                self.assertEqual(got['etat'],'EN_ATTENTE_MAJ')
                new_audit=list((state/'audit_compositions').glob('*.json'))
                self.assertTrue(new_audit)
                self.assertEqual(json.loads(new_audit[0].read_text())['photos_utilisees'],3)
                sent=run.send(now=now,buffer=fake)
                self.assertEqual(len(sent['programmes']),1)
                self.assertEqual(fake.edits[0][0],'buffer-anecdote-existant')
                self.assertEqual(fake.edits[0][2],5)
                self.assertFalse(fake.creates)

if __name__=='__main__': unittest.main()
