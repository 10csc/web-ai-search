# -*- coding: utf-8 -*-
"""web-ai-search 入口 —— send / extract / auto 三模式"""
import argparse, time, sys, os, json, importlib, importlib.util
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


from common import (DEFAULT_CDP_PORT, load_config, ensure_browser, ensure_page, detect_platform, get_or_create_project,
                    safe_page_text, get_project_name, _save_session, get_session_url)
from generator import script_exists, generate_interaction_script, get_platform_script_path
from logger import log_entry


def load_platform_module(platform):
    script_path = get_platform_script_path(platform)
    spec = importlib.util.spec_from_file_location(f"platform_{platform}", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_script_generated(platform, url):
    try: from playwright.sync_api import sync_playwright
    except ImportError: raise RuntimeError("未安装 playwright，请运行: python setup.py")
    config = load_config()
    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, default_url=url)
        page = ensure_page(browser, target_url); time.sleep(1)
        generate_interaction_script(page, platform, page.url)


# ====== send ======

def _try_submit(plat, page, prompt):
    """尝试填prompt+提交，返回 (remaining, success)"""
    plat.fill_prompt(page, prompt)
    plat.dismiss_blockers(page)
    plat.submit(page)
    time.sleep(1)
    remaining = page.evaluate(
        "() => {let e=document.querySelector('[contenteditable=true],textarea');"
        "return e?(e.value||e.innerText||'').length:-1}")
    return remaining, (remaining is not None and remaining <= 2)


def run_send(prompt, topic, url, force_regenerate=False):
    """发送prompt到浏览器AI平台。
    三段式：1)尝试已有链接 -> 2)重试submit -> 3)链接失效则回退新开会话。
    """
    platform = detect_platform(url)
    print(f"[发送] 平台: {platform}")
    if force_regenerate or not script_exists(platform):
        print(f"[发送] 生成脚本..."); _ensure_script_generated(platform, url)
    plat = load_platform_module(platform)
    log_entry(get_project_name(), "input", f"TOPIC:{topic}")
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright，请运行: python setup.py"
    config = load_config()
    project = get_or_create_project()
    is_fixed = config.get("session_mode", "fixed") == "fixed"

    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        target_url = get_session_url(project=project, default_url=url)
        page = ensure_page(browser, target_url)

        # 第1次：发送到已有/默认链接
        remaining, ok = _try_submit(plat, page, prompt)
        if ok:
            current_url = page.url
            if is_fixed and current_url != target_url:
                _save_session(project, current_url)
                print("[发送] 已绑定: {} -> {}".format(project, current_url[:80]))
            print("[发送] 成功 (残留{}字符)".format(remaining))
            return "OK"

        # 第2次：重试 submit（可能UI延迟导致第一次残留）
        print("[发送] 残留{}字符, 重试提交...".format(remaining))
        plat.submit(page); time.sleep(1)
        remaining = page.evaluate(
            "() => {let e=document.querySelector('[contenteditable=true],textarea');"
            "return e?(e.value||e.innerText||'').length:-1}")
        if remaining is not None and remaining <= 2:
            print("[发送] 重试成功")
            if is_fixed and page.url != target_url:
                _save_session(project, page.url)
            return "OK"

        # 第3次：链接失效，回退默认URL新开会话
        if is_fixed:
            print("[发送] 链接可能失效，回退新开会话...")
            page = ensure_page(browser, url)  # 回退到平台首页
            remaining, ok = _try_submit(plat, page, prompt)
            if ok:
                _save_session(project, page.url)
                print("[发送] 新会话绑定: {} -> {}".format(project, page.url[:80]))
                return "OK"

        return "ERROR: 发送失败 (残留{}字符，3次尝试均失败)".format(remaining)


# ====== extract ======

def run_extract(prompt, topic, url):
    platform = detect_platform(url)
    print(f"[提取] 平台: {platform}")
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright，请运行: python setup.py"
    config = load_config()
    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, default_url=url)
        page = ensure_page(browser, target_url); time.sleep(1)
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
    result = run_send(prompt, topic, url, force_regenerate)
    if not result or "ERROR" in str(result):
        return f"发送失败: {result}"
    print("[自动] 发送完成，内容检测中...")
    
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright，请运行: python setup.py"
    config = load_config()
    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, default_url=url)
        page = ensure_page(browser, target_url)
        from extractor import extract_content, is_content_complete
        deadline = time.time() + max_wait
        last_len = 0; stable_count = 0; start_ts = time.time()
        while time.time() < deadline:
            time.sleep(2)
            raw = safe_page_text(page)
            if not raw: continue
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
            else:
                # 提取失败时输出诊断信息
                if marker_count >= 2:
                    print(f"[轮询] {elapsed}s | 页面={len(raw)}字符 | 标记={marker_count} | 提取失败(标记足够但内容未通过验证)")
                else:
                    print(f"[轮询] {elapsed}s | 页面={len(raw)}字符 | 标记={marker_count} | 等待更多标记...")
                # 内容充裕兜底：标记>=2、页面>2000字符、已等待>60秒 → 跳过 CoT 检测，直接用标记对截取
                if marker_count >= 2 and len(raw) > 2000 and elapsed > 60:
                    marker = f"[搜索主题：{topic}]"
                    positions = []
                    idx = 0
                    while True:
                        idx = raw.find(marker, idx)
                        if idx == -1:
                            break
                        positions.append(idx)
                        idx += len(marker)
                    if len(positions) >= 2:
                        forced = raw[positions[-2] + len(marker):positions[-1]].strip()
                        if len(forced) > 300:
                            print(f"[自动] 强制提取 ({len(forced)}字符, {elapsed}s)")
                            log_entry(get_project_name(), "output", forced[:50000])
                            data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
                            os.makedirs(data_dir, exist_ok=True)
                            with open(os.path.join(data_dir, "latest_result.md"), "w", encoding="utf-8") as f:
                                f.write(forced)
                            return forced
        raw = safe_page_text(page)
        content = extract_content(raw, prompt, topic)
        if content and len(content) > 300:
            print(f"[自动] 超时兜底 ({len(content)}字符)")
            log_entry(get_project_name(), "output", content[:50000])
            data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "latest_result.md"), "w", encoding="utf-8") as f:
                f.write(content)
            return content
        return "ERROR: 超时"


# ====== CLI ======

if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')
    _sys.stderr.reconfigure(encoding='utf-8')
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
