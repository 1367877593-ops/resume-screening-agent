"""通过 / 不通过判定。**业务代码里不得手写这套逻辑。**

集中在这里的理由：放行标准散进各处之后，改一次阈值要翻遍全项目，
而且各处会慢慢长出不一致的判定 —— 那时候「通过」到底意味着什么就说不清了。
"""

from __future__ import annotations

from typing import Dict, Optional

from config.settings import get_thresholds
from schema.issue import CheckReport, GateResult


def evaluate_gate(
    report: CheckReport, round_no: Optional[int] = None, thresholds: Optional[Dict] = None
) -> GateResult:
    t = (thresholds or get_thresholds())["gate"]
    rnd = report.round_no if round_no is None else round_no

    blockers = report.count("blocker")
    majors = report.count("major")
    minors = report.count("minor")
    counts = {"blocker_count": blockers, "major_count": majors, "minor_count": minors}

    # 熔断优先于一切：修够了轮数还有 blocker，说明模型自己修不好，转人工。
    # 这一条必须排在 FAIL 前面，否则会永远 FAIL 下去，正是我们要避免的死循环。
    if blockers and rnd >= t["max_rounds"]:
        return GateResult(
            status="NEEDS_HUMAN_REVIEW",
            reason=f"已修订 {rnd} 轮（上限 {t['max_rounds']}）仍有 {blockers} 个 blocker，转人工复核",
            **counts,
        )
    if blockers:
        return GateResult(
            status="FAIL", reason=f"存在 {blockers} 个 blocker 级问题，需修订", **counts
        )
    if majors >= t["max_major"]:
        return GateResult(
            status="FAIL",
            reason=f"major 级问题 {majors} 个，达到不通过阈值 {t['max_major']}",
            **counts,
        )
    if majors:
        return GateResult(
            status="CONDITIONAL_PASS",
            reason=f"有 {majors} 个 major 级问题，可用但建议人工过目",
            **counts,
        )
    return GateResult(
        status="PASS", reason="未发现 blocker 或 major 级问题" if not minors
        else f"仅有 {minors} 个 minor 级问题", **counts
    )
