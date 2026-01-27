.PHONY: help venv install install-dev format lint test clean build release check-clean version bump-patch bump-minor bump-major audit

# Default target - show help
help:
	@echo "Available targets:"
	@echo "  venv        - Create virtual environment and install dependencies"
	@echo "  install     - Install package in current environment"
	@echo "  install-dev - Install package with dev dependencies in current environment"
	@echo "  format      - Format code with ruff and isort"
	@echo "  lint        - Run linting checks"
	@echo "  test        - Run tests with pytest"
	@echo "  check-clean - Verify code is formatted and passes linting"
	@echo "  build       - Build wheel and sdist"
	@echo "  clean       - Clean build artifacts and cache files"
	@echo "  version     - Show current version"
	@echo "  bump-patch  - Bump patch version"
	@echo "  bump-minor  - Bump minor version" 
	@echo "  bump-major  - Bump major version"
	@echo "  release     - Create GitHub release based on current version"
	@echo "  audit       - Run security and dependency audit"

# Environment setup
venv:
	uv venv
	uv sync
	@echo "Virtual environment created. Activate with: source .venv/bin/activate"

# Installation
install:
	uv pip install .

install-dev:
	uv pip install -e '.[dev]'

# Code quality
format:
	uvx isort .
	uvx ruff check . --fix
	uvx ruff format .

lint:
	uvx isort . --check-only
	uvx ruff check .
	uvx ruff format --check .

check-clean: lint
	@echo "✅ Code is clean and properly formatted"

# Testing
test:
	uv run pytest

audit:
	uv run scripts/audit_dependencies.py

test-cov:
	uv run pytest --cov=kpf --cov-report=term-missing --cov-report=html

# Build
build: clean
	uv build

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Version management
version:
	@python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"

bump-patch:
	uvx bump-my-version bump patch

bump-minor:
	uvx bump-my-version bump minor

bump-major:
	uvx bump-my-version bump major

# Release
release: check-clean
	@echo "Creating release for version $$(make version)..."
	@if [ -z "$$(git status --porcelain)" ]; then \
		echo "✅ Working directory is clean"; \
	else \
		echo "❌ Working directory has uncommitted changes"; \
		exit 1; \
	fi
	gh release create v$$(make version) --generate-notes --latest

# Development helpers
dev-setup: venv install-dev
	@echo "✅ Development environment ready!"
	@echo "   Activate with: source .venv/bin/activate"
	@echo "   Run tests with: make test"
	@echo "   Format code with: make format"

# Quick development workflow
dev-check: format test
	@echo "✅ Development check complete"