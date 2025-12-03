"""
Multi-Agent System for Cross-Domain Genie Space Queries

This module implements a sophisticated multi-agent system using LangGraph and 
Databricks ResponseAgent integration for answering questions across multiple 
Genie spaces.

Architecture:
- SupervisorAgent: Routes queries to appropriate sub-agents
- ThinkingPlanningAgent: Analyzes queries and plans execution strategy
- GenieAgents: Query individual Genie spaces
- SQLSynthesisAgent: Combines SQL queries from multiple Genie agents
- SQLExecutionAgent: Executes synthesized SQL queries
"""

import json
import os
from typing import Generator, Literal, List, Dict, Any, Optional
from uuid import uuid4
import asyncio

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


class ServedSubAgent(BaseModel):
    """Configuration for an externally served agent."""
    endpoint_name: str
    name: str
    task: Literal["agent/v1/responses", "agent/v1/chat", "agent/v2/chat"]
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
        """Search for relevant Genie spaces using vector search."""
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        
        result_df = spark.sql(f"""
            SELECT space_id, space_title, score
            FROM {self.vector_search_function}('{query}', {num_results})
        """)
        
        return [row.asDict() for row in result_df.collect()]
    
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
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process messages and return query plan."""
        messages = state.get("messages", [])
        last_message = messages[-1].content if messages else ""
        
        plan = self.analyze_query(last_message)
        
        # Add plan to state
        response_msg = AIMessage(
            content=json.dumps(plan.model_dump(), indent=2),
            name=self.name
        )
        
        return {"messages": [response_msg], "query_plan": plan.model_dump()}


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
        
        Args:
            query: Original user question
            table_metadata: Metadata about relevant tables
            
        Returns:
            Synthesized SQL query
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
        
        Args:
            query: Original user question
            sub_queries_with_sql: List of {"sub_question": str, "sql": str}
            
        Returns:
            Combined SQL query
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
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process state and synthesize SQL."""
        query_plan = state.get("query_plan", {})
        messages = state.get("messages", [])
        
        # Determine which route to take
        if query_plan.get("join_strategy") == "fast_route":
            # Use metadata to synthesize SQL directly
            table_metadata = state.get("table_metadata", [])
            sql = self.synthesize_sql_fast_route(
                messages[0].content,
                table_metadata
            )
        else:
            # Combine SQL from Genie agents
            sub_results = state.get("genie_results", [])
            sql = self.synthesize_sql_slow_route(
                messages[0].content,
                sub_results
            )
        
        response_msg = AIMessage(
            content=f"Synthesized SQL:\n```sql\n{sql}\n```",
            name=self.name
        )
        
        return {"messages": [response_msg], "synthesized_sql": sql}


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
        
        Args:
            sql: SQL query to execute
            
        Returns:
            Dictionary with results and metadata
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
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute synthesized SQL."""
        sql = state.get("synthesized_sql", "")
        
        if not sql:
            result = {
                "success": False,
                "error": "No SQL query to execute"
            }
        else:
            result = self.execute_sql(sql)
        
        if result["success"]:
            content = f"Query executed successfully!\n\n{result['result']}"
        else:
            content = f"Error executing query:\n{result['error']}"
        
        response_msg = AIMessage(content=content, name=self.name)
        
        return {"messages": [response_msg], "execution_result": result}


########################################
# Create LangGraph Supervisor
########################################

TOOLS = []


def stringify_content(state):
    """Helper to stringify message content if it's a list."""
    msgs = state["messages"]
    if isinstance(msgs[-1].content, list):
        msgs[-1].content = json.dumps(msgs[-1].content, indent=4)
    return {"messages": msgs}


