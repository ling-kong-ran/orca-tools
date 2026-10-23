# Changelog

## 2026-10-24 — 仓库首版

- 整理 Account Switcher、Parallel Downloads、GPU Workflows、Local GPU Bridge 与自启助手源码。
- 将旧部署的个人 IP、用户路径、项目名称和 Python 路径改为配置项；未导入真实账号、token、私钥、日志和素材。
- GPU Workflows 1.0.1 从本机 launcher.json 读取 Python；Parallel Downloads 1.0.3 从私有 settings.json 读取远程目标。
- 保留 Bridge/MCP 1.4.0 的 Git 唯一项目同步、渲染前自动更新、覆盖前备份、Godot 参数及 Blender Python。
- 提供 Windows/Linux 安装脚本、多账号配置步骤、持久防火墙、自启、升级与移除文档。
- 通用自启助手只激活用户已审核启用的插件，不携带原机器的审核哈希或自动同意未知版本。
