# Demo cache

这里的 JSON 文件是仓库内置样例的结构化响应回放。`make demo` 使用固定的
`demo / demo-v1` 缓存命名空间，因此不受评审者本机 `.env` 中 provider、模型名
或 API Key 的影响，也不会发起网络请求。

这些响应由 `scripts/generate_demo_cache.py` 中经过人工核对的夹具生成：每条引用
都能在 `data/samples/` 的原文中找到，完整结果会再次经过同一套 Pydantic Schema、
Checker、代码算分和排序状态机，而不是绕过业务逻辑直接展示静态页面。

修改样例、Prompt 版本或 Schema 后重新生成并验证：

```bash
.venv/bin/python scripts/generate_demo_cache.py
.venv/bin/python -m pytest -q
```
