import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from illyadera_queue import free_capacity_for_priority
from journal_publication import reconcile_intents
from controle_file import final_guard
from audit_buffer import report
from test_illyadera_queue import FakeBuffer, make_post, owned, TODAY, at

class JournalPublicationTests(unittest.TestCase):
    def test_checkpoint_avant_suppression_et_reprise(self):
        posts=[make_post(i,i+2) for i in range(10)]
        registry=owned(posts,9)
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'r.json'
            with patch('journal_publication.checkpoint',side_effect=RuntimeError('push échoué')):
                with self.assertRaisesRegex(RuntimeError,'push échoué'):
                    free_capacity_for_priority(at(1),buffer=b,registry=registry,registry_path=p,now=TODAY)
            self.assertFalse(b.deleted)
            r=json.loads(p.read_text())
            self.assertEqual(next(iter(r.values()))['etat'],'LIBERATION_EN_COURS')
            self.assertEqual(reconcile_intents(r,posts,TODAY)[0]['etat'],'PROGRAMME')

    def test_confirmation_perdue_restauration_possible(self):
        posts=[make_post(i,i+2) for i in range(10)]
        registry=owned(posts,9)
        class Lost(FakeBuffer):
            def delete_own(self,identity):
                super().delete_own(identity)
                raise RuntimeError('réponse perdue')
        b=Lost(posts)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'r.json'
            with self.assertRaisesRegex(RuntimeError,'réponse perdue'):
                free_capacity_for_priority(at(1),buffer=b,registry=registry,registry_path=p,now=TODAY,priority='MANGA')
            r=json.loads(p.read_text())
            self.assertEqual(reconcile_intents(r,b.posts,TODAY)[0]['etat'],'LIBERE_POUR_MANGA')

    def test_guard_refuse_post_manuel_et_plafond(self):
        due='2026-12-01T17:00:00.000Z'
        def guard(b):
            return final_guard('MANGA',due,api_key='x',channel_id='chan',post=None,buffer=b,now=TODAY)
        self.assertTrue(guard(FakeBuffer([])))
        with self.assertRaises(RuntimeError):guard(FakeBuffer([make_post(1,5)]))
        with self.assertRaises(RuntimeError):guard(FakeBuffer([make_post(i,i+10) for i in range(10)]))

    def test_audit_sans_texte_ni_id(self):
        posts=[make_post(1,5,'📚 TOP 7 MANGA'),make_post(2,5,'Publication manuelle')]
        result=report(posts)
        self.assertEqual(result['jours_avec_plusieurs_posts'],1)
        self.assertEqual(result['contenus_hors_calendrier'],0)
        self.assertNotIn('Publication manuelle',json.dumps(result))
        self.assertNotIn('post1',json.dumps(result))

if __name__=='__main__':unittest.main()
