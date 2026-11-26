"""Tests complémentaires sans accès à Buffer pour la réparation V10."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch
from illyadera_queue import free_capacity_for_priority
from anecdotes_auto.calendrier import eligible
from sources.collecte import parse_bdzoom

PARIS=ZoneInfo('Europe/Paris')
NOW=dt.datetime(2026,11,26,10,tzinfo=dt.timezone.utc)


def due(days):
    d=NOW.astimezone(PARIS).date()+dt.timedelta(days=days)
    return dt.datetime.combine(d,dt.time(18),tzinfo=PARIS).astimezone(dt.timezone.utc).isoformat()


class FakeBuffer:
    def __init__(self,posts):self.posts=list(posts);self.deleted=[]
    def list_scheduled(self):return list(self.posts)
    def delete_own(self,identity):
        self.deleted.append(identity)
        self.posts=[p for p in self.posts if p['id']!=identity]
        return {'id':identity}


def make(days):
    ident=f'id{days}'
    text='📚 ANECDOTE BD — sujet authentique '+ident
    when=due(days)
    post={'id':ident,'status':'scheduled','channelId':'chan','text':text,'dueAt':when}
    date=dt.datetime.fromisoformat(when).astimezone(PARIS).date().isoformat()
    rec={date:{'etat':'PROGRAMME','id_buffer':ident,'texte_public':text,'due_at':when}}
    return post,rec


class ParserVentesTests(unittest.TestCase):
    def test_tirets_bdzoom_et_titres_distincts(self):
        variants=['=','(–1)','(–2)','nouveau','(+3)','(−1)','(—2)']
        rows=''.join(
            f'<tr><td>{n}</td><td>{variation}</td><td>Album officiel {n}</td>'
            f'<td>Auteur {n}</td><td>Editeur {n}</td></tr>'
            for n,variation in enumerate(variants,1))
        html=('<h1>Zoom sur les meilleures ventes de BD</h1>'
              '<article><p>Top 20 BD du 9 au 15 novembre 2026</p>'
              '<table>'+rows+'</table></article>')
        data=parse_bdzoom(html,'https://www.bdzoom.com/test/')
        self.assertEqual([row['titre'] for row in data['titres']],
                         [f'Album officiel {n}' for n in range(1,8)])
        self.assertEqual(data['titres'][1]['mouvement'],'−1 PL.')
        self.assertEqual(data['titres'][3]['mouvement'],'NOUVEAU')


class AutonomousQueueTests(unittest.TestCase):
    def test_emplacement_top_peut_etre_pourvu_avant_par_anecdote(self):
        day=dt.date(2026,12,1)  # mardi Manga
        ok,status=eligible(day,NOW,[])
        self.assertTrue(ok)
        self.assertEqual(status,'PROVISOIRE_TOP')

    def test_reordonner_la_queue_ne_preempte_qu_une_anecdote_lointaine(self):
        posts=[];reg={}
        for days in range(3,13):
            post,record=make(days);posts.append(post);reg.update(record)
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as temp:
            result=free_capacity_for_priority(due(2),buffer=b,registry=reg,
                registry_path=Path(temp)/'registre.json',max_posts=10,
                now=NOW,priority='REMPLISSAGE')
        self.assertEqual(result['action'],'ANECDOTE_LIBEREE')
        self.assertEqual(b.deleted,['id12'])

    def test_ne_pas_ecraser_une_anecdote_plus_proche_pour_une_date_lointaine(self):
        posts=[];reg={}
        for days in range(2,12):
            post,record=make(days);posts.append(post);reg.update(record)
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as temp:
            result=free_capacity_for_priority(due(18),buffer=b,registry=reg,
                registry_path=Path(temp)/'registre.json',max_posts=10,
                now=NOW,priority='REMPLISSAGE')
        self.assertEqual(result['action'],'AUCUNE_ANECDOTE_PLUS_LOINTAINE')
        self.assertEqual(b.deleted,[])

    def test_ne_jamais_toucher_post_manuel_et_top(self):
        posts=[];reg={}
        for days in range(2,11):
            post,record=make(days);posts.append(post);reg.update(record)
        posts.append({'id':'manuel','status':'scheduled','channelId':'chan',
                      'text':'Publication humaine','dueAt':due(15)})
        b=FakeBuffer(posts)
        with tempfile.TemporaryDirectory() as temp:
            result=free_capacity_for_priority(due(1),buffer=b,registry=reg,
                registry_path=Path(temp)/'registre.json',max_posts=10,
                now=NOW,priority='REMPLISSAGE')
        self.assertEqual(result['action'],'ANECDOTE_LIBEREE')
        self.assertNotIn('manuel',b.deleted)


if __name__=='__main__':unittest.main()
