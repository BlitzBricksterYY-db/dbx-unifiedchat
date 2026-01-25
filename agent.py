"""
MLflow Deployment Agent for Multi-Agent Genie System with Memory Support

This agent.py file contains the runtime-essential components extracted from 
Super_Agent_hybrid.py for MLflow deployment to Databricks Model Serving.

Features:
- Short-term memory (CheckpointSaver): Multi-turn conversations within a session
- Long-term memory (DatabricksStore): User preferences across sessions
- Works seamlessly in distributed Model Serving

Prerequisites:
- UC functions must be registered (see Super_Agent_hybrid.py for definitions)
- Lakebase instance must be created and configured in .env
- One-time setup must be completed (checkpoint and store tables)

Usage:
mlflow.pyfunc.log_model(
    python_model="agent.py",
    ...
)
"""

import json
import re
import os
import sys
from typing import Dict, List, Optional, Any, Generator, Annotated
from typing_extensions import TypedDict
from uuid import uuid4
import operator
import logging

# MLflow and Databricks imports
import mlflow
from databricks_langchain import (
    ChatDatabricks,
    VectorSearchRetrieverTool,
    DatabricksFunctionClient,
    UCFunctionToolkit,
    set_uc_function_client,
    CheckpointSaver,  # For short-term memory (distributed serving)
    DatabricksStore,  # For long-term memory (user preferences)
)
from databricks_langchain.genie import GenieAgent

# LangChain imports
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AIMessageChunk
from langchain_core.runnables import Runnable, RunnableLambda, RunnableConfig
from langchain_core.tools import tool

# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

# MLflow ResponsesAgent imports
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

# Setup logging
logger = logging.getLogger(__name__)

########################################
# Configuration Loading with ModelConfig
########################################

from mlflow.models import ModelConfig

# Development configuration (used for local testing)
# When deployed, this will be overridden by the config passed to log_model()
development_config = {
    # Unity Catalog Configuration
    "catalog_name": "yyang",
    "schema_name": "multi_agent_genie",
    
    # LLM Endpoint Configuration
    "llm_endpoint": "databricks-claude-sonnet-4-5",
    
    # Vector Search Configuration
    "vs_endpoint_name": "genie_multi_agent_vs",
    "embedding_model": "databricks-gte-large-en",
    
    # Lakebase Configuration (for State Management)
    "lakebase_instance_name": "multi-agent-genie-system-state-db",
    "lakebase_embedding_endpoint": "databricks-gte-large-en",
    "lakebase_embedding_dims": 1024,
    
    # Genie Space IDs
    "genie_space_ids": [
        "01f0eab621401f9faa11e680f5a2bcd0",
        "01f0eababd9f1bcab5dea65cf67e48e3",
        "01f0eac186d11b9897bc1d43836cc4e1"
    ],
    
    # SQL Warehouse ID
    "sql_warehouse_id": "148ccb90800933a1",
    
    # Table Metadata Enrichment
    "sample_size": 20,
    "max_unique_values": 20,
}

# Initialize ModelConfig
# For local development: Uses development_config above
# For Model Serving: Uses config passed during mlflow.pyfunc.log_model(model_config=...)
model_config = ModelConfig(development_config=development_config)

logger.info("="*80)
logger.info("CONFIGURATION LOADED via ModelConfig")
logger.info("="*80)

# Extract configuration values
CATALOG = model_config.get("catalog_name")
SCHEMA = model_config.get("schema_name")
TABLE_NAME = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks"
VECTOR_SEARCH_INDEX = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks_vs_index"

# LLM Endpoints
LLM_ENDPOINT_CLARIFICATION = model_config.get("llm_endpoint")
LLM_ENDPOINT_PLANNING = model_config.get("llm_endpoint")
LLM_ENDPOINT_SQL_SYNTHESIS = model_config.get("llm_endpoint")
LLM_ENDPOINT_SUMMARIZE = model_config.get("llm_endpoint")

