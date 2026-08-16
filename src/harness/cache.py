"""输入 hash -> 结果 的磁盘缓存。

这个模块属于 L1 而不是「后期优化项」，原因有三个：
1. 开发期反复调试同一份简历，没有缓存会烧掉大量 token；
2. 修订流程要求「只对变更对象重跑校验」，未变更部分复用上轮结论就靠它；
3. `make demo` 的无 Key 回放完全建立在它之上。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def make_key(parts: Dict[str, Any]) -> str:
    """对调用的全部输入求 hash。

    键里必须包含 model 与 prompt version —— 换模型或改 prompt 后
    复用旧结果会让人误以为改动生效了，是很难发现的一类错误。
    """
    canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cache:
    """两层缓存：只读的 demo 层（提交进仓库）+ 可写的 runtime 层。"""

    def __init__(
        self,
        runtime_dir: Path,
        demo_dir: Path,
        enabled: bool = True,
        demo_mode: bool = False,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.demo_dir = Path(demo_dir)
        self.enabled = enabled
        self.demo_mode = demo_mode

    def _paths(self, key: str):
        """demo 层优先。DEMO_MODE 下只看 demo 层，保证演示结果可复现。"""
        if self.demo_mode:
            return [self.demo_dir / f"{key}.json"]
        return [self.demo_dir / f"{key}.json", self.runtime_dir / f"{key}.json"]

    def get(self, key: str) -> Optional[str]:
        if not self.enabled and not self.demo_mode:
            return None
        for p in self._paths(key):
            if p.exists():
                return p.read_text(encoding="utf-8")
        return None

    def put(self, key: str, value: str) -> None:
        """只写 runtime 层。demo 层由 `make demo-cache` 显式生成，不会被跑一次就污染。

        写临时文件再 `os.replace` 原子替换，不直接写目标路径：候选人是并行筛选的，
        两份内容相同的简历会算出同一个 key，两个线程同时写时，直接写会让另一个线程
        读到只写了一半的 JSON。`os.replace` 在同一文件系统上是原子的，读到的要么是
        旧内容要么是新内容，不会是半截。
        """
        if self.demo_mode or not self.enabled:
            return
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        target = self.runtime_dir / f"{key}.json"
        fd, tmp = tempfile.mkstemp(dir=self.runtime_dir, prefix=f".{key[:16]}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(value)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
