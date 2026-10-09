// Execute actual scene lifecycle with controlled clocks and a minimal canvas.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');require('../static/actions.js');
let timestamp=0,next=0,scheduled=new Map();const classes=new Set(['living-scene']);
const ctx=new Proxy({}, {get:(o,k)=>o[k]??(['createRadialGradient','createLinearGradient'].includes(k)?()=>({addColorStop(){}}):()=>{})});
const gl=new Proxy({getShaderParameter:()=>true,getProgramParameter:()=>true,getUniformLocation:(_,name)=>name}, {get:(o,k)=>o[k]??(()=>({}))});
const surface={getContext:()=>gl,dataset:{},addEventListener(){}},arrival={getContext:()=>ctx,dataset:{}};
const body={classList:{contains:c=>classes.has(c),toggle:(c,on)=>on?classes.add(c):classes.delete(c)}};
const doc={querySelector:s=>s==='#living-wallpaper'?surface:arrival,createElement:()=>({getContext:()=>ctx}),body,documentElement:{dataset:{sceneMetrics:"true",entryMetrics:"true"}}};
const sandbox={Path2D:class{moveTo(){}lineTo(){}addPath(){}},window:{},CharacterActions,document:doc,Image:class{constructor(){this.width=2275;this.height=1279;}decode(){return Promise.resolve();}},MutationObserver:class{observe(){}},innerWidth:1280,innerHeight:720,devicePixelRatio:1,performance:{now:()=>timestamp},requestAnimationFrame:fn=>{scheduled.set(++next,fn);return next;},cancelAnimationFrame:id=>scheduled.delete(id),addEventListener(){}};
let fallback; sandbox.setTimeout=fn=>{fallback=fn;return 1;};sandbox.clearTimeout=()=>{fallback=null;};
vm.runInNewContext(fs.readFileSync('static/entrance-paths.js','utf8'),sandbox);
assert(sandbox.window.EntrancePaths.length>100);
for(const path of sandbox.window.EntrancePaths){assert(path.start+path.duration<=6.151);for(const [x,y] of path.points)assert(x>=0&&x<=1&&y>=0&&y<=1);}
vm.runInNewContext(fs.readFileSync('static/entrance.js','utf8'),sandbox);sandbox.EntranceAppearance=sandbox.window.EntranceAppearance;
vm.runInNewContext(fs.readFileSync('static/scene.js','utf8'),sandbox);
(async()=>{const scene=sandbox.window.wallpaperScene;await scene.ready;let done=0;scene.draw(10,.7,'living');scene.playEntry(()=>done++);
 function tick(ms){timestamp=ms;const callbacks=[...scheduled.values()];scheduled.clear();callbacks.forEach(fn=>fn(ms));}
 tick(1200);assert.equal(Number(arrival.dataset.color),0);assert(Number(arrival.dataset.progress)>0);
 tick(5500);assert.equal(Number(arrival.dataset.color),0);tick(7800);assert(Number(arrival.dataset.color)>.99);assert.equal(done,0);tick(8200);assert.equal(done,1);assert.equal(scheduled.size,0);
 // Entry completion does not depend on scene time advancing (paused setting).
 scene.draw(10,.7,'living');assert.equal(surface.dataset.motionGain,'0.000');scene.draw(11.4,.7,'living');assert.equal(surface.dataset.motionGain,'1.000');
 scene.playEntry(()=>done++);scene.stopEntry();tick(15000);assert.equal(done,1);assert.equal(scheduled.size,0);
 // Restart cannot leave the old callback alive; resize reuses the same paint path.
 scene.playEntry(()=>done++);scene.playEntry(()=>done+=10);tick(23200);assert.equal(done,11);assert.equal(scheduled.size,0);
 scene.playEntry(()=>done++);assert(fallback);fallback();assert.equal(done,12);assert.equal(scheduled.size,0);assert.equal(fallback,null);
 scene.playEntry(()=>done++);doc.hidden=true;tick(24000);assert.equal(done,13);assert.equal(scheduled.size,0);assert.equal(fallback,null);doc.hidden=false;
 console.log('8.2s progressive strokes precede colour; pause/skip/restart and smooth resume passed.');})();
