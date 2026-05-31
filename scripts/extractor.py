# -*- coding: utf-8 -*-
"""提取模块：用标记定位 → 基本有效性检查（不验证格式）"""


def is_content_complete(text):
    """只做存在性检查。格式正确性是 prompt 的事。"""
    if not text or len(text) < 150:
        return False
    if text.strip().startswith("请联网搜索"):
        return False
    # CoT / 页尾特征：不是正式回复内容
    head = text.strip()[:200]
    tail = text.strip()[-200:]
    cot_markers = ["已思考", "搜索到", "个网页"]
    if any(m in head for m in cot_markers):
        return False
    footer_markers = ["内容由 AI 生成", "本回答由 AI 生成"]
    if any(m in tail for m in footer_markers):
        return False
    return True


def _extract_core_keywords(topic):
    import re
    keywords = []
    if "@" in topic:
        hash_part = topic.split("@")[-1]
        if len(hash_part) == 4:
            keywords.append("@" + hash_part)
    clean = topic.split("@")[0] if "@" in topic else topic
    eng_words = re.findall(r"[a-zA-Z0-9]+", clean)
    for w in eng_words:
        if len(w) >= 2:
            keywords.append(w.lower())
    chinese_only = re.sub(r"[a-zA-Z0-9\s\-\u2014\u2013|/]+", "", clean)
    chinese_only = re.sub(r"[\uff01\uff1f\u3002\uff0c\u3001\uff1b\uff1a\u201c\u201d\u2018\u2019\uff08\uff09\u3010\u3011\u300a\u300b\u2026\u2020?!.,;:()\[\]]+", "", chinese_only)
    if len(chinese_only) >= 2:
        for win_size in [2, 3]:
            for i in range(len(chinese_only) - win_size + 1):
                keywords.append(chinese_only[i:i+win_size])
    if len(clean) >= 2:
        keywords.append(clean)
    seen = set()
    result = []
    for kw in keywords:
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result


def _contains_keywords(text, keywords):
    if not keywords:
        return True
    return sum(1 for kw in keywords if kw in text) >= 1


def extract_content(raw_text, prompt, topic):
    """用标记定位：收集所有标记位置 → 取最后一对 → 若非 CoT 则返回；若是 CoT 则取最后一个标记之后"""
    marker = f"[搜索主题：{topic}]"

    positions = []
    idx = 0
    while True:
        idx = raw_text.find(marker, idx)
        if idx == -1:
            break
        positions.append(idx)
        idx += len(marker)

    if len(positions) < 2:
        # 标记不足2个，取最后一个标记之后的所有内容作为降级
        if len(positions) == 1:
            content = raw_text[positions[0] + len(marker):].strip()
            if is_content_complete(content):
                return content
        return None

    # 取最后一对标记之间的内容
    start_pos = positions[-2] + len(marker)
    end_pos = positions[-1]
    content = raw_text[start_pos:end_pos].strip()

    if is_content_complete(content):
        core_keywords = _extract_core_keywords(topic)
        if core_keywords and not _contains_keywords(content, core_keywords):
            return None
        return content

    # 最后一对之间的内容无效（可能是 CoT），取最后一个标记之后的内容
    fallback = raw_text[positions[-1] + len(marker):].strip()
    if is_content_complete(fallback):
        core_keywords = _extract_core_keywords(topic)
        if core_keywords and not _contains_keywords(fallback, core_keywords):
            return None
        return fallback

    return None
