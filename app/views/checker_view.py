"""校验与修订。

这一页是 Part B 的门面：问题按校准维度归类，
并且明确标出每条问题是**规则**抓的还是 LLM 抓的 —— 这个占比不藏。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

import streamlit as st

from views._shared import candidate_picker, gate_badge

SEVERITY = {"blocker": "🔴 blocker", "major": "🟠 major", "minor": "⚪ minor"}
DETECTOR = {"rule": "规则", "llm": "LLM", "sim": "模拟"}
STAGE_NAME = {"extract": "简历提取", "match": "匹配判定",
              "question_set": "题目", "followup": "追问"}


def _detector_summary(issues: List[Dict[str, Any]]) -> str:
    if not issues:
        return "—"
    c = Counter(i["detector"] for i in issues)
    total = sum(c.values())
    return "　".join(f"{DETECTOR.get(k, k)} {v}（{v / total:.0%}）" for k, v in c.most_common())


def render(payload: Dict[str, Any]) -> None:
    rid = candidate_picker(payload, key="chk_pick")
    if not rid:
        return

    stages = payload["candidates"][rid]["stages"]
    all_issues = [i for s in stages for i in s["issues"]]

    c1, c2, c3 = st.columns(3)
    c1.metric("检出问题", len(all_issues))
    c2.metric("修订轮数", sum(s["rounds_used"] for s in stages))
    c3.metric("blocker", sum(1 for i in all_issues if i["severity"] == "blocker"))
    st.caption("检出来源：" + _detector_summary(all_issues))
    st.caption("能用确定性规则判断的一律不调 LLM。这个占比如实公开 —— "
               "如果绝大多数问题都靠 LLM 检出，说明这套校验的可信度有限。")

    st.divider()

    for s in stages:
        name = STAGE_NAME.get(s["stage"], s["stage"])
        gate = s["gate"]
        header = f"{name}　{gate_badge(gate['status'])}　·　修订 {s['rounds_used']} 轮　·　问题 {len(s['issues'])} 条"

        with st.expander(header, expanded=bool(s["issues"])):
            st.caption(gate["reason"])

            if gate["status"] == "NEEDS_HUMAN_REVIEW":
                st.error("已达修订轮数上限仍未通过，已熔断转人工 —— 不做无限循环。")

            if s["issues"]:
                st.dataframe(
                    [
                        {
                            "维度": i["dimension"],
                            "严重度": SEVERITY.get(i["severity"], i["severity"]),
                            "来源": DETECTOR.get(i["detector"], i["detector"]),
                            "编码": i["issue_code"],
                            "位置": i["target_path"] or "—",
                            "说明": i["message"],
                        }
                        for i in s["issues"]
                    ],
                    width="stretch", hide_index=True,
                )
            else:
                st.success("未发现问题")

            if s["notes"]:
                st.markdown("**修订记录**")
                for n in s["notes"]:
                    tag = "✅ 已修正" if n["action"] == "FIXED" else "⚖️ 申辩"
                    st.markdown(f"- {tag}　`{n['issue_code']}`　{n['detail']}")
                if any(n["action"] == "DISPUTED" for n in s["notes"]):
                    st.caption("申辩：模型认为原判定不成立。Checker 也会误判，"
                               "这类分歧交由人裁决，不强迫模型改对的东西。")
