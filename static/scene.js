'use strict';
(() => {
  const surface=document.querySelector('#living-wallpaper'),arrival=document.querySelector('#arrival-contour');
  const entryContext=arrival.getContext('2d'),source=new Image(),edges=new Image(),edgeGlow=new Image(),facePicture=new Image(),rigBase=new Image(),forearm=new Image(),tailMask=new Image(),driftMask=new Image();
  source.src='wallpaper.webp';edges.src='wallpaper-outline.png';facePicture.src='wallpaper-face.png';
  rigBase.src='wallpaper-rig-base.png';forearm.src='forearm-layer.png';
  edgeGlow.src='wallpaper-outline-glow.png';tailMask.src='tail-flow-mask.png';driftMask.src='water-drift-mask.png';
  const tailWaves=new Float32Array(24),tailContact=new Float32Array(2);let waveHead=0,lastTailEmission=-10,tailEnabled=true;
  for(let i=0;i<6;i++)tailWaves[i*4+2]=-100;
  const handContact=new Float32Array(2);let lastHandEmission=-10;
  function recordHandWave(time,arm,wa,strength,velocity){const r=CharacterActions.armRig,p=r.pivot,w=r.wrist,c=r.contact,dx=c[0]-w[0],dy=c[1]-w[1],x=w[0]+Math.cos(wa)*dx+Math.sin(wa)*dy-p[0],y=w[1]-Math.sin(wa)*dx+Math.cos(wa)*dy-p[1];handContact[0]=p[0]+Math.cos(arm)*x+Math.sin(arm)*y;handContact[1]=p[1]-Math.sin(arm)*x+Math.cos(arm)*y;if(strength>0&&Math.abs(velocity)>.014&&time-lastHandEmission>.44){const i=waveHead*4;tailWaves[i]=handContact[0]/source.width;tailWaves[i+1]=handContact[1]/source.height;tailWaves[i+2]=time;tailWaves[i+3]=Math.min(.35,Math.abs(velocity)*strength*.8);waveHead=(waveHead+1)%6;lastHandEmission=time;}}
  let perfFrames=[],perfDraw=[],perfLast=null,perfOn=false;
  function tailContactAt(body,fin,strength){const c=CharacterActions.tailRig.contact,d=CharacterActions.tailDisplacement(c[0],body,fin,strength);tailContact[0]=c[0]-d[0];tailContact[1]=c[1]-d[1];return tailContact;}
  function recordTailWave(time,body,fin,strength,velocity){const c=tailContactAt(body,fin,strength);if(strength>0&&Math.abs(velocity)>.035&&time-lastTailEmission>.36){const at=waveHead*4;tailWaves[at]=c[0]/source.width;tailWaves[at+1]=c[1]/source.height;tailWaves[at+2]=time;tailWaves[at+3]=Math.min(.9,Math.abs(velocity)*strength*.7);waveHead=(waveHead+1)%6;lastTailEmission=time;}}
  let gl=surface.getContext('webgl',{alpha:false,antialias:false,preserveDrawingBuffer:false});
  let program,uniforms={},entryFrame=null,entryTimer=null,entryStart=0,entryActive=false,entryDone=null,entryExpression=null,entryGeneration=0,lastTime=0,lastStrength=.7,lastMode='living';
  const actionController=new CharacterActions.Controller();
  let expressionFrame=null,entryPausedAt=null,expressionPausedAt=null;
  let intensity=.7,intensityTime=0,entryMotion=null,motionGain=1;
  const vertex='attribute vec2 position;varying vec2 uv;void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}';
  const fragment=`precision highp float;varying vec2 uv;uniform sampler2D picture;uniform sampler2D facePicture;uniform sampler2D rigPicture;uniform sampler2D armPicture;uniform vec2 viewport;uniform vec2 imageSize;uniform float time;uniform float strength;uniform vec3 actions;uniform float wink;uniform float armAngle;uniform float wristAngle;uniform float smile;uniform float originalBlend;uniform sampler2D tailMask;uniform sampler2D driftMask;uniform float drift;uniform vec2 tail;uniform vec4 tailWaves[6];
  float zone(vec2 p,vec2 center,vec2 radius){vec2 q=(p-center)/radius;return exp(-dot(q,q)*2.);}
  float ripple(vec2 p,vec2 center,float phase){vec2 delta=(p-center)*imageSize;delta.y*=2.1;float radius=length(delta);float pulse=sin(radius*.075-time*.52+phase);return pulse*exp(-radius/115.)*smoothstep(13.,35.,radius);}
  vec2 tailShift(vec2 pixel){float q=clamp((pixel.x-1840.)/350.,0.,1.);q=q*q*q*(q*(q*6.-15.)+10.);float f=clamp((pixel.x-2040.)/100.,0.,1.);f=f*f*f*(f*(f*6.-15.)+10.);return vec2(tail.x*3.*q+tail.y*2.*f,tail.x*14.*q+tail.y*7.*f)*strength;}
  float tailWave(vec2 p,vec4 wave){float age=time-wave.z;if(age<0.||age>3.2||wave.w<=0.)return 0.;vec2 delta=(p-wave.xy)*imageSize;delta.y*=2.4;float distance=length(delta),radius=12.+age*48.;return sin((distance-radius)*.1)*exp(-pow((distance-radius)/18.,2.))*sin(min(1.,age/.22)*1.5708)*exp(-age*1.05)*wave.w;}
  vec3 eyelid(vec2 q,float frame,float row){vec2 pixel=clamp(q*vec2(220.,150.),vec2(.5),vec2(219.5,149.5));return texture2D(facePicture,vec2((frame*220.+pixel.x)/2860.,(row*150.+pixel.y)/300.)).rgb;}
  vec3 eyeFrame(vec2 q,float closure,float row){float f=clamp(closure,0.,1.)*12.;return mix(eyelid(q,floor(f),row),eyelid(q,min(12.,floor(f)+1.),row),fract(f));}
  void main(){float cover=max(viewport.x/imageSize.x,viewport.y/imageSize.y);vec2 span=viewport/(imageSize*cover);vec2 p=(vec2(uv.x,1.-uv.y)-.5)*span+.5;
    float face=zone(p,vec2(.777,.239),vec2(.11,.15));
    float hair=zone(p,vec2(.614,.296),vec2(.17,.14))+zone(p,vec2(.896,.433),vec2(.14,.23));
    float cloth=zone(p,vec2(.608,.69),vec2(.24,.25));
    float torso=zone(p,vec2(.72,.48),vec2(.2,.31));
    float water=(1.-min(1.,hair+cloth+torso))*.8;
    float tide=time*.52;
    // Compact offline masks exclude face/head, wrist and the tail connection.
    vec3 regions=texture2D(driftMask,p).rgb;
    vec2 offset=drift*(regions.r*vec2(sin(tide-.4)*1.6,cos(tide-.4)*.9)+regions.g*vec2(sin(tide-.85)*1.1,cos(tide-.85)*.6)+regions.b*vec2(0.,sin(tide-.1)*.35));
    offset+=actions.y*regions.b*vec2(-.25,.6);
    offset*=strength;
    p+=offset/imageSize;

    vec2 tex=clamp(p,vec2(.001),vec2(.999));
    vec2 pivot=vec2(${CharacterActions.armRig.pivot.map(n=>n.toFixed(1)).join(',')});vec2 delta=tex*imageSize-pivot;
    float joint=smoothstep(${CharacterActions.armRig.joint.map(n=>n.toFixed(1)).join(',')},length(delta));float angle=armAngle*joint;
    vec2 armUV=(pivot+vec2(cos(angle)*delta.x-sin(angle)*delta.y,sin(angle)*delta.x+cos(angle)*delta.y))/imageSize;
    vec2 wrist=vec2(${CharacterActions.armRig.wrist.map(n=>n.toFixed(1)).join(',')});vec2 wd=armUV*imageSize-wrist;
    float wa=wristAngle*smoothstep(${CharacterActions.armRig.wristBlend.map(n=>n.toFixed(1)).join(',')},armUV.y*imageSize.y);
    armUV=(wrist+vec2(cos(wa)*wd.x-sin(wa)*wd.y,sin(wa)*wd.x+cos(wa)*wd.y))/imageSize;
    vec4 sprite=texture2D(armPicture,clamp(armUV,vec2(.001),vec2(.999)));
    vec2 tailUV=tex;float tailWeight=0.;vec2 pixel=tex*imageSize;
    if(pixel.x>1810.&&pixel.x<2275.&&pixel.y>750.&&pixel.y<1170.){
      tailWeight=texture2D(tailMask,(pixel-vec2(1810.,750.))/vec2(465.,420.)).r;
      tailUV=clamp(tex+tailShift(pixel)*tailWeight/imageSize,vec2(.001),vec2(.999));
    }
    vec3 rebuilt=mix(texture2D(rigPicture,tailUV).rgb,sprite.rgb,sprite.a);
    // Keep the same composite at zero and at movement: no original/rig swap.
    vec3 color=rebuilt;
    // One face sample in the same advected coordinates as the body. The lips
    // stay original artwork: lift the downward lip corner around a fixed inner
    // corner, keeping its original pigment, shading and face angle.
    vec2 fp=tex*imageSize;float lipT=clamp((fp.x-1763.)/15.,0.,1.);
    float lipMask=(1.-smoothstep(1780.,1788.,fp.x))*smoothstep(1758.,1763.,fp.x)*(1.-smoothstep(6.,24.,abs(fp.y-315.)));
    float lipLift=smile*(2.8*lipT-4.2*sin(lipT*3.14159265))*lipMask;
    vec2 faceUV=(fp+vec2(0.,lipLift)-vec2(1700.,215.))/vec2(220.,150.);
    if(faceUV.x>0.&&faceUV.x<1.&&faceUV.y>0.&&faceUV.y<1.){
      // Left and right eyes occupy disjoint halves; choose the closure once,
      // rather than adding two replacement images (which could double pigment).
      float closure=fp.x<1800.?actions.x:max(actions.x,wink);
      color=eyeFrame(faceUV,closure,0.);
    }
    vec2 contact=vec2(${CharacterActions.armRig.contact.map(n=>n.toFixed(1)).join(',')})-wrist;float wc=cos(wristAngle),ws=sin(wristAngle);
    contact=wrist+vec2(wc*contact.x+ws*contact.y,-ws*contact.x+wc*contact.y)-pivot;float ca=cos(armAngle),sa=sin(armAngle);
    vec2 hand=(pivot+vec2(ca*contact.x+sa*contact.y,-sa*contact.x+ca*contact.y))/imageSize;
    float light=sin(tide+p.x*23.+p.y*17.)*.004*water*strength*drift;
    float tailLight=0.;
    if(p.x>.72&&p.y>.55){for(int i=0;i<6;i++)tailLight+=tailWave(p,tailWaves[i]);}
    light+=tailLight*.014*strength*(1.-sprite.a);
    // Existing submerged pigment stays painted; only subtle water refraction light.
    light+=tailWeight*sin(tide*.8+p.x*42.+p.y*19.)*abs(tail.y-tail.x)*.002*strength;
    gl_FragColor=vec4(mix(color+light,texture2D(picture,clamp((vec2(uv.x,1.-uv.y)-.5)*span+.5,vec2(.001),vec2(.999))).rgb,originalBlend),1.);
  }`;
  function shader(kind,text){const value=gl.createShader(kind);gl.shaderSource(value,text);gl.compileShader(value);if(!gl.getShaderParameter(value,gl.COMPILE_STATUS))throw Error('Shader unavailable');return value;}
  function setup(){try{program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('WebGL unavailable');gl.useProgram(program);
      const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);const position=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
      [source,facePicture,rigBase,forearm,tailMask,driftMask].forEach((image,index)=>{const texture=gl.createTexture();gl.activeTexture(gl.TEXTURE0+index);gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);gl.uniform1i(gl.getUniformLocation(program,['picture','facePicture','rigPicture','armPicture','tailMask','driftMask'][index]),index);});
      ['viewport','imageSize','time','strength','actions','wink','armAngle','wristAngle','smile','originalBlend','drift','tail','tailWaves[0]'].forEach(name=>uniforms[name]=gl.getUniformLocation(program,name));document.documentElement.dataset.sceneReady='true';
    }catch{gl=null;document.documentElement.dataset.sceneReady='fallback';}}
  function fit(image){const scale=Math.max(innerWidth/image.width,innerHeight/image.height);return {x:(innerWidth-image.width*scale)/2,y:(innerHeight-image.height*scale)/2,w:image.width*scale,h:image.height*scale};}
  function draw(time,strength,mode,expressionPass=false){const paintStart=perfOn?performance.now():0;lastTime=time;lastStrength=strength;lastMode=mode;const living=mode==='living'&&!document.body.classList.contains('character-active'),active=living&&!!gl&&!!program;surface.hidden=!active;if(document.body.classList.contains('living-scene')!==active)document.body.classList.toggle('living-scene',active);if(!active||document.hidden)return;if(expressionFrame!==null&&!expressionPass)return;if(entryActive&&(performance.now()-entryStart)/1000<7.2)return;
    const ratio=Math.min(devicePixelRatio||1,1.25),w=Math.round(innerWidth*ratio),h=Math.round(innerHeight*ratio);if(surface.width!==w||surface.height!==h){surface.width=w;surface.height=h;gl.viewport(0,0,w,h);}gl.useProgram(program);gl.uniform2f(uniforms.viewport,innerWidth,innerHeight);gl.uniform2f(uniforms.imageSize,source.width,source.height);gl.uniform1f(uniforms.time,time);gl.uniform1f(uniforms.strength,strength);
    const dt=Math.max(0,Math.min(.12,time-intensityTime));intensityTime=time;intensity+=(strength-intensity)*(1-Math.exp(-dt*6));
    if(strength===0)intensity=0;
    if(entryMotion&&!entryActive&&!entryExpression){const progress=CharacterActions.smooth((time-entryMotion.start)/entryMotion.duration);motionGain=entryMotion.from+(1-entryMotion.from)*progress;if(progress===1)entryMotion=null;}
    const effective=entryActive||entryExpression?0:intensity*motionGain;gl.uniform1f(uniforms.strength,effective);
    let action=actionController.update(time);if(strength===0||entryActive||entryExpression)action={blink:0,wink:0,nod:0,wave:0,tail:0};
    let entryWink=0,entrySmile=0;
    if(entryExpression){const age=((expressionPausedAt||entryPausedAt||performance.now())-entryExpression.start)/1000;if(age<0||age>=CharacterActions.lengths.wink){entryExpression=null;motionGain=0;entryMotion={from:0,start:lastTime,duration:1.3};}else{entryWink=CharacterActions.sample('wink',age).wink;entrySmile=.42*CharacterActions.smooth((age-.09)/.3)*(1-CharacterActions.smooth((age-.51)/.54));}}
    const tailBody=tailEnabled?action.tail:0,tailFin=tailEnabled&&effective>0?actionController.tailFin+.025*Math.sin(time*.52-1.1)*actionController.driftGain:0;
    gl.uniform1f(uniforms.drift,actionController.driftGain);
    recordTailWave(time,tailBody,tailFin,effective,tailEnabled?actionController.velocity.tail+actionController.tailFinVelocity*.4:0);
    gl.uniform2f(uniforms.tail,tailBody,tailFin);
    const armAngle=CharacterActions.armAngle(action.wave,effective);
    const wristAngle=entryActive||entryExpression?0:CharacterActions.wristAngle(actionController.wrist,effective,armAngle),smile=entryWink>0?entrySmile:(entryActive||strength===0?0:actionController.smile*motionGain);
    recordHandWave(time,armAngle,wristAngle,effective,actionController.velocity.wave);gl.uniform4fv(uniforms['tailWaves[0]'],tailWaves);
    gl.uniform3f(uniforms.actions,action.blink,action.nod,action.wave);gl.uniform1f(uniforms.wink,entryWink>0?entryWink:action.wink);gl.uniform1f(uniforms.armAngle,armAngle);gl.uniform1f(uniforms.wristAngle,wristAngle);gl.uniform1f(uniforms.smile,smile);gl.uniform1f(uniforms.originalBlend,entryActive?1:entryMotion?1-motionGain:0);gl.drawArrays(gl.TRIANGLES,0,6);
    if(perfOn){const now=performance.now();if(perfLast!==null)perfFrames.push(now-perfLast);perfLast=now;perfDraw.push(now-paintStart);}
    if(document.documentElement.dataset.sceneMetrics==='true'){surface.dataset.frameTime=time.toFixed(3);surface.dataset.actionValues=JSON.stringify({...action,wink:entryWink>0?entryWink:action.wink});surface.dataset.armAngle=armAngle.toFixed(5);surface.dataset.wristAngle=wristAngle.toFixed(5);surface.dataset.smile=smile.toFixed(5);surface.dataset.motionGain=motionGain.toFixed(3);surface.dataset.tailFin=tailFin.toFixed(5);surface.dataset.tailContact=JSON.stringify(Array.from(tailContact));}}
  function stopEntry(preserveExpression=false){const wasActive=entryActive;entryActive=false;entryDone=null;if(!preserveExpression){entryExpression=null;expressionPausedAt=null;if(expressionFrame!==null)cancelAnimationFrame(expressionFrame);expressionFrame=null;}entryPausedAt=null;entryGeneration++;if(entryFrame!==null)cancelAnimationFrame(entryFrame);if(entryTimer!==null)clearTimeout(entryTimer);entryTimer=null;entryFrame=null;entryContext.clearRect(0,0,arrival.width,arrival.height);if(!preserveExpression||wasActive)entryMotion={from:motionGain,start:lastTime,duration:1.3};}
  function expressionTick(){expressionFrame=null;if(!entryExpression||document.hidden)return;draw(lastTime,lastStrength,lastMode,true);if(entryExpression)expressionFrame=requestAnimationFrame(expressionTick);else{motionGain=0;entryMotion={from:0,start:lastTime,duration:1.3};}}
  function finishEntry(){if(!entryActive)return;const done=entryDone;entryActive=false;entryDone=null;if(entryFrame!==null)cancelAnimationFrame(entryFrame);entryFrame=null;if(entryTimer!==null)clearTimeout(entryTimer);entryTimer=null;entryExpression=null;expressionPausedAt=null;if(expressionFrame!==null){cancelAnimationFrame(expressionFrame);expressionFrame=null;}entryMotion={from:0,start:lastTime,duration:1.3};if(done)done();}
  function entry(timestamp){if(!entryActive)return;const perf=document.documentElement.dataset.entryMetrics==='true'?window.__entryPerf:null;if(perf){if(perf.lastTimestamp!==null)perf.frames.push(timestamp-perf.lastTimestamp);perf.lastTimestamp=timestamp;perf.timestamps.push(timestamp);}if(document.hidden){const done=entryDone;stopEntry();done?.();return;}const elapsed=((entryPausedAt||timestamp)-entryStart)/1000;const ratio=Math.min(devicePixelRatio||1,1.25);if(arrival.width!==Math.round(innerWidth*ratio)||arrival.height!==Math.round(innerHeight*ratio)){arrival.width=Math.round(innerWidth*ratio);arrival.height=Math.round(innerHeight*ratio);}entryContext.setTransform(ratio,0,0,ratio,0,0);const ctx=entryContext,w=innerWidth,h=innerHeight;
    if(elapsed>=7.2)draw(lastTime,lastStrength,lastMode);
    const phase=EntranceAppearance.paint(ctx,w,h,source,edges,edgeGlow,elapsed,null);
    if(document.documentElement.dataset.entryMetrics==='true'){arrival.dataset.progress=phase.reveal.toFixed(3);arrival.dataset.color=phase.color.toFixed(3);arrival.dataset.fade=phase.fade.toFixed(3);}
    if(elapsed>=EntranceAppearance.duration){finishEntry();return;}if(!entryPausedAt)entryFrame=requestAnimationFrame(entry);
  }
  function playEntry(onDone){actionController.suspend();stopEntry();entryGeneration++;EntranceAppearance.reset?.();if(document.documentElement.dataset.entryMetrics==='true')window.__entryPerf={frames:[],timestamps:[],paint:[],paintTotal:0,lastTimestamp:null};entryActive=true;entryDone=onDone;entryStart=performance.now();motionGain=0;entryMotion=null;entry(entryStart);draw(lastTime,lastStrength,lastMode);
    // Occluded WebViews may throttle requestAnimationFrame. Never leave the
    // workspace hidden waiting for the last animation frame to be delivered.
    entryTimer=setTimeout(()=>{if(!entryActive)return;finishEntry();},EntranceAppearance.duration*1000+250);}
  const ready=Promise.all([source.decode(),edges.decode(),edgeGlow.decode(),facePicture.decode(),rigBase.decode(),forearm.decode(),tailMask.decode(),driftMask.decode()]).then(()=>{if(gl)setup();else document.documentElement.dataset.sceneReady='fallback';draw(lastTime,lastStrength,lastMode);}).catch(()=>{gl=null;document.documentElement.dataset.sceneReady='fallback';});
  function trigger(kind){if(entryActive||entryExpression)return;actionController.trigger(kind,lastTime);draw(lastTime,lastStrength,lastMode);}
  function setAutomatic(value){actionController.setAutomatic(value);}
  function configureTail(amplitude,speed){actionController.configureTail(amplitude/100,5.2/speed);}
  function measure(enabled){perfOn=enabled;perfFrames=[];perfDraw=[];perfLast=null;}
  function measured(){return {frames:perfFrames,draw:perfDraw};}
  function pauseEntry(paused){const now=performance.now();if(entryActive){if(paused&&!entryPausedAt){entryPausedAt=now;cancelAnimationFrame(entryFrame);entryFrame=null;clearTimeout(entryTimer);}else if(!paused&&entryPausedAt){const delta=now-entryPausedAt;entryStart+=delta;if(entryExpression)entryExpression.start+=delta;entryPausedAt=null;entryFrame=requestAnimationFrame(entry);entryTimer=setTimeout(finishEntry,Math.max(0,EntranceAppearance.duration*1000-(now-entryStart))+250);}}else if(entryExpression){if(paused&&!expressionPausedAt){expressionPausedAt=now;cancelAnimationFrame(expressionFrame);expressionFrame=null;}else if(!paused&&expressionPausedAt){entryExpression.start+=now-expressionPausedAt;expressionPausedAt=null;expressionFrame=requestAnimationFrame(expressionTick);}}}
  window.wallpaperScene={configureWater:settings=>actionController.configureWater(settings),waterState:()=>({pose:{...actionController.value},fin:actionController.tailFin,smile:actionController.smile,drift:actionController.driftGain,hand:Array.from(handContact),active:Object.keys(actionController.manual),nextAuto:actionController.nextAuto}),configureTail,measure,measured,setTailEnabled:value=>{tailEnabled=!!value;},tailState:()=>({body:actionController.value.tail,fin:actionController.tailFin,velocity:actionController.velocity.tail,contact:Array.from(tailContact),waves:Array.from(tailWaves)}),ready,draw,playEntry,stopEntry,trigger,setAutomatic,pauseEntry,isEntryActive:()=>entryActive,entryState:()=>({active:entryActive,expression:!!entryExpression,paused:!!entryPausedAt,entryFrame:entryFrame!==null,expressionFrame:expressionFrame!==null})};
  addEventListener('resize',()=>draw(lastTime,lastStrength,lastMode));new MutationObserver(()=>draw(lastTime,lastStrength,lastMode)).observe(document.body,{attributes:true,attributeFilter:['class']});
  surface.addEventListener('webglcontextlost',event=>{event.preventDefault();gl=null;surface.hidden=true;document.body.classList.remove('living-scene');document.documentElement.dataset.sceneReady='fallback';});
  surface.addEventListener('webglcontextrestored',()=>{gl=surface.getContext('webgl');setup();draw(lastTime,lastStrength,lastMode);});
})();
