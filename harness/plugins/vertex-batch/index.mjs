import {brokerCredentials} from '../broker-credentials.mjs';
/** Batch-only model adapter mounted alongside the unmodified DSH core. */
import {createHash} from 'node:crypto';
import {createBatchDelivery} from './batch-delivery.mjs';
import {createInterface} from 'node:readline';
import {LlmAdapter, LlmError, attributionHeaders, createAssistantMessage} from '../../upstream/packages/llm/llm/lib/index.js';
import {toGemini,responseChunks} from './wire.mjs';
import {snapshots} from './events.mjs';
import {requireConfinedTools} from '../tool-policy.mjs';
import {offlineAgentResponse} from '../offline-agent.mjs';
import {batchPolicy} from './batch-policy.mjs';
import {readPersona,formatPersona} from '../persona.mjs';
import {workspaceOverview} from './workspace-overview.mjs';
import {preloadAttachments,parseAttachmentHandle} from './attachment-preload.mjs';
import {skipUnsupportedAttachments} from '../attachment-policy.mjs';
import {readRunSettings} from '../run-settings.mjs';
import {modelProfiles,modelProfile,validateModelOutput} from '../model-profiles.mjs';

export const inject = ['llm','agents','tools','attachments','fs','shell','sandboxPolicy','sandbox'];
const hash = value => createHash('sha256').update(value).digest('hex');
const offline = process.env.VBS_HARNESS_OFFLINE === '1';
let closing = false;

async function broker(path, body, signal) {
  const base = brokerCredentials.url;
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '')) throw new LlmError('Local broker unavailable','BROKER_UNAVAILABLE');
  const response = await fetch(base+path, {method:body === undefined ? 'GET':'POST', headers:{...attributionHeaders(), 'Content-Type':'application/json','X-VBS-Harness-Token':brokerCredentials.token}, body:body === undefined ? undefined:JSON.stringify(body), signal});
  const value = await response.json();
  if (!response.ok) throw new LlmError(value.detail || 'Batch broker rejected request','BROKER_REJECTED');
  return value;
}

class VertexAdapter extends LlmAdapter {
  constructor(ctx, identities, delivery) {super(); this.ctx=ctx; this.identities=identities; this.delivery=delivery;}
  providerInfo(provider) {return {id:provider,name:offline ? '离线验收 · 无云端调用':'Google Cloud Batch'};}
  async listModels(provider) {return modelProfiles.map(value=>({provider,id:value.id,name:offline&&value.id==='gemini-4-argon'?'Offline protocol test':value.name,inputModalities:['text','image']}));}
  async resolveModel(provider,model) {
    const profile=modelProfile(model);
    return {...(await this.listModels(provider)).find(value=>value.id===model),context:{contextWindow:profile.contextWindow},
      defaultMaxTokens:65536,reasoning:{efforts:['low','medium','high'].map(id=>({id,name:id.toUpperCase()})),defaultEffort:profile.defaultEffort}};
  }
  async *stream(options) {
    const identity = this.identities.get(options.sessionId);
    if (!identity) throw new LlmError('Batch call has no durable agent step identity','MISSING_STEP');
    const id=hash(`${identity.runId}:${identity.step}:${options.purpose || 'main'}`);
    if(options.model!==identity.model)throw new LlmError('模型与冻结的任务不一致','MODEL_CHANGED');
    const filtered=skipUnsupportedAttachments(options.messages,parseAttachmentHandle);
    if(filtered.skipped.length && !filtered.messages.some(message=>message.role==='user' && message.content.length))
      throw new LlmError('不支持的文件类型：请添加提示词或受支持的附件','UNSUPPORTED_ATTACHMENT');
    const preloaded=await preloadAttachments(filtered.messages,this.ctx.attachments,options.signal);
    const decode=response=>{
      const chunks=responseChunks(response,id,options.tools);
      this.delivery.prepare(identity,chunks,options.sessionId);
      return chunks;
    };
    const limits=await readRunSettings();
    const prepared={...options,messages:preloaded.messages,limitsEnabled:limits.limitsEnabled};
    if (offline) {
      // Exercise the same request codec during offline Agent-loop acceptance.
      const offlineRequest=await toGemini({...prepared,tools:options.tools});
      if(process.env.VBS_HARNESS_OFFLINE_ACTIONS==='1') {
        console.log('VBS_OFFLINE_MODEL_STEP '+JSON.stringify({sessionId:options.sessionId,turn:identity.turn,step:identity.step}));
        for(const chunk of decode(offlineAgentResponse(identity,options)))yield chunk;
        return;
      }
      if(preloaded.loaded.length){
        if(!offlineRequest.contents.some(c=>c.parts.some(p=>p.text?.startsWith('[本地预读附件：完整正文]'))))throw new Error('Preloaded content is missing from the first request');
        for(const chunk of responseChunks({candidates:[{finishReason:'STOP',content:{role:'model',parts:[{text:'离线附件预读验收完成：首轮请求包含完整附件正文，未请求读取工具。'}]}}]},id))yield chunk;
        return;
      }
      const alreadyRead = options.messages.findLastIndex(m => m.role === 'tool') > options.messages.findLastIndex(m => m.role === 'user');
      const read = options.tools?.find(t => t.name === 'read');
      const part = !alreadyRead && read
        ? {functionCall:{name:'read',args:{file_path:'README.md'}}}
        : {text:'离线协议验收完成：会话、工具回传和界面事件已运行。没有调用 Google Cloud，也没有产生模型费用。'};
      const parts=!alreadyRead && read && process.env.VBS_HARNESS_OFFLINE_PARALLEL==='1'
        ? [1,3,5].map(offset=>({functionCall:{name:'read',args:{file_path:'README.md',offset,limit:2}}}))
        : [part];
      for (const chunk of decode({candidates:[{finishReason:'STOP',content:{role:'model',parts}}]})) yield chunk;
      return;
    }
    const overview=await workspaceOverview(identity.workspace);
    const batchInstructions=batchPolicy({readOnly:identity.session && this.ctx.sandboxPolicy.resolve({session:identity.session}).mode==='read-only'});
    const personaInstructions=formatPersona((await readPersona()).text,options.model);
    const request=await toGemini({...prepared,batchInstructions,personaInstructions,batchContext:overview.text,tools:options.tools,maxTokens:limits.limitsEnabled ? (options.maxTokens || limits.maxOutputTokens) : undefined}, async ref => {
      const value = await this.ctx.attachments.readImage(ref, options.signal);
      return {data:value.data,mimeType:value.ref.mediaType};
    });
    await broker('/harness/runs', {run_id:identity.runId,session_id:options.sessionId,workspace:identity.workspace,budget_usd:limits.budgetUsd,max_rounds:limits.maxRounds,limits_enabled:limits.limitsEnabled},options.signal);
    await broker('/harness/requests', {request_id:id,run_id:identity.runId,session_id:options.sessionId,step_id:String(identity.step),model:options.model,request},options.signal);
    const cancel=() => {if (!closing) void broker(`/harness/requests/${id}/cancel`).catch(error => this.ctx.logger.warn(error.message));};
    options.signal?.addEventListener('abort',cancel,{once:true});
    try {
      for await (const receipt of snapshots(`${brokerCredentials.url}/harness/requests/${id}/events`,brokerCredentials.token,options.signal)) {
        if (receipt.phase === 'completed') {
          for (const chunk of decode(receipt.response)) yield chunk;
          return;
        }
        if (['failed','cancelled','budget_paused'].includes(receipt.phase)) throw new LlmError(receipt.error || receipt.phase,receipt.phase.toUpperCase());
      }
    } finally {options.signal?.removeEventListener('abort',cancel);}
  }
}

