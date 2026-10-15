import {readFile,mkdir,writeFile,rename,unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

export const modelContextTokens=1048576;
export const defaultRunSettings=Object.freeze({maxOutputTokens:65536,budgetUsd:5,maxRounds:20,limitsEnabled:false});
export function validateRunSettings(value) {
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!Object.hasOwn(defaultRunSettings,k)))throw Error('运行参数格式错误');
  const settings={...defaultRunSettings,...value};
  if(typeof settings.limitsEnabled!=='boolean')throw Error('运行限额开关必须是布尔值');
  if(!Number.isSafeInteger(settings.maxOutputTokens)||settings.maxOutputTokens<1||(settings.limitsEnabled&&settings.maxOutputTokens>modelContextTokens))throw Error('输出额度须为 1–1048576 Token；云端单次能力及总上下文限制仍适用');
  if(!Number.isFinite(settings.budgetUsd)||settings.budgetUsd<=0)throw Error('任务预算必须大于零');
  if(!Number.isSafeInteger(settings.maxRounds)||settings.maxRounds<1)throw Error('模型请求轮数必须为正整数');
  return settings;
}
const path=home=>{if(!home)throw Error('Harness home unavailable');return join(home,'vbs-run-settings.json');};
export async function readRunSettings(home=process.env.DSH_HOME) {
  try{return validateRunSettings(JSON.parse(await readFile(path(home),'utf8')));}
  catch(error){if(error.code!=='ENOENT')throw error;return {...defaultRunSettings};}
}
export async function saveRunSettings(value,home=process.env.DSH_HOME) {
  const settings=validateRunSettings(value),target=path(home),tmp=target+'.'+randomUUID()+'.tmp';
  await mkdir(home,{recursive:true});
  try{await writeFile(tmp,JSON.stringify(settings),{encoding:'utf8',flag:'wx'});await rename(tmp,target);}
  finally{await unlink(tmp).catch(e=>{if(e.code!=='ENOENT')throw e;});}
  return settings;
}
export function runSettingsHandler({authorize,home=process.env.DSH_HOME}) {
  return async(req,res)=>{
    if(!['GET','POST'].includes(req.method)){res.writeHead(405);res.end();return;}
    if(!authorize(req,res))return;
    if(req.method==='POST'&&req.headers.origin!==`http://127.0.0.1:${req.socket.localPort}`){res.writeHead(403);res.end();return;}
    const json=(code,data)=>{res.writeHead(code,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});res.end(JSON.stringify(data));};
    try {
      if(req.method==='GET'){json(200,{settings:await readRunSettings(home),defaults:defaultRunSettings,context_tokens:modelContextTokens});return;}
      const chunks=[];let size=0;
      for await(const chunk of req){size+=Buffer.byteLength(chunk);if(size>4096){json(413,{error:'运行参数过长'});return;}chunks.push(Buffer.from(chunk));}
      let settings;
      try{settings=validateRunSettings(JSON.parse(Buffer.concat(chunks).toString('utf8')));}catch(e){json(400,{error:e.message});return;}
      json(200,{settings:await saveRunSettings(settings,home)});
    }catch{json(500,{error:'无法读取或保存运行参数'});}
  };
}
