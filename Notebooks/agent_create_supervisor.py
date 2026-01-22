import json
import re
from typing import Dict, List, Optional, Any, Generator
from uuid import uuid4

import mlflow
from databricks_langchain import (
    ChatDatabricks,
    DatabricksFunctionClient,
    UCFunctionToolkit,
    VectorSearchRetrieverTool,
    set_uc_function_client,
)
from databricks_langchain.genie import GenieAgent
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.messages import AIMessage
from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph
from langgraph_supervisor import create_supervisor
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)
from pydantic import BaseModel
from functools import partial

client = DatabricksFunctionClient()
set_uc_function_client(client)

########################################
# Configuration
########################################

# TODO: Update these configuration values
CATALOG = "yyang"
SCHEMA = "multi_agent_genie"
TABLE_NAME = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks"
VECTOR_SEARCH_INDEX = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks_vs_index"
LLM_ENDPOINT_NAME = "databricks-claude-sonnet-4-5"
LLM_ENDPOINT_PLANNING = "databricks-claude-haiku-4-5"  # Planning can use lighter model

########################################
# Agent Type Definitions
########################################

class InCodeSubAgent(BaseModel):
    tools: list[str]
    name: str
    description: str
    system_prompt: Optional[str] = None


class GenieSubAgent(BaseModel):
    space_id: str
    name: str
    description: str


TOOLS = []

########################################
# Helper Functions
########################################

def stringify_content(state):
    """Converts list content to JSON string for better parsing."""
    msgs = state["messages"]
    if isinstance(msgs[-1].content, list):
        msgs[-1].content = json.dumps(msgs[-1].content, indent=4)
    return {"messages": msgs}


def enforce_limit(messages, n=10):
    """Appends an instruction to the last user message to limit the result size."""
    last = messages[-1] if messages else {"content": ""}
    content = last.get("content", "") if isinstance(last, dict) else last.content
    return f"{content}\n\nPlease limit the result to at most {n} rows."


def extract_genie_sql(resp: dict) -> tuple:
    """Extracts thinking, SQL, and answer from Genie agent response."""
    thinking = None
    sql = None
    answer = None

    for msg in resp["messages"]:
        if isinstance(msg, AIMessage):
            if msg.name == "query_reasoning":
                thinking = msg.content
            elif msg.name == "query_sql":
                sql = msg.content
            elif msg.name == "query_result":
                answer = msg.content
    return thinking, sql, answer


def query_delta_table(table_name: str, filter_field: str, filter_value: str, select_fields: List[str] = None):
    """Query a delta table with a filter condition."""
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


########################################
# Create Genie Agents
########################################

def create_genie_agents(table_name: str) -> tuple:
    """Create Genie agents from space summary data."""
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    
    # Query space summary data
    space_summary_df = query_delta_table(
        table_name=table_name,
        filter_field="chunk_type",
        filter_value="space_summary",
        select_fields=["space_id", "space_title", "searchable_content"]
    )
    
    genie_agents = []
    genie_agent_tools = []
    genie_subagent_configs = []
    
    for row in space_summary_df.collect():
        space_id = row["space_id"]
        space_title = row["space_title"]
        searchable_content = row["searchable_content"]
        genie_agent_name = f"Genie_{space_title}"
        description = searchable_content
        
        # Create Genie agent
        genie_agent = GenieAgent(
            genie_space_id=space_id,
            genie_agent_name=genie_agent_name,
            description=description,
            include_context=True,
            message_processor=lambda msgs: enforce_limit(msgs, n=10)
        )
        
        genie_agents.append(genie_agent)
        
        # Wrap agent for tool use
        def make_agent_invoker(agent):
            return lambda question: agent.invoke(
                {"messages": [{"role": "user", "content": question}]}
            )
        
        runnable = RunnableLambda(make_agent_invoker(genie_agent))
        runnable.name = genie_agent_name
        runnable.description = description
        
        genie_agent_tools.append(
            runnable.as_tool(
                name=genie_agent_name,
                description=description,
                arg_types={"question": str}
            )
        )
        
        # Store config for supervisor
        genie_subagent_configs.append(
            GenieSubAgent(
                space_id=space_id,
                name=genie_agent_name,
                description=description
            )
        )
    
    return genie_agents, genie_agent_tools, genie_subagent_configs, space_summary_df


