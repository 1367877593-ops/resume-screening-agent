"""SQLite 连接与建表。

题目允许「向量数据库或传统 DB」二选一，这里选 SQLite：
简历筛选是结构化查询场景（按分数排序、按岗位过滤），不是语义检索场景，
上向量库只会是个摆设。真正需要语义检索的是 L2 的经验飞轮，到那时再说。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    jd_id      TEXT NOT NULL,
    jd_title   TEXT NOT NULL,
    payload    TEXT NOT NULL          -- 完整结果的 JSON，用于回看
);

CREATE TABLE IF NOT EXISTS candidates (
    run_id         TEXT NOT NULL,
    resume_id      TEXT NOT NULL,
    candidate_name TEXT,
    rank           INTEGER NOT NULL,
    total_score    REAL NOT NULL,
    recommendation TEXT NOT NULL,
    gate_status    TEXT,
    PRIMARY KEY (run_id, resume_id),
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(total_score DESC);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
