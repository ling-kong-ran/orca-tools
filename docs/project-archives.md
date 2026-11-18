# 从 VPS 解压 GPU 项目素材

先通过 Toolkit 多路下载，把压缩包保存到已注册项目内，例如 `backups/assets.tar.zst`。再让 VPS 上的 Claude 调用 Godot、Blender、VRoid 或 Unity 的 `extract_project_archive`：

```json
{
  "project_id": "your-project",
  "archive_path": "backups/assets.tar.zst",
  "destination": "art-src",
  "strip_components": 1,
  "expected_sha256": "填写校验文件中的64位SHA256"
}
```

- `destination` 必须不存在，父目录必须已存在；工具不会覆盖或合并已有目录。
- 压缩包内已经有 `art-src/` 顶层目录时用 `strip_components: 1`；没有时用 `0`。
- 立即返回任务 ID。用 `native_job_status` 或 `wait_native_job` 查询，直到 `succeeded`；无需 Bash 等待进程。
- 为防止重复提交，可提供 32 位小写十六进制 `request_id`；同 ID 返回原任务，即使原任务失败也不会自动重试。
- 支持 ZIP、TAR、tar.gz/tgz、tar.bz2、tar.xz、tar.zst；Zstandard 需要 GPU 端 Python 3.14+。
- 最多 100,000 项、解压后 32 GiB。拒绝目录越界、链接、设备文件、重复/大小写冲突、受保护路径和可执行文件。
- 在临时目录完成后再发布目标目录；失败不留下半成品目标。原压缩包保留，不还原归档内的文件时间、权限或所有者。
- 这里解压的是 **GPU 电脑项目**，不是 VPS 磁盘。无需启动 Unity/Blender，也不开放通用 shell。

部署时更新 GPU Bridge 和 VPS 的 local-gpu 插件；Bridge 重启后新接口生效，已有 Claude 会话用 `/reload-plugins` 更新工具列表。重启 Bridge 前须保存它管理的编辑器内容。
