# Remote tool response audit

The authenticated GPU Bridge JSON boundary now removes host/account metadata for every module. The local management UI remains separate. User prompts, project content and useful rendering/voice parameters are not translated or rewritten.

| Surface | Finding | Change |
| --- | --- | --- |
| Upload names | Tripo prefixed filenames with local wall-clock time | New names use UUIDs; old input handles are returned as persistent random aliases |
| Time fields | Offset timestamps and timezone labels could expose environment details | Normalize retained timestamps to UTC; omit timezone/locale metadata; run Tripo Node with `TZ=UTC` |
| Status | Upstream returned credential source, device flags, local gallery URL and subscription identity | Keep authentication availability, queue counts, readiness and credit totals only |
| Regional metadata | Region/account/country fields and service/CDN domains could identify a site | Remove metadata fields and Tripo remote URLs; use scoped result download handles |
| Errors | Provider domains, local paths, IPs and region names could appear in errors | Apply the boundary filter to errors and JSON embedded in MCP text |
| Project text reads | A separate file-text path bypassed structured result filtering | Apply the same host/zone text filtering to that path |
| HTTP headers | Default server header disclosed Python runtime details | Return a generic bridge server header |
| Tool definitions | Upstream output schemas still required fields intentionally removed for privacy | Omit upstream output schemas; retain upstream validation of input parameters |
| Scheduler | Accepted counter exceeded schema maximum after reaching maximum concurrency | Saturate counters; clamp old/new scheduler state and concurrency to 3 |

Validation performed without paid submissions:

- Complete Python test suite, including HTTP boundary and nested MCP response tests.
- The real upstream ledger accepted 5,000 acceptance events and 5,000 congestion events, persisted/reloaded successfully, and clamped a legacy concurrency of 10 to 3.
- From the VPS: list tools; query status, capabilities, workflows, workflow log and models; scan returned JSON; verify minimal status and concurrency 3.
- From the VPS: upload a test image, confirm a random filename, download and verify SHA-256; download an existing generated GLB and verify its original SHA-256.

The filter covers plugin-generated JSON metadata and designated project text reads. It cannot retract information already delivered, remove region clues authored in project/media content, sanitize arbitrary binary assets, or provide OS sandboxing for unrestricted scripts. Those are separate boundaries; this audit does not claim they are covered by a JSON filter.
