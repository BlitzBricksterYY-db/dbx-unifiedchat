"""
ClarificationAgent: Graph-based sub-agent for intent, classification, and clarity.

classify_query_type and check_clarity run in parallel, fan-in at merge_classification,
which routes on all available state in one place:

    START
      |-- classify_query_type      (is_irrelevant, is_meta_question)
      +-- check_clarity            (context_summary, question_clear, current_turn)
              | fan-in
          merge_classification
              | route
              |-- is_irrelevant=True     -> handle_irrelevant    -> END
              |-- is_meta_question=True  -> generate_meta_answer -> END
              |-- question_clear=False   -> clarify (always interrupts)
              |                               |
              |                         confirm_continuation
              |                               |-- answering -> handle_clear -> END
              |                               +-- new question -> [classify_query_type,
              |                                                    check_clarity] (loop back)
              +-- question_clear=True    -> handle_clear -> END
"""

import json
import time
from datetime import datetime, timedelta
from typing import List, Optional

from databricks_langchain import ChatDatabricks
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, convert_to_messages
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from ..core.base_agent import BaseAgent
from ..core.state import AgentState, create_conversation_turn


# ---------------------------------------------------------------------------
# Schemas for structured LLM output (TypedDict -- consistent with state.py)
# ---------------------------------------------------------------------------

class QueryTypeClassification(TypedDict):
    is_irrelevant: bool
    is_meta_question: bool


class ClarityCheck(TypedDict):
    question_clear: bool
    context_summary: str
    clarification_reason: Optional[str]
    clarification_options: Optional[List[str]]


class ContinuationCheck(TypedDict):
    is_clarification_response: bool
    reasoning: str


# ---------------------------------------------------------------------------
# Module-level helpers (stateless, no class dependency)
# ---------------------------------------------------------------------------

def _latest_human_content(messages: list) -> str:
    """Extract the most recent human message content in any format.

    Uses LangChain's convert_to_messages to normalise HumanMessage objects,
    LangChain dicts {"type": "human"}, and OpenAI dicts {"role": "user"}.
    """
    try:
        normalised = convert_to_messages(messages)
    except Exception:
        normalised = messages
    for m in reversed(normalised):
        if isinstance(m, HumanMessage):
            return m.content
    return ""

_space_context_cache: dict = {"data": None, "timestamp": None, "table_name": None}
_SPACE_CONTEXT_CACHE_TTL = timedelta(minutes=30)
_VALID_CLARIFICATION_SENSITIVITIES = ["off", "low", "medium", "high", "on"]


def _get_clarification_sensitivity(state: AgentState) -> str:
    sensitivity = state.get("clarification_sensitivity") or "medium"
    if sensitivity in _VALID_CLARIFICATION_SENSITIVITIES:
        return sensitivity
    return "medium"


def _clarification_policy_text(sensitivity: str) -> str:
    policies = {
        "off": (
            "Never ask a clarification question. Always set question_clear=True and "
            "set clarification_reason / clarification_options to null."
        ),
        "low": (
            "Be very lenient. Ask for clarification only when critical information is "
            "missing and the request cannot be answered responsibly without it."
        ),
        "medium": (
            "Use balanced judgment. Ask for clarification when key scope, metric, or "
            "timeframe details are missing and would materially change the answer."
        ),
        "high": (
            "Be strict. Ask for clarification whenever important scope, metric, grain, "
            "or timeframe details are not explicit."
        ),
        "on": (
            "Always ask a clarification question before planning. Always set "
            "question_clear=False and provide a concise clarification_reason plus 2-3 "
            "specific clarification_options, even if the request seems answerable."
        ),
    }
    return policies.get(sensitivity, policies["medium"])


def _emit_clarification_result(writer, result: str, content: str) -> None:
    writer(
        {
            "type": "clarification_result",
            "result": result,
            "content": content,
        }
    )


