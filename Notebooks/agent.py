"""
Super Agent (Hybrid Architecture) - Multi-Agent System Orchestrator

This notebook implements a hybrid architecture combining:
- OOP agent classes (from agent.py) for modularity and reusability
- Explicit state management (from Super_Agent.py) for observability and debugging

Architecture Benefits:
1. ✅ OOP modularity for agent logic - Easy to test and maintain
2. ✅ Explicit state for observability - Clear debugging and monitoring
3. ✅ Best practices from both approaches
4. ✅ Production-ready with rapid development capabilities

Components:
1. Clarification Agent - Validates query clarity (OOP class)
2. Planning Agent - Creates execution plan and identifies relevant spaces (OOP class)
3. SQL Synthesis Agent (Table Route) - Generates SQL using UC tools (OOP class)
4. SQL Synthesis Agent (Genie Route) - Generates SQL using Genie agents (OOP class)
5. SQL Execution Agent - Executes SQL and returns results (OOP class)

The Super Agent uses LangGraph with explicit state tracking for orchestration.
"""

import json
from typing import Dict, List, Optional, Any, Annotated, Literal, Generator
from typing_extensions import TypedDict
import operator
from uuid import uuid4
import re
from functools import partial
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
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AIMessageChunk
from langchain_core.runnables import Runnable, RunnableLambda, RunnableConfig
from langchain_core.tools import tool
import mlflow
import logging

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

print("✓ All dependencies imported successfully (including memory support)")
def query_delta_table(table_name: str, filter_field: str, filter_value: str, select_fields: List[str] = None) -> Any:
    """
    Query a delta table with a filter condition.
    
    Args:
        table_name: Full table name (catalog.schema.table)
        filter_field: Field name to filter on
        filter_value: Value to filter by
        select_fields: List of fields to select (None = all fields)
    
    Returns:
        Spark DataFrame with query results
    """
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()

    if select_fields:
        fields_str = ", ".join(select_fields)
    else:
        fields_str = "*"
    
    df = spark.sql(f"""
        SELECT {fields_str}
        FROM {table_name}
        WHERE {filter_field} = '{filter_value}'
    """)
    
    return df

def load_space_context(table_name: str) -> Dict[str, str]:
    """
    Load space context from Delta table.
    Called fresh on each request - no caching for dynamic refresh.
    
    Args:
        table_name: Full table name (catalog.schema.table)
        
    Returns:
        Dictionary mapping space_id to searchable_content
    """
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    
    df = spark.sql(f"""
        SELECT space_id, searchable_content
        FROM {table_name}
        WHERE chunk_type = 'space_summary'
    """)
    
    context = {row["space_id"]: row["searchable_content"] 
               for row in df.collect()}
    
    print(f"✓ Loaded {len(context)} Genie spaces for context")
    return context

# Note: Context is now loaded dynamically in clarification_node
# This allows refresh without model redeployment
class AgentState(TypedDict):
    """
    Explicit state that flows through the multi-agent system.
    This provides full observability and makes debugging easier.
    """
    # Input
    original_query: str
    
    # Clarification
    question_clear: bool
    clarification_needed: Optional[str]
    clarification_options: Optional[List[str]]
    clarification_count: Optional[int]  # Track clarification attempts (max 1)
    user_clarification_response: Optional[str]  # User's response to clarification
    clarification_message: Optional[str]  # The clarification question asked by agent
    combined_query_context: Optional[str]  # Combined context: original + clarification + response
    
    # Planning
    plan: Optional[Dict[str, Any]]
    sub_questions: Optional[List[str]]
    requires_multiple_spaces: Optional[bool]
    relevant_space_ids: Optional[List[str]]
    relevant_spaces: Optional[List[Dict[str, Any]]]
    vector_search_relevant_spaces_info: Optional[List[Dict[str, str]]]
    requires_join: Optional[bool]
    join_strategy: Optional[str]  # "table_route" or "genie_route"
    execution_plan: Optional[str]
    genie_route_plan: Optional[Dict[str, str]]
    
    # SQL Synthesis
    sql_query: Optional[str]
    sql_synthesis_explanation: Optional[str]  # Agent's explanation/reasoning
    synthesis_error: Optional[str]
    
    # Execution
    execution_result: Optional[Dict[str, Any]]
    execution_error: Optional[str]
    
    # Summary
    final_summary: Optional[str]  # Natural language summary of the workflow execution
    
    # State Management (NEW - for distributed serving and long-term memory)
    user_id: Optional[str]  # User identifier for long-term memory
    thread_id: Optional[str]  # Thread identifier for short-term memory
    user_preferences: Optional[Dict]  # User preferences loaded from long-term memory
    
    # Control flow
    next_agent: Optional[str]
    messages: Annotated[List, operator.add]
    
print("✓ Agent State defined with explicit fields for observability")
class ClarificationAgent:
    """
    Agent responsible for checking query clarity.
    
    Hybrid approach: Can accept context directly (for testing) or load from table (for production).
    
    Usage:
        # Testing: Pass mock context
        agent = ClarificationAgent(llm, {"space1": "mock data"})
        
        # Production: Load from table
        agent = ClarificationAgent.from_table(llm, TABLE_NAME)
    """
    
    def __init__(self, llm: Runnable, context: Dict[str, str]):
        """
        Initialize with context directly.
        
        Args:
            llm: Language model for clarity checking
            context: Dictionary mapping space_id to searchable_content
        """
        self.llm = llm
        self.context = context
        self.name = "Clarification"
    
    @classmethod
    def from_table(cls, llm: Runnable, table_name: str):
        """
        Factory method to create agent by loading context from Delta table.
        Loads fresh context on each call - no caching for dynamic refresh.
        
        Args:
            llm: Language model for clarity checking
            table_name: Full table name (catalog.schema.table)
            
        Returns:
            ClarificationAgent instance with fresh context
        """
        context = load_space_context(table_name)
        return cls(llm, context)
    
    def check_clarity(self, query: str, clarification_count: int = 0) -> Dict[str, Any]:
        """
        Check if the user query is clear and answerable.
        
        Args:
            query: User's question
            clarification_count: Number of times clarification has been requested
            
        Returns:
            Dictionary with clarity analysis
        """
        # If already clarified once, don't ask again - proceed with best effort
        if clarification_count >= 1:
            print("⚠ Max clarification attempts reached (1) - proceeding with query as-is")
            return {"question_clear": True}
        
        clarity_prompt = f"""
Analyze the following question for clarity and specificity based on the context.

IMPORTANT: Only mark as unclear if the question is TRULY VAGUE or IMPOSSIBLE to answer.
Be lenient - if the question can reasonably be answered with the available data, mark it as clear.

Question: {query}

Context (Available Data Sources):
{json.dumps(self.context, indent=2)}

Determine if:
1. The question is clear and answerable as-is (BE LENIENT - default to TRUE)
2. The question is TRULY VAGUE and needs critical clarification (ONLY if essential information is missing)
3. If the question mentions any metrics/dimensions/filters that can be mapped to available data with certain confidence, mark it as CLEAR; otherwise, mark it as UNCLEAR and ask for clarification.


If clarification is truly needed, provide:
- A brief explanation of what's critically unclear
- 2-3 specific clarification options the user can choose from

Return your analysis as JSON:
{{
    "question_clear": true/false,
    "clarification_needed": "explanation if unclear (null if clear)",
    "clarification_options": ["option 1", "option 2", "option 3"] or null
}}

Only return valid JSON, no explanations.
"""
        
        response = self.llm.invoke(clarity_prompt)
        content = response.content.strip()
        
        # Use regex to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # No code blocks, assume entire content is JSON
            json_str = content
        
        # Remove any trailing commas before ] or }
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        try:
            clarity_result = json.loads(json_str)
            return clarity_result
        except json.JSONDecodeError as e:
            print(f"⚠ Clarification JSON parsing error at position {e.pos}: {e.msg}")
            print(f"Raw content (first 300 chars): {content[:300]}")
            print(f"Defaulting to question_clear=True")
            return {"question_clear": True}
    
    def __call__(self, query: str, clarification_count: int = 0) -> Dict[str, Any]:
        """Make agent callable for easy invocation."""
        return self.check_clarity(query, clarification_count)

