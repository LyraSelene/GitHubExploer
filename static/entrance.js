'use strict';
// Image-space paths, cached once per cover geometry. No repeated arc-length work.
((root)=>{
  const duration=8.2;
  function ease(a,b,t){const q=Math.max(0,Math.min(1,(t-a)/(b-a)));return q*q*q*(q*(q*6-15)+10);}
  function phases(t){return {reveal:ease(0,6.35,t),color:ease(5.95,7.55,t),outline:ease(0,.4,t)*(1-ease(7.0,duration,t)),fade:1-ease(7.15,duration,t)};}
  function pose(image,w,h){const s=Math.max(w/image.width,h/image.height);return {x:(w-image.width*s)/2,y:(h-image.height*s)/2,w:image.width*s,h:image.height*s};}
  let cache=null;
  function canvas(w,h){const c=document.createElement('canvas');c.width=Math.round(w);c.height=Math.round(h);return c;}
  function buildPath(path,frame){
    const points=path.points,screen=new Float32Array(points.length*2),cumulative=new Float64Array(points.length),full=new Path2D();let total=0;
    for(let i=0;i<points.length;i++){const x=frame.x+points[i][0]*frame.w,y=frame.y+points[i][1]*frame.h;screen[i*2]=x;screen[i*2+1]=y;if(i){total+=Math.hypot(x-screen[(i-1)*2],y-screen[(i-1)*2+1]);full.lineTo(x,y);}else full.moveTo(x,y);cumulative[i]=total;}
    return {screen,cumulative,total,full,start:path.start,duration:path.duration,done:false};
  }
  function ensureCache(w,h,source,frame){
    if(cache&&cache.w===w&&cache.h===h&&cache.source===source)return cache;
    const completed=canvas(w,h),layer=canvas(w,h),tip=canvas(40,40),tc=tip.getContext('2d'),g=tc.createRadialGradient(20,20,0,20,20,20);
    g.addColorStop(0,'#e0f8ff');g.addColorStop(.08,'#94ddff');g.addColorStop(.25,'rgba(76,178,249,.4)');g.addColorStop(1,'rgba(50,125,220,0)');tc.fillStyle=g;tc.fillRect(0,0,40,40);
    const raw=(root.EntrancePaths||[]).map((path,index)=>({path,index})).sort((a,b)=>{const atop=a.path.points.some(point=>point[1]<.095),btop=b.path.points.some(point=>point[1]<.095);return Number(btop)-Number(atop)||a.path.start-b.path.start||a.index-b.index;});
    // Use one continuous pen schedule. Durations are proportional to contour
    // length, so a large skirt/body contour is visibly drawn instead of
    // flashing in a single frame; each next contour starts after the prior
    // one, preserving the head-to-body order encoded by the source paths.
    const weights=raw.map(item=>{const points=item.path.points;let length=0;for(let i=1;i<points.length;i++)length+=Math.hypot((points[i][0]-points[i-1][0])*source.width,(points[i][1]-points[i-1][1])*source.height);return Math.max(1,length);});
    const weightTotal=weights.reduce((sum,value)=>sum+value,0);
    const revealStart=.32,revealSpan=5.92;
    let cursor=revealStart;
    const paths=raw.map((item,index)=>{
      const duration=revealSpan*weights[index]/Math.max(1,weightTotal);
      const built=buildPath({...item.path,start:cursor,duration},frame);
      cursor+=duration;
      return built;
    });
    cache={w,h,source,frame,paths,completed,cc:completed.getContext('2d'),layer,lc:layer.getContext('2d'),tip,lastTime:-1,tipX:new Float32Array(paths.length),tipY:new Float32Array(paths.length)};return cache;
  }
  // Append a partial path with a binary search in the cached cumulative lengths.
  function append(target,path,fraction,state,index){
    const limit=path.total*fraction,points=path.screen,cum=path.cumulative;let lo=1,hi=cum.length-1;
    while(lo<hi){const mid=(lo+hi)>>>1;if(cum[mid]<limit)lo=mid+1;else hi=mid;}
    target.moveTo(points[0],points[1]);for(let i=1;i<lo;i++)target.lineTo(points[i*2],points[i*2+1]);
    const previous=lo-1,q=Math.min(1,(limit-cum[previous])/Math.max(.001,cum[lo]-cum[previous]));
    const x=points[previous*2]+(points[lo*2]-points[previous*2])*q,y=points[previous*2+1]+(points[lo*2+1]-points[previous*2+1])*q;target.lineTo(x,y);state.tipX[index]=x;state.tipY[index]=y;
  }
  function style(ctx,frame){ctx.globalCompositeOperation='screen';ctx.strokeStyle='#99c7f3';ctx.lineWidth=Math.max(.65,frame.w/1800);ctx.lineJoin='round';ctx.lineCap='round';ctx.shadowColor='#428de0';ctx.shadowBlur=4;}
  function paint(ctx,w,h,source,edges,glow,time,expressionSurface=null){
    const p=phases(time);ctx.clearRect(0,0,w,h);if(p.fade<=0)return p;
    const frame=pose(source,w,h),state=ensureCache(w,h,source,frame);
    if(time<state.lastTime){state.cc.clearRect(0,0,w,h);for(const path of state.paths)path.done=false;}state.lastTime=time;
    const growing=new Path2D(),newlyDone=new Path2D();let active=0,completed=0;
    for(const path of state.paths){const amount=Math.max(0,Math.min(1,(time-path.start)/path.duration));if(amount>=1){if(!path.done){newlyDone.addPath(path.full);path.done=true;completed++;}}else if(amount>0)append(growing,path,amount,state,active++);}
    if(completed){style(state.cc,frame);state.cc.stroke(newlyDone);}
    const lc=state.lc;lc.clearRect(0,0,w,h);lc.save();lc.globalAlpha=p.color;
    if(p.color>0){if(expressionSurface)lc.drawImage(expressionSurface,0,0,w,h);else lc.drawImage(source,frame.x,frame.y,frame.w,frame.h);}
    lc.globalAlpha=p.outline;lc.globalCompositeOperation='screen';lc.drawImage(state.completed,0,0,w,h);
    if(active){style(lc,frame);lc.stroke(growing);lc.shadowBlur=0;
      // One restrained pen tip follows the latest contour, rather than a
      // cluster of glows that would make all contours appear simultaneous.
      lc.globalAlpha=p.outline*.72;const tipIndex=active-1;if(tipIndex>=0)lc.drawImage(state.tip,state.tipX[tipIndex]-10,state.tipY[tipIndex]-10,20,20);}
    lc.restore();ctx.save();ctx.globalAlpha=p.fade;ctx.fillStyle='#000';ctx.fillRect(0,0,w,h);ctx.drawImage(state.layer,0,0,w,h);ctx.restore();return p;
  }
  function reset(){if(cache){cache.cc.clearRect(0,0,cache.w,cache.h);for(const path of cache.paths)path.done=false;cache.lastTime=-1;}}
  root.EntranceAppearance={duration,phases,paint,reset};
})(typeof window!=='undefined'?window:globalThis);
