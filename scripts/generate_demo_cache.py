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

    加进内置样例是为了让 HOLD 与 PARTIAL 这几档在 Demo 里真的出现 ——
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
        ("Q1", "每日 3 万条质检数据里，你定义的「脏数据」判据是什么？漏掉一条会怎样？", "数据口径定义", "MEDIUM", "R3", "使用 Python 与 pandas 清洗产线质检数据，编写脚本把每日 3 万条记录汇总成周报",
         "R3 是硬性要求，简历给了数据规模却没给判据。要确认他清洗时是否理解背后的业务口径。"),
        ("Q2", "阈值告警的那个阈值是怎么定下来的？误报和漏报你更能接受哪一个，为什么？", "阈值取舍", "MEDIUM", "R3", "用 Python 编写规则引擎，对传感器读数做阈值告警",
         "阈值是他自己定的还是照搬现成的，简历里看不出来 —— 这直接决定 R3 算不算真正满足。"),
        ("Q3", "那份 12 页口径文档里，你认为最容易被同事误解的是哪一条？你怎么写才避免的？", "技术表达", "EASY", "R7", "独立撰写了一份 12 页的数据口径说明文档，被团队用作后续交接材料",
         "R7 技术表达在简历里只有这一份文档作证，需要确认他写的时候是否真的考虑过读者会怎么误解。"),
        ("Q4", "生产部门真的按你的图表调整过排产吗？如果没有，你觉得卡在哪里？", "业务落地", "MEDIUM", "R7", "用 matplotlib 输出可视化图表，交付给生产部门作为排产参考",
         "简历写「交付给生产部门作为排产参考」，但没说是否真被采用。交付不等于落地，这一步差别很大。"),
        ("Q5", "你说没做多版对比 —— 如果现在让你验证 ChatGPT 生成的 SQL 是否可靠，你会怎么设计对照？", "实验设计", "HARD", "R5", "尝试过用 ChatGPT 辅助生成正则表达式和 SQL，但没有做过多版对比或效果评估",
         "简历自述「没有做过多版对比或效果评估」，R5 因此判为不满足。这道题给他一次现场证明实验设计能力的机会。"),
        ("Q6", "注意力机制里 Q、K、V 各自解决什么问题？课程之外你自己验证过哪一部分？", "原理理解", "MEDIUM", "R4", "在机器学习导论课上系统学习过神经网络与注意力机制的基本原理，但没有在项目中实践过",
         "R4 要求大模型相关理解，而简历明确写了「没有在项目中实践过」。需要确认课程知识到底停在什么深度。"),
        ("Q7", "把每日汇总脚本交给别人跑，你会补哪些东西才敢交？", "工程化意识", "MEDIUM", "R3", "熟悉 Python，掌握 pandas、numpy、matplotlib",
         "简历里的脚本都是他自己跑自己用，看不出是否具备把代码交给别人维护的工程化意识。"),
        ("Q8", "二手交易平台的搜索功能，你用的是什么方案？数据量涨十倍会先垮在哪？", "系统设计", "MEDIUM", "R3", "使用 Django 搭建后端，实现商品发布、搜索和站内信功能",
         "二手平台是简历里唯一的后端项目，需要确认搜索是直接调库还是他自己设计的。"),
        ("Q9", "如果把二手平台的搜索改成向量检索，你会怎样评估召回质量、怎样决定切块粒度？", "向量检索选型", "HARD", "R10", "数据库为 MySQL，没有使用过向量数据库",
         "R10 要求向量数据库经验，简历明确写「没有使用过」，判为不满足。这道题验证他能否从已有的检索理解迁移过去。"),
        ("Q10", "规则引擎和模型方法，在你那个告警场景里你会怎么选？换成模型的前提条件是什么？", "方案选型判断", "HARD", "R4", "用 Python 编写规则引擎，对传感器读数做阈值告警",
         "R4 判为 PARTIAL —— 他有规则引擎经验但无模型实践。这道题考察的是选型判断，不是实现细节。"),
    ]
    return {"questions": [
        {"question_id": qid, "text": text, "skill_point": skill, "rationale": why,
         "difficulty": diff, "rubric": rubric(),
         "source_requirement_ids": [req], "evidence": [span(doc_id, quote)]}
        for qid, text, skill, diff, req, quote, why in cases
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
        ("Q1", "准确率从 61% 到 84% 的提升如何拆分到具体改动，并怎样排除评测集波动？", "效果归因", "HARD", "R5", "最终答案准确率从 61% 提升到 84%",
         "简历把 23 个百分点的提升记在个人名下，却没写归因方法。R5 正是匹配阶段判为 PARTIAL 的存疑项，要确认这是他定位出来的还是团队的共同结论。"),
        ("Q2", "三版 Prompt 分别改变了什么变量？请给出你保留最终版本的比较证据。", "Prompt 实验设计", "MEDIUM", "R5", "设计了三版 Prompt 并做了效果对比",
         "写了「做了效果对比」但没有给出比较口径，无法判断是严谨的对照实验还是事后追认的说法。"),
        ("Q3", "文档解析、切块和向量化入库中，你遇到的最严重数据质量问题是什么？", "RAG 数据治理", "MEDIUM", "R6", "使用 Python 完成文档解析、切块与向量化入库",
         "解析、切块、入库三步在简历里都只写了「完成」，看不出他是否真的踩过数据质量的坑。"),
        ("Q4", "为什么选择 Chroma？如果数据规模扩大一百倍，你会重新评估哪些指标？", "向量库选型", "HARD", "R10", "使用过 Chroma 向量数据库",
         "R10 要求向量库经验，简历只写「使用过」。需要区分他是选型的决策者，还是接手了现成方案。"),
        ("Q5", "两千余次提问是怎样统计的？其中多少被人工抽检，失败样本如何分类？", "线上指标可信度", "MEDIUM", "R6", "累计服务两千余次提问",
         "两千余次是简历里最抢眼的量化结果，但统计口径和人工抽检比例都没交代，数字的可信度无从判断。"),
        ("Q6", "200 条人工评测集如何采样、标注和处理分歧，怎样避免只覆盖简单意图？", "评测集建设", "HARD", "R5", "建立了一套包含 200 条样本的人工评测集",
         "评测集是他所有归因结论的地基。200 条这个规模能不能支撑 12 个百分点的结论，取决于采样方式。"),
        ("Q7", "意图识别准确率提升 12 个百分点时，基线、指标口径和你的个人贡献分别是什么？", "业务效果验证", "MEDIUM", "R5", "推动意图识别准确率提升 12 个百分点",
         "12 个百分点既没给基线，也没区分个人与团队贡献 —— 这正是 R5 被判 PARTIAL 的直接原因。"),
        ("Q8", "在二十万条评论清洗中，请举一个 pandas 规则误伤数据的例子和修复办法。", "Python 数据处理", "MEDIUM", "R3", "使用 Python 与 pandas 清洗二十万条评论数据",
         "R3 是硬性要求，而简历只给了数据规模、没给难点。需要一个具体的坑来验证他的处理深度。"),
        ("Q9", "如果 FastAPI 服务出现突发超时，你会怎样区分模型、检索和接口层问题？", "服务故障诊断", "EASY", "R3", "熟悉 Python，掌握 pandas、FastAPI",
         "简历列了 FastAPI，但通篇没有线上排障的痕迹。要确认是「用过这个框架」还是「扛过线上问题」。"),
        ("Q10", "请挑一篇技术博客说明你如何把复杂方案写成可供工程团队执行的文档。", "技术表达", "EASY", "R7", "已发表 15 篇大模型相关文章",
         "R7 要求技术表达，15 篇文章只是数量证据。还要确认他能否把方案写成别人照着就能执行的文档。"),
    ]
    return {"questions": [
        {
            "question_id": qid, "text": text, "skill_point": skill, "rationale": why,
            "difficulty": difficulty, "rubric": rubric(),
            "source_requirement_ids": [requirement], "evidence": [span(doc_id, quote)],
        }
        for qid, text, skill, difficulty, requirement, quote, why in cases
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
        # 首轮 9 道题被数量规则判 blocker，触发一轮重写补齐到 10 道。
        first_question_attempt, revised_question_set,
        followups_payload(a_id),
        # 陈涛是 HOLD，同样要出题 —— 只有被 REJECT 的才不出。
        questions_c_payload(c_id),
        followups_c_payload(c_id),

        # ---- 第二轮 ----
        # 只有出题 prompt 变了（注入了第一轮沉淀的经验），其余调用键不变、
        # 全部命中缓存。所以这里只需要两条：两位推进候选人的出题结果。
        # 两人这次都一次给足 10 道 —— 「上次题数不足被打回」正是注入的经验之一。
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
