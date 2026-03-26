"""
Migrated multi-agent Genie system — async @invoke/@stream entry point.

Converted from SuperAgentHybridResponsesAgent (Model Serving) to
MLflow GenAI Server decorated functions (Databricks Apps).
"""

import contextvars
import json
import logging
import threading
import time
from typing import AsyncGenerator, Optional
from uuid import uuid4

import litellm
import mlflow
from mlflow.entities import SpanType
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from agent_server.utils import get_session_id
from agent_server.multi_agent.core.graph import create_super_agent_hybrid
from agent_server.multi_agent.core.state import RESET_STATE_TEMPLATE

mlflow.langchain.autolog(run_tracer_inline=True)

logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)
litellm.suppress_debug_info = True

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure DATABRICKS_HOST/TOKEN env vars are set for libraries that don't use
# the SDK auth chain (e.g. databricks-vectorsearch).
# ---------------------------------------------------------------------------
import os
_is_databricks_apps = bool(os.environ.get("DATABRICKS_CLIENT_ID"))
if not _is_databricks_apps and not os.environ.get("DATABRICKS_TOKEN"):
    try:
        from databricks.sdk import WorkspaceClient as _WsClient
        _w = _WsClient()
        _cfg_auth = _w.config
        if _cfg_auth.host and not os.environ.get("DATABRICKS_HOST"):
            os.environ["DATABRICKS_HOST"] = _cfg_auth.host
        _auth_result = _cfg_auth.authenticate()
        if isinstance(_auth_result, dict):
            _bearer = _auth_result.get("Authorization", "")
        elif callable(_auth_result):
            _bearer = _auth_result().get("Authorization", "")
        else:
            _bearer = ""
        if _bearer.startswith("Bearer "):
            os.environ["DATABRICKS_TOKEN"] = _bearer[7:]
            os.environ.pop("DATABRICKS_CONFIG_PROFILE", None)
            logger.info("Resolved DATABRICKS_HOST/TOKEN from SDK auth chain")
    except Exception as _e:
        logger.warning(f"Could not resolve Databricks auth from SDK: {_e}")

# ---------------------------------------------------------------------------
# Module-level setup (replaces __init__ of SuperAgentHybridResponsesAgent)
# ---------------------------------------------------------------------------
_workflow = create_super_agent_hybrid()

LAKEBASE_INSTANCE_NAME = None
EMBEDDING_ENDPOINT = None
EMBEDDING_DIMS = None
try:
    from agent_server.multi_agent.core.config import get_config
    _cfg = get_config()
    LAKEBASE_INSTANCE_NAME = _cfg.lakebase.instance_name
    EMBEDDING_ENDPOINT = _cfg.lakebase.embedding_endpoint
    EMBEDDING_DIMS = _cfg.lakebase.embedding_dims
except Exception as e:
    logger.warning(f"Failed to load config at import time: {e}")

_store = None
_store_lock = threading.Lock()


def _get_store():
    """Lazy initialization of DatabricksStore for long-term memory."""
    global _store
    if _store is not None:
        return _store
    if not LAKEBASE_INSTANCE_NAME:
        return None
    with _store_lock:
        if _store is not None:
            return _store
        from databricks_langchain import DatabricksStore
        logger.info(f"Initializing DatabricksStore with instance: {LAKEBASE_INSTANCE_NAME}")
        store = DatabricksStore(
            instance_name=LAKEBASE_INSTANCE_NAME,
            embedding_endpoint=EMBEDDING_ENDPOINT,
            embedding_dims=EMBEDDING_DIMS,
        )
        store.setup()
        _store = store
        logger.info("DatabricksStore initialized")
    return _store


# ---------------------------------------------------------------------------
# Helper: extract thread_id / user_id from request
# ---------------------------------------------------------------------------

def _get_or_create_thread_id(request: ResponsesAgentRequest) -> str:
    ci = dict(request.custom_inputs or {})
    if "thread_id" in ci:
        return ci["thread_id"]
    if request.context and getattr(request.context, "conversation_id", None):
        return request.context.conversation_id
    return str(uuid4())


