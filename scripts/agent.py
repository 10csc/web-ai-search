# -*- coding: utf-8 -*-
"""WebAISearch Agent 统一入口 —— 串联全流程。

流程：ToolRouter → Planner → Orchestrator → Synthesizer → Workspace

使用方式：
    python scripts/agent.py "搜索主题" [--depth L2] [--platform deepseek]

    # 完整 Agent 流程（含工具选择、分解、并行、验证）
    python scripts/agent.py "微服务和单体架构在2026年应该怎么选？" --depth L3

    # 快速模式（跳过分解，单平台直接搜索）
    python scripts/agent.py "React 最新版本号" --quick
"""

import os, sys, time, argparse, json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from tool_router import route as route_tool
from planner import plan as make_plan, format_plan
from orchestrator import execute as exec_plan, execute_simple
from synthesizer import synthesize, generate_report, cross_validate
from workspace import WorkspaceState, record_episode
from common import load_config, get_or_create_project
from diagnostics import diagnose, format_diagnosis
from runtime_paths import DATA_DIR


def agent_search(user_query, depth="L2", project_context=None, force_platform=None, quick=False, output_dir=None):
    """Agent 主流程。

    参数:
        user_query: 用户问题
        depth: L1/L2/L3
        project_context: 项目背景（技术栈/约束/目标），只在整合阶段注入，不影响搜索客观性
        force_platform: 强制指定平台
        quick: 快速模式
        output_dir: 报告输出目录（默认 data/）

    返回:
        {
            "query": str,
            "tool_choice": {...},
            "plan": {...},
            "execution": {...},
            "report": str,
            "workspace_summary": {...},
        }
    """
    start_time = time.time()
    project = get_or_create_project()

    # Step 0: 工具选择
    tool_choice = route_tool(user_query)
    actual_tool = tool_choice["tool"]
    actual_depth = tool_choice["depth"]

    # 若用户指定深度，以用户为准
    if depth and depth in ("L1", "L2", "L3"):
        actual_depth = depth
    if actual_tool == "WebSearch":
        actual_depth = "L1"

    print(f"[Agent] 工具: {actual_tool} | 深度: {actual_depth} | 理由: {tool_choice['reason']}")

    # 平台配置检查（每次启动提示）
    from orchestrator import check_platform_config
    print(f"[Agent] 平台配置:\n{check_platform_config(project)}")

    # 若为 WebSearch / L1，跳过 WebAISearch Agent 流程
    if actual_depth == "L1":
        return {
            "query": user_query,
            "tool_choice": tool_choice,
            "plan": None,
            "execution": None,
            "report": f"[WebSearch] {user_query}",
            "note": "L1 查询应由调用方 Agent 使用 WebSearch 工具处理，不走 WebAISearch",
        }

    # Step 1: 规划
    plan_dict = make_plan(user_query, actual_depth, project_context)
    if force_platform:
        # 强制覆盖所有子问题的平台
        for sq in plan_dict["sub_questions"]:
            sq["platform"] = force_platform
            sq["reason"] = "用户指定平台"

    print(format_plan(plan_dict))

    # Workspace
    workspace = WorkspaceState()
    workspace.set_query(user_query)
    workspace.set_plan(plan_dict)

    # Step 2: 执行
    try:
        if quick:
            platform = force_platform or plan_dict["sub_questions"][0]["platform"]
            content = execute_simple(user_query, platform, actual_depth)
            results = [{"question": user_query, "platform": platform, "content": content, "gaps": [], "links": [], "content_len": len(content) if content else 0}]
            execution = {"results": results, "gaps_total": 0, "all_links": []}
        else:
            execution = exec_plan(plan_dict)
            for r in execution.get("results", []):
                workspace.add_result(
                    r.get("platform", "?"),
                    r.get("question", "")[:100],
                    r.get("content_len", 0),
                    len(r.get("gaps", [])),
                    len(r.get("links", [])),
                )
    except Exception as e:
        print(f"\n[Agent] 执行失败: {e}")
        # 自动诊断
        search_platform = plan_dict["sub_questions"][0].get("platform", "deepseek") if plan_dict.get("sub_questions") else "deepseek"
        diag = diagnose("send_failed", context={"platform": search_platform})
        print(format_diagnosis(diag))
        raise

    # Step 3: 整合
    report, validation = synthesize(user_query, execution)

    # 输出报告
    data_dir = output_dir or DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    report_path = os.path.join(data_dir, "latest_result.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[Agent] 报告: {report_path} ({len(report)} 字符)")

    # 记录 Episodic Memory
    elapsed = int(time.time() - start_time)
    for r in execution.get("results", []):
        if r.get("content"):
            record_episode(
                project, r["platform"], r.get("question", "")[:100],
                actual_depth, elapsed,
                credibility=validation.get("confidence", "中") == "高" and 8 or 6,
                content_len=r.get("content_len", 0),
                gaps_count=len(r.get("gaps", [])),
            )

    # 完成
    workspace.complete()
    summary = workspace.get_summary()

    print(f"\n[Agent] 完成 | 耗时: {elapsed}s | 结果: {summary['results']}个 | 置信度: {validation.get('confidence', 'N/A')}")

    return {
        "query": user_query,
        "tool_choice": tool_choice,
        "plan": plan_dict,
        "execution": execution,
        "report": report,
        "report_path": report_path,
        "validation": validation,
        "workspace_summary": summary,
        "elapsed_sec": elapsed,
    }


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')
    _sys.stderr.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description="WebAISearch Agent")
    parser.add_argument("query", nargs="?", default="", help="搜索问题")
    parser.add_argument("--depth", "-d", default="L2", choices=["L1", "L2", "L3"])
    parser.add_argument("--platform", "-p", default=None, help="强制指定平台")
    parser.add_argument("--quick", "-q", action="store_true", help="快速模式（跳过分解）")
    parser.add_argument("--file", "-f", default=None, help="从文件读取问题")
    args = parser.parse_args()

    query = args.query
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            query = f.read().strip()
    if not query:
        print("用法: python agent.py '搜索问题' [--depth L2] [--platform deepseek] [--quick]")
        _sys.exit(1)

    result = agent_search(
        query,
        depth=args.depth,
        force_platform=args.platform,
        quick=args.quick,
    )
    print(f"\n{'='*50}")
    print(f"工具: {result['tool_choice']['tool']} | 深度: {result['plan']['depth'] if result['plan'] else 'L1'} | 耗时: {result.get('elapsed_sec', '?')}s")
    if result.get("report_path"):
        print(f"报告: {result['report_path']}")
    if result.get("note"):
        print(f"说明: {result['note']}")
