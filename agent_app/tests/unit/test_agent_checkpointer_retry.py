import asyncio
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


responses_stub.ResponsesAgentRequest = object
responses_stub.ResponsesAgentResponse = object
responses_stub.ResponsesAgentStreamEvent = _FakeResponsesAgentStreamEvent
responses_stub.output_to_responses_items_stream = lambda *_args, **_kwargs: []
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
messages_stub.BaseMessage = _BaseMessage
sys.modules.setdefault("langchain_core.messages", messages_stub)

utils_stub = types.ModuleType("agent_server.utils")
utils_stub.get_session_id = lambda _request: None
sys.modules.setdefault("agent_server.utils", utils_stub)

state_stub = types.ModuleType("agent_server.multi_agent.core.state")
state_stub.RESET_STATE_TEMPLATE = {}
sys.modules.setdefault("agent_server.multi_agent.core.state", state_stub)

langgraph_pkg = types.ModuleType("langgraph")
sys.modules.setdefault("langgraph", langgraph_pkg)


class _FakeCommand:
    def __init__(self, resume=None, update=None):
        self.resume = resume
        self.update = update or {}


langgraph_types_stub = types.ModuleType("langgraph.types")
langgraph_types_stub.Command = _FakeCommand
sys.modules.setdefault("langgraph.types", langgraph_types_stub)

graph_stub = types.ModuleType("agent_server.multi_agent.core.graph")
graph_stub.create_super_agent_hybrid = lambda: SimpleNamespace(compile=lambda **_kwargs: None)
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
databricks_langchain_stub.DatabricksStore = object
sys.modules.setdefault("databricks_langchain", databricks_langchain_stub)


from agent_server import agent as agent_module


class _FakeInputItem:
    def __init__(self, role: str, content: str):
        self._payload = {"role": role, "content": content}

    def model_dump(self):
        return self._payload


class _FailingCompiledApp:
    def get_state(self, _run_config):
        raise RuntimeError(
            "AdminShutdown: terminating connection due to administrator command"
        )

    def stream(self, *_args, **_kwargs):
        return []


class _SuccessfulCompiledApp:
    def __init__(self):
        self.stream_calls = 0

    def get_state(self, _run_config):
        return SimpleNamespace(tasks=[])

    def stream(self, _input_data, _run_config, **_kwargs):
        self.stream_calls += 1
        yield (
            (),
            "custom",
            {"type": "meta_answer_content", "content": "Recovered after retry"},
        )


async def _collect_events():
    request = SimpleNamespace(
        input=[_FakeInputItem("user", "Give me example questions")],
        custom_inputs={"thread_id": "thread-1"},
        context=SimpleNamespace(conversation_id="thread-1", user_id="user@example.com"),
    )
    return [event async for event in agent_module.stream_handler(request)]


def test_stream_handler_retries_once_on_recoverable_checkpointer_error(monkeypatch):
    apps = [_FailingCompiledApp(), _SuccessfulCompiledApp()]
    reset_reasons = []

    def fake_get_compiled_workflow_app():
        return apps.pop(0)

    def fake_reset_compiled_workflow_app(reason=None):
        reset_reasons.append(reason)

    monkeypatch.setattr(
        agent_module, "_get_compiled_workflow_app", fake_get_compiled_workflow_app
    )
    monkeypatch.setattr(
        agent_module, "_reset_compiled_workflow_app", fake_reset_compiled_workflow_app
    )

    events = asyncio.run(_collect_events())

    assert len(reset_reasons) == 1
    assert "administrator command" in reset_reasons[0].lower()
    assert len(apps) == 0
    assert any(
        getattr(event, "type", "") == "response.output_item.done"
        and event.item["content"][0]["text"].strip() == "Recovered after retry"
        for event in events
    )
