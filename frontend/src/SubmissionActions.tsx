import { useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { useTranslation } from './i18n';
import type { Batch } from './types';

export function SubmissionActions({batch, action}: {batch:Batch; action:(batch:Batch, action:string)=>void}) {
  const t=useTranslation();
  const [confirm,setConfirm]=useState(false);
  const [clock,setClock]=useState(Date.now());
  const active=!!batch.active_action;
  const unknown=['submitting','submission_unknown','submission_unconfirmed'].includes(batch.phase) && !batch.job_name;
  const failed=['upload_failed','submission_failed'].includes(batch.phase) && !batch.job_name;
  useEffect(()=>{
    if (!active) return;
    const timer=setInterval(()=>setClock(Date.now()),1000);
    return ()=>clearInterval(timer);
  },[active]);
  useEffect(()=>setConfirm(false),[batch.phase,batch.job_name,batch.last_checked_at]);
  const stage=batch.operation?.stage;
  const stages:Record<string,string>={checking:'正在核对云端任务',validating:'正在检查参考图',
    uploading_refs:'正在上传参考图',uploading_prompt:'正在上传提示词',credentials:'正在检查连接',creating:'正在创建云端作业'};
  const started=batch.operation?.started_at || batch.action_started_at;
  const elapsed=started ? Math.max(0,Math.floor((clock-Date.parse(started))/1000)) : 0;
  const progress=active ? (!batch.action_started_at ? t('操作已排队') : t(stages[stage || ''] ||
    (batch.active_action === 'poll' ? '正在刷新结果' : '正在处理'))) : '';
  const label=failed ? '重新提交本轮' : batch.job_name ? '刷新结果' :
    ['failed','multiple'].includes(batch.reconciliation_status || '') ? '重试核对' : batch.reconciliation_status==='not_found' ? '重新提交本轮' : '核对并重试';
  const showAction=unknown || failed || !!batch.job_name;
  if (!showAction && !active) return null;
  return <div className="submission-actions">
    {active && <span className="submission-progress" role="status"><LoaderCircle size={13} className="spinning"/>{progress}
      {stage==='uploading_refs' && batch.operation?.total != null && ` · ${(batch.operation.completed || 0)+1}/${batch.operation.total}`}
      {batch.action_started_at && ` · ${elapsed} ${t('秒')}`}</span>}
    <div className="submission-buttons">
      {showAction && <button className="text-button" disabled={active} onClick={()=>action(batch,
        failed ? 'submit' : batch.job_name || batch.reconciliation_status==='failed' || batch.reconciliation_status==='multiple' ? 'poll' : 'recover')}>
        <RefreshCw size={13}/>{t(label)}</button>}
      {unknown && !active && !['failed','multiple'].includes(batch.reconciliation_status || '') &&
        <button className="text-button" onClick={()=>action(batch,'poll')}>{t('仅核对')}</button>}
      {unknown && !active && batch.reconciliation_status==='failed' &&
        <button className="text-button" onClick={()=>setConfirm(true)}>{t('仍要重新提交')}</button>}
    </div>
    {confirm && !active && <div className="submission-confirm" role="group" aria-label={t('确认重新提交')}>
      <p>{t('尚未确认原作业是否存在，重新提交可能产生重复任务和费用。')}</p>
      <button className="text-button" onClick={()=>{setConfirm(false);action(batch,'recover_force');}}>{t('确认重新提交')}</button>
      <button className="text-button" onClick={()=>setConfirm(false)}>{t('返回')}</button>
    </div>}
  </div>;
}
