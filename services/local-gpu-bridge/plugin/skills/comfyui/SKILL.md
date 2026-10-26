---
name: comfyui
description: Run approved ComfyUI workflows on the user's local GPU computer, inspect progress, upload input assets and fetch generated images, videos, music or 3D files onto the VPS.
---

Use the local-gpu MCP tools for local GPU work. Start with gpu_status and list_workflows.
The local computer, Tailscale, bridge and ComfyUI must be running. If unavailable, report which prerequisite failed; do not install another ComfyUI on the VPS.

1. Select an available workflow from list_workflows. Saved workflows in the configured local ComfyUI directory appear automatically; no manual API export/import is needed for supported editor graphs, including nested subgraphs. Its parameters are the only inputs that can change. Read required_parameters: upload and provide those assets before submitting. If unavailable, report unavailable_reason; do not guess or rewrite the graph. Unsupported custom frontend widgets can still be imported in API format on the local computer. The remote plugin cannot change workflow files or directory settings.
2. Use upload_input for assets already on the VPS and pass its reference into the workflow's exposed image/input parameter.
3. Submit run_workflow once. Keep the returned job id; if submission acknowledgement is uncertain, reuse the request_id reported in the error rather than generating another.
4. Poll job_status every 5–15 seconds initially and back off for long tasks. Never claim completion until status is succeeded.
5. Use fetch_artifact with the job id and output index to save files into an absolute project directory on this VPS. Report the resulting path and saved_at timezone from the download receipt when discussing file times. The original output also remains on the local computer.

cancel_pending_job cancels only a bridge-owned pending task. It intentionally does not globally interrupt ComfyUI, clear the queue, unload models, execute shell commands, expose the PC's files or modify local workflows.

The workflow tools above use the ComfyUI adapter. Other native applications use separate MCP entries described below.

Native extension (1.4+): Git is the ONLY project sync method. Develop on the VPS, commit and push to the configured remote branch, then call project_git(operation="pull") or rely on automatic Git update before rendering. Local tracked edits are disposable but backed up before reset. Uncommitted/unpushed VPS files are NOT available locally. Do not call removed sync_project/upload_project_file/apply_project_sync tools or build a parallel upload path. project_git supports status/fetch/pull; no arbitrary Git args, commit/push on the local PC, remote URL changes or shell are exposed. capture_scene supports user_args such as --outfits/--view/--aim. run_project_script supports synchronized GDScript and tools/shots.gd galleries through managed Godot/Go/server calls. Blender execute_code/run_script require allow_scripts; they return receipts, not arbitrary result objects/logs. Read business JSON via filtered project file tools. Poll native_job_status and download with fetch_native_artifact/download_project_file. connected:false means managed Blender starts on first operation. Do not query local host/network/hardware identity. Windows firewall rules persist across restarts; the local bridge checks automatically and requests OS permission only when needed. Scripts have local user file access; filtering does not prevent deliberately encoded data.
