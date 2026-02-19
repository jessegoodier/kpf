# Default target - list available recipes
default:
    @just --list

# Environment setup
# Create virtual environment and install dependencies
venv:
    uv venv
    uv sync
    @echo "Virtual environment created. Activate with: source .venv/bin/activate"

# Installation
# Install package in current environment
install:
    uv pip install .

# Install package with dev dependencies in current environment
install-dev:
    uv pip install -e '.[dev]'

# Code quality
# Format code with ruff and isort
format:
    uvx isort .
    uvx ruff check . --fix
    uvx ruff format .

# Run linting checks
lint:
    uvx isort . --check-only
    uvx ruff check .
    uvx ruff format --check .

# Verify code is formatted and passes linting
check-clean: lint
    @echo "✅ Code is clean and properly formatted"

# Testing
# Run tests with pytest
test:
    uv run pytest

# Run security and dependency audit
audit:
    uv run scripts/audit_dependencies.py

# Run tests with coverage report
test-cov:
    uv run pytest --cov=kpf --cov-report=term-missing --cov-report=html

# Build
# Build wheel and sdist
build: clean
    uv build

# Clean build artifacts and cache files
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
# Show current version
version:
    @python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"

# Bump patch version
bump-patch:
    uvx bump-my-version bump patch

# Bump minor version
bump-minor:
    uvx bump-my-version bump minor

# Bump major version
bump-major:
    uvx bump-my-version bump major

# Release
# Create GitHub release based on current version
release: check-clean
    @echo "Creating release for version $(just version)..."
    @if [ -z "$(git status --porcelain)" ]; then \
        echo "✅ Working directory is clean"; \
    else \
        echo "❌ Working directory has uncommitted changes"; \
        exit 1; \
    fi
    gh release create v$(just version) --generate-notes --latest

# Development helpers
# Setup development environment
dev-setup: venv install-dev
    @echo "✅ Development environment ready!"
    @echo "   Activate with: source .venv/bin/activate"
    @echo "   Run tests with: just test"
    @echo "   Format code with: just format"

# Quick development workflow
dev-check: format test
    @echo "✅ Development check complete"
