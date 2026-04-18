# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `agent_app/tests/README.md` for the supported test workflow

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

## [1.0.0] - Initial Public Release

### Added
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
