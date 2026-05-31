# 网页版 AI 搜索 Skill（v6）

> 通过 CDP 协议操控浏览器里的 AI 对话平台，自动发送搜索 prompt 并提取结构化回复。

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

## 前置：CDP 端口

```bash
<PYTHON> -c "
from scripts.common import load_config, ensure_browser
from playwright.sync_api import sync_playwright
cfg = load_config()
try:
    with sync_playwright() as p:
        browser, page = ensure_browser(p, cfg.get('cdp_port', 9222))
        print(f'CDP OK')
except Exception as e:
    print(f'CDP 不可用: {e}')"
```

不可用则引导用户启动浏览器调试模式。

---

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

## 版本升级

升级时不覆盖用户数据。升级时**只能修改代码文件内容使其适配新版本**，不能删除或重置用户数据目录。

**可覆盖**：`scripts/*.py`、`SKILL.md`、`LEARNINGS.md`、`README.md`、`setup.py`、`references/`
**绝不动**：`config.json`、`data/`、`venv/`、`scripts/platforms/`、`scripts/profiles/`

升级后检查 config.json 的 `local_env.initialized`：
- True → 完成
- False → 运行 `<PYTHON> setup.py`

详细规则见 UPGRADE.md。
