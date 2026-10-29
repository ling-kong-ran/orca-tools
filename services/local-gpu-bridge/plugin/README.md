# Local GPU

This Claude Code plugin lets a VPS submit existing ComfyUI workflows to your own GPU computer over an existing Tailscale connection. Saved workflows in configured local folders appear automatically, including supported editor-format graphs and nested subgraphs. Read availability and required_parameters before running. Prompt, seed, size, sampling and asset parameters are exposed; models, devices and output paths stay fixed. Unsupported frontend widgets require a local API-format import. The local bridge and ComfyUI must be running. Credentials stay in the OS user's private configuration directory and are not included in the plugin. Running local jobs and unrelated ComfyUI queue items are never globally interrupted by this plugin.

After installation start a new Claude session, check `/mcp`, and ask Claude to check the local GPU and list approved workflows. Use `/local-gpu:comfyui` for the bundled workflow instructions.

Version 1.4 uses Git as the only project sync path. Commit and push on the VPS; project_git status/fetch/pull and automatic update before rendering keep the local mirror current. Local tracked edits are discarded without backup when resetting to the configured remote branch. No legacy project upload tools or generic shell are exposed. Godot user_args/project scripts and Blender Python remain available. Windows firewall rules persist; output metadata filtering remains active. For deployment see the repository's docs/gpu-bridge.md.

Request IDs can be reused with identical inputs. Re-submitting a confirmed failed request creates a new job with attempt/retry_of metadata; poll the new returned job ID. Active, successful, unknown and cancelled attempts are returned without resubmission. Never change inputs under the same request ID. Status polling itself does not retry. This is backward-compatible bridge behavior; existing MCP clients need no schema update.

Downloaded ComfyUI/native/project files use the receiving VPS clock for access/modification times at transfer completion. Download receipts include saved_at with a timezone offset, timezone, and timestamp_source=receiver. Unix timestamps represent an absolute instant; file-browser displays can still use the viewer’s timezone.

VRoid Studio (1.5+): vroid-local provides vroid_tools and vroid_operation, sharing approved projects and file downloads. See docs/vroid.md in the repository for pinned local installation and scope. Toolkit 1.6 adds export_vrm after installing scripts/install-vroid-export.py on the PC: explicit project .vrm path, title/author and optional format 1.0|0.0/replace.

Tripo Studio (1.7+): tripo-local exposes the GPU computer's Tripo Studio workflow tools for the user's own membership account (the site is chosen on the PC with tripo.region), plus tripo_upload and tripo_download for files. Account tools stay on the PC. See docs/tripo.md in the repository and /local-gpu:tripo.

Blender VRM (1.5.2+): install the official VRM extension on the Windows computer with scripts/install-blender-vrm.py. The managed factory-startup instance enables it automatically. scene_info reports capabilities.vrm_import/vrm_export. import_asset/export_asset accept .vrm project paths; this does not convert .vroid projects directly. Use vroid_operation(export_vrm) for the initial Studio export; .vroid remains the editable source.

Unity (1.8+): unity-local starts/stops a managed approved Editor, discovers official Pipeline tools and invokes them through the private bridge. No shell, arbitrary C# eval or desktop fallback. Install an LTS Editor, activate its license locally, install com.unity.pipeline, and configure dedicated Editor/CLI copies. See docs/unity.md.
