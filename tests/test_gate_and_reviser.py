"""放行判定与修订闭环。

gate 的判定顺序是有讲究的：熔断必须排在 FAIL 前面，
否则「修不好的东西」会永远 FAIL 下去 —— 正是要避免的死循环。
"""

from __future__ import annotations

import json
from typing import List

import pytest

from agents.reviser import revise
from checker.gate import evaluate_gate
from harness.llm_client import LLMResponse
from schema.issue import CheckReport, Issue
from schema.jd import JD, Requirement
from schema.match import MatchResult, RequirementVerdict
from schema.resume import Education, ExtractedResume

T = {"gate": {"max_major": 3, "max_rounds": 2}}


def issue(severity: str, code: str = "X") -> Issue:
    return Issue(issue_code=code, severity=severity, detector="rule",
                 dimension="数据准确性", message="m")


def report(*severities: str, round_no: int = 0) -> CheckReport:
    return CheckReport(target_type="resume", target_id="r1", round_no=round_no,
                       issues=[issue(s) for s in severities])


# ============================================================ gate


def test_clean_report_passes():
    assert evaluate_gate(report(), thresholds=T).status == "PASS"


def test_minor_only_still_passes():
    g = evaluate_gate(report("minor", "minor"), thresholds=T)
    assert g.status == "PASS" and g.passed


def test_one_or_two_majors_conditionally_pass():
    g = evaluate_gate(report("major", "major"), thresholds=T)
    assert g.status == "CONDITIONAL_PASS" and g.passed


def test_three_majors_fail():
    g = evaluate_gate(report("major", "major", "major"), thresholds=T)
    assert g.status == "FAIL" and not g.passed


def test_any_blocker_fails():
    assert evaluate_gate(report("blocker"), thresholds=T).status == "FAIL"


def test_circuit_breaker_takes_precedence_over_fail():
    """修够轮数仍有 blocker -> 转人工，而不是继续 FAIL。

    顺序写反的话，这个用例会拿到 FAIL，流水线就会一直修下去。
    """
    g = evaluate_gate(report("blocker", round_no=2), thresholds=T)
    assert g.status == "NEEDS_HUMAN_REVIEW"
    assert "转人工" in g.reason


def test_circuit_breaker_not_triggered_before_limit():
    assert evaluate_gate(report("blocker", round_no=1), thresholds=T).status == "FAIL"


def test_majors_alone_never_trigger_human_review():
    """熔断只为 blocker 保留 —— major 再多也是 FAIL，让它继续修。"""
    g = evaluate_gate(report("major", "major", "major", round_no=5), thresholds=T)
    assert g.status == "FAIL"


def test_counts_are_reported():
    g = evaluate_gate(report("blocker", "major", "minor", "minor"), thresholds=T)
    assert (g.blocker_count, g.major_count, g.minor_count) == (1, 1, 2)


# ============================================================ reviser


class ScriptedClient:
    provider = "scripted"

    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload, ensure_ascii=False)
        self.calls: List[str] = []

    def complete(self, system, user, model, json_schema=None):
        self.calls.append(user)
        return LLMResponse(text=self.payload, model="scripted", provider="scripted")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    monkeypatch.setattr(s, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    def _wire(payload):
        client = ScriptedClient(payload)
        monkeypatch.setattr(structured, "get_client", lambda _s: client)
        return client

    return _wire


def test_reviser_refuses_match_result():
    """MatchResult 里有 total_score 和 recommendation，交给模型重写等于让它改分数。"""
    jd = JD(jd_id="J1", title="t", raw_text="...",
            requirements=[Requirement(requirement_id="R1", text="学历", weight=1)])
    from agents.scorer import build_match_result
    result = build_match_result(
        jd, "r1", [RequirementVerdict(requirement_id="R1", satisfied="YES", score=90, reason="r")]
    )
    with pytest.raises(ValueError) as exc:
        revise(result, [issue("blocker")])
    assert "MatchResult" in str(exc.value) and "scorer" in str(exc.value)


def test_reviser_returns_unchanged_when_no_issues(wired):
    client = wired({})
    original = ExtractedResume(resume_id="r1", candidate_name="李明")
    revised, notes = revise(original, [])
    assert revised is original and notes == []
    assert client.calls == []          # 没问题就不该产生调用


def test_reviser_applies_fix_and_records_notes(wired):
    """修订后的对象直接受目标 schema 约束，模型改坏结构会被 pydantic 拦下。"""
    wired({
        "revised": {
            "resume_id": "r1", "candidate_name": "李明",
            "educations": [{"school": "华中科技大学", "degree": "本科", "evidence": []}],
            "work_experiences": [], "projects": [], "skills": [],
        },
        "notes": [
            {"issue_code": "EXT_SPAN_NOT_FOUND", "action": "FIXED", "detail": "删除了无据的出处"},
            {"issue_code": "EXT_FIELD_MISSING", "action": "DISPUTED", "detail": "原文确实没有写"},
        ],
    })
    original = ExtractedResume(
        resume_id="r1",
        educations=[Education(school="清华大学")],
    )
    revised, notes = revise(original, [issue("blocker", "EXT_SPAN_NOT_FOUND")], source_text="原文")

    assert isinstance(revised, ExtractedResume)
    assert revised.educations[0].school == "华中科技大学"
    assert revised.candidate_name == "李明"
    assert [n.action for n in notes] == ["FIXED", "DISPUTED"]


def test_reviser_prompt_carries_issue_details(wired):
    """回灌的必须是具体问题，不是笼统一句「有错，请修改」。"""
    client = wired({"revised": {"resume_id": "r1"}, "notes": []})
    revise(
        ExtractedResume(resume_id="r1"),
        [Issue(issue_code="EXT_DATE_CONFLICT", severity="major", detector="rule",
               dimension="数据准确性", message="起止时间矛盾：2026.06 晚于 2022.09",
               target_path="educations[0]", suggestion="核对原文中的时间")],
        source_text="教育背景 2022.09 - 2026.06",
    )
    sent = client.calls[0]
    assert "EXT_DATE_CONFLICT" in sent
    assert "起止时间矛盾" in sent
    assert "educations[0]" in sent
    assert "教育背景 2022.09 - 2026.06" in sent
