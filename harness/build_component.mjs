import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const root=process.cwd(), upstream=path.join(root,'harness/upstream');
const revision=spawnSync('git',['-C',upstream,'rev-parse','HEAD'],{encoding:'utf8'});
if(revision.status!==0||revision.stdout.trim()!=='d743267388641bc76f17c45ce8b4c231aed1d32c')throw Error('Unexpected upstream revision');
if(process.version!=='v24.18.0')throw Error('Build with pinned Node 24.18.0');
const build=spawnSync(process.execPath,[path.join(upstream,'node_modules/tsdown/dist/run.mjs'),'--config',path.join(root,'harness/lean-preview.config.ts'),'--config-loader','native','--env.DSH_BUILD_FACE','client'],{cwd:root,stdio:'inherit'});
if(build.status!==0)throw Error('Lean preview build failed');
const out=path.join(root,'.runtime/harness-lean-'+Date.now());
const banned = name => /libreoffice|sherpa|sensevoice|speech-to-text|voice-input|experimental-inspector|inspector-profile|session-inspector|subagent|workflow-ptc|tool-workflow|ptc-runtime|llm-pi-ai|llm-deepseek|deepseek-account|deepseek-llm|inventory-deepseek|session-log-deepseek|session-title-first-prompt-llm|product-analytics|product-telemetry|session-telemetry|office-to-pdf|skill-office|ui-sidebar-browser|browser-(?:playwright|stagehand)|computer-use|web-search-deepseek|ui-settings-account|api-account-controller|ui-settings-session-log|ui-settings-web-search|ui-workflow-run/.test(name)
 || /^(?:openai|@openai\/|@anthropic-ai\/|@earendil-works\/pi-ai|chrome-devtools-mcp|@playwright\/mcp|@browserbasehq\/stagehand)/.test(name)
 || /(?:^|dsh-)(?:schedule|tool-schedule|client-ui-schedule)$/.test(name);
const cli=path.join(upstream,'apps/cli');
const roots=['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@deepseek-ai/dsh-app-boot','@deepseek-ai/dsh-home-paths','@deepseek-ai/dsh-http-proxy','@deepseek-ai/dsh-launch-environment','@deepseek-ai/dsh-cmdline','@deepseek-ai/cordis','@deepseek-ai/cordis-plugin-include','commander'];
const records=new Map(), queue=[];
function find(from,name){
 for(let dir=from;;dir=path.dirname(dir)){
  const p=path.join(dir,'node_modules',name,'package.json');
  if(fs.existsSync(p)) return path.dirname(fs.realpathSync(p));
  if(path.dirname(dir)===dir) break;
 }
 throw new Error(`Missing production dependency ${name} from ${from}`);
}
function add(src){if(records.has(src))return records.get(src);const manifest=JSON.parse(fs.readFileSync(path.join(src,'package.json'),'utf8'));
 const r={src,manifest,dependencies:{}};records.set(src,r);queue.push(r);return r;}
const first=add(cli);
first.manifest.dependencies=Object.fromEntries(roots.map(n=>[n,'*']));
first.manifest.peerDependencies={};first.manifest.optionalDependencies={};
while(queue.length){const r=queue.shift();
 const groups=['dependencies','peerDependencies','optionalDependencies'];
 for(const group of groups){let deps=r.manifest[group]??{};
  for(const name of Object.keys(deps)){
   if(banned(name)){delete deps[name];continue;}
   try {const src=find(r.src,name),m=JSON.parse(fs.readFileSync(path.join(src,'package.json'),'utf8'));
    if((m.os&&!m.os.includes('win32'))||(m.cpu&&!m.cpu.includes('x64'))){delete deps[name];continue;}
    r.dependencies[name]=add(src);
   }catch(e){if(group==='dependencies')throw e;delete deps[name];}
  }
 }
 for(const name of r.manifest.dsh?.client?.inject??[]){if(!banned(name)) r.dependencies[name]=add(find(r.src,name));}
}
fs.mkdirSync(out,{recursive:true});
fs.cpSync(path.join(root,'harness/plugins'),path.join(out,'plugins'),{recursive:true,filter:p=>!p.endsWith('.test.mjs')});
fs.copyFileSync(path.join(root,'harness/setup_profile.py'),path.join(out,'setup_profile.py'));
const destRoot=path.join(out,'upstream');fs.mkdirSync(destRoot,{recursive:true});
fs.copyFileSync(path.join(upstream,'LICENSE'),path.join(destRoot,'LICENSE'));
fs.writeFileSync(path.join(destRoot,'package.json'),JSON.stringify({name:'vertex-studio-harness-runtime',private:true,type:'module'}));
const placements=new Map();
const workspace=(src)=>!src.includes(`${path.sep}node_modules${path.sep}`);
function filtered(src,relative,isWorkspace){
 const segments=relative.split(path.sep);
 if(segments.includes('node_modules')||/\.(?:map|tsbuildinfo|pdb|d\.ts|d\.mts|d\.cts)$/.test(relative))return false;
 if(isWorkspace){if(segments.some(x=>['src','tests','test','benchmarks','.git'].includes(x)))return false;
  if(relative.startsWith('lib'+path.sep))return true;
  if(['lib','dist','assets','resources','licenses','presets','bin','scripts','skills'].includes(segments[0]))return true;
  return segments.length===1&&/^(?:package\.json|cordis.*\.yml|LICENSE.*|NOTICE.*|README.*)$/.test(relative);}
 return !segments.some(x=>['.git','test','tests','examples','benchmark','benchmarks'].includes(x));
}
function stripYaml(text){const lines=text.split('\n'),result=[];for(let i=0;i<lines.length;){
 const m=lines[i].match(/^(\s*)- id: ([\w-]+)/);if(m&&(banned(m[2])||['preset-ptc','preset-cordis','delegation','tool-web','web-search-deepseek','schedule','tool-schedule','ui-schedule'].includes(m[2]))){
  const indent=m[1].length;i++;while(i<lines.length){const line=lines[i];if(line.trim()&&!line.trimStart().startsWith('#')&&line.match(/^\s*/)[0].length<=indent)break;i++;}continue;}
 result.push(lines[i++]);}return result.join('\n');}
