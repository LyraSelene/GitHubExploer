'use strict';
// Same pure timeline is used by the renderer and Node boundary checks.
((root) => {
  const lengths={blink:.72,wink:1.05,nod:4.2,wave:5.6,lift:7,tail:5.2,brush:5.8,fin:4.8,tailBrush:13,respond:4.8};
  const tailRig={root:[1810,1060],contact:[2100,972],bounds:[1810,750,2275,1170],amplitude:14,finAmplitude:7};
  function tailDisplacement(x,body,fin,strength){const q=smooth((x-1840)/350),f=smooth((x-2040)/100);return [strength*(body*3*q+fin*2*f),strength*(body*14*q+fin*7*f)];}
  // Source-pixel rig: the top of the sleeve stays attached; cuff and hand
  // rotate as one piece. Asymmetric sweep follows the water gap beside the fin.
  const armRig={pivot:[1778,665],joint:[40,105],contact:[1888,912],wrist:[1840,833],wristBlend:[812,863]};
  function armAngle(value,strength){const s=Math.max(-1,Math.min(1,value))*Math.max(0,Math.min(1,strength));return .195*s+.035*s*s;}
  function wristAngle(value,strength,arm){return Math.max(-.16-arm,Math.min(.23-arm,Math.max(-.065,Math.min(.065,value))*strength));}
  function smooth(value){const t=Math.max(0,Math.min(1,value));return t*t*t*(t*(t*6-15)+10);}
  function envelope(time,duration){return time<0||time>=duration?0:Math.sin(Math.PI*time/duration)**2;}
  function sample(kind,elapsed){const value={blink:0,wink:0,nod:0,wave:0,tail:0,fin:0};if(!(kind in lengths)||!Number.isFinite(elapsed))return value;
    const duration=lengths[kind];if(elapsed<0||elapsed>=duration)return value;
    if(kind==='blink')value.blink=elapsed<.22?smooth(elapsed/.22):elapsed<.30?1:1-smooth((elapsed-.30)/.42);
    if(kind==='wink')value.wink=elapsed<.26?smooth(elapsed/.26):elapsed<.48?1:1-smooth((elapsed-.48)/.57);
    if(kind==='nod')value.nod=envelope(elapsed,duration);
    if(kind==='wave')value.wave=envelope(elapsed,duration)*Math.sin(elapsed/duration*Math.PI*2);
    if(kind==='lift')value.wave=envelope(elapsed,duration)*.92;
    if(kind==='tail')value.tail=envelope(elapsed,duration)*Math.sin(elapsed/duration*Math.PI*2.2);
    // Small palm arc, rather than fabricated individual fingers.
    if(kind==='brush')value.wave=.32*envelope(elapsed,duration)*Math.sin(elapsed/duration*Math.PI*2);
    if(kind==='fin')value.fin=.28*envelope(elapsed,duration);
    if(kind==='tailBrush'){value.tail=sample('tail',elapsed).tail*.72;value.wave=sample('brush',elapsed-7).wave;value.nod=.10*envelope(elapsed-3.2,3.2);}
    if(kind==='respond'){value.fin=.20*envelope(elapsed,2.8);value.wink=sample('wink',elapsed-1.7).wink;}
    return value;
  }
  function automatic(time,tailSpeed=1){const phase=((time%24)+24)%24;let value={blink:0,wink:0,nod:0,wave:0,tail:0};
    // Keep the original painted eyes in ambient motion; eyelid approximation is manual only.
    value.nod=sample('nod',phase-5).nod*.8;value.wave=sample('wave',phase-12).wave*.9;
    const cycle=Math.floor(time/32),tailPhase=time-cycle*32,start=3+(cycle%3)*1.2;
    value.tail=sample('tail',(tailPhase-start)*tailSpeed*(1+(cycle%3-1)*.07)).tail*(.72+(cycle%3)*.08);return value;}
  // Cross-fade the whole action state when clicked again: no reset at the hand or head.
  function blend(from,to,elapsed){const t=smooth(elapsed/.45);return Object.fromEntries(['blink','wink','nod','wave','tail'].map(key=>[key,(from[key]||0)*(1-t)+(to[key]||0)*t]));}
  // Position AND velocity survive interruptions. Exact critically damped step
  // avoids a reset on repeated clicks, completion or automatic/manual handoff.
  class Controller {
    constructor(random=Math.random){this.value={blink:0,wink:0,nod:0,wave:0,tail:0};this.velocity={nod:0,wave:0,tail:0};this.manual={};this.auto=true;this.time=null;this.wrist=0;this.wristVelocity=0;this.smile=0;this.tailFin=0;this.tailFinVelocity=0;this.tailSpeed=1;this.tailAmplitude=.75;this.random=random;this.nextAuto=null;this.cooldowns={};this.autoOwned=new Set();this.settings={preset:'quiet',waitMin:20,waitMax:45,enabled:{tail:true,brush:true,fin:true,drift:true,respond:true}};this.driftGain=1;this.lastAutoKind=null;}
    configureTail(amplitude,speed){this.tailAmplitude=Math.max(0,Math.min(1,amplitude));this.tailSpeed=Math.max(5.2/6,Math.min(1.3,speed));}
    configureWater(settings){this.settings={...this.settings,...settings,enabled:{...this.settings.enabled,...settings.enabled}};for(const kind of Object.keys(this.manual))if(!this.allowed(kind))delete this.manual[kind];}
    allowed(kind){const e=this.settings.enabled;return kind==='tailBrush'?e.tail&&e.brush:kind==='wave'||kind==='lift'?e.brush:e[kind]!==false;}
    trigger(kind,time,automatic=false){if(!(kind in lengths)||!this.allowed(kind))return false;
      if(kind==='respond'&&(this.manual.respond!==undefined||time<(this.cooldowns.respond||0)))return false;
      const body=['tail','fin','brush','wave','lift','tailBrush','respond'];
      if(body.includes(kind)){for(const k of body){delete this.manual[k];this.autoOwned.delete(k);}}
      if(['blink','wink','respond'].includes(kind)){delete this.manual.blink;delete this.manual.wink;}
      this.manual[kind]=time;if(automatic)this.autoOwned.add(kind);else this.autoOwned.delete(kind);
      this.cooldowns[kind]=time+lengths[kind]+(kind==='respond'?2:kind==='blink'?8:10);
      if(kind==='respond')this.autoRespondAfter=time+90;
      this.nextAuto=time+lengths[kind]+this.wait();return true;}
    wait(){return this.settings.waitMin+this.random()*(this.settings.waitMax-this.settings.waitMin);}
    setAutomatic(value){if(this.auto===!!value)return;this.auto=!!value;this.nextAuto=null;if(!this.auto){for(const kind of this.autoOwned)delete this.manual[kind];this.autoOwned.clear();}}
    suspend(){this.manual={};this.autoOwned.clear();this.nextAuto=null;}
    schedule(time){if(!this.auto)return;if(this.nextAuto===null)this.nextAuto=time+this.wait();if(time<this.nextAuto||Object.keys(this.manual).length)return;
      const pool=this.settings.preset==='quiet'?['fin','blink','fin']:['tail','brush','fin','tailBrush','blink','fin','respond'];
      const choices=pool.filter(k=>this.allowed(k)&&k!==this.lastAutoKind&&time>=(this.cooldowns[k]||0)&&(k!=='respond'||time>=(this.autoRespondAfter||0)));
      const kind=choices[Math.floor(this.random()*choices.length)];this.nextAuto=time+this.wait();if(kind){this.trigger(kind,time,true);this.lastAutoKind=kind;}}
    update(time){const dt=this.time===null?0:Math.max(0,Math.min(.12,time-this.time));this.time=time;
      if(dt===0)return {...this.value};
      this.schedule(time);const target={blink:0,wink:0,nod:0,wave:0,tail:0,fin:0};
      for(const kind of Object.keys(this.manual)){const age=(time-this.manual[kind])*(kind==='tail'?this.tailSpeed:1);if(age<lengths[kind]){const pose=sample(kind,age),cap=this.autoOwned.has(kind)?.65:1;for(const key of Object.keys(target))target[key]=Math.max(-1,Math.min(1,target[key]+pose[key]*cap));}else{delete this.manual[kind];this.autoOwned.delete(kind);}}
      target.tail*=this.tailAmplitude;
      // Retain velocities on interruption but wait for the other region to relax.
      if(Math.abs(this.value.tail)>.06)target.wave*=1-smooth((Math.abs(this.value.tail)-.06)/.12);
      if(Math.abs(this.value.wave)>.08)target.tail*=1-smooth((Math.abs(this.value.wave)-.08)/.15);
      for(const eye of ['blink','wink'])this.value[eye]+=(target[eye]-this.value[eye])*(1-Math.exp(-dt*24));
      for(const kind of ['nod','wave','tail']){const omega=kind==='tail'?4:kind==='wave'?3.5:6,delta=this.value[kind]-target[kind],v=this.velocity[kind],decay=Math.exp(-omega*dt),c=v+omega*delta;
        this.value[kind]=target[kind]+(delta+c*dt)*decay;this.velocity[kind]=(v-omega*c*dt)*decay;}
      // Wrist trails forearm and relaxes after it, rather than a single rigid
      // rotation. Counter-bend keeps fingertips inside the water corridor.
      const wristTarget=-.065*this.value.wave,omega=4.5,delta=this.wrist-wristTarget,c=this.wristVelocity+omega*delta,decay=Math.exp(-omega*dt);
      this.wrist=wristTarget+(delta+c*dt)*decay;this.wristVelocity=(this.wristVelocity-omega*c*dt)*decay;
      this.smile+=(this.value.wink*.42-this.smile)*(1-Math.exp(-dt*7));
      this.driftGain+=((this.settings.enabled.drift?1:0)-this.driftGain)*(1-Math.exp(-dt*3));
      const finTarget=Math.max(-1,Math.min(1,this.value.tail+target.fin)),finOmega=3.5,finDelta=this.tailFin-finTarget,finC=this.tailFinVelocity+finOmega*finDelta,finDecay=Math.exp(-finOmega*dt);
      this.tailFin=finTarget+(finDelta+finC*dt)*finDecay;this.tailFinVelocity=(this.tailFinVelocity-finOmega*finC*dt)*finDecay;
      return {...this.value};}
  }
  root.CharacterActions={lengths,sample,automatic,blend,Controller,smooth,armRig,armAngle,wristAngle,tailRig,tailDisplacement};
})(typeof window!=='undefined'?window:globalThis);
