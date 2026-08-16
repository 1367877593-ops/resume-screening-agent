"""为仓库内置样例生成可复现的无 Key Demo 缓存。

这里保存的是经过人工核对的结构化响应夹具，不调用任何在线模型。真实运行仍然
走 Harness 中的模型客户端；本脚本只负责让评审者在没有 API Key 时稳定复现
完整闭环。修改样例、Prompt 版本或输出 Schema 后应重新运行本脚本并跑全量测试。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from checker.simulation.grader import label_map  # noqa: E402
from config.settings import get_settings  # noqa: E402
from harness import structured  # noqa: E402
from harness.llm_client import LLMResponse  # noqa: E402
from ingest.loader import load_text  # noqa: E402
from pipeline import api  # noqa: E402


def span(doc_id: str, text: str) -> dict:
    return {"doc_id": doc_id, "text": text}


def rubric() -> list[dict]:
    return [
        {"level": "优秀", "min_score": 85, "criteria": "说明具体方法、取舍、验证数据与失败案例"},
        {"level": "合格", "min_score": 60, "criteria": "能讲清本人做法与基本结果，但量化验证不完整"},
        {"level": "不合格", "min_score": 0, "criteria": "只复述概念，无法说明个人贡献或证据"},
    ]


def jd_payload() -> dict:
    return {
        "title": "AI 产品实习生（简历智能筛选方向）",
        "requirements": [
            {"requirement_id": "R1", "text": "本科及以上学历", "weight": 8, "is_hard": True, "category": "学历"},
            {"requirement_id": "R2", "text": "计算机、人工智能、统计学等相关专业", "weight": 6, "is_hard": False, "category": "学历"},
            {"requirement_id": "R3", "text": "熟悉 Python 并能独立编写数据处理脚本", "weight": 8, "is_hard": False, "category": "技能"},
            {"requirement_id": "R4", "text": "了解大语言模型基本原理", "weight": 6, "is_hard": False, "category": "技能"},
            {"requirement_id": "R5", "text": "具备 Prompt 工程实践经验", "weight": 7, "is_hard": False, "category": "经验"},
            {"requirement_id": "R6", "text": "有结构化输出、RAG 或 Agent 相关项目经验", "weight": 5, "is_hard": False, "category": "项目"},
            {"requirement_id": "R7", "text": "具备良好的文档撰写能力", "weight": 4, "is_hard": False, "category": "其他"},
            {"requirement_id": "R8", "text": "每周到岗不少于 4 天", "weight": 7, "is_hard": True, "category": "其他"},
            {"requirement_id": "R9", "text": "实习期不少于 3 个月", "weight": 7, "is_hard": True, "category": "其他"},
            {"requirement_id": "R10", "text": "有向量数据库使用经验", "weight": 3, "is_hard": False, "category": "技能"},
            {"requirement_id": "R11", "text": "有开源项目或技术博客", "weight": 2, "is_hard": False, "category": "其他"},
        ],
    }


def resume_a_payload(doc_id: str) -> dict:
    return {
        "resume_id": doc_id,
        "candidate_name": "李明",
        "educations": [{
            "school": "华中科技大学", "degree": "本科", "major": "计算机科学与技术",
            "start": "2022.09", "end": "2026.06",
            "evidence": [span(doc_id, "2022.09 - 2026.06  华中科技大学  计算机科学与技术  本科")],
        }],
        "work_experiences": [{
            "company": "某科技公司", "title": "AI 产品实习生",
            "start": "2025.07", "end": "2025.09",
            "summary": "参与智能客服需求梳理、Prompt 迭代和评测集建设",
            "evidence": [span(doc_id, "参与智能客服模块的需求梳理，独立负责意图识别 Prompt 的编写与迭代")],
        }],
        "projects": [
            {
                "name": "校园问答助手", "role": "技术负责人",
                "description": "基于 LangChain 与 Chroma 的检索问答系统",
                "tech_stack": ["Python", "LangChain", "Chroma", "RAG"],
                "evidence": [span(doc_id, "基于 LangChain 与 Chroma 搭建了面向校内规章制度的检索问答系统")],
            },
            {
                "name": "电商评论情感分析", "description": "评论清洗与 BERT 三分类",
                "tech_stack": ["Python", "pandas", "BERT"],
                "evidence": [span(doc_id, "使用 Python 与 pandas 清洗二十万条评论数据，微调 BERT 模型完成情感三分类")],
            },
        ],
        "skills": [
            {"name": "Python", "level": "熟悉", "evidence": [span(doc_id, "熟悉 Python，掌握 pandas、FastAPI")]},
            {"name": "Prompt 工程", "evidence": [span(doc_id, "了解大语言模型基本原理，有 Prompt 工程实践经验")]},
            {"name": "Chroma", "evidence": [span(doc_id, "使用过 Chroma 向量数据库")]},
        ],
    }


def resume_b_payload(doc_id: str) -> dict:
    return {
        "resume_id": doc_id,
        "candidate_name": "王芳",
        "educations": [{
            "school": "某职业技术学院", "degree": "大专", "major": "市场营销",
            "start": "2023.09", "end": "2026.06",
            "evidence": [span(doc_id, "2023.09 - 2026.06  某职业技术学院  市场营销  大专")],
        }],
        "work_experiences": [{
            "company": "某广告公司", "title": "新媒体运营",
            "start": "2024.03", "end": "2025.06",
            "summary": "公众号和短视频账号运营",
            "evidence": [span(doc_id, "负责公众号与短视频账号的日常运营，撰写推文并策划活动")],
        }],
        "projects": [{
            "name": "用 ChatGPT 辅助生成营销文案",
            "description": "用 ChatGPT 生成初稿后人工润色",
            "tech_stack": ["ChatGPT"],
            "evidence": [span(doc_id, "在日常工作中使用 ChatGPT 生成推文初稿，再人工润色")],
        }],
        "skills": [
            {"name": "Office", "level": "熟练", "evidence": [span(doc_id, "熟练使用 Office、剪映、Photoshop")]},
            {"name": "AI 工具", "evidence": [span(doc_id, "日常使用 ChatGPT、Midjourney")]},
        ],
    }


def match_a_payload(doc_id: str) -> dict:
    evidence = {
        "edu": "2022.09 - 2026.06  华中科技大学  计算机科学与技术  本科",
        "python": "熟悉 Python，掌握 pandas、FastAPI",
        "llm": "了解大语言模型基本原理，有 Prompt 工程实践经验",
        "prompt": "设计了三版 Prompt 并做了效果对比",
        "rag": "基于 LangChain 与 Chroma 搭建了面向校内规章制度的检索问答系统",
        "blog": "个人技术博客持续更新中，已发表 15 篇大模型相关文章",
        "availability": "每周可到岗 5 天，可实习 6 个月",
        "vector": "使用过 Chroma 向量数据库",
    }
    rows = [
        ("R1", "YES", 95, "本科在读，满足学历门槛", "edu"),
        ("R2", "YES", 95, "计算机科学与技术专业", "edu"),
        ("R3", "YES", 95, "明确熟悉 Python 并使用 pandas", "python"),
        ("R4", "YES", 90, "明确了解大语言模型基本原理", "llm"),
        ("R5", "YES", 95, "有多版 Prompt 设计和效果对比经验", "prompt"),
        ("R6", "YES", 95, "有完整 RAG 检索问答项目", "rag"),
        ("R7", "YES", 88, "持续撰写大模型技术博客", "blog"),
        ("R8", "YES", 100, "每周可到岗五天", "availability"),
        ("R9", "YES", 100, "可实习六个月", "availability"),
        ("R10", "YES", 95, "实际使用过 Chroma", "vector"),
        ("R11", "YES", 90, "已有十五篇技术博客", "blog"),
    ]
    return {"verdicts": [
        {"requirement_id": rid, "satisfied": status, "score": score, "reason": reason,
         "evidence": [span(doc_id, evidence[key])]}
        for rid, status, score, reason, key in rows
    ]}


def match_b_payload(doc_id: str) -> dict:
    chatgpt = "在日常工作中使用 ChatGPT 生成推文初稿，再人工润色"
    writing = "负责公众号与短视频账号的日常运营，撰写推文并策划活动"
    rows = [
        {"requirement_id": "R1", "satisfied": "NO", "score": 0, "reason": "最高学历为大专", "evidence": []},
        {"requirement_id": "R2", "satisfied": "NO", "score": 0, "reason": "专业为市场营销", "evidence": []},
        {"requirement_id": "R3", "satisfied": "NO", "score": 5, "reason": "未体现 Python 能力", "evidence": []},
        {"requirement_id": "R4", "satisfied": "PARTIAL", "score": 35, "reason": "使用过 ChatGPT，但未体现原理理解", "evidence": [span(doc_id, chatgpt)]},
        {"requirement_id": "R5", "satisfied": "PARTIAL", "score": 40, "reason": "有提示 AI 生成文案的实践但无系统迭代", "evidence": [span(doc_id, chatgpt)]},
        {"requirement_id": "R6", "satisfied": "NO", "score": 0, "reason": "没有相关工程项目", "evidence": []},
        {"requirement_id": "R7", "satisfied": "YES", "score": 80, "reason": "有持续撰写推文的经历", "evidence": [span(doc_id, writing)]},
        {"requirement_id": "R8", "satisfied": "NO", "score": 0, "reason": "每周只能到岗两天", "evidence": []},
        {"requirement_id": "R9", "satisfied": "NO", "score": 10, "reason": "未说明可实习三个月以上", "evidence": []},
        {"requirement_id": "R10", "satisfied": "NO", "score": 0, "reason": "未使用向量数据库", "evidence": []},
        {"requirement_id": "R11", "satisfied": "NO", "score": 0, "reason": "未体现开源项目或技术博客", "evidence": []},
    ]
    return {"verdicts": rows}


def questions_payload(doc_id: str) -> dict:
    cases = [
        ("Q1", "准确率从 61% 到 84% 的提升如何拆分到具体改动，并怎样排除评测集波动？", "效果归因", "HARD", "R5", "最终答案准确率从 61% 提升到 84%"),
        ("Q2", "三版 Prompt 分别改变了什么变量？请给出你保留最终版本的比较证据。", "Prompt 实验设计", "MEDIUM", "R5", "设计了三版 Prompt 并做了效果对比"),
        ("Q3", "文档解析、切块和向量化入库中，你遇到的最严重数据质量问题是什么？", "RAG 数据治理", "MEDIUM", "R6", "使用 Python 完成文档解析、切块与向量化入库"),
        ("Q4", "为什么选择 Chroma？如果数据规模扩大一百倍，你会重新评估哪些指标？", "向量库选型", "HARD", "R10", "使用过 Chroma 向量数据库"),
        ("Q5", "两千余次提问是怎样统计的？其中多少被人工抽检，失败样本如何分类？", "线上指标可信度", "MEDIUM", "R6", "累计服务两千余次提问"),
        ("Q6", "200 条人工评测集如何采样、标注和处理分歧，怎样避免只覆盖简单意图？", "评测集建设", "HARD", "R5", "建立了一套包含 200 条样本的人工评测集"),
        ("Q7", "意图识别准确率提升 12 个百分点时，基线、指标口径和你的个人贡献分别是什么？", "业务效果验证", "MEDIUM", "R5", "推动意图识别准确率提升 12 个百分点"),
        ("Q8", "在二十万条评论清洗中，请举一个 pandas 规则误伤数据的例子和修复办法。", "Python 数据处理", "MEDIUM", "R3", "使用 Python 与 pandas 清洗二十万条评论数据"),
        ("Q9", "如果 FastAPI 服务出现突发超时，你会怎样区分模型、检索和接口层问题？", "服务故障诊断", "EASY", "R3", "熟悉 Python，掌握 pandas、FastAPI"),
        ("Q10", "请挑一篇技术博客说明你如何把复杂方案写成可供工程团队执行的文档。", "技术表达", "EASY", "R7", "已发表 15 篇大模型相关文章"),
    ]
    return {"questions": [
        {
            "question_id": qid, "text": text, "skill_point": skill,
            "difficulty": difficulty, "rubric": rubric(),
            "source_requirement_ids": [requirement], "evidence": [span(doc_id, quote)],
        }
        for qid, text, skill, difficulty, requirement, quote in cases
    ]}


def followups_payload(doc_id: str) -> dict:
    points = [
        ("P1", "准确率提升的归因过程没有展开", "最终答案准确率从 61% 提升到 84%"),
        ("P2", "两千余次服务量的统计口径不明确", "累计服务两千余次提问"),
        ("P3", "推动十二个百分点提升时个人职责边界不清", "推动意图识别准确率提升 12 个百分点"),
    ]
    return {
        "ambiguity_points": [
            {"point_id": pid, "description": description, "evidence": [span(doc_id, quote)]}
            for pid, description, quote in points
        ],
        "questions": [
            {"followup_id": "F1", "text": "请按改动顺序说明 23 个百分点分别来自哪里，并给出对照实验。", "ambiguity_point_id": "P1", "intent": "确认提升归因是否有可复核证据"},
            {"followup_id": "F2", "text": "两千余次指请求数、会话数还是独立用户数？异常请求是否被剔除？", "ambiguity_point_id": "P2", "intent": "确认线上规模指标的统计口径"},
            {"followup_id": "F3", "text": "十二个百分点提升中哪些工作由你独立完成，哪些由算法或工程同事完成？", "ambiguity_point_id": "P3", "intent": "确认候选人的真实职责与贡献"},
        ],
    }


# ------------------------------------------------------------------ 三人格盲评
#
# 每道题给三份作答和三个分数。Q9 是故意埋的反例：它问的是通用故障排查思路，
# 背题党靠面经就能答得像模像样，因此盲评会给出高分，三分对照据此判定
# 「无区分度」。Demo 因此展示的不是一份完美结果，而是这套机制确实能抓到
# 自己生成的弱题 —— 那才是这个模块存在的理由。

SIM_ANSWERS = {
    "Q1": (
        "先做改动切片：检索召回、重排、Prompt 各自单独上线一次，用同一批评测集测差值。再用自助采样给 23 个百分点算置信区间，区间跨 0 的部分不算数。",
        "准确率提升要从数据质量、模型选型、Prompt 优化三方面归因，同时要做好 A/B 测试和消融实验，确保结果具有统计显著性。",
        "主要是把切块从固定长度改成按条款切，再加了重排。具体每部分贡献多少我当时没有分开测，是一起上线后看的整体提升。",
    ),
    "Q2": (
        "三版分别改了角色设定、few-shot 数量和输出约束。只改一个变量，固定同一批 200 条样本对比，最终版赢在输出格式违规率从 12% 降到 1%。",
        "Prompt 迭代一般是从零样本到少样本再到思维链，要注意角色扮演、任务分解和输出格式约束，通过对比实验选出最优版本。",
        "第一版直接问，第二版加了几个例子，第三版要求按固定字段输出。第三版最稳定，主要是格式不会跑偏，我保留了它。",
    ),
    "Q3": (
        "最严重的是扫描件 PDF 抽出空文本却被当成有效文档入库，检索时污染结果。后来在入库前加了字符数下限和乱码率检查，不合格的直接拦下并报警。",
        "RAG 的数据质量问题主要包括文档解析不完整、切块粒度不合理、向量化效果差等，需要建立完善的数据清洗和质量监控体系。",
        "规章制度文档里有很多表格，直接解析会把表格拆散，导致条款对不上。我改成按条款标题切块之后好了很多。",
    ),
    "Q4": (
        "选 Chroma 是因为本地起得快、无需运维，数据量只有几万条。扩大一百倍要重新看写入吞吐、过滤查询的延迟和内存占用，这三项会先撑不住，届时换 Milvus 或 pgvector。",
        "向量数据库选型要考虑性能、扩展性、易用性和成本。Chroma 适合快速原型，大规模场景可以考虑 Milvus、Pinecone 等专业方案。",
        "当时选 Chroma 主要是因为它轻量、能本地跑，装起来快。数据规模扩大的情况我没有实际测过。",
    ),
    "Q5": (
        "两千余次是网关侧的请求数去掉健康检查和我自己的调试流量。人工抽检了其中 200 条，失败样本按检索没召回、召回了但答错、拒答三类归档。",
        "线上指标统计要明确口径，区分请求数、会话数和用户数，同时要做好埋点和日志采集，定期进行数据校验和人工抽样检查。",
        "两千多次是后台日志统计的请求数。抽检的部分我记得是随机看了一些答得不好的，没有严格按比例做分类统计。",
    ),
    "Q6": (
        "按真实问题的意图分布分层采样，避免全是简单事实题。两个人独立标注，不一致的第三人裁决，分歧率控制在 8% 以内，并保留 20% 的边界样本。",
        "评测集建设要保证样本的代表性和多样性，采用分层抽样方法，多人标注取一致性，同时要覆盖各种边界情况和长尾场景。",
        "200 条是我从历史提问里挑的，尽量覆盖了不同类型的问题。标注主要是我自己做的，没有做多人交叉标注。",
    ),
    "Q7": (
        "基线是上线前一周的线上意图识别准确率 71%。口径是人工复核的准确率，不是模型自评。我负责 Prompt 与评测集，模型微调是算法同事做的，12 个点是两者叠加的结果。",
        "业务效果验证需要设立明确的基线和对照组，统计口径要保持一致，同时要区分个人贡献和团队贡献，用数据说话。",
        "提升 12 个百分点是团队一起做的，我主要负责意图识别 Prompt 的编写和迭代，还有评测集的搭建。",
    ),
    "Q8": (
        "去重规则按「用户 ID + 文本」哈希，结果把同一用户对不同商品的相同短评（如「不错」）全删了，损失了三万条有效样本。后来把商品 ID 加进哈希键，并对短文本单独放宽。",
        "pandas 数据清洗常见问题包括去重逻辑不当、缺失值处理不合理、类型转换错误等，需要在清洗前后做好数据量和分布的对比校验。",
        "清洗二十万条评论时主要处理了重复和空值。误伤的具体例子我印象不深了，当时是边跑边看结果调的规则。",
    ),
    "Q9": (
        "先看网关的分层耗时埋点：接口层看 QPS 和连接池，检索层看向量库的 P99，模型层看上游返回时间。三段里哪段的 P99 抬起来就是哪段的问题，没有埋点就先补埋点再谈定位。",
        "服务超时排查要分层定位，先看监控和日志，从接口层、业务层到依赖服务逐层排查，结合链路追踪工具分析各环节耗时，定位瓶颈点后针对性优化。",
        "我会先看日志和监控，判断是模型调用慢还是检索慢。FastAPI 这块我用得不多，主要是搭接口，深入的性能排查没做过。",
    ),
    "Q10": (
        "写《RAG 检索召回踩坑》那篇时，我把方案拆成「问题现象 - 定位过程 - 改动 - 验证数据」四段，每段都给可复制的配置片段，让读者不用问我就能照着跑一遍。",
        "技术文档写作要结构清晰、层次分明，使用图表辅助说明，注意读者视角，把复杂问题拆解成易于理解的模块，并提供可执行的步骤。",
        "我的博客主要是记录学习过程，会把原理讲一遍再贴代码。面向工程团队执行的文档写得不多，这方面经验还比较少。",
    ),
}

# (专家, 背题党, 简历人格)。阈值见 config/thresholds.yaml：
# expert_pass=70 / bluffer_max=50 / resume_pass=60
SIM_SCORES = {
    "Q1": (92, 35, 68),
    "Q2": (90, 38, 72),
    "Q3": (88, 32, 75),
    "Q4": (91, 42, 65),
    "Q5": (89, 36, 62),
    "Q6": (93, 40, 61),
    "Q7": (90, 34, 74),
    "Q8": (88, 30, 63),
    "Q9": (86, 71, 66),   # 背题党 71 > 50：靠面经即可作答，判为无区分度
    "Q10": (87, 45, 70),
}

SIM_REASONS = {
    "expert": "给出了具体做法、判断依据与量化结果，落在优秀档",
    "bluffer": "只有正确但空泛的通用说法，没有任何本人做过的痕迹，落在不合格档",
    "resume": "能讲清本人做法与基本结果，但量化验证不完整，落在合格档",
}


def persona_answers_payload(persona_index: int) -> dict:
    """三个人格的作答。persona_index: 0=专家 1=背题党 2=简历人格。"""
    return {
        "answers": [
            {"question_id": qid, "answer": answers[persona_index]}
            for qid, answers in SIM_ANSWERS.items()
        ]
    }


def grader_payload() -> dict:
    """盲评结果。

    标签不能手写死：`grade_blind` 每道题都按 question_id 派生一个独立的
    标签映射，夹具必须用同一个函数反推，否则分数会记到错误的人格头上。
    """
    scores = []
    for qid, (expert, bluffer, resume) in SIM_SCORES.items():
        per_persona = {"expert": expert, "bluffer": bluffer, "resume": resume}
        for label, persona in label_map(qid, sorted(per_persona)).items():
            reason = SIM_REASONS[persona]
            if persona == "bluffer" and qid == "Q9":
                reason = "虽无个人经历，但分层排查的通用思路已覆盖题目要点，落在合格档"
            scores.append(
                {
                    "question_id": qid,
                    "label": label,
                    "score": per_persona[persona],
                    "reason": reason,
                }
            )
    return {"scores": scores}


class FixtureClient:
    """按主状态机的调用顺序返回人工核对过的样例响应。"""

    provider = "demo"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, system, user, model, json_schema=None):
        if not self.payloads:
            raise AssertionError("Demo 响应夹具已用尽，状态机出现了未记录的新调用")
        self.calls += 1
        payload = self.payloads.pop(0)
        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model=model,
            provider=self.provider,
        )


def main() -> None:
    jd_text, resumes = api.sample_inputs()
    jd_doc = load_text(jd_text, filename="jd")
    resume_docs = [
        load_text(data.decode("utf-8"), filename=name)
        for name, data in resumes
    ]
    if len(resume_docs) != 2:
        raise AssertionError("内置 Demo 目前要求恰好两份样例简历")
    a_id, b_id = (doc.doc_id for doc in resume_docs)

    final_questions = questions_payload(a_id)
    first_question_attempt = {"questions": final_questions["questions"][:9]}
    revised_question_set = {
        "revised": {
            "resume_id": a_id,
            "jd_id": jd_doc.doc_id,
            "questions": final_questions["questions"],
        },
        "notes": [{
            "issue_code": "Q_COUNT_LT_MIN",
            "action": "FIXED",
            "detail": "Checker 发现首轮只有 9 道题，已补充技术表达题并重新校验",
        }],
    }

    client = FixtureClient([
        jd_payload(),
        resume_a_payload(a_id), match_a_payload(a_id),
        resume_b_payload(b_id), match_b_payload(b_id),
        # 首轮 9 道题被数量规则判 blocker，此时**不会**触发盲评 ——
        # 对一套即将重写的题做模拟是浪费，所以这里没有人格作答的夹具。
        first_question_attempt, revised_question_set,
        # 补齐到 10 道、确定性规则通过之后才进入 SIMULATE：
        # 专家 -> 背题党 -> 简历人格 -> 盲评阅卷。
        persona_answers_payload(0), persona_answers_payload(1), persona_answers_payload(2),
        grader_payload(),
        followups_payload(a_id),
    ])

    with tempfile.TemporaryDirectory(prefix="resume-demo-cache-") as temp:
        temp_root = Path(temp)
        get_settings.cache_clear()
        settings = get_settings()
        settings.demo_mode = False
        settings.cache_enabled = True
        # 与 call_structured 的无 client Demo 命名空间保持一致，避免评审者
        # 本机 .env 里的模型名改变后导致缓存键漂移。
        #
        # 快慢两档都要设成 demo-v1：回放时 `_stage_models()` 见到 DEMO_MODE 会
        # 返回 (None, None)，所有阶段塌缩到同一个 demo 命名空间；生成时若让快阶段
        # 用 llm_model_cheap，算出的缓存键回放永远命中不了 —— 而且失败发生在
        # 评审者机器上，本地毫无察觉。
        settings.llm_model = "demo-v1"
        settings.llm_model_cheap = "demo-v1"
        # 夹具按顺序弹出，而候选人默认是并行筛选的 —— 两个线程交错取用会拿到
        # 对方的响应。这里强制串行；缓存键由输入内容算出，与生成顺序无关，
        # 因此回放时仍可安全并行。
        settings.max_parallel_candidates = 1
        settings.cache_dir = temp_root / "runtime"
        settings.demo_cache_dir = temp_root / "empty-demo"
        settings.trace_dir = temp_root / "traces"
        structured._default_tracer = None

        original_get_client = structured.get_client
        structured.get_client = lambda _settings: client
        try:
            result = api.run(jd_text, resumes)
        finally:
            structured.get_client = original_get_client

        if client.payloads:
            raise AssertionError(f"仍有 {len(client.payloads)} 条 Demo 响应未被状态机消费")
        if [item.recommendation for item in result.ranking.items] != ["ADVANCE", "REJECT"]:
            raise AssertionError("Demo 排序结果与预期不一致")
        if not result.candidates[0].question_set or len(result.candidates[0].question_set.questions) != 10:
            raise AssertionError("Demo 必须为推进候选人生成 10 道题")
        question_stage = next(
            stage for stage in result.candidates[0].stages if stage.stage == "question_set"
        )
        if question_stage.rounds_used != 1 or not question_stage.notes:
            raise AssertionError("Demo 必须展示 Checker 发现问题并完成至少一轮修订")
        if any(not stage.gate.passed for candidate in result.candidates for stage in candidate.stages):
            raise AssertionError("Demo 的每个 Checker 阶段都必须通过")

        simulation = result.candidates[0].simulation
        if simulation is None or len(simulation.diagnoses) != 10:
            raise AssertionError("Demo 必须对全部 10 道题给出三人格盲评诊断")
        if simulation.by_diagnosis().get("NO_DISCRIMINATION") != 1:
            raise AssertionError("Demo 需要恰好一道被判为无区分度的题，用来展示模拟的价值")
        if not any(i.detector == "sim" for i in question_stage.report.issues):
            raise AssertionError("盲评诊断必须落成 detector=sim 的 Issue")

        target = ROOT / "data" / "demo_cache"
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.json"):
            old.unlink()
        generated = sorted((temp_root / "runtime").glob("*.json"))
        for path in generated:
            shutil.copy2(path, target / path.name)

    print(f"generated {len(generated)} demo cache entries in {target}")


if __name__ == "__main__":
    main()
