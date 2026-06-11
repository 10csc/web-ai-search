# WebAISearch

> 通过 CDP 协议操控浏览器中的 AI 对话平台，让 Agent 获得联网搜索+深度分析能力。

## 这是什么

当你用的 AI 编程助手（Claude Code、Codex CLI 等）遇到需要**实时信息**的问题时，本 Skill 操控你浏览器里已登录的 AI 对话平台（DeepSeek、Kimi 等），让它帮你联网搜索并给出结构化分析报告，然后交还给 Agent 继续工作。

```
Agent 发现知识缺口 → 调用本 Skill → 浏览器 AI 平台搜索+分析 → 结果写回 → Agent 继续
```

## 安装

1. 把仓库放到 Skill 目录（以 Claude Code 为例）：
   ```
   C:\Users\<用户名>\.claude\skills\web-ai-search\
   ```

2. 运行配置脚本（自动创建 venv、安装 playright 等依赖）：
   ```bash
   python setup.py
   ```

3. 配置浏览器 CDP 端口（二选一）：

   | 方案 | 操作 | 适合 |
   |------|------|------|
   | A：手动 | 每次搜索前执行 `msedge --remote-debugging-port=9223` | 注重安全 |
   | B：快捷方式 | Edge 快捷方式 → 属性 → 目标末尾加 ` --remote-debugging-port=9223` | 追求方便 |

   > CDP 只监听 127.0.0.1，外部网络不可达。Agent 不会自动启动你的浏览器。

## 首次使用

安装完成后，Agent 会主动问你三件事：

1. **对话模式**：选 `fixed`（推荐，每个项目绑定固定对话链接）还是 `auto`
2. **当前项目名**：用于区分不同项目的对话，如 `my-app`
3. **搜索平台 URL**：默认 `https://chat.deepseek.com/`

之后搜索时，Agent 会**自动判断**是否需要搜索、用什么深度，你只需要正常提问。

## 搜索深度

| 深度 | 含义 | 流程 |
|------|------|------|
| **L1** | 快速确认 | 跳过本 Skill，直接用 WebSearch 工具 |
| **L2**（默认） | 标准调研 | 单平台一次搜索 → 提取结果 |
| **L3** | 深度研究 | 问题分解 → 串行多方向搜索 → 整合报告 |

日常使用一般 L2 就够了。需要多角度分析、交叉验证时用 L3。

## 双平台体系

L2 和 L3 搜索阶段都在**搜索平台**上进行（默认 DeepSeek），L3 的最终整合在**整合平台**上进行（默认 DeepSeek）。

可以在 `config.json` 的 `platform_urls` 里修改各平台首页地址，在 `sessions` 里为每个项目绑定具体聊天链接。

整合平台如果没有配置聊天链接，会自动退回到本地 API 调用完成整合。

## 项目背景注入

搜索时可以通过 `project_context` 参数传入项目背景（技术栈、约束条件等）。这些信息**只在最终整合阶段使用**，不会注入到搜索主题中，保证搜索的客观性。

## 配置参考

`config.json` 主要字段：

```json
{
  "session_mode": "fixed",
  "current_project": "my-app",
  "deepseek_api": "https://api.deepseek.com/v1",
  "deepseek_key": "sk-xxxxxxxxxxxxxxxx",
  "platform_urls": {
    "deepseek": "https://chat.deepseek.com/",
    "kimi": "https://www.kimi.com/"
  },
  "sessions": {
    "my-app": {
      "deepseek": "https://chat.deepseek.com/a/chat/s/xxx"
    }
  }
}
```

- `session_mode`：`fixed`（推荐）或 `auto`
- `current_project`：当前项目名，对应 `sessions` 中的 key
- `deepseek_api`：LLM API 地址（默认 DeepSeek 官方）
- `deepseek_key`：**强烈建议配置**。API key 用于三个关键能力（见下方）
- `platform_urls`：各平台首页地址（兜底用）
- `sessions`：每个项目在各平台的聊天链接（需要手动创建聊天后填入）

### 为什么需要 API key

Agent 的核心搜索能力通过浏览器操控 AI 平台完成（免费、零 API 消耗），但以下三个环节依赖 LLM API：

| 能力 | 用途 | 没 key 的行为 |
|------|------|-------------|
| **Planner 分解** | L3 深度研究时将问题拆为互补分析方向 | 退化为单方向搜索 |
| **合成验证** | 检测整合平台是否真正完成了报告（而非高峰期拒绝/道歉） | 默认放过，可能把拒绝消息当报告 |
| **本地降级总结** | 整合平台不可用时，本地 API 完成素材汇总 | 跳过整合，只返回原始素材 |

> 推荐用 DeepSeek API（`deepseek_api` + `deepseek_key`），价格低、中文能力强。即使没有 key，系统也能降级运行，但 L3 的验证和整合质量会打折扣。

## Agent 命令参考

如果你需要直接调用脚本：

```bash
# 完整 Agent 流程
python scripts/agent.py "搜索主题" --depth L2

# L3 深度研究（分解+多方向+整合）
python scripts/agent.py "复杂问题" --depth L3

# 快速模式（跳过分解）
python scripts/agent.py "简单问题" --quick

# 从文件读取问题
python scripts/agent.py --file question.txt
```

## 故障排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| CDP 连接失败 | 浏览器没开调试端口 | `msedge --remote-debugging-port=9223` |
| 发送失败 | 聊天链接失效 | 手动开新对话，把链接贴到 `config.json` 的 `sessions` |
| 提取不到内容 | AI 回复格式不标准 | 重试 1-2 次，仍不行则检查 AI 平台是否正常 |
| ImportError | 依赖未安装 | `python setup.py` |
| Kimi 上传失败 | Kimi 页面不支持文件上传 | 整合阶段会自动退回本地 API |

## 许可证

MIT
