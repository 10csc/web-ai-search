# -*- coding: utf-8 -*-
"""搜索 Prompt —— 搜索阶段开放式探索+可靠性自标注，整合阶段被动验证+可信度报告。"""
import os, sys, time, random, hashlib, string, re
from common import load_config

DEFAULT_API = "https://api.deepseek.com/v1"

# === 可靠性标注正则 ===
RELIABILITY_PATTERNS = {
    "confirmed": re.compile(r'\[已确认(?::\s*(.+?))?\]'),
    "inferred": re.compile(r'\[推断(?::\s*(.+?))?\]'),
    "unconfirmed": re.compile(r'\[未确认(?::\s*(.+?))?\]'),
}


def extract_intent(user_context):
    """提取搜索主题（≤40字），用于生成 topic 标记。"""
    # 含 traceback → 截取核心错误
    if 'Traceback (most recent call last):' in user_context:
        lines = [l.strip() for l in user_context.split('\n') if l.strip()]
        for line in reversed(lines):
            if 'Error' in line or 'Exception' in line:
                return line[:60]
        return lines[-1][:60] if lines else user_context[:60]

    try:
        from openai import OpenAI
        config = load_config()
        client = OpenAI(base_url=config.get("deepseek_api", DEFAULT_API), api_key="local")
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{
                "role": "system",
                "content": "提取用户问题的核心搜索主题（≤40字）。只输出主题，不要解释。"
            }, {"role": "user", "content": user_context}],
            temperature=0.1, max_tokens=80,
        )
        topic = resp.choices[0].message.content.strip()
        return topic if topic else user_context[:80]
    except Exception:
        # LLM 不可用：取用户最后一行作为主题
        lines = [l for l in user_context.split("\n") if l.strip()]
        return lines[-1][:80] if lines else user_context[:80]


def _make_topic_marker(topic):
    """生成带 hash 的 topic 和标记字符串。"""
    topic_hash = hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:4]
    topic = f"{topic}@{topic_hash}"
    marker = f"[搜索主题：{topic}]"
    return topic, marker


def _marker_fence(marker):
    """标记对定位要求（搜索和整合共享）。"""
    return (
        f"【定位要求】在你的回复最开头（第1行）和最末尾（最后1行）各放一行标记（共2行）：\n"
        f"`{marker}`\n"
        f"两行标记之间是你的正式回复内容。标记必须独占一行。"
    )


def build_search_prompt(topic, depth="L2"):
    """搜索阶段提示词：开放式探索 + 可靠性自标注。

    行为约束（不约束结构）：
    - 每条关键结论标注可信度：[已确认:url] / [推断] / [未确认]
    - 至少给出 2 条独立分析路径，每条路径有各自的结论和来源
    - 无法确认的结论诚实标注而非编造
    - 优先使用高可信度信源（官方文档、学术论文、开源仓库）
    """
    topic, marker = _make_topic_marker(topic)
    core = topic.split("@")[0]

    prompt = (
        f"请联网搜索并深入分析以下问题，自行设计搜索策略和回复结构：\n\n"
        f"**{core}**\n\n"
        f"---\n"
        f"【可靠性要求】\n"
        f"1. 每条关键结论必须标注可信度：\n"
        f"   - 有明确来源支撑 → [已确认: 来源URL或名称]\n"
        f"   - 基于推理但来源不直接 → [推断]\n"
        f"   - 无法找到可靠来源 → [未确认]\n"
        f"2. 至少给出 2 条独立分析路径（独立 = 不同角度/不同信源群）\n"
        f"3. 优先引用官方文档、学术论文、开源仓库，避免自媒体/营销号\n"
        f"4. 无法确认的结论诚实标注，不要为凑来源而引用低质信源\n\n"
        f"{_marker_fence(marker)}"
    )
    return topic, prompt


