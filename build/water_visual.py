"""Reuse WebView harness to record visible character on research page."""
from pathlib import Path
source=Path(__file__).with_name('water_webview_acceptance.py').read_text('utf8')
prefix=source.split('def run():')[0].replace("desktop.assets=lambda:baseline","desktop.assets=original_assets")
suffix='''
def run():
 try:
  time.sleep(2);wait("document.documentElement.dataset.motionReady==='true'&&document.documentElement.dataset.sceneReady==='true'")
  js("page('research');document.body.style.pointerEvents='none';document.querySelector('#action-auto').checked=false;document.querySelector('#action-auto').dispatchEvent(new Event('change'));")
  cdp('Performance.enable',{})
  results['memory_metrics_before']=cdp('Performance.getMetrics',{})
  preview('brush',9);preview('fin',8);preview('respond',7);preview('tailBrush',16)
  # Ambient local current and same source-coordinate mask after action relaxes.
  time.sleep(3);screenshot('idle-start.png');time.sleep(3);screenshot('idle-end.png')
  results['memory_metrics_after']=cdp('Performance.getMetrics',{})
  results['scene']=js("document.documentElement.dataset.sceneReady")
  results['passed']=results['scene']=='true' and all(results[k+'_moves'] for k in ['brush','fin','respond','tailBrush'])
 except Exception:results['error']=traceback.format_exc();results['passed']=False
 finally:
  (OUT/'visual-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8');print(str(OUT),flush=True);print(json.dumps(results),flush=True);window.destroy()
webview.start(run,gui='edgechromium');service.close();server.shutdown();server.server_close()
'''
exec(compile(prefix+suffix,__file__,'exec'))
