"""语义一致性校验（detector = "llm"）。

这一层存在的理由很窄：**确定性规则判不了的那一类错误**。

归因规则能确认「这句引用确实逐字出现在简历里」，但确认不了「这句引用是否
真的支持这个结论」。模型完全可能引用一句真实存在的原文，却给出一个它撑不起
的判定 —— 引用「了解 Python 基础」然后判「精通 Python」，字符串匹配全过。

所以这一层只回答一个问题：**证据撑得起结论吗**。它是整个项目里唯一用 LLM
去验证 LLM 的地方，因此有两条硬约束：

1. 只在确定性规则全部通过之后才跑，能用规则判的绝不花这次调用；
2. 判定必须保守 —— 拿不准就放过。误报会触发一次昂贵的修订，而且会把本来
   正确的结论改坏，代价比漏报高得多。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class SemanticFinding(BaseModel):
    """一条语义矛盾。`quote` 必须是被质疑的那条证据原文，便于人工复核。"""

    requirement_id: str
    explanation: str = Field(description="证据为什么撑不起这个判定，一句话说清")
    quote: str = Field(default="", description="被质疑的证据原文")


class SemanticReport(BaseModel):
    target_id: str
    findings: List[SemanticFinding] = Field(default_factory=list)
    # 实际送检的判定条数。用于区分「查了但没问题」和「根本没查」——
    # 两者在报告里都是零发现，但含义完全不同。
    checked: int = 0
