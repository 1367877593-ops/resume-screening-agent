"""经验库的读写。JSONL 落盘，按 (岗位, issue_code) 去重合并。

用 JSONL 而不是塞进 SQLite：这份数据是追加为主、整体读入的小文件，
再开一张表只是增加一处需要同步维护的 schema。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config.settings import get_settings
from schema.issue import Issue
from schema.lesson import Lesson

# 每个岗位保留的条目上限。经验库不是日志，留太多只会稀释注入内容 ——
# prompt 里塞五十条告诫，模型一条都不会认真看。
MAX_PER_JOB = 12

# 从 issue_code 到「下次该怎么做」的映射。
# 刻意写成静态表而不是让模型总结：告诫必须稳定，否则注入内容每次都在变，
# 缓存键跟着漂移，而且模型总结出来的话术往往比原始规则更含糊。
_GUIDANCE: Dict[str, str] = {
    "Q_COUNT_LT_MIN": "上次这个岗位出的题数量不足被打回，务必一次生成足量题目",
    "Q_DUPLICATE": "上次出现题干高度相似的题，注意每道题考察不同的点",
    "Q_RUBRIC_MISSING": "上次评分标准档位不全，每道题都要给满三档且写清可执行的判据",
    "Q_EVIDENCE_INVALID": "上次题目引用的简历原文对不上，只引用逐字出现的片段",
    "Q_NO_DISCRIMINATION": "上次有题被判无区分度（背题即可作答），必须逼出本人经历中的数字、取舍或失败案例",
    "Q_UNANSWERABLE": "上次有题连专家都答不出，确认题干给足了作答前提",
    "Q_OUT_OF_RANGE": "上次有题超出候选人简历射程，出题前先确认简历里确有着落",
    "EXT_SPAN_NOT_FOUND": "上次提取的出处在原文中找不到，只引用逐字连续的片段",
    "EVIDENCE_TOO_SHORT": "上次出处片段过短，引用 10-60 字的完整句子",
    "MATCH_EVIDENCE_EMPTY": "上次有判定给不出原文出处，说不出依据就判 NO",
    "MATCH_EVIDENCE_INVALID": "上次匹配引用的原文对不上，逐字核对后再引用",
    "SEM_REASON_CONTRADICTS_EVIDENCE": "上次理由与所引证据自相矛盾，理由不能说过头于原文所写",
    "FU_COUNT_OUT_OF_RANGE": "上次追问数量超出区间，严格按要求的条数生成",
}


def _path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    s = get_settings()
    return s.resolve(s.lessons_path)


def load_all(path: Optional[Path] = None) -> List[Lesson]:
    p = _path(path)
    if not p.exists():
        return []
    out: List[Lesson] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(Lesson.model_validate_json(line))
        # 单条损坏不该让整个经验库不可用 —— 它只是增强，不是主干
        except Exception:  # noqa: BLE001
            continue
    return out


def _write_all(lessons: Iterable[Lesson], path: Optional[Path] = None) -> None:
    """整体重写。同 cache.put：临时文件 + os.replace，避免读到写了一半的内容。"""
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(x.model_dump_json() for x in lessons)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".lessons-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body + ("\n" if body else ""))
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def record(
    job_kind: str,
    issues: Iterable[Issue],
    stage_of: Dict[str, str],
    path: Optional[Path] = None,
) -> List[Lesson]:
    """把本次检出的问题合并进经验库，返回该岗位合并后的全部条目。

    `stage_of` 是 issue_code -> stage 的映射，由调用方给出 —— 经验库本身
    不认识流水线的阶段划分。

    没有对应告诫文本的 issue_code 会被跳过：与其注入一句「上次出现了
    RULE_CRASHED」这种模型无法据以改进的话，不如不注入。
    """
    existing = load_all(path)
    by_id = {x.lesson_id: x for x in existing}

    for issue in issues:
        guidance = _GUIDANCE.get(issue.issue_code)
        if not guidance:
            continue
        lid = Lesson.make_id(job_kind, issue.issue_code)
        if lid in by_id:
            by_id[lid].hits += 1
            by_id[lid].updated_at = time.time()
        else:
            by_id[lid] = Lesson(
                lesson_id=lid,
                job_kind=job_kind,
                issue_code=issue.issue_code,
                stage=stage_of.get(issue.issue_code, "unknown"),
                guidance=guidance,
            )

    # 容量控制：按岗位分别裁剪，命中多的留下
    kept: List[Lesson] = []
    grouped: Dict[str, List[Lesson]] = {}
    for x in by_id.values():
        grouped.setdefault(x.job_kind, []).append(x)
    for group in grouped.values():
        group.sort(key=lambda x: (-x.hits, x.issue_code))
        kept.extend(group[:MAX_PER_JOB])

    _write_all(kept, path)
    return [x for x in kept if x.job_kind == job_kind]
