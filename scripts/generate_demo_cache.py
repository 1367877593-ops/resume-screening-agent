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
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from checker.simulation.grader import label_map  # noqa: E402
from flywheel.lessons import load_all  # noqa: E402
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


def resume_c_payload(doc_id: str) -> dict:
    """边缘候选人：硬性项全部踩线满足，软性项半数只能算部分满足。

    加进内置样例是为了让 HOLD / PARTIAL / 超出射程这几档在 Demo 里真的出现 ——
    只有「全 YES」和「全 NO」两个极端时，分档逻辑写了也演示不出来。
    """
    return {
        "resume_id": doc_id,
        "candidate_name": "陈涛",
        "educations": [{
            "school": "某理工大学", "degree": "本科", "major": "电子信息工程",
            "start": "2022.09", "end": "2026.06",
            "evidence": [span(doc_id, "2022.09 - 2026.06  某理工大学  电子信息工程  本科")],
        }],
        "work_experiences": [{
            "company": "某制造业公司", "title": "数据分析实习生",
            "start": "2025.07", "end": "2025.08",
            "summary": "清洗产线质检数据并输出周报",
            "evidence": [span(doc_id, "使用 Python 与 pandas 清洗产线质检数据，编写脚本把每日 3 万条记录汇总成周报")],
        }],
        "projects": [
            {
                "name": "校园二手交易平台", "role": "课程设计",
                "description": "Django 后端，MySQL 存储",
                "tech_stack": ["Python", "Django", "MySQL"],
                "evidence": [span(doc_id, "使用 Django 搭建后端，实现商品发布、搜索和站内信功能")],
            },
            {
                "name": "产线异常检测脚本", "description": "阈值规则告警",
                "tech_stack": ["Python"],
                "evidence": [span(doc_id, "用 Python 编写规则引擎，对传感器读数做阈值告警")],
            },
        ],
        "skills": [
            {"name": "Python", "level": "熟悉",
             "evidence": [span(doc_id, "熟悉 Python，掌握 pandas、numpy、matplotlib")]},
            {"name": "SQL", "evidence": [span(doc_id, "了解 SQL 与 Django，能独立完成数据处理脚本")]},
        ],
    }


def match_c_payload(doc_id: str) -> dict:
    """三项硬性要求踩线满足，因此不会一票否决；软性项拉低总分到 HOLD 区间。"""
    ev = {
        "edu": "2022.09 - 2026.06  某理工大学  电子信息工程  本科",
        "python": "熟悉 Python，掌握 pandas、numpy、matplotlib",
        "clean": "使用 Python 与 pandas 清洗产线质检数据，编写脚本把每日 3 万条记录汇总成周报",
        "ml": "在机器学习导论课上系统学习过神经网络与注意力机制的基本原理，但没有在项目中实践过",
        "chatgpt": "尝试过用 ChatGPT 辅助生成正则表达式和 SQL，但没有做过多版对比或效果评估",
        "doc": "独立撰写了一份 12 页的数据口径说明文档，被团队用作后续交接材料",
        "avail": "每周可到岗 4 天，实习期可保证 3 个月",
    }
    rows = [
        ("R1", "YES", 95, "本科在读，满足学历门槛", "edu"),
        ("R2", "PARTIAL", 55, "电子信息工程与目标专业相关但不对口", "edu"),
        ("R3", "YES", 80, "能用 pandas 独立完成数据清洗脚本", "clean"),
        ("R4", "PARTIAL", 45, "课程层面了解原理，无工程实践", "ml"),
        # 刻意埋的语义矛盾：理由说「有系统的多版迭代经验」，可它引用的那句原文
        # 恰恰写着「没有做过多版对比或效果评估」。引用逐字存在，归因规则查不出来，
        # 只有语义校验能看出证据撑不起结论 —— 这正是 detector=llm 存在的理由。
        ("R5", "PARTIAL", 40, "有系统的 Prompt 多版迭代与效果评估经验", "chatgpt"),
        ("R6", "NO", 10, "没有结构化输出、RAG 或 Agent 项目", None),
        ("R7", "YES", 85, "独立撰写过被团队复用的口径文档", "doc"),
        ("R8", "YES", 100, "每周可到岗 4 天，恰好满足", "avail"),
        ("R9", "YES", 100, "实习期可保证 3 个月，恰好满足", "avail"),
        ("R10", "NO", 0, "明确未使用过向量数据库", None),
        ("R11", "NO", 0, "暂无开源项目与技术博客", None),
    ]
    return {"verdicts": [
        {"requirement_id": rid, "satisfied": st, "score": sc, "reason": rs,
         "evidence": [span(doc_id, ev[k])] if k else []}
        for rid, st, sc, rs, k in rows
    ]}


