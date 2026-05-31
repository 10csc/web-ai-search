# -*- coding: utf-8 -*-
"""web-ai-search 入口 —— send / extract / auto 三模式"""
import argparse, time, sys, os, json, importlib, importlib.util
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


from common import load_config, ensure_browser, detect_platform, safe_page_text, get_project_name
from generator import script_exists, generate_interaction_script, get_platform_script_path
from logger import log_entry


def _save_session(project, url):
    """将项目→链接写入 config.json 的 sessions"""
    config_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.json")
    with open(config_path, 'r', encoding='utf-8-sig') as f:
        c = json.load(f)
    c.setdefault('sessions', {})[project] = url
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def load_platform_module(platform):
    script_path = get_platform_script_path(platform)
    spec = importlib.util.spec_from_file_location(f"platform_{platform}", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_script_generated(platform, url):
    try: from playwright.sync_api import sync_playwright
    except ImportError: raise RuntimeError("未安装 playwright")
    config = load_config()
    with sync_playwright() as p:
        browser, page = ensure_browser(p, config.get("cdp_port", 9222))
        page.bring_to_front(); time.sleep(1)
        from common import get_session_url
        target_url = get_session_url(project=config.get("current_project",""), default_url=url)
        page.goto(target_url, timeout=30000, wait_until="domcontentloaded"); time.sleep(5)
        generate_interaction_script(page, platform, page.url)


# ====== send ======

def run_send(prompt, topic, url, force_regenerate=False):
    platform = detect_platform(url)
    print(f"[发送] 平台: {platform}")
    if force_regenerate or not script_exists(platform):
        print(f"[发送] 生成脚本..."); _ensure_script_generated(platform, url)
    plat = load_platform_module(platform)
    log_entry(get_project_name(), "input", f"TOPIC:{topic}")
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright"
    config = load_config()
    # 新项目无绑定链接时自动标记
    project = config.get("current_project", "")
    sessions = config.get("sessions", {})
    is_new = (config.get("session_mode", "fixed") == "fixed" and project and project not in sessions)

    with sync_playwright() as p:
        browser, page = ensure_browser(p, config.get("cdp_port", 9222))
        page.bring_to_front(); time.sleep(1)
        from common import get_session_url
        target_url = get_session_url(project=project, default_url=url)
        page.goto(target_url, timeout=30000, wait_until="domcontentloaded"); time.sleep(5)
        plat.fill_prompt(page, prompt)
        plat.dismiss_blockers(page)
        plat.submit(page)
        remaining = page.evaluate("() => {let e=document.querySelector('[contenteditable=true],textarea');return e?(e.value||e.innerText||'').length:-1}")

        # 新项目：发送成功后自动绑定对话链接
        if is_new and remaining is not None and remaining <= 2:
            current_url = page.url
            if current_url != target_url and "chat.deepseek.com" in current_url:
                _save_session(project, current_url)
                print(f"[发送] 已绑定: {project} -> {current_url}")

        if remaining is not None and remaining <= 2:
            print("[发送] 成功 (残留{0}字符)".format(remaining)); return "OK"
        else:
            print(f"[发送] 残留{remaining}字符,重试"); plat.submit(page); return "OK"


# ====== extract ======

def run_extract(prompt, topic, url):
    platform = detect_platform(url)
    print(f"[提取] 平台: {platform}")
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright"
    config = load_config()
    with sync_playwright() as p:
        browser, page = ensure_browser(p, config.get("cdp_port", 9222))
        page.bring_to_front(); time.sleep(1)
        raw = safe_page_text(page)
        if not raw: return "ERROR: 页面无内容"
        print(f"[提取] 页面: {len(raw)} 字符")
        from extractor import extract_content
        content = extract_content(raw, prompt, topic)
        if content:
            log_entry(get_project_name(), "output", content[:50000])
            data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "latest_result.md"), "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[提取] 成功 ({len(content)} 字符)")
            return content
        return "ERROR: 提取失败"


# ====== auto: send + detect + extract ======

def run_auto(prompt, topic, url, force_regenerate=False, max_wait=300):
    # step 1: send
    result = run_send(prompt, topic, url, force_regenerate)
    if not result or "ERROR" in str(result):
        return f"发送失败: {result}"
    print("[自动] 发送完成，内容检测中...")
    
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright"
    config = load_config()
    with sync_playwright() as p:
        browser, page = ensure_browser(p, config.get("cdp_port", 9222))
        page.bring_to_front()
        from extractor import extract_content, is_content_complete
        deadline = time.time() + max_wait
        last_len = 0; stable_count = 0; start_ts = time.time()
        while time.time() < deadline:
            time.sleep(2)
            raw = safe_page_text(page)
            if not raw: continue
            # 中间状态输出（标记数/页面大小），让用户知道在轮询
            marker_check = f"[搜索主题：{topic}]"
            marker_count = raw.count(marker_check)
            elapsed = int(time.time() - start_ts)
            print(f"[轮询] {elapsed}s | 页面={len(raw)}字符 | 标记={marker_count}")
            content = extract_content(raw, prompt, topic)
            if content and is_content_complete(content):
                if len(content) == last_len:
                    stable_count += 1
                    if stable_count >= 3:
                        elapsed = int(time.time() - start_ts)
                        print(f"[自动] 稳定 ({len(content)}字符, {elapsed}s)")
                        log_entry(get_project_name(), "output", content[:50000])
                        data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
                        os.makedirs(data_dir, exist_ok=True)
                        with open(os.path.join(data_dir, "latest_result.md"), "w", encoding="utf-8") as f:
                            f.write(content)
                        return content
                else:
                    stable_count = 0
                last_len = len(content)
                elapsed = int(time.time() - start_ts)
                print(f"[自动] 结构完整 ({len(content)}字符, {elapsed}s, 稳定{stable_count}/3)")
        # timeout fallback
        raw = safe_page_text(page)
        content = extract_content(raw, prompt, topic)
        if content and len(content) > 300:
            print(f"[自动] 超时兜底 ({len(content)}字符)")
            log_entry(get_project_name(), "output", content[:50000])
            return content
        return "ERROR: 超时"


# ====== CLI ======

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", "-m", required=True, choices=["send","extract","auto"])
    parser.add_argument("--prompt", "-p", default="")
    parser.add_argument("--prompt-file", "-P", default="")
    parser.add_argument("--topic", "-k", required=True)
    parser.add_argument("--url", "-u", required=True)
    parser.add_argument("--timeout", "-t", type=int, default=300)
    parser.add_argument("--regenerate", "-r", action="store_true")
    args = parser.parse_args()
    if args.prompt_file:
        with open(args.prompt_file, 'r', encoding='utf-8') as f:
            args.prompt = f.read()

    if args.mode == "send":
        result = run_send(args.prompt, args.topic, args.url, args.regenerate)
    elif args.mode == "extract":
        result = run_extract(args.prompt, args.topic, args.url)
    else:
        result = run_auto(args.prompt, args.topic, args.url, args.regenerate, args.timeout)

    print(f"\n===== {args.mode} =====")
    if isinstance(result, str) and len(result) > 500:
        print(result[:500] + "...")
    else:
        print(result)