# Historical Harness acceptance record

Current capabilities and latest basic checks: [HARNESS_FEATURES.md](HARNESS_FEATURES.md). Earlier limits below describe their dated builds.

Date: 2026-10-14. Development branch: `feature/harness-batch`.

## Verified locally

| Check | Result |
|---|---|
| Python backend regression | 115 tests passed |
| Frontend regression | 49 tests passed |
| Native bridge tests | 3 tests passed |
| Gemini wire projection | Signed content, native call IDs, truncation and token accounting checked |
| Google SDK transport | Mock transport confirms exactly one creation attempt on HTTP 500; count input includes system instructions/tools |
| DSH offline host/UI | Built and launched from the pinned upstream; no browser page errors |
| Offline tool loop | Read the isolated workspace README and returned a second-step answer through the DSH loop |
| Desktop child | Created on Windows, authenticated local page loads, separate React tree |
| Native permissions | A `studio_api` invocation from the Harness child is rejected by the webview ACL |
| Studio modal | About dialog opens after requesting the child to hide |
| Runtime lifecycle | Graceful shutdown request and offline/cloud switching guard tested |
| Narrow-window baseline | Existing fix retained; native minimum width remains 1,100 |

The current runtime is a **read-only connection acceptance build** capped at **$0.50 / 3 requests**. The target writable Agent defaults remain disabled.

## Requires human acceptance

- Real Argon model access, GCS/service-agent permissions, and actual Batch latency.
- Text completion and a real two-request file-read/tool-result cycle, including signatures and reported usage.
- Physical DPI changes, window resizing at the limit, tray restore, and closing/reopening the desktop in the user's environment.
- Manual confirmation of image draft preservation and the new setting during normal use. Automated coverage currently checks child hide/show conditions; it does not substitute for the physical-window matrix.

The testing window was handed to the user before the final interactive desktop matrix ran. The agent stopped manipulating that window. Cloud generation has not been started by the assistant.

## Deferred by the agreed gate

Context prepacking, writable tools, file-version conflict checks, full Agent resume/recovery controls, Skills/MCP end-to-end acceptance, and the separately packaged optional component follow successful cloud protocol acceptance. No GitHub Release has been published.

## First human cloud test

The user started one real Argon Batch request on 2026-10-14. From local preparation to receipt handling it took about 4 minutes 32 seconds; this is not a measurement of model generation alone. The returned line contained `INVALID_ARGUMENT` for `parameters_json_schema`, no candidates and no model usage. It did not pass the cloud acceptance gate.

Batch added null fields and empty `required` lists to heterogeneous tool schemas. The original strict equality check obscured the provider error with a receipt association failure. The adapter now uses Gemini's typed `parameters` and advertises only the four read-only acceptance tools. Result association accepts only null padding and semantically empty schema-required defaults; changed content still fails. The actual cached row now associates and reports its provider error.

18 targeted Python tests and 5 wire projection tests passed. No replacement cloud request was submitted by the assistant. Restarting the development app is required to load the changed Python and Node modules. A new human-started test is still required to confirm successful cloud inference.

## Subsequent human cloud task and content policy

The user started another task after the protocol fix. Three Argon Batch requests completed successfully: a `glob` call, its tool result followed by `grep`, and a final 3,689-character text response. Native signed history and tool results were present in subsequent frozen inputs. This demonstrates the live submission/download/tool-result/text loop; the specifically planned README-read fixture, writable sandbox acceptance and physical-window matrix remain outstanding.

The first two model rounds were spent searching an empty workspace. In response to the user's request, `vbs-batch-policy/1` now favors complete content, groups independent local actions, avoids unrelated searches, and makes subsequent requests use returned results. A bounded filename-only directory snapshot accompanies new requests as data. Five policy/context/multi-call tests and the five wire tests passed. The Node host was reloaded after the task ended and with no unsent text; the four existing request records were retained and no new model request was created. The behavioral improvement still needs a new human-started task to measure it.
