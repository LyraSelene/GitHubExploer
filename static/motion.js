'use strict';
(() => {
  const canvas=document.querySelector('#waterlight'), ctx=canvas.getContext('2d');
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  let prefs, modes, entries, defaultPrompt, initialized=false, cycleTimer=null, saveTimer=null;
  let animationId=null, entryTimer=null, entryGeneration=0, entryUiTimer=null, width=0, height=0, clock=0, lastFrame=0;
  let saveQueue=Promise.resolve();
  let nativeHidden=false;
  const modeIds=['living','calm','buoyant','float','breathe','drift','ripple','sparkle','still'];
  const particles=Array.from({length:38},(_,i)=>({x:.34+(i*0.6180339887%1)*.65,y:i*.381966011%1,
    speed:.008+(i%5)*.002,phase:i*2.31,size:1+(i%4)*.42}));
  function resize(){width=innerWidth;height=innerHeight;const ratio=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);draw();}
  function draw(){if(window.wallpaperScene?.isEntryActive())return;ctx.clearRect(0,0,width,height);if(!prefs)return;window.wallpaperScene?.draw(clock,reduced.matches?0:prefs.intensity/100,prefs.mode);if(prefs.mode==='still'||reduced.matches||prefs.intensity===0)return;
    const strength=prefs.intensity/100;
    if(prefs.mode==='buoyant'){const phase=Math.sin(clock*Math.PI/4);document.documentElement.style.setProperty('--water-bob',(phase*strength*9).toFixed(3)+'px');document.documentElement.style.setProperty('--water-rock',(phase*strength*.2).toFixed(3)+'deg');}
    if(['living','calm','buoyant','sparkle','float','breathe','drift'].includes(prefs.mode)){
      const count=prefs.mode==='sparkle'?38:prefs.mode==='calm'?14:8;
      particles.slice(0,count).forEach((p,i)=>{const x=(p.x+Math.sin(clock*.13+p.phase)*.008)*width;
        const y=((p.y-clock*p.speed)%1+1)%1*height;const pulse=.35+.65*(.5+.5*Math.sin(clock*1.2+p.phase));
        ctx.globalAlpha=pulse*(prefs.mode==='sparkle'?.8:.6);ctx.fillStyle='#f7fdff';
        ctx.beginPath();ctx.arc(x,y,p.size*(.6+strength),0,Math.PI*2);ctx.fill();
        if(prefs.mode==='sparkle'&&i%4===0){ctx.strokeStyle='#faffff';ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(x-4,y);ctx.lineTo(x+4,y);ctx.moveTo(x,y-4);ctx.lineTo(x,y+4);ctx.stroke();}
      });
    }
    // Living-mode ripples are shaded in the same image coordinates as the hands.
    if(['ripple','calm','buoyant'].includes(prefs.mode)){
      const centers=[{x:.827,y:.72},{x:.543,y:.414}];
      centers.forEach((c,n)=>{const count=prefs.mode==='ripple'||prefs.mode==='buoyant'?4:2;
        for(let i=0;i<count;i++){const age=((clock*(prefs.mode==='buoyant'?.125:.115)+i/count+n*.2)%1);const r=18+age*(prefs.mode==='calm'?70:150)*(0.5+strength);
          const bob=prefs.mode==='buoyant'?Math.sin(clock*Math.PI/4)*strength*9:0;
          ctx.globalAlpha=Math.sin(age*Math.PI)*(prefs.mode==='calm'?.18:.46);ctx.strokeStyle='#eaffff';ctx.lineWidth=.75;
          ctx.beginPath();ctx.ellipse(c.x*width,c.y*height+bob,r,r*.31,0,0,Math.PI*2);ctx.stroke();}
      });
    }
    ctx.globalAlpha=1;
  }
  function canAnimate(){return initialized&&!nativeHidden&&!prefs.paused&&prefs.mode!=='still'&&prefs.intensity>0&&!document.hidden&&!reduced.matches&&!window.wallpaperScene?.isEntryActive();}
  function frame(timestamp){animationId=null;if(!canAnimate())return;if(!lastFrame||timestamp-lastFrame>=33){const dt=lastFrame?Math.min((timestamp-lastFrame)/1000,.12):0;clock+=dt;lastFrame=timestamp;draw();}animationId=requestAnimationFrame(frame);}
  function scheduleFrames(){if(animationId!==null)cancelAnimationFrame(animationId);animationId=null;lastFrame=0;if(canAnimate())animationId=requestAnimationFrame(frame);else if(reduced.matches||prefs?.mode==='still'||prefs?.intensity===0)ctx.clearRect(0,0,width,height);}
  function note(){const status=document.querySelector('#motion-note');status.textContent=reduced.matches?'系统已开启减少动态效果，壁纸和入场暂时静止。设置仍会保存。':prefs.mode==='living'&&document.documentElement.dataset.sceneReady==='fallback'?'当前设备无法启动局部渲染，已回退整体漂浮；请检查 WebView2 和显卡驱动。':'动态设置自动保存。角色水流模式使用局部形变模拟发丝、衣摆和水流，提示词不会生成视频。';}
  function renderControls(){document.querySelector('#motion-current').textContent=modes[prefs.mode].name;
    const pause=document.querySelector('#motion-pause');pause.textContent=prefs.paused?'▶':'Ⅱ';pause.setAttribute('aria-label',prefs.paused?'继续动态':'暂停动态');pause.title=prefs.paused?'继续动态':'暂停动态';
    document.querySelectorAll('.motion-preset').forEach(button=>{button.classList.toggle('active',button.dataset.mode===prefs.mode);button.setAttribute('aria-pressed',String(button.dataset.mode===prefs.mode));});
    document.querySelector('#motion-intensity').value=prefs.intensity;document.querySelector('#intensity-label').textContent=prefs.intensity+'%';
    document.querySelector('#motion-cycle').checked=prefs.cycle;document.querySelector('#motion-entry-enabled').checked=prefs.entry_enabled;
    document.querySelector('#motion-entry').value=prefs.entry;note();
    document.querySelector('#action-auto').checked=prefs.auto_actions;document.querySelector('#tail-amplitude').value=prefs.tail_amplitude;document.querySelector('#tail-amplitude-label').textContent=prefs.tail_amplitude+'%';document.querySelector('#tail-duration').value=prefs.tail_duration;document.querySelector('#tail-duration-label').textContent=prefs.tail_duration.toFixed(1)+' 秒';
  }
  function waterControls(){document.querySelector('#water-preset').value=prefs.water_preset;document.querySelector('#water-wait-min').value=prefs.water_wait_min;document.querySelector('#water-wait-max').value=prefs.water_wait_max;for(const key of ['tail','brush','fin','drift','respond'])document.querySelector('#water-'+key).checked=prefs['water_'+key];}
  function apply(){document.body.dataset.motion=prefs.mode;document.body.classList.toggle('motion-paused',prefs.paused||document.hidden||prefs.intensity===0);
    const root=document.documentElement,s=prefs.intensity/100;
    root.style.setProperty('--motion-shift',(s*13).toFixed(2)+'px');root.style.setProperty('--motion-side',(s*15).toFixed(2)+'px');
    root.style.setProperty('--motion-angle',(s*.45).toFixed(3)+'deg');root.style.setProperty('--motion-zoom',(1.04+s*.026).toFixed(4));
    root.style.setProperty('--motion-alpha',String(.2+s*.6));
    window.wallpaperScene.configureWater?.({preset:prefs.water_preset,waitMin:prefs.water_wait_min,waitMax:prefs.water_wait_max,enabled:Object.fromEntries(['tail','brush','fin','drift','respond'].map(k=>[k,prefs['water_'+k]]))});window.wallpaperScene.setAutomatic(prefs.auto_actions);window.wallpaperScene.configureTail(prefs.tail_amplitude,prefs.tail_duration);
    if(cycleTimer)clearInterval(cycleTimer);cycleTimer=null;
    if(prefs.cycle&&!prefs.paused&&!document.hidden&&!reduced.matches&&!document.body.classList.contains('entry-playing'))cycleTimer=setInterval(()=>switchMode(1),20000);
    window.wallpaperScene.pauseEntry(prefs.paused);renderControls();waterControls();scheduleFrames();draw();
  }
  function persist(){const snapshot={...prefs};const request=saveQueue.then(()=>api('motion',snapshot));saveQueue=request.catch(()=>{});return request;}
  function save(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>guard(persist),220);}
  function change(values){prefs={...prefs,...values};apply();save();}
  function switchMode(direction){const current=modeIds.indexOf(prefs.mode);change({mode:modeIds[(current+direction+modeIds.length)%modeIds.length]});}
  function open(){document.querySelector('#entry-prompt').value=prefs.prompt;renderControls();openModal('motion-modal');}
  function endEntry(){const active=document.body.classList.contains('entry-playing'),completed=document.body.classList.contains('entry-completed');entryGeneration++;clearTimeout(entryTimer);window.wallpaperScene?.stopEntry(completed);const video=document.querySelector('#arrival-video');video.onended=null;video.onerror=null;video.pause();document.querySelector('#arrival').classList.remove('playing','leaving');document.querySelector('#skip-arrival').hidden=true;document.body.classList.remove('entry-playing','entry-completed');if(active){document.body.classList.add('workspace-enter');clearTimeout(entryUiTimer);entryUiTimer=setTimeout(()=>document.body.classList.remove('workspace-enter'),650);apply();}}
  function fadeEntry(){clearTimeout(entryTimer);document.querySelector('#arrival').classList.add('leaving');entryTimer=setTimeout(endEntry,680);}
  function playEntry(){endEntry();if(reduced.matches){toast('系统开启了减少动态效果，入场已跳过');return;}if(prefs.entry==='none'){toast('当前入场设置为不播放');return;}
    const generation=++entryGeneration,entry=document.querySelector('#arrival');document.body.classList.remove('workspace-enter');clearTimeout(entryUiTimer);entry.dataset.effect=prefs.entry;void entry.offsetWidth;entry.classList.add('playing');
    document.body.classList.add('entry-playing');document.querySelector('#skip-arrival').hidden=false;
    if(cycleTimer)clearInterval(cycleTimer);cycleTimer=null;
    if(prefs.entry==='portrait'){if(document.body.classList.contains('character-active')||document.documentElement.dataset.sceneReady!=='true'||prefs.mode!=='living'){endEntry();toast('原画描边入场需选择原画与角色水流模式；当前保留你的背景设置。');return;}window.wallpaperScene.playEntry(()=>{if(generation===entryGeneration){document.body.classList.add('entry-completed');endEntry();}});scheduleFrames();ctx.clearRect(0,0,width,height);if(prefs.paused)window.wallpaperScene.pauseEntry(true);}
    else if(prefs.entry==='outline'){const video=document.querySelector('#arrival-video');video.currentTime=0;video.onended=()=>{if(generation===entryGeneration)fadeEntry();};video.onerror=()=>{if(generation===entryGeneration){endEntry();toast('入场视频未能播放，可以切换水光或淡入。');}};video.play().catch(()=>{if(generation===entryGeneration){endEntry();toast('入场视频未能播放，可以切换其他效果。');}});entryTimer=setTimeout(fadeEntry,10000);}
    else entryTimer=setTimeout(endEntry,prefs.entry==='fade'?1650:2850);
  }
  function initialize(data){prefs={water_preset:'quiet',water_wait_min:20,water_wait_max:45,water_tail:true,water_brush:true,water_fin:true,water_drift:true,water_respond:true,...data.motion};modes=data.motion_modes;entries=data.entry_modes;defaultPrompt=data.default_entry_prompt;
    const presets=document.querySelector('#motion-presets');presets.replaceChildren();modeIds.forEach(id=>{const button=document.createElement('button');button.className='motion-preset';button.dataset.mode=id;
      const title=document.createElement('strong'), description=document.createElement('span');title.textContent=modes[id].name;description.textContent=modes[id].description;button.append(title,description);button.onclick=()=>change({mode:id});presets.append(button);});
    const select=document.querySelector('#motion-entry');select.replaceChildren();Object.entries(entries).forEach(([key,label])=>{const option=document.createElement('option');option.value=key;option.textContent=label;select.append(option);});
    initialized=true;window.WallpaperMotion={setWindowHidden(value){nativeHidden=!!value;if(nativeHidden)endEntry();apply();},state:()=>({nativeHidden,clock,paused:prefs.paused})};resize();apply();if(prefs.entry_enabled&&prefs.entry!=='none'&&!reduced.matches)playEntry();
    document.querySelector('#motion-open').onclick=open;document.querySelector('#motion-current').onclick=open;
    document.querySelector('#motion-prev').onclick=()=>switchMode(-1);document.querySelector('#motion-next').onclick=()=>switchMode(1);
    document.querySelector('#motion-pause').onclick=()=>change({paused:!prefs.paused});document.querySelector('#motion-replay').onclick=playEntry;
    document.querySelector('#motion-intensity').oninput=event=>change({intensity:Number(event.target.value)});
    document.querySelector('#motion-cycle').onchange=event=>change({cycle:event.target.checked});
    document.querySelector('#motion-entry-enabled').onchange=event=>change({entry_enabled:event.target.checked});
    document.querySelector('#motion-entry').onchange=event=>change({entry:event.target.value});
    document.querySelector('#tail-amplitude').oninput=event=>change({tail_amplitude:Number(event.target.value)});document.querySelector('#tail-duration').oninput=event=>change({tail_duration:Number(event.target.value)});
    document.querySelector('#water-preset').onchange=e=>change({water_preset:e.target.value});
    for(const key of ['tail','brush','fin','drift','respond'])document.querySelector('#water-'+key).onchange=e=>change({['water_'+key]:e.target.checked});
    for(const key of ['min','max'])document.querySelector('#water-wait-'+key).onchange=e=>{const value=Number(e.target.value),min=key==='min'?value:prefs.water_wait_min,max=key==='max'?value:prefs.water_wait_max;if(!Number.isInteger(value)||min<8||max>180||min>max){toast('等待范围应为8–180秒，最小值不能超过最大值');waterControls();return;}change({['water_wait_'+key]:value});};
    document.querySelector('#action-auto').onchange=event=>change({auto_actions:event.target.checked});
    document.querySelectorAll('[data-character-action]').forEach(button=>button.onclick=()=>{if(reduced.matches){toast('系统减少动态效果已开启，请关闭后播放动作');return;}if(document.body.classList.contains('character-active')){toast('当前使用导入素材，请在角色动作库选择原画再播放动作');return;}if(document.documentElement.dataset.sceneReady!=='true'){toast('当前设备未启用角色渲染，请检查 WebView2 与显卡驱动');return;}const kind=button.dataset.characterAction;if(window.wallpaperScene.isEntryActive())return;const key=kind==='wave'||kind==='lift'?'brush':kind;if(prefs['water_'+key]===false){toast('请先开启该动作开关');return;}change({mode:'living',paused:false,intensity:prefs.intensity||45});if(kind==='drift'){change({water_drift:true});return;}window.wallpaperScene.trigger(kind);});
    document.querySelector('#entry-preview').onclick=()=>{closeModal('motion-modal');playEntry();};document.querySelector('#skip-arrival').onclick=()=>endEntry();
    document.querySelector('#prompt-reset').onclick=()=>{document.querySelector('#entry-prompt').value=defaultPrompt;toast('已填入推荐提示词，点击保存即可保留');};
    document.querySelector('#prompt-copy').onclick=()=>guard(async()=>{await navigator.clipboard.writeText(document.querySelector('#entry-prompt').value);toast('入场动画提示词已复制');});
    document.querySelector('#prompt-export').onclick=()=>guard(()=>exportText('入场动画提示词',document.querySelector('#entry-prompt').value));
    document.querySelector('#save-entry-prompt').onclick=()=>guard(async()=>{const prompt=document.querySelector('#entry-prompt').value;
      if(prompt.length>12000)throw Error('提示词最多 12,000 字符');clearTimeout(saveTimer);prefs={...prefs,prompt};await persist();toast('提示词已保存；可以复制到图生视频工具使用');});
    addEventListener('resize',resize);document.addEventListener('visibilitychange',()=>{if(document.hidden)endEntry();apply();});reduced.addEventListener('change',()=>{if(reduced.matches)endEntry();apply();});
    document.documentElement.dataset.motionReady='true';
  }
  const wait=setInterval(()=>{if(typeof state!=='undefined'&&state.data){clearInterval(wait);window.wallpaperScene.ready.then(()=>initialize(state.data));}},50);
})();
