"""Isolated review acceptance tests; model replies are fixtures, never live calls."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Model, Store, UserError
from desktop import Service
from test_materials import pdf_fixture
from review import schedule


class ReviewTests(unittest.TestCase):
    def setUp(self):
        Path('build').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='build',prefix='review-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.service=Service(Store(self.root/'data'))
        self.store=self.service.store
        self.content='# 队列研究\n'+ '\n'.join(['规则 '+str(i)+': 请求应排队等待资源。' for i in range(5)])
        self.report=self.store.save_report('队列实验',self.content,{},[{'path':'queue.py'}])
        self.store.set('settings',{'base_url':'http://localhost:9/v1','model':'fixture'})
        self.source={'type':'report','id':self.report}

    def generated_values(self,kind='qa'):
        return [{'kind':kind,'question':'规则 '+str(i)+' 是什么？','answer':'请求应排队等待资源。',
                 'excerpt':'规则 '+str(i)+': 请求应排队等待资源。','options':['请求应排队等待资源。','无限创建资源'] if kind=='choice' else [],
                 'difficulty':3,'tags':['队列']} for i in range(5)]

    def generate(self,values=None,**extra):
        body={'source':self.source,'count':5,'kind':'qa','send_source':True,**extra}
        with patch.object(Model,'complete',return_value={'content':json.dumps({'cards':values or self.generated_values()},ensure_ascii=False)}) as call:
            result=self.service.dispatch('review_generate',body)
        return result,call

    def manual(self,**extra):
        return self.service.dispatch('review_create',{'source':self.source,'question':'资源忙时？','answer':'请求排队',
            'excerpt':'请求应排队等待资源。','tags':'队列, 推理','project':'推理实验',**extra})

    def test_acceptance_five_report_cards_feedback_restart_and_report_preserved(self):
        preview,call=self.generate(project='队列项目',tags='测试, 队列')
        self.assertEqual(len(preview['cards']),5)
        self.assertEqual(self.service.review.overview()['total'],0)
        payload=call.call_args.args[0][-1]['content']
        self.assertIn('material',payload)
        cards=self.service.dispatch('review_confirm',{'token':preview['token']})['cards']
        self.assertEqual(len(cards),5)
        self.assertEqual(self.service.review.overview()['due_count'],5)
        for card,grade,minutes in zip(cards,['again','hard','good','easy'],[10,1440,1440,5760]):
            before=datetime.now(timezone.utc)
            updated=self.service.dispatch('review_feedback',{'id':card['id'],'revision':card['revision'],'grade':grade})
            delta=(datetime.fromisoformat(updated['due_at'])-before).total_seconds()/60
            self.assertAlmostEqual(delta,minutes,delta=.1)
            self.assertEqual(updated['review_count'],1)
            with self.assertRaises(UserError): self.service.dispatch('review_feedback',{'id':card['id'],'revision':card['revision'],'grade':grade})
        reopened=Service(Store(self.root/'data'))
        saved=reopened.review.get(cards[0]['id'])
        self.assertEqual(saved['review_count'],1)
        self.assertEqual(saved['source']['id'],self.report)
        self.assertEqual(saved['project'],'队列项目')
        self.assertEqual(reopened.review.overview()['due_count'],1)
        self.assertEqual(reopened.review.overview()['completed_today'],4)
        self.assertEqual(reopened.dispatch('report',{'id':self.report})['report'],self.content)
        self.assertEqual(self.store.report(self.report)['evidence'],[{'path':'queue.py'}])
        with self.assertRaises(UserError): self.service.review.confirm(preview['token'])

    def test_four_feedbacks_use_prior_intervals_and_reject_future_reviews(self):
        card=self.manual()
        updated=self.service.review.feedback({'id':card['id'],'revision':1,'grade':'good'})
        with self.assertRaises(UserError): self.service.review.feedback({'id':card['id'],'revision':2,'grade':'good'})
        with self.store.connect() as db: db.execute('UPDATE review_cards SET due_at=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(),card['id']))
        updated=self.service.review.feedback({'id':card['id'],'revision':2,'grade':'good'})
        self.assertEqual(updated['interval_minutes'],4320)
        self.assertEqual(schedule(4320,'hard'),5184)
        self.assertEqual(schedule(4320,'easy'),12960)
        self.assertEqual(schedule(4320,'again'),10)
        with self.assertRaises(UserError): schedule(0,'unknown')

    def test_pdf_page_and_note_source_survive_source_deletion(self):
        path=self.root/'source.pdf';pdf_fixture(path)
        ident=self.service.library.import_paths([path],project='PDF project')['items'][0]['id']
        ref={'type':'material','id':ident,'page':2}
        card=self.manual(source=ref,question='Which page?',answer='Second page',excerpt='Second page pdfneedle evidence')
        self.assertEqual(card['source']['page'],2)
        self.assertEqual(self.service.dispatch('materials_get',{'id':ident,'page':card['source']['page']})['page'],2)
        with self.assertRaises(UserError): self.manual(source=ref,excerpt='First page introduction')
        note=self.service.notes.create('观察','这是一条待验证的假设。',folder='笔记项目')
        ncard=self.manual(source={'type':'note','id':note['id']},excerpt='待验证的假设',answer='待验证')
        self.assertEqual(ncard['source']['type'],'note')
        self.service.library.delete(ident)
        self.service.notes.delete(note['id'])
        self.assertEqual(self.service.review.get(card['id'])['source']['excerpt'],'Second page pdfneedle evidence')
        with self.assertRaises(UserError): self.service.review.source(ref)

    def test_filters_choices_short_and_card_delete_cascades_events(self):
        card=self.manual(kind='choice',answer='请求排队',options=['请求排队','立即丢弃'])
        self.manual(kind='short',tags=['其他'],project='存储')
        self.assertEqual(len(self.service.review.overview({'project':'推理实验','tag':'队列','source_type':'report','source_id':self.report})['cards']),1)
        self.assertEqual(self.service.review.overview({'tag':'missing'})['cards'],[])
        with self.assertRaises(UserError): self.manual(kind='choice',options=['a','b'])
        updated=self.service.review.feedback({'id':card['id'],'revision':1,'grade':'easy'})
        self.service.review.delete(updated['id'])
        with self.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM review_events').fetchone()[0],0)
        self.assertEqual(self.store.report(self.report)['report'],self.content)

    def test_ai_rejects_no_consent_invented_answer_excerpt_and_partial_batch(self):
        with patch.object(Model,'complete') as call:
            with self.assertRaises(UserError): self.service.review.generate({'source':self.source,'send_source':False})
            call.assert_not_called()
        for field,value in [('answer','Invented performance 10x'),('excerpt','Invented source')]:
            values=self.generated_values();values[-1][field]=value
            with self.assertRaises(UserError): self.generate(values)
            self.assertEqual(self.service.review.overview()['total'],0)
        with self.assertRaises(UserError): self.generate(self.generated_values()[:4])
        values=self.generated_values();values[-1]['question']=values[0]['question']
        with self.assertRaises(UserError): self.generate(values)
        with self.assertRaises(UserError): self.generate(source={**self.source,'excerpt':'text not in source'})
        preview,_=self.generate(self.generated_values('choice'),kind='choice')
        self.assertEqual(preview['cards'][0]['options'][0],preview['cards'][0]['answer'])

    def test_selected_passage_and_expired_preview_remote_boundary(self):
        excerpt='规则 0: 请求应排队等待资源。'
        values=[self.generated_values()[0]]
        preview,call=self.generate(values,source={**self.source,'excerpt':excerpt},count=1)
        payload=json.loads(call.call_args.args[0][-1]['content'])
        self.assertEqual(payload['material'],excerpt)
        self.assertEqual(preview['cards'][0]['source']['offset'],self.content.index(excerpt))
        self.service.review.pending[preview['token']]['expires']=0
        with self.assertRaises(UserError): self.service.review.confirm(preview['token'])
        for action in ('review_list','review_source','review_generate','review_confirm'):
            with self.assertRaises(UserError): self.service.remote.dispatch(action,{'source':self.source})


if __name__=='__main__': unittest.main()
