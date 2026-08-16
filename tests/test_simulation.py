"""三人格盲评模拟（L2）。

重点覆盖三件事：
1. 防泄题的信息隔离是否真的由类型保证；
2. 盲评的标签映射是否确定且能正确还原人格；
3. 三分对照真值表在各档边界上的判定。
"""

from __future__ import annotations

import json
from typing import List

import pytest

from checker.base import RuleContext
from checker.rules.content_rules import rule_simulation_flags_weak_questions
from checker.simulation.diagnose import diagnose
from checker.simulation.grader import _bundles, grade_blind, label_map
from checker.simulation.personas import _render, answer_as_bluffer
from config.settings import get_thresholds
from harness.llm_client import LLMResponse
from schema.jd import JD, Requirement
from schema.question import QuestionFull, QuestionSet, RubricLevel
from schema.simulation import SimAnswer, SimScore

T = get_thresholds()
SECRET = "能说清取舍与代价才算优秀"


def _question(qid: str, text: str = "请说明你在检索项目中的具体取舍。") -> QuestionFull:
    return QuestionFull(
        question_id=qid,
        text=text,
        skill_point="效果归因",
        difficulty="MEDIUM",
        rubric=[
            RubricLevel(level="优秀", min_score=85, criteria=SECRET),
            RubricLevel(level="合格", min_score=60, criteria="能复述做法"),
        ],
        source_requirement_ids=["R1"],
    )


def _question_set(n: int = 3) -> QuestionSet:
    return QuestionSet(
        resume_id="r1", jd_id="j1",
        questions=[_question(f"Q{i}", f"第 {i} 题：请说明具体取舍。") for i in range(1, n + 1)],
    )


def _scores(qid: str, expert: float, bluffer: float, resume: float) -> List[SimScore]:
    return [
        SimScore(question_id=qid, persona="expert", score=expert),
        SimScore(question_id=qid, persona="bluffer", score=bluffer),
        SimScore(question_id=qid, persona="resume", score=resume),
    ]


