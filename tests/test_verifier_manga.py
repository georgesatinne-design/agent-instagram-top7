import json
import tempfile
import unittest
from pathlib import Path
from verifier_manga import controle, normaliser, repertoire_manga, sauvegarder


def sample():
    noms = ["Lucky Luke T12", "Instinct - Tome 3", "Gaston T23", "Spy x Family T17", "Blake et Mortimer", "Les Vieux Fourneaux", "Ariol", "Atelier des Sorciers T16", "One Piece T113", "Kagurabachi T11", "Blue Lock T35", "Boruto Two Blue Vortex"]
    return {"categorie":"MANGA", "sources": [
        {"source":"edistat_top200", "accessible":False, "status_http":403},
        {"source":"actualitte_edistat", "accessible":True},
        {"source":"bede_bd_manga", "accessible":True,"url":"https://www.bede.fr/meilleures-ventes","inspection":{"date_palmares_affichee":"20/11/2026","rangs_manquants_jusqu_au_max":[], "premieres_entrees_a_verifier":[{"rang_bd_manga":i,"titre_affiche":t} for i,t in enumerate(noms,1)]}},
    ]}

class TestVerifierManga(unittest.TestCase):
    def test_lexique_protege_instinct_et_accents(self):
        self.assertTrue(repertoire_manga("Instinct - Tome 3"))
        self.assertTrue(repertoire_manga("L’Atelier des Sorciers T16"))
        self.assertFalse(repertoire_manga("Lucky Luke T12"))
        self.assertEqual(normaliser("Édition — T°2"), "edition t 2")

    def test_ne_jamais_certifier_top7_depuis_melange(self):
        x = controle(sample())
        self.assertFalse(x["top7_national_certifie"])
        self.assertFalse(x["publication_manga_autorisee"])
        self.assertEqual(x["action_buffer"], "AUCUNE")
        self.assertIn("Instinct", str(x["candidats_non_certifies"]))
        self.assertIn("403", str(x["alertes"]))

    def test_les_rangs_mixtes_ne_sont_pas_inventes(self):
        x = controle(sample())
        self.assertEqual(x["candidats_non_certifies"][0]["rang_classement_mixte"], 2)
        self.assertEqual(x["candidats_non_certifies"][1]["rang_classement_mixte"], 4)
        self.assertIsNone(x["periode_ventes_exacte"])
        self.assertTrue(x["indetermines_avant_7e"])

    def test_rapport_original_ne_change_pas(self):
        x = controle(sample())
        with tempfile.TemporaryDirectory() as d:
            sauvegarder(Path(d), x)
            self.assertTrue((Path(d)/"verification_manga.json").exists())
            self.assertFalse((Path(d)/"legende_instagram.txt").exists())
            self.assertFalse((Path(d)/"RECU_BUFFER.json").exists())
            data = json.loads((Path(d)/"verification_manga.json").read_text())
            self.assertFalse(data["publication_manga_autorisee"])

    def test_refuse_rapport_etranger(self):
        with self.assertRaises(ValueError):
            controle({"categorie":"BD", "sources":[]})

if __name__ == "__main__":
    unittest.main()