def semantic_clean_payload() -> dict:
    """未发现矛盾。零发现是常态，不是异常。"""
    return {"findings": []}


def semantic_c_payload() -> dict:
    """语义校验抓出陈涛 R5 的理由与其所引证据自相矛盾。"""
    return {"findings": [{
        "requirement_id": "R5",
        "explanation": "理由称有系统的多版迭代与效果评估，但所引原文明说「没有做过多版对比或效果评估」，证据与结论相反",
        "quote": "尝试过用 ChatGPT 辅助生成正则表达式和 SQL，但没有做过多版对比或效果评估",
    }]}



def questions_c_payload(doc_id: str) -> dict:
    cases = [
        ("Q1", "每日 3 万条质检数据里，你定义的「脏数据」判据是什么？漏掉一条会怎样？", "数据口径定义", "MEDIUM", "R3", "使用 Python 与 pandas 清洗产线质检数据，编写脚本把每日 3 万条记录汇总成周报"),
        ("Q2", "阈值告警的那个阈值是怎么定下来的？误报和漏报你更能接受哪一个，为什么？", "阈值取舍", "MEDIUM", "R3", "用 Python 编写规则引擎，对传感器读数做阈值告警"),
        ("Q3", "那份 12 页口径文档里，你认为最容易被同事误解的是哪一条？你怎么写才避免的？", "技术表达", "EASY", "R7", "独立撰写了一份 12 页的数据口径说明文档，被团队用作后续交接材料"),
        ("Q4", "生产部门真的按你的图表调整过排产吗？如果没有，你觉得卡在哪里？", "业务落地", "MEDIUM", "R7", "用 matplotlib 输出可视化图表，交付给生产部门作为排产参考"),
        ("Q5", "你说没做多版对比 —— 如果现在让你验证 ChatGPT 生成的 SQL 是否可靠，你会怎么设计对照？", "实验设计", "HARD", "R5", "尝试过用 ChatGPT 辅助生成正则表达式和 SQL，但没有做过多版对比或效果评估"),
        ("Q6", "注意力机制里 Q、K、V 各自解决什么问题？课程之外你自己验证过哪一部分？", "原理理解", "MEDIUM", "R4", "在机器学习导论课上系统学习过神经网络与注意力机制的基本原理，但没有在项目中实践过"),
        ("Q7", "把每日汇总脚本交给别人跑，你会补哪些东西才敢交？", "工程化意识", "MEDIUM", "R3", "熟悉 Python，掌握 pandas、numpy、matplotlib"),
        ("Q8", "二手交易平台的搜索功能，你用的是什么方案？数据量涨十倍会先垮在哪？", "系统设计", "MEDIUM", "R3", "使用 Django 搭建后端，实现商品发布、搜索和站内信功能"),
        ("Q9", "如果把二手平台的搜索改成向量检索，你会怎样评估召回质量、怎样决定切块粒度？", "向量检索选型", "HARD", "R10", "数据库为 MySQL，没有使用过向量数据库"),
        ("Q10", "规则引擎和模型方法，在你那个告警场景里你会怎么选？换成模型的前提条件是什么？", "方案选型判断", "HARD", "R4", "用 Python 编写规则引擎，对传感器读数做阈值告警"),
    ]
    return {"questions": [
        {"question_id": qid, "text": text, "skill_point": skill, "difficulty": diff,
         "rubric": rubric(), "source_requirement_ids": [req], "evidence": [span(doc_id, quote)]}
        for qid, text, skill, diff, req, quote in cases
    ]}


