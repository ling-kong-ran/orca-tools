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
| main_menu | Save first, then `{"discard_changes":true}` explicitly clears the edit state |
| help | `{"topic":"colors"}` or presets/hair/camera/sessions/values |

Paths for open/save are always relative to an enabled project, and saves require an explicit path. Prepare destination folders through project development/Git. Existing project file tools can download `.vroid` files to the VPS using its receiver clock. `set_param.path` is an editor parameter identifier, not a filesystem path. Section/category labels are case-sensitive. Create/open block until the editor is ready; do not poll screenshots while it rebuilds. After a timeout, query `status` before repeating a mutation.

The upstream 1.0.0 adapter does **not expose VRM export**, custom-preset management or all editor features. It cannot claim those operations succeeded. Export a `.vrm` through Studio when needed, then use [VRM Add-on for Blender](https://vrm-addon-for-blender.info/) for Blender import/export, MToon materials and VRM metadata. Blender automation can use the existing `blender_operation` Python interface once that add-on is installed. `.vroid` project editing remains in Studio; `.vrm` is a separate export format.

## Privacy

The Studio MCP/TCP listeners remain on loopback. Only the authenticated, source-allowlisted Tailscale bridge is reachable from the VPS. The adapter forwards an explicit operation allowlist, validates project paths, filters text with the existing network/hardware/path filter, drops resource links, and strips PNG metadata. Full-window screenshots, developer tools, arbitrary batches, raw commands, arbitrary endpoints, shell and implicit in-place saves are not exposed. The persistent firewall blocks public/LAN egress from the dedicated Studio executable. Tailscale encryption is transport protection; the output filter is not a general sandbox for malicious software or intentionally encoded data.
