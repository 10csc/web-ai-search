# WebAISearch 完整架构文档

> 更新时间：2026-06-07 | 版本：v7 精简版 | 双平台体系（检索+整合），DOM 主导提取

---

## v7 精简原则

1. **双平台体系**：检索平台（DeepSeek）+ 整合平台（Kimi），改两行变量即可换
2. **模型自设计 Prompt**：不预设搜索策略模板，只加标记对定位
3. **DOM 主导提取**：textContent 渲染不可靠 → `div[class*="message"][class*="assistant"]` 直接提取
4. **结尾标记判定完成**：AI 尾部出现 `[搜索主题：xxx]` 才认为完成，绝不提前提取
5. **不筛思考链**：CoT 交给整合层（Kimi）处理，提取层只管拿完整内容

---

## 一、目录结构

```
web-ai-search/
├── config.json              ← 环境配置（CDP端口、会话链接、API key）
├── setup.py                 ← 首次安装脚本
├── data/
│   ├── codex-research.jsonl  ← 搜索日志（JSONL格式，按项目名分文件）
│   ├── latest_result.md      ← 最近一次搜索结果
│   ├── workspace/            ← 任务工作区（临时状态，任务结束后清理）
│   └── memory/               ← 过程记忆（episodes） + 结论记忆（semantic）
├── scripts/
│   ├── main.py               ← 原始入口：send / extract / auto 三步（已验证稳定）
│   ├── agent.py              ← Agent 统一入口：全流程串联
│   ├── tool_router.py        ← 工具选择层：LLM 语义路由（WebSearch vs WebAISearch）
│   ├── prompt_builder.py     ← Prompt 生成器：三模式 × 三级深度
│   ├── planner.py            ← 规划层：问题分解 + L2/L3 路由
│   ├── orchestrator.py       ← 执行编排层：send + poll + extract
│   ├── extractor.py          ← 内容提取层：标记定位 + DOM 兜底
│   ├── evolution.py          ← 自进化引擎：CoT检测 / 页尾识别 / 策略适配
│   ├── synthesizer.py        ← 整合层：信源评分 + 交叉验证 + 报告生成
│   ├── workspace.py          ← 工作区状态 + 情景/语义记忆
│   ├── logger.py             ← JSONL 日志记录
│   ├── common.py             ← 公共工具（CDP、浏览器、会话路由、平台检测）
│   ├── generator.py          ← LLM 代码生成：分析DOM → 生成平台交互脚本
│   ├── profiles/             ← 平台档案（提取特征、轮询参数、CoT关键词）
│   │   ├── _global.json      ← 全局知识库（多平台确认后推广的特征）
│   │   ├── deepseek_extraction.json
│   │   ├── kimi_extraction.json
│   │   └── ...
│   └── platforms/            ← 平台交互脚本（DOM 操作）
│       ├── deepseek.py
│       ├── kimi.py
│       ├── chatgpt.py
│       ├── gemini.py
│       └── scnet.py
└── venv/                     ← 专属虚拟环境
```

---

## 二、完整数据流

