import asyncio
import importlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import types


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@contextmanager
def _noop_context_manager(*_args, **_kwargs):
    class _Span:
        def set_inputs(self, *_args, **_kwargs):
            return None

        def set_outputs(self, *_args, **_kwargs):
            return None

    yield _Span()


mlflow_stub = types.ModuleType("mlflow")
mlflow_stub.update_current_trace = lambda *args, **kwargs: None
mlflow_stub.start_span = lambda *args, **kwargs: _noop_context_manager()
mlflow_stub.langchain = SimpleNamespace(autolog=lambda **_kwargs: None)
sys.modules.setdefault("mlflow", mlflow_stub)

mlflow_entities_stub = types.ModuleType("mlflow.entities")
mlflow_entities_stub.SpanType = SimpleNamespace(AGENT="agent")
sys.modules.setdefault("mlflow.entities", mlflow_entities_stub)

agent_server_decorators_stub = types.ModuleType("mlflow.genai.agent_server")
agent_server_decorators_stub.get_request_headers = lambda: {}
agent_server_decorators_stub.invoke = lambda *args, **kwargs: (lambda fn: fn)
agent_server_decorators_stub.stream = lambda *args, **kwargs: (lambda fn: fn)
sys.modules.setdefault("mlflow.genai.agent_server", agent_server_decorators_stub)

responses_stub = types.ModuleType("mlflow.types.responses")


