/** Keep DSH's confining providers and shared approval policy required. */
export function requireConfinedTools(ctx,name) {
  if(['write','edit'].includes(name) && (ctx.fs?.sandboxMode===undefined || !ctx.sandboxPolicy))
    return '文件沙盒未就绪，操作已停止。请重启 Harness 后再试。';
  if(name==='pwsh' && (ctx.shell?.sandboxMode===undefined || !ctx.sandboxPolicy))
    return '命令沙盒未就绪，操作已停止。不会改用无沙盒执行。';
}
