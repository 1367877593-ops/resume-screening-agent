"""语义一致性校验（detector = "llm"）。

调用量：**每位候选人一次**，整批判定一起送检，与要求项数量无关。

这一层是项目里唯一「用 LLM 验证 LLM」的地方，因此接入方式上做了三处收敛：

- 只在确定性规则全部通过后才被调用（判断在 `pipeline/orchestrator.py`）；
- 只送检**有证据的**判定 —— 没有证据的 YES/PARTIAL 归因规则已经拦下了，
  再花一次 LLM 去看它是浪费；
- 模型不产出 Issue，只产出「哪一条矛盾、为什么」，翻译成 Issue 由
  `content_rules.py` 里注册的规则完成。这样 Issue 的构造仍然只有一个出口。
"""

from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from harness.structured import call_structured
from schema.jd import JD
from schema.match import MatchResult
from schema.semantic import SemanticFinding, SemanticReport


class _SemanticOutput(BaseModel):
    """LLM 输出边界。target_id 由代码补，不让模型转述。"""

    findings: List[SemanticFinding] = Field(default_factory=list)


def _payload(jd: JD, match_result: MatchResult) -> tuple:
    """整理送检清单。返回 (JSON 文本, 送检条数)。"""
    req_text = {r.requirement_id: r.text for r in jd.requirements}
    rows = []
    for v in match_result.verdicts:
        # 没有证据的判定不送检：归因规则已经处理过，这里再看一遍是白花钱
        if not v.evidence:
            continue
        rows.append(
            {
                "requirement_id": v.requirement_id,
                "requirement": req_text.get(v.requirement_id, v.requirement_id),
                "satisfied": v.satisfied,
                "reason": v.reason,
                "evidence": [e.text for e in v.evidence],
            }
        )
    return json.dumps(rows, ensure_ascii=False, indent=2), len(rows)


def check_match_semantics(
    jd: JD,
    match_result: MatchResult,
    model: Optional[str] = None,
) -> SemanticReport:
    verdicts, checked = _payload(jd, match_result)
    if not checked:
        return SemanticReport(target_id=match_result.resume_id, checked=0)

    out = call_structured(
        "checker_semantic",
        {"verdicts": verdicts},
        _SemanticOutput,
        model=model,
    )

    # 模型可能报一个不存在的 requirement_id。丢弃而不是照单全收 ——
    # 挂在错误编号上的 issue 会让 Reviser 去改一条它找不到的判定。
    known = {v.requirement_id for v in match_result.verdicts}
    findings = [f for f in out.findings if f.requirement_id in known]

    return SemanticReport(
        target_id=match_result.resume_id,
        findings=findings,
        checked=checked,
    )