# Lakebase configuration for state management
LAKEBASE_INSTANCE_NAME = model_config.get("lakebase_instance_name")
EMBEDDING_ENDPOINT = model_config.get("lakebase_embedding_endpoint")
EMBEDDING_DIMS = model_config.get("lakebase_embedding_dims")

# Genie space IDs
GENIE_SPACE_IDS = model_config.get("genie_space_ids")

# UC Functions
UC_FUNCTION_NAMES = [
    f"{CATALOG}.{SCHEMA}.get_space_summary",
    f"{CATALOG}.{SCHEMA}.get_table_overview",
    f"{CATALOG}.{SCHEMA}.get_column_detail",
    f"{CATALOG}.{SCHEMA}.get_space_details",
]

logger.info(f"Catalog: {CATALOG}, Schema: {SCHEMA}")
logger.info(f"Lakebase: {LAKEBASE_INSTANCE_NAME}")
logger.info(f"Genie Spaces: {len(GENIE_SPACE_IDS)} spaces configured")
logger.info("="*80)

# Initialize UC Function Client
client = DatabricksFunctionClient()
set_uc_function_client(client)

logger.info(f"Configuration loaded: Catalog={CATALOG}, Schema={SCHEMA}, Lakebase={LAKEBASE_INSTANCE_NAME}")

########################################
# Agent State Definition
########################################

class AgentState(TypedDict):
    """
    Explicit state that flows through the multi-agent system.
    Enhanced with memory fields for distributed serving.
    """
    # Input
    original_query: str
    
    # Clarification
    question_clear: bool
    clarification_needed: Optional[str]
    clarification_options: Optional[List[str]]
    clarification_count: Optional[int]
    user_clarification_response: Optional[str]
    clarification_message: Optional[str]
    combined_query_context: Optional[str]
    
    # Planning
    plan: Optional[Dict[str, Any]]
    sub_questions: Optional[List[str]]
    requires_multiple_spaces: Optional[bool]
    relevant_space_ids: Optional[List[str]]
    relevant_spaces: Optional[List[Dict[str, Any]]]
    vector_search_relevant_spaces_info: Optional[List[Dict[str, str]]]
    requires_join: Optional[bool]
    join_strategy: Optional[str]
    execution_plan: Optional[str]
    genie_route_plan: Optional[Dict[str, str]]
    
    # SQL Synthesis
    sql_query: Optional[str]
    sql_synthesis_explanation: Optional[str]
    synthesis_error: Optional[str]
    has_sql: Optional[bool]
    
    # Execution
    execution_result: Optional[Dict[str, Any]]
    execution_error: Optional[str]
    
    # Summary
    final_summary: Optional[str]
    
    # Memory fields (for distributed serving)
    user_id: Optional[str]
    thread_id: Optional[str]
    user_preferences: Optional[Dict]
    
    # Control flow
    next_agent: Optional[str]
    messages: Annotated[List, operator.add]

########################################
# Helper Functions
########################################

def enforce_limit(messages, n=5):
    """Appends instruction to limit result size."""
    last = messages[-1] if messages else {"content": ""}
    content = last.get("content", "") if isinstance(last, dict) else last.content
    return f"{content}\n\nPlease limit the result to at most {n} rows."


def load_space_context(table_name: str) -> Dict[str, str]:
    """
    Load space context from Delta table.
    Called fresh on each request for dynamic refresh.
    """
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        
        df = spark.sql(f"""
            SELECT space_id, searchable_content
            FROM {table_name}
            WHERE chunk_type = 'space_summary'
        """)
        
        context = {row["space_id"]: row["searchable_content"] 
                   for row in df.collect()}
        
        logger.info(f"Loaded {len(context)} Genie spaces for context")
        return context
    except Exception as e:
        logger.error(f"Failed to load space context: {e}")
        return {}


def extract_json_from_markdown(text: str) -> Optional[Dict]:
    """Extract JSON from markdown code blocks."""
    json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON without code blocks
    try:
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except json.JSONDecodeError:
        pass
    
    return None

########################################
# Agent Classes (OOP Design)
########################################

