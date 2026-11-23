"""Tests du mode maquette, sans réseau ni Buffer."""
import unittest
from maquette_manga_v4 import choisir_candidats, palmares_date


class MaquetteMangaV4Tests(unittest.TestCase):
    def setUp(self):
        self.v = {'categorie':'MANGA','publication_manga_autorisee':False,
                  'date_palmares_bede':'20/11/2026',
                  'candidats_non_certifies':[
                     {'rang_manga_provisoire':n,'rang_classement_mixte':n*2,
                      'titre':f'Exemple Manga {n} - Éditeur {n}'} for n in range(1,8)]}
        self.e = {'categorie':'MANGA','publication_manga_autorisee':False}
        self.a = {'categorie':'MANGA','sources':[{'source':'bede_bd_manga',
                  'inspection':{'date_palmares_affichee':'20/11/2026'}}]}

    def test_sept_rangs_non_certifies(self):
        result = choisir_candidats(self.v, self.e)
        self.assertEqual(len(result),7)
        self.assertEqual(result[0]['rang_mixte'],2)
        self.assertEqual(result[-1]['editeur_indicatif'],'Éditeur 7')

    def test_refuse_liste_incomplete(self):
        self.v['candidats_non_certifies'] = self.v['candidats_non_certifies'][:6]
        with self.assertRaises(ValueError):choisir_candidats(self.v,self.e)

    def test_refuse_dates_contradictoires(self):
        self.a['sources'][0]['inspection']['date_palmares_affichee']='21/11/2026'
        with self.assertRaises(ValueError):palmares_date(self.v,self.a)

    def test_distingue_date_palmares_et_ventes(self):
        self.assertEqual(palmares_date(self.v,self.a),'20/11/2026')

    def test_refuse_changement_autorisation(self):
        self.e['publication_manga_autorisee']=True
        with self.assertRaises(ValueError):choisir_candidats(self.v,self.e)

    def test_refuse_rangs_mixtes_inverses(self):
        self.v['candidats_non_certifies'][4]['rang_classement_mixte'] = 5
        with self.assertRaises(ValueError):choisir_candidats(self.v,self.e)


if __name__=='__main__':unittest.main()