print("✓ ClarificationAgent class defined")
class PlanningAgent:
    """
    Agent responsible for query analysis and execution planning.
    
    OOP design with vector search integration.
    """
    
    def __init__(self, llm: Runnable, vector_search_index: str):
        self.llm = llm
        self.vector_search_index = vector_search_index
        self.name = "Planning"
    
    def search_relevant_spaces(self, query: str, num_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search for relevant Genie spaces using vector search.
        
        Args:
            query: User's question
            num_results: Number of results to return
            
        Returns:
            List of relevant space dictionaries
        """
        vs_tool = VectorSearchRetrieverTool(
            index_name=self.vector_search_index,
            num_results=num_results,
            columns=["space_id", "space_title", "searchable_content"],
            filters={"chunk_type": "space_summary"},
            query_type="ANN",
            include_metadata=True,
            include_score=True
        )
        
        docs = vs_tool.invoke({"query": query})
        
        relevant_spaces = []
        for doc in docs:
            print(doc)
            relevant_spaces.append({
                "space_id": doc.metadata.get("space_id", ""),
                "space_title": doc.metadata.get("space_title", ""),
                "searchable_content": doc.page_content,
                "score": doc.metadata.get("score", 0.0)
            })
        
        return relevant_spaces
    
    def create_execution_plan(
        self, 
        query: str, 
        relevant_spaces: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Create execution plan based on query and relevant spaces.
        
        Args:
            query: User's question
            relevant_spaces: List of relevant Genie spaces
            
        Returns:
            Dictionary with execution plan
        """
        planning_prompt = f"""
You are a query planning expert. Analyze the following question and create an execution plan.

Question: {query}

Potentially relevant Genie spaces:
{json.dumps(relevant_spaces, indent=2)}

Break down the question and determine:
1. What are the sub-questions or analytical components?
2. How many Genie spaces are needed to answer completely? (List their space_ids)
3. If multiple spaces are needed, do we need to JOIN data across them? Reasoning whether the sub-questions are totally independent without joining need.
    - JOIN needed: E.g., "How many active plan members over 50 are on Lexapro?" requires joining member data with pharmacy claims.
    - No need for JOIN: E.g., "How many active plan members over 50? How much total cost for all Lexapro claims?" - Two independent questions.
4. If JOIN is needed, what's the best strategy:
    - "table_route": Directly synthesize SQL across multiple tables
    - "genie_route": Query each Genie Space Agent separately, then combine SQL queries
    - If user explicitly asks for "genie_route", use it; otherwise, use "table_route"
    - always populate the join_strategy field in the JSON output.
5. Execution plan: A brief description of how to execute the plan.
    - For genie_route: Return "genie_route_plan": {{'space_id_1':'partial_question_1', 'space_id_2':'partial_question_2'}}
    - For table_route: Return "genie_route_plan": null
    - Each partial_question should be similar to original but scoped to that space
    - Add "Please limit to top 10 rows" to each partial question

Return your analysis as JSON:
{{
    "original_query": "{query}",
    "vector_search_relevant_spaces_info":{[{sp['space_id']: sp['space_title']} for sp in relevant_spaces]},
    "question_clear": true,
    "sub_questions": ["sub-question 1", "sub-question 2", ...],
    "requires_multiple_spaces": true/false,
    "relevant_space_ids": ["space_id_1", "space_id_2", ...],
    "requires_join": true/false,
    "join_strategy": "table_route" or "genie_route",
    "execution_plan": "Brief description of execution plan",
    "genie_route_plan": {{'space_id_1':'partial_question_1', 'space_id_2':'partial_question_2'}} or null
}}

Only return valid JSON, no explanations.
"""
        
        response = self.llm.invoke(planning_prompt)
        content = response.content.strip()
        
        # Use regex to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # No code blocks, assume entire content is JSON
            json_str = content
        
        # Remove any trailing commas before ] or }
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
        try:
            plan_result = json.loads(json_str)
            return plan_result
        except json.JSONDecodeError as e:
            print(f"❌ Planning JSON parsing error at position {e.pos}: {e.msg}")
            print(f"Raw content (first 500 chars):\n{content[:500]}")
            print(f"Cleaned JSON (first 500 chars):\n{json_str[:500]}")
            
            # Try one more time with even more aggressive cleaning
            try:
                # Remove comments
                json_str_clean = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
                # Remove trailing commas again
                json_str_clean = re.sub(r',(\s*[}\]])', r'\1', json_str_clean)
                plan_result = json.loads(json_str_clean)
                print("✓ Successfully parsed JSON after aggressive cleaning")
                return plan_result
            except:
                raise e  # Re-raise original error
    
    def __call__(self, query: str) -> Dict[str, Any]:
        """
        Analyze query and create execution plan.
        
        Returns:
            Complete execution plan with relevant spaces
        """
        # Search for relevant spaces
        relevant_spaces = self.search_relevant_spaces(query)
        
        # Create execution plan
        plan = self.create_execution_plan(query, relevant_spaces)
        
        return plan

print("✓ PlanningAgent class defined")
class SQLSynthesisTableAgent:
    """
    Agent responsible for fast SQL synthesis using UC function tools.
    
    OOP design with UC toolkit integration.
    """
    
    def __init__(
        self, 
        llm: Runnable, 
        catalog: str, 
        schema: str
    ):
        self.llm = llm
        self.catalog = catalog
        self.schema = schema
        self.name = "SQLSynthesisTable"
        
        # Initialize UC Function Client
        client = DatabricksFunctionClient()
        set_uc_function_client(client)
        
        # Create UC Function Toolkit
        uc_function_names = [
            f"{catalog}.{schema}.get_space_summary",
            f"{catalog}.{schema}.get_table_overview",
            f"{catalog}.{schema}.get_column_detail",
            f"{catalog}.{schema}.get_space_details",
        ]
        
        self.uc_toolkit = UCFunctionToolkit(function_names=uc_function_names)
        self.tools = self.uc_toolkit.tools
        
        # Create SQL synthesis agent with tools
        self.agent = create_agent(
            model=llm,
            tools=self.tools,
            system_prompt=(
                "You are a specialized SQL synthesis agent in a multi-agent system.\n\n"
                "ROLE: You receive execution plans from the planning agent and generate SQL queries.\n\n"

                "## WORKFLOW:\n"
                "1. Review the execution plan and provided metadata\n"
                "2. If metadata is sufficient → Generate SQL immediately\n"
                "3. If insufficient, call UC function tools in this order:\n"
                "   a) get_space_summary for space information\n"
                "   b) get_table_overview for table schemas\n"
                "   c) get_column_detail for specific columns\n"
                "   d) get_space_details ONLY as last resort (token intensive)\n"
                "4. At last, if you still cannot find enough metadata in relevant spaces provided, dont stuck there. Expand the searching scope to all spaces mentioned in the execution plan's 'vector_search_relevant_spaces_info' field. Extract the space_id from 'vector_search_relevant_spaces_info'. \n"
                "5. Generate complete, executable SQL\n\n"

                "## UC FUNCTION USAGE:\n"
                "- Pass arguments as JSON array strings: '[\"space_id_1\", \"space_id_2\"]' or 'null'\n"
                "- Only query spaces from execution plan's relevant_space_ids\n"
                "- Use minimal sufficiency: only query what you need\n\n"

                "## OUTPUT REQUIREMENTS:\n"
                "- Generate complete, executable SQL with:\n"
                "  * Proper JOINs based on execution plan\n"
                "  * WHERE clauses for filtering\n"
                "  * Appropriate aggregations\n"
                "  * Clear column aliases\n"
                "  * Always use real column names, never make up ones\n"
                "- Return your response with:\n"
                "1. Your explanations; If SQL cannot be generated, explain what metadata is missing\n"
                "2. The final SQL query in a ```sql code block\n\n"
            )
        )
    
    def synthesize_sql(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synthesize SQL query based on execution plan.
        
        Args:
            plan: Execution plan from planning agent
            
        Returns:
            Dictionary with:
            - sql: str - Extracted SQL query (None if cannot generate)
            - explanation: str - Agent's explanation/reasoning
            - has_sql: bool - Whether SQL was successfully extracted
        """
        # # Prepare plan summary for agent
        # plan_summary = {
        #     "original_query": plan.get("original_query", ""),
        #     "vector_search_relevant_spaces_info": plan.get("vector_search_relevant_spaces_info", []),
        #     "relevant_space_ids": plan.get("relevant_space_ids", []),
        #     "execution_plan": plan.get("execution_plan", ""),
        #     "requires_join": plan.get("requires_join", False),
        #     "sub_questions": plan.get("sub_questions", [])
        # }
        plan_result = plan
        # Invoke agent
        agent_message = {
            "messages": [
                {
                    "role": "user",
                    "content": f"""
Generate a SQL query to answer the question according to the Query Plan:
{json.dumps(plan_result, indent=2)}

Use your available UC function tools to gather metadata intelligently.
"""
                }
            ]
        }
        
        result = self.agent.invoke(agent_message)
        
        # Extract SQL and explanation from response
        if result and "messages" in result:
            final_content = result["messages"][-1].content
            original_content = final_content
            
            sql_query = None
            has_sql = False
            
            # Try to extract SQL from markdown if present
            if "```sql" in final_content.lower():
                sql_match = re.search(r'```sql\s*(.*?)\s*```', final_content, re.IGNORECASE | re.DOTALL)
                if sql_match:
                    sql_query = sql_match.group(1).strip()
                    has_sql = True
                    # Remove SQL block from content to get explanation
                    final_content = re.sub(r'```sql\s*.*?\s*```', '', final_content, flags=re.IGNORECASE | re.DOTALL)
            elif "```" in final_content:
                sql_match = re.search(r'```\s*(.*?)\s*```', final_content, re.DOTALL)
                if sql_match:
                    # Check if it looks like SQL
                    potential_sql = sql_match.group(1).strip()
                    if any(keyword in potential_sql.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'JOIN']):
                        sql_query = potential_sql
                        has_sql = True
                        # Remove SQL block from content to get explanation
                        final_content = re.sub(r'```\s*.*?\s*```', '', final_content, flags=re.DOTALL)
            
            # Clean up explanation
            explanation = final_content.strip()
            if not explanation:
                explanation = original_content if not has_sql else "SQL query generated successfully."
            
            return {
                "sql": sql_query,
                "explanation": explanation,
                "has_sql": has_sql
            }
        else:
            raise Exception("No response from agent")
    
    def __call__(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Make agent callable."""
        return self.synthesize_sql(plan)

print("✓ SQLSynthesisTableAgent class defined")
class SQLSynthesisGenieAgent:
    """
    Agent responsible for Genie Route SQL synthesis using Genie agents as tools.
    
    Uses LangChain agent pattern where Genie agents are wrapped as tools.
    The agent orchestrates tool calling, retries, and SQL synthesis autonomously.
    
    OOP design with Genie agent-as-tools integration.
    Optimized to only create Genie agents for relevant spaces (not all spaces).
    """
    
    def __init__(self, llm: Runnable, relevant_spaces: List[Dict[str, Any]]):
        """
        Initialize SQL Synthesis Genie Agent with tool-calling pattern.
        
        Args:
            llm: Language model for SQL synthesis
            relevant_spaces: List of relevant spaces from PlanningAgent's Vector Search.
                            Each dict should have: space_id, space_title, searchable_content
        """
        self.llm = llm
        self.relevant_spaces = relevant_spaces
        self.name = "SQLSynthesisGenie"
        
        # Create Genie agents and their tool representations
        self.genie_agents = []
        self.genie_agent_tools = []
        self._create_genie_agent_tools()
        
        # Create SQL synthesis agent with Genie agent tools
        self.sql_synthesis_agent = self._create_sql_synthesis_agent()
    
    def _create_genie_agent_tools(self):
        """
        Create Genie agents as tools only for relevant spaces.
        Uses RunnableLambda wrapper pattern to avoid closure issues.
        
        Pattern copied from test_uc_functions.py lines 1283-1318
        """
        def enforce_limit(messages, n=5):
            last = messages[-1] if messages else {"content": ""}
            content = last.get("content", "") if isinstance(last, dict) else last.content
            return f"{content}\n\nPlease limit the result to at most {n} rows."
        
        print(f"  Creating Genie agent tools for {len(self.relevant_spaces)} relevant spaces...")
        
        for space in self.relevant_spaces:
            space_id = space.get("space_id")
            space_title = space.get("space_title", space_id)
            searchable_content = space.get("searchable_content", "")
            
            if not space_id:
                print(f"  ⚠ Warning: Space missing space_id, skipping: {space}")
                continue
            
            genie_agent_name = f"Genie_{space_title}"
            description = searchable_content
            
            # Create Genie agent
            genie_agent = GenieAgent(
                genie_space_id=space_id,
                genie_agent_name=genie_agent_name,
                description=description,
                include_context=True,
                message_processor=lambda msgs: enforce_limit(msgs, n=5)
            )
            self.genie_agents.append(genie_agent)
            
            # Wrap the agent call in a function that only takes a string argument
            # This function also returns a function to avoid closure issues
            def make_agent_invoker(agent):
                return lambda question: agent.invoke(
                    {"messages": [{"role": "user", "content": question}]}
                )
            
            runnable = RunnableLambda(make_agent_invoker(genie_agent))
            runnable.name = genie_agent_name
            runnable.description = description
            
            self.genie_agent_tools.append(
                runnable.as_tool(
                    name=genie_agent_name,
                    description=description,
                    arg_types={"question": str}
                )
            )
            
            print(f"  ✓ Created Genie agent tool: {genie_agent_name} ({space_id})")
    
    def _create_sql_synthesis_agent(self):
        """
        Create LangGraph SQL Synthesis Agent with Genie agent tools.
        
        Uses Databricks LangGraph SDK with create_agent pattern.
        Pattern copied from test_uc_functions.py lines 1375-1462
        """
        tools = []
        tools.extend(self.genie_agent_tools)
        
        print(f"✓ Created SQL Synthesis Agent with {len(tools)} Genie agent tools")
        
        # Create SQL Synthesis Agent (specialized for multi-agent system)
        sql_synthesis_agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=(
"""You are a SQL synthesis agent, which can take analysis plan, and route queries to the corresponding Genie Agent.
The Plan given to you is a JSON:
{
'original_query': 'The User's Question',
'vector_search_relevant_spaces_info': [{'space_id': 'space_id_1',
   'space_title': 'space_title_1'},
  {'space_id': 'space_id_2',
   'space_title': 'space_title_2'},
  {'space_id': 'space_id_3',
   'space_title': 'space_title_3'}],
"question_clear": true,
"sub_questions": ["sub-question 1", "sub-question 2", ...],
"requires_multiple_spaces": true/false,
"relevant_space_ids": ["space_id_1", "space_id_2", ...],
"requires_join": true/false,
"join_strategy": "table_route" or "genie_route" or null,
"execution_plan": "Brief description of execution plan",
"genie_route_plan": {'space_id_1':'partial_question_1', 'space_id_2':'partial_question_2', 'space_id_3':'partial_question_3', ...} or null,}

## Tool Calling Plan:
1. Under the key of 'genie_route_plan' in the JSON, extracting 'partial_question_1' and feed to the right Genie Agent tool of 'space_id_1' with the input as a string. 
2. Asynchronously send all other partial_questions to the corresponding Genie Agent tools accordingly.
3. You have access to all Genie Agents as tools given to you; locate the proper Genie Agent Tool by searching the 'space_id_1' in the tool's description. After each Genie agent returns result, only extract the SQL string from the Genie tool output JSON {"thinking": thinking, "sql": sql, "answer": answer}.
4. If you find you are still missing necessary analytical components (metrics, filters, dimensions, etc.) to assemble the final SQL, which might be due to some genie agent tool may not have the necessary information being assigned, try to leverage other most likely Genie agents to find the missing pieces.

## Disaster Recovery (DR) Plan:
1. If one Genie agent tool fail to generate a SQL query, allow retry AS IS only one time; 
2. If fail again, try to reframe the partial question 'partial_question_1' according to the error msg returned by the genie tool, e.g., genie tool may say "I dont have information for cost related information", you can remove those components in the 'partial_question_1' which doesn't exist in the genie tool. For example, if the genie tool "Genie_MemberBenefits" doesn't contain benefit cost related information, you can reframe the question by removing the cost-related components in the 'partial_question_1', generate 'partial_question_1_v2' and try again. Only try once;
3. If fail again, return response as is. 


## Overall SQL Synthesis Plan:
Then, you can combine all the SQL pieces into a single SQL query, and return the final SQL query.
OUTPUT REQUIREMENTS:
- Generate complete, executable SQL with:
  * Proper JOINs based on execution plan strategy
  * WHERE clauses for filtering
  * Appropriate aggregations
  * Clear column aliases
  * Always use real column name existed in the data, never make up one
- Return your response with:
1. Your explanation combining both the individual Genie thinking and your own reasoning
2. The final SQL query in a ```sql code block"""
            )
        )
        
        return sql_synthesis_agent
    
    def synthesize_sql(
        self, 
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Synthesize SQL using Genie agents (genie route) with autonomous tool calling.
        
        Args:
            plan: Complete plan dictionary from PlanningAgent containing:
                - original_query: Original user question
                - execution_plan: Execution plan description
                - genie_route_plan: Mapping of space_id to partial question
                - vector_search_relevant_spaces_info: List of relevant spaces
                - relevant_space_ids: List of relevant space IDs
                - requires_join: Whether join is needed
                - join_strategy: Join strategy (table_route/genie_route)
            
        Returns:
            Dictionary with:
            - sql: str - Combined SQL query (None if cannot generate)
            - explanation: str - Agent's explanation/reasoning
            - has_sql: bool - Whether SQL was successfully extracted
        """
        # Build the plan result JSON for the agent
        plan_result = plan
        
        # Create the message for the agent
        agent_message = {
            "messages": [
                {
                    "role": "user",
                    "content": f"""
Generate a SQL query to answer the question according to the Query Plan:
{json.dumps(plan_result, indent=2)}
"""
                }
            ]
        }
        
        print(f"\n{'='*80}")
        print("🤖 Invoking SQL Synthesis Agent with Genie Agent Tools...")
        print(f"{'='*80}")
        print(f"Plan: {json.dumps(plan_result, indent=2)}")
        print(f"{'='*80}\n")
        
        try:
            # Enable MLflow autologging for tracing
            mlflow.langchain.autolog()
            
            # Invoke the agent
            result = self.sql_synthesis_agent.invoke(agent_message)
            
            # Extract SQL from agent result
            # The agent returns {"messages": [...]}
            # Last message contains the final response
            final_message = result["messages"][-1]
            final_content = final_message.content.strip()
            
            print(f"\n{'='*80}")
            print("✅ SQL Synthesis Agent completed")
            print(f"{'='*80}")
            print(f"Result: {final_content[:500]}...")
            print(f"{'='*80}\n")
            
            # Extract SQL and explanation from the result
            sql_query = None
            has_sql = False
            explanation = final_content
            
            # Clean markdown if present and extract SQL
            if "```sql" in final_content.lower():
                sql_match = re.search(r'```sql\s*(.*?)\s*```', final_content, re.IGNORECASE | re.DOTALL)
                if sql_match:
                    sql_query = sql_match.group(1).strip()
                    has_sql = True
                    # Remove SQL block to get explanation
                    explanation = re.sub(r'```sql\s*.*?\s*```', '', final_content, flags=re.IGNORECASE | re.DOTALL)
            elif "```" in final_content:
                sql_match = re.search(r'```\s*(.*?)\s*```', final_content, re.DOTALL)
                if sql_match:
                    potential_sql = sql_match.group(1).strip()
                    if any(keyword in potential_sql.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'JOIN']):
                        sql_query = potential_sql
                        has_sql = True
                        # Remove SQL block to get explanation
                        explanation = re.sub(r'```\s*.*?\s*```', '', final_content, flags=re.DOTALL)
            else:
                # No markdown, check if the entire content is SQL
                if any(keyword in final_content.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'JOIN']):
                    sql_query = final_content
                    has_sql = True
                    explanation = "SQL query generated successfully by Genie agent tools."
            
            explanation = explanation.strip()
            if not explanation:
                explanation = final_content if not has_sql else "SQL query generated successfully by Genie agent tools."
            
            return {
                "sql": sql_query,
                "explanation": explanation,
                "has_sql": has_sql
            }
            
        except Exception as e:
            print(f"\n{'='*80}")
            print("❌ SQL Synthesis Agent failed")
            print(f"{'='*80}")
            print(f"Error: {str(e)}")
            print(f"{'='*80}\n")
            
            return {
                "sql": None,
                "explanation": f"SQL synthesis failed: {str(e)}",
                "has_sql": False
            }
    
    def __call__(
        self, 
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Make agent callable with plan dictionary."""
        return self.synthesize_sql(plan)

print("✓ SQLSynthesisGenieAgent class defined")
class SQLExecutionAgent:
    """
    Agent responsible for executing SQL queries.
    
    OOP design for clean execution logic.
    Synced with test_uc_functions.py implementation.
    """
    
    def __init__(self):
        self.name = "SQLExecution"
    
    def execute_sql(
        self, 
        sql_query: str, 
        max_rows: int = 100,
        return_format: str = "dict"
    ) -> Dict[str, Any]:
        """
        Execute SQL query on delta tables and return formatted results.
        
        Args:
            sql_query: Support two types: 
                1) The result from invoke the SQL synthesis agent (dict with messages)
                2) The SQL query string (can be raw SQL or contain markdown code blocks)
            max_rows: Maximum number of rows to return (default: 100)
            return_format: Format of the result - "dict", "json", or "markdown"
            
        Returns:
            Dictionary containing:
            - success: bool - Whether execution was successful
            - sql: str - The executed SQL query
            - result: Any - Query results in requested format
            - row_count: int - Number of rows returned
            - columns: List[str] - Column names
            - error: str - Error message if failed (optional)
        """
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        
        # Step 1: Extract SQL from agent result or markdown code blocks if present
        if sql_query and isinstance(sql_query, dict) and "messages" in sql_query:
            sql_query = sql_query["messages"][-1].content
        
        extracted_sql = sql_query.strip()
        
        if "```sql" in extracted_sql.lower():
            # Extract content between ```sql and ```
            sql_match = re.search(r'```sql\s*(.*?)\s*```', extracted_sql, re.IGNORECASE | re.DOTALL)
            if sql_match:
                extracted_sql = sql_match.group(1).strip()
        elif "```" in extracted_sql:
            # Extract any code block
            sql_match = re.search(r'```\s*(.*?)\s*```', extracted_sql, re.DOTALL)
            if sql_match:
                extracted_sql = sql_match.group(1).strip()
        
        # Step 2: Add LIMIT clause if not present (for safety)
        if "limit" not in extracted_sql.lower():
            extracted_sql = f"{extracted_sql.rstrip(';')} LIMIT {max_rows}"
        
        try:
            # Step 3: Execute the SQL query
            print(f"\n{'='*80}")
            print("🔍 EXECUTING SQL QUERY")
            print(f"{'='*80}")
            print(f"SQL:\n{extracted_sql}")
            print(f"{'='*80}\n")
            
            df = spark.sql(extracted_sql)
            
            # Step 4: Collect results
            results_list = df.collect()
            row_count = len(results_list)
            columns = df.columns
            
            print(f"✅ Query executed successfully!")
            print(f"📊 Rows returned: {row_count}")
            print(f"📋 Columns: {', '.join(columns)}\n")
            
            # Step 5: Format results based on return_format
            if return_format == "json":
                result_data = df.toJSON().collect()
            elif return_format == "markdown":
                # Create markdown table
                pandas_df = df.toPandas()
                result_data = pandas_df.to_markdown(index=False)
            else:  # dict (default)
                result_data = [row.asDict() for row in results_list]
            
            # Step 7: Display preview
            print(f"{'='*80}")
            print("📄 RESULTS PREVIEW (first 10 rows)")
            print(f"{'='*80}")
            df.show(n=min(10, row_count), truncate=False)
            print(f"{'='*80}\n")
            
            return {
                "success": True,
                "sql": extracted_sql,
                "result": result_data,
                "row_count": row_count,
                "columns": columns,
            }
            
        except Exception as e:
            # Step 8: Handle errors
            error_msg = str(e)
            print(f"\n{'='*80}")
            print("❌ SQL EXECUTION FAILED")
            print(f"{'='*80}")
            print(f"Error: {error_msg}")
            print(f"{'='*80}\n")
            
            return {
                "success": False,
                "sql": extracted_sql,
                "result": None,
                "row_count": 0,
                "columns": [],
                "error": error_msg
            }
    
    def __call__(self, sql_query: str, max_rows: int = 100, return_format: str = "dict") -> Dict[str, Any]:
        """Make agent callable."""
        return self.execute_sql(sql_query, max_rows, return_format)

print("✓ SQLExecutionAgent class defined")
class ResultSummarizeAgent:
    """
    Agent responsible for generating a final summary of the workflow execution.
    
    Analyzes the entire workflow state and produces a natural language summary
    of what was accomplished, whether successful or not.
    
    OOP design for clean summarization logic.
    """
    
    def __init__(self, llm: Runnable):
        self.name = "ResultSummarize"
        self.llm = llm
    
    def generate_summary(self, state: AgentState) -> str:
        """
        Generate a natural language summary of the workflow execution.
        
        Args:
            state: The complete workflow state
            
        Returns:
            String containing natural language summary
        """
        # Build context from state
        summary_prompt = self._build_summary_prompt(state)
        
        # Invoke LLM to generate summary
        response = self.llm.invoke(summary_prompt)
        summary = response.content.strip()
        
        return summary
    
    def _build_summary_prompt(self, state: AgentState) -> str:
        """Build the prompt for summary generation based on state."""
        
        original_query = state.get('original_query', 'N/A')
        question_clear = state.get('question_clear', False)
        clarification_needed = state.get('clarification_needed')
        execution_plan = state.get('execution_plan')
        join_strategy = state.get('join_strategy')
        sql_query = state.get('sql_query')
        sql_explanation = state.get('sql_synthesis_explanation')
        exec_result = state.get('execution_result', {})
        synthesis_error = state.get('synthesis_error')
        execution_error = state.get('execution_error')
        
        prompt = f"""You are a result summarization agent. Generate a concise, natural language summary of what this multi-agent workflow accomplished.

**Original User Query:** {original_query}

**Workflow Execution Details:**

"""
        
        # Add clarification info
        if not question_clear:
            prompt += f"""**Status:** Query needs clarification
**Clarification Needed:** {clarification_needed}
**Summary:** The query was too vague or ambiguous. Requested user clarification before proceeding.
"""
        else:
            # Add planning info
            if execution_plan:
                prompt += f"""**Planning:** {execution_plan}
**Strategy:** {join_strategy or 'N/A'}

"""
            
            # Add SQL synthesis info
            if sql_query:
                prompt += f"""**SQL Generation:** ✅ Successful
**SQL Query:** 
```sql
{sql_query}
```

"""
                if sql_explanation:
                    prompt += f"""**SQL Synthesis Explanation:** {sql_explanation[:2000]}{'...' if len(sql_explanation) > 2000 else ''}

"""
                
                # Add execution info
                if exec_result.get('success'):
                    row_count = exec_result.get('row_count', 0)
                    columns = exec_result.get('columns', [])
                    result = exec_result.get('result', [])
                    prompt += f"""**Execution:** ✅ Successful
**Rows:** {row_count} rows returned
**Columns:** {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}

**Result:** {json.dumps(result, indent=2)}
"""
                elif execution_error:
                    prompt += f"""**Execution:** ❌ Failed
**Error:** {execution_error}

"""
            elif synthesis_error:
                prompt += f"""**SQL Generation:** ❌ Failed
**Error:** {synthesis_error}
**Explanation:** {sql_explanation or 'N/A'}

"""
        
        prompt += """
**Task:** Generate a detailed summary in natural language that:
1. Describes what the user asked for
2. Explains what the system did (planning, SQL generation, execution)
3. States the outcome (success with X rows, error, needs clarification, etc.)
4. print out SQL synthesis explanation if any SQL was generated
5. print out SQL if any SQL was generated; make it the code block
6. print out the result itself (like a table).


Keep it concise and user-friendly. 
"""
        
        return prompt
    
    def __call__(self, state: AgentState) -> str:
        """Make agent callable."""
        return self.generate_summary(state)

print("✓ ResultSummarizeAgent class defined")
def clarification_node(state: AgentState) -> AgentState:
    """
    Clarification node wrapping ClarificationAgent class.
    Combines OOP modularity with explicit state management.
    
    Handles up to 1 clarification request. If user provides clarification,
    incorporates it and proceeds to planning.
    
    IMPORTANT: This node COMBINES context instead of overwriting:
    - Preserves original_query unchanged
    - Stores clarification_message separately
    - Stores user_clarification_response separately
    - Creates combined_query_context for planning agent
    """
    print("\n" + "="*80)
    print("🔍 CLARIFICATION AGENT")
    print("="*80)
    
    # Initialize clarification count if not present
    clarification_count = state.get("clarification_count", 0)
    
    # Check if this is a user response to a previous clarification request
    user_response = state.get("user_clarification_response")
    if user_response and clarification_count > 0:
        print("✓ User provided clarification - incorporating feedback")
        
        # IMPORTANT: Do NOT overwrite original_query - keep it unchanged
        # Instead, create a combined context for planning agent
        original = state["original_query"]
        clarif_msg = state.get("clarification_message", "")
        
        # Build combined query context with structured format
        combined_context = f"""**Original Query**: {original}

**Clarification Question**: {clarif_msg}

**User's Answer**: {user_response}

**Context**: The user was asked for clarification and provided additional information. Use all three pieces of information together to understand the complete intent."""
        
        state["combined_query_context"] = combined_context
        state["question_clear"] = True
        state["next_agent"] = "planning"
        
        print(f"   Original Query (preserved): {original}")
        print(f"   Clarification Message: {clarif_msg}")
        print(f"   User Response: {user_response}")
        print(f"   ✓ Combined context created for planning agent")
        
        state["messages"].append(
            SystemMessage(content=f"User clarification incorporated: {user_response}\nCombined context created with original query, clarification question, and user answer.")
        )
        
        return state
    
    query = state["original_query"]
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_CLARIFICATION)
    
    # Use OOP agent with clarification count
    # Load context fresh from table (no redeployment needed for updates)
    clarification_agent = ClarificationAgent.from_table(llm, TABLE_NAME)
    clarity_result = clarification_agent(query, clarification_count)
    
    # Update explicit state
    state["question_clear"] = clarity_result.get("question_clear", True)
    state["clarification_needed"] = clarity_result.get("clarification_needed")
    state["clarification_options"] = clarity_result.get("clarification_options")
    
    if state["question_clear"]:
        print("✓ Query is clear - proceeding to planning")
        state["next_agent"] = "planning"
        # No clarification needed, so combined context is just the original query
        state["combined_query_context"] = state["original_query"]
    else:
        print("⚠ Query needs clarification (attempt 1 of 1)")
        print(f"   Reason: {state['clarification_needed']}")
        if state["clarification_options"]:
            print("   Options:")
            for i, opt in enumerate(state["clarification_options"], 1):
                print(f"     {i}. {opt}")
        
        # Increment clarification count
        state["clarification_count"] = clarification_count + 1
        
        # Route to END to show clarification request (routing controlled by route_after_clarification)
        # The actual routing is handled by the conditional edge which checks question_clear flag
        
        # Build and store clarification message
        clarification_message = (
            f"I need clarification: {state['clarification_needed']}\n\n"
            f"Please choose one of the following options or provide your own clarification:\n"
        )
        if state["clarification_options"]:
            for i, opt in enumerate(state["clarification_options"], 1):
                clarification_message += f"{i}. {opt}\n"
        
        # Store the clarification message in state
        state["clarification_message"] = clarification_message
        
        state["messages"].append(
            AIMessage(content=clarification_message)
        )
    
    state["messages"].append(
        SystemMessage(content=f"Clarification result: {json.dumps(clarity_result, indent=2)}")
    )
    
    return state


def planning_node(state: AgentState) -> AgentState:
    """
    Planning node wrapping PlanningAgent class.
    Combines OOP modularity with explicit state management.
    
    Uses combined_query_context if available (from clarification flow),
    otherwise uses original_query.
    """
    print("\n" + "="*80)
    print("📋 PLANNING AGENT")
    print("="*80)
    
    # Use combined_query_context if available (includes clarification context)
    # Otherwise fall back to original_query
    query = state.get("combined_query_context") or state["original_query"]
    
    if state.get("combined_query_context"):
        print("✓ Using combined query context (includes clarification)")
    else:
        print("✓ Using original query (no clarification needed)")
    
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING)
    
    # Use OOP agent
    planning_agent = PlanningAgent(llm, VECTOR_SEARCH_INDEX)
    
    # Get relevant spaces with full metadata (for Genie agents)
    relevant_spaces_full = planning_agent.search_relevant_spaces(query)
    
    # Create execution plan
    plan = planning_agent.create_execution_plan(query, relevant_spaces_full)
    
    # Update explicit state
    state["plan"] = plan
    state["sub_questions"] = plan.get("sub_questions", [])
    state["requires_multiple_spaces"] = plan.get("requires_multiple_spaces", False)
    state["relevant_space_ids"] = plan.get("relevant_space_ids", [])
    state["requires_join"] = plan.get("requires_join", False)
    state["join_strategy"] = plan.get("join_strategy")
    state["execution_plan"] = plan.get("execution_plan", "")
    state["genie_route_plan"] = plan.get("genie_route_plan")
    state["vector_search_relevant_spaces_info"] = plan.get("vector_search_relevant_spaces_info", [])
    
    # Store full relevant_spaces for Genie agents (includes searchable_content)
    # This avoids re-querying and reuses Vector Search results
    state["relevant_spaces"] = relevant_spaces_full
    
    # Determine next agent
    if state["join_strategy"] == "genie_route":
        print("✓ Plan complete - using GENIE ROUTE (Genie agents)")
        state["next_agent"] = "sql_synthesis_genie"
    else:
        print("✓ Plan complete - using TABLE ROUTE (direct SQL synthesis)")
        state["next_agent"] = "sql_synthesis_table"
    
    state["messages"].append(
        SystemMessage(content=f"Execution plan: {json.dumps(plan, indent=2)}")
    )
    
    return state


