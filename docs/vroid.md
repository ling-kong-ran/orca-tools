# VRoid Studio

VRoid is part of the existing GPU module and the same Orca Toolkit management entry. It adds the `vroid-local` MCP namespace on the remote Claude side, not another Orca plugin.

## Dependencies and installation

Supported upstream combination: **VRoid Studio 2.14.0 / Unity 6000.0.62**, [vroid-studio-mcp 1.0.0](https://github.com/brainrom/vroid-studio-mcp), and BepInEx IL2CPP build 788. The upstream adapter uses internal editor APIs, so newer Studio versions need a compatibility check. Windows and the existing GPU Bridge must already be installed.

Run from this repository on Windows, using your own installed Studio path:

```powershell
python scripts/install-vroid.py --studio 'D:\SteamLibrary\steamapps\common\VRoid Studio'
```

The installer copies Studio to the bridge data directory under `native/vroid`, gives its executable a dedicated name, verifies pinned dependency SHA-256 values, and configures loopback MCP plus offline Unity libraries. It leaves the original installation and model library untouched. `--data-dir` changes the bridge data root; `--download-cache` can point to a folder containing the three pinned ZIPs for offline installation. The installer refuses to overwrite an existing managed copy. Third-party licenses remain in the installed dependency directories; the binaries and Studio itself are not distributed by this repository.

When no jobs are running, restart the bridge using its existing installer/startup mechanism. The automatic persistent firewall setup now includes the dedicated VRoid executable; Windows may require its administrator prompt for the first rule installation. Never remove the existing renderer rules. VRoid starts on the first tool operation. Its editor window is shown without taking keyboard focus, because a fully hidden Unity window can return black previews on Windows. Preview/camera calls restore only that managed window without taking focus. The first IL2CPP bootstrap can take several minutes. It does not need public internet access.

Update the remote plugin with the existing VPS installer or marketplace update, then run `/reload-plugins` in existing Claude sessions. A new session loads the new namespace automatically. The local management page shows VRoid installation, connection and network isolation alongside Godot and Blender.

## Operations

Start with `vroid_tools` and `local_projects`, then call `vroid_operation(project_id, operation, arguments)`:

MCP 1.5.1 distinguishes editor startup from character readiness. A successful `state` returns `editor_connected:true`. `phase:awaiting_model`, `in_edit:false` and `model_ready:false` mean Studio is running without an open character: call `create` or `open` next. Waiting will not load a model. `loading_model`/`updating_model` refer to a character operation; `editing` means the character is ready. `status` only reports the command queue.

| Operation | Example arguments |
| --- | --- |
| state / status / sections | `{}` |
| create | `{"gender":"female"}` or `male` |
| open | `{"path":"assets/avatar.vroid"}` |
| categories | `{"section":"Face"}` |
| enter / presets | `{"section":"Face","category":"Irises"}`; use actual returned category names |
| select_preset | `{"section":"Face","category":"Irises","index":1,"params":true}` |
| set_param | `{"section":"Face","category":"Irises","path":"<returned parameter path>","value":"#44AA88"}` |
| camera | `{"action":"frame","region":"face","angle":"front"}` |
| screenshot | `{}`; returns an inline preview image |
| preset_preview_list / preset_preview_range | section, category, indexes or start/count; at most 12 previews |
| save | `{"path":"assets/avatar.vroid"}`; add `replace:true` for existing files |
| export_vrm | `{"path":"assets/avatar.vrm","format":"1.0","title":"Avatar","author":"Artist"}`; add `replace:true` for existing files |
| main_menu | Save first, then `{"discard_changes":true}` explicitly clears the edit state |
| help | `{"topic":"colors"}` or presets/hair/camera/sessions/values |

Paths for open/save are always relative to an enabled project, and saves require an explicit path. Prepare destination folders through project development/Git. Existing project file tools can download `.vroid` files to the VPS using its receiver clock. `set_param.path` is an editor parameter identifier, not a filesystem path. Section/category labels are case-sensitive. Create/open block until the editor is ready; do not poll screenshots while it rebuilds. After a timeout, query `status` before repeating a mutation.

Toolkit 1.6 adds **automatic VRM export** to the upstream adapter. Install its Studio extension after the first managed Studio startup has generated the IL2CPP references. Save and close the managed Studio before replacing its assembly (leave the original Studio installation alone):

```powershell
python scripts/install-vroid-export.py
```

Requires the .NET SDK with .NET 6 targeting-pack support (tested with SDK 10). The installer downloads a SHA-256-verified source archive pinned to upstream revision `ab9ad4f90d6ba6486a234a975c86e3298ccfd75e`, applies the repository's export extension, builds against your local interop assemblies, backs up the original DLL, and installs the new assembly and upstream license. It refuses to replace a running managed editor. `--source-archive` supports offline builds; `--build-only path/to/VroidStudioMcp.dll` compiles without changing the installation. No proprietary Studio binaries or generated interop assemblies are redistributed. Start Studio through the bridge and update/reload the VPS plugin. Update the idle bridge with the normal installer to load its new allowlist.

Call `export_vrm` with `{"path":"assets/avatar.vrm","format":"1.0","title":"Avatar","author":"Artist"}`; use `"format":"0.0"` for VRM 0.x and explicit `replace:true` to overwrite. The destination directory must exist. Studio uses its real native export coroutine, waits for completion, validates the GLB container, publishes the completed file, and returns to the edit screen. The bridge returns a project-relative path, format and byte count. Failed/unfinished exports do not replace the destination. One export can take several minutes; after a transport timeout check `status` and the destination before retrying.

Export metadata starts fresh with explicit title/author and no copied local contact/reference fields. Bridge 1.6.3 defaults to `license_preset:"commercial_modifiable"`: commercial use (including corporations), modification and redistribution are allowed, with attribution required. It writes VRM 1.0 permission fields or VRM 0.x `CC_BY` metadata atomically before returning the export receipt; geometry, textures, title and author remain intact. Use `license_preset:"restrictive"` for author-only, non-commercial exports without modification or redistribution. These settings do not remove obligations attached to source assets. To update an existing approved project file without re-exporting, call `set_vrm_license` with `{path:"assets/avatar.vrm",replace:true,license_preset:"commercial_modifiable"}`. The exported file still includes standard application/version and model metadata; hardware, network diagnostics and local absolute paths are not added to the receipt. Download the artifact with `download_project_file`, or import it directly using Blender `import_asset` in the same approved project. Automatic export of real test characters in both formats and import into Blender were verified. Custom-preset management and unexposed editor features remain unsupported.

Use [VRM Add-on for Blender](https://vrm-addon-for-blender.info/) for Blender import/export, MToon materials and VRM metadata. Install the Blender extension with `python scripts/install-blender-vrm.py` on Windows after the GPU Bridge is installed. It downloads the pinned official 4.10.2 extension (or accepts `--archive` for offline installation), verifies SHA-256, keeps the managed Blender firewall in force, and preserves normal user preferences. The managed factory-startup worker explicitly enables VRM and its preference object without auto-saving factory defaults. Save/stop an existing managed Blender when upgrading its worker; the next operation starts the new worker. MCP 1.5.2 `scene_info` reports `capabilities.vrm_import/vrm_export`; `import_asset` and `export_asset` support approved project-relative `.vrm` files. Blender Python can also use the installed operators. `.vroid` project editing remains in Studio; `.vrm` is a separate export format.

## Privacy

The Studio MCP/TCP listeners remain on loopback. Only the authenticated, source-allowlisted Tailscale bridge is reachable from the VPS. The adapter forwards an explicit operation allowlist, validates project paths, filters text with the existing network/hardware/path filter, drops resource links, and strips PNG metadata. Full-window screenshots, developer tools, arbitrary batches, raw commands, arbitrary endpoints, shell and implicit in-place saves are not exposed. The persistent firewall blocks public/LAN egress from the dedicated Studio executable. Tailscale encryption is transport protection; the output filter is not a general sandbox for malicious software or intentionally encoded data.

## Existing sessions with cached tool definitions

If `vroid_tools` lists `export_vrm` but `vroid_operation` rejects it with `Invalid option for operation`, the Claude session still has an older operation enum. That validation happens before the request reaches Studio. Bridge 1.6.2 supports the existing `save` operation as a compatibility route: use the same project-relative `.vrm` path, title, author, optional format and replace arguments. It invokes the identical native exporter with the same path, metadata, overwrite and privacy checks. A `.vroid` path still saves editable source. This route works without restarting the session; alternatively `/reload-plugins` refreshes its schema.

New MCP schemas discover operation names through `vroid_tools` rather than freezing them into an enum, while the bridge retains the strict server-side allowlist. Toolkit 1.1.2 starts both the GPU bridge and ComfyUI when the enabled GPU module activates; it does not open a browser automatically. Previously activation started only ComfyUI, leaving remote MCP unavailable until the local GPU page was opened.
