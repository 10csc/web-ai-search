"""JSONL 日志记录 —— 追加写入，不创建多余文件"""
import json
import os
from datetime import datetime, timezone, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CST = timezone(timedelta(hours=8))


def log_entry(project_name: str, entry_type: str, content: str):
    """追加一条日志到 data/<project_name>.jsonl"""
    data_dir = os.path.join(SKILL_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    log_path = os.path.join(data_dir, f"{project_name}.jsonl")

    record = {
        "time": datetime.now(CST).isoformat(timespec="seconds"),
        "type": entry_type,
        "content": content
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[日志] {entry_type} → {log_path}")


def read_history(project_name: str, limit: int = 5) -> list[dict]:
    """读取最近 N 条日志"""
    log_path = os.path.join(SKILL_DIR, "data", f"{project_name}.jsonl")
    if not os.path.exists(log_path):
        return []
    records = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records[-limit:]
