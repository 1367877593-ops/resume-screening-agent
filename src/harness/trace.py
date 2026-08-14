"""调用链落盘。

README 里那些「结构化输出一次成功率」「规则 vs LLM 检出占比」的数字，
全部从这里统计得出 —— 说「我们处理了幻觉和格式错误」不值钱，
给出「一次成功率 78%，回灌重试后 99.2%」才值钱。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class Tracer:
    """一次运行对应一个 JSONL 文件，每次 LLM 调用追加一行。"""

    def __init__(self, trace_dir: Path, run_id: Optional[str] = None) -> None:
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.trace_dir / f"{self.run_id}.jsonl"

    def record(self, **fields: Any) -> None:
        fields.setdefault("ts", time.time())
        fields.setdefault("run_id", self.run_id)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fields, ensure_ascii=False) + "\n")


def read_traces(trace_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in sorted(Path(trace_dir).glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把 trace 汇总成可以直接贴进 README 的数字。"""
    calls = [r for r in rows if r.get("event") == "structured_call"]
    if not calls:
        return {"calls": 0}

    total = len(calls)
    cache_hits = sum(1 for r in calls if r.get("cache_hit"))
    live = [r for r in calls if not r.get("cache_hit")]
    first_try = sum(1 for r in live if r.get("repair_attempts", 0) == 0 and r.get("ok"))
    ok = sum(1 for r in live if r.get("ok"))

    return {
        "calls": total,
        "cache_hit_rate": round(cache_hits / total, 4),
        "live_calls": len(live),
        # 一次成功率：没有触发任何修复重试就通过 schema 校验
        "first_try_success_rate": round(first_try / len(live), 4) if live else None,
        # 修复后成功率：回灌错误重试之后最终通过
        "final_success_rate": round(ok / len(live), 4) if live else None,
        "total_prompt_tokens": sum(r.get("prompt_tokens", 0) or 0 for r in live),
        "total_completion_tokens": sum(r.get("completion_tokens", 0) or 0 for r in live),
        "avg_latency_ms": (
            round(sum(r.get("latency_ms", 0) or 0 for r in live) / len(live), 1) if live else None
        ),
    }
