import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core import (Cancelled, Model, Sources, Store, Transport, UserError,
                  github_repo, protect_secret, research, validate_endpoint)


class Response(io.BytesIO):
    def __init__(self, raw, content_type="text/event-stream"):
        super().__init__(raw)
        self.headers = {"Content-Type": content_type}


class FakeTransport:
    def __init__(self, raw, content_type="text/event-stream"):
        self.raw = raw
        self.content_type = content_type
        self.requests = []

    def check(self):
        pass

    def open(self, url, payload, headers, authenticated):
        self.requests.append((url, payload, headers, authenticated))
        return Response(self.raw, self.content_type)


def event(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


class CoreTests(unittest.TestCase):
    def test_windows_secret_and_store_roundtrip(self):
        secret = "测试-secret-with-symbols-123"
        encrypted = protect_secret(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(protect_secret(encrypted, True), secret)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_settings({"base_url": "https://example.com/v1", "model": "test", "api_key": secret, "source_tools": True})
            self.assertEqual(store.settings()["api_key"], secret)
            self.assertNotIn(secret, store.path.read_bytes().decode("latin1"))
            context = {"messages": [{"role": "user", "content": "资料"}], "sources": {"files": ["main.py"]}}
            report_id = store.save_report("仓库", "报告", context, [{"path": "main.py"}])
            self.assertEqual(store.report(report_id)["context"], context)
            store.save_report("仓库", "追问后报告", context, [], report_id)
            self.assertEqual(len(store.reports()), 1)
            self.assertEqual(store.report(report_id)["report"], "追问后报告")

    def test_endpoint_rejects_remote_plaintext_or_embedded_credentials(self):
        for url in ["http://remote.example/v1", "https://key@server.test/v1", "https://server.test/v1?key=x", "file:///tmp/key"]:
            with self.assertRaises(UserError):
                validate_endpoint(url)
        validate_endpoint("http://127.0.0.1:11434/v1")
        validate_endpoint("https://api.example.com/v1")

    def test_stream_text_and_fragmented_tool_arguments(self):
        raw = event({"choices": [{"delta": {"content": "你好", "tool_calls": [{"index": 0, "id": "call1", "function": {"name": "read_repository_file", "arguments": '{"path":'}}]}}]})
        raw += event({"choices": [{"delta": {"content": "世界", "tool_calls": [{"index": 0, "function": {"arguments": '"main.py","start_line":1,"end_line":20}'}}]}, "finish_reason": "tool_calls"}]})
        raw += "data: [DONE]\n\n"
        transport = FakeTransport(raw.encode())
        model = Model({"base_url": "https://example.com/v1", "model": "test", "api_key": "secret"}, transport)
        text = []
        result = model.complete([{"role": "user", "content": "test"}], [], text.append)
        self.assertEqual("".join(text), "你好世界")
        self.assertEqual(json.loads(result["tool_calls"][0]["function"]["arguments"])["path"], "main.py")
        self.assertTrue(transport.requests[0][3])

    def test_truncated_stream_is_not_complete(self):
        for reason in [None, "length", "content_filter"]:
            data = event({"choices": [{"delta": {"content": "partial"}, "finish_reason": reason}]})
            transport = FakeTransport(data.encode())
            model = Model({"base_url": "https://example.com/v1", "model": "test"}, transport)
            with self.assertRaises(UserError):
                model.complete([], [], lambda text: None)

    def test_json_fallback_model(self):
        raw = json.dumps({"choices": [{"message": {"content": "完成"}, "finish_reason": "stop"}]}).encode()
        model = Model({"base_url": "https://example.com/v1", "model": "test"}, FakeTransport(raw, "application/json"))
        self.assertEqual(model.complete([], [], lambda text: None)["content"], "完成")

    def test_sources_only_read_actual_repo_paths_and_record_lines(self):
        class RepoTransport:
            calls = []
            def check(self): pass
            def read(self, url):
                self.calls.append(url)
                return b"line1\nline2\nline3\n"
        transport = RepoTransport()
        sources = Sources(transport, lambda *args: None)
        sources.repo = {"owner": "org", "name": "repo", "commit": "abc"}
        sources.files = ["main.py"]
        self.assertIn("不在", sources.read_file("../secret", 1, 20))
        self.assertEqual(transport.calls, [])
        result = sources.read_file("main.py", 2, 2000)
        self.assertIn("2: line2", result)
        self.assertNotIn("1: line1", result)
        self.assertEqual(sources.evidence[0]["start"], 2)
        self.assertEqual(sources.evidence[0]["end"], 3)
        sources.read_count = 10
        self.assertIn("预算", sources.read_file("main.py", 1, 2))
        self.assertEqual(len(transport.calls), 1)

    def test_cancel_before_network(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            Transport(cancel).open("https://example.com")

    def test_author_history_is_pinned_bounded_and_preserves_evidence(self):
        class HistoryTransport:
            def __init__(self): self.urls = []
            def json(self, url):
                self.urls.append(url)
                return [{"sha": "123", "html_url": "https://github.com/o/r/commit/123",
                         "commit": {"author": {"date": "2026-01-02"}, "message": "Add bounded tool loop"}}]
        transport = HistoryTransport()
        sources = Sources(transport, lambda *args: None)
        sources.repo = {"owner": "o", "name": "r", "commit": "fixed123"}
        sources.files = ["agent.py"]
        self.assertIn("路径", sources.history("missing.py"))
        self.assertEqual(transport.urls, [])
        result = sources.history("agent.py")
        self.assertIn("sha=fixed123", transport.urls[0])
        self.assertIn("path=agent.py", transport.urls[0])
        self.assertIn("不是完整开发过程", result)
        self.assertIn("2026-01-02", result)
        self.assertEqual(sources.evidence[0]["excerpt"], result)
        sources.history_count = 4
        self.assertIn("预算", sources.history(""))
        state = sources.snapshot()
        restored = Sources(transport, lambda *args: None)
        restored.restore(state)
        self.assertEqual(restored.history_count, 4)

    def test_discussion_comments_have_version_and_truncation_limits(self):
        class DiscussionTransport:
            def json(self, url):
                if "/comments?" in url:
                    return [{"html_url": "https://github.com/o/r/issues/2#comment", "created_at": "2026-01-03", "body": "x" * 1600}]
                return {"title": "Why this workflow?", "html_url": "https://github.com/o/r/issues/2", "body": "design", "comments": 20}
        sources = Sources(DiscussionTransport(), lambda *args: None)
        sources.repo = {"owner": "o", "name": "r", "commit": "fixed"}
        self.assertIn("正整数", sources.discussion(True))
        result = sources.discussion(2)
        self.assertIn("可能晚于", result)
        self.assertIn('"body_truncated": true', result)
        self.assertIn('"comments_total": 20', result)
        self.assertEqual(sources.history_count, 1)

    def test_agent_focus_applies_to_new_and_existing_reports(self):
        seen = []
        def complete(model, messages, tools, emit):
            seen.append(list(messages))
            return {"role": "assistant", "content": "分析结果"}
        settings = {"base_url": "https://example.com/v1", "model": "test"}
        with patch.object(Model, "complete", complete):
            result = research(settings, {}, "", "仅 README", "", threading.Event(), lambda *args: None, agent_focus=True)
            self.assertIn("AI Agent 学习价值与作者构建路径", seen[0][1]["content"])
            research(settings, {}, "", "", "补充", threading.Event(), lambda *args: None, previous=result["context"], agent_focus=True)
            self.assertIn("有记录的实际演进", seen[1][-1]["content"])

    def test_repo_parser_rejects_ambiguous_branch_links(self):
        self.assertEqual(github_repo("https://github.com/org/repo.git"), ("org", "repo"))
        self.assertIsNone(github_repo("https://article.example.com/x"))
        with self.assertRaises(UserError):
            github_repo("https://github.com/org/repo/tree/main")

    def test_research_reads_tool_results_before_final_and_can_resume(self):
        events, seen = [], []
        def prepare(sources, url, material):
            sources.repo = {"owner": "org", "name": "repo", "commit": "abc"}
            sources.files = ["main.py"]
            return "README evidence"
        def complete(model, messages, tools, emit):
            seen.append(list(messages))
            if len(seen) == 1:
                return {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {
                    "name": "read_repository_file", "arguments": '{"path":"main.py","start_line":1,"end_line":2}'}}]}
            emit("最终报告")
            return {"role": "assistant", "content": "最终报告"}
        with patch.object(Sources, "prepare", prepare), patch.object(Model, "complete", complete), patch.object(Transport, "read", return_value=b"core\nresult"):
            result = research({"base_url": "https://example.com/v1", "model": "test"}, {}, "", "material", "", threading.Event(), lambda *event: events.append(event))
            self.assertEqual(result["report"], "最终报告")
            self.assertTrue(any(m.get("role") == "tool" and "1: core" in m["content"] for m in seen[1]))
            self.assertEqual(result["evidence"][0]["path"], "main.py")
            resumed = research({"base_url": "https://example.com/v1", "model": "test"}, {}, "", "", "追问", threading.Event(), lambda *args: None, result["context"])
            self.assertEqual(resumed["context"]["sources"]["repo"]["commit"], "abc")
            self.assertTrue(any(m.get("content") == "追问" for m in resumed["context"]["messages"]))


if __name__ == "__main__":
    unittest.main()
