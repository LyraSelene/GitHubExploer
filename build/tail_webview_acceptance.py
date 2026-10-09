"""Real WebView2 baseline/neutral/motion measurements, isolated settings."""
import sys,time,json,threading,base64,shutil,traceback,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop,webview
from core import Store
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build'/('tail-webview-'+time.strftime('%Y%m%d-%H%M%S'));OUT.mkdir()
baseline=OUT/'baseline-assets';shutil.copytree(ROOT/'static',baseline/'static')
for name in ['scene.js','actions.js','motion.js']:(baseline/'static'/name).write_bytes((ROOT/'build/tail-action'/('before-'+name)).read_bytes())
# Baseline UI does not contain tail options/trigger.
s=(baseline/'static/index.html').read_text('utf8');s=s.replace('<button data-character-action="tail">轻摆尾巴</button>','');(baseline/'static/index.html').write_text(s,'utf8')
original_assets=desktop.assets;desktop.assets=lambda:baseline
store=Store(OUT/'data');store.set('portrait_scene_v1',True);store.set('wallpaper_motion',{'entry_enabled':False,'auto_actions':False,'paused':False,'mode':'living','intensity':70})
service=desktop.Service(store);server=desktop.make_server(service,'tail-qa');threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/tail-qa/'
window=webview.create_window('Tail action · actual WebView2 / isolated data',url,width=1440,height=900)
results={}
def visible(hidden):
 threading.Thread(target=lambda:window.evaluate_js('window.WallpaperMotion?.setWindowHidden('+str(hidden).lower()+')'),daemon=True).start()
window.events.minimized+=lambda:visible(True)
window.events.restored+=lambda:visible(False)
def js(s):return window.evaluate_js(s)
def wait(s):
 for _ in range(120):
  if js(s):return
  time.sleep(.15)
 raise AssertionError(s)
