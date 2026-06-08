# -*- coding: utf-8 -*-
"""提取模块测试 —— 标记对截取、内容完整性、页尾清除、DOM 选择器映射。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pytest
from extractor import (is_content_complete, extract_with_diagnosis,
                       extract_content, _strip_footer)


# ============================================================
# is_content_complete
# ============================================================

class TestIsContentComplete:
    def test_empty(self):
        assert not is_content_complete("")

    def test_none(self):
        assert not is_content_complete(None)

    def test_too_short(self):
        assert not is_content_complete("短内容")

    def test_minimum_length(self):
        # 刚好 150 字符
        text = "测" * 150
        assert is_content_complete(text)

    def test_prompt_echo(self):
        # AI 回显了 prompt 开头 → 应拒绝
        text = "请联网搜索" + "测" * 200
        assert not is_content_complete(text)

    def test_footer_keyword(self):
        text = "测" * 200 + "\n\n内容由 AI 生成，仅供参考"
        assert not is_content_complete(text)

    def test_footer_window_nuxt(self):
        text = "测" * 200 + "window.__NUXT__"
        assert not is_content_complete(text)

    def test_footer_please_check(self):
        text = "测" * 200 + "请仔细甄别"
        assert not is_content_complete(text)

    def test_normal_content(self):
        text = "Python 3.13 引入了新的 asyncio 特性，包括 TaskGroup 改进..." + "A" * 300
        assert is_content_complete(text)


# ============================================================
# _strip_footer
# ============================================================

class TestStripFooter:
    def test_ai_generated_footer(self):
        # _strip_footer 只在关键词出现在文本后半段（>50%）时才剪切
        text = "这是有用的内容。" + "X" * 100 + "\n\n内容由 AI 生成，仅供参考\n\n其他文字"
        result = _strip_footer(text)
        assert "内容由 AI 生成" not in result
        assert "这是有用的内容" in result

    def test_nuxt_footer(self):
        text = "正文内容" + "X" * 100 + "\nwindow.__NUXT__配置信息"
        result = _strip_footer(text)
        assert "window.__NUXT__" not in result

    def test_no_footer(self):
        text = "纯正文内容，没有任何页尾标识"
        assert _strip_footer(text) == text

    def test_short_footer(self):
        # 页尾在开头（不太可能但也测试一下）
        text = "内容由 AI 生成\n正文正文正文正文正文正文正文正文正文正文正文正文正文正文"
        result = _strip_footer(text)
        # 只在后半段才清除
        assert "内容由 AI 生成" in result  # 在开头所以不剪切


# ============================================================
# extract_with_diagnosis —— 标记对定位
# ============================================================

class TestExtractWithDiagnosis:
    MARKER_PREFIX = "[搜索主题："
    TOPIC = "测试问题@abcd"

    def _marker(self, topic=None):
        t = topic or self.TOPIC
        return f"{self.MARKER_PREFIX}{t}]"

    def _long_content(self, base="这是AI的正式回复内容"):
        return base + "X" * 200

    def test_three_markers_full_pair(self):
        """3 标记：AI开头 + AI结尾 + 额外标记（模拟 prompt 标记也在页面上）→ 取 between"""
        m = self._marker()
        content = self._long_content()
        # 3 标记结构：第1个是 prompt 标记，第2个是 AI 开头，第3个是 AI 结尾
        text = f"{m}\n{m}\n{content}\n{m}\n一些页尾"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is not None
        assert len(result) > 100

    def test_three_markers_between_too_short(self):
        """3 标记但 between 太短 → 走 post-last-marker 兜底"""
        m = self._marker()
        long_content = self._long_content()
        # between 只有几个字符
        text = f"{m}\n{m}\n短\n{m}\n{long_content}"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is not None
        assert "X" in result  # 兜底拿到了长内容

    def test_two_markers_with_content(self):
        """2 标记：prompt + AI开头，无结尾 → 取 post-last-marker"""
        m = self._marker()
        content = self._long_content()
        text = f"{m}\n{m}\n{content}"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is not None

    def test_two_markers_content_incomplete(self):
        """2 标记，post-marker 内容太短 → 返回 incomplete 诊断"""
        m = self._marker()
        text = f"{m}\n{m}\n太短了"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is None
        assert diag is not None
        assert diag["failure_type"] == "incomplete"

    def test_one_marker_only(self):
        """1 标记 → AI 尚未输出"""
        m = self._marker()
        text = f"prompt\n{m}\n"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is None
        assert diag is not None
        assert diag["failure_type"] == "ai_not_started"

    def test_zero_markers(self):
        """0 标记 → marker_missing"""
        text = "这是AI回复但没有标记" + "X" * 300
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is None
        assert diag is not None
        assert diag["failure_type"] == "marker_missing"

    def test_extract_content_compat(self):
        """兼容旧接口 extract_content（3标记场景）"""
        m = self._marker()
        content = self._long_content()
        text = f"{m}\n{m}\n{content}\n{m}"
        result = extract_content(text, "prompt", self.TOPIC)
        assert result is not None

    def test_four_markers(self):
        """4 标记（罕见但应正确处理）"""
        m = self._marker()
        content = self._long_content()
        text = f"{m}\n{m}\n{m}\n{content}\n{m}"
        result, diag = extract_with_diagnosis(text, "prompt", self.TOPIC)
        assert result is not None

    def test_markers_with_uuid_topic(self):
        """带 hash 的复杂 topic（3标记场景）"""
        topic = "LLM推理框架对比分析@f3a2"
        m = self._marker(topic)
        content = self._long_content()
        text = f"{m}\n{m}\n{content}\n{m}"
        result, diag = extract_with_diagnosis(text, "prompt", topic)
        assert result is not None
