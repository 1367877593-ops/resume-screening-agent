"""安全配置 DeepSeek 实时模式。

API Key 通过 getpass 在终端隐藏输入，不出现在命令行参数、shell 历史或输出中。
生成的 .env 权限为 0600，并且已由仓库 .gitignore 排除。
"""

from __future__ import annotations

import getpass
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _validate_key(api_key: str) -> None:
    if len(api_key) < 16 or any(ch.isspace() for ch in api_key):
        raise ValueError("Key 长度异常或包含空白字符，请重新复制官方 API Key。")


def _content(api_key: str) -> str:
    return (
        "# 本文件仅保存在本机，已被 .gitignore 排除。\n"
        "LLM_PROVIDER=deepseek\n"
        f"LLM_API_KEY={api_key}\n"
        "LLM_BASE_URL=https://api.deepseek.com\n"
        "LLM_MODEL=deepseek-v4-pro\n"
        "LLM_MODEL_CHEAP=deepseek-v4-flash\n"
        "LLM_THINKING_MODE=disabled\n"
        "LLM_MAX_OUTPUT_TOKENS=8192\n"
        "DEMO_MODE=0\n"
        "CACHE_ENABLED=1\n"
        "DB_PATH=data/runtime/app.db\n"
        "TRACE_DIR=data/runtime/traces\n"
        "LESSONS_PATH=data/runtime/lessons.jsonl\n"
        "LLM_TIMEOUT_SECONDS=120\n"
        "LLM_MAX_RETRIES=3\n"
    )


def main() -> None:
    print("将配置 DeepSeek V4 Pro 实时模式。Key 输入时不会显示。")
    if ENV_PATH.exists():
        answer = input("检测到已有 .env，是否覆盖？[y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消，原 .env 未修改。")
            return

    api_key = getpass.getpass("请粘贴 DeepSeek API Key：").strip()
    _validate_key(api_key)

    runtime_dir = ROOT / "data" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="env-", dir=runtime_dir, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_content(api_key))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, ENV_PATH)
        os.chmod(ENV_PATH, 0o600)
    finally:
        temp_path.unlink(missing_ok=True)

    print("配置完成：.env 已以 0600 权限保存，Key 未显示。")
    print("下一步运行：make live-check")


if __name__ == "__main__":
    main()
