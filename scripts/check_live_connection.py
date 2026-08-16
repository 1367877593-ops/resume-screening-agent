"""用极小请求验证实时模型连接，不打印 Key 或模型回复正文。

**两个模型都要验。** 流水线是混合模型的：JD 拆解、简历提取、出题走
`LLM_MODEL_CHEAP`，匹配判定与 Checker 修订走 `LLM_MODEL`。只验后者的话，
快模型名写错时这个脚本照样报成功，而 `make run` 会在第一步就失败 ——
那种「检查通过了但跑不起来」的体验比直接报错更糟。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT / "src"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config.settings import get_settings  # noqa: E402
from harness.errors import LLMCallError  # noqa: E402
from harness.llm_client import get_client  # noqa: E402

_PROBE_SYSTEM = "只输出 JSON。"
_PROBE_USER = '返回 {"status":"ok"}，不要添加其他字段。'
_PROBE_SCHEMA = {"type": "object", "properties": {"status": {"const": "ok"}}}


def _hint(message: str) -> str:
    """把厂商返回的原始报错翻译成下一步该做什么。"""
    lowered = message.lower()
    if any(k in lowered for k in ("401", "unauthorized", "invalid api key", "authentication")):
        return "Key 无效或已撤销 —— 重新运行 `make configure-live`。"
    if any(k in lowered for k in ("model", "404", "not found", "does not exist")):
        return (
            "模型标识可能不对 —— 核对 .env 里的 LLM_MODEL / LLM_MODEL_CHEAP "
            "是否与厂商文档中的标识完全一致。"
        )
    if any(k in lowered for k in ("402", "insufficient", "balance", "quota")):
        return "账户余额或额度不足 —— 到厂商控制台充值后重试。"
    if any(k in lowered for k in ("timeout", "timed out", "connect")):
        return "网络不通或超时 —— 检查出口网络与 LLM_BASE_URL。"
    return "完整报错见上一行；Key 已在输出前脱敏。"


def _probe(client, model: str, label: str) -> bool:
    print(f"  {label:<10} {model} ... ", end="", flush=True)
    try:
        response = client.complete(_PROBE_SYSTEM, _PROBE_USER, model, json_schema=_PROBE_SCHEMA)
    except LLMCallError as exc:
        print("失败")
        print(f"    {exc}")
        print(f"    → {_hint(str(exc))}")
        return False

    try:
        ok = json.loads(response.text).get("status") == "ok"
    except json.JSONDecodeError:
        ok = False
    if not ok:
        print("响应了，但最小 JSON 校验没过")
        print("    → 该模型可能不支持严格 JSON 输出，换一个模型或关闭 thinking 模式。")
        return False

    tokens = (response.prompt_tokens or 0) + (response.completion_tokens or 0)
    print(f"成功（{tokens} tokens, {response.latency_ms} ms）")
    return True


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()

    if settings.demo_mode:
        raise SystemExit("DEMO_MODE=1 时不发起真实请求。要做连接检查请先设为 0。")
    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY 为空，请先运行 `make configure-live`。")

    try:
        client = get_client(settings)
    except LLMCallError as exc:
        raise SystemExit(f"客户端初始化失败：{exc}") from None

    print(f"provider = {settings.llm_provider}")

    # 两档模型可能配成同一个，那就只探一次，不浪费一次调用
    targets = [("关键判断", settings.llm_model)]
    if settings.llm_model_cheap and settings.llm_model_cheap != settings.llm_model:
        targets.append(("快速阶段", settings.llm_model_cheap))

    results = [_probe(client, model, label) for label, model in targets]

    if not all(results):
        raise SystemExit(
            "\n连接检查未全部通过。上面标为失败的模型会在实际运行中报同样的错，"
            "修好之后再执行 `make run`。"
        )

    print("\n全部通过；API Key 未输出。现在可以运行 `make run`。")


if __name__ == "__main__":
    main()
