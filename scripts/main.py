# -*- coding: utf-8 -*-
"""web-ai-search 入口 —— send / extract / auto 三模式"""
import argparse, time, sys, os, json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


from common import (DEFAULT_CDP_PORT, load_config, ensure_browser, ensure_page, detect_platform, get_or_create_project,
                    safe_page_text, get_project_name, _save_session, get_session_url, submit_and_verify,
                    save_result)
from generator import script_exists, generate_interaction_script, get_platform_script_path, load_platform_module
from logger import log_entry


def _ensure_script_generated(platform, url):
    try: from playwright.sync_api import sync_playwright
    except ImportError: raise RuntimeError("未安装 playwright，请运行: python setup.py")
    config = load_config()
    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, platform=platform)
        page = ensure_page(browser, target_url); time.sleep(1)
        generate_interaction_script(page, platform, page.url)


# ====== send ======

def _try_submit(plat, page, prompt):
    """尝试填prompt+提交，返回 (remaining, success)。"""
    try:
        return submit_and_verify(plat, page, prompt)
    except Exception as e:
        print(f"[发送] fill/submit 异常: {e}")
        return -1, False


def _validate_before_send(prompt, topic):
    """防呆：发送前验证 prompt 完整性。返回 (ok, errors)。"""
    from prompt_builder import validate_prompt
    ok, errors = validate_prompt(prompt, topic)
    if not ok:
        print(f"[发送] ⚠️ 格式验证失败: {'; '.join(errors)}")
    else:
        print(f"[发送] ✓ 格式验证通过 (topic={topic})")
    return ok, errors


def run_send(prompt, topic, url, force_regenerate=False):
    """发送prompt到浏览器AI平台。
    防呆：发送前验证 prompt 格式，发送后验证内容已提交。
    三段式：1)尝试已有链接 -> 2)重试submit -> 3)链接失效则回退新开会话。
    """
    # === 防呆：发送前验证 ===
    ok, errors = _validate_before_send(prompt, topic)
    if not ok:
        return f"ERROR: 格式验证失败: {'; '.join(errors)}"

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
        target_url = get_session_url(project=project, platform=platform)
        page = ensure_page(browser, target_url)

        # 重试循环：同页面最多 3 次，不回退新会话
        for attempt in range(1, 4):
            remaining, ok = _try_submit(plat, page, prompt)
            if ok:
                current_url = page.url
                if is_fixed and current_url != target_url:
                    _save_session(project, current_url)
                    print("[发送] 已绑定: {} -> {}".format(project, current_url[:80]))
                print("[发送] 成功 (残留{}字符, 第{}次)".format(remaining, attempt))
                return "OK"
            print("[发送] 第{}次失败 (残留{}), {}秒后重试...".format(attempt, remaining, attempt * 2))
            time.sleep(attempt * 2)

        return "ERROR: 发送失败 (残留{}字符，3次尝试均失败)".format(remaining)


# ====== extract ======

def _validate_extraction(content, marker_count):
    """防呆：提取后验证内容质量。返回 (ok, report)。"""
    if not content or len(content) < 150:
        return False, f"内容过短 ({len(content) if content else 0}字符)"
    if marker_count < 2:
        return False, f"标记不足 (仅{marker_count}个，至少需2个形成标记对)"
    # 排除明显的错误内容
    bad_starts = ["请联网搜索", "请搜索", "ERROR"]
    if any(content.strip().startswith(s) for s in bad_starts):
        return False, "内容以搜索指令开头（可能提取了 prompt 而非回复）"
    return True, f"{len(content)}字符, 标记×{marker_count}"


def run_extract(prompt, topic, url):
    """提取搜索结果。
    防呆：验证标记存在、内容长度、关键词匹配。
    """
    platform = detect_platform(url)
    print(f"[提取] 平台: {platform}")
    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright，请运行: python setup.py"
    config = load_config()
    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, platform=platform)
        page = ensure_page(browser, target_url); time.sleep(1)
        raw = safe_page_text(page)
        if not raw: return "ERROR: 页面无内容"
        print(f"[提取] 页面: {len(raw)} 字符")
        marker = f"[搜索主题：{topic}]"
        marker_count = raw.count(marker)
        print(f"[提取] 标记数: {marker_count}")

        from extractor import extract_content, dom_extract
        content = extract_content(raw, prompt, topic)
        # 标记对提取失败 → DOM 兜底（用平台 EXTRACT_SEL）
        if not content:
            content = dom_extract(page, platform)
            if content:
                print(f"[提取] DOM兜底: {len(content)} 字符")
        if content:
            quality_ok, quality_report = _validate_extraction(content, marker_count)
            print(f"[提取] {'✓' if quality_ok else '⚠️'} {quality_report}")
            log_entry(get_project_name(), "output", content[:50000])
            save_result(content)
            print(f"[提取] 成功 ({len(content)} 字符)")
            return content
        return f"ERROR: 提取失败 (页面{len(raw)}字符, 标记{marker_count}个)"


