# 架构、权限与隐私边界

```text
Windows Orca：仅安装 Orca Toolkit
  └─ localhost:18774 统一管理页
       ├─ GPU 模块 ── localhost:18773 管理页
  │                         └─ Local GPU Bridge
  │                              ├─ localhost:8188 ComfyUI
  │                              ├─ 专用 Godot / Blender
  │                              └─ Git 渲染副本
       ├─ Downloads 模块 ── 同服务 /downloads/ 页面
  │         └─ Tailscale + SSH ── Linux 只读分块 reader
       └─ Accounts 模块 / 远程浏览器 ── VPS localhost:18766 账号面板
                                     └─ 该 Linux 用户的 Orca runtime RPC

Linux VPS Claude Code
  └─ local-gpu / godot-local / blender-local MCP
          └─ Tailscale + Bearer token ── Windows tailnet-IP:18772
```

## 连接与身份

Tailscale 负责两台设备之间的加密隧道；Bridge 另外检查请求来源私网 IP 和 token。HTTP 在 Tailscale 隧道内使用，不代表对任意来源开放。本机管理页只绑定127.0.0.1，校验 Host、Origin 和会话 nonce/token，不向远程 MCP 暴露批准工作流、登记项目或修改执行器的接口。

账号工具只访问同一 Linux 用户已有 Orca runtime 元数据和 Unix socket。网页遮罩邮箱，CLI 为交互选择显示邮箱；没有 OAuth 导出接口。运行时元数据本身是秘密，不能进入仓库。账号切换影响后续启动的会话，不能保证改变已运行进程。

## 避免将公网端点与硬件信息返回给远程 Claude

- MCP 不返回 PC 公网地址、主机名、硬件型号或原始 renderer 日志。
- 文本/JSON 项目读取过滤地址、硬件标识、用户与本机路径；原文件仍保留在本机。
- VPS root 隔离 `/run/tailscale` LocalAPI 元数据，普通 worker 不能查询对端公网端点；客户端每次请求检查此条件。
- 专用 Godot/Blender/Go/server 出站仅允许 IPv4 loopback 和 Tailscale 范围；阻断其余IPv4及全部IPv6。普通编辑器、Git 和 Tailscale 自身不受这些专用程序规则影响。

**这不是对管理员或恶意脚本的完全匿名环境。** Tailscale 服务/网络管理员可能看到端点；项目 GDScript、Blender Python 具有本机用户文件和系统访问能力。过滤无法覆盖任意编码、图像/二进制内嵌或所有可能的泄漏途径。只运行可信项目和工作流；不允许不可信主体通过修改仓库内容在本机执行。工具没有声称能让任意代码安全运行。

## Git 与执行权限

配置的 root 必须等于精确仓库根目录，拒绝越界、符号链接和目录联接。Git 操作固定为 status/fetch/reset，不接收任意命令行、不暴露 remote URL 修改或本机 commit/push，禁用 hooks、fsmonitor、递归 submodule 和交互提示。使用本机既有 Git 凭据，不能在 MCP 传入新凭据。

Godot scene 参数放在 `--` 之后；项目脚本与 Blender Python 需本机授权 `allow_scripts`。没有通用 shell MCP。特定图库的子进程通过 `native_script.py` 中的固定代理，Windows Job Object 限制渲染进程派生。它仍不是文件系统沙箱。

## 接口与版本

- Bridge/MCP 1.4.0：唯一 Git 同步、Godot 参数/GDScript、Blender Python、产物下载、输出过滤。
- 旧的 `sync_project`、`upload_project_file`、`apply_project_sync` 已移除；旧HTTP请求给出迁移提示。
- ComfyUI 保存图转换参考其节点定义与官方 graphToPrompt 语义，不保证支持所有自定义前端控件。API图可通过本机 manage.py 导入。
- Orca 插件安装辅助器与 RuntimeClient 使用内部文件布局。应用升级后如接口变化，先审查并适配，不通过禁用安全校验硬撑旧版。
- ComfyUI、模型、Godot、Blender、Go、Orca、Claude 的二进制、许可证及登录状态均不随仓库分发。
