"""确定性规则：数量、schema、算术、日期自洽。

这些全部不调 LLM —— 「题目少于 10 道」这种事拿正则和 len() 就能判，
花钱问模型既慢又不可靠。校准维度对应「数据准确性」与「格式与约束」。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from checker.base import RuleContext, register
from schema.issue import Issue

# 2022.09 / 2022-9 / 2022/09 / 2022年9月 都能吃下
_DATE = re.compile(r"(\d{4})\s*[.\-/年]?\s*(\d{1,2})?")
_NOW_WORDS = ("至今", "现在", "今", "present", "now")


def parse_ym(s: Optional[str]) -> Optional[Tuple[int, int]]:
    """解析成 (年, 月)。解析不了返回 None —— 解析不了不等于有错，不该误报。"""
    if not s:
        return None
    if any(w in s.lower() for w in _NOW_WORDS):
        return (9999, 12)
    m = _DATE.search(s)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else 1
    if not (1900 <= year <= 2100) or not (1 <= month <= 12):
        return None
    return (year, month)


# ------------------------------------------------------------------ 简历


@register("resume")
def rule_resume_not_empty(ctx: RuleContext) -> List[Issue]:
    """提取结果整体为空，多半是 PDF 没解析出文本或模型跑偏。"""
    r = ctx.resume
    if r is None:
        return []
    if not any([r.educations, r.work_experiences, r.projects, r.skills]):
        return [
            Issue(
                issue_code="EXT_EMPTY_RESULT",
                severity="blocker",
                detector="rule",
                dimension="数据准确性",
                message="提取结果为空：教育、工作、项目、技能四类信息一条都没有",
                suggestion="检查文档是否为扫描件，或重新提取",
            )
        ]
    return []


@register("resume")
def rule_candidate_name_present(ctx: RuleContext) -> List[Issue]:
    r = ctx.resume
    if r is None or (r.candidate_name or "").strip():
        return []
    return [
        Issue(
            issue_code="EXT_FIELD_MISSING",
            severity="minor",
            detector="rule",
            dimension="数据准确性",
            message="未提取到候选人姓名",
            target_path="candidate_name",
        )
    ]


@register("resume")
def rule_date_ranges_are_sane(ctx: RuleContext) -> List[Issue]:
    """开始时间晚于结束时间 —— 模型串行或看错年份时的典型症状。"""
    r = ctx.resume
    if r is None:
        return []
    issues: List[Issue] = []
    groups = [("educations", r.educations), ("work_experiences", r.work_experiences)]
    for field_name, items in groups:
        for i, item in enumerate(items):
            start, end = parse_ym(item.start), parse_ym(item.end)
            if start and end and start > end:
                issues.append(
                    Issue(
                        issue_code="EXT_DATE_CONFLICT",
                        severity="major",
                        detector="rule",
                        dimension="数据准确性",
                        message=f"起止时间矛盾：{item.start} 晚于 {item.end}",
                        target_path=f"{field_name}[{i}]",
                        suggestion="核对原文中的时间，修正后重新输出",
                    )
                )
    return issues


# ------------------------------------------------------------------ 匹配


@register("match")
def rule_every_requirement_has_verdict(ctx: RuleContext) -> List[Issue]:
    """漏判必须报出来。

    scorer 已经把漏判按 0 分计入总分，但那只解决了「分数不被刷高」，
    不解决「HR 看到的报告缺了一条」。两件事都要管。
    """
    if ctx.jd is None or ctx.match_result is None:
        return []
    judged = {v.requirement_id for v in ctx.match_result.verdicts}
    missing = [r for r in ctx.jd.requirements if r.requirement_id not in judged]
    return [
        Issue(
            issue_code="MATCH_VERDICT_MISSING",
            severity="blocker",
            detector="rule",
            dimension="数据准确性",
            message=f"要求项 {r.requirement_id}（{r.text}）没有给出判定",
            target_path=f"verdicts[{r.requirement_id}]",
            suggestion="补齐该项判定",
        )
        for r in missing
    ]


@register("match")
def rule_no_unknown_requirement_id(ctx: RuleContext) -> List[Issue]:
    """判定了一个 JD 里不存在的要求 —— 模型编 id 的典型表现。"""
    if ctx.jd is None or ctx.match_result is None:
        return []
    known = {r.requirement_id for r in ctx.jd.requirements}
    return [
        Issue(
            issue_code="MATCH_VERDICT_UNKNOWN_ID",
            severity="major",
            detector="rule",
            dimension="数据准确性",
            message=f"判定引用了不存在的要求项 {v.requirement_id}",
            target_path=f"verdicts[{v.requirement_id}]",
        )
        for v in ctx.match_result.verdicts
        if v.requirement_id not in known
    ]


@register("match")
def rule_score_matches_satisfied(ctx: RuleContext) -> List[Issue]:
    """分数要和判定档位对得上。

    模型说「不满足」却给 80 分，是它内部自相矛盾的信号，
    比单看分数或单看判定都更能暴露问题。区间与 prompt 中的约定一致。
    """
    if ctx.match_result is None:
        return []
    bands = {"YES": (70, 100), "PARTIAL": (30, 69), "NO": (0, 29)}
    issues: List[Issue] = []
    for v in ctx.match_result.verdicts:
        lo, hi = bands[v.satisfied]
        if not (lo <= v.score <= hi):
            issues.append(
                Issue(
                    issue_code="MATCH_SCORE_SATISFIED_MISMATCH",
                    severity="major",
                    detector="rule",
                    dimension="数据准确性",
                    message=f"{v.requirement_id} 判定为 {v.satisfied} 但给分 {v.score:g}（应在 {lo}-{hi}）",
                    target_path=f"verdicts[{v.requirement_id}].score",
                )
            )
    return issues


@register("match")
def rule_total_score_is_reproducible(ctx: RuleContext) -> List[Issue]:
    """总分必须能由分项重算出来。

    这条是防线而不是形式：只要有人（或某次改动）让 LLM 碰了总分，
    这里立刻会红。分数不可复现是这个项目最不能接受的失败。
    """
    if ctx.jd is None or ctx.match_result is None:
        return []
    from agents.scorer import aggregate_score  # 局部导入避免 checker -> agents 的模块级依赖

    expected = aggregate_score(ctx.jd, ctx.match_result.verdicts)
    if abs(expected - ctx.match_result.total_score) > 0.01:
        return [
            Issue(
                issue_code="MATCH_ARITHMETIC_MISMATCH",
                severity="blocker",
                detector="rule",
                dimension="数据准确性",
                message=f"总分 {ctx.match_result.total_score} 与分项重算结果 {expected} 不一致",
                target_path="total_score",
                suggestion="总分必须由 scorer 计算，不得由模型给出或手工填写",
            )
        ]
    return []


# ------------------------------------------------------------------ 题目


@register("question_set")
def rule_question_count(ctx: RuleContext) -> List[Issue]:
    if ctx.question_set is None:
        return []
    min_count = ctx.thresholds["question"]["min_count"]
    n = len(ctx.question_set.questions)
    if n >= min_count:
        return []
    return [
        Issue(
            issue_code="Q_COUNT_LT_MIN",
            severity="blocker",
            detector="rule",
            dimension="格式与约束",
            message=f"题目数量 {n} 少于要求的 {min_count} 道",
            suggestion=f"再补 {min_count - n} 道，覆盖尚未考察到的要求项",
        )
    ]


@register("question_set")
def rule_question_has_usable_rubric(ctx: RuleContext) -> List[Issue]:
    """没有评分标准的题目在面试现场没法用，等于没出。"""
    if ctx.question_set is None:
        return []
    issues: List[Issue] = []
    for q in ctx.question_set.questions:
        if len(q.rubric) < 2:
            issues.append(
                Issue(
                    issue_code="Q_RUBRIC_MISSING",
                    severity="major",
                    detector="rule",
                    dimension="格式与约束",
                    message=f"{q.question_id} 的评分标准只有 {len(q.rubric)} 档，至少需要 2 档",
                    target_path=f"questions[{q.question_id}].rubric",
                )
            )
    return issues


# ------------------------------------------------------------------ 追问


@register("followup")
def rule_followup_count_in_range(ctx: RuleContext) -> List[Issue]:
    if ctx.followups is None:
        return []
    t = ctx.thresholds["followup"]
    n = len(ctx.followups.questions)
    if t["min_count"] <= n <= t["max_count"]:
        return []
    return [
        Issue(
            issue_code="FU_COUNT_OUT_OF_RANGE",
            severity="major",
            detector="rule",
            dimension="格式与约束",
            message=f"追问数量 {n} 不在 {t['min_count']}-{t['max_count']} 区间内",
        )
    ]


@register("followup")
def rule_followup_points_to_existing_ambiguity(ctx: RuleContext) -> List[Issue]:
    """追问必须挂在已声明的模糊点上，否则「针对模糊点」就是句空话。"""
    if ctx.followups is None:
        return []
    known = {p.point_id for p in ctx.followups.ambiguity_points}
    return [
        Issue(
            issue_code="FU_DANGLING_POINT_REF",
            severity="major",
            detector="rule",
            dimension="格式与约束",
            message=f"追问 {q.followup_id} 引用了不存在的模糊点 {q.ambiguity_point_id}",
            target_path=f"questions[{q.followup_id}]",
        )
        for q in ctx.followups.questions
        if q.ambiguity_point_id not in known
    ]
