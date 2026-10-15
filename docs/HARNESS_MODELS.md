# Harness Batch models

The existing DSH composer model selector supports these Google Cloud routes:

| Display name | Exact API model ID | Default thinking | Documented output limit |
| --- | --- | --- | --- |
| Gemini 4 Argon | `gemini-4-argon` | MEDIUM | Long decoding up to the shared model window; native Batch continuation remains unimplemented |
| Gemini 3.8 Flash | `gemini-3.8-flash` | MEDIUM | 65,536 tokens |
| Gemini 3.1 Pro Preview | `gemini-3.1-pro-preview` | HIGH | 65,536 tokens |

Click the model caption, open **模型**, then select a route. The selection is
used for request construction, token counting, Batch submission and cost
estimation. A model stays frozen throughout a running turn's tool loop; a menu
change applies to the next turn. Model-native replay signatures are retained
within that model and are not copied to a different model's request.

Output settings are not silently clamped. Flash/Pro reject configured values
above their documented output limit locally with a message before submission.
Global endpoint, credentials, image handling and text-attachment preloading are
shared. The image-generation mode and its separate model catalog are unchanged.

Request records freeze the exact model and price schedule. Budget reservation
and final usage estimates use that model's global Batch rates before promotional
credits and caching discounts; Pro's input threshold above 200,000 tokens uses
the longer-context rate. Estimates are not Cloud Billing totals. Promotion and
credit balances are not deducted locally. Prices were verified 2026-10-15.

Supported models are based on the official model cards and Batch support list;
project-level access is verified only when the user starts a real request. There
is no fallback to another model or synchronous generation after an error.

Sources:
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-pro
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/batch-inference
- https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing

Offline acceptance covers all three menu choices, a Flash tool round followed
by a Pro attachment turn, per-model token/submission routing, immutable request
identity, output validation, turn freezing and signed replay handling. No real
cloud generation requests are created by the acceptance suite.
