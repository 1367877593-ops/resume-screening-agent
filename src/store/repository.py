"""统一读写门面。上层只依赖这个文件，不直接碰 sqlite。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import get_settings
from store.db import connect


def _db_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    s = get_settings()
    return s.resolve(s.db_path)


def save_run(payload: Dict[str, Any], db_path: Optional[Path] = None) -> str:
    """落库一次完整运行。payload 由 pipeline.api.result_to_dict 生成。"""
    run_id = payload.get("run_id") or uuid.uuid4().hex[:12]
    conn = connect(_db_path(db_path))
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, created_at, jd_id, jd_title, payload)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    time.time(),
                    payload["jd"]["jd_id"],
                    payload["jd"]["title"],
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.execute("DELETE FROM candidates WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO candidates"
                " (run_id, resume_id, candidate_name, rank, total_score, recommendation, gate_status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        c["resume_id"],
                        c.get("candidate_name"),
                        c["rank"],
                        c["total_score"],
                        c["recommendation"],
                        c.get("gate_status"),
                    )
                    for c in payload["ranking"]
                ],
            )
    finally:
        conn.close()
    return run_id


def list_runs(limit: int = 20, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    conn = connect(_db_path(db_path))
    try:
        rows = conn.execute(
            "SELECT run_id, created_at, jd_title,"
            " (SELECT COUNT(*) FROM candidates c WHERE c.run_id = r.run_id) AS n_candidates"
            " FROM runs r ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_run(run_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    conn = connect(_db_path(db_path))
    try:
        row = conn.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:
        conn.close()


def top_candidates(limit: int = 10, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """跨批次查最高分候选人 —— 结构化存储相对 JSON 文件的实际价值所在。"""
    conn = connect(_db_path(db_path))
    try:
        rows = conn.execute(
            "SELECT c.*, r.jd_title FROM candidates c JOIN runs r ON r.run_id = c.run_id"
            " WHERE c.recommendation != 'REJECT' ORDER BY c.total_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
