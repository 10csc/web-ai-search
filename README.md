# WebAISearch

网页版 AI 搜索 Skill —— 通过 CDP 协议操控浏览器中的 AI 对话平台（DeepSeek/ChatGPT/Gemini），自动发送搜索 prompt 并提取结构化回复。

## 快速开始

1. 安装依赖：
`powershell
python -m pip install playwright openai
python -m playwright install chromium
`

2. 启动 Edge 调试端口：
`powershell
Start-Process "msedge" -ArgumentList "--remote-debugging-port=9222"
`

3. 首次使用会自动进行本地环境自举（探测 shell/Python/浏览器路径）。

## 文件说明

| 文件 | 用途 |
|------|------|
| SKILL.md | 完整执行规范（Agent 必读） |
| LEARNINGS.md | 本轮对话精炼知识（术语、ADR、Bug历史、设计模式） |
| eferences/pitfalls.md | 18 条已验证陷阱 |
| scripts/main.py | 入口：--mode send|extract|auto |
| scripts/prompt_builder.py | 生成搜索 prompt（含唯一 hash） |
| scripts/extractor.py | 标记对截取（通用逻辑，平台无关） |
| scripts/generator.py | LLM 分析 DOM → 生成平台交互脚本 |
| scripts/common.py | CDP 连接、平台检测、页面文本提取 |
| scripts/logger.py | JSONL 日志 |
| config.json | 运行时配置（API、端口、local_env） |

## 下一步

针对代码 Agent 辅助场景优化 skill 流程。详见 LEARNINGS.md 第 5 节。