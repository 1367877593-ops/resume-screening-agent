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
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
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

    # 三档决策各一位：只有「全 YES」和「全 NO」两个极端时，分档逻辑演示不出来
    assert [item["recommendation"] for item in payload["ranking"]] == [
        "ADVANCE", "HOLD", "REJECT"
    ]
    assert [item["candidate_name"] for item in payload["ranking"]] == ["李明", "陈涛", "王芳"]

    held = payload["candidates"][payload["ranking"][1]["resume_id"]]
    assert 60.0 <= payload["ranking"][1]["total_score"] < 75.0, "待定档必须落在阈值区间内"
    assert not payload["ranking"][1]["hard_requirement_failed"], "待定候选人不应有硬性项失败"
    assert held["questions"], "HOLD 同样要出题，只有 REJECT 才不出"
    assert any(v["satisfied"] == "PARTIAL" for v in held["match"]["verdicts"])

    advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]
    rejected = payload["candidates"][payload["ranking"][2]["resume_id"]]
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


def test_sample_input_preflight_distinguishes_custom_data():
    jd_text, resumes = api.sample_inputs()

    assert api.is_sample_input(jd_text, resumes)
    assert not api.is_sample_input(jd_text + "\n新增要求", resumes)
    assert not api.is_sample_input(jd_text, [("custom.txt", b"custom resume")])


def test_detected_issues_keep_the_fixed_ones_for_statistics(monkeypatch, tmp_path):
    """已修复的问题必须留在 detected_issues 里。

    「规则 vs LLM 检出占比」是 README 公开承诺的数字。如果只统计最终报告，
    第 0 轮被规则抓到、随后修好的那些会全部消失，占比会系统性地偏向 LLM，
    把这套校验说得比实际更不可信。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))
    advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]
    stage = next(s for s in advanced["stages"] if s["stage"] == "question_set")

    codes = {i["issue_code"] for i in stage["detected_issues"]}
    assert "Q_COUNT_LT_MIN" in codes, "第 0 轮被规则检出并修好的问题不能从统计里消失"
    # 修好之后最终报告里就不该再有它
    assert "Q_COUNT_LT_MIN" not in {i["issue_code"] for i in stage["issues"]}


def test_every_question_states_what_it_probes_and_why(monkeypatch, tmp_path):
    """每道题都必须交代考察点与出题原因。

    面试官是照着这两项决定要不要问的。缺任何一项，题目就只是一句话，
    无从判断该不该问、答成什么样算过关。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))

    for cand in payload["candidates"].values():
        if not cand["questions"]:
            continue
        for q in cand["questions"]["questions"]:
            assert q["skill_point"], f'{q["question_id"]} 缺考察点'
            assert q["rationale"], f'{q["question_id"]} 缺出题原因'