function place(r,dest){if(placements.has(dest))return;placements.set(dest,r);
 fs.mkdirSync(dest,{recursive:true});
 fs.cpSync(r.src,dest,{recursive:true,filter:s=>s===r.src||filtered(s,path.relative(r.src,s),workspace(r.src))});
 const m=structuredClone(r.manifest);delete m.devDependencies;delete m.scripts;
 fs.writeFileSync(path.join(dest,'package.json'),JSON.stringify(m,null,2));
 if(m.name==='@deepseek-ai/dsh-base'||m.name==='@deepseek-ai/dsh-web-app'){
  for(const file of ['cordis.patch.yml','presets/standard.patch.yml','presets/ptc.patch.yml','presets/cordis.patch.yml','presets/minimal.patch.yml']){const p=path.join(dest,file);if(fs.existsSync(p))fs.writeFileSync(p,stripYaml(fs.readFileSync(p,'utf8')));}}
 if(m.name==='@deepseek-ai/dsh-client-ui-sidebar-documentpreview'){
  for(const name of fs.readdirSync(path.join(dest,'lib')))if(name.startsWith('client.'))fs.unlinkSync(path.join(dest,'lib',name));
  fs.cpSync(path.join(root,'.runtime/lean-preview'),path.join(dest,'lib'),{recursive:true});
 }
 for(const [name,dep] of Object.entries(r.dependencies)){
  const globalDest=path.join(destRoot,'node_modules',name);const prior=placements.get(globalDest);
  if(!prior||prior.src===dep.src){place(dep,globalDest);continue;}
  place(dep,path.join(dest,'node_modules',name));
 }
}
place(first,path.join(destRoot,'apps/cli'));
fs.mkdirSync(path.join(out,'node'),{recursive:true});
const nodeBinary=process.env.VBS_HARNESS_NODE || process.execPath;
fs.copyFileSync(nodeBinary,path.join(out,'node/node.exe'));
const nodeLicense=path.join(root,'harness/licenses/Node-LICENSE.txt');
if(!fs.existsSync(nodeLicense))throw Error('Missing Node license notice');
fs.copyFileSync(nodeLicense,path.join(out,'node/LICENSE'));
const adapter=path.join(out,'plugins/vertex-batch/index.mjs');
fs.writeFileSync(adapter,fs.readFileSync(adapter,'utf8').replace('../../upstream/packages/llm/llm/lib/index.js','../../upstream/node_modules/@deepseek-ai/dsh-llm/lib/index.js'));
const report={upstreamCommit:'d743267388641bc76f17c45ce8b4c231aed1d32c',packages:[...new Set([...placements.values()].map(r=>r.manifest.name))].sort(),removedFeatures:['office-conversion','spreadsheet-preview','inspector','voice','non-vertex-providers','subagents','browser-automation','deepseek-account-telemetry']};
for(const name of report.packages)if(banned(name))throw Error('Forbidden package: '+name);
fs.writeFileSync(path.join(out,'component-manifest.json'),JSON.stringify(report,null,2));
spawnSync('python',[path.join(out,'setup_profile.py')],{stdio:'inherit'});
console.log(JSON.stringify({out,packages:report.packages.length}));