class _FakeResponsesAgentStreamEvent(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


def _output_to_responses_items_stream(messages):
    for msg in messages:
        yield _FakeResponsesAgentStreamEvent(
            type="response.output_item.done",
            item={
                "type": "message",
                "id": getattr(msg, "id", "done-id"),
                "role": "assistant",
                "content": [{"type": "output_text", "text": getattr(msg, "content", "")}],
            },
        )


responses_stub.ResponsesAgentRequest = object
responses_stub.ResponsesAgentResponse = object
responses_stub.ResponsesAgentStreamEvent = _FakeResponsesAgentStreamEvent
responses_stub.output_to_responses_items_stream = _output_to_responses_items_stream
responses_stub.to_chat_completions_input = lambda items: items
sys.modules.setdefault("mlflow.types.responses", responses_stub)

sys.modules.setdefault("litellm", types.SimpleNamespace(suppress_debug_info=False))

messages_stub = types.ModuleType("langchain_core.messages")


class _BaseMessage:
    def __init__(self, content="", id=None):
        self.content = content
        self.id = id
        self.tool_calls = None


class _SystemMessage(_BaseMessage):
    pass


class _HumanMessage(_BaseMessage):
    pass


class _AIMessage(_BaseMessage):
    pass


class _AIMessageChunk(_BaseMessage):
    pass


messages_stub.SystemMessage = _SystemMessage
messages_stub.HumanMessage = _HumanMessage
messages_stub.AIMessage = _AIMessage
messages_stub.AIMessageChunk = _AIMessageChunk
sys.modules.setdefault("langchain_core.messages", messages_stub)

utils_stub = types.ModuleType("agent_server.utils")
utils_stub.get_session_id = lambda _request: None
sys.modules.setdefault("agent_server.utils", utils_stub)

state_stub = types.ModuleType("agent_server.multi_agent.core.state")
state_stub.RESET_STATE_TEMPLATE = {}
sys.modules.setdefault("agent_server.multi_agent.core.state", state_stub)

langgraph_pkg = types.ModuleType("langgraph")
sys.modules.setdefault("langgraph", langgraph_pkg)

langgraph_types_stub = types.ModuleType("langgraph.types")
langgraph_types_stub.Command = object
sys.modules.setdefault("langgraph.types", langgraph_types_stub)


class _FakeCompiledApp:
    def __init__(self, raw_events):
        self._raw_events = raw_events

    def get_state(self, _run_config):
        return SimpleNamespace(tasks=[])

    def stream(self, _input_data, _run_config, **_kwargs):
        yield from self._raw_events


class _FakeWorkflow:
    def __init__(self, raw_events):
        self._app = _FakeCompiledApp(raw_events)

    def compile(self, checkpointer=None):
        return self._app


graph_stub = types.ModuleType("agent_server.multi_agent.core.graph")
graph_stub.create_super_agent_hybrid = lambda: _FakeWorkflow([])
sys.modules.setdefault("agent_server.multi_agent.core.graph", graph_stub)


class _FakeCheckpointSaver:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


databricks_langchain_stub = types.ModuleType("databricks_langchain")
databricks_langchain_stub.CheckpointSaver = _FakeCheckpointSaver
sys.modules.setdefault("databricks_langchain", databricks_langchain_stub)


agent_server_pkg = sys.modules.get("agent_server")
if agent_server_pkg is not None and hasattr(agent_server_pkg, "agent"):
    delattr(agent_server_pkg, "agent")
sys.modules.pop("agent_server.agent", None)
agent_module = importlib.import_module("agent_server.agent")


class _FakeInputItem:
    def __init__(self, role: str, content: str):
        self._payload = {"role": role, "content": content}

    def model_dump(self):
        return self._payload


def _build_terminal_update(*, text: str, is_irrelevant: bool, is_meta_question: bool):
    return (
        (),
        "updates",
        {
            "unified_intent_context_clarification": {
                "current_turn": {"metadata": {"is_irrelevant": is_irrelevant, "is_meta_question": is_meta_question}},
                "turn_history": [{"metadata": {"is_irrelevant": is_irrelevant, "is_meta_question": is_meta_question}}],
                "question_clear": True,
                "is_irrelevant": is_irrelevant,
                "is_meta_question": is_meta_question,
                "messages": [_AIMessage(content=text, id="ai-terminal")],
            }
        },
    )


def _build_terminal_streamed_events(*, text: str, kind: str, is_irrelevant: bool, is_meta_question: bool):
    events = [
        (
            (),
            "updates",
            {
                "unified_intent_context_clarification": {
                    "question_clear": True,
                    "messages": [],
                }
            },
        ),
        ((), "custom", {"type": "text_delta", "content": text}),
    ]
    if kind == "meta":
        events.insert(1, ((), "custom", {"type": "summary_start", "content": "Generating meta-answer..."}))
        events.append(((), "custom", {"type": "summary_complete", "content": "Meta-answer complete"}))
    events.append(
        _build_terminal_update(
            text=text,
            is_irrelevant=is_irrelevant,
            is_meta_question=is_meta_question,
        )
    )
    return events


async def _collect_events(raw_events):
    agent_module._workflow = _FakeWorkflow(raw_events)
    request = SimpleNamespace(
        input=[_FakeInputItem("user", "what are healthy habits?")],
        custom_inputs={"thread_id": "thread-1"},
        context=SimpleNamespace(conversation_id="thread-1", user_id=None),
    )
    return [event async for event in agent_module.stream_handler(request)]


def test_irrelevant_terminal_response_streams_after_processing_details():
    refusal = (
        "I'm a data analytics assistant focused on helping you analyze and query "
        "the available data sources."
    )
    events = asyncio.run(
        _collect_events(
            _build_terminal_streamed_events(
                text=refusal,
                kind="irrelevant",
                is_irrelevant=True,
                is_meta_question=False,
            )
        )
    )

    deltas = [event.delta for event in events if getattr(event, "type", "") == "response.output_text.delta"]
    output_texts = [
        part["text"]
        for event in events
        if getattr(event, "type", "") == "response.output_item.done"
        for part in event.item.get("content", [])
        if isinstance(part, dict) and part.get("type") == "output_text"
    ]

    assert any("<details open>" in delta for delta in deltas)
    assert any("</details>" in delta for delta in deltas)
    assert not any("---" in delta for delta in deltas)
    assert any("data analytics assistant" in delta for delta in deltas)
    assert not any("data analytics assistant" in text for text in output_texts)


def test_meta_terminal_response_streams_after_processing_details():
    meta_answer = "## Available Data Sources\n\nYou can ask about patient counts by plan and month."
    events = asyncio.run(
        _collect_events(
            _build_terminal_streamed_events(
                text=meta_answer,
                kind="meta",
                is_irrelevant=False,
                is_meta_question=True,
            )
        )
    )

    deltas = [event.delta for event in events if getattr(event, "type", "") == "response.output_text.delta"]
    output_texts = [
        part["text"]
        for event in events
        if getattr(event, "type", "") == "response.output_item.done"
        for part in event.item.get("content", [])
        if isinstance(part, dict) and part.get("type") == "output_text"
    ]
    assert any("<details open>" in delta for delta in deltas)
    assert any("</details>" in delta for delta in deltas)
    assert not any("---" in delta for delta in deltas)
