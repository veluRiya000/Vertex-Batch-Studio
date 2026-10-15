# Buffered native Batch continuation

Argon responses ending in `CONTINUATION` or `MAX_TOKENS` with a valid
`candidates[0].continuationToken` are checkpointed, then continued in another
one-row Batch job. Original contents, system instructions, tools, thinking
settings and tool configuration remain unchanged. No synthetic user "continue"
message or partial assistant history is inserted. There is no real-time API
fallback. Native long-decode support in Batch still requires a live user test;
Google documents this protocol for GenerateContent v1beta1, not explicitly Batch.

The original request ID and fingerprint identify one logical model step.
Each segment has separate frozen JSONL, output prefix, raw result, job display
name and submission intent. Unknown creates reconcile against their own segment;
they are never blindly resubmitted. Paid usage is settled per segment and summed
once. Subsequent input includes prior decoded tokens for conservative reserves;
cache discounts apply only when returned by Google. Each paid segment consumes
one request from the run limit. Continuation can cost more and take longer.

Only a final STOP releases merged content to DSH. Parts stay distinct and signed
metadata is preserved, following Google SDK merge semantics. Incomplete streaming
arguments and duplicate native tool-call IDs are rejected. Incomplete requests
never execute write/edit/PowerShell/present/batch_finish. Raw segments remain on
disk even if continuation is cancelled, invalid, expired, blocked, or truncated.

With limits enabled, the configured output cap covers the whole generation,
including thoughts. Budget and request guards apply before each new Batch.
With limits disabled, a native continuation raises its output target to Argon's
remaining unified window (1,048,576 minus original input), not infinity. The
initial request retains the previous omitted-cap behavior. Flash/Pro have no
assumed native long-decode support. Missing tokens, repeating tokens, no progress,
malformed responses or unified-window exhaustion stop explicitly.

Cancel stops the chain and targets the current accepted cloud job. A crash keeps
cloud monitoring but requires explicit resume before creating another paid
segment. Already-ended historical requests are not silently resumed or billed.
The activity panel shows buffered segment count, generated tokens and each
segment's queue state, without exposing opaque continuation tokens.

Reference: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon
