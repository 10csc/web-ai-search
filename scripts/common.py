# -*- coding: utf-8 -*-
"""common utilities —— 配置读取、CDP连接、端口管理、会话路由"""
import json
import os
import time
from runtime_paths import (
    CONFIG_PATH as RUNTIME_CONFIG_PATH,
    DATA_DIR,
    SKILL_DIR,
    resolve_config_path,
    ensure_runtime_dirs,
)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = resolve_config_path()

CURRENT_VERSION = 6
DEFAULT_CDP_PORT = 9223
CDP_SCAN_RANGE = (9223, 9226)
DEFAULT_URL = "https://chat.deepseek.com/"


# ====== 配置读取 ======

def load_config():
    """读取 config.json，兼容 v4/v5/v6 所有版本"""
    config_path = CONFIG_PATH
    if not os.path.exists(config_path):
        return _default_config()
    with open(config_path, "r", encoding="utf-8-sig") as f:
        config = json.load(f)
    config.setdefault("version", 0)
    config.setdefault("cdp_port", DEFAULT_CDP_PORT)
    config.setdefault("project_name", "web_ai_search")
    config.setdefault("deepseek_api", "https://api.deepseek.com/v1")
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
        "deepseek_api": "https://api.deepseek.com/v1",
        "local_env": {"initialized": False},
        "session_mode": "fixed", "sessions": {}, "current_project": "",
    }


