import datetime as dt
import json
import unittest
from calendrier import CALENDRIER, prochain_creneau

class TestCreneauBDVendredi17H(unittest.TestCase):
    def setUp(self):
        self.c=json.loads(CALENDRIER.read_text(encoding='utf-8'))

    def test_bd_active_vendredi_17h_paris(self):
        rule=self.c['publications']['BD']
        self.assertTrue(rule['active'])
        self.assertEqual((rule['jour'],rule['heure'],rule['frequence']),('vendredi','17:00','hebdomadaire'))
        self.assertEqual(self.c['preparation']['frequence'],'surveillance_horaire')
        self.assertEqual(self.c['mode_validation'],'programmation_automatique_en_queue')

    def test_hiver_proposition_24h_apres_preparation(self):
        now=dt.datetime(2026,11,26,16,0,tzinfo=dt.timezone.utc)  # jeudi 17 h Paris
        r=prochain_creneau('BD', now=now, configuration=self.c)
        self.assertEqual(r['date_heure_paris'],'2026-11-27T17:00:00+01:00')
        self.assertEqual(r['dueAt'],'2026-11-27T16:00:00.000Z')

    def test_ete_proposition_24h_apres_preparation(self):
        now=dt.datetime(2027,7,1,15,0,tzinfo=dt.timezone.utc)  # jeudi 17 h Paris
        r=prochain_creneau('BD', now=now, configuration=self.c)
        self.assertEqual(r['date_heure_paris'],'2027-07-02T17:00:00+02:00')
        self.assertEqual(r['dueAt'],'2027-07-02T15:00:00.000Z')

    def test_les_autres_categories_sont_inactives(self):
        for cat in ('MANGA','COMICS','QUOTIDIEN'):
            self.assertIsNone(prochain_creneau(cat,now=dt.datetime(2026,11,26,16,tzinfo=dt.timezone.utc),configuration=self.c))

    def test_publication_le_vendredi_si_l_edition_est_disponible_avant_17h(self):
        now=dt.datetime(2026,11,27,9,0,tzinfo=dt.timezone.utc)  # 10 h Paris vendredi : programmation aujourd'hui
        r=prochain_creneau('BD',now=now,configuration=self.c)
        self.assertEqual(r['date_heure_paris'],'2026-11-27T17:00:00+01:00')

    def test_classement_arrive_apres_heure_de_publication(self):
        now=dt.datetime(2026,11,27,16,55,tzinfo=dt.timezone.utc)  # vendredi 17:55 Paris
        r=prochain_creneau('BD',now=now,configuration=self.c)
        self.assertEqual(r['date_heure_paris'],'2026-12-04T17:00:00+01:00')

if __name__ == '__main__':
    unittest.main()
