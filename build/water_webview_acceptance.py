"""Real production-clock WebView2 previews and isolated persistence acceptance."""
import sys,time,json,threading,base64,shutil,traceback,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop,webview
from core import Store
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build'/('water-webview-'+time.strftime('%Y%m%d-%H%M%S'));OUT.mkdir()
baseline=OUT/'baseline-assets';shutil.copytree(ROOT/'static',baseline/'static')
for name in ['scene.js','actions.js','motion.js','index.html']:(baseline/'static'/name).write_bytes((ROOT/'build/water-actions'/('before-'+name)).read_bytes())
original_assets=desktop.assets;desktop.assets=lambda:baseline
store=Store(OUT/'data');store.set('portrait_scene_v1',True);store.set('wallpaper_motion',{'entry_enabled':False,'auto_actions':False,'paused':False,'mode':'living','intensity':70})
service=desktop.Service(store);server=desktop.make_server(service,'water-qa');threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/water-qa/'
window=webview.create_window('Water actions QA · isolated database',url,width=1440,height=900)
results={}
def visible(hidden):threading.Thread(target=lambda:window.evaluate_js('window.WallpaperMotion?.setWindowHidden('+str(hidden).lower()+')'),daemon=True).start()
window.events.minimized+=lambda:visible(True)
window.events.restored+=lambda:visible(False)
def js(s):return window.evaluate_js(s)
def wait(s):
 for _ in range(100):
  if js(s):return
  time.sleep(.12)
 raise AssertionError(s)
def stats(values):
 ordered=sorted(values)
 return {'n':len(values),'median_ms':statistics.median(values),'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))],'over33_percent':100*sum(v>33 for v in values)/len(values),'over50_percent':100*sum(v>50 for v in values)/len(values)}
def measure(name,kind=None,duration=8):
 js("wallpaperScene.measure(true);"+(f"wallpaperScene.trigger('{kind}');" if kind else ''));time.sleep(duration)
 data=js('wallpaperScene.measured()');js('wallpaperScene.measure(false)');results[name]={'frames':stats(data['frames']),'draw_submission':stats(data['draw'])};(OUT/(name+'-raw.json')).write_text(json.dumps(data),'utf8')
def cdp(method,payload):
 from System import Action
 control=window.native.browser.webview;box={};event=threading.Event()
 def dispatch():box['task']=control.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(payload));event.set()
 control.Invoke(Action(dispatch));assert event.wait(5)
 for _ in range(100):
  if box['task'].IsCompleted:return json.loads(str(box['task'].Result))
  time.sleep(.03)
 raise RuntimeError('DevTools timeout')
def screenshot(name):
 size=js('({width:innerWidth,height:innerHeight})');data=cdp('Page.captureScreenshot',{'format':'jpeg','quality':80,'captureBeyondViewport':False,'clip':{'x':0,'y':0,'width':size['width'],'height':size['height'],'scale':.7}});p=OUT/name;p.write_bytes(base64.b64decode(data['data']));return p
def preview(kind,duration):
 # Let previous action fully relax before one real UI click, no synthetic clock.
 time.sleep(3);js(f"document.querySelector('.character-actions [data-character-action={kind}]').click()")
 images=[];poses=[];times=[];start=time.monotonic()
 while time.monotonic()-start<duration:
  tick=time.monotonic();times.append(tick-start);poses.append(js('wallpaperScene.waterState()'));p=screenshot(f'{kind}-{len(images):03}.png');images.append(Image.open(p).convert('RGB').resize((960,581)));time.sleep(max(0,.18-(time.monotonic()-tick)))
 durations=[max(30,round((times[i+1]-times[i])*1000)) for i in range(len(times)-1)]+[180]
 images[0].save(OUT/f'{kind}-software-preview.gif',save_all=True,append_images=images[1:],duration=durations,loop=0)
 (OUT/f'{kind}-poses.json').write_text(json.dumps({'times':times,'poses':poses}),'utf8')
 key='wave' if kind=='brush' else 'wink' if kind=='respond' else 'tail'
 peak=max(range(len(poses)),key=lambda i:abs(poses[i]['fin']) if kind=='fin' else abs(poses[i]['pose'][key]));shutil.copyfile(OUT/f'{kind}-{peak:03}.png',OUT/f'{kind}-peak.png')
 results[kind+'_moves']=max(abs(x['fin']) if kind=='fin' else abs(x['pose'][key]) for x in poses)>(.10 if kind!='respond' else .8)
 return poses
def memory():
 try:
  import psutil
  own=psutil.Process();return {'rss_mb':own.memory_info().rss/1024**2,'children_rss_mb':sum(p.memory_info().rss for p in own.children(recursive=True) if p.is_running())/1024**2}
 except Exception:return {'unavailable':True}
