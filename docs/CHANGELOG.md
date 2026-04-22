# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-04-21

### Changed
- Updated local bundle configuration guidance to use a public-safe committed `databricks.yml` baseline alongside a private `databricks.local.yml` workflow
- Updated local development scripts and documentation to align with the current bundle-driven workflow
- Improved boxplot normalization, validation, and chart materialization behavior
- Improved chart generation and related app configuration handling

### Added
- Support for boxplots without an X-axis grouping field
- `agent_app/databricks.local.yml.example` as a template for private local bundle configuration
- Additional automated coverage for stale clarification stream reconnect behavior and chart-spec handling

### Fixed
- Prevented stale clarification modals from replaying after a user answers a clarification prompt
- Stopped clarification turns from being re-advertised as active resumable streams
- Fixed boxplot validation so an empty X axis is accepted when appropriate

### Removed
- Deprecated `agent_app/scripts/quickstart.py` entrypoint
- Outdated references to `.env.example` in documentation and configuration guidance

## [1.1.0] - 2026-04-20

### Added
- `agent_app/tests/README.md` for the supported test workflow
- `current_chart` support in the rechart API and interactive chart components for richer chart editing context
- Additional chart builder and interactive chart test coverage

### Changed
- Refactored chart generation to better handle pre-aggregated metrics, histogram behavior, and chart validation
- Improved chart workspace and visualization behavior for richer chart editing flows
- Refreshed app, ETL, and configuration documentation for the current workflow

### Fixed
- Improved chart-related error handling and summary output quality

### Removed
- `agent_app/.env.example` from the supported local configuration workflow

## [1.0.0] - 2026-04-19

### Added
- Initial public release of the Databricks multi-agent application
- Multi-agent system with LangGraph
- Support for cross-domain Genie queries
- SQL synthesis across multiple tables
- Vector search for semantic routing
- Short-term and long-term memory with Lakebase
- Model Serving deployment support
- Comprehensive test suite
- ETL pipeline for metadata enrichment

### Features
- SupervisorAgent for orchestration
- ThinkingPlanningAgent with vector search
- Multiple GenieAgents for parallel querying
- SQLSynthesisAgent for complex joins
- SQLExecutionAgent for query execution
- ClarificationAgent for ambiguous queries
- SummarizeAgent for response formatting

### Infrastructure
- Unity Catalog integration
- Vector Search for metadata
- Databricks Genie integration
- Lakebase for state management
- MLflow for tracing and runtime integration

### Changed
- Simplified the repository to a single supported app workflow rooted in `agent_app/`
- Updated CI and pre-commit to validate the supported `agent_app` test surface
- Rewrote top-level docs around the Databricks App bundle and local app development

### Removed
- Root-level Model Serving deployment path
- Legacy `src/`, `Notebooks/`, and root `tests/` directories
- Root packaging and setup files tied only to the removed workflow
- Obsolete helper scripts such as `dab_*`, local LangGraph entrypoints, and upload helpers

### Security
- Local secrets remain isolated to `agent_app/.env`

---

## Version History

This project evolved through multiple iterations before public release:
- Internal development with various prototypes
- Streaming implementation and optimization
- State management improvements
- Configuration refactoring
- Documentation and testing enhancements
- Public release preparation

See [archived plans](../.cursor/plans/) for detailed development history.
