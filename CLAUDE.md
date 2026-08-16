# 项目约束

本文件供 AI 编程辅助工具（Claude Code / Codex / Qoder 等）阅读。
完整架构设计见 `ARCHITECTURE.md`，两份文件必须保持一致，改动其一时同步另一份。

## 项目简介

智能简历解析与试题生成引擎。输入 JD + 若干份简历（PDF/Word），
输出结构化的匹配评分、是否推进面试的决策建议、面试题目与追问，
并由 Checker Agent 校验后闭环修订。

## 交付分层（最重要的约束）

按 L1 → L2 → L3 顺序推进，**上一层未跑通不写下一层的代码**：

- **L1 闭环层**（✅ 已完成）：上传 → 提取 → 匹配打分与推进决策 → 排序 → 试题与追问 → 规则 Checker → 修订闭环 → Streamlit 展示
- **L2 增强层**：三人格盲评模拟（✅ 已完成）+ 反思飞轮（未实现）
- **L3 加固层**：`eval/run_eval.py` 与 trace 面板（✅ 已完成）、语义 Checker（未实现）、UI 打磨

任何时刻仓库里都必须有一个能跑通的 Demo。不要在闭环未完成时去优化加固层的东西。

## 依赖方向（违反即为设计错误）

```
schema ← harness ← store/ingest ← agents/checker ← pipeline ← app
```

- `agents/` 和 `checker/` 下**禁止** import openai / anthropic / 任何厂商 SDK，
  所有 LLM 调用必须走 `harness.structured.call_structured()`
- `app/` 只能 import `pipeline` 和 `schema`，不得直接调用 agents 或 checker
- `schema/` 不依赖任何其他模块

## 分数与决策由代码算

- LLM 只输出**单项判定**（YES / PARTIAL / NO）与理由，**禁止让 LLM 直接给总分**
- 总分由 `agents/scorer.py` 加权求和；推进决策由阈值规则给出
- 判定顺序：硬性要求未满足 → REJECT；否则按 advance / hold 阈值分档
- 阈值全部来自 `config/thresholds.yaml`
- `scorer.py` 不得调用 LLM，必须可单测

## 信息隔离（防泄题）

- `checker/simulation/personas.py` 中三个作答函数的参数类型只能是 `QuestionPublic`
- `QuestionFull.to_public()` 是唯一的转换入口
- 评分标准（rubric）只能出现在 grader 和 checker 中，**绝不进入 persona 的 prompt**
- 这一隔离由类型签名保证，不依赖 prompt 中的自然语言约束
- 给 `QuestionPublic` 加字段等于扩大泄题面，必须是一次显式改动，不要顺手加

## 三人格盲评

- 判定逻辑在 `checker/simulation/diagnose.py`，**纯代码不调 LLM**，阈值取自
  `config/thresholds.yaml` 的 `simulation` 段，必须可单测
- 诊断结论经 `content_rules.py` 里注册的规则翻译成 `Issue`（`detector="sim"`）；
  规则函数本身不发起任何调用
- 盲评标签按 `question_id` 派生种子打乱：**每题独立**（否则模型能跨题推断身份）、
  **结果确定**（否则缓存键漂移，无 Key 回放必然未命中）
- 每人格一次答完整套题，阅卷官一次评完 —— 调用量固定为每轮 4 次，与题目数量无关
- 确定性规则先跑：出现 blocker 时跳过模拟，那套题马上要被重写
- `SIMULATION_ENABLED=0` 必须能整体关掉，且不影响 L1 闭环

## 配置与 Prompt

- 禁止硬编码任何阈值，全部从 `config/thresholds.yaml` 读取
- 禁止在 `.py` 文件中内嵌超过 3 行的 prompt 字符串，全部放 `prompts/*.md`
- 禁止硬编码 API Key，只从 `.env` 读取（通过 `config/settings.py`）
- `.env` 必须在 `.gitignore` 中
- **修改 prompt 时必须先把旧版本归档到 `prompts/_archive/`**，version 号加一，
  并在 `NOTES.md` 记一句改动原因 —— 交付文档要求展示迭代对比，事后补写没有素材

## Checker

- 能用确定性规则判断的，禁止调用 LLM
  （数量校验、schema 校验、算术校验、字符串匹配、向量相似度）
- 每条规则用 `@register` 注册，新增规则不得修改调度代码
- 规则文件按性质分两个：`structure_rules.py`（数量/schema/算术）与
  `content_rules.py`（证据存在性/归因/查重/盲评结论翻译），不要继续拆细
- 每个 `Issue` 必须填写 `detector` 字段（`rule` / `llm` / `sim`）
- 新增 issue_code 必须同步写进 `config/rubric.yaml`，两边对不上就是错
- 统计「规则 vs LLM 检出占比」只能用 `StageOutcome.detected`（各轮累计），
  不能用最后一轮的 `report` —— 后者会漏掉所有已修复的问题，把占比算歪
- 校准维度命名沿用需求原词：**数据准确性**、**归因错误**
- 通过/不通过判定统一走 `checker/gate.py`，业务代码里不手写判定逻辑
- 修订轮数上限为 2，超出即熔断转人工，禁止无限循环

## 编排

- 只对 `ADVANCE` / `HOLD` 的候选人生成试题，被拒候选人不出题
- `REVISE` 后只对变更对象重跑校验，未变更的复用上轮结论
- 修订后必须重跑证据类规则，防止修订过程引入新幻觉

## 演示模式

- `DEMO_MODE=1` 时强制走 `data/demo_cache/` 回放，不发起任何真实请求
- **缓存未命中必须显式抛错**，绝不静默回退到真实调用
- `harness/cache.py` 属于 L1，不是后期优化项

## 工程规范

- 所有 LLM 调用必须落 trace（prompt / 响应 / token / 耗时 / 重试次数）
- 每个 agent 和 checker 模块必须有对应的 `tests/`
- 关键逻辑写中文注释，说明"为什么这么做"而不是"做了什么"