```
用户提问
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  Step 0: agent.py — 统一入口                          │
│  agent_search(query, depth, platform, quick)           │
│  串联: ToolRouter → Planner → Orchestrator → Synthesizer │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│  Step 1: tool_router.py — 工具选择（LLM 语义路由）     │
│  route(query) → {tool, depth, reason}                 │
│                                                       │
│  classify_llm(): DeepSeek-v4-flash 做语义分类          │
│    → "单点事实" → WebSearch + L1                       │
│    → "多维分析" → WebAISearch + L2                     │
│    → "深度架构" → WebAISearch + L3                     │
│                                                       │
│  classify_fallback(): 规则引擎兜底（LLM不可用时）       │
│                                                       │
│  输出: tool_choice {tool, depth, reason, query}       │
│  如果 depth == L1 → 直接返回，不进入后续流程           │
└────────────┬─────────────────────────────────────────┘
             │ depth ∈ {L2, L3}
             ▼
┌──────────────────────────────────────────────────────┐
│  Step 2: planner.py — 搜索规划                        │
│  plan(query, depth) → plan_dict                       │
│                                                       │
│  L2 流程（不调用 LLM）：                                 │
│    sub_questions = [{question: query, platform: SEARCH_PLATFORM}] │
│    1 个子问题 × 检索平台 = 单次搜索                      │
│                                                       │
│  L3 流程（调用 DeepSeek API 分解）：                    │
│    _llm_decompose(query) → ≤3 个采集方向               │
│    按信源类型拆分（英文官方 / 中文案例 / 技术原理）       │
│    全部走检索平台串行 + 整合平台汇总                      │
│    平台变量在 orchestrator.py 顶部改一处全局生效          │
│                                                       │
│  输出: {original_query, depth, sub_questions,         │
│         decomposed, replan_triggers}                   │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│  Step 3: orchestrator.py — 执行编排                   │
│  execute(plan_dict) → {results, gaps_total, all_links}│
│                                                       │
│  对每个 sub_question:                                  │
│    _send_one(browser, platform, question, ...)        │
│      ├─ build_final_prompt() 生成带标记的 prompt       │
│      ├─ get_session_url() 获取已保存的会话链接          │
│      ├─ ensure_page(session_url, new_tab=False)       │
│      │   查找已有页面（URL匹配 → 平台匹配 → 新建）       │
│      ├─ _submit_to_platform() 填入 prompt + 提交       │
│      │   plat.fill_prompt → plat.submit → 检查残留     │
│      └─ 保存新会话 URL（若 URL 变化）                   │
│                                                       │
│    _wait_one(platform, page, prompt, topic, max_wait) │
│      ├─ 轮询循环（复用 main.py 验证过的逻辑）           │
│      │   ├─ safe_page_text() 获取页面文本              │
│      │   ├─ extract_with_diagnosis() 标记提取          │
│      │   ├─ 内容稳定检测（polling.get_stability_rounds）│
│      │   ├─ 自进化触发（30s+标记>=2+诊断可适配）        │
│      │   └─ 强制提取兜底（60s+标记>=2+内容充裕）        │
│      └─ 超时兜底: DOM 直接提取（dom_extract）          │
│                                                       │
│  L2: 1次 send+wait                                    │
│  L3: N次 send+wait（DeepSeek串行）+ 1次 Kimi整合       │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│  Step 4: synthesizer.py — 整合                        │
│  synthesize(query, execution) → (report, validation)  │
│                                                       │
│  cross_validate(results):                             │
│    → 多平台 URL 交叉确认                               │
│    → 信源分类（官方/学术/媒体/社区/自媒体）             │
│    → 信源评分（1-10）                                  │
│                                                       │
│  generate_report(query, results, validation):         │
│    → Markdown 格式报告                                 │
│    → 各平台结果 + 来源评价                             │
│    → 交叉验证报告 + 信息缺口汇总                        │
│    → 写入 data/latest_result.md                       │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────┐
│  Step 5: workspace.py — 记忆持久化                     │
│  record_episode() → 每次搜索的过程记录（JSONL）          │
│  workspace.complete() → 标记任务完成                    │
│                                                       │
│  输出: agent_search 返回值                              │
│    {query, tool_choice, plan, execution, report,       │
│     report_path, validation, workspace_summary,        │
│     elapsed_sec}                                       │
└──────────────────────────────────────────────────────┘
```

---

## 三、核心模块详解

### 3.1 common.py — 基础设施层

> ⛔ **禁止修改**：CDP 连接逻辑、`ensure_page` 的 URL匹配策略、`_save_session` 的二级映射结构

