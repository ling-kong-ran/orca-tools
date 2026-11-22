# Claude Desktop 远程使用 GPU

Windows 客户端只需 Python 3.10+ 和 Claude Desktop。Unity、Blender、Godot、Tripo 等仍运行在原 GPU 主机。

## 网络

- 通常使用 Tailscale：将客户端设备精确加入 Bridge 的 `allowed_peers`，通过私密通道提供连接配置。
- 同一宿主机上的私有 Windows VM 可使用 `private_relay.py`。绑定宿主机专用 RFC1918 地址，只接受配置中的一个 VM 来源地址和独立随机令牌。仅转发 `/v1/` GPU API；不提供管理网页，不向 VM 提供主 Bridge 凭据。
- VM 连接配置必须同时填写 `url` 与完全匹配的 `private_network_peer`。没有显式配置时，客户端仍只允许回环/Tailscale 地址。
- 客户端与网关都拒绝 HTTP 重定向，避免认证头被转发到其他地址；网关不返回 Python 服务版本，不记录请求凭据。
- 私有 VM 模式仅适用于可信、隔离的宿主机内部网络；不是公网或共享局域网的明文接入方案。防火墙仅放行专用接口、VM 单一地址和该网关端口。
- 如果专用接口已有“禁止 VM 访问宿主机”的总阻止规则，新增允许规则不会覆盖它。须先保留非 TCP 协议的阻止，再将 TCP 阻止限定为网关之外的所有端口，最后验证其他端口仍被拦截。Windows 防火墙需要按协议分别表达非 TCP 阻止，不能直接删除总阻止规则。

宿主机私密 relay 配置（真实令牌不要放进仓库）：

```json
{
  "listen": "10.20.0.1",
  "peer": "10.20.0.2",
  "port": 18775,
  "token": "REPLACE_WITH_A_SEPARATE_RANDOM_SECRET_AT_LEAST_32_CHARS",
  "bridge_config": "C:/Users/OWNER/AppData/Local/LocalGpuBridge/config.json"
}
```

启动：`pythonw private_relay.py --config PRIVATE_CONFIG_FILE`。网关不重启 Bridge 或编辑器；原 Bridge 必须已运行。可通过 Windows 登录启动项保持网关可用。

VM 私密 client 配置：

```json
{
  "url": "http://10.20.0.1:18775",
  "private_network_peer": "10.20.0.1",
  "token": "SAME_VM_SPECIFIC_SECRET"
}
```

Linux VPS 原有的 Tailscale 元数据隔离配置不适用于没有 Tailscale 的私有 VM，不要将其配置原样复制。

## 安装

通过已配对的可信文件传输通道，将 `services/local-gpu-bridge/plugin/client.py`、安装脚本和私密连接配置送到 Windows 当前用户的私人目录。不要在终端命令、聊天或截图中粘贴令牌。

```powershell
python scripts/install-claude-desktop-gpu.py --source-client services/local-gpu-bridge/plugin/client.py --client-config PRIVATE_CLIENT_JSON
```

安装器会：

1. 将客户端放到 `%LOCALAPPDATA%/OrcaGpuClient`，限制目录为当前用户与 SYSTEM 可访问。
2. 识别普通版及商店版 Claude 的配置位置；新版商店应用优先使用 `%LOCALAPPDATA%/Claude-Data/claude_…`。备份已有配置并保留其他 MCP 服务。
3. 注册 `orca-gpu`、`orca-godot`、`orca-blender`、`orca-vroid`、`orca-tripo`、`orca-unity` 六个 stdio 服务。Desktop 配置只保存程序和私密配置文件路径，不内嵌令牌。

完全退出并重新打开 Claude Desktop，在设置的本地 MCP 服务中检查连接。聊天中先查询工作流或项目列表，再执行任务。仅安装配置不等于已验证 Desktop UI；应检查实际 MCP 日志及只读调用结果。

卸载时只移除上述六项 MCP 配置，再关闭网关、移除专用启动项。若调整过隔离总规则，应先恢复原来的全部协议/全部端口阻止，再删除本次按协议拆分的规则和端口允许规则，避免出现访问窗口。不要删除其他服务器、账号或项目。
