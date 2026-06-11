# -*- coding: utf-8 -*-
"""Thin JSON API for host agents.

This module is the intended communication seam between Claude/Codex skills and
the WebAISearch runtime. Hosts pass one JSON request and receive one JSON
response; browser control and mutable state stay behind the runtime.
"""

import argparse
import json
import os
import sys
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from agent import agent_search
from common import load_config, get_or_create_project
from runtime_paths import RUNTIME_HOME, DATA_DIR, CONFIG_PATH, ensure_runtime_dirs


def runtime_status():
    config = load_config()
    return {
        "ok": True,
        "runtime_home": RUNTIME_HOME,
        "data_dir": DATA_DIR,
        "config_path": CONFIG_PATH,
        "project": config.get("current_project") or get_or_create_project(),
        "search_platform": config.get("search_platform", "deepseek"),
        "synthesis_platform": config.get("synthesis_platform", "deepseek"),
        "cdp_port": config.get("cdp_port"),
    }


def handle_request(request):
    ensure_runtime_dirs()
    action = request.get("action", "search")

    if action == "status":
        return runtime_status()

    if action != "search":
        return {"ok": False, "error": f"unknown action: {action}"}

    query = (request.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}

    result = agent_search(
        query,
        depth=request.get("depth", "L2"),
        project_context=request.get("project_context"),
        force_platform=request.get("platform"),
        quick=bool(request.get("quick", False)),
        output_dir=request.get("output_dir"),
    )
    return {
        "ok": True,
        "query": result.get("query"),
        "tool_choice": result.get("tool_choice"),
        "report_path": result.get("report_path"),
        "validation": result.get("validation"),
        "elapsed_sec": result.get("elapsed_sec"),
        "workspace_summary": result.get("workspace_summary"),
        "note": result.get("note"),
    }


def _load_request(args):
    if args.request_file:
        with open(args.request_file, "r", encoding="utf-8") as f:
            return json.load(f)
    if args.request_json:
        return json.loads(args.request_json)
    raw = sys.stdin.read().strip()
    if raw:
        return json.loads(raw)
    return {"action": "status"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="WebAISearch runtime JSON API")
    parser.add_argument("--request-json", default="", help="JSON request body")
    parser.add_argument("--request-file", default="", help="Path to JSON request file")
    args = parser.parse_args(argv)

    try:
        response = handle_request(_load_request(args))
    except Exception as exc:
        response = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }

    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
