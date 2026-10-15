/* 界面摘录说明：Harness 活动条、角色提示词设置、Batch 设置和 Cloud 入口的界面组件。可改 h() 结构、图标、文案；保留 fetch 路径、字段键和值。 */
/** DSH's documented client module format; React stays in the DSH component tree. */
window.__ModuleLoader__.load({id:'@vertex-studio/harness-theme',factory(require) {
  const {createElement:h,useEffect,useState}=require('react');
  // 用途：Harness 内部 Logo 的 SVG 形状及颜色；改外观时保留原有设置字段和请求路径。
  function Mark({size=24,className}) {
    return h('svg',{width:size,height:size,viewBox:'0 0 32 32',fill:'none',className,'aria-hidden':true},
      h('rect',{x:3,y:5,width:24,height:23,rx:7,stroke:'#df7b12',strokeWidth:1.85}),
      h('path',{d:'M9.5 23.5L14.5 17.5L18.5 20.5L23.5 13.5',stroke:'#b85d0b',strokeWidth:2,strokeLinecap:'round',strokeLinejoin:'round'}),
      h('path',{d:'M26 2L27.4 5.1L30.5 6.5L27.4 7.9L26 11L24.6 7.9L21.5 6.5L24.6 5.1Z',fill:'#df7b12'}));
  }
  const states={preparing:'准备输入',uploading:'上传中',submitting:'提交中',submission_unknown:'核对提交结果',queued:'云端排队',running:'生成中',cancel_requested:'云端取消待确认',cancelled:'已停止',completed:'已返回',failed:'失败',budget_paused:'达到限额'};
  // 用途：Batch 状态、预算、续传和已恢复答复的展示；改外观时保留原有设置字段和请求路径。
  function Activity({session}) {
    const [data,setData]=useState(),[error,setError]=useState(''),[open,setOpen]=useState(false);
    useEffect(() => {
      let active=true,controller=new AbortController();
      async function refresh() {
        try {const r=await fetch('./vbs/activity',{credentials:'same-origin',signal:controller.signal});if(!r.ok)throw Error('状态暂时不可用');const value=await r.json();if(active){setData(value);setError('');}}
        catch(e){if(active&&e.name!=='AbortError')setError(e.message);}
      }
      void refresh(); const timer=setInterval(refresh,3000);
      return ()=>{active=false;clearInterval(timer);controller.abort();};
    },[]);
    const rows=(data?.requests || []).filter(r=>r.session_id===session?.sessionId);
    const latest=rows.at(-1),current=rows.filter(r=>r.run_id===latest?.run_id);
    const final=r=>['completed','cancelled','failed','budget_paused'].includes(r.phase);
    const spent=current.reduce((s,r)=>s+r.actual_usd,0),reserved=current.filter(r=>!final(r)).reduce((s,r)=>s+r.reserved_usd,0);
    const unresolved=current.filter(final).reduce((s,r)=>s+r.reserved_usd,0);
    const submitted=current.reduce((s,r)=>s+(r.continuation?.submitted_jobs ?? Number(Boolean(r.submission_intent))),0);
    const promotional=current.every(r=>!r.actual_usd||r.cost_estimate)?current.reduce((s,r)=>s+(r.cost_estimate?.promotional_estimated_usd||0),0):null;
    const limitsEnabled=latest?.limits_enabled ?? data?.limits?.limitsEnabled ?? false;
    const end=latest && ['completed','cancelled','failed','budget_paused'].includes(latest.phase) ? Date.parse(latest.updated_at) : Date.now();
    return h('div',{className:'vbs-batch-activity'},
      h('button',{type:'button',className:'vbs-activity-toggle','aria-expanded':open,onClick:()=>setOpen(!open)},
        h('span',{className:'vbs-activity-dot'}), data?.offline ? '离线验收' : latest?.truncated ? '续传已停止' : latest?.continuation?.state==='buffering' ? `正在续传 · 第 ${latest.continuation.segment_index+1} 批 · ${states[latest.phase] || latest.phase}` : latest ? states[latest.phase] || latest.phase : 'Batch · 待开始',
        h('span',{className:'vbs-activity-cost'},data?.offline?'无模型费用':`估算 $${spent.toFixed(3)} · 预留 $${reserved.toFixed(3)}${unresolved?' · 待核对 $'+unresolved.toFixed(3):''} / ${limitsEnabled?'$'+(latest?.budget_usd ?? data?.limits?.budgetUsd ?? 5).toFixed(2):'本地预算/次数不限'}`)),
      latest?.local_recovery?.text && h('details',{className:'vbs-recovered-answer',open:true},
        h('summary',null,'已找回本轮收尾答复'),
        h('p',null,'来自已经返回的原始 Batch 结果。未重新提交，也未重跑工具；上方保留原失败记录。'),
        h('pre',null,latest.local_recovery.text)),
      open && h('div',{className:'vbs-activity-detail'},
        h('p',null,'估算按返回用量计算，含思考 Token，使用优惠返还前的 Batch 价格；预留按输出上限计算，不代表已扣费。最终账单以 Cloud Billing 为准。'),
        promotional!==null && spent>0 && h('p',null,`按公开活动返还规则估算 $${promotional.toFixed(3)}，尚未核验账户抵扣。`),
        h('p',null,limitsEnabled?`最多 ${latest?.max_rounds ?? data?.limits?.maxRounds ?? 20} 次请求 · 文件与命令遵循当前权限。`:'本地预算、次数和自定义输出额度已关闭。Argon 遇到有效续传令牌会自动接续，完整结束后统一交付；文件与命令仍遵循当前权限。'),
        latest && h('p',null,`步骤 ${latest.step_id} · ${submitted}${limitsEnabled?' / '+(latest?.max_rounds ?? data?.limits?.maxRounds ?? 20):''} 次请求 · 等待 ${Math.max(0,Math.floor((end-Date.parse(latest.created_at))/1000))} 秒`),
        latest?.continuation && h('p',null,`已保存 ${latest.continuation.buffered_segments} 段 · 累计生成 ${latest.continuation.generated_tokens} Token（含思考） · 完整结束前不执行工具`),
        latest?.job_name && h('code',null,latest.job_name),
        latest?.error && h('p',{role:'alert'},latest.error),
        error && h('p',{role:'alert'},error)));
  }
  // 用途：跳转到外层 Google Cloud 配置页面的按钮；改外观时保留原有设置字段和请求路径。
  function NotificationSettingsEntry() {
    const [error,setError]=useState(''),[pending,setPending]=useState(false);
    return h('section',{className:'vbs-run-settings vbs-notification-settings-entry'},
      h('h2',null,'完成提醒'),
      h('p',{className:'vbs-run-note'},'选择每批完成或全部完成时提醒，并设置通知声音。生图与 Harness 共用工作室的提醒设置。'),
      h('button',{type:'button',className:'vbs-cloud-settings-button',disabled:pending,onClick:async()=>{
        if(pending)return;setPending(true);setError('');
        try {const r=await fetch('./vbs/open-notification-settings',{method:'POST',credentials:'same-origin'});if(!r.ok)throw Error();}
        catch {setError('无法打开提醒设置，请从工作室设置中打开');}
        finally {setPending(false);}
      }},h('svg',{width:17,height:17,viewBox:'0 0 24 24',fill:'none','aria-hidden':true},
        h('path',{d:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4',stroke:'currentColor',strokeWidth:1.7,strokeLinecap:'round',strokeLinejoin:'round'})),
        pending?'正在打开…':'打开完成提醒设置 ↗'),
      error && h('p',{className:'vbs-notification-error',role:'alert'},error));
  }
  function CloudSettingsEntry() {
    const [pending,setPending]=useState(false),[error,setError]=useState('');
    async function open() {
      if(pending)return;
      setPending(true);setError('');
      try {
        const response=await fetch('./vbs/open-cloud-settings',{method:'POST',credentials:'same-origin'});
        if(!response.ok)throw Error('请从 Vertex Studio 打开此页面后重试');
      } catch {setError('无法打开 Google Cloud 设置，请重试');}
      finally {setPending(false);}
    }
    return h('div',{className:'vbs-cloud-settings-entry'},
      h('button',{type:'button',className:'vbs-cloud-settings-button',disabled:pending,onClick:open},
        h('svg',{width:17,height:17,viewBox:'0 0 24 24',fill:'none','aria-hidden':true},
          h('path',{d:'M18 9h3v-6h-6M21 3l-9 9M10 4H6a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-4',stroke:'currentColor',strokeWidth:1.7,strokeLinecap:'round',strokeLinejoin:'round'})),
        'Google Cloud 配置'),
      error && h('p',{role:'alert'},error));
  }
  // 用途：角色提示词文本框及保存 / 恢复默认按钮；改外观时保留原有设置字段和请求路径。
  function PersonaSettings() {
    const [text,setText]=useState(''),[initial,setInitial]=useState(''),[limit,setLimit]=useState(16000);
    const [loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
    useEffect(()=>{const controller=new AbortController();
      fetch('./vbs/persona',{credentials:'same-origin',signal:controller.signal}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error);return v;})
        .then(v=>{setText(v.text);setInitial(v.text);setLimit(v.max_chars);})
        .catch(e=>{if(e.name!=='AbortError')setError(e.message||'读取失败');})
        .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
      return()=>controller.abort();},[]);
    async function save(reset=false) {
      if(saving)return;setSaving(true);setError('');setMessage('');
      try {const r=await fetch('./vbs/persona',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(reset?{reset:true}:{text})});
        const v=await r.json();if(!r.ok)throw Error(v.error||'保存失败');setText(v.text);setInitial(v.text);setMessage(reset?'已恢复默认':'已保存');
      }catch(e){setError(e.message||'保存失败，请重试');}finally{setSaving(false);}
    }
    return h('section',{className:'vbs-persona-settings'},
      h('h2',null,'角色与提示词'),
      h('label',{htmlFor:'vbs-persona-text'},'角色提示词'),
      h('textarea',{id:'vbs-persona-text',value:text,disabled:loading||saving,maxLength:limit,spellCheck:false,onChange:e=>{setText(e.target.value);setMessage('');},rows:10}),
      h('div',{className:'vbs-persona-note'},h('span',null,text.length+' / '+limit)),
      h('div',{className:'vbs-persona-actions'},
        h('button',{type:'button',className:'vbs-persona-reset',disabled:loading||saving,onClick:()=>save(true)},'恢复默认'),
        h('button',{type:'button',className:'vbs-persona-save',disabled:loading||saving||!text.trim()||text===initial,onClick:()=>save()},saving?'保存中…':'保存')),
      error&&h('p',{role:'alert',className:'vbs-persona-error'},error),
      message&&h('p',{role:'status',className:'vbs-persona-success'},message));
  }
  // 用途：Batch 预算、输出额度、次数及限额开关；改外观时保留原有设置字段和请求路径。
  function RunSettings() {
    const [values,setValues]=useState(),[saved,setSaved]=useState(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
    useEffect(()=>{const abort=new AbortController();fetch('./vbs/run-settings',{credentials:'same-origin',signal:abort.signal}).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.error);return v.settings;}).then(v=>{setValues(v);setSaved(v);}).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>abort.abort();},[]);
    async function save() {
      setBusy(true);setError('');setMessage('');
      try {const r=await fetch('./vbs/run-settings',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});const v=await r.json();if(!r.ok)throw Error(v.error);setValues(v.settings);setSaved(v.settings);setMessage('已保存');}
      catch(e){setError(e.message);}finally{setBusy(false);}
    }
    return h('section',{className:'vbs-run-settings'},h('h2',null,'Batch 运行'),
      values&&h('label',{className:'vbs-limit-row'},h('span',null,'启用运行限额'),h('button',{type:'button',role:'switch','aria-label':'启用运行限额','aria-checked':values.limitsEnabled,className:'vbs-limit-switch',disabled:busy,onClick:()=>{setValues({...values,limitsEnabled:!values.limitsEnabled});setMessage('');}},h('span',null))),
      values&&[['maxOutputTokens','每次输出额度（Token）',1,1048576,1],['budgetUsd','每个任务预算（美元）',0.01,undefined,0.01],['maxRounds','每个任务最多模型请求次数',1,undefined,1]].map(([key,label,min,max,step])=>h('label',{key},h('span',null,label),h('input',{type:'number',value:values[key],min,max,step,disabled:busy||!values.limitsEnabled,onChange:e=>{setValues({...values,[key]:e.target.value===''?null:Number(e.target.value)});setMessage('');}}))),
      h('p',{className:'vbs-run-note'},'建议保持关闭，开启后可能有奇妙限额BUG。'),
      h('div',{className:'vbs-persona-actions'},h('button',{type:'button',className:'vbs-persona-save',disabled:busy||!values||JSON.stringify(values)===JSON.stringify(saved),onClick:save},busy?'保存中…':'保存')),
      error&&h('p',{role:'alert',className:'vbs-persona-error'},error),message&&h('p',{role:'status',className:'vbs-persona-success'},message));
  }
  return {inject:['slots','theme'],apply(ctx) {
    // 主题 Token 配对：每项为 [浅色值, 深色值]；只改颜色值即可保留所有后端行为。
    const pairs={
      '--dsw-alias-bg-base':['#f7f3ed','#171411'], '--dsw-alias-bg-module-platform':['#f2e7d6','#28211b'],
      '--dsw-alias-bg-layer-1':['#fdfbf7','#1f1a16'], '--dsw-alias-bg-layer-2':['#fdfbf7','#26201b'],
      '--dsw-alias-bg-layer-3':['#ffffff','#2e2620'], '--dsw-alias-brand-primary':['#df7b12','#f29d38'],
      '--dsw-alias-brand-text':['#8c4608','#f7be74'], '--dsw-alias-button-primary-fill':['#df7b12','#f29d38'],
      '--dsw-alias-button-primary-hover':['#c96c0b','#f7b15c'], '--dsw-alias-button-info-fill':['#df7b12','#f29d38'],
      '--dsw-alias-label-primary':['#2b221a','#f7ede0'], '--dsw-alias-label-primary-foreground':['#ffffff','#1f1812'],
      '--dsw-alias-label-secondary':['#75604d','#bfa890'], '--dsw-specific-input-major':['#fdfbf7','#1f1a16'],
      '--dsw-menu-surface-fill':['#fdfbf7','#26201b']
    };
    pairs['--dsw-specific-sidebar-fill']=['#fdfbf7','#1f1a16'];
    ctx.effect(()=>ctx.theme.overrideTokens('@vertex-studio/harness-theme',Object.fromEntries(Object.entries(pairs).map(([k,[light,dark]])=>[k,{light,dark}]))));
    ctx.slots.inject('sidebar.brand.mark',()=>ctx.slots.register({name:'sidebar.brand.mark'},Mark));
    ctx.slots.inject('sidebar.brand.name',()=>ctx.slots.register({name:'sidebar.brand.name'},()=>h('span',null,'Vertex Harness')));
    ctx.slots.inject('conversation.hero.brand.mark',()=>ctx.slots.register({name:'conversation.hero.brand.mark'},Mark));
    ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'vertex-persona',order:11,label:()=> '角色与提示词'},PersonaSettings));
    ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'vertex-run-settings',order:12,label:()=> 'Batch 运行'},RunSettings));
    ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'vertex-notifications',order:13,label:()=> '完成提醒'},NotificationSettingsEntry));
    ctx.slots.inject('settings.models.footer',()=>ctx.slots.register({name:'settings.models.footer',id:'vertex-cloud-settings',order:0},CloudSettingsEntry));
    ctx.slots.inject('conversation.input.dock',()=>ctx.slots.register({name:'conversation.input.dock',id:'vertex-batch-activity',order:100},Activity));
  }};
}});
