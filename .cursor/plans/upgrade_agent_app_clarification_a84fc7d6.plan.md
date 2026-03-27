---
name: Upgrade agent_app clarification
overview: Port the clarification subgraph/interrupt architecture from commit ce8217b into `agent_app/agent_server/multi_agent/`, preserving agent_app's unique features (MLflow tracing, retry/sequential execution, chart generator, QueryExecutionResult, etc.) while replacing the old monolithic clarification node with the new ClarificationAgent subgraph and interrupt-based flow.
todos:
  - id: add-base-agent
    content: Copy `base_agent.py` to `agent_app/agent_server/multi_agent/core/base_agent.py`
    status: completed
  - id: update-state
    content: "Update `agent_app/.../core/state.py`: add GraphInput, remove ClarificationRequest/IntentMetadata/pending_clarification/intent_type, simplify helpers while keeping QueryExecutionResult and retry/sequential fields"
    status: completed
  - id: replace-clarification
    content: Replace `agent_app/.../agents/clarification.py` with ClarificationAgent subgraph from src/
    status: completed
  - id: update-graph
    content: "Update `agent_app/.../core/graph.py`: ClarificationAgent subgraph wiring, GraphInput, interrupt routing, three-mode checkpointer (False=uncompiled for serving, True=Lakebase for CLI, 'memory'=MemorySaver for local dev), keep MLflow tracing and execution loop-back"
    status: completed
  - id: update-main
    content: "Update `agent_app/.../main.py`: HumanMessage, Command, invoke_config, interrupt/resume loop"
    status: completed
  - id: update-init-files
    content: Update __init__.py files (agents, core, package) to export new symbols
    status: completed
  - id: update-downstream
    content: Update planning.py, summarize_agent.py, summarize.py, responses_agent.py for removed symbols
    status: completed
  - id: update-serving-interrupt
    content: "Update `responses_agent.py` and `agent.py` serving paths to support interrupt/resume: detect pending interrupt via app.get_state(), send Command(resume=query) instead of initial_state when resuming, ensure ClarificationAgent emits clarification question as streamable event before interrupt()"
    status: completed
  - id: validate-syntax
    content: Syntax-check all modified files and verify no stale imports
    status: completed
isProject: false
---

# Upgrade agent_app to Clarification Subgraph Architecture

## Goal

Selectively port the clarification/subgraph/interrupt changes from `ce8217b` into `agent_app/agent_server/multi_agent/` while preserving agent_app-specific features (MLflow tracing, retry/sequential loops, chart generator, `QueryExecutionResult`, etc.).

## What changes, what stays

**Port from ce8217b (clarification architecture)**:

- `ClarificationAgent` class with compiled subgraph (replace monolithic 871-line function)
- `GraphInput` minimal input schema
- Interrupt-based clarification flow (replace `pending_clarification` state pattern)
- `BaseAgent` shared utilities
- Remove `ClarificationRequest`, `IntentMetadata`, `intent_type` from `ConversationTurn`
- Remove `pending_clarification` from `AgentState`
- Update `create_conversation_turn` (no `intent_type` arg)
- Update routing: clarification no longer routes to END
- Update `main.py` with interrupt/resume loop
- Update `create_agent_graph`: keep returning uncompiled workflow when `with_checkpointer=False` (responses_agent.py compiles it at runtime with Lakebase CheckpointSaver); compile with DatabricksCheckpointSaver when `with_checkpointer=True` (CLI use)

**Preserve (agent_app-specific features)**:

- MLflow tracing wrappers (`_with_node_trace`, `_trace_state_snapshot`, `_sync_turn_metadata`)
- `QueryExecutionResult` TypedDict
- Retry/sequential execution fields on `AgentState` and reset template
- `route_after_execution` loop-back edges (execution to synthesis)
- `sql_synthesis_explanations` field
- `force_synthesis_route` / `join_strategy_route` UI override fields
- `chart_generator`, `web_search`, `utils/` modules unchanged
- `responses_agent.py` (only update stale references)

## Files to modify

### 1. Add new file: `agent_app/agent_server/multi_agent/core/base_agent.py`

Copy from `[src/multi_agent/core/base_agent.py](src/multi_agent/core/base_agent.py)` as-is.

### 2. `agent_app/agent_server/multi_agent/core/state.py`

- Add `GraphInput` TypedDict
- Remove `intent_type` from `ConversationTurn`
- Remove `ClarificationRequest` class
- Remove `IntentMetadata` class
- Remove `intent_metadata` from `AgentState`
- Remove `pending_clarification` from `AgentState`
- **Keep**: `QueryExecutionResult`, retry/sequential/UI-override fields, `sql_synthesis_explanations`
- Simplify `create_conversation_turn` (drop `intent_type` param and validation)
- Remove `create_clarification_request` and `format_clarification_message`
- Update `get_reset_state_template`: remove `pending_clarification`, keep retry/sequential/routing fields
- Update `get_initial_state`: remove `intent_metadata=None`

### 3. `agent_app/agent_server/multi_agent/agents/clarification.py`

Replace the entire 871-line monolithic function with the new `ClarificationAgent` class from `[src/multi_agent/agents/clarification.py](src/multi_agent/agents/clarification.py)` (468 lines). This is the biggest change. The new file uses:

- `BaseAgent` superclass
- Structured LLM outputs (`QueryTypeClassification`, `ClarityCheck`, `ContinuationCheck`)
- Compiled subgraph with parallel fan-out, `interrupt()`, and resume
- No dependency on `IntentMetadata`, `ClarificationRequest`, or `create_clarification_request`

### 4. `agent_app/agent_server/multi_agent/core/graph.py`

