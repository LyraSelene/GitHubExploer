import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from core import Store, UserError
from desktop import Service

class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = Service(Store(Path(self.temp.name)))
        self.remote = self.service.remote
        self.status = self.remote.start(['127.0.0.1'], bind='127.0.0.1')
        self.base = self.status['urls'][0]
        self.cookie = ''

    def tearDown(self):
        self.service.close(); self.temp.cleanup()

    def request(self, path, value=None, headers=None):
        fields = {'Content-Type':'application/json'}
        if self.cookie: fields['Cookie'] = self.cookie
        fields.update(headers or {})
        request = urllib.request.Request(self.base+path, data=json.dumps(value).encode() if value is not None else None, headers=fields)
        return urllib.request.urlopen(request, timeout=3)

    def pair(self):
        with self.request('/pair', {'code': self.status['code']}) as result:
            self.cookie = result.headers['Set-Cookie'].split(';')[0]
            self.assertIn('HttpOnly', result.headers['Set-Cookie'])
            self.assertIn('SameSite=Strict', result.headers['Set-Cookie'])

    def test_pair_scope_secret_isolation_and_revocation(self):
        with self.request('/') as result: self.assertIn(b'pair-screen', result.read())
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api', {'action':'bootstrap'})
        self.assertEqual(error.exception.code, 401)
        self.pair()
        self.service.store.save_settings({'base_url':'https://example.com/v1','model':'fixture','api_key':'never-send-this-key'})
        report_id = self.service.store.save_report('Shared report', 'Saved text', {}, [])
        with self.request('/api', {'action':'bootstrap'}) as result:
            data = json.load(result)
            self.assertNotIn('never-send-this-key', json.dumps(data))
            self.assertNotIn('settings', data)
            self.assertEqual(data['reports'][0]['id'], report_id)
        with self.request('/api', {'action':'chat_new'}) as result: chat = json.load(result)
        self.assertEqual(self.service.chats.get(chat['id']), chat)
        for action in ['settings','chat_agent','remote_start','motion','open_url','shell']:
            with self.assertRaises(urllib.error.HTTPError): self.request('/api', {'action':action})
        for path in ['/desktop.py','/wallpaper.webp','/../core.py']:
            with self.assertRaises(urllib.error.HTTPError): self.request(path)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api', {'action':'bootstrap'}, {'Origin':'https://foreign.example'})
        self.assertEqual(error.exception.code, 403)
        self.remote.sessions.clear()
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api', {'action':'bootstrap'})
        self.assertEqual(error.exception.code, 401)
        self.pair()
        self.remote.sessions = {key:0 for key in self.remote.sessions}
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api', {'action':'bootstrap'})
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/', headers={'Host':'attacker.example'})
        self.assertEqual(error.exception.code, 403)

    def test_expiry_attempt_limit_and_restart(self):
        self.remote.code_until = 0
        for _ in range(5):
            with self.assertRaises(urllib.error.HTTPError) as error: self.request('/pair', {'code':self.status['code']})
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as error: self.request('/pair', {'code':'123456'})
        self.assertEqual(error.exception.code, 429)
        old_server = self.remote.server
        self.remote.stop()
        self.assertFalse(self.remote.status()['enabled'])
        self.assertEqual(self.remote.sessions, {})
        self.status = self.remote.start(['127.0.0.1'], bind='127.0.0.1'); self.base=self.status['urls'][0]
        self.assertIsNot(self.remote.server, old_server)
        self.pair()

    def test_remote_research_and_chat_use_shared_service(self):
        self.pair()
        self.service.store.save_settings({'base_url':'https://example.com/v1','model':'fixture','api_key':''})
        self.service.models._migrate_legacy()
        profile = self.service.models.list_public()[0]
        self.service.models.save({**profile, 'mobile_authorized':True})
        with self.request('/api', {'action':'chat_new'}) as result: session=json.load(result)
        complete = threading.Event()
        def converse(*args):
            args[-1]('token', 'Shared response')
            complete.set()
            return {'answer':'Shared response','turns':[],'evidence':[]}
        with patch('desktop.converse', converse):
            with self.request('/api', {'action':'chat_start','body':{'session_id':session['id'],'text':'hello','tools_enabled':False,'local_enabled':False}}) as result:
                job=json.load(result)
            self.assertTrue(complete.wait(2))
            with self.request('/api', {'action':'chat_poll','body':{'job_id':job['job_id']}}) as result:
                self.assertEqual(json.load(result)['text'], 'Shared response')
        self.assertEqual(self.service.chats.get(session['id'])['messages'][-1]['content'],'Shared response')
        def research(*args, **kwargs):
            return {'report':'Shared remote report','context':{'messages':[],'sources':{}},'evidence':[]}
        with patch('desktop.research', research):
            with self.request('/api', {'action':'start','body':{'material':'Remote test material'}}) as result:
                research_job=json.load(result)
            for _ in range(200):
                with self.request('/api', {'action':'poll','body':research_job}) as result:
                    snapshot=json.load(result)
                if snapshot['state']!='running': break
                threading.Event().wait(.01)
            self.assertEqual(snapshot['state'],'done')
            self.assertEqual(self.service.store.report(snapshot['result']['id'])['report'],'Shared remote report')

if __name__ == '__main__': unittest.main()
