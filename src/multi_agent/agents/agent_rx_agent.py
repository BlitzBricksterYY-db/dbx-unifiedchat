"""
AgentRx - Knowledge Base Management Agent

This agent handles user requests to manage which Genie Spaces the
multi-agent system has access to (i.e. which spaces are indexed in the
enriched metadata tables and Vector Search index used by the Planning Agent).

Capabilities:
- List / inspect what Genie Spaces are currently indexed
- Remove a space from the agent's knowledge base
- Add a new space to the agent's knowledge base
- Browse all Genie Spaces on the workspace for discovery
- Trigger ETL pipeline refreshes (metadata enrichment, vector search sync)

It uses a ReAct (tool-calling) loop so it can chain multiple operations
(e.g., inspect indexed spaces, remove one, then sync the index).
"""

from typing import List, Dict, Any

from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from ..tools.genie_space_manager import ALL_GENIE_TOOLS
from ..tools.knowledge_base_manager import ALL_KB_TOOLS
from ..tools.etl_trigger import ALL_ETL_TOOLS


AGENT_RX_SYSTEM_PROMPT = """You are AgentRx, a knowledge-base management assistant for a Databricks multi-agent system.

The system answers data questions by looking up relevant Genie Spaces in an enriched metadata index (Vector Search). Your job is to manage which Genie Spaces are included in that index — i.e. what the agent "has access to".

## Key Concept
"Adding" or "removing access" to a Genie Space means adding or removing its metadata from the enriched tables and Vector Search index that the Planning Agent uses. It does NOT mean creating, deleting, or modifying the actual Genie Space on the workspace.

## Capabilities

### Knowledge Base Management
1. **List indexed spaces** — show which Genie Spaces the agent currently knows about (from the enriched metadata tables)
2. **Get indexed space details** — inspect chunk types, table coverage, and chunk counts for a specific indexed space
3. **Remove a space from the index** — delete all metadata for a space from the enriched tables, remove exported files, sync the Vector Search index, and invalidate caches. The space itself is untouched.
4. **Add a space to the index** — export a Genie Space's metadata, trigger the ETL pipeline to enrich it and rebuild the search index

### Discovery (read-only)
5. **List all Genie Spaces** on the workspace — browse available spaces, including ones not yet indexed
6. **Inspect a Genie Space's configuration** — view tables, instructions, warehouse of any space on the workspace

### ETL & Refresh
7. **Trigger a Vector Search sync** — lightweight refresh after table-level changes
8. **Trigger the full ETL pipeline** — export → enrich → rebuild index (runs asynchronously)
9. **Invalidate the space context cache** — force the next query to reload from database

## Workflow Guidelines

- When the user asks to "remove" data, a space, or a topic: use **remove_space_from_index** (not a Genie Space deletion).
- When the user asks to "add" a new data source or space: use **add_space_to_index**.
- Before removing, call **list_indexed_spaces** to identify the correct space_id.
- After removal, the Vector Search sync and cache invalidation happen automatically inside the tool.
- If the user asks what data is currently accessible, use **list_indexed_spaces**.
- Always report the outcome of each operation clearly in markdown format.
- If an operation fails, include the error details and suggest corrective actions.

## Response Format

Provide your final response as well-structured markdown with:
- A summary of what was requested
- The operations performed and their results
- Any follow-up actions recommended
"""


class AgentRxAgent:
    """
    Knowledge base management agent using a ReAct tool-calling loop.

    Wraps Genie Space discovery tools, knowledge base management tools,
    and ETL trigger tools into a LangChain tool-calling agent.
    """

    def __init__(self, llm: Runnable, tools: List[BaseTool] = None):
        """
        Initialize AgentRxAgent.

        Args:
            llm: Language model with tool-calling support.
            tools: Override default tools. If None, uses all discovery + KB + ETL tools.
        """
        self.llm = llm
        self.tools = tools or (ALL_GENIE_TOOLS + ALL_KB_TOOLS + ALL_ETL_TOOLS)
        self.name = "AgentRx"
        self._agent = self._build_agent()

    def _build_agent(self):
        """Build the ReAct agent with bound tools."""
        from langgraph.prebuilt import create_react_agent

        return create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=AGENT_RX_SYSTEM_PROMPT,
        )

    def invoke(self, user_request: str) -> Dict[str, Any]:
        """
        Run the agent on a user's resource modification request.

        Args:
            user_request: Natural language description of the modification.

        Returns:
            Dictionary with 'response' (markdown string) and 'tool_calls' (list of tool invocations).
        """
        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": user_request}]}
        )

        messages = result.get("messages", [])

        # Extract final AI response and tool call history
        final_response = ""
        tool_calls = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({"tool": tc.get("name", ""), "args": tc.get("args", {})})
            if hasattr(msg, "content") and msg.content:
                final_response = msg.content

        return {
            "response": final_response,
            "tool_calls": tool_calls,
        }

    def __call__(self, user_request: str) -> Dict[str, Any]:
        """Alias for invoke."""
        return self.invoke(user_request)
