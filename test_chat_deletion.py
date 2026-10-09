import tempfile
import unittest
from pathlib import Path
from core import Store, UserError
from desktop import Service

class ChatDeletionTests(unittest.TestCase):
    def test_delete_restore_persist_and_preserve_transcript_and_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Store(Path(directory)))
            session=service.chats.get(service.chats.create()['id'],internal=True)
            session['messages']=[{'role':'user','content':'保留这段内容'}]
            service.chats.save(session)
            report_id=service.store.save_report('测试报告','保留报告',{},[])
            service.dispatch('chat_delete',{'id':session['id']})
            restarted=Service(Store(Path(directory)))
            self.assertEqual(restarted.chats.list(),[])
            with self.assertRaises(UserError):restarted.dispatch('chat_get',{'id':session['id']})
            self.assertEqual(restarted.dispatch('chat_trash',{})['sessions'][0]['id'],session['id'])
            restored=restarted.dispatch('chat_restore',{'id':session['id']})
            self.assertEqual(restored['messages'],session['messages'])
            self.assertEqual(restarted.store.report(report_id)['report'],'保留报告')
            with self.assertRaises(UserError):restarted.dispatch('chat_restore',{'id':session['id']})
            with self.assertRaises(UserError):restarted.dispatch('chat_delete',{'id':True})

    def test_active_reply_blocks_deletion_including_phone(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Store(Path(directory)));session=service.chats.create()
            service.chat_job={'state':'running','session_id':session['id']}
            with self.assertRaises(UserError):service.remote.dispatch('chat_delete',{'id':session['id']})
            self.assertEqual(len(service.chats.list()),1)
            service.chat_job['state']='done'
            service.remote.dispatch('chat_delete',{'id':session['id']})
            self.assertEqual(len(service.remote.dispatch('chat_trash',{})['sessions']),1)
            service.remote.dispatch('chat_restore',{'id':session['id']})
            self.assertEqual(len(service.chats.list()),1)

if __name__=='__main__':unittest.main()
