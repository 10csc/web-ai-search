# -*- coding: utf-8 -*-
"""搜索 Prompt —— 只负责标记对，搜索策略由模型自行设计。"""
import os, sys, time, random, hashlib, string
from common import load_config

DEFAULT_API = "https://api.deepseek.com/v1"


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


def build_final_prompt(topic, depth="L2"):
    """生成 prompt：搜索指令 + 标记对。搜索策略和回复结构由模型自行设计。"""
    topic_hash = hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:4]
    topic = f"{topic}@{topic_hash}"
    marker = f"[搜索主题：{topic}]"

    prompt = (
        f"请联网搜索并深入分析以下问题，自行设计搜索策略和回复结构：\n\n"
        f"**{topic.split('@')[0]}**\n\n"
        f"---\n"
        f"【定位要求】在你的回复最开头（第1行）和最末尾（最后1行）各放一行标记（共2行）：\n"
        f"`{marker}`\n"
        f"两行标记之间是你的正式回复内容。标记必须独占一行。"
    )
    return topic, prompt


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
