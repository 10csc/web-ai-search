# 网页版 AI 搜索 Skill（v6）

> 通过 CDP 协议操控浏览器里的 AI 对话平台，自动发送搜索 prompt 并提取结构化回复。


## ⛔ 执行失败速查（Agent 必须识别，禁止反复重试）

**前置检查**：首次使用或报 ImportError/未初始化时，Agent 必须先确认 python setup.py 已执行，再确认 config.json 配置（local_env.initialized=true，current_project 已设置），然后根据下方 CDP 章节引导用户完成浏览器配置。三项全部就绪后才能开始搜索。

| 错误信息 | 原因 | 处理 |
|---------|------|------|
| `PermissionError: ... data/_prompt.txt` | Agent 沙箱拦截文件写入 | 添加 prefix_rule 白名单（见沙箱兼容性章节） |
| `ECONNREFUSED 127.0.0.1:9222` | 沙箱网络隔离 或 浏览器未开调试端口 | 先确认 CDP 端口可用（`curl http://127.0.0.1:9222/json/version`），不可用则告知用户启动浏览器（见 CDP 前置章节） |
| `ImportError: No module named 'playwright'` | 依赖未安装 | 运行 `python setup.py` |
| `RuntimeError: 未检测到 CDP 浏览器` | 浏览器未启动或未开调试端口 | 告知用户配置方案（见 CDP 前置章节），不自动执行系统变更 |
| `发送失败` / `提取失败` / `ERROR: 超时` | 网络波动或 AI 回复慢 | 可重试 1-2 次，仍失败则告知用户检查网络和 AI 平台状态 |
| 首次 `run_auto` 合并 send+extract | 标记对可能因渲染延迟未出现 | **严禁**首次使用合并执行，必须先 send → 等用户确认 → extract |

**Agent 铁律**：任何错误最多重试 2 次，第 3 次仍失败必须告知用户具体原因和解决方案，不得无限循环。

---

## 能力概述

本 Skill 提供三种搜索模式 × 三级搜索深度：

| 搜索模式 | 适用场景 |
|---------|---------|
| `debug` | 代码报错、异常排查、版本兼容、API 变更 |
| `code` | 技术选型、方案对比、框架评估 |
| `news` | 行业动态、热点事件、市场分析 |

| 搜索深度 | 含义 |
|---------|------|
| `L1` | 快速确认，只要根因+修复+1个来源 |
| `L2`（默认） | 标准调研，根因+方案对比+多来源验证 |
| `L3` | 深度研究，全链路分析+版本矩阵+迁移路径 |

**Agent 自行判断何时触发、选择什么模式和深度。** 只有一条硬约束：**语法错误（SyntaxError/IndentationError）直接修复，不搜索**——搜也搜不到。

---


## ⚠️ 核心约束（不可违反）

1. **首次使用某平台禁止 `auto` 模式**：必须先 `send` → 等用户确认 → `extract`。**绝对禁止在第一条命令里合并 send+extract**（第一次发送时标记可能因网络/渲染延迟而未出现在页面中，合并执行会导致提取永远失败）
2. **禁止合并步骤**：send 和 extract 是两步，中间必须等用户确认。即使"看起来能一次完成"也必须分步
3. **禁止复用 prompt**：每次搜索必须重新生成，topic 须含 `@xxxx` 哈希
4. **CDP 端口规则**：LISTENING → 直接复用，不杀进程。空闲/TIME_WAIT 且浏览器在运行 → 可重启带调试参数（告知用户）。端口被占用 → 换端口。无论如何不无脑杀进程



---


## Agent 沙箱兼容性

本 Skill 通过浏览器 CDP 协议操控 AI 对话平台，与 Agent 沙箱存在以下冲突：

### 冲突点
| 操作 | 沙箱行为 | 原因 |
|------|---------|------|
| 写 data/ 目录（prompt 文件、中间结果） | 被拦截 | data/ 不在沙箱可写根目录 |
| CDP 连接 localhost:9222 | 被拦截 | 沙箱网络隔离 |
| Playwright 控制浏览器进程 | 被拦截 | 子进程创建 + 网络访问 |

### 原因
本 Skill 的本质是用户态浏览器代理——使用用户的浏览器、登录态、IP 与 AI 对话平台交互，不是无状态 API 调用。沙箱的设计目标是隔离，而本 Skill 的设计目标是代理用户行为，两者逻辑互斥。

