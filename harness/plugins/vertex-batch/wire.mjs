/** Gemini-native request/response projection, independent of any network client. */
import {toParameters} from './schema.mjs';
import {executionArguments} from './tool-arguments.mjs';
import {defaultRunSettings} from '../run-settings.mjs';
import {modelProfile,validateModelOutput} from '../model-profiles.mjs';
export async function toGemini(options, readImage) {
  const contents = [], systems = [];
  let pending;
  if (options.system) systems.push(options.system);
  function finishTools() {
    if (!pending) return;
    if (pending.results.size !== pending.calls.length) throw new Error('Tool turn is incomplete: every function call needs one result before the next Batch request');
    contents.push({role:'user',parts:pending.calls.map(call=>pending.results.get(call.localId))});
    contents.push(...pending.context);
    pending=undefined;
  }
  for (const message of options.messages) {
    if (message.role === 'system' || message.role === 'developer') {
      systems.push(message.content.filter(b => b.type === 'text').map(b => b.text).join('\n'));
      continue;
    }
    const parts = [];
    for (const block of message.content) {
      if (block.type === 'text') parts.push({text: block.text});
      else if (block.type === 'tool-call') parts.push({functionCall:{id:block.id,name:block.name,args:JSON.parse(block.arguments)}});
      else if (block.type === 'image') {
        if (!readImage) throw new Error('Image attachment reader is unavailable');
        const bytes = await readImage(block.attachment);
        parts.push({inlineData:{mimeType:bytes.mimeType,data:Buffer.from(bytes.data).toString('base64')}});
      } else if (block.type !== 'reasoning') throw new Error('Unsupported content block: '+block.type);
    }
    if (message.role === 'tool') {
      const localId=message.source?.callId;
      const call=pending?.calls.find(call=>call.localId===localId);
      if (!call) throw new Error('Tool result has no matching call');
      if (pending.results.has(localId)) throw new Error('Duplicate tool result');
      pending.results.set(localId,{functionResponse:{name:call.name,...(call.nativeId?{id:call.nativeId}:{}),response:{content:parts}}});
      if (pending.results.size===pending.calls.length) finishTools();
      continue;
    }
    if (message.role === 'assistant') {
      finishTools();
      const sameModel=!options.model||!message.source?.model||message.source.model===options.model;
      const content=(sameModel?message.source?.replayState?.response?.geminiContent:undefined) || {role:'model',parts};
      // Tool blocks can move when DSH merges adjacent text/reasoning blocks.
      // Pair function calls by native ID, then by tool-only order, never text indices.
      const localCalls=message.content.filter(block=>block.type==='tool-call');
      const nativeCalls=content.parts.filter(part=>part.functionCall).map(part=>part.functionCall);
      if (localCalls.length!==nativeCalls.length) throw new Error('Tool replay has a different function-call count');
      if (localCalls.length) {
        const used=new Set(),ids=new Set();
        const calls=localCalls.map((block,index)=>{
          if (ids.has(block.id)) throw new Error('Duplicate function call ID');
          ids.add(block.id);
          let nativeIndex=nativeCalls.findIndex((call,i)=>!used.has(i)&&call.id===block.id);
          if (nativeIndex<0) nativeIndex=index;
          const native=nativeCalls[nativeIndex];
          if (used.has(nativeIndex)||native.name!==block.name) throw new Error('Tool replay has a different function-call order');
          used.add(nativeIndex);
          return {localId:block.id,nativeId:native.id,name:native.name,nativeIndex};
        });
        calls.sort((a,b)=>a.nativeIndex-b.nativeIndex);
        pending={calls,results:new Map(),context:[]};
      }
      if (content.parts.length) contents.push(content);
    } else if (parts.length) {
      const content={role:'user',parts};
      // Keep mid-tool user/context additions, but place them after the complete
      // function-response turn so they cannot split Gemini's call/result pair.
      if (pending) pending.context.push(content);
      else contents.push(content);
    }
  }
  finishTools();
  // Explicit system policy; never append it to the user's editable prompt.
  if(options.personaInstructions)systems.push(options.personaInstructions);
  if(options.batchInstructions)systems.push(options.batchInstructions);
  if(options.batchContext)contents.unshift({role:'user',parts:[{text:options.batchContext}]});
  const effort = options.reasoningEffort?.toUpperCase() || modelProfile(options.model).defaultEffort.toUpperCase();
  if (!['LOW','MEDIUM','HIGH'].includes(effort)) throw new Error('Unsupported thinking level');
  const request = {contents, generationConfig:{...(options.limitsEnabled===false ? {} : {maxOutputTokens:validateModelOutput(options.model || 'gemini-4-argon', options.maxTokens ?? defaultRunSettings.maxOutputTokens)}), thinkingConfig:{thinkingLevel:effort}}};
  if (systems.length) request.systemInstruction = {parts:[{text:systems.join('\n\n')}]};
  if (options.tools?.length) request.tools = [{functionDeclarations: options.tools.map(tool => ({name:tool.name, description:tool.description, parameters:toParameters(tool.parameters)}))}];
  return request;
}

