# -*- coding: utf-8 -*-
"""工具路由测试 —— 规则引擎分类（LLM 路径需要真实 API key，仅测 fallback）。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pytest
from tool_router import route, classify_fallback


class TestClassifyFallback:
    """规则引擎兜底路由测试。"""

    # === L3 深度信号 ===

    def test_depth_analysis_triggers_l3(self):
        _, depth, reason = classify_fallback("帮我做一次深度分析：K8s vs Nomad 全链路对比")
        assert depth == "L3"
        assert "深度关键词" in reason

    def test_full_chain_triggers_l3(self):
        _, depth, _ = classify_fallback("设计一个全链路监控系统的重构方案")
        assert depth == "L3"

    def test_security_audit_triggers_l3(self):
        _, depth, _ = classify_fallback("对微服务架构做安全审计")
        assert depth == "L3"

    def test_migration_path_triggers_l3(self):
        _, depth, _ = classify_fallback("PostgreSQL 到 MySQL 的迁移路径")
        assert depth == "L3"

    # === L2 分析信号 ===

    def test_comparison_triggers_l2(self):
        _, depth, _ = classify_fallback("React 和 Vue 的优缺点对比")
        assert depth == "L2"

    def test_selection_triggers_l2(self):
        _, depth, _ = classify_fallback("Rust 和 Go 怎么选")
        assert depth == "L2"

    def test_architecture_triggers_l2(self):
        _, depth, _ = classify_fallback("分布式消息队列的架构设计")
        assert depth == "L2"

    def test_best_practice_triggers_l2(self):
        _, depth, _ = classify_fallback("Django REST framework 最佳实践")
        assert depth == "L2"

    def test_recommendation_triggers_l2(self):
        _, depth, _ = classify_fallback("2026 年推荐用什么前端框架")
        assert depth == "L2"

    # === L1 事实信号 ===

    def test_version_triggers_l1(self):
        tool, depth, _ = classify_fallback("React 最新版本号是多少")
        assert tool == "WebSearch"
        assert depth == "L1"

    def test_api_signature_triggers_l1(self):
        tool, depth, _ = classify_fallback("asyncio.run 的 API 签名")
        assert tool == "WebSearch"
        assert depth == "L1"

    def test_port_triggers_l1(self):
        tool, depth, _ = classify_fallback("Redis 默认端口号")
        assert tool == "WebSearch"
        assert depth == "L1"

    # === 短查询 ===

    def test_short_query_defaults_l1(self):
        tool, depth, _ = classify_fallback("Python 版本号")
        assert tool == "WebSearch"
        assert depth == "L1"

    # === 兜底 ===

    def test_default_fallback(self):
        tool, depth, _ = classify_fallback("Python 在现代软件开发中扮演什么角色以及其生态系统发展趋势")
        assert tool == "WebAISearch"
        assert depth == "L2"

    def test_empty_string(self):
        tool, depth, _ = classify_fallback("")
        assert tool == "WebSearch"
        assert depth == "L1"


class TestRoute:
    """route() 入口测试 —— LLM 不可用时走 fallback。"""

    def test_route_returns_dict(self):
        result = route("Python vs Go 选型对比")
        assert "tool" in result
        assert "depth" in result
        assert "reason" in result
        assert "query" in result

    def test_route_tool_is_valid(self):
        result = route("随便问点什么")
        assert result["tool"] in ("WebSearch", "WebAISearch")

    def test_route_depth_is_valid(self):
        result = route("测试问题")
        assert result["depth"] in ("L1", "L2", "L3")

    def test_route_query_truncated(self):
        long_query = "测" * 200
        result = route(long_query)
        assert len(result["query"]) <= 100

    def test_route_l3_decompose_trigger(self):
        # 包含 L3 触发词："全链路"+"系统性"+"深度分析"
        result = route("帮我做深度分析：设计百万并发分布式消息系统的全链路架构方案，系统性地评估Kafka vs Pulsar")
        assert result["depth"] == "L3"
