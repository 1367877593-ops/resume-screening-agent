"""反思飞轮：把 Checker 发现的问题沉淀成经验，下次生成前按岗位检索注入。

设计上只有一条硬约束：**注入内容必须稳定**。经验条目里带命中次数和时间戳，
但渲染进 prompt 的只有去重排序后的告诫文本 —— 否则每跑一次 prompt 就变一次，
缓存键全部漂移，无 Key 回放永远命中不了。
"""

from flywheel.lessons import load_all, record
from flywheel.retrieve import lessons_block, retrieve

__all__ = ["record", "load_all", "retrieve", "lessons_block"]
