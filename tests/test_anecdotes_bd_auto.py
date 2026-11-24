"""Tests ciblés sur calendrier, preuves, rendu, collision Buffer, source auto."""
import datetime as dt,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from anecdotes_auto.catalogue import bank,valid_fact,valid_url,topic,select
from anecdotes_auto.calendrier import PARIS,eligible,reserved_kind,target_date_time,is_second_sunday
from anecdotes_auto.visuels import page,caption
from anecdotes_auto.decouverte import structured_fact,candidate_links
from anecdotes_auto.buffer import is_top,is_anecdote,Buffer,utc
from anecdotes_auto import run
from bs4 import BeautifulSoup

class TestsAncd(unittest.TestCase):
    def test_bank(self):
        data=bank();self.assertGreaterEqual(len(data),30)
        self.assertEqual(len({a['id'] for a in data}),len(data))
        self.assertTrue(all(valid_fact(x) for x in data))
    def test_urls(self):
        self.assertTrue(valid_url('https://www.dargaud.com/auteurs/morris'))
        for url in ('http://www.dargaud.com','https://evil.com/a','file:///etc/passwd',
                    'https://www.dargaud.com.evil.com/a','https://foo@www.dargaud.com/a'):
            self.assertFalse(valid_url(url))
    def test_public_no_source(self):
        for fact in bank():
            text=caption(fact)
            self.assertNotIn('https://',text)
            self.assertNotIn('Edistat',text)
            self.assertNotIn('Source :',text)
            self.assertLessEqual(len(text),2200)
    def test_visuel_one_page(self):
        im=page(bank()[0],1)
        self.assertEqual(im.size,(1080,1350))
    def test_reserved(self):
        self.assertEqual(reserved_kind(dt.date(2026,11,24)),'MANGA')
        self.assertEqual(reserved_kind(dt.date(2026,11,26)),'COMICS_HEBDO')
        self.assertEqual(reserved_kind(dt.date(2026,11,27)),'BD')
        self.assertEqual(reserved_kind(dt.date(2026,12,13)),'COMICS_MENSUEL')
        self.assertIsNone(reserved_kind(dt.date(2026,12,14)))
    def test_top_future_protected(self):
        now=dt.datetime(2026,11,24,8,tzinfo=PARIS)
        self.assertEqual(eligible(dt.date(2026,11,24),now,[])[1],'RESERVE_AU_TOP')
        self.assertTrue(eligible(dt.date(2026,11,25),now,[])[0])
    def test_fallback_late(self):
        now=dt.datetime(2026,11,24,16,47,tzinfo=PARIS)
        self.assertEqual(eligible(dt.date(2026,11,24),now,[]),(True,'REPLI_TOP'))
        now=dt.datetime(2026,11,27,15,47,tzinfo=PARIS)
        self.assertTrue(eligible(dt.date(2026,11,27),now,[])[0])
    def test_existing_post_protected(self):
        now=dt.datetime(2026,11,25,10,tzinfo=PARIS)
        self.assertFalse(eligible(dt.date(2026,11,25),now,[{'text':'TOP 7 MANGA'}])[0])
    def test_too_late(self):
        now=dt.datetime(2026,11,25,17,45,tzinfo=PARIS)
        self.assertFalse(eligible(dt.date(2026,11,25),now,[])[0])
    def test_local_due_dst(self):
        self.assertNotEqual(utc(target_date_time(dt.date(2026,11,25))),
                            utc(target_date_time(dt.date(2026,6,24))))
        self.assertEqual(utc(target_date_time(dt.date(2026,11,25)))[11:16],'17:00')
    def test_header(self):
        self.assertTrue(is_top({'text':'📚 TOP 5 COMICS — 2026'}))
        self.assertTrue(is_top({'text':'TOP 7 BD DU 09/11 AU 15/11/2026'}))
        self.assertTrue(is_anecdote({'text':'📚 ANECDOTE BD — LE SAVAIS-TU ?'}))
        self.assertFalse(is_top({'text':'📚 ANECDOTE BD'}))
    def test_book_structured(self):
        html='''<html><h1>Absolute Superman Tome 4</h1><p>La série officielle contient de nombreuses informations sur les éditions.</p><script type="application/ld+json">{"@type":"Book","name":"Absolute Superman Tome 4","datePublished":"2026-11-23","numberOfPages":180,"author":{"name":"Jason Aaron"}}</script>'''+'<p>'+'Histoire du livre. '*12+'</p></html>'
        fact=structured_fact('https://www.urban-comics.com/absolute-superman-tome-4/',html)
        self.assertIsNotNone(fact);self.assertIn('180',fact['fait'])
        self.assertEqual(fact['type_preuve'],'METADONNEES_EDITEUR_OFFICIEL')
    def test_no_hallucinated_fact(self):
        self.assertIsNone(structured_fact('https://www.urban-comics.com/livre-test/',
           '<h1>Livre test</h1><p>Voici une histoire passionnante pour les lecteurs.</p>'*10))
    def test_only_publisher(self):
        h='<html><h1>Livre test</h1>'+'<p>parution pages date auteur</p>'*15+'</html>'
        self.assertIsNone(structured_fact('https://www.cbbd.be/fr/about',h))
    def test_select_unique(self):
        data=bank();v=select(data,{}, {},dt.date(2026,11,24))
        self.assertIsNotNone(v)
        self.assertNotEqual(select(data,{v['id']:'2026-11-24'}, {},dt.date(2026,11,24))['id'],v['id'])
    def test_reconcile_top_priority(self):
        class Fake:
            def __init__(self):self.deleted=[]
            def day(self,day):
                return [{'id':'anec-1','text':'📚 ANECDOTE BD — LE SAVAIS-TU ?',
                         'dueAt':'2026-11-26T17:00:00Z','status':'scheduled','channelId':'1'},
                        {'id':'top-1','text':'📚 TOP 5 COMICS','dueAt':'2026-11-26T17:00:00Z',
                         'status':'scheduled','channelId':'1'}]
            def delete_own(self,id):self.deleted.append(id)
        fake=Fake();now=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
        rec={'2026-11-26':{'etat':'PROGRAMME','id_buffer':'anec-1',
             'texte_public':'📚 ANECDOTE BD — LE SAVAIS-TU ?'}}
        result={'erreurs':[],'supprimes_pour_top':[]}
        run.reconcile(fake,rec,now,result)
        self.assertEqual(fake.deleted,['anec-1'])
        self.assertEqual(rec['2026-11-26']['etat'],'SUPPLANTE_PAR_TOP')
    def test_create_payload(self):
        calls=[]
        def fake_post(url,**kw):
            calls.append(kw['json']['variables']['input']);
            class Resp:
                def raise_for_status(self):pass
                def json(self):return {'data':{'createPost':{'__typename':'PostActionSuccess',
                   'post':{'id':'p1','dueAt':'2026-11-25T17:00:00.000Z','status':'scheduled'}}}}
            return Resp()
        buf=Buffer(api_key='test',channel_id='ch',organization_id='org',post=fake_post)
        post=buf.create('📚 ANECDOTE BD','2026-11-25T17:00:00.000Z',[
                    {'image':{'url':'https://raw.githubusercontent.com/example/test/main/01.png'}}]*5)
        self.assertEqual(post['id'],'p1')
        self.assertFalse(calls[0]['needsApproval'])
        self.assertEqual(calls[0]['mode'],'customScheduled')
    def test_pipeline_prepare_then_send_without_network(self):
        import shutil
        from anecdotes_auto import catalogue,visuels
        class Fake:
            def __init__(self):self.posts={};self.created=[]
            def day(self,day):return self.posts.get(day.isoformat(),[])
            def verify_images(self,base_url,names,folder):
                self_url='https://raw.githubusercontent.com/'
                if not base_url.startswith(self_url):raise ValueError('URL')
                assert len(names)==5 and all((folder/x).is_file() for x in names)
                return [{'image':{'url':base_url+x}} for x in names]
            def create(self,text,due,assets):
                d=dt.datetime.fromisoformat(due.replace('Z','+00:00')).astimezone(PARIS).date().isoformat()
                p={'id':'exemple-buffer','text':text,'dueAt':due,'status':'scheduled','channelId':'ch'}
                self.posts.setdefault(d,[]).append(p);self.created.append(p)
                return p
        fake=Fake()
        when=dt.datetime(2026,11,24,5,35,tzinfo=PARIS)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'anecdotes_assets').mkdir()
            original=Path(__file__).resolve().parents[1]/'anecdotes_assets'/'fond_bd_original.jpeg'
            shutil.copyfile(original,root/'anecdotes_assets'/'fond_bd_original.jpeg')
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',root/'anecdotes_state'),\
                patch.object(run,'REGISTRY',root/'anecdotes_state'/'programmes.json'),\
                patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                patch.object(visuels,'ROOT_REPO',root),\
                patch.object(catalogue,'STATE',root/'anecdotes_state'),\
                patch.dict(run.CONFIG,{'horizon_jours':2,'max_posts_par_execution':1}):
                result=run.prepare('owner/depot-public',now=when,buffer=fake,collect=False)
                self.assertEqual(result['plans'],['2026-11-25'])
                done=run.send(now=when,buffer=fake)
                self.assertEqual(len(done['programmes']),1)
                self.assertEqual(len(fake.created),1)
                receipt=json.loads((root/'anecdotes_state'/'programmes.json').read_text())
                self.assertEqual(receipt['2026-11-25']['etat'],'PROGRAMME')
                # A second run must not create a second Buffer publication.
                done2=run.send(now=when,buffer=fake)
                self.assertFalse(done2['programmes'])
                self.assertEqual(len(fake.created),1)

    def test_occupied_wednesday_never_staged(self):
        from anecdotes_auto import catalogue
        class Occupied:
            def day(self,day):
                if day==dt.date(2026,11,25):return [{'text':'Autre publication','id':'o1'}]
                return []
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(run,'ROOT_REPO',root),patch.object(run,'STATE',root/'anecdotes_state'),\
                patch.object(run,'REGISTRY',root/'anecdotes_state'/'programmes.json'),\
                patch.object(run,'PUBLIC',root/'public_media'/'anecdotes_bd'),\
                patch.object(run,'REPORT',root/'sorties'/'anecdotes_bd'),\
                patch.object(catalogue,'STATE',root/'anecdotes_state'),\
                patch.dict(run.CONFIG,{'horizon_jours':1}):
                result=run.prepare('owner/depot-public',now=dt.datetime(2026,11,24,5,35,tzinfo=PARIS),buffer=Occupied(),collect=False)
                self.assertEqual(result['plans'],[])

    def test_day_fail_closed(self):
        def fake_post(url,**kw):
            class Resp:
                def raise_for_status(self):pass
                def json(self):return {'data':{'posts':{'pageInfo':{'hasNextPage':True},'edges':[]}}}
            return Resp()
        buf=Buffer(api_key='test',channel_id='ch',organization_id='org',post=fake_post)
        with self.assertRaises(Exception):buf.day(dt.date(2026,11,25))

if __name__=='__main__':unittest.main()
