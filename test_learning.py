import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from core import LEARNING_TRACKS, Model, Store, UserError, extract_learning_tasks, research, search_github, validate_learning_tasks


TASK = {"title": "追踪请求", "reading": "main.py:handle（已读）", "question": "状态何时变化？",
        "exercise": "记录一次请求的状态转换", "acceptance": "交付状态图和一个失败输入"}


class LearningTests(unittest.TestCase):
    def test_infra_and_agent_modes_reach_model_independently(self):
        seen = []
        def complete(model, messages, tools, on_text):
            seen.append(list(messages))
            return {"role": "assistant", "content": "# 路线\n测试报告"}
        settings = {"base_url": "https://example.com/v1", "model": "fixture"}
        with patch.object(Model, "complete", complete):
            for track in LEARNING_TRACKS:
                research(settings, {"可用硬件": "无 GPU"}, "", "README", "学习目标", threading.Event(), lambda *args: None,
                         learning=True, learning_track=track, agent_focus=track.startswith("AI Agent"))
                prompt = seen[-1][1]['content']
                self.assertIn("本次学习方向：" + track, prompt)
                self.assertIn(LEARNING_TRACKS[track]['mechanisms'], prompt)
                if track.startswith("AI Infra"):
                    self.assertNotIn("补充专项分析：AI Agent 学习价值", prompt)
                else:
                    self.assertIn("补充专项分析：AI Agent 学习价值", prompt)

    def test_existing_learning_database_migrates_without_losing_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with sqlite3.connect(path / 'research.sqlite3') as db:
                db.execute('CREATE TABLE learning_projects(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL, goal TEXT NOT NULL, created TEXT NOT NULL, commit_sha TEXT NOT NULL, tasks TEXT NOT NULL)')
                db.execute('INSERT INTO learning_projects VALUES(1,1,?,?,?,?,?,?)',
                           ('old/repo', 'https://github.com/old/repo', '已有目标', '2026-10-05', 'oldcommit',
                            json.dumps([{**TASK, 'status': '进行中', 'notes': '已有实验记录'}], ensure_ascii=False)))
            db.close()
            store = Store(path)
            old = store.learning_projects()[0]
            self.assertEqual(old['track'], '未分类（旧计划）')
            self.assertEqual(old['tasks'][0]['notes'], '已有实验记录')
            track = 'AI Infra · 训练系统'
            store.save_learning(2, {'owner': 'new', 'name': 'repo', 'commit': 'newcommit'}, '恢复', [TASK], track)
            self.assertEqual(Store(path).learning_projects()[0]['track'], track)

    def test_search_query_uses_language_and_does_not_leak_provider_key(self):
        class Fake:
            url = ""
            def json(self, url):
                self.url = url
                return {"total_count": 1, "items": [{"full_name": "org/agent", "description": "tools", "language": "Python", "pushed_at": "2026-10-01", "topics": ["agent"]}]}
        fake = Fake()
        result = search_github("agent tool", "Python", fake)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.url).query)
        self.assertEqual(query['q'], ["agent tool archived:false language:Python"])
        self.assertNotIn("sort", query)
        self.assertEqual(result['items'][0]['url'], "https://github.com/org/agent")
        self.assertNotIn("stars", result['items'][0])
        with self.assertRaises(UserError):
            search_github("", "Python", fake)

    def test_plan_format_failures_keep_report_without_fake_tasks(self):
        good = "# 学习路线\n正文\n```learning_tasks\n" + json.dumps([TASK], ensure_ascii=False) + "\n```"
        report, tasks, warning = extract_learning_tasks(good)
        self.assertNotIn("learning_tasks", report)
        self.assertEqual(tasks[0]['status'], "未开始")
        self.assertFalse(warning)
        for text in ["# 只有报告", "报告\n```learning_tasks\nnot-json\n```", good + "\n" + good]:
            report, tasks, warning = extract_learning_tasks(text)
            self.assertTrue(report)
            self.assertFalse(tasks)
            self.assertTrue(warning)
        with self.assertRaises(UserError):
            validate_learning_tasks([{**TASK, "acceptance": ""}])

    def test_learning_tasks_survive_restart_and_reject_invalid_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            report_id = store.save_report("repo", "report", {}, [])
            project_id = store.save_learning(report_id, {"owner": "org", "name": "repo", "commit": "fixed"}, "缓存", [TASK])
            store.update_learning_task(project_id, 0, "已完成（自评）", "实验记录在 results.md")
            restored = Store(Path(directory)).learning_projects()[0]
            self.assertEqual(restored['report_id'], report_id)
            self.assertEqual(restored['commit'], "fixed")
            self.assertEqual(restored['tasks'][0]['notes'], "实验记录在 results.md")
            self.assertEqual(restored['tasks'][0]['status'], "已完成（自评）")
            for index, status in [(20, "未开始"), (0, "系统认证掌握"), (True, "未开始")]:
                with self.assertRaises(UserError):
                    store.update_learning_task(project_id, index, status, "")
            self.assertEqual(store.report(report_id)['report'], "report")

    def test_learning_mode_returns_tasks_and_keeps_regular_analysis_unchanged(self):
        seen = []
        output = "# 路线\n先看入口\n```learning_tasks\n" + json.dumps([TASK], ensure_ascii=False) + "\n```"
        def complete(model, messages, tools, on_text):
            seen.append(list(messages))
            return {"role": "assistant", "content": output}
        settings = {"base_url": "https://example.com/v1", "model": "fixture"}
        with patch.object(Model, "complete", complete):
            result = research(settings, {"可用硬件": "CPU"}, "", "README 内容", "学习缓存", threading.Event(), lambda *args: None, learning=True)
            self.assertEqual(result['learning_tasks'][0]['title'], TASK['title'])
            self.assertNotIn("learning_tasks", result['report'])
            self.assertIn("GitHub 仓库进行学习", seen[0][1]['content'])
            normal = research(settings, {}, "", "README 内容", "", threading.Event(), lambda *args: None)
            self.assertEqual(normal['report'], output)
            self.assertEqual(normal['learning_tasks'], [])


if __name__ == "__main__":
    unittest.main()
