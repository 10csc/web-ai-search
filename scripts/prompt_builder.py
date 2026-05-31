# -*- coding: utf-8 -*-
"""搜索 Prompt 生成器 -- 新闻/代码选型/代码调试三模式 + 三级搜索深度"""
import os, sys, time, re
from common import load_config

DEFAULT_API = "http://localhost:3688/v1"

# ====== 新闻模式 ======

NEWS_RULES = """## 搜索规则
1. **停一停**：在深入阅读任何信息前，先判断来源是否可信
2. **调查来源**：搜索来源名称，了解其背景、立场和声誉
3. **找可信报道**：寻找权威来源对同一话题的独立报道，至少2个独立来源交叉验证
4. **追溯原始**：追溯到信息的原始出处，不依赖二手转述
5. **时效性**：优先最近6个月的信息；涉及政策/数据时标注发布时间
6. **权威性**：优先官方机构、学术论文、知名媒体；警惕自媒体和个人博客
7. **区分事实与观点**：明确标注哪些是事实、哪些是分析/推测/观点
8. **声明局限**：若信息不完整、存在争议或来源可能有利益冲突，主动说明"""

NEWS_FORMAT = """## 输出格式要求
1. **必须包含来源列表**：每条信息来源需标注名称和链接
2. **可信度自评**：对本次搜索结果给出1-10分的可信度评分，并说明理由
3. **信息压缩**：核心要点不超过7条，每条不超过50字
4. **回复结构**：概述 → 核心要点 → 详细分析 → 来源评价 → 局限性说明
5. **纯Markdown**：禁止HTML标签、emoji表情、装饰符号
6. **纯中文**：所有解释和描述必须使用中文，专业术语可保留英文原名
7. **禁止多余内容**：不输出问候语、不输出AI自我介绍、不输出与主题无关的闲聊"""

# ====== 代码选型模式 ======

CODE_RULES = """## 搜索规则
1. **技术可行性优先**：搜索目标技术栈的官方文档、GitHub仓库、技术博客，评估方案成熟度
2. **社区活跃度**：关注项目的Star数、最近更新时间、Issue响应速度，判断项目维护状态
3. **方案对比**：至少搜索2个替代方案，从性能/兼容性/学习成本/生态四个维度横向对比
4. **生产环境验证**：优先找有生产环境案例的文章，避免纯Demo或实验性方案
5. **版本兼容性**：明确搜索具体版本号的兼容矩阵，标注各版本差异
6. **性能benchmark**：搜索公开的性能测试数据，避免主观评价
7. **迁移与集成成本**：评估现有代码迁移的工作量和潜在风险
8. **声明局限**：说明搜索到的方案适用场景和已知局限"""

CODE_FORMAT = """## 输出格式要求
1. **必须包含来源列表**：每条来源标注名称+链接+可信度等级
2. **核心要点**：不超过7条，每条聚焦一个技术决策点，含量化数据（如有）
3. **方案对比表**：至少列出2个方案，从性能、兼容性、学习成本、生态、社区活跃度五维对比
4. **可操作性评估**：给出明确的推荐方案和备选方案，标注适用场景和前提条件
5. **风险评估**：列出实施过程中可能遇到的坑点、兼容性问题和性能瓶颈
6. **回复结构**：概述 → 核心要点 → 方案对比表 → 可操作性评估 → 风险评估 → 来源评价 → 局限性说明
7. **纯Markdown**：禁止HTML标签、emoji表情、装饰符号
8. **纯中文**：所有解释和描述必须使用中文，技术术语和代码保留英文原名
9. **禁止多余内容**：不输出问候语、自我介绍、无关闲聊"""

# ====== 代码调试模式（v6 新增） ======

DEBUG_RULES_L1 = """## 搜索规则（快速确认模式）
1. **精确匹配**：只搜索错误信息中的关键标识符（报错类名、函数名、模块名）
2. **版本锁定**：必须包含具体版本号，只搜该版本相关的变更
3. **官方优先**：优先官方文档的 Migration Guide / Changelog / Release Notes
4. **快速判断**：目标是在3分钟内确定根因，不展开深度调研
5. **简洁输出**：只给根因+最快修复方案，不需要多方案对比"""

DEBUG_RULES_L2 = """## 搜索规则（标准调研模式）
1. **精确匹配**：搜索错误信息 + 版本号 + 环境信息
2. **多源交叉验证**：至少搜索官方文档 + GitHub Issues + StackOverflow 三个渠道
3. **版本追踪**：检查该库最近3个大版本的 Changelog，确认是否为已知 breaking change
4. **区分根因与表象**：报错信息可能是间接后果，追溯调用链找到真正触发点
5. **方案对比**：至少给出2个修复路径（升级/降级/替换API/配置调整），标注各自的副作用"""

