"""经验条目（反思飞轮）。

Checker 每次发现的问题不该只用一次。同一个岗位反复筛人时，模型会反复犯同一类
错误 —— 题目数量不够、题干重复、证据引用不完整。把这些沉淀下来，下次生成前
按岗位检索注入，就是「越用越准」。

关键约束是**注入内容必须稳定**：条目里带命中次数，但渲染进 prompt 的只有去重
排序后的告诫文本。否则每跑一次 hits 变一次，prompt 跟着变，缓存键全部漂移，
无 Key 回放就永远命中不了。
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import List

from pydantic import BaseModel, Field


def normalize_job_kind(title: str) -> str:
    """把 JD 标题归一化成检索键。

    只做粗粒度归一（去空白与标点、转小写）。语义级的岗位聚类需要向量检索，
    这个规模上不值得 —— 同一个岗位反复筛人时标题通常是一字不差的。
    """
    return re.sub(r"[\s\-_（）()【】\[\]·,，。.:：/]+", "", title).lower()


class Lesson(BaseModel):
    """一条沉淀下来的经验。

    `lesson_id` 由 (岗位, issue_code) 派生 —— 同一岗位下同一类问题永远合并成
    一条并累加 hits，而不是每次运行都堆一条新的。
    """

    lesson_id: str
    job_kind: str
    issue_code: str
    stage: str = Field(description="出问题的阶段：extract / match / question_set / followup")
    guidance: str = Field(description="一句可操作的告诫，会被注入下一次的 prompt")
    hits: int = 1
    updated_at: float = Field(default_factory=time.time)

    @staticmethod
    def make_id(job_kind: str, issue_code: str) -> str:
        raw = f"{job_kind}::{issue_code}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def render_for_prompt(lessons: List[Lesson]) -> str:
    """渲染成注入 prompt 的文本块。

    **刻意不包含 hits 和时间戳**：那两个字段每次运行都在变，带进 prompt 会让
    缓存键不断漂移。排序用 (issue_code) 而不是 hits，同样是为了稳定。
    """
    if not lessons:
        return "（暂无历史经验，这是该岗位的第一次筛选）"
    ordered = sorted(lessons, key=lambda x: x.issue_code)
    return "\n".join(f"- {x.guidance}" for x in ordered)
