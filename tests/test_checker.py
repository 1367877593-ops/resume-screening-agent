"""Checker 规则测试。

归因规则是项目里对抗幻觉的主力，它的两端都必须守住：
排版差异不能误报，编造内容不能漏报。这两条各有专门用例。
"""

from __future__ import annotations

from typing import List

import pytest

from checker import rules  # noqa: F401  导入即注册
from checker.base import RuleContext, register, registered_rules, run_rules
from checker.evidence import is_grounded, is_too_short, similarity, text_similarity
from checker.rules.structure_rules import parse_ym
from checker.run import check_followups, check_match, check_question_set, check_resume
from config.settings import get_thresholds
from schema.document import RawDoc, SourceSpan
from schema.followup import AmbiguityPoint, FollowUpQuestion, FollowUpSet
from schema.issue import Issue
from schema.jd import JD, Requirement
from schema.match import MatchResult, RequirementVerdict
from schema.question import QuestionFull, QuestionSet, RubricLevel
from schema.resume import Education, ExtractedResume, Skill

RESUME_TEXT = (
    "李明\n\n教育背景\n2022.09 - 2026.06  华中科技大学  计算机科学与技术  本科\n\n"
    "项目经历\n基于 LangChain 与 Chroma 搭建了面向校内规章制度的检索问答系统，"
    "最终答案准确率从 61% 提升到 84%。\n\n技能\n熟悉 Python，掌握 pandas、FastAPI\n"
)


@pytest.fixture
def doc() -> RawDoc:
    return RawDoc(doc_id="D1", filename="resume.txt", full_text=RESUME_TEXT)


def span(text: str) -> SourceSpan:
    return SourceSpan(doc_id="D1", text=text)


def codes(issues: List[Issue]) -> set:
    return {i.issue_code for i in issues}


# ============================================================ 证据匹配


def test_exact_quote_is_grounded():
    assert similarity("华中科技大学  计算机科学与技术  本科", RESUME_TEXT) == 1.0


def test_whitespace_and_punctuation_differences_are_tolerated():
    """模型引用时吞空格、把全角标点写成半角，是排版差异不是编造。"""
    assert is_grounded("华中科技大学 计算机科学与技术 本科", RESUME_TEXT)
    assert is_grounded("准确率从 61% 提升到 84%。", RESUME_TEXT)
    assert is_grounded("准确率从61%提升到84%.", RESUME_TEXT)


def test_fabricated_quote_is_rejected():
    """编造的引用必须抓住，否则整套归因校验就是摆设。"""
    assert not is_grounded("曾在字节跳动担任算法工程师，负责推荐系统", RESUME_TEXT)
    assert not is_grounded("准确率从 61% 提升到 99%，并获得国家级奖项", RESUME_TEXT)


def test_short_spans_are_flagged():
    """「Python」这种词在任何简历里都能匹配上，不具备归因意义。"""
    assert is_too_short("Python")
    assert not is_too_short("熟悉 Python，掌握 pandas")


def test_text_similarity_detects_near_duplicate_questions():
    a = "你提到准确率从 61% 提升到 84%，这个提升主要来自哪一处改动？"
    b = "你提到准确率从 61% 提升到 84%，这个提升主要来自哪些改动？"
    assert text_similarity(a, b) > 0.9
    assert text_similarity(a, "请介绍一下你对 RAG 的理解") < 0.5


# ============================================================ 日期解析


@pytest.mark.parametrize(
    "raw,expected",
    [("2022.09", (2022, 9)), ("2022-9", (2022, 9)), ("2022/09", (2022, 9)),
     ("2022年9月", (2022, 9)), ("2022", (2022, 1)), ("至今", (9999, 12)),
     ("不详", None), ("", None), (None, None)],
)
def test_parse_ym(raw, expected):
    assert parse_ym(raw) == expected


# ============================================================ 简历规则


def test_empty_extraction_is_blocker(doc):
    report, gate = check_resume(ExtractedResume(resume_id="r1"), doc)
    assert "EXT_EMPTY_RESULT" in codes(report.issues)
    assert gate.status == "FAIL"


