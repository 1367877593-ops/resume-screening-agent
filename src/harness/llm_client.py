"""LLM 调用的唯一出口。

这是整个项目里**唯一**知道厂商存在的文件。`agents/` 与 `checker/` 下
出现任何 openai / anthropic 字样都是设计错误 —— 换模型只该改一个环境变量。

重试与退避也放在这一层：业务代码不该关心 429 该等多久。
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from harness.errors import LLMCallError

# OpenAI 兼容协议覆盖了国内外大多数厂商，只有 base_url 不同
_OPENAI_COMPATIBLE_BASES = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "kimi": "https://api.moonshot.cn/v1",
}
_ANTHROPIC_BASE = "https://api.anthropic.com"
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1


class BaseClient:
    provider = "base"

    def complete(
        self,
        system: str,
        user: str,
        model: str,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        raise NotImplementedError


# --------------------------------------------------------------------------
# mock：不发起任何网络请求，按目标 schema 合成一个结构合法的假响应。
# 用途仅限单元测试与无 Key 冒烟 —— 它的内容是无意义的占位符，
# 真正的演示数据走 data/demo_cache/ 的真实调用录制。
# --------------------------------------------------------------------------


def synthesize_from_schema(
    schema: Dict[str, Any], defs: Optional[Dict[str, Any]] = None, depth: int = 0
) -> Any:
    """由 JSON Schema 合成一个满足约束的最小实例。"""
    if depth > 8:
        return None
    defs = defs if defs is not None else schema.get("$defs", {})

    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return synthesize_from_schema(defs.get(ref, {}), defs, depth + 1)

    for combiner in ("anyOf", "oneOf"):
        if combiner in schema:
            options = [o for o in schema[combiner] if o.get("type") != "null"]
            target = options[0] if options else schema[combiner][0]
            return synthesize_from_schema(target, defs, depth + 1)

    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]

    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        return {k: synthesize_from_schema(v, defs, depth + 1) for k, v in props.items()}
    if t == "array":
        min_items = schema.get("minItems", 0)
        if min_items <= 0:
            return []
        item = synthesize_from_schema(schema.get("items", {}), defs, depth + 1)
        return [item] * min_items
    if t == "string":
        return schema.get("default") or "mock"
    if t in ("number", "integer"):
        lo = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        hi = schema.get("maximum")
        val = lo if hi is None else min(lo, hi)
        return int(val) if t == "integer" else float(val)
    if t == "boolean":
        return False
    if t == "null":
        return None
    # 没有 type 信息（如 dict[str, Any]）时给空对象最安全
    return {}


class MockClient(BaseClient):
    provider = "mock"

    def complete(self, system, user, model, json_schema=None):
        payload = synthesize_from_schema(json_schema) if json_schema else {}
        text = json.dumps(payload, ensure_ascii=False)
        return LLMResponse(
            text=text,
            model="mock",
            provider="mock",
            prompt_tokens=len(system + user) // 4,
            completion_tokens=len(text) // 4,
            latency_ms=0,
        )


# --------------------------------------------------------------------------
# 真实厂商
# --------------------------------------------------------------------------


def _sleep_backoff(attempt: int) -> None:
    """指数退避 + 抖动。抖动是为了避免多份简历并发时重试撞在同一时刻。"""
    time.sleep(min(2 ** attempt, 16) * (0.5 + random.random() * 0.5))


class _HTTPClient(BaseClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int,
        max_retries: int,
        max_output_tokens: int = 8192,
    ) -> None:
        if not api_key:
            raise LLMCallError(
                f"provider={self.provider} 需要 API Key，但 LLM_API_KEY 为空。"
                " 请在 .env 中填写，或用 `make demo` 走无 Key 的缓存回放。"
            )
        parsed = urlparse(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise LLMCallError(
                "LLM_BASE_URL 只能填写服务地址，不能包含账号、Key、查询参数或片段。"
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens

    def _safe_error(self, value: Any) -> str:
        """错误信息在进入 UI 或日志前移除密钥，防止上游意外回显。"""
        return str(value).replace(self.api_key, "[REDACTED]")

    def _build(self, system, user, model, json_schema):
        raise NotImplementedError

    def _parse(self, data: Dict[str, Any]):
        raise NotImplementedError

    def complete(self, system, user, model, json_schema=None):
        url, headers, body = self._build(system, user, model, json_schema)
        last_err: Optional[str] = None
        started = time.time()

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, headers=headers, json=body)
                if resp.status_code in _RETRYABLE_STATUS:
                    last_err = self._safe_error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    _sleep_backoff(attempt)
                    continue
                if resp.status_code >= 400:
                    # 4xx 里的鉴权/参数错误重试多少次都一样，直接失败
                    if resp.status_code == 401:
                        # 部分厂商会在错误正文里回显 Key 的尾部，鉴权失败时不转发正文。
                        raise LLMCallError(
                            "HTTP 401: API Key 无效或不属于当前接口，请重新生成并配置。"
                        )
                    if resp.status_code == 402:
                        raise LLMCallError("HTTP 402: API 账户余额不足。")
                    raise LLMCallError(
                        self._safe_error(f"HTTP {resp.status_code}: {resp.text[:300]}")
                    )
                text, ptok, ctok = self._parse(resp.json())
                return LLMResponse(
                    text=text,
                    model=model,
                    provider=self.provider,
                    prompt_tokens=ptok,
                    completion_tokens=ctok,
                    latency_ms=int((time.time() - started) * 1000),
                    attempts=attempt + 1,
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = self._safe_error(f"{type(e).__name__}: {e}")
                _sleep_backoff(attempt)

        raise LLMCallError(f"重试 {self.max_retries} 次后仍失败：{last_err}")


class OpenAICompatibleClient(_HTTPClient):
    provider = "openai_compatible"

    def __init__(self, *args, provider_name: str = "openai", thinking_mode: str = "disabled", **kwargs):
        super().__init__(*args, **kwargs)
        self.provider = provider_name
        if thinking_mode not in {"enabled", "disabled"}:
            raise LLMCallError("LLM_THINKING_MODE 只能是 enabled 或 disabled")
        self.thinking_mode = thinking_mode

    def _build(self, system, user, model, json_schema):
        body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        if json_schema:
            # 让服务端也约束一道格式，能显著降低回灌重试的次数
            body["response_format"] = {"type": "json_object"}
        if self.provider == "deepseek":
            body["thinking"] = {"type": self.thinking_mode}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return f"{self.base_url}/chat/completions", headers, body

    def _parse(self, data):
        usage = data.get("usage") or {}
        return (
            data["choices"][0]["message"]["content"],
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )


class AnthropicClient(_HTTPClient):
    provider = "anthropic"

    def _build(self, system, user, model, json_schema):
        body = {
            "model": model,
            "max_tokens": 8192,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        return f"{self.base_url}/v1/messages", headers, body

    def _parse(self, data):
        usage = data.get("usage") or {}
        parts: List[str] = [b.get("text", "") for b in data.get("content", [])]
        return (
            "".join(parts),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )


def get_client(settings) -> BaseClient:
    """按 LLM_PROVIDER 选择实现。业务代码永远不该调这个函数之外的东西。"""
    provider = (settings.llm_provider or "mock").lower()

    if provider == "mock":
        return MockClient()
    if provider == "anthropic":
        return AnthropicClient(
            settings.llm_api_key,
            settings.llm_base_url or _ANTHROPIC_BASE,
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
            settings.llm_max_output_tokens,
        )
    if provider in _OPENAI_COMPATIBLE_BASES:
        return OpenAICompatibleClient(
            settings.llm_api_key,
            settings.llm_base_url or _OPENAI_COMPATIBLE_BASES[provider],
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
            settings.llm_max_output_tokens,
            provider_name=provider,
            thinking_mode=settings.llm_thinking_mode,
        )
    raise LLMCallError(
        f"未知 provider: {provider}。可选：mock / anthropic / "
        + " / ".join(sorted(_OPENAI_COMPATIBLE_BASES))
    )
