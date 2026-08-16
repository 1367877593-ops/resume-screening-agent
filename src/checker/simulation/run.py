"""三人格模拟的统一入口：作答 -> 盲评 -> 诊断。

调用量：三次作答 + 一次盲评 = **每轮 4 次调用**，与题目数量无关（一次评完整套题）。
按题逐次调用会变成 30 次以上，那个成本不值得。
"""

from __future__ import annotations

from typing import Optional

from config.settings import get_thresholds
from schema.jd import JD
from schema.question import QuestionSet
from schema.simulation import SimulationReport

from checker.simulation.diagnose import diagnose
from checker.simulation.grader import grade_blind
from checker.simulation.personas import answer_as_bluffer, answer_as_expert, answer_as_resume


def simulate_question_set(
    question_set: QuestionSet,
    jd: JD,
    resume_text: str,
    persona_model: Optional[str] = None,
    grader_model: Optional[str] = None,
    thresholds: Optional[dict] = None,
) -> SimulationReport:
    """作答用快模型，盲评用强模型。

    作答只要「像那个人格会给出的答案」，快模型足够；盲评是真正的判断环节，
    打歪了整套诊断就废了，值得用贵的那个。
    """
    # 三个人格拿到的都是 to_public() 的结果，看不到 rubric。
    public = question_set.to_public()

    answers = (
        answer_as_expert(public, jd, model=persona_model)
        + answer_as_bluffer(public, model=persona_model)
        + answer_as_resume(public, resume_text, model=persona_model)
    )
    scores = grade_blind(question_set.questions, answers, model=grader_model)
    t = thresholds or get_thresholds()
    return SimulationReport(
        resume_id=question_set.resume_id,
        answers=answers,
        scores=scores,
        diagnoses=diagnose(scores, t),
        thresholds=dict(t["simulation"]),
    )
