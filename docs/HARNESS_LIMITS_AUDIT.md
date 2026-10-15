# Harness limits audit — 2026-10-15

## Removed acceptance restrictions

| Restriction | Current behavior |
| --- | --- |
| Adapter silently capped output at 8,192; codec capped it again at 32,768 | Removed both clamps. Output is configurable in Harness Settings → Batch 运行. Default: 65,536 tokens including thoughts and final text. |
| Broker forced every task to $0.50 and 3 requests | Removed. New tasks use configured budget/rounds; defaults are $5 / 20. Existing requests and run budgets stay frozen. |
| Arbitrary 200,000 input-token ceiling / 232,768 advertised context | Removed. Input plus requested output must fit the model's actual 1,048,576 total-token window. |
| Local budget ceiling $300 and round ceiling 100 | Removed. Positive finite budgets and positive integer rounds are still validated. |
| Every MAX_TOKENS response was hidden as failure, including generated prose and usage | Preserved and displayed as incomplete output with usage. Incomplete function calls are excluded from execution and replay. No automatic paid continuation. |

Settings are saved locally in `data/harness/home/vbs-run-settings.json`.
Output changes apply to the next request. Budget/round changes apply to new tasks.
Run-scoped reservations prevent concurrent rounds from overspending the configured
budget; exhaustion pauses rather than silently increasing it.

## Actual service constraints

Argon uses a shared 1,048,576-token input + thinking + output window.
Google documents ordinary single-request output separately from million-token
long decoding. Million-token continuations are documented for GenerateContent;
this app remains Batch-only and has not implemented that continuation protocol.
The local setting accepts values up to the total model window without substituting
a smaller value, but the cloud may reject or truncate unsupported Batch values.
The 65,536 default is not a claim of a verified live Batch maximum. No new paid
request was automatically submitted during this change.

Sources:
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon?hl=en
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/migrate

## Remaining unfinished features / explicit limits

Update 2026-10-15: [HARNESS_FEATURES.md](HARNESS_FEATURES.md) supersedes the earlier read-only tool restriction. Registered file/command tools now use the existing DSH sandbox and approval pipeline. The local run-limit switch is implemented; disabled mode omits custom output caps and skips budget/count checks.

- Text attachment preloading: 256 KiB per file and 512 KiB total, with explicit
  skipped status; large files remain accessible through local reads. This prevents
  accidental binary/credential inclusion and huge attachment expansion. It does
  not cap the model's generated output.
- Workspace overview is a bounded filename list, not a full project-content
  prepack; dependency/build/secret paths are omitted. Rule-file intake is bounded
  at 64 KiB; large tool results may be pruned by DSH to an 8,192-character threshold
  with head/tail preserved. These context limits should be considered when full
  Agent integration is completed.
- One active task per workspace and at most two workspaces remain, as agreed in
  the original plan. This prevents overlapping file edits and does not shorten
  generated text.
- Video skipping remains enabled by the user's explicit request, independently
  switchable in `attachment-policy.mjs`. Native audio/PDF/video transfer and native
  million-token Batch continuation remain unimplemented.
- Automatic retries do not create new paid jobs for uncertain submissions. Tool
  arguments must be complete, signatures must be preserved, and broken/auth-blocked
  responses stop. These guards are retained.

## Verification

Offline tests cover values above 8K/32K and above prior budget/round caps,
settings persistence and validation, model-total checks before submission,
partial-text retention with usage, suppressed truncated tool calls, turn release,
and continued refusal to duplicate an uncertain paid job. Live cloud requests
were not resubmitted.


## Observed cloud default truncation (2026-10-15)

A recorded Argon Batch with local limits disabled omitted maxOutputTokens. Its
returned usage was 207,790 input tokens + 30,518 candidate tokens + 2,250 thinking
tokens, exactly 32,768 generated tokens. It returned MAX_TOKENS with a continuation
token; the unfinished write call was retained raw but never executed. A saved
655,360 output setting did not apply in disabled mode. No extra paid request was
made to test or continue it.

The interface now explicitly labels disabled mode as unlimited LOCAL budget/count,
warns that the stored output number is not sent, and identifies cloud MAX_TOKENS
without implying that disabling the switch guarantees unlimited output. This is
a clarification, not a long-decode implementation. Google documents long decodes
on v1beta1 GenerateContent; safe continuation via the Batch path still requires
separate verification and implementation. Do not treat a normal follow-up user
message as lossless continuation of an unfinished function call.


## Native continuation update

The earlier 32,768-token truncation diagnosis remains historical. Native token-based
Batch continuation is now implemented; see [HARNESS_CONTINUATION.md](HARNESS_CONTINUATION.md).
Offline tests use deterministic providers. Batch acceptance of continuation tokens
still requires a user-started real cloud check; no real-time fallback is used.