def stats(values):
 ordered=sorted(values)
 return {'n':len(values),'median_ms':statistics.median(values),'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))], 'over33_percent':100*sum(v>33 for v in values)/len(values),'over50_percent':100*sum(v>50 for v in values)/len(values)}
def instrument():
 js("""window.qaPerf={frames:[],draw:[],last:null,enabled:false};const originalDraw=wallpaperScene.draw;wallpaperScene.draw=function(...args){if(!qaPerf.enabled)return originalDraw(...args);const begin=performance.now();const out=originalDraw(...args),end=performance.now();if(qaPerf.last!==null)qaPerf.frames.push(begin-qaPerf.last);qaPerf.last=begin;qaPerf.draw.push(end-begin);return out;};""")
def measure(name,tail=False):
 js("qaPerf={frames:[],draw:[],last:null,enabled:true};"+("wallpaperScene.trigger('tail');" if tail else ''))
 time.sleep(8)
 data=js('qaPerf.enabled=false;({frames:qaPerf.frames,draw:qaPerf.draw})');results[name]={'frame_intervals':stats(data['frames']),'draw_submission':stats(data['draw'])};(OUT/(name+'-raw.json')).write_text(json.dumps(data),'utf8')
def screenshot(name):
 result=json.loads(cdp('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False}))
 (OUT/name).write_bytes(base64.b64decode(result['data']))
def cdp(method,payload):
 from System import Action
 control=window.native.browser.webview;box={};event=threading.Event()
 def dispatch():
  box['task']=control.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(payload));event.set()
 control.Invoke(Action(dispatch));event.wait(5)
 for _ in range(100):
  if box['task'].IsCompleted:return str(box['task'].Result)
  time.sleep(.05)
 raise RuntimeError('DevTools timeout')
def run():
 try:
  time.sleep(2);wait("document.documentElement.dataset.motionReady==='true'&&document.documentElement.dataset.sceneReady==='true'")
  results['environment']=js('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,userAgent:navigator.userAgent})')
  instrument();measure('before')
  desktop.assets=original_assets;window.load_url(url+'?after=1');time.sleep(2)
  wait("document.documentElement.dataset.motionReady==='true'&&document.documentElement.dataset.sceneReady==='true'")
  instrument();measure('after-neutral');measure('after-tail',True)
  js("window.qaErrors=[];addEventListener('error',e=>qaErrors.push(e.message));")
  # Lifecycle checks use production handlers and clock, outside performance sample.
  js("document.documentElement.dataset.sceneMetrics='true';document.querySelector('[data-character-action=tail]').click()")
  time.sleep(1.3);a=js('wallpaperScene.tailState()');time.sleep(.25);b=js('wallpaperScene.tailState()')
  screenshot('tail-action-ui.png');results['contact_moves']=a['contact']!=b['contact'];results['fin_lags']=abs(a['body']-a['fin'])>.01
  js("document.querySelector('#motion-pause').click()");wait('WallpaperMotion.state().paused');time.sleep(.5);a=js('({tail:wallpaperScene.tailState(),motion:WallpaperMotion.state()})');time.sleep(.7);b=js('({tail:wallpaperScene.tailState(),motion:WallpaperMotion.state()})');results['pause_states']=[a,b];results['pause_freezes']=a==b
  js("document.querySelector('#motion-pause').click();document.querySelector('[data-character-action=tail]').click();document.querySelector('[data-character-action=wave]').click()")
  time.sleep(.3);results['switch_finite']=js('Number.isFinite(wallpaperScene.tailState().body)')
  window.minimize();time.sleep(.7);a=js('wallpaperScene.tailState()');time.sleep(.6);b=js('wallpaperScene.tailState()');results['hidden_freezes']=a==b;window.restore();time.sleep(1)
  js("document.querySelector('#motion-replay').click()");time.sleep(.3);js("document.querySelector('[data-character-action=tail]').click()");results['entry_suppressed']=js("wallpaperScene.isEntryActive()")
  js("document.querySelector('#skip-arrival').click();document.querySelector('#motion-pause').click();wallpaperScene.setAutomatic(false);")
  time.sleep(1.5)
  cdp('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]});time.sleep(.4)
  a=js('wallpaperScene.tailState()');js("document.querySelector('[data-character-action=tail]').click()");time.sleep(.5);b=js('wallpaperScene.tailState()');results['reduced_suppressed']=a==b
  cdp('Emulation.setEmulatedMedia',{'features':[]});time.sleep(.4)
  # Complete controlled timeline rendered by the actual WebGL shader, 12.5 fps preview.
  samples=js("""(()=>{const frames=[];for(let t=90;t<=100;t+=.04)wallpaperScene.draw(t,1,'living');wallpaperScene.configureTail(100,5.2);wallpaperScene.trigger('tail');for(let i=0;i<=100;i++){wallpaperScene.draw(100+i*.08,1,'living');frames.push({time:i*.08,state:wallpaperScene.tailState(),image:document.querySelector('#living-wallpaper').toDataURL('image/jpeg',.82)});}return frames;})()""")
  from PIL import Image,ImageDraw
  frames=[]
  for i,s in enumerate(samples):
   p=OUT/f'frame-{i:03}.jpg';p.write_bytes(base64.b64decode(s.pop('image').split(',')[1]));im=Image.open(p);frames.append(im.resize((960,600)))
  frames[0].save(OUT/'tail-full-preview.gif',save_all=True,append_images=frames[1:],duration=80,loop=0)
  (OUT/'poses.json').write_text(json.dumps(samples,indent=2),'utf8')
  # Actual UI real-time screen recording is separate from measurements.
  window.restore();time.sleep(.5);window.resize(1440,900);time.sleep(.5)
  js("document.querySelector('#motion-open').click();document.querySelector('#tail-amplitude').value=100;document.querySelector('#tail-amplitude').dispatchEvent(new Event('input'));document.querySelector('#tail-duration').value=5.2;document.querySelector('#tail-duration').dispatchEvent(new Event('input'));")
  results['settings_diagnostic']=js("({errors:qaErrors,handler:String(document.querySelector('#motion-open').onclick),className:document.querySelector('#motion-modal').className})")
  wait("document.querySelector('#motion-modal').classList.contains('open')");time.sleep(.3);screenshot('tail-settings.png')
  js("closeModal('motion-modal');wallpaperScene.draw(WallpaperMotion.state().clock,.7,'living');document.querySelector('[data-character-action=tail]').click();")
  live=[];live_states=[];live_times=[]
  for i in range(65):
   start=time.monotonic();live_times.append(start);live_states.append(js('wallpaperScene.tailState().body'));name=f'ui-frame-{i:03}.png';screenshot(name);live.append(Image.open(OUT/name).convert('RGB').resize((960,600)));time.sleep(max(0,.12-(time.monotonic()-start)))
  live[0].save(OUT/'tail-software-preview.gif',save_all=True,append_images=live[1:],duration=[max(30,round((live_times[min(i+1,len(live_times)-1)]-t)*1000)) for i,t in enumerate(live_times)],loop=0)
  results['realtime_preview_moves']=max(live_states)-min(live_states)>.2
  results['settings_persisted']=service.store.get('wallpaper_motion')['tail_amplitude']==100
  results['settles']=abs(samples[-1]['state']['body'])<.005 and abs(samples[-1]['state']['fin'])<.008
  results['waves_continue']=any(samples[65]['state']['waves'][i+3]>0 for i in range(0,24,4))
  results['passed']=all(results[k] for k in ['contact_moves','fin_lags','pause_freezes','hidden_freezes','switch_finite','entry_suppressed','settles','waves_continue','realtime_preview_moves','reduced_suppressed'])
 except Exception:results['error']=traceback.format_exc();results['passed']=False
 finally:
  (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8');print(str(OUT),flush=True);print(json.dumps(results,ensure_ascii=False),flush=True);window.destroy()
webview.start(run,gui='edgechromium');service.close();server.shutdown();server.server_close()
sys.exit(0 if results.get('passed') else 1)
