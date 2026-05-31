# 版本升级指南

## 🛡️ 升级铁律（最高优先级）

> **任何时候升级，以下文件/目录绝不覆盖、不删除、不重置：**

| 文件/目录 | 原因 | 内容 |
|----------|------|------|
| `config.json` | 含用户环境自举数据 | Python 路径、浏览器路径、CDP 端口、API 地址、session 绑定 |
| `data/` | 含搜索历史和结果 | JSONL 日志、latest_result.md、_prompt.txt、_topic.txt |
| `venv/` | 含用户已安装的依赖 | playwright、openai 等 pip 包 |
| `scripts/platforms/` | 含已定型的平台脚本 | deepseek.py、chatgpt.py、gemini.py 等 |
| `scripts/profiles/` | 含 DOM 分析快照 | 平台定型时的页面结构缓存 |

> **升级只能修改这些目录中的文件内容使其适配新版本，绝不能删除整个目录或覆盖为空白。**

> **如果新版本需要变更 config.json 的字段结构，只能通过 `common.py` 的 `load_config()` 自动补全缺失字段，绝不能覆盖现有配置。**

---

## 可安全覆盖的文件

升级时只覆盖以下文件（这些是纯代码/文档，不含用户数据）：

| 文件 | 说明 |
|------|------|
| `SKILL.md` | Agent 入口文档 |
| `LEARNINGS.md` | 架构知识 |
| `README.md` | 项目说明 |
| `setup.py` | 环境配置脚本 |
| `scripts/*.py` | 所有核心代码（common.py、main.py、extractor.py、prompt_builder.py、generator.py、logger.py） |
| `references/*.md` | 参考文档（pitfalls.md 等） |

---

## 安全升级步骤

### Agent 执行升级（推荐）

1. 读 `config.json` 的 `version` 字段
2. 如果 `version < 6`，执行以下步骤：
   - 覆盖所有 `scripts/*.py` 文件
   - 覆盖 `SKILL.md`、`LEARNINGS.md`、`README.md`、`setup.py`
   - 覆盖 `references/` 下所有文件
   - **不覆盖** `config.json`（只通过 `common.py` 的 `load_config()` 自动补全缺失字段）
   - **不动** `data/`、`venv/`、`scripts/platforms/`、`scripts/profiles/`
3. 检查 `config.json` 的 `local_env.initialized`：
   - `True` → 升级完成
   - `False` 或不存在 → 运行 `setup.py`

### 首次安装

1. 复制所有文件到 skill 目录
2. 运行 `python setup.py`（自动使用国内镜像源安装依赖）
3. 环境自举完成后 `config.json` 写入 `version: 6`

### 升级后验证

```bash
<PYTHON> -c "
from scripts.common import load_config, get_python_venv_path
cfg = load_config()
print(f'Version: {cfg.get(\"version\")}')
print(f'Initialized: {cfg.get(\"local_env\", {}).get(\"initialized\")}')
print(f'Python: {get_python_venv_path()}')"
```

---

## 版本历史

### v6（当前）

- 精简 SKILL.md，Agent 认知负担大幅降低
- 新增 `setup.py` 一次性环境探测，替代手动自举
- 全部改用 `import` 方式调用 Python，彻底解决 CLI 中文传参损坏
- 新增 `debug` 搜索模式（代码错误诊断）+ L1/L2/L3 三级深度控制
- `common.py` 兼容 v4/v5/v6 所有 config 格式
- `config.json` 增加 `version` 字段 + `session_mode` + `sessions` 会话管理
- 平台定型改为分步强制（send → 用户确认 → extract）
- `setup.py` 增加国内镜像源自动 fallback（清华→阿里→中科大）
- pitfalls.md 整理：18条 → 5条生效 + 13条归档

### v5

- 架构重构：`main.py`（send/extract/auto 三模式）+ `generator.py`（平台定型）+ `extractor.py`（通用标记对截取）
- 引入本地环境自举机制（Agent 手动探测）
- 引入平台定型机制（LLM 分析 DOM → 生成交互脚本）
- 双标记提取机制：`[搜索主题：xxx@hash]`

### v4

- 初始版本：`pipeline.py` + `auto_search.py` + `parse_result.py`
- DeepSeek/ChatGPT 双平台支持
- 递增扫描抓取策略

---

## config.json 版本兼容矩阵

| 版本 | version 字段 | local_env | session_mode | 升级行为 |
|------|-------------|-----------|-------------|---------|
| v4 | 无 | 无 | 无 | `load_config()` 自动补全所有字段，需运行 `setup.py` |
| v5 | 无 | 有但不完整 | 无 | `load_config()` 自动补全 `version: 6` + `session_mode` |
| v6 | 6 | 完整 | `fixed`/`auto` | 无需操作 |

`common.py` 的 `load_config()` 负责所有版本的兼容补全，Agent 不需要手动处理 config 格式差异。
