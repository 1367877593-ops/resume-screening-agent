.PHONY: install test demo demo-cache configure-live live-check run eval clean

PY  := .venv/bin/python
PIP := .venv/bin/pip

.venv:
	python3 -m venv .venv

install: .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[app,dev]"

test: .venv
	$(PY) -m pytest tests/ -q

# 无 Key 回放：固定使用 data/demo_cache/，不初始化真实模型客户端
demo: .venv
	DEMO_MODE=1 $(PY) -m streamlit run app/main.py

# 样例、Prompt 或 Schema 变化后重建内置回放，并立即跑回归测试
demo-cache: .venv
	$(PY) scripts/generate_demo_cache.py
	$(PY) -m pytest tests/test_demo_replay.py -q

# 在终端中隐藏输入 Key，并以 0600 权限写入被 Git 忽略的 .env
configure-live: .venv
	$(PY) scripts/configure_live.py

# 发起一次极小的真实模型请求，验证鉴权、模型名和 JSON 输出
live-check: .venv
	$(PY) scripts/check_live_connection.py

run: .venv
	$(PY) -m streamlit run app/main.py

# 默认无 Key 回放。真实稳定性数字：RUNS=5 DEMO_MODE=0 make eval
RUNS ?= 1
DEMO_MODE ?= 1
eval: .venv
	DEMO_MODE=$(DEMO_MODE) $(PY) eval/run_eval.py --runs $(RUNS)

clean:
	rm -rf data/runtime .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