def test_history_and_cross_batch_query_are_reachable(monkeypatch, tmp_path):
    """能力表里写着「支持历史回看和跨批次排序查询」，就必须真的查得到。"""
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db", raising=False)
    monkeypatch.setattr(settings, "persist_runs", True, raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    run_id = api.persist(api.run(jd_text, resumes))

    runs = api.history()
    assert [r["run_id"] for r in runs] == [run_id]
    assert runs[0]["n_candidates"] == 3
    assert api.load(run_id)["jd"]["title"]

    # 跨批次查询排除被淘汰的人：王芳不应出现
    top = api.best_candidates()
    assert [c["candidate_name"] for c in top] == ["李明", "陈涛"]
    assert top[0]["total_score"] > top[1]["total_score"]


def test_demo_exercises_both_detectors(monkeypatch, tmp_path):
    """rule 与 llm 两种检出来源都要在内置样例里真的出现。

    「规则 vs LLM 检出占比」是 README 公开的数字。两档里有任何一档从未被
    触发过，这个占比就说明不了什么 —— 只能证明那条路径没写或没跑。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))

    detectors = {
        i["detector"]
        for c in payload["candidates"].values()
        for s in c["stages"]
        for i in s["detected_issues"]
    }
    assert detectors == {"rule", "llm"}


def test_semantic_check_catches_evidence_that_cannot_support_the_verdict(monkeypatch, tmp_path):
    """归因规则确认引用「存在」，语义校验确认引用「撑得起结论」。

    陈涛 R5 的理由声称有系统的多版迭代，而它引用的那句原文恰恰写着
    「没有做过多版对比或效果评估」—— 引用逐字存在，规则查不出来。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)

    jd_text, resumes = api.sample_inputs()
    payload = api.result_to_dict(api.run(jd_text, resumes))
    held = payload["candidates"][payload["ranking"][1]["resume_id"]]

    semantic = held["semantic"]
    assert semantic["checked"] > 0, "没有证据被送检，等于语义校验没跑"
    assert [f["requirement_id"] for f in semantic["findings"]] == ["R5"]

    stage = next(s for s in held["stages"] if s["stage"] == "match")
    llm_issues = [i for i in stage["issues"] if i["detector"] == "llm"]
    assert [i["issue_code"] for i in llm_issues] == ["SEM_REASON_CONTRADICTS_EVIDENCE"]
    # 一条 major -> 交人工过目，不自动重写：语义判断有误报可能
    assert stage["gate"]["status"] == "CONDITIONAL_PASS"
    assert stage["rounds_used"] == 0

    # 没有证据的判定不送检：王芳有 6 条 NO 且无证据
    rejected = payload["candidates"][payload["ranking"][2]["resume_id"]]
    assert rejected["semantic"]["checked"] < len(rejected["match"]["verdicts"])


def test_flywheel_prevents_the_same_mistake_on_the_second_run(monkeypatch, tmp_path):
    """飞轮的完成标志：连跑两次，第二次不再犯第一次犯过的错。

    第一次出题只给了 9 道，被数量规则打回、修订补齐。这条教训沉淀进经验库后，
    第二次运行的出题 prompt 会带上它 —— 于是一次给足，零轮修订。

    第三次运行同样必须命中缓存：经验集合不再变化（只有 hits 在涨，而 hits
    不进 prompt），注入文本因此稳定，缓存键不漂移。
    """
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_cache_dir", ROOT / "data" / "demo_cache", raising=False)
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "runtime-cache", raising=False)
    monkeypatch.setattr(settings, "lessons_path", tmp_path / "lessons.jsonl", raising=False)
    monkeypatch.setattr(settings, "trace_dir", tmp_path / "traces", raising=False)
    monkeypatch.setattr(structured, "_default_tracer", None, raising=False)
    monkeypatch.setattr(
        structured, "get_client",
        lambda _s: (_ for _ in ()).throw(AssertionError("Demo 不应初始化真实客户端")),
    )

    from flywheel import load_all

    jd_text, resumes = api.sample_inputs()

    def question_rounds():
        payload = api.result_to_dict(api.run(jd_text, resumes))
        advanced = payload["candidates"][payload["ranking"][0]["resume_id"]]
        stage = next(s for s in advanced["stages"] if s["stage"] == "question_set")
        return stage["rounds_used"], {i["issue_code"] for i in stage["detected_issues"]}

    first_rounds, first_codes = question_rounds()
    assert first_rounds == 1 and "Q_COUNT_LT_MIN" in first_codes

    second_rounds, second_codes = question_rounds()
    assert second_rounds == 0, "经验已沉淀，第二次不该再因题数不足被打回"
    assert "Q_COUNT_LT_MIN" not in second_codes

    # 第三次仍要命中缓存，否则注入文本不稳定
    third_rounds, _ = question_rounds()
    assert third_rounds == 0

    lessons = {x.issue_code: x for x in load_all(tmp_path / "lessons.jsonl")}
    assert "Q_COUNT_LT_MIN" in lessons
    # 只犯过一次：经验注入后第二、三轮都没再复发，这正是飞轮起作用的证据
    assert lessons["Q_COUNT_LT_MIN"].hits == 1