########################################
# Create LangGraph Supervisor Agent
########################################

def create_langgraph_supervisor(
    llm: Runnable,
    in_code_agents: list[InCodeSubAgent] = [],
    additional_agents: list[Runnable] = [],
):
    """Create a LangGraph supervisor with specialized agents."""
    agents = []
    agent_descriptions = ""

    # Process inline code agents
    for agent in in_code_agents:
        agent_descriptions += f"- {agent.name}: {agent.description}\n"
        
        # Handle agents with tools
        if agent.tools:
            uc_toolkit = UCFunctionToolkit(function_names=agent.tools)
            TOOLS.extend(uc_toolkit.tools)
            agent_tools = uc_toolkit.tools
        else:
            agent_tools = []
        
        # Create agent with custom system prompt if provided
        if agent.system_prompt:
            created_agent = create_agent(
                llm, 
                tools=agent_tools, 
                name=agent.name,
                system_prompt=agent.system_prompt
            )
        else:
            created_agent = create_agent(llm, tools=agent_tools, name=agent.name)
        
        agents.append(created_agent)

    # Add additional pre-built agents
    for agent in additional_agents:
        agents.append(agent)
        # Extract description from agent if available
        agent_name = getattr(agent, 'name', 'unknown_agent')
        agent_desc = getattr(agent, 'description', 'Additional agent')
        agent_descriptions += f"- {agent_name}: {agent_desc}\n"

    # Supervisor prompt
    prompt = f"""
    You are a supervisor in a multi-agent system for analyzing and querying Genie spaces.
    
    Your role is to:
    1. Understand the user's query
    2. Route to appropriate agents in the correct sequence
    3. Coordinate handoffs between agents
    4. Aggregate all outputs into a comprehensive final response
    
    Available Agents:
    {agent_descriptions}
    
    Typical Workflow:
    1. Clarification Agent: Validates query clarity first
    2. Planning Agent: Analyzes query and creates execution plan
    3. SQL Synthesis Agent (Fast or Genie Route): Generates SQL based on the plan
    4. SQL Execution Agent: Executes the generated SQL
    5. Return comprehensive results including:
       - Execution Plan (from Planning Agent)
       - SQL Query (from SQL Synthesis Agent)
       - Query Results (from SQL Execution Agent)
       - Any additional explanations
    
    Always maintain context from previous agent responses when routing to the next agent.
    Your final response should synthesize all the information gathered throughout the workflow.
    Format your final response as:
    
    **Execution Plan**: [Brief summary of the plan]
    **SQL Query**: [The generated SQL]
    **Results**: [Query execution results]
    **Explanation**: [Any additional context or insights]
    """

    return create_supervisor(
        agents=agents,
        model=llm,
        prompt=prompt,
        add_handoff_messages=False,
        output_mode="full_history",
    ).compile()


##########################################
# Wrap LangGraph Supervisor as a ResponsesAgent
##########################################

class LangGraphResponsesAgent(ResponsesAgent):
    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
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
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        first_message = True
        seen_ids = set()

        for _, events in self.agent.stream({"messages": cc_msgs}, stream_mode=["updates"]):
            new_msgs = [
                msg
                for v in events.values()
                for msg in v.get("messages", [])
                if msg.id not in seen_ids
            ]
            if first_message:
                seen_ids.update(msg.id for msg in new_msgs[: len(cc_msgs)])
                new_msgs = new_msgs[len(cc_msgs) :]
                first_message = False
            else:
                seen_ids.update(msg.id for msg in new_msgs)
                node_name = tuple(events.keys())[0]
                yield ResponsesAgentStreamEvent(
                    type="response.output_item.done",
                    item=self.create_text_output_item(
                        text=f"<name>{node_name}</name>", id=str(uuid4())
                    ),
                )
            if len(new_msgs) > 0:
                yield from output_to_responses_items_stream(new_msgs)