def save_config(config):
    """Persist config to the runtime-owned config path."""
    ensure_runtime_dirs()
    with open(RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


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
    cfg = load_config()
    cfg["current_project"] = project
    save_config(cfg)
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


def find_cdp_port(preferred=None):
    """扫描 CDP 端口。优先扫用户配置端口(如果有)，再扫默认端口和范围。返回可用端口号或 None"""
    scan_order = []
    if preferred and preferred not in scan_order:
        scan_order.append(preferred)
    if DEFAULT_CDP_PORT not in scan_order:
        scan_order.append(DEFAULT_CDP_PORT)
    for port in range(CDP_SCAN_RANGE[0] + 1, CDP_SCAN_RANGE[1] + 1):
        if port not in scan_order:
            scan_order.append(port)
    for port in scan_order:
        ws = _scan_port(port)
        if ws:
            return port
    return None


BROWSER_PATHS = [
    # Edge 优先
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    # Chrome fallback
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
]


def _resolve_browser_path():
    """获取 Edge 路径：优先 config，fallback 扫描常见路径。"""
    config = load_config()
    browser_info = config.get("local_env", {}).get("browser", {})
    browser_path = browser_info.get("path", "")
    if browser_path and os.path.exists(browser_path):
        return browser_path
    for p in BROWSER_PATHS:
        if os.path.exists(p):
            return p
    return None


def _kill_browser():
    """杀掉所有 Edge 进程，释放 Profile 文件锁。

    这是显式维护动作，正常搜索流程不应调用。
    """
    import subprocess
    for name in ("msedge.exe", "msedgewebview2.exe"):
        try:
            subprocess.run(
                ["taskkill", "/f", "/im", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass
    time.sleep(1.5)


def _launch_browser(port=None, kill_existing=False):
    """启动浏览器并返回 CDP 端口。

    默认不杀已有浏览器。只有调用方明确传入 kill_existing=True 时才释放 Profile 锁。
    """
    browser_path = _resolve_browser_path()
    if not browser_path:
        return None
    import subprocess
    use_port = port or DEFAULT_CDP_PORT
    if kill_existing:
        _kill_browser()
    print("[*] 启动浏览器 (CDP: {})...".format(use_port))
    subprocess.Popen(
        [browser_path, "--remote-debugging-port={}".format(use_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(5):
        time.sleep(3)
        found = find_cdp_port()
        if found:
            return found
    return None


def ensure_browser(p, cdp_port=None, launch_policy="manual", kill_existing=False):
    """连接 CDP 浏览器。

    launch_policy:
      - "manual": 默认。只连接已有 CDP，不启动/不杀浏览器。
      - "auto": 未检测到 CDP 时尝试启动浏览器。
    返回 (browser, page)。
    """
    port = find_cdp_port(preferred=cdp_port)
    if not port:
        if launch_policy != "auto":
            name = os.path.basename(_resolve_browser_path() or "msedge.exe")
            raise RuntimeError(
                "未检测到 CDP 浏览器。请手动执行：\n"
                "  {0} --remote-debugging-port={1}".format(
                    name, cdp_port or DEFAULT_CDP_PORT)
            )
        print("[*] 未检测到 CDP 浏览器，按显式策略启动...")
        port = _launch_browser(cdp_port or DEFAULT_CDP_PORT, kill_existing=kill_existing)
        if not port:
            name = os.path.basename(_resolve_browser_path() or "msedge.exe")
            raise RuntimeError(
                "无法自动启动浏览器。请手动执行：\n"
                "  {0} --remote-debugging-port={1}".format(
                    name, cdp_port or DEFAULT_CDP_PORT)
            )
    cdp_url = "http://127.0.0.1:{0}".format(port)
    print("[*] 连接浏览器 (CDP: {0})...".format(port))
    try:
        browser = p.chromium.connect_over_cdp(cdp_url, timeout=5000)
    except Exception as e:
        raise RuntimeError(
            "CDP 连接失败 (端口 {0})：{1}".format(port, e)
        )
    contexts = browser.contexts
    if not contexts or not contexts[0].pages:
        raise RuntimeError("无可用的浏览器标签页，请打开至少一个标签页后重试")
    return browser, contexts[0].pages[-1]


def ensure_page(browser, url, new_tab=False):
    """在当前 context 中查找或创建目标 URL 的页面。
    new_tab=True 时始终创建新标签页，不干扰用户已有标签。
    匹配策略：优先 URL 精确匹配 → 平台类型匹配（仅限已注册AI平台）→ 新建。
    """
    config = load_config()
    target_platform = detect_platform(url)
    pages = browser.contexts[0].pages
    if not new_tab:
        # 第一轮：URL 精确/前缀匹配
        for page in pages:
            if page.url.startswith(url) or page.url == url:
                return page
        # 第二轮：仅限已注册 AI 平台页面匹配（避免误匹配用户其他标签页）
        if target_platform != "unknown":
            registered_urls = config.get("platform_urls", {})
            for page in pages:
                page_platform = detect_platform(page.url)
                if page_platform == target_platform and page_platform in registered_urls:
                    # 定位到指定 URL（刷新会话）
                    try:
                        page.goto(url, timeout=15000, wait_until="domcontentloaded")
                        time.sleep(2)
                        return page
                    except Exception:
                        continue
    page = browser.contexts[0].new_page()
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)
    return page
    return page


# ====== 提交验证 ======

def submit_and_verify(plat, page, prompt):
    """统一的填prompt+提交+验证。返回 (remaining, success)。"""
    plat.fill_prompt(page, prompt)
    plat.dismiss_blockers(page)
    plat.submit(page)
    time.sleep(1)
    if not getattr(plat, "VERIFY_BY_INPUT_CLEAR", True):
        return 0, True
    try:
        remaining = page.evaluate(
            "() => {let e=document.querySelector('[contenteditable=true],textarea');"
            "return e?(e.value||e.innerText||'').length:-1}")
        return remaining, (remaining is not None and remaining <= 2)
    except Exception:
        return -1, False


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
    """从 config.json 的 platform_urls 提取域名做匹配。加新平台只需改配置。"""
    from urllib.parse import urlparse
    url_lower = url.lower()
    config = load_config()
    for name, homepage in config.get("platform_urls", {}).items():
        if not isinstance(homepage, str) or name.startswith("_"):
            continue
        try:
            domain = urlparse(homepage).netloc.replace("www.", "").lower()
            if domain and domain in url_lower:
                return name
        except Exception:
            pass
    return "unknown"


# ====== 会话路由 ======

def is_valid_session_url(url, platform=None):
    """检查 URL 是否是真实聊天链接（非首页）。"""
    if not url:
        return False
    config = load_config()
    patterns = config.get("chat_path_patterns", {}).get(platform, []) if platform else []
    if patterns:
        return any(p in url for p in patterns)
    # 通用判断：非首页
    from urllib.parse import urlparse
    path = urlparse(url).path.strip("/")
    return len(path) > 0


def get_session_url(project=None, platform=None):
    """fixed 模式按 project+platform 两级查找会话链接。

    优先级：sessions.{project}.{platform} > platform_urls.{platform} > 拼凑
    """
    config = load_config()
    platform_urls = config.get("platform_urls", {})
    fallback = platform_urls.get(platform, f"https://chat.{platform}.com/") if platform else DEFAULT_URL
    mode = config.get("session_mode", "fixed")
    if mode != "fixed":
        return fallback

    project = project or config.get("current_project", "") or _auto_project()
    sessions = config.get("sessions", {})

    proj_sessions = sessions.get(project, {})
    if isinstance(proj_sessions, dict) and platform and platform in proj_sessions:
        return proj_sessions[platform]

    # 兼容旧格式
    if isinstance(proj_sessions, str) and proj_sessions:
        return proj_sessions

    return fallback


def _save_session(project, url):
    """保存平台链接到 config.json（两级映射）。
    失败时打印警告但不中断主流程。
    """
    try:
        config = load_config()
    except Exception as e:
        print(f"[警告] 读取 config.json 失败: {e}")
        return
    platform = detect_platform(url)
    sessions = config.setdefault("sessions", {})
    proj_sessions = sessions.setdefault(project, {})
    if isinstance(proj_sessions, str):
        old_url = proj_sessions
        old_platform = detect_platform(old_url)
        proj_sessions = {old_platform: old_url}
        sessions[project] = proj_sessions
    proj_sessions[platform] = url
    try:
        save_config(config)
    except Exception as e:
        print(f"[警告] 保存会话链接失败: {e}")


# ====== 结果持久化 ======

def save_result(content):
    """将搜索结果写入 data/latest_result.md。消除 6 处重复写入。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "latest_result.md"), "w", encoding="utf-8") as f:
        f.write(content)


# ====== 平台交互共享 ======

SEND_BUTTON_SELECTORS = [
    "button[aria-label=发送]",
    "button[aria-label=Send]",
    "[aria-label=Send message]",
    "button[data-testid=send-button]",
]


def dismiss_blockers_base(page):
    """通用弹窗/对话框消除：dialog.accept + Escape。各平台可在差异处覆盖。"""
    try:
        page.on("dialog", lambda d: d.accept())
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass
