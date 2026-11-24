"""V7: multi-source, rights, pertinence, stock et remplacement sous identifiant Buffer fixe.
No live HTTP request; test provider responses are deterministic fixtures.
"""
import datetime as dt
import hashlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image,ImageDraw
from anecdotes_auto import recherche_images as ri, catalogue, stock_images, photos_reelles, run


def photo(seed):
    rnd=random.Random(seed);img=Image.new('RGB',(880,630),'white');d=ImageDraw.Draw(img)
    for i in range(90):
        x=rnd.randrange(820);y=rnd.randrange(580)
        d.rectangle((x,y,x+rnd.randrange(4,60),y+rnd.randrange(4,35)),
                    fill=(rnd.randrange(250),rnd.randrange(250),rnd.randrange(250)))
    out=io.BytesIO();img.save(out,'JPEG',quality=86);return out.getvalue()


class DummyReply:
    def __init__(self,data,status=200):self.data=data;self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError(self.status_code)
    def json(self):return self.data

class SearchSession:
    def __init__(self,make_relevant=True):self.calls=[];self.make_relevant=make_relevant
    def get(self,url,params=None,headers=None,timeout=None,**kw):
        self.calls.append((url,params))
        if url==ri.COMMONS_API:
            q=params['gsrsearch']
            m=(len(self.calls)%5)+1
            if 'Angoulême' in q or 'Angouleme' in q:
                name=f'Angoulême Musée bande dessinée façade distincte {m} - photo.jpg' if self.make_relevant else f'Chat dans jardin {m}.jpg'
                return DummyReply({'query':{'pages':[
                  {'title':'File:'+name,'imageinfo':[{'mime':'image/jpeg','extmetadata':{
                    'LicenseShortName':{'value':'CC0 1.0'},
                    'ImageDescription':{'value':'<p>Angoulême musée de la bande dessinée façade musée</p>'}},
                    'url':'https://upload.wikimedia.org/wikipedia/commons/a/b/test.jpg'}]},
                  {'title':'File:Angoulême sous licence attribution.jpg','imageinfo':[{'mime':'image/jpeg','extmetadata':{'LicenseShortName':{'value':'CC BY 4.0'}}}]}]}})
            return DummyReply({'query':{'pages':[]}})
        if url==ri.OPENVERSE_API:
            return DummyReply({'results':[]})
        if url==ri.LOC_API:
            return DummyReply({'results':[]})
        raise AssertionError(url)


