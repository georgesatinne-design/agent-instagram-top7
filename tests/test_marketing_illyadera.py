import unittest
import datetime as dt
from marketing_illyadera import summarize,cta,tags,classify
from marketing_veille import counts
from marketing_experiences import evaluate,assignment,VARIANTS,variant
class MarketingTests(unittest.TestCase):
    def test_missing(self):
        now=dt.datetime(2026,11,28,tzinfo=dt.timezone.utc);r=summarize([],now)
        self.assertEqual(r['status'],'AUCUNE_MESURE_EXPLOITABLE')
        self.assertEqual(r['formats']['ANECDOTE']['cta'],'comment')
    def test_comparable(self):
        now=dt.datetime(2026,11,28,tzinfo=dt.timezone.utc)
        p=[{'id':str(i),'text':'📚 ANECDOTE DU 9e ART','dueAt':'2026-11-24T17:00:00Z','metrics':[{'type':k,'value':v} for k,v in [('reach',1000),('shares',40),('saves',10),('comments',5)]]} for i in range(4)]
        r=summarize(p,now)
        self.assertEqual(r['status'],'MESURES_DISPONIBLES')
        self.assertEqual(r['formats']['ANECDOTE']['cta'],'comment')
        self.assertEqual(r['formats']['ANECDOTE']['medianes_par_portee']['share'],.04)
        self.assertEqual(len(tags('ACTUS').split()),5)
        p[0]['metadata']={'type':'reel'}
        r=summarize(p,now);self.assertEqual(r['formats']['REEL']['echantillon'],1)
        self.assertEqual(r['formats']['ANECDOTE']['echantillon'],3)
        self.assertNotIn('share',r['formats']['ANECDOTE']['medianes_par_portee'])
    def test_experiment(self):
        self.assertEqual(assignment('2026-11-29')==assignment('2026-12-06'),False)
        self.assertEqual(variant(VARIANTS['A']+' 👇'),'A')
        self.assertIsNone(evaluate([('A',.01),('B',.09)])['choix'])
        self.assertEqual(evaluate([('A',.01)]*6+[('B',.03)]*6)['choix'],'B')
    def test_public_headings(self):
        n,f=counts('<nav><h2>Les 10 meilleurs titres manga</h2></nav><h2>Les meilleurs albums de la semaine</h2><h2>Interview avec un auteur de bande dessinée</h2>')
        self.assertEqual(n,2);self.assertEqual(f['selection'],1);self.assertEqual(f['entretien'],1)
