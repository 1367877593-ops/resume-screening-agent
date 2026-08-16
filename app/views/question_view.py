"""题目与追问。被淘汰的候选人不出题，这里会明确说明原因。"""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from views._shared import candidate_picker, quote_block

DIFF = {"EASY": "🟢 简单", "MEDIUM": "🟡 中等", "HARD": "🔴 困难"}

# (字段, 列名, 阈值键, 分数高是否为好事)
#
# 背题党那一列的方向是反的 —— 他答得越好，说明题目越没有区分度。
# 按分数绝对值染色会把最该刺眼的那一格画成绿色，正好把结论看反。
PERSONA_COLS = [
    ("expert_score", "理想专家", "expert_pass", True),
    ("bluffer_score", "背题党", "bluffer_max", False),
    ("resume_score", "简历人格", "resume_pass", True),
]

DEFAULT_THRESHOLDS = {"expert_pass": 70.0, "bluffer_max": 50.0, "resume_pass": 60.0}

DIAGNOSIS_STYLE = {
    "GOOD": ("✅", "好题"),
    "NO_DISCRIMINATION": ("❌", "无区分度"),
    "OUT_OF_RANGE": ("⚠️", "超出射程"),
    "BROKEN": ("🔻", "题目有问题"),
}


def _cell(score: float, threshold: float, higher_is_better: bool) -> str:
    """按「离阈值多远、在哪一侧」染色，而不是按分数绝对值。

    绿 = 这个人格在这道题上的表现符合预期，红 = 不符合。
    30 分是经验取的饱和距离：再远也不会更红或更绿。
    """
    margin = (score - threshold) if higher_is_better else (threshold - score)
    t = max(-1.0, min(1.0, margin / 30.0))
    hue = 60 + t * 60          # -1 红 / 0 黄 / +1 绿
    return (
        f"<td style='background:hsl({hue:.0f},70%,86%);text-align:center;"
        f"padding:.35rem .6rem;border-bottom:2px solid #fff'>{score:.0f}</td>"
    )


def _heatmap(
    diagnoses: List[Dict[str, Any]],
    questions: List[Dict[str, Any]],
    thresholds: Dict[str, float],
) -> None:
    """三人格盲评热力图。

    读法是看**一行之内**三个分数的高低关系，不是看绝对分：
    专家高、背题党低，说明这道题问到了只有真做过的人才答得出的东西。
    """
    skill = {q["question_id"]: q.get("skill_point", "") for q in questions}

    rows = []
    for d in diagnoses:
        icon, label = DIAGNOSIS_STYLE.get(d["diagnosis"], ("", d["diagnosis"]))
        cells = "".join(
            _cell(d[key], thresholds.get(tkey, DEFAULT_THRESHOLDS[tkey]), up)
            for key, _, tkey, up in PERSONA_COLS
        )
        rows.append(
            "<tr><td style='padding:.35rem .6rem;white-space:nowrap'>"
            f"<b>{html.escape(d['question_id'])}</b>"
            f"<span style='color:#868e96'>　{html.escape(skill.get(d['question_id'], ''))}</span></td>"
            f"{cells}"
            f"<td style='padding:.35rem .6rem'>{icon} {label}</td></tr>"
        )

    header = "".join(
        f"<th style='padding:.35rem .6rem;font-weight:600'>{name}"
        f"<div style='font-weight:400;font-size:.78rem;color:#868e96'>"
        f"{'≥' if up else '≤'} {thresholds.get(tkey, DEFAULT_THRESHOLDS[tkey]):.0f} 为正常</div></th>"
        for _, name, tkey, up in PERSONA_COLS
    )
    st.markdown(
        "<table style='border-collapse:collapse;font-size:.88rem'>"
        f"<tr><th style='padding:.35rem .6rem;text-align:left'>题目</th>{header}"
        "<th style='padding:.35rem .6rem;text-align:left'>诊断</th></tr>"
        + "".join(rows)
        + "</table>",
        unsafe_allow_html=True,
    )