/** Validate a whole response before emitting any actionable tool call. */
export function responseChunks(response, requestId, tools=[]) {
  const candidate = response.candidates?.[0];
  if (!candidate || !['STOP','MAX_TOKENS'].includes(candidate.finishReason)) throw new Error('Batch response did not finish successfully');
  if(candidate.continuationToken)throw new Error('Batch native continuation has not finished; buffered content cannot be dispatched');
  const truncated=candidate.finishReason==='MAX_TOKENS';
  // A truncated tool call is never published as actionable or replayed.
  const parts = truncated ? (candidate.content?.parts||[]).filter(p=>typeof p.text==='string') : candidate.content?.parts;
  if(truncated)parts.push({text:'\n\n[云端返回 MAX_TOKENS，本轮生成未完整结束；本地运行限额关闭也不能取消云端默认或单次输出限制。原始结果已保留，未执行本轮未完整结束的工具调用。本次云端没有返回可用续传令牌，无法自动接续；已收到的内容保留在本地。]'});
  if (!Array.isArray(parts) || !parts.length) throw new Error('Batch response has no content');
  if (!parts.some(part => part.functionCall || (!part.thought && typeof part.text === 'string' && part.text.trim()))) throw new Error('Batch response has no final text or tool call');
  const paddingFields=new Map();
  for(const part of parts) {
    const call=part.functionCall,schema=tools.find(tool=>tool.name===call?.name)?.parameters;
    if(!call || !call.args || typeof call.args!=='object' || Array.isArray(call.args))continue;
    for(const [key,value] of Object.entries(call.args)) {
      if(value!==null && Object.hasOwn(schema?.properties||{},key))paddingFields.set(key,Array.isArray(value)?'array':'value');
    }
  }
  const chunks = [], metadata = [];
  for (const [index, part] of parts.entries()) {
    let block;
    if (typeof part.text === 'string') block = {type:part.thought ? 'reasoning' : 'text', text:part.text};
    else if (part.functionCall) {
      if (typeof part.functionCall.name !== 'string' || !part.functionCall.args || typeof part.functionCall.args !== 'object' || Array.isArray(part.functionCall.args)) throw new Error('Invalid function call');
      const schema=tools.find(tool=>tool.name===part.functionCall.name)?.parameters;
      const args=executionArguments(part.functionCall.args,schema,paddingFields);
      // Keep metadata/replay byte-for-byte as returned; normalize execution only.
      block = {type:'tool-call', id:part.functionCall.id || `${requestId}-${index}`, name:part.functionCall.name, arguments:JSON.stringify(args)};
    } else throw new Error('Unsupported response part');
    chunks.push({type:'block-start', index, blockType:block.type});
    if (block.type === 'tool-call') chunks.push({type:'tool-call-delta', index, id:block.id, name:block.name, argumentsDelta:block.arguments});
    else chunks.push({type:block.type === 'text' ? 'text-delta' : 'reasoning-delta', index, text:block.text});
    chunks.push({type:'block-end', index, block});
    metadata.push(part);
  }
  const usage = response.usageMetadata;
  if (usage) chunks.push({type:'usage', usage:{inputTokens:(usage.promptTokenCount || 0)-(usage.cachedContentTokenCount || 0), outputTokens:(usage.candidatesTokenCount || 0)+(usage.thoughtsTokenCount || 0), cacheReadTokens:usage.cachedContentTokenCount || 0, totalTokens:usage.totalTokenCount}});
  chunks.push({type:'finish', reason:{kind:truncated ? 'max-tokens' : parts.some(p => p.functionCall) ? 'tool-calls':'stop'}, replayState:{response:{geminiContent:truncated?{role:'model',parts:metadata}:candidate.content,...(response.initialPromptTokenCount!==undefined?{initialPromptTokenCount:response.initialPromptTokenCount}:{})}, blocks:metadata}});
  return chunks;
}
