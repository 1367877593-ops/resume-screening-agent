"""确定性规则：证据存在性、归因正确性、题目查重。

这一组是项目里对抗幻觉的主力。核心思路：**不问模型「你确定吗」**，
而是把它给出的原文引用拿回原文里逐字核对 —— 编造的引用对不上，
确定性的字符串匹配就能抓住，不需要再花一次 LLM 调用去猜。

校准维度对应「归因错误」与「题目质量」。
"""

from __future__ import annotations

from typing import List, Optional

from checker.base import RuleContext, register
from checker.evidence import is_grounded, is_too_short, text_similarity
from schema.document import SourceSpan
from schema.issue import Issue


def _check_spans(
    spans: List[SourceSpan],
    full_text: str,
    ctx: RuleContext,
    path: str,
    code_not_found: str,
) -> List[Issue]:
    """把一组 span 拿回原文核对。所有归因规则共用这段逻辑。"""
    t = ctx.thresholds["evidence"]
    issues: List[Issue] = []
    for i, span in enumerate(spans):
        if is_too_short(span.text, t["min_span_length"]):
            issues.append(
                Issue(
                    issue_code="EVIDENCE_TOO_SHORT",
                    severity="minor",
                    detector="rule",
                    dimension="归因错误",
                    message=f"出处片段过短，不足以支撑结论：{span.text!r}",
                    target_path=f"{path}.evidence[{i}]",
                    suggestion="引用一段 10-60 字的完整原文",
                    evidence=[span],
                )
            )
            continue
        if not is_grounded(span.text, full_text, t["min_similarity"]):
            issues.append(
                Issue(
                    issue_code=code_not_found,
                    severity="blocker",
                    detector="rule",
                    dimension="归因错误",
                    message=f"出处在原文中不存在：{span.text[:40]!r}",
                    target_path=f"{path}.evidence[{i}]",
                    suggestion="改为引用原文中逐字出现的片段，或删除这条无据的结论",
                    evidence=[span],
                )
            )
    return issues


# ------------------------------------------------------------------ 简历


@register("resume")
def rule_resume_evidence_is_grounded(ctx: RuleContext) -> List[Issue]:
    if ctx.resume is None or ctx.resume_doc is None:
        return []
    full = ctx.resume_doc.full_text
    issues: List[Issue] = []
    groups = [
        ("educations", ctx.resume.educations),
        ("work_experiences", ctx.resume.work_experiences),
        ("projects", ctx.resume.projects),
        ("skills", ctx.resume.skills),
    ]
    for name, items in groups:
        for i, item in enumerate(items):
            issues.extend(
                _check_spans(item.evidence, full, ctx, f"{name}[{i}]", "EXT_SPAN_NOT_FOUND")
            )
    return issues


# ------------------------------------------------------------------ 匹配


@register("match")
def rule_positive_verdict_needs_evidence(ctx: RuleContext) -> List[Issue]:
    """判定满足却给不出出处 —— 说不出依据的「满足」不作数。

    NO 不要求出处：不存在的东西没有原文可引。
    """
    if ctx.match_result is None:
        return []
    return [
        Issue(
            issue_code="MATCH_EVIDENCE_EMPTY",
            severity="blocker",
            detector="rule",
            dimension="归因错误",
            message=f"{v.requirement_id} 判定为 {v.satisfied} 但没有给出任何原文出处",
            target_path=f"verdicts[{v.requirement_id}].evidence",
            suggestion="补上支撑该判定的简历原文，或把判定改为 NO",
        )
        for v in ctx.match_result.verdicts
        if v.satisfied in ("YES", "PARTIAL") and not v.evidence
    ]


@register("match")
def rule_match_evidence_is_grounded(ctx: RuleContext) -> List[Issue]:
    if ctx.match_result is None or ctx.resume_doc is None:
        return []
    full = ctx.resume_doc.full_text
    issues: List[Issue] = []
    for v in ctx.match_result.verdicts:
        issues.extend(
            _check_spans(
                v.evidence, full, ctx, f"verdicts[{v.requirement_id}]", "MATCH_EVIDENCE_INVALID"
            )
        )
    return issues


# ------------------------------------------------------------------ 题目


@register("match")
def rule_semantic_contradictions(ctx: RuleContext) -> List[Issue]:
    """把语义校验的结论翻译成 Issue（detector = llm）。

    这里只做映射，不发起调用 —— 规则表整体保持纯函数，可以脱离 LLM 单测。
    真正的调用在 `checker/semantic.py`，且只在确定性规则全过之后才会发生。

    判 major 而不是 blocker：语义判断本身有误报可能，让它进报告、攒够三条
    才触发重写，比一条就打回要稳。
    """
    if ctx.semantic is None:
        return []
    return [
        Issue(
            issue_code="SEM_REASON_CONTRADICTS_EVIDENCE",
            severity="major",
            detector="llm",
            dimension="语义一致性",
            message=f"{f.requirement_id}：{f.explanation}",
            target_path=f"verdicts[{f.requirement_id}]",
            suggestion="把判定改成证据真正支持的档位，或换一条撑得起结论的原文",
        )
        for f in ctx.semantic.findings
    ]


@register("question_set")
def rule_question_evidence_is_grounded(ctx: RuleContext) -> List[Issue]:
    if ctx.question_set is None or ctx.resume_doc is None:
        return []
    full = ctx.resume_doc.full_text
    issues: List[Issue] = []
    for q in ctx.question_set.questions:
        issues.extend(
            _check_spans(q.evidence, full, ctx, f"questions[{q.question_id}]", "Q_EVIDENCE_INVALID")
        )
    return issues


@register("question_set")
def rule_questions_are_not_duplicates(ctx: RuleContext) -> List[Issue]:
    """题干高度相似 = 十道题实际只考了七个点，是「凑数量」的典型表现。"""
    if ctx.question_set is None:
        return []
    threshold = ctx.thresholds["question"]["duplicate_similarity"]
    qs = ctx.question_set.questions
    issues: List[Issue] = []
    for i in range(len(qs)):
        for j in range(i + 1, len(qs)):
            sim = text_similarity(qs[i].text, qs[j].text)
            if sim >= threshold:
                issues.append(
                    Issue(
                        issue_code="Q_DUPLICATE",
                        severity="major",
                        detector="rule",
                        dimension="题目质量",
                        message=f"{qs[i].question_id} 与 {qs[j].question_id} 题干相似度 {sim:.2f}，重复考察",
                        target_path=f"questions[{qs[j].question_id}]",
                        suggestion="替换其中一道，改考尚未覆盖的要求项",
                    )
                )
    return issues


# ------------------------------------------------------------------ 追问


@register("followup")
def rule_ambiguity_evidence_is_grounded(ctx: RuleContext) -> List[Issue]:
    """找不到原文依据的「模糊点」是模型编的。"""
    if ctx.followups is None or ctx.resume_doc is None:
        return []
    full = ctx.resume_doc.full_text
    issues: List[Issue] = []
    for p in ctx.followups.ambiguity_points:
        issues.extend(
            _check_spans(p.evidence, full, ctx, f"ambiguity_points[{p.point_id}]", "FU_SPAN_NOT_FOUND")
        )
    return issues
