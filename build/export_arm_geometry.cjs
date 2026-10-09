require('../static/actions.js');
const {armRig,armAngle,wristAngle}=CharacterActions;
require('node:fs').writeFileSync(require('node:path').join(__dirname,'arm-geometry.json'),JSON.stringify({rig:armRig,poses:Array.from({length:41},(_,i)=>armAngle(-1+i/20,1)).flatMap(arm=>[-.065,0,.065].map(w=>({arm,wrist:wristAngle(w,1,arm)})))}));