def create_langgraph_supervisor(
    llm: Runnable,
    genie_spaces: List[Genie] = [],
    in_code_agents: List[InCodeSubAgent] = [],
    vector_search_function: str = None,
):
    """
    Create a LangGraph supervisor for the multi-agent system.
    
    Args:
        llm: Language model for agents
        genie_spaces: List of Genie space configurations
        in_code_agents: List of in-code agent configurations
        vector_search_function: UC function name for vector search
    """
    agents = []
    agent_descriptions = ""
    
    # Add Thinking and Planning Agent
    thinking_agent = ThinkingPlanningAgent(llm, vector_search_function)
    agents.append(thinking_agent)
    agent_descriptions += (
        f"- {thinking_agent.name}: Analyzes queries, breaks them into sub-tasks, "
        "and determines execution strategy\n"
    )
    
    # Add Genie Space Agents
    for genie in genie_spaces:
        agent_descriptions += f"- {genie.name}: {genie.description}\n"
        genie_agent = GenieAgent(
            genie_space_id=genie.space_id,
            genie_agent_name=genie.name,
            description=genie.description,
            include_context=True  # Include reasoning and SQL
        )
        genie_agent.name = genie.name
        agents.append(genie_agent)
    
    # Add SQL Synthesis Agent
    sql_synthesis_agent = SQLSynthesisAgent(llm)
    agents.append(sql_synthesis_agent)
    agent_descriptions += (
        f"- {sql_synthesis_agent.name}: Synthesizes SQL queries across multiple "
        "tables or combines results from Genie agents\n"
    )
    
    # Add SQL Execution Agent
    sql_exec_agent = SQLExecutionAgent()
    agents.append(sql_exec_agent)
    agent_descriptions += (
        f"- {sql_exec_agent.name}: Executes SQL queries and returns results\n"
    )
    
    # Add in-code tool-calling agents
    for agent in in_code_agents:
        agent_descriptions += f"- {agent.name}: {agent.description}\n"
        uc_toolkit = UCFunctionToolkit(function_names=agent.tools)
        TOOLS.extend(uc_toolkit.tools)
        agents.append(create_agent(llm, tools=uc_toolkit.tools, name=agent.name))
    
    # Supervisor prompt
    prompt = f"""
    You are a supervisor in a multi-agent system designed to answer complex questions
    across multiple Genie spaces (data sources).
    
    **Your workflow:**
    
    1. **Understand**: Read the user's question carefully
    2. **Plan**: Call ThinkingPlanning agent to analyze the question
    3. **Check Clarity**: If question needs clarification, ask user for clarification
    4. **Route Execution**:
       - **Single Space**: If one Genie can answer, call that Genie agent
       - **Multiple Spaces (No Join)**: Call each relevant Genie, then verbally merge answers
       - **Multiple Spaces (With Join)**:
         * **Fast Route**: Call SQLSynthesis with metadata, then SQLExecution
         * **Slow Route**: Call each Genie for sub-questions, SQLSynthesis combines, SQLExecution runs
    5. **Respond**: Provide a clear, comprehensive answer with:
       - Thinking process
       - SQL query used (if applicable)
       - Results
    
    **Available Agents:**
    {agent_descriptions}
    
    **Important Guidelines:**
    - Always start with ThinkingPlanning agent
    - Show your reasoning process transparently
    - For multi-space joins, prefer fast route when possible
    - Ensure patient counts < 10 are returned as "Count is less than 10"
    - Never show individual patient_ids, only counts
    - Be thorough and accurate
    
    Let's help the user find the answer!
    """
    
    return create_supervisor(
        agents=agents,
        model=llm,
        prompt=prompt,
        add_handoff_messages=False,
        output_mode="full_history",
    ).compile()


########################################
# ResponsesAgent Wrapper
########################################

