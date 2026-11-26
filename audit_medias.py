"""Inventaire local en lecture seule des médias publics. N'efface JAMAIS de fichier."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

def audit(root):
    root=Path(root)
    groups=defaultdict(list)
    total=0
    for p in sorted((root/'public_media').rglob('*')):
        if not p.is_file() or p.is_symlink():continue
        size=p.stat().st_size
        total+=size
        with p.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
        groups[digest].append({'path':p.relative_to(root).as_posix(),'bytes':size})
    duplicates=[v for v in groups.values() if len(v)>1]
    return {'fichiers':sum(map(len,groups.values())),'octets':total,
            'octets_dupliques':sum(sum(x['bytes'] for x in v[1:]) for v in duplicates),
            'doublons_exacts':duplicates,
            'note':'Ne pas supprimer : des URLs distinctes peuvent encore être référencées par Buffer.'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='.')
    args=parser.parse_args()
    print(json.dumps(audit(args.root),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
