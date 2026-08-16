"""历史记录与跨批次查询。

这一页是 SQLite 相对「把结果写成 JSON 文件」的价值所在：能按批次回看，
也能跨批次横向比。存储层的 list_runs / load_run / top_candidates 早就写好了，
在此之前没有任何界面入口 —— 能力表里写着的功能，点不到就等于没有。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import streamlit as st

from views._shared import rec_badge


def _when(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def render(
    runs: List[Dict[str, Any]],
    top: List[Dict[str, Any]],
    persistence_enabled: bool,
    current_run_id: Optional[str] = None,
    on_load: Optional[Callable[[str], None]] = None,
) -> None:
    if not persistence_enabled:
        st.info(
            "当前配置为不落盘（`PERSIST_RUNS=0`），因此没有历史记录。\n\n"
            "公网部署时这是刻意的：落库内容含简历原文，而所有访问者共用同一份库。"
        )
        return

    st.markdown("#### 历次运行")
    if not runs:
        st.caption("还没有历史记录。跑一次筛选后会出现在这里。")
    else:
        for run in runs:
            is_current = run["run_id"] == current_run_id
            cols = st.columns([3, 2, 1.2, 1.2])
            cols[0].markdown(
                f"**{run['jd_title'] or '（无标题）'}**"
                + ("　:green[当前]" if is_current else "")
            )
            cols[1].caption(_when(run["created_at"]))
            cols[2].caption(f"{run['n_candidates']} 位候选人")
            if is_current:
                cols[3].caption("已载入")
            elif on_load is not None:
                if cols[3].button("载入", key=f"load_run_{run['run_id']}"):
                    on_load(run["run_id"])
            st.caption(f"`{run['run_id']}`")
            st.divider()

    st.markdown("#### 跨批次最高分候选人")
    st.caption(
        "跨越所有批次按总分排序，已排除被淘汰的人 —— "
        "同一个岗位分几次筛，值得回头看的人不会淹没在某一批里。"
    )
    if not top:
        st.caption("暂无数据。")
        return

    st.dataframe(
        [
            {
                "候选人": c.get("candidate_name") or c["resume_id"],
                "总分": round(c["total_score"], 2),
                "建议": rec_badge(c["recommendation"]),
                "岗位": c.get("jd_title") or "—",
                "批次": c["run_id"],
            }
            for c in top
        ],
        width="stretch",
        hide_index=True,
    )
