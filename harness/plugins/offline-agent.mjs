/** Isolated, opt-in model substitute; never used for a cloud request. */
export function offlineAgentResponse(identity,options) {
  const text=options.messages.filter(m=>m.role==='user').flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');
  const approval=text.includes('APPROVAL_TEST');
  const step=Number(identity.step);
  let parts;
  const deliveryText=options.messages.filter(m=>m.role==='user').flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).findLast(t=>t.includes('DELIVERY_TEST'));
  if(deliveryText) {
    if(step===1) {
      const bad=deliveryText.includes('DELIVERY_TEST_FAIL');
      const args=bad?{file_path:'never-created.md',content:null}:{file_path:'batch-delivery.md',content:'# Batch delivery\nComplete offline content\n'};
      if(deliveryText.includes('DELIVERY_TEST_APPROVAL'))Object.assign(args,{file_path:'batch-approved.md',sandbox_permissions:'workspace-write',justification:'离线测试：仅本次创建交付文件。'});
      parts=[{functionCall:{name:'write',args:{...args,summary:null}}},
        {functionCall:{name:'present',args:{files:[{path:args.file_path}]}}},
        {functionCall:{name:'batch_finish',args:{summary:`BATCH_DELIVERY_LOCAL_DONE: created ${args.file_path}. No extra model round was used.`,file_path:null,content:null}}}];
    } else parts=[{text:'DELIVERY_FAILURE_REPORTED_WITHOUT_FALSE_SUCCESS'}];
    parts=parts.map((p,i)=>({functionCall:p.functionCall?{id:`offline-delivery-${step}-${i}`,...p.functionCall}:undefined,...(!p.functionCall?p:{})}));
    // Do not leave undefined members in the JSON response fixture.
    parts=parts.map(p=>p.functionCall?{functionCall:p.functionCall}:{text:p.text});
    return {candidates:[{finishReason:'STOP',content:{role:'model',parts}}]};
  }
  if(step===1 && approval) parts=[{functionCall:{name:'write',args:{file_path:'approval-demo.md',content:'APPROVAL_GRANTED\n',sandbox_permissions:'workspace-write',justification:'离线测试：申请仅本次在工作区创建测试文件。'}}}];
  else if(step===1) parts=[
    {functionCall:{name:'write',args:{file_path:'agent-demo.md',content:'# 离线 Agent\n原文\n'}}},
    {functionCall:{name:'pwsh',args:{description:'离线命令执行测试',command:"if($env:VBS_HARNESS_BROKER_TOKEN){throw 'PRIVATE_TOKEN_LEAK'}; Write-Output 'HARNESS_COMMAND_OK'",workdir:identity.workspace}}},
  ];
  else if(step===2 && !approval) parts=[{functionCall:{name:'edit',args:{file_path:'agent-demo.md',old_string:'原文',new_string:'更新后的正文'}}}];
  else parts=[{text:approval?'APPROVAL_TEST_DONE':'AGENT_WRITE_EDIT_COMMAND_DONE'}];
  parts=parts.map((p,i)=>p.functionCall?{functionCall:{id:`offline-agent-${step}-${i}`,...p.functionCall}}:p);
  return {candidates:[{finishReason:'STOP',content:{role:'model',parts}}]};
}
