# 项目约束

本文件供 AI 编程辅助工具（Claude Code / Codex / Qoder 等）阅读。
完整架构设计见 `ARCHITECTURE.md`。

## 项目简介

智能简历解析与试题生成引擎。输入 JD + 若干份简历（PDF/Word），
输出结构化的匹配评分、面试题目与追问，并由 Checker Agent 校验后闭环修订。

## 依赖方向（违反即为设计错误）

```
schema ← harness ← store/ingest ← agents/checker ← pipeline ← app
```

- `agents/` 和 `checker/` 下**禁止** import openai / anthropic / 任何厂商 SDK，
  所有 LLM 调用必须走 `harness.structured.call_structured()`
- `app/` 只能 import `pipeline` 和 `schema`，不得直接调用 agents 或 checker
- `schema/` 不依赖任何其他模块

## 信息隔离（防泄题）

- `checker/simulation/personas.py` 中三个作答函数的参数类型只能是 `QuestionPublic`
- `QuestionFull.to_public()` 是唯一的转换入口
- 评分标准（rubric）只能出现在 grader 和 checker 中，**绝不进入 persona 的 prompt**
- 这一隔离由类型签名保证，不依赖 prompt 中的自然语言约束

## 配置与 Prompt

- 禁止硬编码任何阈值，全部从 `config/thresholds.yaml` 读取
- 禁止在 `.py` 文件中内嵌超过 3 行的 prompt 字符串，全部放 `prompts/*.md`
- 禁止硬编码 API Key，只从 `.env` 读取（通过 `config/settings.py`）
- `.env` 必须在 `.gitignore` 中

## Checker

- 能用确定性规则判断的，禁止调用 LLM
  （数量校验、schema 校验、算术校验、字符串匹配、向量相似度）
- 每条规则用 `@register` 注册，新增规则不得修改调度代码
- 每个 `Issue` 必须填写 `detector` 字段（`rule` / `llm` / `sim`）
- 通过/不通过判定统一走 `checker/gate.py`，业务代码里不手写判定逻辑
- 修订轮数上限为 2，超出即熔断转人工，禁止无限循环

## 工程规范

- 所有 LLM 调用必须落 trace（prompt / 响应 / token / 耗时 / 重试次数）
- 每个 agent 和 checker 模块必须有对应的 `tests/`
- 关键逻辑写中文注释，说明"为什么这么做"而不是"做了什么"
- 修订后必须重跑证据类规则，防止修订过程引入新幻觉
