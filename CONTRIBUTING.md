# Contributing to DBX-UnifiedChat

Thank you for your interest in contributing to this project. Please use the workflow below when proposing changes.

## Current Asset Status

This repository has three active workflows:

1. Root Databricks Asset Bundle for shared metadata and ETL.
   - In `dev`, deploy the root bundle and run the ETL pipeline to create the metadata artifacts and vector index.
   - If your `dev` workspace already has a shared metadata/index setup, you can reuse that instead of rebuilding it.
2. `agent_app/` Databricks Asset Bundle for the app and Lakebase-backed runtime.
   - This is the active deployment path for the agent application.
   - You can point it at another Lakebase database when appropriate, as long as the schema and tables are kept separate.
3. Local development in `agent_app/`.
   - Use the local bootstrap and hot-reload scripts for iterative development across the frontend, middleware, and backend.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/databricks-solutions/dbx-unifiedchat.git
   cd dbx-unifiedchat
   ```

2. Create a virtual environment and install the project with development dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. If your change touches Databricks integration, deployment, or app runtime, review the setup notes in `README.md` and `tests/README.md` before testing.

4. For app-specific work, use the `agent_app/` workflow described in the repository README.

5. When you need to recreate the metadata index in `dev`, deploy the root bundle and run the ETL pipeline:
   ```bash
   databricks bundle validate
   databricks bundle deploy
   databricks bundle run etl_pipeline
   ```

6. When you need to deploy the app stack with Lakebase, use the app bundle:
   ```bash
   cd agent_app
   ./scripts/deploy.sh --run
   ```

7. For local development in `agent_app`, use the local bootstrap or hot-reload scripts:
   ```bash
   cd agent_app
   ./scripts/dev-local.sh
   ./scripts/dev-local-hot-reload.sh
   ```

## Code Standards

- Follow PEP 8 conventions.
- Include type annotations for public functions.
- Keep changes focused and easy to review.
- Update documentation when behavior, configuration, or workflows change.
- Follow the formatting and line-length settings in `pyproject.toml` (100 characters).

## Linting

This repository uses `black`, `isort`, `flake8`, and `mypy`.

```bash
black .
isort .
flake8 .
mypy src/multi_agent
```

## Testing

Run the tests that match the scope of your change:

```bash
# Root integration and end-to-end tests
pytest tests/

# App-specific tests
pytest agent_app/tests/

# Marker-based subsets
pytest -m unit
pytest -m integration
pytest -m e2e

# Coverage
pytest --cov=src/multi_agent tests/
```

Databricks workspace access is required for integration and end-to-end testing.

## Pull Request Process

1. Open an issue first for significant changes so the approach can be discussed early.
2. Create a feature branch from `main`.
3. Make your changes with clear, descriptive commits.
4. Run the relevant lint and test commands before opening a PR.
5. Open the PR with a short summary, context for the change, and the testing you performed.
6. Address review feedback and keep the PR focused on one concern when possible.

## Security

- Never commit credentials, tokens, or other secrets.
- Use `.env.example` as the starting point for local configuration.
- Report security issues through coordinated disclosure. Do not use public issues or pull requests for vulnerabilities; see `SECURITY.md` and contact `security@databricks.com`.

## License

By contributing, you agree that your changes are covered by the license in `LICENSE.md`.