### 解决方案：prefix_rule 白名单
在 Agent（如 Codex CLI）中为本 Skill 的 venv Python 添加白名单：
```
["{SKILL_DIR}/venv/Scripts/python.exe"]
```
该 venv 是 Skill 专属隔离环境，仅用于执行本 Skill 脚本。添加后所有 Skill 命令（生成 prompt、send、extract、run_auto）自动放行。

用户安装后执行的具体 prefix_rule 由 config.json 的 local_env.python_venv 决定。Agent 首次调用时若因沙箱被拦截，应提示用户添加该路径为白名单。

### 不推荐替代方案
- MCP 化：CDP 连接依赖实时浏览器状态（登录态、页面 DOM），MCP server 进程管理增加浏览器崩溃恢复、CDP 重连等故障点。当前阶段 MCP 化的唯一收益是工具链集成，性价比低。
- 移到沙箱可写目录：只解决文件写入问题，无法解决 CDP 网络隔离和 Playwright 子进程限制。

---


## 前置：CDP 端口

本 Skill 需要浏览器开启远程调试端口（默认 9222，自动扫描 9222-9225）。

**设计原则：Agent 不自动启动浏览器，不越权，不杀进程。两个方案由用户自选。**

### Agent 行为

连接 http://127.0.0.1:9222/json/version：
- **通** → 进入搜索
- **不通** → 输出：

> CDP 不可用。请二选一：
> **A（每次手动，更安全）**：执行 `msedge --remote-debugging-port=9222`，然后告诉我继续。
> **B（一劳永逸）**：右键 Edge 快捷方式 → 属性 → 目标末尾加 ` --remote-debugging-port=9222`（注意前面有空格）。之后每次打开 Edge 都自带 CDP。

### 方案对比

| | A：手动 | B：修改快捷方式 |
|------|------|------|
| 自动化 | 每次搜索前手动一行命令 | 零操作 |
| 安全 | CDP 仅搜索窗口期暴露 | CDP 随 Edge 常驻 |
| 配置 | 零 | 改一次快捷方式 |
| 额外进程 | 无 | 无（同一实例，不带 CDP 不额外开销） |
| 推荐 | 安全性优先 | 便利性优先 |

### 安全分析

CDP 仅监听 127.0.0.1，外部网络不可达。网页 fetch 受同源策略限制无法读取响应。信任本地单用户环境，两种方案风险均可控。

### 安全分析

CDP 仅监听 127.0.0.1，外部网络不可达。网页 fetch 受同源策略限制无法读取响应。信任本地单用户环境，两种方案风险均可控。


| 风险 | 等级 | 说明 |
|------|------|------|
| Edge 单例冲突 | 低 | 用户先开普通 Edge → CDP 自启变普通窗口。agent 提示关掉重开即可 |
| CDP 常驻 | 低 | 信任本地环境，常驻开销可忽略（~100MB 内存） |
| 注册表残留 | 极低 | 卸载：删除 HKCU\Software\Microsoft\Windows\CurrentVersion\Run\EdgeCDP |


### 为什么不设开机自启 / 快捷方式

CDP 长期开放无必要且增加攻击面。每次搜索时用户主动执行一行命令，零配置、低残留。


### 为什么不设开机自启 / 快捷方式

CDP 长期开放无必要且增加攻击面。每次搜索时用户主动执行一行命令，零配置、零残留、零风险敞口。

## 搜索流程

`<PYTHON>` = `local_env.python_venv`。`{SKILL_DIR}` = 本 skill 目录。

### Step 1：生成 prompt

`{DEPTH}` 选 L1/L2/L3（默认 L2）。`{搜索意图}` = 用户原话或完整错误信息。

```bash
<PYTHON> -c "
import sys, os
sys.path.insert(0, os.path.join('{SKILL_DIR}', 'scripts'))
from prompt_builder import extract_intent, build_final_prompt

topic, ptype = extract_intent('''{搜索意图}''')
topic, prompt = build_final_prompt(topic, ptype, depth='{DEPTH}')

os.makedirs(os.path.join('{SKILL_DIR}', 'data'), exist_ok=True)
with open(os.path.join('{SKILL_DIR}', 'data', '_prompt.txt'), 'w', encoding='utf-8') as f:
    f.write(prompt)
with open(os.path.join('{SKILL_DIR}', 'data', '_topic.txt'), 'w', encoding='utf-8') as f:
    f.write(topic)
print(f'TOPIC:{topic}')
print(f'TYPE:{ptype}')"
```

