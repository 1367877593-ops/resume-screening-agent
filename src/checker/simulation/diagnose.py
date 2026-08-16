"""三分对照真值表。

**这一层不调用任何 LLM**，只把三个分数按阈值翻译成诊断结论 ——
和 `agents/scorer.py` 一样的理由：判定逻辑必须可复现、可单测，
不能今天这么判明天那么判。阈值全部来自 `config/thresholds.yaml`。

判定顺序不可调换：先看专家。专家都答不出的题，讨论「有没有区分度」
是没有意义的 —— 那是一道坏题，不是一道难题。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from schema.simulation import QuestionDiagnosis, SimScore


def _judge(expert: float, bluffer: float, resume: float, t: Dict) -> tuple:
    """返回 (诊断, 说明)。真值表见 ARCHITECTURE.md 第七节。"""
    if expert < t["expert_pass"]:
        return (
            "BROKEN",
            f"理想专家只拿到 {expert:.0f} 分（低于 {t['expert_pass']:.0f}），"
            "题目表述不清或缺少作答前提",
        )
    if bluffer > t["bluffer_max"]:
        return (
            "NO_DISCRIMINATION",
            f"背题党拿到 {bluffer:.0f} 分（高于 {t['bluffer_max']:.0f}），"
            "靠通用面经即可作答，区分不出真实经历",
        )
    if resume < t["resume_pass"]:
        return (
            "OUT_OF_RANGE",
            f"简历人格只拿到 {resume:.0f} 分（低于 {t['resume_pass']:.0f}），"
            "题目有区分度但超出这位候选人简历的射程",
        )
    return (
        "GOOD",
        f"专家 {expert:.0f} / 背题党 {bluffer:.0f} / 简历 {resume:.0f}，"
        "有区分度且候选人答得上",
    )


def diagnose(scores: List[SimScore], thresholds: Dict) -> List[QuestionDiagnosis]:
    """把盲评分数汇总成每道题一条诊断。

    三个人格的分数缺任何一个，这道题就不出诊断 —— 缺分数时补 0 会让
    题目被误判成 BROKEN，凭空产生一条要求模型重写的 issue。
    """
    t = thresholds["simulation"]
    by_question: Dict[str, Dict[str, float]] = {}
    order: List[str] = []
    for s in scores:
        if s.question_id not in by_question:
            by_question[s.question_id] = {}
            order.append(s.question_id)
        by_question[s.question_id][s.persona] = s.score

    out: List[QuestionDiagnosis] = []
    for qid in order:
        got = by_question[qid]
        if not {"expert", "bluffer", "resume"} <= set(got):
            continue
        expert, bluffer, resume = got["expert"], got["bluffer"], got["resume"]
        verdict, detail = _judge(expert, bluffer, resume, t)
        out.append(
            QuestionDiagnosis(
                question_id=qid,
                expert_score=expert,
                bluffer_score=bluffer,
                resume_score=resume,
                diagnosis=verdict,
                detail=detail,
            )
        )
    return out
