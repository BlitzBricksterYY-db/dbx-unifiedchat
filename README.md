![DBX-UnifiedChat Logo](docs/logos/dbx-unifiedchat-logo-pacman-eating-data.png)

# DBX-UnifiedChat - Databricks Unified Chat

> A multi-agent system for intelligent cross-domain data queries built with LangGraph, Databricks Genie, Lakebase, and Claude models/skills on Databricks Platform.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Databricks-blue.svg)](LICENSE.md)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.0.30-green.svg)](https://github.com/langchain-ai/langgraph)
[![LangChain](https://img.shields.io/badge/LangChain-≥0.1.0-green.svg)](https://github.com/langchain-ai/langchain)
[![MLflow](https://img.shields.io/badge/MLflow-≥3.6.0-orange.svg)](https://mlflow.org/)
[![Databricks SDK](https://img.shields.io/badge/Databricks%20SDK-≥0.20.0-red.svg)](https://github.com/databricks/databricks-sdk-py)
[![Pydantic](https://img.shields.io/badge/Pydantic-≥2.0.0-blue.svg)](https://github.com/pydantic/pydantic)
[![Claude Models](https://img.shields.io/badge/Claude-Sonnet%2FHaiku_4.5-purple.svg)](https://www.anthropic.com/claude)
[![Claude Skills](https://img.shields.io/badge/Claude-Skills-purple.svg)](https://www.anthropic.com/claude)

---

## Overview

Organizations struggle to query data across multiple domains and data sources, requiring deep SQL expertise and knowledge of complex data schemas. **Databricks Unified Chat** solves this by providing an intelligent multi-agent system that routes natural language queries to the appropriate data sources, synthesizes results, and delivers comprehensive answers.

Built on LangGraph, Databricks Genie and Lakebase, this solution enables business users to ask questions spanning multiple data domains without needing to understand the underlying data architecture or write complex SQL queries.

> ### Why use DBX-UnifiedChat?
- **Accuracy of Answer** 
    - Validated with customers and partners, e.g., tumor outcome data analysis.
- **Explanation and Curation** 
    - Results are curated and explained by SQL answer returned and associated explanations.
- **Speed**
    - Optimized with parallel/cache/token reduction/architecture design
    - Achieves 1-2 seconds TTFT
    - For complex query across domains, we see it achieves 1/3 to 1/2 of the time of the No/Low-Code custom agent solution.



## Architecture

![Agent Architecture](docs/architecture/architecture_diagram_simple_v2.png)

The system uses a multi-agent architecture powered by LangGraph:

* **Supervisor Agent (multi-purpose)** - Frontend agent that orchestrates the workflow and coordinates handoffs to other agents
* **Thinking & Planning Agent** - Analyzes queries and creates execution plans based on the query intent and context
* **Genie Agents** - Query individual Genie spaces for domain-specific data
* **SQL Synthesis Agent (table route)** - Combines and synthesizes SQL across table data sources using UC Functions (instructed retrieval)
* **SQL Synthesis Agent (genie route)** - Combines and synthesizes SQL across genie space data sources using Genie agents as tools (parallel execution)
* **SQL Execution Agent** - Executes queries and extracts results
* **Summarize Agent** - Summarizes results and formats responses for the user

The system leverages:
* **LangGraph** for agent orchestration and workflow management
* **LangChain** for agent tools and integrations
* **Lakebase** for state management and long/short-term memory
* **Databricks Genie** as Agent/Tool for natural language to SQL conversion
* **UC Functions** as Tools for multi-step instructed retrieval
* **Databricks SDK** for Databricks platform integration
* **Databricks SQL Warehouse** for query execution
* **Model Serving** for model deployment and serving
* **MLflow** for Agent observability, evaluation and model tracking
* **Pydantic** for data validation and configuration
* **Pytest** for testing framework
* **PyYAML** for configuration management
* **Vector Search** for semantic metadata retrieval
* **Unity Catalog** for data governance and metadata management

### Key Technologies Applied:

* **Multi-turn Chatting** - Supports clarification, continue, refine, and new question flows for conversational interactions
* **Meta-question Fast Route** - Optimized path for handling meta-questions about the system itself
* **Multi-step Instructed Retrieval** - Advanced retrieval strategy in table route with step-by-step instructions
* **Parallel GenieAgent Tool Calls** - Concurrent execution of multiple Genie agents for improved performance in Genie route
* **Lakebase with Long/Short-term Memory** - Persistent memory management for maintaining context across conversations

See [Architecture Documentation](docs/ARCHITECTURE.md) for detailed design.



## Presentation

<a href="https://blitzbricksteryy-db.github.io/dbx-unifiedchat/docs/decks/slides_2slide.html" target="_blank">
  <img src="docs/logos/deck_logo.png" width="600px" alt="View Presentation Slides" />
  <br />
  <b>🚀 Click here to view the Interactive Presentation Slides</b>
</a>



## UI Illustration

![UI Tutorial Annotated](docs/UI/UI_tutorial_annotated.png)

---

## Quick Start

### Prerequisites

* Python 3.10 or higher
* Node.js 18 or higher
* `uv`, `npm`, `jq`, and Databricks CLI
* Databricks workspace with:
  * Genie spaces configured
  * SQL Warehouse configured
  * Permissions to deploy Databricks Asset Bundles and Databricks Apps

### Installation

```bash
git clone https://github.com/databricks-solutions/dbx-unifiedchat.git
cd dbx-unifiedchat
```

### Recommended Workflow

#### 1. Deploy metadata prerequisites from the root bundle

Deploy the root-level Databricks Asset Bundle first, then run the ETL job defined in `resources/etl_pipeline.yml`. This is the prerequisite for both local testing and deployed app environments because it creates the metadata artifacts and vector index the agent relies on.

```bash
databricks bundle validate
databricks bundle deploy
databricks bundle run etl_pipeline
```

Use `-t prod` for the production target when needed.

#### 2. Deploy the app and agent from `agent_app`

The active deployment path is now the Databricks App in `agent_app/`.

Before running `agent_app/scripts/deploy.sh`, make sure you have:

* Databricks CLI installed, authenticated, and able to run `databricks bundle deploy` / `databricks bundle run`
* A Databricks CLI profile available via `--profile <profile>` or `DATABRICKS_CONFIG_PROFILE` in `agent_app/.env`
* `uv` installed locally, because the deploy script uses `uv run` for Lakebase permission bootstrapping
* Python 3.10+ with `PyYAML` available locally, because the script reads `agent_app/databricks.yml` via `import yaml`
* Permission in the target workspace to deploy Databricks Apps / Asset Bundles and access the configured Lakebase, SQL warehouse, catalogs, and schemas

`Node.js`, `npm`, and `jq` are used by the local development workflows, but are not required just to run `agent_app/scripts/deploy.sh`.

```bash
cd agent_app
./scripts/deploy.sh --run
```

Useful options:

* `./scripts/deploy.sh --target prod --run`
* `./scripts/deploy.sh --profile <profile> --run`
* `./scripts/deploy.sh --sync --run`

#### 3. Local app development in `agent_app`

Use the bootstrap/build script once, then use hot reload for normal development.

```bash
cd agent_app

# One-time local bootstrap/build
./scripts/dev-local.sh

# Iterative development with hot reload
./scripts/dev-local-hot-reload.sh
```

Useful options:

* `./scripts/dev-local.sh --profile <profile>`
* `./scripts/dev-local-hot-reload.sh --profile <profile>`
* `./scripts/dev-local-hot-reload.sh --skip-migrate`

#### 4. Legacy model serving path

The old Model Serving agent flow is deprecated. The related code still exists in the repo for now, but the supported deployment model is the Databricks App under `agent_app/`.

---

## Repository Structure

```text
.
├── databricks.yml                  # Root DAB for shared metadata resources
├── resources/
│   └── etl_pipeline.yml            # Job that exports Genie metadata and builds the VS index
├── etl/                            # ETL notebooks used by the root bundle job
├── agent_app/                      # Active Databricks App + agent implementation
│   ├── databricks.yml              # App DAB
│   ├── agent_server/               # Multi-agent backend
│   ├── e2e-chatbot-app-next/       # Frontend and app backend
│   ├── scripts/
│   │   ├── deploy.sh               # Deploy app bundle
│   │   ├── dev-local.sh            # One-time local bootstrap/build
│   │   └── dev-local-hot-reload.sh # Local hot-reload workflow
│   └── tests/                      # App-specific unit tests
├── tests/                          # Root integration and end-to-end tests
├── docs/                           # Project documentation
└── notebooks/                      # Legacy / notebook-based workflows
```

---

## Documentation

### Getting Started

* [**Development Guide**](docs/DEVELOPMENT_GUIDE.md) - Project setup and workflow overview
* [**ETL Guide**](docs/ETL_GUIDE.md) - Root bundle ETL and metadata indexing workflow
* [**Local Development Guide**](docs/LOCAL_DEVELOPMENT.md) - Local environment notes
* [**Configuration Reference**](docs/CONFIGURATION.md) - Configuration details across environments

### Reference

* [**Architecture**](docs/ARCHITECTURE.md) - System design and agent workflows
* [**API Reference**](docs/API.md) - Agent APIs and interfaces
* [**Testing Guide**](tests/README.md) - Run tests and write new tests
* [**Contributing**](CONTRIBUTING.md) - Contribution guidelines
* `agent_app/scripts/deploy.sh` - Current app deployment entry point
* `agent_app/scripts/dev-local.sh` - Current local bootstrap/build entry point
* `agent_app/scripts/dev-local-hot-reload.sh` - Current hot-reload development entry point

---

## Testing

```bash
# Root integration / e2e tests
pytest tests/

# Agent app unit tests
pytest agent_app/tests/
```

See [Testing Guide](tests/README.md) for detailed testing documentation.

---

## Configuration

This repository now centers on two active configuration layers plus one legacy path:

| Configuration | Scope | Purpose |
|--------------|-------|---------|
| `databricks.yml` | Repository root | Shared metadata resources and ETL pipeline deployment |
| `agent_app/databricks.yml` | App bundle | Databricks App deployment and runtime settings |
| `agent_app/.env` | Local app dev | Local script configuration for auth, database, and MLflow |
| Legacy model serving config | Deprecated | Older serving-based flow still present in repo |

See [Configuration Guide](docs/CONFIGURATION.md) for more detail.

---

## Examples

### Metadata Setup

```bash
# Deploy shared metadata resources and build the index
databricks bundle deploy
databricks bundle run etl_pipeline
```

### App Deployment

```bash
cd agent_app
./scripts/deploy.sh --run
```

### Local Development

```bash
cd agent_app
./scripts/dev-local.sh
./scripts/dev-local-hot-reload.sh
```

---

## What's Included

| Component | Description |
|-----------|-------------|
| **Multi-Agent System** | LangGraph-based agent orchestration with specialized agents |
| **Genie Integration** | Native integration with Databricks Genie spaces |
| **Vector Search** | Semantic routing and metadata retrieval |
| **ETL Pipeline** | Metadata enrichment and index building |
| **Deployment Tools** | Notebooks and scripts for Databricks deployment |
| **Test Suite** | Comprehensive unit, integration, and E2E tests |

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for:

* Development setup and workflow
* Code style guidelines and testing requirements
* Pull request process
* Community guidelines

For security vulnerabilities, please see our [Security Policy](SECURITY.md).

---

## Support Disclaimer

The content provided here is for **reference and educational purposes only**. It is not officially supported by Databricks under any Service Level Agreements (SLAs). All materials are provided **AS IS**, without any guarantees or warranties, and are not intended for production use without proper review and testing.

The source code in this project is provided under the Databricks License. All third-party libraries included or referenced are subject to their respective licenses. See [NOTICE.md](NOTICE.md) for third-party license information.

If you encounter issues while using this content, please open a GitHub Issue in this repository. Issues will be reviewed as time permits, but there are **no formal SLAs** for support.

---

## License

(c) 2026 Databricks, Inc. All rights reserved.

The source in this project is provided subject to the Databricks License. See [LICENSE.md](LICENSE.md) for details.

**Third-Party Licenses**: This project depends on various third-party packages. See [NOTICE.md](NOTICE.md) for complete attribution and license information.

---

## Acknowledgments

Built with:

* [**LangGraph**](https://github.com/langchain-ai/langgraph) - Agent orchestration and workflow management
* [**Databricks Genie**](https://docs.databricks.com/genie/) - Natural language to SQL conversion
* [**Databricks Vector Search**](https://docs.databricks.com/vector-search/) - Semantic search and retrieval
* [**MLflow**](https://mlflow.org/) - Model deployment and serving
* [**Unity Catalog**](https://docs.databricks.com/data-governance/unity-catalog/) - Data governance and metadata

---

## About Databricks Field Solutions

This repository is part of the [Databricks Field Solutions](https://github.com/databricks-solutions) collection - a curated set of real-world implementations, demonstrations, and technical content created by Databricks field engineers to share practical expertise and best practices.
