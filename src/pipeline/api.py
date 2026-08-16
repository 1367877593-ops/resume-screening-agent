"""app 与业务逻辑之间的唯一边界。

存在的理由：`app/` 只允许 import `pipeline` 和 `schema`。
界面需要读文件、跑流程、看 trace、落库，这些能力统一从这里出去，
编排逻辑就不会一点点渗进 UI 代码里。
"""

from __future__ import annotations

import hmac
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import ROOT, get_settings
from harness.structured import start_run
from harness.trace import new_run_id, read_traces, summarize
from ingest.loader import load_file, load_text
from schema.document import RawDoc
from store.repository import list_runs, load_run, save_run

from pipeline.orchestrator import (
    CandidateOutcome,
    PipelineResult,
    generate_interviews,
    run_pipeline,
)

SAMPLE_DIR = ROOT / "data" / "samples"

# (文件名, 文件内容)
Upload = Tuple[str, bytes]


def sample_inputs() -> Tuple[str, List[Upload]]:
    """内置样例：一份 JD + 两份对比鲜明的简历，用于一键演示。"""
    jd_text = (SAMPLE_DIR / "jd.txt").read_text(encoding="utf-8")
    resumes = [
        (p.name, p.read_bytes())
        for p in sorted(SAMPLE_DIR.glob("resume_*.txt"))
    ]
    return jd_text, resumes


def is_sample_input(jd_text: str, resumes: Sequence[Upload]) -> bool:
    """判断当前输入是否与内置 Demo 完全一致。

    Demo 缓存按输入内容寻址；哪怕只改了一个字符，也不应等到流水线中途才
    暴露 ``CacheMissError``。UI 用这个轻量预检尽早给出可理解的提示。
    """
    sample_jd, sample_resumes = sample_inputs()
    return jd_text == sample_jd and list(resumes) == sample_resumes


