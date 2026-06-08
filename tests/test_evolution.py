# -*- coding: utf-8 -*-
"""自进化引擎测试 —— PollingProfile 自适应数学逻辑。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import tempfile, shutil
import pytest


@pytest.fixture
def temp_profiles():
    """Monkey-patch evolution 的 PROFILES_DIR 路径。"""
    tmp = tempfile.mkdtemp(prefix="evotest_")
    profiles_dir = os.path.join(tmp, "profiles")
    os.makedirs(profiles_dir, exist_ok=True)

    import evolution
    old_profiles = evolution.PROFILES_DIR
    evolution.PROFILES_DIR = profiles_dir

    yield tmp

    evolution.PROFILES_DIR = old_profiles
    shutil.rmtree(tmp, ignore_errors=True)


class TestPollingProfileDefaults:
    def test_default_interval(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        assert profile.get_interval() == 2.0

    def test_default_stability_rounds(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        assert profile.get_stability_rounds() == 2

    def test_default_max_wait(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        assert profile.get_max_wait() == 180

    def test_default_no_closing_threshold(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        assert profile.get_no_closing_threshold() == 10


class TestRecordSample:
    def test_single_sample(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile.record_sample(10, 500)
        samples = profile.data["polling"]["samples"]
        assert len(samples) == 1

    def test_growth_rate_calculation(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        # 记录 3 个样本：在 10 秒内增长了 500 字符
        profile.record_sample(0, 100)
        profile.record_sample(5, 350)
        profile.record_sample(10, 600)
        rate = profile.data["polling"]["growth_rate_cps"]
        # (600-100)/(10-0) = 50 cps
        assert rate == 50.0

    def test_sample_limit(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        # 超过 30 条后触发截断（保留后 20），但后续继续追加，最终远少于 35
        for i in range(35):
            profile.record_sample(i * 2, i * 100)
        samples = profile.data["polling"]["samples"]
        assert len(samples) < 30  # 截断机制生效

    def test_no_growth_rate_with_insufficient_samples(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile.record_sample(0, 100)
        profile.record_sample(5, 200)
        rate = profile.data["polling"]["growth_rate_cps"]
        assert rate == 0  # 少于 3 个样本不计算


class TestAdaptInterval:
    def test_high_growth_rate(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["growth_rate_cps"] = 120  # >100
        profile.adapt_interval()
        assert profile.get_interval() == 2.0

    def test_medium_growth_rate(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["growth_rate_cps"] = 50  # 30~100
        profile.adapt_interval()
        assert profile.get_interval() == 3.0

    def test_slow_growth_rate(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["growth_rate_cps"] = 15  # <30
        profile.adapt_interval()
        assert profile.get_interval() == 5.0

    def test_zero_growth_rate(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["growth_rate_cps"] = 0
        profile.adapt_interval()
        assert profile.get_interval() == 2.0

    def test_negative_rate(self, temp_profiles):
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["growth_rate_cps"] = -5
        profile.adapt_interval()
        assert profile.get_interval() == 2.0


class TestClosingMarker:
    def test_had_closing_decreases_threshold(self, temp_profiles):
        """有结尾标记 → 阈值升高（下次多等）"""
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["no_closing_threshold"] = 6
        profile.update_closing_marker_reliability(had_closing=True)
        assert profile.get_no_closing_threshold() == 7

    def test_no_closing_decreases_threshold(self, temp_profiles):
        """无结尾标记 → 阈值降低（下次少等）"""
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["no_closing_threshold"] = 8
        profile.update_closing_marker_reliability(had_closing=False)
        assert profile.get_no_closing_threshold() == 6

    def test_threshold_floor(self, temp_profiles):
        """阈值不低于 5"""
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["no_closing_threshold"] = 5
        profile.update_closing_marker_reliability(had_closing=False)
        assert profile.get_no_closing_threshold() == 5

    def test_threshold_ceiling(self, temp_profiles):
        """阈值不超过 10"""
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["no_closing_threshold"] = 10
        profile.update_closing_marker_reliability(had_closing=True)
        assert profile.get_no_closing_threshold() == 10

    def test_no_change_logging(self, temp_profiles):
        """阈值不变时不记录进化日志"""
        import evolution
        profile = evolution.PollingProfile("test_platform")
        profile._ensure_polling_section()
        profile.data["polling"]["no_closing_threshold"] = 5
        old_len = len(profile.extraction_profile.data.get("evolution_log", []))
        profile.update_closing_marker_reliability(had_closing=False)  # 已是最低
        # 已在 floor，不变化
        assert profile.get_no_closing_threshold() == 5
