"""Test de non-régression BD/Manga pour l'installation V9.1."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class TestWorkflows(unittest.TestCase):
    def test_tests_bd_limites_aux_modules_bd(self):
        yml=(ROOT/'.github/workflows/hebdomadaire.yml').read_text(encoding='utf8')
        self.assertNotIn('unittest discover -s tests -v',yml)
        for test in ('test_agent.py','test_top7_buffer.py','test_illyadera_queue.py'):
            self.assertIn(test,yml)
        self.assertIn("if: steps.source.outputs.new == 'true'",yml)

    def test_manga_public_compatible_avec_buffer(self):
        src=(ROOT/'manga_pipeline_auto.py').read_text(encoding='utf8')
        self.assertIn("m['version_contenu']=VERSION_PUBLIQUE",src)
        self.assertIn('SOURCE_PUBLIQUE.search(legende)',src)
        self.assertNotIn('TOP RECONSTITUÉ • EDISTAT',src)
        self.assertNotIn('Classement hebdomadaire reconstitué',src)

if __name__=='__main__': unittest.main()
