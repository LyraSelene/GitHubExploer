"""Bounded local declarative plugins; never evaluate third-party Python/JS."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from core import UserError, assets

API_VERSION='1.0'
PERMISSIONS={'network':'访问公开 GitHub 网络','materials_read':'读取本机资料库','reports_read':'读取本机研究报告',
             'file_write':'写入文件','external_command':'执行外部命令'}
BLOCKED={'file_write','external_command'}
OPERATIONS={'markdown_outline':set(),'markdown_excerpt':set(),'materials_search':{'materials_read'},
            'report_read':{'reports_read'},'github_search':{'network'},'diagnostic_error':set()}
MAX_PACKAGE=2_000_000
def stamp():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def json_object(raw):
    try:value=json.loads(raw)
    except (ValueError,UnicodeError):raise UserError('插件 JSON 无效。') from None
    if not isinstance(value,dict):raise UserError('插件 JSON 必须是对象。')
    return value
def safe_path(name):
    if not isinstance(name,str) or '\\' in name or ':' in name or '\x00' in name:raise UserError('插件包路径无效。')
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts:raise UserError('插件包包含越界路径。')
    if any(x.endswith((' ','.')) for x in p.parts):raise UserError('插件路径不兼容 Windows。')
    return p.as_posix()

class PluginManager:
    def __init__(self,store):
        self.store=store;self.root=(store.directory/'plugins').resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.pending={}
        with store.connect() as db:db.executescript('''
          CREATE TABLE IF NOT EXISTS plugins(id TEXT PRIMARY KEY,name TEXT NOT NULL,version TEXT NOT NULL,
            manifest TEXT NOT NULL,package TEXT NOT NULL,sha256 TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,
            grants TEXT NOT NULL DEFAULT '[]',installed_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS plugin_logs(id INTEGER PRIMARY KEY,plugin_id TEXT NOT NULL,level TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tool_audit(id INTEGER PRIMARY KEY,tool_name TEXT NOT NULL,plugin_id TEXT NOT NULL,
            source TEXT NOT NULL,permissions TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,
            input_summary TEXT NOT NULL,output_summary TEXT NOT NULL,elapsed_ms REAL NOT NULL,created_at TEXT NOT NULL);
        ''')

    def read_package(self,source):
        path=Path(source);files={};total=0
        if path.is_symlink() or path.is_junction():raise UserError('插件包不能是链接。')
        if path.is_dir():
            for file in path.rglob('*'):
                if file.is_symlink() or file.is_junction():raise UserError('插件包不能包含链接或目录联接。')
                if not file.is_file():continue
                name=safe_path(file.relative_to(path).as_posix());total+=file.stat().st_size
                if total>MAX_PACKAGE or len(files)>=100:raise UserError('插件包最多 2 MB / 100 个文件。')
                files[name]=file.read_bytes()
        elif path.is_file() and path.suffix.lower()=='.zip':
            if path.stat().st_size>MAX_PACKAGE:raise UserError('插件包最多 2 MB。')
            try:
                with zipfile.ZipFile(path) as z:
                    for info in z.infolist():
                        name=safe_path(info.filename)
                        if info.is_dir():continue
                        if name in files or stat.S_ISLNK(info.external_attr>>16):raise UserError('插件 ZIP 存在重复路径或链接。')
                        total+=info.file_size
                        if total>MAX_PACKAGE or len(files)>=100:raise UserError('解压后最多 2 MB / 100 个文件。')
                        files[name]=z.read(info)
            except zipfile.BadZipFile:raise UserError('插件 ZIP 损坏。') from None
        else:raise UserError('仅支持本地文件夹或 ZIP 插件包。')
        if any(Path(n).suffix.lower() not in {'.json','.md','.txt'} for n in files):raise UserError('第一版只接受 JSON、Markdown、TXT 声明包，不执行脚本。')
        try:texts={n:raw.decode('utf-8-sig') for n,raw in files.items()}
        except UnicodeError:raise UserError('插件包必须为 UTF-8 文本。') from None
        manifest=self.validate(texts);serialized=json.dumps(texts,ensure_ascii=False,sort_keys=True)
        return manifest,texts,hashlib.sha256(serialized.encode()).hexdigest()

    def validate(self,files):
        if 'manifest.json' not in files:raise UserError('插件包根目录缺少 manifest.json。')
        m=json_object(files['manifest.json'])
        for key in ('id','name','version','entry','compatible_version'):
            if not isinstance(m.get(key),str) or not m[key].strip() or len(m[key])>150:raise UserError('manifest 缺少有效字段：'+key)
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,59}',m['id']):raise UserError('插件 id 无效。')
        if not re.fullmatch(r'\d+\.\d+\.\d+',m['version']):raise UserError('版本需使用 major.minor.patch。')
        if m['compatible_version']!=API_VERSION:raise UserError('兼容版本不匹配（当前 API '+API_VERSION+'）。')
        entry=safe_path(m['entry'])
        if not entry.endswith('.json') or entry=='manifest.json' or entry not in files:raise UserError('入口须为包内 JSON 文件。')
        permissions=m.get('permissions')
        if not isinstance(permissions,list) or any(not isinstance(p,str) or p not in PERMISSIONS for p in permissions) or len(set(permissions))!=len(permissions):raise UserError('插件权限声明无效。')
        tools=m.get('tools')
        if not isinstance(tools,list) or not 1<=len(tools)<=12:raise UserError('插件需声明 1–12 个工具。')
        runtime=json_object(files[entry])
        if runtime.get('runtime')!='declarative-v1' or not isinstance(runtime.get('operations'),dict):raise UserError('仅支持 declarative-v1 受限入口。')
        from tool_registry import validate_schema, BUILTINS
        reserved={t['name'] for t in BUILTINS};names=set()
        for tool in tools:
            if not isinstance(tool,dict):raise UserError('工具格式无效。')
            name=tool.get('name','')
            if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,59}',name) or name in names or name in reserved:raise UserError('工具名称重复或与内置工具冲突。')
            names.add(name)
            if not isinstance(tool.get('description'),str) or not 1<=len(tool['description'])<=1000:raise UserError('工具需有描述。')
            try: validate_schema(tool.get('parameters'))
            except ValueError as exc: raise UserError(str(exc)) from None
            if tool.get('output_format') not in {'text','json'}:raise UserError('输出格式须为 text 或 json。')
            needed=tool.get('permissions')
            if not isinstance(needed,list) or any(p not in permissions for p in needed):raise UserError('工具权限必须包含在插件声明中。')
            operation=runtime['operations'].get(name)
            if not isinstance(operation,str) or operation not in OPERATIONS or not OPERATIONS[operation].issubset(set(needed)):raise UserError('入口操作无效或缺少必需权限。')
        if set(runtime['operations'])!=names:raise UserError('入口与工具列表必须一致。')
        return m

    def preview(self,source):
        try:m,files,digest=self.read_package(source)
        except (OSError,ValueError,TypeError):raise UserError('无法读取插件包，请检查格式和路径。') from None
        token=uuid.uuid4().hex
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires']>time.monotonic()}
            if len(self.pending)>=8:raise UserError('待确认插件过多。')
            self.pending[token]={'manifest':m,'files':files,'digest':digest,'expires':time.monotonic()+600}
        return {'token':token,'manifest':m,'sha256':digest,'permissions':[{'id':p,'label':PERMISSIONS[p],'supported':p not in BLOCKED} for p in m['permissions']],
                'notice':'安装仅保存预览的声明包，不执行脚本，安装后默认禁用。危险权限本版不支持。'}

    @staticmethod
    def validate_grants(m,grants):
        if not isinstance(grants,list) or any(g not in m['permissions'] or g in BLOCKED for g in grants):raise UserError('未声明权限或危险权限不能授权。')

    def install(self,token,grants):
        with self.lock:
            item=self.pending.get(token)
            if not item or item['expires']<=time.monotonic():raise UserError('预览已过期，请重新选择。')
            m=item['manifest'];self.validate_grants(m,grants);ident=m['id'];directory=(self.root/ident).resolve()
            if directory.parent!=self.root:raise UserError('插件路径无效。')
            with self.store.connect() as db:
                if db.execute('SELECT 1 FROM plugins WHERE id=?',(ident,)).fetchone():raise UserError('插件已安装；不会覆盖已有授权。')
                directory.mkdir(exist_ok=False)
                try:
                    for name,content in item['files'].items():
                        target=directory/Path(name);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8')
                    current=stamp()
                    db.execute('INSERT INTO plugins(id,name,version,manifest,package,sha256,grants,installed_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident,m['name'],m['version'],json.dumps(m,ensure_ascii=False),json.dumps(item['files'],ensure_ascii=False),item['digest'],json.dumps(grants),current,current))
                except Exception:shutil.rmtree(directory,ignore_errors=True);raise
            del self.pending[token];self.log(ident,'info','已安装，默认禁用；未执行任何脚本。');return self.get(ident)

    def get(self,ident,internal=False):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM plugins WHERE id=?',(ident,)).fetchone()
        if not row:raise UserError('插件不存在或已卸载。')
        item=dict(row);item['manifest']=json.loads(item['manifest']);item['grants']=json.loads(item['grants']);item['enabled']=bool(item['enabled'])
        if not internal:item.pop('package')
        return item

    def list(self):
        with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM plugins ORDER BY name')]
        return [self.get(ident) for ident in ids]

    def toggle(self,ident,enabled,grants=None):
        if not isinstance(enabled,bool):raise UserError('启用开关需为布尔值。')
        with self.lock:
            item=self.get(ident);grants=item['grants'] if grants is None else grants;self.validate_grants(item['manifest'],grants)
            with self.store.connect() as db:db.execute('UPDATE plugins SET enabled=?,grants=?,updated_at=? WHERE id=?',(int(enabled),json.dumps(grants),stamp(),ident))
            self.log(ident,'info','已启用。' if enabled else '已禁用。')
        return self.get(ident)

    def uninstall(self,ident):
        with self.lock:
            self.get(ident);target=(self.root/ident).resolve()
            if target.parent!=self.root or target.is_symlink() or target.is_junction():raise UserError('插件目录边界检查失败。')
            if target.exists():shutil.rmtree(target)
            with self.store.connect() as db:db.execute('DELETE FROM plugins WHERE id=?',(ident,))
            self.log(ident,'info','已卸载；审计记录保留。')
        return {'ok':True}

    def catalog(self):
        root=assets()/'builtin_plugins';items=[]
        if root.exists():
            for path in sorted(root.iterdir()):
                if path.is_dir():
                    try:
                        m,_,digest=self.read_package(path);items.append({'id':m['id'],'name':m['name'],'version':m['version'],'description':m.get('description',''),'permissions':m['permissions'],'sha256':digest})
                    except UserError:pass
        return items

    def preview_builtin(self,ident):
        if ident not in {p['id'] for p in self.catalog()}:raise UserError('内置插件不存在。')
        return self.preview(assets()/'builtin_plugins'/ident)

    def tools(self,enabled_only=True):
        tools=[]
        for item in self.list():
            if enabled_only and not item['enabled']:continue
            for tool in item['manifest']['tools']:tools.append({**tool,'source':'plugin:'+item['id'],'plugin_id':item['id'],'enabled':item['enabled']})
        return tools

    def available(self,permissions):
        result=[]
        for tool in self.tools():
            grants=self.get(tool['plugin_id'])['grants']
            if all(p in permissions and p in grants and p not in BLOCKED for p in tool['permissions']):result.append(tool)
        return result

    def invoke(self,tool,args,permissions,brokers):
        with self.lock:
            item=self.get(tool['plugin_id'],internal=True)
            if not item['enabled']:raise UserError('插件已禁用，工具不可调用。')
            current=next((t for t in item['manifest']['tools'] if t['name']==tool['name']),None)
            if not current:raise UserError('插件工具不存在。')
            if any(p not in permissions or p not in item['grants'] or p in BLOCKED for p in current['permissions']):raise UserError('权限拒绝：插件未获所需权限。')
            package=json.loads(item['package']);runtime=json_object(package[item['manifest']['entry']]);op=runtime['operations'][tool['name']]
            if op=='markdown_outline':value='\n'.join(l.strip() for l in args.get('text','').splitlines() if re.match(r'^\s{0,3}#{1,6}\s+\S',l))[:16000] or '（没有 Markdown 标题）'
            elif op=='markdown_excerpt':value=args.get('text','')[:min(16000,max(1,args.get('length',1200)))]
            elif op=='diagnostic_error':raise RuntimeError('Diagnostic plugin failure')
            else:
                broker=brokers.get(op)
                if broker is None:raise UserError('权限拒绝：当前入口未提供此能力。')
                value=broker(args)
            if current['output_format']=='json' and isinstance(value,str):return {'text':value}
            if current['output_format']=='text' and not isinstance(value,str):return json.dumps(value,ensure_ascii=False)
            return value

    def log(self,ident,level,message):
        with self.store.connect() as db:db.execute('INSERT INTO plugin_logs(plugin_id,level,message,created_at) VALUES(?,?,?,?)',(ident,level,message[:400],stamp()))
    def logs(self,ident=None):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row
            if ident:return [dict(r) for r in db.execute('SELECT * FROM plugin_logs WHERE plugin_id=? ORDER BY id DESC LIMIT 100',(ident,))]
            return [dict(r) for r in db.execute('SELECT * FROM plugin_logs ORDER BY id DESC LIMIT 100')]
    def audit(self,tool,status,reason,args,output,elapsed):
        # Metadata only, no source text, raw output, headers, tokens or keys.
        with self.store.connect() as db:db.execute('INSERT INTO tool_audit(tool_name,plugin_id,source,permissions,status,reason,input_summary,output_summary,elapsed_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (tool['name'],tool.get('plugin_id',''),tool['source'],json.dumps(tool['permissions']),status,reason,
             '参数数量 '+str(len(args)) if isinstance(args,dict) else '参数格式无效','输出字符数 '+str(len(str(output))),round(elapsed,2),stamp()))
    def audits(self,ident=None):
        with self.store.connect() as db:
            db.row_factory=sqlite3.Row
            if ident:return [dict(r) for r in db.execute('SELECT * FROM tool_audit WHERE plugin_id=? ORDER BY id DESC LIMIT 100',(ident,))]
            return [dict(r) for r in db.execute('SELECT * FROM tool_audit ORDER BY id DESC LIMIT 100')]
