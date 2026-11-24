"""Tests de non-régression: sources, éditions, rendu, Buffer et sécurité."""
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from zoneinfo import ZoneInfo

import comics_sources_hebdo as source
import comics_pipeline_auto as pipeline
import comics_score_publication as scoring
import comics_buffer_auto as buffer

NOW=dt.datetime(2026,11,24,12,0,tzinfo=ZoneInfo('Europe/Paris'))
TITLES=[('Absolute Wonder Woman Tome 3','Urban Comics'),
        ('Absolute Superman Tome 3','Urban Comics'),
        ('Absolute Batman Tome 1','Urban Comics'),
        ('Absolute Batman Tome 2','Urban Comics'),
        ('Absolute Flash Tome 3','Urban Comics'),
        ('X-Men Elsewhen Tome 1','Huginn & Muninn'),
        ('Absolute Batman Tome 3','Urban Comics')]

def html_fnac(titles=TITLES):
    body='<h1>Meilleures ventes Comics</h1>'
    for i,(name,publisher) in enumerate(titles,1):
        body+=f'''<article class="Article-item"><a href="/a{10000+i}">
        <img alt="{name}" src="https://static.fnac-static.com/{i}.jpg" />{name}</a>
        <p>Type Comics</p><p>Format cartonné</p><p>Editeur {publisher}</p>
        <p>Parution 13/11/2026</p></article>'''
    return '<html><body>'+body+'</body></html>'

class ComicsSourceTests(unittest.TestCase):
    def test_fnac_reel_ordre_7_comics(self):
        rows=source.parse_fnac(html_fnac())
        self.assertEqual([x['rang_enseigne'] for x in rows],list(range(1,8)))
        self.assertEqual(rows[0]['titre'],TITLES[0][0])
    def test_fnac_manga_ou_bd_exclus(self):
        html=html_fnac([('Godspeed - comics 4/4','Paquet Eds')]+TITLES)
        rows=source.parse_fnac(html)
        self.assertEqual(len(rows),7)
        self.assertNotIn('Godspeed',str(rows))
    def test_fnac_manquant_bloque(self):
        with self.assertRaises(source.CollectError):source.parse_fnac(html_fnac(TITLES[:6]))
    def test_title_heading_bloque(self):
        with self.assertRaises(source.CollectError):source.parse_fnac(html_fnac().replace('Meilleures ventes Comics','Promotions nouveautés'))
    def test_source_releve_pareto(self):
        data,proof=source.build_candidate(fnac_html=html_fnac(),now=NOW)
        self.assertEqual(data['mode_interne'],'RELEVE_ENSEIGNE')
        self.assertNotIn('fin_ventes',data)  # aucune période de ventes inventée
        self.assertEqual(len(data['titres']),7)
        self.assertEqual(data['edition'],'COMICS_2026-11-29')
    def test_date_week_bounds(self):
        self.assertEqual(source.week_bounds(dt.date(2026,11,24)),('2026-11-23','2026-11-29'))
    def test_rejet_url_cover(self):
        self.assertFalse(source.validate_cover_url('http://static.fnac-static.com/test.jpg'))
        self.assertFalse(source.validate_cover_url('https://attacker.org/test.jpg'))
    def test_rejet_url_collecte(self):
        with self.assertRaises(source.CollectError):source.fetch('https://example.com')
    def test_mdcu_mauvais_titre(self):
        with self.assertRaises(source.CollectError):source.parse_mdcu_top('<h1>Best comics France</h1>')

