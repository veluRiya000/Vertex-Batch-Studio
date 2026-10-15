import {test} from 'node:test';
import assert from 'node:assert/strict';
import {toGemini} from './wire.mjs';
const tool=(id,text)=>({role:'tool',source:{callId:id},content:[{type:'text',text}]});
const user=text=>({role:'user',content:[{type:'text',text}]});
function assistant(ids=['a','b','c']) {
 const raw={role:'model',parts:[{text:'thinking 1',thought:true},{text:'thinking 2',thought:true},...ids.map((id,i)=>({functionCall:{id,name:'read',args:{file_path:'script.md',offset:i*2000+1}},...(i===0?{thoughtSignature:'signature'}:{})}))]};
 return {role:'assistant',content:[{type:'reasoning',text:'merged thinking'},...ids.map(id=>({type:'tool-call',id,name:'read',arguments:'{}'}))],source:{replayState:{response:{geminiContent:raw}}}};
}
test('three same-name parallel calls get one response message in original call order',async()=>{
 const a=assistant();const request=await toGemini({messages:[a,tool('c','third'),tool('a','first'),tool('b','second')]});
 assert.equal(request.contents.length,2);assert.deepEqual(request.contents[0],a.source.replayState.response.geminiContent);
 assert.deepEqual(request.contents[1].parts.map(p=>p.functionResponse.id),['a','b','c']);
 assert.deepEqual(request.contents[1].parts.map(p=>p.functionResponse.response.content[0].text),['first','second','third']);
 assert.equal(request.contents[0].parts[2].thoughtSignature,'signature');
});
test('interleaved context and user additions do not split a function response turn',async()=>{
 const request=await toGemini({messages:[assistant(['a','b']),tool('a','first'),user('additional context'),{role:'developer',content:[{type:'text',text:'rule'}]},tool('b','second'),user('after')]});
 assert.equal(request.contents[1].parts.length,2);assert.equal(request.contents[2].parts[0].text,'additional context');assert.equal(request.contents[3].parts[0].text,'after');assert.equal(request.systemInstruction.parts[0].text,'rule');
});
test('missing, duplicate and orphan results are rejected locally before a paid request',async()=>{
 await assert.rejects(toGemini({messages:[assistant(),tool('a','first')]}),/incomplete/);
 await assert.rejects(toGemini({messages:[assistant(),tool('a','first'),tool('a','duplicate')]}),/Duplicate/);
 await assert.rejects(toGemini({messages:[tool('x','orphan')]}),/matching/);
 await assert.rejects(toGemini({messages:[assistant(),tool('a','first'),assistant(['next'])]}),/incomplete/);
});
test('different model rounds retain separate response groups',async()=>{
 const request=await toGemini({messages:[assistant(['a','b']),tool('b','B'),tool('a','A'),assistant(['c']),tool('c','C'),{role:'assistant',content:[{type:'text',text:'done'}]}]});
 assert.deepEqual(request.contents.map(c=>[c.role,c.parts.filter(p=>p.functionResponse).length]),[['model',0],['user',2],['model',0],['user',1],['model',0]]);
});
