"""app 与业务逻辑之间的唯一边界。

存在的理由：`app/` 只允许 import `pipeline` 和 `schema`。
界面需要读文件、跑流程、看 trace、落库，这些能力统一从这里出去，
编排逻辑就不会一点点渗进 UI 代码里。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.settings import ROOT, get_settings
from harness.trace import read_traces, summarize
from ingest.loader import load_file, load_text
from schema.document import RawDoc
from store.repository import list_runs, load_run, save_run

from pipeline.orchestrator import CandidateOutcome, PipelineResult, run_pipeline

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


def run(jd_text: str, resumes: Sequence[Upload]) -> PipelineResult:
    if not jd_text.strip():
        raise ValueError("JD 不能为空")
    if not resumes:
        raise ValueError("至少需要一份简历")
    jd_doc = load_text(jd_text, filename="jd")
    return run_pipeline(jd_doc, [_to_doc(u) for u in resumes])


# ------------------------------------------------------------------ 序列化


def _overall_gate(outcome: CandidateOutcome) -> str:
    """一个候选人的整体校验状态：取最差的那一档。"""
    order = ["PASS", "CONDITIONAL_PASS", "FAIL", "NEEDS_HUMAN_REVIEW"]
    statuses = [s.gate.status for s in outcome.stages] or ["PASS"]
    return max(statuses, key=order.index)


def result_to_dict(result: PipelineResult, run_id: Optional[str] = None) -> Dict[str, Any]:
    gate_by_id = {o.resume_id: _overall_gate(o) for o in result.candidates}
    return {
        "run_id": run_id or uuid.uuid4().hex[:12],
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
                "stages": [
                    {
                        "stage": s.stage,
                        "rounds_used": s.rounds_used,
                        "gate": s.gate.model_dump(mode="json"),
                        "issues": [i.model_dump(mode="json") for i in s.report.issues],
                        "notes": [n.model_dump(mode="json") for n in s.notes],
                    }
                    for s in o.stages
                ],
            }
            for o in result.candidates
        },
    }


def persist(result: PipelineResult) -> str:
    return save_run(result_to_dict(result))


def history(limit: int = 20) -> List[Dict[str, Any]]:
    return list_runs(limit)


def load(run_id: str) -> Optional[Dict[str, Any]]:
    return load_run(run_id)


# ------------------------------------------------------------------ trace


def trace_stats() -> Dict[str, Any]:
    s = get_settings()
    return summarize(read_traces(s.resolve(s.trace_dir)))


def trace_rows(limit: int = 200) -> List[Dict[str, Any]]:
    s = get_settings()
    rows = [r for r in read_traces(s.resolve(s.trace_dir)) if r.get("event") == "structured_call"]
    return rows[-limit:]


def runtime_mode() -> Dict[str, Any]:
    s = get_settings()
    return {
        "demo_mode": s.demo_mode,
        "provider": s.llm_provider,
        "model": s.llm_model,
        "cache_enabled": s.cache_enabled,
    }
