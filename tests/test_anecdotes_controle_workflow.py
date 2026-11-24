"""Non-regressions : absence de photo != panne Buffer != succès silencieux."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anecdotes_auto import controle_workflow as c


class TestControleFinal(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)

    def write_reports(self,pending=None,erreurs=None,etat=None):
        pending=pending if pending is not None else []
        (self.root/'REPRISES_A_FAIRE.json').write_text(json.dumps(pending),encoding='utf8')
        (self.root/'ETAT.json').write_text(json.dumps(dict(
            statut=etat or ('REPRISES_A_FAIRE' if pending else 'EXECUTION_TERMINEE'),
            remplacements_non_effectues=len(pending),erreurs=erreurs or [])),encoding='utf8')
        (self.root/'RESULTATS_BUFFER.json').write_text(json.dumps(dict(programmes=[{'id':'Buffer1'}],erreurs=[])),encoding='utf8')

    def test_remplacement_en_attente_est_avertissement_et_non_echec(self):
        self.write_reports([dict(date='2026-11-29',fact_id='festival-scolaire-1975',
                                 raison='Aucune photo vérifiée')])
        problems,pending,updates=c.inspect_reports(self.root)
        self.assertEqual(problems,[])
        self.assertEqual(len(pending),1)
        self.assertEqual(updates,1)
        output=c.render_summary(problems,pending,updates)
        self.assertIn('⚠️',output)
        with patch.dict('os.environ',{},clear=True):
            self.assertEqual(c.main(['--report-dir',str(self.root)]),0)

    def test_non_remplacement_explique_pas_un_succes_total(self):
        self.write_reports([dict(date='2026-11-29', fact_id='festival-scolaire-1975',raison='Sans archives')])
        text=c.render_summary(*c.inspect_reports(self.root))
        self.assertIn('ancienne présentation',text)
        self.assertNotIn('Aucune anecdote en attente',text)

    def test_erreur_buffer_reste_bloquante(self):
        self.write_reports()
        path=self.root/'RESULTATS_BUFFER.json'
        d=json.loads(path.read_text())
        d['erreurs']=['Buffer refusé']
        path.write_text(json.dumps(d),encoding='utf8')
        self.assertEqual(c.main(['--report-dir',str(self.root)]),1)

    def test_rapport_manquant_reste_bloquant(self):
        self.assertEqual(c.main(['--report-dir',str(self.root)]),1)

    def test_incoherence_reste_bloquante(self):
        self.write_reports([{'date':'2026-11-29','fact_id':'x'}])
        path=self.root/'ETAT.json'
        d=json.loads(path.read_text());d['remplacements_non_effectues']=0
        path.write_text(json.dumps(d),encoding='utf8')
        self.assertEqual(c.main(['--report-dir',str(self.root)]),1)

    def test_succes_sans_reprise(self):
        self.write_reports()
        self.assertEqual(c.main(['--report-dir',str(self.root)]),0)

    def test_workflow_apres_archivage_et_test_existing(self):
        wf=(Path(__file__).resolve().parents[1]/'.github/workflows/anecdotes_bd_auto.yml').read_text(encoding='utf8')
        self.assertIn('python -m anecdotes_auto.controle_workflow',wf)
        self.assertLess(wf.index('Archiver le rapport interne'),wf.index('Contrôler les reprises'))
        self.assertNotIn('sys.exit(1)',wf)


if __name__=='__main__':unittest.main()
