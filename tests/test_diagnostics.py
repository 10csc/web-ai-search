# -*- coding: utf-8 -*-
"""错误诊断模块测试 —— 验证各错误类型的诊断覆盖。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pytest
from diagnostics import diagnose, format_diagnosis, ERROR_CHECKS


class TestDiagnose:
    def test_send_failed_diagnosis(self):
        result = diagnose("send_failed", context={"platform": "deepseek"})
        assert result["error_type"] == "send_failed"
        assert result["total"] > 0
        assert "diagnosis" in result
        assert isinstance(result["passed"], int)

    def test_extract_failed_diagnosis(self):
        result = diagnose("extract_failed")
        assert result["error_type"] == "extract_failed"

    def test_llm_call_failed_diagnosis(self):
        result = diagnose("llm_call_failed")
        assert result["error_type"] == "llm_call_failed"

    def test_cdp_connection_failed_diagnosis(self):
        result = diagnose("cdp_connection_failed")
        assert result["error_type"] == "cdp_connection_failed"

    def test_config_error_diagnosis(self):
        result = diagnose("config_error")
        assert result["error_type"] == "config_error"

    def test_unknown_error_diagnosis(self):
        result = diagnose("unknown_error")
        assert result["error_type"] == "unknown_error"
        # unknown 应检查配置+CDP+API
        assert result["total"] >= 3

    def test_all_results_have_required_fields(self):
        for etype in ERROR_CHECKS:
            result = diagnose(etype)
            for r in result["results"]:
                assert "check" in r
                assert "passed" in r
                assert "message" in r
                assert "fix" in r

    def test_format_diagnosis_output(self):
        result = diagnose("config_error")
        output = format_diagnosis(result)
        assert "config_error" in output
        assert "通过" in output or "passed" in output


class TestDiagnoseCoverage:
    """确保所有 ERROR_CHECKS 中的错误类型都能正常诊断。"""
    def test_all_error_types_work(self):
        for etype in ERROR_CHECKS:
            result = diagnose(etype)
            assert result["error_type"] == etype
            assert result["total"] > 0

    def test_send_failed_has_all_checks(self):
        """send_failed 是最高频错误，应覆盖 CDP/会话/脚本/配置。"""
        result = diagnose("send_failed", context={"platform": "deepseek"})
        checks = [r["check"] for r in result["results"]]
        assert "CDP 连接" in checks
        assert "平台脚本" in checks
        assert "配置文件" in checks
