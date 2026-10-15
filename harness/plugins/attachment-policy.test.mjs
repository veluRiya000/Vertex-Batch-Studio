import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {attachmentPolicy,isVideoAttachment,skipUnsupportedAttachments} from './attachment-policy.mjs';
import {parseAttachmentHandle,preloadAttachments} from './vertex-batch/attachment-preload.mjs';
import {toGemini} from './vertex-batch/wire.mjs';
function handle(name) {
 const digest=createHash('sha256').update(name).digest('hex');
 return `[File ${JSON.stringify(name)} (10 bytes, sha256:${digest.slice(0,8)}): verbatim read-only copy saved at ${JSON.stringify(join(resolve('attachments'),digest,name))}. Read that path with your file tools when its contents are needed; copy it to a writable location before modifying it. When delegating file work, include this saved path in the delegation prompt; only subagents sharing this execution environment can read it.]`;
}
const text=text=>({type:'text',text});
test('video MIME and case-insensitive extension detection do not block text or images',()=>{
 for(const name of ['剪辑.MP4','video.mov','clip.webm','clip.mkv'])assert.equal(isVideoAttachment(name),true);
 assert.equal(isVideoAttachment('unknown','video/mp4'),true);
 for(const name of ['notes.md','photo.png','video.mp4.txt','source.ts','module.mts','description'])assert.equal(isVideoAttachment(name),false);
});
test('skip removes uploaded video handles only; user prose and tool replay stay intact',async()=>{
 const image={type:'image',attachment:{id:'image'}};
 const tool={role:'tool',content:[text(handle('clip.mp4'))]};
 const messages=[{role:'user',content:[text('分析 clip.mp4 的名字'),text(handle('clip.MP4')),text(handle('notes.md')),image]},tool];
 const original=JSON.stringify(messages),r=skipUnsupportedAttachments(messages,parseAttachmentHandle);
 assert.equal(r.skipped.length,1);assert.equal(r.messages[0].content.length,3);
 assert.equal(r.messages[0].content[0].text,'分析 clip.mp4 的名字');
 assert.equal(r.messages[1],tool);assert.equal(JSON.stringify(messages),original);
 const encoded=await toGemini({messages:[{role:'user',content:[text('hi'),text(handle('clip.mp4'))]}].map(m=>skipUnsupportedAttachments([m],parseAttachmentHandle).messages[0])});
 assert.equal(JSON.stringify(encoded).includes('[File'),false);
});
test('skip disabled preserves original attachments; overlay flag is independent',()=>{
 const messages=[{role:'user',content:[text(handle('clip.mp4'))]}];
 assert.equal(skipUnsupportedAttachments(messages,parseAttachmentHandle,{...attachmentPolicy,skipVideoAttachments:false}).messages,messages);
 assert.equal(skipUnsupportedAttachments(messages,parseAttachmentHandle,{...attachmentPolicy,showUnsupportedVideoOverlay:false}).skipped.length,1);
});
test('skipped video never invokes attachment reader; structured video is also removed',async()=>{
 let reads=0;
 const r=skipUnsupportedAttachments([{role:'user',content:[text(handle('clip.mp4')),{type:'video',attachment:{name:'movie',mediaType:'video/mp4'}}]}],parseAttachmentHandle);
 const result=await preloadAttachments(r.messages,{fileHostPath(){reads++;throw Error('must not read');}});
 assert.equal(r.skipped.length,2);assert.equal(reads,0);assert.deepEqual(result.messages[0].content,[]);
});
