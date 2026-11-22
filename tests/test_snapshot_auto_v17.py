import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import run, ROOT


class TestSourceVerifiedSnapshot(unittest.TestCase):
    def test_verified_source_never_uses_demo_watermark(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            snap=root/'source_bdzoom.json'
            snap.write_bytes((ROOT/'donnees/demo_bd_2026.json').read_bytes())
            with patch('agent.search_bede_catalog',return_value=({},[])), \
                 patch('agent.search_google_books',return_value=None), \
                 patch('agent.download_cover',return_value=(True,'simulation')), \
                 patch('agent.render_top7',return_value={'pages':8,'missing_covers':[],'visual_fingerprint':'test'}) as mock_render:
                report=run(root/'sorties',snap,verified_snapshot=True)
            self.assertEqual(report['dossiers'][0]['diapositives'],8)
            self.assertEqual(report['dossiers'][0]['couvertures'],7)
            self.assertFalse(mock_render.call_args.kwargs['use_watermark'])
            self.assertEqual(mock_render.call_args.args[0]['categorie'],'BD')
            self.assertIn('snapshot',report['journal'][0].lower())

if __name__=='__main__':unittest.main()
