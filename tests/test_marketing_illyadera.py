import unittest
import datetime as dt
from marketing_illyadera import summarize,cta,tags
class MarketingTests(unittest.TestCase):
    def test_missing(self):
        now=dt.datetime(2026,11,28,tzinfo=dt.timezone.utc)
        r=summarize([],now)
        self.assertEqual(r['status'],'AUCUNE_MESURE_EXPLOITABLE')
        self.assertEqual(r['formats']['ANECDOTE']['cta'],'comment')
    def test_real_signal(self):
        now=dt.datetime(2026,11,28,tzinfo=dt.timezone.utc)
        p=[{'id':str(i),'text':'📚 ANECDOTE DU 9e ART','dueAt':'2026-11-24T17:00:00Z','metrics':[{'type':k,'value':v} for k,v in [('reach',1000),('shares',40),('saves',10),('comments',5)]]} for i in range(4)]
        r=summarize(p,now)
        self.assertEqual(r['status'],'MESURES_DISPONIBLES')
        self.assertEqual(r['formats']['ANECDOTE']['cta'],'share')
        self.assertIn('Partage',cta('ANECDOTE',policy=r))
        self.assertEqual(len(tags('ACTUS').split()),5)
    def test_small_sample(self):
        now=dt.datetime(2026,11,28,tzinfo=dt.timezone.utc)
        r=summarize([{'id':'1','text':'📚 ANECDOTE DU 9e ART','dueAt':'2026-11-24T17:00:00Z','metrics':[{'type':'reach','value':1000},{'type':'shares','value':90}]}],now)
        self.assertEqual(r['formats']['ANECDOTE']['cta'],'comment')
