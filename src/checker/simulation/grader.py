"""盲评阅卷。

阅卷官能看到评分标准（这是它的本职），但看不到作答者是谁 —— 每份作答只带
A / B / C 标签，标签到人格的映射留在代码侧。否则「这份是背题党写的」本身
就会变成打分依据，三分对照立刻失去意义。

两个容易忽略的点：

1. **标签按题独立打乱。** 一次调用要评十道题，如果全程 A 都是专家，模型很容易
   从前几题的风格推断出后面的身份。每道题重新洗一次牌就没有这个泄漏面。
2. **洗牌必须确定性。** 用 `random.shuffle()` 会让同样的输入每次生成不同的
   prompt，缓存键跟着漂移，`make demo` 的回放就再也命中不了。这里用
   question_id 派生种子，同一道题永远是同一个映射。
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from harness.structured import call_structured
from schema.question import QuestionFull
from schema.simulation import SimAnswer, SimScore

_LABELS = ("A", "B", "C")


class _GradedScore(BaseModel):
    question_id: str
    label: str
    score: float = Field(ge=0, le=100)
    reason: str = ""


class _GraderOutput(BaseModel):
    scores: List[_GradedScore] = Field(default_factory=list)


def label_map(question_id: str, personas: List[str]) -> Dict[str, str]:
    """标签 -> 人格。同一 question_id 恒定，不同题之间互不相同。"""
    seed = int(hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:8], 16)
    shuffled = list(personas)
    random.Random(seed).shuffle(shuffled)
    return dict(zip(_LABELS, shuffled))


def _bundles(questions: List[QuestionFull], answers: List[SimAnswer]) -> tuple:
    """把每道题打包成「题面 + 评分标准 + 匿名作答」，同时返回反查表。"""
    by_question: Dict[str, Dict[str, str]] = {}
    for a in answers:
        by_question.setdefault(a.question_id, {})[a.persona] = a.answer

    bundles: List[dict] = []
    reverse: Dict[str, Dict[str, str]] = {}
    for q in questions:
        got = by_question.get(q.question_id)
        if not got:
            continue
        mapping = label_map(q.question_id, sorted(got))
        reverse[q.question_id] = mapping
        bundles.append(
            {
                "question_id": q.question_id,
                "question": q.text,
                "rubric": [r.model_dump() for r in q.rubric],
                "answers": [
                    {"label": label, "answer": got[persona]}
                    for label, persona in mapping.items()
                ],
            }
        )
    return bundles, reverse


def grade_blind(
    questions: List[QuestionFull],
    answers: List[SimAnswer],
    model: Optional[str] = None,
) -> List[SimScore]:
    """一次调用评完所有题。分数按标签回落到人格。"""
    bundles, reverse = _bundles(questions, answers)
    if not bundles:
        return []

    graded = call_structured(
        "grader",
        {"bundles": json.dumps(bundles, ensure_ascii=False, indent=2)},
        _GraderOutput,
        model=model,
    )

    scores: List[SimScore] = []
    for row in graded.scores:
        persona = reverse.get(row.question_id, {}).get(row.label.strip().upper())
        # 标签对不上就丢弃：宁可这道题少一个分数、在诊断阶段被跳过，
        # 也不能把分数记到错误的人格头上 —— 那会让三分对照给出反向结论。
        if persona is None:
            continue
        scores.append(
            SimScore(
                question_id=row.question_id,
                persona=persona,
                score=row.score,
                reason=row.reason,
            )
        )
    return scores
