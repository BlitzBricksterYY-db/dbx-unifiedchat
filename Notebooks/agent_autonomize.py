"""
Multi-Agent System with Supervisor-Based Orchestration using UC Functions

This module implements a supervisor-based pattern using LangGraph's create_supervisor()
for dynamically coordinating multiple agents. All custom agent logic is exposed through
Unity Catalog Functions, making them accessible as tools to the LangGraph supervisor.

Architecture:
- Supervisor: LangGraph supervisor created via create_supervisor().compile()
- QueryPlanning Agent: Uses UC functions for query analysis and planning
- SQLAgent: Uses UC functions for SQL synthesis and execution  
- ResultsMerger Agent: Uses UC functions for merging multi-agent results
- Genie Agents: Query individual Genie spaces for domain-specific data

Key Features:
- Custom agent logic exposed as Unity Catalog Functions
- Full LangGraph integration with proper tool calling
- MLflow tracing for all UC function invocations
- Supervisor dynamically routes queries to appropriate agents
- Supports complex workflows: planning → execution → synthesis → response

UC Functions (defined in agent_uc_functions.py):
- analyze_query_plan: Query analysis and execution planning
- synthesize_sql_fast_route: Direct SQL synthesis across tables
- synthesize_sql_slow_route: Combine SQL from multiple sources
- execute_sql_query: Execute SQL and return formatted results
- get_table_metadata: Retrieve table schemas and relationships
- verbal_merge_results: Merge narrative answers from multiple agents
"""

import json
import os
from typing import Generator, Literal, List, Dict, Any, Optional
from uuid import uuid4

import mlflow
from databricks_langchain import (
    ChatDatabricks,
    DatabricksFunctionClient,
    UCFunctionToolkit,
    set_uc_function_client,
)
from databricks_langchain.genie import GenieAgent
from langchain_core.runnables import Runnable
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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

# Initialize UC Function Client
client = DatabricksFunctionClient()
set_uc_function_client(client)

########################################
# Configuration Models
########################################

GENIE = "genie"
THINKING_PLANNING = "thinking_planning"
SQL_SYNTHESIS = "sql_synthesis"
SQL_EXECUTION = "sql_execution"


class Genie(BaseModel):
    """Configuration for a Genie Space agent."""
    space_id: str
    name: str
    task: str = GENIE
    description: str


class InCodeSubAgent(BaseModel):
    """Configuration for an in-code tool-calling agent."""
    tools: list[str]
    name: str
    description: str


class QueryPlan(BaseModel):
    """Structured output for query planning."""
    question_clear: bool
    clarification_needed: Optional[str] = None
    clarification_options: Optional[List[str]] = None
    sub_questions: Optional[List[str]] = None
    requires_multiple_spaces: bool = False
    relevant_space_ids: Optional[List[str]] = None
    requires_join: bool = False
    join_strategy: Optional[str] = None  # "fast_route" or "slow_route"
    execution_plan: Optional[str] = None


########################################
# Thinking and Planning Agent
########################################

