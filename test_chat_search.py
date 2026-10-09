import tempfile
import unittest
from pathlib import Path
from core import Store,UserError
from desktop import Service
class SearchTests(unittest.TestCase):
 def test_content_title_material_deleted_persistence_and_literal(self):
  with tempfile.TemporaryDirectory() as d:
   service=Service(Store(Path(d)));a=service.chats.create();a=service.chats.get(a['id'],internal=True)
   a['title']='队列笔记';a['messages']=[{'role':'user','content':'看看 KV Cache','material':'附加材料 token%_你好'},{'role':'assistant','content':'这是背压和取消。'}];service.chats.save(a)
   for query,field,index in [('cache','content',0),('背压','content',1),('token%_','material',0)]:
    r=service.dispatch('chat_search',{'query':query})['sessions'];self.assertEqual(r[0]['id'],a['id']);self.assertEqual(r[0]['field'],field);self.assertEqual(r[0]['message_index'],index)
   self.assertEqual(service.chats.search('队列')['sessions'][0]['message_index'],None)
   self.assertEqual(service.chats.search('不存在')['sessions'],[])
   self.assertEqual(service.chats.search('')['sessions'],[])
   service=Service(Store(Path(d)));self.assertEqual(len(service.remote.dispatch('chat_search',{'query':'CACHE'})['sessions']),1)
   service.chats.delete(a['id']);self.assertEqual(service.chats.search('背压')['sessions'],[])
   service.chats.restore(a['id']);self.assertEqual(len(service.chats.search('背压')['sessions']),1)
   for q in [True,None,'x'*161]:
    with self.assertRaises(UserError):service.chats.search(q)
