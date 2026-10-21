.PHONY: demo test eval compliance lint

PY ?= python

demo:
	$(PY) -m metricguard.cli ask "9月复购率按渠道"

catalog:
	$(PY) -m metricguard.cli catalog

test:
	$(PY) -m pytest

eval:
	$(PY) evals/run.py

compliance:
	$(PY) scripts/compliance_check.py .

lint:
	ruff check src tests evals
