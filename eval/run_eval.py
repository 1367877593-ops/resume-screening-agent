"""从 trace 与实际运行中统计可复现的评测数字。

这个脚本只做一件事：**把 README 里的数字变成可以当场重跑的东西**。
所有指标都标注了来源，没有跑出来的一律不打印占位符。

关于「分数稳定性」有一个必须说清楚的前提：DEMO_MODE 下每次运行都命中同一批
缓存，方差必然是 0 —— 那是缓存的性质，不是模型的性质。脚本会如实标注这一点，
真实的稳定性数字只能在配置了 API Key 后跑出来。

用法：

    make eval                       # 无 Key，回放内置样例
    RUNS=5 DEMO_MODE=0 make eval    # 接真实模型跑 5 次，得到有意义的方差
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config.settings import get_settings  # noqa: E402
from harness import structured  # noqa: E402
from harness.trace import read_traces, summarize  # noqa: E402
from pipeline import api  # noqa: E402


def _pct(part: int, total: int) -> str:
    return f"{part / total * 100:.1f}%" if total else "—"


def _collect(runs: int) -> Dict[str, Any]:
    """跑 N 次内置样例，把每次的结果摊平成可统计的记录。"""
    jd_text, resumes = api.sample_inputs()

    scores: Dict[str, List[float]] = {}
    recommendations: Dict[str, set] = {}
    issues: List[Dict[str, Any]] = []

    for _ in range(runs):
        payload = api.result_to_dict(api.run(jd_text, resumes))
        for item in payload["ranking"]:
            name = item.get("candidate_name") or item["resume_id"]
            scores.setdefault(name, []).append(item["total_score"])
            recommendations.setdefault(name, set()).add(item["recommendation"])
        for cand in payload["candidates"].values():
            for stage in cand["stages"]:
                # 用累计检出而不是最终报告：被修好的问题也是「检出」，
                # 漏掉它们会让规则类检出的占比被系统性低估。
                for issue in stage["detected_issues"]:
                    issues.append({**issue, "stage": stage["stage"]})

    return {
        "scores": scores,
        "recommendations": recommendations,
        "issues": issues,
    }


def _report(runs: int, demo_mode: bool, data: Dict[str, Any], traces: Dict[str, Any]) -> str:
    out: List[str] = []
    w = out.append

    w("=" * 66)
    w(f"评测结果　运行 {runs} 次　模式：{'DEMO 回放' if demo_mode else '真实模型'}")
    w("=" * 66)

    # ---------------------------------------------------------- 结构化输出
    w("\n【结构化输出】来源：本次运行的 trace")
    if not traces.get("calls"):
        w("  本次运行没有产生调用记录。")
    else:
        w(f"  总调用            {traces['calls']}")
        w(f"  缓存命中率        {traces['cache_hit_rate'] * 100:.1f}%")
        w(f"  实际发出的调用    {traces['live_calls']}")
        if traces["live_calls"]:
            w(f"  一次成功率        {traces['first_try_success_rate'] * 100:.1f}%"
              "　（未触发任何修复重试即通过 schema 校验）")
            w(f"  修复后成功率      {traces['final_success_rate'] * 100:.1f}%"
              "　（回灌校验报错重试后最终通过）")
            w(f"  prompt tokens     {traces['total_prompt_tokens']}")
            w(f"  completion tokens {traces['total_completion_tokens']}")
            w(f"  平均耗时          {traces['avg_latency_ms']} ms")
        else:
            w("  全部命中缓存，没有真实请求 —— 成功率与耗时需在 DEMO_MODE=0 下统计。")

    # ---------------------------------------------------------- 检出来源
    w("\n【Checker 检出来源】来源：本次运行的 CheckReport")
    issues = data["issues"]
    if not issues:
        w("  本次运行未检出任何问题。")
    else:
        total = len(issues)
        by_detector: Dict[str, int] = {}
        for i in issues:
            by_detector[i["detector"]] = by_detector.get(i["detector"], 0) + 1
        for det in ("rule", "llm"):
            n = by_detector.get(det, 0)
            w(f"  {det:<5} {n:>3} 条　{_pct(n, total)}")
        w("  —— 这个占比是「用 LLM 验证 LLM」风险的直接度量：靠确定性规则"
          "检出的比例越高，这套校验越可信。")

        by_code: Dict[str, int] = {}
        for i in issues:
            by_code[i["issue_code"]] = by_code.get(i["issue_code"], 0) + 1
        w("\n  按 issue_code：")
        for code, n in sorted(by_code.items(), key=lambda kv: -kv[1]):
            det = next(i["detector"] for i in issues if i["issue_code"] == code)
            w(f"    {code:<28} {n:>3}　[{det}]")

    # ---------------------------------------------------------- 稳定性
    w("\n【分数稳定性】来源：同一份简历重复运行的总分")
    for name, values in data["scores"].items():
        spread = max(values) - min(values)
        stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
        recs = data["recommendations"][name]
        w(f"  {name:<6} 均值 {statistics.mean(values):>6.2f}　"
          f"极差 {spread:>5.2f}　总体标准差 {stdev:>5.2f}　"
          f"决策 {'稳定（' + recs.pop() + '）' if len(recs) == 1 else '出现摇摆：' + str(recs)}")
    if demo_mode:
        w("  ⚠️ DEMO 回放下每次命中同一批缓存，方差必然为 0 —— 这是缓存的性质，")
        w("     不能用来说明模型稳定。真实数字请用 DEMO_MODE=0 且 RUNS>=5 重跑。")
    elif runs < 3:
        w("  ⚠️ 运行次数过少，方差没有参考价值。建议 RUNS>=5。")

    w("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="统计稳定性、检出占比与诊断分布")
    parser.add_argument("--runs", type=int, default=1, help="重复运行次数（算方差用）")
    parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()

    # 单独开一个 trace 目录：默认目录里堆着历次运行的记录，
    # 混在一起算出来的「一次成功率」是历史平均值，不是这次的结果。
    eval_dir = settings.resolve(Path("data/runtime/eval")) / time.strftime("%Y%m%d-%H%M%S")
    settings.trace_dir = eval_dir
    structured._default_tracer = None

    if not settings.demo_mode and not settings.llm_api_key:
        print("未配置 LLM_API_KEY 且 DEMO_MODE=0。\n"
              "先跑 `make configure-live`，或用 `make eval`（DEMO_MODE=1 回放）。")
        raise SystemExit(1)

    data = _collect(args.runs)
    traces = summarize(read_traces(eval_dir))

    if args.json:
        print(json.dumps(
            {
                "runs": args.runs,
                "demo_mode": settings.demo_mode,
                "traces": traces,
                "scores": data["scores"],
                "issues": data["issues"],
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print(_report(args.runs, settings.demo_mode, data, traces))
        print(f"trace 明细：{eval_dir}")


if __name__ == "__main__":
    main()
