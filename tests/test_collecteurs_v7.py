"""Test de régression fondé sur la structure publiée par les sources, sans accès Internet."""
import datetime as dt
import unittest
from sources.collecte import dates_semaine,parse_bdzoom,rangs_bede,latest_bdzoom_url,SourceError

class CollecteursV7(unittest.TestCase):
    def test_published_november_period(self):
        self.assertEqual(dates_semaine('Top 20 BD (copyright GfK/Livres Hebdo) du 2 au 8 novembre 2026'),('2026-11-02','2026-11-08'))
    def test_published_cross_month_period(self):
        self.assertEqual(dates_semaine('Top 20 BD (copyright GfK/Livres Hebdo) du 26 octobre au 1er novembre 2026'),('2026-10-26','2026-11-01'))
    def test_date_outside_entry_content(self):
        rows=''.join('<tr><td>{}e</td><td>(+1)</td><td>Album vérifié {}</td><td>Artiste</td><td>Éditeur</td></tr>'.format(i,i) for i in range(1,8))
        html='<h1>Zoom sur les meilleures ventes de BD du 18 novembre 2026</h1><main><article><div class="entry-content"><p>Cette semaine...</p></div><p>Top 20 BD (copyright GfK/Livres Hebdo) du 2 au 8 novembre 2026</p><table>'+rows+'</table></article></main>'
        d=parse_bdzoom(html,'https://www.bdzoom.com/test/')
        self.assertEqual(d['fin_ventes'],'2026-11-08')
        self.assertEqual(len(d['titres']),7)
        self.assertEqual(d['titres'][0]['mouvement'],'+1 PL.')
    def test_bede_cards_as_divs_not_li(self):
        html='''<h1>Les meilleures ventes - palmarès du 20/11/2026</h1><div class="cards">
          <div class="book"><span>#1</span><a href="/album/1"><img src="https://cdn.bede.fr/1.jpg" alt="Les Aventures de Lucky Luke - Tome 12"/></a></div>
          <div class="book"><span>#2</span><a href="/album/2"><img src="https://cdn.bede.fr/2.jpg" alt="Spy x Family tome 17"/></a></div>
        </div>'''
        d=rangs_bede(html)
        self.assertEqual(d['date_palmares'],'20/11/2026')
        self.assertEqual([x['rang_general'] for x in d['classement_general']],[1,2])
        self.assertEqual(d['classement_general'][0]['fiche_url'],'https://www.bede.fr/album/1')
    def test_bdzoom_choose_latest_link(self):
        html='''<a href="/216365/meilleures-ventes/zoom-sur-les-meilleures-ventes-de-bd-du-11-novembre-2026/">Zoom sur les meilleures ventes de BD du 11 novembre 2026</a>
        <a href="/216589/meilleures-ventes/zoom-sur-les-meilleures-ventes-de-bd-du-18-novembre-2026/">Zoom sur les meilleures ventes de BD du 18 novembre 2026</a>'''
        self.assertIn('18-novembre-2026',latest_bdzoom_url(html))
    def test_no_period_invented(self):
        with self.assertRaises(SourceError):dates_semaine('Top 20 BD du 18 novembre 2026')

if __name__=='__main__': unittest.main()
