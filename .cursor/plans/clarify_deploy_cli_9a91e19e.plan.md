---
name: clarify deploy CLI
overview: "Redesign the `deploy.sh` interface so each flag describes one obvious action: deploy, optionally run one post-deploy job, and optionally start the app. Mirror the same vocabulary in the notebook handoff and docs so operators do not have to infer what `--run` means, while keeping workspace sync clearly labeled as a dev-oriented bundle file sync rather than a deployment step."
todos:
  - id: cli-flags
    content: Redesign `deploy.sh` around `--run-job` and `--start-app`, with alias resolution for `prep` and `full`
    status: completed
  - id: notebook-terms
    content: Update `deploy_notebook.py` and `notebook_deploy_lib.py` to match the new `deploy.sh` flags and handoff wording
    status: completed
  - id: docs-refresh
    content: Update README examples and help text last, after code changes settle, so docs match the final CLI behavior
    status: completed
  - id: compat-aliases
    content: Keep legacy flags as deprecated aliases unless a breaking change is preferred
    status: completed
isProject: false
---

# Clarify Deploy CLI

## Proposed CLI

Recommend this flag set for [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh):

- `--target`, `-t`: bundle target
- `--profile`, `-p`: Databricks CLI profile override
- `--sync-workspace`: sync local bundle files to the Databricks workspace bundle folder for workspace-side development; does not affect deployment behavior by itself
- `--list-jobs`: list available bundle jobs with short descriptions, then exit
- `--run-job <prep|full|job_key>`: run one post-deploy bundle job; accepts `prep`, `full`, or a bundle job key
- `--start-app`: start the deployed app after deploy and any optional post-deploy job
- `--bootstrap-local`: prepare local Python env
- `--skip-bootstrap`: skip local bootstrap
- `--ci`: CI mode
- `--help`, `-h`: show help

## Why This Is Clearer

- `--start-app` is explicit; it replaces the ambiguous `--run`
- `--run-job` makes all job execution paths one concept instead of splitting them across `--prep-only`, `--full-deploy`, and `--job`
- `prep` and `full` become readable aliases for the wrapper jobs rather than separate top-level modes
- `--sync-workspace` is explicit about scope: it only syncs the bundle folder in the workspace for dev workflows and does not materially affect the subsequent deployment step
- `--list-jobs` gives users a discovery path so they do not need to open `resources/jobs.yml` to find valid job keys
- The command reads as a sentence:
  - `./scripts/deploy.sh --target dev --sync-workspace --run-job prep --start-app`
  - `./scripts/deploy.sh --target dev --run-job agent_app_validate_app_job`

## Help Text Shape

Suggested lead examples in the script header:

Suggested help text wording:

- `--sync-workspace`: Sync local bundle files to the workspace bundle folder for workspace-side development. This does not change deployment behavior on its own.
- `--list-jobs`: List available bundle jobs and their purpose, then exit.
- `--run-job <prep|full|job_key>`: Run one post-deploy bundle job. Use `prep`, `full`, or a bundle job key.
- `--start-app`: Start the deployed app after deploy and any optional post-deploy job.

- `./scripts/deploy.sh --target dev --run-job prep`
  Deploy, then run the prep workflow.
- `./scripts/deploy.sh --target dev --sync-workspace`
  Sync bundle files to the workspace for dev iteration, then continue with normal deploy.
- `./scripts/deploy.sh --target dev --list-jobs`
  Show available bundle job keys and descriptions for the selected target, then exit.
- `./scripts/deploy.sh --target dev --run-job full --start-app`
  Deploy, run the full post-deploy workflow, then start the app.
- `./scripts/deploy.sh --target dev --run-job agent_app_validate_app_job`
  Deploy, then run one specific bundle job.

## Implementation Scope

Update [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy.sh):

- Replace the current split mode handling:
  - `--prep-only`
  - `--full-deploy`
  - `--job`
  - `--run`
- Introduce one post-deploy job resolver:
  - map `prep` -> `agent_app_preps_job`
  - map `full` -> `agent_app_full_deploy_job`
  - otherwise treat the value as a bundle job key and validate it from `bundle validate`
- Add a job discovery path that reads bundle job metadata from `bundle validate` output and prints:
  - job key
  - rendered job name when available
  - description when available
- Rename state variables so the code matches the UX terms, for example:
  - `POST_DEPLOY_JOB`
  - `START_APP`
- Keep `--sync-workspace` as an explicitly dev-oriented flag and update its help text to say it only syncs bundle files into the workspace bundle folder
- Preserve the note that `databricks bundle deploy` remains the step that actually applies deployment changes

Then update [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/deploy_notebook.py) and [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/notebook_deploy_lib.py`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/notebook_deploy_lib.py) to accommodate the `deploy.sh` changes:

- Rename widget/config terms from `deploy_mode` and `run_after` to clearer names like:
  - `job_to_run`
  - `start_app`
- Generate the new command form in notebook handoff output
- Update the printed notes so operators see the same vocabulary as the shell help
- Keep notebook-side job discovery and examples aligned with `--list-jobs` and `--run-job`
- Preserve notebook behavior as a thin control plane around the canonical shell script rather than introducing separate deployment semantics

Update docs last, after the script and notebook changes are complete, in [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/README-notebook-deploy.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/scripts/README-notebook-deploy.md) and [`/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/README.md`](/Users/yang.yang/CursorProjects/KUMC_POC_hlsfieldtemp/agent_app/README.md):

- Rewrite examples to prefer `--run-job` and `--start-app`
- Explain that `prep` and `full` are convenience aliases under `--run-job`
- Remove wording that forces readers to infer that `--run` means app startup
- Clarify that workspace sync is optional and primarily useful when developing directly from the workspace bundle folder
- State explicitly that sync does not have independent deployment effect beyond uploading local bundle files
- Add `--list-jobs` usage so users know how to discover valid raw job keys
- Keep the README update as the final step so documentation reflects the implemented CLI exactly

## Recommended Compatibility Approach

Default recommendation: keep old flags as hidden deprecated aliases for one iteration, but remove them from examples/help text.

- This keeps current scripts and muscle memory working
- New users only see the clearer interface
- The script can print a short deprecation warning when an old flag is used

## Validation

- Shell syntax check for `scripts/deploy.sh`
- Verify `--list-jobs` output is readable and includes the expected bundle jobs
- Verify notebook handoff command rendering matches the new flags
- Quick doc pass to ensure examples and widget names are consistent end to end