def test_grounded_resume_passes(doc):
    resume = ExtractedResume(
        resume_id="r1",
        candidate_name="李明",
        educations=[Education(school="华中科技大学", degree="本科",
                              evidence=[span("华中科技大学  计算机科学与技术  本科")])],
        skills=[Skill(name="Python", evidence=[span("熟悉 Python，掌握 pandas、FastAPI")])],
    )
    report, gate = check_resume(resume, doc)
    assert report.issues == []
    assert gate.status == "PASS"


def test_fabricated_evidence_is_caught(doc):
    resume = ExtractedResume(
        resume_id="r1",
        candidate_name="李明",
        educations=[Education(school="清华大学",
                              evidence=[span("清华大学 软件工程 硕士，导师为图灵奖得主")])],
    )
    report, gate = check_resume(resume, doc)
    assert "EXT_SPAN_NOT_FOUND" in codes(report.issues)
    assert gate.status == "FAIL"


def test_date_conflict_is_caught(doc):
    resume = ExtractedResume(
        resume_id="r1", candidate_name="李明",
        educations=[Education(school="华中科技大学", start="2026.06", end="2022.09")],
    )
    report, _ = check_resume(resume, doc)
    assert "EXT_DATE_CONFLICT" in codes(report.issues)


def test_missing_name_is_only_minor(doc):
    """姓名缺失是瑕疵不是灾难，不该拦住整条流水线。"""
    resume = ExtractedResume(resume_id="r1", skills=[Skill(name="Python")])
    report, gate = check_resume(resume, doc)
    assert "EXT_FIELD_MISSING" in codes(report.issues)
    assert gate.status == "PASS"


# ============================================================ 匹配规则


def make_jd() -> JD:
    return JD(jd_id="J1", title="AI 产品实习生", raw_text="...", requirements=[
        Requirement(requirement_id="R1", text="本科及以上学历", weight=5),
        Requirement(requirement_id="R2", text="熟悉 Python", weight=5),
    ])


def make_match(verdicts, total=None, jd=None) -> MatchResult:
    from agents.scorer import build_match_result
    result = build_match_result(jd or make_jd(), "r1", verdicts)
    if total is not None:                 # 刻意制造不一致，测试算术校验
        result = result.model_copy(update={"total_score": total})
    return result


def v(rid, satisfied, score, ev=None):
    return RequirementVerdict(requirement_id=rid, satisfied=satisfied, score=score,
                              reason="r", evidence=ev or [])


def test_missing_verdict_is_blocker(doc):
    report, gate = check_match(make_jd(), make_match([v("R1", "YES", 90, [span("华中科技大学  计算机科学与技术  本科")])]), doc)
    assert "MATCH_VERDICT_MISSING" in codes(report.issues)
    assert gate.status == "FAIL"


def test_unknown_requirement_id_is_caught(doc):
    verdicts = [v("R1", "NO", 0), v("R2", "NO", 0), v("R9", "YES", 90, [span("熟悉 Python，掌握 pandas、FastAPI")])]
    report, _ = check_match(make_jd(), make_match(verdicts), doc)
    assert "MATCH_VERDICT_UNKNOWN_ID" in codes(report.issues)


def test_score_inconsistent_with_satisfied_is_caught(doc):
    """说「不满足」却给 80 分，是模型自相矛盾的信号。"""
    verdicts = [v("R1", "NO", 80), v("R2", "NO", 0)]
    report, _ = check_match(make_jd(), make_match(verdicts), doc)
    assert "MATCH_SCORE_SATISFIED_MISMATCH" in codes(report.issues)


def test_tampered_total_score_is_caught(doc):
    """总分被改成算不出来的值 -> 立刻报 blocker。

    这条是防线：只要哪次改动让 LLM 碰了总分，这里必红。
    """
    verdicts = [v("R1", "NO", 0), v("R2", "NO", 0)]
    report, gate = check_match(make_jd(), make_match(verdicts, total=99.0), doc)
    assert "MATCH_ARITHMETIC_MISMATCH" in codes(report.issues)
    assert gate.status == "FAIL"


def test_positive_verdict_without_evidence_is_blocker(doc):
    verdicts = [v("R1", "YES", 90), v("R2", "NO", 0)]
    report, _ = check_match(make_jd(), make_match(verdicts), doc)
    assert "MATCH_EVIDENCE_EMPTY" in codes(report.issues)


