import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp,rm} from 'node:fs/promises';
import {join,resolve,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';

test('DSH failure and normal finish use exact turn ID; broker errors are contained',async()=>{
 const home=await mkdtemp(join(tmpdir(),'vbs-lifecycle-'));
 const previousHome=process.env.DSH_HOME;process.env.DSH_HOME=home;
 const previousFetch=globalThis.fetch;
 const previousOffline=process.env.VBS_HARNESS_OFFLINE;
 const previousUrl=process.env.VBS_HARNESS_BROKER_URL;
 process.env.VBS_HARNESS_OFFLINE='0';process.env.VBS_HARNESS_BROKER_URL='http://127.0.0.1:1';
 try {
  const {apply}=await import('./index.mjs');
  const handlers=new Map(),warnings=[],calls=[];
  apply({effect(){},on(name,fn){handlers.set(name,fn);},logger:{warn(text){warnings.push(text);}}});
  globalThis.fetch=async(url,options)=>{calls.push({url,method:options.method,body:options.body});return {ok:true,async json(){return {phase:'paused'};}};};
  const agent={id:'test-session',session:{header:{cwd:process.cwd()}}};
  await handlers.get('agent/request')({agent,turn:99,step:1},async()=>({}));
  await handlers.get('agent/error')({agent,turn:3,step:1,error:Error('failed')});
  const digest=createHash('sha256').update('test-session:3').digest('hex');
  assert.equal(calls[0].url,`http://127.0.0.1:1/harness/runs/${digest}/finish`);
  assert.equal(calls[0].method,'POST');assert.equal(calls[0].body,'{}');
  await handlers.get('agent/turn-stopping')({agent,turn:4});
  assert.equal(calls.length,2);
  globalThis.fetch=async()=>{throw Error('broker offline');};
  await handlers.get('agent/error')({agent,turn:5});
  assert.deepEqual(warnings,['broker offline']);
 } finally {
  globalThis.fetch=previousFetch;
  if(previousHome===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=previousHome;
  assert.equal(dirname(resolve(home)),resolve(tmpdir()));assert.ok(basename(home).startsWith('vbs-lifecycle-'));await rm(home,{recursive:true,force:true});
  for(const [key,value] of [['VBS_HARNESS_OFFLINE',previousOffline],['VBS_HARNESS_BROKER_URL',previousUrl]])
   if(value===undefined)delete process.env[key];else process.env[key]=value;
 }
});