def load_space_context(table_name: str) -> dict:
    """Load Genie space summaries from Delta with 30-minute TTL caching."""
    global _space_context_cache
    now = datetime.now()

    if (
        _space_context_cache["data"] is not None
        and _space_context_cache["table_name"] == table_name
        and _space_context_cache["timestamp"] is not None
        and now - _space_context_cache["timestamp"] < _SPACE_CONTEXT_CACHE_TTL
    ):
        age = (now - _space_context_cache["timestamp"]).total_seconds()
        print(f"[space_context] cache hit ({len(_space_context_cache['data'])} spaces, age: {age:.1f}s)")
        return _space_context_cache["data"]

    print("[space_context] loading from database")
    try:
        from databricks.connect import DatabricksSession
        spark = DatabricksSession.builder.serverless().getOrCreate()
    except ImportError:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()

    df = spark.sql(f"""
        SELECT space_id, searchable_content
        FROM {table_name}
        WHERE chunk_type = 'space_summary'
    """)
    context = {row["space_id"]: row["searchable_content"] for row in df.collect()}
    _space_context_cache.update({"data": context, "timestamp": now, "table_name": table_name})
    print(f"[space_context] loaded {len(context)} spaces")
    return context


# ---------------------------------------------------------------------------
# ClarificationAgent
# ---------------------------------------------------------------------------

