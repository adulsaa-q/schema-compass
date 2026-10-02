# Contributing to schema-compass

Thank you for your interest in contributing to `schema-compass`!

We follow Test-Driven Development (TDD), strict typing, deterministic AST safety analysis, and graph-theoretic path optimization.

---

## Development Setup

`schema-compass` uses [`uv`](https://github.com/astral-sh/uv) for fast, deterministic Python environment management.

### Prerequisites
- Python 3.12+
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh` or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`)

### Getting Started

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/schema-compass.git
   cd schema-compass
   ```

2. **Sync virtual environment with dev dependencies:**
   ```bash
   uv sync
   ```

3. **Verify the test suite passes:**
   ```bash
   uv run pytest
   ```

---

## Engineering Standards

1. **Test-Driven Development (TDD):**
   - Always write a failing test first in `tests/` demonstrating the bug or new feature.
   - Run `uv run pytest` to confirm the test fails (RED).
   - Implement the minimal code required to pass (GREEN).
   - Refactor for clarity, performance, and type safety (REFACTOR).

2. **Static Typing & Code Style:**
   - 100% type annotations on all function and method signatures.
   - Run Ruff linter and formatter before submitting a Pull Request:
     ```bash
     uv run ruff check --fix .
     uv run ruff format .
     ```

3. **Database dialect safety:**
   - Never introduce dependencies on live production databases in tests.
   - All tests must run locally using in-memory SQLite fixtures (`:memory:`) or mock catalog dataclasses.

---

## Pull Request Process

1. Create a feature branch: `git checkout -b feat/your-feature-name`.
2. Commit with conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`, `test: ...`).
3. Push to your fork and submit a PR to `main`.
4. Ensure all GitHub Actions CI checks pass.
