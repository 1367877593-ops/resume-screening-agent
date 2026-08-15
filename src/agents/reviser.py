"""定向修订：把 Checker 的问题清单退回给模型，要求它改。

两个刻意的设计：

1. **按对象粒度整体重写，不做 JSON Patch。** 让模型产出补丁指令，
   它既要理解问题又要算准路径，失败率显著更高，而且补丁打错的后果
   比重写更难排查。整体重写再校验一遍，简单且可验证。

2. **拒绝修订 MatchResult。** 那个对象里有 total_score 和 recommendation，
   交给模型重写就等于让它改分数 —— 项目最核心的约束会从这里漏掉。
   要修就修 MatchVerdicts，然后重新过一遍 scorer。
"""

from __future__ import annotations

import json
from typing import List, Optional, Tuple, Type, TypeVar

from pydantic import BaseModel, Field, create_model

from harness.structured import call_structured
from schema.issue import Issue
from schema.match import MatchResult
from schema.revision import RevisionNote

T = TypeVar("T", bound=BaseModel)


def _wrapper_model(model_cls: Type[T]) -> Type[BaseModel]:
    """动态构造 {revised: T, notes: [...]} 的包装类型。

    这样修订后的对象直接受目标 schema 约束，模型改坏了结构会在
    call_structured 里被 pydantic 拦下并触发回灌重试，不需要额外校验代码。
    """
    return create_model(
        f"Revised{model_cls.__name__}",
        revised=(model_cls, ...),
        notes=(List[RevisionNote], Field(default_factory=list)),
    )


def _issues_payload(issues: List[Issue]) -> str:
    return json.dumps(
        [
            {
                "issue_code": i.issue_code,
                "severity": i.severity,
                "dimension": i.dimension,
                "message": i.message,
                "target_path": i.target_path,
                "suggestion": i.suggestion,
            }
            for i in issues
        ],
        ensure_ascii=False,
        indent=2,
    )


def revise(
    target: T,
    issues: List[Issue],
    source_text: str = "",
    model: Optional[str] = None,
) -> Tuple[T, List[RevisionNote]]:
    """按问题清单修订对象。返回 (修订后的对象, 修订说明)。"""
    if isinstance(target, MatchResult):
        raise ValueError(
            "不能直接修订 MatchResult —— 它含 total_score 与 recommendation，"
            "交给模型重写等于让它改分数。请修订 MatchVerdicts 后重新调用 "
            "agents.scorer.build_match_result()。"
        )
    if not issues:
        return target, []

    model_cls = type(target)
    wrapper = _wrapper_model(model_cls)
    result = call_structured(
        "reviser",
        {
            "object_type": model_cls.__name__,
            "current_json": target.model_dump_json(indent=2),
            "issues": _issues_payload(issues),
            "source_text": source_text or "（本次修订不涉及原文核对）",
        },
        wrapper,
        model=model,
    )
    return result.revised, result.notes
