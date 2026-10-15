/** Reopen durable offline sessions through DSH's strict current-format reader. */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {zstdDecompressSync} from 'node:zlib';
const root=path.resolve(import.meta.dirname,'..');
const lib=path.join(root,'harness/component/upstream/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/types');
const {scanZstdFrames}=await import(pathToFileURL(path.join(lib,'zstd.js')));
const {scanLog}=await import(pathToFileURL(path.join(lib,'format.js')));
const base=path.resolve(process.argv[2]);
let count=0,summaries=0;
for(const name of fs.readdirSync(base,{recursive:true}).filter(n=>n.endsWith('session.v4.jsonl.zstd'))){
 const data=fs.readFileSync(path.join(base,name)),scan=scanZstdFrames(data);
 if(scan.tornStart!==undefined)throw Error('Torn frame');
 const plain=Buffer.concat(scan.frames.map(f=>zstdDecompressSync(data.subarray(f.start,f.end))));
 const restored=scanLog(plain);
 for(const event of restored.events)if(event.type==='assistant/message'&&event.data.message.content.some(p=>p.text?.startsWith('**本地交付已确认**')))summaries++;
 count++;
}
if(!count)throw Error('No durable sessions found');
console.log(JSON.stringify({strictReopen:'passed',sessions:count,localSummaries:summaries}));