DEBUG_RULES_L3 = """## 搜索规则（深度研究模式）
1. **全链路排查**：从报错点出发，搜索整个依赖链（直接依赖→间接依赖→系统环境）
2. **版本矩阵**：列出该库最近6个大版本的相关变更，标注各版本的API迁移路径
3. **社区深度挖掘**：搜索 GitHub Issues 中closed/open的所有相关讨论、相关 PR、相关 Discussion
4. **性能与安全**：评估各修复方案对性能和安全的影响
5. **回归测试**：搜索是否有已知的修复引入新bug的案例"""

DEBUG_FORMAT_L1 = """## 输出格式要求（快速确认）
1. **根因**：一句话说清错误原因
2. **修复**：一句话给出修复方案（含代码diff）
3. **来源**：1个权威来源链接
4. **回复结构**：根因 → 修复 → 来源
5. **纯中文Markdown，禁止多余内容**"""

DEBUG_FORMAT_L2 = """## 输出格式要求（标准调研）
1. **必须包含来源列表**：每条来源标注名称+链接+可信度等级
2. **根因分析**：明确指出错误原因，区分是API变更、版本不兼容还是配置问题
3. **证据**：引用官方文档/Issue/PR中的原文关键句
4. **候选方案**：A/B至少2个方案，标注各方案的前提条件和副作用
5. **推荐方案**：给出明确推荐并说明理由
6. **风险评估**：标注修复可能引入的新问题
7. **回复结构**：根因分析 → 证据 → 候选方案 → 推荐方案 → 风险评估 → 来源评价
8. **纯Markdown**：禁止HTML标签、emoji表情、装饰符号
9. **纯中文**：技术术语和代码保留英文原名
10. **禁止多余内容**"""

DEBUG_FORMAT_L3 = """## 输出格式要求（深度研究）
1. **必须包含来源列表**：每条来源标注名称+链接+可信度等级
2. **根因分析**：详细说明错误触发机制，含调用链分析
3. **版本矩阵**：列出相关库各版本的API状态，标注breaking change节点
4. **证据**：引用官方文档/Issue/PR/SO回答中的关键片段
5. **候选方案**：A/B/C至少3个方案，从修复成本、副作用、长期维护三个维度对比
6. **推荐方案**：给出明确推荐并说明优先级排序理由
7. **迁移路径**：如涉及版本升级，给出分步迁移计划
8. **风险评估**：标注各方案可能引入的新问题及其概率
9. **回复结构**：根因分析 → 版本矩阵 → 证据 → 候选方案 → 推荐方案 → 迁移路径 → 风险评估 → 来源评价
10. **纯Markdown，纯中文，禁止多余内容**"""

# ====== 本地关键词分类 ======

CODE_KW = ['方案', '选型', '对比', '区别', '差异', '优化', '性能', '架构', '兼容', '可行性', '代码', '实现', '技术', '配置', '部署', '测试', 'vs', 'VS', '框架', '库', 'API', '选择', '适用', '场景']

# 错误特征关键词：仅在 LLM 不可用时作为兜底分类（高精度词，避免误判）
DEBUG_KW = [
    'ImportError', 'ModuleNotFoundError', 'AttributeError', 'TypeError',
    'NameError', 'KeyError', 'ValueError', 'SyntaxError', 'IndentationError',
    'DeprecationWarning', 'FutureWarning', 'No module named', 'cannot import',
    'has no attribute', 'unexpected keyword', 'missing required',
    'removed in version', 'breaking change',
]


def _has_traceback(text):
    """检测用户输入是否包含错误 traceback"""
    # 标准 Python traceback 特征
    if 'Traceback (most recent call last):' in text:
        return True
    if re.search(r'File ".*", line \d+', text):
        return True
    # 含有多个错误特征关键词
    hits = sum(1 for kw in DEBUG_KW[:15] if kw in text)  # 只用前15个最明确的
    return hits >= 2


def classify_local(topic):
    """本地关键词分类（LLM 不可用时的兜底）"""
    # 先检查 debug 特征
    if any(kw in topic for kw in DEBUG_KW[:15]):
        return 'debug'
    if any(kw in topic for kw in CODE_KW):
        return 'code'
    return 'news'


def extract_intent(user_context, depth="L2"):
    """提取搜索意图和类型。depth 参数仅传递给分类 prompt 供参考。"""
    # 本地预检：含 traceback 直接判定为 debug
    if _has_traceback(user_context):
        topic = _extract_debug_topic(user_context)
        return (topic, "debug")

    try:
        from openai import OpenAI
        config = load_config()
        client = OpenAI(base_url=config.get("deepseek_api", DEFAULT_API), api_key="local")
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{
                "role": "system",
                "content": (
                    "分析用户消息：1) 提取核心搜索意图，用一句话概括（<=30字）"
                    "2) 判断类型：code（技术选型/代码优化/架构方案/性能分析/技术可行性）、"
                    "debug（代码报错/异常排查/版本兼容问题/bug修复/导入错误）、"
                    "或 news（行业动态/热点事件/政策法规/市场分析）"
                    "输出格式：TYPE:code|debug|news\nTOPIC:搜索主题\n不要多余解释。"
                )
            }, {"role": "user", "content": user_context}],
            temperature=0.1, max_tokens=150,
        )
        text = resp.choices[0].message.content.strip()
        ptype = "news"
        topic = ""
        for line in text.split("\n"):
            if line.startswith("TYPE:"):
                val = line[5:].strip().lower()
                if val in ("code", "debug", "news"):
                    ptype = val
            elif line.startswith("TOPIC:"):
                topic = line[6:].strip()
        if not topic:
            topic = text.split("\n")[-1].strip()
        # 本地关键词覆盖兜底
        if ptype == 'news':
            ptype = classify_local(topic)
        return (topic, ptype) if topic else (user_context[:80], "news")
    except Exception:
        lines = [l for l in user_context.split("\n") if l.strip()]
        t = lines[-1][:80] if lines else user_context[:80]
        return (t, classify_local(t))


