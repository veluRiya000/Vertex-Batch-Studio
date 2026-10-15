import {brokerCredentials} from '../broker-credentials.mjs';
/** Token-based amber palette for the upstream DSH web surface. */
import {readFileSync} from 'node:fs';
import {cloudSettingsHandler} from './navigation.mjs';
import {personaSettingsHandler} from '../persona.mjs';
import {attachmentPolicy} from '../attachment-policy.mjs';
import {runSettingsHandler,readRunSettings} from '../run-settings.mjs';
export const inject = ['webServer','connection'];
export function apply(ctx) {
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/vbs/run-settings',handler:runSettingsHandler({authorize:(req,res)=>ctx.connection.authorizeIndex(req,res)})}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/vbs/persona',handler:personaSettingsHandler({
    authorize:(req,res)=>ctx.connection.authorizeIndex(req,res),
  })}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/vbs/open-cloud-settings',handler:cloudSettingsHandler({
    authorize:(req,res)=>ctx.connection.authorizeIndex(req,res),
    brokerUrl:brokerCredentials.url,
    brokerToken:brokerCredentials.token,
  })}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/vbs/open-notification-settings',handler:cloudSettingsHandler({
    authorize:(req,res)=>ctx.connection.authorizeIndex(req,res),
    brokerUrl:brokerCredentials.url, brokerToken:brokerCredentials.token, tab:'notifications',
  })}));
  const css=readFileSync(new URL('./theme.css',import.meta.url),'utf8');
  const videoOverlay=readFileSync(new URL('./video-overlay.js',import.meta.url),'utf8');
  const focusedPaging=readFileSync(new URL('./focused-paging.js',import.meta.url),'utf8');
  ctx.on('webserver/index-inject', rows => {
    rows.push({kind:'style',text:css});
    rows.push({kind:'script',placement:'body',text:focusedPaging});
    rows.push({kind:'script',placement:'body',text:'window.__VBS_ATTACHMENT_POLICY__='+JSON.stringify(attachmentPolicy)+';\n'+videoOverlay});
    rows.push({kind:'script',placement:'body',text:"document.title='Vertex Studio · Harness';"});
  });
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/vbs/activity',async handler(req,res) {
    if(req.method!=='GET'){res.writeHead(405);res.end();return;}
    if(!ctx.connection.authorizeIndex(req,res))return;
    try {
      const offline=process.env.VBS_HARNESS_OFFLINE==='1';
      const base=brokerCredentials.url;
      if(!offline && !/^http:\/\/127\.0\.0\.1:\d+$/.test(base || ''))throw Error('Broker unavailable');
      const result=offline ? [] : await fetch(base+'/harness/requests',{headers:{'X-VBS-Harness-Token':brokerCredentials.token}});
      if(!offline && !result.ok)throw Error('Broker rejected');
      const values=offline ? result : await result.json();
      const requests=values.map(({request_id,run_id,session_id,step_id,phase,created_at,updated_at,job_name,error,reserved_usd,actual_usd,cost_estimate,truncated,budget_usd,max_rounds,limits_enabled,local_recovery,continuation,submission_intent})=>({request_id,run_id,session_id,step_id,phase,created_at,updated_at,job_name,error,reserved_usd,actual_usd,cost_estimate,truncated,budget_usd,max_rounds,limits_enabled,local_recovery,continuation,submission_intent}));
      res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
      res.end(JSON.stringify({offline,requests,limits:await readRunSettings()}));
    } catch {res.writeHead(503);res.end('Batch activity unavailable');}
  }}));
}