def sql_synthesis_table_node(state: AgentState) -> AgentState:
    """
    Fast SQL synthesis node wrapping SQLSynthesisTableAgent class.
    Combines OOP modularity with explicit state management.
    """
    print("\n" + "="*80)
    print("⚡ SQL SYNTHESIS AGENT - TABLE ROUTE")
    print("="*80)
    
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_SQL_SYNTHESIS, temperature=0.1)
    
    # Use OOP agent
    sql_agent = SQLSynthesisTableAgent(llm, CATALOG, SCHEMA)
    
    # # Prepare plan for agent
    # plan = {
    #     "original_query": state["original_query"],
    #     "vector_search_relevant_spaces_info": state.get("vector_search_relevant_spaces_info", []),
    #     "relevant_space_ids": state.get("relevant_space_ids", []),
    #     "execution_plan": state.get("execution_plan", ""),
    #     "requires_join": state.get("requires_join", False),
    #     "sub_questions": state.get("sub_questions", [])
    # }
    plan = state.get("plan", {})
    print("plan loaded from state is:", plan)
    print(json.dumps(plan, indent=2))
    
    try:
        print("🤖 Invoking SQL synthesis agent...")
        result = sql_agent(plan)
        
        # Extract SQL and explanation
        sql_query = result.get("sql")
        explanation = result.get("explanation", "")
        has_sql = result.get("has_sql", False)
        
        state["sql_synthesis_explanation"] = explanation
        
        if has_sql and sql_query and explanation:
            state["sql_query"] = sql_query
            state["has_sql"] = has_sql
            state["next_agent"] = "sql_execution"
            print("✓ SQL query synthesized successfully")
            print(f"SQL Preview: {sql_query[:200]}...")
            if explanation:
                print(f"Agent Explanation: {explanation[:200]}...")
            
            # Add message with SQL synthesis explanation
            state["messages"].append(
                AIMessage(content=f"SQL Synthesis (Table Route):\n{explanation}")
            )
        else:
            print("⚠ No SQL generated - agent explanation:")
            print(f"  {explanation}")
            state["synthesis_error"] = "Cannot generate SQL query"
            state["next_agent"] = "summarize"
            
            # Add message with explanation even if no SQL
            state["messages"].append(
                AIMessage(content=f"SQL Synthesis Failed (Table Route):\n{explanation}")
            )
        
    except Exception as e:
        print(f"❌ SQL synthesis failed: {e}")
        state["synthesis_error"] = str(e)
        state["sql_synthesis_explanation"] = str(e)
        # Route to summarize via conditional edge (route_after_synthesis)
        state["messages"].append(
                AIMessage(content=f"SQL Synthesis Failed (Table Route):\n{state['sql_synthesis_explanation']}")
            )
    
    return state


