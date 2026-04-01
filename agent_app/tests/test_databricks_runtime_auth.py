from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_server.databricks_runtime_auth import get_vector_search_workspace_client
from agent_server.multi_agent.agents.planning_agent import PlanningAgent


class _DummyLLM:
    def stream(self, _prompt):
        return []


def test_get_vector_search_workspace_client_reuses_compatible_auth(monkeypatch):
    compatible_client = SimpleNamespace(
        config=SimpleNamespace(
            auth_type="pat",
            host="https://example.databricks.com",
            token="token-123",
        )
    )

    monkeypatch.setattr(
        "agent_server.databricks_runtime_auth.get_workspace_client",
        lambda: compatible_client,
    )

    result = get_vector_search_workspace_client()

    assert result is compatible_client


def test_get_vector_search_workspace_client_materializes_cli_bearer(monkeypatch):
    cli_client = SimpleNamespace(
        config=SimpleNamespace(
            auth_type="databricks-cli",
            host="https://example.databricks.com",
            authenticate=lambda: {"Authorization": "Bearer rotated-token"},
        )
    )

    created_clients = []

    def fake_workspace_client(*, host=None, token=None):
        client = SimpleNamespace(
            config=SimpleNamespace(auth_type="pat", host=host, token=token)
        )
        created_clients.append(client)
        return client

    monkeypatch.setattr(
        "agent_server.databricks_runtime_auth.get_workspace_client",
        lambda: cli_client,
    )
    monkeypatch.setattr(
        "agent_server.databricks_runtime_auth.WorkspaceClient",
        fake_workspace_client,
    )

    result = get_vector_search_workspace_client()

    assert len(created_clients) == 1
    assert result is created_clients[0]
    assert result.config.host == "https://example.databricks.com"
    assert result.config.token == "rotated-token"


def test_planning_agent_retries_once_on_invalid_token(monkeypatch):
    docs = [
        SimpleNamespace(
            page_content="Space summary",
            metadata={
                "space_id": "space-1",
                "space_title": "Test Space",
                "score": 0.9,
            },
        )
    ]
    attempts = {"count": 0}

    class _FakeVectorStore:
        def similarity_search(self, **_kwargs):
            return docs

    class _FakeTool:
        def __init__(self):
            self._vector_store = _FakeVectorStore()

    def fake_build_vs_tool(self):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Invalid Token")
        return _FakeTool()

    monkeypatch.setattr(PlanningAgent, "_build_vs_tool", fake_build_vs_tool)

    agent = PlanningAgent(_DummyLLM(), "catalog.schema.index")
    results = agent.search_relevant_spaces("query", num_results=1)

    assert attempts["count"] == 2
    assert results == [
        {
            "space_id": "space-1",
            "space_title": "Test Space",
            "searchable_content": "Space summary",
            "score": 0.9,
        }
    ]
