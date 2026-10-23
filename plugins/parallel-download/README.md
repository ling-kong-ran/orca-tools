# Parallel Downloads 1.0.3

Orca Windows 并行下载插件：**Ctrl+Alt+D** 或命令面板 **Parallel Downloads: Open Manager**。

先按 [下载插件部署](../../docs/parallel-download.md) 创建私有 settings.json，再导入本目录并审核启用。没有 npm 依赖。

源文件按固定大小分块，通过临时受限制 SSH 密钥读取，支持暂停续传、重试及 SHA-256 验证。项目同步不走此工具，统一使用 Git。
