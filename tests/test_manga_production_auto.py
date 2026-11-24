"""Tests hors ligne : les sept titres, le moteur graphique et Buffer simulé."""
import datetime as dt
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image

from manga_qualite import _genre_from_tokens,auditer,bnf_isbn,genre_bede,catalog_status
from manga_pipeline_auto import produire, compute_movements
from manga_buffer_auto import construire, mardi_suivant, transmettre
from sources.couvertures import cover_path
from manga_sources_hebdo import classify_item

# Fixtures existantes dans la précédente extension, 100 % fictives.
from test_manga_sources_hebdo import article,bede

ROOT=Path(__file__).resolve().parents[1]


def complet(row):
    return {'statut':'NON_MANGA','raison':'roman confirmé par ISBN', 'sources':[{'source':'fixture','statut':'NON_MANGA'}]}


def images_temoin(data,directory):
    directory.mkdir(parents=True,exist_ok=True)
    for book in data['titres']:
        Image.new('RGB',(450,680),(242,242,240)).save(cover_path(directory,book['titre']))
    return [{'rang':x['rang'],'ean':x['ean'],'ok':True,'origine':'couverture-fictive-test'} for x in data['titres']]


class MangaProductionTests(unittest.TestCase):
    def test_titre_manga_nouveau_reconnu_dans_catalogue_source(self):
        row={'titre_article':'Manga totalement inédit Tome 42',
             'ean':'9799999999991','editeur_article':'Maison nouvelle'}
        bede=[{'alt':'Manga totalement inédit - Tome 42 - Maison nouvelle',
               'cover_url':'https://cdn.bede.fr/media/manga/inconnu.png'}]
        ok,title,why,_=classify_item(row,{},bede)
        self.assertTrue(ok)
        self.assertEqual(why,'bede_categorie_manga')
        bede[0]['cover_url']='https://cdn.bede.fr/media/albums/inconnu.png'
        self.assertFalse(classify_item(row,{},bede)[0])
        self.assertFalse(classify_item({'titre_article':'Instinct du mensonge',
            'ean':'9789999999999','editeur_article':'Flammarion'}, {}, [])[0])

    def test_bnf_sru_exact_isbn_and_subjects(self):
        isbn='9782080490896'
        xml=f'''<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/"
          xmlns:dc="http://purl.org/dc/elements/1.1/">
          <srw:numberOfRecords>1</srw:numberOfRecords><srw:records><srw:record>
          <srw:recordData><dc:identifier>ISBN {isbn}</dc:identifier>
          <dc:title>Un roman français</dc:title><dc:subject>Romans français</dc:subject>
          </srw:recordData></srw:record></srw:records></srw:searchRetrieveResponse>'''.encode()
        class Response:
            content=xml
            url='https://catalogue.bnf.fr/api/SRU'
            def raise_for_status(self):pass
        result=bnf_isbn(isbn,getter=lambda *a,**k:Response())
        self.assertEqual(result['statut'],'NON_MANGA')
        self.assertEqual(result['source'],'BnF catalogue général SRU')
        self.assertEqual(result['categories'],['Romans français'])
        bad=xml.replace(isbn.encode(),b'9782889880003')
        class Wrong(Response):content=bad
        self.assertEqual(bnf_isbn(isbn,getter=lambda *a,**k:Wrong())['statut'],'INCERTAIN')

    def test_politique_generale_ou_fiction_seule_ne_suffisent_pas(self):
        self.assertEqual(_genre_from_tokens(['Fiction'])[0],'INCERTAIN')
        self.assertEqual(_genre_from_tokens(['History'])[0],'INCERTAIN')
        self.assertEqual(_genre_from_tokens(['Manga'])[0],'MANGA')
        self.assertEqual(_genre_from_tokens(['Comics & Graphic Novels'])[0],'INCERTAIN')

    def test_bede_bd_precise_reconnue_mais_pas_album_ambigu(self):
        row={'titre_article':'Des Boum et des Paf','ean':'9782808513821'}
        lines=[{'alt':'Gaston Lagaffe - Tome 23 - Des Boum et des Paf - Dupuis',
                'cover_url':'https://cdn.bede.fr/box/208x285/media/albums/gaston.jpg'}]
        self.assertEqual(genre_bede(row,lines)['statut'],'NON_MANGA')
        lines[0]['alt']='Gaston Lagaffe - Tome 23 - Des Boum et des Paf - Marque inconnue'
        self.assertIsNone(genre_bede(row,lines))

    def test_classifier_interroge_bnf_en_repli(self):
        row={'ean':'9782080490896','titre_article':'L inconnue'}
        queried=[]
        def bnf(x):
            queried.append('bnf')
            return {'statut':'NON_MANGA','raison':'roman confirmé','source':'BnF'}
        result=catalog_status(row,
            google=lambda x:{'statut':'INCERTAIN','raison':'absent'},
            bnf=bnf,openlibrary=lambda x:{'statut':'INCERTAIN','raison':'absent'})
        self.assertEqual(queried,['bnf'])
        self.assertEqual(result['statut'],'NON_MANGA')

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

    def test_buffer_edition_deja_programmee_avec_recu_versionne_ne_renvoie_rien(self):
        import manga_buffer_auto as m
        due='2026-11-24T17:00:00.000Z'
        caption='📚 TOP 7 MANGA — VENTES DU 09/11 AU 15/11/2026'
        payload={'text':caption,'dueAt':due,'assets':[{'image':{'url':'https://raw.githubusercontent.com/x/y/main/a.png'}}],
                 'channelId':'c'}
        with tempfile.TemporaryDirectory() as td, patch.object(m,'construire',return_value=payload):
            folder=Path(td)
            receipt={'statut':'POST_PROGRAMME','edition':'MANGA_2026-11-15',
               'id_buffer':'buffer-123','date_programmee_utc':due,
               'version_contenu':m.VERSION_PUBLIQUE}
            (folder/'ancien.json').write_text(json.dumps(receipt),encoding='utf8')
            send=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Aucun appel Buffer autorise'))
            a=m.transmettre(folder,'https://raw.githubusercontent.com/x/y/main/',api_key='dummy',
                channel_id='c',send=True,post=send,
                now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc),
                previous_receipt=folder/'ancien.json')
            self.assertEqual(a['id_buffer'],'buffer-123')
            b=m.transmettre(folder,'https://raw.githubusercontent.com/x/y/main/',api_key='dummy',
                channel_id='c',send=True,post=send,
                now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc),
                previous_receipt=folder/'RECU_BUFFER.json')
            self.assertEqual(a,b)

    def test_trop_d_incertitudes_bloque_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);shutil.copy2(ROOT/'editions_manga_v5.json',root/'editions_manga_v5.json')
            folder=produire(root=root,sortie=root/'sorties',precedent=root/'pas_de_precedent.json',
                   cache=root/'pas_de_cache.json',html_actualitte=article(),html_bede=bede(),
                   html_annuel='',resolver=lambda r:{'statut':'INCERTAIN','raison':'pas de genre'},
                   covers=images_temoin)
            state=json.loads((folder/'ETAT.json').read_text())
            self.assertFalse(state['pret_buffer'])
            self.assertEqual(state['mode_publication'],'NON_AUTORISE')
            self.assertLess(json.loads((folder/'SCORE_PUBLICATION.json').read_text())['taux_ouvrages_qualifies'],20)
            with self.assertRaisesRegex(ValueError,'pas suffisamment vérifié'):
                construire(folder/'MANGA','https://raw.githubusercontent.com/test/repo/main/public_media/x/MANGA/',
                           'instagram-test',now=dt.datetime(2026,11,23,18,tzinfo=dt.timezone.utc))

if __name__=='__main__':unittest.main()
