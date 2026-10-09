import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from core import Cancelled, Sources, Store, UserError
from desktop import Service
from github_import import classification
from github_source import GitHubRepository, GitHubTransport, parse_url
from materials import LibraryAccess

SHA='a'*40


def repo(sha=SHA):
    names=['README.md','docs/guide.md','src/a.py','src/b.py','src/c.py','tests/test_a.py','requirements.txt','.env','key.pem','image.png','node_modules/cache.js','large.txt','symlink.py']
    return {'owner':'org','name':'python-repo','url':'https://github.com/org/python-repo','commit':sha,'branch':'main','ref':'main','scope':'',
        'description':'Python fixture','language':'Python','commit_time':'2026-10-07T00:00:00Z',
        'tree':[{'path':p,'sha':str(i),'size':2_000_000 if p=='large.txt' else 180,'mode':'120000' if p=='symlink.py' else '100644','type':'blob'} for i,p in enumerate(names)]}


class GitHubImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='build',prefix='gh-test-');self.root=Path(self.temp.name)
        self.s=Service(Store(self.root));self.addCleanup(self.temp.cleanup);self.addCleanup(self.s.close)
        self.reads=[]

    def wait(self,ident):
        for _ in range(200):
            r=self.s.github_import.run(ident)
            if r['status']!='running' and not self.s.github_import.workers:return r
            time.sleep(.01)
        self.fail('import timeout')

    def scan(self,r=None):
        with patch.object(GitHubRepository,'scan',return_value=r or repo()),patch.object(GitHubRepository,'read') as read:
            job=self.s.dispatch('github_scan',{'url':'https://github.com/org/python-repo/'});result=self.wait(job['id'])
            read.assert_not_called()
        self.assertEqual(result['status'],'done');return result['version_id']

    def read(self,_reader,r,path,limit):
        self.reads.append(path);return ('# '+path+'\ndef lookup(key):\n    return cache[key]\nneedle '+path).encode()

    def imports(self,version,paths,reader=None):
        with patch.object(GitHubRepository,'read',reader or (lambda reader,r,path,limit:self.read(reader,r,path,limit))):
            job=self.s.dispatch('github_import',{'version_id':version,'paths':paths,'confirmed':True,'tags':'GitHub','project':'cache'})
            return self.wait(job['id'])

    def test_scan_confirm_import_search_dedupe_restart_provenance_permissions(self):
        version=self.scan();preview=self.s.github_import.preview(version)
        self.assertEqual(preview['excluded_count'],6)
        with self.assertRaises(UserError):self.s.dispatch('github_import',{'version_id':version,'paths':['README.md'],'confirmed':False})
        paths=['docs/guide.md','src/a.py','src/b.py','src/c.py'];result=self.imports(version,paths)
        self.assertEqual(result['status'],'done');self.assertEqual(len(self.s.library.list()['documents']),4)
        hits=self.s.library.search('needle');self.assertEqual(len(hits),4)
        self.assertTrue(hits[0]['start_line']);self.assertIn(SHA,hits[0]['source_url'])
        self.assertIn('#L',hits[0]['source_url']);self.assertEqual(hits[0]['document']['github']['commit_sha'],SHA)
        calls=len(self.reads);self.imports(version,paths);self.assertEqual(len(self.reads),calls)
        self.assertEqual(self.scan(),version)
        restored=Service(Store(self.root));self.addCleanup(restored.close)
        self.assertEqual(len(restored.library.list()['documents']),4);self.assertEqual(restored.github_import.preview(version)['version']['import_status'],'complete')
        src=Sources(None,lambda *a:None);denied=LibraryAccess(restored.library,False,src);self.assertIn('拒绝',denied.search({'query':'needle'}));self.assertFalse(src.evidence)
        granted=LibraryAccess(restored.library,True,src);result=json.loads(granted.search({'query':'needle'}))['sources'][0]
        self.assertEqual(result['commit'],SHA);self.assertEqual(result['repository'],'org/python-repo');self.assertTrue(result['start'])
        ref={'type':'material','id':hits[0]['document']['id'],'chunk_id':hits[0]['chunk_id']}
        source=restored.review.source(ref);self.assertEqual(source['github']['commit_sha'],SHA)
        card=restored.review.create({'source':ref,'question':'Q','answer':'return cache[key]','excerpt':'return cache[key]'})
        self.assertIn(SHA,card['source']['source_url'])
        for action in ['github_scan','github_import','learning_generate','learning_accept']:
            with self.assertRaises(UserError):restored.remote.dispatch(action,{})

    def test_new_version_diff_retains_old_and_deletion_keeps_report_review(self):
        old=self.scan();self.imports(old,['docs/guide.md','src/a.py'])
        updated=repo('b'*40);updated['tree']=[f for f in updated['tree'] if f['path']!='src/b.py'];next(f for f in updated['tree'] if f['path']=='src/a.py')['sha']='newblob'
        new=self.scan(updated);d=self.s.github_import.preview(new)
        self.assertIn('src/b.py',d['deleted_paths']);self.assertEqual(next(f for f in d['files'] if f['path']=='src/a.py')['change'],'modified')
        self.imports(new,['src/a.py']);self.assertEqual(len(self.s.library.list()['documents']),3)
        document=self.s.library.list()['documents'][0];card=self.s.review.create({'source':{'type':'material','id':document['id']},'question':'Q','answer':'A','excerpt':'return cache[key]'})
        report=self.s.store.save_report('derived','retained',{},[{'document_id':document['id']}])
        self.s.github_import.delete(new,True);self.assertEqual(len(self.s.library.list()['documents']),0)
        self.assertEqual(self.s.store.report(report)['report'],'retained');self.assertEqual(self.s.review.get(card['id'])['answer'],'A')

    def test_failed_file_continue_cancel_resume_and_restart_interrupted(self):
        version=self.scan()
        def failing(reader,r,path,limit):
            if path=='src/b.py':raise UserError('fixture timeout')
            return self.read(reader,r,path,limit)
        result=self.imports(version,['src/a.py','src/b.py','src/c.py'],failing)
        self.assertEqual(result['status'],'partial');self.assertEqual(len(self.s.library.list()['documents']),2)
        self.imports(version,['src/b.py']);self.assertEqual(len(self.s.library.list()['documents']),3)
        entered=threading.Event();release=threading.Event()
        def slow(reader,r,path,limit):
            entered.set();release.wait(3);reader.transport.check();return self.read(reader,r,path,limit)
        with patch.object(GitHubRepository,'read',slow):
            job=self.s.github_import.launch('import',{'version_id':version,'paths':['README.md','docs/guide.md'],'confirmed':True})
            self.assertTrue(entered.wait(2));self.s.github_import.cancel(job['id']);release.set();result=self.wait(job['id'])
        self.assertEqual(result['status'],'partial');self.assertIn('取消',result['error']);self.assertEqual(self.s.github_import.preview(version)['version']['import_status'],'partial')
        self.imports(version,['README.md','docs/guide.md']);self.assertEqual(len(self.s.library.list()['documents']),5)
        with self.s.store.connect() as db:db.execute("INSERT INTO github_runs(kind,status,input_json,created_at) VALUES('import','running','{}','now')")
        restored=Service(Store(self.root));self.addCleanup(restored.close);self.assertEqual(restored.github_import.list()['runs'][0]['status'],'partial')

    def test_sensitive_binary_limits_and_no_arbitrary_url(self):
        for url in ['http://github.com/o/r','https://github.com.evil/o/r','https://github.com@127.0.0.1/o/r','https://github.com/o/r?token=secret','file:///etc/passwd','https://github.com/o/r/blob/main/../secret']:
            with self.assertRaises(UserError):parse_url(url)
        for url in ['http://127.0.0.1/x','https://evil.example/x','https://api.github.com@evil.example/x']:
            with self.assertRaises(UserError):GitHubTransport(threading.Event()).open(url)
        version=self.scan()
        with self.assertRaises(UserError):self.s.github_import.launch('import',{'version_id':version,'paths':['.env'],'confirmed':True})
        with patch.object(GitHubRepository,'read',return_value=b'-----BEGIN PRIVATE KEY-----\nsecret'):
            job=self.s.github_import.launch('import',{'version_id':version,'paths':['src/a.py'],'confirmed':True});r=self.wait(job['id'])
        self.assertEqual(r['status'],'partial');self.assertFalse(self.s.library.list()['documents'])
        with patch.object(GitHubRepository,'read',return_value=b'\x00binary'):
            job=self.s.github_import.launch('import',{'version_id':version,'paths':['src/b.py'],'confirmed':True});self.wait(job['id'])
        self.assertFalse(self.s.library.list()['documents'])

    def test_shared_reader_branch_slash_and_commit_file(self):
        class Fake:
            def json(self,url,limit=None):
                if '/git/trees/' in url:return {'tree':repo()['tree'],'truncated':False}
                if '/commits/' in url:
                    if 'feature%2Fx%2Fsrc%2Fa.py' in url or 'feature%2Fx%2Fsrc' in url:raise UserError('HTTP 404')
                    return {'sha':SHA,'commit':{'committer':{'date':'now'}}}
                return {'default_branch':'main','private':False,'description':'test','language':'Python'}
        read=GitHubRepository(Fake());r=read.scan('https://github.com/org/python-repo/blob/feature/x/src/a.py')
        self.assertEqual(r['ref'],'feature/x');self.assertEqual(r['scope'],'src/a.py');self.assertEqual(r['commit'],SHA)

    def test_canonical_url_decoded_secret_and_cross_repository_learning(self):
        class Fake:
            def json(self,url,limit=None):
                if '/git/trees/' in url:return {'tree':repo()['tree'],'truncated':False}
                if '/commits/' in url:return {'sha':SHA,'commit':{'committer':{'date':'now'}}}
                return {'default_branch':'main','private':False,'owner':{'login':'org'},'name':'python-repo'}
        resolved=GitHubRepository(Fake()).scan('https://github.com/ORG/PYTHON-REPO/')
        self.assertEqual(resolved['url'],'https://github.com/org/python-repo')
        version=self.scan()
        raw=('说明\npassword = "'+'a'*20+'"').encode('gb18030')
        result=self.imports(version,['src/a.py'],lambda *a:raw)
        self.assertEqual(result['status'],'partial')
        self.assertFalse(self.s.library.list()['documents'])
        self.imports(version,['src/a.py'])
        other=repo();other['name']='other';other['url']='https://github.com/org/other'
        next_version=self.scan(other);self.imports(next_version,['src/a.py'])
        ids=[d['id'] for d in self.s.library.list()['documents']]
        with self.assertRaises(UserError):
            self.s.dispatch('learning_from_materials',{'document_ids':ids,'send_sources':True})
        updated=repo('b'*40);self.scan(updated)
        self.assertFalse(self.s.github_import.preview(version)['new_version'])


if __name__=='__main__':unittest.main()
