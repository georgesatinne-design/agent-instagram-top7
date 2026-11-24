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

    def test_buffer_accepte_legende_sans_sources_et_refuse_edistat(self):
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
               'mode_publication':'RECONSTITUE','version_contenu':'manga_sans_sources_v1',
               'pages':slides,'caption_file':'legende_instagram.txt'}
            (folder/'post_manifest.json').write_text(json.dumps(m),encoding='utf8')
            (folder/'legende_instagram.txt').write_text(
               '📚 TOP 7 MANGA — Les meilleures ventes\n📅 Ventes DU 09/11 AU 15/11/2026\n\n#1 Manga')
            payload=construire(folder,'https://raw.githubusercontent.com/a/b/main/x/','canal',
                           now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))
            self.assertEqual(len(payload['assets']),8)
            self.assertNotIn('edistat',payload['text'].lower())
            self.assertNotIn('reconstitué',payload['text'].lower())
            (folder/'legende_instagram.txt').write_text(
              '📚 TOP 7 MANGA — Les meilleures ventes\n📅 Ventes DU 09/11 AU 15/11/2026\nSource Edistat')
            with self.assertRaisesRegex(ValueError,'nom de source'):
                construire(folder,'https://raw.githubusercontent.com/a/b/main/x/','canal',
                           now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))

    def test_meme_edition_corrigee_sans_dupliquer_ni_decaler_son_horaire(self):
        import manga_buffer_auto as m
        from unittest.mock import patch
        due='2026-11-24T17:00:00.000Z'
        old_caption='📚 TOP 7 MANGA — Classement reconstitué\n📅 Ventes DU 09/11 AU 15/11/2026\nEdistat'
        new_caption='📚 TOP 7 MANGA — Les meilleures ventes\n📅 Ventes DU 09/11 AU 15/11/2026'
        now=dt.datetime(2026,11,24,14,tzinfo=dt.timezone.utc)
        existing=[{'id':'buffer-conserve','status':'scheduled','channelId':'canal','text':old_caption,'dueAt':due}]
        # La fonction construire pourrait calculer un autre mardi : l'édition déjà
        # programmée conserve obligatoirement son horaire lors de la correction.
        payload={'text':new_caption,'dueAt':'2026-12-01T17:00:00.000Z',
                 'assets':[{'image':{'url':'https://raw.githubusercontent.com/test/repo/main/revision.png'}}],
                 'channelId':'canal','metadata':{'instagram':{'type':'post'}}}
        class ImageResponse:
            headers={'Content-Type':'image/png'}
            def raise_for_status(self):pass
            def close(self):pass
        seen=[]
        def fake_graphql(post,key,query,variables):
            seen.append(variables['input'])
            return {'editPost':{'post':{'id':'buffer-conserve','status':'scheduled','dueAt':due}}}
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            old_receipt=folder/'ancien.json'
            old_receipt.write_text(json.dumps({'edition':'MANGA_2026-11-15',
               'statut':'POST_PROGRAMME','id_buffer':'buffer-conserve','date_programmee_utc':due}),encoding='utf8')
            with patch.object(m,'construire',return_value=payload), \
                 patch.object(m,'_list_manga_programmes',return_value=existing), \
                 patch.object(m,'_graphql',side_effect=fake_graphql):
                res=m.transmettre(folder,'https://raw.githubusercontent.com/test/repo/main/',
                  api_key='dummy',channel_id='canal',send=True,
                  now=now,previous_receipt=old_receipt,
                  get=lambda *a,**kw:ImageResponse())
            self.assertEqual(res['action'],'CORRECTION_PROGRAMMEE')
            self.assertEqual(res['id_buffer'],'buffer-conserve')
            self.assertEqual(res['date_programmee_utc'],due)
            self.assertEqual(res['version_contenu'],'manga_sans_sources_v1')
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0]['dueAt'],due)
            self.assertIn('Les meilleures ventes',seen[0]['text'])
            # Deuxième passage : reçu déjà versionné, AUCUNE mutation API.
            with patch.object(m,'construire',return_value=payload), \
                 patch.object(m,'_graphql',side_effect=AssertionError('Aucun second appel Buffer')):
                again=m.transmettre(folder,'https://raw.githubusercontent.com/test/repo/main/',
                    api_key='dummy',channel_id='canal',send=True,now=now,
                    previous_receipt=folder/'RECU_BUFFER.json')
            self.assertEqual(again['id_buffer'],'buffer-conserve')

    def test_ne_jamais_republier_un_recu_dont_le_creneau_est_passe(self):
        import manga_buffer_auto as m
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            old=folder/'ancien.json'
            old.write_text(json.dumps({'edition':'MANGA_2026-11-15',
              'statut':'POST_PROGRAMME','id_buffer':'ancien-post',
              'date_programmee_utc':'2026-11-24T17:00:00.000Z'}))
            payload={'text':'📚 TOP 7 MANGA — Ventes DU 09/11 AU 15/11/2026',
                     'dueAt':'2026-12-01T17:00:00.000Z'}
            with patch.object(m,'construire',return_value=payload), \
                 patch.object(m,'_graphql',side_effect=AssertionError('Post expiré : aucun appel')):
                result=m.transmettre(folder,'https://raw.githubusercontent.com/test/repo/main/',
                  api_key='dummy',channel_id='canal',send=True,
                  now=dt.datetime(2026,11,24,17,1,tzinfo=dt.timezone.utc),previous_receipt=old)
            self.assertEqual(result['action'],'DEJA_TRANSMIS_NON_MODIFIABLE')

if __name__=='__main__':unittest.main()
