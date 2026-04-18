![DBX-UnifiedChat Logo](docs/logos/dbx-unifiedchat-logo-pacman-eating-data.png)

# DBX-UnifiedChat

> A Databricks App for cross-domain data exploration with LangGraph, Databricks Genie, Lakebase, Vector Search, and MLflow tracing.

[![License](https://img.shields.io/badge/license-Databricks-blue.svg)](LICENSE.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

`DBX-UnifiedChat` now has one supported application workflow: the Databricks App
bundle under `agent_app/`. The older root-level Model Serving path has been
removed from this repository.

The supported stack includes:

- `agent_app/agent_server/` for the backend agent runtime
- `agent_app/e2e-chatbot-app-next/` for the UI and app backend
- `agent_app/resources/*.yml` for bundle-managed app and job resources
- `etl/` for metadata export, enrichment, and vector index build notebooks

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- `uv`, `npm`, `jq`, and Databricks CLI
- Databricks workspace access with permissions for Apps, Jobs, SQL Warehouse, and Genie

### Deploy the app

```bash
cd agent_app
./scripts/deploy.sh --target dev --run-job full --start-app
```

Useful variants:

- `./scripts/deploy.sh --target dev --run-job prep`
- `./scripts/deploy.sh --target prod --run-job full --start-app`
- `./scripts/deploy.sh --target dev --list-jobs`
- `./scripts/deploy.sh --target prod --run-job full --ci --skip-bootstrap`

### Local development

```bash
cd agent_app

# One-time bootstrap + local startup
./scripts/dev-local.sh

# Hot reload loop
./scripts/dev-local-hot-reload.sh
```

## Repository Structure

```text
.
├── agent_app/                      # Canonical Databricks App bundle
│   ├── databricks.yml              # Bundle variables and targets
│   ├── agent_server/               # Python backend / LangGraph runtime
│   ├── e2e-chatbot-app-next/       # Frontend and app backend
│   ├── resources/                  # App and job resources
│   ├── scripts/                    # Deploy and local dev entrypoints
│   ├── tests/                      # Supported Python test suite
│   └── workflows/                  # Databricks notebook tasks
├── docs/                           # Project documentation
├── etl/                            # Shared ETL notebooks used by the bundle
└── supplemental_scripts/           # Utility scripts still used outside deploy flow
```

## Testing

Run the supported Python tests from `agent_app`:

```bash
cd agent_app
uv sync --dev
uv run pytest tests/ -v
```

See [Testing Guide](agent_app/tests/README.md) for the current test layout.

## Configuration

The active configuration layers are:

| File | Purpose |
|------|---------|
| `agent_app/databricks.yml` | Canonical deployment targets, bundle variables, ETL, and app settings |
| `agent_app/.env` | Local-only runtime and machine-specific settings |

See [Configuration Guide](docs/CONFIGURATION.md) for details.

## Documentation

- [Development Guide](docs/DEVELOPMENT_GUIDE.md)
- [Local Development Guide](docs/LOCAL_DEVELOPMENT.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Configuration Guide](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [Testing Guide](agent_app/tests/README.md)
- [Contributing](CONTRIBUTING.md)

## Support Disclaimer

This content is provided for reference and educational purposes only. It is not
officially supported by Databricks under any SLA and is provided AS IS.

## License

Copyright (c) 2026 Databricks, Inc.

See [LICENSE.md](LICENSE.md) and [NOTICE.md](NOTICE.md) for licensing details.
