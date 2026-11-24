"""Tests des règles de diffusion MANGA 70/100, entièrement hors ligne."""
from __future__ import annotations
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from manga_score_publication import evaluer, ean_valide
from manga_buffer_auto import construire

EANS=('9782749958200','9791042021870','9791043311772','9782344071120',
      '9782505144656','9791043306617','9791043301445')


def jeu(n_unknown=46,n_non=9,missing_cover=False):
    livres=[{'rang':i+1,'rang_general_livres':i+1,'ean':ean,
             'preuve_genre':'ean_identifie','titre':f'Manga {i+1}'} for i,ean in enumerate(EANS)]
    details=[]
    for i in range(n_non):
        details.append({'rang_general_livres':i+8,'ean':f'non-{i}', 'statut':'NON_MANGA'})
    for i in range(n_unknown):
        details.append({'rang_general_livres':i+40,'ean':f'inconnu-{i}', 'statut':'INCERTAIN'})
    data={'categorie':'MANGA','debut_ventes':'2026-11-09','fin_ventes':'2026-11-15',
       'date_publication':'2026-11-20', 'url_source':'https://actualitte.com/article/135341/meilleures-ventes/test',
       'certification':'A_VERIFIER','titres':livres}
    proof={'articles_dans_top200':200,'date_palmares_bede':'20/11/2026',
        'periode_ventes':['2026-11-09','2026-11-15'],
        'audit_genre':{'avant_septieme_examines':len(details),'details':details}}
    covers=[{'ean':ean,'rang':i+1,'ok':True} for i,ean in enumerate(EANS)]
    if missing_cover:covers[-1]['ok']=False
    return data,proof,covers


class Publication70Tests(unittest.TestCase):
    def test_ean(self):
        self.assertTrue(all(ean_valide(e) for e in EANS))
        self.assertFalse(ean_valide('9782749958201'))

    def test_meme_structure_que_le_rapport_reel_autorisee_en_reconstitution(self):
        data,proofs,covers=jeu()
        quality=evaluer(data,proofs,covers)
        self.assertEqual(quality['valeur'],77.74)
        self.assertTrue(quality['autorise_publication'])
        self.assertEqual(quality['mode'],'RECONSTITUE')
        self.assertEqual(quality['ouvrages_avant_top7_non_qualifies'],46)
        self.assertEqual(quality['taux_ouvrages_qualifies'],25.81)

    def test_incertain_trop_nombreux_interdit(self):
        data,proofs,covers=jeu(n_unknown=100,n_non=0)
        r=evaluer(data,proofs,covers)
        self.assertFalse(r['autorise_publication'])
        self.assertLess(r['taux_ouvrages_qualifies'],20)

    def test_couverture_absente_interdit(self):
        data,proofs,covers=jeu(missing_cover=True)
        self.assertFalse(evaluer(data,proofs,covers)['autorise_publication'])

    def test_incoherence_source_interdit(self):
        data,proofs,covers=jeu()
        proofs['articles_dans_top200']=199
        self.assertFalse(evaluer(data,proofs,covers)['autorise_publication'])

    def test_ean_de_genre_inconnu_invalide_interdit(self):
        data,proofs,covers=jeu()
        data['titres'][0]['ean']='9782749958201'
        self.assertFalse(evaluer(data,proofs,covers)['autorise_publication'])

    def test_buffer_refuse_une_reconstitution_sans_mention_legende(self):
        data,proofs,covers=jeu()
        score=evaluer(data,proofs,covers)
        data['qualite_editoriale']=score
        with tempfile.TemporaryDirectory() as temp:
            dossier=Path(temp)/'MANGA_2026-11-15'; folder=dossier/'MANGA';folder.mkdir(parents=True)
            (dossier/'classement_manga.json').write_text(json.dumps(data),encoding='utf8')
            (dossier/'preuves_manga.json').write_text(json.dumps(proofs),encoding='utf8')
            (folder/'AUDIT_COUVERTURES.json').write_text(json.dumps({'controles':covers}),encoding='utf8')
            slides=[f'{i:02d}_rang_{8-i}.png' for i in range(1,8)]+['08_recapitulatif.png']
            for f in slides:Image.new('RGB',(1080,1350),(255,255,255)).save(folder/f)
            m={'category':'MANGA','ready_to_stage':True,'qualite_editoriale':score,
               'mode_publication':'RECONSTITUE','pages':slides,'caption_file':'legende_instagram.txt'}
            (folder/'post_manifest.json').write_text(json.dumps(m),encoding='utf8')
            (folder/'legende_instagram.txt').write_text('📚 TOP 7 MANGA — non certifié\\nVENTES DU 09/11 AU 15/11/2026')
            with self.assertRaisesRegex(ValueError,'Mention de reconstitution'):
                construire(folder,'https://raw.githubusercontent.com/a/b/main/x/','canal',
                           now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))
            (folder/'legende_instagram.txt').write_text(
                '📚 TOP 7 MANGA — Classement reconstitué\\nVENTES DU 09/11 AU 15/11/2026\\nClassement incomplet')
            payload=construire(folder,'https://raw.githubusercontent.com/a/b/main/x/','canal',
                           now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))
            self.assertEqual(len(payload['assets']),8)

if __name__=='__main__':unittest.main()
