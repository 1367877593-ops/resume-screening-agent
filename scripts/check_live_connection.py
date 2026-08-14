"""用极小请求验证实时模型连接，不打印 Key 或模型回复正文。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT / "src"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config.settings import get_settings  # noqa: E402
from harness.errors import LLMCallError  # noqa: E402
from harness.llm_client import get_client  # noqa: E402


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    if settings.demo_mode:
        raise SystemExit("DEMO_MODE 必须为 0 才能执行真实连接检查。")
    if settings.llm_provider != "deepseek":
        raise SystemExit("LLM_PROVIDER 必须为 deepseek。")
    if settings.llm_model != "deepseek-v4-pro":
        raise SystemExit("LLM_MODEL 必须为 deepseek-v4-pro。")
    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY 为空，请先运行 make configure-live。")

    client = get_client(settings)
    try:
        response = client.complete(
            "只输出 JSON。",
            '返回 {"status":"ok"}，不要添加其他字段。',
            settings.llm_model,
            json_schema={"type": "object", "properties": {"status": {"const": "ok"}}},
        )
    except LLMCallError as exc:
        raise SystemExit(f"真实连接失败：{exc}") from None
    payload = json.loads(response.text)
    if payload.get("status") != "ok":
        raise SystemExit("模型已响应，但最小 JSON 校验失败。")

    print(
        "真实连接成功："
        f"provider={response.provider}, model={response.model}, "
        f"tokens={response.prompt_tokens + response.completion_tokens}, "
        f"latency_ms={response.latency_ms}"
    )
    print("API Key 未输出；现在可以运行 make run。")


if __name__ == "__main__":
    main()
