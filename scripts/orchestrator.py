# -*- coding: utf-8 -*-
"""执行编排层。
双平台体系：
  - 检索平台（默认 DeepSeek）：发送搜索 → 轮询提取
  - 整合平台（默认 Kimi）：汇总素材 → 生成报告

平台可替换：改 SEARCH_PLATFORM / SYNTH_PLATFORM + PLATFORM_URLS 即可。
已定型平台脚本在 platforms/ 目录（deepseek/kimi/chatgpt/gemini/scnet），
替换时指定对应名称即可。
"""

import os, sys, time, re
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from common import (
    load_config, ensure_browser, ensure_page, safe_page_text,
    get_or_create_project, get_session_url, is_valid_session_url, DEFAULT_CDP_PORT,
)
from prompt_builder import build_final_prompt, validate_prompt
from extractor import extract_with_diagnosis, is_content_complete
from logger import log_entry

# === 平台配置（改这里全局生效；URL 在 config.json platform_urls/sessions） ===
SEARCH_PLATFORM = "deepseek"   # 检索平台
SYNTH_PLATFORM = "deepseek"   # 整合平台（Kimi 交互脚本待修复）

GAP_KEYWORDS = [
    "需要进一步了解", "建议查阅", "建议参考",
    "未覆盖", "未涉及", "超出范围", "不确定", "存疑",
    "有待验证", "需要确认", "暂不明确", "信息不足",
]


def detect_gaps(content):
    if not content: return []
    gaps = []
    for kw in GAP_KEYWORDS:
        if kw in content:
            idx = content.find(kw)
            ctx = content[max(0,idx-20):idx+len(kw)+60].replace("\n"," ").strip()
            gaps.append(f"[{kw}] {ctx}...")
    return gaps


def extract_links(content):
    if not content: return []
    urls = re.findall(r'https?://[^\s<>"\')\]]+', content)
    seen, result = set(), []
    for u in urls:
        u = u.rstrip(".,;:")
        if u not in seen and len(u) > 30:
            seen.add(u); result.append(u)
    return result[:20]


