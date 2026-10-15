import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

function renderActivity(data) {
  let plugin,Activity,index=0;
  const states=[data,'',true];
  const react={useState:()=>[states[index++],()=>{}],useEffect:()=>{},
    createElement:(type,props,...children)=>({type,props,children})};
  vm.runInNewContext(readFileSync('harness/plugins/studio-theme/client.js','utf8'),{
    window:{__ModuleLoader__:{load({factory}){plugin=factory(()=>react);}}},Date,AbortController,
  });
  plugin.apply({effect:()=>{},theme:{},slots:{inject:(_,fn)=>fn(),register:(meta,fn)=>{if(meta.id==='vertex-batch-activity')Activity=fn;}}});
  const tree=Activity({session:{sessionId:'s'}});
  function text(node){if(!node)return '';if(Array.isArray(node))return node.map(text).join(' ');if(typeof node==='object')return text(node.children);return String(node);}
  return text(tree);
}
const receipt=(overrides={})=>({session_id:'s',run_id:'run',phase:'completed',actual_usd:0,reserved_usd:0,created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:01:00Z',budget_usd:5,...overrides});
test('usage estimates and live reservations have explicit distinct labels; other sessions and turns excluded',()=>{
  const text=renderActivity({requests:[receipt({session_id:'other',actual_usd:100}),receipt({run_id:'previous',actual_usd:50}),receipt({actual_usd:.25,cost_estimate:{promotional_estimated_usd:.125}}),receipt({phase:'running',reserved_usd:6.732838})]});
  assert.match(text,/估算 \$0\.250 · 预留 \$6\.733/);
  assert.doesNotMatch(text,/50\.000|100\.000/);
  assert.match(text,/不代表已扣费/);
  assert.match(text,/返还规则估算 \$0\.125/);
});
test('a finished request without usage is unresolved, not a paid or ongoing reservation',()=>{
  const text=renderActivity({requests:[receipt({phase:'failed',reserved_usd:.83434})]});
  assert.match(text,/估算 \$0\.000 · 预留 \$0\.000 · 待核对 \$0\.834/);
});

test('recovered original answer is visible with an honest historical failure notice',()=>{
  const text=renderActivity({requests:[receipt({local_recovery:{text:'Original final answer'}})]});
  assert.match(text,/已找回本轮收尾答复/);
  assert.match(text,/Original final answer/);
  assert.match(text,/未重新提交，也未重跑工具/);
  assert.match(text,/保留原失败记录/);
});

test('native continuation shows progress without pretending the model turn is complete',()=>{
  const text=renderActivity({requests:[receipt({phase:'queued',submission_intent:true,continuation:{state:'buffering',buffered_segments:2,segment_index:2,generated_tokens:65536,submitted_jobs:3}})]});
  assert.match(text,/正在续传 · 第 3 批 · 云端排队/);
  assert.match(text,/已保存 2 段/);
  assert.match(text,/3 \/ 20 次请求/);
  assert.match(text,/完整结束前不执行工具/);
});
