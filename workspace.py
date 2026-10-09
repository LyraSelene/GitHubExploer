"""Navigation and associations over existing records; no second learning system."""
import json
import re
import sqlite3
from datetime import datetime, timezone

from core import UserError
from github_source import parse_url


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def repository_key(url):
    try:
        owner, name, _ = parse_url(url)
        return (owner + '/' + name).lower()
    except (UserError, ValueError, TypeError):
        return None


def decoded(value, fallback):
    try:
        result = json.loads(value or '')
        return result if isinstance(result, type(fallback)) else fallback
    except (ValueError, TypeError):
        return fallback


class Workspace:
    def __init__(self, service):
        self.s, self.store = service, service.store
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS repository_projects(
                    id INTEGER PRIMARY KEY,repository_key TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,url TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_positions(
                    project_id INTEGER PRIMARY KEY REFERENCES learning_projects(id) ON DELETE CASCADE,
                    unit_index INTEGER NOT NULL,unit_id TEXT NOT NULL,scroll REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_drafts(
                    project_id INTEGER NOT NULL REFERENCES learning_projects(id) ON DELETE CASCADE,
                    unit_index INTEGER NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id,unit_index));
            ''')

    def _unit(self, project_id, index):
        if type(project_id) is not int or type(index) is not int:
            raise UserError('学习位置格式无效。')
        with self.store.connect() as db:
            row = db.execute('SELECT tasks FROM learning_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise UserError('学习项目不存在。')
        tasks = json.loads(row[0])
        if not 0 <= index < len(tasks):
            raise UserError('学习单元不存在。')
        return tasks[index]

    def position(self, body=None):
        if body:
            task = self._unit(body.get('project_id'), body.get('index'))
            scroll = body.get('scroll', 0)
            if type(scroll) not in (float, int) or not 0 <= scroll <= 100000:
                raise UserError('阅读位置无效。')
            with self.store.connect() as db:
                db.execute('''INSERT INTO learning_positions VALUES(?,?,?,?,?)
                    ON CONFLICT(project_id) DO UPDATE SET unit_index=excluded.unit_index,
                    unit_id=excluded.unit_id,scroll=excluded.scroll,updated_at=excluded.updated_at''',
                    (body['project_id'], body['index'], task.get('unit_id', ''), scroll, stamp()))
            return {'ok': True}
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM learning_positions ORDER BY updated_at DESC')]

    def drafts(self, body=None):
        if body:
            entries = body.get('entries', [])
            if not isinstance(entries, list) or len(entries) > 100:
                raise UserError('待保存记录过多。')
            validated = []
            for entry in entries:
                self._unit(entry.get('project_id'), entry.get('index'))
                clean = {'project_id': entry['project_id'], 'index': entry['index']}
                # Never let a recovered draft silently mark a unit complete.
                for key in ('notes', 'response', 'artifact', 'blockers'):
                    value = entry.get(key, '')
                    if not isinstance(value, str) or len(value) > 15000:
                        raise UserError('学习记录最多15,000字符。')
                    clean[key] = value
                validated.append(clean)
            with self.store.connect() as db:
                for entry in validated:
                    db.execute('''INSERT INTO learning_drafts VALUES(?,?,?,?)
                        ON CONFLICT(project_id,unit_index) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at''',
                        (entry['project_id'], entry['index'], json.dumps(entry, ensure_ascii=False), stamp()))
            return {'ok': True}
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM learning_drafts')]

    def records(self):
        """Derive links from immutable provenance, never from matching titles."""
        records = []
        reports = {}
        materials = {}
        learning = {}

        def add(kind, ident, title, key, commit='', **extra):
            if key:
                records.append({'type': kind, 'id': ident, 'title': title,
                                'repository_key': key, 'commit': commit or '', **extra})

        with self.store.connect() as db:
            for row in db.execute('SELECT id,title,context,evidence,created FROM reports'):
                context, evidence = decoded(row[2], {}), decoded(row[3], [])
                repo = context.get('sources', {}).get('repo') or {}
                pairs = set()
                if repo.get('owner') and repo.get('name'):
                    pairs.add(((repo['owner'] + '/' + repo['name']).lower(), repo.get('commit', '')))
                for e in evidence:
                    key = repository_key(e.get('url', ''))
                    match = re.search(r'/blob/([0-9a-fA-F]{40})/', e.get('url', ''))
                    if key and match:
                        pairs.add((key, match[1]))
                reports[row[0]] = pairs
                for key, commit in pairs:
                    add('report', row[0], row[1], key, commit, updated_at=row[4])
            for row in db.execute("SELECT id,title,source_json,imported_at FROM documents WHERE status='ready'"):
                src = decoded(row[2], {}); key = repository_key(src.get('repository_url', ''))
                if key:
                    materials[row[0]] = {(key, src.get('commit_sha', ''))}
                    add('material', row[0], row[1], key, src.get('commit_sha'), updated_at=row[3])
            for row in db.execute('SELECT id,repository_url,commit_sha,repository_name,last_checked_at FROM github_versions'):
                add('version', row[0], row[3], repository_key(row[1]), row[2], updated_at=row[4])
            for p in self.store.learning_projects():
                key = repository_key(p['url']); learning[p['id']] = {(key, p['commit'])} if key else set()
                add('learning', p['id'], p['name'], key, p['commit'], updated_at=p['created'],
                    completed=sum(t['status'] == '已完成（自评）' for t in p['tasks']), total=len(p['tasks']))
            note_pairs = {}
            for row in db.execute('''SELECT n.id,n.title,n.updated_at,l.target_type,l.target_id FROM notes n
                JOIN note_links l ON n.id=l.note_id WHERE n.deleted_at IS NULL'''):
                kind, target = row[3:]
                pairs = set()
                if kind == 'github':
                    key = repository_key(target)
                    if key: pairs.add((key, ''))
                elif kind == 'learning_task' and target.split(':')[0].isdigit():
                    pairs = learning.get(int(target.split(':')[0]), set())
                elif target.isdigit():
                    pairs = (reports if kind == 'report' else materials).get(int(target), set())
                note_pairs.setdefault(row[0], set()).update(pairs)
                for key, commit in pairs:
                    add('note', row[0], row[1], key, commit, updated_at=row[2])
            for row in db.execute('SELECT id,title,question,source,due_at FROM review_cards'):
                src = decoded(row[3], {}); pairs = set()
                src_repo = src.get('github') or {}
                key = repository_key(src_repo.get('repository_url', src_repo.get('url', '')))
                if key: pairs.add((key, src_repo.get('commit_sha', '')))
                for e in src.get('evidence', []):
                    key = repository_key(e.get('url', ''))
                    if key: pairs.add((key, e.get('commit', '')))
                if not pairs:
                    typ, ident = src.get('type'), src.get('id')
                    pairs = (reports if typ == 'report' else materials if typ == 'material' else note_pairs if typ == 'note' else {}).get(ident, set())
                for key, commit in pairs:
                    add('review', row[0], row[1] or row[2], key, commit, due_at=row[4])
        # One note can reference two items from the same version.
        return list({(r['type'], r['id'], r['repository_key'], r['commit']): r for r in records}.values())

    def projects(self):
        records = self.records()
        grouped = {}
        for r in records:
            grouped.setdefault(r['repository_key'], []).append(r)
        with self.store.connect() as db:
            for key in grouped:
                db.execute('''INSERT INTO repository_projects(repository_key,title,url,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(repository_key) DO NOTHING''', (key, key, 'https://github.com/' + key, stamp()))
            db.row_factory = sqlite3.Row
            result = []
            for row in db.execute('SELECT * FROM repository_projects ORDER BY id DESC'):
                p = dict(row); items = grouped.get(p['repository_key'], [])
                p['count'] = len(items); p['commits'] = sorted({r['commit'] for r in items if r['commit']})
                p['recent'] = max((r.get('updated_at', '') for r in items), default=p['updated_at'])
                result.append(p)
        return sorted(result, key=lambda p: p['recent'], reverse=True)

    def project(self, ident):
        projects = self.projects()
        p = next((p for p in projects if p['id'] == ident), None)
        if p is None: raise UserError('关联项目不存在。')
        return {**p, 'records': [r for r in self.records() if r['repository_key'] == p['repository_key']]}

    def home(self):
        positions = self.position(); projects = self.store.learning_projects()
        chosen = None
        for pos in positions:
            p = next((p for p in projects if p['id'] == pos['project_id']), None)
            if p and 0 <= pos['unit_index'] < len(p['tasks']):
                chosen = {'project_id': p['id'], 'index': pos['unit_index'], 'title': p['tasks'][pos['unit_index']]['title'],
                          'project': p['name'], 'commit': p['commit'], 'scroll': pos['scroll']}
                break
        if chosen is None:
            for p in projects:
                index = next((i for i,t in enumerate(p['tasks']) if t['status'] != '已完成（自评）'), None)
                if index is not None:
                    chosen = {'project_id':p['id'],'index':index,'title':p['tasks'][index]['title'],'project':p['name'],'commit':p['commit'],'scroll':0}
                    break
        runs = []
        if self.s.active_research(): runs.append({'type':'research','id':self.s.active_research()['job_id'],'title':'研究进行中'})
        for r in self.s.github_import.list()['runs']:
            if r['status'] == 'running': runs.append({'type':'import','id':r['id'],'title':r['current_file'],'status':r['status']})
        for r in self.s.tasks.runs():
            if r['status'] in {'running','cancelling','prepared'}: runs.append({'type':'workflow','id':r['id'],'title':r.get('title',r.get('kind','工作流')),'status':r['status']})
        for d in self.s.learning_flow.list()['suggestions']:
            if d['status'] == 'running':runs.append({'type':'suggestion','id':d['report_id'],'title':'整理学习内容'})
        overview = self.s.review.overview({'due_only':True})
        return {'continue':chosen,'due_count':overview['due_count'], 'due':[{'id':c['id'],'title':c['title'] or c['question']} for c in overview['cards'][:3]],
                'running':runs, 'projects':self.projects()[:6], 'positions':positions}

    def feedback(self, body):
        p = next((p for p in self.store.learning_projects() if p['id'] == body.get('project_id')), None)
        task = self._unit(body.get('project_id'), body.get('index'))
        answer = body.get('answer', task.get('response', ''))
        if not isinstance(answer, str) or len(answer) > 15000: raise UserError('答案格式无效。')
        try:
            actual = self.s.learning_flow.evidence(self.store.report(p['report_id'])) if p and p.get('report_id') else []
        except UserError:
            actual = []
        checked = [e for e in task.get('evidence', []) if e.get('excerpt') and any(
            e.get('url') == a['url'] and e.get('commit') == a['commit'] and e['excerpt'] in a['excerpt'] for a in actual)]
        supported = bool(checked) and bool(answer.strip()) and any(answer.strip() in e['excerpt'] for e in checked)
        return {'status':'有原文支持' if supported else '待核实' if checked else '材料不足',
                'message':('回答能在已读材料中逐字找到。接下来尝试解释成立条件，并用最小实践验证。' if supported else
                    '当前材料不足以核对回答。请先补充来源；不会据此判断对错。' if not checked else
                    '回答不是原文的逐字摘录，可能是你的概括或推论。请对照来源解释条件与例外；此本地检查无法评价推理是否正确。'),
                'sources':checked,'reference':task.get('answer','') if any(task.get('answer') and task['answer'] in e['excerpt'] for e in checked) else '',
                'limitation':'仅核对已读摘录，不进行模型评分；反馈与学习完成均不证明掌握。'}
