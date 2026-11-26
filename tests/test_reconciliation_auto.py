import datetime as dt
import tempfile
import unittest
from pathlib import Path
from intentions_tops import fingerprint
from reconciliation_auto import reconcile_tops,read_json

NOW=dt.datetime(2026,11,26,10,tzinfo=dt.timezone.utc)
DUE='2026-12-01T17:00:00.000Z'
EDITION='MANGA_2026-11-22'
TEXT='📚 TOP 7 MANGA — édition test'

class ReconciliationAutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.intents={EDITION:{'etat':'CREATION_EN_COURS','due_at':DUE,'empreinte_texte':fingerprint(TEXT)}}
        self.post={'id':'p1','status':'scheduled','dueAt':DUE,'text':TEXT}

    def test_exact_reconstitue_sans_mutation(self):
        result=reconcile_tops(self.intents,[self.post],root=self.root,now=NOW)
        self.assertEqual(result['reconstitues'],1)
        receipt=read_json(self.root/'manga_buffer_receipts'/(EDITION+'.json'))
        self.assertEqual(receipt['id_buffer'],'p1')
        self.assertEqual(self.intents[EDITION]['etat'],'CONFIRME')

    def test_aucun_renvoi_apres_echeance(self):
        result=reconcile_tops(self.intents,[],root=self.root,now=dt.datetime(2026,12,2,tzinfo=dt.timezone.utc))
        self.assertEqual(result['expires_sans_renvoi'],1)
        self.assertEqual(self.intents[EDITION]['etat'],'EXPIRE_INCERTAIN')
        self.assertFalse((self.root/'manga_buffer_receipts').exists())

    def test_ambigu_ou_texte_different(self):
        self.assertEqual(reconcile_tops(self.intents,[self.post,{**self.post,'id':'p2'}],root=self.root,now=NOW)['ambigus'],1)
        self.assertEqual(reconcile_tops(self.intents,[{**self.post,'text':'Autre texte'}],root=self.root,now=NOW)['en_attente'],1)
        self.assertFalse((self.root/'manga_buffer_receipts').exists())

    def test_workflows_automatiques(self):
        root=Path(__file__).resolve().parents[1]/'.github'/'workflows'
        for file in ('audit_manga_sources.yml','audit_buffer_lecture_seule.yml'):
            self.assertIn('  schedule:',(root/file).read_text())

if __name__=='__main__':unittest.main()
