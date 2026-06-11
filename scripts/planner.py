# -*- coding: utf-8 -*-
"""规划层 —— 问题分解 + L2/L3 路由。

双平台体系：
  - 检索平台（SEARCH_PLATFORM）：发送搜索 → 轮询提取
  - 整合平台（SYNTH_PLATFORM）：汇总素材 → 生成报告
平台配置在 orchestrator.py 顶部，改一处全局生效。
"""

import os, sys, json, re
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from orchestrator import _get_search_platform, _get_synthesis_platform


def _get_llm_config():
    config_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("deepseek_api", "https://api.deepseek.com/v1"), \
               cfg.get("deepseek_key", "")
    except Exception:
        return "https://api.deepseek.com/v1", ""


DECOMPOSE_PROMPT = """你是研究规划器。将用户问题拆分为 2 个独立研究任务，每个任务都是完整分析（含搜索+推理+结论），不是单纯信息采集。

## 原则
- L2: 不拆，返回 FULL
- L3: 拆为 2 个互补分析视角，每个 ≤60字
- 每个方向都是完整的"搜索→分析→结论"，不是"采集某类信息"
- 两个方向互补（如：技术深度+产业实践，或英文生态+中文生态）
- 禁止拆超过 2 个

## 示例（L3 LLM推理平台选型）
DOMAIN: 主流推理框架(vLLM/TRT-LLM/SGLang)技术架构对比与性能分析
DOMAIN: 国内企业LLM推理平台落地实践、成本优化与踩坑经验

## 输出格式
L3: DOMAIN: xxx
L2: FULL:
每行一个方向。不要编号、不要多余解释。"""


def _llm_decompose(user_query, depth="L2"):
    """LLM 分解为采集方向。失败返回 None。"""
    try:
        from openai import OpenAI
        api_url, api_key = _get_llm_config()
        if not api_key:
            return None
        client = OpenAI(base_url=api_url, api_key=api_key)
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": DECOMPOSE_PROMPT},
                {"role": "user", "content": f"深度: {depth}\n"
                    + ("L3: 拆为 2 个互补分析方向\n" if depth == "L3" else "")
                    + f"问题: {user_query}"},
            ],
            temperature=0.1, max_tokens=500,
        )
        text = resp.choices[0].message.content.strip()
        domains = []
        for line in text.split("\n"):
            line = line.strip()
            line_clean = re.sub(r"^L\d:\s*", "", line.strip())
            if re.match(r"FULL:", line_clean, re.I):
                return [{"question": user_query, "decomposed": False}]
            m = re.match(r"DOMAIN:\s*(.+)", line_clean, re.I)
            if m and m.group(1).strip():
                domains.append({"question": m.group(1).strip(), "decomposed": True})
        return domains if domains else None
    except Exception as e:
        print(f"[Planner] LLM 分解失败: {e}")
        return None


def plan(user_query, depth="L2", project_context=None):
    """规划入口。

    project_context: 项目背景（技术栈/约束/目标），只在整合阶段使用，不注入搜索主题。
    返回 {original_query, project_context, depth, sub_questions, ...}。
    """
    sp = _get_search_platform()
    kp = _get_synthesis_platform()
    sub_questions = []

    if depth == "L2":
        sub_questions.append({
            "question": user_query,
            "platform": sp,
            "reason": f"L2 {sp} 单平台检索",
            "stage": "search",
        })
    else:
        domains = _llm_decompose(user_query, depth) or \
                  [{"question": user_query, "decomposed": False}]

        for d in domains[:3]:
            sub_questions.append({
                "question": d["question"],
                "platform": sp,
                "reason": f"L3 采集: {sp} 串行",
                "stage": "search",
            })

        # 整合 prompt：不注入项目背景到搜索主题，而是在整合时单独传递
        count = len(sub_questions)
        synth_question = f"基于以上 {count} 份采集素材，生成完整技术研究报告（含交叉验证、信源评分、矛盾检测）"
        if project_context:
            synth_question += f"\n\n【项目背景（仅用于建议适配，不改变报告客观性）】\n{project_context}"
        sub_questions.append({
            "question": synth_question,
            "platform": kp,
            "reason": f"{kp} 整合+验证",
            "stage": "synthesis",
        })

    decomposed = len(sub_questions) > 2

    return {
        "original_query": user_query,
        "project_context": project_context,
        "depth": depth,
        "sub_questions": sub_questions,
        "decomposed": decomposed,
        "replan_triggers": {
            "timeout_no_new_info_sec": 60,
            "credibility_below": 6,
            "contradiction_detected": True,
            "max_replan_rounds": 3,
            "max_research_rounds": 2,
        },
    }


def format_plan(plan_dict):
    sqs = plan_dict.get("sub_questions", [])
    lines = [
        f"搜索计划: {plan_dict['original_query'][:80]}",
        f"深度: {plan_dict['depth']} | 子问题: {len(sqs)}个",
        f"{'='*50}",
    ]
    for i, sq in enumerate(sqs, 1):
        lines.append(f"  [{i}] → {sq['platform']} | {sq['question'][:60]}")
        lines.append(f"      {sq.get('reason', '')}")
    lines.append(f"{'='*50}")
    lines.append("RePlan: 超时60s | 可信度<6 | 矛盾检测 | 最多3轮")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')
    for q, d in [
        ("企业级 LLM 推理平台：推理框架选型、GPU调度、模型服务化", "L3"),
        ("Rust trait 和 Go interface 的设计差异", "L2"),
    ]:
        print(format_plan(plan(q, d)))
        print()
