"""文本归一化。

这一步直接决定证据链能不能用：简历 PDF 抽出来的文本常带断行和页眉页脚，
如果不清洗，模型引用的原文片段和 full_text 对不上，Checker 会把大量
正确结论误判成归因错误。
"""

from __future__ import annotations

import re
from typing import List

_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")
# 中文断行：上一行结尾与下一行开头都是中文且上一行没有句末标点，多半是排版折行
_CJK_BREAK = re.compile(r"([一-鿿])\n([一-鿿])")


def _drop_repeated_lines(text: str, min_repeats: int = 3) -> str:
    """出现三次以上的短行按页眉页脚处理。

    阈值取 3 是因为两页的简历里正常内容重复两次并不罕见（如「项目经历」小标题），
    但连续出现三次的短行几乎只可能是页眉、页脚或页码。
    """
    lines = text.split("\n")
    counts: dict = {}
    for ln in lines:
        s = ln.strip()
        if 0 < len(s) <= 30:
            counts[s] = counts.get(s, 0) + 1
    junk = {s for s, c in counts.items() if c >= min_repeats}
    return "\n".join(ln for ln in lines if ln.strip() not in junk)


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("﻿", "")
    text = _drop_repeated_lines(text)
    text = _CJK_BREAK.sub(r"\1\2", text)
    text = _TRAILING_WS.sub("\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def split_paragraphs(text: str) -> List[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