def _synthesize_local(materials, user_query):
    """本地 API 总结 — 纯文本调用，不触发搜索循环。"""
    import json as _json, ssl, urllib.request
    try:
        config = load_config()
        api_url = config.get("deepseek_api", "https://api.deepseek.com/v1")
        api_key = config.get("deepseek_key", "")
        if not api_key:
            return None

        payload = _json.dumps({
            "model": "deepseek-v4-pro",
            "messages": [
                {"role": "system", "content": "你是技术报告生成器。基于采集素材生成完整研究报告（概述、核心发现、方案对比、风险评估）。纯 Markdown，中文。"},
                {"role": "user", "content": f"原始问题：{user_query}\n\n采集素材：\n{materials[:25000]}\n\n请基于以上素材生成完整研究报告。注意：只做总结归纳，不发起新的联网搜索。"}
            ],
            "temperature": 0.3, "max_tokens": 4096,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=120, context=ctx)
        body = _json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [本地总结] 失败: {e}")
        return None


def _evolve_upload(platform, page):
    """自进化：诊断页面文件上传能力，持久化到平台档案。"""
    from evolution import load_or_create_profile
    import json as _json
    try:
        profile = load_or_create_profile(platform)
        upload_info = page.evaluate("""() => {
            let r = {fileInputs: [], uploadButtons: [], method: 'unknown'};
            document.querySelectorAll('input[type="file"]').forEach(el => {
                r.fileInputs.push({
                    accept: el.getAttribute('accept')?.substring(0,100)||'',
                    visible: el.offsetParent !== null,
                    parentClass: el.parentElement?.className?.substring(0,60)||''
                });
            });
            // 找上传图标/按钮
            document.querySelectorAll('button,[role=button],svg').forEach(el => {
                let a = (el.getAttribute('aria-label')||'').toLowerCase();
                let t = (el.textContent||'').toLowerCase();
                if (a.includes('upload')||a.includes('file')||a.includes('clip')||a.includes('attach')||
                    t.includes('上传')||t.includes('文件')||t.includes('附件')){
                    r.uploadButtons.push({
                        tag: el.tagName,
                        aria: a.substring(0,40),
                        text: t.substring(0,40),
                        class: el.className?.toString()?.substring(0,60)||''
                    });
                }
            });
            if (r.fileInputs.length > 0) r.method = 'hidden_input';
            return r;
        }""")
        if upload_info:
            profile.data["_upload_diagnosis"] = upload_info
            profile.save()
            print(f"  [进化] {platform} 上传能力已记录: {upload_info.get('method','unknown')}")
    except Exception as e:
        print(f"  [进化] 上传诊断失败: {e}")


def check_platform_config(project=None):
    """首次使用检查：打印各平台配置状态。"""
    from common import get_session_url, is_valid_session_url
    lines = []
    for plat in [SEARCH_PLATFORM, SYNTH_PLATFORM]:
        url = get_session_url(project=project, platform=plat)
        ok = is_valid_session_url(url, plat)
        status = "✓ 已配置" if ok else "✗ 未配置（首页）"
        lines.append(f"  {plat}: {status}  {url[:80]}")
    lines.append(f"  搜索失败=拒绝  总结失败=降级本地API")
    return "\n".join(lines)


def _get_platform_module(platform):
    import importlib.util
    from generator import get_platform_script_path, script_exists
    if not script_exists(platform): return None
    spec = importlib.util.spec_from_file_location(f"platform_{platform}",
                                                   get_platform_script_path(platform))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _submit_to_platform(platform, page, prompt, topic):
    plat = _get_platform_module(platform)
    if not plat: return False, f"平台 {platform} 未定型"
    try:
        plat.fill_prompt(page, prompt)
        plat.dismiss_blockers(page)
        plat.submit(page)
        time.sleep(2)
        remaining = page.evaluate(
            "() => {let e=document.querySelector('[contenteditable=true],textarea');"
            "return e?(e.value||e.innerText||'').length:-1}")
        if remaining is not None and remaining <= 2:
            return True, None
        # 输入框未清空：重试一次
        plat.submit(page); time.sleep(2)
        remaining = page.evaluate(
            "() => {let e=document.querySelector('[contenteditable=true],textarea');"
            "return e?(e.value||e.innerText||'').length:-1}")
        if remaining is not None and remaining <= 2:
            return True, None
        return False, f"残留 {remaining}"
    except Exception as e:
        return False, str(e)


def _send_one(browser, platform, question, config, project, depth, decomposed):
    """发送一个问题，返回 (page, prompt, topic) 或 (None,None,None)。"""
    topic, prompt = build_final_prompt(question, depth)
    ok, errors = validate_prompt(prompt, topic)
    if not ok:
        print(f"  [{platform}] prompt 验证失败")
        return None, None, None

    session_url = get_session_url(project=project, platform=platform)

    if not is_valid_session_url(session_url, platform):
        print(f"  [{platform}] ⚠ 未配置聊天链接（当前是首页，无法使用）")
        print(f"  [{platform}] → 请在浏览器中打开 {platform} 创建聊天，把 URL 贴到 config.json")
        print(f"  [{platform}] → 路径: sessions.{project}.{platform}")
        return None, None, None

    try:
        page = ensure_page(browser, session_url, new_tab=False)
        time.sleep(2)
    except Exception as e:
        print(f"  [{platform}] 打开页面失败: {e}")
        return None, None, None

    ok_send, err = _submit_to_platform(platform, page, prompt, topic)
    if not ok_send:
        print(f"  [{platform}] 发送失败 ({str(err)[:40]})，重试...")
        try:
            page = ensure_page(browser, session_url, new_tab=False); time.sleep(2)
        except Exception:
            pass
        ok_send, err = _submit_to_platform(platform, page, prompt, topic)
        if not ok_send:
            print(f"  [{platform}] 重试失败: {err}")
            return None, None, None

    time.sleep(0.5)
    if page.url != session_url:
        from common import _save_session
        _save_session(project, page.url)
        print(f"  [{platform}] ✓ 已发送 (新会话)")
    else:
        print(f"  [{platform}] ✓ 已发送")
    return page, prompt, topic


def _wait_one(platform, page, prompt, topic, max_wait=180):
    """轮询等待提取。DOM 提取为主（避免 textContent 漏标记），结尾标记判定完成。"""
    from evolution import load_or_create_polling
    from extractor import dom_extract

    polling = load_or_create_polling(platform)
    interval = polling.get_interval()
    stability_rounds = polling.get_stability_rounds()
    deadline = time.time() + max_wait
    last_len, stable_count = 0, 0
    start_ts = time.time()
    no_closing_stable = 0       # 无结尾标记但内容稳定的轮数
    closing_marker = f"[搜索主题：{topic}]"

    print(f"  [轮询] 间隔={interval}s 稳定阈值={stability_rounds}轮 (DOM模式)")

    while time.time() < deadline:
        time.sleep(interval)
        elapsed = int(time.time() - start_ts)

        # 主导：DOM 直接提取最后一个 AI 回复
        content = dom_extract(page, platform)

        if content and is_content_complete(content, platform=platform):
            tail = content.strip()[-300:]
            has_closing = closing_marker in tail

            if has_closing:
                no_closing_stable = 0
                print(f"  [轮询] {elapsed}s | DOM={len(content)}字符 | "
                      f"结尾标记✓ 稳定{stable_count}/{stability_rounds}")
                if len(content) == last_len:
                    stable_count += 1
                    if stable_count >= stability_rounds:
                        polling.adapt_interval()
                        polling.update_closing_marker_reliability(True)
                        return content
                else:
                    stable_count = 0
                last_len = len(content)
            else:
                stable_count = 0
                # 内容稳定但无结尾标记：AI 可能已完成但忘记放标记
                if len(content) == last_len and len(content) > 500:
                    no_closing_stable += 1
                else:
                    no_closing_stable = 0
                last_len = len(content)
                if elapsed % 15 == 0:
                    print(f"  [轮询] {elapsed}s | DOM={len(content)}字符 | "
                          f"等待结尾标记...(稳定{no_closing_stable}轮)")
                # 无标记但内容长期稳定（10轮≈30s）：AI 已完成，直接提取
                closing_threshold = polling.get_no_closing_threshold()
                if no_closing_stable >= closing_threshold:
                    polling.adapt_interval()
                    # 自进化：该平台不靠谱放结尾标记，下次降低阈值
                    polling.update_closing_marker_reliability(False)
                    print(f"  [兜底] {elapsed}s | 无结尾标记但内容稳定{no_closing_stable}轮 ({len(content)}字符)")
                    return content
        else:
            stable_count = 0
            last_len = 0
            # 辅助：textContent 标记提取
            raw = safe_page_text(page)
            if raw:
                txt_content, _ = extract_with_diagnosis(raw, prompt, topic, platform)
                if txt_content and is_content_complete(txt_content, platform=platform):
                    tail = txt_content.strip()[-300:]
                    if closing_marker in tail:
                        polling.adapt_interval()
                        print(f"  [textContent] {elapsed}s | {len(txt_content)}字符")
                        return txt_content

    # 超时兜底：DOM → textContent → 放弃
    content = dom_extract(page, platform)
    if content and len(content) > 150:
        print(f"  [DOM兜底] ({len(content)}字符)")
        return content
    raw = safe_page_text(page)
    if raw:
        content, _ = extract_with_diagnosis(raw, prompt, topic, platform)
        if content and len(content) > 150:
            return content
    return None


def execute(plan_dict, progress_callback=None):
    """执行搜索计划。检索平台串行采集，整合平台汇总报告。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "未安装 playwright"}

    config = load_config()
    project = get_or_create_project()
    depth = plan_dict.get("depth", "L2")
    decomposed = plan_dict.get("decomposed", False)
    sqs = plan_dict["sub_questions"]
    results = []
    all_links = []
    sp, kp = SEARCH_PLATFORM, SYNTH_PLATFORM
    send_failures = 0           # 连续发送失败计数
    MAX_SEND_FAILURES = 3       # 连续失败上限，超限提示用户接管

    with sync_playwright() as p:
        browser, _ = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))

        if depth == "L2":
            # === L2: 单平台检索 ===
            sq = sqs[0]
            print(f"\n[Send] L2 {sp}: {sq['question'][:50]}")
            page, prompt, topic = _send_one(browser, sp, sq["question"],
                                            config, project, depth, decomposed)
            if page:
                send_failures = 0
                print(f"  [等待] 提取中...")
                content = _wait_one(sp, page, prompt, topic, max_wait=180)
                if content:
                    gaps = detect_gaps(content)
                    links = extract_links(content)
                    all_links.extend(links)
                    results.append({"question": sq["question"], "platform": sp,
                        "content": content, "gaps": gaps, "links": links,
                        "content_len": len(content)})
                    log_entry(project, "output", f"[{sp}] {len(content)}字符")
                    print(f"  [{sp}] ✓ {len(content)}字符")
                else:
                    results.append({"question": sq["question"], "platform": sp,
                                    "content": None, "error": "提取超时", "gaps": [], "links": []})
            else:
                send_failures += 1
                if send_failures >= MAX_SEND_FAILURES:
                    print(f"  ⛔ 连续 {send_failures} 次发送失败，请手动检查浏览器状态后重试")
        else:
            # === L3: 采集串行 + 整合汇总 ===
            # 整合平台子问题以 "基于以上" 开头，其余为采集方向
            collect_sqs = [s for s in sqs if not s["question"].startswith("基于以上")]
            synth_sqs = [s for s in sqs if s["question"].startswith("基于以上")]

            for i, sq in enumerate(collect_sqs):
                print(f"\n[Send] L3 [{i+1}/{len(collect_sqs)}] {sp}: {sq['question'][:60]}")
                page, prompt, topic = _send_one(browser, sp, sq["question"],
                                                config, project, depth, decomposed)
                if not page:
                    send_failures += 1
                    results.append({"question": sq["question"], "platform": sp,
                                    "content": None, "error": "发送失败", "gaps": [], "links": []})
                    if send_failures >= MAX_SEND_FAILURES:
                        print(f"  ⛔ 连续 {send_failures} 次发送失败，请手动检查浏览器状态后重试")
                        break
                    continue

                send_failures = 0
                print(f"  [等待] 提取中...")
                content = _wait_one(sp, page, prompt, topic, max_wait=180)
                if content:
                    gaps = detect_gaps(content)
                    links = extract_links(content)
                    all_links.extend(links)
                    results.append({"question": sq["question"], "platform": sp,
                        "content": content, "gaps": gaps, "links": links,
                        "content_len": len(content)})
                    log_entry(project, "output", f"[{sp}] {len(content)}字符")
                    print(f"  [{sp}] ✓ {len(content)}字符")
                else:
                    results.append({"question": sq["question"], "platform": sp,
                                    "content": None, "error": "提取超时", "gaps": [], "links": []})
                    print(f"  [{sp}] ✗ 提取超时")

            if synth_sqs:
                sq = synth_sqs[0]
                # === 1. 采集素材写入临时文件 ===
                materials = "\n\n---\n\n".join([
                    f"## 采集方向 {i+1}\n{r['content']}"
                    for i, r in enumerate(results) if r.get("content")
                ])
                data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
                os.makedirs(data_dir, exist_ok=True)
                mat_file = os.path.join(data_dir, "_materials.md")
                with open(mat_file, "w", encoding="utf-8") as f:
                    f.write(materials)
                print(f"  [素材] {len(materials)}字符 → {mat_file}")
                if len(materials) < 100:
                    print(f"  [{kp}] ⚠ 素材文件内容不足（{len(materials)}字符），跳过整合")
                    results.append({"question": sq["question"], "platform": kp,
                                    "content": None, "error": "素材不足", "gaps": [], "links": []})
                    synthesis_ok = False

                # === 2. 打开整合平台页面 ===
                topic, prompt = build_final_prompt(sq["question"], depth)
                synthesis_ok = True
                if not validate_prompt(prompt, topic)[0]:
                    print(f"  [{kp}] prompt 验证失败")
                    results.append({"question": sq["question"], "platform": kp,
                                    "content": None, "error": "prompt验证", "gaps": [], "links": []})
                    synthesis_ok = False

                if synthesis_ok:
                    session_url = get_session_url(project=project, platform=kp)
                    if not is_valid_session_url(session_url, kp):
                        print(f"  [{kp}] ⚠ 未配置聊天链接 → 降级本地 API 总结")
                        print(f"  [{kp}] → 配置方法: sessions.{project}.{kp} = \"聊天URL\"")
                        content = _synthesize_local(materials, plan_dict.get("original_query", ""))
                        if content:
                            results.append({"question": sq["question"], "platform": f"{kp}(本地)",
                                "content": content, "gaps": [], "links": [],
                                "content_len": len(content)})
                            log_entry(project, "output", f"[{kp}/本地] {len(content)}字符")
                            print(f"  [{kp}/本地] ✓ {len(content)}字符")
                        else:
                            results.append({"question": sq["question"], "platform": kp,
                                            "content": None, "error": "本地总结也失败", "gaps": [], "links": []})
                        synthesis_ok = False
                if synthesis_ok:
                    try:
                        page = ensure_page(browser, session_url, new_tab=False)
                        time.sleep(2)
                    except Exception as e:
                        print(f"  [{kp}] 打开页面失败: {e}")
                        results.append({"question": sq["question"], "platform": kp,
                                        "content": None, "error": f"页面: {e}", "gaps": [], "links": []})
                        synthesis_ok = False

                if synthesis_ok:
                    # === 3. 上传素材文件 ===
                    print(f"\n[Send] L3 {kp}: {sq['question'][:60]}")
                    plat_mod = _get_platform_module(kp)
                    uploaded = False
                    if plat_mod and hasattr(plat_mod, "upload_file"):
                        try:
                            uploaded = plat_mod.upload_file(page, mat_file)
                            print(f"  [上传] {'✓' if uploaded else '✗'}")
                            if not uploaded:
                                _evolve_upload(kp, page)
                        except Exception as e:
                            print(f"  [上传] 异常: {e}")
                            _evolve_upload(kp, page)

                    # === 4. 填入整合提示词 + 发送 ===
                    ok_send, err = _submit_to_platform(kp, page, prompt, topic)
                    if not ok_send:
                        print(f"  [{kp}] 发送失败 ({str(err)[:40]})，重试...")
                        try:
                            page = ensure_page(browser, session_url, new_tab=False); time.sleep(2)
                            if not uploaded:
                                plat_mod2 = _get_platform_module(kp)
                                if plat_mod2 and hasattr(plat_mod2, "upload_file"):
                                    plat_mod2.upload_file(page, mat_file)
                        except Exception:
                            pass
                        ok_send, err = _submit_to_platform(kp, page, prompt, topic)
                        if not ok_send:
                            print(f"  [{kp}] 重试失败: {err}")
                            results.append({"question": sq["question"], "platform": kp,
                                            "content": None, "error": f"发送: {err}", "gaps": [], "links": []})
                            synthesis_ok = False

                if synthesis_ok:
                    # === 5. 保存会话 ===
                    time.sleep(0.5)
                    if page.url != session_url:
                        from common import _save_session
                        _save_session(project, page.url)
                        print(f"  [{kp}] ✓ 已发送 (新会话)")
                    else:
                        print(f"  [{kp}] ✓ 已发送")

                    # === 6. 轮询提取 ===
                    print(f"  [等待] {kp} 整合中...")
                    content = _wait_one(kp, page, prompt, topic, max_wait=300)
                    if content:
                        gaps = detect_gaps(content)
                        links = extract_links(content)
                        all_links.extend(links)
                        results.append({"question": sq["question"], "platform": kp,
                            "content": content, "gaps": gaps, "links": links,
                            "content_len": len(content)})
                        log_entry(project, "output", f"[{kp}] {len(content)}字符")
                        print(f"  [{kp}] ✓ {len(content)}字符")
                    else:
                        results.append({"question": sq["question"], "platform": kp,
                                        "content": None, "error": "超时", "gaps": [], "links": []})

    return {
        "results": results,
        "gaps_total": sum(len(r.get("gaps", [])) for r in results),
        "all_links": list(set(all_links)),
    }


def execute_simple(query, platform="deepseek", depth="L2"):
    plan_dict = {
        "original_query": query, "depth": depth,
        "sub_questions": [{"question": query, "platform": platform, "reason": "指定"}],
        "decomposed": False, "replan_triggers": {},
    }
    outcome = execute(plan_dict)
    if "error" in outcome: return f"ERROR: {outcome['error']}"
    r = outcome.get("results", [])
    return r[0].get("content") if r else None
