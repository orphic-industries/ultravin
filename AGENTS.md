
### Quick Commands
 - `make init` create the environment and install dependencies
 - `make help` see available commands
 - `make af` format code
 - `make lint` run linter
 - `make typecheck` run type checker
 - `make test` run tests
 - `make check` run all checks (format, lint, typecheck, test)

### Git

- Push your own work straight to `master`; don't open a PR for it.

### Automation

- CI runs `.github/workflows/ci.yaml`, `.github/workflows/security.yaml` and `.github/workflows/vpic-release.yaml`. None of them merges a pull request.
- `vpic-release.yaml` is the one workflow that publishes. From `master`, after the wheel matches NHTSA's unmodified `spvindecode`, it creates a GitHub release of a month's wheels. It uploads nothing to PyPI or crates.io.
- No workflow bumps dependencies or reviews pull requests. Dependencies stay at `uv.lock` and `Cargo.lock` until a person changes them.
- A data month lands through a pull request a person merges. `vpic-release.yaml` opens it with the importer's output, and `make refresh` re-freezes the corpus on its branch. See `docs/DATA_REFRESH.md`.

### Code Conventions

- Always run `make checku` after making changes.

#### Testing
- Use **pytest** (no test classes).
- Always set `match=` in `pytest.raises`.
- Prefer `monkeypatch` over other mocks.
- Mirror the source-tree layout in `tests/`.

#### Exceptions
- Catch only specific exceptions—never blanket `except:` blocks.
- Don’t raise bare `Exception`.

#### Python
- Manage env/deps with **uv** (`uv add|remove`, `uv run -- …`).
- No logging config or side-effects at import time.
- Keep interfaces (CLI, web, etc.) thin; put logic elsewhere.
- Use `typer` for CLI interfaces, `fastapi` for web interfaces, and `pydantic` for data models.