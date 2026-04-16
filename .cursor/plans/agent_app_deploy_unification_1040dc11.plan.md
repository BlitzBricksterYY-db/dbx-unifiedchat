---
name: agent app deploy unification
overview: "Consolidate bundle ownership into `agent_app/databricks.yml`, keep the repo layout intact for now, and support two equivalent deployment paths: a self-bootstrapping local/CI flow via `agent_app/scripts/deploy.sh` and a Databricks-native flow via jobs/notebooks."
todos:
  - id: canon-bundle-root
    content: Define `agent_app/databricks.yml` as the only maintained bundle config and normalize shared variable names.
    status: pending
  - id: relocate-entrypoints
    content: Bring ETL/deploy/validation entrypoints under `agent_app` so bundle packaging no longer depends on parent-directory references.
    status: pending
  - id: job-only-resources
    content: Refactor `agent_app/resources/` toward job-only bundle resources and move infra/app setup into notebooks or scripts.
    status: pending
  - id: dual-deploy-interfaces
    content: Align `deploy.sh` and the notebook/job flow so both invoke the same prep and full-deploy stages, with `deploy.sh` also bootstrapping local terminal prerequisites.
    status: pending
  - id: retire-root-bundle
    content: Update CI/docs and retire the root bundle after the `agent_app` replacement is validated.
    status: pending
isProject: false
---

# Consolidate Bundle Ownership And Dual Deploy Paths

## Goal

Keep the repository root layout unchanged in the short term, make [`agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml) the only maintained bundle source of truth, move bundle-managed ETL entrypoints under `agent_app/`, and support two user-selectable deployment paths that drive the same underlying deploy flow.

## Desired End State

- One maintained bundle entrypoint: [`agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml)
- Root [`databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/databricks.yml) retired after migration
- ETL, prep, app deploy, and validation jobs defined under [`agent_app/resources/`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/resources)
- Two supported deploy modes:
  - shell-first via [`agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh), including local bootstrap for `uv`, the virtualenv, and terminal prerequisites
  - Databricks-native via notebooks/jobs, building on [`agent_app/scripts/deploy_notebook.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py), [`agent_app/scripts/notebook_deploy_lib.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/notebook_deploy_lib.py), and the existing merge direction in [`.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md)

## Core Design

### 1. Make `agent_app` the operational root

Use [`agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml) as the canonical place for:
- target definitions
- workspace/profile resolution
- shared variables for ETL, app runtime, Lakebase, MLflow, and app validation
- job include patterns for all maintained deploy resources

Normalize overlapping names so one variable model feeds both ETL and app code. Prefer one canonical naming contract rather than parallel aliases such as `catalog` vs `catalog_name` or `warehouse_id` vs `sql_warehouse_id`.

### 2. Move bundle-managed ETL entrypoints under `agent_app`

Bring the currently root-owned ETL/job task entrypoints into bundle-owned paths inside `agent_app`, based on:
- [`etl/01_export_genie_spaces.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/etl/01_export_genie_spaces.py)
- [`etl/02_enrich_table_metadata.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/etl/02_enrich_table_metadata.py)
- [`etl/03_build_vector_search_index.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/etl/03_build_vector_search_index.py)
- [`Notebooks/deploy_agent.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/Notebooks/deploy_agent.py)
- [`Notebooks/test_agent_databricks.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/Notebooks/test_agent_databricks.py)

This avoids parent-directory notebook references from the app bundle and makes sync/package behavior deterministic.

### 3. Keep two deploy paths over one underlying workflow

Both deploy modes should trigger the same logical stages:

```mermaid
flowchart LR
  etlExport[ExportGenie] --> etlEnrich[EnrichMetadata]
  etlEnrich --> vectorBuild[BuildVectorIndex]
  vectorBuild --> prepInfra[PrepareSharedInfra]
  prepInfra --> deployApp[DeployApp]
  deployApp --> validateApp[ValidateApp]
```

#### Path A: shell wrapper

[`agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh) becomes the primary local terminal and CI entrypoint. It should:
- verify or install `uv` for local terminal usage when missing
- create or reuse the project virtualenv before running Python-based helpers
- install or sync local Python dependencies needed by the deploy flow
- validate other required local tooling such as the Databricks CLI before attempting bundle commands
- resolve bundle config only from `agent_app/databricks.yml`
- optionally run sync/deploy/run commands
- call the appropriate job entrypoint rather than depending on declarative app resource assumptions
- support running either prep-only or full deploy flows depending on flags

