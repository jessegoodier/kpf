# AGENTS.md

## Project Overview

`kpf` is a Python terminal utility that provides a better UX for `kubectl port-forward`. It features interactive service selection, automatic restarts, and multi-resource support.

- Core logic: `src/kpf`
- Tests: `tests/`
- Package manager: `uv`

## Setup & Development

- **Install dependencies**: `just venv` (uses `uv sync`)
- **Activate environment**: `source .venv/bin/activate`
- **Install dev dependencies**: `just install-dev`

## Common Commands

- **Run Tests**: `just test` or `uv run pytest`
- **Format Code**: `just format` (runs `ruff` and `isort`)
- **Lint Code**: `just lint` (runs `ruff check` and `isort --check-only`)
- **Clean Build**: `just clean`
- **Check All**: `just check-clean` (verifies formatting and linting)

## Code Style & Conventions

- **Language**: Python 3.14+
- **Formatting**: Enforced by `ruff` and `isort`.
- **Line Length**: 100 characters (defined in `pyproject.toml`).
- **Imports**: Sorted by `isort` (profile: black).
- **Type Hints**: Encouraged.

## Testing Instructions

- **Framework**: `pytest`
- **Coverage**: `pytest-cov` is configured.
- Run `just test` to execute the full suite.
- Write new tests in `tests/` with the prefix `test_`.
- Ensure all tests pass before submitting changes.

## Release Process

- versioning and releases are handled by @./.github/workflows/release.yml

## Structure (Key Files)

- `src/kpf/main.py`: Entry point logic
- `src/kpf/kfwd.py`: Port forwarding logic
- `src/kpf/validators.py`: Input validation
- `pyproject.toml`: Configuration for build, dependencies, and tools
- `Makefile`: Command shortcuts
- `src/kpf/completions/kpf.bash`: Bash completion script
- `src/kpf/completions/_kpf`: Zsh completion script

## Must have for all changes

- Verify changes to completions are needed or not in `src/kpf/completions/`
