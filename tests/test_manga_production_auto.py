"""Tests hors ligne : les sept titres, le moteur graphique et Buffer simulé."""
import datetime as dt
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

from manga_qualite import _genre_from_tokens,auditer
from manga_pipeline_auto import produire, compute_movements
from manga_buffer_auto import construire, mardi_suivant, transmettre
from sources.couvertures import cover_path

# Fixtures existantes dans la précédente extension, 100 % fictives.
from test_manga_sources_hebdo import article,bede

ROOT=Path(__file__).resolve().parents[1]


def complet(row):
    return {'statut':'NON_MANGA','raison':'roman confirmé par ISBN', 'sources':[{'source':'fixture','statut':'NON_MANGA'}]}


def images_temoin(data,directory):
    directory.mkdir(parents=True,exist_ok=True)
    for book in data['titres']:
        Image.new('RGB',(450,680),(242,242,240)).save(cover_path(directory,book['titre']))
    return [{'rang':x['rang'],'ok':True,'origine':'couverture-fictive-test'} for x in data['titres']]


class MangaProductionTests(unittest.TestCase):
    def test_google_books_roman_vs_manga(self):
        self.assertEqual(_genre_from_tokens(['Fiction / Romance'])[0],'NON_MANGA')
        self.assertEqual(_genre_from_tokens(['Comics & Graphic Novels / Manga'])[0],'MANGA')
        self.assertEqual(_genre_from_tokens(['Comics & Graphic Novels'])[0],'INCERTAIN')
        self.assertEqual(_genre_from_tokens([])[0],'INCERTAIN')

    def test_inconnu_bloque_publication(self):
        d={'categorie':'MANGA','titres':[{'ean':str(i),'rang':i,'rang_general_livres':i*3,'mouvement':'NON DOCUMENTÉ'} for i in range(1,8)]}
        p={'titres_anterieurs_sans_preuve_genre':[{'ean':'X','rang_general_livres':2,'titre_article':'Inconnu'}]}
        d,p,_=auditer(d,p,resolver=lambda r:{'statut':'INCERTAIN','raison':'metadata absentes'})
        self.assertEqual(d['certification'],'A_VERIFIER')
        self.assertFalse(d['controle_genre_complet'])

    def test_manga_oublie_est_reclasse_automatiquement(self):
        d={'categorie':'MANGA','titres':[{'ean':str(i),'rang':i,'rang_general_livres':i*10,'mouvement':'NON DOCUMENTÉ'} for i in range(1,8)]}
        p={'titres_anterieurs_sans_preuve_genre':[{'ean':'9781111111111','rang_general_livres':3,'titre_article':'Manga inattendu'},
                                                  {'ean':'9782222222222','rang_general_livres':9,'titre_article':'Roman'}]}
        def resolve(b):
            return {'statut':'MANGA' if 'Manga' in b['titre_article'] else 'NON_MANGA', 'raison':'notice ISBN'}
        d,p,_=auditer(d,p,resolver=resolve)
        self.assertEqual(d['certification'],'TOP7_EDISTAT_VERIFIE')
        self.assertEqual(d['titres'][0]['titre'],'Manga inattendu')
        self.assertEqual([b['rang'] for b in d['titres']],list(range(1,8)))
        self.assertEqual(len(d['titres']),7)

    def test_pas_de_fleches_avec_ancien_classement_incertain(self):
        d={'debut_ventes':'2026-11-16','titres':[{'ean':'x','rang':1,'mouvement':'+4 PL.'}]}
        p={'fin_ventes':'2026-11-15','certification':'A_VERIFIER','titres':[{'ean':'x','rang':5}]}
        compute_movements(d,p)
        self.assertFalse(d['variations_verifiees'])
        self.assertEqual(d['titres'][0]['mouvement'],'NON DOCUMENTÉ')

    def test_production_complete_en_maquette_et_buffer_simule(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            shutil.copy2(ROOT/'editions_manga_v5.json',root/'editions_manga_v5.json')
            folder=produire(root=root,sortie=root/'sorties',precedent=root/'pas_de_precedent.json',
                   cache=root/'pas_de_cache.json',html_actualitte=article(),html_bede=bede(),
                   html_annuel='',resolver=complet,covers=images_temoin)
            s=json.loads((folder/'ETAT.json').read_text())
            self.assertEqual(s['statut_ventes'],'TOP7_EDISTAT_VERIFIE')
            self.assertTrue(s['pret_buffer'])
            self.assertEqual(s['pages'],8)
            self.assertEqual(len(list((folder/'MANGA').glob('0?_*.png'))),8)
            out=construire(folder/'MANGA','https://raw.githubusercontent.com/test/repo/main/public_media/MANGA_2026-11-15/MANGA/',
                           'instagram-test',now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))
            self.assertFalse(out['needsApproval'])
            self.assertEqual(len(out['assets']),8)
            self.assertEqual(out['mode'],'customScheduled')
            self.assertEqual(out['dueAt'],'2026-11-24T17:00:00.000Z')
            # Buffer ne doit pas être appelé lors d'une simulation.
            simulated=transmettre(folder/'MANGA','https://raw.githubusercontent.com/test/repo/main/public_media/MANGA_2026-11-15/MANGA/',
                                  api_key='',channel_id='instagram-test',send=False,
                                  now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))
            self.assertEqual(simulated['statut'],'SIMULATION')
            self.assertFalse((folder/'MANGA'/'RECU_BUFFER.json').exists())

    def test_buffer_detecte_une_edition_deja_programmee_sans_nouvel_envoi(self):
        import manga_buffer_auto as m
        due='2026-11-24T17:00:00.000Z'
        caption='📚 TOP 7 MANGA — VENTES DU 09/11 AU 15/11/2026'
        payload={'text':caption,'dueAt':due,'assets':[{'image':{'url':'https://raw.githubusercontent.com/x/y/main/a.png'}}],
                 'channelId':'c'}
        class ImageResponse:
            headers={'Content-Type':'image/png'}
            def raise_for_status(self):pass
            def close(self):pass
        existing=[{'id':'buffer-123','status':'scheduled','channelId':'c','text':caption,'dueAt':due}]
        with tempfile.TemporaryDirectory() as td, \
             patch.object(m,'construire',return_value=payload), \
             patch.object(m,'_list_manga_programmes',return_value=existing):
            send=lambda *a,**k: (_ for _ in ()).throw(AssertionError('mutation Buffer interdite'))
            a=m.transmettre(Path(td),'https://raw.githubusercontent.com/x/y/main/',api_key='dummy',
                channel_id='c',send=True,post=send,get=lambda *a,**kw:ImageResponse())
            self.assertEqual(a['action'],'DEJA_PROGRAMME')
            b=m.transmettre(Path(td),'https://raw.githubusercontent.com/x/y/main/',api_key='dummy',
                channel_id='c',send=True,post=send,get=lambda *a,**kw:ImageResponse())
            self.assertEqual(a,b)

    def test_aucun_buffer_pour_donnees_non_certifiees(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shutil.copy2(ROOT/'editions_manga_v5.json',root/'editions_manga_v5.json')
            folder=produire(root=root,sortie=root/'sorties',precedent=root/'pas_de_precedent.json',
                   cache=root/'pas_de_cache.json',html_actualitte=article(),html_bede=bede(),
                   html_annuel='',resolver=lambda r:{'statut':'INCERTAIN','raison':'pas de genre'},
                   covers=images_temoin)
            state=json.loads((folder/'ETAT.json').read_text())
            self.assertFalse(state['pret_buffer'])
            with self.assertRaisesRegex(ValueError,'pas suffisamment vérifié'):
                construire(folder/'MANGA','https://raw.githubusercontent.com/test/repo/main/public_media/x/MANGA/',
                           'instagram-test',now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))

if __name__=='__main__':unittest.main()
