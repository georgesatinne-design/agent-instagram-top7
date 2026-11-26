"""Exécute le vrai bloc Python du workflow Manga, sans réseau ni secrets."""
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class WorkflowScriptsTests(unittest.TestCase):
    def test_manga_outputs(self):
        source=(ROOT/'.github/workflows/manga_top7_collecte.yml').read_text(encoding='utf8')
        block=source.split('id: publication',1)[1]
        script=textwrap.dedent(re.search(r"python - <<'PY'\n(.*?)\n\s*PY\n",block,re.S).group(1))
        for skip in (False,True):
            with self.subTest(skip=skip), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                edition='MANGA_2026-11-22'
                folder=root/'sorties'/'manga_production'/edition
                folder.mkdir(parents=True)
                (folder/'ETAT.json').write_text(json.dumps({'edition':edition,'pret_buffer':not skip,'skip_history':skip,
                    'statut_ventes':'A_VERIFIER','couvertures':0 if skip else 7}))
                output=root/'output.txt'
                env={**os.environ,'GITHUB_OUTPUT':str(output),'PYTHONPATH':str(ROOT)}
                proc=subprocess.run([sys.executable,'-c',script],cwd=root,env=env,capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stderr)
                values=dict(line.split('=',1) for line in output.read_text().splitlines())
                self.assertEqual(values,{'edition':edition,'ready':str(not skip).lower(),'skip_history':str(skip).lower()})

if __name__=='__main__':unittest.main()
