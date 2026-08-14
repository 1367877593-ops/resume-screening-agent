"""修订闭环。阶段 4 的完成标志就是这几条能过。"""

from __future__ import annotations

import json
from typing import List

import pytest

from agents.scorer import build_match_result
from checker.run import check_match, check_resume
from harness.llm_client import LLMResponse
from pipeline.orchestrator import _revise_loop
from schema.document import RawDoc, SourceSpan
from schema.jd import JD, Requirement
from schema.match import MatchVerdicts, RequirementVerdict
from schema.resume import Education, ExtractedResume

RESUME_TEXT = (
    "李明\n\n教育背景\n2022.09 - 2026.06  华中科技大学  计算机科学与技术  本科\n\n"
    "技能\n熟悉 Python，掌握 pandas、FastAPI\n"
)
DOC = RawDoc(doc_id="D1", filename="r.txt", full_text=RESUME_TEXT)

REAL_QUOTE = "华中科技大学  计算机科学与技术  本科"
FAKE_QUOTE = "清华大学 软件工程 硕士，师从图灵奖得主，发表顶会论文十篇"


class QueueClient:
    provider = "queued"

    def __init__(self, payloads: List[dict]) -> None:
        self.queue = [json.dumps(p, ensure_ascii=False) for p in payloads]
        self.calls = 0

    def complete(self, system, user, model, json_schema=None):
        self.calls += 1
        text = self.queue.pop(0) if self.queue else "{}"
        return LLMResponse(text=text, model="queued", provider="queued")


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

    def _wire(payloads):
        client = QueueClient(payloads)
        monkeypatch.setattr(structured, "get_client", lambda _s: client)
        return client

    return _wire


def _resume(quote: str) -> ExtractedResume:
    return ExtractedResume(
        resume_id="D1", candidate_name="李明",
        educations=[Education(school="华中科技大学",
                              evidence=[SourceSpan(doc_id="D1", text=quote)])],
    )


def test_loop_converges_after_one_revision(wired):
    """编造的出处被抓到 -> 模型改成真实原文 -> 第二轮通过。"""
    client = wired([{
        "revised": _resume(REAL_QUOTE).model_dump(mode="json"),
        "notes": [{"issue_code": "EXT_SPAN_NOT_FOUND", "action": "FIXED",
                   "detail": "改为原文中真实存在的片段"}],
    }])

    obj, outcome = _revise_loop(
        _resume(FAKE_QUOTE),
        lambda o, r: check_resume(o, DOC, round_no=r),
        stage="extract", source_text=RESUME_TEXT, max_rounds=2,
    )

    assert outcome.rounds_used == 1
    assert outcome.gate.status == "PASS"
    assert obj.educations[0].evidence[0].text == REAL_QUOTE
    assert [n.action for n in outcome.notes] == ["FIXED"]
    assert client.calls == 1


def test_loop_stops_at_max_rounds_and_escalates(wired):
    """模型怎么修都修不好时必须熔断转人工，而不是无限循环。"""
    stubborn = {
        "revised": _resume(FAKE_QUOTE).model_dump(mode="json"),
        "notes": [{"issue_code": "EXT_SPAN_NOT_FOUND", "action": "DISPUTED",
                   "detail": "我认为原文就是这么写的"}],
    }
    client = wired([stubborn] * 5)

    _, outcome = _revise_loop(
        _resume(FAKE_QUOTE),
        lambda o, r: check_resume(o, DOC, round_no=r),
        stage="extract", source_text=RESUME_TEXT, max_rounds=2,
    )

    assert outcome.rounds_used == 2
    assert outcome.gate.status == "NEEDS_HUMAN_REVIEW"
    assert all(n.action == "DISPUTED" for n in outcome.notes)

    # 只打了 1 次模型：第二轮的修订请求与第一轮逐字相同（同一个对象、同一批问题），
    # 直接命中缓存。轮数上限保证循环终止，缓存保证不重复付费 —— 两层都要在。
    assert client.calls == 1


def test_clean_input_needs_no_revision(wired):
    client = wired([])
    _, outcome = _revise_loop(
        _resume(REAL_QUOTE),
        lambda o, r: check_resume(o, DOC, round_no=r),
        stage="extract", source_text=RESUME_TEXT, max_rounds=2,
    )
    assert outcome.rounds_used == 0 and outcome.gate.status == "PASS"
    assert client.calls == 0


def test_match_revision_recomputes_score_through_scorer(wired):
    """匹配环节修订的是判定，总分每轮由 scorer 重算 —— 模型碰不到分数。"""
    jd = JD(jd_id="J1", title="t", raw_text="...", requirements=[
        Requirement(requirement_id="R1", text="本科及以上学历", weight=5),
        Requirement(requirement_id="R2", text="熟悉 Python", weight=5),
    ])

    # 初版：R2 判 YES 却没给出处 -> MATCH_EVIDENCE_EMPTY（blocker）
    bad = MatchVerdicts(verdicts=[
        RequirementVerdict(requirement_id="R1", satisfied="YES", score=90, reason="本科",
                           evidence=[SourceSpan(doc_id="D1", text=REAL_QUOTE)]),
        RequirementVerdict(requirement_id="R2", satisfied="YES", score=80, reason="会 Python"),
    ])
    fixed = MatchVerdicts(verdicts=[
        RequirementVerdict(requirement_id="R1", satisfied="YES", score=90, reason="本科",
                           evidence=[SourceSpan(doc_id="D1", text=REAL_QUOTE)]),
        RequirementVerdict(requirement_id="R2", satisfied="YES", score=70, reason="会 Python",
                           evidence=[SourceSpan(doc_id="D1", text="熟悉 Python，掌握 pandas、FastAPI")]),
    ])
    wired([{"revised": fixed.model_dump(mode="json"),
            "notes": [{"issue_code": "MATCH_EVIDENCE_EMPTY", "action": "FIXED", "detail": "补上出处"}]}])

    result, outcome = _revise_loop(
        bad,
        lambda o, r: check_match(jd, o, DOC, round_no=r),
        stage="match", source_text=RESUME_TEXT, max_rounds=2,
        rebuild=lambda mv: build_match_result(jd, "D1", mv.verdicts, candidate_name="李明"),
    )

    assert outcome.gate.status == "PASS"
    # 修订后 R2 从 80 降到 70，总分必须跟着变 -> 证明重算走的是 scorer
    assert result.total_score == pytest.approx(80.0)   # (90 + 70) / 2
    assert result.recommendation == "ADVANCE"
    assert result.recommendation_reason.startswith("建议推进面试")
