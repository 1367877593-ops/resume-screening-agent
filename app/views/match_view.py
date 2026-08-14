"""匹配详情：分项判定 + 原文出处高亮。

「可审计」在这一页兑现 —— 每条判定旁边就是它引用的原文，
右侧可以直接看到那句话在简历中的位置。
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from views._shared import candidate_picker, highlight, quote_block, rec_badge

SATISFIED = {"YES": "✅ 满足", "PARTIAL": "🟡 部分满足", "NO": "❌ 不满足"}


def render(payload: Dict[str, Any]) -> None:
    rid = candidate_picker(payload, key="match_pick")
    if not rid:
        return

    data = payload["candidates"][rid]
    match = data["match"]
    req_text = {r["requirement_id"]: r["text"] for r in payload["jd"]["requirements"]}
    weights = {r["requirement_id"]: r["weight"] for r in payload["jd"]["requirements"]}

    top = st.container()
    with top:
        c1, c2 = st.columns([1, 3])
        c1.metric("总分", f"{match['total_score']:.1f}")
        c2.markdown(f"### {rec_badge(match['recommendation'])}")
        st.info(match["recommendation_reason"])

    left, right = st.columns([1.35, 1])

    with left:
        st.markdown("#### 分项判定")
        for v in match["verdicts"]:
            head = (
                f"{SATISFIED.get(v['satisfied'], v['satisfied'])} · "
                f"{v['requirement_id']} {req_text.get(v['requirement_id'], '')} "
                f"（权重 {weights.get(v['requirement_id'], '—')}，得分 {v['score']:g}）"
            )
            with st.expander(head, expanded=v["satisfied"] != "YES"):
                st.write(v["reason"])
                if v["evidence"]:
                    st.caption("原文出处")
                    for e in v["evidence"]:
                        quote_block(e["text"])
                else:
                    st.caption("无出处（判定为不满足时不需要出处）")

    with right:
        st.markdown("#### 简历原文")
        st.caption(f"{data['filename']} · 黄色为被引用的出处")
        spans = [e["text"] for v in match["verdicts"] for e in v["evidence"]]
        st.markdown(
            f"<div style='max-height:70vh;overflow:auto;font-size:.86rem;line-height:1.7'>"
            f"{highlight(data['resume_text'], spans)}</div>",
            unsafe_allow_html=True,
        )
