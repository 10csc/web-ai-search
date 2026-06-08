# -*- coding: utf-8 -*-
"""编排层测试 —— 平台配置检查、平台模块加载。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import json, tempfile, shutil
import pytest


@pytest.fixture
def temp_skill():
    tmp = tempfile.mkdtemp(prefix="orchtest_")
    cfg = {
        "version": 6, "session_mode": "fixed",
        "sessions": {
            "myproject": {
                "deepseek": "https://chat.deepseek.com/a/chat/s/abc123",
                "kimi": "https://www.kimi.com/chat/xyz789",
            }
        },
        "current_project": "myproject",
        "platform_urls": {
            "deepseek": "https://chat.deepseek.com/",
            "kimi": "https://www.kimi.com/",
        },
        "cdp_port": 9223,
    }
    with open(os.path.join(tmp, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    import common
    old_skill = common.SKILL_DIR
    old_config = common.CONFIG_PATH
    common.SKILL_DIR = tmp
    common.CONFIG_PATH = os.path.join(tmp, "config.json")
    yield tmp
    common.SKILL_DIR = old_skill
    common.CONFIG_PATH = old_config
    shutil.rmtree(tmp, ignore_errors=True)


class TestCheckPlatformConfig:
    def test_configured_projects(self, temp_skill):
        import orchestrator
        output = orchestrator.check_platform_config(project="myproject")
        assert "deepseek" in output
        # SEARCH_PLATFORM 和 SYNTH_PLATFORM 可能相同
        assert "已配置" in output

    def test_returns_string(self, temp_skill):
        import orchestrator
        output = orchestrator.check_platform_config()
        assert isinstance(output, str)
        assert len(output) > 0


class TestGetPlatformModule:
    def test_deepseek_module(self):
        from generator import load_platform_module
        mod = load_platform_module("deepseek")
        assert hasattr(mod, "fill_prompt")
        assert hasattr(mod, "submit")
        assert hasattr(mod, "dismiss_blockers")

    def test_kimi_module(self):
        from generator import load_platform_module
        mod = load_platform_module("kimi")
        assert hasattr(mod, "fill_prompt")
        assert hasattr(mod, "submit")

    def test_chatgpt_module(self):
        from generator import load_platform_module
        mod = load_platform_module("chatgpt")
        assert hasattr(mod, "fill_prompt")


class TestSEARCHAndSYNTHPlatforms:
    """验证平台获取函数正常返回已知平台名。"""
    def test_search_platform(self):
        import orchestrator
        p = orchestrator._get_search_platform()
        assert p in ("deepseek", "kimi", "chatgpt", "gemini", "scnet")

    def test_synth_platform(self):
        import orchestrator
        p = orchestrator._get_synthesis_platform()
        assert p in ("deepseek", "kimi", "chatgpt", "gemini", "scnet")
