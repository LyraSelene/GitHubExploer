const assert=require('assert');require('../static/actions.js');
const A=CharacterActions,c=new A.Controller();c.setAutomatic(false);c.configureTail(1,1);c.update(0);c.trigger('tail',0);
let previous=0,positive=0,negative=0,lag=0;
for(let i=1;i<=600;i++){const t=i/60,v=c.update(t);assert(Number.isFinite(v.tail));assert(Math.abs(v.tail-previous)<.06);previous=v.tail;positive=Math.max(positive,v.tail);negative=Math.min(negative,v.tail);lag=Math.max(lag,Math.abs(v.tail-c.tailFin));assert.deepEqual(A.tailDisplacement(1810,v.tail,c.tailFin,1),[0,0]);}
assert(positive>.2&&negative<-.2&&lag>.1);assert(Math.abs(c.value.tail)<.002&&Math.abs(c.tailFin)<.003);
for(let i=601;i<1500;i++){const t=i/60;if(i%31===0)c.trigger('tail',t);const old=c.value.tail,vel=c.velocity.tail;c.update(t);assert(Math.abs(c.value.tail-old)<.08);assert(Math.abs(c.velocity.tail-vel)<.5);}
const state=JSON.stringify([c.value,c.velocity,c.tailFin]);c.update(c.time);assert.equal(JSON.stringify([c.value,c.velocity,c.tailFin]),state);
assert.equal(A.sample('tail',-1).tail,0);assert.equal(A.sample('tail',5.2).tail,0);
assert.equal(A.automatic(18).tail,0);assert.equal(A.automatic(18).wink,0);
console.log(JSON.stringify({positive,negative,lag,passed:true}));
