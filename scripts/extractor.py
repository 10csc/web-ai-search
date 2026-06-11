# -*- coding: utf-8 -*-
"""提取模块 —— 标记对定位 + DOM 兜底。不筛 CoT/思考链（交给整合层处理）。"""

from evolution import GlobalKnowledge


def is_content_complete(text, platform=None):
    """基本质量检查：长度够 + 不是 prompt 回显 + 不是页尾 UI。"""
    if not text or len(text) < 150:
        return False
    if text.strip().startswith("请联网搜索"):
        return False
    # 页尾特征排除
    tail = text.strip()[-200:]
    for kw in GlobalKnowledge.get_footer_patterns():
        if kw in tail:
            return False
    return True


def _get_platform_sel(platform):
    """从平台脚本读取 EXTRACT_SEL，找不到用兜底选择器。"""
    import importlib.util, os
    try:
        platforms_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms")
        spec = importlib.util.spec_from_file_location(
            f"platform_{platform}", os.path.join(platforms_dir, f"{platform}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "EXTRACT_SEL", 'div[class*="message"]')
    except Exception:
        pass
    return 'div[class*="message"]'


def dom_extract(page, platform="deepseek"):
    """DOM 兜底：用平台脚本的选择器提取最后一个 AI 回复。"""
    try:
        sel = _get_platform_sel(platform)
        msgs = page.locator(sel)
        count = msgs.count()
        if count > 0:
            text = msgs.nth(count - 1).text_content() or ""
            if len(text) > 150:
                return text.strip()
    except Exception:
        pass
    return None


def extract_with_diagnosis(raw_text, prompt, topic, platform=None):
    """标记定位提取。

    策略：
    1. 标记 >= 3: 最后一对 = AI 的标记对，取 between-pair
    2. 标记 == 2: prompt的1个 + AI开头1个，取 post-last-marker（AI 回复中）
    3. 标记 == 1: 仅 prompt 标记，AI 尚未输出 → 返回 None
    4. 标记 == 0: 返回 None（交给 DOM 兜底）
    """
    marker = f"[搜索主题：{topic}]"

    positions = []
    idx = 0
    while True:
        idx = raw_text.find(marker, idx)
        if idx == -1:
            break
        positions.append(idx)
        idx += len(marker)

    if len(positions) >= 3:
        # AI 已输出开头+结尾标记：取 between-pair（AI 正式回复）
        content = raw_text[positions[-2] + len(marker):positions[-1]].strip()
        if len(content) >= 10 and is_content_complete(content, platform=platform):
            return content, None
        # between 太短/无效，取 post-last-marker 兜底
        fallback = raw_text[positions[-1] + len(marker):].strip()
        fallback = _strip_footer(fallback)
        if is_content_complete(fallback, platform=platform):
            return fallback, None
        return None, {"failure_type": "low_quality", "adaptable": False,
                       "_marker_count": len(positions)}

    if len(positions) == 2:
        # prompt 1个 + AI开头1个：取 post-last-marker（AI 回复内容，可能还在生成）
        content = raw_text[positions[-1] + len(marker):].strip()
        content = _strip_footer(content)
        if is_content_complete(content, platform=platform):
            return content, None
        return None, {"failure_type": "incomplete",
                       "evidence": f"仅2标记(AI未输出结尾标记)，post-marker内容{len(content)}字符",
                       "adaptable": False, "_marker_count": 2}

    if len(positions) == 1:
        # 仅 prompt 标记，AI 还没开始输出
        return None, {"failure_type": "ai_not_started",
                       "evidence": "仅1标记，AI尚未输出",
                       "adaptable": False, "_marker_count": 1}

    # 标记 = 0
    return None, {"failure_type": "marker_missing",
                   "evidence": f"页面{len(raw_text)}字符中未找到标记",
                   "adaptable": False, "_marker_count": 0}


def _strip_footer(text):
    """清除页尾 UI 文字。"""
    for kw in GlobalKnowledge.get_footer_patterns():
        pos = text.find(kw)
        if pos > 0 and pos > len(text) * 0.5:
            return text[:pos].strip()
    return text


def extract_content(raw_text, prompt, topic, platform=None):
    """兼容旧接口。"""
    content, _ = extract_with_diagnosis(raw_text, prompt, topic, platform)
    return content