def sql_synthesis_genie_node(state: AgentState) -> AgentState:
    """
    Slow SQL synthesis node wrapping SQLSynthesisGenieAgent class.
    Combines OOP modularity with explicit state management.
    
    Uses relevant_spaces from PlanningAgent (no need to re-query all spaces).
    """
    print("\n" + "="*80)
    print("🐢 SQL SYNTHESIS AGENT - GENIE ROUTE")
    print("="*80)
    
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_SQL_SYNTHESIS, temperature=0.1)
    
    # Get relevant spaces from state (already discovered by PlanningAgent)
    relevant_spaces = state.get("relevant_spaces", [])
    
    if not relevant_spaces:
        print("❌ No relevant_spaces found in state")
        state["synthesis_error"] = "No relevant spaces available for genie route"
        # Route to summarize via conditional edge (route_after_synthesis)
        return state
    
    # Use OOP agent - only creates Genie agents for relevant spaces
    sql_agent = SQLSynthesisGenieAgent(llm, relevant_spaces)
    
    plan = state.get("plan", {})
    genie_route_plan = plan.get("genie_route_plan", {})
    
    if not genie_route_plan:
        print("❌ No genie_route_plan found in plan")
        state["synthesis_error"] = "No routing plan available for genie route"
        # Route to summarize via conditional edge (route_after_synthesis)
        return state
    
    try:
        print(f"🤖 Querying {len(genie_route_plan)} Genie agents...")
        result = sql_agent(plan)
        
        # Extract SQL and explanation
        sql_query = result.get("sql")
        explanation = result.get("explanation", "")
        has_sql = result.get("has_sql", False)
        
        state["sql_synthesis_explanation"] = explanation
        
        # Update explicit state
        if has_sql and sql_query and explanation:
            state["sql_query"] = sql_query
            state["next_agent"] = "sql_execution"
            state["has_sql"] = has_sql
            print("✓ SQL fragments combined successfully")
            print(f"SQL Preview: {sql_query[:200]}...")
            if explanation:
                print(f"Agent Explanation: {explanation[:200]}...")
            
            # Add message with SQL synthesis explanation
            state["messages"].append(
                AIMessage(content=f"SQL Synthesis (Genie Route):\n{explanation}")
            )
        else:
            print("⚠ No SQL generated - agent explanation:")
            print(f"  {explanation}")
            state["synthesis_error"] = "Cannot generate SQL query from Genie agent fragments"
            state["next_agent"] = "summarize"
            
            # Add message with explanation even if no SQL
            state["messages"].append(
                AIMessage(content=f"SQL Synthesis Failed (Genie Route):\n{explanation}")
            )
        
    except Exception as e:
        print(f"❌ SQL synthesis failed: {e}")
        state["synthesis_error"] = str(e)
        state["sql_synthesis_explanation"] = str(e)
        # Route to summarize via conditional edge (route_after_synthesis)
        state["messages"].append(
                AIMessage(content=f"SQL Synthesis Failed (Genie Route):\n{state['sql_synthesis_explanation']}")
            )
    
    return state


