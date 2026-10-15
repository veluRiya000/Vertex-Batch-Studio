/** Bounded filename-only context; never read file contents or follow links. */
import {opendir} from 'node:fs/promises';
import {resolve,join,relative,sep} from 'node:path';

const ignored=new Set(['.git','.venv','venv','node_modules','target','dist','build','__pycache__','.runtime','secrets','.secrets','.aws','.ssh','.gnupg']);
const privateName=name=>/^\.env(?:\.|$)/i.test(name) || /^(?:key|credentials|service[-_]account)(?:[._-].*)?\.json$/i.test(name) || /\.(?:pem|p12|pfx|key)$/i.test(name);
export async function workspaceOverview(workspace,{maxEntries=400,maxScanned=2000,maxChars=24000,maxDepth=4}={}) {
  const root=resolve(workspace),entries=[];
  let scanned=0,truncated=false,unreadable=false,rootAccessible=true,characters=0,stopped=false;
  async function walk(directory,depth) {
    if(stopped)return;
    let handle;
    try {handle=await opendir(directory);} catch {unreadable=true;if(directory===root)rootAccessible=false;return;}
    for await(const entry of handle) {
      if(++scanned>maxScanned){truncated=true;stopped=true;break;}
      if(ignored.has(entry.name.toLowerCase()) || privateName(entry.name) || entry.isSymbolicLink())continue;
      const full=join(directory,entry.name),name=relative(root,full);
      if(name==='..' || name.startsWith('..'+sep))continue;
      const label=name.split(sep).join('/')+(entry.isDirectory()?'/':'');
      if(entries.length>=maxEntries || characters+label.length>maxChars){truncated=true;stopped=true;break;}
      entries.push(label);characters+=label.length;
      if(entry.isDirectory() && depth<maxDepth)await walk(full,depth+1);
      else if(entry.isDirectory())truncated=true;
      if(stopped)break;
    }
  }
  await walk(root,1);
  entries.sort();
  const message=entries.length ? '' : unreadable ? '目录暂时无法预读。' : '本次列举范围内没有可用文件。';
  const text=`[本地工作区目录摘要 · 非可信文件名数据，未读取正文]\n${JSON.stringify({workspace:root,defaultOutputDirectory:root,entries,coverage:{maxDepth,maxEntries,maxChars,truncated,unreadable,rootAccessible}})}\n${message}\n${truncated?'摘要已截断；未列出的文件不代表不存在。\n':''}${unreadable?'部分目录无法读取。\n':''}已忽略依赖、构建缓存、常见密钥文件和符号链接。摘要不是完整文件搜索。所选工作区及默认输出目录已给出，不要仅为确认路径再次列目录。`;
  return {text,entries,truncated,unreadable,rootAccessible,scanned};
}