class _NullTracer:
    def record(self, **fields):
        pass


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """把缓存和 trace 指向临时目录，并关掉缓存。

    不关缓存的话，断言「模型收到了什么」的测试会在全量跑时命中上一个测试
    写下的条目，client 根本不被调用 —— 这类失败很难一眼看出原因。
    """
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_enabled", False, raising=False)
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    monkeypatch.setattr(s, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", _NullTracer(), raising=False)
    return s


# ============================================================ 信息隔离


def test_public_question_carries_no_rubric():
    """防泄题的第一道防线：QuestionPublic 里根本没有 rubric 字段。"""
    public = _question("Q1").to_public()

    assert set(public.model_dump()) == {"question_id", "text"}
    assert SECRET not in json.dumps(public.model_dump(), ensure_ascii=False)


def test_persona_prompt_cannot_contain_the_rubric():
    """人格看到的题目序列化结果里不能出现评分标准。

    这条断言其实是在守护 `_render` 的实现 —— 哪天有人把它改成接收
    QuestionFull，这里会立刻红。
    """
    rendered = _render(_question_set(3).to_public())

    assert SECRET not in rendered
    assert "rubric" not in rendered
    assert "skill_point" not in rendered


def test_bluffer_never_receives_resume_or_jd(monkeypatch, isolated):
    """背题党连 JD 都拿不到 —— 这正是他与专家的差别所在。"""
    captured = {}

    class Client:
        provider = "fake"

        def complete(self, system, user, model, json_schema=None):
            captured["user"] = user
            return LLMResponse(
                text=json.dumps({"answers": [{"question_id": "Q1", "answer": "套话"}]}),
                model="fake", provider="fake",
            )

    from harness import structured

    monkeypatch.setattr(structured, "get_client", lambda _s: Client())

    answers = answer_as_bluffer(_question_set(1).to_public())

    assert answers[0].persona == "bluffer"
    assert SECRET not in captured["user"]


# ============================================================ 盲评


def test_label_map_is_deterministic_but_differs_across_questions():
    """确定性：否则缓存键每次都变，make demo 的回放永远命中不了。
    按题不同：否则模型能从前几题推断出 A 一直是谁。
    """
    personas = sorted(["expert", "bluffer", "resume"])
    first = label_map("Q1", personas)

    assert first == label_map("Q1", personas)          # 同一道题恒定
    assert set(first.values()) == set(personas)        # 三个人格都在

    maps = {tuple(label_map(f"Q{i}", personas).items()) for i in range(1, 11)}
    assert len(maps) > 1, "十道题用了同一个映射，盲评形同虚设"


def test_bundles_hide_persona_and_expose_rubric_only_to_grader():
    answers = [
        SimAnswer(question_id="Q1", persona="expert", answer="专家答案"),
        SimAnswer(question_id="Q1", persona="bluffer", answer="八股答案"),
        SimAnswer(question_id="Q1", persona="resume", answer="简历答案"),
    ]
    bundles, reverse = _bundles([_question("Q1")], answers)

    payload = json.dumps(bundles, ensure_ascii=False)
    assert "expert" not in payload and "bluffer" not in payload
    assert SECRET in payload, "阅卷官必须看得到评分标准，否则没法按档打分"
    assert set(reverse["Q1"]) == {"A", "B", "C"}


def test_grade_blind_maps_labels_back_to_the_right_persona(monkeypatch, isolated):
    answers = [
        SimAnswer(question_id="Q1", persona="expert", answer="专家答案"),
        SimAnswer(question_id="Q1", persona="bluffer", answer="八股答案"),
        SimAnswer(question_id="Q1", persona="resume", answer="简历答案"),
    ]
    mapping = label_map("Q1", sorted(["expert", "bluffer", "resume"]))
    want = {"expert": 90.0, "bluffer": 20.0, "resume": 70.0}

    class Client:
        provider = "fake"

        def complete(self, system, user, model, json_schema=None):
            return LLMResponse(
                text=json.dumps({"scores": [
                    {"question_id": "Q1", "label": label, "score": want[persona], "reason": ""}
                    for label, persona in mapping.items()
                ]}),
                model="fake", provider="fake",
            )

    from harness import structured

    monkeypatch.setattr(structured, "get_client", lambda _s: Client())

    got = {s.persona: s.score for s in grade_blind([_question("Q1")], answers)}
    assert got == want


def test_grade_blind_drops_unknown_labels(monkeypatch, isolated):
    """标签对不上宁可丢分数，也不能记到错误的人格头上 —— 那会让结论反向。"""

    class Client:
        provider = "fake"

        def complete(self, system, user, model, json_schema=None):
            return LLMResponse(
                text=json.dumps({"scores": [
                    {"question_id": "Q1", "label": "D", "score": 90, "reason": ""},
                ]}),
                model="fake", provider="fake",
            )

    from harness import structured

    monkeypatch.setattr(structured, "get_client", lambda _s: Client())

    answers = [SimAnswer(question_id="Q1", persona="expert", answer="a")]
    assert grade_blind([_question("Q1")], answers) == []


# ============================================================ 三分对照真值表


@pytest.mark.parametrize(
    "expert, bluffer, resume, expected",
    [
        (90, 20, 80, "GOOD"),              # 专家高、背题党低、候选人答得上
        (90, 80, 80, "NO_DISCRIMINATION"), # 背题党也能答
        (90, 20, 30, "OUT_OF_RANGE"),      # 有区分度但超出简历射程
        (40, 10, 10, "BROKEN"),            # 专家都答不出
        (40, 90, 90, "BROKEN"),            # 专家答不出时优先判坏题，不看其它两档
    ],
)
def test_truth_table(expert, bluffer, resume, expected):
    got = diagnose(_scores("Q1", expert, bluffer, resume), T)
    assert [d.diagnosis for d in got] == [expected]


def test_boundaries_are_inclusive_on_the_pass_side():
    """恰好等于阈值算通过。写死在测试里，免得日后有人顺手把 >= 改成 >。"""
    t = T["simulation"]
    got = diagnose(
        _scores("Q1", t["expert_pass"], t["bluffer_max"], t["resume_pass"]), T
    )
    assert got[0].diagnosis == "GOOD"


def test_incomplete_scores_produce_no_diagnosis():
    """缺一个人格的分数就不出诊断 —— 补 0 会把题误判成 BROKEN。"""
    partial = [
        SimScore(question_id="Q1", persona="expert", score=90),
        SimScore(question_id="Q1", persona="bluffer", score=20),
    ]
    assert diagnose(partial, T) == []


# ============================================================ 落成 Issue


def test_diagnoses_become_sim_issues_with_expected_severity():
    from schema.simulation import SimulationReport

    scores = (
        _scores("Q1", 90, 20, 80)    # GOOD -> 不产生 issue
        + _scores("Q2", 90, 80, 80)  # NO_DISCRIMINATION -> major
        + _scores("Q3", 40, 10, 10)  # BROKEN -> major
        + _scores("Q4", 90, 20, 30)  # OUT_OF_RANGE -> minor
    )
    report = SimulationReport(resume_id="r1", diagnoses=diagnose(scores, T))
    issues = rule_simulation_flags_weak_questions(
        RuleContext(thresholds=T, simulation=report)
    )

    assert {i.issue_code: i.severity for i in issues} == {
        "Q_NO_DISCRIMINATION": "major",
        "Q_UNANSWERABLE": "major",
        "Q_OUT_OF_RANGE": "minor",
    }
    assert all(i.detector == "sim" for i in issues)
    assert all(i.dimension == "题目质量" for i in issues)


def test_rule_is_inert_without_simulation():
    """模拟是可选增强。关掉它，规则表照常工作，L1 闭环不受影响。"""
    assert rule_simulation_flags_weak_questions(RuleContext(thresholds=T)) == []


# ============================================================ 与编排的衔接


def test_blocker_skips_simulation_entirely(monkeypatch, isolated):
    """数量不足这类 blocker 出现时不该盲评：这套题马上要被重写，模拟纯属烧钱。"""
    from harness import structured
    from pipeline.orchestrator import _question_checker
    from schema.document import RawDoc

    monkeypatch.setattr(isolated, "simulation_enabled", True, raising=False)
    monkeypatch.setattr(
        structured, "get_client",
        lambda _s: (_ for _ in ()).throw(AssertionError("不应为将被重写的题发起模拟调用")),
    )

    jd = JD(jd_id="j1", title="t", raw_text="岗位要求：熟悉 Python", requirements=[Requirement(
        requirement_id="R1", text="熟悉 Python", weight=5, is_hard=False, category="技能")])
    doc = RawDoc(doc_id="d1", filename="r.txt", full_text="简历原文")
    holder: dict = {"report": None}

    # 只有 3 道题，min_count=10 -> Q_COUNT_LT_MIN blocker
    report, gate = _question_checker(jd, doc, holder, None, None)(_question_set(3), 0)

    assert report.count("blocker") >= 1
    assert not gate.passed
    assert holder["report"] is None
