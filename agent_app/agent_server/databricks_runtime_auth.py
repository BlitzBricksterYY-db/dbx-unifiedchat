"""Databricks auth helpers for long-lived local and deployed runtimes."""

from __future__ import annotations

import logging
from typing import Any

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

_VECTOR_SEARCH_COMPATIBLE_AUTH_TYPES = {
    "model_serving_user_credentials",
    "oauth-m2m",
    "pat",
}


def _extract_authorization_header(auth_result: Any) -> str:
    """Normalize SDK auth results into an Authorization header string."""
    if isinstance(auth_result, dict):
        return auth_result.get("Authorization", "")

    if callable(auth_result):
        headers = auth_result()
        if isinstance(headers, dict):
            return headers.get("Authorization", "")

    return ""


def get_workspace_client() -> WorkspaceClient:
    """Build a WorkspaceClient using the current runtime auth chain."""
    return WorkspaceClient()


def _has_vector_search_compatible_credentials(workspace_client: WorkspaceClient) -> bool:
    """Return whether the SDK client exposes credentials databricks-langchain understands."""
    config = workspace_client.config
    auth_type = getattr(config, "auth_type", None)

    if auth_type == "model_serving_user_credentials":
        return True

    if auth_type == "pat":
        return bool(getattr(config, "host", None) and getattr(config, "token", None))

    if auth_type == "oauth-m2m":
        return bool(
            getattr(config, "host", None)
            and getattr(config, "client_id", None)
            and getattr(config, "client_secret", None)
        )

    return False


def get_vector_search_workspace_client() -> WorkspaceClient:
    """Build a WorkspaceClient compatible with databricks-vectorsearch.

    Databricks Apps and explicit PAT/OAuth configs already produce compatible
    auth types. Local CLI auth does not, so we materialize a fresh bearer token
    for the current request instead of storing one in process-global env vars.
    """
    workspace_client = get_workspace_client()
    auth_type = getattr(workspace_client.config, "auth_type", None)

    if (
        auth_type in _VECTOR_SEARCH_COMPATIBLE_AUTH_TYPES
        and _has_vector_search_compatible_credentials(workspace_client)
    ):
        return workspace_client

    auth_header = _extract_authorization_header(
        workspace_client.config.authenticate()
    )
    if not auth_header.startswith("Bearer "):
        raise ValueError(
            "Unable to resolve a bearer token for Databricks Vector Search "
            f"(auth_type={auth_type!r})."
        )

    if not workspace_client.config.host:
        raise ValueError("Databricks host is required for Vector Search auth.")

    logger.info(
        "Materialized fresh Databricks bearer token for vector search "
        "(auth_type=%s)",
        auth_type,
    )
    return WorkspaceClient(
        host=workspace_client.config.host,
        token=auth_header[7:],
        auth_type="pat",
    )
