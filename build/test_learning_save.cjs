const fs=require('fs'),assert=require('assert');
const source=fs.readFileSync('static/learning-flow.js','utf8');
const start=source.indexOf('async function flush()'),end=source.indexOf(' function renderProject',start);
const implementation=source.slice(start,end);
async function scenario(){
 let dirty=new Map([['1:0',{index:0}],['1:1',{index:1}]]),saveTimer=null,saving=Promise.resolve(),fail=true,calls=[],snapshots=[];
 const document={querySelector:()=>null};
 async function api(action,body){if(action==='learning_drafts'){snapshots.push(body.entries);return;}calls.push(body.index);if(fail){fail=false;throw Error('network fixture');}}
 const flush=eval('('+implementation+')');
 await assert.rejects(flush);assert.equal(dirty.size,2,'Failure must retain all entries');
 await flush();assert.equal(dirty.size,0);assert.deepEqual(calls,[0,0,1]);assert.equal(snapshots[0].length,2);
 const old={index:0,notes:'old'},newer={index:0,notes:'new'};dirty.set('1:0',old);
 api=async(action,body)=>{if(action==='progress'){calls.push(body.notes);if(body===old)dirty.set('1:0',newer);}};
 await flush();assert.equal(dirty.size,0);assert.deepEqual(calls.slice(-2),['old','new']);
 console.log('save queue: failure retention, retry and concurrent edit passed');
}
scenario().catch(e=>{console.error(e);process.exit(1)});
