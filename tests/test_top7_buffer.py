import json
import tempfile
import shutil
import unittest
from pathlib import Path
from PIL import Image

from agent import run, ROOT
from buffer_client import draft_payload, deposit_draft, construct_draft
from visual_top7 import movement, BACKGROUND


class Top7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_tmp = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.fixture_tmp.name)
        run(cls.fixture_root, ROOT / 'donnees/demo_bd_2026.json')

    @classmethod
    def tearDownClass(cls):
        cls.fixture_tmp.cleanup()

    def test_original_background_exists(self):
        self.assertTrue(BACKGROUND.exists())

    def test_movement_requires_proof(self):
        book = {'mouvement': '+2 PL.'}
        self.assertEqual(movement(book, True), '↑ 2 PLACES')
        self.assertEqual(movement(book, False), 'ÉVOLUTION NON DISPONIBLE')

    def test_eight_slides_and_reverse_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            report = run(output, ROOT / 'donnees/demo_bd_2026.json')
            self.assertEqual(report['dossiers'][0]['diapositives'], 8)
            files = sorted((output / 'BD').glob('0*.png'))
            self.assertEqual(len(files), 8)
            self.assertEqual(files[0].name, '01_rang_7.png')
            self.assertEqual(files[-1].name, '08_recapitulatif.png')
            for file in files:
                with Image.open(file) as image:
                    self.assertEqual(image.size, (1080, 1350))
            manifest = json.loads((output / 'BD/post_manifest.json').read_text(encoding='utf-8'))
            self.assertFalse(manifest['ready_to_stage'])
            self.assertEqual(manifest['status'],'READY_FOR_QUEUE')
            caption = (output / 'BD/legende_instagram.txt').read_text(encoding='utf-8')
            self.assertNotIn('Source :', caption)
            self.assertNotIn('BDZoom', caption)
            self.assertNotIn('GfK', caption)
            self.assertTrue((output / 'BD/classement_donnees.json').exists())
            with self.assertRaises(ValueError):
                construct_draft(output / 'BD', 'https://example.com/')

    def _ready_folder(self, output):
        # Copy the already-rendered fixture instead of regenerating 8 large PNGs
        # on every test. Content and manifest remain identical.
        folder = output / 'BD'
        shutil.copytree(self.fixture_root / 'BD', folder)
        manifest_path = folder / 'post_manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['ready_to_stage'] = True  # Simulation du résultat d'une collecte complète
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        return folder

    def test_buffer_payload_queue_and_eight_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self._ready_folder(Path(tmp))
            base = 'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/'
            payload = draft_payload(folder, base, 'channel-test')
            fields = payload['variables']['input']
            self.assertNotIn('saveToDraft', fields)
            self.assertFalse(fields['needsApproval'])
            self.assertEqual(fields['mode'], 'customScheduled')
            self.assertIn('dueAt', fields)
            self.assertEqual(len(fields['assets']), 8)
            self.assertTrue(fields['assets'][0]['image']['url'].endswith('01_rang_7.png'))
            simulation = deposit_draft(folder, base, 'channel-test', '', send=False)
            self.assertEqual(simulation['statut'], 'SIMULATION')
            self.assertEqual(simulation['publication'], 'QUEUE_BUFFER')
            self.assertFalse((folder / 'RECU_BUFFER.json').exists())

    @staticmethod
    def _post_responses(*, existing=None, created_status='scheduled', fail_if_create=False):
        calls=[]
        class FakeResponse:
            def __init__(self, answer): self.answer=answer
            def raise_for_status(self): pass
            def json(self): return self.answer
        def fake_post(url, **kwargs):
            message=kwargs['json']
            query=message['query']
            variables=message.get('variables') or {}
            if 'GetOrganizations' in query:
                answer={'account':{'organizations':[{'id':'org-id'}]}}
                calls.append(('org',variables))
            elif 'CheckScheduledSlot' in query:
                answer={'posts':{'pageInfo':{'hasNextPage':False},
                                 'edges':[{'node':item} for item in (existing or [])]}}
                calls.append(('slot',variables))
            elif 'EditExistingPost' in query:
                inp=variables['input']
                answer={'editPost':{'__typename':'PostActionSuccess',
                                   'post':{'id':inp['id'],'status':'scheduled','dueAt':inp['dueAt']}}}
                calls.append(('edit',inp))
            elif 'CreatePost' in query:
                if fail_if_create:raise AssertionError('La création supplémentaire est interdite')
                inp=variables['input']
                answer={'createPost':{'__typename':'PostActionSuccess',
                                     'post':{'id':'post_123','status':created_status,'dueAt':inp['dueAt']}}}
                calls.append(('create',inp))
            else:
                raise AssertionError('Opération GraphQL non reconnue')
            return FakeResponse({'data':answer})
        return fake_post,calls

    def test_buffer_mock_endpoint_creates_scheduled_post_and_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            fake_post,calls=self._post_responses()
            base='https://raw.githubusercontent.com/u/r/main/public_media/week/BD/'
            received=deposit_draft(folder,base,'channel','dummy_token',send=True,
                                  check_images=False,post=fake_post)
            self.assertEqual(received['statut'],'POST_PROGRAMME')
            self.assertEqual(received['action'],'CREATION')
            self.assertEqual([k for k,_ in calls],['org','slot','create'])
            self.assertNotIn('saveToDraft',calls[-1][1])
            self.assertEqual(calls[-1][1]['mode'],'customScheduled')
            received_again=deposit_draft(folder,base,'channel','dummy_token',send=True,
                                        check_images=False,post=fake_post)
            self.assertEqual(received_again['statut'],'DEJA_DEPOSE')
            self.assertEqual(len(calls),3)

    def test_buffer_rejects_unexpected_draft_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            fake_post,calls=self._post_responses(created_status='draft')
            with self.assertRaisesRegex(RuntimeError,'statut : draft'):
                deposit_draft(folder,'https://example.com/','channel','dummy',
                              send=True,check_images=False,post=fake_post)
            self.assertFalse((folder/'RECU_BUFFER.json').exists())

    def test_replaces_previous_bd_top_at_same_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            from buffer_client import draft_payload
            base='https://example.com/'
            inp=draft_payload(folder,base,'channel')['variables']['input']
            old_post={'id':'older_bd_post','channelId':'channel','status':'scheduled',
                      'dueAt':inp['dueAt'],'text':'📚 TOP 7 BD — Les meilleures ventes\n📅 Ventes DU 26/10 AU 01/11/2026'}
            fake_post,calls=self._post_responses(existing=[old_post],fail_if_create=True)
            received=deposit_draft(folder,base,'channel','dummy',send=True,
                                  check_images=False,post=fake_post)
            self.assertEqual(received['action'],'REMPLACEMENT')
            self.assertEqual(received['id_buffer'],'older_bd_post')
            self.assertEqual(received['ancienne_fin_ventes'],'2026-11-01')
            self.assertEqual([k for k,_ in calls],['org','slot','edit'])
            self.assertEqual(len(calls[-1][1]['assets']),8)
            self.assertEqual(calls[-1][1]['text'],inp['text'])

    def test_same_edition_not_created_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            base='https://example.com/'
            inp=draft_payload(folder,base,'channel')['variables']['input']
            existing={'id':'same_post','channelId':'channel','status':'scheduled',
                      'dueAt':inp['dueAt'],'text':inp['text']}
            fake_post,calls=self._post_responses(existing=[existing],fail_if_create=True)
            received=deposit_draft(folder,base,'channel','dummy',send=True,
                                  check_images=False,post=fake_post)
            self.assertEqual(received['action'],'DEJA_PROGRAMME')
            self.assertEqual([k for k,_ in calls],['org','slot'])

    def test_newer_post_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            base='https://example.com/'
            inp=draft_payload(folder,base,'channel')['variables']['input']
            newer={'id':'newer_post','channelId':'channel','status':'scheduled',
                   'dueAt':inp['dueAt'],'text':'📚 TOP 7 BD\n📅 Ventes DU 09/11 AU 15/11/2026'}
            fake_post,calls=self._post_responses(existing=[newer],fail_if_create=True)
            with self.assertRaisesRegex(RuntimeError,'plus récent'):
                deposit_draft(folder,base,'channel','dummy',send=True,
                              check_images=False,post=fake_post)
            self.assertEqual([k for k,_ in calls],['org','slot'])

    def test_ambiguous_slot_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=self._ready_folder(Path(tmp))
            base='https://example.com/'
            inp=draft_payload(folder,base,'channel')['variables']['input']
            older={'id':'post_older','channelId':'channel','status':'scheduled',
                   'dueAt':inp['dueAt'],'text':'📚 TOP 7 BD\n📅 Ventes DU 26/10 AU 01/11/2026'}
            second={**older,'id':'post_second'}
            fake_post,calls=self._post_responses(existing=[older,second],fail_if_create=True)
            with self.assertRaisesRegex(RuntimeError,'Plusieurs Top 7 BD'):
                deposit_draft(folder,base,'channel','dummy',send=True,
                              check_images=False,post=fake_post)
            self.assertEqual([k for k,_ in calls],['org','slot'])

    def test_buffer_rejects_other_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'post_manifest.json').write_text(json.dumps({
                'status': 'DRAFT_ONLY', 'ready_to_stage': True, 'pages': ['01.png']
            }), encoding='utf-8')
            with self.assertRaises(ValueError):
                construct_draft(folder, 'https://example.com/')


if __name__ == '__main__':
    unittest.main()