class ComicsQualityTests(unittest.TestCase):
    def setUp(self):
        self.data,self.proofs=source.build_candidate(fnac_html=html_fnac(),now=NOW)
        self.covers=[{'ok':True,'rang':i} for i in range(1,8)]
    def test_score_releve_plus_de_70(self):
        result=scoring.calculer(self.data,self.proofs,self.covers,today=NOW.date())
        self.assertTrue(result['autorise_publication'])
        self.assertGreaterEqual(result['valeur'],70)
        self.assertIn('pas',result['limite'].lower())
    def test_couverture_absente_interdit(self):
        self.covers[1]['ok']=False
        self.assertFalse(scoring.calculer(self.data,self.proofs,self.covers,today=NOW.date())['autorise_publication'])
    def test_donnees_incompletes_interdit(self):
        self.data['titres']=self.data['titres'][:-1]
        self.assertFalse(scoring.calculer(self.data,self.proofs,self.covers,today=NOW.date())['autorise_publication'])
    def test_releve_trop_ancien_interdit(self):
        self.assertFalse(scoring.calculer(self.data,self.proofs,self.covers,today=dt.date(2026,12,5))['autorise_publication'])
    def test_mouvement_sans_precedent(self):
        pipeline.update_previous(self.data,None)
        self.assertFalse(self.data['variations_verifiees'])
    def test_mouvement_semaine_prec(self):
        prev=json.loads(json.dumps(self.data))
        prev['semaine_reference']=['2026-11-16','2026-11-22']
        prev['titres'][0]['rang']=3
        pipeline.update_previous(self.data,prev)
        self.assertEqual(self.data['titres'][0]['mouvement'],'+2 PL.')
    def test_pas_mouvement_mode_different(self):
        prev=json.loads(json.dumps(self.data));prev['mode_interne']='NATIONAL_HEBDO'
        prev['semaine_reference']=['2026-11-16','2026-11-22']
        pipeline.update_previous(self.data,prev)
        self.assertFalse(self.data['variations_verifiees'])

class ComicsPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.base=Path(cls.tmp.name)
        def covers(data,folder):
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            for book in data['titres']:
                Image.new('RGB',(270,400),'white').save(pipeline.cover_path(folder,book['titre']))
            return [{'rang':b['rang'],'ok':True,'origine':'fixture'} for b in data['titres']]
        cls.out=pipeline.produire(output=cls.base/'out',previous=cls.base/'previous.json',
            fnac_html=html_fnac(),now=NOW,covers=covers)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_manifest_et_huit_png(self):
        state=json.loads((self.out/'ETAT.json').read_text())
        self.assertTrue(state['pret_buffer'])
        folder=self.out/'COMICS';m=json.loads((folder/'post_manifest.json').read_text())
        self.assertEqual(len(m['pages']),8)
        self.assertEqual(m['pages'][0],'01_rang_7.png')
        self.assertEqual(m['pages'][-1],'08_recapitulatif.png')
        for p in m['pages']:
            with Image.open(folder/p) as im:self.assertEqual(im.size,(1080,1350))
    def test_aucun_nom_source_public(self):
        folder=self.out/'COMICS';s=(folder/'legende_instagram.txt').read_text()
        self.assertNotIn('Edistat',s);self.assertNotIn('Fnac',s)
        self.assertIn('Classement relevé le 24/11/2026',s)
        self.assertNotIn('Ventes DU',s)
    def test_manifest_score_interne(self):
        m=json.loads((self.out/'COMICS'/'post_manifest.json').read_text())
        self.assertGreaterEqual(m['qualite_editoriale']['valeur'],70)
        self.assertTrue(m['ready_to_stage'])
    def test_buffer_payload_sans_envoi(self):
        folder=self.out/'COMICS';base='https://raw.githubusercontent.com/user/public/main/public_media/COMICS_2026-11-29/COMICS_abc/'
        payload=buffer.construire(folder,base,'channel-test',now=NOW)
        self.assertEqual(len(payload['assets']),8)
        self.assertTrue(payload['dueAt'].startswith('2026-11-26T17:00:00'))
        self.assertNotIn('Fnac',payload['text'])
    def test_ne_change_pas_images_manga_bd(self):
        for x in ('manga_pipeline_auto.py','visual_top7.py','buffer_client.py'):
            self.assertTrue((Path(pipeline.__file__).parent/x).exists())

