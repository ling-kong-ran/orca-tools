# Unity

Unity is a module of the existing Toolkit GPU Bridge. It uses the official Unity CLI's MCP server and the project package `com.unity.pipeline`. It does not depend on Codex or expose an additional public HTTP service.

## Install outside the system drive

Use an LTS Editor and the current official CLI. Example Windows layout:

| Item | Example |
| --- | --- |
| CLI install root (`UNITY_CLI_HOME`) | `D:\Apps\Unity\CLI` |
| Editors | `D:\Apps\Unity\Editors` |
| Downloads / temporary files | `D:\UnityData\Downloads` / `D:\UnityData\Temp` |
| Package cache (`UPM_CACHE_ROOT`) | `D:\UnityData\UPM` |
| Asset Store cache (`ASSETSTORE_CACHE_PATH`) | `D:\UnityData\Assets` |
| Projects | `D:\UnityProjects` |

Download the official installer from `https://unity.com/install.ps1`, inspect it, set `UNITY_CLI_HOME`, `TEMP` and `TMP`, then run it. Create the editor directory before `unity editors install-path --set <directory>`. `unity install lts --dry-run --format json` reports the exact release and size before installation. The CLI's download cache is separate: inspect `unity cache info` and relocate that cache before a large download. Windows shared licensing/configuration records may still use the OS profile/system directories; the editor binaries, project data and large caches should stay on the selected drive.

The user must sign in and accept the applicable Unity terms/activate an eligible license locally. Do not put account tokens in bridge settings or source control. Install only required build modules; the bridge does not install or purchase licenses remotely.

Create/open an approved Unity project and install Pipeline once:

```powershell
unity pipeline install --project-path D:\UnityProjects\MyProject
```

Use an Input System package compatible with the selected Editor. Pipeline 0.9.1-exp.1 references Input System APIs; in the 6000.3.27f1 verification project, `com.unity.inputsystem` 1.20.1 compiled successfully, while the CLI template's pinned 1.12.0 referenced a removed `BuildTarget.ReservedCFE` member. Check Editor compilation before diagnosing an empty MCP catalog as a transport failure.

## Bridge setup

Install/update the GPU Bridge with `scripts/install-local-gpu.py`. Configure these local-only `native` settings:

- `unity_executable`: a dedicated `Unity-LocalGpu.exe` copy beside the installed Editor's `Unity.exe` (keep the rest of its installation intact).
- `unity_cli_executable`: a dedicated `unity-cli-local-gpu.exe` copy of the CLI.
- `unity_data_dir`: non-system-drive directory for managed Unity logs, temporary files and caches.

Approve the project from the existing management page. An empty `unity_subdir` selects the approved project root; otherwise set a relative subdirectory containing `Assets`, `Packages`, `ProjectSettings`. Existing projects and Git settings are preserved. Enable Git update before opening for a render-only local mirror.

Run the existing network privacy setup. Its Unity rules apply to the dedicated Editor/CLI executables, not normal application copies; cached activation and packages must be prepared locally before use. Unity needs compiler/package-manager child processes, so its managed Windows job permits up to 128 processes and terminates the managed tree together. Editor job workers are limited to four; the higher process ceiling accommodates compiler launchers during initial import. This is not a filesystem sandbox or a guarantee against untrusted project code spawning other executables. Only sync trusted projects.

## VPS tools

Update the installed `local-gpu` Claude plugin to 1.8.0 and run `/reload-plugins` in existing Claude sessions. The new `unity-local` namespace provides the shared project/Git/file tools plus:

| Tool | Purpose |
| --- | --- |
| `unity_start` | Open only an approved project in the managed Editor |
| `unity_stop` | Stop that managed Editor; save first |
| `unity_tools` | Discover current Pipeline tool names and schemas |
| `unity_call` | Invoke one discovered tool with its typed arguments |

No CLI installation/authentication commands, generic shell, arbitrary C# eval, machine diagnostics or desktop screenshot fallback are exposed. Viewport screenshots use Unity's own view capture. All results pass through the shared remote privacy filter. The official CLI/Pipeline tool catalog can change: never guess names or parameters.

CLI 1.0.0-beta.14 can return duplicate unqualified tool names across command groups. The bridge omits every ambiguous name (including `run`) instead of risking dispatch to the wrong operation. Batch dispatch, menu invocation and audit/package refresh shortcuts are also omitted. Unambiguous viewport and editing tools remain available; recheck the catalog after upgrading the CLI.

Version 1.8.1 adds qualified adapters through the same `unity_call` endpoint: `console.get/status`, `test.list/run/status`, `build.run/status`, `package.list/search/add/status`. These use fixed CLI command groups with typed arguments and no shell. Compiler messages are preserved after privacy filtering. Tests start asynchronously; builds are validated with `dry_run=true` or explicitly started with `confirm=true`, then polled. Build output is restricted to project-relative `Builds/` and scene inputs to existing `Assets/*.unity`. Registry package additions require an exact name@version; Git/file URLs are not exposed. Package Manager can fetch packages independently of the externally blocked managed Editor; registry search for Entities was verified without changing firewall rules. A particular third-party registry/package still needs its own configuration and availability check.

Verification of 1.8.1: 128 bridge tests passed. A VPS client read an intentional C# compiler error, discovered and passed one EditMode test, validated a build, and generated a Windows Standalone Player with zero errors/warnings. The temporary compile-error source was removed and clean recompilation confirmed. This verifies the tool routes; it does not certify a game's test coverage or release readiness.
