"""Confirmed, resumable public repository snapshots in the existing library."""
import hashlib
import json
from pathlib import PurePosixPath, Path
import re
import sqlite3
import threading
import time
import urllib.parse

from core import Cancelled, UserError
from github_source import GitHubRepository, GitHubTransport
from materials import TEXT_EXTENSIONS, IGNORED, chunks, metadata, parse

MAX_FILE = 1024 * 1024
MAX_FILES = 100
MAX_TOTAL = 15 * 1024 * 1024


def classification(item):
    path=item['path']; p=PurePosixPath(path); name=p.name.lower(); parts={v.lower() for v in p.parts}
    if p.is_absolute() or '..' in p.parts or '\\' in path or '\x00' in path: return 'excluded','路径不安全'
    if item.get('mode') not in {'100644','100755',None}: return 'excluded','符号链接或非普通文件'
    if parts & (IGNORED | {'vendor','.cache','.next','.idea','.github'}): return 'excluded','构建产物、依赖缓存或管理目录'
    if parts & {'.ssh','.aws','.azure','.config'} or name.startswith(('.env','.npmrc','.pypirc','.netrc')) or re.search(r'(secret|credential|token|password|private.?key|id_rsa|id_ed25519)',name) or p.suffix.lower() in {'.pem','.key','.crt','.p12','.pfx','.cert','.keystore'}: return 'excluded','疑似密钥或敏感配置'
    if (item.get('size') or 0)>MAX_FILE: return 'excluded','超过 1 MB'
    if p.suffix.lower() not in TEXT_EXTENSIONS | {'.rst','.adoc','.lock','.mod','.sum'} and name not in {'dockerfile','makefile','cmakelists.txt'} and not name.startswith(('readme','license','copying')):return 'excluded','图片、音视频、二进制或不支持的文件类型'
    if parts & {'tests','test','benchmark','benchmarks','bench'} or name.startswith('test_'): return 'test',''
    if name.startswith(('readme','license','copying')) or parts & {'docs','doc','documentation','examples','example','tutorial','tutorials'}:
        if p.suffix.lower() in TEXT_EXTENSIONS | {'.rst','.adoc'} or name.startswith(('readme','license','copying')): return 'primary',''
    if name in {'dockerfile','makefile','requirements.txt','pyproject.toml','package.json','cargo.toml','go.mod','go.sum','setup.py','setup.cfg','poetry.lock','uv.lock','cmakelists.txt'} or name.startswith(('docker-compose','requirements')) or p.suffix.lower() in {'.yaml','.yml','.json','.toml','.ini','.cfg','.conf'}: return 'engineering',''
    if p.suffix.lower() in TEXT_EXTENSIONS | {'.rst','.adoc'}: return 'code',''
    return 'excluded','图片、音视频、二进制或不支持的文件类型'


def sensitive(raw):
    sample=raw.decode('utf-8',errors='ignore')
    # Conservatively refuse rather than retain likely real credentials. Placeholders
    # in examples are allowed; no claim that this is a full secret scanner.
    return bool(re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}',sample) or
        re.search(r'(?im)(?:api[_-]?key|password|secret|token)\s*[:=]\s*[\"\'](?!example|test|dummy|your|placeholder|changeme|\$|<|\{|none|null)[A-Za-z0-9_+/-]{16,}[\"\']',sample))


