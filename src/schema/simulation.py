"""三人格盲评模拟（L2）。

要解决的问题是：「这道面试题出得好不好」通常只能靠人主观感受，
无法进入自动化闭环。这里把它拆成一个可测量的信号 ——
让三个信息量不同的人格分别作答，再盲评打分，用三个分数的**相对关系**
反推题目质量：

- 只有真正懂的人答得上、背题党答不上  -> 这道题有区分度
- 背题党也答得上                      -> 题目在考记忆而不是能力
- 连理想专家都答不上                  -> 题目本身有问题

注意判定用的是分数之间的关系，不是绝对分。模型今天给分松一点、
明天紧一点，只要三个人格是同一次盲评里打出来的，相对关系就是稳的。
"""

from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field

# expert：领域理想专家，信息最全（题面 + JD）
# bluffer：只背过面经八股，拿不到简历，也不了解岗位
# resume：扮演候选人本人，只能依据简历里写过的东西作答
Persona = Literal["expert", "bluffer", "resume"]

# GOOD              好题
# NO_DISCRIMINATION 背题党也能答，无区分度
# OUT_OF_RANGE      有区分度，但超出这位候选人的射程
# BROKEN            理想专家都答不上，题目本身有问题
Diagnosis = Literal["GOOD", "NO_DISCRIMINATION", "OUT_OF_RANGE", "BROKEN"]

PERSONA_LABEL: Dict[str, str] = {
    "expert": "理想专家",
    "bluffer": "背题党",
    "resume": "简历人格",
}

DIAGNOSIS_LABEL: Dict[str, str] = {
    "GOOD": "好题",
    "NO_DISCRIMINATION": "无区分度",
    "OUT_OF_RANGE": "超出射程",
    "BROKEN": "题目有问题",
}


class SimAnswer(BaseModel):
    """某个人格对某道题的作答。"""

    question_id: str
    persona: Persona
    answer: str


class SimScore(BaseModel):
    """盲评给出的分数。

    `persona` 不是阅卷官填的 —— 阅卷官只看到 A / B / C 标签，
    映射回人格这一步在代码里完成，见 grader.py。
    """

    question_id: str
    persona: Persona
    score: float = Field(ge=0, le=100)
    reason: str = ""


class QuestionDiagnosis(BaseModel):
    """一道题的三分对照结论。由纯代码依据阈值算出，可单测。"""

    question_id: str
    expert_score: float
    bluffer_score: float
    resume_score: float
    diagnosis: Diagnosis
    detail: str

    @property
    def is_problem(self) -> bool:
        return self.diagnosis != "GOOD"


class SimulationReport(BaseModel):
    resume_id: str
    answers: List[SimAnswer] = Field(default_factory=list)
    scores: List[SimScore] = Field(default_factory=list)
    diagnoses: List[QuestionDiagnosis] = Field(default_factory=list)
    # 本次判定用的阈值，随报告一起带出去。
    # 一是让报告自解释（同一份报告换阈值会得到不同结论）；
    # 二是 app/ 只能 import pipeline 和 schema，拿不到 config，
    # 而热力图必须按这组阈值染色才能把「背题党分高 = 坏事」表达出来。
    thresholds: Dict[str, float] = Field(default_factory=dict)

    def by_diagnosis(self) -> Dict[str, int]:
        """各档诊断的题目数，直接进评测结果与 UI 概览。"""
        out: Dict[str, int] = {}
        for d in self.diagnoses:
            out[d.diagnosis] = out.get(d.diagnosis, 0) + 1
        return out

    def problem_questions(self) -> List[QuestionDiagnosis]:
        return [d for d in self.diagnoses if d.is_problem]