class ThinkingPlanningAgent:
    """
    Agent responsible for analyzing queries, breaking them down into sub-tasks,
    and determining the best execution strategy.
    """
    
    def __init__(self, llm: Runnable, vector_search_function_name: str):
        self.llm = llm
        self.vector_search_function = vector_search_function_name
        self.name = "ThinkingPlanning"
    
    def _search_relevant_spaces(self, query: str, num_results: int = 5) -> List[Dict]:
        """Search for relevant Genie spaces using AI Bridge VectorSearchRetrieverTool."""
        from databricks_langchain import VectorSearchRetrieverTool
        
        # Extract index name from function name
        parts = self.vector_search_function.split('.')
        catalog = parts[0]
        schema = parts[1]
        index_name = f"{catalog}.{schema}.enriched_genie_docs_chunks_vs_index"
        
        # Create VectorSearchRetrieverTool with filter for space_summary chunks
        vs_tool = VectorSearchRetrieverTool(
            index_name=index_name,
            num_results=num_results,
            filters={"chunk_type": "space_summary"},
            query_type="ANN",
        )
        
        # Invoke the tool to get results
        docs = vs_tool.invoke({"query": query})
        
        # Extract space information from document metadata
        relevant_spaces = []
        for doc in docs:
            relevant_spaces.append({
                "space_id": doc.metadata.get("space_id", ""),
                "space_title": doc.metadata.get("space_title", ""),
                "score": doc.metadata.get("score", 0.0)
            })
        
        return relevant_spaces
    
    def analyze_query(self, query: str) -> QueryPlan:
        """
        Analyze a user query and create an execution plan.
        
        Returns:
            QueryPlan with analysis results and execution strategy
        """
        # First, check if question is clear
        clarity_prompt = f"""
        Analyze the following question for clarity and specificity:
        
        Question: {query}
        
        Determine if:
        1. The question is clear and answerable as-is
        2. The question needs clarification
        
        If clarification is needed, provide:
        - A brief explanation of what's unclear
        - 2-3 specific clarification options the user can choose from
        
        Return your analysis as JSON:
        {{
            "question_clear": true/false,
            "clarification_needed": "explanation if unclear",
            "clarification_options": ["option 1", "option 2", "option 3"]
        }}
        
        Only return valid JSON, no explanations.
        """
        
        clarity_response = self.llm.invoke(clarity_prompt)
        clarity_result = json.loads(clarity_response.content)
        
        if not clarity_result.get("question_clear", False):
            return QueryPlan(
                question_clear=False,
                clarification_needed=clarity_result.get("clarification_needed"),
                clarification_options=clarity_result.get("clarification_options", [])
            )
        
        # Question is clear, proceed with planning
        # Search for relevant Genie spaces
        relevant_spaces = self._search_relevant_spaces(query, num_results=5)
        
        # Analyze query structure and requirements
        planning_prompt = f"""
        You are a query planning expert. Analyze the following question and create an execution plan.
        
        Question: {query}
        
        Potentially relevant Genie spaces:
        {json.dumps(relevant_spaces, indent=2)}
        
        Break down the question and determine:
        1. What are the sub-questions or analytical components?
        2. How many Genie spaces are needed to answer completely? (List their space_ids)
        3. If multiple spaces are needed, do we need to JOIN data across them?
        4. If JOIN is needed, what's the best strategy:
           - "fast_route": Directly synthesize SQL across multiple tables
           - "slow_route": Query each space separately, then combine results
        5. If no JOIN needed, can answers be verbally merged?
        
        Return your analysis as JSON:
        {{
            "question_clear": true,
            "sub_questions": ["sub-question 1", "sub-question 2", ...],
            "requires_multiple_spaces": true/false,
            "relevant_space_ids": ["space_id_1", "space_id_2", ...],
            "requires_join": true/false,
            "join_strategy": "fast_route" or "slow_route" or null,
            "execution_plan": "Brief description of execution plan"
        }}
        
        Only return valid JSON, no explanations.
        """
        
        planning_response = self.llm.invoke(planning_prompt)
        plan_result = json.loads(planning_response.content)
        
        return QueryPlan(**plan_result)


########################################
# SQL Synthesis Agent
########################################

class SQLSynthesisAgent:
    """
    Agent responsible for synthesizing SQL queries, either from scratch
    or by combining SQL from multiple Genie agents.
    """
    
    def __init__(self, llm: Runnable):
        self.llm = llm
        self.name = "SQLSynthesis"
    
    def synthesize_sql_fast_route(
        self, 
        query: str, 
        table_metadata: List[Dict]
    ) -> str:
        """
        Fast route: Directly synthesize SQL across multiple tables.
        """
        prompt = f"""
        You are an expert SQL developer. Generate a SQL query to answer the following question
        using the available tables.
        
        Question: {query}
        
        Available Tables and Metadata:
        {json.dumps(table_metadata, indent=2)}
        
        Generate a complete, executable SQL query. Include:
        - Proper JOINs where needed
        - WHERE clauses for filtering
        - Appropriate aggregations
        - Column aliases for clarity
        
        Return ONLY the SQL query, no explanations.
        """
        
        response = self.llm.invoke(prompt)
        return response.content.strip()
    
    def synthesize_sql_slow_route(
        self,
        query: str,
        sub_queries_with_sql: List[Dict[str, str]]
    ) -> str:
        """
        Slow route: Combine SQL from multiple Genie agents into a unified query.
        """
        prompt = f"""
        You are an expert SQL developer. Combine the following SQL queries into a single query
        that answers the original question.
        
        Original Question: {query}
        
        Sub-queries and their SQL:
        {json.dumps(sub_queries_with_sql, indent=2)}
        
        Generate a unified SQL query that:
        - Combines results from sub-queries using JOINs, CTEs, or subqueries
        - Ensures proper correlation between results
        - Maintains data integrity
        - Returns the final answer to the original question
        
        Return ONLY the SQL query, no explanations.
        """
        
        response = self.llm.invoke(prompt)
        return response.content.strip()


########################################
# SQL Execution Agent
########################################

class SQLExecutionAgent:
    """
    Agent responsible for executing SQL queries and returning results.
    """
    
    def __init__(self):
        self.name = "SQLExecution"
    
    def execute_sql(self, sql: str) -> Dict[str, Any]:
        """
        Execute SQL query and return results.
        """
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        
        try:
            result_df = spark.sql(sql)
            
            # Convert to markdown table for display
            pandas_df = result_df.toPandas()
            markdown_table = pandas_df.to_markdown(index=False)
            
            return {
                "success": True,
                "result": markdown_table,
                "row_count": len(pandas_df),
                "columns": list(pandas_df.columns)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "sql": sql
            }


