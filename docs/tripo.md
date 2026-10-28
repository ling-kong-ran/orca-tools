# Tripo Studio

Tripo Studio 接在现有的 GPU 模块里，和 Godot、Blender、VRoid 共用同一个桥、同一个 Orca Toolkit 入口。远程 Claude 多一个 `tripo-local` MCP 命名空间，用的是**你自己的 Tripo Studio 会员账号和积分**（网页端），不是 Tripo 的 API 积分。

账号、专用浏览器 profile 和登录会话只在 Windows 本机。VPS 只能看到工作流工具，看不到也碰不到凭据；文件以 `tripo:inputs/...`、`tripo:archive/...` 这样的代号进出，本机路径不出本机。

## 依赖

- 本机已装 GPU Bridge（[部署](gpu-bridge.md)），Node.js 22+，Google Chrome 或 Microsoft Edge。
- 第三方插件 [Ador-able/tripo-studio-mcp](https://github.com/Ador-able/tripo-studio-mcp)（非 Tripo 官方，走 Studio 网页当前的接口；网页改版时需要更新）。装在本机的 Codex 里：

```powershell
codex plugin marketplace add https://github.com/Ador-able/tripo-studio-mcp.git --ref main --json
codex plugin add tripo-studio-mcp@tripo-studio --json
```

桥直接启动插件自带的 `mcp/bootstrap.mjs`，不需要 Codex 一直开着。

## 国内站和国际站

在桥的配置（`scripts/gpu-settings.local.json` 或已安装的 `%LOCALAPPDATA%\LocalGpuBridge\config.json`）里选区域：

```json
"tripo": {"region": "cn"}
```

| region | 站点 | 接口 | 数据目录 | 调试端口 / 服务端口 |
| --- | --- | --- | --- | --- |
| `global`（默认） | studio.tripo3d.ai | api.tripo3d.ai | `%LOCALAPPDATA%\TripoStudioMCP` | 9222 / 32175 |
| `cn` | studio.tripo3d.com | api-cn.tripo3d.com | `%LOCALAPPDATA%\TripoStudioMCP-cn` | 9223 / 32176 |

两个站的账号和积分不互通。上游插件只认国际站；国内站用的是同一套 `/v2/studio/...` 接口，所以 `cn` 时桥在 `%LOCALAPPDATA%\LocalGpuBridge\tripo\cn\<版本>` 放一份插件副本，只改三个站点地址、凭据名和本机服务端口，每一处都要求在原文件里恰好出现一次。上游改了写法时桥会报 “needs a bridge update”，不会打出半截补丁。上游插件升级后，下次调用会自动重做副本。

可选字段：`plugin_cache`（插件缓存目录）、`data_dir`、`asset_root`（默认 `Documents\TripoStudio`，上传的图放在其中的 `bridge-inputs`）、`browser`（固定用哪个浏览器）。

## 自启动

配置了 `tripo` 时，桥启动就把 Tripo 插件的后台拉起来，之后每分钟检查一次，挂了就重启；登录脚本运行期间暂停，不和登录窗口抢 profile。桥本身随 Windows 登录启动，[登录助手](../tools/orca-startup/) 掉线时会拉起桥，并在 `startup.log` 里记录 `tripo` 状态（`connected`、`starting`、`not-installed`、`unavailable`）。

## 登录（每台电脑一次）

```powershell
python scripts/tripo-login.py            # 按配置的 region
python scripts/tripo-login.py --region cn
```

它先停掉插件的后台服务，再用有界面的浏览器打开专用 profile。在里面正常登录（国内站可用手机号、微信），看到工作台后关窗口。之后插件用无头浏览器复用这个 profile 读取会话，不保存密码。会话过期时 `tripo_get_status` 显示 `authenticated:false`，再跑一次登录脚本即可。登录期间不要在 VPS 上提交 Tripo 任务。

不支持从别的浏览器导出 cookie：会话只在这个专用 profile 里。

## VPS 端

用现有的 VPS 安装器或 marketplace 更新插件（[GPU 部署](gpu-bridge.md) 第 4 节），在已开的 Claude 会话里 `/reload-plugins`。`tripo-local` 的工具列表运行时从桥上拉取：

| 工具 | 作用 |
| --- | --- |
| `tripo_get_status` | 登录状态、余额、后台队列 |
| `tripo_get_workflow_capabilities` | 全部操作和 JSON Schema（生图、四视图、生成模型、拆分、补全、重拓扑、贴图、放大、PBR、绑骨、动画） |
| `tripo_start_workflow` / `tripo_get_workflow` / `tripo_list_workflows` / `tripo_get_workflow_log` / `tripo_cancel_workflow` / `tripo_retry_workflow` | 提交、查询、取消、从头重试 |
| `tripo_list_models` / `tripo_get_model` / `tripo_list_images` / `tripo_get_image` / `tripo_list_templates` | 账号里的模型、图片和模板 |
| `tripo_upload` | 把 VPS 上的图或模型（40 MB 以内）送到本机，返回 `tripo:inputs/...` |
| `tripo_download` | 把结果（`tripo:archive/...`、`tripo:assets/...`）下载到 VPS 目录，带 SHA-256 |

`tripo_set_account`、`tripo_clear_account`、`tripo_open_gallery` 不对 VPS 开放。工具和操作说明由桥换成英文后下发，schema 里的非 ASCII 说明会去掉，VPS 端看不到站点区域。

带 `may_consume_credits` 的步骤会扣会员积分。`INSUFFICIENT_CREDITS` 直接报告，不重试；`OUTCOME_UNKNOWN` 表示远端可能已经在跑，不要重新提交。

## 桥接接口

`GET /v1/tripo/status`、`GET /v1/tripo/tools`、`POST /v1/tripo/call {name, arguments}`、`POST /v1/tripo/upload {filename, content_base64}`、`GET /v1/tripo/file?path=tripo:...`。与其他接口一样要求 Bearer token 和 Tailscale 来源白名单。
