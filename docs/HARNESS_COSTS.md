# Harness cost estimates

The UI reports **usage-based estimates**, **reserved maximum request cost**, and
**unresolved amounts** separately. These are USD estimates, not Cloud Billing
charges. Budget enforcement uses gross Global Batch rates before promotional or
account credits. Returned cache hits use the model's published cached-input rate.

For each returned response, input cost is `(prompt - cached + tool input) × input
rate + cached × cached-input rate`; output cost is `(candidate + thinking tokens)
× output rate`. Rates are per million tokens. Prompt tokens already include cached
tokens. Total tokens are a cross-check, not another billable output count.

Valid usage is recorded even when response validation stops malformed model
output. Missing usage stays unresolved; it is never treated as an actual charge.
Definitive validation/auth rejection without generation clears its reservation.
Repeated polling does not add another cost or submit another job.

Before each request, the backend reserves input cost plus the **requested maximum**
output cost. For example, Argon with 89,619 input tokens and a 655,360 output cap
reserves `$0.179238 + $6.553600 = $6.732838` at gross Batch rates. That request
cannot fit a $5 budget even with no previous spend. Pausing before submission
incurs no new model request. It does not mean $6.73 has been spent.

Google's current promotional Global Batch prices are Argon $1 input / $5 output
per million, with $0.05 cached input through November 30, 2026; Flash $0.375 /
$1.875, with $0.0375 cached input through December 31. Promotions are provided
as credits back on net spend. The UI shows the promotional calculation separately
without assuming account eligibility, free credits, taxes or a final invoice.
Pro Batch remains $1/$6 up to 200K input and $2/$9 above 200K, with no published
cached-input discount in its Batch table.

Historical raw files and original ledger values are retained for audit; this
change does not restart, resubmit, cancel, or alter the budget of a live task.

Sources (checked 2026-10-15):
- https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/GenerateContentResponse

## Disabled run limits

Settings → Batch 运行 → 启用运行限额 can disable budget/count admission and custom
output caps. When no output cap is sent, the displayed reservation uses 65,536
tokens as a conservative cloud-default estimate only; it does not cap or block
the request. Actual returned usage replaces that estimate. Model service limits,
explicit pause/stop and all tool approval policies remain effective.
