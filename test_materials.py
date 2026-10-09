"""Isolated library acceptance, permission and migration tests. No model/network use."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from core import Model, Sources, Store, UserError, research
from desktop import Service
from materials import Library, LibraryAccess


def pdf_fixture(path):
    # Minimal two-page text PDF; no authoring or layout artifact is delivered.
    writer = PdfWriter()
    for text in ('First page introduction', 'Second page pdfneedle evidence'):
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 30 350 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(str(path))


class MaterialsTests(unittest.TestCase):
    def setUp(self):
        Path('build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='library-test-', dir='build')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / 'data')
        self.library = Library(self.store)
        self.files = self.root / 'files'
        self.files.mkdir()
        self.paths = [self.files / name for name in ('notes.txt', '设计.md', 'worker.py', 'paper.pdf')]
        self.paths[0].write_text('uniquequeue 请求队列 背压 限流\n'+('long text\n'*300)+'boundaryneedle', encoding='utf-8')
        self.paths[1].write_text('# 缓存设计 Cache heading\n缓存失效 onlybodytoken 中文检索命中', encoding='utf-8')
        self.paths[2].write_text('def cancel_task():\n    return "codecancel"\n', encoding='utf-8')
        pdf_fixture(self.paths[3])

    def import_all(self):
        return self.library.import_paths(self.paths, ['推理', '学习'], '队列实验')

    def test_acceptance_four_files_search_pdf_dedupe_restart(self):
        self.assertEqual(self.import_all()['imported'], 4)
        self.assertEqual(self.import_all()['duplicate'], 4)
        self.assertEqual(len(self.library.list()['documents']), 4)
        hits = self.library.search('pdfneedle')
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['document']['name'], 'paper.pdf')
        self.assertEqual(hits[0]['page'], 2)
        self.assertEqual(self.library.search('uniquequeue')[0]['document']['name'], 'notes.txt')
        self.assertEqual(self.library.search('codecancel')[0]['document']['name'], 'worker.py')
        self.assertEqual(self.library.search('中文检索')[0]['document']['name'], '设计.md')
        self.assertEqual(self.library.search('背压')[0]['document']['name'], 'notes.txt')
        self.assertEqual(self.library.search('ONLYBODYTOKEN')[0]['document']['name'], '设计.md')
        hit = self.library.search('boundaryneedle')[0]
        preview = self.library.preview(hit['document']['id'], chunk_id=hit['chunk_id'])
        self.assertEqual(preview['text'], self.paths[0].read_bytes().decode('utf-8'))
        self.assertEqual(preview['text'][preview['hit']['start_offset']:preview['hit']['end_offset']], preview['hit']['content'])
        restored = Library(Store(self.root / 'data'))
        self.assertEqual(len(restored.list()['documents']), 4)
        self.assertEqual(restored.search('pdfneedle')[0]['page'], 2)
        self.paths[3].unlink()  # Preview and retrieval depend on the snapshot, not the file.
        pdf = restored.preview(hits[0]['document']['id'], chunk_id=hits[0]['chunk_id'])
        self.assertIn('pdfneedle', pdf['text'])
        self.assertEqual(pdf['pages'], [1, 2])
        self.assertEqual(pdf['page'], 2)

    def test_title_tags_and_retrieval_fallback(self):
        self.import_all()
        self.assertEqual(len(self.library.search('缓存设计', title_only=True)), 1)
        self.assertEqual(self.library.search('onlybodytoken', title_only=True), [])
        self.assertEqual(len(self.library.search('worker.py', title_only=True)), 1)
        self.assertEqual(len(self.library.search('worker.py')), 1)
        hit = self.library.search('codecancel', tag='推理', project='队列实验')[0]
        self.assertEqual(self.library.search('codecancel', tag='无此标签'), [])
        self.library.update(hit['document']['id'], '代码, 取消', '取消练习')
        self.assertEqual(len(self.library.list(tag='代码')['documents']), 1)
        self.assertEqual(self.library.search('codecancel', tag='推理'), [])
        self.assertEqual(len(self.library.search('codecancel', tag='代码', project='取消练习')), 1)
        self.library.fts = False
        self.assertEqual(self.library.search('pdfneedle')[0]['page'], 2)
        with self.assertRaises(UserError): self.library.search('x'*201)
        self.assertEqual(self.library.search('" OR *'), [])

    def test_cascade_delete(self):
        self.import_all()
        hit = self.library.search('pdfneedle')[0]
        self.library.delete(hit['document']['id'])
        self.assertEqual(self.library.search('pdfneedle'), [])
        with self.store.connect() as db:
            for table in ('document_chunks', 'document_pages', 'document_tags'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table+' WHERE document_id=?', (hit['document']['id'],)).fetchone()[0], 0)
            if self.library.fts:
                self.assertEqual(db.execute('SELECT count(*) FROM document_chunks_fts WHERE rowid=?', (hit['chunk_id'],)).fetchone()[0], 0)
        self.assertTrue(self.paths[3].exists())

    def test_folder_failure_retry_hash_and_original_reports_preserved(self):
        report_id = self.store.save_report('existing', 'old report', {}, [])
        ignored = self.files / 'node_modules'
        ignored.mkdir()
        (ignored / 'skip.txt').write_text('skipneedle', encoding='utf-8')
        (self.files / 'image.bin').write_bytes(b'\x00binary')
        bad = self.files / 'broken.pdf'
        bad.write_bytes(b'invalid pdf')
        result = self.library.import_paths([self.files], folder=True)
        self.assertEqual(result['imported'], 4)
        self.assertEqual(result['failed'], 1)
        failed = next(d for d in self.library.list()['documents'] if d['status'] == 'failed')
        self.assertTrue(failed['error'])
        self.assertTrue(failed['sha256'])
        self.assertEqual(self.library.search('skipneedle'), [])
        self.assertEqual(self.library.retry(failed['id'])['failed'], 1)
        pdf_fixture(bad)  # Retry identical successful content merges into the prior record.
        self.assertEqual(self.library.retry(failed['id'])['duplicate'], 1)
        self.assertEqual(len(self.library.list()['documents']), 4)
        self.assertEqual(self.store.report(report_id)['report'], 'old report')
        missing = self.files / 'missing.txt'
        failed = self.library.import_paths([missing])['items'][0]
        self.assertIn('error', failed)
        missing.write_text('retryneedle', encoding='utf-8')
        result = self.library.retry(failed['id'])
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['items'][0]['id'], failed['id'])
        self.assertEqual(len(self.library.search('retryneedle')), 1)

    def test_scan_and_binary_fail(self):
        path = self.files / 'scan.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=400, height=400)
        writer.write(str(path))
        result = self.library.import_paths([path])
        self.assertIn('OCR', result['items'][0]['error'])
        path = self.files / 'binary.txt'
        path.write_bytes(b'\x00\x01')
        self.assertIn('二进制', self.library.import_paths([path])['items'][0]['error'])

    def run_research(self, enabled=False, previous=None, force_call=False):
        seen = []
        def complete(model, messages, tools, emit):
            seen.append(json.loads(json.dumps({'messages': messages, 'tools': tools})))
            if len(seen) == 1 and (enabled or force_call):
                return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'lib1', 'type': 'function',
                    'function': {'name': 'search_materials', 'arguments': '{"query":"pdfneedle"}'}}]}
            return {'role': 'assistant', 'content': 'Derived private pdfneedle report' if enabled else 'Public answer'}
        with patch.object(Model, 'complete', complete):
            result = research({'base_url': 'http://localhost:9/v1', 'model': 'fixture', 'source_tools': False},
                              {}, '', 'Public material for testing', 'Continue analysis', threading.Event(), lambda *args: None,
                              previous=previous, library=self.library, materials_enabled=enabled)
        return result, seen

    def test_permission_denies_tools_and_previous_private_context(self):
        self.import_all()
        with patch.object(self.library, 'search', wraps=self.library.search) as search:
            denied, seen = self.run_research(False, force_call=True)
            search.assert_not_called()
        self.assertEqual(seen[0]['tools'], [])
        self.assertFalse(any('pdfneedle' in (m.get('content') or '') for m in seen[1]['messages']))
        self.assertIn('权限拒绝', seen[1]['messages'][-1]['content'])
        granted, seen = self.run_research(True)
        self.assertEqual(seen[0]['tools'][0]['function']['name'], 'search_materials')
        self.assertIn('pdfneedle', json.dumps(seen[1]['messages']))
        evidence = next(e for e in granted['evidence'] if e.get('document_id'))
        self.assertEqual(evidence['page'], 2)
        self.assertTrue(granted['context']['materials_used'])
        with patch.object(self.library, 'search') as search:
            revoked, seen = self.run_research(False, previous=granted['context'])
            search.assert_not_called()
        self.assertNotIn('pdfneedle', json.dumps(seen))
        self.assertFalse(revoked['context']['materials_used'])
        self.assertFalse(any(e.get('document_id') for e in revoked['evidence']))
        access = LibraryAccess(self.library, False, Sources(None, lambda *args: None))
        self.assertIn('权限拒绝', access.search({'query':'pdfneedle'}))

    def test_service_api_and_remote_scope(self):
        self.import_all()
        service = Service(self.store)
        self.assertEqual(len(service.dispatch('materials_list', {})['documents']), 4)
        hit = service.dispatch('materials_search', {'query': 'pdfneedle'})['results'][0]
        self.assertEqual(service.dispatch('materials_get', {'id': hit['document']['id'], 'chunk_id': hit['chunk_id']})['page'], 2)
        with self.assertRaises(UserError): service.start({'materials_enabled': 'true'})
        with self.assertRaises(UserError): service.remote.dispatch('materials_search', {'query':'pdfneedle'})
        with patch.object(service, 'start', return_value={'job_id':'fixture'}) as start:
            service.remote.dispatch('start', {'material':'public', 'materials_enabled':True})
            self.assertIs(start.call_args.args[0]['materials_enabled'], False)
        self.assertNotIn('pdfneedle', json.dumps(service.bootstrap()))


if __name__ == '__main__': unittest.main()
