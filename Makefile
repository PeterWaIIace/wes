PYTHON ?= python3
CONFIG ?= task.wes

.PHONY: help install install-dev run serve test lint format fix check

help:
	@echo "Targets:"
	@echo "  make install      Install runtime dependencies"
	@echo "  make install-dev  Install project with dev tools"
	@echo "  make run          Run CLI with CONFIG=$(CONFIG)"
	@echo "  make serve        Start web interface on port 8000"
	@echo "  make test         Run tests with pytest"
	@echo "  make lint         Run Ruff lint checks"
	@echo "  make format       Format code with Ruff"
	@echo "  make fix          Auto-fix lint issues and format"
	@echo "  make check        Run lint checks, format check, and tests"

install:
	$(PYTHON) -m pip install -r requirements.txt

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	$(PYTHON) -m wes.cli $(CONFIG)

serve:
	$(PYTHON) -m wes.cli serve

test:
	pytest -v

lint:
	ruff check .

format:
	ruff format .

fix:
	ruff check . --fix
	ruff format .

check:
	ruff check .
	ruff format --check .
	pytest -v
