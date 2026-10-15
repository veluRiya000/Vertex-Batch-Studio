import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {join,resolve,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';
import {modelProfiles,validateModelOutput} from '../model-profiles.mjs';
import {toGemini} from './wire.mjs';

test('all three models are selectable, and selection remains frozen only within one turn',async()=>{
 const home=await mkdtemp(join(tmpdir(),'vbs-models-'));
 const previous=process.env.DSH_HOME,offline=process.env.VBS_HARNESS_OFFLINE;
 process.env.DSH_HOME=home;process.env.VBS_HARNESS_OFFLINE='1';
 try {
  const {apply}=await import('./index.mjs');
  const hooks=new Map(),effects=[];let adapter;
  apply({sandboxPolicy:{resolve(){return {mode:'read-only',workspaceRoot:home};}},sandbox:{confine(){throw Error('Read-only preparation must not grant workspace writes');}},on(name,fn){hooks.set(name,fn);},effect(fn){effects.push(fn);},llm:{registerAdapter(_,value){adapter=value;}},logger:{warn(){}}});
  effects.at(-1)();
  assert.deepEqual((await adapter.listModels('vertex-batch')).map(m=>m.id),modelProfiles.map(m=>m.id));
  assert.equal((await adapter.resolveModel('vertex-batch','gemini-3.1-pro-preview')).reasoning.defaultEffort,'high');
  const agent={id:'test',session:{header:{cwd:home}}},prepare=hooks.get('agent/request');
  let config=await prepare({agent,turn:1,step:1},async()=>({model:'gemini-3.8-flash'}));
  assert.equal(config.model,'gemini-3.8-flash');
  config=await prepare({agent,turn:1,step:2},async()=>({model:'gemini-3.1-pro-preview'}));
  assert.equal(config.model,'gemini-3.8-flash');
  config=await prepare({agent,turn:2,step:1},async()=>({model:'gemini-3.1-pro-preview'}));
  assert.equal(config.model,'gemini-3.1-pro-preview');
  const chunks=[];
  for await(const c of adapter.stream({sessionId:agent.id,model:config.model,messages:[{role:'user',content:[{type:'text',text:'hello'}]}],tools:[]}))chunks.push(c);
  assert.ok(chunks.some(c=>c.type==='text-delta'));
 }finally{
  for(const [key,value] of [['DSH_HOME',previous],['VBS_HARNESS_OFFLINE',offline]])if(value===undefined)delete process.env[key];else process.env[key]=value;
  assert.equal(dirname(resolve(home)),resolve(tmpdir()));assert.ok(basename(home).startsWith('vbs-models-'));await rm(home,{recursive:true,force:true});
 }
});
test('documented model caps reject oversized requests without silent truncation',async()=>{
 assert.equal(validateModelOutput('gemini-4-argon',200000),200000);
 for(const model of ['gemini-3.8-flash','gemini-3.1-pro-preview']){
  assert.equal(validateModelOutput(model,65536),65536);
  await assert.rejects(toGemini({model,maxTokens:65537,messages:[{role:'user',content:[{type:'text',text:'hi'}]}]}),/65536/);
 }
});
test('foreign-model native thought signatures are not replayed into a different model',async()=>{
 const message={role:'assistant',source:{model:'gemini-4-argon',replayState:{response:{geminiContent:{role:'model',parts:[{text:'old answer',thoughtSignature:'foreign-signature'}]}}}},content:[{type:'text',text:'old answer'}]};
 const request=await toGemini({model:'gemini-3.8-flash',messages:[message,{role:'user',content:[{type:'text',text:'new question'}]}]});
 assert.ok(!JSON.stringify(request).includes('foreign-signature'));
 assert.equal(request.contents[0].parts[0].text,'old answer');
});