# ====== auto: send + detect + extract ======

def run_auto(prompt, topic, url, force_regenerate=False, max_wait=300):
    platform = detect_platform(url)
    result = run_send(prompt, topic, url, force_regenerate)
    if not result or "ERROR" in str(result):
        return f"发送失败: {result}"
    print("[自动] 发送完成，内容检测中...")

    try: from playwright.sync_api import sync_playwright
    except ImportError: return "ERROR: 未安装 playwright，请运行: python setup.py"
    from evolution import load_or_create_polling

    config = load_config()
    polling = load_or_create_polling(platform)
    interval = polling.get_interval()
    stability_rounds = polling.get_stability_rounds()
    print(f"[自动] 平台={platform} 轮询间隔={interval}s 稳定阈值={stability_rounds}轮")

    with sync_playwright() as p:
        browser, _page = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))
        project = get_or_create_project()
        target_url = get_session_url(project=project, platform=platform)
        page = ensure_page(browser, target_url)
        from extractor import dom_extract, is_content_complete
        from evolution import load_or_create_polling
        polling_p = load_or_create_polling(platform)
        no_closing_stable = 0
        closing_threshold = polling_p.get_no_closing_threshold()
        closing_marker = f"[搜索主题：{topic}]"
        deadline = time.time() + max_wait
        last_len = 0; stable_count = 0; start_ts = time.time()

        while time.time() < deadline:
            time.sleep(interval)
            elapsed = int(time.time() - start_ts)

            # 主导：DOM 直接提取最后一个 AI 回复（避免标记污染）
            content = dom_extract(page, platform)

            if content and is_content_complete(content, platform=platform):
                tail = content.strip()[-300:]
                has_closing = closing_marker in tail
                polling.record_sample(elapsed, len(content))

                if has_closing:
                    no_closing_stable = 0
                    print(f"[轮询] {elapsed}s | DOM={len(content)}字符 | "
                          f"结尾标记✓ 稳定{stable_count}/{stability_rounds}")
                    if len(content) == last_len:
                        stable_count += 1
                        if stable_count >= stability_rounds:
                            print(f"[自动] 稳定 ({len(content)}字符, {elapsed}s)")
                            polling.adapt_interval()
                            polling.update_closing_marker_reliability(True)
                            log_entry(get_project_name(), "output", content[:50000])
                            save_result(content)
                            return content
                    else:
                        stable_count = 0
                    last_len = len(content)
                else:
                    stable_count = 0
                    if len(content) == last_len and len(content) > 500:
                        no_closing_stable += 1
                    else:
                        no_closing_stable = 0
                    last_len = len(content)
                    if elapsed % 15 == 0:
                        print(f"[轮询] {elapsed}s | DOM={len(content)}字符 | "
                              f"等待结尾标记...(稳定{no_closing_stable}轮)")
                    # 无标记但内容长期稳定：AI 已完成
                    if no_closing_stable >= closing_threshold:
                        polling.adapt_interval()
                        polling.update_closing_marker_reliability(False)
                        print(f"[自动] 无结尾标记但稳定 ({len(content)}字符, {elapsed}s)")
                        log_entry(get_project_name(), "output", content[:50000])
                        save_result(content)
                        return content

            # DOM 提取失败 → 兜底：标记对定位 + 强制提取
            if not content and elapsed > 60:
                raw = safe_page_text(page)
                if raw:
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
                        forced = raw[positions[-1] + len(marker):].strip()
                        if len(forced) < 300:
                            forced = raw[positions[-2] + len(marker):positions[-1]].strip()
                        if len(forced) > 300:
                            from evolution import GlobalKnowledge
                            for footer_kw in GlobalKnowledge.get_footer_patterns():
                                pos = forced.find(footer_kw)
                                if pos > 0 and pos > len(forced) * 0.5:
                                    forced = forced[:pos].strip()
                                    break
                            print(f"[自动] 强制提取 ({len(forced)}字符, {elapsed}s)")
                            log_entry(get_project_name(), "output", forced[:50000])
                            save_result(forced)
                            return forced

            # 有 DOM 内容但一直不稳定：最终阶段也收下
            if content and len(content) > 300 and elapsed > max_wait * 0.8:
                print(f"[自动] 接近超时兜底 ({len(content)}字符, {elapsed}s)")
                log_entry(get_project_name(), "output", content[:50000])
                save_result(content)
                return content

        # 超时：最后一试
        content = dom_extract(page, platform)
        if content and len(content) > 300:
            print(f"[自动] 超时兜底 ({len(content)}字符)")
            log_entry(get_project_name(), "output", content[:50000])
            save_result(content)
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
