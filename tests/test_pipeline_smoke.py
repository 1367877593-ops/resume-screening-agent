"""端到端串联验证：JD 文本 -> 拆解 -> 提取 -> 匹配 -> 排序 -> 推进决策。

各模块单独跑通不代表串起来能跑。这里用脚本化的假响应（内容仿真实模型输出）
把 L1 的主干走一遍，确保接口拼得上、类型对得齐、决策落得下。
"""

from __future__ import annotations

import json
from typing import List

import pytest

from agents.extractor import extract_resume
from agents.jd_parser import parse_jd
from agents.matcher import match
from agents.scorer import rank
from config.settings import ROOT
from harness.llm_client import LLMResponse
from ingest.loader import load_file, load_text

SAMPLES = ROOT / "data" / "samples"

JD_PARSED = {
    "title": "AI 产品实习生",
    "requirements": [
        {"requirement_id": "R1", "text": "本科及以上学历", "weight": 8, "is_hard": True, "category": "学历"},
        {"requirement_id": "R2", "text": "熟悉 Python", "weight": 9, "is_hard": False, "category": "技能"},
        {"requirement_id": "R3", "text": "有 Prompt 工程实践经验", "weight": 8, "is_hard": False, "category": "经验"},
        {"requirement_id": "R4", "text": "每周到岗不少于 4 天", "weight": 5, "is_hard": True, "category": "其他"},
    ],
}

RESUME_A = {
    "resume_id": "x", "candidate_name": "李明",
    "educations": [{"school": "华中科技大学", "degree": "本科", "major": "计算机科学与技术",
                    "evidence": [{"doc_id": "D", "text": "华中科技大学  计算机科学与技术  本科"}]}],
    "work_experiences": [], "projects": [], "skills": [],
}

VERDICTS_A = {"verdicts": [
    {"requirement_id": "R1", "satisfied": "YES", "score": 100, "reason": "本科在读", "evidence": []},
    {"requirement_id": "R2", "satisfied": "YES", "score": 90, "reason": "多个项目使用 Python", "evidence": []},
    {"requirement_id": "R3", "satisfied": "YES", "score": 85, "reason": "设计过三版 Prompt", "evidence": []},
    {"requirement_id": "R4", "satisfied": "YES", "score": 100, "reason": "每周可到岗 5 天", "evidence": []},
]}

RESUME_B = {
    "resume_id": "y", "candidate_name": "王芳",
    "educations": [{"school": "某职业技术学院", "degree": "大专", "major": "市场营销", "evidence": []}],
    "work_experiences": [], "projects": [], "skills": [],
}

VERDICTS_B = {"verdicts": [
    {"requirement_id": "R1", "satisfied": "NO", "score": 0, "reason": "大专学历", "evidence": []},
    {"requirement_id": "R2", "satisfied": "NO", "score": 10, "reason": "未提及 Python", "evidence": []},
    {"requirement_id": "R3", "satisfied": "PARTIAL", "score": 40, "reason": "用过 ChatGPT 但非工程实践", "evidence": []},
    {"requirement_id": "R4", "satisfied": "NO", "score": 0, "reason": "每周仅 2 天", "evidence": []},
]}


class ScriptedClient:
    provider = "scripted"

    def __init__(self, script: List[dict]) -> None:
        self.script = [json.dumps(s, ensure_ascii=False) for s in script]
        self.calls = 0

    def complete(self, system, user, model, json_schema=None):
        self.calls += 1
        return LLMResponse(text=self.script.pop(0), model="scripted", provider="scripted")


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """把缓存与 trace 指向临时目录，并注入脚本化 client。"""
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    monkeypatch.setattr(s, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    def _wire(script):
        client = ScriptedClient(script)
        monkeypatch.setattr(structured, "get_client", lambda _s: client)
        return client

    return _wire


def test_ingest_reads_sample_files():
    jd_doc = load_file(SAMPLES / "jd.txt")
    assert "AI 产品实习生" in jd_doc.full_text
    assert jd_doc.chunks and jd_doc.chunks[0].doc_id == jd_doc.doc_id


def test_jd_can_be_pasted_as_plain_text():
    """JD 在页面上是个文本框，不走文件解析 —— 这条路径必须单独通。"""
    doc = load_text("岗位：AI 产品实习生\n\n要求：熟悉 Python", filename="jd-粘贴")
    assert "Python" in doc.full_text


def test_end_to_end_ranking_and_decision(wired):
    client = wired([JD_PARSED, RESUME_A, VERDICTS_A, RESUME_B, VERDICTS_B])

    jd_doc = load_file(SAMPLES / "jd.txt")
    jd = parse_jd(jd_doc)
    assert len(jd.requirements) == 4
    assert [r.requirement_id for r in jd.requirements if r.is_hard] == ["R1", "R4"]

    results = []
    for fname in ("resume_a.txt", "resume_b.txt"):
        doc = load_file(SAMPLES / fname)
        resume = extract_resume(doc)
        # resume_id 由代码指定，不用模型编的，避免多份简历撞号
        assert resume.resume_id == doc.doc_id
        results.append(match(jd, resume, doc))

    a, b = results
    assert a.candidate_name == "李明" and b.candidate_name == "王芳"

    # A 全项满足 -> 推进
    # 权重 8/9/8/5，得分 100/90/85/100 -> (800+810+680+500)/30 = 93.0
    assert a.total_score == pytest.approx(93.0)
    assert a.recommendation == "ADVANCE"
    assert a.hard_requirement_failed == []

    # B 两项硬性要求不满足 -> 一票否决，与总分无关
    assert b.recommendation == "REJECT"
    assert set(b.hard_requirement_failed) == {"本科及以上学历", "每周到岗不少于 4 天"}
    assert "硬性要求未满足" in b.recommendation_reason

    ranking = rank(jd.jd_id, results)
    assert [i.candidate_name for i in ranking.items] == ["李明", "王芳"]
    assert [c.candidate_name for c in ranking.advancing()] == ["李明"]

    assert client.calls == 5   # 1 次 JD + 2×(提取 + 匹配)


def test_second_run_hits_cache(wired):
    """同样的输入再跑一遍不应产生新的模型调用 —— 修订流程的增量重跑靠这个。"""
    client = wired([JD_PARSED, JD_PARSED])
    jd_doc = load_file(SAMPLES / "jd.txt")

    parse_jd(jd_doc)
    assert client.calls == 1
    parse_jd(jd_doc)
    assert client.calls == 1
