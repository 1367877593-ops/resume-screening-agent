# 智能简历解析与试题生成引擎 — 架构与模块划分

> 本文档用作开发前的架构约束。建议在开工时整份喂给 Claude Code，并把「六、给 AI 编程工具的硬约束」一节单独复制成项目根目录的 `CLAUDE.md`。

---

## 一、设计原则

1. **单向依赖**：`schema ← harness ← store/ingest ← agents/checker ← pipeline ← app`。任何反向 import 都是设计错误。
2. **Harness 独立成层**：所有 LLM 调用必须经过 `harness`，业务代码里不出现任何厂商 SDK。这一层就是评分表里说的 "Agent 编排和 Harness"。
3. **契约集中**：所有跨模块数据结构定义在 `schema/`，它不依赖任何其他模块。
4. **信息隔离靠类型**：`QuestionFull` / `QuestionPublic` 是两个类型，防泄题由函数签名保证，不靠 prompt 请求模型自觉。
5. **确定性优先**：能用规则校验的绝不调 LLM。`Issue.detector` 字段记录来源，最终可统计"规则 vs LLM"的检出占比。
6. **配置外置**：所有阈值进 `config/thresholds.yaml`，所有 prompt 进 `prompts/*.md`，代码里不出现魔数和长字符串。

---

## 二、目录结构

```
resume-agent/
├── README.md                      # 交付文档：架构图/Prompt思路/难点
├── CLAUDE.md                      # 给 AI 编程工具的硬约束
├── pyproject.toml
├── .env.example                   # 只有 key 名，无真实值
├── .gitignore                     # 必须含 .env、data/runtime/
├── Makefile                       # make install / make demo / make eval
│
├── config/
│   ├── settings.py                # pydantic-settings，读 .env
│   ├── thresholds.yaml            # 所有阈值：分数线、相似度、轮数上限
│   └── rubric.yaml                # Checker 校准维度定义 + 通过/不通过规则
│
├── prompts/                       # 每个 prompt 一个文件，带 version 头
│   ├── extract.md
│   ├── match.md
│   ├── question_gen.md
│   ├── followup.md
│   ├── persona_expert.md
│   ├── persona_bluffer.md
│   ├── persona_resume.md
│   ├── grader.md                  # 盲评阅卷官
│   ├── checker_semantic.md
│   └── reviser.md
│
├── src/
│   ├── schema/                    # 契约层，零依赖
│   │   ├── document.py            # RawDoc, Chunk, SourceSpan
│   │   ├── resume.py              # ExtractedResume, Education, Project, Skill
│   │   ├── jd.py                  # JD, Requirement(weight, is_hard)
│   │   ├── match.py               # RequirementVerdict, MatchResult
│   │   ├── question.py            # QuestionFull, QuestionPublic, Rubric, QuestionSet
│   │   ├── followup.py            # AmbiguityPoint, FollowUpQuestion
│   │   ├── issue.py               # Issue, Severity, Detector, CheckReport, Gate
│   │   └── simulation.py          # Persona, SimAnswer, SimScore, QuestionDiagnosis
│   │
│   ├── harness/                   # ★ 核心加分模块
│   │   ├── llm_client.py          # 统一入口，provider 可切换
│   │   ├── structured.py          # schema 约束调用 + 校验 + 修复重试
│   │   ├── retry.py               # 指数退避、超时、限流
│   │   ├── prompt_loader.py       # 载入 prompts/ + 变量注入 + 版本号
│   │   ├── trace.py               # 每次调用落盘：prompt/响应/token/耗时/重试
│   │   └── cache.py               # 输入 hash → 结果，支持增量重跑
│   │
│   ├── ingest/
│   │   ├── loader.py              # pdf/docx → RawDoc(全文 + 分块)
│   │   ├── chunker.py
│   │   └── normalizer.py          # 清洗页眉页脚、合并断行
│   │
│   ├── store/
│   │   ├── db.py                  # SQLite
│   │   ├── vector.py              # Chroma
│   │   └── repository.py          # 统一读写门面，上层只依赖这个
│   │
│   ├── agents/
│   │   ├── extractor.py           # Part A-i  结构化提取
│   │   ├── matcher.py             # Part A-ii 匹配打分
│   │   ├── question_gen.py        # Part A-iii 试题生成
│   │   ├── followup_gen.py        # Part A-iv 追问模拟
│   │   └── reviser.py             # 定向修订
│   │
│   ├── checker/                   # Part B
│   │   ├── base.py                # Rule 基类 + @register 注册表
│   │   ├── evidence.py            # span 模糊匹配工具（多处复用）
│   │   ├── rules/                 # detector = "rule"
│   │   │   ├── sys_rules.py
│   │   │   ├── ext_rules.py
│   │   │   ├── match_rules.py
│   │   │   ├── question_rules.py
│   │   │   ├── followup_rules.py
│   │   │   └── set_rules.py
│   │   ├── semantic.py            # detector = "llm"
│   │   ├── simulation/            # detector = "sim" ★
│   │   │   ├── personas.py        # 三人格作答
│   │   │   ├── grader.py          # 盲评
│   │   │   └── diagnose.py        # 三分对照真值表
│   │   └── gate.py                # 通过规则 + 熔断
│   │
│   ├── flywheel/
│   │   ├── lessons.py             # 写入、去重、容量控制
│   │   └── retrieve.py            # 按岗位类型 + issue_code 检索注入
│   │
│   ├── pipeline/
│   │   └── orchestrator.py        # 唯一的状态机
│   │
│   └── utils/
│
├── app/                           # Streamlit
│   ├── main.py
│   └── views/
│       ├── upload_view.py
│       ├── match_view.py          # 分项判定 + 点击理由高亮原文
│       ├── question_view.py       # 10题 × 3人格 分数热力图
│       ├── checker_view.py        # issue 列表 + 修订前后 diff
│       └── trace_view.py          # 调用链
│
├── eval/
│   ├── golden/                    # 人工标注集
│   │   ├── questions_labeled.json # 5好题 + 5坏题，用于校准阈值
│   │   └── resumes_expected.json
│   ├── run_eval.py                # 输出诊断准确率
│   └── stability.py               # 同简历跑 N 次的分数方差
│
├── data/
│   ├── samples/                   # 1份JD + 4类陷阱简历
│   └── runtime/                   # traces / lessons / db（gitignore）
│
└── tests/
```

