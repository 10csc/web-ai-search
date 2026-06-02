# -*- coding: utf-8 -*-
"""common utilities —— 配置读取、CDP连接、端口管理、会话路由"""
import json
import os
import time

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")

CURRENT_VERSION = 6
DEFAULT_CDP_PORT = 9222
CDP_SCAN_RANGE = (9222, 9225)
DEFAULT_URL = "https://chat.deepseek.com/"


# ====== 配置读取 ======

def load_config():
    """读取 config.json，兼容 v4/v5/v6 所有版本"""
    if not os.path.exists(CONFIG_PATH):
        return _default_config()
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        config = json.load(f)
    config.setdefault("version", 0)
    config.setdefault("cdp_port", DEFAULT_CDP_PORT)
    config.setdefault("project_name", "web_ai_search")
    config.setdefault("deepseek_api", "http://localhost:3688/v1")
    if "local_env" not in config:
        config["local_env"] = {"initialized": False}
    config.setdefault("session_mode", "fixed")
    config.setdefault("sessions", {})
    config.setdefault("current_project", "")
    return config


def _default_config():
    return {
        "version": CURRENT_VERSION, "cdp_port": DEFAULT_CDP_PORT,
        "project_name": "web_ai_search",
        "deepseek_api": "http://localhost:3688/v1",
        "local_env": {"initialized": False},
        "session_mode": "fixed", "sessions": {}, "current_project": "",
    }


def get_python_venv_path():
    """读取 venv Python 路径，兼容新旧 config 格式"""
    config = load_config()
    local = config.get("local_env", {})
    venv = local.get("python_venv", None)
    if venv:
        return venv
    python_path = local.get("python", {}).get("path", None)
    if python_path and "venv" in python_path.lower():
        return python_path
    return python_path


def is_env_initialized():
    config = load_config()
    return config.get("local_env", {}).get("initialized", False)


def needs_version_upgrade():
    config = load_config()
    return config.get("version", 0) < CURRENT_VERSION


def get_project_name():
    return load_config().get("project_name", "web_ai_search")


def _auto_project():
    """从工作目录自动推断项目名"""
    cwd = os.getcwd()
    return os.path.basename(cwd.rstrip(os.sep)) or "default"


