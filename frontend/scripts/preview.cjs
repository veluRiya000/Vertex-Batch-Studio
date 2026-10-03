// Local browser launcher. Keeps monitoring alive after the browser window closes.
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const root = path.resolve(__dirname,'../..'), frontend = path.join(root,'frontend'), runtime = path.join(root,'.runtime')
fs.mkdirSync(runtime,{recursive:true})
const pause = ms => new Promise(resolve=>setTimeout(resolve,ms))
function start(program,args,name,cwd=root) {
  const log=fs.openSync(path.join(runtime,name+'.log'),'a')
  const child=spawn(program,args,{cwd,windowsHide:true,detached:true,stdio:['ignore',log,log]})
  fs.closeSync(log);child.unref()
  return child
}
async function backendReady() {
  try {
    const value=JSON.parse(fs.readFileSync(path.join(runtime,'connection.json'),'utf8'))
    if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(value.url))return false
    const response=await fetch(value.url+'/health',{headers:{'X-VBS-Token':value.token},signal:AbortSignal.timeout(1000)})
    return response.ok
  }catch{return false}
}
async function previewReady(url) {
  try {const response=await fetch(url+'/api/health',{signal:AbortSignal.timeout(1000)});return response.ok && (await response.json()).status==='ok'}catch{return false}
}
async function main() {
  if(!await backendReady()) {
    start(path.join(root,'.venv/Scripts/python.exe'),['-X','utf8','-m','backend','serve','--port','0'],'preview-backend')
    for(let i=0;i<100&&!await backendReady();i++)await pause(200)
    if(!await backendReady())throw new Error('Backend did not start. See .runtime/preview-backend.log')
  }
  const url='http://127.0.0.1:5173'
  if(!await previewReady(url)) {
    start(process.execPath,[path.join(frontend,'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','5173','--strictPort'],'preview-frontend',frontend)
    for(let i=0;i<100&&!await previewReady(url);i++)await pause(200)
    if(!await previewReady(url))throw new Error('Preview did not start; port 5173 may be occupied. See .runtime/preview-frontend.log')
  }
  console.log('Vertex Batch Studio: '+url)
  if(!process.argv.includes('--no-open'))spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',"Start-Process '"+url+"'"],{windowsHide:true,stdio:'ignore'})
}
main().catch(error=>{console.error(error.message);process.exitCode=1})
