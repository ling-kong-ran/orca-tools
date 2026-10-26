---
name: vroid
description: Create and edit local VRoid Studio characters through the project-scoped vroid-local MCP tools, inspect model previews and save .vroid projects.
---

Use vroid-local, not shell or raw TCP. Start with vroid_tools and local_projects. The managed Studio instance starts on first operation; its first bootstrap can take several minutes. Network isolation must be ready.

Do not confuse editor startup with model readiness. A successful state reply has editor_connected=true. phase=awaiting_model, in_edit=false and model_ready=false mean Studio is already running at the model selection screen: call create or open immediately, according to the user's intended character. Waiting cannot open a model. phase=loading_model/updating_model means a character operation is in progress; phase=editing means it is ready. status only describes the command queue. Never start a two-minute background wait just because there is no open character.

Use vroid_operation with an enabled project_id, operation and arguments. Workflow: state, create(gender) or open(path), categories(section), presets/enter(section,category), select_preset or set_param, camera, screenshot, save(path). Section/category names are case-sensitive; discover exact labels instead of guessing. Numeric/color parameter paths come from enter and are not filesystem paths. Model previews are inline MCP images without the editor UI.

open/save require project-relative .vroid paths; save always needs path and replace=true if the file exists. Keep the original model unless replacement was intended. Save before main_menu, which requires explicit discard_changes=true. Destination directories must already exist. Download saved project files with download_project_file. Development sync uses Git only; do not add a second upload path.

Mutation calls block while the model rebuilds. A timeout can mean the operation is still running: query status before repeating. Never poll screenshot during rebuilds. Do not query host identity, hardware or network information. No batch, UI screenshot, shell, raw protocol or diagnostic bypass is available.

Upstream 1.0.0 does not expose VRM export. Do not invent an export operation or claim a .vroid save is a VRM export. VRM files exported by Studio can be edited/rendered with Blender and its separately installed VRM Add-on. Local rendering is on the PC; do not install another VRoid Studio on the VPS.
