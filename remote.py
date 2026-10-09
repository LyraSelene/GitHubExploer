"""Opt-in LAN companion; paired sessions expose only research/chat operations."""
from __future__ import annotations
import ipaddress
import json
import secrets
import socket
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from core import UserError, assets

ALLOWED = {'bootstrap', 'chat_new', 'chat_get', 'chat_search', 'chat_rename', 'chat_delete', 'chat_restore', 'chat_trash', 'chat_start', 'chat_poll',
           'chat_cancel', 'report', 'start', 'poll', 'cancel', 'progress'}
STATIC = {'': 'companion.html', 'companion.html': 'companion.html',
          'companion.css': 'companion.css', 'companion.js': 'companion.js', 'format.js': 'format.js'}

class CompanionServer(ThreadingHTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

def lan_addresses():
    addresses = set()
    for address in socket.gethostbyname_ex(socket.gethostname())[2]:
        ip = ipaddress.ip_address(address)
        if ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local:
            addresses.add(address)
    return sorted(addresses)

def companion_data(service, mobile=True):
    with service.lock:
        active = ({'job_id': service.job['id'], 'state': service.job['state'], 'status': service.job['status']}
                  if service.job else None)
    service.models._migrate_legacy()
    models = service.models.list_public(mobile=mobile)
    models = [{k:v for k,v in m.items() if k in {'id','name','vendor','model','capabilities'}} for m in models]
    return {'profile': service.store.get('profile', {}), 'model': models[0]['model'] if models else '暂无可用模型', 'models':models,
            'agent': service.chats.agent(), 'sessions': service.chats.list(),
            'reports': [{'id': r[0], 'title': r[1], 'created': r[2]} for r in service.store.reports()],
            'learning': service.store.learning_projects(), 'active_chat': service.active_chat(),
            'active_research': active}

class RemoteAccess:
    def __init__(self, service):
        self.service = service
        self.lock = threading.RLock()
        self.server = None
        self.sessions = {}
        self.attempts = {}
        self.code = ''
        self.code_until = 0
        self.addresses = []

    def status(self):
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if v > now}
            return {'enabled': self.server is not None,
                    'urls': [f'http://{ip}:{self.server.server_port}/' for ip in self.addresses] if self.server else [],
                    'code': self.code if now < self.code_until and self.server else '',
                    'code_seconds': max(0, int(self.code_until-now)) if self.server else 0,
                    'devices': len(self.sessions)}

    def start(self, addresses=None, bind='0.0.0.0'):
        with self.lock:
            if self.server: return self.status()
            self.addresses = addresses if addresses is not None else lan_addresses()
            if not self.addresses: raise UserError('未找到局域网 IPv4 地址，请先连接 Wi-Fi。')
            self.code = str(secrets.randbelow(900000)+100000)
            self.code_until = time.monotonic()+600
            self.sessions.clear(); self.attempts.clear()
            self.server = self.make_server(bind)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            return self.status()

    def renew(self):
        with self.lock:
            if not self.server: raise UserError('请先开启手机连接。')
            self.code = str(secrets.randbelow(900000)+100000)
            self.code_until = time.monotonic()+600
            return self.status()

    def stop(self):
        with self.lock:
            server, self.server = self.server, None
            self.sessions.clear(); self.attempts.clear(); self.code = ''; self.code_until = 0
        if server:
            server.shutdown(); server.server_close()
        return self.status()

    def dispatch(self, action, body):
        if action not in ALLOWED: raise UserError('手机端不支持此操作。')
        if action == 'bootstrap': return companion_data(self.service)
        if action == 'start':
            # The phone surface has no explicit materials-permission control.
            # Never let a crafted LAN request silently grant the Agent library access.
            body = dict(body or {})
            body['materials_enabled'] = False
            body['notes_enabled'] = False
            return self.service.start(body, mobile=True)
        if action == 'chat_start': return self.service.start_chat(body, mobile=True)
        return self.service.dispatch(action, body)

    def make_server(self, bind):
        remote = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def valid(self):
                host = self.headers.get('Host', '')
                allowed = {f'{ip}:{self.server.server_port}' for ip in remote.addresses}
                origin = self.headers.get('Origin')
                return (host in allowed and (not origin or origin == 'http://'+host)
                        and self.headers.get('Sec-Fetch-Site') not in {'cross-site'})
            def write(self, status, raw, content='application/json; charset=utf-8', cookie=None):
                self.send_response(status)
                self.send_header('Content-Type', content); self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                if cookie: self.send_header('Set-Cookie', cookie)
                self.end_headers(); self.wfile.write(raw)
            def reply(self, status, value, cookie=None):
                self.write(status, json.dumps(value, ensure_ascii=False).encode(), cookie=cookie)
            def authorized(self):
                try:
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    key = cookies['infra_phone'].value
                except (KeyError, ValueError): return False
                with remote.lock:
                    return remote.server is self.server and remote.sessions.get(key, 0)>time.monotonic()
            def do_GET(self):
                if not self.valid(): return self.reply(403, {'error': '连接地址无效。'})
                path = urllib.parse.urlsplit(self.path).path.lstrip('/')
                if path not in STATIC: return self.reply(404, {'error': 'Not found'})
                filename = STATIC[path]
                mime = 'text/html; charset=utf-8' if filename.endswith('.html') else 'text/css' if filename.endswith('.css') else 'text/javascript'
                self.write(200, (assets()/'static'/filename).read_bytes(), mime)
            def do_POST(self):
                if not self.valid(): return self.reply(403, {'error': '连接来源无效。'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.reply(415, {'error': '需要 JSON 请求。'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0<length<=300000: raise UserError('请求材料过大。')
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict): raise UserError('请求格式无效。')
                    if self.path == '/pair':
                        with remote.lock:
                            now = time.monotonic(); ip = self.client_address[0]
                            failures = [x for x in remote.attempts.get(ip, []) if now-x<600]
                            remote.attempts[ip] = failures
                            if len(failures)>=5: return self.reply(429, {'error': '尝试过多，请在十分钟后重试。'})
                            code = body.get('code')
                            if remote.server is not self.server or now>=remote.code_until or not isinstance(code, str) or not secrets.compare_digest(code, remote.code):
                                failures.append(now); return self.reply(403, {'error': '配对码错误或已过期，请查看电脑端。'})
                            if len(remote.sessions)>=10: raise UserError('已达到连接设备上限，请在电脑端关闭后重新开启。')
                            key = secrets.token_urlsafe(32); remote.sessions[key]=now+12*3600
                            return self.reply(200, {'ok': True}, f'infra_phone={key}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
                    if self.path != '/api': return self.reply(404, {'error': 'Not found'})
                    if not self.authorized(): return self.reply(401, {'error': '请先配对，或在电脑端重新开启连接。'})
                    payload = body.get('body', {})
                    if not isinstance(payload, dict): raise UserError('请求格式无效。')
                    self.reply(200, remote.dispatch(body.get('action'), payload))
                except (UserError, ValueError, TypeError) as exc:
                    self.reply(400, {'error': str(exc) if isinstance(exc, UserError) else '请求格式无效。'})
                except Exception: self.reply(400, {'error': '请求未完成，请检查输入。'})
        server = CompanionServer((bind, 0), Handler)
        server.timeout = 5
        return server
