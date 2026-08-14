"""Harness 层的异常。业务代码只需要认这几个，不必知道底层用的哪家厂商。"""

from __future__ import annotations


class HarnessError(Exception):
    """Harness 层所有异常的基类。"""


class LLMCallError(HarnessError):
    """网络、鉴权、限流等调用层失败，已用尽重试。"""


class StructuredOutputError(HarnessError):
    """模型输出无法解析成目标 schema，且修复重试已用尽。"""


class CacheMissError(HarnessError):
    """DEMO_MODE 下缓存未命中。

    这里刻意抛错而不是回退到真实调用：静默回退会在评审者的机器上
    悄悄发起一次注定失败的请求（他们没有 Key），或者更糟 —— 让人
    以为看到的是演示数据，其实是实时生成的。宁可响亮地失败。
    """
