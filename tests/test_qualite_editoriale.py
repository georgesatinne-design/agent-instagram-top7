import unittest
from anecdotes_auto.qualite_editoriale import score

class Tests(unittest.TestCase):
 def test_prefers_narrative_revelation_over_pagecount(self):
  vivid={'hook':"Et si l'auteur s'était caché dans sa BD ?", 'fait':"Hergé s'est dessiné dans ses albums.",
         'contexte':"On distingue sa silhouette à différentes occasions.",
         'detail':"Il apparaît au départ de Tintin pour le Congo.", 'theme':'COULISSES',
         'type_preuve':'SOURCE_PRIMAIRE_OFFICIELLE'}
  flat={'hook':'Un album, trois détails !','fait':'Cette édition comporte 64 pages.',
         'contexte':'Elle paraît le 15/05/2026.','detail':'La fiche indique le scénariste.',
         'theme':'EDITION','type_preuve':'METADONNEES_EDITEUR_OFFICIEL'}
  self.assertGreater(score(vivid),score(flat))
 def test_score_is_bounded(self):
  self.assertTrue(0 <= score({}) <= 100)
if __name__=='__main__':unittest.main()