| 函数 | 职责 | 关键逻辑 |
|------|------|---------|
| `load_config()` | 读取 config.json，兼容 v4/v5/v6 | 设置默认值，不抛异常 |
| `get_or_create_project()` | 获取当前项目名 | 首次自动从工作目录推断并持久化 |
| `find_cdp_port()` | 扫描可用 CDP 端口 | 9223 → 9224 → 9225 → 9226 |
| `ensure_browser(p, cdp_port)` | 连接 CDP 浏览器 | 先扫描 → 未找到则自动启动 → 兜底提示用户 |
| `ensure_page(browser, url, new_tab)` | 查找或创建页面 | URL精确匹配 → 平台类型匹配 → 新建 |
| `safe_page_text(page)` | 提取页面文本 | textContent → innerText → inner_text 三级降级 |
| `detect_platform(url)` | URL → 平台名 | 字符串匹配（deepseek/kimi/chatgpt/gemini/scnet） |
| `get_session_url(project, default_url)` | 获取已保存会话链接 | fixed 模式按 project→platform 两级查找 |
| `_save_session(project, url)` | 保存会话链接 | 两级映射，兼容旧字符串格式 |

**会话路由（fixed 模式）**:
```
config.json → sessions → {项目名} → {平台名} → URL
例: sessions.codex-research.deepseek = "https://chat.deepseek.com/a/chat/s/xxx"
```

### 3.2 prompt_builder.py — Prompt 生成（100行）

> ⛔ **禁止修改**：标记对格式 `[搜索主题：{topic}]`、topic 的 `@xxxx` 哈希机制

| 函数 | 职责 |
|------|------|
| `extract_intent(user_context)` | LLM 提取搜索主题（≤40字），失败时本地截取 |
| `build_final_prompt(topic, depth, focused)` | 生成 prompt：搜索指令 + 标记对要求。搜索策略由模型自行设计 |
| `validate_prompt(prompt, topic)` | 防呆验证：topic 哈希 + 标记存在 |

**v7 关键简化**：
- 删除 debug/code/news 三套固定模板（~250行死代码）
- prompt 极简：搜索问题 + 标记对指令，无预设规则
- 模型自行设计搜索策略、回复结构和输出格式
- 标记对指令格式：
  ```
  【定位要求】在你的回复最开头（第1行）和最末尾（最后1行）各放一行标记：
  `[搜索主题：{topic}@xxxx]`
  两行标记之间是你的正式回复内容。标记必须独占一行。
  ```
- prompt 中标记出现 1 次（在指令中），AI 需输出 2 次（开头+结尾），总计 3 次 = 完成

### 3.3 extractor.py — 内容提取（108行）

> ⛔ **禁止修改**：标记数量阈值（≥3=between-pair, 2=post-marker, ≤1=未完成）

| 函数 | 职责 |
|------|------|
| `extract_with_diagnosis(raw_text, prompt, topic, platform)` | 标记定位提取（textContent 辅助用） |
| `is_content_complete(text)` | 基本质量检查（长度≥150 + 页尾排除，**不筛 CoT**） |
| `dom_extract(page, platform)` | **主导**：DOM 选择器直接提取最后一个 AI 回复 |
| `_strip_footer(text)` | 清除页尾 UI 垃圾文字 |

**v7 关键简化**：
- 删除 CoT 关键词检测（交给整合层 Kimi 处理）
- 删除 evolution 依赖（FailureAnalyzer 等）
- DOM 选择器 `div[class*="message"][class*="assistant"]`（textContent 在 DeepSeek 渲染中不可靠）
- 标记阈值精确化（prompt 含 1 个标记）：

  | 标记数 | 含义 | 策略 |
  |--------|------|------|
  | ≥3 | AI 已输出开头+结尾标记 | between-last-pair（取 AI 正式回复） |
  | 2 | AI 已输出开头标记，未输出结尾 | post-last-marker（取 AI 回复中） |
  | 1 | 仅 prompt 标记，AI 未开始 | 返回 None，继续等待 |
  | 0 | 异常 | 返回 None，走 DOM 兜底 |