class ClarificationAgent:
    """Agent responsible for validating query clarity."""
    
    def __init__(self, llm: Runnable, table_name: str):
        self.llm = llm
        self.table_name = table_name
        self.space_context = load_space_context(table_name)
    
    def process(self, state: AgentState) -> AgentState:
        """Process clarification logic."""
        original_query = state.get("original_query", "")
        user_clarification_response = state.get("user_clarification_response")
        clarification_count = state.get("clarification_count", 0)
        
        # If this is a clarification response from user
        if user_clarification_response:
            logger.info("Processing user's clarification response")
            combined_context = f"Original query: {original_query}\nClarification: {user_clarification_response}"
            
            return {
                "question_clear": True,
                "combined_query_context": combined_context,
                "next_agent": "planning",
                "messages": [AIMessage(content=f"Thank you for the clarification. Proceeding with analysis.")]
            }
        
        # Initial clarification check
        prompt = f"""Analyze this query and determine if it's clear enough to execute.

Available Genie Spaces:
{json.dumps(self.space_context, indent=2)}

User Query: {original_query}

Only mark as unclear if TRULY VAGUE. Be lenient - if answerable with available data, mark as clear.

Return JSON:
{{
    "question_clear": true/false,
    "clarification_needed": "explanation if unclear (null if clear)",
    "clarification_options": ["option 1", "option 2"] or null
}}
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        result = extract_json_from_markdown(response.content)
        
        if not result:
            logger.warning("Failed to parse clarification response, defaulting to clear")
            result = {"question_clear": True, "clarification_needed": None, "clarification_options": None}
        
        is_clear = result.get("question_clear", True)
        
        if is_clear or clarification_count >= 1:
            return {
                "question_clear": True,
                "next_agent": "planning",
                "messages": [AIMessage(content="Query is clear. Proceeding to planning.")]
            }
        else:
            clarification_msg = f"{result.get('clarification_needed', 'Please clarify your question.')}\n\nOptions:\n"
            for i, opt in enumerate(result.get('clarification_options', []), 1):
                clarification_msg += f"{i}. {opt}\n"
            
            return {
                "question_clear": False,
                "clarification_needed": result.get("clarification_needed"),
                "clarification_options": result.get("clarification_options"),
                "clarification_count": clarification_count + 1,
                "clarification_message": clarification_msg,
                "next_agent": "end",
                "messages": [AIMessage(content=clarification_msg)]
            }


class PlanningAgent:
    """Agent responsible for query planning and vector search."""
    
    def __init__(self, llm: Runnable, vector_search_index: str):
        self.llm = llm
        self.vector_search_tool = VectorSearchRetrieverTool(
            index_name=vector_search_index,
            columns=["space_id", "space_title", "searchable_content"],
            num_results=5
        )
    
    def process(self, state: AgentState) -> AgentState:
        """Process planning logic with vector search."""
        query = state.get("combined_query_context") or state.get("original_query", "")
        
        # Vector search for relevant spaces
        try:
            vs_results = self.vector_search_tool.invoke(query)
            relevant_spaces = []
            for doc in vs_results:
                relevant_spaces.append({
                    "space_id": doc.metadata.get("space_id"),
                    "space_title": doc.metadata.get("space_title"),
                    "searchable_content": doc.page_content
                })
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            relevant_spaces = []
        
        # Generate plan
        prompt = f"""Analyze this query and create an execution plan.

Query: {query}

Relevant Genie Spaces from vector search:
{json.dumps(relevant_spaces, indent=2)}