def _simulation_section(sim: Dict[str, Any], questions: List[Dict[str, Any]]) -> None:
    diagnoses = sim.get("diagnoses") or []
    if not diagnoses:
        return

    counts: Dict[str, int] = {}
    for d in diagnoses:
        counts[d["diagnosis"]] = counts.get(d["diagnosis"], 0) + 1
    summary = "　".join(
        f"{DIAGNOSIS_STYLE[k][0]} {DIAGNOSIS_STYLE[k][1]} {counts[k]}"
        for k in DIAGNOSIS_STYLE
        if counts.get(k)
    )

    st.markdown("#### 三人格盲评")
    st.caption(
        "同一套题交给三个信息量不同的人格作答，阅卷官在不知道谁是谁的情况下打分。"
        "题目质量因此变成可测量的信号，而不是主观感受。"
    )
    st.markdown(f"**{summary}**")
    _heatmap(diagnoses, questions, sim.get("thresholds") or DEFAULT_THRESHOLDS)

    problems = [d for d in diagnoses if d["diagnosis"] != "GOOD"]
    if problems:
        with st.expander(f"被诊断出问题的 {len(problems)} 道题"):
            for d in problems:
                icon, label = DIAGNOSIS_STYLE.get(d["diagnosis"], ("", d["diagnosis"]))
                st.markdown(f"**{d['question_id']}　{icon} {label}**　{d['detail']}")
    st.divider()


def render(
    payload: Dict[str, Any],
    on_generate: Optional[Callable[[str], None]] = None,
) -> None:
    rid = candidate_picker(payload, key="q_pick")
    if not rid:
        return

    data = payload["candidates"][rid]
    if not data["questions"]:
        recommendation = data["match"]["recommendation"]
        if recommendation in {"ADVANCE", "HOLD"} and on_generate is not None:
            candidate_name = data["resume"].get("candidate_name") or data["filename"]
            st.info(
                "排名与匹配已经完成。为缩短首次等待时间，面试题和追问改为按需生成。"
            )
            if st.button(
                f"为 {candidate_name} 生成面试题与追问",
                type="primary",
                key=f"generate_interview_{rid}",
            ):
                on_generate(rid)
            return
        st.warning(
            f"该候选人的建议是「{recommendation}」，未生成试题。\n\n"
            "只为值得面试的候选人出题：既符合业务逻辑，也把模型调用量压下来一大截。"
        )
        return

    questions = data["questions"]["questions"]
    st.markdown(f"#### 面试题（{len(questions)} 道）")

    counts = {k: sum(1 for q in questions if q["difficulty"] == k) for k in DIFF}
    st.caption("难度分布： " + " ／ ".join(f"{DIFF[k]} {v}" for k, v in counts.items()))

    st.divider()
    sim = data.get("simulation")
    if sim:
        _simulation_section(sim, questions)
    diagnosis_by_q = {
        d["question_id"]: d for d in (sim or {}).get("diagnoses") or []
    }

    for q in questions:
        with st.expander(f"{q['question_id']}　{q['text']}"):
            st.caption(f"考察点：{q['skill_point']}　·　难度：{DIFF.get(q['difficulty'], '')}"
                       f"　·　对应要求：{'、'.join(q['source_requirement_ids']) or '—'}")
            if d := diagnosis_by_q.get(q["question_id"]):
                icon, label = DIAGNOSIS_STYLE.get(d["diagnosis"], ("", d["diagnosis"]))
                st.markdown(f"**盲评诊断**　{icon} {label}　·　{d['detail']}")
            if q["rubric"]:
                st.markdown("**评分标准**")
                st.dataframe(
                    [{"档位": r["level"], "起评分": r["min_score"], "标准": r["criteria"]}
                     for r in q["rubric"]],
                    width="stretch", hide_index=True,
                )
            if q["evidence"]:
                st.markdown("**简历依据**")
                for e in q["evidence"]:
                    quote_block(e["text"])

    st.divider()

    fu = data["followups"]
    if not fu:
        return

    st.markdown(f"#### 追问（{len(fu['questions'])} 个）")
    st.caption("针对简历里说不清楚的地方，而不是简历没写的东西 —— 后者属于匹配打分。")

    points = {p["point_id"]: p for p in fu["ambiguity_points"]}
    for q in fu["questions"]:
        point = points.get(q["ambiguity_point_id"])
        with st.expander(f"{q['followup_id']}　{q['text']}"):
            st.markdown(f"**想确认什么**　{q['intent']}")
            if point:
                st.markdown(f"**对应模糊点**　{point['description']}")
                for e in point["evidence"]:
                    quote_block(e["text"])
