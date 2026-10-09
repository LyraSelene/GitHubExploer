const assert=require('node:assert/strict');
require('../static/actions.js');
const {sample,automatic,lengths,blend}=globalThis.CharacterActions;
for(const kind of Object.keys(lengths)){
  for(const time of [-1,0,lengths[kind],lengths[kind]+1])assert.deepEqual(sample(kind,time),{blink:0,wink:0,nod:0,wave:0});
  for(let time=0;time<lengths[kind];time+=.01){const value=sample(kind,time);assert(value.blink>=0&&value.blink<=1);assert(Math.abs(value.nod)<=1);assert(Math.abs(value.wave)<=1);}
}
assert.equal(sample('blink',.25).blink,1);
assert(sample('wave',.7).wave!==0);
assert(sample('nod',.7).nod!==0);
assert.deepEqual(automatic(0),automatic(24));
const active={blink:.5,wink:0,nod:.6,wave:-.4},neutral={blink:0,wink:0,nod:0,wave:0};
assert.deepEqual(blend(active,neutral,0),active);
assert.deepEqual(blend(active,neutral,.45),neutral);
assert(Math.abs(blend(active,neutral,.001).wave-active.wave)<.000001);
assert(sample('wave',.001).wave<.000001);
assert.deepEqual(sample('unknown',1),{blink:0,wink:0,nod:0,wave:0});
assert.deepEqual(sample('blink',NaN),{blink:0,wink:0,nod:0,wave:0});
console.log('Action timing: start/end neutral, finite amplitudes, full blink, loop continuity passed.');
const controller=new CharacterActions.Controller();controller.setAutomatic(false);controller.update(0);controller.trigger('wave',0);
let previous=controller.update(0),maxWave=0;
for(let t=.016;t<8;t+=.016){if(t>1.5&&t<1.516){const value={...controller.value},velocity={...controller.velocity};controller.trigger('nod',t);assert.deepEqual(controller.value,value);assert.deepEqual(controller.velocity,velocity);}
  if(t>2&&t<2.016)controller.trigger('wave',t);
  const now=controller.update(t);assert(Math.abs(now.wave-previous.wave)<.025);assert(Math.abs(now.nod-previous.nod)<.025);maxWave=Math.max(maxWave,Math.abs(now.wave));previous=now;}
assert(maxWave>.5,'Movement retains visible amplitude');
const frozen=controller.update(8);assert.deepEqual(controller.update(8),frozen);
controller.setAutomatic(true);const before={...controller.value};assert.deepEqual(controller.update(8),before);
console.log('Interrupted/repeated actions preserve state and velocity; frame steps bounded; pause frozen.');
const lift=new CharacterActions.Controller();lift.setAutomatic(false);lift.update(0);lift.trigger('lift',0);
let liftPeak=0;
for(let t=.016;t<3.5;t+=.016){lift.update(t);liftPeak=Math.max(liftPeak,lift.value.wave);}
assert(liftPeak>.8,'Lift visibly raises the arm with a slower follow');const held={...lift.value},speed={...lift.velocity};lift.trigger('wave',3.5);
assert.deepEqual(lift.value,held);assert.deepEqual(lift.velocity,speed);assert(!('lift' in lift.manual),'New hand action replaces old target');
assert(Math.abs(lift.update(3.516).wave-held.wave)<.025);console.log('Lift peak and interrupted hand action continuity passed.');

assert.equal(sample('wink',.38).wink,1);assert.equal(sample('wink',.38).blink,0);assert(sample('blink',.4).blink>.8);assert(sample('blink',.65).blink<.1);console.log('Slow blink and single-eye wink timing passed.');
const eyes=new CharacterActions.Controller();eyes.setAutomatic(false);eyes.update(0);eyes.trigger('wink',0);
for(let t=.016;t<.4;t+=.016)eyes.update(t);
eyes.update(.4);const eyeBefore={...eyes.value};eyes.trigger('blink',.4);assert(!('wink' in eyes.manual));
assert.deepEqual(eyes.update(.4),eyeBefore);assert(Math.abs(eyes.update(.416).wink-eyeBefore.wink)<.4);
for(let t=.432;t<2;t+=.016)eyes.update(t);
assert(eyes.value.wink<.001&&eyes.value.blink<.001);console.log('Interrupted eye actions ease back without snapping.');
let lastAngle=CharacterActions.armAngle(-1,1);
for(let v=-.999;v<=1;v+=.001){const angle=CharacterActions.armAngle(v,1);assert(angle>=lastAngle);assert(angle>=-.160001&&angle<=.230001);lastAngle=angle;}
assert.equal(CharacterActions.armAngle(1,0),0);
// Switch hand targets every .7 seconds; check the renderer's actual angular
// velocity in addition to controller state continuity.
const repeated=new CharacterActions.Controller();repeated.setAutomatic(false);repeated.update(0);
let prev=0,peakSpeed=0;
for(let i=1;i<=1800;i++){let t=i/60;if(i%42===1)repeated.trigger(i%84===1?'lift':'wave',t);const angle=CharacterActions.armAngle(repeated.update(t).wave,1);peakSpeed=Math.max(peakSpeed,Math.abs(angle-prev)*60);prev=angle;}
assert(peakSpeed<.4,`Repeated actions turn too fast: ${peakSpeed}`);
console.log('Asymmetric arm bounds and 30-second repeated-action angular velocity passed.');
const flex=new CharacterActions.Controller();flex.setAutomatic(false);flex.update(0);flex.trigger('lift',0);
let wristPeak=0;
for(let i=1;i<300;i++){const prior=flex.wrist;flex.update(i/60);assert(Math.abs(flex.wrist-prior)<.005);wristPeak=Math.max(wristPeak,Math.abs(flex.wrist));const arm=CharacterActions.armAngle(flex.value.wave,1),wrist=CharacterActions.wristAngle(flex.wrist,1,arm);assert(arm+wrist>=-.16&&arm+wrist<=.23);}
assert(wristPeak>.04);const freeze={wrist:flex.wrist,velocity:flex.wristVelocity,smile:flex.smile};flex.update(299/60);assert.deepEqual({wrist:flex.wrist,velocity:flex.wristVelocity,smile:flex.smile},freeze);
flex.trigger('wink',5);let smilePeak=0;
for(let i=300;i<540;i++){flex.update(i/60);smilePeak=Math.max(smilePeak,flex.smile);}
assert(smilePeak>.7);assert(flex.smile<.001);
console.log('Delayed wrist movement, combined safe angles, paused secondary state, wink smile and return passed.');