class ClarificationAgent(BaseAgent):
    """
    Clarification sub-agent implemented as a compiled LangGraph sub-graph.

    Node methods are private to this class -- they access LLMs and config via
    self rather than being threaded through partial().
    """

    def __init__(self, llm_endpoint: str, table_name: str):
        super().__init__("clarification")
        self.table_name = table_name
        self.llm_endpoint = llm_endpoint

        base_llm = ChatDatabricks(endpoint=llm_endpoint, temperature=0.1)
        self.query_type_llm = base_llm.with_structured_output(QueryTypeClassification)
        self.clarity_llm = base_llm.with_structured_output(ClarityCheck)
        self.continuation_llm = base_llm.with_structured_output(ContinuationCheck)
        self.base_llm = base_llm

        self.subgraph = self._build_subgraph()

    # -----------------------------------------------------------------------
    # Graph construction
    # -----------------------------------------------------------------------

    def _build_subgraph(self):
        graph = StateGraph(AgentState)

        graph.add_node("classify_query_type", self._classify_query_type)
        graph.add_node("check_clarity", self._check_clarity)
        graph.add_node("merge_classification", self._merge_classification)
        graph.add_node("handle_irrelevant", self._handle_irrelevant)
        graph.add_node("generate_meta_answer", self._generate_meta_answer)
        graph.add_node("clarify", self._clarify)
        graph.add_node("confirm_continuation", self._confirm_continuation)
        graph.add_node("handle_clear", self._handle_clear)

        # Parallel fan-out
        graph.add_edge(START, "classify_query_type")
        graph.add_edge(START, "check_clarity")

        # Fan-in -- route on all known state in one place
        graph.add_edge("classify_query_type", "merge_classification")
        graph.add_edge("check_clarity", "merge_classification")

        def route_after_classification(state: AgentState) -> str:
            if state.get("is_irrelevant"):
                return "handle_irrelevant"
            if state.get("is_meta_question"):
                return "generate_meta_answer"
            if not state.get("question_clear", True):
                return "clarify"
            return "handle_clear"

        graph.add_conditional_edges(
            "merge_classification",
            route_after_classification,
            {
                "handle_irrelevant": "handle_irrelevant",
                "generate_meta_answer": "generate_meta_answer",
                "clarify": "clarify",
                "handle_clear": "handle_clear",
            },
        )

        # clarify always interrupts, then confirm_continuation decides
        # whether the response answers the question or is a new query
        graph.add_edge("clarify", "confirm_continuation")

        def route_after_continuation(state: AgentState):
            if not state.get("question_clear", True):
                return ["classify_query_type", "check_clarity"]
            return "handle_clear"

        graph.add_conditional_edges("confirm_continuation", route_after_continuation)

        graph.add_edge("handle_irrelevant", END)
        graph.add_edge("generate_meta_answer", END)
        graph.add_edge("handle_clear", END)

        return graph.compile()

    # -----------------------------------------------------------------------
    # Node methods
    # -----------------------------------------------------------------------

    def _classify_query_type(self, state: AgentState) -> dict:
        """Structured LLM call: is_irrelevant + is_meta_question. Runs in parallel."""
        messages = state.get("messages", [])
        current_query = _latest_human_content(messages)
        space_context = load_space_context(self.table_name)

        prompt = f"""You are screening a user query before routing it to a data analytics system.

User Query: {current_query}

Available Data Sources:
{json.dumps(space_context, indent=2)}

Most queries are regular data questions and should pass through with both flags set to False.
Only set a flag to True when the query clearly and unambiguously matches the description below.

is_irrelevant=True ONLY IF: the query is completely unrelated to data analytics — e.g. greetings,
small talk, weather, sports, politics, recipes, personal advice, or creative writing.

is_meta_question=True ONLY IF: the user is asking about the system itself rather than querying data —
e.g. "what tables are available?", "what can you do?", "show me example questions", or "what data sources exist?".

If the query is a normal data or business intelligence question (even a vague one), set both to False.
"""
        try:
            result: QueryTypeClassification = self.query_type_llm.invoke(prompt)
            print(f"[classify_query_type] irrelevant={result['is_irrelevant']} meta={result['is_meta_question']}")
            return {"is_irrelevant": result["is_irrelevant"], "is_meta_question": result["is_meta_question"]}
        except Exception as e:
            print(f"[classify_query_type] error: {e} — defaulting to regular query")
            return {"is_irrelevant": False, "is_meta_question": False}

    def _check_clarity(self, state: AgentState) -> dict:
        """Structured LLM call: summarize context, detect follow-up, check clarity.

        Runs in parallel with classify_query_type. If unclear, interrupt() pauses
        the graph for user input and resumes with the user's response.
        """
        writer = get_stream_writer()
        messages = state.get("messages", [])
        current_query = _latest_human_content(messages)
        space_context = load_space_context(self.table_name)
        clarification_sensitivity = _get_clarification_sensitivity(state)

        print(f"[check_clarity] query={current_query!r} (messages count={len(messages)}, last 3 types={[type(m).__name__ for m in messages[-3:]]})")
        prior_turn = state.get("current_turn") or {}
        prior_summary = prior_turn.get("context_summary", "")
        prompt = f"""You are analyzing a user query for a data analytics assistant.

According to the available data sources:
{json.dumps(space_context, indent=2)}


- Most recent user query: {current_query}

- Prior conversation context: {prior_summary or "None — this is the first message"}


- Clarification sensitivity: {clarification_sensitivity}

- Clarification policy for this request:
{_clarification_policy_text(clarification_sensitivity)}


Answer the following:

1. context_summary: A single sentence that (a) synthesizes the conversation history, (b) states
   clearly what the user wants, and (c) is actionable for SQL query planning. If there is no prior
   context, summarize only the current query.

2. question_clear: True if there is enough information to write a SQL query, based on the
   clarification policy above. Mark False when the current sensitivity setting says clarification
   is needed before planning.

3. clarification_reason: If question_clear=False, a brief explanation of what is missing.
   Otherwise null.

4. clarification_options: If question_clear=False, 2-3 specific options the user can choose from.
   Otherwise null.
"""
        try:
            result: ClarityCheck = self.clarity_llm.invoke(prompt)
            question_clear = result["question_clear"]
            context_summary = result.get("context_summary") or current_query
            clarification_reason = result.get("clarification_reason") or "Query needs more specificity"
            clarification_options = result.get("clarification_options") or []
            if clarification_sensitivity == "off":
                question_clear = True
                clarification_reason = ""
                clarification_options = []
            elif clarification_sensitivity == "on":
                question_clear = False
                clarification_reason = (
                    result.get("clarification_reason")
                    or "Before I proceed, I want to confirm the exact scope you want."
                )
                clarification_options = result.get("clarification_options") or [
                    "Specify the metric or outcome you care about",
                    "Specify the time range or comparison window",
                    "Specify the breakdown or segment you want",
                ]
            print(f"[check_clarity] clear={question_clear}")
        except Exception as e:
            print(f"[check_clarity] error: {e} — defaulting to clear")
            question_clear = True
            context_summary = current_query
            clarification_reason = ""
            clarification_options = []

        metadata = {}
        if not question_clear:
            metadata["clarification_reason"] = clarification_reason
            metadata["clarification_options"] = clarification_options

        turn = create_conversation_turn(
            query=current_query,
            context_summary=context_summary,
            triggered_clarification=False,
            metadata=metadata,
        )
        return {"current_turn": turn, "question_clear": question_clear}

    def _merge_classification(self, state: AgentState) -> dict:
        """Fan-in point after parallel classification nodes. No-op."""
        return {}

    def _handle_irrelevant(self, state: AgentState) -> dict:
        """Return a polite refusal, streamed via ``text_delta`` for consistency."""
        print("[handle_irrelevant] returning refusal")
        turn = dict(state.get("current_turn") or {})
        turn.setdefault("metadata", {})["is_irrelevant"] = True

        refusal = (
            "I'm a data analytics assistant focused on helping you analyze and query "
            "the available data sources.\n\n"
            "I can help with questions about the data. To see what's available, try:\n"
            '- "What data sources are available?"\n'
            '- "What tables can I query?"\n'
            '- "Show me example questions I can ask"\n\n'
            "Could you rephrase your question to focus on analyzing the available data?"
        )

        writer = get_stream_writer()
        writer({"type": "agent_step", "agent": "clarification", "content": "Checking query intent and clarity..."})
        _emit_clarification_result(
            writer,
            "irrelevant_query",
            "Clarification result: irrelevant query.",
        )
        writer({"type": "summary_start", "content": "Generating response..."})
        writer({"type": "text_delta", "content": refusal})
        writer({"type": "summary_complete", "content": f"Response generated ({len(refusal)} chars)"})

        return {
            "current_turn": turn,
            "turn_history": [turn] if turn else [],
            "question_clear": True,
            "is_irrelevant": True,
            "is_meta_question": False,
            "final_summary": refusal,
            "messages": [AIMessage(content=refusal)],
        }

    def _generate_meta_answer(self, state: AgentState) -> dict:
        """Streaming LLM call: markdown answer about available data.

        Uses ``text_delta`` custom events (same as summarize_agent) so both
        serving layers (agent.py and responses_agent.py) handle token
        streaming correctly.  Emits ``meta_answer_content`` at the end for
        the complete-response path.
        """
        messages = state.get("messages", [])
        current_query = _latest_human_content(messages)
        space_context = load_space_context(self.table_name)

        prompt = f"""The user is asking about what data or capabilities are available.

User Query: {current_query}

Available Data Sources:
{json.dumps(space_context, indent=2)}

Provide a clear, informative markdown answer about what's available.
Use ## headings, **bold** keywords, and bullet lists. Be professional and helpful.
"""
        writer = get_stream_writer()
        writer({"type": "agent_step", "agent": "clarification", "content": "Checking query intent and clarity..."})
        _emit_clarification_result(
            writer,
            "meta_question",
            "Clarification result: meta question.",
        )
        writer({"type": "summary_start", "content": "Generating meta-answer..."})
        print("[generate_meta_answer] generating")
        try:
            content = ""
            for chunk in self.base_llm.stream(prompt):
                if chunk.content:
                    content += chunk.content
                    writer({"type": "text_delta", "content": chunk.content})
            answer = content.strip()
        except Exception as e:
            print(f"[generate_meta_answer] error: {e}")
            answer = "## Available Data Sources\n\nSorry, I encountered an error retrieving the data source information."
            writer({"type": "text_delta", "content": answer})

        writer({"type": "summary_complete", "content": f"Meta-answer generated ({len(answer)} chars)"})

        turn = dict(state.get("current_turn") or {})
        turn.setdefault("metadata", {})["is_meta_question"] = True

        return {
            "current_turn": turn,
            "turn_history": [turn] if turn else [],
            "question_clear": True,
            "is_meta_question": True,
            "meta_answer": answer,
            "final_summary": answer,
            "messages": [AIMessage(content=answer)],
        }

    def _clarify(self, state: AgentState) -> dict:
        """Always interrupts for user input -- only reached when question_clear=False.

        Emits the clarification question as a streamable event before pausing so
        the serving layer can relay the question to the user in the HTTP response.
        """
        turn = state.get("current_turn") or {}
        metadata = turn.get("metadata") or {}
        clarification_reason = metadata.get("clarification_reason", "Query needs more specificity")
        clarification_options = metadata.get("clarification_options") or []
        context_summary = turn.get("context_summary", "")
        prompt_already_sent = bool(metadata.get("clarification_prompt_sent"))

        writer = get_stream_writer()
        markdown = f"### Clarification Needed\n\n{clarification_reason}\n\n"
        if clarification_options:
            markdown += "**Please choose from the following options:**\n\n"
            for i, opt in enumerate(clarification_options, 1):
                markdown += f"{i}. {opt}\n\n"
        if not prompt_already_sent:
            metadata["clarification_prompt_sent"] = True
            turn["metadata"] = metadata
            writer(
                {
                    "type": "agent_step",
                    "agent": "clarification",
                    "content": "Clarification required before planning can continue.",
                }
            )
            _emit_clarification_result(
                writer,
                "needs_clarification",
                "Clarification result: more detail needed before planning.",
            )
            writer({
                "type": "clarification_content",
                "content": markdown.strip(),
                "reason": clarification_reason,
                "options": clarification_options,
            })

        print("[clarify] pausing via interrupt()")
        user_response = interrupt({
            "type": "clarification_request",
            "reason": clarification_reason,
            "options": clarification_options,
            "markdown": markdown.strip(),
        })

        print(f"[clarify] resumed with: {user_response!r}")
        turn = dict(turn)
        turn["triggered_clarification"] = True
        turn["context_summary"] = (
            f"{context_summary} — "
            f"Clarification asked: {clarification_reason} — "
            f"User answered: {user_response}"
        )
        return {
            "current_turn": turn,
            "question_clear": True,
            # Preserve or not the clarification prompt in message history so traces show
            # the assistant turn that led to the user's follow-up response.
            "messages": [
                #AIMessage(content=markdown.strip()),
                HumanMessage(content=user_response)
            ],
        }

    def _confirm_continuation(self, state: AgentState) -> dict:
        """Check if the user's response answers the clarification or is a new question.

        Pass-through when no clarification was triggered (question was already clear).
        If the user responded with a new, unrelated question, set question_clear=False
        so the subgraph loops back to the parallel classification nodes.
        """
        turn = state.get("current_turn") or {}
        if not turn.get("triggered_clarification"):
            return {"question_clear": True}

        messages = state.get("messages", [])
        user_response = _latest_human_content(messages)
        original_context = turn.get("context_summary", "")

        prompt = f"""A user was asked a clarification question while answering a data analytics query.
Determine whether their response directly answers the clarification or is a brand-new, unrelated question.

Original context / clarification asked: {original_context}
User's response: {user_response}

is_clarification_response=True  -> they answered the clarification (even loosely)
is_clarification_response=False -> they changed the subject or asked something entirely new
"""
        try:
            result: ContinuationCheck = self.continuation_llm.invoke(prompt)
            is_continuation = result["is_clarification_response"]
            print(f"[confirm_continuation] is_continuation={is_continuation} reason={result['reasoning']!r}")
        except Exception as e:
            print(f"[confirm_continuation] error: {e} — assuming continuation")
            is_continuation = True

        if is_continuation:
            return {"question_clear": True}

        print("[confirm_continuation] user asked a new question — restarting classification")
        turn = dict(turn)
        turn["triggered_clarification"] = False
        return {"current_turn": turn, "question_clear": False}

    def _handle_clear(self, state: AgentState) -> dict:
        """Pure Python. Confirm clarity and forward to planning."""
        print("[handle_clear] query is clear")
        writer = get_stream_writer()
        _emit_clarification_result(
            writer,
            "clear_continue_to_planning",
            "Clarification result: clear, continue to planning.",
        )
        turn = state.get("current_turn", {})
        return {
            "current_turn": turn,
            "turn_history": [turn] if turn else [],
            "question_clear": True,
        }

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def run(self, state: AgentState) -> dict:
        self.track_agent_model_usage(self.llm_endpoint)
        return self.subgraph.invoke(state)