def run():
 try:
  time.sleep(2);wait("document.documentElement.dataset.motionReady==='true'&&document.documentElement.dataset.sceneReady==='true'")
  results['environment']=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,userAgent:navigator.userAgent})');results['memory_before']=memory();measure('before-tail', 'tail')
  desktop.assets=original_assets;window.load_url(url+'?after=1');time.sleep(2);wait("document.documentElement.dataset.motionReady==='true'&&document.documentElement.dataset.sceneReady==='true'")
  js("window.qaErrors=[];addEventListener('error',e=>qaErrors.push(e.message));document.body.style.pointerEvents='none';document.querySelector('#action-auto').checked=false;document.querySelector('#action-auto').dispatchEvent(new Event('change'));")
  measure('after-neutral');measure('after-combination','tailBrush',14);results['memory_after']=memory()
  # Individual previews precede combination and response, all production time.
  brush=preview('brush',9);fin=preview('fin',8)
  results['hand_contact_moves']=len({tuple(x['hand']) for x in brush})>2;results['fin_root_stable']=all(abs(x['pose']['tail'])<.01 for x in fin)
  response=preview('respond',7);combo=preview('tailBrush',16)
  results['combo_no_wink']=all(x['pose']['wink']<.001 for x in combo);results['combo_separated']=all(not(abs(x['pose']['wave'])>.08 and abs(x['pose']['tail'])>.08) for x in combo)
  js("document.querySelector('.character-actions [data-character-action=respond]').click()");time.sleep(.4);before=js('wallpaperScene.waterState()');js("for(let i=0;i<15;i++)document.querySelector('.character-actions [data-character-action=respond]').click()");after=js('wallpaperScene.waterState()');results['response_coalesced']=before['nextAuto']==after['nextAuto'] and after['active']==['respond']
  js("document.querySelector('#motion-pause').click()");wait('WallpaperMotion.state().paused');time.sleep(.3);a=js('({water:wallpaperScene.waterState(),motion:WallpaperMotion.state(),waves:wallpaperScene.tailState().waves})');time.sleep(.8);b=js('({water:wallpaperScene.waterState(),motion:WallpaperMotion.state(),waves:wallpaperScene.tailState().waves})');results['pause_freezes']=a==b
  js("document.querySelector('#motion-pause').click()");window.minimize();time.sleep(.8);a=js('wallpaperScene.waterState()');time.sleep(.6);results['hidden_freezes']=a==js('wallpaperScene.waterState()');window.restore();time.sleep(.7)
  window.resize(1100,760);time.sleep(.7);results['resize_ready']=js("document.documentElement.dataset.sceneReady==='true'&&!document.querySelector('#living-wallpaper').hidden");screenshot('narrow-window.png');window.resize(1440,900);time.sleep(.7)
  js("document.querySelector('#motion-replay').click()");time.sleep(.4);js("document.querySelector('[data-character-action=tailBrush]').click()");results['entry_suppresses']=js('wallpaperScene.isEntryActive()&&wallpaperScene.waterState().active.length===0');js("document.querySelector('#skip-arrival').click()");time.sleep(2)
  cdp('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]});time.sleep(.5);a=js('wallpaperScene.waterState()');js("document.querySelector('[data-character-action=respond]').click()");time.sleep(.5);results['reduced_freezes']=a==js('wallpaperScene.waterState()');cdp('Emulation.setEmulatedMedia',{'features':[]});time.sleep(.5)
  js("document.querySelector('#motion-open').click();document.querySelector('#water-preset').value='lively';document.querySelector('#water-preset').dispatchEvent(new Event('change'));document.querySelector('#water-wait-min').value=8;document.querySelector('#water-wait-min').dispatchEvent(new Event('change'));document.querySelector('#water-wait-max').value=12;document.querySelector('#water-wait-max').dispatchEvent(new Event('change'));")
  wait("document.querySelector('#motion-modal').classList.contains('open')");screenshot('water-settings.png');time.sleep(.8)
  js("closeModal('motion-modal');document.querySelector('#action-auto').checked=true;document.querySelector('#action-auto').dispatchEvent(new Event('change'));")
  auto=[]
  for i in range(45):time.sleep(1);auto.append(js('wallpaperScene.waterState()'))
  results['auto_actual_started']=any(x['active'] for x in auto);js("document.querySelector('#action-auto').checked=false;document.querySelector('#action-auto').dispatchEvent(new Event('change'));");time.sleep(6);v=js('wallpaperScene.waterState()');results['auto_off_relaxes']=abs(v['pose']['wave'])<.002 and abs(v['pose']['tail'])<.002 and v['active']==[]
  time.sleep(.8);snapshot=service.store.get('wallpaper_motion');results['prefs_persisted']=snapshot['water_preset']=='lively' and snapshot['water_wait_min']==8 and snapshot['water_wait_max']==12
  window.load_url(url+'?restart=1');time.sleep(2);wait("document.documentElement.dataset.motionReady==='true'");results['reload_restores']=js("document.querySelector('#water-preset').value==='lively'&&document.querySelector('#water-wait-max').value==='12'&&!document.querySelector('#action-auto').checked")
  reopened=Store(OUT/'data');results['store_reopen']=reopened.get('wallpaper_motion')==snapshot
  results['page_errors']=js('window.qaErrors||[]');results['passed']=all(v for k,v in results.items() if isinstance(v,bool)) and not results['page_errors']
 except Exception:results['error']=traceback.format_exc();results['passed']=False
 finally:
  (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8');print(str(OUT),flush=True);print(json.dumps(results,ensure_ascii=False),flush=True);window.destroy()
webview.start(run,gui='edgechromium');service.close();server.shutdown();server.server_close();sys.exit(0 if results.get('passed') else 1)
