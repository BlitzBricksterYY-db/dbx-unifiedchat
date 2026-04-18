# Agent App Tests

This is the supported Python test surface for the repository.

## Run all tests

```bash
cd agent_app
uv sync --dev
uv run pytest tests/ -v
```

## Run a single test file

```bash
cd agent_app
uv run pytest tests/unit/test_lakebase_config.py -v
```

## Current layout

- `tests/unit/` for focused unit coverage
- `tests/*.py` for broader backend behavior tests

## Notes

- Run tests from `agent_app/` so imports resolve against the app package.
- The previous root-level `tests/` suite has been removed.