class LangGraphResponsesAgent(ResponsesAgent):
    """Wraps LangGraph supervisor as a ResponsesAgent for MLflow deployment."""
    
    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """Synchronous prediction."""
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done"
        ]
        return ResponsesAgentResponse(
            output=outputs, 
            custom_outputs=request.custom_inputs
        )

    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        """Streaming prediction."""
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        first_message = True
        seen_ids = set()

        for _, events in self.agent.stream(
            {"messages": cc_msgs}, 
            stream_mode=["updates"]
        ):
            new_msgs = [
                msg
                for v in events.values()
                for msg in v.get("messages", [])
                if msg.id not in seen_ids
            ]
            
            if first_message:
                seen_ids.update(msg.id for msg in new_msgs[:len(cc_msgs)])
                new_msgs = new_msgs[len(cc_msgs):]
                first_message = False
            else:
                seen_ids.update(msg.id for msg in new_msgs)
                node_name = tuple(events.keys())[0]
                yield ResponsesAgentStreamEvent(
                    type="response.output_item.done",
                    item=self.create_text_output_item(
                        text=f"<name>{node_name}</name>",
                        id=str(uuid4())
                    ),
                )
            
            if len(new_msgs) > 0:
                yield from output_to_responses_items_stream(new_msgs)


########################################
# Configuration
########################################

# LLM Endpoint
LLM_ENDPOINT_NAME = os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-4-5")
llm = ChatDatabricks(endpoint=LLM_ENDPOINT_NAME)

# Vector Search Function
VECTOR_SEARCH_FUNCTION = os.getenv(
    "VECTOR_SEARCH_FUNCTION",
    "yyang.multi_agent_genie.search_genie_spaces"
)

# Genie Spaces (populated from vector search at runtime)
# For now, configure known spaces
GENIE_SPACES = [
    Genie(
        space_id="01f072dbd668159d99934dfd3b17f544",
        name="GENIE_PATIENT",
        description=(
            "Patient demographics, age, ECOG scores, appointments, and insurance data. "
            "Use this for questions about patient age, location, demographics, "
            "appointments with doctors, and insurance coverage."
        ),
    ),
    Genie(
        space_id="01f08f4d1f5f172ea825ec8c9a3c6064",
        name="MEDICATIONS",
        description=(
            "Patient medications including drug names, medication class, dates ordered "
            "and discontinued, route, strength, and dosage. Use this for questions about "
            "medications, prescriptions, and drugs patients are taking."
        ),
    ),
    Genie(
        space_id="01f073c5476313fe8f51966e3ce85bd7",
        name="GENIE_DIAGNOSIS_STAGING",
        description=(
            "Patient diagnoses including primary cancer diagnoses, metastatic cancer, "
            "comorbidities, and staging details. Use this for questions about cancer "
            "types, diagnosis, disease staging, and patient conditions."
        ),
    ),
    Genie(
        space_id="01f07795f6981dc4a99d62c9fc7c2caa",
        name="GENIE_TREATMENT",
        description=(
            "Patient treatments including surgeries, diagnostic procedures, radiological "
            "testing, cancer treatment plans, and bone marrow/stem cell transplants. "
            "Use this for questions about treatments, procedures, and interventions."
        ),
    ),
    Genie(
        space_id="01f08a9fd9ca125a986d01c1a7a5b2fe",
        name="GENIE_LABORATORY_BIOMARKERS",
        description=(
            "Laboratory testing and genomic testing for cancer biomarkers including "
            "testing dates, results, and contextual information. Use this for questions "
            "about lab results, biomarkers, and genomic testing."
        ),
    ),
]

# In-code tool agents
IN_CODE_AGENTS = [
    InCodeSubAgent(
        tools=["system.ai.*"],
        name="CodeExecutionAgent",
        description=(
            "Specializes in solving programming challenges, generating code snippets, "
            "debugging issues, and explaining complex coding concepts."
        ),
    )
]

########################################
# Create and Configure Agent
########################################

supervisor = create_langgraph_supervisor(
    llm=llm,
    genie_spaces=GENIE_SPACES,
    in_code_agents=IN_CODE_AGENTS,
    vector_search_function=VECTOR_SEARCH_FUNCTION,
)

# Enable MLflow autologging
mlflow.langchain.autolog()

# Create ResponsesAgent wrapper
AGENT = LangGraphResponsesAgent(supervisor)

# Set as the model for MLflow
mlflow.models.set_model(AGENT)

