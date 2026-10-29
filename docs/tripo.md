# Tripo Studio

Tripo Studio 接在现有的 GPU 模块里，和 Godot、Blender、VRoid 共用同一个桥、同一个 Orca Toolkit 入口。远程 Claude 多一个 `tripo-local` MCP 命名空间，用的是**你自己的 Tripo Studio 会员账号和积分**（网页端），不是 Tripo 的 API 积分。

账号、专用浏览器 profile 和登录会话只在 Windows 本机。VPS 只能看到工作流工具，看不到也碰不到凭据；文件以 `tripo:inputs/...`、`tripo:archive/...` 这样的代号进出，本机路径不出本机。

## 依赖

- 本机已装 GPU Bridge（[部署](gpu-bridge.md)），Node.js 22+，Google Chrome 或 Microsoft Edge。
- 第三方运行包 [Ador-able/tripo-studio-mcp](https://github.com/Ador-able/tripo-studio-mcp)（非 Tripo 官方，走 Studio 网页当前的接口；网页改版时需要更新）。直接安装到 Bridge 的独立目录：

```powershell
python scripts/install-tripo.py
```

安装器把上游引用解析成固定提交，再下载仓库中已经编译的包。默认安装到 `%LOCALAPPDATA%\LocalGpuBridge\tripo\plugins\<版本>`。也可用 `--ref <提交>` 固定来源，或 `--bundle <已编译包目录>` 离线安装。

桥自己持有 `mcp/bootstrap.mjs` 和后台的生命周期，不需要安装、启动或登录 Codex，也不连接 Codex 的 MCP 服务。已有的 Codex 插件缓存不会再作为默认安装来源；如果旧配置显式设置了 `plugin_cache`，应删除该字段或改到上述独立目录。

## 国内站和国际站

在桥的配置（`scripts/gpu-settings.local.json` 或已安装的 `%LOCALAPPDATA%\LocalGpuBridge\config.json`）里选区域：

```json
"tripo": {"region": "cn"}
```

| region | 站点 | 接口 | 数据目录 | 调试端口 / 服务端口 |
| --- | --- | --- | --- | --- |
| `global`（默认） | studio.tripo3d.ai | api.tripo3d.ai | `%LOCALAPPDATA%\TripoStudioMCP` | 9222 / 32175 |
| `cn` | studio.tripo3d.com | api-cn.tripo3d.com | `%LOCALAPPDATA%\TripoStudioMCP-cn` | 9223 / 32176 |

两个站的账号和积分不互通。上游只支持国际站；`cn` 时桥生成一份中国站运行包，适配站点地址、服务端口、独立单实例锁及 Cookie 会话恢复。中国站使用浏览器会话，不依赖只接受国际站凭据名的原生密码 helper。运行包采用版本、补丁号和源码摘要组成的不可变目录，避免 Windows 被旧进程占用时替换失败。每个补丁都要求原文本恰好出现一次；上游结构改变时明确报错，不生成半截运行包。

可选字段：`plugin_cache`（插件缓存目录）、`data_dir`、`asset_root`（默认 `Documents\TripoStudio`，上传的图放在其中的 `bridge-inputs`）、`browser`（固定用哪个浏览器）。

国内站上传使用临时令牌返回的百度 BOS S3 兼容地址，校验域名并按区域签名，不使用 AWS 加速端点。依据：[BOS 服务域名](https://intl.cloud.baidu.com/en/doc/BOS/s/xjwvyq9l4-intl-en)。未知存储地址会明确拒绝，避免把临时凭据发送到任意主机。

服务重启后，读取已有的运行中 Action 会恢复后台观察器，只查询既有任务，不重发生成请求。取消工作流会停止本机后续步骤；已提交的云端任务可能无法取消，取消结果中的提示为准，不代表退款。

中国站运行包的任务并发固定为 3；接受与拥塞计数按持久化 schema 上限饱和，避免达到最大并发后计数溢出、任务已扣分但工作流记账失败。读取旧状态时也会限制并发，无需依赖反复清空状态文件。

## 远端信息最小化

GPU Bridge 的远端 JSON 出口统一过滤本机身份、网络地址、区域、账号资料、时区字段和已知服务域名；嵌套在 MCP 文本中的 JSON 同样过滤。Tripo 的签名链接不下发，结果使用受限下载句柄。状态工具只返回登录是否可用、队列及积分，不返回登录来源、凭据存储、设备标志、本地画廊地址或会员身份。原上游 outputSchema 不再公开，以免继续声明已删除的私有字段；输入参数验证仍由上游完成。

保留的时间统一为 UTC。新上传文件使用随机编号；历史带本机时间的输入路径在新返回中使用持久化随机别名，原有句柄仍可用。Node 子进程固定使用 UTC，不修改 Windows 或 VPS 的系统时区。

过滤针对插件附加的环境与账号元数据，不改写用户项目中的中文、配音语言、模型内容或图片像素。原始模型、项目文件等二进制内容不在 JSON 过滤范围内，也不能撤回 Claude 已经收到的信息。任意脚本仍有既有本机文件权限，因此返回过滤不是操作系统安全沙箱。

## 自启动

配置了 `tripo` 时，桥启动就把 Tripo 插件的后台拉起来，之后每分钟检查一次，挂了就重启；登录脚本运行期间暂停，不和登录窗口抢 profile。桥本身随 Windows 登录启动，[登录助手](../tools/orca-startup/) 掉线时会拉起桥，并在 `startup.log` 里记录 `tripo` 状态（`connected`、`starting`、`not-installed`、`unavailable`）。

## 登录（每台电脑一次）

```powershell
python scripts/tripo-login.py            # 按配置的 region
python scripts/tripo-login.py --region cn
```

它先停掉插件的后台服务，再用有界面的浏览器打开专用 profile。在里面正常登录（国内站可用手机号、微信），看到工作台后关窗口。之后插件用无头浏览器复用这个 profile 读取会话，不保存密码。会话过期时 `tripo_get_status` 显示 `authenticated:false`，再跑一次登录脚本即可。登录期间不要在 VPS 上提交 Tripo 任务。

国内站也支持导入用户明确提供的现有会话 Cookie：

```powershell
python scripts/tripo-login.py --region cn --cookie
```

在隐藏提示中输入 `ory_kratos_session` 的值，不要把 Cookie 放进命令行参数、配置文件或脚本。工具先向 `auth-cn.tripo3d.com` 验证会话，再在本机专用浏览器 profile 中保存；不输出 Cookie/JWT，也不上传给 VPS。到期后可重新导入，或使用上面的网页登录流程。导入期间暂停 Tripo 调用，关闭后后台会重新读取浏览器会话。

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
