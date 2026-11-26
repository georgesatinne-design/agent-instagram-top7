import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from illyadera_queue import free_capacity_for_priority
from anecdotes_auto.buffer import Buffer,BufferError,utc

PARIS=ZoneInfo('Europe/Paris')
TODAY=dt.datetime(2026,11,26,10,0,tzinfo=dt.timezone.utc)


def at(days=0,hour=18):
    day=(TODAY.astimezone(PARIS).date()+dt.timedelta(days=days))
    return dt.datetime.combine(day,dt.time(hour),tzinfo=PARIS).astimezone(dt.timezone.utc).isoformat().replace('+00:00','Z')


def make_post(i,days,text='AUTRE PUBLICATION'):
    return {'id':f'post{i}','status':'scheduled','channelId':'chan','dueAt':at(days),'text':text}


def owned(posts,at_index):
    p=posts[at_index]
    p['text']='📚 ANECDOTE BD — sujet vérifié '+p['id']
    date=dt.datetime.fromisoformat(p['dueAt'].replace('Z','+00:00')).astimezone(PARIS).date().isoformat()
    return {date:{'etat':'PROGRAMME','id_buffer':p['id'],'due_at':p['dueAt'],
                  'texte_public':p['text'],'fact_id':'anecdote-'+p['id']}}


class FakeBuffer:
    def __init__(self,posts):self.posts=list(posts);self.deleted=[];self.reads=0
    def list_scheduled(self):self.reads+=1;return list(self.posts)
    def delete_own(self,id):
        self.deleted.append(id);self.posts=[p for p in self.posts if p['id']!=id];return {'id':id}


class PreemptionTests(unittest.TestCase):
    def test_queue_pleine_libere_une_anecdote_lointaine_verifiee(self):
        posts=[make_post(i,i+2) for i in range(10)]
        registry=owned(posts,9)
        buffer=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.json'
            result=free_capacity_for_priority(at(1),buffer=buffer,registry=registry,registry_path=path,
                                              max_posts=10,now=TODAY,priority='MANGA')
            self.assertEqual(result['action'],'ANECDOTE_LIBEREE')
            self.assertEqual(buffer.deleted,['post9'])
            self.assertEqual(len(buffer.posts),9)
            self.assertEqual(next(iter(json.loads(path.read_text()).values()))['etat'],'LIBERE_POUR_MANGA')

    def test_donne_priorite_a_anecdote_du_meme_jour(self):
        posts=[make_post(i,i+2) for i in range(5)]
        registry=owned(posts,1)
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as d:
            result=free_capacity_for_priority(at(3),buffer=b,registry=registry,registry_path=Path(d)/'r.json',
                                              max_posts=10,now=TODAY)
        self.assertEqual(result['action'],'ANECDOTE_LIBEREE')
        self.assertEqual(b.deleted,['post1'])

    def test_aucune_anecdote_eligible_ne_sera_inventee(self):
        b=FakeBuffer([make_post(i,i+1) for i in range(10)])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'aucune anecdote'):
                free_capacity_for_priority(at(12),buffer=b,registry={},registry_path=Path(d)/'r.json',
                                           max_posts=10,now=TODAY)
        self.assertFalse(b.deleted)

    def test_post_manuel_du_meme_jour_bloque_la_creation_du_top(self):
        b=FakeBuffer([make_post(1,2)])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,'occupé'):
                free_capacity_for_priority(at(2),buffer=b,registry={},registry_path=Path(d)/'r.json',
                                           max_posts=10,now=TODAY)
        self.assertFalse(b.deleted)

    def test_place_libre_et_rien_sur_le_jour_ne_supprime_rien(self):
        b=FakeBuffer([make_post(0,2)])
        with tempfile.TemporaryDirectory() as d:
            result=free_capacity_for_priority(at(3),buffer=b,registry={},registry_path=Path(d)/'r.json',
                                              max_posts=10,now=TODAY)
        self.assertEqual(result['action'],'PLACE_DISPONIBLE')
        self.assertFalse(b.deleted)

    def test_mismatch_texte_interdit_suppression(self):
        posts=[make_post(i,i+1) for i in range(10)]
        registry=owned(posts,9)
        posts[9]['text']='Texte changé manuellement dans Buffer'
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                free_capacity_for_priority(at(12),buffer=b,registry=registry,registry_path=Path(d)/'r.json',
                                           max_posts=10,now=TODAY)
        self.assertEqual(b.deleted,[])

    def test_top_deja_prevu_ne_preempte_pas(self):
        b=FakeBuffer([make_post(1,2,text='📚 TOP 7 MANGA — période')])
        with tempfile.TemporaryDirectory() as d:
            result=free_capacity_for_priority(at(2),buffer=b,registry={},registry_path=Path(d)/'r.json',
                                              max_posts=10,now=TODAY)
        self.assertEqual(result['action'],'TOP_DEJA_PREVU')
        self.assertEqual(b.deleted,[])


class BufferBulkTests(unittest.TestCase):
    def test_recuperation_paginated_et_filtrage_canal(self):
        buffer=Buffer(api_key='testkey',channel_id='chan',organization_id='org')
        calls=[]
        def fakecall(query,variables=None):
            calls.append(variables)
            if len(calls)==1:
                return {'posts':{'pageInfo':{'hasNextPage':True,'endCursor':'end1'},
                         'edges':[{'node':make_post(1,2)},{'node':make_post(2,5)}]}}
            return {'posts':{'pageInfo':{'hasNextPage':False,'endCursor':None},
                           'edges':[{'node':make_post(3,3)}]}}
        buffer.call=fakecall
        out=buffer.list_scheduled()
        self.assertEqual([x['id'] for x in out],['post1','post3','post2'])
        self.assertEqual(calls[-1]['cursor'],'end1')
        self.assertEqual(len(calls),2)

    def test_incomplete_page_rejected(self):
        buffer=Buffer(api_key='x',channel_id='chan',organization_id='org')
        buffer.call=lambda *args,**kwargs:{'posts':{'edges':[],'pageInfo':{'hasNextPage':True}}}
        with self.assertRaises(BufferError):buffer.list_scheduled()


class IntegrationRulesTests(unittest.TestCase):
    def test_workflows_share_one_concurrency_group(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('hebdomadaire.yml','manga_top7_collecte.yml','comics_top7_auto.yml','anecdotes_bd_auto.yml'):
            content=(root/'.github/workflows'/name).read_text()
            self.assertIn('group: illyadera-buffer-operations',content)

    def test_bd_incomplet_is_deferred_without_buffer_call(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/hebdomadaire.yml').read_text()
        self.assertIn('id: dossier',text)
        self.assertIn("out.write('ready='+str(ready).lower()",text)
        self.assertIn("steps.dossier.outputs.ready == 'true'",text)
        self.assertNotIn('Top 7 BD incomplet : dépôt automatique refusé',text)


if __name__=='__main__':unittest.main()
