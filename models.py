"""Multiple local model profiles, task routing and redacted metrics."""
from __future__ import annotations

import json
import math
import time
import threading
import re
import sqlite3
from datetime import datetime, timezone

from core import Model, Transport, UserError, Cancelled, protect_secret, validate_endpoint

TASKS = ("research", "chat", "summary", "ppt")

def safe_error(exc):
    # Never persist endpoint response bodies or exception text that might echo a key.
    if isinstance(exc, Cancelled): return "请求已取消。"
    code = re.match(r"^HTTP (\d{3})：", str(exc))
    if code: return "HTTP " + code[1] + "：模型服务拒绝请求，请检查配置与额度。"
    return "模型请求失败（" + type(exc).__name__ + "），请检查网络、模型与接口兼容性。"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ModelManager:
    def __init__(self, store):
        self.store = store
        self._schema()
        self._migrate_legacy()

    def _schema(self):
        with self.store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS model_profiles (
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, vendor TEXT NOT NULL,
              base_url TEXT NOT NULL, model_name TEXT NOT NULL, capabilities TEXT NOT NULL DEFAULT '[]',
              is_default INTEGER NOT NULL DEFAULT 0, mobile_authorized INTEGER NOT NULL DEFAULT 0,
              secret TEXT NOT NULL DEFAULT '', source_tools INTEGER NOT NULL DEFAULT 1,
              request_count INTEGER NOT NULL DEFAULT 0, estimated_tokens INTEGER NOT NULL DEFAULT 0,
              failure_count INTEGER NOT NULL DEFAULT 0, total_latency_ms REAL NOT NULL DEFAULT 0,
              last_error TEXT NOT NULL DEFAULT '', last_request_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_routes (
              task TEXT PRIMARY KEY, primary_id INTEGER, backup_id INTEGER, fallback_enabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS model_errors (
              id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, task TEXT NOT NULL,
              error TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """)

    def _migrate_legacy(self):
        with self.store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM model_profiles").fetchone()[0]
            if not count:
                old = self.store.get("settings", {}) or {}
                if old.get("model"):
                    stamp = now()
                    db.execute("""INSERT INTO model_profiles
                      (name,vendor,base_url,model_name,capabilities,is_default,mobile_authorized,secret,source_tools,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""", ("默认模型", "OpenAI 兼容", old.get("base_url", "https://api.openai.com/v1").rstrip("/"),
                      old["model"].strip(), json.dumps(["chat", "research", "summary", "ppt"]), 1, 0,
                      old.get("secret", ""), int(old.get("source_tools", True)), stamp, stamp))
            profile = db.execute("SELECT id FROM model_profiles WHERE is_default=1 ORDER BY id LIMIT 1").fetchone()
            if not profile:
                profile = db.execute("SELECT id FROM model_profiles ORDER BY id LIMIT 1").fetchone()
                if profile: db.execute("UPDATE model_profiles SET is_default=1 WHERE id=?", (profile[0],))
            if profile:
                for task in TASKS:
                    db.execute("INSERT OR IGNORE INTO model_routes(task,primary_id) VALUES(?,?)", (task, profile[0]))

    @staticmethod
    def _caps(value):
        if isinstance(value, str): value = value.split(",")
        if not isinstance(value, list): raise UserError("能力标签格式无效。")
        result = [str(x).strip().lower() for x in value if str(x).strip()]
        return list(dict.fromkeys(result))[:12]

    def _row(self, row):
        item = dict(row)
        item["capabilities"] = json.loads(item["capabilities"] or "[]")
        item["model"] = item.pop("model_name")
        item["is_default"] = bool(item["is_default"]); item["mobile_authorized"] = bool(item["mobile_authorized"])
        item['source_tools'] = bool(item['source_tools'])
        latency = item.pop("total_latency_ms") / max(1, item["request_count"])
        item["metrics"] = {"request_count": item.pop("request_count"), "estimated_tokens": item.pop("estimated_tokens"),
                           "failure_count": item.pop("failure_count"), "avg_latency_ms": round(latency, 1),
                           "last_error": item["last_error"], "last_request_at": item["last_request_at"]}
        item["has_key"] = bool(item.pop("secret"))
        return item

    def list_public(self, mobile=False):
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM model_profiles ORDER BY is_default DESC,id").fetchall()
        values = [self._row(r) for r in rows]
        if mobile:
            return [{k:v for k,v in item.items() if k in {"id","name","vendor","model","capabilities"}} for item in values if item["mobile_authorized"]]
        return values

    def routes_public(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT task,primary_id,backup_id,fallback_enabled FROM model_routes").fetchall()
        return {r[0]: {"primary_id": r[1], "backup_id": r[2], "fallback_enabled": bool(r[3])} for r in rows}

    def save(self, values):
        ident = values.get("id")
        name, vendor = str(values.get("name", "")).strip(), str(values.get("vendor", "OpenAI 兼容")).strip()
        base, model = str(values.get("base_url", "")).strip().rstrip("/"), str(values.get("model", values.get("model_name", ""))).strip()
        if not name or not model or len(name)>100 or len(model)>200 or len(vendor)>100 or len(base)>2000: raise UserError("请填写有效的模型名称和模型标识。")
        for flag in ("is_default", "mobile_authorized", "source_tools"):
            if flag in values and not isinstance(values[flag], bool): raise UserError("模型开关必须为布尔值。")
        validate_endpoint(base); caps = self._caps(values.get("capabilities", ["chat", "research"]))
        stamp = now(); secret = values.get("api_key")
        with self.store.connect() as db:
            old = db.execute("SELECT secret FROM model_profiles WHERE id=?", (ident,)).fetchone() if ident else None
            if values.get("clear_key") is True: secret = ""
            elif secret is None or secret == "": secret = old[0] if old else ""
            elif not isinstance(secret, str): raise UserError("API Key 格式无效。")
            elif secret: secret = protect_secret(secret)
            first = not db.execute("SELECT 1 FROM model_profiles LIMIT 1").fetchone()
            default = values.get("is_default") is True or first
            params = (name,vendor,base,model,json.dumps(caps,ensure_ascii=False),int(default),int(values.get("mobile_authorized") is True),secret,int(values.get("source_tools",True)),stamp)
            if ident:
                if not old: raise UserError("模型配置不存在。")
                db.execute("UPDATE model_profiles SET name=?,vendor=?,base_url=?,model_name=?,capabilities=?,is_default=?,mobile_authorized=?,secret=?,source_tools=?,updated_at=? WHERE id=?", params + (ident,))
            else:
                ident = db.execute("INSERT INTO model_profiles(name,vendor,base_url,model_name,capabilities,is_default,mobile_authorized,secret,source_tools,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", params + (stamp,)).lastrowid
            if default:
                db.execute("UPDATE model_profiles SET is_default=0 WHERE id!=?", (ident,))
            elif not db.execute("SELECT 1 FROM model_profiles WHERE is_default=1").fetchone():
                db.execute("UPDATE model_profiles SET is_default=1 WHERE id=?", (ident,))
            for task in TASKS: db.execute("INSERT OR IGNORE INTO model_routes(task,primary_id) VALUES(?,?)", (task, ident))
        return next(x for x in self.list_public() if x["id"] == ident)

    def delete(self, ident):
        with self.store.connect() as db:
            if not db.execute("SELECT 1 FROM model_profiles WHERE id=?", (ident,)).fetchone(): raise UserError("模型配置不存在。")
            if db.execute("SELECT COUNT(*) FROM model_profiles").fetchone()[0] <= 1: raise UserError("至少保留一个模型配置。")
            db.execute("DELETE FROM model_profiles WHERE id=?", (ident,)); db.execute("UPDATE model_routes SET primary_id=NULL WHERE primary_id=?", (ident,)); db.execute("UPDATE model_routes SET backup_id=NULL WHERE backup_id=?", (ident,))
            db.execute("DELETE FROM model_errors WHERE profile_id=?", (ident,))
        self._migrate_legacy()
        return {"ok": True}

    def save_routes(self, values):
        if not isinstance(values, dict): raise UserError("模型路由格式无效。")
        with self.store.connect() as db:
            for task in TASKS:
                item = values.get(task, {})
                primary, backup = item.get("primary_id"), item.get("backup_id")
                if not isinstance(item.get("fallback_enabled", False), bool): raise UserError("自动切换需明确开启。")
                if primary and primary == backup: raise UserError("主模型与备用模型应不同。")
                for ident in (primary, backup):
                    if ident is not None:
                        row = db.execute("SELECT capabilities FROM model_profiles WHERE id=?", (ident,)).fetchone()
                        if not row: raise UserError("路由模型不存在。")
                        if task not in json.loads(row[0]): raise UserError("所选模型缺少该任务的能力标签。")
                if item.get("fallback_enabled") and not backup: raise UserError("开启自动切换前请选择备用模型。")
                db.execute("INSERT OR REPLACE INTO model_routes(task,primary_id,backup_id,fallback_enabled) VALUES(?,?,?,?)", (task,primary,backup,int(item.get("fallback_enabled") is True)))
        return self.routes_public()

    def resolve(self, task, selected_id=None, mobile=False, fallback=True):
        if task not in TASKS: raise UserError("模型任务类型无效。")
        self._migrate_legacy()
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            route = db.execute("SELECT * FROM model_routes WHERE task=?", (task,)).fetchone()
            if selected_id is not None: row = db.execute("SELECT * FROM model_profiles WHERE id=?", (selected_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM model_profiles WHERE id=?", (route['primary_id'],)).fetchone() if route and route['primary_id'] else db.execute("SELECT * FROM model_profiles WHERE is_default=1 LIMIT 1").fetchone()
        if not row: raise UserError("请先配置可用模型。")
        if mobile and not bool(row['mobile_authorized']): raise UserError("手机只能使用电脑明确授权的模型。")
        if task not in json.loads(row['capabilities']): raise UserError("模型缺少当前任务的能力标签。")
        item = {'base_url':row['base_url'], 'model':row['model_name'], 'api_key':protect_secret(row['secret'], decrypt=True) if row['secret'] else '',
                'source_tools':bool(row['source_tools']), 'profile_id':row['id'], 'task':task, '_manager':self, '_mobile':mobile}
        # Explicit per-request choices never enable an unrequested alternate model.
        if fallback and selected_id is None and route and route['fallback_enabled'] and route['backup_id']:
            item['_backup_id'] = route['backup_id']
        return item

    def record(self, profile_id, task, prompt_chars, output_chars, elapsed_ms, success, error=""):
        tokens = math.ceil((max(0,int(prompt_chars)) + max(0,int(output_chars))) / 4)
        with self.store.connect() as db:
            db.execute("UPDATE model_profiles SET request_count=request_count+1,estimated_tokens=estimated_tokens+?,failure_count=failure_count+?,total_latency_ms=total_latency_ms+?,last_error=CASE WHEN ?!='' THEN ? ELSE last_error END,last_request_at=?,updated_at=? WHERE id=?", (tokens, int(not success), float(elapsed_ms),error,error, now(), now(), profile_id))
            if error: db.execute("INSERT INTO model_errors(profile_id,task,error,created_at) VALUES(?,?,?,?)", (profile_id,task,str(error)[:500],now()))

    def settings_for(self, task, selected_id=None):
        return self.resolve(task, selected_id)

    def errors(self):
        with self.store.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM model_errors ORDER BY id DESC LIMIT 30")]

    def test(self, ident, task="chat", capability=False):
        settings = self.resolve(task, ident, fallback=False); transport = Transport(threading.Event())
        try:
            model = Model(settings, transport)
            if not capability:
                response = model.complete([{"role":"user","content":"请只回复：连接成功"}], [], lambda _:None)
                if not response.get('content'): raise UserError('连接成功但没有文字响应。')
                return {"ok":True,"message":"连接成功 · 已收到文字响应"}
            # Check actual structured output and tool call behavior, not the model's self-description.
            response = model.complete([{'role':'user','content':'材料：队列容量是8，请求满时拒绝。仅返回JSON对象，包含capacity:8和overflow:"reject"，不要代码围栏。'}], [], lambda _:None)
            try: valid = json.loads(response.get('content','')) == {'capacity':8,'overflow':'reject'}
            except ValueError: valid = False
            checks = [{'name':'结构化材料提取','passed':valid}]
            if task == 'research':
                tool = {'type':'function','function':{'name':'probe_source','description':'读取测试材料','parameters':{'type':'object','properties':{},'additionalProperties':False}}}
                response = model.complete([{'role':'user','content':'必须调用probe_source一次读取来源，不要直接回答。'}], [tool], lambda _:None)
                calls = response.get('tool_calls', [])
                checks.append({'name':'研究工具调用格式', 'passed':any(c.get('function',{}).get('name')=='probe_source' and c.get('function',{}).get('arguments','').strip()=='{}' for c in calls)})
            return {'ok':all(x['passed'] for x in checks),'checks':checks,'message':'行为检查完成；仅验证此样例，不代表研究质量、上下文长度或所有能力。'}
        finally: transport.close()
