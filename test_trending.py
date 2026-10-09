import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core import Store,UserError
from trending import Trending,TrendingParser
HTML='''<article class="Box-row"><h2><a href="/owner/project">owner / project</a></h2><p>Queue &amp; cache</p><span itemprop="programmingLanguage">Python</span><a href="/owner/project/stargazers">12,345</a><span class="float-sm-right">123 stars today</span></article>'''
class TrendingTests(unittest.TestCase):
 def test_parser_and_fixed_links(self):
  p=TrendingParser();p.feed(HTML);self.assertEqual(p.items[0]['name'],'owner/project');self.assertEqual(p.items[0]['period_stars'],'123 stars today');self.assertEqual(p.items[0]['description'],'Queue & cache')
  p=TrendingParser();p.feed(HTML.replace('/owner/project"','https://evil.test/x"'));self.assertEqual(p.items,[])
 def test_period_cache_refresh_failure_and_restart(self):
  with tempfile.TemporaryDirectory() as d:
   t=Trending(Store(Path(d)))
   with patch('trending.Transport.read',return_value=HTML.encode()) as read:
    a=t.get('daily');self.assertFalse(a['cached']);self.assertTrue(t.get('daily')['cached']);self.assertEqual(read.call_count,1)
    t.get('weekly');self.assertEqual(read.call_count,2)
   restored=Trending(Store(Path(d)))
   with patch('trending.Transport.read',side_effect=UserError('offline')):
    self.assertTrue(restored.get('daily',True)['stale'])
    with self.assertRaises(UserError):restored.get('monthly')
    with self.assertRaises(UserError):restored.get('other')