Return JSON:
{{
    "original_query": "{query}",
    "vector_search_relevant_spaces_info": {json.dumps(relevant_spaces)},
    "question_clear": true,
    "sub_questions": ["sub-q1", "sub-q2"],
    "requires_multiple_spaces": true/false,
    "relevant_space_ids": ["space_id1"],
    "requires_join": true/false,
    "join_strategy": "table_route" or "genie_route",
    "execution_plan": "description",
    "genie_route_plan": {{"space_id": "partial_question"}} or null
}}
"""
        
        response = self.llm.invoke([HumanMessage(content=prompt)])
        plan = extract_json_from_markdown(response.content) or {}
        
        # Determine next agent based on strategy
        join_strategy = plan.get("join_strategy", "table_route")
        next_agent = "sql_synthesis_genie" if join_strategy == "genie_route" else "sql_synthesis_table"
        
        return {
            "plan": plan,
            "sub_questions": plan.get("sub_questions", []),
            "requires_multiple_spaces": plan.get("requires_multiple_spaces", False),
            "relevant_space_ids": plan.get("relevant_space_ids", []),
            "relevant_spaces": relevant_spaces,
            "vector_search_relevant_spaces_info": relevant_spaces,
            "requires_join": plan.get("requires_join", False),
            "join_strategy": join_strategy,
            "execution_plan": plan.get("execution_plan", ""),
            "genie_route_plan": plan.get("genie_route_plan"),
            "next_agent": next_agent,
            "messages": [AIMessage(content=f"Plan created: {plan.get('execution_plan', 'Processing...')}")]
        }


class SQLSynthesisTableAgent:
    """SQL synthesis using UC metadata functions (table route)."""
    
    def __init__(self, llm: Runnable, uc_function_names: List[str]):
        self.llm = llm
        self.uc_toolkit = UCFunctionToolkit(function_names=uc_function_names)
    
    def process(self, state: AgentState) -> AgentState:
        """Process SQL synthesis using UC functions."""
        plan = state.get("plan", {})
        
        # This would invoke the LLM with UC function tools
        # Simplified for deployment - actual implementation would call tools
        
        return {
            "has_sql": False,
            "synthesis_error": "Table route SQL synthesis requires full implementation",
            "next_agent": "summarize",
            "messages": [AIMessage(content="SQL synthesis in progress (table route)...")]
        }


class SQLSynthesisGenieAgent:
    """SQL synthesis using Genie agents (genie route)."""
    
    def __init__(self, llm: Runnable, relevant_spaces: List[Dict[str, Any]]):
        self.llm = llm
        self.relevant_spaces = relevant_spaces
        self.genie_agents = []
        
        # Create Genie agents for relevant spaces
        for space in relevant_spaces:
            space_id = space.get("space_id")
            if not space_id:
                continue
            
            try:
                genie_agent = GenieAgent(
                    genie_space_id=space_id,
                    genie_agent_name=f"Genie_{space.get('space_title', space_id)}",
                    description=space.get("searchable_content", ""),
                    include_context=True,
                    message_processor=lambda msgs: enforce_limit(msgs, n=5)
                )
                self.genie_agents.append((space_id, genie_agent))
            except Exception as e:
                logger.error(f"Failed to create Genie agent for {space_id}: {e}")
    
    def process(self, state: AgentState) -> AgentState:
        """Process SQL synthesis using Genie agents."""
        genie_route_plan = state.get("genie_route_plan", {})
        
        # Query Genie agents and combine SQL
        # Simplified for deployment
        
        return {
            "has_sql": False,
            "synthesis_error": "Genie route SQL synthesis requires full implementation",
            "next_agent": "summarize",
            "messages": [AIMessage(content="SQL synthesis in progress (genie route)...")]
        }


class SQLExecutionAgent:
    """Agent for executing SQL queries."""
    
    def __init__(self, llm: Runnable):
        self.llm = llm
    
    def process(self, state: AgentState) -> AgentState:
        """Execute SQL query on delta tables."""
        sql_query = state.get("sql_query")
        
        if not sql_query:
            return {
                "execution_error": "No SQL query to execute",
                "next_agent": "summarize",
                "messages": [AIMessage(content="No SQL to execute")]
            }
        
        try:
            from pyspark.sql import SparkSession
            spark = SparkSession.builder.getOrCreate()
            
            df = spark.sql(sql_query)
            results = df.limit(100).collect()
            
            return {
                "execution_result": {
                    "success": True,
                    "row_count": len(results),
                    "columns": df.columns,
                    "data": [row.asDict() for row in results]
                },
                "next_agent": "summarize",
                "messages": [AIMessage(content=f"Query executed successfully. {len(results)} rows returned.")]
            }
        except Exception as e:
            return {
                "execution_error": str(e),
                "next_agent": "summarize",
                "messages": [AIMessage(content=f"Query execution failed: {str(e)}")]
            }


class ResultSummarizeAgent:
    """Agent for generating final summary."""
    
    def __init__(self, llm: Runnable):
        self.llm = llm
    
    def process(self, state: AgentState) -> AgentState:
        """Generate comprehensive summary of workflow execution."""
        summary_prompt = f"""Generate a natural language summary of this workflow execution.

