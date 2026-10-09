"""Isolated persistence, association, version, export and Agent permission checks."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import Model, Store, UserError, research
from desktop import Service, DesktopBridge
from notes import Notes


class NotesTests(unittest.TestCase):
    def setUp(self):
        Path('build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='notes-test-', dir='build')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = Service(Store(self.root))
        self.store, self.notes = self.service.store, self.service.notes
        self.report_id = self.store.save_report('existing research', '# Original report\nEvidence preserved.', {}, [{'path':'README.md'}])
        self.links = [{'type':'report', 'id':str(self.report_id), 'label':'existing research'},
                      {'type':'github','id':'https://github.com/fixture/queue','label':'queue repository'},
                      {'type':'learning_task','id':'1:0','label':'取消任务'}]

    def save(self, note, **updates):
        values = {k:note[k] for k in ('id','title','content','tags','folder','pinned','revision')}
        values['links'] = [{'type':l['target_type'], 'id':l['target_id'], 'label':l['target_label']} for l in note['links']]
        values.update(updates)
        return self.service.dispatch('notes_save', values)

    def test_acceptance_report_link_content_search_restart_delete_restore(self):
        note = self.service.dispatch('notes_create', {'title':'队列实验', 'content':'# 请求队列\nuniqueNoteNeedle 中文背压验证', 'links':self.links, 'tags':['推理'], 'folder':'AI Infra'})
        self.assertEqual(self.notes.search('uniquenoteneedle')[0]['id'], note['id'])
        self.assertEqual(self.notes.search('背压')[0]['id'], note['id'])
        self.assertEqual(self.notes.search('中文背压')[0]['id'], note['id'])
        self.assertEqual(self.notes.reverse('report',self.report_id)[0]['id'],note['id'])
        note = self.save(note, content='# Updated\nuniqueNoteNeedle durableNoteContent')
        reloaded = Service(Store(self.root))
        restored = reloaded.dispatch('notes_get',{'id':note['id']})
        self.assertEqual(restored['content'],note['content'])
        self.assertEqual(restored['links'],note['links'])
        self.assertEqual(restored['folder'],'AI Infra')
        reloaded.dispatch('notes_delete',{'id':note['id']})
        self.assertEqual(reloaded.notes.search('durableNoteContent'), [])
        self.assertEqual(reloaded.notes.reverse('report',self.report_id), [])
        self.assertTrue(reloaded.notes.get(note['id'],True)['deleted'])
        recovered = Service(Store(self.root)).dispatch('notes_restore',{'id':note['id']})
        self.assertEqual(recovered['content'],note['content'])
        self.assertEqual(recovered['links'],note['links'])
        original = self.store.report(self.report_id)
        self.assertEqual(original['report'],'# Original report\nEvidence preserved.')
        self.assertEqual(original['evidence'],[{'path':'README.md'}])

    def test_versions_keep_ten_prior_snapshots_and_links(self):
        note = self.notes.create('version test','zero',links=self.links)
        for i in range(1,16):
            note = self.save(note,content='body-'+str(i),folder='folder-'+str(i), links=self.links if i<10 else [])
        versions = self.notes.versions(note['id'])
        self.assertEqual(len(versions),11)
        self.assertEqual(versions[-1]['content'],'body-5')
        old = versions[-1]
        note = self.notes.restore_version(note['id'],old['version_no'])
        self.assertEqual(note['content'],'body-5')
        self.assertEqual(note['folder'],'folder-5')
        self.assertEqual(len(note['links']),3)
        self.assertEqual(note['revision'],17)
        self.assertEqual(len(self.notes.versions(note['id'])),11)
        self.save(note)  # Unchanged autosave must not create a version.
        self.assertEqual(self.notes.get(note['id'])['revision'],17)
        with self.assertRaises(UserError): self.save(note,revision=1,content='stale writer')
        self.assertEqual(self.notes.get(note['id'])['content'],'body-5')

    def test_metadata_sort_export_and_material_backlink(self):
        source = self.root/'source.txt'
        source.write_text('local document',encoding='utf-8')
        doc_id=self.service.library.import_paths([source])['items'][0]['id']
        first = self.notes.create('Title: "quoted"', 'older content', ['缓存'], 'infra', True,
            [{'type':'material','id':str(doc_id),'label':'source.txt'}])
        self.notes.create('new note','other text',folder='other')
        last = self.notes.create('last note','new text',folder='infra')
        self.assertEqual([n['id'] for n in self.notes.list()],[first['id'],last['id'],2])
        self.assertEqual(self.service.dispatch('notes_list', {'tag':'缓存'})['notes'][0]['id'],first['id'])
        self.assertEqual(self.notes.reverse('material',doc_id)[0]['id'],first['id'])
        text = self.notes.export(first['id'])
        self.assertIn('older content',text)
        self.assertIn('material',text)
        self.assertIn('title: "Title:',text)
        files=self.notes.export_folder('infra')
        self.assertEqual(len(files),2)
        self.assertNotEqual(files[0]['name'],files[1]['name'])
        self.assertTrue(all('/' not in f['name'] for f in files))
        self.assertEqual(self.notes.export_folder(''),[])

    def run_agent(self, enabled, previous=None, force=False):
        seen=[]
        def complete(model,messages,tools,emit):
            seen.append(json.loads(json.dumps({'messages':messages,'tools':tools})))
            if len(seen)==1 and (enabled or force):
                return {'role':'assistant','content':'','tool_calls':[{'id':'note-call','type':'function','function':{'name':'search_notes','arguments':'{"query":"PrivateNoteNeedle"}'}}]}
            return {'role':'assistant','content':'PrivateNoteNeedle derived answer' if enabled else 'public answer'}
        with patch.object(Model,'complete',complete):
            result=research({'base_url':'http://localhost:9/v1','model':'fixture','source_tools':False},{},'', 'public source', 'follow question',
                threading.Event(),lambda *args:None,previous=previous,notes=self.notes,notes_enabled=enabled)
        return result,seen

    def test_agent_permission_revocation_and_remote_boundary(self):
        self.notes.create('private note','PrivateNoteNeedle secret details')
        with patch.object(self.notes,'search',wraps=self.notes.search) as search:
            result,seen=self.run_agent(False,force=True)
            search.assert_not_called()
        self.assertEqual(seen[0]['tools'],[])
        self.assertIn('权限拒绝',seen[1]['messages'][-1]['content'])
        authorized,seen=self.run_agent(True)
        self.assertEqual(seen[0]['tools'][0]['function']['name'],'search_notes')
        self.assertTrue(authorized['context']['notes_used'])
        self.assertEqual(authorized['evidence'][-1]['source'],'本地笔记')
        with patch.object(self.notes,'search') as search:
            revoked,seen=self.run_agent(False,previous=authorized['context'])
            search.assert_not_called()
        self.assertNotIn('PrivateNoteNeedle',json.dumps(seen))
        self.assertFalse(revoked['context']['notes_used'])
        with self.assertRaises(UserError): self.service.start({'notes_enabled':'true'})
        with self.assertRaises(UserError): self.service.remote.dispatch('notes_list',{})
        with patch.object(self.service,'start') as start:
            self.service.remote.dispatch('start',{'notes_enabled':True})
            self.assertIs(start.call_args.args[0]['notes_enabled'],False)
        self.assertNotIn('PrivateNoteNeedle',json.dumps(self.service.bootstrap()))

    def test_folder_export_native_bridge_creates_distinct_files(self):
        self.notes.create('same title','one',folder='infra')
        self.notes.create('same title','two',folder='infra')
        export_root=self.root/'exports';export_root.mkdir()
        import types,sys
        fake=types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER='folder'),windows=[types.SimpleNamespace(create_file_dialog=lambda *args,**kwargs:[str(export_root)])])
        with patch.dict(sys.modules,{'webview':fake}):
            result=DesktopBridge(self.service).export_notes_folder('infra')
        self.assertTrue(result['saved'])
        files=list(Path(result['path']).glob('*.md'))
        self.assertEqual(len(files),2)
        self.assertTrue(any('one' in f.read_text(encoding='utf-8') for f in files))


if __name__=='__main__':unittest.main()
