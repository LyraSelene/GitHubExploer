"""Local HTTP fixtures only: never calls a paid model endpoint."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from core import Sources, Transport, UserError, research, search_github


class IntegrationTests(unittest.TestCase):
    def test_search_over_http_returns_public_repo_without_authorization(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                observed.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"total_count": 1, "items": [{"full_name": "fixture/repo", "description": "learning fixture", "language": "Python"}]}).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        transport = Transport(threading.Event())
        original_json = transport.json
        try:
            def local_json(url):
                return original_json(f"http://127.0.0.1:{server.server_port}/" + url.split("?", 1)[-1])
            with patch.object(transport, "json", local_json):
                result = search_github("agent", "Python", transport)
            self.assertEqual(result["items"][0]["name"], "fixture/repo")
            self.assertIsNone(observed[0][1])
            self.assertIn("per_page=12", observed[0][0])
        finally:
            transport.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_http_stream_to_repo_tool_to_report(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, self.headers.get("Authorization"), body))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.end_headers()
                if len(seen) == 1:
                    chunks = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "read1", "type": "function", "function": {
                        "name": "read_repository_file", "arguments": '{"path":"main.py","start_line":1,"end_line":2}'}}]}, "finish_reason": "tool_calls"}]}]
                else:
                    chunks = [{"choices": [{"delta": {"content": "选择性借鉴。"}, "finish_reason": None}]},
                              {"choices": [{"delta": {"content": "已读 main.py 第 1–2 行，未运行实验。"}, "finish_reason": "stop"}]}]
                for chunk in chunks:
                    self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def prepare(sources, url, material):
                sources.repo = {"owner": "fixture", "name": "repo", "commit": "fixture123"}
                sources.files = ["main.py"]
                return "仅用于测试的 README"
            events = []
            with patch.object(Sources, "prepare", prepare), patch.object(Transport, "read", return_value=b"def main():\n    return 42\n"):
                result = research({"base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "fixture-model", "api_key": "test-key"},
                                  {"可用硬件": "CPU"}, "https://github.com/fixture/repo", "", "", threading.Event(), lambda *args: events.append(args))
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[0][0], "/v1/chat/completions")
            self.assertEqual(seen[0][1], "Bearer test-key")
            self.assertEqual(seen[0][2]["model"], "fixture-model")
            self.assertTrue(seen[0][2]["tools"])
            self.assertTrue(any(m["role"] == "tool" and "def main()" in m["content"] for m in seen[1][2]["messages"]))
            self.assertIn("未运行实验", result["report"])
            self.assertEqual(result["evidence"][0]["end"], 2)
            self.assertNotIn("test-key", json.dumps(result, ensure_ascii=False))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_http_errors_do_not_echo_credentials(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"secret-test-key echoed by provider"}')
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(UserError) as caught:
                Transport(threading.Event()).open(f"http://127.0.0.1:{server.server_port}", {}, {"Authorization": "Bearer secret-test-key"}, True)
            self.assertIn("401", str(caught.exception))
            self.assertNotIn("secret-test-key", str(caught.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