class ComicsBufferTests(unittest.TestCase):
    def test_prochain_jeudi_hiver(self):
        self.assertEqual(buffer.next_comics_slot(now=NOW),'2026-11-26T17:00:00.000Z')
    def test_prochain_jeudi_ete(self):
        date=dt.datetime(2026,6,16,12,tzinfo=dt.timezone.utc)
        self.assertEqual(buffer.next_comics_slot(now=date),'2026-06-18T16:00:00.000Z')
    def test_header_ne_recupere_pas_manga(self):
        self.assertIsNone(buffer.HEADER.match('TOP 7 MANGA'))
        self.assertIsNotNone(buffer.HEADER.match('📚 TOP 7 COMICS — Les meilleures ventes'))
    def test_source_interdite(self):
        self.assertIsNotNone(buffer.PUBLIC_SOURCE.search('Source: Edistat'))
        self.assertIsNotNone(buffer.PUBLIC_SOURCE.search('Fnac'))
    def test_buffer_receipt_idempotence(self):
        folder=Path(tempfile.gettempdir())/'comics_idempotence_test_placeholder'
        folder.mkdir(exist_ok=True)
        (folder/'post_manifest.json').write_text(json.dumps({'edition':'COMICS_2026-11-29'}))
        base='https://raw.githubusercontent.com/user/public/main/public_media/COMICS_2026-11-29/COMICS_abcd/'
        with patch.object(buffer,'construire',return_value={'text':'TOP 7 COMICS','dueAt':'2026-11-26T17:00:00.000Z','assets':[]}),\
             patch.object(buffer,'_listed',return_value=[]):
            # Reçu existant, échéance passée: pas de nouvel appel API, pas de doublon.
            with tempfile.TemporaryDirectory() as d:
                receipt=Path(d)/'prior.json'
                receipt.write_text(json.dumps({'statut':'POST_PROGRAMME','edition':'COMICS_2026-11-29',
                 'id_buffer':'123','date_programmee_utc':'2026-11-24T10:00:00.000Z'}))
                result=buffer.transmettre(folder,base,api_key='fake',channel_id='channel',send=True,
                    now=NOW,previous_receipt=receipt)
                self.assertEqual(result['action'],'DEJA_TRANSMIS_NON_MODIFIABLE')

if __name__=='__main__':unittest.main()

class ComicsBufferMockApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        (self.folder/'post_manifest.json').write_text(json.dumps({'edition':'COMICS_2026-11-29'}))
        self.base='https://raw.githubusercontent.com/org/repo/main/public_media/comics/'
        self.due='2026-11-26T17:00:00.000Z'
        self.payload={'text':'📚 TOP 7 COMICS — Les meilleures ventes\n📅 Classement relevé le 24/11/2026',
            'dueAt':self.due,'assets':[{'image':{'url':self.base+'1.png'}}],
            'channelId':'channel-comics','metadata':{'instagram':{'type':'post','shouldShareToFeed':True}}}
        class ImageResponse:
            headers={'Content-Type':'image/png'}
            def raise_for_status(self):pass
            def close(self):pass
        self.get=lambda *a,**k:ImageResponse()
    def tearDown(self):self.temp.cleanup()
    def test_api_creer_post_et_recu(self):
        def graphql(post,key,query,variables=None):
            self.assertIn('createPost',query)
            return {'createPost':{'post':{'id':'comic-42','status':'scheduled','dueAt':self.due}}}
        with patch.object(buffer,'construire',return_value=self.payload), \
            patch.object(buffer,'_listed',return_value=[]), \
            patch.object(buffer,'_graphql',side_effect=graphql):
            r=buffer.transmettre(self.folder,self.base,api_key='fake',channel_id='channel-comics',
                 send=True,now=NOW,post=lambda *a,**k:None,get=self.get)
        self.assertEqual(r['id_buffer'],'comic-42')
        self.assertEqual(r['action'],'CREATION')
        self.assertTrue((self.folder/'RECU_BUFFER.json').is_file())
    def test_api_modifier_sans_changer_le_creneau(self):
        receipt=self.folder/'prior.json'
        receipt.write_text(json.dumps({'statut':'POST_PROGRAMME','edition':'COMICS_2026-11-29',
           'id_buffer':'comic-original','date_programmee_utc':self.due}))
        existing=[{'id':'comic-original','dueAt':self.due,'status':'scheduled',
                   'channelId':'channel-comics','text':'📚 TOP 7 COMICS — ancien'}]
        def graphql(post,key,query,variables=None):
            self.assertIn('editPost',query)
            self.assertEqual(variables['input']['dueAt'],self.due)
            return {'editPost':{'post':{'id':'comic-original','status':'scheduled','dueAt':self.due}}}
        with patch.object(buffer,'construire',return_value=self.payload),\
             patch.object(buffer,'_listed',return_value=existing),\
             patch.object(buffer,'_graphql',side_effect=graphql):
            r=buffer.transmettre(self.folder,self.base,api_key='fake',channel_id='channel-comics',
                send=True,previous_receipt=receipt,now=NOW,get=self.get)
        self.assertEqual(r['action'],'MISE_A_JOUR')
        self.assertEqual(r['id_buffer'],'comic-original')
    def test_exige_post_comics_pas_bd(self):
        self.assertFalse(buffer.HEADER.match('📚 TOP 7 BD'))
        self.assertFalse(buffer.HEADER.match('📚 TOP 7 MANGA'))
