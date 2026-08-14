"""scorer 是唯一决定「是否推进面试」的地方，也是全项目最该被测透的模块。

这些用例同时充当一份可执行的规则说明书：改了判定逻辑，这里必然红。
"""

from __future__ import annotations

from typing import List

import pytest

from agents.scorer import (
    aggregate_score,
    build_match_result,
    decide,
    find_hard_failures,
    normalized_weights,
    rank,
)
from schema.jd import JD, Requirement
from schema.match import RequirementVerdict

T = {"match": {"advance": 75.0, "hold": 60.0}}


def make_jd(*specs) -> JD:
    """specs: (id, weight, is_hard)"""
    return JD(
        jd_id="jd1",
        title="AI 产品实习生",
        raw_text="...",
        requirements=[
            Requirement(requirement_id=i, text=f"要求{i}", weight=w, is_hard=h)
            for i, w, h in specs
        ],
    )


def v(rid: str, satisfied: str, score: float) -> RequirementVerdict:
    return RequirementVerdict(
        requirement_id=rid, satisfied=satisfied, score=score, reason="r"
    )


# ---------------------------------------------------------------- 权重


def test_weights_normalize_to_one():
    w = normalized_weights(make_jd(("R1", 3, False), ("R2", 7, False)))
    assert w["R1"] == pytest.approx(0.3)
    assert w["R2"] == pytest.approx(0.7)
    assert sum(w.values()) == pytest.approx(1.0)


def test_all_zero_weights_degrade_to_equal_not_crash():
    """权重全 0 是模型输出异常，但它不该让流程崩掉。"""
    w = normalized_weights(make_jd(("R1", 0, False), ("R2", 0, False)))
    assert w["R1"] == pytest.approx(0.5) and w["R2"] == pytest.approx(0.5)


# ---------------------------------------------------------------- 加权


def test_aggregate_is_weighted_not_averaged():
    jd = make_jd(("R1", 9, False), ("R2", 1, False))
    # 高权重项满分、低权重项零分，总分应贴近 90 而不是均值 50
    assert aggregate_score(jd, [v("R1", "YES", 100), v("R2", "NO", 0)]) == pytest.approx(90.0)


def test_missing_verdict_counts_as_zero():
    """漏判必须计 0 分。

    若跳过未判定项，模型少答几条反而分数更高 —— 这是个会被优化掉的漏洞。
    """
    jd = make_jd(("R1", 1, False), ("R2", 1, False))
    assert aggregate_score(jd, [v("R1", "YES", 100)]) == pytest.approx(50.0)


# ---------------------------------------------------------------- 硬性项


def test_hard_failure_vetoes_high_score():
    """硬性项不满足时，总分再高也淘汰 —— 这是一票否决，不是扣分。"""
    jd = make_jd(("R1", 9, False), ("R2", 1, True))
    verdicts = [v("R1", "YES", 100), v("R2", "NO", 0)]
    result = build_match_result(jd, "resume1", verdicts, thresholds=T)

    assert result.total_score == pytest.approx(90.0)
    assert result.recommendation == "REJECT"
    assert result.hard_requirement_failed == ["要求R2"]
    assert "硬性要求未满足" in result.recommendation_reason


def test_missing_verdict_on_hard_requirement_is_treated_as_failure():
    """存疑时不放行：硬性项没给判定，按未满足处理。"""
    jd = make_jd(("R1", 1, False), ("R2", 1, True))
    assert find_hard_failures(jd, [v("R1", "YES", 100)]) == ["要求R2"]


def test_partial_on_hard_requirement_does_not_veto():
    """PARTIAL 不触发一票否决，只是拉低分数 —— 否决只留给明确的 NO。"""
    jd = make_jd(("R1", 1, True),)
    assert find_hard_failures(jd, [v("R1", "PARTIAL", 50)]) == []


# ---------------------------------------------------------------- 阈值


@pytest.mark.parametrize(
    "score,expected",
    [(100.0, "ADVANCE"), (75.0, "ADVANCE"), (74.9, "HOLD"),
     (60.0, "HOLD"), (59.9, "REJECT"), (0.0, "REJECT")],
)
def test_thresholds_are_inclusive_lower_bounds(score, expected):
    assert decide(score, [], thresholds=T) == expected


# ---------------------------------------------------------------- 排序


def test_hard_failures_sink_to_bottom_regardless_of_score():
    jd_pass = make_jd(("R1", 1, False))
    jd_hard = make_jd(("R1", 1, True))
    high_but_failed = build_match_result(jd_hard, "bad", [v("R1", "NO", 0)], thresholds=T)
    low_but_clean = build_match_result(jd_pass, "ok", [v("R1", "PARTIAL", 65)], thresholds=T)

    items = rank("jd1", [high_but_failed, low_but_clean]).items
    assert [i.resume_id for i in items] == ["ok", "bad"]
    assert items[0].rank == 1 and items[1].rank == 2


def test_ranking_is_stable_on_ties():
    """并列时顺序必须稳定，否则演示两次看到的排名不一样，没法解释。"""
    jd = make_jd(("R1", 1, False))
    results = [
        build_match_result(jd, rid, [v("R1", "YES", 80)], thresholds=T)
        for rid in ("c", "a", "b")
    ]
    assert [i.resume_id for i in rank("jd1", results).items] == ["a", "b", "c"]
    assert [i.resume_id for i in rank("jd1", list(reversed(results))).items] == ["a", "b", "c"]


def test_only_advancing_candidates_get_questions():
    """被淘汰的候选人不出题：既是业务逻辑，也把调用量压下来一大截。"""
    jd = make_jd(("R1", 1, False))
    results = [
        build_match_result(jd, "high", [v("R1", "YES", 90)], thresholds=T),   # ADVANCE
        build_match_result(jd, "mid", [v("R1", "PARTIAL", 65)], thresholds=T), # HOLD
        build_match_result(jd, "low", [v("R1", "NO", 10)], thresholds=T),      # REJECT
    ]
    advancing = rank("jd1", results).advancing()
    assert {c.resume_id for c in advancing} == {"high", "mid"}


# ---------------------------------------------------------------- 理由


def test_reason_is_consistent_with_verdicts():
    """理由由代码拼装，必须和实际判定一致 —— 模型写的理由可能和它自己的 verdict 打架。"""
    jd = make_jd(("R1", 5, False), ("R2", 5, False))
    result = build_match_result(
        jd, "r1", [v("R1", "YES", 95), v("R2", "NO", 10)], thresholds=T
    )
    assert "综合得分 52.5" in result.recommendation_reason
    assert "优势：要求R1" in result.recommendation_reason
    assert "短板：要求R2" in result.recommendation_reason