def _to_doc(upload: Upload) -> RawDoc:
    """上传的是字节流，pdf/docx 解析需要真实文件，落到临时目录再读。"""
    name, data = upload
    suffix = Path(name).suffix.lower()
    if suffix in (".txt", ".md"):
        return load_text(data.decode("utf-8", errors="replace"), filename=name)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = Path(f.name)
    try:
        doc = load_file(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return doc.model_copy(update={"filename": name})


def run(
    jd_text: str,
    resumes: Sequence[Upload],
    generate_interview: bool = True,
) -> PipelineResult:
    settings = get_settings()
    # run_id 在开跑前就定下来，trace、落库 payload 和 UI 展示共用同一个。
    # 否则 trace 自己生成一个、payload 再生成一个，两边对不上，
    # 事后拿着一条历史记录查不到它当时发出的调用。
    run_id = new_run_id()
    start_run(run_id)
    if not jd_text.strip():
        raise ValueError("JD 不能为空")
    if not resumes:
        raise ValueError("至少需要一份简历")
    if len(jd_text) > settings.max_jd_chars:
        raise ValueError(f"JD 过长，最多允许 {settings.max_jd_chars} 个字符")
    if len(resumes) > settings.max_resumes_per_run:
        raise ValueError(f"单次最多处理 {settings.max_resumes_per_run} 份简历")
    total_bytes = sum(len(data) for _, data in resumes)
    max_bytes = settings.max_total_upload_mb * 1024 * 1024
    if total_bytes > max_bytes:
        raise ValueError(f"简历总大小不能超过 {settings.max_total_upload_mb} MB")
    jd_doc = load_text(jd_text, filename="jd")
    result = run_pipeline(
        jd_doc,
        [_to_doc(u) for u in resumes],
        include_interview=generate_interview,
    )
    result.run_id = run_id
    return result


def generate_interview(result: PipelineResult, resume_id: str) -> PipelineResult:
    """为快速筛选结果中的一名候选人按需补充题目与追问。"""
    known = {o.resume_id for o in result.candidates}
    if resume_id not in known:
        raise ValueError("找不到对应候选人")
    return generate_interviews(result, [resume_id])


def access_control_required() -> bool:
    """公网部署时由 Secret 开启；只向 UI 暴露是否需要认证。"""
    return bool(get_settings().app_access_code)


def verify_access_code(candidate: str) -> bool:
    """常量时间比较访问口令，避免把正确值暴露给 UI。"""
    expected = get_settings().app_access_code
    return bool(expected) and hmac.compare_digest(candidate, expected)


# ------------------------------------------------------------------ 序列化


def _overall_gate(outcome: CandidateOutcome) -> str:
    """一个候选人的整体校验状态：取最差的那一档。"""
    order = ["PASS", "CONDITIONAL_PASS", "FAIL", "NEEDS_HUMAN_REVIEW"]
    statuses = [s.gate.status for s in outcome.stages] or ["PASS"]
    return max(statuses, key=order.index)


def result_to_dict(result: PipelineResult, run_id: Optional[str] = None) -> Dict[str, Any]:
    gate_by_id = {o.resume_id: _overall_gate(o) for o in result.candidates}
    return {
        # 默认沿用 run() 定下的那个，让 payload 与 trace 对得上
        "run_id": run_id or result.run_id or uuid.uuid4().hex[:12],
        "jd": result.jd.model_dump(mode="json"),
        "ranking": [
            {**item.model_dump(mode="json"), "gate_status": gate_by_id.get(item.resume_id)}
            for item in result.ranking.items
        ],
        "candidates": {
            o.resume_id: {
                "resume": o.resume.model_dump(mode="json"),
                "resume_text": o.resume_doc.full_text,
                "filename": o.resume_doc.filename,
                "match": o.match_result.model_dump(mode="json"),
                "questions": o.question_set.model_dump(mode="json") if o.question_set else None,
                "followups": o.followups.model_dump(mode="json") if o.followups else None,
                "simulation": o.simulation.model_dump(mode="json") if o.simulation else None,
                "stages": [
                    {
                        "stage": s.stage,
                        "rounds_used": s.rounds_used,
                        "gate": s.gate.model_dump(mode="json"),
                        "issues": [i.model_dump(mode="json") for i in s.report.issues],
                        # 各轮累计检出（含已修复的）。UI 展示的是最终状态，
                        # 但「检出占比」这类统计必须用这一份，否则会漏掉
                        # 所有被修好的问题。
                        "detected_issues": [i.model_dump(mode="json") for i in s.detected],
                        "notes": [n.model_dump(mode="json") for n in s.notes],
                    }
                    for s in o.stages
                ],
            }
            for o in result.candidates
        },
    }


def persist(result: PipelineResult, run_id: Optional[str] = None) -> str:
    """保存或更新一次运行；按需出题后沿用原 run_id，不制造重复记录。

    `PERSIST_RUNS=0` 时跳过落库并原样返回 run_id —— 界面照常工作，
    只是这次结果不留在磁盘上。公网演示应该走这条路径。
    """
    payload = result_to_dict(result, run_id=run_id)
    if not get_settings().persist_runs:
        return payload["run_id"]
    return save_run(payload)


def persistence_enabled() -> bool:
    return get_settings().persist_runs


def history(limit: int = 20) -> List[Dict[str, Any]]:
    return list_runs(limit)


def load(run_id: str) -> Optional[Dict[str, Any]]:
    return load_run(run_id)


# ------------------------------------------------------------------ trace


def trace_stats(run_id: Optional[str] = None) -> Dict[str, Any]:
    """`run_id` 为 None 时统计全部历史。

    UI 默认传本次运行的 run_id：读整个目录算出来的是历次运行的平均值，
    跑第二次 Demo 时「一次成功率」会莫名其妙地变，那只是把上一次也算进来了。
    """
    s = get_settings()
    return summarize(read_traces(s.resolve(s.trace_dir), run_id=run_id))


def trace_rows(limit: int = 200, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    s = get_settings()
    rows = [
        r for r in read_traces(s.resolve(s.trace_dir), run_id=run_id)
        if r.get("event") == "structured_call"
    ]
    return rows[-limit:]


def runtime_mode() -> Dict[str, Any]:
    s = get_settings()
    return {
        "demo_mode": s.demo_mode,
        "provider": s.llm_provider,
        "model": s.llm_model,
        "fast_model": s.llm_model_cheap,
        # UI 只得到布尔值，绝不接触密钥本身。
        "api_key_configured": bool(s.llm_api_key),
        "access_control": bool(s.app_access_code),
        "cache_enabled": s.cache_enabled,
        "max_parallel_candidates": s.max_parallel_candidates,
        "simulation_enabled": s.simulation_enabled,
        "persist_runs": s.persist_runs,
    }