def get_or_create_project():
    """获取当前项目名。若 config.json 中 current_project 为空，自动从工作目录推断并持久化。"""
    config = load_config()
    project = config.get("current_project", "")
    if project:
        return project
    # 首次使用：自动推断并保存
    project = _auto_project()
    config_path = os.path.join(SKILL_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        cfg["current_project"] = project
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return project


# ====== CDP 端口管理 ======

def _scan_port(port):
    """扫描单个端口是否可用 CDP，返回 webSocketDebuggerUrl 或 None"""
    import urllib.request
    try:
        url = "http://127.0.0.1:{}/json/version".format(port)
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return data.get("webSocketDebuggerUrl", "")
    except Exception:
        return None


def find_cdp_port():
    """快速扫描 CDP 端口。先试默认端口 9222，再扫 9223-9225，返回可用端口号或 None"""
    ws = _scan_port(DEFAULT_CDP_PORT)
    if ws:
        return DEFAULT_CDP_PORT
    for port in range(CDP_SCAN_RANGE[0] + 1, CDP_SCAN_RANGE[1] + 1):
        ws = _scan_port(port)
        if ws:
            return port
    return None


def _launch_browser(port=None):
    """启动浏览器并返回 CDP 端口"""
    config = load_config()
    browser_info = config.get("local_env", {}).get("browser", {})
    browser_path = browser_info.get("path", "")
    if not browser_path or not os.path.exists(browser_path):
        return None
    import subprocess
    use_port = port or DEFAULT_CDP_PORT
    print("[*] 启动浏览器 (CDP: {})...".format(use_port))
    subprocess.Popen(
        [browser_path, "--remote-debugging-port={}".format(use_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    found = find_cdp_port()
    if found:
        return found
    return use_port
def _is_edge_running():
    """检查 Edge 进程是否在运行（不限 CDP 模式）"""
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/fi", "IMAGENAME eq msedge.exe", "/fo", "csv"],
                          capture_output=True, text=True, timeout=5)
        return r.stdout.count("msedge.exe") > 1
    except Exception:
        return False


def _kill_edge():
    """强制关闭所有 Edge 进程"""
    import subprocess
    try:
        subprocess.run(["taskkill", "/f", "/im", "msedge.exe"],
                      capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass


def ensure_browser(p, cdp_port=None):
    """连接 CDP 浏览器。
    流程：扫描端口 -> Edge无CDP则杀进程重启 -> 重试3次 -> 报错。
    信任本地单用户环境，自动处理 Edge 崩溃和冲突。
    返回 (browser, page)。
    """
    config = load_config()
    browser_info = config.get("local_env", {}).get("browser", {})
    browser_name = os.path.basename(browser_info.get("path", "浏览器"))

    # 1. 扫描已有 CDP 端口
    port = find_cdp_port()

    # 2. 无 CDP 但 Edge 在运行 -> 可能开了普通 Edge 锁住了 CDP 自启
    if not port and _is_edge_running():
        print("[*] Edge 在运行但无 CDP，正在重启...")
        _kill_edge()
        time.sleep(2)

    # 3. 尝试启动 + 重试（最多3次，每次等3秒）
    if not port:
        for attempt in range(3):
            print("[*] 启动浏览器 CDP 模式 (尝试 {}/3)...".format(attempt + 1))
            port = _launch_browser(cdp_port or DEFAULT_CDP_PORT)
            if port:
                break
            time.sleep(3)
            port = find_cdp_port()
            if port:
                break

    # 4. 仍未找到 -> 报错
    if not port:
        raise RuntimeError(
            "未检测到 CDP 浏览器，自动启动也失败。\n"
            "请手动执行：{} --remote-debugging-port=9222\n"
            "然后重试。".format(browser_name)
        )

    cdp_url = "http://127.0.0.1:{}".format(port)
    print("[*] 连接浏览器 (CDP: {})...".format(port))
    try:
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=5000)
    except Exception as e:
        raise RuntimeError(
            "CDP 连接失败 (端口 {})：{}\n"
            "请确认浏览器已启动并开启远程调试：\n"
            "  {} --remote-debugging-port={}".format(port, e, browser_name, port)
        )
    contexts = browser.contexts
    if not contexts or not contexts[0].pages:
        raise RuntimeError("无可用的浏览器标签页，请打开至少一个标签页后重试")
    return browser, contexts[0].pages[-1]
def ensure_page(browser, url, new_tab=False):
    """在当前 context 中查找或创建目标 URL 的页面。
    new_tab=True 时始终创建新标签页，不干扰用户已有标签。
    所有操作均后台执行，不调用 bring_to_front()。
    """
    pages = browser.contexts[0].pages
    if not new_tab:
        for page in pages:
            if url in page.url:
                return page
    page = browser.contexts[0].new_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)
    return page


# ====== 页面文本 ======

def safe_page_text(page):
    """安全提取页面文本（textContent 优先，不受虚拟滚动影响）"""
    try:
        return page.evaluate("document.body.textContent || ''")
    except Exception:
        pass
    try:
        return page.inner_text("body")
    except Exception:
        pass
    try:
        return page.evaluate("document.body ? document.body.innerText : ''")
    except Exception:
        return ""


# ====== 平台检测 ======

def detect_platform(url):
    url_lower = url.lower()
    if "chatgpt.com" in url_lower: return "chatgpt"
    if "deepseek.com" in url_lower: return "deepseek"
    if "gemini.google.com" in url_lower: return "gemini"
    if "claude.ai" in url_lower: return "claude"
    return "unknown"


# ====== 会话路由 ======

def get_session_url(project=None, default_url=None):
    """fixed 模式按 project+platform 两级查找会话链接。
    sessions 结构: {"项目名": {"deepseek": "https://...", "chatgpt": "https://..."}}
    """
    config = load_config()
    mode = config.get("session_mode", "fixed")
    if mode != "fixed":
        return default_url or DEFAULT_URL

    project = project or config.get("current_project", "") or _auto_project()
    sessions = config.get("sessions", {})
    platform = detect_platform(default_url or DEFAULT_URL)

    proj_sessions = sessions.get(project, {})
    if isinstance(proj_sessions, dict) and platform in proj_sessions:
        return proj_sessions[platform]

    # 兼容旧格式：sessions[project] 直接是 URL 字符串
    if isinstance(proj_sessions, str) and proj_sessions:
        return proj_sessions

    return default_url or DEFAULT_URL


def _save_session(project, url):
    """保存平台链接到 config.json（两级映射）"""
    config_path = os.path.join(SKILL_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8-sig") as f:
        config = json.load(f)
    platform = detect_platform(url)
    sessions = config.setdefault("sessions", {})
    proj_sessions = sessions.setdefault(project, {})
    if isinstance(proj_sessions, str):
        old_url = proj_sessions
        old_platform = detect_platform(old_url)
        proj_sessions = {old_platform: old_url}
        sessions[project] = proj_sessions
    proj_sessions[platform] = url
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
