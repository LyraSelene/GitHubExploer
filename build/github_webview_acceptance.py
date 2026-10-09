"""Real WebView2/public Python repository acceptance, using isolated storage.

No model requests or repository code execution. Results are written for review.
"""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
from core import Store
from desktop import Service, make_server

root = Path(__file__).resolve().parent / ('github-webview-' + time.strftime('%Y%m%d-%H%M%S'))
root.mkdir()
store = Store(root / 'data')
store.set('wallpaper_motion', {'schema': 4, 'entry_enabled': False, 'mode': 'still', 'paused': True})
service = Service(store)
server = make_server(service, 'github-acceptance')
threading.Thread(target=server.serve_forever, daemon=True).start()
window = webview.create_window('GitHub import acceptance · isolated data',
    f'http://127.0.0.1:{server.server_port}/github-acceptance/', width=1400, height=900)
results = {}

def wait_js(expression, timeout=30):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if window.evaluate_js(expression): return
        time.sleep(.25)
    raise AssertionError('Timeout: ' + expression)

def run():
    try:
        wait_js("document.documentElement.dataset.ready === 'true' && document.documentElement.dataset.githubImportReady === 'true' && document.documentElement.dataset.learningFlowReady === 'true'")
        results['frontend_initialized'] = True
        window.evaluate_js("document.querySelector('[data-page=materials]').click(); document.getElementById('github-material-import').click(); document.getElementById('github-import-url').value='https://github.com/pallets/itsdangerous/'; document.getElementById('github-scan').click()")
        until = time.monotonic() + 180
        while time.monotonic() < until:
            runs = service.github_import.list()['runs']
            if runs and runs[0]['status'] != 'running': break
            time.sleep(.5)
        assert runs and runs[0]['status'] == 'done', runs
        version = runs[0]['version_id']
        preview = service.github_import.preview(version)
        results['repository'] = preview['version']
        results['scanned_files'] = len(preview['files'])
        assert not service.library.list()['documents'], 'Scan downloaded content'
        wait_js("document.querySelectorAll('#github-import-files input').length > 0")
        docs = [f['path'] for f in preview['files'] if f['path'].startswith('docs/') and f['category'] != 'excluded']
        code = [f['path'] for f in preview['files'] if f['path'].startswith('src/') and f['path'].endswith('.py')][:3]
        assert docs and len(code) == 3, 'Expected docs and three source files'
        selected = docs + code
        window.evaluate_js("document.querySelectorAll('#github-import-files input').forEach(el=>el.checked=" + json.dumps(selected) + ".includes(el.value));document.getElementById('github-import-start').click()")
        until = time.monotonic() + 180
        while time.monotonic() < until:
            runs = service.github_import.list()['runs']
            if runs[0]['kind'] == 'import' and runs[0]['status'] != 'running' and not service.github_import.workers: break
            time.sleep(.5)
        assert runs[0]['status'] == 'done', runs[0]
        results['selected_paths'] = selected
        results['import_run'] = runs[0]
        documents = service.library.list()['documents']
        assert len(documents) == len(selected), documents
        window.evaluate_js("document.getElementById('materials-query').value='serializer';document.getElementById('materials-search').click()")
        wait_js("document.getElementById('materials-status').textContent.startsWith('找到 ') && document.querySelectorAll('#materials-results .material-item').length > 0")
        hits = service.library.search('serializer')
        assert hits and all(h['start_line'] and '#L' in h['source_url'] and preview['version']['commit_sha'] in h['source_url'] for h in hits)
        window.evaluate_js("document.querySelector('#materials-results .material-item').click()")
        wait_js("document.querySelector('#materials-preview .material-hit') !== null", 45)
        results['search_hits'] = len(hits)
        results['preview_text'] = window.evaluate_js("document.getElementById('materials-preview').innerText").strip()[:2500]
        assert '固定 GitHub 来源' in results['preview_text']
        results['permissions_default_off'] = window.evaluate_js("!document.getElementById('materials-enabled').checked && !document.getElementById('materials-learning-enabled').checked")
        assert results['permissions_default_off']
        restored = Service(Store(root / 'data'))
        try:
            assert len(restored.library.list()['documents']) == len(selected)
            assert restored.github_import.preview(version)['version']['import_status'] == 'complete'
            results['reopened_storage'] = True
        finally: restored.close()
        results['passed'] = True
    except Exception as exc:
        results['error'] = repr(exc)
        try:
            results['ui_diagnostics'] = window.evaluate_js("({toast:document.getElementById('toast').innerText,status:document.getElementById('materials-status').innerText,preview:document.getElementById('materials-preview').innerText})")
        except Exception: pass
        results['passed'] = False
    finally:
        (root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(str(root / 'results.json'), flush=True)
        print(json.dumps({'passed': results.get('passed'), 'error': results.get('error')}, ensure_ascii=False), flush=True)
        window.destroy()

webview.start(run, gui='edgechromium')
service.close()
server.shutdown()
server.server_close()
sys.exit(0 if results.get('passed') else 1)
