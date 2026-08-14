"""全局配置。API Key 只从 .env 读，代码里不出现任何真实值。"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- LLM ----
    # mock provider 不发起网络请求，用于无 Key 的冒烟测试
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "deepseek-v4-pro"
    llm_model_cheap: str = "deepseek-v4-flash"
    # 结构化抽取默认关闭思考输出，减少延迟与费用；仍然使用真实 V4 Pro 推理。
    llm_thinking_mode: str = "disabled"
    # 给单次请求设置硬上限，避免异常输出持续消耗额度。
    llm_max_output_tokens: int = 8192

    # ---- 运行模式 ----
    # DEMO_MODE=1 时强制走 data/demo_cache/ 回放，未命中显式报错，绝不静默回退
    demo_mode: bool = False
    cache_enabled: bool = True

    # ---- 存储 ----
    db_path: Path = Path("data/runtime/app.db")
    trace_dir: Path = Path("data/runtime/traces")
    cache_dir: Path = Path("data/runtime/cache")
    demo_cache_dir: Path = Path("data/demo_cache")
    lessons_path: Path = Path("data/runtime/lessons.jsonl")

    # ---- 调用控制 ----
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    def resolve(self, p: Path) -> Path:
        """相对路径一律相对仓库根目录，避免受启动目录影响。"""
        return p if p.is_absolute() else ROOT / p


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@functools.lru_cache(maxsize=1)
def get_thresholds() -> Dict[str, Any]:
    """阈值表。任何判定逻辑都必须从这里取值，不得硬编码。"""
    with open(ROOT / "config" / "thresholds.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
