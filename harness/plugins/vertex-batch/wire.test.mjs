import {test} from 'node:test';
import assert from 'node:assert/strict';
import {toGemini,responseChunks} from './wire.mjs';
test('native function response preserves signed assistant content',async () => {
  const content={role:'model',parts:[{functionCall:{id:'native-call-id',name:'read',args:{file_path:'test.txt'}},thoughtSignature:'signed-value'}]};
  const options={messages:[{role:'assistant',content:[{type:'tool-call',id:'c',name:'read',arguments:'{"file_path":"test.txt"}'}],source:{replayState:{response:{geminiContent:content}}}},{role:'tool',source:{callId:'c'},content:[{type:'text',text:'hello'}]}],tools:[],reasoningEffort:'high'};
  const request=await toGemini(options);
  assert.deepEqual(request.contents[0],content);
  assert.equal(request.contents[1].parts[0].functionResponse.name,'read');
  assert.equal(request.contents[1].parts[0].functionResponse.id,'native-call-id');
  assert.equal(request.generationConfig.thinkingConfig.thinkingLevel,'HIGH');
  assert.equal(request.generationConfig.temperature,undefined);
});
test('truncated response never emits actionable tool chunks',() => {
  assert.equal(responseChunks({candidates:[{finishReason:'MAX_TOKENS',content:{parts:[{functionCall:{name:'write',args:{}}}]}}]},'x').some(chunk=>chunk.type==='tool-call-delta'),false);
});
test('a thinking-only response does not pretend to be a final answer',()=>{
  assert.throws(()=>responseChunks({candidates:[{finishReason:'STOP',content:{parts:[{text:'summary only',thought:true}]}}]},'x'));
});
test('tool ids and token accounting remain stable',() => {
  const response={candidates:[{finishReason:'STOP',content:{role:'model',parts:[{text:'summary',thought:true},{functionCall:{name:'read',args:{file_path:'中.txt'}}}]}}],usageMetadata:{promptTokenCount:20,cachedContentTokenCount:5,candidatesTokenCount:3,thoughtsTokenCount:4,totalTokenCount:27}};
  const chunks=responseChunks(response,'id');
  assert.equal(chunks.find(c => c.type === 'tool-call-delta').id,'id-1');
  assert.deepEqual(chunks.find(c => c.type === 'usage').usage,{inputTokens:15,outputTokens:7,cacheReadTokens:5,totalTokens:27});
  assert.deepEqual(chunks.at(-1).replayState.response.geminiContent,response.candidates[0].content);
});


test('Batch declares typed parameters for writable tool schemas',async()=>{
  const {toParameters}=await import('./schema.mjs');
  const parameters={type:'object',properties:{file_path:{type:'string'},limit:{type:'number'}},required:['file_path']};
  const request=await toGemini({messages:[{role:'user',content:[{type:'text',text:'hello'}]}],tools:[{name:'read',description:'read file',parameters}]});
  const declaration=request.tools[0].functionDeclarations[0];
  assert.equal(declaration.parametersJsonSchema,undefined);
  assert.deepEqual(declaration.parameters,{type:'OBJECT',properties:{file_path:{type:'STRING'},limit:{type:'NUMBER'}},required:['file_path']});
  assert.equal(parameters.type,'object');
  assert.deepEqual(toParameters({type:'object',additionalProperties:false}),{type:'OBJECT',additionalProperties:false});
  assert.throws(()=>toParameters({type:'object',properties:{broken:null}}));
});