def sql_execution_node(state: AgentState) -> AgentState:
    """
    SQL execution node wrapping SQLExecutionAgent class.
    Combines OOP modularity with explicit state management.
    """
    print("\n" + "="*80)
    print("🚀 SQL EXECUTION AGENT")
    print("="*80)
    
    sql_query = state.get("sql_query")
    
    if not sql_query:
        print("❌ No SQL query to execute")
        state["execution_error"] = "No SQL query provided"
        # Route to summarize via fixed edge (sql_execution → summarize)
        return state
    
    # Use OOP agent
    execution_agent = SQLExecutionAgent()
    result = execution_agent(sql_query)
    
    if result["success"]:
        print(f"✓ Query executed successfully!")
        print(f"📊 Rows returned: {result['row_count']}")
        print(f"📋 Columns: {', '.join(result['columns'])}")
        
        state["messages"].append(
            SystemMessage(content=f"Execution successful: {result['row_count']} rows returned")
        )
    else:
        print(f"❌ SQL execution failed: {result.get('error', 'Unknown error')}")
        state["execution_error"] = result.get("error")
        
        state["messages"].append(
            SystemMessage(content=f"Execution failed: {result.get('error')}")
        )
    
    state["execution_result"] = result
    state["next_agent"] = "summarize"
    
    return state


