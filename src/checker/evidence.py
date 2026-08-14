"""span 在原文中的模糊匹配。整套归因校验都建立在这个函数上。

为什么不用精确匹配：模型引用原文时常有轻微出入 —— 吞掉一个空格、
把全角括号写成半角、跨行时丢了换行。这些都是排版差异，不是编造。
但如果放得太宽，真正编造的内容也会蒙混过关，所以阈值要能调
（config/thresholds.yaml: evidence.min_similarity），并且有测试守住两端。
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from config.settings import get_thresholds

# 空白、常见标点的全半角差异一律抹平后再比对
_STRIP = re.compile(r"[\s　]+")
_PUNCT_MAP = str.maketrans("，。、；：（）【】「」！？－～", ",.,;:()[]\"\"!?-~")


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_PUNCT_MAP)
    s = _STRIP.sub("", s)
    return s.lower()


def similarity(span_text: str, full_text: str) -> float:
    """span 在 full_text 中的最佳匹配相似度，0-1。

    先试子串命中（绝大多数情况会在这里返回 1.0，很快），
    命不中再滑窗比对。简历长度有限，这个开销可以接受。
    """
    span = normalize_for_match(span_text)
    full = normalize_for_match(full_text)
    if not span or not full:
        return 0.0
    if span in full:
        return 1.0
    if len(span) >= len(full):
        return SequenceMatcher(None, span, full).ratio()

    width = len(span)
    step = max(1, width // 4)
    best = 0.0
    for i in range(0, len(full) - width + 1, step):
        r = SequenceMatcher(None, span, full[i:i + width]).ratio()
        if r > best:
            best = r
            if best >= 0.999:
                break
    return best


def is_grounded(span_text: str, full_text: str, threshold: Optional[float] = None) -> bool:
    """这段引用是否真实存在于原文。False 即判定为归因错误。"""
    t = threshold if threshold is not None else get_thresholds()["evidence"]["min_similarity"]
    return similarity(span_text, full_text) >= t


def is_too_short(span_text: str, min_length: Optional[int] = None) -> bool:
    """过短的 span 不具备归因意义 —— 「Python」这种词在任何简历里都能匹配上。"""
    n = min_length if min_length is not None else get_thresholds()["evidence"]["min_span_length"]
    return len(normalize_for_match(span_text)) < n


def text_similarity(a: str, b: str) -> float:
    """两段文本的整体相似度，用于题目查重。"""
    return SequenceMatcher(None, normalize_for_match(a), normalize_for_match(b)).ratio()
