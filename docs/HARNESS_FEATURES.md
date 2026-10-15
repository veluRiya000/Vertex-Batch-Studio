# Harness Agent development build

## Current capabilities

The Batch adapter now supplies the tools registered for the current DSH session,
including file reads, create/write, literal edits, PowerShell, planning, questions,
Skills and any manually configured MCP tools. Removed browser, voice, Office,
delegation and DeepSeek providers remain disabled. Generation remains Google Cloud
Batch-only; no realtime provider is substituted.

File and command execution use DSH's existing confining providers, per-session
permission presets and one-shot approval UI. New sessions default to
workspace-write with escalation approvals. Existing session selections are
preserved. Read-only mode still denies writes unless a wider one-shot operation
is approved. Missing confinement stops affected tools instead of spawning through
an unrestricted fallback. User-selected full access keeps its upstream meaning.

The upstream filesystem observation policy is retained: existing files must be
observed before replacement, stale versions are rejected, new files are created
without overwriting concurrent creations, and successful changes carry diffs.
Standing workspace sandbox ACLs are provisioned before the first model request
in workspace-write mode so initialization cannot invalidate newly observed file
versions. PowerShell inherits the upstream 7 / Windows 5.1 executable resolution.

Windows confinement restricts file effects, not all reads, network or processes.
MCP servers do not automatically inherit the file sandbox. Enable external
servers deliberately. No MCP connection is enabled by default.

## Local run-limit switch

Harness Settings → Batch 运行 → 启用运行限额 is enabled by default.

- Enabled: the saved maximum output, per-task gross USD budget and model-request
  count are enforced. Defaults remain 65,536 output tokens / $5 / 20 requests.
- Disabled: the adapter omits the custom maxOutputTokens field and the broker
  ignores the budget and request-count ceilings. The cloud uses its model's
  default output allowance. Token accounting, pricing and displayed reservations
  remain available; their values do not stop the run.
- The switch takes effect on the next request, including later tool steps of an
  active run. It does not mutate an already-submitted input or restart a paused
  task automatically. Budget/count value changes still apply to new tasks.
- Explicit stop/pause, tool approval, file conflicts and cloud model constraints
  remain effective in both modes. This does not implement million-token Batch
  continuation or make a truncated tool call executable.

The setting is persisted in data/harness/home/vbs-run-settings.json. New settings
and settings without limitsEnabled default to limits disabled. Explicit saved
choices are preserved. Old request/run records remain readable and keep their
existing interpretation; already-submitted inputs are not rewritten. The private
run API defaults the optional limits_enabled boolean to false for new runs.

## Delivery and basic checks

Development root: D:\文件\vetexbatchstudio. Double-click Restart-Studio.cmd after
finishing active work and saving drafts to load the updated backend/component.
The image studio remains separate. Sessions, credentials and user workspaces are
not cleared. Preview component archives are local artifacts, not public releases.

Focused offline checks exercised real file create/edit, saved UTF-8 content,
PowerShell stdout, read-only denial, the visible one-shot approval before a write,
and the persisted run-limit switch. Model requests were offline substitutes.
Focused broker checks verify no budget/count pause with limits disabled, no custom
output field, continued cost accounting, and continued explicit pause enforcement.
No paid cloud test, full fault-injection matrix or new public release was run.

## Remaining delivery work

Full interrupted-turn recovery UI, richer workspace prepacking, a component
import/upgrade/rollback installer and the broad fault matrix remain future work.
DSH's existing session, tool, sandbox and approval implementations are reused;
the pinned upstream checkout is not edited.

## Bridge credential isolation

The private local broker token is captured in the Node plugin module and removed
from the process environment before tool subprocesses start. The basic command
check fails if that token is inherited. Google credentials remain in Python.
Typed Gemini parameter schemas follow the provider's published Schema fields:
https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/Schema


### Batch 回传与本地收尾恢复

结果关联会核对冻结请求。Cloud Storage 将重复记录中的数组字段补成空数组时，只有原始请求在相同结构路径包含该数组字段，才接受这类补字段；提示词、工具内容、数组顺序及实际参数变化仍会被拒绝。

启动时会重新核对因旧关联规则失败、且已下载到本地的结果。只有唯一一行、正常 STOP、纯文字的最终答复才自动恢复，并按返回用量更新费用估算。恢复不会联网、提交付费作业或执行工具，不恢复含工具调用或截断的响应。原会话的失败历史保留，活动栏显示找回的收尾答复；原任务保持暂停。


### Single-request Batch delivery

The adapter exposes an explicit `batch_finish` terminal tool. For a deliverable
whose complete contents and local steps are already known, the model can return
write/edit/foreground-command operations, optional file presentation, and a final
`batch_finish` carrying the full final reply in ONE Batch response. The finish
tool runs as an exclusive barrier after the earlier tools have finalized.

Only authoritative successful outcomes allow `concludeTurn()`. Failed/denied
writes, missing results, new tool context requiring model attention, background
commands, nonzero exits, timeouts and aborts do not finish locally. File cards in
this delivery sequence are also denied if a preceding operation failed, so an
old file cannot be presented as a newly generated deliverable.

After all tool results commit, the turn-stopping hook appends the model-authored
summary as an ordinary final assistant message prefixed **本地交付已确认**. This
does not generate another cloud request, fabricate usage, or replay any action.
The original signed model response and function-call/result pairing stay intact.
The summary's successful local display is distinct from a second model answer.

This is explicit completion, not a heuristic that ends after every write. Discovery,
unknown file contents, necessary test analysis and unfinished work retain normal
multi-step execution. Pure text replies finish normally without this tool.

Focused offline UI regression: `python harness/verify_batch_delivery.py` (requires
Playwright and Chromium in the test Python environment). It uses an isolated home,
scrubs credential environment variables, and verifies a real file write, file
cards and final reply from exactly one offline model response; rejected writes
continue without false success; one-shot approval remains required before the
write; subsequent messages preserve valid history. No paid model request is made.


### Local completion persistence correction

The local delivery summary is appended after its terminal tool result commits,
while the same step remains open. It is never appended at `agent/turn-stopping`,
which follows `step/end`. Event observers defer publication to a microtask to
avoid reentrant Session writes, and verify the open step again before appending.
Full persistence/reopen validation must cover local-completion changes; checking
only the running conversation is insufficient.