def summarize_node(state: AgentState) -> AgentState:
    """
    Result summarize node wrapping ResultSummarizeAgent class.
    
    This is the final node that all workflow paths go through.
    Generates a natural language summary AND preserves all workflow data.
    
    Returns state with ALL fields preserved including:
    - sql_query: Generated SQL query
    - execution_result: Query execution results
    - sql_synthesis_explanation: SQL generation explanation
    - synthesis_error: SQL generation errors (if any)
    - execution_error: Query execution errors (if any)
    - execution_plan: Planning agent's execution plan
    - final_summary: Natural language summary (NEW)
    """
    print("\n" + "="*80)
    print("📝 RESULT SUMMARIZE AGENT")
    print("="*80)
    
    # Create LLM for summarization (no max_tokens limit for comprehensive output)
    llm = ChatDatabricks(endpoint=LLM_ENDPOINT_SUMMARIZE, temperature=0.1, max_tokens=2000)
    
    # Use OOP agent to generate summary
    summarize_agent = ResultSummarizeAgent(llm)
    summary = summarize_agent(state)
    
    print(f"\n✅ Summary Generated:")
    print(f"{summary}")
    
    # Store summary in state (all other fields are preserved automatically)
    state["final_summary"] = summary
    
    # Display what's being returned
    print(f"\n📦 State Fields Being Returned:")
    print(f"  ✓ final_summary: {len(summary)} chars")
    if state.get("sql_query"):
        print(f"  ✓ sql_query: {len(state['sql_query'])} chars")
    if state.get("execution_result"):
        exec_result = state["execution_result"]
        if exec_result.get("success"):
            print(f"  ✓ execution_result: {exec_result.get('row_count', 0)} rows")
        else:
            print(f"  ✓ execution_result: Failed - {exec_result.get('error', 'Unknown')[:50]}...")
    if state.get("sql_synthesis_explanation"):
        print(f"  ✓ sql_synthesis_explanation: {len(state['sql_synthesis_explanation'])} chars")
    if state.get("execution_plan"):
        print(f"  ✓ execution_plan: {state['execution_plan'][:80]}...")
    if state.get("synthesis_error"):
        print(f"  ⚠ synthesis_error: {state['synthesis_error'][:50]}...")
    if state.get("execution_error"):
        print(f"  ⚠ execution_error: {state['execution_error'][:50]}...")
    
    print("="*80)
    
    # Build comprehensive final message with ALL workflow information
    final_message_parts = []
    
    # 1. Summary
    final_message_parts.append(f"📝 **Summary:**\n{summary}\n")
    
    # 2. Original Query
    if state.get("original_query"):
        final_message_parts.append(f"🔍 **Original Query:**\n{state['original_query']}\n")
    
    # 3. Execution Plan
    if state.get("execution_plan"):
        final_message_parts.append(f"📋 **Execution Plan:**\n{state['execution_plan']}")
        if state.get("join_strategy"):
            final_message_parts.append(f"Strategy: {state['join_strategy']}\n")
    
    # 4. SQL Synthesis Explanation
    if state.get("sql_synthesis_explanation"):
        final_message_parts.append(f"💭 **SQL Synthesis Explanation:**\n{state['sql_synthesis_explanation']}\n")
    
    # 5. Generated SQL
    if state.get("sql_query"):
        final_message_parts.append(f"💻 **Generated SQL:**\n```sql\n{state['sql_query']}\n```\n")
    
    # 6. Execution Results
    exec_result = state.get("execution_result")
    if exec_result:
        if exec_result.get("success"):
            final_message_parts.append(f"✅ **Execution Successful:**\n")
            final_message_parts.append(f"- Rows: {exec_result.get('row_count', 0)}\n")
            final_message_parts.append(f"- Columns: {', '.join(exec_result.get('columns', []))}\n")
            
            # Convert results to pandas DataFrame and display
            results = exec_result.get("result", [])
            if results:
                try:
                    import pandas as pd
                    df = pd.DataFrame(results)
                    
                    final_message_parts.append(f"\n📊 **Query Results:**\n")
                    
                    # Display DataFrame
                    print("\n" + "="*80)
                    print("📊 QUERY RESULTS (Pandas DataFrame)")
                    print("="*80)
                    try:
                        display(df)  # Use Databricks display() for interactive view
                    except:
                        print(df.to_string())  # Fallback to string representation
                    print("="*80 + "\n")
                    
                    # Add DataFrame info to message
                    final_message_parts.append(f"DataFrame shape: {df.shape}\n")
                    final_message_parts.append(f"Preview (first 5 rows):\n```\n{df.head().to_string()}\n```\n")
                    
                    # Note: DataFrame not stored in state (not msgpack serializable)
                    # Users can recreate it from state['execution_result']['result']
                    
                except Exception as e:
                    final_message_parts.append(f"⚠️ Could not convert to DataFrame: {e}\n")
                    final_message_parts.append(f"Raw results (first 3): {results[:3]}\n")
        else:
            final_message_parts.append(f"❌ **Execution Failed:**\n")
            final_message_parts.append(f"Error: {exec_result.get('error', 'Unknown error')}\n")
    
    # 7. Errors (if any)
    if state.get("synthesis_error"):
        final_message_parts.append(f"❌ **Synthesis Error:**\n{state['synthesis_error']}\n")
    if state.get("execution_error"):
        final_message_parts.append(f"❌ **Execution Error:**\n{state['execution_error']}\n")
    
    # 8. Relevant Spaces (if any)
    if state.get("relevant_space_ids"):
        final_message_parts.append(f"\n🎯 **Relevant Genie Spaces:** {len(state['relevant_space_ids'])} spaces analyzed\n")
    
    # Combine all parts into final comprehensive message
    comprehensive_message = "\n".join(final_message_parts)
    
    # Add comprehensive message to state messages
    state["messages"].append(
        AIMessage(content=comprehensive_message)
    )
    
    print(f"\n✅ Comprehensive final message created ({len(comprehensive_message)} chars)")
    
    # Route to END via fixed edge (summarize → END)
    # Return complete state with ALL fields preserved
    return state