def test_negative_verdict_needs_no_evidence(doc):
    """判 NO 不要求出处 —— 不存在的东西没有原文可引。"""
    verdicts = [v("R1", "NO", 0), v("R2", "NO", 0)]
    report, _ = check_match(make_jd(), make_match(verdicts), doc)
    assert "MATCH_EVIDENCE_EMPTY" not in codes(report.issues)


# ============================================================ 题目规则


def q(qid, text, rubric=2, ev=None):
    return QuestionFull(
        question_id=qid, text=text, skill_point="sp", difficulty="MEDIUM",
        rubric=[RubricLevel(level=f"L{i}", min_score=60, criteria="c") for i in range(rubric)],
        evidence=ev or [],
    )


def test_question_count_below_minimum_is_blocker(doc):
    qs = QuestionSet(resume_id="r1", jd_id="J1", questions=[q("Q1", "题目一")])
    report, gate = check_question_set(qs, doc)
    assert "Q_COUNT_LT_MIN" in codes(report.issues)
    assert gate.status == "FAIL"


def test_duplicate_questions_are_caught(doc):
    qs = QuestionSet(resume_id="r1", jd_id="J1", questions=[
        q("Q1", "你提到准确率从 61% 提升到 84%，这个提升主要来自哪一处改动？"),
        q("Q2", "你提到准确率从 61% 提升到 84%，这个提升主要来自哪些改动？"),
    ])
    report, _ = check_question_set(qs, doc)
    assert "Q_DUPLICATE" in codes(report.issues)


def test_question_without_rubric_is_major(doc):
    qs = QuestionSet(resume_id="r1", jd_id="J1", questions=[q("Q1", "题目一", rubric=1)])
    report, _ = check_question_set(qs, doc)
    assert "Q_RUBRIC_MISSING" in codes(report.issues)


# ============================================================ 追问规则


def test_followup_count_out_of_range(doc):
    fs = FollowUpSet(resume_id="D1",
                     ambiguity_points=[AmbiguityPoint(point_id="P1", description="d")],
                     questions=[FollowUpQuestion(followup_id="F1", text="t",
                                                 ambiguity_point_id="P1", intent="i")])
    report, _ = check_followups(fs, doc)
    assert "FU_COUNT_OUT_OF_RANGE" in codes(report.issues)


def test_followup_referencing_unknown_point(doc):
    fs = FollowUpSet(resume_id="D1", ambiguity_points=[],
                     questions=[FollowUpQuestion(followup_id=f"F{i}", text="t",
                                                 ambiguity_point_id="P9", intent="i")
                                for i in range(3)])
    report, _ = check_followups(fs, doc)
    assert "FU_DANGLING_POINT_REF" in codes(report.issues)


# ============================================================ 注册表机制


def test_new_rule_runs_without_touching_dispatch_code():
    """注册表的全部意义：加规则不用改调度代码。这条测的是那个设计承诺。"""
    from checker.base import _REGISTRY
    before = len(registered_rules("resume"))

    @register("resume")
    def _temp_rule(ctx):
        return [Issue(issue_code="TEMP", severity="minor", detector="rule",
                      dimension="格式与约束", message="临时规则")]

    try:
        assert len(registered_rules("resume")) == before + 1
        ctx = RuleContext(thresholds=get_thresholds())
        report = run_rules("resume", "r1", ctx)
        assert "TEMP" in codes(report.issues)
    finally:
        _REGISTRY["resume"].remove(_temp_rule)
    assert len(registered_rules("resume")) == before


def test_crashing_rule_does_not_abort_the_whole_check():
    """一条规则的边角 bug 不该拖垮整轮校验。"""
    from checker.base import _REGISTRY

    @register("resume")
    def _boom(ctx):
        raise RuntimeError("故意炸")

    try:
        ctx = RuleContext(thresholds=get_thresholds())
        report = run_rules("resume", "r1", ctx)
        assert "RULE_CRASHED" in codes(report.issues)
        assert all(i.severity == "minor" for i in report.issues if i.issue_code == "RULE_CRASHED")
    finally:
        _REGISTRY["resume"].remove(_boom)
