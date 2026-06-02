# WebAISearch

> 通过 CDP 协议操控浏览器中的 AI 对话平台，自动发送搜索 prompt 并提取结构化回复。

## 项目目标

现代 AI 编程助手（Codex、Claude Code 等）内置的知识有截止日期。当遇到需要**实时信息**、**最新文档**、**版本兼容性**的问题时，传统搜索引擎返回的是链接列表，Agent 还需要额外解析。

本 Skill 把浏览器里的 AI 对话平台（DeepSeek/ChatGPT/Gemini）变成 Agent 的**外部研究能力**——Agent 发送搜索 prompt，平台联网搜索并总结，Skill 自动提取结构化结果返回给 Agent。

```
Agent 发现知识缺口 → 调用 Skill → 浏览器 AI 平台搜索 → 结构化结果 → Agent 继续工作
```

## 功能

| 搜索模式 | 适用场景 |
|---------|---------|
| `debug` | 代码报错、异常排查、版本兼容、API 变更 |
| `code` | 技术选型、方案对比、框架评估 |
| `news` | 行业动态、热点事件、市场分析 |

| 深度 | 含义 |
|------|------|
| L1 | 快速确认：根因 + 修复 + 1 个来源 |
| L2（默认） | 标准调研：根因 + 方案对比 + 多来源验证 |
| L3 | 深度研究：全链路分析 + 版本矩阵 + 迁移路径 |

**核心设计**：

- **环境自举**：`setup.py` 一次运行，自动探测 OS/Shell/Python/浏览器路径，写入 `config.json`，后续直接用
- **平台定型**：LLM 分析目标平台 DOM → 生成专用交互脚本 → 缓存复用，新平台无需手写适配代码
- **标记对定位**：在 prompt 中要求 AI 输出 `[搜索主题：xxx@hash]` 标记，从页面文本中精确定位回复内容，不依赖 DOM 选择器
- **双模式会话管理**：`fixed`（固定项目链接）和 `auto`（自动管理对话）

## 让 Agent 使用本 Skill

### 安装

1. 将本仓库放入 Agent 的 skill 目录：

```
# Codex
C:\Users\<用户名>\.codex\skills\web-ai-search\

# Claude Code  
C:\Users\<用户名>\.agents\skills\web-ai-search\
# 或
C:\Users\<用户名>\.claude\skills\web-ai-search\
```

2. 运行环境配置（自动创建 venv、安装 playwright）：

```bash
python setup.py
```

> 中国大陆用户：`setup.py` 会自动尝试清华/阿里/中科大镜像源，无需手动配置。

3. 注册浏览器 CDP 开机自启（信任本地单用户环境）：

```powershell
# Windows (Edge) — 一次性配置，之后每次登录自动启动 CDP
$path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $path -Name "EdgeCDP" -Value '"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222'
```

```bash
# macOS (Chrome) — 添加到登录项或使用 launchctl
# 每次搜索前手动执行，或设为开机自启：
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &
```

> **设计说明**：CDP 仅监听 127.0.0.1，外部网络不可达。信任本地单用户环境，Agent 内置自动崩溃恢复（common.py 的 ensure_browser）。正常情况零手动操作。

### 触发 Skill

Agent 加载本 Skill 后会自动读取 `SKILL.md`。你只需要告诉 Agent：

```
帮我搜索一下 Python 3.13 的 asyncio 有哪些 breaking changes
```

Agent 会自行判断触发搜索、选择模式和深度。首次使用会主动询问对话模式配置。

### 配置

`config.json`：

```json
{
  "version": 6,
  "session_mode": "fixed",
  "sessions": {},
  "current_project": "",
  "cdp_port": 9222
}
```

- `session_mode`：`fixed`（推荐）每个项目绑定固定对话链接；`auto` 自由管理
- `cdp_port`：浏览器调试端口，默认 9222

## 架构

```
SKILL.md          # Agent 入口文档（Agent 读取此文件了解如何执行）
config.json       # 运行时配置（环境自举数据、会话绑定）
setup.py          # 一次性环境探测 + 依赖安装
scripts/
  main.py         # 入口：run_send / run_extract / run_auto
  prompt_builder.py  # 意图识别 + prompt 生成（含唯一标记）
  extractor.py    # 标记对截取（平台无关）
  generator.py    # LLM 分析 DOM → 生成平台交互脚本 → 缓存
  common.py       # CDP 连接、平台检测、配置读取
  logger.py       # JSONL 日志
references/
  pitfalls.md     # 已知陷阱与设计约束
```

## 支持的平台

| 平台 | URL | 状态 |
|------|-----|------|
| DeepSeek | chat.deepseek.com | 已定型 |
| ChatGPT | chatgpt.com | 已定型 |
| Gemini | gemini.google.com | 已定型 |
| Claude | claude.ai | 待定型 |

新平台通过 `generator.py` 自动定型，无需手写适配代码。

## 许可证

MIT