print("✓ All node wrappers defined (including summarize)")
def create_super_agent_hybrid():
    """
    Create the Hybrid Super Agent LangGraph workflow.
    
    Combines:
    - OOP agent classes for modularity
    - Explicit state management for observability
    """
    print("\n" + "="*80)
    print("🏗️ BUILDING HYBRID SUPER AGENT WORKFLOW")
    print("="*80)
    
    # Create the graph with explicit state
    workflow = StateGraph(AgentState)
    
    # Add nodes (wrapping OOP agents)
    workflow.add_node("clarification", clarification_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("sql_synthesis_table", sql_synthesis_table_node)
    workflow.add_node("sql_synthesis_genie", sql_synthesis_genie_node)
    workflow.add_node("sql_execution", sql_execution_node)
    workflow.add_node("summarize", summarize_node)  # Final summarization node
    
    # Define routing logic based on explicit state
    def route_after_clarification(state: AgentState) -> str:
        if state.get("question_clear", False):
            return "planning"
        return END  # End if clarification needed
    
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
        return "summarize"  # Summarize if synthesis error
    
    # Add edges with conditional routing
    workflow.set_entry_point("clarification")
    
    workflow.add_conditional_edges(
        "clarification",
        route_after_clarification,
        {
            "planning": "planning",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "planning",
        route_after_planning,
        {
            "sql_synthesis_table": "sql_synthesis_table",
            "sql_synthesis_genie": "sql_synthesis_genie",
            "summarize": "summarize"
        }
    )
    
    workflow.add_conditional_edges(
        "sql_synthesis_table",
        route_after_synthesis,
        {
            "sql_execution": "sql_execution",
            "summarize": "summarize"
        }
    )
    
    workflow.add_conditional_edges(
        "sql_synthesis_genie",
        route_after_synthesis,
        {
            "sql_execution": "sql_execution",
            "summarize": "summarize"
        }
    )
    
    # SQL execution always goes to summarize
    workflow.add_edge("sql_execution", "summarize")
    
    # Summarize is the final node before END
    workflow.add_edge("summarize", END)
    
    # NOTE: Workflow compiled WITHOUT checkpointer here
    # Checkpointer will be added at runtime in SuperAgentHybridResponsesAgent
    # This allows distributed Model Serving with CheckpointSaver
    app_graph = workflow
    
    print("✓ Workflow nodes added:")
    print("  1. Clarification Agent (OOP)")
    print("  2. Planning Agent (OOP)")
    print("  3. SQL Synthesis Agent - Table Route (OOP)")
    print("  4. SQL Synthesis Agent - Genie Route (OOP)")
    print("  5. SQL Execution Agent (OOP)")
    print("  6. Result Summarize Agent (OOP) - FINAL NODE")
    print("\n✓ Explicit state management enabled")
    print("✓ Conditional routing configured")
    print("✓ All paths route to summarize node before END")
    print("✓ Checkpointer will be added at runtime (distributed serving)")
    print("\n✅ Hybrid Super Agent workflow created successfully!")
    print("="*80)
    
    return app_graph

# Create the Hybrid Super Agent
super_agent_hybrid = create_super_agent_hybrid()
class SuperAgentHybridResponsesAgent(ResponsesAgent):
    """
    Enhanced ResponsesAgent with both short-term and long-term memory for distributed Model Serving.
    
    Features:
    - Short-term memory (CheckpointSaver): Multi-turn conversations within a session
    - Long-term memory (DatabricksStore): User preferences across sessions with semantic search
    - Connection pooling and automatic credential rotation
    - Works seamlessly in distributed Model Serving (multiple instances)
    
    Memory Architecture:
    - Short-term: Stored per thread_id in Lakebase checkpoints table
    - Long-term: Stored per user_id in Lakebase store table with vector embeddings
    """
    
    def __init__(self, workflow: StateGraph):
        """
        Initialize the ResponsesAgent wrapper.
        
        Args:
            workflow: The uncompiled LangGraph StateGraph workflow
        """
        self.workflow = workflow
        self.lakebase_instance_name = LAKEBASE_INSTANCE_NAME
        self._store = None
        self._memory_tools = None
        print("✓ SuperAgentHybridResponsesAgent initialized with memory support")
    
    @property
    def store(self):
        """Lazy initialization of DatabricksStore for long-term memory."""
        if self._store is None:
            logger.info(f"Initializing DatabricksStore with instance: {self.lakebase_instance_name}")
            self._store = DatabricksStore(
                instance_name=self.lakebase_instance_name,
                embedding_endpoint=EMBEDDING_ENDPOINT,
                embedding_dims=EMBEDDING_DIMS,
            )
            self._store.setup()  # Creates store table if not exists
            logger.info("✓ DatabricksStore initialized")
        return self._store
    
    @property
    def memory_tools(self):
        """Create memory tools for long-term memory access."""
        if self._memory_tools is None:
            logger.info("Creating memory tools for long-term memory")
            
            @tool
            def get_user_memory(query: str, config: RunnableConfig) -> str:
                """Search for relevant user information using semantic search.
                
                Use this tool to retrieve previously saved information about the user,
                such as their preferences, facts they've shared, or other personal details.
                
                Args:
                    query: The search query to find relevant memories
                    config: Runtime configuration containing user_id
                """
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Memory not available - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                results = self.store.search(namespace, query=query, limit=5)
                
                if not results:
                    return "No memories found for this user."
                
                memory_items = [f"- [{item.key}]: {json.dumps(item.value)}" for item in results]
                return f"Found {len(results)} relevant memories (ranked by similarity):\n" + "\n".join(memory_items)
            
            @tool
            def save_user_memory(memory_key: str, memory_data_json: str, config: RunnableConfig) -> str:
                """Save information about the user to long-term memory.
                
                Use this tool to remember important information the user shares,
                such as preferences, facts, or other personal details.
                
                Args:
                    memory_key: A descriptive key for this memory (e.g., "preferences", "favorite_visualization")
                    memory_data_json: JSON string with the information to remember. 
                        Example: '{"preferred_chart_type": "bar", "default_spaces": ["patient_data"]}'
                    config: Runtime configuration containing user_id
                """
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot save memory - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                
                try:
                    memory_data = json.loads(memory_data_json)
                    if not isinstance(memory_data, dict):
                        return f"Failed: memory_data must be a JSON object, not {type(memory_data).__name__}"
                    self.store.put(namespace, memory_key, memory_data)
                    return f"Successfully saved memory with key '{memory_key}' for user"
                except json.JSONDecodeError as e:
                    return f"Failed to save memory: Invalid JSON format - {str(e)}"
            
            @tool
            def delete_user_memory(memory_key: str, config: RunnableConfig) -> str:
                """Delete a specific memory from the user's long-term memory.
                
                Use this when the user asks you to forget something or remove
                a piece of information from their memory.
                
                Args:
                    memory_key: The key of the memory to delete
                    config: Runtime configuration containing user_id
                """
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot delete memory - no user_id provided."
                
                namespace = ("user_memories", user_id.replace(".", "-"))
                self.store.delete(namespace, memory_key)
                return f"Successfully deleted memory with key '{memory_key}' for user"
            
            self._memory_tools = [get_user_memory, save_user_memory, delete_user_memory]
            logger.info(f"✓ Created {len(self._memory_tools)} memory tools")
        
        return self._memory_tools
    
    def _get_or_create_thread_id(self, request: ResponsesAgentRequest) -> str:
        """Get thread_id from request or create a new one.
        
        Priority:
        1. Use thread_id from custom_inputs if present
        2. Use conversation_id from chat context if available
        3. Generate a new UUID
        """
        ci = dict(request.custom_inputs or {})
        
        if "thread_id" in ci:
            return ci["thread_id"]
        
        # Use conversation_id from ChatContext as thread_id
        if request.context and getattr(request.context, "conversation_id", None):
            return request.context.conversation_id
        
        # Generate new thread_id
        return str(uuid4())
    
    def _get_user_id(self, request: ResponsesAgentRequest) -> Optional[str]:
        """Extract user_id from request context.
        
        Priority:
        1. Use user_id from chat context (preferred for Model Serving)
        2. Use user_id from custom_inputs
        """
        if request.context and getattr(request.context, "user_id", None):
            return request.context.user_id
        
        if request.custom_inputs and "user_id" in request.custom_inputs:
            return request.custom_inputs["user_id"]
        
        return None
    
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """
        Make a prediction (non-streaming).
        
        Args:
            request: The request containing input messages
            
        Returns:
            ResponsesAgentResponse with output items
        """
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
        """
        Make a streaming prediction with both short-term and long-term memory.
        
        Handles three scenarios:
        1. New query: Fresh start with new original_query
        2. Clarification response: User answering agent's clarification question
        3. Follow-up query: New query with access to previous conversation context
        
        Memory Systems:
        - Short-term (CheckpointSaver): Preserves conversation state across distributed instances
        - Long-term (DatabricksStore): User preferences accessible via memory tools
        
        Args:
            request: The request containing:
                - input: List of messages (user query is the last message)
                - context.conversation_id: Used as thread_id (preferred)
                - context.user_id: Used for long-term memory (preferred)
                - custom_inputs: Dict with optional keys:
                    - thread_id (str): Thread identifier override
                    - user_id (str): User identifier override
                    - is_clarification_response (bool): Set to True when user is answering clarification
                    - clarification_count (int): Preserved from previous state
                    - original_query (str): Preserved from previous state for clarification responses
                    - clarification_message (str): Preserved from previous state for clarification responses
            
        Yields:
            ResponsesAgentStreamEvent for each step in the workflow
            
        Usage in Model Serving:
            # New query with memory
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Show me patient data"}],
                "context": {
                    "conversation_id": "session_001",
                    "user_id": "user@example.com"
                }
            }
            
            # Clarification response
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Patient count by age group"}],
                "custom_inputs": {
                    "thread_id": "session_001",  # Must match previous call
                    "is_clarification_response": true,
                    "original_query": "Show me patient data",
                    "clarification_message": "...",
                    "clarification_count": 1
                }
            }
            
            # Follow-up query (agent remembers context and user preferences)
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Now show by gender"}],
                "context": {
                    "conversation_id": "session_001",
                    "user_id": "user@example.com"
                }
            }
        """
        # Get identifiers
        thread_id = self._get_or_create_thread_id(request)
        user_id = self._get_user_id(request)
        
        # Update custom_inputs with resolved identifiers
        ci = dict(request.custom_inputs or {})
        ci["thread_id"] = thread_id
        if user_id:
            ci["user_id"] = user_id
        request.custom_inputs = ci
        
        logger.info(f"Processing request - thread_id: {thread_id}, user_id: {user_id}")
        
        # Convert request input to chat completions format
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        
        # Get the latest user message
        latest_query = cc_msgs[-1]["content"] if cc_msgs else ""
        
        # Configure runtime with thread_id and user_id
        run_config = {"configurable": {"thread_id": thread_id}}
        if user_id:
            run_config["configurable"]["user_id"] = user_id
        
        # Check if this is a clarification response
        is_clarification_response = ci.get("is_clarification_response", False)
        
        # Initialize state based on scenario
        if is_clarification_response:
            # Scenario 2: Clarification Response
            # User is answering the agent's clarification question
            # Preserve state from previous call and add user's response
            
            original_query = ci.get("original_query", latest_query)
            clarification_message = ci.get("clarification_message", "")
            clarification_count = ci.get("clarification_count", 1)
            
            initial_state = {
                # Preserve from previous state
                "original_query": original_query,
                "clarification_message": clarification_message,
                "clarification_count": clarification_count,
                
                # Add user's clarification response
                "user_clarification_response": latest_query,
                "question_clear": False,
                
                # Messages
                "messages": [HumanMessage(content=f"Clarification response: {latest_query}")],
                
                # Route back to clarification node
                "next_agent": "clarification"
            }
        else:
            # Scenario 1 & 3: New Query or Follow-Up Query
            # CheckpointSaver will restore context for follow-ups
            
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
        
        # Add user_id to state for long-term memory access
        if user_id:
            initial_state["user_id"] = user_id
            initial_state["thread_id"] = thread_id
        
        first_message = True
        seen_ids = set()
        
        # Execute workflow with CheckpointSaver for distributed serving
        # CRITICAL: CheckpointSaver as context manager ensures all instances share state
        with CheckpointSaver(instance_name=self.lakebase_instance_name) as checkpointer:
            # Compile graph with checkpointer at runtime
            # This allows distributed Model Serving to access shared state
            app = self.workflow.compile(checkpointer=checkpointer)
            
            logger.info(f"Executing workflow with checkpointer (thread: {thread_id})")
            
            # Stream the workflow execution
            # CheckpointSaver will:
            # 1. Restore previous state from thread_id (if exists) from Lakebase
            # 2. Merge with initial_state (initial_state takes precedence)
            # 3. Preserve conversation history across distributed instances
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
                    # Get node name
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
        
        logger.info(f"Workflow execution completed (thread: {thread_id})")


# Create the deployable agent
AGENT = SuperAgentHybridResponsesAgent(super_agent_hybrid)

print("\n" + "="*80)
print("✅ HYBRID SUPER AGENT RESPONSES AGENT CREATED")
print("="*80)
print("Architecture: OOP Agents + Explicit State Management")
print("Benefits:")
print("  ✓ Modular and testable agent classes")
print("  ✓ Full state observability for debugging")
print("  ✓ Production-ready with development-friendly design")
print("\nThis agent is now ready for:")
print("  1. Local testing with AGENT.predict()")
print("  2. Logging with mlflow.pyfunc.log_model()")
print("  3. Deployment to Databricks Model Serving")
print("\nMemory Features:")
print("  ✓ Short-term memory: Multi-turn conversations (CheckpointSaver)")
print("  ✓ Long-term memory: User preferences (DatabricksStore)")
print("  ✓ Works in distributed Model Serving (shared state via Lakebase)")
print("="*80)

# Set the agent for MLflow tracking
mlflow.langchain.autolog()
mlflow.models.set_model(AGENT)