def _get_user_id(request: ResponsesAgentRequest):
    if request.context and getattr(request.context, "user_id", None):
        return request.context.user_id
    if request.custom_inputs and "user_id" in request.custom_inputs:
        return request.custom_inputs["user_id"]
    return None


# ---------------------------------------------------------------------------
# Helper: format custom streaming events
# ---------------------------------------------------------------------------

def _make_json_serializable(obj):
    from langchain_core.messages import BaseMessage
    from uuid import UUID

    if obj is None:
        return None
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="ignore")
        except Exception:
            return f"<bytes:{len(obj)}>"
    if isinstance(obj, set):
        return [_make_json_serializable(item) for item in obj]
    if isinstance(obj, BaseMessage):
        msg_dict = {"type": obj.__class__.__name__, "content": str(obj.content) if obj.content else ""}
        if hasattr(obj, "id") and obj.id:
            msg_dict["id"] = str(obj.id)
        if hasattr(obj, "tool_calls") and obj.tool_calls:
            msg_dict["tool_calls"] = [_make_json_serializable(tc) for tc in obj.tool_calls]
        return msg_dict
    if isinstance(obj, dict):
        return {str(k): _make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    try:
        return str(obj)
    except Exception:
        return f"<{type(obj).__name__}>"


_CUSTOM_FORMATTERS = {
    "agent_thinking": lambda d: f"{d['agent'].upper()}: {d['content']}",
    "agent_start": lambda d: f"Starting {d['agent']} agent for: {d.get('query', '')}",
    "intent_detection": lambda d: f"Intent: {d['result']} - {d.get('reasoning', '')}",
    "clarity_analysis": lambda d: f"Query {'clear' if d['clear'] else 'unclear'}: {d.get('reasoning', '')}",
    "vector_search_start": lambda d: f"Searching vector index: {d['index']}",
    "vector_search_results": lambda d: f"Found {d['count']} relevant spaces",
    "plan_formulation": lambda d: f"Execution plan: {d.get('strategy', 'unknown')} strategy",
    "sql_generated": lambda d: f"SQL generated: {d.get('query', d.get('query_preview', ''))}",
    "sql_validation_start": lambda d: "Validating SQL query...",
    "sql_execution_start": lambda d: "Executing SQL query...",
    "sql_execution_complete": lambda d: f"Query complete: {d.get('rows', 0)} rows",
    "summary_start": lambda d: "Generating summary...",
    "genie_agent_call": lambda d: f"Calling Genie agent for space: {d.get('space_id', 'unknown')}",
    "meta_answer_content": lambda d: f"\n\n{d.get('content', '')}",
    "clarification_content": lambda d: f"\n\n{d.get('content', '')}",
    "clarification_result": lambda d: d.get("content", f"Clarification result: {d.get('result', 'unknown')}"),
    "tool_call_start": lambda d: d.get("content", "Calling " + d.get("tool", "tool") + "..."),
    "tool_call_end": lambda d: d.get("content", "Tool returned result"),
    "agent_step": lambda d: d.get("content", f"Step: {d.get('step', '')}"),
    "agent_result": lambda d: d.get("content", f"Result: {d.get('result', '')}"),
    "tools_available": lambda d: d.get("content", "Tools loaded"),
    "sql_synthesis_start": lambda d: f"SQL synthesis starting ({d.get('route', 'unknown')} route)",
    "summarize_step": lambda d: d.get("content", "Summarize step"),
    "summary_complete": lambda d: d.get("content", "Summary complete"),
}


def _format_custom_event(custom_data: dict) -> str:
    event_type = custom_data.get("type", "unknown")
    formatter = _CUSTOM_FORMATTERS.get(
        event_type,
        lambda d: f"info {event_type}: {json.dumps(_make_json_serializable(d), indent=2, default=str)}",
    )
    try:
        return formatter(custom_data)
    except Exception:
        return f"info {event_type}: {str(custom_data)}"


def _create_text_output_item(text: str, id: str):
    return {
        "type": "message",
        "id": id,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def _create_text_delta(delta: str, id: str):
    return {
        "type": "response.output_text.delta",
        "item_id": id,
        "content_index": 0,
        "delta": delta,
    }


def _create_function_call_item(id: str, call_id: str, name: str, arguments: str):
    return {
        "type": "function_call",
        "id": id,
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


# ---------------------------------------------------------------------------
# @invoke / @stream entry points
# ---------------------------------------------------------------------------


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    """Collect all streaming events and return the final response."""
    outputs = [
        event.item
        async for event in stream_handler(request)
        if event.type == "response.output_item.done"
    ]
    return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)


@stream()
async def stream_handler(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Stream the multi-agent workflow — async wrapper around sync LangGraph execution."""
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})

    thread_id = _get_or_create_thread_id(request)
    user_id = _get_user_id(request)

    mlflow.update_current_trace(
        metadata={
            "chat.thread_id": thread_id,
            **({"chat.user_id": user_id} if user_id else {}),
        }
    )

    ci = dict(request.custom_inputs or {})
    ci["thread_id"] = thread_id
    if user_id:
        ci["user_id"] = user_id
    request.custom_inputs = ci

    logger.info(f"Processing request - thread_id: {thread_id}, user_id: {user_id}")

    workflow_start_time = time.time()
    first_token_time = None

    cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
    latest_query = cc_msgs[-1]["content"] if cc_msgs else ""

    run_config = {"configurable": {"thread_id": thread_id}}
    if user_id:
        run_config["configurable"]["user_id"] = user_id

    # Agent settings from UI (via custom_inputs)
    execution_mode = ci.get("execution_mode", "parallel")
    force_synthesis_route = ci.get("force_synthesis_route", "auto")
    clarification_sensitivity = ci.get("clarification_sensitivity", "medium")
    count_only = ci.get("count_only", False)

    initial_state = {
        **RESET_STATE_TEMPLATE,
        "original_query": latest_query,
        "execution_mode": execution_mode,
        "force_synthesis_route": force_synthesis_route,
        "clarification_sensitivity": clarification_sensitivity,
        "count_only": count_only,
        "messages": [
            SystemMessage(content="""You are a multi-agent Q&A analysis system.
Your role is to help users query and analyze cross-domain data.

Guidelines:
- Always explain your reasoning and execution plan
- Validate SQL queries before execution
- Provide clear, comprehensive summaries
- If information is missing, ask for clarification (max once)
- Use UC functions and Genie agents to generate accurate SQL
- Return results with proper context and explanations"""),
            HumanMessage(content=latest_query),
        ],
    }
    if user_id:
        initial_state["user_id"] = user_id
        initial_state["thread_id"] = thread_id

    first_message = True
    seen_ids: set = set()

    import asyncio

    _SENTINEL = object()
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _run_workflow():
        """Stream events from the sync LangGraph workflow into an asyncio.Queue."""
        from databricks_langchain import CheckpointSaver

        try:
            with mlflow.start_span(
                name="langgraph_workflow",
                span_type=SpanType.AGENT,
                attributes={
                    "thread_id": thread_id,
                    "execution_mode": execution_mode,
                    "force_synthesis_route": force_synthesis_route,
                    "clarification_sensitivity": clarification_sensitivity,
                    "count_only": count_only,
                },
            ) as span:
                span.set_inputs(
                    {
                        "original_query": latest_query,
                        "thread_id": thread_id,
                        "user_id": user_id,
                        "execution_mode": execution_mode,
                        "force_synthesis_route": force_synthesis_route,
                        "clarification_sensitivity": clarification_sensitivity,
                        "count_only": count_only,
                    }
                )
                last_state: dict = {}
                with CheckpointSaver(instance_name=LAKEBASE_INSTANCE_NAME) as checkpointer:
                    from langgraph.types import Command

                    app = _workflow.compile(checkpointer=checkpointer)
                    logger.info(f"Executing workflow with checkpointer (thread: {thread_id})")

                    existing_state = app.get_state(run_config)
                    if existing_state.tasks and any(
                        hasattr(t, "interrupts") and t.interrupts for t in existing_state.tasks
                    ):
                        logger.info(f"Resuming from interrupt on thread {thread_id}")
                        input_data = Command(
                            resume=latest_query,
                            update={
                                "execution_mode": execution_mode,
                                "force_synthesis_route": force_synthesis_route,
                                "clarification_sensitivity": clarification_sensitivity,
                                "count_only": count_only,
                            },
                        )
                    else:
                        input_data = initial_state

                    for raw_event in app.stream(
                        input_data,
                        run_config,
                        stream_mode=["updates", "messages", "custom", "tasks"],
                        subgraphs=True,
                    ):
                        # subgraphs=True: 3-tuple (ns, mode, data)
                        # or 2-tuple (ns, (mode, data)) depending on LangGraph version
                        if len(raw_event) == 3:
                            ns, mode, data = raw_event
                        elif isinstance(raw_event[0], tuple):
                            ns = raw_event[0]
                            mode, data = raw_event[1]
                        else:
                            ns, mode, data = (), raw_event[0], raw_event[1]

                        if mode == "updates" and not ns and isinstance(data, dict):
                            last_state.update(data)
                        # Normalise to 3-tuple for downstream consumer
                        loop.call_soon_threadsafe(
                            queue.put_nowait, (ns, mode, data)
                        )

                workflow_output: dict = {"status": "completed"}
                if summary := last_state.get("final_summary"):
                    workflow_output["final_summary"] = summary
                if sql := last_state.get("sql_query"):
                    workflow_output["sql_query"] = sql
                if er := last_state.get("execution_result"):
                    workflow_output["execution_result_status"] = er.get("status")
                    workflow_output["row_count"] = er.get("row_count")
                span.set_outputs(workflow_output)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    trace_context = contextvars.copy_context()
    loop.run_in_executor(None, trace_context.run, _run_workflow)

    progress_steps: list[str] = []
    progress_item_id = str(uuid4())
    progress_started = False
    details_finalized = False
    in_summarize = False
    streaming_item_id = str(uuid4())
    text_deltas_emitted = False
    seen_content_events: set[tuple[str, str]] = set()

    def _emit_progress_step(step_text: str):
        """Append a step to the live progress block (returns events to yield)."""
        nonlocal progress_started
        events = []
        if not progress_started:
            progress_started = True
            events.append(ResponsesAgentStreamEvent(
                **_create_text_delta(
                    delta='<details open>\n<summary>Processing Steps</summary>\n',
                    id=progress_item_id,
                ),
            ))
        events.append(ResponsesAgentStreamEvent(
            **_create_text_delta(
                delta=f'<div class="ps">{step_text}</div>\n',
                id=progress_item_id,
            ),
        ))
        return events

    def _finalize_progress():
        """Close the live progress block with a closing tag delta."""
        nonlocal details_finalized
        events = []
        if progress_started and not details_finalized:
            details_finalized = True
            events.append(ResponsesAgentStreamEvent(
                **_create_text_delta(delta="\n</details>\n\n", id=progress_item_id),
            ))
        return events

    while True:
        event = await queue.get()
        if event is _SENTINEL:
            break
        if isinstance(event, Exception):
            raise event

        # Normalised 3-tuple from _run_workflow: (namespace, mode, data)
        ns, event_type, event_data = event

        # Skip subgraph-internal updates (avoid noise and premature final-node detection)
        if event_type == "updates" and ns:
            continue

        # ── tasks: detect errors ──
        if event_type == "tasks":
            try:
                ev = event_data if isinstance(event_data, dict) else {}
                if ev.get("event") == "error":
                    node_name = ev.get("name", "unknown")
                    error = ev.get("error", "Unknown error")
                    logger.error(f"Task failed: {node_name} - {error}")
                    yield ResponsesAgentStreamEvent(
                        type="response.output_item.done",
                        item=_create_text_output_item(text=f"Error in {node_name}: {error}", id=str(uuid4())),
                    )
            except Exception as e:
                logger.warning(f"Error processing task event: {e}")
            continue

        # ── custom: stream progress live, handle text deltas and special events ──
        if event_type == "custom":
            try:
                et = event_data.get("type", "") if isinstance(event_data, dict) else ""
                if et == "text_delta":
                    delta_content = event_data.get("content", "")
                    if delta_content:
                        if not text_deltas_emitted:
                            for ev in _finalize_progress():
                                yield ev
                        if first_token_time is None:
                            first_token_time = time.time()
                            logger.info(f"TTFT: {first_token_time - workflow_start_time:.3f}s")
                        text_deltas_emitted = True
                        yield ResponsesAgentStreamEvent(
                            **_create_text_delta(delta=delta_content, id=streaming_item_id),
                        )
                elif et in ("meta_answer_content", "clarification_content", "clarification_requested"):
                    content_key = (et, str(event_data.get("content", "")) if isinstance(event_data, dict) else str(event_data))
                    if content_key in seen_content_events:
                        continue
                    seen_content_events.add(content_key)
                    if not details_finalized:
                        for ev in _finalize_progress():
                            yield ev
                    yield ResponsesAgentStreamEvent(
                        type="response.output_item.done",
                        item=_create_text_output_item(text=_format_custom_event(event_data), id=str(uuid4())),
                    )
                    if et == "clarification_content" and isinstance(event_data, dict):
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=_create_text_output_item(text="", id=str(uuid4())),
                            databricks_output={
                                "clarification": {
                                    "reason": event_data.get("reason", ""),
                                    "options": event_data.get("options", []),
                                }
                            },
                        )
                elif et.endswith("_error") or et == "error":
                    yield ResponsesAgentStreamEvent(
                        type="response.output_item.done",
                        item=_create_text_output_item(text=_format_custom_event(event_data), id=str(uuid4())),
                    )
                elif et == "code_enrichment_progress":
                    step_text = event_data.get("content", "")
                    if step_text:
                        progress_steps.append(step_text)
                        for ev in _emit_progress_step(step_text):
                            yield ev
                elif et == "summary_start":
                    in_summarize = True
                    streaming_item_id = str(uuid4())
                    text_deltas_emitted = False
                elif et == "summary_complete":
                    pass
                else:
                    step_text = _format_custom_event(event_data)
                    progress_steps.append(step_text)
                    for ev in _emit_progress_step(step_text):
                        yield ev
            except Exception as e:
                logger.warning(f"Error processing custom event: {e}")
            continue

        # ── messages: skip (text_delta custom events handle all streaming) ──
        if event_type == "messages":
            continue

        # ── updates: stream node progress, only emit AIMessages from final nodes ──
        if event_type == "updates":
            events_dict = event_data
            if isinstance(events_dict, tuple):
                flattened = {}
                for item in events_dict:
                    if isinstance(item, dict):
                        flattened.update(item)
                events_dict = flattened
            if not isinstance(events_dict, dict):
                logger.warning(f"Skipping malformed updates event: {type(event_data).__name__}")
                continue
            node_names = list(events_dict.keys())
            new_msgs = [
                msg
                for v in events_dict.values()
                if isinstance(v, dict)
                for msg in v.get("messages", [])
                if hasattr(msg, "id") and msg.id not in seen_ids
            ]

            seen_ids.update(msg.id for msg in new_msgs)

            routing_nodes = {
                "planning",
                "sql_synthesis_table",
                "sql_synthesis_genie",
                "sql_execution",
            }
            for node_name, update in events_dict.items():
                if not isinstance(update, dict):
                    continue
                if node_name != "summarize":
                    step = f"Step: {node_name}"
                    extra = [k for k in update if k != "messages"]
                    if extra:
                        step += f" ({', '.join(extra)})"
                    progress_steps.append(step)
                    for ev in _emit_progress_step(step):
                        yield ev
                    if node_name in routing_nodes and "next_agent" in update:
                        routing = f"Routing → {update['next_agent']}"
                        progress_steps.append(routing)
                        for ev in _emit_progress_step(routing):
                            yield ev

            is_final_node = "summarize" in node_names
            if not is_final_node:
                for update in events_dict.values():
                    if not isinstance(update, dict):
                        continue
                    if update.get("is_meta_question") or update.get("is_irrelevant"):
                        is_final_node = True
                        break

            if is_final_node:
                for ev in _finalize_progress():
                    yield ev
                if not text_deltas_emitted:
                    for msg in new_msgs:
                        if isinstance(msg, AIMessage):
                            for se in output_to_responses_items_stream([msg]):
                                yield se
            continue

    for ev in _finalize_progress():
        yield ev

    ttcl = time.time() - workflow_start_time
    logger.info(
        f"Workflow completed (thread: {thread_id}) "
        f"TTFT={first_token_time - workflow_start_time if first_token_time else 'N/A'}s, TTCL={ttcl:.3f}s"
    )
