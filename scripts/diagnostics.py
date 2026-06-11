# -*- coding: utf-8 -*-
"""Agent 流程错误诊断模块 —— 出错时自动运行对应测试，定位根因。

用法：
    from diagnostics import diagnose
    result = diagnose("send_failed", context={"url": "...", "platform": "deepseek"})
    print(result["diagnosis"])   # 人类可读的诊断结果
    print(result["fix"])         # 建议修复方案
"""

import os, sys, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from runtime_paths import resolve_config_path


def _check_config(_ctx=None):
    """检查 config.json 是否存在且格式正确。"""
    config_path = resolve_config_path()
    if not os.path.exists(config_path):
        return False, "config.json 不存在", "运行 setup.py 初始化配置"
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"config.json 格式错误: {e}", "修复 JSON 格式或重新运行 setup.py"

    issues = []
    if not cfg.get("local_env", {}).get("initialized"):
        issues.append("local_env.initialized=false，环境未初始化")
    if not cfg.get("current_project"):
        issues.append("current_project 为空，未设置项目名")

    if issues:
        return False, "; ".join(issues), "运行 python setup.py 完成初始化，然后设 current_project"

    return True, "配置正常", None


def _check_cdp(_ctx=None):
    """检查 CDP 端口是否可用。"""
    from common import find_cdp_port, _scan_port, DEFAULT_CDP_PORT
    config = _safe_load_config()
    preferred = config.get("cdp_port", DEFAULT_CDP_PORT) if config else DEFAULT_CDP_PORT
    port = find_cdp_port(preferred=preferred)
    if port:
        return True, f"CDP 可用 (端口 {port})", None
    # 逐个扫
    available = []
    for p in range(9222, 9227):
        if _scan_port(p):
            available.append(str(p))
    if available:
        return False, f"CDP 端口 {preferred} 不可用，但 {','.join(available)} 可用", \
               f"修改 config.json 的 cdp_port 为可用端口，或执行 msedge --remote-debugging-port={preferred}"
    return False, "所有 CDP 端口 (9222-9226) 均不可用", \
           "执行 msedge --remote-debugging-port=9223 打开浏览器调试端口"


def _check_session_url(platform=None):
    """检查会话 URL 是否配置正确。"""
    from common import get_session_url, is_valid_session_url
    config = _safe_load_config()
    project = config.get("current_project", "") if config else ""
    url = get_session_url(project=project, platform=platform)
    if not url:
        return False, f"无法获取 {platform} 的会话 URL", "在 config.json 的 sessions.{project}.{platform} 中填入聊天链接"
    if not is_valid_session_url(url, platform):
        return False, f"{platform} 会话 URL 是首页而非聊天链接: {url[:80]}", \
               f"在 {platform} 中创建一个新对话，把链接填入 config.json"
    return True, f"{platform} 会话 URL 有效", None


def _check_platform_script(platform):
    """检查平台脚本是否可加载且函数签名完整。"""
    import importlib.util
    script_path = os.path.join(SCRIPT_DIR, "platforms", f"{platform}.py")
    if not os.path.exists(script_path):
        return False, f"平台脚本不存在: {platform}.py", "运行首次 send 来自动生成，或手动创建脚本"

    try:
        spec = importlib.util.spec_from_file_location(f"diag_{platform}", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return False, f"平台脚本加载失败: {e}", "检查脚本语法或删除后重新生成"

    missing = []
    for fn in ["fill_prompt", "submit", "dismiss_blockers"]:
        if not hasattr(mod, fn):
            missing.append(fn)
    if missing:
        return False, f"平台脚本缺少函数: {', '.join(missing)}", "删除 scripts/platforms/{platform}.py 后重新 send 生成"

    return True, f"{platform} 平台脚本就绪", None


def _check_api_config(_ctx=None):
    """检查 LLM API 配置（DeepSeek API key）。"""
    config = _safe_load_config()
    if not config:
        return False, "无法读取配置", "检查 config.json 是否存在"
    key = config.get("deepseek_key", "")
    if not key:
        return False, "deepseek_key 未配置", "在 config.json 中填入 DeepSeek API key"
    if key.startswith("sk-") and len(key) > 20:
        return True, "API key 已配置", None
    return False, "deepseek_key 格式可疑", "检查 key 是否为有效的 DeepSeek API key (sk-xxx)"


def _safe_load_config():
    try:
        from common import load_config
        return load_config()
    except Exception:
        return None


# ============================================================
# 诊断主函数
# ============================================================

ERROR_CHECKS = {
    "send_failed": [
        ("CDP 连接", _check_cdp),
        ("会话 URL", lambda ctx: _check_session_url(ctx.get("platform"))),
        ("平台脚本", lambda ctx: _check_platform_script(ctx.get("platform", "deepseek"))),
        ("配置文件", _check_config),
    ],
    "extract_failed": [
        ("配置文件", _check_config),
        ("CDP 连接", _check_cdp),
    ],
    "llm_call_failed": [
        ("API 配置", _check_api_config),
        ("配置文件", _check_config),
    ],
    "cdp_connection_failed": [
        ("CDP 连接", _check_cdp),
        ("配置文件", _check_config),
    ],
    "config_error": [
        ("配置文件", _check_config),
        ("API 配置", _check_api_config),
    ],
    "unknown_error": [
        ("配置文件", _check_config),
        ("CDP 连接", _check_cdp),
        ("API 配置", _check_api_config),
    ],
}


def diagnose(error_type, context=None):
    """根据错误类型运行对应诊断检查。

    error_type: "send_failed" | "extract_failed" | "llm_call_failed" |
                "cdp_connection_failed" | "config_error" | "unknown_error"
    context: dict, 可包含 platform, url, project 等上下文
    """
    ctx = context or {}
    checks = ERROR_CHECKS.get(error_type, ERROR_CHECKS["unknown_error"])

    results = []
    passed = 0
    failed = 0

    for name, check_fn in checks:
        try:
            ok, msg, fix = check_fn(ctx)
        except Exception as e:
            ok, msg, fix = False, f"诊断异常: {e}", None

        results.append({
            "check": name,
            "passed": ok,
            "message": msg,
            "fix": fix,
        })
        if ok:
            passed += 1
        else:
            failed += 1

    # 生成诊断摘要
    fail_items = [r for r in results if not r["passed"]]
    if not fail_items:
        diagnosis = "所有基本检查通过，问题可能在网络或平台服务端。建议：重试 1-2 次，检查 AI 平台是否正常服务。"
    else:
        lines = [f"{len(fail_items)} 项检查未通过："]
        for r in fail_items:
            lines.append(f"  [{r['check']}] {r['message']}")
            if r["fix"]:
                lines.append(f"    → 修复: {r['fix']}")
        diagnosis = "\n".join(lines)

    return {
        "error_type": error_type,
        "passed": passed,
        "failed": failed,
        "total": len(results),
        "results": results,
        "diagnosis": diagnosis,
    }


def format_diagnosis(result):
    """格式化输出诊断结果。"""
    lines = [
        f"=== 错误诊断: {result['error_type']} ===",
        f"通过 {result['passed']}/{result['total']} 项检查",
        "",
    ]
    for r in result["results"]:
        icon = "[OK]" if r["passed"] else "[FAIL]"
        lines.append(f"{icon} {r['check']}: {r['message']}")
        if not r["passed"] and r["fix"]:
            lines.append(f"    修复: {r['fix']}")
    lines.append("")
    lines.append(f"诊断结论: {result['diagnosis']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')

    # 快速自检
    for etype in ["send_failed", "config_error", "unknown_error"]:
        r = diagnose(etype)
        print(format_diagnosis(r))
        print()
