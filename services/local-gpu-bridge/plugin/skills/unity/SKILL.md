---
name: unity
description: Operate an approved Unity project on the private GPU worker through the unified toolkit.
---

Development stays on the VPS. Commit and push there, then use `project_git` to update the approved local render mirror. Do not assume any local drive letter or request arbitrary local directories.

1. Read `local_projects` and `local_status`. Unity and its dedicated CLI must be installed, licensed locally, and network isolation ready.
2. Call `unity_start` with the approved project ID. Initial import/compilation can take time. It starts only the managed Editor, with graphics enabled; it cannot activate licenses or accept software terms.
3. Read `unity_tools` for that project. Use only the actual returned names and input schemas with `unity_call`. The official Pipeline package must be installed locally. If the only exposed operation is the CLI status tool, inspect its readiness result and wait for import; a missing package or license needs local setup.
4. Save scene/asset changes through exposed Editor tools. Viewport capture must use the Editor's capture tools. Desktop screenshot fallback, shell, machine/account/network diagnostics, and arbitrary C# eval are not exposed.
5. Entering Play mode is not proof the game advances. Verify gameplay progress and capture a rendered viewport. Reuse approved project file download tools for saved assets, or inline view captures returned by Unity.
6. A timeout or broken connection may follow a completed edit. Inspect scene/editor state before repeating. Do not automatically retry writes. `unity_stop` stops only the managed project and can discard unsaved changes; save first.

Qualified adapters in `unity_tools` restore otherwise ambiguous operations: `console.get` reads compiler/console errors (`level="error"`); `console.status` reads counts; `test.list`, `test.run`, `test.status` list/start/poll tests; `build.run`, `build.status` validate/start/poll Player builds. Tests always start asynchronously. For build validation use `dry_run=true`; actual builds require `confirm=true`, existing Assets/*.unity scenes, and project-relative Builds/ output paths. Poll status before retrying any operation. `package.list`, `package.search`, `package.add`, `package.status` use Package Manager; package.add accepts exact registry name@version only. Missing test-framework or build support should be diagnosed from the returned structured error. Package Manager is a separate process: do not infer downloads fail merely because the managed Editor has external networking blocked.

Responses are filtered at the GPU Bridge's remote boundary. Never query or encode host identity, public IP, timezone, credentials, or local environment information in scripts/assets. Unity project code still executes on the local account; the integration is not a full OS sandbox.
