"""End-to-end workflow fixtures, separate from live provider/network checks."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from core import Model, Store, UserError
from desktop import Service
from learning_flow import FIELDS

SHA='a'*40


def values():
    return [{**{k:'缓存机制 '+str(i) for k in FIELDS},'title':'单元 '+str(i),'answer':'return cache[key]',
        'evidence':[{'key':0,'symbol':'lookup','quote':'def lookup(key):\n    return cache[key]'}]} for i in range(3)]


class LearningFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='build',prefix='flow-test-');self.root=Path(self.temp.name)
        self.s=Service(Store(self.root));self.s.store.set('settings',{'base_url':'http://127.0.0.1:9/v1','model':'fixture'})
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.s.close)
        self.repo={'owner':'org','name':'repo','commit':SHA}
        self.evidence=[{'path':'cache.py','url':'https://github.com/org/repo/blob/'+SHA+'/cache.py#L1-L2',
            'start':1,'end':2,'excerpt':'def lookup(key):\n    return cache[key]'}]
        self.report=self.s.store.save_report('缓存','# 分析\n缓存命中返回已保存对象。',{'sources':{'repo':self.repo}},self.evidence)

    def wait(self):
        for _ in range(100):
            d=self.s.learning_flow.get(self.report)
            if d['status']!='running' and not self.s.learning_flow.workers:return d
            time.sleep(.02)
        self.fail('generation timeout')

    def generate(self,response=None):
        with patch.object(Model,'complete',return_value={'content':json.dumps({'units':response or values()},ensure_ascii=False)}):
            self.s.dispatch('learning_generate',{'report_id':self.report,'goal':'学习缓存','track':'AI Infra · 推理服务','retry':True})
            d=self.wait()
        self.assertEqual(d['status'],'ready',d['error']);return d

    def accept(self):
        d=self.generate();units=d['units'][:2]
        result=self.s.dispatch('learning_accept',{'report_id':self.report,'units':units})
        return result['project_id'],units

    def test_preview_choice_complete_dedupe_restart_settings(self):
        d=self.generate();self.assertEqual(self.s.store.learning_projects(),[])
        self.s.dispatch('learning_defer',{'report_id':self.report});self.assertEqual(self.s.learning_flow.get(self.report)['status'],'deferred')
        chosen=d['units'][:2];chosen[0]['title']='我的目标';p=self.s.dispatch('learning_accept',{'report_id':self.report,'units':chosen})['project_id']
        again=self.s.dispatch('learning_accept',{'report_id':self.report,'units':chosen});self.assertEqual(again['added'],0)
        project=self.s.store.learning_projects()[0];self.assertEqual(len(project['tasks']),2)
        self.assertEqual(project['tasks'][0]['title'],'我的目标')
        with self.assertRaises(UserError):self.s.dispatch('progress',{'project_id':p,'index':0,'status':'已完成（自评）','notes':''})
        self.s.dispatch('progress',{'project_id':p,'index':0,'status':'学习中','notes':'已做实验','response':'我的答案','artifact':'results.md','blockers':'缺GPU'})
        result=self.s.dispatch('progress',{'project_id':p,'index':0,'status':'已完成（自评）','complete':True,'add_review':True})
        self.assertEqual(result['review']['status'],'ready');card=self.s.review.get(result['review']['card_id'])
        self.assertEqual(card['source']['learning_notes'],'已做实验');self.assertEqual(card['source']['evidence'][0]['commit'],SHA)
        self.assertAlmostEqual((datetime.fromisoformat(card['due_at'])-datetime.now(timezone.utc)).total_seconds()/86400,1,delta=.01)
        self.s.dispatch('progress',{'project_id':p,'index':0,'status':'已完成（自评）','complete':True})
        reopened=Service(Store(self.root));self.addCleanup(reopened.close)
        reopened.dispatch('progress',{'project_id':p,'index':0,'status':'已完成（自评）','complete':True})
        self.assertEqual(reopened.review.overview()['total'],1)
        reopened.dispatch('learning_settings',{'auto_review':False,'intervals':[1,3,7,14,30]})
        second=reopened.dispatch('progress',{'project_id':p,'index':1,'status':'已完成（自评）','complete':True,'add_review':True})
        self.assertEqual(second['review']['status'],'skipped');self.assertEqual(reopened.review.overview()['total'],1)
        self.assertEqual(reopened.store.report(self.report)['report'],'# 分析\n缓存命中返回已保存对象。')

    def test_failed_generation_retry_and_failed_review_preserve_completion(self):
        with patch.object(Model,'complete',side_effect=UserError('fixture provider failure')):
            self.s.learning_flow.start(self.report);d=self.wait()
        self.assertEqual(d['status'],'failed');self.assertTrue(self.s.store.report(self.report))
        p,_=self.accept()
        with patch.object(self.s.store,'learning_projects',side_effect=RuntimeError('fixture')):
            result=self.s.dispatch('progress',{'project_id':p,'index':0,'status':'已完成（自评）','complete':True})
        self.assertEqual(result['review']['status'],'pending')
        self.assertEqual(self.s.store.learning_projects()[0]['tasks'][0]['status'],'已完成（自评）')
        link=self.s.dispatch('learning_review_retry',{'project_id':p,'index':0})
        self.assertEqual(link['status'],'ready');self.assertEqual(self.s.review.overview()['total'],1)

    def test_grounding_rejects_fake_evidence_symbol_answer(self):
        for field,value in [('answer','ten times faster'),('evidence',[{'key':0,'symbol':'invented','quote':'return cache[key]'}]),('evidence',[{'key':5,'symbol':'lookup','quote':'return cache[key]'}])]:
            v=values();v[0][field]=value
            with patch.object(Model,'complete',return_value={'content':json.dumps({'units':v})}):
                self.s.learning_flow.start(self.report,force=True);d=self.wait()
            self.assertEqual(d['status'],'failed');self.assertEqual(self.s.store.learning_projects(),[])

    def test_manual_feedback_edit_pause_history_and_local_views(self):
        now=datetime.now(timezone.utc)
        card=self.s.dispatch('review_create',{'source':{'type':'manual','url':'https://example.com/reference'},'title':'回忆缓存',
            'question':'缓存是什么？','answer':'我的参考内容','tags':'缓存','due_at':(now-timedelta(minutes=1)).isoformat(),'schedule_days':[1,3,7,14,30]})
        intervals=[]
        for grade in ['again','hard','good','easy']:
            # New cards for each grade, feedback is revision guarded.
            c=self.s.dispatch('review_create',{'source':{'type':'manual'},'question':grade,'answer':'参考','due_at':(now-timedelta(days=1)).isoformat(),'schedule_days':[1,3,7,14,30]})
            update=self.s.dispatch('review_feedback',{'id':c['id'],'revision':c['revision'],'grade':grade,'notes':'自评记录'})
            intervals.append(update['interval_minutes']);history=self.s.dispatch('review_history',{'id':c['id']})
            self.assertEqual(history['events'][0]['notes'],'自评记录')
            with self.assertRaises(UserError):self.s.dispatch('review_feedback',{'id':c['id'],'revision':c['revision'],'grade':grade})
        self.assertEqual(intervals,[1440,1440,4320,12600])
        paused=self.s.dispatch('review_update',{'id':card['id'],'revision':card['revision'],'paused':True})
        with self.assertRaises(UserError):self.s.review.feedback({'id':card['id'],'revision':paused['revision'],'grade':'good'})
        edit=self.s.dispatch('review_update',{'id':card['id'],'revision':paused['revision'],'paused':False,'answer':'我编辑后的答案','due_at':(now+timedelta(days=2)).isoformat()})
        self.assertTrue(edit['source']['user_edited']);self.assertTrue(self.s.review.overview({'view':'upcoming'})['cards'])

    def test_old_tasks_not_auto_migrated_and_legacy_data_preserved(self):
        old={'title':'旧任务','reading':'main.py','question':'Q','exercise':'E','acceptance':'A'}
        p=self.s.store.save_learning(self.report,self.repo,'已有目标',[old]);self.s.store.update_learning_task(p,0,'已完成（自评）','旧笔记')
        reopened=Service(Store(self.root));self.addCleanup(reopened.close)
        self.assertEqual(reopened.store.learning_projects()[0]['tasks'][0]['notes'],'旧笔记')
        self.assertEqual(reopened.review.overview()['total'],0)
        self.assertIsNone(reopened.learning_flow.review_link(p,0))


if __name__=='__main__':unittest.main()
