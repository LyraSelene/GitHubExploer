"""Isolated real WebView2 flow; deterministic source evidence, no model calls."""
import base64,json,sys,threading,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop,webview
from core import Store
from test_workspace import seed,SHA
OUT=Path(__file__).resolve().parent/('workspace-ui-'+time.strftime('%Y%m%d-%H%M%S'));OUT.mkdir()
service=desktop.Service(Store(OUT/'data'));report,project,units=seed(service)
service.store.set('wallpaper_motion',{'entry_enabled':False,'paused':True,'mode':'still'})
service.workspace.position({'project_id':project,'index':1,'scroll':120})
material=OUT/'cache.py';material.write_text('def lookup(key):\n    return cache[key]\n',encoding='utf-8')
service.library.import_paths([material])
document=service.library.list()['documents'][0]['id']
with service.store.connect() as db:
    db.execute('UPDATE documents SET source_json=? WHERE id=?',(json.dumps({'repository_url':'https://github.com/org/repo','commit_sha':SHA,'path':'cache.py'}),document))
service.notes.create('缓存练习笔记','自己的机制理解',links=[{'type':'report','id':str(report),'label':'缓存研究'}])

server=desktop.make_server(service,'workspace-qa');threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/workspace-qa/'
window=webview.create_window('Infra workspace acceptance · isolated storage',url,width=1400,height=900)
checks={}
def js(code):
    print("JS "+code[:100],flush=True)
    return window.evaluate_js(code)
def wait(condition):
    for _ in range(150):
        if js(condition):return
        time.sleep(.15)
    raise AssertionError(condition)
def screenshot(name):
    from PIL import ImageGrab
    from System import Action
    from System.Drawing import Point
    control=window.native.browser.webview;box={};event=threading.Event()
    def bounds():
        point=control.PointToScreen(Point(0,0));box['rect']=(point.X,point.Y,point.X+control.Width,point.Y+control.Height);event.set()
    control.Invoke(Action(bounds))
    if not event.wait(5):raise RuntimeError('Screenshot bounds unavailable')
    ImageGrab.grab(bbox=box['rect'],all_screens=True).save(OUT/name)
def run():
    try:
        print("acceptance starting",flush=True)
        time.sleep(2)
        wait("document.documentElement.dataset.workspaceReady==='true'&&document.querySelector('#workspace-home button')!==null")
        checks['home_initialized']=js("document.querySelector('#home-page').classList.contains('active')")
        screenshot('home.png')
        js("[...document.querySelectorAll('#workspace-home button')].find(b=>b.textContent==='继续学习 →').click()")
        wait("document.querySelectorAll('.learning-unit-nav button').length===2&&document.querySelectorAll('#progress-content .task')[1].hidden===false")
        checks['resume_correct_unit']=True
        checks['resume_scroll']=abs(js("document.querySelector('main').scrollTop")-120)<3
        js("document.querySelectorAll('#progress-content .task')[1].querySelector('.learning-evidence').open=true")
        checks['fixed_source']=SHA in js("document.querySelectorAll('#progress-content .task')[1].innerText")
        js("for(const [key,value] of Object.entries({response:'return cache[key]',notes:'已完成隔离练习',artifact:'results/cache.md',blockers:'等待真实项目验证'})){const e=document.querySelectorAll('#progress-content .task')[1].querySelector('[data-record='+key+']');e.value=value;e.dispatchEvent(new Event('input'));}")
        time.sleep(1.6)
        js("[...document.querySelectorAll('#progress-content .task')[1].querySelectorAll('button')].find(b=>b.textContent==='核对理解与来源').click()")
        wait("document.querySelectorAll('#progress-content .task')[1].querySelector('.learning-feedback').textContent.includes('有原文支持')")
        checks['feedback_grounded']=True;screenshot('learning-reader.png')
        js("[...document.querySelectorAll('#progress-content .task')[1].querySelectorAll('button')].find(b=>b.textContent==='完成学习（用户自评）').click()")
        wait("document.querySelectorAll('#progress-content .task')[1].innerText.includes('关联复习已创建')")
        checks['completion_ui_progress']=js("document.querySelector('.progress-head span').textContent.includes('1/2')&&document.querySelectorAll('.learning-unit-nav button')[1].textContent.includes('已完成')")
        js("[...document.querySelectorAll('#progress-content .task')[1].querySelectorAll('button')].find(b=>b.textContent==='完成学习（用户自评）').click()")
        time.sleep(.6);checks['completion_idempotent']=service.review.overview()['total']==1
        js("[...document.querySelectorAll('#progress-content .task')[1].querySelectorAll('button')].find(b=>b.textContent==='打开关联复习').click()")
        wait("document.querySelector('#review-detail').innerText.includes('查看答案与来源')")
        checks['review_navigation']=True;screenshot('review.png')
        ident=service.workspace.projects()[0]['id'];js('void window.WorkspaceUI.openProject('+str(ident)+')')
        wait("document.querySelector('.workspace-version')!==null");checks['associations_commit']=SHA in js("document.querySelector('#workspace-project').innerText")
        checks['associations_all_types']=all(t in js("document.querySelector('#workspace-project').innerText") for t in ['资料','研究报告','学习计划','笔记','复习'])
        screenshot('project-associations.png')
        window.resize(1024,768);time.sleep(.7);checks['narrow_no_overflow']=js('document.documentElement.scrollWidth<=innerWidth');screenshot('project-narrow.png')
        # Reopen storage and reload the WebView with a fresh Service.
        service.close();reopened=desktop.Service(Store(OUT/'data'));server.service=reopened
        # make_server handler closes over its service; use a fresh server instead.
        second=desktop.make_server(reopened,'workspace-restart');threading.Thread(target=second.serve_forever,daemon=True).start()
        window.load_url(f'http://127.0.0.1:{second.server_port}/workspace-restart/')
        wait("document.documentElement.dataset.workspaceReady==='true'&&document.querySelector('#workspace-home button')!==null")
        js("[...document.querySelectorAll('#workspace-home button')].find(b=>b.textContent==='继续学习 →').click()")
        wait("document.querySelectorAll('#progress-content .task').length===2&&document.querySelectorAll('#progress-content .task')[1].hidden===false")
        checks['restart_unit']=True
        checks['restart_notes']=js("document.querySelectorAll('#progress-content .task')[1].querySelector('[data-record=notes]').value")=='已完成隔离练习'
        checks['restart_review_unique']=reopened.review.overview()['total']==1
        checks['restart_sources']=SHA in js("document.querySelector('#progress-content').innerText")
        window.resize(1400,900);time.sleep(.5)
        js("document.querySelectorAll('#progress-content .task')[1].querySelector('.learning-evidence').open=true;document.querySelectorAll('#progress-content .task')[1].querySelector('[data-record=response]').scrollIntoView({block:'center'});")
        time.sleep(.5);screenshot('restart-learning.png');reopened.close();second.shutdown();second.server_close()
        checks['passed']=all(checks.values())
    except Exception:checks['error']=traceback.format_exc();checks['passed']=False
    finally:
        (OUT/'results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8');print(str(OUT),flush=True);print(json.dumps(checks,ensure_ascii=False),flush=True);window.destroy()
webview.start(run,gui='edgechromium');service.close();server.shutdown();server.server_close()
sys.exit(0 if checks.get('passed') else 1)