test('optional permission nulls are omitted for execution while signed replay is preserved',async()=>{
  const tools=[{name:'write',parameters:{type:'object',properties:{file_path:{type:'string'},content:{type:'string'},sandbox_permissions:{type:'string'},justification:{type:'string'}},required:['file_path','content']}}];
  const raw={role:'model',parts:[{functionCall:{id:'w1',name:'write',args:{file_path:'x.md',content:'complete file',sandbox_permissions:null,justification:null}},thoughtSignature:'original-signature'}]};
  const response={candidates:[{finishReason:'STOP',content:raw}]};
  const before=JSON.stringify(response);
  const chunks=responseChunks(response,'req',tools);
  const block=chunks.find(c=>c.type==='block-end').block;
  assert.deepEqual(JSON.parse(block.arguments),{file_path:'x.md',content:'complete file'});
  assert.equal(JSON.stringify(response),before);
  const replayState=chunks.at(-1).replayState;
  assert.deepEqual(replayState.response.geminiContent,raw);
  const request=await toGemini({messages:[{role:'assistant',content:[block],source:{replayState}},{role:'tool',source:{callId:'w1'},content:[{type:'text',text:'Created file'}]}]});
  assert.deepEqual(request.contents[0],raw);
  assert.equal(request.contents[1].parts[0].functionResponse.id,'w1');
});

test('permission normalization cannot drop real escalation, invalid types, required or unknown fields',async()=>{
  const {executionArguments}=await import('./tool-arguments.mjs');
  const schema={type:'object',properties:{sandbox_permissions:{type:'string'},justification:{type:'string'}}};
  const escalation={sandbox_permissions:'danger-full-access',justification:'needs approval'};
  assert.strictEqual(executionArguments(escalation,schema),escalation);
  const invalid={sandbox_permissions:123,justification:false};
  assert.strictEqual(executionArguments(invalid,schema),invalid);
  const args={sandbox_permissions:null,justification:null,content:null,other:null};
  assert.strictEqual(executionArguments(args,undefined),args);
  assert.strictEqual(executionArguments(args,{type:'object'}),args);
  assert.deepEqual(executionArguments(args,{...schema,required:['sandbox_permissions']}),{sandbox_permissions:null,content:null,other:null});
  assert.deepEqual(executionArguments(args,{properties:{...schema.properties,justification:{type:'string',nullable:true}}}),{justification:null,content:null,other:null});
});

test('heterogeneous Batch tool args can only discard proven unknown null/empty-list padding',()=>{
  const tools=[{name:'write',parameters:{type:'object',properties:{content:{type:'string'}},required:['content'],additionalProperties:false}},
    {name:'present',parameters:{type:'object',properties:{files:{type:'array'}},required:['files'],additionalProperties:false}},
    {name:'batch_finish',parameters:{type:'object',properties:{summary:{type:'string'}},required:['summary'],additionalProperties:false}}];
  const raw={role:'model',parts:[{functionCall:{name:'write',args:{content:'full file',files:[],summary:null}}},
    {functionCall:{name:'present',args:{files:[{path:'x'}],content:null,summary:null}}},
    {functionCall:{name:'batch_finish',args:{summary:'done',content:null,files:[],unknown:null}}}]};
  const chunks=responseChunks({candidates:[{finishReason:'STOP',content:raw}]},'id',tools);
  const args=chunks.filter(c=>c.type==='block-end').map(c=>JSON.parse(c.block.arguments));
  assert.deepEqual(args,[{content:'full file'},{files:[{path:'x'}]},{summary:'done',unknown:null}]);
  assert.deepEqual(chunks.at(-1).replayState.response.geminiContent,raw);
});

test('cloud truncation is identified without promising that local unlimited mode removes provider limits',()=>{
  const chunks=responseChunks({candidates:[{finishReason:'MAX_TOKENS',content:{parts:[{functionCall:{name:'write',args:{content:'partial'}}}]}}]},'req');
  const text=chunks.filter(c=>c.type==='text-delta').map(c=>c.text).join('');
  assert.match(text,/云端返回 MAX_TOKENS/);
  assert.match(text,/限额关闭也不能取消云端/);
  assert.match(text,/没有返回可用续传令牌/);
  assert.ok(!text.includes('private-resume-token'));
  assert.ok(!chunks.some(c=>c.type==='tool-call-delta'));
});

test('buffered native continuation cannot leak tools or text through the adapter',()=>{
  for(const finishReason of ['MAX_TOKENS','CONTINUATION'])assert.throws(()=>responseChunks({candidates:[{finishReason,continuationToken:'private',content:{parts:[{text:'partial'},{functionCall:{name:'write',args:{content:'partial'}}}]}}]},'req'));
});