---

## 三、模块职责与依赖

| 模块 | 职责 | 可以 import |
|---|---|---|
| `schema` | 定义所有跨模块数据结构 | 无 |
| `harness` | LLM 调用的可靠性封装 | schema, config |
| `ingest` | 文档 → RawDoc | schema |
| `store` | 持久化门面 | schema |
| `agents` | 生成类业务逻辑 | schema, harness, store, flywheel |
| `checker` | 校验类业务逻辑 | schema, harness, store |
| `flywheel` | 经验沉淀与检索 | schema, store |
| `pipeline` | 编排状态机 | 以上全部 |
| `app` | 展示 | **仅 pipeline 和 schema** |

`app` 不得直接调 `agents` 或 `checker`,否则编排逻辑会散进 UI。

---

## 四、关键接口签名

```python
# harness/structured.py —— 所有结构化输出的唯一入口
def call_structured(
    prompt_name: str,
    variables: dict,
    output_model: type[T],
    max_repair: int = 2,
) -> T: ...
# 内部：载入 prompt → 调用 → Pydantic 校验 → 失败则把报错回灌重试 → 落 trace

# checker/simulation/personas.py —— 信息隔离靠签名保证
def answer_as_expert(questions: list[QuestionPublic], jd: JD) -> list[SimAnswer]: ...
def answer_as_bluffer(questions: list[QuestionPublic]) -> list[SimAnswer]: ...
def answer_as_resume(questions: list[QuestionPublic], resume_text: str) -> list[SimAnswer]: ...
# 三者都拿不到 QuestionFull，看不见评分标准

# checker/simulation/grader.py —— 盲评
def grade_blind(q: QuestionFull, answers: list[SimAnswer]) -> list[SimScore]: ...
# 内部打乱顺序，标 A/B/C，代码侧映射回 persona

# checker/gate.py
def evaluate_gate(report: CheckReport, round_no: int) -> GateResult: ...
# blocker 存在 → FAIL；major ≥3 → FAIL；major 1-2 → CONDITIONAL_PASS
# round_no >= max_rounds 且仍有 blocker → NEEDS_HUMAN_REVIEW（熔断）

# agents/reviser.py —— 按对象粒度重写，不做 JSON Patch
def revise(target_obj: BaseModel, issues: list[Issue], context: ReviseContext) -> ReviseResult: ...
# ReviseResult = {revised, changelog[], disputes[]}
```