def followups_c_payload(doc_id: str) -> dict:
    points = [
        ("P1", "「熟悉 Python」的深度缺少可核实的例子", "熟悉 Python，掌握 pandas、numpy、matplotlib"),
        ("P2", "使用 ChatGPT 的方式停留在工具层，效果无验证", "尝试过用 ChatGPT 辅助生成正则表达式和 SQL，但没有做过多版对比或效果评估"),
        ("P3", "实习期与到岗天数恰好踩线，需确认可持续性", "每周可到岗 4 天，实习期可保证 3 个月"),
    ]
    return {
        "ambiguity_points": [
            {"point_id": pid, "description": desc, "evidence": [span(doc_id, quote)]}
            for pid, desc, quote in points
        ],
        "questions": [
            {"followup_id": "F1", "text": "请举一个你写过的最复杂的 pandas 处理，说明为什么不能用更简单的写法。", "ambiguity_point_id": "P1", "intent": "确认 Python 能力的实际深度"},
            {"followup_id": "F2", "text": "ChatGPT 生成的 SQL 你是怎么确认正确的？有没有出过错？", "ambiguity_point_id": "P2", "intent": "确认使用 AI 工具时是否有验证意识"},
            {"followup_id": "F3", "text": "4 天到岗和 3 个月实习是硬约束还是可协商？课程安排会不会影响？", "ambiguity_point_id": "P3", "intent": "确认投入度是否稳定"},
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



# 陈涛的题。Q9 是第二个刻意埋的反例：向量检索是好问题（专家答得出、背题党答不出），
# 但他简历里明说没用过向量数据库，简历人格答不上 —— 三分对照据此判「超出射程」。
# 这一档是 minor，不阻断流程，只在报告里提示「这道题留给下一轮」。
SIM_ANSWERS_C = {
    "Q1": (
        "脏数据分三类：传感器掉线导致的空值、超出量程的物理不可能值、同一时间戳重复上报。前两类直接丢并计数，第三类保留最后一条。漏掉超量程值会把周报均值拉偏，产线会误判工况。",
        "数据清洗要处理缺失值、异常值和重复值，常用方法包括均值填充、3σ 原则和去重，需要结合业务场景选择合适的策略。",
        "主要是把空值和明显不合理的数值去掉，比如温度出现负几百度那种。重复记录我按时间戳去了重。漏掉的话周报数字会不准。",
    ),
    "Q2": (
        "先用历史三个月数据画分布，取 P99 做初始阈值，再和产线老师傅确认哪些告警他们真的会去看。这个场景更怕漏报：漏一次可能是批量不良，误报只是多跑一趟。",
        "阈值设定需要平衡误报率和漏报率，可以通过 ROC 曲线选择最优工作点，同时结合业务成本进行调整。",
        "阈值是看历史数据大概定的，取了个经验值。误报多了工人会烦，漏报会出质量问题，我觉得漏报更严重一些。",
    ),
    "Q3": (
        "最容易误解的是「有效工时」——它排除了换模时间但包含调试时间。我在文档里没有只给定义，而是配了一张包含边界情况的示例表，让人直接对着查。",
        "技术文档要结构清晰、术语统一，使用图表辅助说明，注意读者视角，把复杂概念拆解成易于理解的模块。",
        "应该是几个指标的口径，比如合格率怎么算。我在文档里都写了公式，还举了例子，同事看了之后没再来问过我。",
    ),
    "Q4": (
        "只在试点线用过两周。卡点是我的图表按天聚合，而排产决策是按班次做的，粒度对不上，他们还得自己再拆一次。",
        "数据可视化要贴合业务需求，通过与业务方沟通明确使用场景，持续迭代优化图表设计，形成数据驱动的决策闭环。",
        "生产部门确认收到了图表，具体有没有按它调整排产我不太清楚，我实习结束前没有跟进到这一步。",
    ),
    "Q5": (
        "准备 30 条已知正确结果的查询做对照集，同一需求让模型生成三次，比较结果一致性和与人工 SQL 的差异，重点看聚合口径和 NULL 处理这两个最容易错的地方。",
        "验证 AI 生成代码需要建立测试用例集，进行单元测试和集成测试，同时人工审核关键逻辑，确保结果准确可靠。",
        "我会把生成的 SQL 拿到测试库跑一遍，看结果对不对。设计对照实验的话我没做过，可能要准备一批标准答案来比对。",
    ),
    "Q6": (
        "Q 是当前位置要找什么，K 是每个位置能提供什么，V 是真正被取走的内容。点积算相关性、softmax 归一成权重。我自己只手推过一遍小矩阵，没在真实模型上验证过。",
        "注意力机制中 Query 表示查询向量，Key 是键向量，Value 是值向量，通过 QK 点积计算注意力权重再对 V 加权求和，实现对重要信息的聚焦。",
        "Q 是查询，K 是键，V 是值，通过 Q 和 K 算相似度得到权重再乘 V。这是课上学的，我没有在项目里实际用过。",
    ),
    "Q7": (
        "补三样：输入数据的 schema 校验（列名和类型变了要立刻报错而不是算出错数）、失败时的明确退出码、还有一份包含真实脏数据的样例输入让对方能自测。",
        "代码交接需要完善文档、添加注释、编写单元测试，遵循编码规范，使用版本控制工具管理，确保可维护性和可读性。",
        "我会写个 README 说明怎么跑、需要什么依赖，再把硬编码的路径改成参数。异常处理也要加一些，不然报错看不懂。",
    ),
    "Q8": (
        "就是 MySQL 的 LIKE 模糊匹配加了个分类过滤。涨十倍先垮在全表扫描上，商品表没建合适的索引；再往上是中文分词做不了，搜「自行车」搜不到「单车」。",
        "搜索功能可以使用数据库索引、全文检索引擎如 Elasticsearch，通过分词、倒排索引和相关性排序提升搜索性能和准确度。",
        "用的是 MySQL 的模糊查询。数据量大了应该会变慢，可能需要加索引或者上专门的搜索引擎，具体我没测过。",
    ),
    "Q9": (
        "召回质量看两个：人工标注 100 条查询的相关商品做 Recall@10，再抽查高频零结果查询。切块粒度对商品这种短文本不适用，应该整条标题加描述做一个向量，反而要考虑的是标题和描述该不该分开建两路召回。",
        "向量检索需要选择合适的嵌入模型，通过余弦相似度计算语义相关性，评估指标包括召回率、准确率和 MRR，切块要平衡语义完整性和检索精度。",
        "向量检索我没有用过，只知道大概是把文本转成向量再算相似度。怎么评估召回质量和切块粒度我确实不了解，需要学习之后才能回答。",
    ),
    "Q10": (
        "现在这个场景我还是选规则：告警要能向产线解释为什么响，规则说得清。换模型的前提是有足够多的标注异常样本，且存在规则表达不了的多变量联合模式 —— 我那个场景两个条件都不满足。",
        "规则引擎适合逻辑明确、可解释性要求高的场景，模型方法适合复杂非线性关系，选择时要考虑数据量、可解释性需求和维护成本。",
        "规则简单直接，出了问题好排查。用模型的话应该需要比较多的历史数据来训练，我那个项目数据量不大，所以用了规则。",
    ),
}

# Q9：简历人格 45 < resume_pass=60 -> 超出射程（minor，不阻断）
SIM_SCORES_C = {
    "Q1": (92, 30, 75), "Q2": (88, 35, 70), "Q3": (85, 32, 78), "Q4": (87, 38, 72),
    "Q5": (90, 42, 64), "Q6": (89, 45, 62), "Q7": (86, 33, 68), "Q8": (88, 36, 66),
    "Q9": (90, 40, 45), "Q10": (87, 34, 61),
}


def persona_answers_payload(table: dict, persona_index: int) -> dict:
    """某个人格对整套题的作答。persona_index: 0=专家 1=背题党 2=简历人格。"""
    return {
        "answers": [
            {"question_id": qid, "answer": answers[persona_index]}
            for qid, answers in table.items()
        ]
    }


def grader_payload(table: Optional[dict] = None) -> dict:
    """盲评结果。

    标签不能手写死：`grade_blind` 每道题都按 question_id 派生一个独立的
    标签映射，夹具必须用同一个函数反推，否则分数会记到错误的人格头上。

    评语按分数档位现算，不按题号硬编码 —— 两套题里都有 Q9，但它们不合格的
    原因完全不同（一个是背题党答得太好，一个是简历人格答不上）。
    """
    table = SIM_SCORES if table is None else table
    rows = []
    for qid, (expert, bluffer, resume) in table.items():
        per_persona = {"expert": expert, "bluffer": bluffer, "resume": resume}
        for label, persona in label_map(qid, sorted(per_persona)).items():
            score = per_persona[persona]
            if score >= 85:
                reason = "给出了具体做法、判断依据与量化结果，落在优秀档"
            elif score >= 60:
                reason = "能讲清本人做法与基本结果，但量化验证不完整，落在合格档"
            else:
                reason = "只有正确但空泛的通用说法，没有本人做过的痕迹，落在不合格档"
            rows.append(
                {"question_id": qid, "label": label, "score": score, "reason": reason}
            )
    return {"scores": rows}


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
    if len(resume_docs) != 3:
        raise AssertionError("内置 Demo 目前要求恰好三份样例简历（推进 / 待定 / 淘汰各一）")
    a_id, b_id, c_id = (doc.doc_id for doc in resume_docs)

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
        # 每位候选人：提取 -> 匹配 -> （规则通过后）语义校验
        resume_a_payload(a_id), match_a_payload(a_id), semantic_clean_payload(),
        resume_b_payload(b_id), match_b_payload(b_id), semantic_clean_payload(),
        # 陈涛的 R5 理由与证据矛盾：语义校验检出一条 major。
        # 一条 major 判 CONDITIONAL_PASS（可用但建议人工过目），不触发重写 ——
        # 语义判断有误报可能，一条就打回反而容易把正确结论改坏。
        resume_c_payload(c_id), match_c_payload(c_id), semantic_c_payload(),
        # 首轮 9 道题被数量规则判 blocker，此时**不会**触发盲评 ——
        # 对一套即将重写的题做模拟是浪费，所以这里没有人格作答的夹具。
        first_question_attempt, revised_question_set,
        # 补齐到 10 道、确定性规则通过之后才进入 SIMULATE：
        # 专家 -> 背题党 -> 简历人格 -> 盲评阅卷。
        persona_answers_payload(SIM_ANSWERS, 0),
        persona_answers_payload(SIM_ANSWERS, 1),
        persona_answers_payload(SIM_ANSWERS, 2),
        grader_payload(),
        followups_payload(a_id),
        # 陈涛是 HOLD，同样要出题 —— 只有被 REJECT 的才不出。
        questions_c_payload(c_id),
        persona_answers_payload(SIM_ANSWERS_C, 0),
        persona_answers_payload(SIM_ANSWERS_C, 1),
        persona_answers_payload(SIM_ANSWERS_C, 2),
        grader_payload(SIM_SCORES_C),
        followups_c_payload(c_id),

        # ---- 第二轮 ----
        # 只有出题 prompt 变了（注入了第一轮沉淀的经验），其余调用键不变、
        # 全部命中缓存。所以这里只需要两条：两位推进候选人的出题结果。
        # 两人这次都一次给足 10 道 —— 「上次题数不足被打回」正是注入的经验之一。
        # 题目内容与第一轮的最终结果一致，因此后续的人格作答与盲评继续命中缓存。
        final_questions,
        questions_c_payload(c_id),
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
        # 经验库隔离到临时目录：否则本机跑过 demo 之后再重建缓存，
        # 第一轮就带着上次的经验，生成出来的键与「首次运行」对不上。
        settings.lessons_path = temp_root / "lessons.jsonl"
        settings.demo_cache_dir = temp_root / "empty-demo"
        settings.trace_dir = temp_root / "traces"
        structured._default_tracer = None

        original_get_client = structured.get_client
        structured.get_client = lambda _settings: client
        try:
            result = api.run(jd_text, resumes)
            # 第二轮：第一轮的问题已沉淀进经验库，出题 prompt 会带上它们，
            # 缓存键因此不同。把这一轮也录进去，评审者连跑两次才不会未命中 ——
            # 而且第二轮的改善本身就是飞轮的完成标志。
            second = api.run(jd_text, resumes)
        finally:
            structured.get_client = original_get_client

        if client.payloads:
            raise AssertionError(f"仍有 {len(client.payloads)} 条 Demo 响应未被状态机消费")

        # 飞轮：第一轮题数不足被打回，第二轮带着经验一次到位
        first_q = next(s for s in result.candidates[0].stages if s.stage == "question_set")
        second_q = next(s for s in second.candidates[0].stages if s.stage == "question_set")
        if first_q.rounds_used != 1 or second_q.rounds_used != 0:
            raise AssertionError(
                f"飞轮应让第二轮免于重复同一个错误，实际 {first_q.rounds_used} -> {second_q.rounds_used}"
            )
        lessons = load_all(settings.lessons_path)
        if not any(x.issue_code == "Q_COUNT_LT_MIN" for x in lessons):
            raise AssertionError("题数不足这条经验没有被沉淀")
        recs = [item.recommendation for item in result.ranking.items]
        if recs != ["ADVANCE", "HOLD", "REJECT"]:
            raise AssertionError(f"Demo 必须让三档决策各出现一次，实际为 {recs}")
        hold = next(i for i in result.ranking.items if i.recommendation == "HOLD")
        if not (60.0 <= hold.total_score < 75.0):
            raise AssertionError(f"待定候选人应落在 [60, 75) 区间，实际 {hold.total_score}")
        if not result.candidates[0].question_set or len(result.candidates[0].question_set.questions) != 10:
            raise AssertionError("Demo 必须为推进候选人生成 10 道题")
        question_stage = next(
            stage for stage in result.candidates[0].stages if stage.stage == "question_set"
        )
        if question_stage.rounds_used != 1 or not question_stage.notes:
            raise AssertionError("Demo 必须展示 Checker 发现问题并完成至少一轮修订")
        if any(not stage.gate.passed for candidate in result.candidates for stage in candidate.stages):
            raise AssertionError("Demo 的每个 Checker 阶段都必须通过")

        # 语义校验必须真的跑到，并且抓到那条埋进去的矛盾
        held = next(c for c in result.candidates if c.match_result.recommendation == "HOLD")
        if held.semantic is None or not held.semantic.checked:
            raise AssertionError("语义校验没有跑到")
        match_stage = next(s for s in held.stages if s.stage == "match")
        sem = [i for i in match_stage.detected if i.detector == "llm"]
        if [i.issue_code for i in sem] != ["SEM_REASON_CONTRADICTS_EVIDENCE"]:
            raise AssertionError(f"语义校验未按预期检出，实际 {[i.issue_code for i in sem]}")
        if match_stage.gate.status != "CONDITIONAL_PASS":
            raise AssertionError("一条语义 major 应判 CONDITIONAL_PASS，交人工过目而不是自动重写")
        if match_stage.rounds_used != 0:
            raise AssertionError("语义校验的单条发现不应触发重写")

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
