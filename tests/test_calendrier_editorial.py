import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from calendrier_editorial import (PARIS,reserved_kind,slot_on,next_weekly,monthly_slot,
    validate_slot,frozen_slot,assert_arbitrated)
from anecdotes_auto.calendrier import target_date_time,eligible
from manga_buffer_auto import mardi_suivant
from comics_buffer_periodique import next_slot
from illyadera_queue import planned_slots

class CalendrierEditorialTests(unittest.TestCase):
    def test_semaine_complete(self):
        first=dt.date(2026,12,7)
        self.assertEqual([reserved_kind(first+dt.timedelta(days=i)) for i in range(7)],
                         [None,'MANGA',None,'COMICS_HEBDO','BD',None,'COMICS_MENSUEL'])
        self.assertEqual([slot_on(first+dt.timedelta(days=i)).hour for i in range(7)],
                         [18,18,18,18,17,18,18])
        self.assertIsNone(reserved_kind(dt.date(2026,12,20)))

    def test_hiver_ete(self):
        for day,utc_hour in [(dt.date(2026,11,27),16),(dt.date(2027,7,2),15)]:
            self.assertEqual(target_date_time(day).astimezone(dt.timezone.utc).hour,utc_hour)
        self.assertEqual(mardi_suivant(dt.datetime(2026,11,26,10,tzinfo=PARIS)),
                         '2026-12-01T17:00:00.000Z')

    def test_arbitrage_bd_identique(self):
        now=dt.datetime(2026,11,27,16,20,tzinfo=PARIS)
        self.assertEqual(planned_slots('BD',now),['2026-12-04T16:00:00.000Z'])

    def test_mensuel_pas_de_troisieme_dimanche(self):
        self.assertEqual(monthly_slot(2026,11,dt.datetime(2026,12,1,tzinfo=PARIS)),
                         '2026-12-13T17:00:00.000Z')
        with self.assertRaises(ValueError):
            monthly_slot(2026,11,dt.datetime(2026,12,14,tzinfo=PARIS))
        self.assertEqual(next_slot({'cadence':'MENSUEL','annee':2026,'mois':12},
                         now=dt.datetime(2027,1,2,tzinfo=PARIS)), '2027-01-10T17:00:00.000Z')

    def test_categorie_et_heure_refusees(self):
        now=dt.datetime(2026,12,1,9,tzinfo=PARIS)
        with self.assertRaises(ValueError):validate_slot('BD','2026-12-01T17:00:00Z',now=now)
        with self.assertRaises(ValueError):validate_slot('MANGA','2026-12-01T16:00:00Z',now=now)
        self.assertEqual(eligible(dt.date(2026,12,1),now,[]),(True,'PROVISOIRE_TOP'))
        self.assertFalse(eligible(dt.date(2026,12,1),now,[{}])[0])

    def test_creneau_fige_et_expiration(self):
        due='2026-12-01T17:00:00.000Z'
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'plan.json';p.write_text(json.dumps({'slots':[due]}))
            with patch.dict(os.environ,{'ILLYADERA_SLOT_PLAN':str(p)}):
                now=dt.datetime(2026,12,1,10,tzinfo=PARIS)
                self.assertEqual(frozen_slot('MANGA','2026-12-08T17:00:00.000Z',now=now),due)
                self.assertEqual(assert_arbitrated('MANGA',due,now=now),due)
                with self.assertRaises(RuntimeError):
                    assert_arbitrated('MANGA','2026-12-08T17:00:00.000Z',now=now)
                with self.assertRaises(ValueError):
                    frozen_slot('MANGA','2026-12-08T17:00:00.000Z',now=dt.datetime(2026,12,1,17,30,tzinfo=PARIS))

if __name__=='__main__':unittest.main()
