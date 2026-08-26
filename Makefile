# Small Makefile for common tasks

# Define Python executable and virtual environment path
PY := ./.venv/bin/python
VENV_ACTIVATE := source ./.venv/bin/activate

.PHONY: all install test scaffold run cli docs clean

all: install test docs

install:
	@echo "Setting up virtual environment and installing dependencies..."
	@if [ ! -d "$(VENV)" ]; then uv venv; fi
	$(VENV_ACTIVATE); uv pip install -e .[dev,docs]

test:
	@echo "Running tests..."
	$(VENV_ACTIVATE); $(PY) -m pytest -q

cli:
	@echo "Running berg_agents CLI command: $(ARGS)..."
	$(VENV_ACTIVATE); $(PY) -m berg_agents.cli $(ARGS)

run:
	@echo "Starting interactive berg_agents..."
	$(VENV_ACTIVATE); $(PY) -m berg_agents.cli chat

docs:
	@echo "Building Quarto documentation..."
	@if ! command -v quarto >/dev/null 2>&1; then \
		echo "Error: Quarto is not installed. Please install it from https://quarto.org/docs/getting-started/"; \
		exit 1; \
	fi
	$(VENV_ACTIVATE); $(PY) -m pip install -e .[docs] # Ensure docs dependencies are installed
	quarto render

clean:
	@echo "Cleaning up build artifacts and caches..."
	rm -rf ./.venv
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf docs/docs_web # Remove built Quarto site
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.bak" -delete
