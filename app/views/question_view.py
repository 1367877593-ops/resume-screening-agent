"""题目与追问。被淘汰的候选人不出题，这里会明确说明原因。"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from views._shared import candidate_picker, quote_block

DIFF = {"EASY": "🟢 简单", "MEDIUM": "🟡 中等", "HARD": "🔴 困难"}


def render(payload: Dict[str, Any]) -> None:
    rid = candidate_picker(payload, key="q_pick")
    if not rid:
        return

    data = payload["candidates"][rid]
    if not data["questions"]:
        st.warning(
            f"该候选人的建议是「{data['match']['recommendation']}」，未生成试题。\n\n"
            "只为值得面试的候选人出题：既符合业务逻辑，也把模型调用量压下来一大截。"
        )
        return

    questions = data["questions"]["questions"]
    st.markdown(f"#### 面试题（{len(questions)} 道）")

    counts = {k: sum(1 for q in questions if q["difficulty"] == k) for k in DIFF}
    st.caption("难度分布： " + " ／ ".join(f"{DIFF[k]} {v}" for k, v in counts.items()))

    for q in questions:
        with st.expander(f"{q['question_id']}　{q['text']}"):
            st.caption(f"考察点：{q['skill_point']}　·　难度：{DIFF.get(q['difficulty'], '')}"
                       f"　·　对应要求：{'、'.join(q['source_requirement_ids']) or '—'}")
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