Topic 必须含 `@` 字符。含 traceback 时自动识别为 debug 模式。

### Step 2：检查平台定型

```bash
<PYTHON> -c "
import os, sys
sys.path.insert(0, os.path.join('{SKILL_DIR}', 'scripts'))
from generator import script_exists
from common import detect_platform
platform = detect_platform('{URL}')
print(f'PLATFORM:{platform}')
print(f'EXISTS:{script_exists(platform)}')"
```

`EXISTS:True` → 一条命令完成。`EXISTS:False` → 分步执行。

### 已定型（一条命令）

```bash
<PYTHON> -c "
import sys, os
sys.path.insert(0, os.path.join('{SKILL_DIR}', 'scripts'))
from main import run_auto
with open(os.path.join('{SKILL_DIR}', 'data', '_prompt.txt'), 'r', encoding='utf-8') as f:
    prompt = f.read()
with open(os.path.join('{SKILL_DIR}', 'data', '_topic.txt'), 'r', encoding='utf-8') as f:
    topic = f.read().strip()
result = run_auto(prompt, topic, '{URL}', max_wait=300)
print('OK' if result and 'ERROR' not in str(result) else f'FAIL: {result}')"
```

### 首次定型（分步，禁止合并）⚠️

> **重要：这是两步操作，必须分两次命令执行。绝对禁止写成一条复合命令（如 && 连接）。**

**第一步：发送**

```bash
<PYTHON> -c "
import sys, os
sys.path.insert(0, os.path.join('{SKILL_DIR}', 'scripts'))
from main import run_send
with open(os.path.join('{SKILL_DIR}', 'data', '_prompt.txt'), 'r', encoding='utf-8') as f:
    prompt = f.read()
with open(os.path.join('{SKILL_DIR}', 'data', '_topic.txt'), 'r', encoding='utf-8') as f:
    topic = f.read().strip()
print(run_send(prompt, topic, '{URL}', force_regenerate=True))"
```

告知用户："已在浏览器发送搜索请求，AI 回复完毕后告诉我'提取'。"**等待用户回复后才能执行第二步。**

**第二步：提取**（用户说"提取"后执行）

```bash
<PYTHON> -c "
import sys, os
sys.path.insert(0, os.path.join('{SKILL_DIR}', 'scripts'))
from main import run_extract
with open(os.path.join('{SKILL_DIR}', 'data', '_prompt.txt'), 'r', encoding='utf-8') as f:
    prompt = f.read()
with open(os.path.join('{SKILL_DIR}', 'data', '_topic.txt'), 'r', encoding='utf-8') as f:
    topic = f.read().strip()
result = run_extract(prompt, topic, '{URL}')
print('OK' if result and 'ERROR' not in str(result) else f'FAIL: {result}')"
```

结果在 `{SKILL_DIR}/data/latest_result.md`。

---


## 对话管理

`config.json` 的 `session_mode` 控制对话切换行为：

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `fixed`（默认推荐） | 从 `sessions` 按项目名查找链接，每次刷新同一对话页面 | 多项目开发，每个项目独立对话 |
| `auto` | Agent 可自行新建对话、切换对话 | 每次搜索独立话题 |

### fixed 模式详细规则

1. **已有项目**：从 `sessions[项目名]` 读取链接 → `page.goto(链接)` → 刷新页面即可（不新建对话）
2. **新项目（sessions 中无记录）**：自动打开 DeepSeek 首页 → 自动发送消息 → 绑定新对话链接到 `sessions`
3. **固定对话刷新**：`fixed` 模式只刷新页面不关闭/新建对话，保持对话连续性

**设置固定链接**：用户说"用这个链接" → Agent 写入 `sessions[项目名] = 链接`，设 `current_project`。

**切换对话**：用户说"换个对话"/"新对话" → `fixed` 模式下更新 `sessions`，`auto` 模式下新建对话。


## 快速参考

| 平台 | URL | 模式 | TYPE |
|------|-----|------|------|
| deepseek | chat.deepseek.com | debug | 代码错误诊断 |
| chatgpt | chatgpt.com | code | 技术选型 |
| gemini | gemini.google.com | news | 新闻热点 |
| claude | claude.ai | | |