### 3.4 evolution.py — 自进化引擎（保留但 v7 暂不接入）

> extractor 已不依赖 evolution（去掉 CoT 检测），但平台档案和轮询配置仍在使用。

| 组件 | 职责 |
|------|------|
| `ExtractionProfile` | 单平台提取档案 |
| `GlobalKnowledge` | 全局知识库（≥2平台确认后推广） |
| `PollingProfile` | 轮询参数（间隔、稳定轮数），自适应调整 |
| `load_or_create_polling(platform)` | 加载/创建轮询档案（orchestrator 仍使用） |

### 3.5 orchestrator.py — 执行编排（317行）

> ⛔ **禁止修改**：`_wait_one` 的 DOM 主导 + 结尾标记判定完成逻辑

| 函数 | 职责 |
|------|------|
| `_send_one(browser, platform, question, ...)` | 发送 prompt，复用已保存会话 URL |
| `_submit_to_platform(platform, page, prompt, topic)` | 平台交互：fill → dismiss → submit |
| `_wait_one(platform, page, prompt, topic, max_wait)` | **DOM 主导轮询**：dom_extract → 结尾标记判定 → 稳定检测 |
| `execute(plan_dict)` | 主执行：L2 单次检索，L3 串行采集+整合 |
| `execute_simple(query, platform, depth)` | 简化入口 |

**平台配置**（改两行全局生效）:
```python
SEARCH_PLATFORM = "deepseek"   # 检索平台
SYNTH_PLATFORM = "kimi"        # 整合平台
```

**_wait_one 流程**:
```
while 未超时:
    content = dom_extract(page, platform)    # DOM 主导提取
    if content 尾部含结尾标记:
        if 内容稳定(N轮):
            return content                   # ← 完成！
    else:
        # 辅助: textContent 标记提取（DOM 不可用时）
        # 每15s打印等待状态
超时 → DOM兜底 → textContent兜底 → None
```

### 3.6 agent.py — 统一入口

> ⛔ **禁止修改**：流程串联顺序（ToolRouter → Planner → Orchestrator → Synthesizer）

```
agent_search(query, depth, platform, quick):
  0. ToolRouter 选择工具和深度
  1. Planner 生成搜索计划
  2. Orchestrator 执行搜索
  3. Synthesizer 整合报告
  4. Workspace 记录记忆
  5. 返回完整结果
```

### 3.7 main.py — 原始入口（已验证稳定）

> ⛔ **禁止修改**：`run_send` 的三段式回退、`run_auto` 的完整轮询+自进化+强制提取逻辑、`_extract_with_evolution` 的进化循环

| 函数 | 用途 |
|------|------|
| `run_send(prompt, topic, url)` | 发送 prompt → 已验证稳定 |
| `run_extract(prompt, topic, url)` | 提取内容 → 已验证稳定 |
| `run_auto(prompt, topic, url, max_wait)` | 发送+轮询+提取一站式 → 已验证稳定 |
| `_extract_with_evolution(page, prompt, topic, platform, polling)` | 提取+进化重试 |
| `_try_submit(plat, page, prompt)` | 填prompt+提交 |

> **注意**：`main.py` 是原始两段式入口（send → 用户确认 → extract），`agent.py` 是新的全自动入口。两者共享 extractor/evolution/prompt_builder，但各自管理 Playwright 生命周期。

---

## 四、会话管理

### 会话生命周期

```
首次使用:
  ensure_page(homepage) → 新标签页打开首页
  → fill_prompt + submit → AI 开始回复
  → 检查 page.url 是否变化
  → _save_session(project, page.url) 保存新对话链接

后续使用:
  get_session_url(project) → 从 config.json 读取已保存链接
  → ensure_page(saved_url) → 找到已有页面或导航到该 URL
  → fill_prompt + submit → 在同一对话中继续
```

### config.json sessions 结构

