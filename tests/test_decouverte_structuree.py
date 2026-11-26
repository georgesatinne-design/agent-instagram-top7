import datetime as dt
import tempfile
import unittest
from pathlib import Path
from anecdotes_auto.decouverte_structuree import fact_from_row,explicit_relation,scenes_for,enrich
from anecdotes_auto.catalogue import valid_fact,write
NOW=dt.datetime(2026,11,26,tzinfo=dt.timezone.utc)

def row():
    return {k:{'value':v} for k,v in {
        'item':'http://www.wikidata.org/entity/Q111','target':'http://www.wikidata.org/entity/Q222',
        'creator':'http://www.wikidata.org/entity/Q333','itemLabel':'Héros Exemple',
        'targetLabel':'Personne Exemple','creatorLabel':'Auteur Exemple','prop':'P138',
        'ref':'https://www.citebd.org/exemple'}.items()}
HTML="<main><p>Héros Exemple tire son nom de Personne Exemple.</p><p>Auteur Exemple a créé Héros Exemple.</p></main>"

class DiscoveryTests(unittest.TestCase):
    def test_deux_assertions_et_scenes(self):
        f=fact_from_row(row(),HTML,NOW)
        self.assertTrue(valid_fact(f))
        self.assertIn('Personne Exemple',f['fait'])
        self.assertEqual(len(scenes_for(f)),3)
        self.assertNotIn(HTML,f['preuve_courte'])

    def test_simple_cooccurrence_ne_suffit_pas(self):
        self.assertIsNone(fact_from_row(row(),'<p>Héros Exemple, Personne Exemple et Auteur Exemple.</p>',NOW))
        self.assertIsNone(fact_from_row(row(),'<p>Héros Exemple ne tire pas son nom de Personne Exemple.</p>',NOW))
        self.assertIsNone(fact_from_row(row(),'<p>Héros Exemple tire son nom de Personne Exemple.</p>',NOW))

    def test_domaine_non_autorise(self):
        r=row();r['ref']['value']='https://example.com'
        self.assertIsNone(fact_from_row(r,HTML,NOW))

    def test_reserve_suffisante_sans_requete(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'state';state.mkdir()
            write(root/'banque_initiale.json',{'faits':[{'id':str(i)} for i in range(30)]})
            class NoNetwork:
                def get(self,*a,**k):raise AssertionError('Réseau inutile')
            result=enrich(root=root,state=state,now=NOW,session=NoNetwork())
            self.assertEqual(result['statut'],'RESERVE_SUFFISANTE')

    def test_collecte_bornee_et_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'state';state.mkdir()
            calls=[]
            class Response:
                def raise_for_status(self):pass
                def json(self):return {'results':{'bindings':[row(),row()]}}
            class Session:
                def get(self,*a,**k):calls.append('index');return Response()
            def get_html(*a):calls.append('archive');return HTML
            result=enrich(root=root,state=state,now=NOW,session=Session(),fetch_html=get_html)
            self.assertEqual(result['nouveaux'],1)
            self.assertEqual(calls,['index','archive'])
            enrich(root=root,state=state,now=NOW,session=Session(),fetch_html=get_html)
            self.assertEqual(calls,['index','archive'])
if __name__=='__main__':unittest.main()
