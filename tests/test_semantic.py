"""语义一致性校验（detector = "llm"）。

这一层是项目里唯一「用 LLM 验证 LLM」的地方，所以要测的重点不是「它能不能
发现问题」，而是**它有没有被约束住**：只在规则全过后才跑、不送检没证据的判定、
模型乱报编号时不照单全收、关掉之后主闭环照常。
"""

from __future__ import annotations

import json

import pytest

from checker.base import RuleContext
from checker.rules.content_rules import rule_semantic_contradictions
from checker.semantic import _payload, check_match_semantics
from config.settings import get_thresholds
from harness.llm_client import LLMResponse
from schema.document import SourceSpan
from schema.jd import JD, Requirement
from schema.match import RequirementVerdict
from schema.semantic import SemanticFinding, SemanticReport
from agents.scorer import build_match_result

T = get_thresholds()
QUOTE = "了解 Python 基础语法，完成过课程作业"


class _NullTracer:
    def record(self, **fields):
        pass


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_enabled", False, raising=False)
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    monkeypatch.setattr(s, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", _NullTracer(), raising=False)
    return s


def _jd() -> JD:
    return JD(
        jd_id="j1", title="AI 实习生", raw_text="要求：熟悉 Python；有向量库经验",
        requirements=[
            Requirement(requirement_id="R1", text="熟悉 Python", weight=5,
                        is_hard=False, category="技能"),
            Requirement(requirement_id="R2", text="有向量数据库经验", weight=3,
                        is_hard=False, category="技能"),
        ],
    )


def _match(with_evidence: bool = True):
    verdicts = [
        RequirementVerdict(
            requirement_id="R1", satisfied="YES", score=90, reason="精通 Python",
            evidence=[SourceSpan(doc_id="d1", text=QUOTE)] if with_evidence else [],
        ),
        RequirementVerdict(
            requirement_id="R2", satisfied="NO", score=0, reason="未提及", evidence=[],
        ),
    ]
    return build_match_result(_jd(), "r1", verdicts, candidate_name="某人")


class _Client:
    provider = "fake"

    def __init__(self, findings):
        self.findings = findings
        self.seen_user = None

    def complete(self, system, user, model, json_schema=None):
        self.seen_user = user
        return LLMResponse(
            text=json.dumps({"findings": self.findings}, ensure_ascii=False),
            model="fake", provider="fake",
        )


# ============================================================ 送检范围


def test_only_verdicts_with_evidence_are_sent():
    """没有证据的判定不送检 —— 归因规则已经拦过，再花一次 LLM 是浪费。"""
    text, checked = _payload(_jd(), _match())

    assert checked == 1
    rows = json.loads(text)
    assert [r["requirement_id"] for r in rows] == ["R1"]
    assert QUOTE in text


def test_no_call_at_all_when_nothing_has_evidence(monkeypatch, isolated):
    from harness import structured

    monkeypatch.setattr(
        structured, "get_client",
        lambda _s: (_ for _ in ()).throw(AssertionError("无证据可查时不应发起调用")),
    )

    report = check_match_semantics(_jd(), _match(with_evidence=False))

    assert report.checked == 0 and report.findings == []


# ============================================================ 结果处理


def test_contradiction_is_reported(monkeypatch, isolated):
    from harness import structured

    client = _Client([{
        "requirement_id": "R1",
        "explanation": "证据只说了解基础，判定却给精通",
        "quote": QUOTE,
    }])
    monkeypatch.setattr(structured, "get_client", lambda _s: client)

    report = check_match_semantics(_jd(), _match())

    assert report.checked == 1
    assert [f.requirement_id for f in report.findings] == ["R1"]
    # 送检内容里要带上判定与理由，否则模型无从对照
    assert "精通 Python" in client.seen_user


def test_unknown_requirement_id_is_dropped(monkeypatch, isolated):
    """模型报一个不存在的编号时丢弃。

    照单全收的话，Reviser 会被要求去改一条它根本找不到的判定 ——
    修不掉，然后一路耗到熔断。
    """
    from harness import structured

    monkeypatch.setattr(structured, "get_client", lambda _s: _Client([
        {"requirement_id": "R1", "explanation": "真实矛盾", "quote": QUOTE},
        {"requirement_id": "R99", "explanation": "编造的编号", "quote": ""},
    ]))

    report = check_match_semantics(_jd(), _match())

    assert [f.requirement_id for f in report.findings] == ["R1"]


def test_clean_result_is_not_an_error(monkeypatch, isolated):
    """零发现是常态。checked 字段用来区分「查了没问题」和「根本没查」。"""
    from harness import structured

    monkeypatch.setattr(structured, "get_client", lambda _s: _Client([]))

    report = check_match_semantics(_jd(), _match())

    assert report.findings == [] and report.checked == 1


# ============================================================ 落成 Issue


def test_findings_become_llm_issues():
    report = SemanticReport(target_id="r1", checked=2, findings=[
        SemanticFinding(requirement_id="R1", explanation="证据撑不起结论", quote=QUOTE),
    ])
    issues = rule_semantic_contradictions(RuleContext(thresholds=T, semantic=report))

    assert len(issues) == 1
    assert issues[0].issue_code == "SEM_REASON_CONTRADICTS_EVIDENCE"
    assert issues[0].detector == "llm"
    assert issues[0].severity == "major"
    assert issues[0].dimension == "语义一致性"
    assert issues[0].target_path == "verdicts[R1]"


def test_rule_is_inert_without_semantic_report():
    """语义校验是可选增强。关掉它，规则表照常工作。"""
    assert rule_semantic_contradictions(RuleContext(thresholds=T)) == []


# ============================================================ 与编排的衔接


def test_blocker_skips_semantic_check(monkeypatch, isolated):
    """确定性规则判出 blocker 时不做语义分析。

    这是项目核心主张「能用规则判的绝不调 LLM」的直接体现 ——
    那批判定马上要被重写，对它花一次 LLM 是纯浪费。
    """
    from harness import structured
    from pipeline.orchestrator import _match_checker
    from schema.document import RawDoc

    monkeypatch.setattr(isolated, "semantic_check_enabled", True, raising=False)
    monkeypatch.setattr(
        structured, "get_client",
        lambda _s: (_ for _ in ()).throw(AssertionError("出现 blocker 时不应做语义校验")),
    )

    jd = _jd()
    doc = RawDoc(doc_id="d1", filename="r.txt", full_text="简历原文与引用对不上")
    holder: dict = {"report": None}

    # 证据在原文中不存在 -> MATCH_EVIDENCE_INVALID（blocker）
    report, gate = _match_checker(jd, doc, holder, None)(_match(), 0)

    assert report.count("blocker") >= 1
    assert holder["report"] is None


def test_semantic_runs_once_rules_are_clean(monkeypatch, isolated):
    from harness import structured
    from pipeline.orchestrator import _match_checker
    from schema.document import RawDoc

    monkeypatch.setattr(isolated, "semantic_check_enabled", True, raising=False)
    monkeypatch.setattr(structured, "get_client", lambda _s: _Client([{
        "requirement_id": "R1", "explanation": "证据只说了解基础", "quote": QUOTE,
    }]))

    doc = RawDoc(doc_id="d1", filename="r.txt", full_text=f"技能\n{QUOTE}\n")
    holder: dict = {"report": None}
    report, gate = _match_checker(_jd(), doc, holder, None)(_match(), 0)

    assert holder["report"] is not None
    llm_issues = [i for i in report.issues if i.detector == "llm"]
    assert [i.issue_code for i in llm_issues] == ["SEM_REASON_CONTRADICTS_EVIDENCE"]
    # 一条 major -> CONDITIONAL_PASS：留痕交人工，不自动重写
    assert gate.status == "CONDITIONAL_PASS" and gate.passed


def test_disabled_switch_skips_the_call(monkeypatch, isolated):
    from harness import structured
    from pipeline.orchestrator import _match_checker
    from schema.document import RawDoc

    monkeypatch.setattr(isolated, "semantic_check_enabled", False, raising=False)
    monkeypatch.setattr(
        structured, "get_client",
        lambda _s: (_ for _ in ()).throw(AssertionError("开关关闭时不应发起调用")),
    )

    doc = RawDoc(doc_id="d1", filename="r.txt", full_text=f"技能\n{QUOTE}\n")
    holder: dict = {"report": None}
    report, gate = _match_checker(_jd(), doc, holder, None)(_match(), 0)

    assert holder["report"] is None
    assert not [i for i in report.issues if i.detector == "llm"]
