.PHONY: install test demo demo-cache run eval clean

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

run: .venv
	$(PY) -m streamlit run app/main.py

eval: .venv
	@test -f eval/run_eval.py || { echo "eval/run_eval.py 属于 L3，尚未实现"; exit 1; }
	$(PY) eval/run_eval.py

clean:
	rm -rf data/runtime .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
