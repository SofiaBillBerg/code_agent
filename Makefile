# Small Makefile for common tasks
PY=python
VENV=.venv

.PHONY: test scaffold run cli docs

test:
	$(PY) -m pytest -q

scaffold:
	$(PY) -m code_agent.cli scaffold $(ROOT) --name=$(NAME)

cli:
	$(PY) -m code_agent.cli $(ARGS)

run:
	# example run wrapper; customize env vars as needed
tac:
	@echo "No-op"

docs:
	# build docs if mkdocs/quarto present
	if command -v mkdocs >/dev/null 2>&1; then mkdocs build; else echo "mkdocs not installed"; fi