def _extract_debug_topic(user_context):
    """从 traceback 中提取简洁的 bug 描述作为 topic（用于标记定位和搜索）"""
    lines = user_context.strip().split("\n")
    error_line = ""
    error_type = ""
    
    # 1. 优先找最后一行的 Error/Exception
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        m = re.search(r'(\w+(?:Error|Exception|Warning))(?:\s*:\s*)?(.*)', line)
        if m:
            error_type = m.group(1)
            error_line = m.group(2).strip() if m.group(2) else ""
            break
    
    # 2. 如果没找到 Error/Exception，找 No module / cannot import
    if not error_type:
        for line in reversed(lines):
            if 'No module named' in line:
                error_type = "ModuleNotFoundError"
                error_line = line.strip()
                break
            if 'cannot import' in line:
                error_type = "ImportError"
                error_line = line.strip()
                break
            if 'not found' in line.lower():
                error_type = "NotFoundError"
                error_line = line.strip()
                break
    
    # 3. 兜底
    if not error_type:
        error_type = "Bug"
        error_line = lines[-1].strip()[:80] if lines else "未知错误"
    
    # 4. 清理：去掉路径、引号噪声
    error_line = re.sub(r'File ".*?", ', '', error_line)
    error_line = re.sub(r'[\"\'`]', '', error_line)
    error_line = error_line.strip()
    
    # 5. 提取核心字段（模块名、函数名等）
    module_match = re.search(r"(?:No module named |from )['\"]?(\w+(?:\.\w+)*)", error_line)
    module_name = module_match.group(1) if module_match else ""
    
    # 6. 组装 topic：bug + 错误类型 + 核心信息
    parts = ["bug", error_type]
    if module_name:
        parts.append(module_name)
    if error_line and len(error_line) < 80:
        # 取错误描述的前几个有意义词
        desc = error_line.split(":")[-1].strip() if ":" in error_line else error_line
        desc = re.sub(r'\s+', ' ', desc)[:40]
        if desc and desc not in str(parts):
            parts.append(desc)
    
    topic = " ".join(parts)
    # 确保 topic 长度合理（不超过50字符，留给 @hash 空间）
    if len(topic) > 50:
        topic = topic[:47] + "..."
    return topic


def build_final_prompt(topic, ptype, depth="L2"):
    """生成最终搜索 prompt，保持双标记机制不变"""
    import random, hashlib, string

    topic_hash = hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:4]
    seed = ''.join(random.choices(string.ascii_lowercase + string.digits, k=3))
    topic = f"{topic}@{topic_hash}"
    marker = f"[搜索主题：{topic}]"
    depth = depth if depth in ("L1", "L2", "L3") else "L2"

    if ptype == "debug":
        if depth == "L1":
            rules, fmt = DEBUG_RULES_L1, DEBUG_FORMAT_L1
        elif depth == "L3":
            rules, fmt = DEBUG_RULES_L3, DEBUG_FORMAT_L3
        else:
            rules, fmt = DEBUG_RULES_L2, DEBUG_FORMAT_L2
        label = "代码错误诊断"
    elif ptype == "code":
        rules, fmt = CODE_RULES, CODE_FORMAT
        label = "技术方案分析"
    else:
        rules, fmt = NEWS_RULES, NEWS_FORMAT
        label = "新闻热点分析"

    prompt_text = (
        f"请联网搜索以下{label}主题：**{topic.split('@')[0]}**\n\n"
        f"{rules}\n\n"
        f"{fmt}\n\n"
        f"---\n"
        f"请严格按上述规则和格式要求执行搜索并回复。**必须使用中文**。\n\n"
        f"【定位要求】在你的正式回复（非思考过程）的开头和结尾，分别加上一行：\n"
        f"`{marker}`\n"
        f"注意：这行定位符必须独占一行，中间内容不能包含此行。"
    )
    return topic, prompt_text


if __name__ == "__main__":
    ctx = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    depth = sys.argv[2] if len(sys.argv) > 2 else "L2"
    topic, ptype = extract_intent(ctx, depth)
    if not topic:
        print("NONE")
        sys.exit(0)
    topic, prompt = build_final_prompt(topic, ptype, depth)
    print(f"TOPIC:{topic}")
    print(f"TYPE:{ptype}")
    print(f"DEPTH:{depth}")
    print(prompt)