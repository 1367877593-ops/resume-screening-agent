"""存储门面 + L1 全流程集成 + UI 消费的数据结构。

最后一条是防回归的关键：视图层按固定的键名读字典，
序列化少一个键，界面就会在演示时当场 KeyError。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from harness.llm_client import LLMResponse
from ingest.loader import load_text
from pipeline import api
from store.repository import list_runs, load_run, save_run, top_candidates

RESUME_TEXT = (
    "李明\n\n教育背景\n2022.09 - 2026.06  华中科技大学  计算机科学与技术  本科\n\n"
    "项目经历\n基于 LangChain 与 Chroma 搭建检索问答系统，准确率从 61% 提升到 84%。\n\n"
    "技能\n熟悉 Python，掌握 pandas、FastAPI\n"
)
QUOTE_EDU = "华中科技大学  计算机科学与技术  本科"
QUOTE_SKILL = "熟悉 Python，掌握 pandas、FastAPI"
QUOTE_PROJ = "基于 LangChain 与 Chroma 搭建检索问答系统，准确率从 61% 提升到 84%。"

D = lambda t: {"doc_id": "D1", "text": t}  # noqa: E731


def _jd():
    return {"title": "AI 产品实习生", "requirements": [
        {"requirement_id": "R1", "text": "本科及以上学历", "weight": 6, "is_hard": True, "category": "学历"},
        {"requirement_id": "R2", "text": "熟悉 Python", "weight": 4, "is_hard": False, "category": "技能"},
    ]}


def _resume():
    return {
        "resume_id": "x", "candidate_name": "李明",
        "educations": [{"school": "华中科技大学", "degree": "本科", "evidence": [D(QUOTE_EDU)]}],
        "work_experiences": [], "projects": [], "skills": [
            {"name": "Python", "evidence": [D(QUOTE_SKILL)]}],
    }


def _verdicts():
    return {"verdicts": [
        {"requirement_id": "R1", "satisfied": "YES", "score": 95, "reason": "本科在读",
         "evidence": [D(QUOTE_EDU)]},
        {"requirement_id": "R2", "satisfied": "YES", "score": 85, "reason": "多处使用 Python",
         "evidence": [D(QUOTE_SKILL)]},
    ]}


def _questions(n: int = 10):
    topics = [
        ("需求分析", "你如何把模糊的业务需求拆成可验收的检索指标？"),
        ("数据治理", "项目中的知识文档如何清洗、切分并处理重复内容？"),
        ("检索设计", "为什么选择 Chroma，向量检索参数是怎样确定的？"),
        ("召回评估", "准确率从 61% 提升到 84% 时使用了什么评测集和计算口径？"),
        ("归因分析", "哪些改动真正贡献了准确率提升，如何排除数据波动的影响？"),
        ("失败诊断", "请举一个检索失败案例，并说明你如何定位到根因。"),
        ("接口工程", "如果用 FastAPI 暴露服务，你会怎样设计超时、重试与错误码？"),
        ("数据分析", "你如何使用 pandas 分析离线评测结果并发现薄弱问题类型？"),
        ("上线监控", "上线后你会监控哪些质量、延迟与成本指标？"),
        ("方案权衡", "如果延迟必须减半但准确率不能下降，你会优先调整哪些环节？"),
    ]
    return {"questions": [
        {
            "question_id": f"Q{i}",
            "text": topics[i - 1][1],
            "skill_point": topics[i - 1][0], "difficulty": "MEDIUM",
            "rubric": [
                {"level": "优秀", "min_score": 85, "criteria": "能说清取舍与代价"},
                {"level": "合格", "min_score": 60, "criteria": "能复述做法"},
            ],
            "source_requirement_ids": ["R2"], "evidence": [D(QUOTE_PROJ)],
        }
        for i in range(1, min(n, len(topics)) + 1)
    ]}


def _followups():
    return {
        "ambiguity_points": [
            {"point_id": "P1", "description": "准确率提升的归因不清", "evidence": [D(QUOTE_PROJ)]}],
        "questions": [
            {"followup_id": f"F{i}", "text": f"追问 {i}", "ambiguity_point_id": "P1",
             "intent": "确认归因"} for i in range(1, 4)
        ],
    }


class QueueClient:
    provider = "queued"

    def __init__(self, payloads: List[dict]) -> None:
        self.queue = [json.dumps(p, ensure_ascii=False) for p in payloads]
        self.calls = 0

    def complete(self, system, user, model, json_schema=None):
        self.calls += 1
        if not self.queue:
            raise AssertionError(f"脚本用尽，出现了第 {self.calls} 次预期外的调用")
        return LLMResponse(text=self.queue.pop(0), model="queued", provider="queued")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    monkeypatch.setattr(s, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(s, "db_path", tmp_path / "app.db", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    def _wire(payloads):
        client = QueueClient(payloads)
        monkeypatch.setattr(structured, "get_client", lambda _s: client)
        return client

    return _wire


# ============================================================ 存储


def test_save_and_load_roundtrip(tmp_path):
    payload = {"run_id": "run1", "jd": {"jd_id": "J1", "title": "AI 产品实习生"},
               "ranking": [{"rank": 1, "resume_id": "r1", "candidate_name": "李明",
                            "total_score": 91.0, "recommendation": "ADVANCE",
                            "gate_status": "PASS"}]}
    db = tmp_path / "t.db"
    assert save_run(payload, db_path=db) == "run1"
    assert load_run("run1", db_path=db)["jd"]["title"] == "AI 产品实习生"
    assert list_runs(db_path=db)[0]["n_candidates"] == 1


def test_resaving_same_run_does_not_duplicate_candidates(tmp_path):
    payload = {"run_id": "run1", "jd": {"jd_id": "J1", "title": "t"},
               "ranking": [{"rank": 1, "resume_id": "r1", "total_score": 80.0,
                            "recommendation": "ADVANCE"}]}
    db = tmp_path / "t.db"
    save_run(payload, db_path=db)
    save_run(payload, db_path=db)
    assert list_runs(db_path=db)[0]["n_candidates"] == 1


def test_top_candidates_excludes_rejected(tmp_path):
    db = tmp_path / "t.db"
    save_run({"run_id": "r", "jd": {"jd_id": "J", "title": "t"}, "ranking": [
        {"rank": 1, "resume_id": "a", "total_score": 90.0, "recommendation": "ADVANCE"},
        {"rank": 2, "resume_id": "b", "total_score": 95.0, "recommendation": "REJECT"},
    ]}, db_path=db)
    assert [c["resume_id"] for c in top_candidates(db_path=db)] == ["a"]


# ============================================================ 全流程


def test_full_l1_pipeline_and_payload_shape(wired):
    client = wired([_jd(), _resume(), _verdicts(), _questions(), _followups()])

    result = api.run("岗位：AI 产品实习生\n要求：本科、熟悉 Python", [("resume_a.txt", RESUME_TEXT.encode())])
    payload = api.result_to_dict(result, run_id="run1")

    assert client.calls == 5          # JD + 提取 + 匹配 + 出题 + 追问，无一次修订
    assert payload["ranking"][0]["recommendation"] == "ADVANCE"
    assert payload["ranking"][0]["gate_status"] == "PASS"

    cand = payload["candidates"][payload["ranking"][0]["resume_id"]]
    assert len(cand["questions"]["questions"]) == 10
    assert len(cand["followups"]["questions"]) == 3
    assert [s["stage"] for s in cand["stages"]] == ["extract", "match", "question_set", "followup"]
    assert all(s["gate"]["status"] == "PASS" for s in cand["stages"])


def test_payload_contains_every_key_the_views_read(wired):
    """视图按固定键名读字典，少一个键就会在演示时当场 KeyError。"""
    wired([_jd(), _resume(), _verdicts(), _questions(), _followups()])
    payload = api.result_to_dict(
        api.run("JD 文本", [("resume_a.txt", RESUME_TEXT.encode())])
    )

    assert {"run_id", "jd", "ranking", "candidates"} <= set(payload)
    assert {"jd_id", "title", "requirements"} <= set(payload["jd"])
    assert {"requirement_id", "text", "category", "weight", "is_hard"} <= set(
        payload["jd"]["requirements"][0])

    item = payload["ranking"][0]
    assert {"rank", "resume_id", "candidate_name", "total_score",
            "recommendation", "hard_requirement_failed", "gate_status"} <= set(item)

    cand = payload["candidates"][item["resume_id"]]
    assert {"resume", "resume_text", "filename", "match", "questions",
            "followups", "stages"} <= set(cand)
    assert {"total_score", "verdicts", "recommendation",
            "recommendation_reason"} <= set(cand["match"])
    assert {"requirement_id", "satisfied", "score", "reason", "evidence"} <= set(
        cand["match"]["verdicts"][0])
    assert {"question_id", "text", "skill_point", "difficulty", "rubric",
            "source_requirement_ids", "evidence"} <= set(cand["questions"]["questions"][0])
    assert {"followup_id", "text", "ambiguity_point_id", "intent"} <= set(
        cand["followups"]["questions"][0])
    assert {"stage", "rounds_used", "gate", "issues", "notes"} <= set(cand["stages"][0])


def test_rejected_candidate_gets_no_questions(wired):
    """被淘汰的不出题 —— 脚本里也就不需要出题的响应，用尽即报错可验证这一点。"""
    fail_verdicts = {"verdicts": [
        {"requirement_id": "R1", "satisfied": "NO", "score": 0, "reason": "大专", "evidence": []},
        {"requirement_id": "R2", "satisfied": "NO", "score": 5, "reason": "未提及", "evidence": []},
    ]}
    client = wired([_jd(), _resume(), fail_verdicts])

    result = api.run("JD", [("r.txt", RESUME_TEXT.encode())])
    payload = api.result_to_dict(result)

    assert client.calls == 3                       # 没有出题与追问的调用
    cand = payload["candidates"][payload["ranking"][0]["resume_id"]]
    assert payload["ranking"][0]["recommendation"] == "REJECT"
    assert cand["questions"] is None and cand["followups"] is None


def test_persist_writes_to_store(wired):
    wired([_jd(), _resume(), _verdicts(), _questions(), _followups()])
    result = api.run("JD", [("r.txt", RESUME_TEXT.encode())])

    run_id = api.persist(result)
    assert api.load(run_id)["jd"]["title"] == "AI 产品实习生"
    assert api.history()[0]["run_id"] == run_id
