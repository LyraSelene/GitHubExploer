import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from chat import ChatStore, DEFAULT_AGENT, agent_config, converse, trim_turns
from core import Cancelled, Store, UserError
from desktop import Service


def call(name, args, identifier='fixture-call'):
    return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': identifier, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}


class ChatTests(unittest.TestCase):
    def wait_job(self, service):
        for _ in range(200):
            with service.lock:
                if service.chat_job['state'] != 'running': return dict(service.chat_job)
            time.sleep(.01)
        self.fail('chat worker timeout')

    def test_role_import_validation_and_session_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)); service = Service(store)
            session = service.dispatch('chat_new', {})
            service.dispatch('chat_agent', {'name': '自定义伙伴', 'prompt': '练习队列'})
            new = service.dispatch('chat_new', {})
            self.assertEqual(session['agent'], DEFAULT_AGENT)
            self.assertEqual(new['agent']['name'], '自定义伙伴')
            self.assertEqual(ChatStore(Store(Path(directory))).get(new['id']), new)
            for bad in [{}, {'name': 'x', 'prompt': ''}, {'name': 1, 'prompt': 'x'}, {'name': 'x', 'prompt': 'x'*12001}]:
                with self.assertRaises(UserError): agent_config(bad)
            renamed = service.dispatch('chat_rename', {'id': session['id'], 'title': '学习队列'})
            self.assertEqual(renamed['title'], '学习队列')
            self.assertNotIn('turns', service.dispatch('chat_get', {'id': session['id']}))

    def test_tool_result_then_reply_and_memory_across_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)); chats = ChatStore(store)
            report_id = store.save_report('队列研究', '真实测试夹具的报告内容', {}, [])
            session = chats.get(chats.create()['id'], internal=True)
            seen = []
            class FixtureModel:
                def __init__(self, *args): pass
                def complete(self, messages, tools, on_text):
                    seen.append(copy.deepcopy(messages))
                    if len(seen) == 1: return call('read_local_report', {'id': report_id})
                    self.assert_reply(messages)
                    on_text('基于报告讨论取消。')
                    return {'role': 'assistant', 'content': '基于报告讨论取消。'}
                def assert_reply(self, messages):
                    assert '真实测试夹具的报告内容' in messages[-1]['content']
            events = []
            with patch('chat.Model', FixtureModel):
                result = converse({}, store, session, '看看报告', '', True, True, threading.Event(), lambda k,v: events.append((k,v)))
            self.assertEqual(result['answer'], '基于报告讨论取消。')
            self.assertEqual(seen[-1][-1]['tool_call_id'], 'fixture-call')
            self.assertEqual(len(result['evidence']), 1)
            self.assertEqual(len([e for e in events if e[0] == 'tool']), 2)
            session['turns'] = result['turns']
            class NextModel:
                def __init__(self, *args): pass
                def complete(self, messages, tools, on_text):
                    seen.append(copy.deepcopy(messages)); return {'role':'assistant', 'content':'继续'}
            with patch('chat.Model', NextModel):
                converse({}, store, session, '接着聊', '', False, True, threading.Event(), lambda *a: None)
                self.assertTrue(any(m.get('tool_call_id') == 'fixture-call' for m in seen[-1]))
                converse({}, store, session, '关闭本机读取', '', True, False, threading.Event(), lambda *a: None)
                self.assertFalse(any(m.get('tool_call_id') == 'fixture-call' for m in seen[-1]))
                self.assertNotIn('真实测试夹具的报告内容', json.dumps(seen[-1], ensure_ascii=False))

    def test_unauthorized_local_tools_are_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)); chats = ChatStore(store)
            session = chats.get(chats.create()['id'], internal=True)
            replies = [call('read_local_report', {'id': 1}), {'role': 'assistant', 'content': '没有权限'}]
            class FixtureModel:
                def __init__(self, *args): pass
                def complete(self, messages, tools, on_text): return replies.pop(0)
            with patch('chat.Model', FixtureModel), patch.object(store, 'report', side_effect=AssertionError('unauthorized read')):
                result = converse({}, store, session, '你好', '', True, False, threading.Event(), lambda *a: None)
            self.assertIn('未启用', result['turns'][0][-2]['content'])

    def test_failed_and_cancelled_turns_preserve_history_without_partial_context(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)); store.save_settings({'base_url':'https://example.com/v1','model':'fixture','api_key':''})
            service = Service(store); session = service.dispatch('chat_new', {})
            def success(*args):
                args[-1]('token', '完整回复')
                return {'answer': '完整回复', 'turns': [[{'role':'user','content':'你好'},{'role':'assistant','content':'完整回复'}]], 'evidence':[]}
            with patch('desktop.converse', success):
                service.start_chat({'session_id':session['id'],'text':'你好'})
                job = self.wait_job(service)
            self.assertEqual(job['state'], 'done')
            with patch('desktop.converse', side_effect=UserError('测试失败')):
                service.start_chat({'session_id':session['id'],'text':'第二条'})
                job = self.wait_job(service)
            self.assertEqual(job['state'], 'error')
            self.assertEqual(len(service.chats.get(session['id'], True)['turns']), 1)
            started = threading.Event()
            def blocked(*args):
                started.set(); cancel=args[-2]
                self.assertTrue(cancel.wait(2)); raise Cancelled()
            with patch('desktop.converse', blocked):
                result=service.start_chat({'session_id':session['id'],'text':'停止这轮'})
                self.assertTrue(started.wait(1))
                with self.assertRaises(UserError): service.start_chat({'session_id':session['id'],'text':'并发'})
                service.dispatch('chat_cancel', {'job_id':result['job_id']})
                job=self.wait_job(service)
            self.assertEqual(job['state'], 'cancelled')
            reboot=Service(Store(Path(directory)))
            saved=reboot.chats.get(session['id'], True)
            self.assertEqual(len(saved['messages']), 4)
            self.assertEqual(len(saved['turns']), 1)
            self.assertEqual(reboot.store.reports(), [])

    def test_context_trimming_keeps_complete_tool_turns(self):
        turns = [[{'role':'user','content':'x'*20},call('search_github', {'query':'x','language':''}),
                  {'role':'tool','tool_call_id':'fixture-call','content':'result'}, {'role':'assistant','content':str(i)}] for i in range(12)]
        kept=trim_turns(turns)
        self.assertEqual(len(kept), 8)
        self.assertEqual(kept[0][-1]['content'], '4')
        self.assertEqual(trim_turns(turns, 1), [])

    def test_tools_disabled_and_cancel_before_request(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)); chats=ChatStore(store); session=chats.get(chats.create()['id'],True)
            class FixtureModel:
                def __init__(self, *args): pass
                def complete(self, messages, tools, on_text):
                    assert tools == []; return call('search_github', {'query':'x','language':''})
            with patch('chat.Model',FixtureModel):
                with self.assertRaises(UserError): converse({},store,session,'hi','',False,False,threading.Event(),lambda *a:None)
                cancelled=threading.Event();cancelled.set()
                with self.assertRaises(Cancelled): converse({},store,session,'hi','',False,False,cancelled,lambda *a:None)


if __name__ == '__main__': unittest.main()