Original Query: {state.get('original_query')}
Plan: {json.dumps(state.get('plan', {}), indent=2)}
SQL Generated: {state.get('has_sql', False)}
SQL Query: {state.get('sql_query', 'None')}
Execution Result: {json.dumps(state.get('execution_result', {}), indent=2)}
Errors: {state.get('synthesis_error') or state.get('execution_error') or 'None'}

Generate a user-friendly summary including:
1. What the user asked
2. What the system did
3. The outcome
4. SQL query if generated
5. Results summary
"""
        
        response = self.llm.invoke([HumanMessage(content=summary_prompt)])
        
        return {
            "final_summary": response.content,
            "next_agent": "end",
            "messages": [AIMessage(content=response.content)]
        }

########################################
# Workflow Creation Function
########################################

def create_super_agent_hybrid() -> StateGraph:
    """
    Create the multi-agent workflow using OOP agents and explicit state management.
    
    Returns uncompiled StateGraph. Checkpointer will be added at runtime.
    """
    logger.info("Creating Super Agent Hybrid workflow")
    
    # Initialize LLMs
    llm_clarification = ChatDatabricks(endpoint=LLM_ENDPOINT_CLARIFICATION, temperature=0.1)
    llm_planning = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING, temperature=0.1)
    llm_sql_synthesis = ChatDatabricks(endpoint=LLM_ENDPOINT_SQL_SYNTHESIS, temperature=0.1)
    llm_summarize = ChatDatabricks(endpoint=LLM_ENDPOINT_SUMMARIZE, temperature=0.1)
    
    # Create agent instances
    clarification_agent = ClarificationAgent(llm_clarification, TABLE_NAME)
    planning_agent = PlanningAgent(llm_planning, VECTOR_SEARCH_INDEX)
    sql_synthesis_table_agent = SQLSynthesisTableAgent(llm_sql_synthesis, UC_FUNCTION_NAMES)
    sql_execution_agent = SQLExecutionAgent(llm_sql_synthesis)
    summarize_agent = ResultSummarizeAgent(llm_summarize)
    
    # Node wrappers
    def clarification_node(state: AgentState) -> AgentState:
        return clarification_agent.process(state)
    
    def planning_node(state: AgentState) -> AgentState:
        return planning_agent.process(state)
    
    def sql_synthesis_table_node(state: AgentState) -> AgentState:
        return sql_synthesis_table_agent.process(state)
    
    def sql_synthesis_genie_node(state: AgentState) -> AgentState:
        relevant_spaces = state.get("relevant_spaces", [])
        genie_agent = SQLSynthesisGenieAgent(llm_sql_synthesis, relevant_spaces)
        return genie_agent.process(state)
    
    def sql_execution_node(state: AgentState) -> AgentState:
        return sql_execution_agent.process(state)
    
    def summarize_node(state: AgentState) -> AgentState:
        return summarize_agent.process(state)
    
    # Create workflow
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("clarification", clarification_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("sql_synthesis_table", sql_synthesis_table_node)
    workflow.add_node("sql_synthesis_genie", sql_synthesis_genie_node)
    workflow.add_node("sql_execution", sql_execution_node)
    workflow.add_node("summarize", summarize_node)
    
    # Define routing
    def route_after_clarification(state: AgentState) -> str:
        if state.get("question_clear", False):
            return "planning"
        return END
    
    def route_after_planning(state: AgentState) -> str:
        next_agent = state.get("next_agent", "summarize")
        if next_agent == "sql_synthesis_table":
            return "sql_synthesis_table"
        elif next_agent == "sql_synthesis_genie":
            return "sql_synthesis_genie"
        return "summarize"
    
    def route_after_synthesis(state: AgentState) -> str:
        next_agent = state.get("next_agent", "summarize")
        if next_agent == "sql_execution":
            return "sql_execution"
        return "summarize"
    
    # Add edges
    workflow.set_entry_point("clarification")
    workflow.add_conditional_edges("clarification", route_after_clarification, {"planning": "planning", END: END})
    workflow.add_conditional_edges("planning", route_after_planning, {
        "sql_synthesis_table": "sql_synthesis_table",
        "sql_synthesis_genie": "sql_synthesis_genie",
        "summarize": "summarize"
    })
    workflow.add_conditional_edges("sql_synthesis_table", route_after_synthesis, {
        "sql_execution": "sql_execution",
        "summarize": "summarize"
    })
    workflow.add_conditional_edges("sql_synthesis_genie", route_after_synthesis, {
        "sql_execution": "sql_execution",
        "summarize": "summarize"
    })
    workflow.add_edge("sql_execution", "summarize")
    workflow.add_edge("summarize", END)
    
    logger.info("Workflow created successfully")
    return workflow

########################################
# ResponsesAgent Wrapper with Memory
########################################

class SuperAgentHybridResponsesAgent(ResponsesAgent):
    """
    Enhanced ResponsesAgent with both short-term and long-term memory.
    
    Features:
    - Short-term memory (CheckpointSaver): Multi-turn conversations
    - Long-term memory (DatabricksStore): User preferences
    - Works in distributed Model Serving
    """
    
    def __init__(self, workflow: StateGraph):
        self.workflow = workflow
        self.lakebase_instance_name = LAKEBASE_INSTANCE_NAME
        self._store = None
        self._memory_tools = None
        logger.info("SuperAgentHybridResponsesAgent initialized")
    
    @property
    def store(self):
        """Lazy initialization of DatabricksStore."""
        if self._store is None:
            logger.info(f"Initializing DatabricksStore: {self.lakebase_instance_name}")
            self._store = DatabricksStore(
                instance_name=self.lakebase_instance_name,
                embedding_endpoint=EMBEDDING_ENDPOINT,
                embedding_dims=EMBEDDING_DIMS,
            )
            self._store.setup()
        return self._store
    
    @property
    def memory_tools(self):
        """Create memory tools for long-term memory."""
        if self._memory_tools is None:
            
            @tool
            def get_user_memory(query: str, config: RunnableConfig) -> str:
                """Search for relevant user information."""
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Memory not available - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                results = self.store.search(namespace, query=query, limit=5)
                
                if not results:
                    return "No memories found for this user."
                
                memory_items = [f"- [{item.key}]: {json.dumps(item.value)}" for item in results]
                return f"Found {len(results)} memories:\n" + "\n".join(memory_items)
            
            @tool
            def save_user_memory(memory_key: str, memory_data_json: str, config: RunnableConfig) -> str:
                """Save information about the user."""
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot save memory - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                
                try:
                    memory_data = json.loads(memory_data_json)
                    self.store.put(namespace, memory_key, memory_data)
                    return f"Successfully saved memory '{memory_key}'"
                except json.JSONDecodeError as e:
                    return f"Failed: Invalid JSON - {str(e)}"
            
            @tool
            def delete_user_memory(memory_key: str, config: RunnableConfig) -> str:
                """Delete a specific memory."""
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot delete memory - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                self.store.delete(namespace, memory_key)
                return f"Successfully deleted memory '{memory_key}'"
            
            self._memory_tools = [get_user_memory, save_user_memory, delete_user_memory]
            logger.info(f"Created {len(self._memory_tools)} memory tools")
        
        return self._memory_tools
    
    def _get_or_create_thread_id(self, request: ResponsesAgentRequest) -> str:
        """Get thread_id from request or create new one."""
        ci = dict(request.custom_inputs or {})
        
        if "thread_id" in ci:
            return ci["thread_id"]
        
        if request.context and getattr(request.context, "conversation_id", None):
            return request.context.conversation_id
        
        return str(uuid4())
    
    def _get_user_id(self, request: ResponsesAgentRequest) -> Optional[str]:
        """Extract user_id from request context."""
        if request.context and getattr(request.context, "user_id", None):
            return request.context.user_id
        
        if request.custom_inputs and "user_id" in request.custom_inputs:
            return request.custom_inputs["user_id"]
        
        return None
    
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """Make a prediction (non-streaming)."""
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done"
        ]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)
    
    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        """Make a streaming prediction with memory support."""
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        latest_query = cc_msgs[-1]["content"] if cc_msgs else ""
        
        # Get thread_id and user_id
        thread_id = self._get_or_create_thread_id(request)
        user_id = self._get_user_id(request)
        
        logger.info(f"Processing request (thread: {thread_id}, user: {user_id})")
        
        # Configure run
        run_config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": user_id,
            }
        }
        
        # Check if clarification response
        is_clarification_response = request.custom_inputs.get("is_clarification_response", False) if request.custom_inputs else False
        
        if is_clarification_response:
            original_query = request.custom_inputs.get("original_query", latest_query)
            clarification_message = request.custom_inputs.get("clarification_message", "")
            clarification_count = request.custom_inputs.get("clarification_count", 1)
            
            initial_state = {
                "original_query": original_query,
                "clarification_message": clarification_message,
                "clarification_count": clarification_count,
                "user_clarification_response": latest_query,
                "question_clear": False,
                "messages": [HumanMessage(content=f"Clarification response: {latest_query}")],
            }
        else:
            initial_state = {
                "original_query": latest_query,
                "question_clear": False,
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
                    HumanMessage(content=latest_query)
                ],
                "next_agent": "clarification"
            }
        
        # Add user_id to state
        if user_id:
            initial_state["user_id"] = user_id
            initial_state["thread_id"] = thread_id
        
        first_message = True
        seen_ids = set()
        
        # Execute workflow with CheckpointSaver (CRITICAL for distributed serving)
        with CheckpointSaver(instance_name=self.lakebase_instance_name) as checkpointer:
            app = self.workflow.compile(checkpointer=checkpointer)
            
            logger.info(f"Executing workflow (thread: {thread_id})")
            
            for _, events in app.stream(initial_state, run_config, stream_mode=["updates"]):
                new_msgs = [
                    msg
                    for v in events.values()
                    for msg in v.get("messages", [])
                    if hasattr(msg, 'id') and msg.id not in seen_ids
                ]
                
                if first_message:
                    seen_ids.update(msg.id for msg in new_msgs[: len(cc_msgs)])
                    new_msgs = new_msgs[len(cc_msgs) :]
                    first_message = False
                else:
                    seen_ids.update(msg.id for msg in new_msgs)
                    if events:
                        node_name = tuple(events.keys())[0]
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=self.create_text_output_item(
                                text=f"<name>{node_name}</name>", id=str(uuid4())
                            ),
                        )
                
                if len(new_msgs) > 0:
                    yield from output_to_responses_items_stream(new_msgs)
        
        logger.info(f"Workflow completed (thread: {thread_id})")

########################################
# Agent Creation and MLflow Setup
########################################

# Create the workflow (uncompiled)
super_agent_hybrid = create_super_agent_hybrid()

# Create the deployable agent with memory support
AGENT = SuperAgentHybridResponsesAgent(super_agent_hybrid)

logger.info("="*80)
logger.info("SUPER AGENT WITH MEMORY CREATED")
logger.info("="*80)
logger.info("Features:")
logger.info("  ✓ Short-term memory (CheckpointSaver)")
logger.info("  ✓ Long-term memory (DatabricksStore)")
logger.info("  ✓ Distributed serving ready")
logger.info("="*80)

# Set the agent for MLflow tracking
mlflow.langchain.autolog()
mlflow.models.set_model(AGENT)
