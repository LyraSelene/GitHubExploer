import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from core import Store, UserError
from desktop import Service, make_server


class DesktopTests(unittest.TestCase):
    def test_music_setting_defaults_off_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Store(Path(directory)))
            self.assertEqual(service.bootstrap()['music'], {'enabled': False})
            service.dispatch('music', {'enabled': True})
            restored = Service(Store(Path(directory)))
            self.assertTrue(restored.bootstrap()['music']['enabled'])
            with self.assertRaises(UserError): restored.dispatch('music', {'enabled': 'false'})
            restored.dispatch('music', {'enabled': False})
            self.assertFalse(Service(Store(Path(directory))).bootstrap()['music']['enabled'])

    def test_saved_key_is_not_in_bootstrap_or_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_settings({'base_url': 'https://example.com/v1', 'model': 'fixture', 'api_key': 'sensitive-key'})
            service = Service(store)
            data = service.bootstrap()
            self.assertTrue(data['settings']['has_key'])
            self.assertNotIn('sensitive-key', json.dumps(data))
            service.dispatch('settings', {'base_url': 'https://example.com/v1', 'model': 'fixture-2', 'api_key': '', 'keep_key': True})
            self.assertEqual(store.settings()['api_key'], 'sensitive-key')

    def test_job_saves_report_progress_and_followup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.save_settings({'base_url': 'https://example.com/v1', 'model': 'fixture', 'api_key': ''})
            service = Service(store)
            task = {'title': '练习', 'reading': 'main.py（夹具）', 'question': '为什么排队？', 'exercise': '写队列', 'acceptance': '检查取消'}
            finished = threading.Event()
            context = {'messages': [], 'sources': {'repo': {'owner': 'o', 'name': 'r', 'commit': 'fixed'}}}
            def fake_research(*args, **kwargs):
                args[6]('status', '正在读取')
                return {'report': '# 报告\n正文', 'context': context, 'evidence': [], 'learning_tasks': [task], 'learning_warning': ''}
            original_save = service.public_report
            def public_report(report_id):
                result = original_save(report_id)
                finished.set()
                return result
            with patch('desktop.research', fake_research), patch.object(service, 'public_report', public_report), patch.object(service.learning_flow,'start',return_value={'status':'running'}) as suggestions:
                job = service.start({'url': 'https://github.com/o/r', 'learning': True, 'track': 'AI Infra · 推理服务', 'goal': '队列'})
                self.assertTrue(finished.wait(3))
                with service.lock: snapshot = {k:v for k,v in service.job.items() if k != 'cancel'}
                self.assertEqual(snapshot['state'], 'done')
                self.assertEqual(snapshot['id'], job['job_id'])
                report_id = snapshot['result']['id']
                self.assertEqual(store.learning_projects(), [])
                suggestions.assert_called_once_with(report_id,'队列','AI Infra · 推理服务')
                finished.clear()
                service.start({'report_id': report_id, 'question': '解释取消'})
                self.assertTrue(finished.wait(3))
                self.assertIn('解释取消', store.report(report_id)['report'])
                self.assertEqual(len(store.reports()), 1)
                restored = Service(Store(Path(directory)))
                self.assertEqual(restored.bootstrap()['reports'][0]['id'], report_id)
                self.assertIn('解释取消', restored.dispatch('report', {'id': report_id})['report'])
                self.assertEqual(len(restored.store.learning_projects()), 0)

    def test_server_scopes_static_assets_and_rejects_foreign_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Store(Path(directory)))
            server = make_server(service, 'fixture-token')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base + '/fixture-token/') as response:
                    self.assertIn(b'wallpaper', response.read())
                    self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
                    self.assertIn('frame-src https://music.163.com', response.headers['Content-Security-Policy'])
                    self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                for asset in ['github-import.js', 'learning-flow.js', 'review.js', 'review.css', 'tasks.js', 'tasks.css', 'notes.js', 'notes.css', 'materials.js', 'materials.css', 'motion.css', 'motion.js', 'chat.css', 'chat.js', 'entrance.mp4', 'scene.js', 'entrance.js', 'entrance-paths.js', 'wallpaper-outline-glow.png', 'wallpaper-face.png', 'wallpaper-outline.png', 'actions.js', 'wallpaper-blink.webp', 'wallpaper-eyelids.png', 'music.js', 'music.css', 'forearm-layer.png', 'wallpaper-rig-base.png', 'wallpaper-smile.png', 'trending.js']:
                    with urllib.request.urlopen(base + '/fixture-token/' + asset) as response:
                        self.assertGreater(len(response.read()), 100)
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(base + '/wrong-token/')
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(base + '/fixture-token/../core.py')
                body = json.dumps({'action': 'bootstrap'}).encode()
                req = urllib.request.Request(base + '/fixture-token/api', data=body, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req) as response:
                    self.assertIn('tracks', json.load(response))
                req = urllib.request.Request(base + '/fixture-token/api', data=body, headers={'Origin': 'https://foreign.example'})
                with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(req)
                self.assertEqual(caught.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == '__main__': unittest.main()
