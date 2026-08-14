"""所有结构化输出的唯一入口。

`call_structured` 把「让模型返回一个能用的对象」这件事的全部脏活收在一处：
载入 prompt -> 变量注入 -> 附加 JSON Schema -> 调用 -> 抽取 JSON -> Pydantic 校验
-> 失败则把校验报错回灌给模型重试 -> 全程落 trace -> 命中缓存则跳过以上全部。

业务代码只写一行 `call_structured("extract", {...}, ExtractedResume)`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from config.settings import ROOT, get_settings
from harness.cache import Cache, make_key
from harness.errors import CacheMissError, StructuredOutputError
from harness.llm_client import BaseClient, get_client
from harness.trace import Tracer

T = TypeVar("T", bound=BaseModel)

PROMPT_DIR = ROOT / "prompts"

# 系统提示保持极短：具体任务描述属于 prompts/*.md，不该散落在代码里
_SYSTEM = "你是严谨的信息抽取与评估助手。只输出 JSON，不要输出任何解释性文字。"

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_VAR = re.compile(r"\{\{(\w+)\}\}")


@dataclass
class PromptTemplate:
    name: str
    version: int
    body: str


def load_prompt(name: str) -> PromptTemplate:
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"找不到 prompt：{path}")
    raw = path.read_text(encoding="utf-8")

    meta: Dict[str, Any] = {}
    m = _FRONTMATTER.match(raw)
    body = raw
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = raw[m.end():]
    return PromptTemplate(name=name, version=int(meta.get("version", 1)), body=body.strip())


def render(template: str, variables: Dict[str, Any]) -> str:
    """{{var}} 注入。

    缺变量时直接报错而不是留下字面量 —— 把 "{{jd_text}}" 原样发给模型，
    它多半会礼貌地编一个 JD 出来，这种错误极难在输出里看出来。
    """
    missing = {v for v in _VAR.findall(template) if v not in variables}
    if missing:
        raise KeyError(f"prompt 变量缺失：{sorted(missing)}")
    return _VAR.sub(lambda m: str(variables[m.group(1)]), template)


def extract_json(text: str) -> str:
    """从模型输出里挖出 JSON。

    即使要求了「只输出 JSON」，模型仍可能裹一层 ```json 或加一句寒暄，
    所以这里按 代码块 -> 首尾花括号 的顺序兜底。
    """
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text.strip()


def _build_user_message(body: str, schema: Dict[str, Any]) -> str:
    return (
        f"{body}\n\n"
        "## 输出格式\n"
        "严格输出符合以下 JSON Schema 的 JSON，不要输出 Schema 本身，"
        "不要包含任何解释文字或 Markdown 代码块标记。\n\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


_default_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    global _default_tracer
    if _default_tracer is None:
        s = get_settings()
        _default_tracer = Tracer(s.resolve(s.trace_dir))
    return _default_tracer


def call_structured(
    prompt_name: str,
    variables: Dict[str, Any],
    output_model: Type[T],
    max_repair: int = 2,
    client: Optional[BaseClient] = None,
    tracer: Optional[Tracer] = None,
    model: Optional[str] = None,
) -> T:
    settings = get_settings()
    tracer = tracer or get_tracer()
    client = client or get_client(settings)
    model = model or settings.llm_model

    tpl = load_prompt(prompt_name)
    schema = output_model.model_json_schema()
    user = _build_user_message(render(tpl.body, variables), schema)

    cache = Cache(
        runtime_dir=settings.resolve(settings.cache_dir),
        demo_dir=settings.resolve(settings.demo_cache_dir),
        enabled=settings.cache_enabled,
        demo_mode=settings.demo_mode,
    )
    key = make_key(
        {
            "provider": client.provider,
            "model": model,
            "prompt": prompt_name,
            "version": tpl.version,
            "user": user,
            "schema": schema.get("title", output_model.__name__),
        }
    )

    cached = cache.get(key)
    if cached is not None:
        obj = output_model.model_validate_json(cached)
        tracer.record(
            event="structured_call", prompt=prompt_name, prompt_version=tpl.version,
            model=model, provider=client.provider, cache_hit=True, ok=True,
            repair_attempts=0, cache_key=key,
        )
        return obj

    if settings.demo_mode:
        # 刻意不回退到真实调用，理由见 harness/errors.py:CacheMissError
        raise CacheMissError(
            f"DEMO_MODE=1 但缓存未命中（prompt={prompt_name} v{tpl.version}, key={key[:12]}…）。\n"
            "演示数据只覆盖 data/samples/ 里的样例输入。"
            "要处理自己的数据请在 .env 中设置 DEMO_MODE=0 并配置 LLM_API_KEY。"
        )

    last_error = ""
    current_user = user

    for repair_attempt in range(max_repair + 1):
        resp = client.complete(_SYSTEM, current_user, model, json_schema=schema)
        raw = extract_json(resp.text)
        try:
            obj = output_model.model_validate_json(raw)
        except (ValidationError, ValueError) as e:
            last_error = str(e)[:1500]
            tracer.record(
                event="structured_call", prompt=prompt_name, prompt_version=tpl.version,
                model=model, provider=client.provider, cache_hit=False, ok=False,
                repair_attempts=repair_attempt, error=last_error[:500],
                prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
                latency_ms=resp.latency_ms, http_attempts=resp.attempts, cache_key=key,
            )
            if repair_attempt == max_repair:
                break
            # 把校验报错原文回灌 —— 模型对具体的 pydantic 错误信息响应得相当好，
            # 比笼统说一句「格式不对，请重来」有效得多
            current_user = (
                f"{user}\n\n## 上一次输出有误\n你上次返回的内容是：\n{resp.text[:2000]}\n\n"
                f"校验报错：\n{last_error}\n\n请修正后重新输出完整 JSON。"
            )
            continue

        tracer.record(
            event="structured_call", prompt=prompt_name, prompt_version=tpl.version,
            model=model, provider=client.provider, cache_hit=False, ok=True,
            repair_attempts=repair_attempt,
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms, http_attempts=resp.attempts, cache_key=key,
        )
        cache.put(key, obj.model_dump_json())
        return obj

    raise StructuredOutputError(
        f"prompt={prompt_name} 修复重试 {max_repair} 次后仍无法得到合法的 "
        f"{output_model.__name__}。最后一次校验报错：\n{last_error}"
    )
