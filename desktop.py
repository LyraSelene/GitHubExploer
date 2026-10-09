"""Wallpaper desktop UI; existing research core and database remain shared."""
from __future__ import annotations
import argparse
import json
import mimetypes
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import (Cancelled, DEFAULT_LEARNING_TRACK, LEARNING_TRACKS, Model, Store, Transport,
                  UserError, assets, github_repo, import_material, research, search_github)
from motion import ENTRIES, MODES, PROMPT, load_preferences, validate_preferences
from chat import ChatStore, DEFAULT_AGENT, agent_config, converse
from media import import_character, media_file, media_state, select_character
from remote import RemoteAccess, companion_data
from trending import Trending
from materials import Library
from notes import Notes
from review import Review
from tasks import Tasks
from models import ModelManager
from plugins import PluginManager
from learning_flow import LearningFlow
from github_import import GitHubImport
from workspace import Workspace


class Service:
    def __init__(self, store=None):
        self.store = store or Store()
        self.lock = threading.Lock()
        self.job = None
        self.chats = ChatStore(self.store)
        self.chat_job = None
        self.models = ModelManager(self.store)
        self.plugins = PluginManager(self.store)
        self.store.tools = self.plugins
        self.remote = RemoteAccess(self)
        self.trending = Trending(self.store)
        self.library = Library(self.store)
        self.notes = Notes(self.store)
        self.review = Review(self.store, self.library, self.notes, self.models)
        self.tasks = Tasks(self.store, self.library, self.notes, self.models)
        self.learning_flow = LearningFlow(self.store,self.review,self.models,self.library)
        self.github_import = GitHubImport(self.store,self.library)
        self.workspace = Workspace(self)

    def bootstrap(self):
        self.models._migrate_legacy()
        profiles = self.models.list_public()
        settings = next((p for p in profiles if p['is_default']), {})
        material_summary = self.library.list()
        note_items = self.notes.list()
        return {"profile": self.store.get("profile", {}), "settings": {
            "base_url": settings.get('base_url','https://api.openai.com/v1'), "model": settings.get('model',''),
            "has_key": settings.get('has_key',False), "source_tools": settings.get('source_tools', True)},
            "models": profiles, "model_routes": self.models.routes_public(),
            "tracks": LEARNING_TRACKS, "default_track": self.store.get('learning_track', DEFAULT_LEARNING_TRACK),
            "reports": [{'id': r[0], 'title': r[1], 'created': r[2]} for r in self.store.reports()],
            "learning": self.public_learning_projects(), "learning_suggestions":self.learning_flow.list(), 'motion': load_preferences(self.store),
            'motion_modes': MODES, 'entry_modes': ENTRIES, 'default_entry_prompt': PROMPT,
            'music': {'enabled': self.store.get('bgm_enabled', False) is True},
            'chat_sessions': self.chats.list(), 'chat_agent': self.chats.agent(), 'default_chat_agent': DEFAULT_AGENT,
            'active_chat': self.active_chat(), 'active_research': self.active_research(), 'character_media': media_state(self.store),
            'materials': {'count': material_summary['counts'].get('ready', 0), 'failed': material_summary['counts'].get('failed', 0)},
            'notes': {'count': len(note_items), 'folders': sorted({n['folder'] for n in note_items if n['folder']})}}

    def active_research(self):
        with self.lock:
            return {'job_id': self.job['id']} if self.job and self.job['state'] == 'running' else None

    def public_learning_projects(self):
        projects=self.store.learning_projects()
        with self.store.connect() as db:
            present={row[0] for row in db.execute('SELECT id FROM documents')}
        for project in projects:
            for task in project['tasks']:
                for source in task.get('evidence',[]):
                    if source.get('document_id') is not None:
                        source['source_deleted']=source['document_id'] not in present
        return projects

    def active_chat(self):
        with self.lock:
            if self.chat_job and self.chat_job['state'] == 'running':
                return {'job_id': self.chat_job['id'], 'session_id': self.chat_job['session_id']}
        return None

    def start_chat(self, body, mobile=False):
        settings = self.models.resolve('chat', body.get('model_id'), mobile=mobile)
        text, material = body.get('text', ''), body.get('material', '')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 12000: raise UserError('消息需要 1–12,000 个字符。')
        if not isinstance(material, str) or len(material) > 35000: raise UserError('附加材料最多 35,000 字符。')
        tools_enabled, local_enabled = body.get('tools_enabled', True), body.get('local_enabled', False)
        materials_enabled=body.get('materials_enabled',False) if not mobile else False
        if not isinstance(materials_enabled,bool):raise UserError('资料读取权限格式无效。')
        if not isinstance(tools_enabled, bool) or not isinstance(local_enabled, bool): raise UserError('工具权限格式无效。')
        with self.lock:
            if self.chat_job and self.chat_job['state'] == 'running': raise UserError('已有对话正在回复，请等待或停止。')
            session = self.chats.get(body.get('session_id'), internal=True)
            user_message = {'role': 'user', 'content': text.strip(), 'material': material, 'status': 'pending'}
            session['messages'].append(user_message)
            if session['title'] == '新的对话': session['title'] = text.strip().splitlines()[0][:40]
            self.chats.save(session)
            job = {'id': secrets.token_hex(10), 'session_id': session['id'], 'state': 'running', 'status': '正在连接模型…',
                   'text': '', 'tools': [], 'evidence': [], 'cancel': threading.Event(), 'result': None, 'error': ''}
            self.chat_job = job

        def emit(kind, value):
            with self.lock:
                if kind == 'status': job['status'] = value
                elif kind == 'turn': job['text'] = ''
                elif kind == 'token': job['text'] += value
                elif kind == 'evidence': job['evidence'].append(value)
                elif kind == 'tool':
                    if value['state'] == 'running': job['tools'].append(value)
                    elif job['tools']: job['tools'][-1] = value

        def worker():
            try:
                result = converse(settings, self.store, session, text.strip(), material, tools_enabled,
                                  local_enabled, job['cancel'], emit, **({'library':self.library,'materials_enabled':True} if materials_enabled else {}))
                with self.lock:
                    if job['cancel'].is_set(): raise Cancelled()
                    user_message['status'] = 'done'
                    session['messages'].append({'role': 'assistant', 'content': result['answer'],
                        'evidence': result['evidence'], 'tools': list(job['tools']), 'status': 'done'})
                    session['turns'] = result['turns']
                    self.chats.save(session)
                    job.update(state='done', status='回复已保存到本机', result=self.chats.get(session['id']))
            except Exception as exc:
                with self.lock:
                    cancelled = isinstance(exc, Cancelled)
                    user_message['status'] = 'cancelled' if cancelled else 'error'
                    error = '已停止。此轮未进入后续模型上下文。' if cancelled else (str(exc) if isinstance(exc, UserError) else '回复未完成，请检查网络、模型兼容性与输入范围。')
                    user_message['error'] = error
                    self.chats.save(session)
                    job.update(state='cancelled' if cancelled else 'error', status=error, error=error,
                               result=self.chats.get(session['id']))
        threading.Thread(target=worker, daemon=True).start()
        return {'job_id': job['id'], 'session': self.chats.get(session['id'])}

    def public_report(self, report_id):
        item = self.store.report(report_id)
        with self.store.connect() as db:
            for evidence in item['evidence']:
                if evidence.get('document_id'):
                    evidence['source_deleted']=not bool(db.execute('SELECT 1 FROM documents WHERE id=?',(evidence['document_id'],)).fetchone())
        return {k: item[k] for k in ['id', 'title', 'created', 'report', 'evidence']}

    def start(self, body, mobile=False):
        notes_enabled = body.get('notes_enabled', False)
        if not isinstance(notes_enabled, bool):
            raise UserError('读取笔记权限必须明确为开启或关闭。')
        materials_enabled = body.get('materials_enabled', False)
        if not isinstance(materials_enabled, bool):
            raise UserError('资料库权限必须明确为开启或关闭。')
        settings = self.models.resolve('research', body.get('model_id'), mobile=mobile)
        previous = self.store.report(body['report_id']) if body.get('report_id') else None
        url = str(body.get('url', '')).strip()
        material = str(body.get('material', ''))
        question = str(body.get('question', '')).strip()
        learning = bool(body.get('learning'))
        track = body.get('track', DEFAULT_LEARNING_TRACK)
        goal = body.get('goal', '')
        if learning:
            if track not in LEARNING_TRACKS or not github_repo(url) or not goal.strip():
                raise UserError('请选择学习方向，填写仓库首页链接和学习目标。')
            question = f'学习方向：{track}\n本次目标：{goal}'
            self.store.set('learning_track', track)
        if not previous and not url and not material.strip():
            raise UserError('请添加项目链接或材料。')
        if previous and not question:
            raise UserError('请输入追问。')
        with self.lock:
            if self.job and self.job['state'] == 'running':
                raise UserError('已有研究正在进行，请先等待完成或停止。')
            self.job = {'id': secrets.token_hex(10), 'state': 'running', 'status': '正在收集材料…',
                        'text': '', 'evidence': [e for e in previous['evidence'] if materials_enabled or e.get('source') != '本地资料库'] if previous else [],
                        'cancel': threading.Event(), 'result': None, 'error': ''}
            job = self.job
        profile = self.store.get('profile', {})
        focus = bool(body.get('agent_focus', False))
        if previous and previous['context'].get('learning_track'):
            focus = previous['context']['learning_track'].startswith('AI Agent') or focus

        def emit(kind, value):
            with self.lock:
                if kind == 'status': job['status'] = value
                elif kind == 'turn': job['text'] = ''
                elif kind == 'token': job['text'] += value
                elif kind == 'evidence': job['evidence'].append(value)

        def worker():
            try:
                result = research(settings, profile, url, material, question, job['cancel'], emit,
                                  previous['context'] if previous else None, agent_focus=focus,
                                  learning=learning, learning_track=track, library=self.library,
                                  materials_enabled=materials_enabled, notes=self.notes, notes_enabled=notes_enabled)
                if job['cancel'].is_set(): raise Cancelled()
                title = previous['title'] if previous else (url.rstrip('/').split('/')[-1] if url else material.strip().splitlines()[0])[:80]
                report = previous['report'] + '\n\n---\n\n## 追问\n' + question + '\n\n' + result['report'] if previous else result['report']
                evidence = list(previous['evidence']) if previous else []
                for item in result['evidence']:
                    if item not in evidence: evidence.append(item)
                report_id = self.store.save_report(title, report, result['context'], evidence, previous['id'] if previous else None)
                # Publish research first. Suggestion failures never change the
                # saved report or create unconfirmed formal learning tasks.
                suggestion_warning=''
                if result['context']['sources'].get('repo') and not previous:
                    try:self.learning_flow.start(report_id,goal or question,track)
                    except Exception:suggestion_warning='报告已保存；学习内容尚未整理，可稍后重试。'

                with self.lock:
                    job.update(state='done', status='研究完成 · 已自动保存到研究历史', result=self.public_report(report_id),
                               warning=suggestion_warning or result.get('learning_warning', ''))
            except Cancelled:
                with self.lock: job.update(state='cancelled', status='已停止，未保存未完成输出。')
            except Exception as exc:
                with self.lock:
                    job.update(state='error', error=str(exc) if isinstance(exc, UserError) else '请求未完成，请检查网络、模型兼容性与材料范围。')
        threading.Thread(target=worker, daemon=True).start()
        return {'job_id': job['id']}

    def dispatch(self, action, body):
        if action == 'workspace_home': return self.workspace.home()
        if action == 'workspace_projects': return {'projects':self.workspace.projects()}
        if action == 'workspace_project': return self.workspace.project(body.get('id'))
        if action == 'learning_position': return self.workspace.position(body if body else None)
        if action == 'learning_drafts': return self.workspace.drafts(body if body else None)
        if action == 'learning_feedback': return self.workspace.feedback(body)
        if action == 'sync_status':
            return {'reports':[{'id':r[0],'title':r[1],'created':r[2]} for r in self.store.reports()], 'active_research':self.active_research()}
        if action == 'tools_list':
            from tool_registry import ToolRegistry
            return {'tools': ToolRegistry(self.plugins).public(), 'plugins': self.plugins.list(), 'audit': self.plugins.audits()}
        if action == 'plugin_catalog': return {'plugins': self.plugins.catalog()}
        if action == 'plugin_preview': return self.plugins.preview(body.get('path'))
        if action == 'plugin_preview_builtin': return self.plugins.preview_builtin(body.get('id'))
        if action == 'plugin_install': return self.plugins.install(body.get('token'), body.get('grants', []))
        if action == 'plugin_toggle': return self.plugins.toggle(body.get('id'), body.get('enabled'), body.get('grants'))
        if action == 'plugin_uninstall': return self.plugins.uninstall(body.get('id'))
        if action == 'plugin_logs': return {'logs': self.plugins.logs(body.get('id'))}
        if action == 'models_list':
            return {'models':self.models.list_public(), 'routes':self.models.routes_public(), 'errors':self.models.errors()}
        if action == 'model_save': return self.models.save(body)
        if action == 'model_delete': return self.models.delete(body.get('id'))
        if action == 'model_routes_save': return self.models.save_routes(body)
        if action == 'model_test_connection': return self.models.test(body.get('id'), body.get('task','chat'))
        if action == 'model_test_capabilities': return self.models.test(body.get('id'), body.get('task','chat'), True)
        if action == 'tasks_list': return self.tasks.list(body)
        if action == 'task_targets': return self.tasks.targets()
        if action == 'task_get': return self.tasks.get(body.get('id'))
        if action == 'task_create': return self.tasks.create(body)
        if action == 'task_update': return self.tasks.update(body.get('id'), body)
        if action == 'task_complete':
            return self.tasks.update(body.get('id'), {'status':'done','revision':body.get('revision')})
        if action == 'automation_list': return self.tasks.automation_list()
        if action == 'automation_create': return self.tasks.automation_create(body)
        if action == 'automation_toggle': return self.tasks.automation_toggle(body)
        if action == 'workflow_runs': return {'runs':self.tasks.runs()}
        if action == 'workflow_prepare': return self.tasks.prepare(body)
        if action == 'workflow_start': return self.tasks.start(body.get('id'), body.get('send_sources') is True)
        if action == 'workflow_get': return self.tasks.run_get(body.get('id'))
        if action == 'workflow_cancel': return self.tasks.cancel(body.get('id'))
        if action == 'github_scan': return self.github_import.launch('scan',body)
        if action == 'github_import': return self.github_import.launch('import',body)
        if action == 'github_poll': return self.github_import.run(body.get('id'))
        if action == 'github_cancel': return self.github_import.cancel(body.get('id'))
        if action == 'github_preview': return self.github_import.preview(body.get('id'))
        if action == 'github_versions': return self.github_import.list()
        if action == 'github_delete': return self.github_import.delete(body.get('id'),body.get('all_versions') is True)
        if action == 'learning_suggestions': return self.learning_flow.list()
        if action == 'learning_suggestion': return self.learning_flow.get(body.get('report_id'))
        if action == 'learning_generate': return self.learning_flow.start(body.get('report_id'),body.get('goal',''),body.get('track',DEFAULT_LEARNING_TRACK),body.get('retry') is True)
        if action == 'learning_cancel': return self.learning_flow.cancel(body.get('report_id'))
        if action == 'learning_defer': return self.learning_flow.defer(body.get('report_id'))
        if action == 'learning_accept': return self.learning_flow.accept(body)
        if action == 'learning_settings': return self.learning_flow.settings(body if body else None)
        if action == 'learning_review_retry': return self.learning_flow.ensure_review(body.get('project_id'),body.get('index'),True)
        if action == 'learning_review_status': return self.learning_flow.review_link(body.get('project_id'),body.get('index'))
        if action == 'learning_from_materials':
            if body.get('send_sources') is not True: raise UserError('请明确允许将选中资料发送给模型。')
            ids=body.get('document_ids',[])
            if not isinstance(ids,list) or not 1<=len(ids)<=10:raise UserError('选择1–10份已成功导入的资料。')
            evidence=[];blocks=[];repo=None
            for ident in ids:
                item=self.library.preview(ident);doc=item['document'];src=doc.get('github',{})
                if not src or doc['status']!='ready':raise UserError('仅支持成功导入的 GitHub 文本资料。')
                if repo and (repo['commit']!=src['commit_sha'] or repo['owner']+'/'+repo['name']!=src['repository']):raise UserError('请选同一个仓库固定版本的资料。')
                owner,name=src['repository'].split('/',1);repo={'owner':owner,'name':name,'commit':src['commit_sha']}
                passage=item['text'][:6000];end=passage.count('\n')+1
                evidence.append({'path':src['file_path'],'url':src['url']+f'#L1-L{end}','start':1,'end':end,'commit':repo['commit'],'document_id':ident,'excerpt':passage})
                blocks.append('## '+src['file_path']+'\n'+passage)
            report=self.store.save_report(repo['owner']+'/'+repo['name']+' · 导入资料学习', '\n\n'.join(blocks),{'sources':{'repo':repo}},evidence)
            return {'report_id':report,'suggestion':self.learning_flow.start(report,body.get('goal',''),body.get('track',DEFAULT_LEARNING_TRACK))}
        if action == 'review_update': return self.review.update(body)
        if action == 'review_history': return self.review.history(body.get('id'))
        if action == 'review_list': return self.review.overview(body)
        if action == 'review_targets': return self.review.targets()
        if action == 'review_source': return self.review.source(body)
        if action == 'review_create': return self.review.create(body)
        if action == 'review_feedback': return self.review.feedback(body)
        if action == 'review_delete': return self.review.delete(body.get('id'))
        if action == 'review_generate': return self.review.generate(body)
        if action == 'review_confirm': return self.review.confirm(body.get('token'))
        if action == 'notes_list':
            items = self.notes.search(body.get('query', ''), folder=body.get('folder', ''), include_deleted=body.get('include_deleted') is True)
            tag = body.get('tag', '')
            all_notes = self.notes.list(include_deleted=body.get('include_deleted') is True)
            return {'notes': [n for n in items if not tag or tag in n['tags']],
                    'folders': sorted({n['folder'] for n in all_notes if n['folder']}),
                    'tags': sorted({t for n in all_notes for t in n['tags']})}
        if action == 'notes_create': return self.notes.create(body.get('title', '未命名笔记'), body.get('content', ''), body.get('tags', []), body.get('folder', ''), body.get('pinned', False), body.get('links', []))
        if action == 'notes_get': return self.notes.get(body.get('id'), include_deleted=body.get('include_deleted') is True)
        if action == 'notes_save': return self.notes.save(body.get('id'), body.get('title', ''), body.get('content', ''), body.get('tags', []), body.get('folder', ''), body.get('pinned', False), body.get('links', []), body.get('revision'))
        if action == 'notes_delete': return self.notes.delete(body.get('id'))
        if action == 'notes_restore': return self.notes.restore(body.get('id'))
        if action == 'notes_versions': return {'versions': self.notes.versions(body.get('id'))}
        if action == 'notes_restore_version': return self.notes.restore_version(body.get('id'), body.get('version'))
        if action == 'notes_reverse': return {'notes': self.notes.reverse(body.get('type'), body.get('id'))}
        if action == 'notes_export': return {'text': self.notes.export(body.get('id'))}
        if action == 'notes_export_folder': return {'files': self.notes.export_folder(body.get('folder', ''))}
        if action == 'notes_targets':
            materials = self.library.list()['documents']
            return {'materials': [{'id':d['id'], 'title':d['title']} for d in materials],
                    'reports': [{'id':r[0], 'title':r[1]} for r in self.store.reports()],
                    'learning': self.store.learning_projects()}
        if action == 'materials_list': return self.library.list(body.get('tag', ''), body.get('project', ''))
        if action == 'materials_search':
            return {'results': self.library.search(body.get('query', ''), title_only=body.get('title_only') is True,
                tag=body.get('tag', ''), project=body.get('project', ''))}
        if action == 'materials_get': return self.library.preview(body.get('id'), body.get('page'), body.get('chunk_id'))
        if action == 'materials_delete': return self.library.delete(body.get('id'))
        if action == 'materials_retry': return self.library.retry(body.get('id'))
        if action == 'materials_update': return self.library.update(body.get('id'), body.get('tags', []), body.get('project', ''))
        if action == 'trending': return self.trending.get(body.get('period','daily'),body.get('refresh',False))
        if action == 'companion': return companion_data(self, mobile=False)
        if action == 'remote_status': return self.remote.status()
        if action == 'remote_start': return self.remote.start()
        if action == 'remote_stop': return self.remote.stop()
        if action == 'remote_renew': return self.remote.renew()
        if action == 'bootstrap': return self.bootstrap()
        if action == 'music':
            enabled = body.get('enabled')
            if not isinstance(enabled, bool): raise UserError('BGM 开关格式无效。')
            self.store.set('bgm_enabled', enabled)
            return {'enabled': enabled}
        if action == 'character_select': return select_character(self.store, body.get('id'))
        if action == 'chat_new': return self.chats.create()
        if action == 'chat_get': return self.chats.get(body.get('id'))
        if action == 'chat_search': return self.chats.search(body.get('query', ''))
        if action == 'chat_trash': return {'sessions': self.chats.list(deleted=True)}
        if action in {'chat_delete', 'chat_restore'}:
            with self.lock:
                if self.chat_job and self.chat_job['state'] == 'running' and self.chat_job['session_id'] == body.get('id'):
                    raise UserError('请先停止回复，完成后再删除对话。')
                return self.chats.delete(body.get('id')) if action == 'chat_delete' else self.chats.restore(body.get('id'))
        if action == 'chat_rename':
            with self.lock:
                if self.chat_job and self.chat_job['state'] == 'running' and self.chat_job['session_id'] == body.get('id'):
                    raise UserError('请在回复完成后修改会话标题。')
                return self.chats.rename(body.get('id'), body.get('title'))
        if action == 'chat_agent':
            config = agent_config(body)
            self.store.set('chat_agent', config)
            return {'agent': config}
        if action == 'chat_start': return self.start_chat(body)
        if action == 'chat_poll':
            with self.lock:
                if not self.chat_job or self.chat_job['id'] != body.get('job_id'): raise UserError('对话任务不存在。')
                return {k: v for k, v in self.chat_job.items() if k != 'cancel'}
        if action == 'chat_cancel':
            with self.lock:
                if not self.chat_job or self.chat_job['id'] != body.get('job_id'): raise UserError('对话任务不存在。')
                self.chat_job['cancel'].set()
            return {'ok': True}
        if action == 'motion':
            prefs = validate_preferences(body)
            self.store.set('wallpaper_motion', prefs)
            return {'motion': prefs}
        if action == 'report': return self.public_report(int(body['id']))
        if action == 'profile':
            profile = body.get('profile', {})
            if not isinstance(profile, dict) or any(not isinstance(v, str) or len(v) > 5000 for v in profile.values()):
                raise UserError('背景字段格式无效。')
            self.store.set('profile', profile)
            return {'ok': True}
        if action == 'settings':
            values = dict(body)
            if values.pop('keep_key', False): values['api_key'] = self.store.settings().get('api_key', '')
            self.store.save_settings(values)
            profiles = self.models.list_public()
            default = next((p for p in profiles if p['is_default']), None)
            self.models.save({**(default or {}), **values, 'name':default['name'] if default else '默认模型',
                              'capabilities':default['capabilities'] if default else ['chat','research','summary','ppt'], 'is_default':True})
            return {'ok': True}
        if action == 'test_connection':
            values = dict(body)
            if values.pop('keep_key', False): values['api_key'] = self.store.settings().get('api_key', '')
            transport = Transport(threading.Event())
            try:
                Model(values, transport).complete([{'role': 'user', 'content': '请只回复：连接成功'}], [], lambda text: None)
                return {'message': '连接成功，可以保存。源码工具调用需在研究时验证。'}
            finally: transport.close()
        if action == 'search':
            transport = Transport(threading.Event())
            try: return search_github(body.get('query', ''), body.get('language', ''), transport)
            finally: transport.close()
        if action == 'start': return self.start(body)
        if action == 'poll':
            with self.lock:
                if not self.job or body.get('job_id') != self.job['id']: raise UserError('研究任务不存在。')
                return {k: v for k, v in self.job.items() if k != 'cancel'}
        if action == 'cancel':
            with self.lock:
                if self.job: self.job['cancel'].set()
            return {'ok': True}
        if action == 'progress':
            return self.learning_flow.progress(body)
        raise UserError('未知操作。')

    def close(self):
        self.learning_flow.close()
        self.github_import.close()
        self.tasks.close()
        self.remote.stop()
        with self.lock:
            if self.job: self.job['cancel'].set()
            if self.chat_job: self.chat_job['cancel'].set()


