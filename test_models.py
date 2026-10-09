"""Models acceptance: isolated SQLite and loopback HTTP only, no paid services."""
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.request
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from core import Cancelled, Model, Store, Transport, UserError
from desktop import Service, make_server
from models import TASKS
from remote import companion_data


class ModelTests(unittest.TestCase):
    def setUp(self):
        Path('build').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='build',prefix='models-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.service=Service(Store(self.root/'data'))
        self.addCleanup(self.service.close)
        self.manager=self.service.models
        self.seen=[]
        seen=self.seen
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append({'path':self.path,'auth':self.headers.get('Authorization'),'body':body})
                if body.get('tools'):
                    msg={'content':None,'tool_calls':[{'id':'probe','type':'function','function':{'name':'probe_source','arguments':'{}'}}]}
                elif 'capacity' in body['messages'][-1]['content']:
                    msg={'content':'{"capacity":8,"overflow":"reject"}'}
                else:msg={'content':'连接成功'}
                raw=json.dumps({'choices':[{'finish_reason':'stop','message':msg}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.base=f'http://127.0.0.1:{server.server_port}/v1'
        self.a=self.save('本地 Ollama','local',vendor='Ollama',is_default=True)
        self.b=self.save('兼容研究模型','research',api_key='models-fixture-private-key')

    def save(self,name,model,**extra):
        return self.manager.save({'name':name,'model':model,'base_url':self.base,'capabilities':list(TASKS),**extra})

    def routes(self,enabled=False):
        return self.manager.save_routes({t:{'primary_id':self.a['id'],'backup_id':self.b['id'],'fallback_enabled':enabled} for t in TASKS})

    def test_two_profiles_routes_dpapi_restart_and_public_boundary(self):
        routes=self.routes()
        routes['research']['primary_id']=self.b['id'];routes['research']['backup_id']=self.a['id']
        self.manager.save_routes(routes)
        with self.service.store.connect() as db:
            cipher=db.execute('SELECT secret FROM model_profiles WHERE id=?',(self.b['id'],)).fetchone()[0]
        self.assertTrue(cipher);self.assertNotEqual(cipher,'models-fixture-private-key')
        public=json.dumps(self.service.bootstrap())
        for secret in ('models-fixture-private-key',cipher,'"secret"','"api_key"'):self.assertNotIn(secret,public)
        restored=Service(Store(self.root/'data'));self.addCleanup(restored.close)
        self.assertEqual(len(restored.models.list_public()),2)
        self.assertEqual(restored.models.resolve('research')['model'],'research')
        self.assertEqual(restored.models.resolve('chat')['model'],'local')
        self.assertEqual(restored.models.resolve('research')['api_key'],'models-fixture-private-key')
        self.assertFalse(restored.models.routes_public()['research']['fallback_enabled'])

    def test_real_loopback_connection_chat_research_behavior_and_headers(self):
        self.assertTrue(self.service.dispatch('model_test_connection',{'id':self.a['id'],'task':'chat'})['ok'])
        self.assertTrue(self.service.dispatch('model_test_capabilities',{'id':self.a['id'],'task':'chat'})['ok'])
        result=self.service.dispatch('model_test_capabilities',{'id':self.b['id'],'task':'research'})
        self.assertTrue(result['ok']);self.assertEqual(len(result['checks']),2)
        for request in self.seen:
            self.assertNotIn('models-fixture-private-key',json.dumps(request['body']))
            if request['body']['model']=='research':self.assertEqual(request['auth'],'Bearer models-fixture-private-key')
            else:self.assertIsNone(request['auth'])
            self.assertEqual(request['path'],'/v1/chat/completions')
        items={m['id']:m for m in self.manager.list_public()}
        self.assertEqual(items[self.a['id']]['metrics']['request_count'],2)
        self.assertEqual(items[self.b['id']]['metrics']['request_count'],2)
        self.assertGreater(items[self.b['id']]['metrics']['estimated_tokens'],0)
        self.assertGreater(items[self.b['id']]['metrics']['avg_latency_ms'],0)

    def test_capability_self_claim_is_not_success(self):
        with patch.object(Model,'_complete',return_value={'content':'我支持所有能力'}):
            result=self.manager.test(self.b['id'],'research',True)
        self.assertFalse(result['ok']);self.assertFalse(any(x['passed'] for x in result['checks']))

    def test_key_update_preservation_clear_and_single_default(self):
        b=self.manager.save({**self.b,'is_default':True,'api_key':''})
        self.assertEqual(sum(m['is_default'] for m in self.manager.list_public()),1)
        self.assertEqual(self.manager.resolve('chat',b['id'])['api_key'],'models-fixture-private-key')
        self.manager.save({**b,'clear_key':True})
        self.assertEqual(self.manager.resolve('chat',b['id'])['api_key'],'')

    def test_failure_redacts_errors_persists_metrics_and_partial_output(self):
        key='models-fixture-private-key'; output=[]
        def bad(model,messages,tools,on_text):
            on_text(key[:12]);on_text(key[12:]);raise UserError('Gateway echoed '+key)
        with patch.object(Model,'_complete',bad):
            with self.assertRaises(UserError) as error:
                Model(self.manager.resolve('chat',self.b['id']),Transport(threading.Event())).complete([],[],output.append)
        self.assertNotIn(key,str(error.exception));self.assertNotIn(key,''.join(output))
        data=json.dumps(self.service.dispatch('models_list',{}))
        self.assertNotIn(key,data);self.assertNotIn('Gateway echoed',data)
        restored=Service(Store(self.root/'data'));self.addCleanup(restored.close)
        metric=next(m for m in restored.models.list_public() if m['id']==self.b['id'])['metrics']
        self.assertEqual(metric['failure_count'],1);self.assertEqual(metric['request_count'],1)

    def test_stream_and_response_key_echo_never_enters_report_context(self):
        key='models-fixture-private-key';output=[]
        def echo(model,messages,tools,on_text):
            for value in ('prefix ',key[:8],key[8:],' suffix'):on_text(value)
            return {'content':'prefix '+key+' suffix'}
        with patch.object(Model,'_complete',echo):
            result=Model(self.manager.resolve('research',self.b['id']),Transport(threading.Event())).complete([],[],output.append)
        self.assertEqual(''.join(output),'prefix [凭据已隐藏] suffix')
        self.assertNotIn(key,json.dumps(result))

    def test_fallback_requires_switch_and_no_partial_or_uncertain_retry(self):
        calls=[]
        def fail_primary(model,messages,tools,on_text):
            calls.append(model.settings['profile_id'])
            if model.settings['profile_id']==self.a['id']:raise UserError('HTTP 429：额度不足。')
            return {'content':'备用回答'}
        self.routes(False)
        with patch.object(Model,'_complete',fail_primary):
            with self.assertRaises(UserError):Model(self.manager.resolve('chat'),Transport(threading.Event())).complete([],[],lambda _:None)
        self.assertEqual(calls,[self.a['id']]);calls.clear();self.routes(True)
        with patch.object(Model,'_complete',fail_primary):
            self.assertEqual(Model(self.manager.resolve('chat'),Transport(threading.Event())).complete([],[],lambda _:None)['content'],'备用回答')
        self.assertEqual(calls,[self.a['id'],self.b['id']])
        for error,partial in [(UserError('网络结果不确定'),False),(UserError('HTTP 503：失败'),True),(Cancelled(),False)]:
            calls.clear()
            def fail(model,messages,tools,on_text):
                calls.append(model.settings['profile_id'])
                if partial:on_text('已经输出')
                raise error
            with patch.object(Model,'_complete',fail):
                with self.assertRaises((UserError,Cancelled)):Model(self.manager.resolve('chat'),Transport(threading.Event())).complete([],[],lambda _:None)
            self.assertEqual(calls,[self.a['id']])

    def test_mobile_authorization_for_primary_backup_and_management(self):
        for action in ('models_list','model_save','model_delete','model_test_connection','model_test_capabilities','model_routes_save','settings'):
            with self.assertRaises(UserError):self.service.remote.dispatch(action,{'api_key':'hostile'})
        session=self.service.chats.create()
        with self.assertRaises(UserError):self.service.remote.dispatch('chat_start',{'session_id':session['id'],'text':'hello'})
        self.assertEqual(companion_data(self.service)['models'],[])
        self.manager.save({**self.a,'mobile_authorized':True})
        public=json.dumps(companion_data(self.service))
        for item in ('base_url','api_key','secret','models-fixture-private-key',self.b['name']):self.assertNotIn(item,public)
        with self.assertRaises(UserError):self.manager.resolve('research',self.b['id'],mobile=True)
        self.routes(True)
        with patch.object(Model,'_complete',side_effect=UserError('HTTP 429：拒绝')) as call:
            with self.assertRaises(UserError):Model(self.manager.resolve('chat',mobile=True),Transport(threading.Event())).complete([],[],lambda _:None)
            self.assertEqual(call.call_count,1)
        authorized=self.manager.resolve('chat',mobile=True)
        self.manager.save({**self.a,'mobile_authorized':False})
        with patch.object(Model,'_complete') as call:
            with self.assertRaises(UserError):Model(authorized,Transport(threading.Event())).complete([],[],lambda _:None)
            call.assert_not_called()

    def test_legacy_migration_keeps_cipher_and_permissions_off(self):
        store=Store(self.root/'legacy');store.save_settings({'base_url':self.base,'model':'legacy','api_key':'legacy-private'})
        original=store.get('settings')['secret']; service=Service(store);self.addCleanup(service.close)
        with store.connect() as db:self.assertEqual(db.execute('SELECT secret FROM model_profiles').fetchone()[0],original)
        self.assertEqual(service.models.resolve('chat')['api_key'],'legacy-private')
        self.assertFalse(service.models.list_public()[0]['mobile_authorized'])

    def test_task_route_rejects_missing_capability_and_invalid_switch(self):
        chat=self.manager.save({**self.a,'capabilities':['chat']})
        with self.assertRaises(UserError):self.manager.resolve('research',chat['id'])
        with self.assertRaises(UserError):self.routes()
        with self.assertRaises(UserError):self.manager.save_routes({'chat':{'primary_id':self.b['id'],'fallback_enabled':True}})

    def test_http_initialization_and_research_report_exclude_secrets(self):
        routes=self.routes();routes['research']['primary_id']=self.b['id'];routes['research']['backup_id']=self.a['id'];self.manager.save_routes(routes)
        server=make_server(self.service,'models-fixture')
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}/models-fixture/'
        def request(action,body=None):
            req=urllib.request.Request(base+'api',data=json.dumps({'action':action,'body':body or {}}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=3) as response:return json.load(response)
        for asset in ('models.js','models.css'):
            with urllib.request.urlopen(base+asset) as response:self.assertGreater(len(response.read()),100)
        raw=json.dumps(request('bootstrap'));self.assertNotIn('models-fixture-private-key',raw);self.assertNotIn('"api_key"',raw);self.assertNotIn('"secret"',raw)
        job=request('start',{'material':'队列容量为8，满时拒绝。'})
        until=time.monotonic()+3
        while time.monotonic()<until:
            poll=request('poll',job)
            if poll['state']!='running':break
            time.sleep(.02)
        self.assertEqual(poll['state'],'done')
        report=self.service.store.report(poll['result']['id'])
        for secret in ('models-fixture-private-key','"api_key"','"_manager"','"secret"'):self.assertNotIn(secret,json.dumps(report))
        self.assertEqual(self.seen[-1]['body']['model'],'research')


if __name__=='__main__':unittest.main()
