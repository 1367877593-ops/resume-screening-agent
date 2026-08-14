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
    assert all(stage["gate"]["status"] == "PASS" for stage in advanced["stages"])
    question_stage = next(stage for stage in advanced["stages"] if stage["stage"] == "question_set")
    assert question_stage["rounds_used"] == 1
    assert question_stage["notes"][0]["issue_code"] == "Q_COUNT_LT_MIN"
    assert rejected["questions"] is None and rejected["followups"] is None
    assert not (tmp_path / "runtime-cache").exists()
