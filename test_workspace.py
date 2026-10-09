import json
from pathlib import Path
import tempfile
import unittest
from core import Store, UserError, Sources, github_repo
from desktop import Service
from learning_flow import FIELDS

SHA='a'*40

def seed(s):
    repo={'owner':'org','name':'repo','commit':SHA}
    quote='def lookup(key):\n    return cache[key]'
    evidence=[{'path':'cache.py','url':f'https://github.com/org/repo/blob/{SHA}/cache.py#L1-L2','start':1,'end':2,'excerpt':quote}]
    report=s.store.save_report('缓存研究','# 缓存机制\n命中后读取已有对象。',{'sources':{'repo':repo}},evidence)
    raw=[{**{k:'缓存练习 '+str(i) for k in FIELDS},'title':'缓存单元 '+str(i+1),'answer':'return cache[key]',
          'evidence':[{'key':0,'symbol':'lookup','quote':quote}]} for i in range(3)]
    units=s.learning_flow.validate(raw,s.learning_flow.evidence(s.store.report(report)),report)
    with s.store.connect() as db:
        db.execute('INSERT INTO learning_suggestions(report_id,status,units,updated_at) VALUES(?,?,?,?)',(report,'ready',json.dumps(units),'2026-10-08'))
    p=s.learning_flow.accept({'report_id':report,'units':units[:2]})['project_id']
    return report,p,units

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='build',prefix='workspace-test-')
        self.s=Service(Store(Path(self.temp.name)));self.addCleanup(self.temp.cleanup);self.addCleanup(self.s.close)
        self.report,self.p,self.units=seed(self.s)

    def test_position_draft_restart_and_completion(self):
        self.s.workspace.position({'project_id':self.p,'index':1,'scroll':421})
        self.s.workspace.drafts({'entries':[{'project_id':self.p,'index':1,'notes':'未保存笔记','response':'return cache[key]'}]})
        r=Service(Store(Path(self.temp.name)));self.addCleanup(r.close)
        self.assertEqual(r.workspace.home()['continue']['index'],1)
        self.assertEqual(r.workspace.home()['continue']['scroll'],421)
        self.assertEqual(r.workspace.drafts()[0]['notes'],'未保存笔记')
        r.dispatch('progress',{'project_id':self.p,'index':1,'status':'进行中','notes':'未保存笔记','response':'return cache[key]','artifact':'','blockers':''})
        self.assertEqual(r.workspace.drafts(),[])
        for _ in range(2):r.dispatch('progress',{'project_id':self.p,'index':1,'status':'已完成（自评）','complete':True})
        self.assertEqual(r.review.overview()['total'],1)

    def test_repository_id_and_commit_separation(self):
        first=self.s.workspace.projects()[0]
        self.s.store.save_report('新版', '# 新版', {'sources':{'repo':{'owner':'ORG','name':'REPO','commit':'b'*40}}},[])
        p=self.s.workspace.projects()[0]
        self.assertEqual(first['id'],p['id']);self.assertEqual(len(p['commits']),2)
        records=self.s.workspace.project(p['id'])['records']
        self.assertEqual(next(r for r in records if r['type']=='learning')['commit'],SHA)
        self.assertEqual(next(r for r in records if r['type']=='report' and r['id']==self.report)['commit'],SHA)

    def test_feedback_is_grounded_and_limited(self):
        f=self.s.workspace.feedback({'project_id':self.p,'index':0,'answer':'return cache[key]'})
        self.assertEqual(f['status'],'有原文支持');self.assertIn('不证明掌握',f['limitation'])
        f=self.s.workspace.feedback({'project_id':self.p,'index':0,'answer':'快十倍'})
        self.assertEqual(f['status'],'待核实')
        with self.s.store.connect() as db:db.execute('UPDATE reports SET evidence=? WHERE id=?',('[]',self.report))
        self.assertEqual(self.s.workspace.feedback({'project_id':self.p,'index':0,'answer':'x'})['status'],'材料不足')
        with self.assertRaises(UserError):self.s.workspace.feedback({'project_id':-1,'index':0})

    def test_fixed_commit_link_and_validation(self):
        self.assertEqual(github_repo('https://github.com/org/repo/tree/'+SHA),('org','repo'))
        with self.assertRaises(UserError):self.s.workspace.position({'project_id':self.p,'index':500})
        with self.assertRaises(UserError):self.s.workspace.position({'project_id':self.p,'index':0,'scroll':-1})

if __name__=='__main__':unittest.main()