class ImageDiscoveryV7(unittest.TestCase):
    def test_sources_independantes_et_filtre_cc0(self):
        res=ri._commons_results('Angoulême musée',SearchSession())
        self.assertEqual(len(res),1)
        self.assertEqual(res[0]['provider'],'commons')
        self.assertEqual(res[0]['license_label'],'cc0 1.0')

    def test_pas_d_image_sans_lien_avec_histoire(self):
        s=(1,'LE LIEU','Angoulême musée',('angouleme','angoulême'),('musée','angouleme'))
        self.assertFalse(ri._match_candidate({'meta_text':'Paris nature street park','title':'jardin'},s))
        self.assertTrue(ri._match_candidate({'meta_text':'Angoulême musée bande dessinée','title':'Angoulême'},s))
        self.assertFalse(ri._match_candidate({'meta_text':'Angoulême musée AI-generated','title':'Angoulême'},s))

    def test_recuperation_3_photos_pertinentes_et_distinctes(self):
        f=next(x for x in catalogue.bank() if x['id']=='angouleme-collections')
        sess=SearchSession()
        def mock_download(session,title,option):
            blob=photo(sum(map(ord,title))%20000)
            return blob,{'titre_commons':title,'url_commons':'https://commons.wikimedia.org/wiki/File:'+title,
                         'sha256':hashlib.sha256(blob).hexdigest(),'licence':'CC0 1.0'}
        with tempfile.TemporaryDirectory() as td,patch.object(ri,'_fetch_file',side_effect=mock_download):
            files,records=ri.discover(f,session=sess,cache=Path(td))
            self.assertEqual(len(files),3)
            self.assertEqual({p['page'] for p in records},{1,3,4})
            self.assertEqual(len({ri._phash(p) for p in files}),3)
            self.assertTrue(all(p['pertinence'] and p['role'] and p['licence']=='CC0 1.0' for p in records))
            # Cache persists across future weekly runs.
            n=len(sess.calls)
            second=ri.discover(f,session=sess,cache=Path(td))
            self.assertEqual(len(second[0]),3)
            self.assertEqual(len(sess.calls),n)

    def test_fausse_photo_ne_suffit_pas(self):
        f=next(x for x in catalogue.bank() if x['id']=='angouleme-collections')
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(photos_reelles.PhotosIndisponibles):
                ri.discover(f,session=SearchSession(make_relevant=False),cache=Path(td))

    def test_duc_angouleme_n_est_pas_le_musee_bd(self):
        scene=ri.SCENES['angouleme'][0]
        self.assertFalse(ri._match_candidate({'meta_text':
          "Entrée du duc d'Angoulême à Paris en 1823, Musée Carnavalet",'title':'duc'},scene))

    def test_autre_topffer_ne_remplace_pas_rodolphe(self):
        scene=ri.SCENES['topffer'][0]
        self.assertFalse(ri._match_candidate({'meta_text':'Friedrich Töpffer 1897 portrait',
                                              'title':'Friedrich Töpffer'},scene))
        self.assertTrue(ri._match_candidate({'meta_text':'Rodolphe Töpffer portrait',
                                             'title':'Rodolphe Töpffer'},scene))

    def test_annee_1975_ne_peut_pas_etre_remplacee_par_photo_actuelle(self):
        fact=next(x for x in catalogue.bank() if x['id']=='festival-scolaire-1975')
        self.assertEqual(ri.SCENES[fact['id']][0][-1],('1975',))
        scene=ri.SCENES[fact['id']][0]
        self.assertFalse(ri._match_candidate({'title':'Festival Angoulême 2026','meta_text':'festival Angoulême'},scene))

    def test_openverse_exclut_licence_attribution(self):
        class S:
            def get(self,*a,**kw):return DummyReply({'results':[
                {'title':'A','url':'https://cdn.stocksnap.io/a.jpg','foreign_landing_url':'https://stocksnap.io/a','license':'by'},
                {'title':'B','url':'https://cdn.stocksnap.io/b.jpg','foreign_landing_url':'https://stocksnap.io/b','license':'cc0','mature':False}]})
        out=ri._openverse_results('example',S())
        self.assertEqual([r['title'] for r in out],['B'])
        self.assertFalse(ri._safe_image_url('https://private.local/secret','openverse'))

    def test_loc_ne_prend_pas_no_known_restrictions_pour_pdm(self):
        class S:
            def get(self,*a,**kw):return DummyReply({'results':[
                {'title':'Photo A','rights_advisory':'No known restrictions','image_url':['https://www.loc.gov/a.jpg']},
                {'title':'Photo B','rights_advisory':'Public domain','image_url':['https://www.loc.gov/b.jpg'],
                 'id':'https://www.loc.gov/item/12345/'}]})
        out=ri._loc_results('comics',S())
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]['title'],'Photo B')

    def test_infrastructure_de_repli_sans_image_generative(self):
        f=next(x for x in catalogue.bank() if x['id']=='angouleme-collections')
        with patch('anecdotes_auto.photos_reelles.resolve',side_effect=photos_reelles.PhotosIndisponibles('aucun scénario')) as legacy,\
             patch.object(ri,'discover',return_value=([Path('a'),Path('b'),Path('c')],[{'page':1},{'page':3},{'page':4}])) as nouveau:
            a,b=ri.resolve_avance(f)
        self.assertEqual(len(a),3)
        legacy.assert_called_once();nouveau.assert_called_once()

    def test_preparation_du_stock_sans_appel_buffer(self):
        with tempfile.TemporaryDirectory() as td:
            stock_path=Path(td)/'stock.json';state=Path(td)
            def mock_resolve(f):
                if f['id'].startswith('bruxelles'):
                    return ['a','b','c'],[{'page':1},{'page':3},{'page':4}]
                raise photos_reelles.PhotosIndisponibles('aucune photo')
            now=dt.datetime(2026,11,24,15,tzinfo=dt.timezone.utc)
            with (patch.object(stock_images,'STOCK',stock_path),
                  patch.object(stock_images,'STATE',state),
                  patch.object(stock_images,'limiter_cache_images',return_value=0)):
                report=stock_images.preparer_stock(limit=5,now=now,resolver=mock_resolve)
                self.assertEqual(len(report['tentatives']),5)
                self.assertTrue(stock_path.exists())
                report2=stock_images.preparer_stock(limit=5,now=now,resolver=mock_resolve)
                self.assertEqual(len(report2['tentatives']),5) # 5 other facts, not same 5
                self.assertTrue(set(t['fait'] for t in report['tentatives']).isdisjoint(
                    set(t['fait'] for t in report2['tentatives'])))

    def test_fait_illustre_prime_sur_theme_recent(self):
        day=dt.date(2026,11,29)
        facts=[x for x in catalogue.bank() if x['id'] in ('bruxelles-horta','spirou-naissance')]
        registry={'2026-11-30':{'etat':'PROGRAMME','sujet':'bruxelles','fact_id':'bruxelles-1984'}}
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            catalogue.write(state/'stock_photos_verifiees.json',{
                'bruxelles-horta':{'statut':'PRET'},'spirou-naissance':{'statut':'INDISPONIBLE'}})
            with patch.object(run,'STATE',state):
                choices=run.sujets_par_disponibilite(facts,registry,day)
        self.assertEqual(choices[0]['id'],'bruxelles-horta')

    def test_rattrapage_du_29_par_autre_sujet_avec_meme_id_buffer(self):
        current='2026-11-29';neighbour='2026-11-30'
        old='📚 ANECDOTE BD — LE SAVAIS-TU ?\n\nPrésentation antérieure'
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'anecdotes_state';state.mkdir()
            catalogue.write(state/'programmes.json',{
              current:{'etat':'PROGRAMME','fact_id':'festival-scolaire-1975','sujet':'festival',
                       'id_buffer':'post-29','texte_public':old,'version_visuelle':'BD_STORY_PHOTOS_V3_2026_11'},
              neighbour:{'etat':'PROGRAMME','fact_id':'bruxelles-1984','sujet':'bruxelles',
                       'id_buffer':'post-30','texte_public':'📚 ANECDOTE BD — LE SAVAIS-TU ?\nDéjà valide',
                       'version_visuelle':'BD_STORY_PHOTOS_V5_NARRATION_SEMANTIQUE_2026_11'}})
            catalogue.write(state/'stock_photos_verifiees.json',{'bruxelles-horta':{'statut':'PRET'}})
            originals=[];proofs=[]
            for i,page in enumerate((1,3,4)):
                p=root/f'photo-{i}.jpg';p.write_bytes(photo(100+i));originals.append(p)
                proofs.append({'page':page,'role':'LE LIEU','pertinence':'Photo de Magasins Waucquez',
                               'licence':'CC0 1.0','famille_source':f'different-{i}',
                               'titre_commons':f'Waucquez {i}'})
            class BufferStub:
                def __init__(self):self.edits=[]
                def day(self,day):
                    if day.isoformat()==current:
                        return [{'id':'post-29','text':old,'status':'scheduled',
                                 'channelId':'channel','dueAt':current+'T17:00:00Z'}]
                    if day.isoformat()==neighbour:
                        return [{'id':'post-30','text':'📚 ANECDOTE BD — LE SAVAIS-TU ?\nDéjà valide',
                                 'status':'scheduled','channelId':'channel','dueAt':neighbour+'T17:00:00Z'}]
                    return []
                def verify_images(self,base,names,folder):
                    self.asserted=True
                    return [{'image':{'url':base+name}} for name in names]
                def edit_own(self,post_id,text,due,assets):
                    self.edits.append((post_id,due,len(assets)))
                    return {'id':post_id,'dueAt':due,'status':'scheduled'}
            buff=BufferStub()
            def media(f):
                if f['id']=='bruxelles-horta':return originals,proofs
                raise photos_reelles.PhotosIndisponibles('Pas de photo correspondant au fait')
            now=dt.datetime(2026,11,29,0,tzinfo=dt.timezone.utc)
            with (patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',state),
                 patch.object(run,'REGISTRY',state/'programmes.json'),
                 patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),
                 patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),
                 patch.object(run,'resolve',side_effect=media),
                 patch.dict(run.CONFIG,{'horizon_jours':1,'max_posts_par_execution':4})):
                prep=run.prepare('owner/public',now=now,buffer=buff,collect=False)
                self.assertEqual(prep['remplacements_non_effectues'],[])
                chosen=catalogue.read(state/'programmes.json')[current]
                self.assertEqual(chosen['fact_id'],'bruxelles-horta')
                self.assertEqual(chosen['etat'],'EN_ATTENTE_MAJ')
                report=run.send(now=now,buffer=buff)
            self.assertEqual(report['remplacements_non_effectues'],[])
            self.assertEqual(buff.edits,[('post-29',current+'T17:00:00Z',5)])

    def test_version_ne_modifie_pas_bd_manga_comics(self):
        self.assertIn('V7_MULTI_SOURCES',run.VERSION_VISUELLE)
        self.assertIn('BD_STORY_PHOTOS_V5_NARRATION_SEMANTIQUE_2026_11',run.VERSIONS_DEJA_VALIDES)
        wf=(Path(__file__).resolve().parents[1]/'.github/workflows/anecdotes_bd_phototheque.yml').read_text()
        self.assertIn('concurrency:',wf)
        self.assertIn('preparer',Path(__file__).resolve().parents[1].joinpath('anecdotes_auto/stock_images.py').read_text())

if __name__=='__main__':unittest.main()
