import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,symlink,rm} from 'node:fs/promises';
import {join,resolve,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';
import {batchPolicy,batchPolicyVersion} from './batch-policy.mjs';
import {workspaceOverview} from './workspace-overview.mjs';
import {toGemini,responseChunks} from './wire.mjs';

async function removeFixture(root) {
  const target=resolve(root),parent=resolve(tmpdir());
  if(dirname(target)!==parent || !basename(target).startsWith('vbs-'))throw Error('Refusing cleanup outside this test fixture');
  await rm(target,{recursive:true,force:true});
}

test('Batch instructions stay in systemInstruction and preserve original instructions and user content',async()=>{
  const prompt=batchPolicy();
  const options={system:'Follow the project rules.',batchInstructions:prompt,batchContext:'README.md',messages:[{role:'developer',content:[{type:'text',text:'Keep the existing behavior.'}]},{role:'user',content:[{type:'text',text:'Write the complete document.'}]}]};
  const request=await toGemini(options);
  const system=request.systemInstruction.parts[0].text;
  assert.ok(system.includes('Follow the project rules.'));
  assert.ok(system.includes('Keep the existing behavior.'));
  assert.ok(system.endsWith(prompt));
  assert.ok(system.includes(batchPolicyVersion));
  assert.ok(system.includes('当前会话为仅查看模式'));
  assert.ok(!batchPolicy({readOnly:false}).includes('当前会话为仅查看模式'));
  assert.ok(!system.includes('README.md'));
  assert.equal(request.contents[0].parts[0].text,'README.md');
  assert.equal(request.contents[0].role,'user');
  assert.equal(request.contents[1].parts[0].text,'Write the complete document.');
  assert.equal(options.system,'Follow the project rules.');
});
test('filename overview excludes credentials, dependencies and links, and never includes file bytes',async()=>{
  const root=await mkdtemp(join(tmpdir(),'vbs-overview-'));
  const outside=await mkdtemp(join(tmpdir(),'vbs-external-'));
  try {
    await mkdir(join(root,'src'));
    await writeFile(join(root,'src','main.py'),'private-content-marker');
    await writeFile(join(root,'key.json'),'credential-marker');
    await writeFile(join(root,'.env'),'credential-marker');
    await mkdir(join(root,'secrets'));await writeFile(join(root,'secrets','downloaded.json'),'credential-marker');
    await mkdir(join(root,'node_modules'));await writeFile(join(root,'node_modules','large.js'),'dependency');
    await writeFile(join(outside,'outside.txt'),'outside-marker');
    await symlink(outside,join(root,'external'),process.platform==='win32'?'junction':'dir');
    const result=await workspaceOverview(root);
    assert.ok(result.entries.includes('src/main.py'));
    for(const value of ['private-content-marker','credential-marker','outside-marker','key.json','.env','node_modules','external'])assert.ok(!result.text.includes(value),value);
  } finally {
    // Exact temporary roots created above; no workspace paths are removed.
    await removeFixture(root);await removeFixture(outside);
  }
});
test('large or unavailable directories produce bounded context rather than blocking a text response',async()=>{
  const root=await mkdtemp(join(tmpdir(),'vbs-overview-limit-'));
  try {
    for(let i=0;i<8;i++)await writeFile(join(root,`file-${i}.txt`),'');
    const result=await workspaceOverview(root,{maxEntries:3});
    assert.equal(result.entries.length,3);assert.equal(result.truncated,true);
    assert.ok(result.text.includes('未列出的文件不代表不存在'));
    const unavailable=await workspaceOverview(join(root,'missing'));
    assert.equal(unavailable.unreadable,true);
  } finally {await removeFixture(root);}
});
test('depth limit does not hide siblings that are within the same bounded listing',async()=>{
  const root=await mkdtemp(join(tmpdir(),'vbs-overview-depth-'));
  try {
    await mkdir(join(root,'aaa','nested'),{recursive:true});
    await writeFile(join(root,'aaa','nested','deep.txt'),'');
    await writeFile(join(root,'b.txt'),'');
    const result=await workspaceOverview(root,{maxDepth:2});
    assert.ok(result.entries.includes('b.txt'));
    assert.ok(result.entries.includes('aaa/nested/'));
    assert.ok(!result.entries.includes('aaa/nested/deep.txt'));
    assert.equal(result.truncated,true);
  } finally {await removeFixture(root);}
});
test('full content plus grouped independent calls retain order, signatures and both tool results',async()=>{
  const content={role:'model',parts:[{text:'Complete draft and the required reads.'},{functionCall:{id:'first',name:'read',args:{file_path:'a.md'}},thoughtSignature:'signature-1'},{functionCall:{id:'second',name:'read',args:{file_path:'b.md'}}}]};
  const chunks=responseChunks({candidates:[{finishReason:'STOP',content}]},'request');
  const blocks=chunks.filter(c=>c.type==='block-end').map(c=>c.block);
  assert.deepEqual(blocks.map(b=>b.type),['text','tool-call','tool-call']);
  const replayState=chunks.at(-1).replayState;
  const request=await toGemini({messages:[{role:'assistant',content:blocks,source:{replayState}},{role:'tool',source:{callId:'first'},content:[{type:'text',text:'A'}]},{role:'tool',source:{callId:'second'},content:[{type:'text',text:'B'}]}]});
  assert.deepEqual(request.contents[0],content);
  assert.equal(request.contents[1].parts[0].functionResponse.id,'first');
  assert.equal(request.contents.length,2);
  assert.equal(request.contents[1].parts.length,2);
  assert.equal(request.contents[1].parts[1].functionResponse.id,'second');
});

test('first request receives selected output root and deeper bounded paths without reading bodies',async()=>{
  const root=await mkdtemp(join(tmpdir(),'vbs-overview-oneshot-'));
  try {
    await mkdir(join(root,'src','ui','parts'),{recursive:true});
    await writeFile(join(root,'src','ui','parts','panel.tsx'),'never-send-file-body');
    const result=await workspaceOverview(root);
    assert.ok(result.entries.includes('src/ui/parts/panel.tsx'));
    const data=JSON.parse(result.text.split('\n')[1]);
    assert.equal(data.workspace,resolve(root));
    assert.equal(data.defaultOutputDirectory,resolve(root));
    assert.equal(data.coverage.rootAccessible,true);
    assert.equal(data.coverage.maxDepth,4);
    assert.equal(data.coverage.truncated,false);
    assert.ok(!result.text.includes('never-send-file-body'));
    const unavailable=await workspaceOverview(join(root,'missing'));
    assert.equal(unavailable.rootAccessible,false);
  } finally {await removeFixture(root);}
});
