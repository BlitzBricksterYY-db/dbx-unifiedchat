---
name: deployment simplification plan
overview: Make deployment easier by converging on one canonical deploy surface for this repo, while adding a Pixels-style guided workspace path for demos and a clearly separate production/operator path. Align CI, docs, and bundle structure so users are not forced to understand multiple competing deployment models.
todos:
  - id: canon-agent-app
    content: Define `agent_app` as the only supported app deployment bundle and normalize shared variable names.
    status: pending
  - id: unify-job-graph
    content: Move ETL, prep, deploy, and validation stages under `agent_app` jobs so shell and notebook flows share one execution graph.
    status: pending
  - id: harden-deploy-entrypoint
    content: Upgrade `agent_app/scripts/deploy.sh` with preflight checks, stage selection, and smoke validation.
    status: pending
  - id: align-ci-and-docs
    content: Make CI and documentation follow the same canonical deployment path and separate demo guidance from legacy/prod references.
    status: pending
isProject: false
---

# Deployment Simplification Plan

## Recommendation

Adopt the same split that makes `pixels` approachable:
- one obvious, low-friction "try it in Databricks" path
- one clearly documented, canonical production path

For this repo, that means keeping `agent_app` as the operational center and stopping the current split-brain story where root DAB, app DAB, legacy Model Serving docs, notebook deploy docs, and CI all point in different directions.

## What To Change

### 1. Make one deploy path canonical

Use [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml) and [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh) as the single supported deploy surface for the app.

Concretely:
- treat [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/databricks.yml) as ETL-only during transition, then retire it after migration
- stop documenting the legacy Model Serving flow as an active deployment option in [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/DEPLOYMENT.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/DEPLOYMENT.md)
- align variable names so there is one contract, not `catalog_name` vs `catalog` and `sql_warehouse_id` vs `warehouse_id`

Why: today the README says the app path is canonical, but CI still deploys the root bundle and runs legacy jobs.

### 2. Add a Pixels-style guided workspace entrypoint

Keep the local shell workflow, but add a guided Databricks-native entrypoint modeled after `pixels`' `RUNME.py` and numbered walkthrough.

Build this around the existing notebook/operator path in:
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/README-notebook-deploy.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/README-notebook-deploy.md)
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py)

Turn it into a true accelerator path that:
- resolves target settings
- checks auth and required resources
- prints or triggers the exact prep/deploy/run commands
- links to the deployed app and validation status

This should be explicitly positioned as the easiest "operator in the workspace" path, not a second competing source of truth.

### 3. Collapse deployment stages into one job graph

Reuse the existing merge direction from:
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_bundle_merge_7f2e2f39.plan.md)
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_deploy_unification_1040dc11.plan.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.cursor/plans/agent_app_deploy_unification_1040dc11.plan.md)

Target end state:
- ETL, shared infra prep, app deploy, and validation all live under `agent_app`
- `agent_app/resources/*.yml` defines the maintained jobs
- shell and notebook paths both invoke the same prep/full-deploy stages

This mirrors `pixels` well: one guided path for demos, but a predictable workflow graph underneath.

```mermaid
flowchart LR
  prepData[PrepData] --> prepInfra[PrepInfra]
  prepInfra --> deployApp[DeployApp]
  deployApp --> validateApp[ValidateApp]
  validateApp --> appReady[AppReady]
```

### 4. Make CI follow the same path users follow

Update [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.github/workflows/ci-cd.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/.github/workflows/ci-cd.yml) so CI validates and deploys the same `agent_app` flow that the README recommends.

Concretely:
- validate the app bundle, not only the repo-root bundle
- call `agent_app/scripts/deploy.sh` in CI mode rather than raw root-level `databricks bundle ...`
- run a small post-deploy smoke check against the app path users actually consume

Why: “industry friendly” means docs, automation, and runtime all agree.

### 5. Remove personal and fragile workspace assumptions

Harden [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/databricks.yml) for team use:
- replace the hardcoded user `root_path` with a portable pattern or target override strategy
- document which values must be supplied per environment vs which can be defaulted
- prefer service-principal-friendly auth assumptions in docs and CI

This is one of the biggest gaps vs `pixels`, which is easier to clone and run because the onboarding story is repo-centric, not person-centric.

### 6. Separate demo docs from production docs

Refactor documentation so each audience gets one clear story.

Update:
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/README.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/README.md)
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/DEPLOYMENT.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/DEPLOYMENT.md)
- [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/CONFIGURATION.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/docs/CONFIGURATION.md)

Recommended doc split:
- README: quick start and canonical path only
- deployment guide: operator and CI flow for the app bundle
- optional workspace guide: notebook-driven/demo path
- migration note: legacy Model Serving path is retained only as historical/reference material

This follows the strongest `pixels` pattern: tutorial and production guidance are both present, but clearly separated.

### 7. Add deployment preflight and smoke validation

Strengthen [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh) so it feels more like a product installer than a thin wrapper.

Add:
- CLI/version checks
- required dependency checks
- target/profile/auth validation
- clear missing-permission diagnostics
- optional `--prep-only` and `--full-deploy` modes
- post-deploy smoke verification that the app exists, starts, and can access required resources

This is the main way to make the deployment experience feel industry-ready without adding heavy platform complexity.

## Suggested Implementation Order

1. Normalize `agent_app` as the canonical bundle and variable model.
2. Move ETL and deploy stages under `agent_app` jobs.
3. Update `deploy.sh` to orchestrate prep/full-deploy/smoke validation.
4. Align CI with the new script-based flow.
5. Rework docs into quick start vs operator/production vs legacy reference.
6. Polish the notebook/workspace entrypoint into a supported accelerator path.

## Success Criteria

- A new engineer can deploy the app by following one path from the README.
- A Databricks operator can deploy from inside the workspace without reverse-engineering scripts.
- CI uses the same bundle and same deploy contract as humans.
- Environment settings are portable and not tied to a single user workspace path.
- Legacy deployment flows are clearly marked as legacy and no longer compete with the supported path.