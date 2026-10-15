import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,dirname,basename} from 'node:path';
import {Readable} from 'node:stream';
import {defaultPersona,readPersona,savePersona,formatPersona,personaSettingsHandler} from './persona.mjs';
import {toGemini} from './vertex-batch/wire.mjs';
import {batchPolicy} from './vertex-batch/batch-policy.mjs';
async function fixture(fn){const root=await mkdtemp(join(tmpdir(),'vbs-persona-'));try{await fn(root);}finally{
  const target=resolve(root);if(dirname(target)!==resolve(tmpdir())||!basename(target).startsWith('vbs-persona-'))throw Error('Unexpected fixture');await rm(target,{recursive:true,force:true});}}
async function call(handler,{method='GET',origin,body=''}={}){const req=Readable.from([body]);Object.assign(req,{method,headers:{origin},socket:{localPort:4567}});
  const res={writeHead(code,headers){this.code=code;this.headers=headers;},end(body){this.body=body;}};await handler(req,res);return res;}
test('custom Unicode persona survives a fresh read and reset persists the default',()=>fixture(async home=>{
 assert.equal((await readPersona(home)).text,defaultPersona);
 const text='请用中文回答，优先给完整内容。\n保留我的换行。';await savePersona(text,home);assert.equal((await readPersona(home)).text,text);
 await savePersona(defaultPersona,home);assert.equal(JSON.parse(await readFile(join(home,'vbs-persona.json'),'utf8')).text,defaultPersona);
}));
test('POST requires authenticated same-origin access and does not mutate on rejection',()=>fixture(async home=>{
 const handler=personaSettingsHandler({home,authorize:()=>true});
 const bad=await call(handler,{method:'POST',origin:'http://evil.invalid',body:JSON.stringify({text:'bad'})});assert.equal(bad.code,403);
 assert.equal((await readPersona(home)).text,defaultPersona);
 const denied=personaSettingsHandler({home,authorize:(_req,res)=>{res.writeHead(401);res.end();return false;}});
 assert.equal((await call(denied)).code,401);
}));
test('empty, oversized, malformed and ambiguous writes are rejected; save and reset work',()=>fixture(async home=>{
 const handler=personaSettingsHandler({home,authorize:()=>true}),origin='http://127.0.0.1:4567';
 for(const body of ['bad',JSON.stringify({text:'  '}),JSON.stringify({text:'x'.repeat(16001)}),JSON.stringify({reset:true,text:'x'}),JSON.stringify({reset:false})])assert.equal((await call(handler,{method:'POST',origin,body})).code,400);
 assert.equal((await call(handler,{method:'POST',origin,body:JSON.stringify({text:'My role'})})).code,200);
 assert.equal((await readPersona(home)).text,'My role');
 assert.equal((await call(handler,{method:'POST',origin,body:JSON.stringify({reset:true})})).code,200);
 assert.equal((await readPersona(home)).text,defaultPersona);
}));
test('a corrupt saved persona is reported instead of silently overwriting it',()=>fixture(async home=>{
 await writeFile(join(home,'vbs-persona.json'),'broken','utf8');await assert.rejects(readPersona(home));
 const result=await call(personaSettingsHandler({home,authorize:()=>true}));assert.equal(result.code,500);assert.equal(await readFile(join(home,'vbs-persona.json'),'utf8'),'broken');
}));
test('persona is frozen in system instructions before Batch rules without altering the user prompt',async()=>{
 const request=await toGemini({system:'DSH default',personaInstructions:formatPersona('Use Chinese. Model: {{model}}',{id:'gemini-4-argon'}),batchInstructions:batchPolicy(),messages:[{role:'user',content:[{type:'text',text:'Original prompt'}]}]});
 const instructions=request.systemInstruction.parts[0].text;assert.ok(instructions.includes('Use Chinese. Model: gemini-4-argon'));
 assert.ok(instructions.indexOf('Use Chinese.')<instructions.indexOf('Vertex Studio Batch'));
 assert.equal(request.contents[0].parts[0].text,'Original prompt');
 assert.ok(instructions.includes('read_image'));
});
