"""Tests sans web, sans secrets et sans appel Buffer."""
import io,sys,types,unittest,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import illyadera_covers as c

class FakeResponse:
 def __init__(self,url,content=None,mime='image/jpeg',data=None):
  self.url=url;self.content=content if content is not None else b'';self.headers={'Content-Type':mime};self._json=data
 def raise_for_status(self):pass
 def json(self):return self._json

def jpg():
 b=io.BytesIO();Image.new('RGB',(350,520),'#DD5533').save(b,'JPEG');return b.getvalue()

class CoverTests(unittest.TestCase):
 def test_isbn_validity(self):
  self.assertEqual(c.isbn13({'ean':'9782344071120'}),'9782344071120')
  self.assertEqual(c.isbn13({'ean':'9782344071121'}),'')
  self.assertEqual(c.isbn13({'ean':'bad'}),'')
 def test_title_and_volume(self):
  self.assertTrue(c.title_agrees('Blue Lock T35','Blue Lock Tome 35'))
  self.assertFalse(c.title_agrees('Blue Lock T35','Blue Lock Tome 34'))
  self.assertFalse(c.title_agrees('L’Atelier des sorciers T6','Blue Lock Tome 6'))
 def test_reject_unexpected_host(self):
  self.assertFalse(c._safe('https://attacker.invalid/cover.jpg'))
  self.assertFalse(c._safe('http://covers.openlibrary.org/cover.jpg'))
 def test_fallback_openlibrary_exact_isbn(self):
  book={'rang':1,'titre':'Blue Lock T35','ean':'9782344071120'}
  def get(url,**kwargs):
   if url=='https://openlibrary.org/isbn/9782344071120.json':return FakeResponse(url,mime='application/json',data={'title':'Blue Lock tome 35','isbn_13':['9782344071120']})
   if 'openlibrary.org' in url:return FakeResponse(url,jpg())
   raise RuntimeError('Should not need other suppliers')
  # _candidates generator is lazy, so first successful cover doesn't call Google.
  mod=types.ModuleType('sources');covers=types.ModuleType('sources.couvertures')
  covers.cover_path=lambda d,t:Path(d)/(hashlib.sha256(t.encode()).hexdigest()[:20]+'.png')
  with tempfile.TemporaryDirectory() as td, patch.dict(sys.modules,{'sources':mod,'sources.couvertures':covers}):
   result=c.resolve_cover(book,td,get=get)
   self.assertTrue(result['ok'],result)
   self.assertEqual(result['source'],'Open Library — ISBN exact')
   self.assertTrue(Path(result['chemin']).is_file())
   second=c.resolve_cover(book,td,get=lambda **kwargs:(_ for _ in ()).throw(RuntimeError('cache expected')))
   self.assertTrue(second['ok'])
 def test_fallback_google_does_not_accept_wrong_tome(self):
  book={'rang':1,'titre':'Blue Lock T35','ean':'9782344071120'}
  def get(url,**kwargs):
   if 'openlibrary.org' in url:raise ValueError('Missing')
   if url==c.GOOGLE:
    return FakeResponse(url,mime='application/json',data={'items':[{'volumeInfo':{
      'title':'Blue Lock Tome 34','industryIdentifiers':[{'type':'ISBN_13','identifier':book['ean']}],
      'imageLinks':{'large':'https://books.google.com/cover.png'}}}]})
   raise AssertionError(url)
  mod=types.ModuleType('sources');covers=types.ModuleType('sources.couvertures');covers.cover_path=lambda d,t:Path(d)/(t+'.png')
  with tempfile.TemporaryDirectory() as td, patch.dict(sys.modules,{'sources':mod,'sources.couvertures':covers}):
   r=c.resolve_cover(book,td,get=get)
   self.assertFalse(r['ok'])
 def test_no_ean_requires_match(self):
  book={'rang':3,'titre':'Brume T5 La Cité d’Ys'}
  def get(url,**kwargs):
   if url==c.GOOGLE:
    return FakeResponse(url,mime='application/json',data={'items':[
     {'volumeInfo':{'title':'Brume Tome 4 La Cité d’Ys','imageLinks':{'large':'https://books.google.com/wrong'}}},
     {'volumeInfo':{'title':'Brume Tome 5 La Cité d’Ys','imageLinks':{'large':'https://books.google.com/good'}}}
    ]})
   return FakeResponse(url,jpg())
  mod=types.ModuleType('sources');covers=types.ModuleType('sources.couvertures');covers.cover_path=lambda d,t:Path(d)/(hashlib.sha1(t.encode()).hexdigest()+'.png')
  with tempfile.TemporaryDirectory() as td, patch.dict(sys.modules,{'sources':mod,'sources.couvertures':covers}):
   result=c.resolve_cover(book,td,get=get)
   self.assertTrue(result['ok'])
   self.assertIn('titre vérifié',result['source'])
   self.assertEqual(result['url'],'https://books.google.com/good')
if __name__=='__main__': unittest.main()
