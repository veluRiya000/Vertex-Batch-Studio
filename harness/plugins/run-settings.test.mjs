import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,dirname,basename} from 'node:path';
import {defaultRunSettings,readRunSettings,saveRunSettings,validateRunSettings,runSettingsHandler} from './run-settings.mjs';
import {toGemini,responseChunks} from './vertex-batch/wire.mjs';

test('new settings default to disabled limits; saved enabled limits and higher values are preserved',async()=>{
 const home=await mkdtemp(join(tmpdir(),'vbs-run-settings-'));
 try {
  assert.deepEqual(await readRunSettings(home),defaultRunSettings);
  assert.equal(defaultRunSettings.limitsEnabled,false);
  const value={maxOutputTokens:200000,budgetUsd:450,maxRounds:150,limitsEnabled:true};
  assert.deepEqual(await saveRunSettings(value,home),value);assert.deepEqual(await readRunSettings(home),value);
  const request=await toGemini({maxTokens:value.maxOutputTokens,messages:[{role:'user',content:[{type:'text',text:'write'}]}]});
  assert.equal(request.generationConfig.maxOutputTokens,200000);
  for(const bad of [{maxOutputTokens:0},{maxOutputTokens:1048577,limitsEnabled:true},{budgetUsd:Infinity},{maxRounds:1.5},{unknown:true}])assert.throws(()=>validateRunSettings(bad));
 } finally {
  assert.equal(dirname(resolve(home)),resolve(tmpdir()));assert.ok(basename(home).startsWith('vbs-run-settings-'));await rm(home,{recursive:true,force:true});
 }
});
test('settings endpoint checks auth, origin and invalid values',async()=>{
 const handler=runSettingsHandler({authorize:()=>false});
 const res={writeHead(){throw Error('must defer auth response');},end(){}};
 await handler({method:'GET'},res);
 let status;
 const secure=runSettingsHandler({authorize:()=>true});
 await secure({method:'POST',headers:{origin:'https://external.example'},socket:{localPort:12345}},{writeHead(code){status=code;},end(){}});
 assert.equal(status,403);
});
test('truncated body and usage are shown, function calls are never actionable and raw response stays intact',()=>{
 const response={candidates:[{finishReason:'MAX_TOKENS',content:{role:'model',parts:[{text:'partial document'},{functionCall:{name:'write',args:{content:'incomplete'}}}]}}],usageMetadata:{promptTokenCount:10,candidatesTokenCount:80,thoughtsTokenCount:20,totalTokenCount:110}};
 const original=JSON.stringify(response),chunks=responseChunks(response,'x');
 assert.ok(chunks.some(c=>c.type==='text-delta'&&c.text==='partial document'));
 assert.ok(!chunks.some(c=>c.type==='tool-call-delta'));
 assert.equal(chunks.at(-1).reason.kind,'max-tokens');
 assert.equal(chunks.find(c=>c.type==='usage').usage.outputTokens,100);
 assert.ok(!chunks.at(-1).replayState.response.geminiContent.parts.some(p=>p.functionCall));
 assert.equal(JSON.stringify(response),original);
});

test('disabled local limits persist and omit output caps without changing the thinking level',async()=>{
 const home=await mkdtemp(join(tmpdir(),'vbs-run-settings-'));
 try {
  const value={...defaultRunSettings,limitsEnabled:false,maxOutputTokens:2000000};
  await saveRunSettings(value,home);
  assert.equal((await readRunSettings(home)).limitsEnabled,false);
  const request=await toGemini({limitsEnabled:false,maxTokens:2000000,model:'gemini-3.8-flash',reasoningEffort:'high',messages:[{role:'user',content:[{type:'text',text:'write'}]}]});
  assert.equal(Object.hasOwn(request.generationConfig,'maxOutputTokens'),false);
  assert.equal(request.generationConfig.thinkingConfig.thinkingLevel,'HIGH');
 } finally {await rm(home,{recursive:true,force:true});}
});
