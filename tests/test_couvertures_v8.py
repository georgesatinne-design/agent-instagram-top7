"""Tests du nouveau collecteur de couvertures : aucune requête Internet."""
import io, tempfile, unittest
from pathlib import Path
from PIL import Image
from sources.couvertures import (meme_livre, match_catalog, parse_catalogue_images,
                                search_bede_catalog, search_google_books, download_cover)

BOOKS=[
 {'rang':1,'titre':'Lucky Luke (Les Aventures de… d’après Morris) T12 : Saint Lucky Luke'},
 {'rang':2,'titre':'Gaston T23 : Des boum et des paf'},
 {'rang':3,'titre':'Blake et Mortimer HS : Affaires classées'},
 {'rang':7,'titre':'Brume T5 : La Cité d’YS'},
]
ALTS=[
 'Les Aventures de Lucky Luke d’après Morris - Tome 12 - Saint Lucky Luke - Lucky Comics',
 'Gaston Lagaffe - Tome 23 - Des Boum et des Paf - Dupuis',
 'Blake & Mortimer - Hors-série - Tome 15 - Affaires classées',
 'Brume tome 5 : la cite d’ys',
]
class CoverTests(unittest.TestCase):
 def test_titles_normalized_but_wrong_tome_rejected(self):
  for b,a in zip(BOOKS,ALTS):self.assertTrue(meme_livre(b['titre'],a),(b,a))
  self.assertFalse(meme_livre('Brume T5 : La cite d’Ys','Brume Tome 4 : La cite d’Ys'))
  self.assertFalse(meme_livre('Mortelle Adèle et les labyrinthes de papier','Mortelle Adèle : Les reliques du chat lune'))
 def test_catalog_matching_rejects_ambiguous(self):
  candidates=[{'alt':a,'couverture_url':f'https://cdn.bede.fr/{i}.jpg'} for i,a in enumerate(ALTS)]
  match=match_catalog(BOOKS,candidates)
  self.assertEqual(len(match),4)
  self.assertTrue(match[2]['url'].endswith('1.jpg'))
  match=match_catalog([BOOKS[0]],[candidates[0],{'alt':ALTS[0], 'couverture_url':'https://cdn.bede.fr/edition2.jpg'}])
  self.assertEqual(match,{})
 def test_parser_and_search_uses_other_bede_pages(self):
  html='<img alt="Gaston Lagaffe - Tome 23 - Des Boum et des Paf - Dupuis" src="https://cdn.bede.fr/23.jpg">'
  parsed=parse_catalogue_images(html,'https://www.bede.fr/sorties-bd-dupuis')
  self.assertEqual(len(parsed),1)
  found,errors=search_bede_catalog([BOOKS[1]],fetcher=lambda url:html,index={'classement_general':[]})
  self.assertIn(2,found)
  self.assertEqual(errors,[])
 def test_image_download_requires_real_image_and_safe_hostname(self):
  img=Image.new('RGB',(300,450),'red');raw=io.BytesIO();img.save(raw,format='JPEG')
  class MockResponse:
   url='https://cdn.bede.fr/ok.jpg'
   content=raw.getvalue()
   headers={'Content-Type':'image/jpeg'}
   def raise_for_status(self):pass
  with tempfile.TemporaryDirectory() as d:
   ok,msg=download_cover(BOOKS[1],{2:{'url':'https://cdn.bede.fr/ok.jpg','reference':ALTS[1]}},Path(d),getter=lambda url,**kw:MockResponse())
   self.assertTrue(ok,msg)
   self.assertEqual(len(list(Path(d).glob('*.png'))),1)
 def test_google_metadata_only_matching(self):
  class Response:
   def raise_for_status(self):pass
   def json(self):return {'items':[{'volumeInfo':{'title':'Brume', 'subtitle':'La Cité d’Ys', 'imageLinks':{'thumbnail':'http://books.google.com/cover?id=1'}}}]}
  # API result lacking a tome is accepted only when the series and subtitle match;
  # this remains a candidate and must subsequently pass image/host validation.
  candidate=search_google_books(BOOKS[3],getter=lambda url,**kw:Response())
  self.assertEqual(candidate['url'],'https://books.google.com/cover?id=1')
if __name__=='__main__':unittest.main()