class DesktopAPI:
    """Flat public bridge: never traverse service, locks or native windows."""
    def __init__(self, bridge):
        self._bridge = bridge

    def open_chat(self): return self._bridge.open_chat()
    def open_url(self, url): return self._bridge.open_url(url)
    def import_file(self): return self._bridge.import_file()
    def import_character(self): return self._bridge.import_character()
    def import_materials(self, folder=False, tags=None, project=''): return self._bridge.import_materials(folder, tags, project)
    def export_file(self, name, text): return self._bridge.export_file(name, text)
    def export_notes_folder(self, folder): return self._bridge.export_notes_folder(folder)
    def close_after_notes(self): return self._bridge.close_after_notes()
    def notes_close_failed(self): return self._bridge.notes_close_failed()


class CompanionBridge:
    """Expose only allowlisted workspace navigation to the companion window."""
    def __init__(self, bridge):
        self._bridge = bridge

    def open_workspace(self, target):
        return self._bridge.open_workspace(target)


class DesktopBridge:
    def __init__(self, service, url=None):
        self.service = service
        self.url = url
        self.chat_window = None
        self.window_lock = threading.Lock()
        self.close_allowed = False
        self.close_pending = False

    def open_chat(self):
        import webview
        with self.window_lock:
            if self.chat_window:
                self.chat_window.show(); self.chat_window.restore()
                return {'opened': True}
            if not self.url: return {'error': '聊天窗口尚未初始化。'}
            self.chat_window = webview.create_window('Agent 对话 · Infra 研究室', self.url+'companion.html',
                width=1280, height=850, min_size=(760, 600), background_color='#ffffff', text_select=True, js_api=CompanionBridge(self))
            def closed(): self.chat_window = None
            self.chat_window.events.closed += closed
            return {'opened': True}

    def open_workspace(self, target):
        """Allowlisted navigation only. Shares the existing main-window controls."""
        import webview
        if target not in {'tasks', 'models', 'materials', 'notes', 'review', 'github'}:
            return {'error': '未知的研究室页面。'}
        if not webview.windows:
            return {'error': '研究室窗口未打开。'}
        main = webview.windows[0]
        main.show()
        main.restore()
        script = "document.getElementById('settings-open').click()" if target == 'models' else "page(" + json.dumps(target) + ")"
        main.evaluate_js(script)
        return {'opened': True}

    def close_chat(self):
        if self.chat_window: self.chat_window.destroy()

    def import_character(self):
        import webview
        filenames = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
            file_types=('角色动作 (*.mp4;*.webm;*.gif;*.webp;*.png;*.jpg;*.jpeg)',))
        if not filenames: return None
        try: return import_character(self.service.store, filenames[0])
        except Exception as exc: return {'error': str(exc) if isinstance(exc, UserError) else '无法导入动作素材。'}

    def import_file(self):
        import webview
        filenames = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
            file_types=('研究材料 (*.md;*.txt;*.pdf;*.py;*.cu;*.cpp;*.rs;*.json;*.yaml;*.toml)', '所有文件 (*.*)'))
        if not filenames: return None
        try: return {'name': Path(filenames[0]).name, 'text': import_material(Path(filenames[0]))}
        except Exception as exc: return {'error': str(exc) if isinstance(exc, UserError) else '无法读取所选材料。'}

    def import_materials(self, folder=False, tags=None, project=''):
        import webview
        try:
            mode = webview.FileDialog.FOLDER if folder else webview.FileDialog.OPEN
            paths = webview.windows[0].create_file_dialog(mode, allow_multiple=not folder)
            if not paths: return None
            return self.service.library.import_paths(paths, tags, project, folder=folder)
        except Exception as exc:
            return {'error': str(exc) if isinstance(exc, (UserError, OSError)) else '无法导入所选资料：' + str(exc)}

    def open_url(self, url):
        import webbrowser
        if isinstance(url, str) and url.startswith(('https://', 'http://')):
            webbrowser.open(url)

    def export_file(self, name, text):
        import re
        import webview
        name = re.sub(r'[<>:"/\\|?*]', '_', str(name))[:100]
        filenames = webview.windows[0].create_file_dialog(webview.FileDialog.SAVE, save_filename=name + '.md', file_types=('Markdown (*.md)',))
        if not filenames: return {'saved': False}
        try:
            Path(filenames[0]).write_text(text, encoding='utf-8')
            return {'saved': True}
        except OSError: return {'error': '无法写入所选文件。'}

    def export_notes_folder(self, folder):
        import webview
        import re
        try:
            files = self.service.notes.export_folder(folder)
            if not files: raise UserError('该文件夹没有可导出的笔记。')
            paths = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not paths: return {'saved': False}
            base = Path(paths[0]).resolve()
            # Create a fresh subdirectory, never overwrite existing exports.
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', folder or '未分类')[:60].strip(' .') or '笔记'
            directory = base / (name + '-笔记-' + time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3))
            directory.mkdir()
            for item in files:
                (directory / item['name']).write_text(item['text'], encoding='utf-8')
            return {'saved': True, 'count': len(files), 'path': str(directory)}
        except (UserError, OSError) as exc: return {'error': str(exc)}

    def close_after_notes(self):
        import webview
        self.close_allowed = True
        self.close_pending = False
        webview.windows[0].destroy()

    def notes_close_failed(self):
        self.close_pending = False


