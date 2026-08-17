"""反思飞轮：把 Checker 的问题沉淀为经验，下次同岗位生成前注入。

这一层没有 LLM 调用，全部是确定性逻辑，所以测得比较硬。最关键的一条是
**注入内容必须稳定** —— 跑一百次得到的文本必须一模一样，否则缓存键不断漂移，
无 Key 回放就永远命中不了。
"""

from __future__ import annotations

import pytest

from flywheel.lessons import MAX_PER_JOB, load_all, record
from flywheel.retrieve import lessons_block, retrieve
from schema.issue import Issue
from schema.lesson import Lesson, normalize_job_kind, render_for_prompt


def _issue(code: str, detector: str = "rule") -> Issue:
    return Issue(
        issue_code=code, severity="major", detector=detector,
        dimension="格式与约束", message=f"{code} 发生了",
    )


STAGES = {
    "Q_COUNT_LT_MIN": "question_set",
    "Q_DUPLICATE": "question_set",
    "SEM_REASON_CONTRADICTS_EVIDENCE": "match",
}


# ============================================================ 归一化


@pytest.mark.parametrize("a, b", [
    ("AI 产品实习生（简历方向）", "AI产品实习生(简历方向)"),
    ("Data Analyst - Intern", "data_analyst_intern"),
    ("算法工程师 · 推荐", "算法工程师推荐"),
])
def test_job_kind_ignores_punctuation_and_case(a, b):
    """同一个岗位反复筛人时，标题的空格和括号常有出入，不该算成两个岗位。"""
    assert normalize_job_kind(a) == normalize_job_kind(b)


def test_different_jobs_do_not_collide():
    assert normalize_job_kind("AI 产品实习生") != normalize_job_kind("AI 算法实习生")


# ============================================================ 写入与合并


def test_same_issue_merges_and_counts_hits(tmp_path):
    """同一岗位下同一类问题合并成一条并累加，而不是每次运行堆一条新的。"""
    p = tmp_path / "lessons.jsonl"

    record("job-a", [_issue("Q_COUNT_LT_MIN")], STAGES, path=p)
    record("job-a", [_issue("Q_COUNT_LT_MIN")], STAGES, path=p)
    kept = record("job-a", [_issue("Q_COUNT_LT_MIN")], STAGES, path=p)

    assert len(kept) == 1
    assert kept[0].hits == 3
    assert kept[0].stage == "question_set"


def test_jobs_are_isolated_from_each_other(tmp_path):
    p = tmp_path / "lessons.jsonl"

    record("job-a", [_issue("Q_COUNT_LT_MIN")], STAGES, path=p)
    kept_b = record("job-b", [_issue("Q_DUPLICATE")], STAGES, path=p)

    assert [x.issue_code for x in kept_b] == ["Q_DUPLICATE"]
    assert len(load_all(p)) == 2, "两个岗位的经验都要留着，只是互不检索"


def test_issue_without_guidance_is_skipped(tmp_path):
    """没有可操作告诫的 issue_code 不入库。

    注入一句「上次出现了 RULE_CRASHED」，模型没法据此改进任何东西，
    只会占用注入预算。
    """
    p = tmp_path / "lessons.jsonl"

    kept = record("job-a", [_issue("RULE_CRASHED"), _issue("Q_DUPLICATE")], STAGES, path=p)

    assert [x.issue_code for x in kept] == ["Q_DUPLICATE"]


def test_capacity_is_capped_per_job(tmp_path, monkeypatch):
    """经验库不是日志。prompt 里塞五十条告诫，模型一条都不会认真看。

    告诫表用临时的合成条目：真实表有多少条是偶然的，随 issue_code 增删变化，
    容量控制本身不该因为那个数字恰好小于上限就测不到。
    """
    from flywheel import lessons as lessons_mod

    codes = [f"SYNTHETIC_{i:02d}" for i in range(MAX_PER_JOB + 3)]
    monkeypatch.setattr(
        lessons_mod, "_GUIDANCE", {c: f"合成告诫 {c}" for c in codes}, raising=True
    )

    p = tmp_path / "lessons.jsonl"
    kept = record("job-a", [_issue(c) for c in codes], {}, path=p)

    assert len(kept) == MAX_PER_JOB


def test_corrupt_line_does_not_break_the_library(tmp_path):
    """单条损坏不该让整个经验库不可用 —— 它只是增强，不是主干。"""
    p = tmp_path / "lessons.jsonl"
    record("job-a", [_issue("Q_DUPLICATE")], STAGES, path=p)
    p.write_text(p.read_text(encoding="utf-8") + "{ 这不是合法 JSON\n", encoding="utf-8")

    assert [x.issue_code for x in load_all(p)] == ["Q_DUPLICATE"]


def test_missing_file_is_not_an_error(tmp_path):
    assert load_all(tmp_path / "nope.jsonl") == []


# ============================================================ 检索与注入


def test_retrieve_filters_by_job_and_stage(tmp_path):
    p = tmp_path / "lessons.jsonl"
    record(normalize_job_kind("AI 实习生"),
           [_issue("Q_DUPLICATE"), _issue("SEM_REASON_CONTRADICTS_EVIDENCE")],
           STAGES, path=p)

    got = retrieve("AI 实习生", stage="question_set", path=p)

    assert [x.issue_code for x in got] == ["Q_DUPLICATE"]
    assert retrieve("另一个岗位", stage="question_set", path=p) == []


def test_first_run_says_so_explicitly(tmp_path):
    """空经验库要给一句明确的话，而不是留空 —— 空白会让 prompt 出现悬空小节。"""
    block = lessons_block("新岗位", stage="question_set", path=tmp_path / "none.jsonl")

    assert "第一次" in block


def test_injected_text_is_stable_regardless_of_hits(tmp_path):
    """注入内容不含命中次数与时间戳。

    这是整个飞轮里最要命的一条：带上 hits，每跑一次 prompt 就变一次，
    缓存键全部漂移，`make demo` 的回放会直接失效。
    """
    p = tmp_path / "lessons.jsonl"
    issues = [_issue("Q_COUNT_LT_MIN"), _issue("Q_DUPLICATE")]

    record("job-a", issues, STAGES, path=p)
    first = lessons_block("job-a", stage="question_set", path=p)
    for _ in range(5):
        record("job-a", issues, STAGES, path=p)
    later = lessons_block("job-a", stage="question_set", path=p)

    assert first == later
    assert max(x.hits for x in load_all(p)) == 6, "hits 确实在涨，只是没进 prompt"


def test_rendering_is_order_independent():
    """条目顺序变化不该改变注入文本 —— 同样是为了缓存键稳定。"""
    a = Lesson(lesson_id="1", job_kind="j", issue_code="A_CODE", stage="s", guidance="甲")
    b = Lesson(lesson_id="2", job_kind="j", issue_code="B_CODE", stage="s", guidance="乙")

    assert render_for_prompt([a, b]) == render_for_prompt([b, a])
