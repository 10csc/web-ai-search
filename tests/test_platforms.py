# -*- coding: utf-8 -*-
"""平台契约测试 —— 验证每个平台脚本都有必需的函数签名。"""

import os, sys
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import importlib.util
import pytest

# 所有已存在的平台
PLATFORMS = ["deepseek", "kimi", "chatgpt", "gemini"]

# 必需函数 + 参数个数
REQUIRED_FUNCTIONS = {
    "fill_prompt":    2,   # (page, prompt_text)
    "dismiss_blockers": 1, # (page)
    "submit":         1,   # (page)
}

REQUIRED_CONSTANTS = [
    "CAPABILITIES",  # list[str], 如 ["text_input", "file_upload"]
    "FILL_SEL",      # str, 输入框选择器
    "EXTRACT_SEL",   # str, AI 回复选择器
]

OPTIONAL_FUNCTIONS = {
    "upload_file":    2,   # (page, file_path)
    "wait_for_response": 2, # (page, timeout)
}


def _load_platform(platform_name):
    """动态加载平台模块。"""
    path = os.path.join(SCRIPT_DIR, "platforms", f"{platform_name}.py")
    if not os.path.exists(path):
        pytest.skip(f"平台脚本不存在: {platform_name}")
    spec = importlib.util.spec_from_file_location(
        f"test_{platform_name}", path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPlatformConstants:
    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_capabilities_exists(self, platform):
        mod = _load_platform(platform)
        for const in REQUIRED_CONSTANTS:
            assert hasattr(mod, const), f"[{platform}] 缺少常量: {const}"

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_capabilities_is_list(self, platform):
        mod = _load_platform(platform)
        caps = getattr(mod, "CAPABILITIES", [])
        assert isinstance(caps, list), f"[{platform}] CAPABILITIES 应为 list"
        assert len(caps) >= 1, f"[{platform}] CAPABILITIES 不能为空"

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_extract_sel_is_str(self, platform):
        mod = _load_platform(platform)
        sel = getattr(mod, "EXTRACT_SEL", "")
        assert isinstance(sel, str) and len(sel) > 0, \
            f"[{platform}] EXTRACT_SEL 应为非空字符串"


class TestPlatformFunctionSignatures:
    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_required_functions_exist(self, platform):
        mod = _load_platform(platform)
        for func_name, arg_count in REQUIRED_FUNCTIONS.items():
            assert hasattr(mod, func_name), \
                f"[{platform}] 缺少必需函数: {func_name}"
            fn = getattr(mod, func_name)
            assert callable(fn), \
                f"[{platform}] {func_name} 不是可调用对象"
            # 检查参数个数（忽略 self 如果存在）
            actual_args = fn.__code__.co_argcount
            assert actual_args >= arg_count, \
                f"[{platform}] {func_name} 参数不足: 需要≥{arg_count}, 实际{actual_args}"

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_optional_functions_if_exist(self, platform):
        mod = _load_platform(platform)
        for func_name, arg_count in OPTIONAL_FUNCTIONS.items():
            if hasattr(mod, func_name):
                fn = getattr(mod, func_name)
                assert callable(fn)
                actual_args = fn.__code__.co_argcount
                assert actual_args >= arg_count, \
                    f"[{platform}] {func_name} 参数不足: 需要≥{arg_count}, 实际{actual_args}"

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_dismiss_blockers_exists(self, platform):
        mod = _load_platform(platform)
        assert hasattr(mod, "dismiss_blockers"), \
            f"[{platform}] 缺少 dismiss_blockers"

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_submit_is_callable(self, platform):
        mod = _load_platform(platform)
        fn = getattr(mod, "submit")
        assert fn.__code__.co_argcount >= 1


class TestPlatformModuleStructure:
    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_no_missing_imports(self, platform):
        """确保平台脚本导入不会因缺少依赖而崩溃。"""
        mod = _load_platform(platform)
        # 成功加载即通过
        assert mod is not None

    @pytest.mark.parametrize("platform", PLATFORMS)
    def test_fill_prompt_accepts_page(self, platform):
        """fill_prompt 的第一个参数应该是 page 对象。"""
        mod = _load_platform(platform)
        fn = mod.fill_prompt
        # 参数名检查（约定）
        arg_names = fn.__code__.co_varnames[:fn.__code__.co_argcount]
        assert arg_names[0] in ("page", "self"), \
            f"[{platform}] fill_prompt 第1个参数应为 page，实为 {arg_names[0]}"


class TestPlatformCoverage:
    def test_deepseek_covers_all_required(self):
        mod = _load_platform("deepseek")
        for fn in REQUIRED_FUNCTIONS:
            assert hasattr(mod, fn)

    def test_kimi_has_upload(self):
        """Kimi 整合场景需要文件上传。"""
        mod = _load_platform("kimi")
        assert hasattr(mod, "upload_file"), \
            "Kimi 作为整合平台必须支持 upload_file"
