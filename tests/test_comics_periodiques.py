import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from comics_sources_periodiques import (parse_mdcu_article,article_urls,parse_monthly_bdfugue,
    collect_one,SourceError,MDCU_INDEX)
from comics_score_periodique import calculer
from comics_visual_periodique import ordered_names,render
from comics_pipeline_periodique import run_one,update_evolution
from comics_buffer_periodique import next_slot,construire
from sources.couvertures import cover_path

URL='https://mdcu-comics.fr/news/42476-meilleures-ventes-comics-bdfugue-semaine-46'
MONTH='https://mdcu-comics.fr/news/42388-meilleures-ventes-comics-bdfugue-octobre-2026'
NAMES=['Coffret Absolute Batman Collector','Les Affamés du crépuscule T02',
       'Absolute Superman Tome 3','Absolute Wonder Woman Tome 3','Skinbreaker',
       'Gunslinger Spawn 2023 - 2024','Savage Sword of Conan (Titan Series) T04']
PUBLISHERS=['Urban Comics','Delcourt','Urban Comics','Urban Comics','Delcourt','Delcourt','Panini Comics']

def article(n=5,monthly=False):
    title='Meilleures ventes comics BDfugue octobre 2026' if monthly else 'Meilleures ventes comics BDfugue semaine 46'
    date='31/10/2026' if monthly else '15/11/2026'
    html=f'<html><main><h1>{title}</h1><p>Par CaptainMDCU {date} 09:16</p><h2>Meilleures ventes BDFugue</h2>'
    for i in range(n):
        t=NAMES[i];p=PUBLISHERS[i]
        html+=f'<div class="book"><h3>#{i+1}</h3><h5><a href="/comics/{i+1}">{t}</a></h5><p>13/11/2026 -</p><li>{p}</li><img alt="{t}" src="/covers/{i+1}.jpg" /></div>'
    html+='</main><h2>Commentaires</h2></html>'
    return html

def context(n=5,monthly=False):
    url=MONTH if monthly else URL
    cad='MENSUEL' if monthly else 'HEBDO'
    return parse_mdcu_article(article(n,monthly),url,cadence=cad)

