"""Task/automation persistence, cancellation and idempotency on isolated DBs."""
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from core import Store, Model, UserError
from desktop import Service
from tasks import now, stamp, date_time
from test_materials import pdf_fixture


class TasksTests(unittest.TestCase):
    def setUp(self):
        Path('build').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='tasks-test-',dir='build')
        self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.service=Service(Store(self.root/'data'));self.addCleanup(self.service.close)
        self.store=self.service.store;self.tasks=self.service.tasks
        self.report=self.store.save_report('原有报告','# Original untouched\n请求应排队。',{},[{'path':'queue.py'}])
        self.note=self.service.notes.create('原有笔记','这是待验证的假设。')
        self.store.set('settings',{'base_url':'http://localhost:9/v1','model':'fixture'})

    def prepare(self,workflow='weekly',key='fixture',**values):
        return self.tasks.prepare({'workflow':workflow,'request_id':key,'start':stamp(now()-timedelta(days=7)),
            'end':stamp(now()+timedelta(minutes=1)),**values})

    def wait(self,ident):
        end=time.monotonic()+4
        while time.monotonic()<end:
            result=self.tasks.run_get(ident)
            if result['status'] not in {'ready','running'}:
                while self.tasks.active and time.monotonic()<end:time.sleep(.005)
                return result
            time.sleep(.01)
        self.fail('Worker did not finish')

    def task(self,**values):
        return self.tasks.create({'title':'每周队列练习','description':'追踪入口到出队','tags':'推理, 队列',
            'priority':'high','due_at':stamp(now()-timedelta(days=1)),'recurrence':'weekly',
            'links':[{'type':'report','id':self.report}],**values})

    def test_weekly_task_completion_calendar_inputs_and_restart(self):
        task=self.task()
        self.assertEqual(task['recurrence'],'weekly'); self.assertEqual(task['links'][0]['title'],'原有报告')
        self.assertEqual(self.tasks.list({'view':'overdue'})['overdue_count'],1)
        done=self.service.dispatch('task_complete',{'id':task['id'],'revision':task['revision']})
        self.assertEqual(done['status'],'todo');self.assertGreater(date_time(done['due_at']),now())
        self.assertEqual((date_time(done['due_at'])-date_time(task['due_at'])).days,7)
        self.assertEqual(len(self.tasks.list()['events']),1)
        with self.assertRaises(UserError):self.service.dispatch('task_complete',{'id':task['id'],'revision':task['revision']})
        edited=self.tasks.update(task['id'],{'revision':done['revision'],'title':'Edited','tags':['取消'],'priority':'urgent'})
        self.assertEqual(edited['title'],'Edited')
        reopened=Service(Store(self.root/'data'));self.addCleanup(reopened.close)
        self.assertEqual(reopened.tasks.get(task['id'])['links'],task['links'])
        self.assertEqual(len(reopened.tasks.list()['events']),1)
        self.assertEqual(reopened.tasks.list()['overdue_count'],0)
        with self.assertRaises(UserError):self.task(recurrence='custom',custom_interval=0)
        custom=self.task(recurrence='custom',custom_interval=3,custom_unit='hour',due_at=stamp(now()-timedelta(hours=1)))
        custom=self.tasks.update(custom['id'],{'status':'done','revision':1})
        self.assertGreater(date_time(custom['due_at']),now())

    def test_weekly_uses_period_and_learning_events_and_idempotent_report(self):
        task=self.task(); self.tasks.update(task['id'],{'status':'done','revision':1})
        with self.store.connect() as db:
            db.execute("INSERT INTO reports(title,created,report,context,evidence) VALUES(?,?,?,?,?)",('outside','2001-01-01 00:00','secretOutside','{}','[]'))
        learning={'title':'取消任务','reading':'queue.py','question':'为什么排队','exercise':'写队列','acceptance':'取消后不输出'}
        pid=self.store.save_learning(self.report,{'owner':'fixture','name':'queue','commit':'fixed'},'queue',[learning])
        self.store.update_learning_task(pid,0,'进行中','今天读入口')
        prepared=self.prepare()
        self.assertNotIn('secretOutside',json.dumps(prepared))
        self.assertEqual(len(prepared['input']['learning_events']),1)
        with patch.object(Model,'complete') as call:
            self.tasks.start(prepared['id']);finished=self.wait(prepared['id']);call.assert_not_called()
        self.assertEqual(finished['status'],'succeeded');self.assertIn('今天读入口',finished['result'])
        self.assertIn('原有报告',finished['result']);self.assertIn('当前快照',finished['result'])
        before=len(self.store.reports())
        repeated=self.prepare();self.tasks.start(repeated['id'])
        self.assertEqual(repeated['id'],prepared['id']);self.assertEqual(len(self.store.reports()),before)
        reopened=Service(Store(self.root/'data'));self.addCleanup(reopened.close)
        self.assertEqual(reopened.tasks.run_get(prepared['id'])['report_id'],finished['report_id'])
        self.assertEqual(self.store.report(self.report)['report'],'# Original untouched\n请求应排队。')

    def test_cancel_mid_execution_persists_and_creates_no_report(self):
        entered=threading.Event();release=threading.Event()
        original=self.tasks.local_result
        def blocked(item,job):
            entered.set();release.wait(3);return original(item,job)
        prepared=self.prepare()
        with patch.object(self.tasks,'local_result',blocked):
            self.tasks.start(prepared['id']);self.assertTrue(entered.wait(2))
            cancelled=self.tasks.cancel(prepared['id']);self.assertEqual(cancelled['status'],'cancelled')
            self.assertIsNone(cancelled['report_id']);release.set();self.wait(prepared['id'])
        reopened=Service(Store(self.root/'data'));self.addCleanup(reopened.close)
        self.assertEqual(reopened.tasks.run_get(prepared['id'])['status'],'cancelled')
        self.assertEqual(len(self.store.reports()),1)

    def test_successful_model_call_and_publish_retry_do_not_resend(self):
        prepared=self.prepare('error',input='Traceback: queue full')
        with self.assertRaises(UserError):self.tasks.start(prepared['id'])
        original=self.tasks.publish;failures=[1]
        def fails_once(ident,job):
            if failures:failures.pop();raise RuntimeError('Commit failed')
            return original(ident,job)
        with patch.object(Model,'complete',return_value={'content':'# 原因分析\n可能队列容量不足。'}) as call,patch.object(self.tasks,'publish',fails_once):
            self.tasks.start(prepared['id'],True);failed=self.wait(prepared['id'])
            self.assertEqual(failed['status'],'failed');self.assertTrue(failed['can_retry'])
            self.tasks.start(prepared['id']);done=self.wait(prepared['id'])
            self.assertEqual(done['status'],'succeeded');self.assertEqual(call.call_count,1)
            self.tasks.start(prepared['id'],True);self.assertEqual(call.call_count,1)
        self.assertEqual(len(self.store.reports()),2)

    def test_ambiguous_network_result_never_retries_explicit_http_refusal_can_retry(self):
        prepared=self.prepare('error',input='error')
        with patch.object(Model,'complete',side_effect=UserError('无法连接服务。')) as call:
            self.tasks.start(prepared['id'],True);result=self.wait(prepared['id'])
            self.assertEqual(result['status'],'uncertain');self.assertFalse(result['can_retry'])
            self.tasks.start(prepared['id'],True);self.assertEqual(call.call_count,1)
        another=self.prepare('error','refused',input='error')
        with patch.object(Model,'complete',side_effect=[UserError('HTTP 429：请求过多。'),{'content':'# Analysis'}]) as call:
            self.tasks.start(another['id'],True);failure=self.wait(another['id'])
            self.assertTrue(failure['can_retry']);self.tasks.start(another['id'],True)
            self.assertEqual(self.wait(another['id'])['status'],'succeeded');self.assertEqual(call.call_count,2)

    def test_ppt_sources_page_and_idle_task(self):
        path=self.root/'source.pdf';pdf_fixture(path);ident=self.service.library.import_paths([path])['items'][0]['id']
        with self.assertRaises(UserError):self.prepare('ppt')
        prepared=self.prepare('ppt',sources=[{'type':'material','id':ident,'page':2}])
        self.assertEqual(prepared['sources'][0]['page'],2);self.assertIn('pdfneedle',prepared['sources'][0]['text'])
        with patch.object(Model,'complete',return_value={'content':'# 大纲\n## 第1页\n内容\n演讲备注\n来源：PDF 第2页'}) as call:
            self.tasks.start(prepared['id'],True);self.assertEqual(self.wait(prepared['id'])['status'],'succeeded')
            self.assertIn('pdfneedle',json.dumps(call.call_args.args[0]));self.assertEqual(call.call_args.args[1],[])
        task={'title':'队列入口','reading':'queue.py','question':'如何排队','exercise':'实现队列','acceptance':'检查取消'}
        self.store.save_learning(self.report,{'owner':'fixture','name':'queue','commit':'fixed'},'queue',[task])
        idle=self.prepare('idle','idle')
        self.tasks.start(idle['id']);out=self.wait(idle['id'])['result'];self.assertIn('15–30',out);self.assertIn('queue.py',out)

    def test_automation_default_off_occurrence_idempotent_and_persisted(self):
        first=stamp(now()-timedelta(hours=1))
        plan=self.tasks.automation_create({'workflow':'weekly','name':'每周汇总','recurrence':'weekly','next_run':first,'days':7})
        self.assertFalse(plan['enabled']);self.assertFalse(self.tasks.automation_list()['enabled'])
        self.tasks.tick();self.assertEqual(self.tasks.runs(),[])
        self.tasks.automation_toggle({'id':plan['id'],'enabled':True});self.tasks.tick();self.assertEqual(self.tasks.runs(),[])
        self.tasks.automation_toggle({'enabled':True});self.tasks.tick()
        run=self.tasks.runs()[0];self.wait(run['id']);self.tasks.tick()
        self.assertEqual(len(self.tasks.runs()),1);self.assertGreater(date_time(self.tasks.automation_list()['automations'][0]['next_run']),now())
        reopened=Service(Store(self.root/'data'));self.addCleanup(reopened.close)
        self.assertTrue(reopened.tasks.automation_list()['enabled']);self.assertEqual(len(reopened.tasks.runs()),1)
        for action in ('tasks_list','workflow_start','automation_toggle'):
            with self.assertRaises(UserError):self.service.remote.dispatch(action,{})

    def test_crash_recovery_cached_response_and_remote_inflight(self):
        ready=self.prepare('error',input='queue error')
        with self.store.connect() as db:
            db.execute("UPDATE workflow_runs SET status='running',request_state='dispatched' WHERE id=?",(ready['id'],))
        reopened=Service(Store(self.root/'data'));self.addCleanup(reopened.close)
        self.assertEqual(reopened.tasks.run_get(ready['id'])['status'],'uncertain')
        done=self.prepare('error','cache',input='queue error')
        with self.store.connect() as db:db.execute("UPDATE workflow_runs SET status='running',request_state='responded',result='# Cached response' WHERE id=?",(done['id'],))
        reopened2=Service(Store(self.root/'data'));self.addCleanup(reopened2.close)
        with patch.object(Model,'complete') as call:
            reopened2.tasks.start(done['id']);limit=time.monotonic()+3
            while reopened2.tasks.run_get(done['id'])['status']=='running' and time.monotonic()<limit:time.sleep(.01)
            self.assertEqual(reopened2.tasks.run_get(done['id'])['status'],'succeeded');call.assert_not_called()


if __name__=='__main__':unittest.main()
