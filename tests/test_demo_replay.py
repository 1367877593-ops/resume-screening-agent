"""无 Key Demo 的端到端回放测试。"""

from __future__ import annotations

from config.settings import ROOT, get_settings
from harness import structured
from pipeline import api


def test_bundled_demo_runs_full_l1_without_live_client(monkeypatch, tmp_path):
    """评审者机器即使配置了别的 provider/model，也应稳定命中内置回放。"""
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "llm_provider", "deepseek", raising=False)
    monkeypatch.setattr(settings, "llm_model", "a-model-not-used-by-demo", raising=False)
    monkeypatch.setattr(settings, "llm_api_key", "", raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)
    monkeypatch.setattr(
        structured,
        "get_client",
        lambda _settings: (_ for _ in ()).throw(AssertionError("Demo 不应初始化真实客户端")),
    )

    jd_text, resumes = api.sample_inputs()
    result = api.run(jd_text, resumes)
    payload = api.result_to_dict(result, run_id="demo-test")

    assert [item["recommendation"] for item in payload["ranking"]] == ["ADVANCE", "REJECT"]
    assert payload["ranking"][0]["candidate_name"] == "李明"
    assert payload["ranking"][1]["candidate_name"] == "王芳"

    advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]
    rejected = payload["candidates"][payload["ranking"][1]["resume_id"]]
    assert len(advanced["questions"]["questions"]) == 10
    assert len(advanced["followups"]["questions"]) == 3
    assert all(
        stage["gate"]["status"] in ("PASS", "CONDITIONAL_PASS")
        for stage in advanced["stages"]
    )

    # 首轮只生成 9 道题，被确定性数量规则打回，修订补齐后复检通过
    question_stage = next(stage for stage in advanced["stages"] if stage["stage"] == "question_set")
    assert question_stage["rounds_used"] == 1
    assert question_stage["notes"][0]["issue_code"] == "Q_COUNT_LT_MIN"
    assert rejected["questions"] is None and rejected["followups"] is None
    assert not (tmp_path / "runtime-cache").exists()


def test_bundled_demo_shows_persona_simulation_catching_a_weak_question(monkeypatch, tmp_path):
    """内置 Demo 必须展示三人格盲评抓出自己生成的弱题。

    Demo 刻意不做成一份完美结果：其中一道通用故障排查题背题党也能答好，
    盲评据此判为无区分度。评审者看到的是机制在工作，而不是一份摆拍的报告。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)
    monkeypatch.setattr(
        structured,
        "get_client",
        lambda _settings: (_ for _ in ()).throw(AssertionError("Demo 不应初始化真实客户端")),
    )

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))
    advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]

    simulation = advanced["simulation"]
    assert simulation is not None, "题目页的热力图依赖这个字段"
    assert len(simulation["diagnoses"]) == 10

    counts: dict = {}
    for d in simulation["diagnoses"]:
        counts[d["diagnosis"]] = counts.get(d["diagnosis"], 0) + 1
    assert counts["NO_DISCRIMINATION"] == 1
    assert counts["GOOD"] == 9

    weak = next(d for d in simulation["diagnoses"] if d["diagnosis"] == "NO_DISCRIMINATION")
    assert weak["bluffer_score"] > settings_thresholds()["simulation"]["bluffer_max"]

    # 诊断必须落成 detector=sim 的 Issue，否则 gate 看不到它
    question_stage = next(s for s in advanced["stages"] if s["stage"] == "question_set")
    sim_issues = [i for i in question_stage["issues"] if i["detector"] == "sim"]
    assert [i["issue_code"] for i in sim_issues] == ["Q_NO_DISCRIMINATION"]
    # 1 个 major -> CONDITIONAL_PASS：报告里留痕，但不阻断流程
    assert question_stage["gate"]["status"] == "CONDITIONAL_PASS"


def settings_thresholds() -> dict:
    from config.settings import get_thresholds

    return get_thresholds()


def test_sample_input_preflight_distinguishes_custom_data():
    jd_text, resumes = api.sample_inputs()

    assert api.is_sample_input(jd_text, resumes)
    assert not api.is_sample_input(jd_text + "\n新增要求", resumes)
    assert not api.is_sample_input(jd_text, [("custom.txt", b"custom resume")])


def test_detected_issues_keep_the_fixed_ones_for_statistics(monkeypatch, tmp_path):
    """已修复的问题必须留在 detected_issues 里。

    「规则 vs LLM 检出占比」是 README 公开承诺的数字。如果只统计最终报告，
    第 0 轮被规则抓到、随后修好的那些会全部消失，占比会系统性地偏向 LLM/sim，
    把这套校验说得比实际更不可信。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))
    advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]
    stage = next(s for s in advanced["stages"] if s["stage"] == "question_set")

    codes = {i["issue_code"] for i in stage["detected_issues"]}
    assert "Q_COUNT_LT_MIN" in codes, "第 0 轮被规则检出并修好的问题不能从统计里消失"
    assert "Q_NO_DISCRIMINATION" in codes
    # 最终报告里只剩没修的那条
    assert {i["issue_code"] for i in stage["issues"]} == {"Q_NO_DISCRIMINATION"}

    detectors = {i["detector"] for i in stage["detected_issues"]}
    assert detectors == {"rule", "sim"}
