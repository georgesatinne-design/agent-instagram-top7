import unittest
from anecdotes_auto.politique_editoriale import accepte
from anecdotes_auto.archives_institutionnelles import commons,safe,FACTS
class PolitiqueTests(unittest.TestCase):
    def test_rejet(self):
        for fid in ('bruxelles-horta','topffer-professeur','lucky-luke-morris','lucky-luke-goscinny'):
            self.assertFalse(accepte({'id':fid}))
        self.assertTrue(accepte({'id':'hokusai-manga-carnets'}))
    def test_commons(self):
        self.assertEqual(commons('Yellowkid phonograph.jpg'),'https://upload.wikimedia.org/wikipedia/commons/9/9b/Yellowkid_phonograph.jpg')
        self.assertTrue(safe(commons('Yellowkid phonograph.jpg')))
        self.assertFalse(safe('https://unknown.example/a.jpg'))
