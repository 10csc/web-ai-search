# -*- coding: utf-8 -*-
"""工具选择层 —— LLM 语义路由。

原则：用户输入是自然语言（非定式），不能用硬编码关键词匹配。
用 fast 模型做毫秒级分类 → LLM 不可用时降级规则引擎。
"""

import json, ssl, os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

ROUTING_PROMPT = """你是搜索任务路由器。分析用户问题，输出 JSON 分类。

## 分类维度
- tool: "WebSearch"（单点事实，答案是一个确定值）或 "WebAISearch"（需要分析、对比、推理、综合判断）
- depth: "L1"（快速确认）、"L2"（标准调研，多维分析）、"L3"（深度研究，全链路架构设计）
- reason: 一句话（≤30字）

## 示例
"React 最新版本号" → {"tool":"WebSearch","depth":"L1","reason":"单点事实查询"}
"Python和Go在微服务场景下怎么选" → {"tool":"WebAISearch","depth":"L2","reason":"多维对比分析"}
"设计百万并发分布式消息系统完整方案" → {"tool":"WebAISearch","depth":"L3","reason":"全链路架构设计"}

## 规则
只输出 JSON，不要 markdown 代码块，不要其他文字。

问题："""


def _get_api_config():
    """从 config.json 读取 API 配置。"""
    config_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("deepseek_api", "https://api.deepseek.com/v1"), \
               cfg.get("deepseek_key", "")
    except Exception:
        return "https://api.deepseek.com/v1", ""


def classify_llm(user_query):
    """LLM 语义路由。失败返回 None。"""
    api_url, api_key = _get_api_config()
    if not api_key:
        return None

    try:
        from urllib.request import Request, urlopen

        payload = json.dumps({
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": "你是搜索路由器。输出纯 JSON。"},
                {"role": "user", "content": ROUTING_PROMPT + user_query},
            ],
            "temperature": 0.0,
            "max_tokens": 150,
        }, ensure_ascii=False).encode("utf-8")

        req = Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        ctx = ssl.create_default_context()
        resp = urlopen(req, timeout=10, context=ctx)
        body = json.loads(resp.read().decode("utf-8"))
        text = body["choices"][0]["message"]["content"].strip()

        # 清理 markdown 包裹
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        text = text.strip()

        result = json.loads(text)
        tool = result.get("tool", "WebAISearch")
        depth = result.get("depth", "L2")
        reason = result.get("reason", "LLM 路由")

        # 合法性校验
        if tool not in ("WebSearch", "WebAISearch"):
            tool = "WebAISearch"
        if depth not in ("L1", "L2", "L3"):
            depth = "L2"

        return tool, depth, reason

    except Exception as e:
        print(f"[Router] LLM 不可用: {e}")
        return None


# === 规则引擎（LLM 不可用时兜底，保持基本可用性）===

def classify_fallback(user_query):
    """规则引擎兜底。"""
    q = user_query.strip()

    # 深度信号
    if any(kw in q for kw in ["深度分析", "全链路", "系统性", "安全审计", "版本矩阵",
                                "重构方案", "迁移路径", "多方案"]):
        return "WebAISearch", "L3", "深度关键词命中"
    # 分析信号
    if any(kw in q for kw in ["对比", "选型", "方案", "区别", "差异", "优缺点",
                                "推荐", "哪个更", "怎么选", "架构", "设计",
                                "最佳实践", "迁移", "评估", "适用场景"]):
        return "WebAISearch", "L2", "分析关键词命中"
    # 事实信号
    if any(kw in q for kw in ["版本号", "多少钱", "地址", "电话", "端口号",
                                "默认配置", "API 签名", "函数签名"]):
        return "WebSearch", "L1", "事实关键词命中"
    # 短问题
    if len(q) <= 25:
        return "WebSearch", "L1", "短查询默认"

    return "WebAISearch", "L2", "兜底默认"


def route(user_query):
    """路由入口：LLM 优先，规则兜底。"""
    result = classify_llm(user_query)
    if result:
        tool, depth, reason = result
    else:
        tool, depth, reason = classify_fallback(user_query)

    return {
        "tool": tool,
        "depth": depth,
        "reason": reason,
        "query": user_query[:100],
    }


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')

    tests = [
        "React 最新版本号是多少？",
        "微服务和单体架构在 2026 年应该怎么选？",
        "帮我设计一个分布式任务调度系统的架构方案",
        "Rust 为什么会成为2026年最受开发者喜爱的语言？分析核心优势和应用场景",
        "Python asyncio 和 Trio 的核心区别是什么？",
        "LangGraph 的 Checkpoint 机制怎么配置？",
    ]
    for q in tests:
        result = route(q)
        print(f"[{result['tool']} / {result['depth']}] {q[:60]}")
        print(f"  理由: {result['reason']}\n")
