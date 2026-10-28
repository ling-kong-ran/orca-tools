# Local GPU Bridge 1.6.4

Windows 私网 GPU 服务和 Linux Claude Code MCP 插件。

- [完整部署步骤](../../docs/gpu-bridge.md)
- [架构与权限](../../docs/architecture.md)
- [自启、升级、备份与移除](../../docs/operations.md)
- [VRoid Studio 接入](../../docs/vroid.md)

服务源码位于本目录，远程插件在 `plugin/`，marketplace 清单位于 `.claude-plugin/`。只使用 Python 标准库，不需要 pip 安装第三方依赖。

项目开发在 VPS，本机通过唯一的 Git 同步入口更新渲染副本；不会将 VPS 的未提交文件自动上传。原生功能包括 Godot scene 参数/项目脚本、Blender Python/固定操作，ComfyUI 支持已保存图自动发现及 API 图导入。

安装请使用仓库根目录的 `scripts/install-local-gpu.py` / `scripts/install-vps-gpu.py`，不要把示例地址当成真实配置直接运行。服务配置与 token 只保存在运行目录，不能提交 Git。

保存的 Hunyuan3D 2.1 编辑器工作流支持自定义图片上传控件，以及白模和多视图节点的种子控制控件；上传按钮和生成后种子策略不会误传为后端输入。图片输入可通过 MCP 上传替换。安装自定义节点后，需要等待 ComfyUI 队列空闲再重启 ComfyUI，已运行的进程不会自动加载新节点。桥接服务也需要加载更新后的解析器；无需重新授权 Toolkit 插件。