class GitHubImport:
    def __init__(self,store,library):
        self.store,self.library=store,library
        self.lock=threading.RLock();self.workers={}
        with store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS github_versions(
                id INTEGER PRIMARY KEY,repository_url TEXT NOT NULL,owner TEXT NOT NULL,repository_name TEXT NOT NULL,
                default_branch TEXT NOT NULL,commit_sha TEXT NOT NULL,commit_url TEXT NOT NULL,
                repository_description TEXT NOT NULL,language TEXT NOT NULL,commit_time TEXT NOT NULL,
                imported_at TEXT,last_checked_at TEXT NOT NULL,import_status TEXT NOT NULL,tree_json TEXT NOT NULL,
                UNIQUE(repository_url,commit_sha));
              CREATE TABLE IF NOT EXISTS github_files(
                id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES github_versions(id) ON DELETE CASCADE,
                path TEXT NOT NULL,blob_sha TEXT NOT NULL,size INTEGER NOT NULL,category TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',
                document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,content_hash TEXT NOT NULL DEFAULT '',
                UNIQUE(version_id,path));
              CREATE TABLE IF NOT EXISTS github_runs(
                id INTEGER PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,input_json TEXT NOT NULL,
                version_id INTEGER,progress INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL DEFAULT 0,
                current_file TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0);
            ''')
            db.execute("UPDATE github_runs SET status='partial',error='应用已关闭；已保存内容保留，请继续导入。' WHERE status='running'")
            db.execute("UPDATE github_versions SET import_status='partial' WHERE import_status='importing'")

    def launch(self,kind,body):
        if kind=='scan':
            from github_source import parse_url
            parse_url(body.get('url'))
        else:
            if body.get('confirmed') is not True: raise UserError('请先确认所选文件范围。')
            preview=self.preview(body.get('version_id')); allowed={f['path']:f for f in preview['files']}
            paths=body.get('paths')
            if not isinstance(paths,list) or not 1<=len(set(paths))<=MAX_FILES or any(not isinstance(p,str) or p not in allowed or allowed[p]['category']=='excluded' for p in paths): raise UserError('请勾选 1–100 个允许导入的文件。')
            if sum(allowed[p]['size'] for p in set(paths))>MAX_TOTAL: raise UserError('选中内容超过 15 MB，请分批导入。')
            metadata(body.get('tags',[]),body.get('project',''))
        with self.lock:
            if self.workers: raise UserError('已有 GitHub 扫描或导入正在运行，请等待或取消。')
            cancel=threading.Event()
            with self.store.connect() as db:
                ident=db.execute('INSERT INTO github_runs(kind,status,input_json,version_id,created_at) VALUES(?,?,?,?,?)',(kind,'running',json.dumps(body,ensure_ascii=False),body.get('version_id'),time.strftime('%Y-%m-%d %H:%M:%S'))).lastrowid
            self.workers[ident]=cancel
            threading.Thread(target=self._run,args=(ident,kind,body,cancel),daemon=True).start()
        return self.run(ident)

    def run(self,ident):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM github_runs WHERE id=?',(ident,)).fetchone()
        if not row: raise UserError('导入任务不存在。')
        result=dict(row);result.pop('input_json');return result

    def cancel(self,ident):
        with self.lock:
            if ident in self.workers: self.workers[ident].set()
            with self.store.connect() as db: db.execute('UPDATE github_runs SET cancel_requested=1 WHERE id=?',(ident,))
        return self.run(ident)

    def _set(self,ident,**values):
        with self.store.connect() as db: db.execute('UPDATE github_runs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),ident))

    def _run(self,ident,kind,body,cancel):
        transport=GitHubTransport(cancel)
        with self.store.connect() as db:cached=[json.loads(r[0]) for r in db.execute('SELECT tree_json FROM github_versions')]
        trees={(r['owner'].lower(),r['name'].lower(),r['commit']):{'tree':r['tree'],'truncated':False} for r in cached}
        reader=GitHubRepository(transport,trees);version=body.get('version_id')
        try:
            if kind=='scan':
                self._set(ident,current_file='读取公开仓库元信息、固定 commit 与目录树')
                try:
                    repo=reader.scan(body['url'])
                except UserError as exc:
                    if 'HTTP 404' in str(exc):
                        raise UserError('仓库不存在或不是公开仓库；私有仓库、登录和 GitHub Token 暂不支持。') from None
                    if 'HTTP 403' in str(exc) or 'HTTP 429' in str(exc):
                        raise UserError('GitHub API 限流或访问拒绝；请稍后手动扫描，不会自动重试。') from None
                    raise
                transport.check();version=self._store_scan(repo)
                self._set(ident,version_id=version,status='done',current_file='扫描完成，请选择范围；尚未下载文件正文')
            else:
                preview=self.preview(version);repo=preview['repo'];repo['tree']=preview['tree']
                tags,project=metadata(body.get('tags',[]),body.get('project') or repo['owner']+'/'+repo['name'])
                paths=list(dict.fromkeys(body['paths'])); failures=0
                with self.store.connect() as db:
                    db.execute("UPDATE github_versions SET import_status='importing' WHERE id=?",(version,))
                    db.executemany('UPDATE github_files SET selected=1 WHERE version_id=? AND path=?',[(version,p) for p in paths])
                self._set(ident,total=len(paths))
                for index,path in enumerate(paths):
                    transport.check();self._set(ident,current_file=path,progress=index)
                    with self.store.connect() as db:
                        row=db.execute('SELECT status,document_id FROM github_files WHERE version_id=? AND path=?',(version,path)).fetchone()
                    if row and row[0]=='ready' and row[1]: continue
                    try:
                        raw=reader.read(repo,path,MAX_FILE);transport.check()
                        if sensitive(raw): raise UserError('内容疑似含凭据，已拒绝保存；请选择其他资料。')
                        self._save_file(version,repo,path,raw,tags,project)
                    except Cancelled: raise
                    except Exception as exc:
                        failures+=1
                        error=str(exc) if isinstance(exc,UserError) else '网络或解析失败：'+type(exc).__name__
                        with self.store.connect() as db: db.execute("UPDATE github_files SET status='failed',error=? WHERE version_id=? AND path=?",(error,version,path))
                        if 'HTTP 403' in error or 'HTTP 429' in error:
                            raise UserError('GitHub API 限流或访问拒绝，已停止本批次；稍后手动继续，不自动重试。')
                transport.check();self._set(ident,progress=len(paths),status='partial' if failures else 'done',current_file='导入结束')
                self._refresh_status(version)
        except Exception as exc:
            error='用户已取消；已保存文件保留。' if isinstance(exc,Cancelled) else str(exc) if isinstance(exc,UserError) else 'GitHub 请求失败：'+type(exc).__name__
            self._set(ident,status='partial' if kind=='import' or isinstance(exc,Cancelled) else 'failed',error=error)
            if version:
                with self.store.connect() as db: db.execute("UPDATE github_versions SET import_status='partial' WHERE id=?",(version,))
        finally:
            transport.close()
            with self.lock:self.workers.pop(ident,None)

    def _store_scan(self,repo):
        now=time.strftime('%Y-%m-%d %H:%M:%S');url=repo['url']
        with self.store.connect() as db:
            db.execute('''INSERT INTO github_versions(repository_url,owner,repository_name,default_branch,commit_sha,commit_url,repository_description,language,commit_time,last_checked_at,import_status,tree_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(repository_url,commit_sha) DO UPDATE SET last_checked_at=excluded.last_checked_at''',
              (url,repo['owner'],repo['name'],repo['branch'],repo['commit'],url+'/commit/'+repo['commit'],repo['description'],repo['language'],repo['commit_time'],now,'scanned',json.dumps(repo,ensure_ascii=False)))
            ident=db.execute('SELECT id FROM github_versions WHERE repository_url=? AND commit_sha=?',(url,repo['commit'])).fetchone()[0]
            for item in repo['tree']:
                category,reason=classification(item)
                db.execute('INSERT OR IGNORE INTO github_files(version_id,path,blob_sha,size,category,error) VALUES(?,?,?,?,?,?)',(ident,item['path'],item.get('sha',''),item.get('size') or 0,category,reason))
        return ident

    def _save_file(self,version,repo,path,raw,tags,project):
        # Parse selected text only, using the library parser; source files never
        # become local executable files. Hash identity includes commit/path so
        # identical bytes in multiple versions retain their distinct provenance.
        p=Path(path);suffix=p.suffix.lower()
        parser_path=p if suffix in TEXT_EXTENSIONS or p.name.lower() in {'makefile','dockerfile'} else p.with_suffix('.txt')
        kind,title,pages=parse(raw,parser_path);content=pages[0][1]
        if sensitive(content.encode('utf-8')):
            raise UserError('内容疑似含凭据，已拒绝保存；请选择其他资料。')
        digest=hashlib.sha256(raw).hexdigest();url=repo['url']+'/blob/'+repo['commit']+'/'+urllib.parse.quote(path,safe='/')
        identity=hashlib.sha256((url+'\0'+digest).encode()).hexdigest();now=time.strftime('%Y-%m-%d %H:%M:%S')
        provenance={'version_id':version,'repository':repo['owner']+'/'+repo['name'],'repository_url':repo['url'],'file_path':path,'commit_sha':repo['commit'],'url':url,'selected':True,'parsed':True}
        with self.library.lock,self.store.connect() as db:
            old=db.execute('SELECT id FROM documents WHERE path=? AND source_json<>\'{}\'',(url,)).fetchone()
            if old:doc=old[0]
            else:
                doc=db.execute('''INSERT INTO documents(name,path,kind,size,sha256,content_hash,imported_at,title,tags,project,status,error,source_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(p.name,url,kind,len(raw),identity,digest,now,path,json.dumps(tags,ensure_ascii=False),project,'ready','',json.dumps(provenance,ensure_ascii=False))).lastrowid
                db.execute('INSERT INTO document_pages VALUES(?,?,?)',(doc,0,content))
                db.executemany('INSERT INTO document_tags VALUES(?,?)',[(doc,t) for t in tags])
                for index,(start,end,heading,part) in enumerate(chunks(content)):
                    line_start=content.count('\n',0,start)+1;line_end=content.count('\n',0,max(start,end-1))+1
                    db.execute('''INSERT INTO document_chunks(document_id,chunk_index,page,heading,content,start_offset,end_offset,start_line,end_line,chunk_hash,commit_sha,source_url)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(doc,index,None,heading,part,start,end,line_start,line_end,hashlib.sha256(part.encode()).hexdigest(),repo['commit'],url+f'#L{line_start}-L{line_end}'))
            db.execute("UPDATE github_files SET status='ready',error='',document_id=?,content_hash=? WHERE version_id=? AND path=?",(doc,digest,version,path))
            db.execute('UPDATE github_versions SET imported_at=coalesce(imported_at,?) WHERE id=?',(now,version))

    def _refresh_status(self,version):
        with self.store.connect() as db:
            missing=db.execute("SELECT count(*) FROM github_files WHERE version_id=? AND selected=1 AND (status<>'ready' OR document_id IS NULL)",(version,)).fetchone()[0]
            db.execute('UPDATE github_versions SET import_status=? WHERE id=?',('partial' if missing else 'complete',version))

    def preview(self,ident):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM github_versions WHERE id=?',(ident,)).fetchone()
            if not row:raise UserError('仓库版本不存在。')
            version=dict(row);repo=json.loads(version.pop('tree_json'));files=[dict(r) for r in db.execute('SELECT * FROM github_files WHERE version_id=? ORDER BY category,path',(ident,))]
            other=db.execute('SELECT tree_json FROM github_versions WHERE repository_url=? AND id<? ORDER BY id DESC LIMIT 1',(version['repository_url'],ident)).fetchone()
        prior={f['path']:f.get('sha') for f in json.loads(other[0])['tree']} if other else {}
        for f in files:
            f['change']='added' if f['path'] not in prior else 'modified' if prior[f['path']]!=f['blob_sha'] else 'unchanged'
            if f['status']=='ready' and f['document_id'] is None:f['status']='deleted'
        current={f['path'] for f in files}
        recommended=[f for f in files if f['category'] in {'primary','engineering'}]
        return {'version':version,'repo':repo,'tree':repo['tree'],'files':files,'deleted_paths':sorted(set(prior)-current),
            'new_version':bool(other),'already_imported':version['import_status'] in {'complete','partial'},
            'recommended_count':len(recommended),'excluded_count':sum(f['category']=='excluded' for f in files),
            'estimated_bytes':sum(f['size'] for f in recommended),'estimated_seconds':len(recommended)*.8,
            'notice':'耗时仅为估算；文件大小来自 GitHub 目录，解码或网络错误在导入时显示。公开仓库不支持 Token。'}

    def list(self):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row
            return {'versions':[dict(r) for r in db.execute('SELECT id,repository_url,repository_name,commit_sha,import_status,imported_at,last_checked_at FROM github_versions ORDER BY id DESC')],
                    'runs':[dict(r) for r in db.execute('SELECT id,kind,status,version_id,progress,total,current_file,error,created_at FROM github_runs ORDER BY id DESC LIMIT 30')]}

    def delete(self,ident,all_versions=False):
        with self.lock:
            if self.workers: raise UserError('请先停止导入再删除。')
            preview=self.preview(ident)
            with self.store.connect() as db:
                ids=[r[0] for r in db.execute('SELECT id FROM github_versions WHERE repository_url=?',(preview['version']['repository_url'],))] if all_versions else [ident]
                for version in ids:
                    docs=[r[0] for r in db.execute('SELECT document_id FROM github_files WHERE version_id=? AND document_id IS NOT NULL',(version,))]
                    db.executemany('DELETE FROM documents WHERE id=?',[(d,) for d in docs])
                    if all_versions: db.execute('DELETE FROM github_versions WHERE id=?',(version,))
                    else: db.execute("UPDATE github_versions SET import_status='deleted' WHERE id=?",(version,))
            return {'ok':True,'notice':'只删除本地资料；报告、学习与复习快照保留，原链接仍可打开。'}

    def close(self):
        with self.lock:
            for cancel in self.workers.values():cancel.set()
