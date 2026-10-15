import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createBatchDelivery} from './batch-delivery.mjs';

const call=(id,name)=>({type:'block-end',block:{type:'tool-call',id,name,arguments:'{}'}});
function fixture(calls=[call('write','write'),call('finish','batch_finish')]) {
  const records=[],identity={runId:'run',turn:1,step:1,model:'gemini-4-argon'};
  const events=[{type:'step/start',seq:0,data:{turn:1,step:1}}];
  const agent={id:'s',session:{id:'s',snapshotEvents:()=>events,append(...args){records.push(args);events.push({type:args[0],data:args[1],seq:events.length});}}};
  const ids=new Map([['s',identity]]);
  const d=createBatchDelivery({},ids,args=>({role:'assistant',...args}));
  d.prepare(identity,[...calls,{type:'finish',reason:{kind:'tool-calls'}}],'s');
  let concluded=false;
  const exec={agent,callId:'finish',name:'batch_finish',signal:new AbortController().signal,concludeTurn(){concluded=true;}};
  const observe=(id,name,result)=>{
    d.observe({agent,callId:id,name},result);
    if(name==='batch_finish'){
      const event={type:'tool/result',seq:events.length,data:{turn:1,step:1,message:{toolCallId:id,isError:result.isError}}};
      events.push(event);d.committed(agent.session,event);
    }
  };
  return {d,agent,ids,identity,exec,records,events,observe,get concluded(){return concluded;}};
}
test('successful delivery concludes only after real results and appends one local final reply without token usage',async()=>{
  const f=fixture();f.observe('write','write',{isError:false,value:{path:'x.md'}});
  const value=await f.d.tool.execute({summary:'Full final reply'},f.exec);
  assert.equal(f.concluded,true);
  assert.equal(f.d.finalize(f.agent,1),false); // terminal result not committed yet
  f.observe('finish','batch_finish',{isError:false,value,concludesTurn:true});
  assert.equal(f.d.finalize(f.agent,1),true);
  assert.equal(f.d.finalize(f.agent,1),false);
  const [type,data,opts]=f.records[0];
  assert.equal(type,'assistant/message');assert.equal(data.step,1);
  assert.match(data.message.content[0].text,/本地交付已确认.*Full final reply/s);
  assert.equal(data.usage,undefined);assert.deepEqual(opts,{surfaceOp:'append'});
});
test('missing, failed or context-producing outcomes never conclude',async()=>{
  for(const outcome of [undefined,{isError:true},{isError:false,additionalContexts:[{}]}]){
    const f=fixture();if(outcome)f.observe('write','write',outcome);
    await assert.rejects(f.d.tool.execute({summary:'done'},f.exec));
    assert.equal(f.concluded,false);assert.equal(f.records.length,0);
  }
});
test('post-policy blocking and abort cannot turn into a successful local final reply',async()=>{
  const f=fixture();f.observe('write','write',{isError:false});
  await f.d.tool.execute({summary:'done'},f.exec);
  f.observe('finish','batch_finish',{isError:true});
  assert.equal(f.d.finalize(f.agent,1),false);
  const stop=new AbortController();stop.abort();
  await assert.rejects(f.d.tool.execute({summary:'done'},{...f.exec,signal:stop.signal}));
});
test('discovery, duplicate finish and non-final finish cannot stop the Agent loop',async()=>{
  for(const calls of [[call('read','read'),call('finish','batch_finish')],[call('finish','batch_finish'),call('write','write')],[call('write','write'),call('finish','batch_finish'),call('other','batch_finish')]]){
    const f=fixture(calls);f.observe('write','write',{isError:false});f.observe('read','read',{isError:false});
    await assert.rejects(f.d.tool.execute({summary:'done'},f.exec));assert.equal(f.concluded,false);
  }
});
test('commands must finish in foreground with zero exit code, without abort or timeout',async()=>{
  for(const value of [{kind:'background',exitCode:0},{kind:'foreground',exitCode:null},{kind:'foreground',exitCode:1},{kind:'foreground',exitCode:0,timedOut:true},{kind:'foreground',exitCode:0,aborted:true}]){
    const f=fixture([call('cmd','pwsh'),call('finish','batch_finish')]);
    f.observe('cmd','pwsh',{isError:false,value});
    await assert.rejects(f.d.tool.execute({summary:'done'},f.exec));assert.equal(f.concluded,false);
  }
  const f=fixture([call('cmd','pwsh'),call('finish','batch_finish')]);
  f.observe('cmd','pwsh',{isError:false,value:{kind:'foreground',exitCode:0,timedOut:false,aborted:false,signal:null}});
  await f.d.tool.execute({summary:'done'},f.exec);assert.equal(f.concluded,true);
});
test('turn, step and session identities isolate completion from stale tool events',async()=>{
  const f=fixture();
  f.d.observe({agent:{id:'other'},callId:'write',name:'write'},{isError:false});
  await assert.rejects(f.d.tool.execute({summary:'done'},f.exec));
  f.observe('write','write',{isError:false});
  const value=await f.d.tool.execute({summary:'done'},f.exec);
  f.observe('finish','batch_finish',{isError:false,value,concludesTurn:true});
  assert.equal(f.d.finalize(f.agent,2),false);
  f.d.clear(f.agent,2);assert.equal(f.d.finalize(f.agent,1),true);
});

test('dependent file cards are blocked when a preceding write failed',()=>{
  const f=fixture([call('write','write'),call('cards','present'),call('finish','batch_finish')]);
  assert.match(f.d.guard({agent:f.agent,callId:'cards',name:'present'}),/未成功/);
  f.observe('write','write',{isError:true});
  assert.match(f.d.guard({agent:f.agent,callId:'cards',name:'present'}),/未成功/);
  f.observe('write','write',{isError:false});
  assert.equal(f.d.guard({agent:f.agent,callId:'cards',name:'present'}),undefined);
});

test('terminal summary waits for publication and precedes step/end',async()=>{
  const f=fixture();f.observe('write','write',{isError:false});
  const value=await f.d.tool.execute({summary:'complete'},f.exec);
  f.observe('finish','batch_finish',{isError:false,value,concludesTurn:true});
  assert.equal(f.records.length,0); // no forbidden reentrant append
  await Promise.resolve();
  assert.equal(f.records.length,1);
  f.events.push({type:'step/end',data:{turn:1,step:1}});
  assert.equal(f.d.finalize(f.agent,1),false);
});
test('a late callback cannot corrupt a closed step or turn',async()=>{
  for(const type of ['step/end','turn/end']){
    const f=fixture();f.observe('write','write',{isError:false});
    const value=await f.d.tool.execute({summary:'complete'},f.exec);
    f.observe('finish','batch_finish',{isError:false,value,concludesTurn:true});
    f.events.push({type,data:{turn:1,step:1}});
    await Promise.resolve();
    assert.equal(f.records.length,0);
    assert.equal(f.d.finalize(f.agent,1),false);
  }
});
