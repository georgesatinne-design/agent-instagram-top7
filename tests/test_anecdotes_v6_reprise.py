"""V6: posts non remplacés signalés, retries idempotents, alternatives narrativement pertinentes."""
import datetime as dt
import hashlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw

from anecdotes_auto import catalogue, photos_reelles, run

PARIS=ZoneInfo('Europe/Paris')

def sample(seed):
    rnd=random.Random(seed)
    im=Image.new('RGB',(900,630),'white');draw=ImageDraw.Draw(im)
    for i in range(110):
        xy=(rnd.randrange(900),rnd.randrange(630))
        draw.rectangle((*xy,min(899,xy[0]+rnd.randrange(30,120)),min(629,xy[1]+rnd.randrange(15,100))),
                       fill=(rnd.randrange(230),rnd.randrange(230),rnd.randrange(230)))
    data=io.BytesIO();im.save(data,'JPEG',quality=89);return data.getvalue()

class SimulatedBuffer:
    def __init__(self,dates):
        self.dates=dates;self.edits=[];self.creates=[]
    def day(self,day):
        key=day.isoformat()
        if key not in self.dates:return []
        return [{'id':'buffer-'+key,'dueAt':key+'T17:00:00Z',
             'text':'📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncienne version',
             'status':'scheduled','channelId':'test'}]
    def verify_images(self,base,names,folder):
        assert all((folder/name).exists() for name in names)
        return [{'image':{'url':base+name}} for name in names]
    def edit_own(self,ident,caption,due,assets):
        self.edits.append((ident,caption,due,len(assets)))
        return {'id':ident,'dueAt':due,'status':'scheduled'}
    def create(self,*args):
        self.creates.append(args)
        raise AssertionError('Jamais créer de doublon pour remplacer')

