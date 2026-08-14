"""首屏：候选人排序。

HR 场景真正要的是排序而不是单份报告，所以这是默认标签页。
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from views._shared import gate_badge, rec_badge


def render(payload: Dict[str, Any]) -> None:
    jd = payload["jd"]
    ranking = payload["ranking"]

    st.subheader(jd["title"])
    hard = [r["text"] for r in jd["requirements"] if r["is_hard"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("候选人", len(ranking))
    c2.metric("建议推进", sum(1 for r in ranking if r["recommendation"] == "ADVANCE"))
    c3.metric("要求项", len(jd["requirements"]))
    c4.metric("其中硬性", len(hard))

    if hard:
        st.caption("硬性门槛（不满足即淘汰，不看总分）：" + " ／ ".join(hard))

    st.divider()

    st.dataframe(
        [
            {
                "排名": r["rank"],
                "候选人": r.get("candidate_name") or r["resume_id"],
                "总分": round(r["total_score"], 1),
                "建议": rec_badge(r["recommendation"]),
                "校验": gate_badge(r.get("gate_status") or "PASS"),
                "未满足的硬性要求": "；".join(r["hard_requirement_failed"]) or "—",
            }
            for r in ranking
        ],
        width="stretch",
        hide_index=True,
        column_config={"总分": st.column_config.ProgressColumn(
            "总分", min_value=0, max_value=100, format="%.1f")},
    )

    st.caption(
        "总分由代码对各要求项加权求和得出，不由模型给出；"
        "硬性要求未满足者一票否决并沉底。"
    )

    with st.expander("JD 拆解结果（加权要求项）"):
        st.dataframe(
            [
                {
                    "编号": r["requirement_id"],
                    "要求": r["text"],
                    "类别": r["category"],
                    "权重": r["weight"],
                    "硬性": "是" if r["is_hard"] else "",
                }
                for r in jd["requirements"]
            ],
            width="stretch", hide_index=True,
        )
