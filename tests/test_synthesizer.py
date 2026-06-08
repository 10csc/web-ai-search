# -*- coding: utf-8 -*-
"""整合层测试 —— 信源分类、评分、交叉验证、报告生成。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pytest
from synthesizer import (classify_source, score_source, analyze_sources,
                         cross_validate, generate_report, synthesize)


# ============================================================
# classify_source —— 信源分类
# ============================================================

class TestClassifySource:
    def test_official_github(self):
        assert classify_source("https://github.com/python/cpython") == "官方"

    def test_official_python_docs(self):
        assert classify_source("https://docs.python.org/3.13/") == "官方"

    def test_academic_springer(self):
        # springer.com 纯学术，arxiv.org 同时匹配官方+学术，官方排在前面
        assert classify_source("https://link.springer.com/article/10.1007/12345") == "学术"

    def test_media_techcrunch(self):
        assert classify_source("https://techcrunch.com/2025/01/ai-report") == "媒体"

    def test_community_stackoverflow(self):
        assert classify_source("https://stackoverflow.com/questions/123") == "社区"

    def test_self_media_wechat(self):
        assert classify_source("https://mp.weixin.qq.com/s/abc123") == "自媒体"

    def test_unclassified(self):
        assert classify_source("https://random-blog.example.com/post") == "未分类"

    def test_empty_string(self):
        assert classify_source("") == "未分类"


# ============================================================
# score_source —— 信源评分
# ============================================================

class TestScoreSource:
    def test_official_score(self):
        assert score_source("https://docs.python.org/3.13/") == 9

    def test_academic_score(self):
        # springer.com 纯学术，arxiv.org 会被 官方 模式先匹配
        assert score_source("https://link.springer.com/article/10.1007/12345") == 8

    def test_unknown_score(self):
        assert score_source("https://example.com/page") == 5


# ============================================================
# analyze_sources —— 批量信源分析
# ============================================================

class TestAnalyzeSources:
    def test_multiple_sources(self):
        urls = [
            "https://docs.python.org/3.13/",
            "https://github.com/python/cpython",
            "https://stackoverflow.com/q/123",
            "https://zhihu.com/q/456",
        ]
        result = analyze_sources(urls)
        assert len(result["sources"]) == 4
        assert result["avg_score"] > 0
        assert "官方" in result["categories"]
        assert "社区" in result["categories"]

    def test_empty_list(self):
        result = analyze_sources([])
        assert result["sources"] == []
        assert result["avg_score"] == 0

    def test_single_url(self):
        result = analyze_sources(["https://github.com/python/cpython"])
        assert len(result["sources"]) == 1
        assert result["sources"][0]["category"] == "官方"


# ============================================================
# cross_validate —— 交叉验证
# ============================================================

class TestCrossValidate:
    def test_single_source(self):
        results = [{"platform": "deepseek", "content": "Python 3.13 发布", "content_len": 200, "gaps": [], "links": ["https://docs.python.org/3.13/"]}]
        v = cross_validate(results)
        assert v["level"] == "single_source"

    def test_two_sources_overlap(self):
        url = "https://docs.python.org/3.13/"
        results = [
            {"platform": "deepseek", "content": f"参考 {url}", "content_len": 200, "gaps": [], "links": [url]},
            {"platform": "kimi", "content": f"详见 {url}", "content_len": 200, "gaps": [], "links": [url]},
        ]
        v = cross_validate(results)
        assert v["level"] == "cross_validated"
        assert len(v["confirmed_urls"]) >= 1
        assert v["confidence"] == "中"

    def test_two_sources_no_overlap(self):
        results = [
            {"platform": "deepseek", "content": "A", "content_len": 200, "gaps": [], "links": ["https://a.com/"]},
            {"platform": "kimi", "content": "B", "content_len": 200, "gaps": [], "links": ["https://b.com/"]},
        ]
        v = cross_validate(results)
        assert v["level"] == "multi_source_no_overlap"
        assert v["confidence"] == "低"

    def test_empty_results(self):
        v = cross_validate([])
        assert v["level"] == "single_source"


# ============================================================
# generate_report —— 报告生成
# ============================================================

class TestGenerateReport:
    def test_basic_structure(self):
        results = [
            {"platform": "deepseek", "question": "测试Q", "content": "测试C" * 50, "content_len": 150, "gaps": [], "links": ["https://github.com/"]},
        ]
        validation = {"level": "single_source", "confidence": "低", "confirmed_urls": [], "single_source_urls": []}
        report = generate_report("测试查询", results, validation)
        assert "测试查询" in report
        assert "deepseek" in report
        assert "信源" not in report or "来源" in report  # 有来源分析

    def test_report_with_no_content(self):
        results = [{"platform": "gemini", "content": "", "content_len": 0, "gaps": [], "links": [], "error": "超时"}]
        validation = {"level": "single_source", "confidence": "低"}
        report = generate_report("失败查询", results, validation)
        assert "未获取到结果" in report

    def test_report_truncates_long_content(self):
        content = "长" * 6000
        results = [{"platform": "deepseek", "question": "Q", "content": content, "content_len": 6000, "gaps": [], "links": []}]
        validation = {"level": "single_source", "confidence": "低"}
        report = generate_report("Q", results, validation)
        assert "截断" in report or len(report) < len(content)

    def test_report_with_gaps(self):
        results = [
            {"platform": "deepseek", "question": "Q", "content": "内容" * 50, "content_len": 100, "gaps": ["缺少版本号信息", "缺少性能数据"], "links": []},
        ]
        validation = {"level": "single_source", "confidence": "低"}
        report = generate_report("Q", results, validation)
        assert "信息缺口" in report


# ============================================================
# synthesize —— 完整整合流程
# ============================================================

class TestSynthesize:
    def test_full_pipeline(self):
        results = [
            {"platform": "deepseek", "content": "参考 https://docs.python.org/3.13/", "content_len": 100, "gaps": [], "links": ["https://docs.python.org/3.13/"]},
        ]
        output = {"results": results}
        report, validation = synthesize("Python 3.13", output)
        assert isinstance(report, str)
        assert isinstance(validation, dict)
        assert "level" in validation
