"""三人格盲评模拟（L2 创新层）。

把「题目质量」从主观感受变成可测量信号：三个信息量不同的人格盲评作答，
用分数的相对关系反推题目是否有区分度。判定逻辑在 diagnose.py，纯代码。
"""

from checker.simulation.diagnose import diagnose
from checker.simulation.grader import grade_blind
from checker.simulation.personas import answer_as_bluffer, answer_as_expert, answer_as_resume
from checker.simulation.run import simulate_question_set

__all__ = [
    "answer_as_expert",
    "answer_as_bluffer",
    "answer_as_resume",
    "grade_blind",
    "diagnose",
    "simulate_question_set",
]