- 发送后不按 Escape | 残留 <=2 字符 = 发送成功
- platform 脚本在 `scripts/platforms/`
- 详细设计 → LEARNINGS.md | 陷阱 → references/pitfalls.md

---


---

## 📋 以下为首次配置内容（配置完成后 Agent 可跳过此部分）

> ⚠️ 以下章节仅在首次安装或升级时需要。日常使用中 Agent 无需加载这些内容，可直接跳至搜索流程。

## 🛡️ 升级铁律（不可违反）

> **任何时候升级/更新本 Skill，以下文件/目录绝对不可覆盖：**

| 文件/目录 | 原因 |
|----------|------|
| `config.json` | 含用户环境自举数据（Python路径、浏览器路径、CDP端口等） |
| `data/` | 含搜索历史和结果 |
| `venv/` | 含用户已安装的 Python 依赖 |
| `scripts/platforms/` | 含已定型的平台交互脚本 |
| `scripts/profiles/` | 含 DOM 分析快照 |

> **更新只能修改内容使其适配新版本，绝不能删除或重置这些目录。**

**可覆盖**：`scripts/*.py`、`SKILL.md`、`LEARNINGS.md`、`README.md`、`setup.py`、`references/`

---


## 首次配置提醒

首次加载本 Skill 时，**主动询问用户以下配置**（不等用户自己提）：

1. **对话模式**：选 `fixed`（固定项目链接，默认推荐）还是 `auto`（自动管理对话）？
   - `fixed`：每个项目绑定一个固定 DeepSeek 对话链接，搜索时刷新该对话页面
   - `auto`：Agent 可自行刷新页面、新建对话
2. **当前项目名**（fixed 模式）：用于区分不同项目，如 `"my_app"`。新项目首次搜索自动绑定链接。
   - **重要**：若不设置，项目名回退为当前工作目录名（`os.getcwd()` 的 basename），导致换目录后视为新项目、创建新对话链接。Agent 必须在首次搜索前确认项目名已设置。若 current_project 为空，Skill 内置的 get_or_create_project() 会自动从工作目录推断并持久化到 config.json，后续不再依赖目录。
3. **搜索平台 URL**：默认 `https://chat.deepseek.com/`，是否更换？

写入 `config.json` 对应字段后不再重复询问。

---


## 前置：Python 路径

读 `config.json` 的 `local_env.python_venv`，有值直接用。无值则 fallback 到 `local_env.python.path`，都没有则：

```bash
python3 --version 2>/dev/null || python --version 2>/dev/null || py --version 2>/dev/null
<找到的Python> -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple  # 中国大陆用户
<找到的Python> setup.py
```

> **Python 版本兼容**：本 Skill 要求 Python >= 3.8（playwright 要求）。`setup.py` 会自动检测并提示。用户系统 Python 版本可能与开发者不同，`setup.py` 会自动创建独立 venv 避免污染系统环境。


## 版本升级

升级时不覆盖用户数据。升级时**只能修改代码文件内容使其适配新版本**，不能删除或重置用户数据目录。

**可覆盖**：`scripts/*.py`、`SKILL.md`、`LEARNINGS.md`、`README.md`、`setup.py`、`references/`
**绝不动**：`config.json`、`data/`、`venv/`、`scripts/platforms/`、`scripts/profiles/`

升级后检查 config.json 的 `local_env.initialized`：
- True → 完成
- False → 运行 `<PYTHON> setup.py`

详细规则见 UPGRADE.md。

---


## 多 Agent 共享（推荐）

如果同时使用多个 AI 编码 Agent（如 Codex CLI、Claude Code 等），建议只保留一份 Skill 实体，其他 Agent 目录通过目录联接（Junction）指向它：

```powershell
# 假设主副本在 .agents/skills/web-ai-search/
cmd /c mklink /J "C:\Users\<用户名>\.codex\skills\web-ai-search" "C:\Users\<用户名>\.agents\skills\web-ai-search"
cmd /c mklink /J "C:\Users\<用户名>\.claude\skills\web-ai-search" "C:\Users\<用户名>\.agents\skills\web-ai-search"
```

优点：修改一处全部 Agent 生效，搜索历史、配置、venv 共享，不会出现版本分裂。

每个 Agent 仍需为其 venv Python 添加 prefix_rule 白名单（详见 SKILL.md Agent 沙箱兼容性章节），路径由各 Agent 的沙箱配置决定。

