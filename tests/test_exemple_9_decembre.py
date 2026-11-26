import unittest
from anecdotes_auto.photos_reelles import _license,PhotosIndisponibles
from anecdotes_auto.exemple_9_decembre import matching,POST_ID,DUE
from anecdotes_auto.catalogue import bank
from anecdotes_auto.storytelling import editorial_eligible

class ExempleTests(unittest.TestCase):
    def test_archive_fermee(self):
        meta={'LicenseShortName':{'value':'Public domain'},'Artist':{'value':'Richard F. Outcault'}}
        self.assertIn('1928',_license(meta,'1896-11-08 Yellow Kid.jpg',{'archive_outcault_1896':True}))
        with self.assertRaises(PhotosIndisponibles):_license(meta,'unknown.jpg',{'archive_outcault_1896':True})
    def test_identite_exacte(self):
        p={'id':POST_ID,'dueAt':DUE,'status':'scheduled','text':'📚 ANECDOTE BD — exemple'}
        class B:
            def list_scheduled(self):return [p]
        self.assertEqual(matching(B(),{}),p)
        p['id']='un-autre'
        with self.assertRaises(RuntimeError):matching(B(),{})
    def test_fait_eligible(self):
        self.assertTrue(editorial_eligible(next(f for f in bank() if f['id']=='yellowkid-guerre-journaux')))
