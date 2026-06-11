# -*- coding: utf-8 -*-
"""工作区状态管理 —— Workspace State + Episodic Memory + Semantic Memory。

状态与记忆分离（LangGraph 设计原则）：
- Workspace State（JSON）：当前任务的文件/日志/中间结果，任务结束后归档
- Episodic Memory（JSONL）：每次搜索的过程记录——平台、耗时、可信度、是否触发重搜
- Semantic Memory（Markdown）：结论性知识，按主题索引，用户确认后归档
"""

import os, json, time
from datetime import datetime, timezone, timedelta
from runtime_paths import WORKSPACE_DIR, MEMORY_DIR, SKILL_DIR as _SKILL_DIR

CST = timezone(timedelta(hours=8))

# 向后兼容：旧代码/test 直接读写 SKILL_DIR / WORKSPACE_DIR / MEMORY_DIR
SKILL_DIR = _SKILL_DIR
SCRIPT_DIR = os.path.join(_SKILL_DIR, "scripts")


def _ensure_dirs():
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    os.makedirs(MEMORY_DIR, exist_ok=True)


# ============================================================
# Workspace State —— 当前任务状态（任务结束自动清理）
# ============================================================

class WorkspaceState:
    """一次研究任务的工作区。"""

    def __init__(self, task_id=None):
        _ensure_dirs()
        self.task_id = task_id or f"task_{int(time.time())}"
        self.path = os.path.join(WORKSPACE_DIR, f"{self.task_id}.json")
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "task_id": self.task_id,
            "created_at": datetime.now(CST).isoformat(),
            "status": "created",
            "query": "",
            "plan": {},
            "results": [],
            "replan_count": 0,
            "checkpoints": [],
        }

    def save(self):
        self.state["updated_at"] = datetime.now(CST).isoformat()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def set_query(self, query):
        self.state["query"] = query
        self.state["status"] = "planned"
        self.save()

    def set_plan(self, plan_dict):
        self.state["plan"] = {k: str(v)[:200] if isinstance(v, (list, dict)) else v
                              for k, v in plan_dict.items()}
        self.save()

    def add_result(self, platform, question, content_len, gaps_count, links_count):
        self.state["results"].append({
            "platform": platform,
            "question": question[:100],
            "content_len": content_len,
            "gaps": gaps_count,
            "links": links_count,
            "time": datetime.now(CST).isoformat(),
        })
        self.state["status"] = "executing"
        self.save()

    def add_checkpoint(self, label=""):
        self.state["checkpoints"].append({
            "label": label,
            "results_count": len(self.state["results"]),
            "time": datetime.now(CST).isoformat(),
        })
        self.save()

    def increment_replan(self):
        self.state["replan_count"] += 1
        self.save()

    def complete(self):
        self.state["status"] = "completed"
        self.state["completed_at"] = datetime.now(CST).isoformat()
        self.save()

    def cleanup(self):
        """任务结束清理工作区文件。"""
        if os.path.exists(self.path):
            os.remove(self.path)

    def get_summary(self):
        return {
            "task_id": self.task_id,
            "status": self.state["status"],
            "results": len(self.state["results"]),
            "replans": self.state["replan_count"],
            "query": self.state["query"][:80],
        }


# ============================================================
# Episodic Memory —— 过程记录（每次搜索的平台/耗时/可信度）
# ============================================================

def record_episode(project, platform, topic, depth, duration_sec, credibility, content_len, gaps_count, triggered_replan=False):
    """记录一次搜索 episode。"""
    _ensure_dirs()
    path = os.path.join(MEMORY_DIR, f"{project}_episodes.jsonl")
    record = {
        "time": datetime.now(CST).isoformat(),
        "platform": platform,
        "topic": topic[:100],
        "depth": depth,
        "duration_sec": duration_sec,
        "credibility": credibility,
        "content_len": content_len,
        "gaps": gaps_count,
        "triggered_replan": triggered_replan,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_episodes(project, limit=20):
    """读取最近的 episode 记录。"""
    path = os.path.join(MEMORY_DIR, f"{project}_episodes.jsonl")
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records[-limit:]


def get_platform_stats(project):
    """统计各平台的历史表现——供 Planner 调优路由。"""
    episodes = read_episodes(project, limit=100)
    stats = {}
    for ep in episodes:
        p = ep["platform"]
        if p not in stats:
            stats[p] = {"count": 0, "total_cred": 0, "total_duration": 0, "total_gaps": 0}
        stats[p]["count"] += 1
        stats[p]["total_cred"] += ep.get("credibility", 0)
        stats[p]["total_duration"] += ep.get("duration_sec", 0)
        stats[p]["total_gaps"] += ep.get("gaps", 0)
    for p in stats:
        n = stats[p]["count"]
        stats[p]["avg_credibility"] = round(stats[p]["total_cred"] / n, 1) if n else 0
        stats[p]["avg_duration"] = round(stats[p]["total_duration"] / n, 1) if n else 0
        stats[p]["avg_gaps"] = round(stats[p]["total_gaps"] / n, 1) if n else 0
    return stats


# ============================================================
# Semantic Memory —— 结论知识（按主题索引，用户确认后归档）
# ============================================================

def archive_conclusion(project, topic, conclusion, sources=None):
    """用户确认后将结论归档到 Semantic Memory。"""
    _ensure_dirs()
    path = os.path.join(MEMORY_DIR, f"{project}_semantic.md")
    entry = f"\n---\n## {topic}\n\n**归档时间**: {datetime.now(CST).isoformat()}\n\n{conclusion}\n"
    if sources:
        entry += f"\n### 来源\n" + "\n".join(f"- {s}" for s in sources)
    entry += "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def search_semantic(project, keyword, limit=5):
    """按关键词搜索 Semantic Memory。"""
    path = os.path.join(MEMORY_DIR, f"{project}_semantic.md")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # 按 --- 分割条目
    entries = content.split("\n---\n")
    matches = []
    for entry in entries:
        if keyword.lower() in entry.lower():
            matches.append(entry[:500])
    return matches[-limit:]


if __name__ == "__main__":
    # 自测
    ws = WorkspaceState()
    ws.set_query("Python asyncio vs Trio 2026 选型")
    ws.add_result("deepseek", "asyncio breaking changes", 3500, 0, 5)
    ws.add_result("kimi", "Trio 最新版本特性", 4200, 1, 8)
    ws.complete()
    print("Workspace:", ws.get_summary())

    record_episode("test", "deepseek", "Python asyncio", "L2", 45, 8, 3500, 0)
    record_episode("test", "kimi", "Python asyncio", "L2", 32, 7, 4200, 1)
    print("Episodes:", len(read_episodes("test")))
    print("Stats:", get_platform_stats("test"))
