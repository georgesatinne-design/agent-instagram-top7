import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from surveillance_bd import identifier_edition, already_processed, probe


class TestSurveillanceBd(unittest.TestCase):
    @staticmethod
    def ranking(end='2026-11-15', reverse=False):
        enddate=dt.date.fromisoformat(end)
        start=enddate-dt.timedelta(days=6)
        return {
            'categorie':'BD', 'debut_ventes':start.isoformat(),'fin_ventes':end,
            'titres':[{'rang':i,'titre':f'Album BD {8-i if reverse else i}'} for i in range(1,8)],
        }

    def test_detect_new_week_and_persisted_receipt(self):
        now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            data=self.ranking()
            first=probe(collect=lambda:data,receipts=folder,output=folder/'snapshot.json',now=now)
            self.assertTrue(first['nouveau'])
            self.assertEqual(first['edition'],'BD_2026-11-15')
            self.assertTrue((folder/'snapshot.json').is_file())
            receipt=folder/'BD_2026-11-15.json'
            receipt.write_text(json.dumps({
                'statut':'POST_PROGRAMME','empreinte_classement':first['empreinte_classement']
            }),encoding='utf-8')
            second=probe(collect=lambda:data,receipts=folder,output=folder/'second.json',now=now)
            self.assertFalse(second['nouveau'])
            self.assertFalse((folder/'second.json').exists())

    def test_new_week_gets_its_own_id(self):
        now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc)
        first=identifier_edition(self.ranking('2026-11-08'),now=now)
        other=identifier_edition(self.ranking('2026-11-15'),now=now)
        self.assertNotEqual(first['edition'],other['edition'])

    def test_modified_ranking_same_week_does_not_duplicate(self):
        now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc)
        first=identifier_edition(self.ranking(),now=now)
        changed=identifier_edition(self.ranking(reverse=True),now=now)
        self.assertNotEqual(first['empreinte_classement'],changed['empreinte_classement'])
        with tempfile.TemporaryDirectory() as tmp:
            r=Path(tmp)/f'{first["edition"]}.json'
            r.write_text(json.dumps({'statut':'POST_PROGRAMME','empreinte_classement':first['empreinte_classement']}))
            seen,reason=already_processed(changed,receipts=Path(tmp))
            self.assertTrue(seen)
            self.assertIn('modifié',reason)

    def test_in_progress_reservation_blocks_second_send(self):
        info=identifier_edition(self.ranking(),now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/(info['edition']+'.json')).write_text(json.dumps({'statut':'RESERVATION_AVANT_ENVOI'}))
            seen,reason=already_processed(info,receipts=Path(tmp))
            self.assertTrue(seen)
            self.assertIn('incertain',reason)

    def test_old_ranking_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'trop ancien'):
            identifier_edition(self.ranking('2026-09-01'),now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc))

    def test_missing_rank_is_rejected(self):
        ranking=self.ranking();ranking['titres'][1]['rang']=3
        with self.assertRaisesRegex(ValueError,'incomplet'):
            identifier_edition(ranking,now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc))

    def test_future_dates_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'futur'):
            identifier_edition(self.ranking('2027-01-10'),now=dt.datetime(2026,11,22,12,tzinfo=dt.timezone.utc))

if __name__ == '__main__':unittest.main()