########################################
# Helper Functions for Agent Integration
########################################

def stringify_content(state):
    """Helper to stringify content for agent communication."""
    msgs = state["messages"]
    if isinstance(msgs[-1].content, list):
        msgs[-1].content = json.dumps(msgs[-1].content, indent=4)
    return {"messages": msgs}


########################################
# ResponsesAgent Wrapper
########################################

class LangGraphResponsesAgent(ResponsesAgent):
    """
    MLflow 3.7.0 ResponsesAgent wrapper for LangGraph CompiledStateGraph.
    
    This wraps the compiled supervisor graph to provide MLflow-compatible serving.
    """
    
    def __init__(self, agent: CompiledStateGraph):
        """
        Initialize with a CompiledStateGraph instance.
        
        Args:
            agent: CompiledStateGraph from create_supervisor().compile()
        """
        self.agent = agent

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """
        Synchronous prediction method.
        
        Args:
            request: ResponsesAgentRequest with input messages
            
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
        Streaming prediction method.
        
        Streams updates from the LangGraph execution.
        """
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        first_message = True
        seen_ids = set()

        # Stream updates from the graph execution
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
                node_name = tuple(events.keys())[0]  # assumes one name per node
                yield ResponsesAgentStreamEvent(
                    type="response.output_item.done",
                    item=self.create_text_output_item(
                        text=f"<name>{node_name}</name>", id=str(uuid4())
                    ),
                )
            if len(new_msgs) > 0:
                yield from output_to_responses_items_stream(new_msgs)


########################################
# Factory Function - Create LangGraph Supervisor
########################################

def create_langgraph_supervisor(
    llm: Runnable,
    genie_spaces: List[Genie],
    uc_function_catalog: str = "yyang",
    uc_function_schema: str = "multi_agent_genie",
    in_code_agents: List[InCodeSubAgent] = [],
) -> CompiledStateGraph:
    """
    Factory function to create a LangGraph supervisor with all sub-agents.
    
    Args:
        llm: Language model for supervisor
        genie_spaces: List of Genie space configurations
        uc_function_catalog: UC catalog containing agent functions
        uc_function_schema: UC schema containing agent functions
        in_code_agents: Optional list of in-code tool-calling agents
        
    Returns:
        Compiled LangGraph supervisor ready for use
    """
    agents = []
    agent_descriptions = ""
    
    # Create Query Planning Agent using UC functions
    # This agent has access to analyze_query_plan and get_table_metadata functions
    planning_toolkit = UCFunctionToolkit(function_names=[
        f"{uc_function_catalog}.{uc_function_schema}.analyze_query_plan",
        f"{uc_function_catalog}.{uc_function_schema}.get_table_metadata",
    ])
    planning_agent = create_agent(
        llm,
        tools=planning_toolkit.tools,
        name="QueryPlanning"
    )
    agents.append(planning_agent)
    agent_descriptions += (
        "- QueryPlanning: Analyzes queries, breaks them down into sub-tasks, "
        "determines execution strategy, and searches for relevant Genie spaces using vector search. "
        "Has access to analyze_query_plan() and get_table_metadata() functions.\n"
    )
    
    # Create SQL Synthesis and Execution Agent using UC functions
    # This agent can synthesize SQL (fast/slow route) and execute queries
    sql_toolkit = UCFunctionToolkit(function_names=[
        f"{uc_function_catalog}.{uc_function_schema}.synthesize_sql_fast_route",
        f"{uc_function_catalog}.{uc_function_schema}.synthesize_sql_slow_route",
        f"{uc_function_catalog}.{uc_function_schema}.execute_sql_query",
    ])
    sql_agent = create_agent(
        llm,
        tools=sql_toolkit.tools,
        name="SQLAgent"
    )
    agents.append(sql_agent)
    agent_descriptions += (
        "- SQLAgent: Synthesizes and executes SQL queries. Can use fast route (direct SQL synthesis) "
        "or slow route (combine multiple queries). Has access to synthesize_sql_fast_route(), "
        "synthesize_sql_slow_route(), and execute_sql_query() functions.\n"
    )
    
    # Create Results Merging Agent using UC function
    merge_toolkit = UCFunctionToolkit(function_names=[
        f"{uc_function_catalog}.{uc_function_schema}.verbal_merge_results",
    ])
    merge_agent = create_agent(
        llm,
        tools=merge_toolkit.tools,
        name="ResultsMerger"
    )
    agents.append(merge_agent)
    agent_descriptions += (
        "- ResultsMerger: Merges results from multiple Genie agents into a cohesive answer. "
        "Has access to verbal_merge_results() function.\n"
    )
    
    # Process additional inline code agents (if any)
    for agent in in_code_agents:
        agent_descriptions += f"- {agent.name}: {agent.description}\n"
        uc_toolkit = UCFunctionToolkit(function_names=agent.tools)
        agents.append(create_agent(llm, tools=uc_toolkit.tools, name=agent.name))
    
    # Create Genie agents
    for genie in genie_spaces:
        agent_descriptions += f"- {genie.name}: {genie.description}\n"
        genie_agent = GenieAgent(
            genie_space_id=genie.space_id,
            genie_agent_name=genie.name,
            description=genie.description,
            include_context=True
        )
        genie_agent.name = genie.name
        agents.append(genie_agent)
    
    # Create supervisor prompt with enhanced instructions
    prompt = f"""
    You are a supervisor in a multi-agent system coordinating specialized agents to answer complex queries.

    **Workflow:**
    1. Understand the user's last request
    2. Read through the entire chat history
    3. If the answer to the user's last request is present in chat history, answer using information in the history
    4. If the answer is not in the history, follow the agent route: **plan → choose tools → execute → reflect → respond**
    5. **For complex queries, start with QueryPlanning agent:**
       - Delegate to QueryPlanning agent to analyze the query and create an execution plan
       - The plan will include: relevant space IDs, whether joins are needed, and execution strategy
    6. **Based on the plan or query type, delegate to appropriate agents:**
       - For single Genie space queries: delegate to the specific Genie agent (Provider Enrollment, Claims, or Diagnosiss and Procedures)
       - For multi-space queries without joins: delegate to multiple Genie agents, then use ResultsMerger to combine answers
       - For queries requiring SQL joins: delegate to SQLAgent to synthesize and execute combined SQL
    7. **Show your thinking process:** Explain which agents you're delegating to and why
    8. Provide a comprehensive, well-structured final answer to the user

    **Available Agents:**
    {agent_descriptions}

    **Key Guidelines:**
    - QueryPlanning agent is your strategic advisor - use it for complex/multi-domain queries
    - Genie agents have domain expertise - use them for data retrieval from their specific domains
    - SQLAgent can join data across domains - use it when you need integrated analysis
    - ResultsMerger combines narrative answers - use it when joining data isn't necessary but synthesis is
    - Always explain your agent delegation strategy to the user
    - Provide clear, accurate, and actionable responses
    """
    
    return create_supervisor(
        agents=agents,
        model=llm,
        prompt=prompt,
        add_handoff_messages=False,
        output_mode="full_history",
    ).compile()


