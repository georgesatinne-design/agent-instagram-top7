import datetime as dt
import tempfile
import unittest
from pathlib import Path
from media_preflight import verify_public_assets
from audit_medias import audit
from illyadera_queue import free_capacity_for_priority
from test_illyadera_queue import FakeBuffer, make_post, owned, TODAY, at

class ImageResponse:
    def __init__(self, mime='image/png', status=200):
        self.headers={'Content-Type':mime}
        self.status_code=status
    def raise_for_status(self):pass
    def close(self):pass

class SafetyTests(unittest.TestCase):
    def test_media_public_required(self):
        item={'image':{'url':'https://raw.githubusercontent.com/a/b/main/x.png'}}
        self.assertTrue(verify_public_assets([item],getter=lambda *a,**k:ImageResponse()))
        with self.assertRaises(RuntimeError):
            verify_public_assets([item],getter=lambda *a,**k:ImageResponse('text/html'),attempts=1)
        with self.assertRaises(ValueError):
            verify_public_assets([{'image':{'url':'https://example.com/x.png'}}])

    def test_limit_free(self):
        with self.assertRaises(ValueError):
            free_capacity_for_priority(at(2),buffer=FakeBuffer([]),now=TODAY,max_posts=11)

    def test_other_top_never_preempted(self):
        b=FakeBuffer([make_post(1,2,'📚 TOP 7 MANGA')])
        with self.assertRaises(RuntimeError):
            free_capacity_for_priority(at(2),buffer=b,registry={},now=TODAY,priority='COMICS')
        self.assertFalse(b.deleted)

    def test_modified_queue_blocks_delete(self):
        posts=[make_post(i,i+2) for i in range(10)]
        registry=owned(posts,9)
        class Changed(FakeBuffer):
            def list_scheduled(self):
                rows=super().list_scheduled()
                if self.reads>1:return rows[:-1]
                return rows
        b=Changed(posts)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                free_capacity_for_priority(at(1),buffer=b,registry=registry,registry_path=Path(d)/'r.json',now=TODAY)
        self.assertFalse(b.deleted)

    def test_media_audit_never_deletes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'public_media';p.mkdir()
            (p/'a.png').write_bytes(b'hello');(p/'b.png').write_bytes(b'hello')
            r=audit(d)
            self.assertEqual(r['fichiers'],2)
            self.assertEqual(r['octets_dupliques'],5)
            self.assertTrue((p/'b.png').is_file())

if __name__=='__main__':unittest.main()