class TestRepriseV6(unittest.TestCase):
    def test_alternatives_curatees_lucky_luke(self):
        book=json.loads(photos_reelles.CATALOGUE.read_text('utf8'))
        for fact_id in ('lucky-luke-morris','lucky-luke-goscinny','lucky-luke-80'):
            scenario=book['scenarios'][fact_id]
            self.assertGreaterEqual(len(scenario['visuels']),4)
            self.assertIn(3,[x['page'] for x in scenario['visuels']])
            self.assertTrue(any(x.get('alternatives') for x in scenario['visuels']))
            for scene in scenario['visuels']:
                for option in [scene,*scene.get('alternatives',[])]:
                    self.assertTrue(option.get('pertinence'))
                    self.assertTrue(option.get('famille_source'))
                    self.assertTrue(option.get('titre'))

    def test_images_de_secours_sont_distinctes_et_par_etape(self):
        fact=next(f for f in catalogue.bank() if f['id']=='lucky-luke-morris')
        with tempfile.TemporaryDirectory() as td:
            seen=[]
            def fake_fetch(session,titre,option):
                seen.append(titre)
                blob=sample(sum(map(ord,titre))%100_000)
                # One original is an intentionally repeated photo: alternate must be used.
                if titre.startswith('Goscinny (scenarist') and '5894' in titre:
                    blob=sample(sum(map(ord,'Morris y Goscinny 1 - Amsterdam - 27051971.jpg'))%100_000)
                return blob,{'titre_commons':titre,'licence':'CC0 1.0',
                    'sha256':hashlib.sha256(blob).hexdigest()}
            with patch.object(photos_reelles,'_fetch_file',side_effect=fake_fetch):
                pics,proofs=photos_reelles.resolve(fact,cache=Path(td))
            self.assertGreaterEqual(len(pics),3)
            self.assertEqual(len(pics),len(proofs))
            self.assertEqual(len({p['page'] for p in proofs}),len(proofs))
            self.assertTrue(all(p['pertinence'] and p['role'] and p['licence']=='CC0 1.0' for p in proofs))
            self.assertTrue(any('5892' in x or '5893' in x for x in seen))

    def test_versions_v5_deja_reussies_pas_forcees_a_reecriture(self):
        self.assertIn('BD_STORY_PHOTOS_V5_NARRATION_SEMANTIQUE_2026_11',run.VERSIONS_DEJA_VALIDES)
        self.assertIn(run.VERSION_VISUELLE,run.VERSIONS_DEJA_VALIDES)

    def test_non_remplacements_visibles_mais_non_doubles(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'anecdotes_state';state.mkdir()
            dates=['2026-11-29','2026-12-02']
            registry={day:{'etat':'PROGRAMME','fact_id':('festival-scolaire-1975' if day.endswith('29') else 'lucky-luke-1946'),
                  'sujet':'fest' if day.endswith('29') else 'lucky',
                  'id_buffer':'buffer-'+day,'texte_public':'📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncienne version',
                  'version_visuelle':'BD_STORY_PHOTOS_V4_IMAGES_UNIQUES_2026_11'} for day in dates}
            catalogue.write(state/'programmes.json',registry)
            fake=SimulatedBuffer(dates)
            now=dt.datetime(2026,11,24,10,tzinfo=PARIS)
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),\
                 patch.object(run,'REGISTRY',state/'programmes.json'),\
                 patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                 patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                 patch.object(run,'resolve',side_effect=photos_reelles.PhotosIndisponibles('Ressource indisponible')),\
                 patch.dict(run.CONFIG,{'horizon_jours':9,'max_posts_par_execution':3}):
                prep=run.prepare('owner/public-repo',now=now,buffer=fake,collect=False)
                self.assertEqual(len(prep['remplacements_non_effectues']),2)
                result=run.send(now=now,buffer=fake)
                self.assertEqual(len(result['remplacements_non_effectues']),2)
                self.assertFalse(fake.edits)
                self.assertFalse(fake.creates)
                final=json.loads((root/'sorties/anecdotes_bd/ETAT.json').read_text())
                self.assertEqual(final['statut'],'REPRISES_A_FAIRE')
                self.assertEqual(final['remplacements_non_effectues'],2)
                self.assertEqual(len(json.loads((root/'sorties/anecdotes_bd/REPRISES_A_FAIRE.json').read_text())),2)

    def test_autre_anecdote_pertinente_remplace_un_post_bloque_sans_doublon(self):
        # Le sujet initial n'a aucune photo vérifiée ; Lucky Luke en possède trois.
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'anecdotes_state';state.mkdir()
            date='2026-11-29'
            old='📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nAncienne version'
            catalogue.write(state/'programmes.json',{date:{
                'etat':'PROGRAMME','fact_id':'festival-scolaire-1975',
                'sujet':'festival','id_buffer':'buffer-'+date,
                'texte_public':old,
                'version_visuelle':'BD_STORY_PHOTOS_V4_IMAGES_UNIQUES_2026_11'}})
            fake=SimulatedBuffer(['2026-11-28',date])
            images=[];proofs=[]
            source_dir=root/'sources';source_dir.mkdir()
            for n in (1,2,4):
                p=source_dir/f'vrai-cliche-{n}.jpg'
                p.write_bytes(sample(n*225+12));images.append(p)
                proofs.append({'titre_commons':f'Cliche {n}.jpg',
                 'page':n,'role':f'Etape {n}',
                 'pertinence':'Photographie d’archive des créateurs de Lucky Luke',
                 'licence':'CC0 1.0','famille_source':f'original-{n}'})
            def fake_resolve(fact):
                if fact['id']=='lucky-luke-morris':return images,proofs
                raise photos_reelles.PhotosIndisponibles('Photo absente')
            now=dt.datetime(2026,11,28,10,tzinfo=PARIS)
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),\
                 patch.object(run,'REGISTRY',state/'programmes.json'),\
                 patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                 patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                 patch.object(run,'resolve',side_effect=fake_resolve),\
                 patch.dict(run.CONFIG,{'horizon_jours':1,'max_posts_par_execution':3}):
                prepared=run.prepare('owner/public-repo',now=now,buffer=fake,collect=False)
                self.assertIn(date,prepared['plans'])
                self.assertEqual(prepared['remplacements_non_effectues'],[])
                current=json.loads((state/'programmes.json').read_text())
                self.assertEqual(current[date]['etat'],'EN_ATTENTE_MAJ')
                self.assertEqual(current[date]['fact_id'],'lucky-luke-morris')
                result=run.send(now=now,buffer=fake)
                self.assertEqual(len(result['programmes']),1)
                self.assertEqual(result['remplacements_non_effectues'],[])
                self.assertEqual(len(fake.edits),1)
                self.assertEqual(fake.edits[0][0],'buffer-'+date)
                self.assertFalse(fake.creates)

    def test_git_workflow_signale_les_reprises_apres_archivage(self):
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/anecdotes_bd_auto.yml')
        data=workflow.read_text('utf8')
        self.assertIn('REPRISES_A_FAIRE.json',data)
        self.assertLess(data.index('Archiver le rapport interne'), data.index('Signaler les anecdotes'))
        self.assertIn('sys.exit(1)',data)

if __name__=='__main__':unittest.main()