########################################
# Configuration
########################################

# LLM Endpoint
LLM_ENDPOINT_NAME = os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-4-5")
llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME)

# Unity Catalog Configuration for Agent Functions
UC_FUNCTION_CATALOG = os.getenv("UC_FUNCTION_CATALOG", "yyang")
UC_FUNCTION_SCHEMA = os.getenv("UC_FUNCTION_SCHEMA", "multi_agent_genie")

# Genie Spaces Configuration
GENIE_SPACES = [
    Genie(
        space_id="01f0956a54af123e9cd23907e8167df9",
        name="Provider Enrollment",
        description=(
            "This agent can answer questions about provider and patient enrollment. "
            "This dataset contains two tables: provider and enrollment."
        ),
    ),
    Genie(
        space_id="01f0956a387714969edde65458dcc22a",
        name="Claims",
        description=(
            "This agent can answer questions about Medical and pharmacy claims."
        ),
    ), 
    Genie(
        space_id="01f0956a4b0512e2a8aa325ffbac821b",
        name="Diagnosiss and Procedures",
        description=(
            "This agent can answer questions about diagnosiss and procedures."
        ),
    ),
]

########################################
# Create Supervisor-Based Agent
########################################

# Optional: Add in-code agents with UC functions
IN_CODE_AGENTS = [
    # Uncomment to add code execution capabilities
    # InCodeSubAgent(
    #     tools=["system.ai.*"],
    #     name="code execution agent",
    #     description="The code execution agent specializes in solving programming challenges, "
    #                 "generating code snippets, debugging issues, and explaining complex coding concepts.",
    # )
]

def get_supervisor_agent():
    """Factory function to create the compiled supervisor graph."""
    return create_langgraph_supervisor(
        llm=llm,
        genie_spaces=GENIE_SPACES,
        uc_function_catalog=UC_FUNCTION_CATALOG,
        uc_function_schema=UC_FUNCTION_SCHEMA,
        in_code_agents=IN_CODE_AGENTS,
    )

# Create compiled supervisor graph
supervisor = get_supervisor_agent()

# Create MLflow 3.7.0 ResponsesAgent wrapper for deployment
AGENT = LangGraphResponsesAgent(agent=supervisor)

# Enable MLflow autologging for tracing
mlflow.langchain.autolog()

# Set the MLflow model for deployment
mlflow.models.set_model(AGENT)

