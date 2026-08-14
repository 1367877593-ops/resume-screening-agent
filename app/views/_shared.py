"""视图共用的小工具。"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

import streamlit as st

REC_STYLE = {
    "ADVANCE": ("🟢", "推进面试", "#2b8a3e"),
    "HOLD": ("🟡", "待定", "#e67700"),
    "REJECT": ("⚪", "淘汰", "#868e96"),
}

GATE_STYLE = {
    "PASS": ("✅", "通过"),
    "CONDITIONAL_PASS": ("🟨", "有条件通过"),
    "FAIL": ("❌", "不通过"),
    "NEEDS_HUMAN_REVIEW": ("🔺", "转人工"),
}


def rec_badge(rec: str) -> str:
    icon, label, _ = REC_STYLE.get(rec, ("", rec, "#666"))
    return f"{icon} {label}"


def gate_badge(status: str) -> str:
    icon, label = GATE_STYLE.get(status, ("", status))
    return f"{icon} {label}"


def candidate_picker(payload: Dict[str, Any], key: str) -> Optional[str]:
    """按排序结果给出候选人下拉框，返回 resume_id。"""
    ranking: List[Dict[str, Any]] = payload["ranking"]
    if not ranking:
        return None
    labels = {
        item["resume_id"]: f"#{item['rank']}  {item.get('candidate_name') or item['resume_id']}"
                           f"  ·  {item['total_score']:.1f}  ·  {rec_badge(item['recommendation'])}"
        for item in ranking
    }
    return st.selectbox(
        "选择候选人", list(labels), format_func=lambda rid: labels[rid], key=key
    )


def quote_block(text: str) -> None:
    st.markdown(f"<div class='quote'>{html.escape(text)}</div>", unsafe_allow_html=True)


def highlight(full_text: str, spans: List[str]) -> str:
    """把出处在原文里标黄。

    只对**逐字命中**的片段高亮。模糊匹配通过但字面对不上的（排版差异），
    宁可不高亮 —— 在界面上假装标中了，比不标更误导人。
    """
    escaped = html.escape(full_text)
    for span in sorted({s for s in spans if s}, key=len, reverse=True):
        needle = html.escape(span)
        if needle in escaped:
            escaped = escaped.replace(needle, f"<mark>{needle}</mark>")
    return escaped.replace("\n", "<br>")
