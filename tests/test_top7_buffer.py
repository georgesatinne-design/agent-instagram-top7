import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from agent import run, ROOT
from buffer_client import draft_payload, deposit_draft, construct_draft
from visual_top7 import movement, BACKGROUND


class Top7Tests(unittest.TestCase):
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
        run(output, ROOT / 'donnees/demo_bd_2026.json')
        folder = output / 'BD'
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

    def test_buffer_mock_endpoint_creates_scheduled_post_and_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self._ready_folder(Path(tmp))
            class FakeResponse:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {'data': {'createPost': {
                        '__typename': 'PostActionSuccess',
                        'post': {'id': 'post_123', 'status': 'scheduled'},
                    }}}
            calls = []
            def fake_post(url, **kwargs):
                calls.append(kwargs['json']['variables']['input'])
                return FakeResponse()
            base = 'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/'
            received = deposit_draft(folder, base, 'channel', 'dummy_token', send=True,
                                     check_images=False, post=fake_post)
            self.assertEqual(received['statut'], 'POST_PROGRAMME')
            self.assertEqual(len(calls), 1)
            self.assertNotIn('saveToDraft', calls[0])
            self.assertIn('dueAt', calls[0])
            self.assertEqual(calls[0]['mode'], 'customScheduled')
            received_again = deposit_draft(folder, base, 'channel', 'dummy_token', send=True,
                                           check_images=False, post=fake_post)
            self.assertEqual(received_again['statut'], 'DEJA_DEPOSE')
            self.assertEqual(len(calls), 1)

    def test_buffer_rejects_unexpected_draft_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self._ready_folder(Path(tmp))
            class FakeResponse:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {'data': {'createPost': {
                        '__typename': 'PostActionSuccess',
                        'post': {'id': 'draft_123', 'status': 'draft'},
                    }}}
            def fake_post(url, **kwargs):
                return FakeResponse()
            with self.assertRaisesRegex(RuntimeError, 'statut : draft'):
                deposit_draft(folder, 'https://example.com/', 'channel', 'dummy',
                              send=True, check_images=False, post=fake_post)
            self.assertFalse((folder / 'RECU_BUFFER.json').exists())

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
