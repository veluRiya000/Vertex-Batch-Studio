/** Explicit terminal tool; completion is based on committed local outcomes. */
export const finishToolName='batch_finish';
const allowed=new Set(['write','edit','pwsh','present']);

export function createBatchDelivery(ctx,identities,createAssistantMessage) {
  const plans=new Map();
  function current(agent) {
    const identity=identities.get(agent?.id),plan=plans.get(agent?.id);
    return plan && identity && plan.runId===identity.runId && plan.step===identity.step ? plan : undefined;
  }
  function prepare(identity,chunks,sessionId) {
    plans.delete(sessionId);
    const finish=chunks.findLast(c=>c.type==='finish');
    if(finish?.reason.kind==='max-tokens')return;
    const calls=chunks.filter(c=>c.type==='block-end' && c.block.type==='tool-call').map(c=>c.block);
    if(!calls.some(c=>c.name===finishToolName))return;
    const valid=calls.at(-1)?.name===finishToolName && calls.filter(c=>c.name===finishToolName).length===1 &&
      calls.length>1 && calls.slice(0,-1).every(c=>allowed.has(c.name)) &&
      calls.slice(0,-1).some(c=>['write','edit','pwsh'].includes(c.name)) &&
      new Set(calls.map(c=>c.id)).size===calls.length;
    plans.set(sessionId,{runId:identity.runId,turn:identity.turn,step:identity.step,model:identity.model,calls,valid,results:new Map()});
  }
  function observe(exec,result) {
    const plan=current(exec.agent);
    if(!plan)return;
    const call=plan.calls.find(c=>c.id===exec.callId && c.name===exec.name);
    if(!call)return;
    // Authoritative finalized result, not optimistic model output.
    plan.results.set(call.id,result);
    if(call.name===finishToolName){plan.confirmed=!result.isError && result.concludesTurn===true;plan.agent=exec.agent;}
  }
  function completed(plan) {
    if(!plan?.valid)return 'batch_finish 必须是同一次响应中唯一且最后的收尾调用，前面应有完整交付操作。';
    for(const call of plan.calls.slice(0,-1)) {
      const result=plan.results.get(call.id);
      if(!result || result.isError)return `本地交付尚未完成：${call.name} 未成功，请根据工具结果处理后再收尾。`;
      if(result.additionalContexts?.length)return '工具返回了需要模型处理的新信息，不能本地直接收尾。';
      if(call.name==='pwsh') {
        const v=result.value;
        if(!v || v.kind!=='foreground' || v.exitCode!==0 || v.aborted || v.timedOut || v.signal)
          return '命令未正常以前台零退出码完成，仍需检查或等待，不能直接收尾。';
      }
    }
  }
  // Raw ToolDefinition: validate its small schema explicitly at execution.
  const tool={
    name:finishToolName,
    description:'Finish this Batch turn LOCALLY after all preceding delivery operations succeed. Put this exactly once and LAST in the SAME response as complete write/edit/foreground pwsh operations (and optional present). Supply the full final user-facing summary now; it is shown only after local success. Do not use for discovery, questions, background commands, or unfinished tests. Failure keeps the Agent loop running. No model request is needed solely to say done.',
    parameters:{type:'object',properties:{summary:{type:'string',minLength:1,description:'Complete final reply to display after the planned operations succeed. Mention deliverables and any unverified limitations. Do not claim tests that were not included and completed.'}},required:['summary'],additionalProperties:false},
    output:{
      schema:{type:'object',properties:{summary:{type:'string'}},required:['summary'],additionalProperties:false},
      render:()=>[{type:'text',text:'本轮交付操作已由本地执行器确认完成，无需再次请求模型收尾。'}],
      presentationMeta:(_,value)=>({batchDelivery:true,summary:value.summary}),
    },
    presentCall:()=>({card:'generic',title:'本地交付确认',kind:'other'}),
    presentResult:(_,result)=>({card:'generic',title:result.isError?'交付未完成，继续处理':'本地交付已确认',content:result.content}),
    async execute(args,exec) {
      exec.signal.throwIfAborted();
      if(!args || typeof args!=='object' || Array.isArray(args) || Object.keys(args).some(k=>k!=='summary') ||
          typeof args.summary!=='string' || !args.summary.trim())throw Error('batch_finish.summary 必须是完整的非空交付说明。');
      const plan=current(exec.agent),problem=completed(plan);
      if(problem)throw Error(problem);
      if(plan.calls.at(-1).id!==exec.callId)throw Error('收尾调用身份与冻结的操作列表不一致。');
      // Confining/approval policies already ran on each preceding real tool.
      // The terminal marker survives only an authoritative successful result.
      exec.concludeTurn();
      return {summary:args.summary};
    },
  };
  function committed(session,event) {
    if(event.type!=='tool/result')return;
    const plan=plans.get(session.id),data=event.data;
    if(!plan?.confirmed || plan.agent?.session!==session || data?.turn!==plan.turn || data.step!==plan.step ||
       data.message?.toolCallId!==plan.calls.at(-1).id || data.message.isError)return;
    plan.resultCommitted=true;
    // Session forbids reentrant appends during event publication. This runs
    // after publication returns, before the async tool scheduler closes the
    // step. finalize independently verifies that the step is still open.
    queueMicrotask(()=>{
      if(plans.get(session.id)!==plan)return;
      try {finalize(plan.agent,plan.turn);}
      catch(error){ctx.logger?.warn('Local delivery summary retained in tool result: '+error.message);}
    });
  }
  function finalize(agent,turn) {
    const plan=current(agent);
    if(!plan?.confirmed || !plan.resultCommitted || plan.turn!==turn)return false;
    const boundary=agent.session.snapshotEvents().findLast(event=>['step/start','step/end','turn/start','turn/end'].includes(event.type));
    if(boundary?.type!=='step/start' || boundary.data.turn!==turn || boundary.data.step!==plan.step)return false;
    const result=plan.results.get(plan.calls.at(-1).id);
    const summary=result.value?.summary;
    if(typeof summary!=='string'||!summary.trim())throw Error('本地交付说明缺失，已保留工具结果。');
    // The terminal tool/result is committed and its step is STILL OPEN.
    // Never append assistant/message at agent/turn-stopping (after step/end).
    // No invented usage and no extra cloud request.
    agent.session.append('assistant/message',{
      turn,step:plan.step,stream:[],
      message:createAssistantMessage({content:[{type:'text',text:'**本地交付已确认**\n\n'+summary}],
        source:{provider:'vertex-batch',model:plan.model}}),
    },{surfaceOp:'append'});
    plans.delete(agent.id);
    return true;
  }
  function guard(exec) {
    const plan=current(exec.agent);
    if(!plan?.valid || exec.name!=='present')return;
    const index=plan.calls.findIndex(c=>c.id===exec.callId && c.name==='present');
    if(index<0)return;
    for(const call of plan.calls.slice(0,index)) {
      const result=plan.results.get(call.id);
      if(!result || result.isError)return '前序交付操作未成功，不能把旧文件或未生成的文件展示为新交付。';
    }
  }
  function clear(agent,turn){const plan=current(agent);if(plan && plan.turn===turn)plans.delete(agent.id);}
  return {tool,prepare,observe,committed,finalize,clear,guard};
}
