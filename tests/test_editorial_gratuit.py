import unittest
from anecdotes_auto.catalogue import bank
from anecdotes_auto.decouverte import editorial_links
from anecdotes_auto.storytelling import editorial_eligible, story
from anecdotes_auto.recherche_images import SCENES

class EditorialGratuitTests(unittest.TestCase):
    def test_nouvelles_anecdotes_documentees(self):
        facts={f['id']:f for f in bank()}
        for key in ('asterix-idefix-lecteurs','peanuts-spike-snoopy','peanuts-niche-incendie',
                    'astro-figurant-vedette','tintin-chromos-savoirs','yellowkid-guerre-journaux'):
            f=facts[key]
            self.assertTrue(editorial_eligible(f))
            self.assertTrue(f['url_source'].startswith('https://'))
            self.assertIn(key,SCENES)
            self.assertEqual(story(f)['revelation'],f['fait'])

    def test_metadonnees_commerciales_non_publiables(self):
        self.assertFalse(editorial_eligible({'id':'test-edition','theme':'EDITION',
                          'type_preuve':'METADONNEES_EDITEUR_OFFICIEL'}))

    def test_decouverte_piste_sans_invention(self):
        html='<a href="/fr/histoire">Les secrets de la création</a><a href="https://example.com/history">Histoire du personnage</a>'
        out=editorial_links(html,'https://www.tintin.com/fr/herge')
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]['statut'],'A_VERIFIER')
        self.assertNotIn('fait',out[0])

if __name__=='__main__':unittest.main()
