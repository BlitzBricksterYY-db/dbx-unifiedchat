import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys
import types


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
multi_agent_root = Path(__file__).resolve().parents[2] / "agent_server" / "multi_agent"

multi_agent_pkg = types.ModuleType("agent_server.multi_agent")
multi_agent_pkg.__path__ = [str(multi_agent_root)]
sys.modules.setdefault("agent_server.multi_agent", multi_agent_pkg)

core_pkg = types.ModuleType("agent_server.multi_agent.core")
core_pkg.__path__ = [str(multi_agent_root / "core")]
sys.modules.setdefault("agent_server.multi_agent.core", core_pkg)


@contextmanager
def _noop_context_manager(*_args, **_kwargs):
    class _Span:
        def set_inputs(self, *_args, **_kwargs):
            return None

        def set_outputs(self, *_args, **_kwargs):
            return None

        def set_status(self, *_args, **_kwargs):
            return None

        def set_attribute(self, *_args, **_kwargs):
            return None

    yield _Span()


mlflow_stub = types.ModuleType("mlflow")
mlflow_stub.update_current_trace = lambda *args, **kwargs: None
mlflow_stub.start_span = lambda *args, **kwargs: _noop_context_manager()
mlflow_stub.langchain = SimpleNamespace(autolog=lambda **_kwargs: None)
sys.modules.setdefault("mlflow", mlflow_stub)

mlflow_entities_stub = types.ModuleType("mlflow.entities")
mlflow_entities_stub.SpanType = SimpleNamespace(AGENT="agent", TOOL="tool")
sys.modules.setdefault("mlflow.entities", mlflow_entities_stub)

agent_server_decorators_stub = types.ModuleType("mlflow.genai.agent_server")
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

langchain_core_pkg = types.ModuleType("langchain_core")
sys.modules.setdefault("langchain_core", langchain_core_pkg)

runnables_stub = types.ModuleType("langchain_core.runnables")
runnables_stub.RunnableConfig = dict
sys.modules.setdefault("langchain_core.runnables", runnables_stub)

tools_stub = types.ModuleType("langchain_core.tools")
tools_stub.tool = lambda fn: fn
sys.modules.setdefault("langchain_core.tools", tools_stub)

messages_stub = types.ModuleType("langchain_core.messages")


class _BaseMessage:
    def __init__(self, content=""):
        self.content = content
        self.id = None
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
state_stub.AgentState = dict
state_stub.ConversationTurn = dict
state_stub.GraphInput = dict
state_stub.QueryExecutionResult = dict
sys.modules.setdefault("agent_server.multi_agent.core.state", state_stub)

graph_stub = types.ModuleType("agent_server.multi_agent.core.graph")
graph_stub.create_super_agent_hybrid = lambda: None
sys.modules.setdefault("agent_server.multi_agent.core.graph", graph_stub)

langgraph_graph_stub = types.ModuleType("langgraph.graph")
langgraph_graph_stub.StateGraph = object
sys.modules.setdefault("langgraph.graph", langgraph_graph_stub)


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


class _FakeCommand:
    def __init__(self, resume=None, update=None):
        self.resume = resume
        self.update = update or {}


langgraph_types_stub = types.ModuleType("langgraph.types")
langgraph_types_stub.Command = _FakeCommand
sys.modules.setdefault("langgraph.types", langgraph_types_stub)

mlflow_pyfunc_stub = types.ModuleType("mlflow.pyfunc")
mlflow_pyfunc_stub.ResponsesAgent = object
sys.modules.setdefault("mlflow.pyfunc", mlflow_pyfunc_stub)


from agent_server.multi_agent.core import responses_agent


class _FakeInputItem:
    def __init__(self, role: str, content: str):
        self._payload = {"role": role, "content": content}

    def model_dump(self):
        return self._payload


class _FakeCompiledApp:
    def __init__(self):
        self.received_input = None

    def get_state(self, _run_config):
        return SimpleNamespace(tasks=[SimpleNamespace(interrupts=True)])

    def stream(self, input_data, _run_config, **_kwargs):
        self.received_input = input_data
        return []


class _FakeWorkflow:
    def __init__(self, app):
        self._app = app

    def compile(self, checkpointer=None):
        return self._app


def test_resume_command_carries_all_agent_settings():
    compiled_app = _FakeCompiledApp()
    responses_agent.LAKEBASE_INSTANCE_NAME = "test-instance"
    agent = responses_agent.SuperAgentHybridResponsesAgent(_FakeWorkflow(compiled_app))
    agent.lakebase_instance_name = "test-instance"

    request = SimpleNamespace(
        input=[_FakeInputItem("user", "monthly for 2024")],
        custom_inputs={
            "thread_id": "thread-123",
            "user_id": "user@example.com",
            "execution_mode": "sequential",
            "force_synthesis_route": "table_route",
            "clarification_sensitivity": "on",
        },
        context=SimpleNamespace(conversation_id="thread-123", user_id="user@example.com"),
    )

    for _event in agent.predict_stream(request):
        pass

    assert isinstance(compiled_app.received_input, _FakeCommand)
    assert compiled_app.received_input.resume == "monthly for 2024"
    assert compiled_app.received_input.update == {
        "execution_mode": "sequential",
        "force_synthesis_route": "table_route",
        "clarification_sensitivity": "on",
    }