export function apply(ctx) {
  ctx.effect(() => {
    const input=createInterface({input:process.stdin});
    input.on('line',line => {if (line === 'vbs-shutdown') {closing=true; process.emit('SIGTERM');}});
    return () => input.close();
  });
  const identities=new Map();
  const delivery=createBatchDelivery(ctx,identities,createAssistantMessage);
  ctx.effect(()=>ctx.tools.register(delivery.tool));
  ctx.on('tools/result',(exec,result)=>delivery.observe(exec,result));
  ctx.on('session/event',(session,event)=>delivery.committed(session,event));
  const preparedWorkspaces=new Set();
  if(offline && process.env.VBS_HARNESS_OFFLINE_ACTIONS==='1')ctx.on('tools/result',(exec,result)=>{
    console.log('VBS_OFFLINE_TOOL '+JSON.stringify({tool:exec.name,isError:result.isError,error:result.error,content:result.content}));
  });
  ctx.on('agent/request', async ({agent,turn,step,signal},next) => {
    const config=await next();
    const policy=ctx.sandboxPolicy.resolve({session:agent.session});
    // Provision standing workspace ACLs before any model observes file versions.
    // confine prepares a runner; it does not execute this command or widen mode.
    if(policy.mode==='workspace-write' && !preparedWorkspaces.has(policy.workspaceRoot)) {
      await ctx.sandbox.confine(['cmd.exe','/c','exit','0'],policy,signal);
      preparedWorkspaces.add(policy.workspaceRoot);
    }
    const runId=hash(`${agent.id}:${turn}`),previous=identities.get(agent.id);
    // Preserve the model across tool rounds; a menu change applies next turn.
    const model=previous?.runId===runId?previous.model:(config.model || 'gemini-4-argon');
    modelProfile(model);
    const limits=await readRunSettings();
    const maxTokens=limits.limitsEnabled ? validateModelOutput(model,limits.maxOutputTokens) : undefined;
    identities.set(agent.id,{runId,turn,step,model,session:agent.session,workspace:agent.session.header.cwd || process.cwd()});
    return {...config,provider:'vertex-batch',model,maxTokens};
  });
  const finishTurn=async ({agent,turn}) => {
    if (!offline) await broker(`/harness/runs/${hash(`${agent.id}:${turn}`)}/finish`,{}).catch(error => ctx.logger.warn(error.message));
  };
  ctx.on('agent/turn-stopping',async payload=>{delivery.clear(payload.agent,payload.turn);await finishTurn(payload);});
  // DSH emits errors instead of the normal stopping boundary on failure.
  // Use the event's exact turn identity, never a later turn's mutable map.
  ctx.on('agent/error',async payload=>{delivery.clear(payload.agent,payload.turn);await finishTurn(payload);});
  // DSH owns validation, read-before-edit checks, sandbox modes and approvals.
  // Do not route mutations to an unconfined provider if composition is broken.
  ctx.on('tools/pre-execute', async (exec,next) => {
    const denied=delivery.guard(exec) || requireConfinedTools(ctx,exec.name || exec.toolName);
    if(denied)return {kind:'deny',reason:denied};
    return next();
  });
  ctx.effect(() => ctx.llm.registerAdapter(['vertex-batch'],new VertexAdapter(ctx,identities,delivery)));
}