For CI, the same script should support a non-interactive fast path that skips unnecessary local bootstrap steps when the environment is already prepared.

##### Proposed `deploy.sh` flags

Keep the existing flags and add explicit stage/bootstrap controls:

- `--target`, `-t`: bundle target such as `dev` or `prod`
- `--profile`, `-p`: explicit Databricks CLI profile override
- `--sync`: run `databricks bundle sync` before deploy
- `--run`: run the post-deploy app start step when applicable
- `--prep-only`: run only the prep workflow and stop before app deploy
- `--full-deploy`: run the full workflow from prep through deploy and validation
- `--bootstrap-local`: force local bootstrap of `uv`, `.venv`, and Python dependencies before deploy
- `--skip-bootstrap`: assume local tooling is already installed and skip bootstrap checks
- `--ci`: non-interactive mode optimized for CI runners; implies no prompts and prefers fail-fast validation
- `--help`, `-h`: print usage and examples

##### Proposed `deploy.sh` defaults

- Local terminal default:
  - bootstrap local tooling if needed
  - create or reuse `.venv` non-destructively
  - sync dependencies into the existing environment when needed
  - deploy selected target
  - do not automatically run prep-only unless requested
  - do not automatically start the app unless `--run` is set
- CI default:
  - require explicit `--ci`
  - skip opportunistic installs unless `--bootstrap-local` is also passed
  - fail immediately on missing required tooling or auth

##### Behavior matrix

| Mode | Suggested command shape | Bootstrap behavior | Bundle/job behavior |
|---|---|---|---|
| Local terminal, standard app deploy | `./scripts/deploy.sh -t dev --full-deploy --run` | Ensure `uv`, `.venv`, and Python deps are ready; install or instruct when missing | Validate bundle, deploy resources, run full pipeline or app deploy stage, then start app if requested |
| Local terminal, infra prep only | `./scripts/deploy.sh -t dev --prep-only` | Same local bootstrap as above | Run ETL/prep stages only, stop before app deploy |
| Local terminal, advanced pre-provisioned env | `./scripts/deploy.sh -t prod --full-deploy --skip-bootstrap` | Skip venv and dependency setup | Use existing environment and run deploy stages directly |
| CI runner, full deploy | `./scripts/deploy.sh -t prod --full-deploy --ci --skip-bootstrap` | Expect runner image to already contain required tools | Validate and run deploy flow with fail-fast, non-interactive behavior |
| CI runner, prep-only job | `./scripts/deploy.sh -t dev --prep-only --ci --skip-bootstrap` | Expect prepared runner | Run prep stages only for scheduled or one-off ETL/setup pipelines |

##### Stage mapping

Map the flags to a small set of named bundle jobs so both shell and notebook flows use the same execution surface:

- `--prep-only`:
  - invoke `agent_app_preps_job`
  - covers ETL + shared infrastructure preparation stages
- `--full-deploy`:
  - invoke full pipeline job
  - covers prep + app deploy + validation
- `--run`:
  - before migration, may still map to the current app-resource start behavior
  - after migration to jobs-only resources, should map to an explicit post-deploy runtime activation step only if the app still requires one
  - otherwise, if full deploy already leaves the app in the desired running state, `--run` should become a compatibility alias or no-op and be documented clearly

##### Local bootstrap responsibilities

