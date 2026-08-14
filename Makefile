.PHONY: install test demo run eval clean

PY  := .venv/bin/python
PIP := .venv/bin/pip

.venv:
	python3 -m venv .venv

install: .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[app,dev]"

test: .venv
	$(PY) -m pytest tests/ -q

# 无 Key 回放。app/main.py 属于 L1 阶段 5，尚未实现时给出明确提示而不是一串堆栈
demo: .venv
	@test -f app/main.py || { echo "app/main.py 尚未实现（L1 阶段 5）。当前可运行：make test"; exit 1; }
	DEMO_MODE=1 $(PY) -m streamlit run app/main.py

run: .venv
	@test -f app/main.py || { echo "app/main.py 尚未实现（L1 阶段 5）。当前可运行：make test"; exit 1; }
	$(PY) -m streamlit run app/main.py

eval: .venv
	@test -f eval/run_eval.py || { echo "eval/run_eval.py 属于 L3，尚未实现"; exit 1; }
	$(PY) eval/run_eval.py

clean:
	rm -rf data/runtime .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
