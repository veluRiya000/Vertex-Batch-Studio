import {readFile,mkdir,writeFile,rename,unlink} from 'node:fs/promises';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

export const defaultPersona='You are a coding agent powered by the {{model}} model.';
const maxChars=16000;
function settingsPath(home) {
  if(!home)throw new Error('Harness home is unavailable');
  return join(home,'vbs-persona.json');
}
function validate(text) {
  if(typeof text!=='string'||!text.trim()||text.length>maxChars)throw new Error('Invalid persona text');
  return text;
}
export async function readPersona(home=process.env.DSH_HOME) {
  let text=defaultPersona;
  try {text=validate(JSON.parse(await readFile(settingsPath(home),'utf8')).text);}
  catch(error) {if(error.code!=='ENOENT')throw error;}
  return {text,default_text:defaultPersona,max_chars:maxChars};
}
export async function savePersona(text,home=process.env.DSH_HOME) {
  validate(text);
  const target=settingsPath(home),temporary=target+'.'+randomUUID()+'.tmp';
  await mkdir(home,{recursive:true});
  try {await writeFile(temporary,JSON.stringify({version:1,text}),{encoding:'utf8',flag:'wx'});await rename(temporary,target);}
  finally {await unlink(temporary).catch(error=>{if(error.code!=='ENOENT')throw error;});}
  return {text,default_text:defaultPersona,max_chars:maxChars};
}
export function formatPersona(text,model) {
  const name=typeof model==='string'?model:(model?.id||model?.model||'Gemini');
  return '[用户配置的角色与回答风格]\n以下内容覆盖默认角色描述，不改变工具权限、审批、预算及 Batch 执行规则。\n'+validate(text).replaceAll('{{model}}',name);
}
export function personaSettingsHandler({authorize,home=process.env.DSH_HOME}) {
  return async(req,res)=>{
    if(!['GET','POST'].includes(req.method)){res.writeHead(405,{allow:'GET, POST'});res.end();return;}
    if(!authorize(req,res))return;
    if(req.method==='POST'&&req.headers.origin!==`http://127.0.0.1:${req.socket.localPort}`){res.writeHead(403);res.end();return;}
    const json=(code,value)=>{res.writeHead(code,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});res.end(JSON.stringify(value));};
    try {
      if(req.method==='GET'){json(200,await readPersona(home));return;}
      const chunks=[];let bytes=0;
      for await(const chunk of req){bytes+=Buffer.byteLength(chunk);if(bytes>65536){json(413,{error:'提示词过长'});return;}chunks.push(Buffer.from(chunk));}
      let value;
      try {value=JSON.parse(Buffer.concat(chunks).toString('utf8'));}
      catch {json(400,{error:'请求格式错误'});return;}
      if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['text','reset'].includes(k))||('reset' in value&&value.reset!==true)||('reset' in value&&'text' in value)){
        json(400,{error:'请求格式错误'});return;
      }
      const text=value.reset===true?defaultPersona:value.text;
      try {validate(text);}catch {json(400,{error:'请输入角色提示词，最多 16000 个字符'});return;}
      json(200,await savePersona(text,home));
    }catch {json(500,{error:'无法读取或保存角色提示词，请重试'});}
  };
}
