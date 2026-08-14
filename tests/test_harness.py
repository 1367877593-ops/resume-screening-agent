"""Harness 层测试。

重点覆盖三件在真实运行中最容易悄悄出错的事：
变量缺失、修复重试、DEMO_MODE 未命中缓存时是否真的响亮失败。
"""

from __future__ import annotations

import json
from typing import List, Optional

import pytest
from pydantic import BaseModel, Field

from harness.cache import Cache, make_key
from harness.errors import CacheMissError, StructuredOutputError
from harness.llm_client import LLMResponse, MockClient, synthesize_from_schema
from harness.structured import extract_json, load_prompt, render
from harness.trace import Tracer, read_traces, summarize


class Toy(BaseModel):
    name: str
    score: float = Field(ge=0, le=100)
    tags: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class StubClient:
    """按预设脚本依次返回，用来精确控制第几次调用返回什么。"""

    provider = "stub"

    def __init__(self, script: List[str]) -> None:
        self.script = list(script)
        self.calls: List[str] = []

    def complete(self, system, user, model, json_schema=None):
        self.calls.append(user)
        text = self.script.pop(0) if self.script else "{}"
        return LLMResponse(text=text, model="stub", provider="stub")


# ---------------------------------------------------------------- 变量注入


def test_render_replaces_variables():
    assert render("你好 {{name}}", {"name": "世界"}) == "你好 世界"


def test_render_raises_on_missing_variable():
    """缺变量必须报错：把 {{jd_text}} 原样发给模型，它会礼貌地编一个出来。"""
    with pytest.raises(KeyError):
        render("{{a}} 和 {{b}}", {"a": "1"})


def test_load_prompt_reads_version_from_frontmatter():
    tpl = load_prompt("extract")
    assert tpl.version >= 1
    assert "{{resume_text}}" in tpl.body
    assert not tpl.body.startswith("---")


# ---------------------------------------------------------------- JSON 抽取


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '好的，结果如下：\n```\n{"a": 1}\n```',
        '这是结果 {"a": 1} 希望有帮助',
    ],
)
def test_extract_json_survives_common_wrappers(raw):
    assert json.loads(extract_json(raw)) == {"a": 1}


# ---------------------------------------------------------------- 缓存


def test_cache_key_changes_with_prompt_version():
    """换 prompt 版本必须换 key，否则改了 prompt 却复用旧结果，极难发现。"""
    a = make_key({"prompt": "extract", "version": 1})
    b = make_key({"prompt": "extract", "version": 2})
    assert a != b


def test_cache_roundtrip(tmp_path):
    cache = Cache(runtime_dir=tmp_path / "rt", demo_dir=tmp_path / "demo")
    assert cache.get("k") is None
    cache.put("k", '{"v": 1}')
    assert cache.get("k") == '{"v": 1}'


def test_demo_mode_never_writes_runtime_cache(tmp_path):
    cache = Cache(tmp_path / "rt", tmp_path / "demo", demo_mode=True)
    cache.put("k", "x")
    assert not (tmp_path / "rt").exists()


# ---------------------------------------------------------------- mock 合成


def test_synthesize_produces_schema_valid_instance():
    """mock provider 的产物必须真的能过 pydantic 校验，否则测不出别的东西。"""
    payload = synthesize_from_schema(Toy.model_json_schema())
    Toy.model_validate(payload)


def test_mock_client_returns_parsable_json():
    resp = MockClient().complete("s", "u", "m", json_schema=Toy.model_json_schema())
    Toy.model_validate_json(resp.text)


# ---------------------------------------------------------------- 结构化调用


def _call(monkeypatch, tmp_path, client, **overrides):
    """把 settings 指向临时目录，避免测试污染 data/runtime。"""
    from config.settings import get_settings
    from harness import structured

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "cache_dir", tmp_path / "cache", raising=False)
    monkeypatch.setattr(s, "demo_cache_dir", tmp_path / "demo", raising=False)
    for k, v in overrides.items():
        monkeypatch.setattr(s, k, v, raising=False)

    tracer = Tracer(tmp_path / "traces")
    obj = structured.call_structured(
        "extract",
        {"resume_text": "张三，三年 Python 经验", "doc_id": "d1"},
        Toy,
        client=client,
        tracer=tracer,
    )
    return obj, tracer


def test_call_structured_succeeds_first_try(monkeypatch, tmp_path):
    client = StubClient(['{"name": "张三", "score": 88, "tags": ["py"]}'])
    obj, tracer = _call(monkeypatch, tmp_path, client)

    assert obj.name == "张三" and obj.score == 88
    rows = read_traces(tracer.trace_dir)
    assert rows[-1]["ok"] is True and rows[-1]["repair_attempts"] == 0


def test_call_structured_repairs_invalid_output(monkeypatch, tmp_path):
    """第一次给了越界的 score，回灌报错后第二次修对 —— 这是幻觉/格式错误处理的核心路径。"""
    client = StubClient(
        [
            '{"name": "张三", "score": 999}',            # score 超出 le=100
            '{"name": "张三", "score": 88, "tags": []}',  # 修正
        ]
    )
    obj, tracer = _call(monkeypatch, tmp_path, client)

    assert obj.score == 88
    # 第二次调用的 prompt 里必须带上具体的校验报错，而不是笼统的「格式不对」
    assert "上一次输出有误" in client.calls[1]
    assert "score" in client.calls[1]

    stats = summarize(read_traces(tracer.trace_dir))
    assert stats["first_try_success_rate"] == 0.0   # 一次没成
    assert stats["final_success_rate"] > 0          # 但最终成了


def test_call_structured_raises_after_exhausting_repairs(monkeypatch, tmp_path):
    client = StubClient(["{}"] * 5)
    with pytest.raises(StructuredOutputError):
        _call(monkeypatch, tmp_path, client)


def test_cache_hit_skips_second_call(monkeypatch, tmp_path):
    """阶段 0 的完成标志：第二次同样的调用必须命中缓存，不再打模型。"""
    client = StubClient(['{"name": "张三", "score": 88}'])
    _call(monkeypatch, tmp_path, client)
    assert len(client.calls) == 1

    _call(monkeypatch, tmp_path, client)   # 脚本已空，若真的再调会拿到 "{}" 而失败
    assert len(client.calls) == 1


def test_demo_mode_raises_on_cache_miss(monkeypatch, tmp_path):
    """DEMO_MODE 未命中缓存必须响亮失败，绝不静默回退到真实调用。"""
    client = StubClient(['{"name": "张三", "score": 88}'])
    with pytest.raises(CacheMissError) as exc:
        _call(monkeypatch, tmp_path, client, demo_mode=True)

    assert client.calls == []                  # 一次真实调用都没发生
    assert "DEMO_MODE" in str(exc.value)
