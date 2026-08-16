"""实时连接检查脚本。

这个脚本的全部价值就是「告诉人下一步该做什么」，所以要测的是两件事：
两档模型都被探到了，以及厂商报错被翻译成了可执行的建议。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from harness.errors import LLMCallError
from harness.llm_client import LLMResponse

ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_live_connection", ROOT / "scripts" / "check_live_connection.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load_script()


class _StubClient:
    provider = "stub"

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.seen = []

    def complete(self, system, user, model, json_schema=None):
        self.seen.append(model)
        if model in self.failing:
            raise LLMCallError(f"HTTP 404: model '{model}' does not exist")
        return LLMResponse(
            text='{"status":"ok"}', model=model, provider="stub",
            prompt_tokens=8, completion_tokens=4, latency_ms=120,
        )


@pytest.mark.parametrize(
    "message, expected",
    [
        ("HTTP 401 Unauthorized", "configure-live"),
        ("Invalid API key provided", "configure-live"),
        ("HTTP 404: model 'deepseek-v9' does not exist", "LLM_MODEL"),
        ("HTTP 402 Insufficient Balance", "余额"),
        ("Read timed out", "超时"),
        ("某种没见过的错误", "脱敏"),
    ],
)
def test_hint_translates_vendor_errors_into_next_steps(message, expected):
    assert expected in check._hint(message)


def test_probe_reports_success_without_leaking_the_reply(capsys):
    client = _StubClient()

    assert check._probe(client, "deepseek-v4-pro", "关键判断") is True

    out = capsys.readouterr().out
    assert "成功" in out and "deepseek-v4-pro" in out
    assert "status" not in out, "不应把模型回复正文打出来"


def test_probe_surfaces_the_hint_on_failure(capsys):
    client = _StubClient(failing={"bad-model"})

    assert check._probe(client, "bad-model", "快速阶段") is False

    out = capsys.readouterr().out
    assert "失败" in out
    assert "LLM_MODEL" in out, "报错没有翻译成可执行的建议"


def test_both_models_are_probed_and_cheap_failure_fails_the_check(monkeypatch):
    """只验关键模型会给出虚假信心：流水线第一步（JD 拆解）走的是快模型。

    这里让快模型探测失败，断言整个检查必须失败 —— 否则就会出现
    「live-check 通过了但 make run 第一步就死」。
    """
    client = _StubClient(failing={"cheap-model"})
    monkeypatch.setattr(check, "get_client", lambda _s: client)

    settings = check.get_settings()
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    monkeypatch.setattr(settings, "llm_api_key", "sk-not-real", raising=False)
    monkeypatch.setattr(settings, "llm_model", "pro-model", raising=False)
    monkeypatch.setattr(settings, "llm_model_cheap", "cheap-model", raising=False)
    monkeypatch.setattr(check.get_settings, "cache_clear", lambda: None)

    with pytest.raises(SystemExit) as exc:
        check.main()

    assert client.seen == ["pro-model", "cheap-model"], "快模型没有被探测"
    assert "未全部通过" in str(exc.value)


def test_identical_models_are_probed_once(monkeypatch):
    client = _StubClient()
    monkeypatch.setattr(check, "get_client", lambda _s: client)

    settings = check.get_settings()
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    monkeypatch.setattr(settings, "llm_api_key", "sk-not-real", raising=False)
    monkeypatch.setattr(settings, "llm_model", "same", raising=False)
    monkeypatch.setattr(settings, "llm_model_cheap", "same", raising=False)
    monkeypatch.setattr(check.get_settings, "cache_clear", lambda: None)

    check.main()

    assert client.seen == ["same"], "两档配成同一个模型时不该白花一次调用"