class TestsComicsPeriodiques(unittest.TestCase):
    def test_mdcu_weekly_5_with_ranks_editors_covers(self):
        x=context()
        self.assertEqual(x['edition'],'COMICS_HEBDO_2026_W46')
        self.assertEqual(len(x['titres']),5)
        self.assertEqual(x['titres'][0]['editeur'],'Urban Comics')
        self.assertEqual(x['titres'][-1]['titre'],'Skinbreaker')
        self.assertEqual(x['titres'][3]['couverture_candidate_url'],'https://mdcu-comics.fr/covers/4.jpg')
    def test_mdcu_monthly_five_must_not_invent_seven(self):
        with self.assertRaises(SourceError):context(5,monthly=True)
    def test_mdcu_monthly_seven_if_explicit(self):
        x=context(7,monthly=True)
        self.assertEqual(x['edition'],'COMICS_MENSUEL_2026_10')
        self.assertEqual(len(x['titres']),7)
    def test_discovery_home(self):
        sample='<a href="/news/42476-meilleures-ventes-comics-bdfugue-semaine-46">Meilleures ventes comics BDfugue semaine 46</a>'
        self.assertEqual(article_urls(sample),[URL])
        self.assertEqual(article_urls(sample,mode='MENSUEL'),[])
    def test_missing_position_is_refused(self):
        bad=article().replace('<h3>#3</h3>','<h3>#8</h3>')
        with self.assertRaises(SourceError):parse_mdcu_article(bad,URL,cadence='HEBDO')
    def test_old_articles_are_refused(self):
        def ff(url):
            if url.endswith('/news') or url.endswith('/'):
                return f'<a href="{URL}">Meilleures ventes comics BDfugue semaine 46</a>'
            return article()
        with self.assertRaises(SourceError):
            collect_one('HEBDO',now=dt.datetime(2026,12,4,tzinfo=dt.timezone.utc),fetcher=ff)
    def test_monthly_only_five_not_published(self):
        def ff(url):
            if 'meilleures-ventes/comics' in url:raise SourceError('403')
            if url.endswith('/news') or url.endswith('/'):
                return f'<a href="{MONTH}">Meilleures ventes comics BDfugue octobre 2026</a>'
            return article(5,monthly=True)
        with self.assertRaises(SourceError):
            collect_one('MENSUEL',now=dt.datetime(2026,11,3,tzinfo=dt.timezone.utc),fetcher=ff)
    def test_403_fnac_never_required(self):
        def ff(url):
            if 'fnac' in url:raise AssertionError('Fnac ne doit pas être appelée')
            if url.endswith('/news') or url.endswith('/'):
                return f'<a href="{URL}">Meilleures ventes comics BDfugue semaine 46</a>'
            return article()
        data,_=collect_one('HEBDO',now=dt.datetime(2026,11,17,tzinfo=dt.timezone.utc),fetcher=ff)
        self.assertEqual(len(data['titres']),5)
    def test_score_sufficient_but_not_probability(self):
        x=context();proof={'mode_interne':x['mode_interne']}
        covers=[{'rang':i,'ok':True} for i in range(1,6)]
        result=calculer(x,proof,covers,today=dt.date(2026,11,17))
        self.assertTrue(result['autorise_publication'])
        self.assertEqual(result['unite'],'points_sur_100_non_probabiliste')
    def test_missing_cover_blocks_even_with_other_points(self):
        x=context();proof={'mode_interne':x['mode_interne']}
        cov=[{'rang':i,'ok':i!=2} for i in range(1,6)]
        self.assertFalse(calculer(x,proof,cov,today=dt.date(2026,11,17))['autorise_publication'])
    def test_separate_history(self):
        x=context();prior=context();prior['edition']='COMICS_HEBDO_2026_W45'
        prior['titres'][0]['rang']=2
        update_evolution(x,prior)
        self.assertTrue(x['variations_verifiees'])
        self.assertEqual(x['titres'][0]['mouvement'],'+1 PL.')
        a=context();prior['cadence']='MENSUEL';update_evolution(a,prior)
        self.assertFalse(a['variations_verifiees'])
    def test_filenames(self):
        self.assertEqual(ordered_names(5),['01_rang_5.png','02_rang_4.png','03_rang_3.png','04_rang_2.png','05_rang_1.png','06_recapitulatif.png'])
        self.assertEqual(len(ordered_names(7)),8)
    def test_buffer_weekly_thursday(self):
        x=context();when=dt.datetime(2026,11,17,9,tzinfo=dt.timezone.utc)
        self.assertEqual(next_slot(x,now=when),'2026-11-19T17:00:00.000Z')
    def test_buffer_monthly_second_sunday(self):
        x=context(7,monthly=True)
        when=dt.datetime(2026,11,3,9,tzinfo=dt.timezone.utc)
        self.assertEqual(next_slot(x,now=when),'2026-11-08T17:00:00.000Z')
    def test_complete_weekly_pipeline_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            x=context();proof={'mode_interne':x['mode_interne']}
            def downloader(book,folder):
                file=cover_path(folder,book['titre']);file.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(220,330),'white').save(file)
                return {'rang':book['rang'],'ok':True,'origine':'test'}
            now=dt.datetime(2026,11,17,11,tzinfo=dt.timezone.utc)
            target=run_one('HEBDO',output=Path(tmp)/'out',history=Path(tmp)/'hist',now=now,
                prebuilt=(x,proof),covers_fn=downloader)
            state=json.loads((target/'ETAT.json').read_text())
            self.assertTrue(state['pret_buffer']);self.assertEqual(state['pages'],6)
            self.assertTrue((target/'COMICS'/'06_recapitulatif.png').exists())
            caption=(target/'COMICS'/'legende_instagram.txt').read_text()
            self.assertIn('TOP 5 COMICS',caption)
            self.assertNotIn('BDFugue',caption)
            self.assertNotIn('reconstitué',caption)
            payload=construire(target/'COMICS','https://raw.githubusercontent.com/u/r/main/public_media/COMICS_HEBDO_2026_W46/COMICS_abc/',
                'a-channel',now=now)
            self.assertEqual(len(payload['assets']),6)
            self.assertEqual(payload['dueAt'],'2026-11-19T17:00:00.000Z')
    def test_complete_monthly_pipeline_eight_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            x=context(7,monthly=True);proof={'mode_interne':x['mode_interne']}
            def downloader(book,folder):
                file=cover_path(folder,book['titre']);file.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(220,330),'white').save(file)
                return {'rang':book['rang'],'ok':True,'origine':'test'}
            now=dt.datetime(2026,11,3,11,tzinfo=dt.timezone.utc)
            target=run_one('MENSUEL',output=Path(tmp)/'out',history=Path(tmp)/'hist',now=now,
                prebuilt=(x,proof),covers_fn=downloader)
            state=json.loads((target/'ETAT.json').read_text())
            self.assertTrue(state['pret_buffer']);self.assertEqual(state['pages'],8)
            payload=construire(target/'COMICS','https://raw.githubusercontent.com/u/r/main/public_media/COMICS_MENSUEL_2026_10/COMICS_abc/',
                'channel',now=now)
            self.assertEqual(len(payload['assets']),8)
            self.assertEqual(payload['dueAt'],'2026-11-08T17:00:00.000Z')
    def test_idempotence_does_not_create_second_post(self):
        from comics_buffer_periodique import transmettre
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'post_manifest.json').write_text(json.dumps({'edition':'COMICS_HEBDO_2026_W46','cadence':'HEBDO'}))
            receipt=folder/'previous.json';receipt.write_text(json.dumps({
                'statut':'POST_PROGRAMME','edition':'COMICS_HEBDO_2026_W46',
                'cadence':'HEBDO','id_buffer':'abc123','date_programmee_utc':'2026-11-19T17:00:00.000Z'}))
            now=dt.datetime(2026,11,20,10,tzinfo=dt.timezone.utc)
            with patch('comics_buffer_periodique.construire',return_value={'text':'TOP 5 COMICS','dueAt':'2026-11-26T17:00:00.000Z','assets':[]}):
                result=transmettre(folder,'https://raw.githubusercontent.com/o/r/main/',api_key='x',channel_id='y',send=True,now=now,previous_receipt=receipt)
            self.assertEqual(result['action'],'DEJA_TRANSMIS_NON_MODIFIABLE')
    def test_no_source_result_is_nonpublication(self):
        with tempfile.TemporaryDirectory() as tmp:
            def ff(url):raise SourceError('403 Forbidden')
            result=run_one('HEBDO',output=Path(tmp),now=dt.datetime(2026,11,24,tzinfo=dt.timezone.utc),fetcher=ff)
            self.assertFalse(json.loads((result/'ETAT.json').read_text())['pret_buffer'])
    def test_both_modes_independent(self):
        self.assertNotEqual(ordered_names(5),ordered_names(7))

if __name__=='__main__':unittest.main()
