/* 界面摘录说明：Harness 启动入口及原生子 WebView 显示控制。可改入口文字、图标和外观；保留状态轮询、切换序号、遮挡弹窗与子视图显隐逻辑。
 * 仅此副本新增说明；原工程未改动。 */
import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';
import {LoaderCircle, Play, RefreshCw, SquareTerminal, ExternalLink} from 'lucide-react';
import {api} from './api';
import {useTranslation} from './i18n';

interface Status {available:boolean; running:boolean; ready:boolean; error:string|null; validation_required:boolean; offline:boolean|null; ui_request_seq?:number; ui_request_tab?:string;}
// 界面组件 HarnessPane：Harness 启动入口及原生子 WebView 显示控制。
export function HarnessPane({active, blocked}:{active:boolean; blocked:boolean}) {
  const t=useTranslation();
  const [status,setStatus]=useState<Status>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [url,setUrl]=useState('');
  const [offline,setOffline]=useState(false);
  const native=!!window.studio?.harnessView;
  const lastUiRequest=useRef(0);
  const refreshSequence=useRef(0);
  const refresh=useCallback(async () => {
    const sequence=++refreshSequence.current;
    try {
      const value=await api<Status>('/harness/status');
      // A delayed pre-switch response must not restore an obsolete startup state.
      if(sequence!==refreshSequence.current)return;
      setStatus(value);setError('');
      if((value.ui_request_seq || 0)>lastUiRequest.current){
        lastUiRequest.current=value.ui_request_seq!;
        window.dispatchEvent(new Event(value.ui_request_tab==='notifications' ? 'vbs:open-notification-settings' : 'vbs:open-cloud-settings'));
      }
      if(value.offline!==null)setOffline(value.offline);
    } catch(e) {if(sequence===refreshSequence.current)setError((e as Error).message);}
  },[]);
  useEffect(()=>()=>{refreshSequence.current++;},[]);
  async function stop() {
    setBusy(true);setError('');
    try {await window.studio?.harnessView?.(false,offline);await api('/harness/stop','POST');setUrl('');await refresh();}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  useEffect(()=>{
    const stopped=()=>{setUrl('');setStatus(value=>value?{...value,running:false,ready:false}:value);void refresh();};
    window.addEventListener('vbs:harness-stopped',stopped);
    return ()=>window.removeEventListener('vbs:harness-stopped',stopped);
  },[refresh]);
  useEffect(() => {
    if (!active) return;
    void refresh();
    const timer=setInterval(() => void refresh(),1000);
    return () => clearInterval(timer);
  },[active,refresh]);
  useLayoutEffect(() => {
    if (!native) return;
    let current=true;
    void window.studio!.harnessView!(active && !blocked && !!status?.ready,offline,true).catch(e => {if(current)setError(String(e));});
    return()=>{current=false;};
  },[active,blocked,status?.ready,offline,native]);
  async function start(isOffline:boolean) {
    setBusy(true); setError(''); setOffline(isOffline);
    try {
      if (native) await window.studio!.harnessView!(true,isOffline);
      else {
        const response=await api<Status & {url:string}>('/harness/start','POST',{offline:isOffline});
        setUrl(response.url); setStatus(response);
      }
      await refresh();
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if (!active) return null;
  const readyView=native && !!status?.ready;
  const showEntry=!native || (!!status && !status.ready) || (!status && !!error);
  return <section className="harness-pane" aria-label={t('Harness')} data-view-ready={readyView} aria-busy={busy || !status}>
    {/* Native view restoration is asynchronous. Never leave the startup hero
        underneath an already-loaded view, including during modal/mode toggles. */}
    {showEntry && <div className="harness-entry">
      <div className="harness-mark"><SquareTerminal size={28} strokeWidth={1.75}/></div>
      <span className="harness-eyebrow">GOOGLE CLOUD · BATCH AGENT</span>
      <h1>Harness</h1>
      <div className="harness-entry-actions">
        <button className="harness-primary" disabled={busy || !status?.available} onClick={() => void start(false)}>
          {busy ? <LoaderCircle size={16} className="spin"/>:<Play size={16}/>} {t(busy ? '正在启动':'打开 Harness')}
        </button>
        <button className="icon-button" aria-label={t('刷新')} onClick={() => void refresh()}><RefreshCw size={16}/></button>
        {status?.running && !native && <button className="harness-secondary" disabled={busy} onClick={()=>void stop()}>{t('停止')}</button>}
      </div>
      {url && !native && <a className="harness-browser-link" href={url} target="_blank" rel="noreferrer"><ExternalLink size={14}/>{t('打开浏览器界面')}</a>}
      {status && !status.available && <div className="harness-notice">{t('Harness 可选组件尚未安装。')}</div>}
      {status?.validation_required && <div className="harness-notice">{t('工具实际仅支持读取；文件写入尚未接入。')}</div>}
      {error && <p className="harness-error" role="alert">{error}</p>}
    </div>}
    {native && !status && !error && <div className="harness-restoring" role="status"><LoaderCircle size={18} className="spin" aria-hidden/><span>{t('正在连接 Harness')}</span></div>}
    {readyView && error && <div className="harness-resume-error" role="alert">{error}<button className="harness-secondary" onClick={()=>void refresh()}>{t('刷新')}</button></div>}
  </section>;
}
