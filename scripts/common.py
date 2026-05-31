# -*- coding: utf-8 -*-
"""common utilities —— 读取配置、CDP连接、平台检测（只读不写）"""
import json
import os
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

CURRENT_VERSION = 6


def load_config():
    """读取 config.json，兼容 v4/v5/v6 所有版本"""
    if not os.path.exists(CONFIG_PATH):
        return _default_config()

    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        config = json.load(f)

    # v4/v5 兼容：补全缺失字段
    config.setdefault("version", 0)
    config.setdefault("cdp_port", 9222)
    config.setdefault("project_name", "web_ai_search")
    config.setdefault("deepseek_api", "http://localhost:3688/v1")

    if "local_env" not in config:
        config["local_env"] = {"initialized": False}

    # v4/v5 兼容：补全 v6 新增的会话管理字段
    config.setdefault("session_mode", "fixed")
    config.setdefault("sessions", {})
    config.setdefault("current_project", "")

    return config


def _default_config():
    return {
        "version": CURRENT_VERSION,
        "cdp_port": 9222,
        "project_name": "web_ai_search",
        "deepseek_api": "http://localhost:3688/v1",
        "local_env": {"initialized": False},
        "session_mode": "fixed",
        "sessions": {},
        "current_project": "",
    }


def get_python_venv_path():
    """读取 config 中的 venv Python 路径，兼容新旧 config 格式"""
    config = load_config()
    local = config.get("local_env", {})
    venv = local.get("python_venv", None)
    if venv:
        return venv
    # fallback: 旧格式可能只有 local_env.python.path（.agents/.claude 配置）
    python_path = local.get("python", {}).get("path", None)
    if python_path and "venv" in python_path.lower():
        return python_path
    return python_path


def is_env_initialized():
    """环境是否已通过 setup.py 初始化"""
    config = load_config()
    return config.get("local_env", {}).get("initialized", False)


def needs_version_upgrade():
    """检测 config 版本是否低于当前代码版本"""
    config = load_config()
    return config.get("version", 0) < CURRENT_VERSION


def get_project_name():
    return load_config().get("project_name", "web_ai_search")


def safe_page_text(page):
    """安全提取页面 innerText（两种 fallback）"""
    try:
        return page.inner_text("body")
    except Exception:
        pass
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""


def detect_platform(url):
    """从 URL 识别 AI 对话平台"""
    url_lower = url.lower()
    if "chatgpt.com" in url_lower:
        return "chatgpt"
    if "deepseek.com" in url_lower:
        return "deepseek"
    if "gemini.google.com" in url_lower:
        return "gemini"
    if "claude.ai" in url_lower:
        return "claude"
    return "unknown"


def ensure_browser(p, cdp_port):
    """通过 CDP 连接已有浏览器实例"""
    cdp_url = f"http://127.0.0.1:{cdp_port}"
    print(f"[*] 连接浏览器 (CDP: {cdp_port})...")
    browser = p.chromium.connect_over_cdp(cdp_url, timeout=5000)
    contexts = browser.contexts
    if not contexts or not contexts[0].pages:
        raise Exception("无可用的浏览器标签页")
    page = contexts[0].pages[-1]
    print(f"[*] 已连接: {len(contexts[0].pages)} 个标签页")
    return browser, page


def get_session_url(project=None, default_url=None):
    """根据 session_mode 和项目名返回搜索 URL。
    fixed 模式：从 sessions 中按项目名查找，未找到返回 default_url
    auto 模式：直接返回传入的 url
    """
    config = load_config()
    mode = config.get("session_mode", "fixed")
    if mode == "fixed":
        project = project or config.get("current_project", "")
        sessions = config.get("sessions", {})
        if project and project in sessions:
            return sessions[project]
        return default_url or "https://chat.deepseek.com/"
    return default_url
