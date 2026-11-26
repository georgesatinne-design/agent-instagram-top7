import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from intentions_tops import reserve,lookup,confirm,recoverable
from journal_publication import checkpoint

class IntentionsTopsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'intentions.json'
        self.payload={'dueAt':'2026-12-01T17:00:00.000Z','text':'📚 TOP 7 MANGA — édition'}
        self.edition='MANGA_2026-11-22'
        self.post={'id':'post1','status':'scheduled','dueAt':self.payload['dueAt'],'text':self.payload['text']}

    def test_reservation_persistante_et_confirmation(self):
        with patch('intentions_tops.checkpoint') as save:
            reserve(self.edition,self.payload,path=self.path)
            self.assertTrue(save.called)
            with self.assertRaises(RuntimeError):reserve(self.edition,self.payload,path=self.path)
            self.assertTrue(recoverable(self.edition,self.post,self.payload,path=self.path))
            confirm(self.edition,'post1',self.payload['dueAt'],path=self.path)
            self.assertEqual(lookup(self.edition,self.path)['etat'],'CONFIRME')
            self.assertFalse(recoverable(self.edition,{**self.post,'id':'post2'},self.payload,path=self.path))

    def test_texte_et_creneau_exacts(self):
        reserve(self.edition,self.payload,path=self.path)
        self.assertFalse(recoverable(self.edition,{**self.post,'text':'Manuel'},self.payload,path=self.path))
        self.assertFalse(recoverable(self.edition,{**self.post,'dueAt':'2026-12-08T17:00:00Z'},self.payload,path=self.path))

    def test_push_echoue_avant_mutation(self):
        with patch('intentions_tops.checkpoint',side_effect=RuntimeError('push refusé')):
            with self.assertRaises(RuntimeError):reserve(self.edition,self.payload,path=self.path)
        self.assertEqual(lookup(self.edition,self.path)['etat'],'CREATION_EN_COURS')

    def test_checkpoint_production_interdit_hors_main(self):
        with patch.dict(os.environ,{'ILLYADERA_DURABLE_JOURNAL':'1','GITHUB_ACTIONS':'true','GITHUB_REF':'refs/heads/test'}):
            with self.assertRaises(RuntimeError):checkpoint(self.path)

    def test_workflows_isolent_les_tests_et_ont_un_arret(self):
        root=Path(__file__).resolve().parents[1]/'.github'/'workflows'
        for name in ('hebdomadaire.yml','manga_top7_collecte.yml','comics_top7_auto.yml','anecdotes_bd_auto.yml'):
            source=(root/name).read_text()
            self.assertIn("vars.ILLYADERA_PAUSE_PUBLICATION != '1'",source)
            self.assertNotIn("    env:\n      ILLYADERA_DURABLE_JOURNAL",source)
            self.assertNotIn("\n          python -m unittest discover -s tests -p 'test_illyadera_queue.py' -q",source)

if __name__=='__main__':unittest.main()