def build_synthesis_prompt(topic, depth="L2"):
    """整合阶段提示词：被动验证 + 交叉确认 + 可信度报告。

    行为约束（不约束结构）：
    - 对素材中每条关键结论，独立搜索至少一次进行确认
    - 标注验证结果：[已验证:url] / [存疑:原因] / [矛盾:来源A vs 来源B]
    - 生成带可信度评分的最终报告
    - 无法验证的标注 [未确认]，不编造确认来源
    """
    topic, marker = _make_topic_marker(topic)
    core = topic.split("@")[0]

    prompt = (
        f"你是一位研究审核员。请对以下素材进行独立验证并生成最终报告：\n\n"
        f"**{core}**\n\n"
        f"---\n"
        f"【验证要求】\n"
        f"1. 提取素材中的每条关键结论，独立搜索至少一次进行确认\n"
        f"2. 标注验证结果：\n"
        f"   - 搜索确认一致 → [已验证: 确认来源URL]\n"
        f"   - 搜索后仍有疑虑 → [存疑: 具体原因]\n"
        f"   - 不同来源说法冲突 → [矛盾: 来源A vs 来源B]\n"
        f"   - 无法找到独立来源验证 → [未确认]\n"
        f"3. 在报告末尾给出整体可信度评分（1-10），附评分理由\n"
        f"4. 不编造验证来源——宁可标注 [未确认]，不给虚假确认\n"
        f"5. 最终报告应包含：概述、已验证结论、存疑结论、矛盾标记、可信度评分\n\n"
        f"{_marker_fence(marker)}"
    )
    return topic, prompt


def build_final_prompt(topic, depth="L2"):
    """兼容旧接口：默认走搜索阶段提示词。整合阶段请用 build_synthesis_prompt。"""
    return build_search_prompt(topic, depth)


def validate_prompt(prompt, topic):
    """防呆：确保 prompt 包含标记对。返回 (ok, errors)。"""
    errors = []
    if not prompt or len(prompt) < 50:
        errors.append("PROMPT_TOO_SHORT")
    if not topic or "@" not in topic:
        errors.append("TOPIC_NO_HASH")
    else:
        hash_part = topic.split("@")[-1]
        if len(hash_part) != 4:
            errors.append(f"TOPIC_HASH_LEN:{len(hash_part)}")

    marker = f"[搜索主题：{topic}]"
    if marker not in prompt:
        errors.append("MARKER_MISSING")

    return len(errors) == 0, errors


def assess_reliability(content):
    """统计可靠性标注，判定搜索结果是否可靠。

    返回 {confirmed:N, inferred:N, unconfirmed:N, reliable:bool, fallback:bool}。

    兜底：0 个标注 → 默认通过（reliable=True, fallback=True），不阻塞流程。
    """
    if not content:
        return {"confirmed": 0, "inferred": 0, "unconfirmed": 0,
                "reliable": False, "fallback": True}

    counts = {
        "confirmed": len(RELIABILITY_PATTERNS["confirmed"].findall(content)),
        "inferred": len(RELIABILITY_PATTERNS["inferred"].findall(content)),
        "unconfirmed": len(RELIABILITY_PATTERNS["unconfirmed"].findall(content)),
    }
    total = sum(counts.values())

    if total == 0:
        counts["reliable"] = True
        counts["fallback"] = True
    else:
        counts["reliable"] = counts["confirmed"] > 0 and counts["confirmed"] >= counts["unconfirmed"]
        counts["fallback"] = False

    return counts


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')
    ctx = _sys.argv[1] if len(_sys.argv) > 1 else _sys.stdin.read()
    topic = extract_intent(ctx)
    if not topic:
        print("NONE")
        _sys.exit(0)
    topic, prompt = build_final_prompt(topic)
    ok, errors = validate_prompt(prompt, topic)
    print(f"TOPIC:{topic}")
    print(f"VALID:{'OK' if ok else 'FAIL:' + '; '.join(errors)}")
    print(prompt)
