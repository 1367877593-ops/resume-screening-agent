"""按岗位与阶段检索经验，渲染成可注入 prompt 的文本块。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from schema.lesson import Lesson, normalize_job_kind, render_for_prompt

from flywheel.lessons import load_all


def retrieve(
    job_title: str,
    stage: str,
    limit: int = 6,
    path: Optional[Path] = None,
) -> List[Lesson]:
    """取该岗位在该阶段的历史经验，命中多的优先。

    `limit` 存在的理由和 MAX_PER_JOB 一样：注入六条以上，模型基本就开始
    挑着看了，多注入不等于更有效。
    """
    key = normalize_job_kind(job_title)
    hits = [x for x in load_all(path) if x.job_kind == key and x.stage == stage]
    hits.sort(key=lambda x: (-x.hits, x.issue_code))
    return hits[:limit]


def lessons_block(
    job_title: str,
    stage: str,
    limit: int = 6,
    path: Optional[Path] = None,
) -> str:
    """检索 + 渲染。业务代码只需要这一个函数。"""
    return render_for_prompt(retrieve(job_title, stage, limit=limit, path=path))
