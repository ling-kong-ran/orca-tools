---
name: tripo
description: Generate and post-process 3D models (image/text/multiview to 3D, retopology, textures, PBR, rigging, animation) with the user's own Tripo Studio membership through the tripo-local MCP tools on the GPU computer.
---

Use tripo-local, not a browser, shell or direct calls to Tripo web endpoints. The Tripo account, its browser profile and session stay on the GPU computer; this side never sees or handles credentials. Which Studio site and account are used is configured on the GPU computer; nothing here depends on it.

Start with tripo_get_status. session.authenticated=false means the user has to sign in once on the PC with scripts/tripo-login.py; tell them, do not retry in a loop. Account tools (set or clear the account, open the gallery) are not exposed here on purpose.

Workflow:
1. tripo_get_workflow_capabilities returns every operation with its JSON Schema, which results it produces and whether it may spend credits.
2. Local inputs: first tripo_upload(path=absolute VPS file). It returns tripo:inputs/<name>; put that string where a step wants image_path, front/left/back/right, reference_images, model_path or render_image_path.
3. tripo_start_workflow(name, steps) only validates and queues, then returns workflow_id at once. Chain steps with the result types listed in the capabilities (asset_id, project_id).
4. Poll tripo_get_workflow(workflow_id) with reasonable delays (30-60 s for models); tripo_get_workflow_log explains failures. Results name files as tripo:archive/... or tripo:assets/...; fetch them with tripo_download(path, destination_dir=absolute VPS folder).

Credits: steps marked may_consume_credits spend the user's membership credits. Do not start a paid workflow the user did not ask for. INSUFFICIENT_CREDITS is final: report it, never retry. OUTCOME_UNKNOWN means the request may already be running remotely: never resubmit; only tripo_retry_workflow on the user's explicit request (it creates a new workflow and can charge again).

model.generate tier smart_mesh is the game-ready low-poly mesh; high_detail is the dense model. Set face_limit for game props. Text or images with sensitive content need allow_sensitive explicitly.
