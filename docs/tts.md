# Qwen3 多语言配音

桥接支持现有 `FB_Qwen3TTS*` 工作流的语言、音色与风格参数。需先在本机 ComfyUI 安装相应 Qwen3-TTS 节点及模型，重启实际被桥接使用的 ComfyUI 实例。仓库不分发模型、账号凭据或个人工作流。

Qwen3-TTS CustomVoice 支持中文、英文、日文、韩文、法文、德文、西班牙文、葡萄牙文、俄文、意大利文，另有 Auto 自动检测。参见 [Qwen 官方模型说明](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)。实际可选值以本机节点 schema 为准。

## 使用

1. 在 ComfyUI 保存配音工作流，接好 Qwen3 CustomVoice → SaveAudioAdvanced，选择已安装的模型。
2. 可分别保存中文、英文和多语言预设；例如 English 预设选择语言 English、音色 Ryan 或 Aiden，中文可使用 Serena 或 Vivian。多语言预设用 Auto，运行时也可指定语言。
3. 在 GPU 管理页刷新工作流。Claude 调用 `list_workflows`，查看该工作流实际暴露的参数名和 enum，再运行 `run_workflow`。
4. 节点 id 为 1 时，常见参数为 `text_1`、`language_1`、`speaker_1`、`instruct_1`。其他 id 或子图的参数名可能不同，不要硬编码猜测。
5. 查询 `job_status` 到 succeeded，使用 `fetch_artifact` 取回 FLAC 等音频。

示例请求参数（针对 id=1 的节点）：

```json
{
  "text_1": "Hello, welcome to local voice generation.",
  "language_1": "English",
  "speaker_1": "Ryan",
  "instruct_1": "Speak in clear, natural English."
}
```

语言与音色参数由节点的选项列表校验，风格文字允许修改；模型路径、设备与输出位置保持本机原值，不向远程开放。此次实际执行验证了中文与英文生成；其他语言提供选择，未逐一执行质量测试。

## 排查 Unavailable

- 确认 `/object_info` 中有工作流使用的节点（如 `FB_Qwen3TTSCustomVoice`）。文件已放入 custom_nodes 并不代表当前服务已加载。
- 如果同时运行多个 ComfyUI 端口，确认桥接的 comfy_url 指向已加载节点的实例；只重启另一个实例不能修复当前实例。
- 节点加载失败时检查本机日志与依赖，不能用另一个同名节点替换后假定输入兼容。
- 桥接节点 schema 缓存最长约60秒，ComfyUI 重启完成后刷新或稍等再刷新。
- 服务使用单实例锁，避免多个桥接进程占用相同管理端口并返回不同版本。未知任务状态只查询恢复，不盲目重复提交。
