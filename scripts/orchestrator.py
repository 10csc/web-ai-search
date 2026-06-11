# -*- coding: utf-8 -*-
"""执行编排层。
双平台体系：
  - 检索平台：发送搜索 → 轮询提取
  - 整合平台：汇总素材 → 生成报告

平台配置在 config.json：search_platform / synthesis_platform / platform_urls
加新平台只需改 config.json，零代码改动。
"""

import os, sys, time, re
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from common import (
    load_config, ensure_browser, ensure_page, safe_page_text,
    get_or_create_project, get_session_url, is_valid_session_url, DEFAULT_CDP_PORT,
    submit_and_verify, save_result,
)
from generator import load_platform_module
from prompt_builder import build_search_prompt, build_synthesis_prompt, validate_prompt, assess_reliability
from extractor import extract_with_diagnosis, is_content_complete
from logger import log_entry
from diagnostics import diagnose, format_diagnosis


def _get_search_platform():
    return load_config().get("search_platform", "deepseek")


def _get_synthesis_platform():
    return load_config().get("synthesis_platform", "deepseek")

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


def _is_valid_synthesis(content, max_chars=2000):
    """LLM 判断合成内容是否有效（非拒绝/道歉/空话）。返回 (bool, str)。"""
    import json as _json, ssl, urllib.request
    try:
        config = load_config()
        api_url = config.get("deepseek_api", "https://api.deepseek.com/v1")
        api_key = config.get("deepseek_key", "")
        if not api_key:
            return True, "无 API key，默认通过"

        sample = content[:max_chars]
        payload = _json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是一个内容质量检测器。只回复 YES 或 NO。"},
                {"role": "user", "content": f"以下文本是否是一份有效的研究整合报告（包含分析、结论、验证标注）？如果文本主要是道歉、拒绝、高峰期提示、或只有搜索URL列表没有分析，回复 NO。\n\n{sample}"}
            ],
            "temperature": 0.0, "max_tokens": 2,
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            f"{api_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        body = _json.loads(resp.read().decode("utf-8"))
        answer = body["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("YES"), f"LLM判定: {answer}"
    except Exception as e:
        print(f"  [验证检测] LLM 调用失败，默认通过: {e}")
        return True, f"检测异常，默认通过"


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
    sp = _get_search_platform()
    kp = _get_synthesis_platform()
    for plat in list(dict.fromkeys([sp, kp])):  # 去重
        url = get_session_url(project=project, platform=plat)
        ok = is_valid_session_url(url, plat)
        status = "✓ 已配置" if ok else "✗ 未配置（首页）"
        lines.append(f"  {plat}: {status}  {url[:80]}")
    lines.append(f"  搜索={sp}  整合={kp}  搜索失败=拒绝  总结失败=降级本地API")
    return "\n".join(lines)


def _submit_to_platform(platform, page, prompt, topic):
    plat = load_platform_module(platform)
    if not plat: return False, f"平台 {platform} 未定型"
    try:
        remaining, ok = submit_and_verify(plat, page, prompt)
        if ok:
            return True, None
        # 输入框未清空：重试一次
        plat.submit(page); time.sleep(1.5)
        return True, None  # 尽力了
    except Exception as e:
        return False, str(e)


def _send_one(browser, platform, question, config, project, depth, decomposed, stage="search"):
    """发送一个问题，返回 (page, prompt, topic) 或 (None,None,None)。

    stage="search" 用 build_search_prompt（开放性探索+可靠性自标注）
    stage="synthesis" 用 build_synthesis_prompt（被动验证+可信度报告）
    """
    if stage == "synthesis":
        topic, prompt = build_synthesis_prompt(question, depth)
    else:
        topic, prompt = build_search_prompt(question, depth)
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
    """轮询等待提取。DOM 提取为主（避免 textContent 漏标记），结尾标记判定完成。

    textContent 兜底路径接入自进化：提取失败时触发 FailureAnalyzer → StrategyAdapter。
    """
    from evolution import load_or_create_polling, load_or_create_profile
    from evolution import FailureAnalyzer, StrategyAdapter
    from extractor import dom_extract

    polling = load_or_create_polling(platform)
    profile = load_or_create_profile(platform)
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
                txt_content, diagnosis = extract_with_diagnosis(raw, prompt, topic, platform)
                # 自进化：诊断 → 适配
                if diagnosis and diagnosis.get("adaptable"):
                    try:
                        analysis = FailureAnalyzer.analyze(raw, txt_content, platform, profile)
                        if analysis and analysis.get("adaptable"):
                            StrategyAdapter.adapt(profile, analysis)
                    except Exception:
                        pass
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
        content, diagnosis = extract_with_diagnosis(raw, prompt, topic, platform)
        # 自进化：超时兜底说明策略需要调整
        if diagnosis and diagnosis.get("adaptable"):
            try:
                analysis = FailureAnalyzer.analyze(raw, content, platform, profile)
                if analysis and analysis.get("actionable"):
                    StrategyAdapter.adapt(profile, analysis)
            except Exception:
                pass
        if content and len(content) > 150:
            return content
    return None


def _diagnose_and_adapt(error_type, platform=None):
    """故障诊断 + 自进化联动。

    1. 运行诊断检查，定位根因
    2. 如果诊断发现平台相关问题，触发 StrategyAdapter 适配策略
    3. 输出人类可读诊断结果
    """
    ctx = {"platform": platform} if platform else {}
    result = diagnose(error_type, ctx)
    print(f"\n{format_diagnosis(result)}")

    # 诊断 → 进化联动：平台脚本问题/配置问题 → 触发策略适配
    if result["failed"] > 0:
        try:
            from evolution import load_or_create_profile, StrategyAdapter
            ep = load_or_create_profile(platform) if platform else load_or_create_profile("deepseek")
            # 将诊断失败项转为进化信号
            fail_msgs = [r["message"] for r in result["results"] if not r["passed"]]
            diagnosis = {
                "failure_type": error_type,
                "evidence": "; ".join(fail_msgs[:3]),
                "severity": "high" if result["failed"] >= 2 else "medium",
                "suggestion": result["diagnosis"],
                "adaptable": True,
                "scope": "platform_specific" if platform else "cross_platform",
            }
            adapted = StrategyAdapter.adapt(ep, diagnosis)
            if adapted:
                print(f"  [进化] 策略已适配: {adapted.get('changes', [])}")
        except Exception:
            pass

    return result


def execute(plan_dict, progress_callback=None):
    """执行搜索计划。

    L2: 单平台搜索 + 可靠性评估（无重搜）
    L3: 搜索（可靠性循环）+ 整合验证（被动验证模式）
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "未安装 playwright"}

    config = load_config()
    project = get_or_create_project()
    depth = plan_dict.get("depth", "L2")
    sqs = plan_dict["sub_questions"]
    results = []
    all_links = []
    sp = _get_search_platform()
    kp = _get_synthesis_platform()
    send_failures = 0
    MAX_SEND_FAILURES = 3
    replan = plan_dict.get("replan_triggers", {})
    max_research_rounds = replan.get("max_research_rounds", 2)

    with sync_playwright() as p:
        browser, _ = ensure_browser(p, config.get("cdp_port", DEFAULT_CDP_PORT))

        if depth == "L2":
            # === L2: 单平台搜索 + 可靠性评估 ===
            sq = sqs[0]
            stage = sq.get("stage", "search")
            print(f"\n[Send] L2 {sp}: {sq['question'][:50]}")
            page, prompt, topic = _send_one(browser, sp, sq["question"],
                                            config, project, depth, True, stage)
            if page:
                send_failures = 0
                print(f"  [等待] 提取中...")
                content = _wait_one(sp, page, prompt, topic, max_wait=180)
                if content:
                    reliability = assess_reliability(content)
                    gaps = detect_gaps(content)
                    links = extract_links(content)
                    all_links.extend(links)
                    results.append({"question": sq["question"], "platform": sp,
                        "content": content, "gaps": gaps, "links": links,
                        "content_len": len(content), "reliability": reliability})
                    log_entry(project, "output", f"[{sp}] {len(content)}字符 可靠={reliability.get('reliable')}")
                    print(f"  [{sp}] ✓ {len(content)}字符 可靠={reliability.get('reliable')}")
                else:
                    results.append({"question": sq["question"], "platform": sp,
                                    "content": None, "error": "提取超时", "gaps": [], "links": []})
            else:
                send_failures += 1
                if send_failures >= MAX_SEND_FAILURES:
                    print(f"  ⛔ 连续 {send_failures} 次发送失败，请手动检查浏览器状态后重试")
                    _diagnose_and_adapt("send_failed", platform=sp)
        else:
            # === L3: 搜索（可靠性循环）+ 整合验证 ===
            search_sqs = [s for s in sqs if s.get("stage") != "synthesis"]
            synth_sqs = [s for s in sqs if s.get("stage") == "synthesis"]

            # --- 阶段 1: 搜索 + 可靠性循环 ---
            for i, sq in enumerate(search_sqs):
                print(f"\n[Search] L3 [{i+1}/{len(search_sqs)}] {sp}: {sq['question'][:60]}")
                content = None
                reliability = None
                re_search_count = 0

                for round_num in range(max_research_rounds + 1):
                    if round_num > 0:
                        print(f"  [重搜] 第{round_num}轮 ({sq['question'][:40]}...)")
                    page, prompt, topic = _send_one(browser, sp, sq["question"],
                                                    config, project, depth, True, "search")
                    if not page:
                        send_failures += 1
                        if send_failures >= MAX_SEND_FAILURES:
                            print(f"  ⛔ 连续 {send_failures} 次发送失败，请手动检查浏览器状态后重试")
                            _diagnose_and_adapt("send_failed", platform=sp)
                            break
                        continue

                    send_failures = 0
                    print(f"  [等待] 提取中...")
                    content = _wait_one(sp, page, prompt, topic, max_wait=180)
                    if not content:
                        break

                    reliability = assess_reliability(content)
                    status = "兜底通过" if reliability.get("fallback") else \
                             f"已确认={reliability['confirmed']} 推断={reliability['inferred']} 未确认={reliability['unconfirmed']}"
                    print(f"  [可靠性] {status} → {'✓ 可靠' if reliability['reliable'] else '✗ 不可靠'}")

                    # 自进化：不可靠 → 适配提取策略
                    if not reliability["reliable"] and not reliability.get("fallback"):
                        try:
                            from evolution import load_or_create_profile, StrategyAdapter
                            ep = load_or_create_profile(sp)
                            StrategyAdapter.adapt(ep, {
                                "failure_type": "low_reliability",
                                "evidence": f"confirmed={reliability['confirmed']} inferred={reliability['inferred']} unconfirmed={reliability['unconfirmed']}",
                                "severity": "medium",
                                "suggestion": "提示词中加强可靠性要求，或降低该平台标记依赖",
                                "adaptable": True,
                                "scope": "platform_specific",
                            })
                        except Exception:
                            pass

                    if reliability["reliable"]:
                        break

                    re_search_count += 1

                if content:
                    gaps = detect_gaps(content)
                    links = extract_links(content)
                    all_links.extend(links)
                    results.append({"question": sq["question"], "platform": sp,
                        "content": content, "gaps": gaps, "links": links,
                        "content_len": len(content),
                        "reliability": reliability or {},
                        "re_search_count": re_search_count})
                    log_entry(project, "output", f"[{sp}] {len(content)}字符 重搜={re_search_count}次")
                    print(f"  [{sp}] ✓ {len(content)}字符 (重搜{re_search_count}次)")
                else:
                    results.append({"question": sq["question"], "platform": sp,
                                    "content": None, "error": "提取超时", "gaps": [], "links": []})
                    print(f"  [{sp}] ✗ 提取超时")

            # --- 阶段 2: 整合验证 ---
            if synth_sqs:
                sq = synth_sqs[0]
                # 1. 采集素材写入临时文件
                materials = "\n\n---\n\n".join([
                    f"## 采集方向 {i+1}\n{r['content']}"
                    for i, r in enumerate(results) if r.get("content")
                ])
                data_dir = os.path.join(os.path.dirname(SCRIPT_DIR), "data")
                os.makedirs(data_dir, exist_ok=True)
                mat_file = os.path.join(data_dir, "_materials.md")
                try: os.remove(mat_file)
                except Exception: pass
                with open(mat_file, "w", encoding="utf-8") as f:
                    f.write(materials)
                print(f"  [素材] {len(materials)}字符 → {mat_file}")

                synthesis_ok = True
                if len(materials) < 100:
                    print(f"  [{kp}] ⚠ 素材文件内容不足，跳过整合")
                    try: os.remove(mat_file)
                    except Exception: pass
                    results.append({"question": sq["question"], "platform": kp,
                                    "content": None, "error": "素材不足", "gaps": [], "links": []})
                    synthesis_ok = False

                # 2. 打开整合平台 + 上传素材 + 发送验证提示词
                if synthesis_ok:
                    session_url = get_session_url(project=project, platform=kp)
                    if not is_valid_session_url(session_url, kp):
                        print(f"  [{kp}] ⚠ 未配置聊天链接 → 降级本地 API 总结")
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
                    # 生成合成阶段提示词
                    topic, prompt = build_synthesis_prompt(sq["question"], depth)
                    if not validate_prompt(prompt, topic)[0]:
                        print(f"  [{kp}] prompt 验证失败")
                        results.append({"question": sq["question"], "platform": kp,
                                        "content": None, "error": "prompt验证", "gaps": [], "links": []})
                        synthesis_ok = False

                if synthesis_ok:
                    # 上传素材 + 发送验证提示词
                    print(f"\n[Verify] L3 {kp}: {sq['question'][:60]}")
                    plat_mod = load_platform_module(kp)
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

                    ok_send, err = _submit_to_platform(kp, page, prompt, topic)
                    if not ok_send:
                        print(f"  [{kp}] 发送失败 ({str(err)[:40]})，重试...")
                        try:
                            page = ensure_page(browser, session_url, new_tab=False); time.sleep(2)
                            if not uploaded:
                                plat_mod2 = load_platform_module(kp)
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
                    time.sleep(0.5)
                    if page.url != session_url:
                        from common import _save_session
                        _save_session(project, page.url)
                        print(f"  [{kp}] ✓ 已发送 (新会话)")
                    else:
                        print(f"  [{kp}] ✓ 已发送")
                    try: os.remove(mat_file)
                    except Exception: pass

                    print(f"  [等待] {kp} 验证整合中...")
                    content = _wait_one(kp, page, prompt, topic, max_wait=300)
                    if content:
                        valid, reason = _is_valid_synthesis(content)
                        if not valid:
                            print(f"  [{kp}] LLM判定无效 ({reason}) → 降级本地 API 总结")
                            local = _synthesize_local(materials, plan_dict.get("original_query", ""))
                            if local:
                                results.append({"question": sq["question"], "platform": f"{kp}(本地)",
                                    "content": local, "gaps": [], "links": [],
                                    "content_len": len(local)})
                                log_entry(project, "output", f"[{kp}/本地] {len(local)}字符")
                                print(f"  [{kp}/本地] ✓ {len(local)}字符")
                            else:
                                results.append({"question": sq["question"], "platform": kp,
                                                "content": content, "error": "整合无效且本地总结失败",
                                                "gaps": [], "links": []})
                        else:
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

    # 清理临时材料文件
    try:
        mat_file = os.path.join(os.path.dirname(SCRIPT_DIR), "data", "_materials.md")
        if os.path.exists(mat_file):
            os.remove(mat_file)
    except Exception:
        pass

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