```json
{
  "session_mode": "fixed",
  "sessions": {
    "项目A": {
      "deepseek": "https://chat.deepseek.com/a/chat/s/xxx",
      "kimi": "https://www.kimi.com/chat/xxx"
    },
    "项目B": {
      "deepseek": "https://chat.deepseek.com/a/chat/s/yyy"
    }
  }
}
```

- `session_mode: "fixed"` → 按项目名查找固定链接
- `session_mode: "auto"` → Agent 自行管理（不查 sessions）

---

## 五、关键数据文件

| 文件 | 格式 | 内容 |
|------|------|------|
| `config.json` | JSON | CDP端口、会话链接、API key、本地环境 |
| `data/{project}.jsonl` | JSONL | 每次搜索的 input/output 日志 |
| `data/latest_result.md` | Markdown | 最近一次搜索结果 |
| `data/workspace/task_{ts}.json` | JSON | 任务工作区（执行中状态） |
| `data/memory/{project}_episodes.jsonl` | JSONL | 搜索过程记录（平台/耗时/可信度） |
| `data/memory/{project}_semantic.md` | Markdown | 结论性知识（用户确认后归档） |
| `scripts/profiles/_global.json` | JSON | 全局知识库（CoT关键词、页尾特征） |
| `scripts/profiles/{platform}_extraction.json` | JSON | 平台提取档案 |

---

## 六、禁止修改标记汇总

### 绝对不可改

| 位置 | 内容 | 原因 |
|------|------|------|
| `common.py` | `ensure_page` URL 三级匹配（精确→平台→新建） | 经过大量试错验证的稳定策略 |
| `common.py` | `get_session_url` / `_save_session` 二级映射 | 会话路由的根基 |
| `prompt_builder.py` | `build_final_prompt` 标记对格式 `[搜索主题：{topic}]` | 标记格式变则提取全崩 |
| `prompt_builder.py` | `validate_prompt` 验证规则 | 防呆最后一道关 |
| `extractor.py` | `extract_with_diagnosis` 标记数量阈值（≥3/2/1/0） | 提取逻辑核心 |
| `extractor.py` | `dom_extract` DOM 选择器 | 主导提取方式 |
| `orchestrator.py` | `_wait_one` DOM主导 + 结尾标记判定 + 稳定检测 | 绝不提前提取 |
| `orchestrator.py` | `SEARCH_PLATFORM` / `SYNTH_PLATFORM` 变量名 | 平台替换接口 |
| `main.py` | `run_send` / `run_auto` 逻辑 | 已验证的备用入口 |
| `evolution.py` | `PollingProfile` 数据结构 | 轮询参数持久化 |

### 可自由修改

| 位置 | 内容 |
|------|------|
| `platforms/*.py` | 平台 DOM 选择器（随平台 UI 变化） |
| `profiles/*.json` | 平台档案数据（运行时自动更新） |
| `config.json` | 配置项 |
| `agent.py` | 流程编排参数（max_wait 等） |
| `orchestrator.py` | `SEARCH_PLATFORM` / `SYNTH_PLATFORM` 的值（换平台） |
| `planner.py` | `DECOMPOSE_PROMPT` 分解策略 |

---

## 七、与 Claude Code / Codex CLI 的关系

```
Claude Code / Codex CLI（调用方 Agent）
    │
    │  Skill 调用: web-ai-search
    │
    ▼
web-ai-search Skill（本仓库）
    │
    ├─ 通过 prefix_rule 白名单放行 venv Python
    ├─ 通过 CDP 协议操控用户浏览器中的 AI 平台
    │   (DeepSeek / Kimi / ChatGPT / Gemini / SCnet)
    │
    └─ 搜索结果写入 data/latest_result.md
        调用方 Agent 按需读取
```

**关键约束**:
1. 本 Skill 的 venv Python 必须在调用方 Agent 的沙箱白名单中
2. CDP 端口必须在调用前由用户手动开启（Agent 不自动启动浏览器）
3. 搜索结果写入文件而非注入 context，避免 token 浪费
