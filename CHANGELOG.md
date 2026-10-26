# Changelog

## 2026-10-27 — VRoid Studio / MCP 1.5.0

- 在现有 Toolkit GPU 模块加入 vroid-local：通过本机编辑器 API 新建/打开角色、预设和参数调整、镜头、预览与 .vroid 保存。
- 独立 Studio 副本、固定依赖校验、离线 IL2CPP 启动、持久防火墙与按需启动。
- 项目相对路径及显式覆盖、文本信息过滤、仅模型预览及 PNG 元数据清除；不暴露原始命令、整窗截图或通用 shell。
- 增加部署步骤和上游 API 限制说明；上游 1.0.0 尚无 VRM 导出工具。

## 2026-10-26 — Windows 音频产物与 VPS 文件时间 / MCP 1.4.1

- 修复 SaveAudioAdvanced 等节点返回 Windows 反斜杠子目录时，桥接过滤掉已保存音频的问题；保留路径越界检查。
- 支持从 ComfyUI history 恢复旧成功任务的空产物列表，无需重新生成音效。
- ComfyUI、Godot/Blender 产物和项目文件下载统一按接收 VPS 时钟设置文件时间，回执明确保存时间和时区。
- 增加 Windows 路径、旧任务恢复、三类下载及非整点时区的回归测试。

## 2026-10-26 — 失败任务复用 request_id

- Git/Godot/Blender 与 ComfyUI 支持同 request_id、同参数重新提交已失败任务，创建新一轮 job，保留原记录。
- 返回 attempt/retry_of，按持久化轮次选择最新任务；并发重试去重，服务重启后仍然有效。
- 进行中、成功、未知或已取消的任务保持原结果；更改参数仍拒绝。现有 MCP 工具接口兼容，无需 reload plugin。
- 增加并发、恢复、限流、参数绑定及 ComfyUI 重试测试。

## 2026-10-25 — GitHub SSH 代理排错文档

- 补充 GitHub SSH 443 经本机 SOCKS 代理、Windows OpenSSH 与 MSYS SHELL 兼容问题的配置和验证步骤。
- 说明 GitHub 代理应只匹配对应 Host，保留 Tailscale 私网 SSH 与主机密钥校验。

## 2026-10-25 — Go 离线构建缓存路径修复

- 修复 GOENV=off 隐藏用户配置的 Go 模块/编译缓存位置，导致已下载依赖仍报 module lookup disabled 的问题。
- 受管构建使用明确的本机缓存路径；安装器读取并保存原 Go 缓存配置。保留 GOPROXY=off、固定工具链及现有网络隔离。
- 增加缓存环境与安装器回归测试。

## 2026-10-24 — ComfyUI 自动启动 / Toolkit 1.1.1

- 修复桥接已自启但 ComfyUI 未启动，导致重启后工作流不可用的问题。
- 本机配置 comfy_startup 后，桥接登录启动、Toolkit 激活及 GPU 入口均可启动现有 ComfyUI；仅回环监听，沿用现有模型和输入/输出目录。
- 跨进程启动锁防止重复实例；等待占用端口，不中断现有队列，失败记录本机日志。配置和启动参数不暴露给 VPS。

## 2026-10-24 — Orca Toolkit 1.1.0

- Accounts 改为本机内置页面，直接通过已配对 Orca 连接列出和选择远程账号，保留邮箱遮罩、用量与重置倒计时。
- 不再依赖远程浏览器页、worktree 或单独的 VPS 账号面板；切换校验当前选择、连接和结果，已有 Claude 会话保持原账号。
- Downloads 增加远程目录/文件选择器、筛选和隐藏文件选项，按远程环境记住上次目录及文件地址。
- 继续沿用一个插件、回环管理 API、Host/Origin/token 校验；远程浏览仅使用固定只读 RPC。

## 2026-10-24 — Orca Toolkit 1.0.1

- Downloads 增加 Browse 文件夹选择按钮，保留手动输入路径。
- Windows 原生目录选择支持中文和空格；取消不改变原目录，记录上次选择或成功用于下载的目录。
- 目录选择接口沿用本机 Host/Origin/token 校验，不向 VPS 传输本机目录，不开放任意 shell。
- 继续仅分发一个 Orca Toolkit 插件；原有 GPU 管理页面及后台服务保持各自职责。

## 2026-10-24 — GPU Bridge 配音修复

- Qwen3 TTS 开放语言、预设音色与朗读风格参数；语言/音色使用节点 enum 验证，保留设备与模型路径过滤。
- 增加跨进程单实例锁并关闭 Windows HTTP 端口复用，避免重复启动导致管理页和私网接口版本不一致。
- 修复任务恰好在 history/queue 两次查询之间完成时被误判 unknown 的竞争窗口。
- 增加中文/英文调用说明、参数测试、单实例及完成状态竞争测试。

## 2026-10-24 — Orca Toolkit 1.0.0

- 合并为一个 Orca Toolkit 插件，内部分 Accounts、Downloads、GPU 模块。
- 增加 18774 统一管理页与模块设置，下载页面合入同一服务。
- 下载记录与断点保留原目录，旧设置可迁移；远程目标变更前检查未完成任务与未清理访问。
- 故障模块不阻止整个工具集启动；登录助手只激活 Toolkit。
- 后台账号服务、GPU 服务及远程 MCP 继续独立运行，保留既有隔离与凭据边界。

## 2026-10-24 — 仓库首版

- 整理 Account Switcher、Parallel Downloads、GPU Workflows、Local GPU Bridge 与自启助手源码。
- 将旧部署的个人 IP、用户路径、项目名称和 Python 路径改为配置项；未导入真实账号、token、私钥、日志和素材。
- GPU Workflows 1.0.1 从本机 launcher.json 读取 Python；Parallel Downloads 1.0.3 从私有 settings.json 读取远程目标。
- 保留 Bridge/MCP 1.4.0 的 Git 唯一项目同步、渲染前自动更新、覆盖前备份、Godot 参数及 Blender Python。
- 提供 Windows/Linux 安装脚本、多账号配置步骤、持久防火墙、自启、升级与移除文档。
- 通用自启助手只激活用户已审核启用的插件，不携带原机器的审核哈希或自动同意未知版本。