- Import `ClarificationAgent` instead of `unified_intent_context_clarification_node`
- Import `GraphInput` from state
- `create_super_agent_hybrid(config=None)`: accept config, build `ClarificationAgent`, use `StateGraph(AgentState, input=GraphInput)`
- Mount `clarification_agent.subgraph` as the unified node (wrapped in `_with_node_trace` for MLflow)
- Update `route_after_unified`: remove `question_clear` branch to END; only END for irrelevant/meta
- **Keep**: `_with_node_trace`, `_trace_state_snapshot`, `_sync_turn_metadata` (adapt `_sync_turn_metadata` to not reference `intent_type`)
- **Keep**: `route_after_execution` loop-back edges
- `create_agent_graph` three modes:
  - `with_checkpointer=False` (default, used by serving): **return uncompiled workflow** -- `responses_agent.py` and `agent.py` compile it at runtime with their own Lakebase `CheckpointSaver`
  - `with_checkpointer=True` (CLI with Databricks): compile with `DatabricksCheckpointSaver` as before
  - `with_checkpointer="memory"` (local dev): compile with `MemorySaver` so `interrupt()` works without Lakebase

### 5. `agent_app/agent_server/multi_agent/main.py`

- Import `HumanMessage`, `Command`, `uuid`
- Use `HumanMessage(content=query)` instead of dict messages
- Add `invoke_config` with `thread_id` for checkpointer
- Add interrupt/resume loop (`while response.get("__interrupt__")`)
- Remove `pending_clarification` display branch
- Include `final_summary` in response display chain
- `run_query` without `--thread-id`: use `create_agent_graph(config, with_checkpointer="memory")` so interrupt works locally
- `run_query` with `--thread-id`: use `create_agent_graph(config, with_checkpointer=True)` for Lakebase
- `run_interactive`: use `create_agent_graph(config, with_checkpointer=True)` (assumes Databricks)

### 6. `agent_app/agent_server/multi_agent/agents/__init__.py`

- Export `ClarificationAgent` instead of `unified_intent_context_clarification_node`

### 7. `agent_app/agent_server/multi_agent/core/__init__.py`

- Remove `ClarificationRequest`, `IntentMetadata`, `create_clarification_request`, `format_clarification_message` from exports
- Add `GraphInput` if desired

### 8. `agent_app/agent_server/multi_agent/__init__.py`

- Remove `ClarificationRequest`, `IntentMetadata` from exports

### 9. Serving-layer interrupt support: `responses_agent.py` and `agent.py`

Both serving entry points need interrupt/resume logic so that `interrupt()` in the ClarificationAgent subgraph actually works in production.

**Pattern (apply to both files):**

- After compiling the graph with `CheckpointSaver`, check for a pending interrupt on the thread before streaming:

```python
from langgraph.types import Command

with CheckpointSaver(instance_name=...) as checkpointer:
    app = workflow.compile(checkpointer=checkpointer)
    
    # Check if this thread has a pending interrupt from a previous turn
    existing_state = app.get_state(run_config)
    if existing_state.tasks and any(
        hasattr(t, 'interrupts') and t.interrupts for t in existing_state.tasks
    ):
        # Resume from interrupt -- user's new message is the answer
        input_data = Command(resume=latest_query)
    else:
        # Fresh execution
        input_data = initial_state
    
    for event in app.stream(input_data, run_config, stream_mode=[...]):
        ...
```

- `**responses_agent.py**` (`predict_stream`): apply the pattern inside the `with CheckpointSaver(...)` block (line 515-532)
- `**agent.py**` (`stream_handler` → `_run_workflow`): apply the pattern inside the `with CheckpointSaver(...)` block (line 351-358)
- **ClarificationAgent**: ensure the clarification question is emitted as an `AIMessage` or custom streaming event **before** `interrupt()` is called, so the user sees the question in the HTTP response of the first turn

### 10. Downstream consumers (minimal changes)

- `agents/planning.py`: replace `intent_type` usage with `is_followup` pattern (same as src/)
- `agents/summarize_agent.py` / `agents/summarize.py`: remove `pending_clarification` branch in prompt builder
- `core/responses_agent.py`: update stale comments referencing `intent_metadata`, `unified_intent_context_clarification_node`
- `core/graph.py` `_sync_turn_metadata`: remove `intent_type` from trace metadata (field no longer exists on turns)

### 10. NOT touched (intentionally)

- `utils/conversation.py`, `utils/conversation_models.py`, `utils/intent_detection_service.py` -- these define independent copies of the old types for their own use; they are not imported by the graph
- `agents/chart_generator.py`, `tools/web_search.py`, `tools/uc_functions.py`
- `agents/sql_synthesis.py`, `agents/sql_synthesis_agents.py`, `agents/sql_execution.py`, `agents/sql_execution_agent.py`
- `core/config.py`

## Risk areas

- **MLflow tracing + subgraph**: wrapping `clarification_agent.subgraph` (a compiled graph) with `_with_node_trace` should work since LangGraph subgraphs are callable, but needs testing
- **responses_agent.py**: the serving path initializes state with `RESET_STATE_TEMPLATE` which still includes `pending_clarification` -- must be removed from the template
- **Interrupt in Model Serving**: `responses_agent.py` and `agent.py` must detect pending interrupts and resume with `Command(resume=...)` on subsequent requests; without this, `interrupt()` saves checkpoint but the next request starts fresh instead of resuming (now in scope -- see section 9)
- **Checkpointing architecture**: `responses_agent.py` and `agent.py` receive an **uncompiled** `StateGraph` and compile it at runtime with Lakebase `CheckpointSaver`. `create_agent_graph(with_checkpointer=False)` must continue returning an uncompiled workflow for this path. The new `with_checkpointer="memory"` mode is only for local CLI dev where Lakebase is unavailable -- it compiles with `MemorySaver` so `interrupt()` works in-process.