def make_server(service, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def valid(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'} and self.path.startswith('/' + token + '/')
        def reply(self, status, data):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            if not self.valid(): return self.reply(404, {'error': 'Not found'})
            path = urllib.parse.urlsplit(self.path).path[len(token)+2:]
            if path.startswith('media/'):
                file = media_file(service.store, path[6:])
                if not file: return self.reply(404, {'error': 'Not found'})
                size = file.stat().st_size
                start, end = 0, size - 1
                partial = self.headers.get('Range')
                if partial:
                    import re
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', partial)
                    if not match: return self.reply(416, {'error': 'Invalid range'})
                    start = int(match[1]); end = min(int(match[2]) if match[2] else end, end)
                    if start > end: return self.reply(416, {'error': 'Invalid range'})
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(end-start+1)); self.send_header('Accept-Ranges', 'bytes')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if partial: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                with file.open('rb') as source:
                    source.seek(start); remaining = end-start+1
                    while remaining:
                        block = source.read(min(65536, remaining))
                        if not block: break
                        self.wfile.write(block); remaining -= len(block)
                return
            allowed = {'': 'index.html', 'index.html': 'index.html', 'style.css': 'style.css', 'ui.js': 'ui.js', 'wallpaper.webp': 'wallpaper.webp',
                       'materials.js': 'materials.js', 'materials.css': 'materials.css',
                       'workspace.js': 'workspace.js', 'workspace.css': 'workspace.css', 'tail-flow-mask.png':'tail-flow-mask.png', 'water-drift-mask.png':'water-drift-mask.png',
                       'github-import.js': 'github-import.js', 'learning-flow.js': 'learning-flow.js',
                       'notes.js': 'notes.js', 'notes.css': 'notes.css',
                       'review.js': 'review.js', 'review.css': 'review.css',
                       'tasks.js': 'tasks.js', 'tasks.css': 'tasks.css',
                       'models.js': 'models.js', 'models.css': 'models.css',
                       'motion.css': 'motion.css', 'motion.js': 'motion.js', 'chat.css': 'chat.css', 'chat.js': 'chat.js',
                       'entrance.mp4': 'entrance.mp4', 'media.css': 'media.css', 'media.js': 'media.js',
                       'trending.js': 'trending.js', 'scene.js': 'scene.js', 'entrance.js': 'entrance.js', 'entrance-paths.js': 'entrance-paths.js', 'wallpaper-outline-glow.png': 'wallpaper-outline-glow.png', 'wallpaper-face.png': 'wallpaper-face.png', 'wallpaper-outline.png': 'wallpaper-outline.png',
                       'actions.js': 'actions.js', 'wallpaper-blink.webp': 'wallpaper-blink.webp', 'wallpaper-eyelids.png': 'wallpaper-eyelids.png', 'wallpaper-smile.png': 'wallpaper-smile.png',
                       'wallpaper-rig-base.webp': 'wallpaper-rig-base.webp', 'wallpaper-rig-base.png': 'wallpaper-rig-base.png', 'forearm-layer.png': 'forearm-layer.png',
                       'companion.html': 'companion.html', 'companion.css': 'companion.css', 'companion.js': 'companion.js',
                       'format.js': 'format.js', 'remote-ui.js': 'remote-ui.js', 'music.js': 'music.js', 'music.css': 'music.css'}
            if path not in allowed: return self.reply(404, {'error': 'Not found'})
            raw = (assets() / 'static' / allowed[path]).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(allowed[path])[0] or 'application/octet-stream')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-src https://music.163.com; frame-ancestors 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)
        def do_POST(self):
            origin = self.headers.get('Origin')
            expected = f'http://127.0.0.1:{self.server.server_port}'
            if not self.valid() or (origin and origin != expected): return self.reply(403, {'error': 'Forbidden'})
            if self.path != '/' + token + '/api': return self.reply(404, {'error': 'Not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 300_000: raise UserError('请求材料过大。')
                body = json.loads(self.rfile.read(length))
                result = service.dispatch(body['action'], body.get('body', {}))
                self.reply(200, result)
            except UserError as exc: self.reply(400, {'error': str(exc)})
            except Exception: self.reply(400, {'error': '请求未完成，请核对输入或服务配置。'})
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview-server', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    service = Service(Store(args.data_dir) if args.data_dir else None)
    service.tasks.start_scheduler()
    token = secrets.token_urlsafe(24)
    server = make_server(service, token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/{token}/'
    if args.preview_server:
        print(url, flush=True)
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt: pass
    else:
        import webview
        bridge = DesktopBridge(service, url)
        window = webview.create_window('Infra 研究室 · AI Infra / AI Agent', url, js_api=DesktopAPI(bridge),
            width=1440, height=900, min_size=(1100, 730), background_color='#eaf6fc', text_select=True)
        def motion_visibility(hidden):
            def update():
                try: window.evaluate_js('window.WallpaperMotion?.setWindowHidden(' + ('true' if hidden else 'false') + ')')
                except Exception: pass
            threading.Thread(target=update, daemon=True).start()
        window.events.minimized += lambda: motion_visibility(True)
        window.events.restored += lambda: motion_visibility(False)
        def save_notes_before_close():
            if bridge.close_allowed:
                return
            # Closing fires on the WinForms UI thread. Evaluate in a worker so
            # WebView2's UI-thread Invoke cannot deadlock window shutdown.
            if not bridge.close_pending:
                bridge.close_pending = True
                def prepare_close():
                    try:
                        window.evaluate_js('void Promise.all([window.NotesUI ? window.NotesUI.flush() : Promise.resolve(),window.LearningUI ? window.LearningUI.flush() : Promise.resolve()]).then(()=>window.pywebview.api.close_after_notes()).catch(error=>{window.pywebview.api.notes_close_failed();toast("学习或笔记未保存，请重试保存后关闭："+error.message);})')
                    except Exception:
                        bridge.notes_close_failed()
                threading.Thread(target=prepare_close, daemon=True).start()
            return False
        window.events.closing += save_notes_before_close
        window.events.closed += service.close
        window.events.closed += bridge.close_chat
        def smoke():
            if args.smoke_test:
                for _ in range(30):
                    time.sleep(.3)
                    try:
                        if window.evaluate_js("document.documentElement.dataset.ready === 'true' && document.documentElement.dataset.motionReady === 'true' && document.documentElement.dataset.chatReady === 'true' && document.documentElement.dataset.mediaReady === 'true' && document.documentElement.dataset.materialsReady === 'true' && document.documentElement.dataset.notesReady === 'true' && document.documentElement.dataset.reviewReady === 'true' && document.documentElement.dataset.tasksReady === 'true' && document.documentElement.dataset.modelsReady === 'true' && document.documentElement.dataset.githubImportReady === 'true' && document.documentElement.dataset.learningFlowReady === 'true' && document.documentElement.dataset.workspaceReady === 'true'"):
                            scene = window.evaluate_js('document.documentElement.dataset.sceneReady')
                            (service.store.directory / 'webview-smoke-passed.txt').write_text('WebView page, bootstrap, motion, chat, media, materials, notes, review and tasks controls initialized. Scene renderer: ' + str(scene), encoding='utf-8')
                            window.evaluate_js("document.getElementById('settings-open').click()")
                            for _ in range(30):
                                time.sleep(.2)
                                if window.evaluate_js("document.getElementById('settings-modal').classList.contains('open') && document.querySelectorAll('[data-task]').length === 4 && document.getElementById('model-mobile') !== null"):
                                    (service.store.directory / 'models-smoke-passed.txt').write_text('Devices and models modal opened; four task routes and desktop-only mobile authorization initialized.', encoding='utf-8')
                                    break
                            window.evaluate_js("document.querySelector('[data-close=\"settings-modal\"]').click()")
                            bridge.open_chat()
                            for _ in range(30):
                                time.sleep(.3)
                                if bridge.chat_window.evaluate_js("document.documentElement.dataset.companionReady === 'true'"):
                                    (service.store.directory / 'companion-smoke-passed.txt').write_text('Independent white chat window initialized; shared service connected.', encoding='utf-8')
                                    break
                            first = bridge.chat_window
                            bridge.open_chat()
                            if bridge.chat_window is not first: raise RuntimeError('Chat window not reused')
                            bridge.close_chat()
                            for _ in range(30):
                                if bridge.chat_window is None: break
                                time.sleep(.1)
                            bridge.open_chat()
                            for _ in range(30):
                                time.sleep(.3)
                                if bridge.chat_window.evaluate_js("document.documentElement.dataset.companionReady === 'true'"):
                                    (service.store.directory / 'companion-lifecycle-passed.txt').write_text('Chat reused, closed and reopened successfully.', encoding='utf-8')
                                    break
                            window.destroy()
                            return
                    except Exception: pass
                window.destroy()
        webview.start(smoke, gui='edgechromium')
    service.close()
    server.shutdown()
    server.server_close()


if __name__ == '__main__': main()