#######################################################
# Configure the Multi-Agent System
#######################################################

# Initialize LLM
llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME)
llm_planning = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING)

# Create Genie agents (for genie route)
genie_agents, genie_agent_tools, genie_subagent_configs, space_summary_df = create_genie_agents(TABLE_NAME)

# Build space context for clarification and planning
space_summary_list = space_summary_df.collect()
context = {}
for row in space_summary_list:
    space_id = row["space_id"]
    context[space_id] = row["searchable_content"]

# Define UC function names
UC_FUNCTION_NAMES = [
    f"{CATALOG}.{SCHEMA}.get_space_summary",
    f"{CATALOG}.{SCHEMA}.get_table_overview",
    f"{CATALOG}.{SCHEMA}.get_column_detail",
    f"{CATALOG}.{SCHEMA}.get_space_details",
]

########################################
# SQL Execution Tool
########################################

def execute_sql_on_delta_tables(
    sql_query: str,
    max_rows: int = 100,
    return_format: str = "dict"
) -> Dict[str, Any]:
    """
    Execute SQL query on delta tables and return formatted results.
    
    Args:
        sql_query: The SQL query to execute (can be raw SQL or contain markdown code blocks)
        max_rows: Maximum number of rows to return (default: 100)
        return_format: Format of the result - "dict", "dataframe", "json", or "markdown"
    
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
    import pandas as pd
    
    spark = SparkSession.builder.getOrCreate()
    
    # Step 1: Extract SQL from markdown code blocks if present
    if sql_query and isinstance(sql_query, dict) and "messages" in sql_query:
        sql_query = sql_query["messages"][-1].content
    
    extracted_sql = sql_query.strip()
    
    if "```sql" in extracted_sql.lower():
        sql_match = re.search(r'```sql\s*(.*?)\s*```', extracted_sql, re.IGNORECASE | re.DOTALL)
        if sql_match:
            extracted_sql = sql_match.group(1).strip()
    elif "```" in extracted_sql:
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
        if return_format == "dataframe":
            result_data = df.toPandas()
        elif return_format == "json":
            result_data = df.toJSON().collect()
        elif return_format == "markdown":
            pandas_df = df.toPandas()
            result_data = pandas_df.to_markdown(index=False)
        else:  # dict (default)
            result_data = [row.asDict() for row in results_list]
        
        # Step 6: Display preview
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


# Create SQL execution tool
from langchain_core.tools import tool

@tool("execute_sql_tool")
def execute_sql_tool(sql_query: str, max_rows: int = 100) -> str:
    """
    Execute SQL query on delta tables and return results.
    
    Args:
        sql_query: The SQL query to execute
        max_rows: Maximum number of rows to return (default: 100)
    
    Returns:
        JSON string with execution results
    """
    result = execute_sql_on_delta_tables(sql_query, max_rows, return_format="dict")
    return json.dumps(result, indent=2, default=str)


########################################
# Create Genie Route Agent with Genie Tools
########################################

def create_genie_route_agent(llm: Runnable, genie_agent_tools: list) -> Runnable:
    """Create SQL synthesis agent for genie route using Genie agent tools."""
    
    system_prompt = """You are a SQL synthesis agent for the genie route, which routes queries to Genie Agents.
    
    The Plan given to you is a JSON:
    {
    'original_query': 'The User's Question',
    'vector_search_relevant_spaces_info': [{'space_id': 'space_id_1', 'space_title': 'space_title_1'}, ...],
    "question_clear": true,
    "sub_questions": ["sub-question 1", "sub-question 2", ...],
    "requires_multiple_spaces": true/false,
    "relevant_space_ids": ["space_id_1", "space_id_2", ...],
    "requires_join": true/false,
    "join_strategy": "table_route" or "genie_route" or null,
    "execution_plan": "Brief description of execution plan",
    "genie_route_plan": {'space_id_1':'partial_question_1', 'space_id_2':'partial_question_2', ...} or null,
    }
    
    ## Tool Calling Plan:
    1. Under the key 'genie_route_plan' in the JSON, extract 'partial_question_1' and feed to the right Genie Agent tool of 'space_id_1'
    2. Asynchronously send all other partial_questions to the corresponding Genie Agent tools accordingly
    3. Locate the proper Genie Agent Tool by searching the 'space_id' in the tool's description
    4. After each Genie agent returns result, extract only the SQL string from the output
    5. If you find you are missing necessary analytical components, try other likely Genie agents
    
    ## Disaster Recovery (DR) Plan:
    1. If one Genie agent tool fails to generate a SQL query, allow retry AS IS only one time
    2. If fail again, try to reframe the partial question according to the error msg returned by the genie tool
    3. If fail again, return response as is
    
    ## Overall SQL Synthesis Plan:
    Combine all the SQL pieces into a single SQL query, and return the final SQL query.
    
    OUTPUT REQUIREMENTS:
    - Generate complete, executable SQL with:
      * Proper JOINs based on execution plan strategy
      * WHERE clauses for filtering
      * Appropriate aggregations
      * Clear column aliases
      * Always use real column name existed in the data, never make up one
    - Return ONLY the SQL query without explanations or markdown formatting
    - If SQL cannot be generated, explain what metadata is missing
    """
    
    return create_agent(
        model=llm,
        tools=genie_agent_tools,
        name="sql_synthesis_genie_route",
        system_prompt=system_prompt
    )


########################################
# Create All Sub-Agents with Individual LLMs
########################################

# Keep IN_CODE_AGENTS empty - all agents now created individually with their own LLMs
IN_CODE_AGENTS = []

# Create LLMs for different agents (can be customized per agent)
llm_clarification = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING, temperature=0.1)  # Fast model for simple task
llm_planning = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING, temperature=0.1)
llm_table_route = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME, temperature=0.1)  # Powerful model for SQL synthesis
llm_genie_route = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING, temperature=0.1)
llm_execution = ChatDatabricks(endpoint=LLM_ENDPOINT_PLANNING, temperature=0.1)

# 1. Clarification Agent
clarification_agent = create_agent(
    model=llm_clarification,
    tools=[],
    name="clarification_agent",
    system_prompt=f"""
    You are a clarification agent. Your job is to analyze user queries and determine if they are clear enough to execute.
    
    Available Genie Spaces:
    {json.dumps(context, indent=2)}
    
    If the query is clear, respond with:
    {{"question_clear": true}}
    
    If clarification is needed, respond with:
    {{
        "question_clear": false,
        "clarification_needed": "explanation of what's unclear",
        "clarification_options": ["option 1", "option 2", "option 3"]
    }}
    
    Only return valid JSON, no explanations.
    """
)
clarification_agent.name = "clarification_agent"
clarification_agent.description = "Validates query clarity and requests clarification if the user query is ambiguous or missing information."

# 2. Planning Agent
planning_agent = create_agent(
    model=llm_planning,
    tools=[],
    name="planning_agent",
    system_prompt=f"""
    You are a query planning expert. Analyze user questions and create detailed execution plans.
    
    You will receive:
    1. The user's query
    2. Relevant Genie spaces from vector search
    
    Determine:
    1. Sub-questions or analytical components
    2. How many Genie spaces are needed
    3. Whether JOIN is required across spaces
    4. Best strategy: "table_route" (direct SQL) or "genie_route" (query Genie agents separately)
    5. Create genie_route_plan: {{'space_id_1': 'partial_question_1', 'space_id_2': 'partial_question_2'}}
    
    Return JSON:
    {{
        "original_query": "user query",
        "vector_search_relevant_spaces_info": [(space_id, space_title), ...],
        "question_clear": true,
        "sub_questions": ["sub-question 1", "sub-question 2"],
        "requires_multiple_spaces": true/false,
        "relevant_space_ids": ["space_id_1", "space_id_2"],
        "requires_join": true/false,
        "join_strategy": "table_route" or "genie_route" or null,
        "execution_plan": "Brief description",
        "genie_route_plan": {{'space_id_1': 'partial_question_1'}} or null
    }}
    
    Only return valid JSON, no explanations.
    """
)
planning_agent.name = "planning_agent"
planning_agent.description = "Analyzes queries, searches for relevant Genie spaces, identifies join requirements, and creates execution plans (table_route or genie_route)."

# 3. SQL Synthesis Table Route Agent
uc_toolkit_table_route = UCFunctionToolkit(function_names=UC_FUNCTION_NAMES)
TOOLS.extend(uc_toolkit_table_route.tools)

sql_synthesis_table_route = create_agent(
    model=llm_table_route,
    tools=uc_toolkit_table_route.tools,
    name="sql_synthesis_table_route",
    system_prompt="""
    You are a specialized SQL synthesis agent for the table route.
    
    WORKFLOW:
    1. Review the execution plan from the planning agent
    2. If metadata is sufficient → Generate SQL immediately
    3. If insufficient, call UC function tools in this order:
       a) get_space_summary for space information
       b) get_table_overview for table schemas
       c) get_column_detail for specific column details
       d) get_space_details as last resort (token intensive)
    
    UC FUNCTION USAGE:
    - Pass arguments as JSON array strings: '["space_id_1", "space_id_2"]'
    - Use 'null' to get all entities under parent level
    - Query minimal sufficient metadata only
    
    OUTPUT:
    - Complete, executable SQL with proper JOINs, WHERE clauses, aggregations
    - Use only real column names from metadata
    - Return ONLY the SQL query without markdown formatting
    """
)
sql_synthesis_table_route.name = "sql_synthesis_table_route"
sql_synthesis_table_route.description = "Generates SQL queries using UC metadata functions (table route). Best for queries requiring joins across multiple tables."

# 4. SQL Synthesis Genie Route Agent (with Genie tools)
genie_route_agent = create_genie_route_agent(llm_genie_route, genie_agent_tools)
genie_route_agent.name = "sql_synthesis_genie_route"
genie_route_agent.description = "Generates SQL by routing queries to individual Genie agents and combining their SQL outputs. Use when join_strategy is 'genie_route'."

# 5. SQL Execution Agent
TOOLS.append(execute_sql_tool)
sql_execution_agent = create_agent(
    model=llm_execution,
    tools=[execute_sql_tool],
    name="sql_execution_agent",
    system_prompt="""
    You are a SQL execution agent. Your job is to:
    1. Take SQL queries from the SQL synthesis agents
    2. Execute them on delta tables using the execute_sql_tool
    3. Return formatted results with execution status
    
    IMPORTANT: Always use the execute_sql_tool to run SQL queries.
    
    When you receive a SQL query:
    - Extract the SQL if it's in markdown formatting or JSON
    - Call execute_sql_tool with the SQL query
    - Parse and present the results clearly
    
    The tool returns a JSON with:
      * success: boolean indicating if execution succeeded
      * sql: the executed query
      * result: query results (list of dictionaries)
      * row_count: number of rows returned
      * columns: list of column names
      * error: error message if failed
    
    Present the results in a user-friendly format including:
    - Success status
    - SQL that was executed
    - Results summary (row count, columns)
    - Sample of the data (if successful)
    - Error details (if failed)
    """
)
sql_execution_agent.name = "sql_execution_agent"
sql_execution_agent.description = "Executes SQL queries on delta tables and returns structured results with success status, data, and metadata."

# Collect all agents for supervisor
ALL_AGENTS = [
    clarification_agent,
    planning_agent,
    sql_synthesis_table_route,
    genie_route_agent,
    sql_execution_agent
]

#################################################
# Create supervisor and set up MLflow for tracing
#################################################

# Create supervisor with all agents
supervisor = create_langgraph_supervisor(
    llm, 
    IN_CODE_AGENTS,  # Empty list now
    additional_agents=ALL_AGENTS  # All agents with their own LLMs
)

mlflow.langchain.autolog()
AGENT = LangGraphResponsesAgent(supervisor)
mlflow.models.set_model(AGENT)