Move the essential parts of [`local_dev_only_setup_venv.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/local_dev_only_setup_venv.sh) into `deploy.sh` or a shared helper that `deploy.sh` calls:

- verify supported Python version
- ensure `uv` is available
- create or reuse `.venv` under `agent_app`
- sync/install Python dependencies for deploy helpers
- verify required CLIs and Python imports used by deploy-time scripts

##### Bootstrap policy decision

`deploy.sh` should use a non-destructive bootstrap model by default:

- reuse an existing `.venv` when present
- create `.venv` only when missing
- sync or install dependencies without deleting the environment
- never wipe `.venv` as part of the normal deploy path

If a destructive environment reset is ever needed, add it later as an explicit opt-in mode such as `--clean-rebuild`, not as the default bootstrap behavior.

#### Path B: Databricks-native jobs/notebooks

The notebook/operator flow should remain supported through:
- [`agent_app/scripts/deploy_notebook.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py)
- [`agent_app/scripts/notebook_deploy_lib.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/notebook_deploy_lib.py)

This path should surface the same bundle settings, then hand off to the same bundle jobs for execution from the Databricks environment. The notebook path remains the operator control plane; the jobs remain the execution plane.

### 4. Define explicit task 4 after ETL 01/02/03

After ETL tasks 01/02/03 complete, add a dedicated task 04 that prepares shared runtime infrastructure before app deployment. This task should create if missing, or verify/update if already present:

- UC functions required by the agent stack
- the Lakebase instance used for runtime state
- the MLflow experiment used by the deployed app and related traces/artifacts

This task should be the canonical bridge between ETL readiness and deploy readiness. In the prep-only workflow, task 04 is the terminal step. In the full deploy workflow, task 04 should be immediately followed by app deploy and validation.

Recommended task sequence:

- Task 01: export Genie spaces
- Task 02: enrich metadata
- Task 03: build vector search index
- Task 04: ensure UC functions, Lakebase instance, and MLflow experiment exist
- Task 05: deploy app
- Task 06: validate app

### 5. Refocus `agent_app/resources/` on jobs

Replace current declarative non-job resources in:
- [`agent_app/resources/app.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/resources/app.yml)
- [`agent_app/resources/database.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/resources/database.yml)
- [`agent_app/resources/schemas.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/resources/schemas.yml)

with job-driven notebook/script orchestration for:
- UC function registration
- MLflow experiment creation
- Lakebase bootstrap and grants
- app deploy/update
- post-deploy validation and smoke checks

The maintained bundle resources should be jobs only, with notebooks/scripts performing imperative resource setup where needed.

### 6. Retire the root bundle cleanly

After the `agent_app` bundle absorbs ETL and deploy orchestration:
- stop maintaining [`databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/databricks.yml) as an active config
- update docs and CI to point to `agent_app`
- remove or mark legacy root resource files such as [`resources/etl_pipeline.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/resources/etl_pipeline.yml), [`resources/agent_deploy.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/resources/agent_deploy.yml), and [`resources/full_pipeline.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/resources/full_pipeline.yml) once equivalent `agent_app` resources exist

## Key Files To Change

- [`agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml)
- [`agent_app/resources/`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/resources)
- [`agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh)
- [`agent_app/scripts/deploy_notebook.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py)
- [`agent_app/scripts/notebook_deploy_lib.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/notebook_deploy_lib.py)
- [`agent_app/scripts/grant_lakebase_permissions.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/grant_lakebase_permissions.py)
- [`local_dev_only_setup_venv.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/local_dev_only_setup_venv.sh) as a reference to absorb or simplify if its responsibilities move into `deploy.sh`
- root ETL/notebook entrypoints that must be copied or moved under `agent_app`
- docs and CI references including [`CONTRIBUTING.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/CONTRIBUTING.md) and [`.github/workflows/ci-cd.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.github/workflows/ci-cd.yml)

## Implementation Notes

- Reuse the existing merge direction already documented in [`.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md)
- Treat `deploy.sh` and the notebook/job path as two front doors to one deployment model, not as two independently maintained implementations
- Consolidate bootstrap logic so local terminal users do not need a separate manual setup step before running `deploy.sh`, unless explicitly choosing an advanced/custom environment
- Prefer minimal compatibility shims during migration, then delete duplicated root config once the `agent_app` path validates in dev and prod
- Preserve the repo root layout for now; do not physically flatten `agent_app/` into the repository root as part of this phase
- Sequence the migration carefully:
  - first add the new `agent_app` jobs and task entrypoints
  - then refactor `deploy.sh` and the notebook/operator flow to target those jobs rather than `resources.apps`
  - then migrate CI and docs to the new `agent_app` commands
  - only after that retire legacy root bundle files and declarative app/database/schema resources
- Treat current `resources.apps` coupling as a temporary compatibility layer. Do not remove it until `deploy.sh` no longer depends on resolving app metadata from bundle `resources.apps`.
- Standardize the post-migration meaning of `--run` during implementation. The preferred outcome is that full deploy leaves the app in the desired state without requiring a separate app-resource run, and any remaining runtime activation step is explicit and documented.
- Reconcile Python version expectations before wiring bootstrap into CI. If local bootstrap logic requires Python 3.11+, either update CI to match or keep CI on a lighter path that avoids inheriting stricter local setup assumptions prematurely.