---

## 五、编排状态机

```
INGEST → EXTRACT → CHECK(ext) ──┐
                                 ├─→ MATCH → CHECK(match) ──┐
                                 │                           │
                          [FAIL] → REVISE ──┘         [FAIL] → REVISE ──┘
                                 │                           │
                                 └───────────────────────────┴─→ GENERATE_QA
                                                                     │
                                                       SIMULATE(3人格) + CHECK(q/set)
                                                                     │
                                              [FAIL] → REVISE → 增量重跑 ──┘
                                                                     │
                                                          WRITE_LESSONS → OUTPUT
```

约束：
- 每个 `CHECK` 后必进 `gate.evaluate_gate()`,不允许在业务代码里手写判定。
- `REVISE` 后**只对变更对象重跑校验**，未变更的复用上轮结论（靠 `harness/cache.py`）。
- 修订后必须重跑证据类规则（`EXT_SPAN_NOT_FOUND` / `MATCH_EVIDENCE_INVALID`），防止修订过程引入新幻觉。
- `max_rounds = 2`，超出即熔断转人工，禁止无限循环。

---

## 六、给 AI 编程工具的硬约束（复制成 CLAUDE.md）

```markdown
# 项目约束

## 依赖方向（违反即为错误）
schema ← harness ← store/ingest ← agents/checker ← pipeline ← app
- agents/ 和 checker/ 下**禁止** import openai / anthropic / 任何厂商 SDK，
  所有 LLM 调用必须走 harness.structured.call_structured()
- app/ 只能 import pipeline 和 schema

## 信息隔离
- checker/simulation/personas.py 中的三个作答函数，参数类型只能是 QuestionPublic
- QuestionFull.to_public() 是唯一的转换入口
- 评分标准（rubric）只能出现在 grader 和 checker 中，绝不进入 persona 的 prompt

## 配置与 Prompt
- 禁止硬编码任何阈值，全部从 config/thresholds.yaml 读取
- 禁止在 .py 文件中内嵌超过 3 行的 prompt 字符串，全部放 prompts/*.md
- 禁止硬编码 API Key，只从 .env 读

## Checker
- 能用确定性规则判断的，禁止调用 LLM（数量、schema、算术、字符串匹配、向量相似度）
- 每条规则用 @register 注册，新增规则不得修改调度代码
- 每个 Issue 必须填 detector 字段（rule / llm / sim）

## 其他
- 所有 LLM 调用必须落 trace
- 每个 agent 和 checker 模块必须有对应的 tests/
- 关键逻辑写中文注释，说明"为什么"而不是"做了什么"
```

---

## 七、开发顺序（按可演示性排序）

| 阶段 | 内容 | 完成标志 |
|---|---|---|
| 0 | schema + harness + 假数据 | `call_structured` 能返回校验通过的对象 |
| 1 | ingest + extractor + store | 上传 PDF 能看到带 source_span 的 JSON |
| 2 | matcher + 分项加权 | 分数由代码算出，可解释可复现 |
| 3 | question_gen + followup_gen | 端到端跑通，**此时先做一版 Streamlit** |
| 4 | checker/rules + gate | 规则类 issue 能检出 |
| 5 | reviser + 修订闭环 | 修订前后 diff 可见 |
| 6 | simulation 三人格 | 热力图出来 |
| 7 | flywheel + eval | 通过率曲线 + 准确率数字 |
| 8 | README + 录屏 | — |

阶段 3 结束时必须有一个能跑的 Demo。**先把闭环打通再加深度**,不要在阶段 1 打磨 PDF 解析。

---

## 八、README 必备章节（对照交付物清单）

1. 快速启动（3 条命令以内）
2. 架构图 + 数据流
3. Prompt 设计思路：贴 2–3 个关键 prompt，说明迭代前后对比
4. Checker 校准维度表 + 通过/不通过规则（可直接引用 config/rubric.yaml）
5. 难点与解决方案：结构化输出不稳定 / 幻觉与归因错误 / 打分不可复现
6. 创新点：三人格模拟验题 + 反思飞轮
7. 评测结果：诊断准确率、分数稳定性方差、规则 vs LLM 检出占比
8. 已知局限：用 LLM 验证 LLM 的循环论证风险及缓解措施
