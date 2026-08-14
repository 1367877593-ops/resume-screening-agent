"""调用链。README 里的那些数字就是从这里统计出来的。"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def render(stats: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    if not stats.get("calls"):
        st.info("本次会话还没有调用记录。")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总调用", stats["calls"])
    c2.metric("缓存命中率", _pct(stats.get("cache_hit_rate")))
    c3.metric("一次成功率", _pct(stats.get("first_try_success_rate")),
              help="没有触发任何修复重试就通过 schema 校验")
    c4.metric("修复后成功率", _pct(stats.get("final_success_rate")),
              help="把 pydantic 校验报错回灌给模型重试之后最终通过")

    c5, c6, c7 = st.columns(3)
    c5.metric("输入 token", f"{stats.get('total_prompt_tokens', 0):,}")
    c6.metric("输出 token", f"{stats.get('total_completion_tokens', 0):,}")
    c7.metric("平均耗时", f"{stats.get('avg_latency_ms') or 0:.0f} ms")

    st.caption("「一次成功率」与「修复后成功率」之间的差，就是结构化输出修复机制的实际贡献。")
    st.divider()

    st.dataframe(
        [
            {
                "prompt": f"{r.get('prompt')} v{r.get('prompt_version')}",
                "模型": r.get("model"),
                "缓存": "命中" if r.get("cache_hit") else "",
                "结果": "✅" if r.get("ok") else "❌",
                "修复次数": r.get("repair_attempts", 0),
                "耗时(ms)": r.get("latency_ms", 0),
                "token": (r.get("prompt_tokens", 0) or 0) + (r.get("completion_tokens", 0) or 0),
                "错误": (r.get("error") or "")[:80],
            }
            for r in reversed(rows)
        ],
        width="stretch", hide_index=True,
    )
