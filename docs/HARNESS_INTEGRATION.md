# Harness integration

Current implementation: [Harness Agent features](HARNESS_FEATURES.md).
Model routes: [Harness models](HARNESS_MODELS.md).
Cost estimates: [Harness costs](HARNESS_COSTS.md).
Optional payload: [Harness component](HARNESS_COMPONENT.md).

Python owns credentials, Batch submissions, request receipts and usage estimates.
DSH owns sessions, tools, permission presets and human approval. Tauri displays
its independent local child WebView. The scoped Node token cannot configure
Studio or read Google credentials; the child has no Studio native-command access.
The fixed DSH submodule is d743267388641bc76f17c45ce8b4c231aed1d32c, MIT licensed.

Use the project's pinned Python, frontend and Node dependencies. Initialize the
submodule, build the upstream artifacts, then assemble harness/component using
harness/build_component.mjs. The generated profile uses absolute paths and is
regenerated when starting the component after relocation. Launch DSH only through
its official profile. Development preview data is separate from installed user
data. See HARNESS_COMPONENT.md for the build and local packaging commands.

The model adapter preserves native Gemini tool calls, signatures and ordered tool
responses. Each model request is one frozen JSONL row submitted as its own Batch
job. Unknown submissions are reconciled before another job may be created. SSE
reports local receipt status; complete returned content is displayed without fake
model streaming. Context and retained history are packed into subsequent requests.

No build/check command starts a paid cloud generation automatically. Historical
cloud and offline observations are retained in HARNESS_ACCEPTANCE.md. The latest
change has basic offline write/command/approval checks, not a complete live-cloud
writable-Agent acceptance matrix. This development branch is not published
automatically as a GitHub release.
