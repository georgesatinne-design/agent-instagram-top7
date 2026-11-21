import json, tempfile, unittest
from pathlib import Path
from PIL import Image
from agent import run, ROOT
from buffer_client import draft_payload, deposit_draft, construct_draft
from visual_top7 import movement, BACKGROUND

class Top7Tests(unittest.TestCase):
    def test_original_background_exists(self):
        self.assertTrue(BACKGROUND.exists())
    def test_movement_requires_proof(self):
        book={'mouvement':'+2 PL.'}
        self.assertEqual(movement(book,True),'↑ 2 PLACES')
        self.assertEqual(movement(book,False),'ÉVOLUTION NON DISPONIBLE')
    def test_eight_slides_and_reverse_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            report=run(output,ROOT/'donnees/demo_bd_2026.json')
            self.assertEqual(report['dossiers'][0]['diapositives'],8)
            files=sorted((output/'BD').glob('0*.png'))
            self.assertEqual(len(files),8)
            self.assertEqual(files[0].name,'01_rang_7.png')
            self.assertEqual(files[-1].name,'08_recapitulatif.png')
            for f in files:
                with Image.open(f) as image:
                    self.assertEqual(image.size,(1080,1350))
            manifest=json.loads((output/'BD/post_manifest.json').read_text())
            self.assertFalse(manifest['ready_to_stage'])
            self.assertTrue((output/'BD/legende_instagram.txt').exists())
            with self.assertRaises(ValueError):construct_draft(output/'BD','https://example.com/')
    def test_buffer_payload_draft_only_and_8_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            run(output,ROOT/'donnees/demo_bd_2026.json')
            folder=output/'BD';f=folder/'post_manifest.json';data=json.loads(f.read_text());data['ready_to_stage']=True
            f.write_text(json.dumps(data))
            payload=draft_payload(folder,'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/','channel-test')
            fields=payload['variables']['input']
            self.assertTrue(fields['saveToDraft'])
            self.assertEqual(fields['mode'],'customScheduled')
            self.assertIn('dueAt',fields)
            self.assertEqual(len(fields['assets']),8)
            self.assertEqual(fields['assets'][0]['image']['url'].split('/')[-1],'01_rang_7.png')
            simulation=deposit_draft(folder,'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/','channel-test','',send=False)
            self.assertEqual(simulation['statut'],'SIMULATION')
            self.assertFalse((folder/'RECU_BUFFER.json').exists())
    def test_buffer_mock_endpoint_can_only_create_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            run(folder,ROOT/'donnees/demo_bd_2026.json')
            p=folder/'BD';manifest_path=p/'post_manifest.json'
            manifest=json.loads(manifest_path.read_text());manifest['ready_to_stage']=True
            manifest_path.write_text(json.dumps(manifest))
            class FakeResponse:
                def raise_for_status(self):pass
                def json(self):return {'data':{'createPost':{'__typename':'PostActionSuccess','post':{'id':'draft_123','status':'draft'}}}}
            calls=[]
            def fake_post(url,**kwargs):
                calls.append(kwargs['json']['variables']['input'])
                return FakeResponse()
            received=deposit_draft(p,'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/','channel','dummy_token',send=True,check_images=False,post=fake_post)
            self.assertEqual(received['statut'],'BROUILLON_DEPOSE')
            self.assertEqual(len(calls),1)
            self.assertTrue(calls[0]['saveToDraft'])
            self.assertIn('dueAt',calls[0])
            self.assertEqual(calls[0]['mode'],'customScheduled')
            received_again=deposit_draft(p,'https://raw.githubusercontent.com/u/r/main/public_media/week/BD/','channel','dummy_token',send=True,check_images=False,post=fake_post)
            self.assertEqual(received_again['statut'],'DEJA_DEPOSE')
            self.assertEqual(len(calls),1)
    def test_buffer_rejects_other_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); (folder/'post_manifest.json').write_text(json.dumps({'status':'DRAFT_ONLY','ready_to_stage':True,'pages':['01.png']}))
            with self.assertRaises(ValueError):construct_draft(folder,'https://example.com/')
if __name__=='__main__':unittest.main()
