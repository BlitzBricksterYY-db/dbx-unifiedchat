# Databricks notebook source
# DBTITLE 1,Auto reload Local Package
# MAGIC %load_ext autoreload
# MAGIC %autoreload 2

# COMMAND ----------

# DBTITLE 1,📥⏳Install Packages
# MAGIC %pip install python-dotenv databricks-sdk databricks-sql-connector databricks-langchain[memory]==0.12.1 databricks-vectorsearch==0.63 databricks-agents mlflow[databricks]>=3.6.0

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# DBTITLE 1,Configuration
"""
Configuration loaded from config.py and .env file.
To update configuration, edit .env file instead of this notebook.

SQL_WAREHOUSE_ID CONFIGURATION:
Required for SQLExecutionAgent to execute queries via SQL Warehouse.

Development Environment:
- Set SQL_WAREHOUSE_ID in .env file: SQL_WAREHOUSE_ID=your-dev-warehouse-id
- Get warehouse ID from: SQL Warehouses UI → Click warehouse → Copy ID from URL or Details

Production Environment (Model Serving):
- Option 1: Set SQL_WAREHOUSE_ID in .env file (if same warehouse for dev/prod)
- Option 2: Configure via Model Serving endpoint environment variables:
  - Add environment variable: SQL_WAREHOUSE_ID=your-prod-warehouse-id
  - Or use secrets: SQL_WAREHOUSE_ID={{secrets/scope/warehouse_id_key}}
- The agent will use environment variables if available, falling back to .env

RELOADING CONFIGURATION AFTER CHANGING .env:
If you modify the .env file, you need to reload the configuration:
1. Change the line below from: config = get_config()
   To: config = get_config(reload=True)
2. Re-run this cell to reload all config values
3. Re-extract any config variables you need (CATALOG, SCHEMA, etc.)
"""

# Import centralized configuration
import sys
import os

# Add parent directory to path to import config
notebook_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
parent_dir = os.path.dirname(notebook_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from config import get_config

# Load configuration from .env
# NOTE: If you change .env file, call get_config(reload=True) to reload
# Example: config = get_config(reload=True)
config = get_config(reload=True)

# Extract configuration values
CATALOG = config.unity_catalog.catalog_name
SCHEMA = config.unity_catalog.schema_name
TABLE_NAME = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks"
VECTOR_SEARCH_INDEX = f"{CATALOG}.{SCHEMA}.enriched_genie_docs_chunks_vs_index"

# LLM Endpoints - Diversified by Agent Role for Optimal Speed/Accuracy Balance
# Each agent uses a model optimized for its specific task
LLM_ENDPOINT_CLARIFICATION = config.llm.clarification_endpoint
LLM_ENDPOINT_PLANNING = config.llm.planning_endpoint
LLM_ENDPOINT_SQL_SYNTHESIS_TABLE = config.llm.sql_synthesis_table_endpoint
LLM_ENDPOINT_SQL_SYNTHESIS_GENIE = config.llm.sql_synthesis_genie_endpoint
LLM_ENDPOINT_EXECUTION = config.llm.execution_endpoint
LLM_ENDPOINT_SUMMARIZE = config.llm.summarize_endpoint

# Lakebase configuration for state management (from .env)
LAKEBASE_INSTANCE_NAME = config.lakebase.instance_name
EMBEDDING_ENDPOINT = config.lakebase.embedding_endpoint
EMBEDDING_DIMS = config.lakebase.embedding_dims

# Table Metadata configuration (from .env)
SQL_WAREHOUSE_ID = config.table_metadata.sql_warehouse_id
GENIE_SPACE_ID = config.table_metadata.genie_space_ids

# Validate SQL_WAREHOUSE_ID is configured
if not SQL_WAREHOUSE_ID:
    print("⚠️ WARNING: SQL_WAREHOUSE_ID is not configured!")
    print("Set it in .env file: SQL_WAREHOUSE_ID=your-warehouse-id")
    print("Get warehouse ID from: SQL Warehouses UI → Click warehouse → Copy ID from URL or Details")
    print("Example: SQL_WAREHOUSE_ID=148ccb90800933a1")
    raise ValueError("SQL_WAREHOUSE_ID must be configured in .env file")

# Print configuration summary
config.print_summary()

# COMMAND ----------

# DBTITLE 1,ONE-TIME SETUP: Initialize Lakebase Tables for State Management
"""
IMPORTANT: Run this cell ONCE to set up Lakebase tables for state management.

This creates:
1. checkpoints table - For short-term memory (multi-turn conversations)
2. store table - For long-term memory (user preferences with semantic search)

Prerequisites:
- Lakebase instance must be created in: SQL Warehouses -> Lakebase Postgres -> Create database instance
- Update LAKEBASE_INSTANCE_NAME above with your instance name
"""

# Uncomment and run ONCE to initialize tables
# from databricks_langchain import CheckpointSaver, DatabricksStore
#
# print("Initializing Lakebase tables...")
# print(f"Instance: {LAKEBASE_INSTANCE_NAME}")
#
# # Setup checkpoint table for short-term memory
# with CheckpointSaver(instance_name=LAKEBASE_INSTANCE_NAME) as saver:
#     saver.setup()
#     print("✓ Checkpoint table created/verified")
#
# # Setup store table for long-term memory
# store = DatabricksStore(
#     instance_name=LAKEBASE_INSTANCE_NAME,
#     embedding_endpoint=EMBEDDING_ENDPOINT,
#     embedding_dims=EMBEDDING_DIMS,
# )
# store.setup()
# print("✓ Store table created/verified")
#
# print("\n✅ Lakebase tables are ready for state management!")
# print("="*80)

# COMMAND ----------

# DBTITLE 1,ONE-TIME SETUP: Register Unity Catalog Functions for Metadata Querying
# """
# Register UC functions that will be used as tools by the SQL Synthesis Agent.

# These UC functions query different levels of the enriched genie docs chunks table:
# 1. get_space_summary: High-level space information
# 2. get_table_overview: Table-level metadata
# 3. get_column_detail: Column-level metadata
# 4. get_space_details: Complete metadata (last resort - token intensive)

# All functions use LANGUAGE SQL for better performance and compatibility.
# """

# print("="*80)
# print("REGISTERING UNITY CATALOG FUNCTIONS")
# print("="*80)
# print(f"Target table: {TABLE_NAME}")
# print(f"Functions will be created in: {CATALOG}.{SCHEMA}")
# print("="*80)

# # Optional: Drop existing functions if you need to recreate them
# # Uncomment these lines if you need to drop and recreate the functions
# # spark.sql(f'DROP FUNCTION IF EXISTS {CATALOG}.{SCHEMA}.get_space_summary')
# # spark.sql(f'DROP FUNCTION IF EXISTS {CATALOG}.{SCHEMA}.get_table_overview')
# # spark.sql(f'DROP FUNCTION IF EXISTS {CATALOG}.{SCHEMA}.get_column_detail')
# # spark.sql(f'DROP FUNCTION IF EXISTS {CATALOG}.{SCHEMA}.get_space_details')

# # UC Function 1: get_space_summary (SQL scalar function)
# spark.sql(f"""
# CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.get_space_summary(
#     space_ids_json STRING DEFAULT 'null' COMMENT 'JSON array of space IDs to query, or "null" to retrieve all spaces. Example: ["space_1", "space_2"] or "null"'
# )
# RETURNS STRING
# LANGUAGE SQL
# COMMENT 'Get high-level summary of Genie spaces. Returns JSON with space summaries including chunk_id, chunk_type, space_title, and content.'
# RETURN
#     SELECT COALESCE(
#         to_json(
#             map_from_entries(
#                 collect_list(
#                     struct(
#                         space_id,
#                         named_struct(
#                             'chunk_id', chunk_id,
#                             'chunk_type', chunk_type,
#                             'space_title', space_title,
#                             'content', searchable_content
#                         )
#                     )
#                 )
#             )
#         ),
#         '{{}}'
#     ) as result
#     FROM {TABLE_NAME}
#     WHERE chunk_type = 'space_summary'
#     AND (
#         space_ids_json IS NULL 
#         OR TRIM(LOWER(space_ids_json)) IN ('null', 'none', '')
#         OR array_contains(from_json(space_ids_json, 'array<string>'), space_id)
#     )
# """)
# print("✓ Registered: get_space_summary")

# # UC Function 2: get_table_overview (SQL scalar function with grouping)
# spark.sql(f"""
# CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.get_table_overview(
#     space_ids_json STRING DEFAULT 'null' COMMENT 'JSON array of space IDs to query (required, prefer single space). Example: ["space_1"]',
#     table_names_json STRING DEFAULT 'null' COMMENT 'JSON array of table names to filter, or "null" for all tables in the specified spaces. Example: ["table1", "table2"] or "null"'
# )
# RETURNS STRING
# LANGUAGE SQL
# COMMENT 'Get table-level metadata for specific Genie spaces. Returns JSON with table metadata including chunk_id, chunk_type, table_name, and content grouped by space.'
# RETURN
#     SELECT COALESCE(
#         to_json(
#             map_from_entries(
#                 collect_list(
#                     struct(
#                         space_id,
#                         named_struct(
#                             'space_title', space_title,
#                             'tables', tables
#                         )
#                     )
#                 )
#             )
#         ),
#         '{{}}'
#     ) as result
#     FROM (
#         SELECT 
#             space_id,
#             first(space_title) as space_title,
#             collect_list(
#                 named_struct(
#                     'chunk_id', chunk_id,
#                     'chunk_type', chunk_type,
#                     'table_name', table_name,
#                     'content', searchable_content
#                 )
#             ) as tables
#         FROM {TABLE_NAME}
#         WHERE chunk_type = 'table_overview'
#         AND array_contains(from_json(space_ids_json, 'array<string>'), space_id)
#         AND (
#             table_names_json IS NULL 
#             OR TRIM(LOWER(table_names_json)) IN ('null', 'none', '')
#             OR array_contains(from_json(table_names_json, 'array<string>'), table_name)
#         )
#         GROUP BY space_id
#     )
# """)
# print("✓ Registered: get_table_overview")

# # UC Function 3: get_column_detail (SQL scalar function with grouping)
# spark.sql(f"""
# CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.get_column_detail(
#     space_ids_json STRING DEFAULT 'null' COMMENT 'JSON array of space IDs to query (required, prefer single space). Example: ["space_1"]',
#     table_names_json STRING DEFAULT 'null' COMMENT 'JSON array of table names to filter (required, prefer single table). Example: ["table1"]',
#     column_names_json STRING DEFAULT 'null' COMMENT 'JSON array of column names to filter, or "null" for all columns in the specified tables. Example: ["col1", "col2"] or "null"'
# )
# RETURNS STRING
# LANGUAGE SQL
# COMMENT 'Get column-level metadata for specific Genie spaces. Returns JSON with column metadata including chunk_id, chunk_type, table_name, column_name, and content grouped by space.'
# RETURN
#     SELECT COALESCE(
#         to_json(
#             map_from_entries(
#                 collect_list(
#                     struct(
#                         space_id,
#                         named_struct(
#                             'space_title', space_title,
#                             'columns', columns
#                         )
#                     )
#                 )
#             )
#         ),
#         '{{}}'
#     ) as result
#     FROM (
#         SELECT 
#             space_id,
#             first(space_title) as space_title,
#             collect_list(
#                 named_struct(
#                     'chunk_id', chunk_id,
#                     'chunk_type', chunk_type,
#                     'table_name', table_name,
#                     'column_name', column_name,
#                     'content', searchable_content
#                 )
#             ) as columns
#         FROM {TABLE_NAME}
#         WHERE chunk_type = 'column_detail'
#         AND array_contains(from_json(space_ids_json, 'array<string>'), space_id)
#         AND array_contains(from_json(table_names_json, 'array<string>'), table_name)
#         AND (
#             column_names_json IS NULL 
#             OR TRIM(LOWER(column_names_json)) IN ('null', 'none', '')
#             OR array_contains(from_json(column_names_json, 'array<string>'), column_name)
#         )
#         GROUP BY space_id
#     )
# """)
# print("✓ Registered: get_column_detail")

# # UC Function 4: get_space_details (SQL scalar function - last resort)
# spark.sql(f"""
# CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.get_space_details(
#     space_ids_json STRING DEFAULT 'null' COMMENT 'JSON array of space IDs to query (required). Example: ["space_1", "space_2"]. WARNING: Returns large metadata - use as LAST RESORT.'
# )
# RETURNS STRING
# LANGUAGE SQL
# COMMENT 'Get complete metadata for specific Genie spaces - use as LAST RESORT (token intensive). Returns JSON with complete space metadata including chunk_id, chunk_type, space_title, and all available metadata content.'
# RETURN
#     SELECT COALESCE(
#         to_json(
#             map_from_entries(
#                 collect_list(
#                     struct(
#                         space_id,
#                         named_struct(
#                             'chunk_id', chunk_id,
#                             'chunk_type', chunk_type,
#                             'space_title', space_title,
#                             'complete_metadata', searchable_content
#                         )
#                     )
#                 )
#             )
#         ),
#         '{{}}'
#     ) as result
#     FROM {TABLE_NAME}
#     WHERE chunk_type = 'space_details'
#     AND array_contains(from_json(space_ids_json, 'array<string>'), space_id)
# """)
# print("✓ Registered: get_space_details")

# print("\n" + "="*80)
# print("✅ ALL 4 UC FUNCTIONS REGISTERED SUCCESSFULLY!")
# print("="*80)
# print("Functions available for SQL Synthesis Agent:")
# print(f"  1. {CATALOG}.{SCHEMA}.get_space_summary")
# print(f"  2. {CATALOG}.{SCHEMA}.get_table_overview")
# print(f"  3. {CATALOG}.{SCHEMA}.get_column_detail")
# print(f"  4. {CATALOG}.{SCHEMA}.get_space_details")
# print("="*80)

# COMMAND ----------

# DBTITLE 1,📝💾%%writefile agent.py
#%%writefile agent.py
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

# Import conversation management modules
import sys
from pathlib import Path
# # (obsolete) Add kumc_poc to path if not already present
# kumc_poc_path = str(Path(__file__).parent.parent / "kumc_poc") if '__file__' in globals() else "../kumc_poc"
# if kumc_poc_path not in sys.path:
#     sys.path.insert(0, kumc_poc_path)

# NOTE: No imports from kumc_poc - all TypedDicts and logic are inline
# This simplifies the agent and makes it self-contained
from databricks_langchain.genie import GenieAgent
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AIMessageChunk
from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel, RunnableConfig
from langchain_core.tools import tool, StructuredTool
import mlflow
import logging
from pydantic import BaseModel, Field
import json


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
    
    # LLM Endpoint Configuration - Diversified by Agent Role
    "llm_endpoint": "databricks-claude-sonnet-4-5",  # Default/fallback
    "llm_endpoint_clarification": "databricks-claude-haiku-4-5",
    "llm_endpoint_planning": "databricks-claude-sonnet-4-5",
    "llm_endpoint_sql_synthesis_table": "databricks-claude-haiku-4-5",
    "llm_endpoint_sql_synthesis_genie": "databricks-claude-sonnet-4-5",
    "llm_endpoint_execution": "databricks-claude-haiku-4-5",
    "llm_endpoint_summarize": "databricks-claude-haiku-4-5",
    
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

# LLM Endpoints - Diversified by Agent Role
default_endpoint = model_config.get("llm_endpoint")
LLM_ENDPOINT_CLARIFICATION = model_config.get("llm_endpoint_clarification") or default_endpoint
LLM_ENDPOINT_PLANNING = model_config.get("llm_endpoint_planning") or default_endpoint
LLM_ENDPOINT_SQL_SYNTHESIS_TABLE = model_config.get("llm_endpoint_sql_synthesis_table") or default_endpoint
LLM_ENDPOINT_SQL_SYNTHESIS_GENIE = model_config.get("llm_endpoint_sql_synthesis_genie") or default_endpoint
LLM_ENDPOINT_EXECUTION = model_config.get("llm_endpoint_execution") or default_endpoint
LLM_ENDPOINT_SUMMARIZE = model_config.get("llm_endpoint_summarize") or default_endpoint

# Lakebase configuration for state management
LAKEBASE_INSTANCE_NAME = model_config.get("lakebase_instance_name")
EMBEDDING_ENDPOINT = model_config.get("lakebase_embedding_endpoint")
EMBEDDING_DIMS = model_config.get("lakebase_embedding_dims")

# Genie space IDs
GENIE_SPACE_IDS = model_config.get("genie_space_ids")

# SQL Warehouse ID (required for SQLExecutionAgent)
SQL_WAREHOUSE_ID = model_config.get("sql_warehouse_id")

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
logger.info(f"SQL Warehouse ID: {SQL_WAREHOUSE_ID}")

# Validate SQL_WAREHOUSE_ID is configured
if not SQL_WAREHOUSE_ID:
    error_msg = (
        "SQL_WAREHOUSE_ID is not configured! "
        "Ensure 'sql_warehouse_id' is set in prod_config.yaml or development_config."
    )
    logger.error(error_msg)
    raise ValueError(error_msg)

logger.info("="*80)

# Initialize UC Function Client
client = DatabricksFunctionClient()
set_uc_function_client(client)

logger.info(f"Configuration loaded: Catalog={CATALOG}, Schema={SCHEMA}, Lakebase={LAKEBASE_INSTANCE_NAME}")

print("✓ All dependencies imported successfully (including memory support)")

# ==============================================================================
# PHASE 1 OPTIMIZATION: Caching Infrastructure
# ==============================================================================

from datetime import timedelta

# Space context cache with TTL (30 minutes)
_space_context_cache = {"data": None, "timestamp": None, "table_name": None}
_SPACE_CONTEXT_CACHE_TTL = timedelta(minutes=30)

# Agent instance caches (persistent across requests)
_agent_cache = {}

# Genie agent pool (lazy initialization)
_genie_agent_pool = {}

# Phase 2: Vector search result cache (for refinement queries)
_vector_search_cache = {}  # Format: {thread_id: {"query": str, "results": List, "timestamp": datetime}}
_VECTOR_SEARCH_CACHE_TTL = timedelta(minutes=10)  # Shorter TTL for conversation-specific cache

# Phase 2: LLM connection pool (avoid repeated connection overhead)
_llm_connection_pool = {}  # Format: {endpoint_name: ChatDatabricks instance}

def get_pooled_llm(endpoint_name: str, temperature: float = 0.1, max_tokens: int = None):
    """
    Get or create a pooled LLM connection.
    Reuses connections across requests to avoid connection overhead.
    Expected gain: -500ms cumulative across multiple LLM calls.
    
    Args:
        endpoint_name: Name of the LLM endpoint
        temperature: Temperature for generation (default 0.1)
        max_tokens: Maximum tokens to generate (default None)
    
    Returns:
        ChatDatabricks instance from pool
    """
    
    # Create a cache key that includes temperature and max_tokens
    cache_key = f"{endpoint_name}_{temperature}_{max_tokens}"
    
    if cache_key not in _llm_connection_pool:
        record_cache_miss("llm_pool")
        print(f"⚡ Creating pooled LLM connection: {endpoint_name} (temperature={temperature})")
        kwargs = {"endpoint": endpoint_name, "temperature": temperature}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        _llm_connection_pool[cache_key] = ChatDatabricks(**kwargs)
        print(f"✓ LLM connection pooled: {cache_key}")
    else:
        record_cache_hit("llm_pool")
        print(f"♻️ Reusing pooled LLM connection: {cache_key} (-50ms to -200ms)")
    
    return _llm_connection_pool[cache_key]

def clear_llm_connection_pool():
    """Clear LLM connection pool (useful for configuration changes)."""
    global _llm_connection_pool
    _llm_connection_pool = {}
    print("✓ LLM connection pool cleared")

print("✓ Phase 2 LLM connection pooling initialized (-500ms cumulative)")

# ==============================================================================
# PHASE 3: Performance Monitoring Infrastructure
# ==============================================================================

import time
from functools import wraps
from typing import Callable

# Performance metrics storage
_performance_metrics = {
    "node_timings": {},  # {node_name: [execution_times]}
    "cache_stats": {
        "space_context_hits": 0,
        "space_context_misses": 0,
        "vector_search_hits": 0,
        "vector_search_misses": 0,
        "agent_cache_hits": 0,
        "agent_cache_misses": 0,
        "llm_pool_hits": 0,
        "llm_pool_misses": 0
    },
    "workflow_metrics": {
        "ttft_seconds": [],  # Time to first token
        "ttcl_seconds": [],  # Time to completion
        "total_requests": 0
    }
}

def measure_node_time(node_name: str):
    """
    Decorator to measure node execution time.
    Expected use: Track per-node performance for optimization.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                
                # Record timing
                if node_name not in _performance_metrics["node_timings"]:
                    _performance_metrics["node_timings"][node_name] = []
                _performance_metrics["node_timings"][node_name].append(elapsed)
                
                # Print timing
                print(f"⏱️  {node_name}: {elapsed:.3f}s")
                
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"⏱️  {node_name}: {elapsed:.3f}s (FAILED)")
                raise
        return wrapper
    return decorator

def track_agent_model_usage(agent_name: str, model_endpoint: str):
    """
    Track which LLM model is used by each agent for monitoring and cost analysis.
    
    Args:
        agent_name: Name of the agent (e.g., "clarification", "planning")
        model_endpoint: LLM endpoint being used (e.g., "databricks-claude-haiku-4-5")
    """
    if "agent_model_usage" not in _performance_metrics:
        _performance_metrics["agent_model_usage"] = {}
    
    if agent_name not in _performance_metrics["agent_model_usage"]:
        _performance_metrics["agent_model_usage"][agent_name] = {
            "model": model_endpoint,
            "invocations": 0
        }
    
    _performance_metrics["agent_model_usage"][agent_name]["invocations"] += 1
    print(f"📊 Agent '{agent_name}' using model: {model_endpoint}")

def record_cache_hit(cache_type: str):
    """Record a cache hit for monitoring."""
    key = f"{cache_type}_hits"
    if key in _performance_metrics["cache_stats"]:
        _performance_metrics["cache_stats"][key] += 1

def record_cache_miss(cache_type: str):
    """Record a cache miss for monitoring."""
    key = f"{cache_type}_misses"
    if key in _performance_metrics["cache_stats"]:
        _performance_metrics["cache_stats"][key] += 1

def get_performance_summary():
    """
    Get comprehensive performance summary with averages and cache hit rates.
    """
    summary = {
        "node_averages": {},
        "cache_hit_rates": {},
        "workflow_averages": {}
    }
    
    # Calculate node averages
    for node_name, timings in _performance_metrics["node_timings"].items():
        if timings:
            summary["node_averages"][node_name] = {
                "avg_seconds": sum(timings) / len(timings),
                "min_seconds": min(timings),
                "max_seconds": max(timings),
                "count": len(timings)
            }
    
    # Calculate cache hit rates
    for cache_type in ["space_context", "vector_search", "agent_cache", "llm_pool"]:
        hits = _performance_metrics["cache_stats"].get(f"{cache_type}_hits", 0)
        misses = _performance_metrics["cache_stats"].get(f"{cache_type}_misses", 0)
        total = hits + misses
        if total > 0:
            summary["cache_hit_rates"][cache_type] = {
                "hit_rate": hits / total,
                "hits": hits,
                "misses": misses,
                "total": total
            }
    
    # Calculate workflow averages
    ttft_list = _performance_metrics["workflow_metrics"]["ttft_seconds"]
    ttcl_list = _performance_metrics["workflow_metrics"]["ttcl_seconds"]
    
    if ttft_list:
        summary["workflow_averages"]["ttft_avg"] = sum(ttft_list) / len(ttft_list)
        summary["workflow_averages"]["ttft_min"] = min(ttft_list)
        summary["workflow_averages"]["ttft_max"] = max(ttft_list)
    
    if ttcl_list:
        summary["workflow_averages"]["ttcl_avg"] = sum(ttcl_list) / len(ttcl_list)
        summary["workflow_averages"]["ttcl_min"] = min(ttcl_list)
        summary["workflow_averages"]["ttcl_max"] = max(ttcl_list)
    
    summary["workflow_averages"]["total_requests"] = _performance_metrics["workflow_metrics"]["total_requests"]
    
    # Add agent model usage tracking
    if "agent_model_usage" in _performance_metrics:
        summary["agent_model_usage"] = _performance_metrics["agent_model_usage"]
    
    return summary

def reset_performance_metrics():
    """Reset all performance metrics (useful for testing)."""
    global _performance_metrics
    _performance_metrics = {
        "node_timings": {},
        "cache_stats": {
            "space_context_hits": 0,
            "space_context_misses": 0,
            "vector_search_hits": 0,
            "vector_search_misses": 0,
            "agent_cache_hits": 0,
            "agent_cache_misses": 0,
            "llm_pool_hits": 0,
            "llm_pool_misses": 0
        },
        "workflow_metrics": {
            "ttft_seconds": [],
            "ttcl_seconds": [],
            "total_requests": 0
        }
    }
    print("✓ Performance metrics reset")

def print_agent_model_usage():
    """Print a summary of which LLM models each agent is using."""
    print("\n" + "="*80)
    print("🤖 AGENT LLM MODEL USAGE SUMMARY")
    print("="*80)
    
    if "agent_model_usage" not in _performance_metrics or not _performance_metrics["agent_model_usage"]:
        print("No agent model usage tracked yet.")
        return
    
    for agent_name, usage_info in sorted(_performance_metrics["agent_model_usage"].items()):
        model = usage_info.get("model", "unknown")
        invocations = usage_info.get("invocations", 0)
        print(f"\n{agent_name.upper()}:")
        print(f"  Model: {model}")
        print(f"  Invocations: {invocations}")
    
    print("="*80)

print("✓ Phase 3 performance monitoring infrastructure initialized")
print("  - Node timing decorators")
print("  - Cache hit/miss tracking")
print("  - TTFT/TTCL metrics")
print("  - Performance summary reporting")
print("  - Agent LLM model usage tracking (NEW)")

def clear_space_context_cache():
    """Manually clear space context cache (useful for testing or refresh)."""
    global _space_context_cache
    _space_context_cache = {"data": None, "timestamp": None, "table_name": None}
    print("✓ Space context cache cleared")

def clear_agent_caches():
    """Clear all agent caches (useful for configuration changes)."""
    global _agent_cache, _genie_agent_pool, _vector_search_cache
    _agent_cache = {}
    _genie_agent_pool = {}
    _vector_search_cache = {}
    print("✓ Agent caches cleared (including vector search)")

def clear_vector_search_cache(thread_id: str = None):
    """Clear vector search cache for a specific thread or all threads."""
    global _vector_search_cache
    if thread_id:
        if thread_id in _vector_search_cache:
            del _vector_search_cache[thread_id]
            print(f"✓ Vector search cache cleared for thread: {thread_id}")
    else:
        _vector_search_cache = {}
        print("✓ All vector search caches cleared")

def get_cache_stats():
    """Get cache statistics for monitoring."""
    stats = {
        "space_context_cached": _space_context_cache["data"] is not None,
        "space_context_timestamp": _space_context_cache["timestamp"],
        "agent_cache_size": len(_agent_cache),
        "genie_pool_size": len(_genie_agent_pool),
        "vector_search_cache_size": len(_vector_search_cache),
        "llm_connection_pool_size": len(_llm_connection_pool),
        "cached_agents": list(_agent_cache.keys()),
        "pooled_genie_spaces": list(_genie_agent_pool.keys()),
        "vector_search_threads": list(_vector_search_cache.keys()),
        "pooled_llm_connections": list(_llm_connection_pool.keys())
    }
    return stats

print("✓ Phase 1 caching infrastructure initialized")

# ==============================================================================
# PHASE 1 OPTIMIZATION: Cached Agent Getters (Module-Level Singletons)
# ==============================================================================

def get_cached_planning_agent():
    """
    Get or create cached PlanningAgent instance.
    Expected gain: -500ms to -1s per request
    """
    if "planning" not in _agent_cache:
        record_cache_miss("agent_cache")
        print("⚡ Creating PlanningAgent (first use)...")
        llm = get_pooled_llm(LLM_ENDPOINT_PLANNING)
        # Note: Agent class will be defined later in notebook
        # This is a forward reference that works because Python resolves at runtime
        _agent_cache["planning"] = PlanningAgent(llm, VECTOR_SEARCH_INDEX)
        print("✓ PlanningAgent cached")
    else:
        record_cache_hit("agent_cache")
        print("✓ Using cached PlanningAgent")
    return _agent_cache["planning"]

def get_cached_sql_table_agent():
    """
    Get or create cached SQLSynthesisTableAgent instance.
    Expected gain: -500ms to -1s per request
    """
    if "sql_table" not in _agent_cache:
        record_cache_miss("agent_cache")
        print("⚡ Creating SQLSynthesisTableAgent (first use)...")
        llm = get_pooled_llm(LLM_ENDPOINT_SQL_SYNTHESIS_TABLE)
        _agent_cache["sql_table"] = SQLSynthesisTableAgent(llm, CATALOG, SCHEMA)
        print("✓ SQLSynthesisTableAgent cached")
    else:
        record_cache_hit("agent_cache")
        print("✓ Using cached SQLSynthesisTableAgent")
    return _agent_cache["sql_table"]

def get_cached_summarize_agent():
    """
    Get or create cached ResultSummarizeAgent instance.
    Expected gain: -100ms to -300ms per request
    """
    if "summarize" not in _agent_cache:
        record_cache_miss("agent_cache")
        print("⚡ Creating ResultSummarizeAgent (first use)...")
        llm = get_pooled_llm(LLM_ENDPOINT_SUMMARIZE, temperature=0.1, max_tokens=5000)
        _agent_cache["summarize"] = ResultSummarizeAgent(llm)
        print("✓ ResultSummarizeAgent cached")
    else:
        record_cache_hit("agent_cache")
        print("✓ Using cached ResultSummarizeAgent")
    return _agent_cache["summarize"]

print("✓ Agent cache getters defined")

# ==============================================================================
# PHASE 1 OPTIMIZATION: Genie Agent Pool (Lazy Initialization)
# ==============================================================================

def get_or_create_genie_agent(space_id: str, space_title: str, description: str):
    """
    Get existing Genie agent from pool or create new one if not cached.
    
    OPTIMIZATION: Reuses Genie agents across requests to avoid expensive initialization.
    Expected gain: -1 to -3s on genie route (creating 3-5 agents)
    
    Args:
        space_id: Genie space ID
        space_title: Space title for agent name
        description: Space description
    
    Returns:
        Cached or newly created GenieAgent instance
    """
    global _genie_agent_pool
    
    if space_id not in _genie_agent_pool:
        from databricks_langchain import GenieAgent
        
        print(f"⚡ Creating Genie agent for space: {space_title} (first use)")
        
        def enforce_limit(messages, n=5):
            """Enforce result limit in Genie queries."""
            last = messages[-1] if messages else {"content": ""}
            content = last.get("content", "") if isinstance(last, dict) else last.content
            return f"{content}\n\nPlease limit the result to at most {n} rows."
        
        genie_agent = GenieAgent(
            genie_space_id=space_id,
            genie_agent_name=f"Genie_{space_title}",
            description=description,
            include_context=True,
            message_processor=lambda msgs: enforce_limit(msgs, n=5)
        )
        
        _genie_agent_pool[space_id] = genie_agent
        print(f"✓ Genie agent cached for {space_title}")
    else:
        print(f"✓ Using cached Genie agent for {space_title}")
    
    return _genie_agent_pool[space_id]

print("✓ Genie agent pool initialized")

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

def _load_space_context_uncached(table_name: str) -> Dict[str, str]:
    """
    Internal function: Load space context from Delta table without caching.
    
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
    
    return context

def load_space_context(table_name: str) -> Dict[str, str]:
    """
    Load space context from Delta table with TTL-based caching.
    
    OPTIMIZATION: Caches results for 30 minutes to avoid repeated Spark queries.
    Expected gain: -1 to -2s per request (when cache is hot)
    
    Args:
        table_name: Full table name (catalog.schema.table)
        
    Returns:
        Dictionary mapping space_id to searchable_content
    """
    global _space_context_cache
    
    now = datetime.now()
    
    # Check if cache is valid
    cache_valid = (
        _space_context_cache["data"] is not None and
        _space_context_cache["timestamp"] is not None and
        _space_context_cache["table_name"] == table_name and
        now - _space_context_cache["timestamp"] < _SPACE_CONTEXT_CACHE_TTL
    )
    
    if cache_valid:
        record_cache_hit("space_context")
        cache_age_seconds = (now - _space_context_cache["timestamp"]).total_seconds()
        print(f"✓ Using cached space context ({len(_space_context_cache['data'])} spaces, age: {cache_age_seconds:.1f}s)")
        return _space_context_cache["data"]
    else:
        # Cache miss - load from database
        record_cache_miss("space_context")
        print(f"⚡ Loading space context from database (cache {'expired' if _space_context_cache['data'] else 'empty'})...")
        context = _load_space_context_uncached(table_name)
        
        # Update cache
        _space_context_cache["data"] = context
        _space_context_cache["timestamp"] = now
        _space_context_cache["table_name"] = table_name
        
        print(f"✓ Loaded {len(context)} Genie spaces and cached for {_SPACE_CONTEXT_CACHE_TTL.total_seconds()/60:.0f} minutes")
        return context

# Note: Context is now loaded dynamically in clarification_node
# This allows refresh without model redeployment
# ==============================================================================
# Inline TypedDicts for Unified Agent (No kumc_poc imports)
# ==============================================================================

from typing import TypedDict, Optional, List, Dict, Any, Literal, Annotated
from datetime import datetime
import operator
import uuid as uuid_module

class ConversationTurn(TypedDict):
    """
    Represents a single conversation turn with all its context.
    Inline definition for simplified unified agent.
    """
    turn_id: str
    query: str
    intent_type: Literal["new_question", "refinement", "continuation", "clarification_response"]
    parent_turn_id: Optional[str]
    context_summary: Optional[str]
    timestamp: str  # ISO format datetime string
    triggered_clarification: Optional[bool]
    metadata: Optional[Dict[str, Any]]

class ClarificationRequest(TypedDict):
    """Unified clarification request object."""
    reason: str
    options: List[str]
    turn_id: str
    timestamp: str
    best_guess: Optional[str]
    best_guess_confidence: Optional[float]

class IntentMetadata(TypedDict):
    """Intent metadata for business logic."""
    intent_type: Literal["new_question", "refinement", "continuation", "clarification_response"]
    confidence: float
    reasoning: str
    topic_change_score: float
    domain: Optional[str]
    operation: Optional[str]
    complexity: Literal["simple", "moderate", "complex"]
    parent_turn_id: Optional[str]

class AgentState(TypedDict):
    """Simplified agent state using turn-based context management."""
    # Turn Management
    current_turn: Optional[ConversationTurn]
    turn_history: Annotated[List[ConversationTurn], operator.add]
    intent_metadata: Optional[IntentMetadata]
    
    # Clarification
    pending_clarification: Optional[ClarificationRequest]
    question_clear: bool
    
    # Meta-question handling (NEW)
    is_meta_question: Optional[bool]
    meta_answer: Optional[str]
    
    # Deprecated
    original_query: Optional[str]
    
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
    
    # Execution
    execution_result: Optional[Dict[str, Any]]
    execution_error: Optional[str]
    
    # Summary
    final_summary: Optional[str]
    
    # Conversation Management
    user_id: Optional[str]
    thread_id: Optional[str]
    user_preferences: Optional[Dict[str, Any]]
    
    # Control Flow
    next_agent: Optional[str]
    messages: Annotated[List, operator.add]

# Helper functions
def create_conversation_turn(
    query: str,
    intent_type: Literal["new_question", "refinement", "continuation", "clarification_response"],
    parent_turn_id: Optional[str] = None,
    context_summary: Optional[str] = None,
    triggered_clarification: bool = False,
    metadata: Optional[Dict[str, Any]] = None
) -> ConversationTurn:
    """
    Factory function to create a ConversationTurn with runtime validation.
    
    Args:
        query: User's query string
        intent_type: Must be one of: "new_question", "refinement", "continuation", "clarification_response"
        parent_turn_id: Optional parent turn ID for context
        context_summary: Optional summary of conversation context
        triggered_clarification: Whether this turn triggered clarification
        metadata: Optional additional metadata
        
    Returns:
        ConversationTurn with validated intent_type
        
    Raises:
        ValueError: If intent_type is not one of the allowed values
    """
    # Runtime validation to enforce type contract
    valid_intent_types = {"new_question", "refinement", "continuation", "clarification_response"}
    if intent_type not in valid_intent_types:
        raise ValueError(
            f"Invalid intent_type: '{intent_type}'. "
            f"Must be one of: {valid_intent_types}."
        )
    
    return ConversationTurn(
        turn_id=str(uuid_module.uuid4()),
        query=query,
        intent_type=intent_type,
        parent_turn_id=parent_turn_id,
        context_summary=context_summary,
        timestamp=datetime.utcnow().isoformat(),
        triggered_clarification=triggered_clarification,
        metadata=metadata or {}
    )

def create_clarification_request(
    reason: str,
    options: List[str],
    turn_id: str,
    best_guess: Optional[str] = None,
    best_guess_confidence: Optional[float] = None
) -> ClarificationRequest:
    """Factory function to create a ClarificationRequest."""
    return ClarificationRequest(
        reason=reason,
        options=options,
        turn_id=turn_id,
        timestamp=datetime.utcnow().isoformat(),
        best_guess=best_guess,
        best_guess_confidence=best_guess_confidence
    )

def format_clarification_message(clarification: ClarificationRequest) -> str:
    """Format a clarification request into a user-friendly message."""
    message = f"I need clarification: {clarification['reason']}\n\n"
    message += "Please choose one of the following options or provide your own clarification:\n"
    for i, option in enumerate(clarification['options'], 1):
        message += f"{i}. {option}\n"
    return message

def get_reset_state_template() -> Dict[str, Any]:
    """Get template for resetting per-query execution fields."""
    return {
        "pending_clarification": None,
        "question_clear": False,
        "is_meta_question": False,
        "meta_answer": None,
        "plan": None,
        "sub_questions": None,
        "requires_multiple_spaces": None,
        "relevant_space_ids": None,
        "relevant_spaces": None,
        "vector_search_relevant_spaces_info": None,
        "requires_join": None,
        "join_strategy": None,
        "execution_plan": None,
        "genie_route_plan": None,
        "sql_query": None,
        "sql_synthesis_explanation": None,
        "synthesis_error": None,
        "execution_result": None,
        "execution_error": None,
        "final_summary": None,
    }

print("✓ Inline TypedDicts defined (no kumc_poc imports)")

# State Reset Template
# All per-query execution fields that should be cleared for each new query.
# This prevents stale data from persisting across queries when using CheckpointSaver.
# Used by both Model Serving (run_agent) and local testing (invoke_super_agent_hybrid).
# Use the shared reset state template from conversation_models
RESET_STATE_TEMPLATE = get_reset_state_template()

# NOTE: Turn-based fields (current_turn, turn_history, intent_metadata) are NOT reset
# They are managed by unified_intent_context_clarification_node and persist across queries

# For reference, the template includes per-query fields (see conversation_models.get_reset_state_template()):
# RESET_STATE_TEMPLATE = {
    # Clarification fields (per-query) - SIMPLIFIED from 7+ legacy fields to 2
    # "pending_clarification": None,
    # "question_clear": False,
    
    # Planning fields (per-query)
    # "plan": None,
    # "sub_questions": None,
    # "requires_multiple_spaces": None,
    # "relevant_space_ids": None,
    # "relevant_spaces": None,
    # "vector_search_relevant_spaces_info": None,
    # "requires_join": None,
    # "join_strategy": None,
    # "execution_plan": None,
    # "genie_route_plan": None,
    
    # SQL fields (per-query)
    # "sql_query": None,
    # "sql_synthesis_explanation": None,
    # "synthesis_error": None,
    
    # Execution fields (per-query)
    # "execution_result": None,
    # "execution_error": None,
    
    # Summary (per-query)
    # "final_summary": None,
# }

# Fields intentionally NOT in reset template:
# 
# NEW TURN-BASED FIELDS (persist across queries via CheckpointSaver):
# - current_turn: Set by intent_detection_node for each query
# - turn_history: Accumulated by reducer with operator.add, persists across conversation
# - intent_metadata: Set by intent_detection_node for each query
#
# DEPRECATED LEGACY FIELDS (removed from AgentState):
# - clarification_count: Replaced by turn_history with triggered_clarification flag
# - last_clarified_query: Replaced by turn_history with triggered_clarification flag
# - combined_query_context: Replaced by current_turn.context_summary (LLM-generated)
# - clarification_needed (as state field): Replaced by pending_clarification object
# - clarification_options (as state field): Replaced by pending_clarification object
#
# DEPRECATED BUT KEPT FOR BACKWARD COMPATIBILITY:
# - original_query: Kept in AgentState but deprecated. Use messages array instead.
#   This field is still set in initial_state for compatibility with legacy code.
#
# PERSISTENT FIELDS (never reset):
# - messages: Managed by operator.add in AgentState, persists across conversation
# - user_id, thread_id, user_preferences: Identity/context, persists for entire conversation
# - next_agent: Control flow field, managed by nodes and routing logic (not in reset template)

print("✓ State reset template defined for per-query field clearing")

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
        relevant_spaces: List[Dict[str, Any]],
        original_query: str = None
    ) -> Dict[str, Any]:
        """
        Create execution plan based on query and relevant spaces.
        
        Args:
            query: User's question (may be context_summary if available)
            relevant_spaces: List of relevant Genie spaces
            original_query: Original user query from this turn (before context enrichment)
            
        Returns:
            Dictionary with execution plan
        """
        # Use original_query if provided, otherwise use query as original
        original_query_display = original_query if original_query is not None else query
        
        planning_prompt = f"""
You are a query planning expert. Analyze the following question and create an execution plan.

User original query this turn: {original_query_display}

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
        
        # Stream LLM response for immediate first token emission
        print("🤖 Streaming planning LLM call...")
        content = ""
        for chunk in self.llm.stream(planning_prompt):
            if chunk.content:
                content += chunk.content
        
        content = content.strip()
        print(f"✓ Planning stream complete ({len(content)} chars)")
        
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
                "- Use minimal sufficiency: only query what you need\n"
                "- OPTIMIZATION: When possible, call multiple UC functions in parallel by returning multiple tool calls\n"
                "  Example: If you need table_overview for space_1 AND column_detail for space_2, call both tools at once\n"
                "- This enables parallel execution and reduces latency by 1-2 seconds\n\n"

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
    
    EXECUTION MODES:
    ---------------
    1. LangGraph Agent Mode (default via synthesize_sql()):
       - Uses LangGraph agent with tool calling
       - Supports retries, disaster recovery, and adaptive routing
       - Agent decides which tools to call and when
       - Best for complex queries requiring orchestration
    
    2. RunnableParallel Mode (via invoke_genie_agents_parallel()):
       - Uses RunnableParallel for direct parallel execution
       - Faster for simple parallel queries
       - No retry logic or adaptive routing
       - Best for straightforward parallel execution
    
    ARCHITECTURE:
    ------------
    - Upgraded from RunnableLambda to RunnableParallel pattern
    - Each Genie agent is wrapped as both a tool and a parallel executor
    - Supports efficient parallel invocation using LangChain's RunnableParallel
    - Optimized to only create Genie agents for relevant spaces (not all spaces)
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
        
        OPTIMIZED: Uses cached Genie agents from pool to avoid expensive initialization.
        Expected gain: -1 to -3s on genie route (when agents are already cached)
        
        Creates both:
        1. Individual tool wrappers for LangGraph agent tool calling
        2. A parallel executor mapping for efficient batch invocation
        
        Uses LangChain preferred syntax with Pydantic BaseModel and StructuredTool.
        """
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
            
            # OPTIMIZATION: Get Genie agent from pool (cached or newly created)
            genie_agent = get_or_create_genie_agent(space_id, space_title, description)
            self.genie_agents.append(genie_agent)
            
            # Define tool input schema using Pydantic
            class GenieToolInput(BaseModel):
                question: str = Field(..., description="Natural-language query to run in the Genie Space")
                conversation_id: Optional[str] = Field(None, description="Optional Genie conversation for continuity")
            
            # Create tool function using factory pattern to capture agent
            def make_genie_tool_call(agent):
                """Factory function to capture agent in closure properly"""
                def _genie_tool_call(question: str, conversation_id: Optional[str] = None):
                    """
                    StructuredTool with args_schema expects individual field arguments,
                    not a single Pydantic object.
                    """
                    # GenieAgent expects a LangChain-style message list
                    result = agent.invoke({
                        "messages": [{"role": "user", "content": question}],
                        "conversation_id": conversation_id,
                    })
                    # Extract final output + optional context
                    out = {"conversation_id": result.get("conversation_id")}
                    msgs = result["messages"]
                    def _get(name): 
                        return next((getattr(m, "content", "") for m in msgs if getattr(m, "name", None) == name), None)
                    out["answer"] = _get("query_result") or ""
                    reasoning = _get("query_reasoning")
                    sql = _get("query_sql")
                    if reasoning: out["reasoning"] = reasoning
                    if sql: out["sql"] = sql
                    return out
                return _genie_tool_call
            
            # Create StructuredTool
            genie_tool = StructuredTool(
                name=genie_agent_name,
                description=(
                    f"Use for governed analytics queries (NL→SQL) in {space_title}. "
                    f"{description}. "
                    "Returns an answer and, when available, the generated SQL and reasoning."
                ),
                args_schema=GenieToolInput,
                func=make_genie_tool_call(genie_agent),
            )
            self.genie_agent_tools.append(genie_tool)
            
            print(f"  ✓ Created Genie agent tool: {genie_agent_name} ({space_id})")
    
    def _create_parallel_execution_tool(self):
        """
        Create a tool that allows the agent to invoke multiple Genie agents in parallel.
        
        This tool gives the agent control over parallel execution with the same
        disaster recovery capabilities as individual tool calls.
        
        Uses RunnableParallel pattern with StructuredTool for type safety.
        """

        
        # Define input schema for parallel execution
        class ParallelGenieInput(BaseModel):
            genie_route_plan: Dict[str, str] = Field(
                ..., 
                description="Dictionary mapping space_id to question. Example: {'space_id_1': 'Get member demographics', 'space_id_2': 'Get benefits'}"
            )
        
        # Merge function to combine outputs from multiple Genie agents
        def merge_genie_outputs(outputs: Dict[str, Any]) -> Dict[str, Any]:
            """
            Merge outputs from multiple Genie agents into a unified result.
            
            Args:
                outputs: Dictionary keyed by space_id, each containing agent results
            
            Returns:
                Unified dictionary with extracted SQL, reasoning, and metadata from all agents
            """
            merged_results = {}
            
            for space_id, result in outputs.items():
                extracted = {
                    "space_id": space_id,
                    "question": outputs.get(f"{space_id}_question", ""),
                    "sql": "",
                    "reasoning": "",
                    "answer": "",
                    "conversation_id": "",
                    "success": False
                }
                
                # Handle direct dict output from StructuredTool
                if isinstance(result, dict):
                    extracted["answer"] = result.get("answer", "")
                    extracted["sql"] = result.get("sql", "")
                    extracted["reasoning"] = result.get("reasoning", "")
                    extracted["conversation_id"] = result.get("conversation_id", "")
                    extracted["success"] = bool(result.get("sql") or result.get("answer"))
                
                # Handle message-based output (fallback)
                elif isinstance(result, dict) and "messages" in result:
                    messages = result.get("messages", [])
                    
                    # Extract reasoning (query_reasoning)
                    for msg in messages:
                        if hasattr(msg, 'name') and msg.name == 'query_reasoning':
                            extracted["reasoning"] = msg.content if hasattr(msg, 'content') else ""
                            break
                    
                    # Extract SQL (query_sql)
                    for msg in messages:
                        if hasattr(msg, 'name') and msg.name == 'query_sql':
                            extracted["sql"] = msg.content if hasattr(msg, 'content') else ""
                            extracted["success"] = True
                            break
                    
                    # Extract answer (query_result)
                    for msg in messages:
                        if hasattr(msg, 'name') and msg.name == 'query_result':
                            extracted["answer"] = msg.content if hasattr(msg, 'content') else ""
                            break
                    
                    # Extract conversation_id
                    extracted["conversation_id"] = result.get("conversation_id", "")
                
                merged_results[space_id] = extracted
            
            return merged_results
        
        # Build a mapping from space_id to tool for easy lookup
        space_id_to_tool = {}
        for space in self.relevant_spaces:
            space_id = space.get("space_id")
            if space_id:
                # Find the corresponding tool by matching space_id
                for tool in self.genie_agent_tools:
                    # Match tool to space by checking if space_title is in tool name
                    space_title = space.get("space_title", space_id)
                    if f"Genie_{space_title}" == tool.name:
                        space_id_to_tool[space_id] = tool
                        break
        
        # Tool function that builds and invokes dynamic parallel execution
        def invoke_parallel_genie_agents(genie_route_plan: Dict[str, str]) -> Dict[str, Any]:
            """
            Invoke multiple Genie agents in parallel for efficient SQL generation.
            
            StructuredTool with args_schema expects individual field arguments,
            not a single Pydantic object.
            
            Args:
                genie_route_plan: Dictionary mapping space_id to question
            
            Returns:
                Dictionary with results from each Genie agent, keyed by space_id.
                Each result contains the SQL query, reasoning, and answer from that agent.
            """
            try:
                route_plan = genie_route_plan
                
                # Validate all requested space_ids exist
                for space_id in route_plan.keys():
                    if space_id not in space_id_to_tool:
                        return {
                            "error": f"No tool found for space_id: {space_id}",
                            "available_space_ids": list(space_id_to_tool.keys())
                        }
                
                if not route_plan:
                    return {"error": "No valid parallel tasks to execute"}
                
                # Build dynamic parallel tasks - each task invokes the corresponding tool's func
                # Call the underlying function directly with individual arguments
                parallel_tasks = {}
                for space_id, question in route_plan.items():
                    tool = space_id_to_tool[space_id]
                    # Create a lambda that calls the tool's func with individual kwargs
                    # Use default argument to capture values properly in closure
                    parallel_tasks[space_id] = RunnableLambda(
                        lambda inp, sid=space_id, t=tool: t.func(
                            question=inp[sid], conversation_id=None
                        )
                    )
                
                # Create parallel runner and compose with merge function
                parallel = RunnableParallel(**parallel_tasks)
                composed = parallel | RunnableLambda(merge_genie_outputs)
                
                # Invoke the composed chain
                results = composed.invoke(route_plan)
                
                return results
                
            except Exception as e:
                return {"error": f"Parallel execution failed: {str(e)}"}
        
        # Create StructuredTool with proper schema
        parallel_tool = StructuredTool(
            name="invoke_parallel_genie_agents",
            description=(
                "Invoke multiple Genie agents in PARALLEL for fast SQL generation. "
                "Input: Dictionary mapping space_id to question. "
                "Example: {'space_01j9t0jhx009k25rvp67y1k7j0': 'Get member demographics', 'space_01j9t0jhx009k25rvp67y1k7j1': 'Get benefit costs'}. "
                "Returns: Dictionary with SQL, reasoning, and answer from each agent. "
                "Use this tool when: "
                "(1) You need to query multiple Genie spaces simultaneously, "
                "(2) The queries are independent (no dependencies between them), "
                "(3) You want faster execution than calling each agent sequentially. "
                "After getting results, check if you have all needed SQL components. If missing information, you can: "
                "call this tool again with updated questions, or call individual Genie agent tools for specific missing pieces."
            ),
            args_schema=ParallelGenieInput,
            func=invoke_parallel_genie_agents,
        )
        
        return parallel_tool
    
    def _create_sql_synthesis_agent(self):
        """
        Create LangGraph SQL Synthesis Agent with Genie agent tools.
        
        Uses Databricks LangGraph SDK with create_agent pattern.
        Includes both individual Genie agent tools AND a parallel execution tool.
        """
        tools = []
        tools.extend(self.genie_agent_tools)
        
        # Add parallel execution tool
        parallel_tool = self._create_parallel_execution_tool()
        tools.append(parallel_tool)
        
        print(f"✓ Created SQL Synthesis Agent with {len(self.genie_agent_tools)} Genie agent tools + 1 parallel execution tool")
        
        # Create SQL Synthesis Agent (specialized for multi-agent system)
        sql_synthesis_agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=(
"""You are a SQL synthesis agent with access to both INDIVIDUAL and PARALLEL Genie agent execution tools.

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
"genie_route_plan": {'space_id_1':'partial_question_1', 'space_id_2':'partial_question_2', ...} or null,}

## TOOL EXECUTION STRATEGY:

### OPTION 1: PARALLEL EXECUTION (⚡ ALWAYS USE THIS - Saves 1-2 seconds!)
**DEFAULT STRATEGY**: Use the `invoke_parallel_genie_agents` tool to query ALL Genie spaces simultaneously.
This tool executes multiple Genie agent calls in parallel using RunnableParallel pattern.

1. Extract the genie_route_plan from the input JSON
2. Convert it to a JSON string: '{"space_id_1": "question1", "space_id_2": "question2"}'
3. Call: invoke_parallel_genie_agents(genie_route_plan='{"space_id_1": "question1", ...}')
4. You'll receive JSON with SQL and thinking from ALL agents at once
5. Check if you have all needed SQL components
6. If missing information:
   - Reframe questions and call invoke_parallel_genie_agents again with updated questions
   - OR call specific individual Genie agent tools for missing pieces

### OPTION 2: SEQUENTIAL EXECUTION (⚠️ Only for Special Cases)
**RARE**: Only use individual Genie agent tools sequentially when:
- One query strictly depends on results from another (rare in practice)
- Parallel execution failed and you need granular error handling
- You're doing adaptive refinement based on partial results

**NOTE**: 99% of queries should use OPTION 1 (parallel) for optimal performance.

## DISASTER RECOVERY (DR) - WORKS FOR BOTH PARALLEL AND SEQUENTIAL:

1. **First Attempt**: Try your query AS IS
2. **If fails**: Analyze the error message
   - If agent says "I don't have information for X", remove X from the question
   - If agent returns empty/incomplete SQL, try rephrasing the question
3. **Retry Once**: Call the same tool with updated question(s)
4. **If still fails**: Try alternative Genie agents that might have the information
5. **Final fallback**: Work with what you have and explain limitations

## EXAMPLE PARALLEL EXECUTION WITH DR:

Step 1: Call invoke_parallel_genie_agents with initial questions
Step 2: Check results - if space_1 succeeded but space_2 failed
Step 3: Keep space_1 SQL, retry space_2 with reframed question using invoke_parallel_genie_agents
Step 4: Combine all successful SQL fragments

## SQL SYNTHESIS:
Combine all SQL fragments into a single query.

OUTPUT REQUIREMENTS:
- Generate complete, executable SQL with:
  * Proper JOINs based on execution plan strategy
  * WHERE clauses for filtering  
  * Appropriate aggregations
  * Clear column aliases
  * Always use real column names from the data
- Return your response with:
  1. Your explanation (including which execution strategy you used)
  2. The final SQL query in a ```sql code block"""
            )
        )
        
        return sql_synthesis_agent
    
    def invoke_genie_agents_parallel(self, genie_route_plan: Dict[str, str]) -> Dict[str, Any]:
        """
        Invoke multiple Genie agents in parallel using RunnableParallel.
        
        This method demonstrates the proper use of RunnableParallel for efficient
        parallel execution of multiple Genie agents simultaneously.
        
        Args:
            genie_route_plan: Dictionary mapping space_id to partial_question
                Example: {
                    "space_01j9t0jhx009k25rvp67y1k7j0": "Get member demographics",
                    "space_01j9t0jhx009k25rvp67y1k7j1": "Get benefit costs"
                }
        
        Returns:
            Dictionary mapping space_id to agent response
            Example: {
                "space_01j9t0jhx009k25rvp67y1k7j0": {...response...},
                "space_01j9t0jhx009k25rvp67y1k7j1": {...response...}
            }
        """
        if not genie_route_plan:
            return {}
        
        # Build space_id to tool mapping
        space_id_to_tool = {}
        for space in self.relevant_spaces:
            space_id = space.get("space_id")
            if space_id and space_id in genie_route_plan:
                # Find the corresponding tool by matching space_id
                for tool in self.genie_agent_tools:
                    space_title = space.get("space_title", space_id)
                    if f"Genie_{space_title}" == tool.name:
                        space_id_to_tool[space_id] = tool
                        break
        
        # Build parallel tasks that call tool.func() directly with individual arguments
        parallel_tasks = {}
        for space_id, question in genie_route_plan.items():
            if space_id in space_id_to_tool:
                tool = space_id_to_tool[space_id]
                parallel_tasks[space_id] = RunnableLambda(
                    lambda inp, sid=space_id, t=tool: t.func(
                        question=inp[sid], conversation_id=None
                    )
                )
            else:
                print(f"  ⚠ Warning: No tool found for space_id: {space_id}")
        
        if not parallel_tasks:
            print("  ⚠ Warning: No valid parallel tasks to execute")
            return {}
        
        # Create RunnableParallel with all tasks
        parallel_runner = RunnableParallel(**parallel_tasks)
        
        print(f"  🚀 Invoking {len(parallel_tasks)} Genie agents in parallel using RunnableParallel...")
        
        try:
            # Invoke all agents in parallel
            # Now invoke with the actual question mapping
            results = parallel_runner.invoke(genie_route_plan)
            
            print(f"  ✅ Parallel invocation completed for {len(results)} agents")
            print(results)
            return results
            
        except Exception as e:
            print(f"  ❌ Parallel invocation failed: {str(e)}")
            return {}
    
    def synthesize_sql(
        self, 
        plan: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Synthesize SQL using Genie agents with intelligent tool selection.
        
        The agent has access to:
        1. invoke_parallel_genie_agents tool - For fast parallel execution
        2. Individual Genie agent tools - For sequential/dependent queries
        
        The agent autonomously decides which strategy to use and handles
        disaster recovery with retry logic for both parallel and sequential execution
        
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
        
        print(f"\n{'='*80}")
        print("🤖 SQL Synthesis Agent - Starting (with parallel execution tool)...")
        print(f"{'='*80}")
        print(f"Plan: {json.dumps(plan_result, indent=2)}")
        print(f"{'='*80}\n")
        
        # Create the message for the agent
        # The agent will autonomously decide whether to use:
        # 1. invoke_parallel_genie_agents tool (fast parallel execution)
        # 2. Individual Genie agent tools (sequential execution)
        # 3. A combination of both strategies
        agent_message = {
            "messages": [
                {
                    "role": "user",
                    "content": f"""
Generate a SQL query to answer the question according to the Query Plan:
{json.dumps(plan_result, indent=2)}

RECOMMENDED APPROACH:
If 'genie_route_plan' is provided with multiple spaces, consider using the invoke_parallel_genie_agents tool for faster execution.
Convert the genie_route_plan to a JSON string and call the tool to get all SQL fragments in parallel.
Then combine them into a final SQL query.
"""
                }
            ]
        }
        
        try:
            # MLflow autologging is enabled globally at agent initialization
            # No need to call it again here to avoid context issues
            
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
    Agent responsible for executing SQL queries using Databricks SQL Warehouse.
    
    PRODUCTION-READY DESIGN:
    - Uses databricks-sql-connector with unified authentication (Config + credentials_provider)
    - Automatically handles OAuth credentials when deployed with registered resources
    - Supports both development (notebook) and production (Model Serving) environments
    
    AUTHENTICATION WITH AUTOMATIC PASSTHROUGH:
    When you register resources during agent deployment:
    
        resources = [
            DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
            # ... other resources
        ]
        mlflow.langchain.log_model(..., resources=resources)
    
    Databricks automatically:
    1. Creates a service principal for your agent
    2. Manages OAuth token generation and rotation
    3. Injects credentials into the Model Serving environment
    
    The Config() class automatically reads workspace host and injected OAuth credentials,
    eliminating the need for manual DATABRICKS_HOST/DATABRICKS_TOKEN configuration.
    
    Reference: https://docs.databricks.com/generative-ai/agent-framework/agent-authentication
    
    LEGACY MANUAL AUTHENTICATION (if not using automatic passthrough):
    If you're not using resource registration, you can still manually configure:
    - DATABRICKS_HOST and DATABRICKS_TOKEN via Model Serving environment variables
    - Config() will still read them from the environment
    """
    
    def __init__(self, warehouse_id: str):
        """
        Initialize SQL Execution Agent.
        
        Args:
            warehouse_id: Databricks SQL Warehouse ID for query execution
        """
        self.name = "SQLExecution"
        self.warehouse_id = warehouse_id
    
    def execute_sql(
        self, 
        sql_query: str, 
        max_rows: int = 100,
        return_format: str = "dict"
    ) -> Dict[str, Any]:
        """
        Execute SQL query using Databricks SQL Warehouse and return formatted results.
        
        PRODUCTION BEST PRACTICES IMPLEMENTED:
        1. Context Managers: Uses 'with' statements for automatic resource cleanup
        2. Connection Resilience: Configures timeouts and retry logic for transient failures
        3. Proper Error Handling: Categorizes errors for better production debugging
        4. ANSI SQL Mode: Ensures consistent SQL behavior across environments
        5. Model Serving Compatible: Works without Spark session via REST API
        
        Connection Configuration:
        - Socket timeout: 900s (balances Model Serving 297s limit with warehouse query time)
        - HTTP retries: 30 attempts with exponential backoff (1-60s)
        - Session config: ANSI mode enabled for SQL compliance
        
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
            - error_type: str - Exception type for debugging (only on failure)
            - error_hint: str - Suggested resolution (only on failure)
        """
        from databricks import sql
        from databricks.sdk.core import Config
        import json
        
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
        
        # Step 2: Enforce LIMIT clause (for safety and token management)
        # Always enforce max_rows limit, even if query already has LIMIT
        limit_pattern = re.search(r'\bLIMIT\s+(\d+)\b', extracted_sql, re.IGNORECASE)
        if limit_pattern:
            existing_limit = int(limit_pattern.group(1))
            if existing_limit > max_rows:
                # Replace existing LIMIT with max_rows if it exceeds the limit
                extracted_sql = re.sub(
                    r'\bLIMIT\s+\d+\b', 
                    f'LIMIT {max_rows}', 
                    extracted_sql, 
                    flags=re.IGNORECASE
                )
                print(f"⚠️  Reduced LIMIT from {existing_limit} to {max_rows} (max_rows enforcement)")
        else:
            # Add LIMIT if not present
            extracted_sql = f"{extracted_sql.rstrip(';')} LIMIT {max_rows}"
        
        try:
            # Step 3: Initialize Databricks Config for unified authentication
            # BEST PRACTICE: Config() automatically reads workspace host and OAuth credentials
            # - In Model Serving with automatic passthrough: reads injected service principal credentials
            # - In notebooks: reads from notebook context or environment variables
            # - With manual config: reads DATABRICKS_HOST and DATABRICKS_TOKEN from environment
            cfg = Config()
            
            # Step 4: Execute the SQL query using SQL Warehouse
            print(f"\n{'='*80}")
            print("🔍 EXECUTING SQL QUERY (via SQL Warehouse)")
            print(f"{'='*80}")
            print(f"Warehouse ID: {self.warehouse_id}")
            print(f"SQL:\n{extracted_sql}")
            print(f"{'='*80}\n")
            
            # Connect to SQL Warehouse using context manager (production best practice)
            # Context managers ensure proper cleanup even if exceptions occur
            # credentials_provider=cfg lets the connector fetch OAuth tokens transparently
            with sql.connect(
                server_hostname=cfg.host,
                http_path=f"/sql/1.0/warehouses/{self.warehouse_id}",
                credentials_provider=lambda: cfg.authenticate,  # Unified authentication - handles OAuth automatically
                # Production settings for resilience
                session_configuration={
                    "ansi_mode": "true"  # Enable ANSI SQL compliance for consistent behavior
                },
                socket_timeout=900,  # 15 minutes - Model Serving has 297s limit, warehouse queries can be longer
                http_retry_delay_min=1,  # Minimum retry delay in seconds
                http_retry_delay_max=60,  # Maximum retry delay in seconds
                http_retry_max_redirects=5,  # Max HTTP redirects
                http_retry_stop_after_attempts=30,  # Max retry attempts for transient failures
            ) as connection:
                
                # Use nested context manager for cursor (ensures cursor cleanup)
                with connection.cursor() as cursor:
                    
                    # Execute query
                    cursor.execute(extracted_sql)
                    
                    # PHASE 2 OPTIMIZATION: Get row count efficiently
                    # Try to use cursor.rowcount if available (more efficient than len(fetchall()))
                    columns = [desc[0] for desc in cursor.description]
                    
                    # Fetch results (limited by LIMIT clause already enforced)
                    results = cursor.fetchall()
                    
                    # Use actual result count (fetchall is safe because of LIMIT enforcement)
                    row_count = len(results)
                    
                    print(f"✅ Query executed successfully!")
                    print(f"📊 Rows returned: {row_count} (LIMIT enforced at {max_rows})")
                    print(f"📋 Columns: {', '.join(columns)}\n")
                    print(f"⚡ Optimization: Query has LIMIT {max_rows} - safe to fetch all rows")
                    
                    # Step 5: Convert results to list of dicts for compatibility
                    result_data = [dict(zip(columns, row)) for row in results]
                    
                # Cursor automatically closed here by context manager
            
            # Connection automatically closed here by context manager
            
            # Step 6: Format results based on return_format
            if return_format == "json":
                # Convert to JSON strings (matching old spark behavior)
                result_data = [json.dumps(row) for row in result_data]
            elif return_format == "markdown":
                # Create markdown table
                import pandas as pd
                pandas_df = pd.DataFrame(result_data)
                result_data = pandas_df.to_markdown(index=False)
            # else: dict format (default) - already in correct format
            
            # Step 7: Display preview
            print(f"{'='*80}")
            print("📄 RESULTS PREVIEW (first 10 rows)")
            print(f"{'='*80}")
            # Preview first 10 rows
            for i, row in enumerate(result_data[:10]):
                if return_format == "markdown":
                    break  # Don't print individual rows for markdown
                print(f"Row {i+1}: {row}")
            print(f"{'='*80}\n")
            
            return {
                "success": True,
                "sql": extracted_sql,
                "result": result_data,
                "row_count": row_count,
                "columns": columns,
            }
            
        except Exception as e:
            # Step 8: Handle errors with specific exception types for better diagnostics
            error_type = type(e).__name__
            error_msg = str(e)
            
            # Provide production-grade error categorization
            if "DatabaseError" in error_type or "OperationalError" in error_type:
                error_category = "SQL Execution Error"
                error_hint = "Check SQL syntax and table/column permissions"
            elif "ConnectionError" in error_type or "timeout" in error_msg.lower():
                error_category = "Connection Error"
                error_hint = "Verify SQL Warehouse is running and network connectivity"
            elif "Authentication" in error_msg or "Unauthorized" in error_msg:
                error_category = "Authentication Error"
                error_hint = "Verify access token and warehouse permissions"
            else:
                error_category = "General Error"
                error_hint = "Review full error details below"
            
            print(f"\n{'='*80}")
            print(f"❌ SQL EXECUTION FAILED - {error_category}")
            print(f"{'='*80}")
            print(f"Error Type: {error_type}")
            print(f"Error Message: {error_msg}")
            print(f"Hint: {error_hint}")
            print(f"Warehouse ID: {self.warehouse_id}")
            print(f"{'='*80}\n")
            
            return {
                "success": False,
                "sql": extracted_sql,
                "result": None,
                "row_count": 0,
                "columns": [],
                "error": f"{error_category}: {error_msg}",
                "error_type": error_type,
                "error_hint": error_hint
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
    
    @staticmethod
    def _safe_json_dumps(obj: Any, indent: int = 2) -> str:
        """
        Safely serialize objects to JSON, converting dates/datetime to strings.
        
        Args:
            obj: Object to serialize
            indent: JSON indentation level
            
        Returns:
            JSON string with date/datetime objects converted to ISO format strings
        """
        from datetime import date, datetime
        from decimal import Decimal
        
        def default_handler(o):
            if isinstance(o, (date, datetime)):
                return o.isoformat()
            elif isinstance(o, Decimal):
                return float(o)
            else:
                raise TypeError(f'Object of type {o.__class__.__name__} is not JSON serializable')
        
        return json.dumps(obj, indent=indent, default=default_handler)
    
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
        
        # Stream LLM response for immediate first token emission
        print("🤖 Streaming summary generation...")
        summary = ""
        for chunk in self.llm.stream(summary_prompt):
            if chunk.content:
                summary += chunk.content
        
        summary = summary.strip()
        print(f"✓ Summary stream complete ({len(summary)} chars)")
        
        return summary
    
    def _build_summary_prompt(self, state: AgentState) -> str:
        """Build the prompt for summary generation based on state."""
        
        original_query = state.get('original_query', 'N/A')
        question_clear = state.get('question_clear', False)
        pending_clarification = state.get('pending_clarification')
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
        if not question_clear and pending_clarification:
            clarification_reason = pending_clarification.get('reason', 'Query needs clarification')
            prompt += f"""**Status:** Query needs clarification
**Clarification Needed:** {clarification_reason}
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
                    
                    # TOKEN PROTECTION: Sample results to prevent huge prompts
                    # - Max 10 rows
                    # - Max 10 columns per row
                    # - Max 5000 characters for JSON
                    MAX_PREVIEW_ROWS = 10
                    MAX_PREVIEW_COLS = 10
                    MAX_JSON_CHARS = 5000
                    
                    # Sample rows
                    result_preview = result[:MAX_PREVIEW_ROWS] if len(result) > MAX_PREVIEW_ROWS else result
                    
                    # Sample columns (if result has too many columns)
                    if result_preview and len(columns) > MAX_PREVIEW_COLS:
                        # Keep only first MAX_PREVIEW_COLS columns
                        sampled_cols = columns[:MAX_PREVIEW_COLS]
                        result_preview = [
                            {k: v for k, v in row.items() if k in sampled_cols}
                            for row in result_preview
                        ]
                        col_display = ', '.join(sampled_cols) + f'... (+{len(columns) - MAX_PREVIEW_COLS} more columns)'
                    else:
                        col_display = ', '.join(columns[:10]) + ('...' if len(columns) > 10 else '')
                    
                    # Serialize to JSON
                    result_json = self._safe_json_dumps(result_preview, indent=2)
                    
                    # Truncate JSON if too large
                    if len(result_json) > MAX_JSON_CHARS:
                        result_json = result_json[:MAX_JSON_CHARS] + f'\n... (truncated, {len(result_json) - MAX_JSON_CHARS} chars omitted)'
                    
                    prompt += f"""**Execution:** ✅ Successful
**Rows:** {row_count} rows returned{f' (showing first {MAX_PREVIEW_ROWS})' if row_count > MAX_PREVIEW_ROWS else ''}
**Columns:** {col_display}

**Result Preview:** 
{result_json}
{f'... and {row_count - MAX_PREVIEW_ROWS} more rows' if row_count > MAX_PREVIEW_ROWS else ''}
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

# ==============================================================================
# DEPRECATED FUNCTIONS (Replaced by Intent Detection Service)
# ==============================================================================
# The following functions have been replaced by the IntentDetectionAgent:
# - find_most_recent_clarification_context() → Intent detection handles this
# - is_new_question() → Intent detection provides intent_type classification
#
# These have been removed to simplify the codebase. See:
# - kumc_poc/intent_detection_service.py for the replacement
# - kumc_poc/conversation_models.py for the new data models
# ==============================================================================

# ==============================================================================
# State Extraction Helpers (Token Optimization)
# ==============================================================================
"""
Minimal state extraction helpers to reduce token usage.

Instead of passing the entire AgentState (25+ fields) to each agent,
these helpers extract only the fields each node actually needs.

Expected savings: 60-70% token reduction per node
"""

def extract_intent_detection_context(state: AgentState) -> dict:
    """
    Extract minimal context for intent detection.
    
    OPTIMIZED: Applies message and turn history truncation
    """
    messages = state.get("messages", [])
    turn_history = state.get("turn_history", [])
    
    return {
        "messages": truncate_message_history(messages, max_turns=5),
        "turn_history": truncate_turn_history(turn_history, max_turns=10),
        "user_id": state.get("user_id"),
        "thread_id": state.get("thread_id"),
        # For logging: track original sizes
        "_original_message_count": len(messages),
        "_original_turn_count": len(turn_history)
    }

def extract_clarification_context(state: AgentState) -> dict:
    """
    Extract minimal context for clarification.
    
    OPTIMIZED: Applies message and turn history truncation
    """
    messages = state.get("messages", [])
    turn_history = state.get("turn_history", [])
    
    return {
        "current_turn": state.get("current_turn"),
        "turn_history": truncate_turn_history(turn_history, max_turns=10),
        "intent_metadata": state.get("intent_metadata"),
        "messages": truncate_message_history(messages, max_turns=5),
        # For logging: track original sizes
        "_original_message_count": len(messages),
        "_original_turn_count": len(turn_history)
    }

def extract_planning_context(state: AgentState) -> dict:
    """Extract minimal context for planning."""
    return {
        "current_turn": state.get("current_turn"),
        "intent_metadata": state.get("intent_metadata"),
        "original_query": state.get("original_query")  # Backward compat
    }

def extract_synthesis_table_context(state: AgentState) -> dict:
    """Extract minimal context for table-based SQL synthesis."""
    return {
        "plan": state.get("plan", {}),
        "relevant_space_ids": state.get("relevant_space_ids", [])
    }

def extract_synthesis_genie_context(state: AgentState) -> dict:
    """Extract minimal context for genie-based SQL synthesis."""
    return {
        "plan": state.get("plan", {}),
        "relevant_spaces": state.get("relevant_spaces", []),
        "genie_route_plan": state.get("genie_route_plan")
    }

def extract_execution_context(state: AgentState) -> dict:
    """Extract minimal context for SQL execution."""
    return {
        "sql_query": state.get("sql_query")
    }

def extract_summarize_context(state: AgentState) -> dict:
    """
    Extract minimal context for result summarization.
    
    OPTIMIZED: Applies message history truncation
    """
    messages = state.get("messages", [])
    
    return {
        "messages": truncate_message_history(messages, max_turns=5),
        "sql_query": state.get("sql_query"),
        "execution_result": state.get("execution_result"),
        "execution_error": state.get("execution_error"),
        "sql_synthesis_explanation": state.get("sql_synthesis_explanation"),
        "synthesis_error": state.get("synthesis_error"),
        # For logging: track original size
        "_original_message_count": len(messages)
    }

print("✓ State extraction helpers defined (for token optimization)")

# ==============================================================================
# Message History Truncation (Token Optimization - Priority 3)
# ==============================================================================
"""
Smart message history truncation to keep only recent turns.

Reduces token usage in long conversations by keeping only:
- All SystemMessage instances (prompts)
- Last N HumanMessage/AIMessage pairs

Example: After 10 turns (20 messages):
- Before: 18K tokens
- After: 6K tokens (67% reduction)
"""

def truncate_message_history(
    messages: List, 
    max_turns: int = 5,
    keep_system: bool = True
) -> List:
    """
    Keep only recent turns + system messages.
    
    Args:
        messages: Full message history
        max_turns: Number of recent turns to keep (default 5)
        keep_system: Whether to preserve all SystemMessage instances
        
    Returns:
        Truncated message list
    """
    if not messages:
        return []
    
    # Separate system messages from conversation
    system_msgs = []
    conversation_msgs = []
    
    for msg in messages:
        if isinstance(msg, SystemMessage) and keep_system:
            system_msgs.append(msg)
        else:
            conversation_msgs.append(msg)
    
    # Keep only last N turns (each turn = HumanMessage + AIMessage pair)
    recent_msgs = conversation_msgs[-(max_turns * 2):] if len(conversation_msgs) > max_turns * 2 else conversation_msgs
    
    return system_msgs + recent_msgs


def truncate_turn_history(
    turn_history: List, 
    max_turns: int = 10
) -> List:
    """
    Keep only recent turns in turn_history.
    
    Args:
        turn_history: Full turn history
        max_turns: Number of recent turns to keep (default 10)
        
    Returns:
        Truncated turn history list
    """
    if not turn_history:
        return []
    
    # Keep only last N turns
    return turn_history[-max_turns:] if len(turn_history) > max_turns else turn_history


print("✓ Message truncation functions defined (keeps last 5 message turns, 10 turn_history)")

# ==============================================================================
# Fast-Path Routing Heuristics (Phase 2 Optimization)
# ==============================================================================

def should_use_fast_path(query: str, turn_history: List) -> Dict[str, Any]:
    """
    Determine if query can skip full LLM analysis using fast-path heuristics.
    
    Heuristics for obvious cases that don't need full intent detection:
    1. First query that is detailed and clear (>15 words with SQL keywords)
    2. Follow-up refinements with clear action verbs
    3. Simple data retrieval queries
    
    Args:
        query: Current user query
        turn_history: Conversation history
    
    Returns:
        Dict with:
        - use_fast_path: bool - Whether to skip full LLM analysis
        - intent_type: str - Inferred intent type
        - confidence: float - Confidence in fast-path decision
        - reasoning: str - Explanation
    """
    query_lower = query.lower().strip()
    word_count = len(query.split())
    
    # Heuristic 1: First detailed query with SQL-related keywords
    sql_keywords = ['show', 'get', 'list', 'find', 'how many', 'count', 'sum', 'average', 
                    'total', 'group by', 'where', 'patients', 'claims', 'providers']
    has_sql_intent = any(kw in query_lower for kw in sql_keywords)
    
    if len(turn_history) == 0 and word_count >= 15 and has_sql_intent:
        return {
            "use_fast_path": True,
            "intent_type": "new_question",
            "confidence": 0.85,
            "reasoning": f"First detailed query ({word_count} words) with clear SQL intent",
            "question_clear": True
        }
    
    # Heuristic 2: Follow-up refinements with clear action verbs
    refinement_keywords = ['filter', 'narrow', 'exclude', 'include', 'only', 'just', 
                           'limit to', 'restrict', 'add', 'remove', 'without', 'with']
    has_refinement_intent = any(kw in query_lower for kw in refinement_keywords)
    
    if len(turn_history) > 0 and has_refinement_intent and word_count >= 5:
        return {
            "use_fast_path": True,
            "intent_type": "refinement",
            "confidence": 0.80,
            "reasoning": f"Follow-up refinement with clear intent ({word_count} words)",
            "question_clear": True
        }
    
    # Heuristic 3: Simple retrieval queries (show me, get me, list)
    simple_commands = query_lower.startswith(('show ', 'get ', 'list ', 'display ', 'give me'))
    if simple_commands and word_count >= 6 and has_sql_intent:
        intent = "new_question" if len(turn_history) == 0 else "continuation"
        return {
            "use_fast_path": True,
            "intent_type": intent,
            "confidence": 0.75,
            "reasoning": f"Simple retrieval command with clear structure",
            "question_clear": True
        }
    
    # No fast-path: use full LLM analysis
    return {
        "use_fast_path": False,
        "reasoning": "Query requires full LLM analysis for accurate classification"
    }

print("✓ Fast-path routing heuristics defined (-500ms to -1s for obvious queries)")

# ==============================================================================
# Unified Intent, Context, and Clarification Node (Simplified - No kumc_poc imports)
# ==============================================================================

def check_clarification_rate_limit(turn_history: List[ConversationTurn], window_size: int = 5) -> bool:
    """
    Check if clarification was triggered in the last N turns (sliding window).
    OPTIMIZED: Fast-path checks for common cases.
    
    Args:
        turn_history: List of conversation turns
        window_size: Number of recent turns to check (default: 5)
    
    Returns:
        True if rate limited (skip clarification), False if ok to clarify
    """
    # PHASE 3 OPTIMIZATION: Fast-path for empty history
    if not turn_history:
        return False  # No history = no rate limit
    
    # PHASE 3 OPTIMIZATION: Fast-path check most recent turn first (most likely)
    if turn_history[-1].get("triggered_clarification", False):
        return True  # Rate limited (most recent turn had clarification)
    
    # PHASE 3 OPTIMIZATION: Fast-path for short history
    if len(turn_history) < 2:
        return False  # Only 1 turn and it doesn't have clarification
    
    # Look at remaining recent turns (skip last one, already checked)
    recent_turns = turn_history[max(0, len(turn_history) - window_size):-1]
    
    # Check remaining turns
    for turn in recent_turns:
        if turn.get("triggered_clarification", False):
            return True  # Rate limited
    
    return False  # OK to clarify

print("✓ Clarification rate limit function optimized with fast-path checks (-100 to -200ms)")


@measure_node_time("unified_intent_context_clarification")
def unified_intent_context_clarification_node(state: AgentState) -> dict:
    """
    Unified node that combines intent detection, context generation, and clarity check.
    
    Single LLM call for:
    1. Intent classification (new_question, refinement, continuation, clarification_response)
    2. Context summary generation
    3. Clarity assessment with rate limiting (max 1 per 5 turns)
    
    Returns: Dictionary with state updates
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    def stream_markdown_response(content: str, label: str = "Response"):
        """
        DEPRECATED: For local/notebook testing only.
        In production, use writer() events instead for UI display.
        This function only prints to console/logs, not to model serving UI.
        """
        print(f"\n✨ {label}:")
        print("-" * 80)
        
        # Print content immediately without character-by-character delay
        print(content)
        
        print("-" * 80)
    
    def format_clarification_markdown(reason: str, options: list = None) -> str:
        """
        Format clarification reason and options as professional markdown.
        
        Args:
            reason: The clarification reason text
            options: List of clarification options
            
        Returns:
            Formatted markdown string
        """
        # Start with heading and reason
        markdown = f"### Clarification Needed\n\n{reason}\n\n"
        
        # Add options if provided
        if options and len(options) > 0:
            markdown += "**Please choose from the following options:**\n\n"
            for i, option in enumerate(options, 1):
                markdown += f"{i}. {option}\n\n"
        
        return markdown.strip()
    
    def format_meta_answer_markdown(answer: str) -> str:
        """
        Format meta-answer as professional markdown if not already formatted.
        
        Args:
            answer: The meta answer text
            
        Returns:
            Formatted markdown string
        """
        # Check if already formatted (has markdown headings)
        if answer.startswith("#") or "**" in answer:
            return answer  # Already formatted
        
        # Add basic formatting
        markdown = f"## Available Capabilities\n\n{answer}"
        return markdown
    
    print("\n" + "="*80)
    print("🎯 UNIFIED INTENT, CONTEXT & CLARIFICATION AGENT")
    print("="*80)
    
    # Get current query from messages
    messages = state.get("messages", [])
    turn_history = state.get("turn_history", [])
    
    human_messages = [m for m in messages if isinstance(m, HumanMessage)]
    current_query = human_messages[-1].content if human_messages else ""
    
    writer({"type": "agent_start", "agent": "unified_intent_context_clarification", "query": current_query})
    
    print(f"Query: {current_query}")
    print(f"Turn history: {len(turn_history)} turns")
    
    # PHASE 2 OPTIMIZATION: Check if we can use fast-path routing
    fast_path_result = should_use_fast_path(current_query, turn_history)
    
    if fast_path_result["use_fast_path"]:
        print(f"🚀 FAST-PATH ACTIVATED: {fast_path_result['reasoning']}")
        print(f"   Intent: {fast_path_result['intent_type']} (confidence: {fast_path_result['confidence']:.2f})")
        print(f"   Skipping full LLM analysis (-500ms to -1s)")
        
        writer({
            "type": "fast_path_activated",
            "intent_type": fast_path_result['intent_type'],
            "confidence": fast_path_result['confidence'],
            "reasoning": fast_path_result['reasoning']
        })
        
        # Create simplified context summary for fast-path
        context_summary = f"{current_query}"
        if turn_history:
            last_query = turn_history[-1]['query']
            context_summary = f"Building on previous query '{last_query[:50]}...', user asks: {current_query}"
        
        # Create conversation turn with fast-path results
        turn = create_conversation_turn(
            query=current_query,
            intent_type=fast_path_result['intent_type'],
            parent_turn_id=None,
            context_summary=context_summary,
            triggered_clarification=False,
            metadata={"fast_path": True, "confidence": fast_path_result['confidence']}
        )
        
        # Create intent metadata
        intent_metadata = IntentMetadata(
            intent_type=fast_path_result['intent_type'],
            confidence=fast_path_result['confidence'],
            reasoning=fast_path_result['reasoning'],
            topic_change_score=0.5,
            domain=None,
            operation=None,
            complexity="simple" if fast_path_result['intent_type'] == "refinement" else "moderate",
            parent_turn_id=None
        )
        
        # Return early - skip to planning
        return {
            "current_turn": turn,
            "turn_history": [turn],
            "intent_metadata": intent_metadata,
            "question_clear": True,  # Fast-path assumes clear queries
            "pending_clarification": None,
            "next_agent": "planning",
            "messages": [
                SystemMessage(content=f"Fast-path: {fast_path_result['intent_type']} (skipped LLM analysis)")
            ]
        }
    
    # If not fast-path, continue with full LLM analysis
    print("🔄 Using full LLM analysis (query requires detailed classification)")
    
    # Format conversation context
    conversation_context = ""
    if turn_history:
        conversation_context = "Previous conversation:\n"
        for i, turn in enumerate(turn_history[-5:], 1):  # Last 5 turns
            intent_label = turn['intent_type'].replace('_', ' ').title()
            conversation_context += f"{i}. [{intent_label}] {turn['query']}\n"
            if turn.get('context_summary'):
                conversation_context += f"   Context: {turn['context_summary'][:1000]}...\n"
    else:
        conversation_context = "No previous conversation (first query)."
    
    # Load space context for clarity check
    space_context = load_space_context(TABLE_NAME)
    
    # Single unified prompt for intent + context + clarity + meta-question detection
    unified_prompt = f"""Analyze the user's query in the context of the conversation history.

Current Query: {current_query}

Conversation History:
{conversation_context}

Available Data Sources:
{json.dumps(space_context, indent=2)}

## Task 1: Detect Meta-Questions (NEW)
First, determine if this is a META-QUESTION about the system itself:
- Questions about available tables, data sources, spaces, schemas
- Questions about system capabilities, what data is available
- Questions about the structure or organization of data

If it's a meta-question, you MUST:
1. Set "is_meta_question": true
2. Generate a direct answer using the Available Data Sources above
3. Provide a clear, informative response about what's available

## Task 2: Classify Intent
Classify the query into ONE of these categories:
1. **new_question**: A completely different topic/domain from previous queries
2. **refinement**: Narrowing/filtering/modifying the previous query on same topic
3. **continuation**: Follow-up exploring same topic from different angle
4. **clarification_response**: User is providing the clarification response to the clarification request

## Task 3: Generate Context Summary
Create a 2-3 sentence summary that:
- Synthesizes the conversation history
- States clearly what the user wants
- Is actionable for SQL query planning

## Task 4: Check Clarity
Determine if the query is clear enough to generate SQL:
- Is the question clear and answerable as-is? (BE LENIENT - default to TRUE)
- ONLY mark as unclear if CRITICAL information is missing
- If unclear, provide 2-3 specific clarification options
- Never mark as unclear if the question is a clarification response to a previous clarification request
- Meta-questions should always be marked as clear

Return ONLY valid JSON:
{{
  "is_meta_question": true/false,
  "meta_answer": "Direct answer formatted as professional markdown (if is_meta_question=true)" or null,
  "intent_type": "new_question" | "refinement" | "continuation" | "clarification_response",
  "confidence": 0.95,
  "context_summary": "2-3 sentence summary for planning agent",
  "question_clear": true/false,
  "clarification_reason": "Why unclear formatted as markdown with headings, bullets, bold keywords (if question_clear=false)" or null,
  "clarification_options": ["Option 1 with description", "Option 2 with description", "Option 3 with description"] or null,
  "metadata": {{
    "domain": "patients | claims | providers | medications | ...",
    "complexity": "simple | moderate | complex",
    "topic_change_score": 0.8
  }}
}}

IMPORTANT Markdown Formatting Guidelines:
- When is_meta_question=true: Format meta_answer with ## heading, **bold** keywords, bullet lists, proper spacing
- When question_clear=false: Format clarification_reason with ### heading, explain issue clearly, incorporate clarification_options as numbered list with descriptions, use **bold** for key terms
- Use professional but friendly tone appropriate for healthcare analytics
- Ensure the markdown is ready to display directly to end users
"""
    
    # Call LLM with invoke for clean output (using pooled connection)
    llm = get_pooled_llm(LLM_ENDPOINT_CLARIFICATION)
    track_agent_model_usage("clarification", LLM_ENDPOINT_CLARIFICATION)
    
    try:
        print("🤖 Calling unified LLM for intent & context analysis...")
        
        # Use invoke for clean, complete output (no streaming artifacts)
        response = llm.invoke(unified_prompt)
        content = response.content
        
        print(f"✓ Analysis complete ({len(content)} chars)")
        
        # Parse JSON response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        result = json.loads(content)
        
        # Extract results
        is_meta_question = result.get("is_meta_question", False)
        meta_answer = result.get("meta_answer")
        intent_type = result["intent_type"].lower()
        confidence = result["confidence"]
        context_summary = result["context_summary"]
        question_clear = result["question_clear"]
        clarification_reason = result.get("clarification_reason")
        clarification_options = result.get("clarification_options", [])
        metadata = result.get("metadata", {})
        
        print(f"✓ Intent: {intent_type} (confidence: {confidence:.2f})")
        print(f"  Context: {context_summary[:100]}...")
        print(f"  Question clear: {question_clear}")
        print(f"  Meta-question: {is_meta_question}")
        
        # Create conversation turn
        turn = create_conversation_turn(
            query=current_query,
            intent_type=intent_type,
            parent_turn_id=None,  # Could extract from history if needed
            context_summary=context_summary,
            triggered_clarification=False,  # Will be updated if clarification triggered
            metadata=metadata
        )
        
        # Create intent metadata
        intent_metadata = IntentMetadata(
            intent_type=intent_type,
            confidence=confidence,
            reasoning=f"Unified analysis: {intent_type}",
            topic_change_score=metadata.get("topic_change_score", 0.5),
            domain=metadata.get("domain"),
            operation=None,
            complexity=metadata.get("complexity", "moderate"),
            parent_turn_id=None
        )
        
        # Emit events
        writer({
            "type": "intent_detected",
            "intent_type": intent_type,
            "confidence": confidence,
            "complexity": metadata.get("complexity", "moderate")
        })
        
        # NEW: Check if this is a meta-question - handle immediately
        if is_meta_question and meta_answer:
            print("🔍 Meta-question detected - answering directly without SQL")
            
            # Create turn for meta-question
            turn["metadata"]["is_meta_question"] = True
            
            writer({
                "type": "meta_question_detected",
                "answer_preview": meta_answer[:100]
            })
            
            # Ensure meta-answer is formatted as markdown
            formatted_meta_answer = format_meta_answer_markdown(meta_answer)
            
            # Emit markdown content as custom event for UI display
            writer({
                "type": "meta_answer_content",
                "content": formatted_meta_answer
            })
            
            # Return with meta-answer and flag to skip SQL generation
            return {
                "current_turn": turn,
                "turn_history": [turn],
                "intent_metadata": IntentMetadata(
                    intent_type=intent_type,
                    confidence=confidence,
                    reasoning=f"Meta-question: {intent_type}",
                    topic_change_score=metadata.get("topic_change_score", 0.5),
                    domain=metadata.get("domain"),
                    operation=None,
                    complexity=metadata.get("complexity", "simple"),
                    parent_turn_id=None
                ),
                "question_clear": True,
                "is_meta_question": True,  # Flag for routing
                "meta_answer": meta_answer,  # Direct answer
                "pending_clarification": None,
                "messages": [
                    AIMessage(content=meta_answer),
                    SystemMessage(content="Meta-question answered directly, skipping SQL generation")
                ]
            }
        
        # Check if clarification needed
        if not question_clear:
            print(f"⚠ Query unclear: {clarification_reason}")
            
            # Check rate limit
            is_rate_limited = check_clarification_rate_limit(turn_history, window_size=5)
            
            if is_rate_limited:
                print("⚠ Clarification rate limit reached (1 per 5 turns)")
                print("  Proceeding with best-effort interpretation")
                
                writer({"type": "clarification_skipped", "reason": "Rate limited (1 per 5 turns)"})
                
                # Force proceed to planning
                return {
                    "current_turn": turn,
                    "turn_history": [turn],
                    "intent_metadata": intent_metadata,
                    "question_clear": True,  # Force clear
                    "pending_clarification": None,
                    "messages": [
                        SystemMessage(content=f"Clarification rate limited. Proceeding with: {context_summary}")
                    ]
                }
            else:
                # OK to clarify
                print("✓ Requesting clarification from user")
                
                # Create clarification request
                clarification_request = create_clarification_request(
                    reason=clarification_reason or "Query needs more specificity",
                    options=clarification_options,
                    turn_id=turn["turn_id"],
                    best_guess=context_summary,
                    best_guess_confidence=confidence
                )
                
                # Mark turn as triggering clarification
                turn["triggered_clarification"] = True
                
                writer({"type": "clarification_requested", "reason": clarification_reason})
                
                # Format clarification with options as markdown
                formatted_clarification = format_clarification_markdown(
                    reason=clarification_reason,
                    options=clarification_options
                )
                
                # Emit markdown content as custom event for UI display
                writer({
                    "type": "clarification_content",
                    "content": formatted_clarification
                })
                
                return {
                    "current_turn": turn,
                    "turn_history": [turn],
                    "intent_metadata": intent_metadata,
                    "question_clear": False,
                    "pending_clarification": clarification_request,
                    "messages": [
                        AIMessage(content=formatted_clarification),
                        SystemMessage(content=f"Clarification requested for turn {turn['turn_id']}")
                    ]
                }
        else:
            # Question is clear, proceed to planning
            print("✓ Query is clear - proceeding to planning")
            
            writer({"type": "clarity_analysis", "clear": True, "reasoning": "Query is clear and answerable"})
            
            return {
                "current_turn": turn,
                "turn_history": [turn],
                "intent_metadata": intent_metadata,
                "question_clear": True,
                "pending_clarification": None,
                "messages": [
                    SystemMessage(content=f"Intent: {intent_type}, proceeding to planning")
                ]
            }
        
    except Exception as e:
        print(f"❌ Unified agent error: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: create minimal turn and proceed
        turn = create_conversation_turn(
            query=current_query,
            intent_type="new_question",
            context_summary=f"Query: {current_query}",
            triggered_clarification=False,
            metadata={}
        )
        
        intent_metadata = IntentMetadata(
            intent_type="new_question",
            confidence=0.5,
            reasoning=f"Error fallback: {str(e)}",
            topic_change_score=1.0,
            domain=None,
            operation=None,
            complexity="moderate",
            parent_turn_id=None
        )
        
        return {
            "current_turn": turn,
            "turn_history": [turn],
            "intent_metadata": intent_metadata,
            "question_clear": True,  # Proceed despite error
            "pending_clarification": None,
            "messages": [
                SystemMessage(content=f"Unified agent error (proceeding anyway): {str(e)}")
            ]
        }

print("✓ Unified intent, context, and clarification node defined")

@measure_node_time("planning")
def planning_node(state: AgentState) -> dict:
    """
    Planning node wrapping PlanningAgent class using turn-based context.
    
    IMPROVEMENTS:
    - Uses current_turn.context_summary (LLM-generated) instead of manual combined_query_context
    - Intent-aware planning (different strategies for refinements vs new questions)
    - Clean separation from clarification logic
    
    OPTIMIZED: Uses minimal state extraction to reduce token usage
    
    Returns: Dictionary with only the state updates (for clean MLflow traces)
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    print("\n" + "="*80)
    print("📋 PLANNING AGENT (Token Optimized)")
    print("="*80)
    
    # OPTIMIZATION: Extract only minimal context needed for planning
    context = extract_planning_context(state)
    print(f"📊 State optimization: Using {len(context)} fields (vs {len([k for k in state.keys() if state.get(k) is not None])} in full state)")
    
    # Get current turn and intent from state
    current_turn = context.get("current_turn")
    if not current_turn:
        # Fallback for backward compatibility
        print("⚠ No current_turn found, falling back to legacy behavior")
        query = context.get("original_query", "")
        intent_type = "new_question"
        context_summary = None
    else:
        query = current_turn["query"]
        intent_type = current_turn.get("intent_type", "new_question")
        context_summary = current_turn.get("context_summary")
    
    # Use context_summary if available (LLM-generated from intent detection)
    # This replaces the manual combined_query_context template
    planning_query = context_summary or query
    
    # Emit agent start event
    writer({"type": "agent_start", "agent": "planning", "query": planning_query[:100]})
    
    print(f"Query: {query}")
    print(f"Intent: {intent_type}")
    if context_summary:
        print(f"✓ Using context summary from intent detection")
        print(f"  Summary: {context_summary[:200]}...")
    else:
        print(f"✓ Using query directly (no context needed)")
    
    # OPTIMIZATION: Use cached agent instance
    planning_agent = get_cached_planning_agent()
    track_agent_model_usage("planning", LLM_ENDPOINT_PLANNING)
    
    # PHASE 2 OPTIMIZATION: Vector search result caching for refinements
    thread_id = state.get("thread_id", "default")
    intent_metadata = state.get("intent_metadata", {})
    can_reuse_cache = intent_type in ["refinement", "clarification_response", "continuation"]
    
    relevant_spaces_full = None
    cache_hit = False
    
    if can_reuse_cache and thread_id in _vector_search_cache:
        cache_entry = _vector_search_cache[thread_id]
        cache_age = datetime.now() - cache_entry["timestamp"]
        
        if cache_age < _VECTOR_SEARCH_CACHE_TTL:
            record_cache_hit("vector_search")
            relevant_spaces_full = cache_entry["results"]
            cache_hit = True
            print(f"🚀 VECTOR SEARCH CACHE HIT (thread: {thread_id}, age: {cache_age.seconds}s)")
            print(f"   Reusing {len(relevant_spaces_full)} spaces for {intent_type} query")
            print(f"   Expected gain: -300 to -800ms")
            
            writer({
                "type": "vector_search_cache_hit",
                "thread_id": thread_id,
                "intent_type": intent_type,
                "space_count": len(relevant_spaces_full)
            })
        else:
            print(f"⚠️ Vector search cache expired (age: {cache_age.seconds}s > {_VECTOR_SEARCH_CACHE_TTL.seconds}s)")
    
    # If no cache hit, perform vector search
    if relevant_spaces_full is None:
        record_cache_miss("vector_search")
        # Emit vector search start event
        writer({"type": "vector_search_start", "index": VECTOR_SEARCH_INDEX})
        
        # Get relevant spaces with full metadata (for Genie agents)
        # Use planning_query which includes context_summary if available
        print(f"🔍 Performing vector search (cache miss or new question)...")
        relevant_spaces_full = planning_agent.search_relevant_spaces(planning_query)
        
        # Cache results for future refinements
        _vector_search_cache[thread_id] = {
            "query": planning_query,
            "results": relevant_spaces_full,
            "timestamp": datetime.now()
        }
        print(f"✓ Cached vector search results for thread: {thread_id}")
    
    # Emit vector search results
    writer({"type": "vector_search_results", "spaces": relevant_spaces_full, "count": len(relevant_spaces_full)})
    
    # Emit plan formulation start
    writer({"type": "agent_thinking", "agent": "planning", "content": "Creating execution plan..."})
    
    # Create execution plan
    # IMPORTANT: Use planning_query (with context_summary) not just query
    # Pass original_query so it can be shown in the prompt before context_summary
    plan = planning_agent.create_execution_plan(planning_query, relevant_spaces_full, original_query=query)
    
    # Extract plan components
    join_strategy = plan.get("join_strategy")
    
    # Emit plan formulation result
    writer({"type": "plan_formulation", "strategy": join_strategy, "requires_join": plan.get("requires_join", False)})
    
    # Determine next agent
    if join_strategy == "genie_route":
        print("✓ Plan complete - using GENIE ROUTE (Genie agents)")
        next_agent = "sql_synthesis_genie"
    else:
        print("✓ Plan complete - using TABLE ROUTE (direct SQL synthesis)")
        next_agent = "sql_synthesis_table"
    
    # Return only updates (no in-place modifications)
    return {
        "plan": plan,
        "sub_questions": plan.get("sub_questions", []),
        "requires_multiple_spaces": plan.get("requires_multiple_spaces", False),
        "relevant_space_ids": plan.get("relevant_space_ids", []),
        "requires_join": plan.get("requires_join", False),
        "join_strategy": join_strategy,
        "execution_plan": plan.get("execution_plan", ""),
        "genie_route_plan": plan.get("genie_route_plan"),
        "vector_search_relevant_spaces_info": plan.get("vector_search_relevant_spaces_info", []),
        "relevant_spaces": relevant_spaces_full,
        "next_agent": next_agent,
        "messages": [
            SystemMessage(content=f"Execution plan: {json.dumps(plan, indent=2)}")
        ]
    }


@measure_node_time("sql_synthesis_table")
def sql_synthesis_table_node(state: AgentState) -> dict:
    """
    Fast SQL synthesis node wrapping SQLSynthesisTableAgent class.
    Combines OOP modularity with explicit state management.
    
    OPTIMIZED: Uses minimal state extraction to reduce token usage
    
    Returns: Dictionary with only the state updates (for clean MLflow traces)
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    print("\n" + "="*80)
    print("⚡ SQL SYNTHESIS AGENT - TABLE ROUTE (Token Optimized)")
    print("="*80)
    
    # OPTIMIZATION: Extract only minimal context needed for table-based synthesis
    context = extract_synthesis_table_context(state)
    print(f"📊 State optimization: Using {len(context)} fields (vs {len([k for k in state.keys() if state.get(k) is not None])} in full state)")
    
    plan = context.get("plan", {})
    relevant_space_ids = context.get("relevant_space_ids", [])
    
    # Emit synthesis start event
    writer({"type": "sql_synthesis_start", "route": "table", "spaces": relevant_space_ids})
    
    # OPTIMIZATION: Use cached agent instance
    sql_agent = get_cached_sql_table_agent()
    track_agent_model_usage("sql_synthesis_table", LLM_ENDPOINT_SQL_SYNTHESIS_TABLE)
    
    print("plan loaded from state is:", plan)
    print(json.dumps(plan, indent=2))
    
    try:
        print("🤖 Invoking SQL synthesis agent...")
        
        # Emit detailed start event
        writer({"type": "agent_thinking", "agent": "sql_synthesis_table", "content": "🧠 Starting SQL synthesis using UC function tools..."})
        writer({"type": "agent_step", "agent": "sql_synthesis_table", "step": "analyzing_plan", "content": f"📋 Analyzing execution plan for {len(relevant_space_ids)} relevant spaces"})
        
        # Emit tool preparation event
        uc_functions = ["get_space_summary", "get_table_overview", "get_column_detail", "get_space_details"]
        writer({"type": "tools_available", "agent": "sql_synthesis_table", "tools": uc_functions, "content": f"🔧 Available UC functions: {', '.join(uc_functions)}"})
        
        # Emit query strategy
        writer({"type": "agent_thinking", "agent": "sql_synthesis_table", "content": f"🎯 Strategy: Query metadata for spaces {relevant_space_ids} then synthesize SQL"})
        
        # Call the agent
        result = sql_agent(plan)
        
        # Emit tool completion event
        writer({"type": "agent_step", "agent": "sql_synthesis_table", "step": "metadata_gathered", "content": "✅ Metadata collection complete, synthesizing SQL query..."})
        
        # Extract SQL and explanation
        sql_query = result.get("sql")
        explanation = result.get("explanation", "")
        has_sql = result.get("has_sql", False)
        
        if has_sql and sql_query and explanation:
            print("✓ SQL query synthesized successfully")
            print(f"SQL Preview: {sql_query[:200]}...")
            if explanation:
                print(f"Agent Explanation: {explanation[:200]}...")
            
            # Emit detailed success events
            writer({"type": "sql_generated", "agent": "sql_synthesis_table", "query_preview": sql_query[:200], "content": f"💻 SQL Query Generated ({len(sql_query)} chars)"})
            writer({"type": "agent_result", "agent": "sql_synthesis_table", "result": "success", "content": f"✅ SQL synthesis complete: {explanation[:150]}..."})
            
            # Return updates for successful synthesis
            return {
                "sql_query": sql_query,
                "has_sql": has_sql,
                "sql_synthesis_explanation": explanation,
                "next_agent": "sql_execution",
                "messages": [
                    AIMessage(content=f"SQL Synthesis (Table Route):\n{explanation}")
                ]
            }
        else:
            print("⚠ No SQL generated - agent explanation:")
            print(f"  {explanation}")
            
            # Emit failure event
            writer({"type": "agent_result", "agent": "sql_synthesis_table", "result": "no_sql", "content": f"⚠️ Could not generate SQL: {explanation[:150]}..."})
            
            # Return updates for failed synthesis
            return {
                "synthesis_error": "Cannot generate SQL query",
                "sql_synthesis_explanation": explanation,
                "next_agent": "summarize",
                "messages": [
                    AIMessage(content=f"SQL Synthesis Failed (Table Route):\n{explanation}")
                ]
            }
        
    except Exception as e:
        print(f"❌ SQL synthesis failed: {e}")
        error_msg = str(e)
        # Return updates for exception
        return {
            "synthesis_error": error_msg,
            "sql_synthesis_explanation": error_msg,
            "messages": [
                AIMessage(content=f"SQL Synthesis Failed (Table Route):\n{error_msg}")
            ]
        }


@measure_node_time("sql_synthesis_genie")
def sql_synthesis_genie_node(state: AgentState) -> dict:
    """
    Slow SQL synthesis node wrapping SQLSynthesisGenieAgent class.
    Combines OOP modularity with explicit state management.
    
    Uses relevant_spaces from PlanningAgent (no need to re-query all spaces).
    
    OPTIMIZED: Uses minimal state extraction to reduce token usage
    
    Returns: Dictionary with only the state updates (for clean MLflow traces)
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    print("\n" + "="*80)
    print("🐢 SQL SYNTHESIS AGENT - GENIE ROUTE (Token Optimized)")
    print("="*80)
    
    # OPTIMIZATION: Extract only minimal context needed for genie-based synthesis
    context = extract_synthesis_genie_context(state)
    print(f"📊 State optimization: Using {len(context)} fields (vs {len([k for k in state.keys() if state.get(k) is not None])} in full state)")
    
    # Get relevant spaces from state (already discovered by PlanningAgent)
    relevant_spaces = context.get("relevant_spaces", [])
    relevant_space_ids = [s.get("space_id") for s in relevant_spaces if s.get("space_id")]
    
    # Emit synthesis start event
    writer({"type": "sql_synthesis_start", "route": "genie", "spaces": relevant_space_ids})
    
    # Use dedicated SQL_SYNTHESIS_GENIE endpoint for orchestrating multiple Genie agents
    # This agent requires stronger reasoning for complex coordination
    llm = get_pooled_llm(LLM_ENDPOINT_SQL_SYNTHESIS_GENIE, temperature=0.1)
    
    if not relevant_spaces:
        print("❌ No relevant_spaces found in state")
        # Return error update
        return {
            "synthesis_error": "No relevant spaces available for genie route"
        }
    
    # Use OOP agent - only creates Genie agents for relevant spaces
    sql_agent = SQLSynthesisGenieAgent(llm, relevant_spaces)
    track_agent_model_usage("sql_synthesis_genie", LLM_ENDPOINT_SQL_SYNTHESIS_GENIE)
    
    # Use minimal context (already extracted)
    plan = context.get("plan", {})
    genie_route_plan = context.get("genie_route_plan") or plan.get("genie_route_plan", {})
    
    if not genie_route_plan:
        print("❌ No genie_route_plan found in plan")
        # Return error update
        return {
            "synthesis_error": "No routing plan available for genie route"
        }
    
    try:
        print(f"🤖 Querying {len(genie_route_plan)} Genie agents...")
        
        # Emit detailed start event
        writer({"type": "agent_thinking", "agent": "sql_synthesis_genie", "content": f"🧠 Starting SQL synthesis using {len(genie_route_plan)} Genie agents..."})
        writer({"type": "agent_step", "agent": "sql_synthesis_genie", "step": "preparing_genie_calls", "content": f"📋 Preparing to query {len(genie_route_plan)} Genie spaces"})
        
        # Emit detailed events for each Genie agent call with full context
        for idx, (space_id, query) in enumerate(genie_route_plan.items(), 1):
            space_title = next((s.get("space_title", space_id) for s in relevant_spaces if s.get("space_id") == space_id), space_id)
            writer({
                "type": "genie_agent_call", 
                "agent": "sql_synthesis_genie",
                "space_id": space_id, 
                "space_title": space_title,
                "query": query,
                "content": f"🤖 [{idx}/{len(genie_route_plan)}] Calling Genie agent '{space_title}' with query: {query[:100]}{'...' if len(query) > 100 else ''}"
            })
        
        # Emit execution strategy
        writer({"type": "agent_thinking", "agent": "sql_synthesis_genie", "content": "⚡ Executing Genie agents in parallel for optimal performance..."})
        
        # Call the agent
        result = sql_agent(plan)
        
        # Emit completion event
        writer({"type": "agent_step", "agent": "sql_synthesis_genie", "step": "combining_results", "content": "🔄 All Genie agents responded, combining SQL fragments..."})
        
        # Extract SQL and explanation
        sql_query = result.get("sql")
        explanation = result.get("explanation", "")
        has_sql = result.get("has_sql", False)
        
        # Update explicit state
        if has_sql and sql_query and explanation:
            print("✓ SQL fragments combined successfully")
            print(f"SQL Preview: {sql_query[:200]}...")
            if explanation:
                print(f"Agent Explanation: {explanation[:200]}...")
            
            # Emit detailed success events
            writer({"type": "sql_generated", "agent": "sql_synthesis_genie", "query_preview": sql_query[:200], "content": f"💻 Combined SQL Query Generated ({len(sql_query)} chars)"})
            writer({"type": "agent_result", "agent": "sql_synthesis_genie", "result": "success", "content": f"✅ SQL synthesis complete: {explanation[:150]}..."})
            writer({"type": "agent_thinking", "agent": "sql_synthesis_genie", "content": f"🎯 Successfully combined SQL from {len(genie_route_plan)} Genie agents"})
            
            # Return updates for successful synthesis
            return {
                "sql_query": sql_query,
                "has_sql": has_sql,
                "sql_synthesis_explanation": explanation,
                "next_agent": "sql_execution",
                "messages": [
                    AIMessage(content=f"SQL Synthesis (Genie Route):\n{explanation}")
                ]
            }
        else:
            print("⚠ No SQL generated - agent explanation:")
            print(f"  {explanation}")
            
            # Emit detailed failure event
            writer({"type": "agent_result", "agent": "sql_synthesis_genie", "result": "no_sql", "content": f"⚠️ Could not generate SQL from Genie agents: {explanation[:150]}..."})
            
            # Return updates for failed synthesis
            return {
                "synthesis_error": "Cannot generate SQL query from Genie agent fragments",
                "sql_synthesis_explanation": explanation,
                "next_agent": "summarize",
                "messages": [
                    AIMessage(content=f"SQL Synthesis Failed (Genie Route):\n{explanation}")
                ]
            }
        
    except Exception as e:
        print(f"❌ SQL synthesis failed: {e}")
        error_msg = str(e)
        # Return updates for exception
        return {
            "synthesis_error": error_msg,
            "sql_synthesis_explanation": error_msg,
            "messages": [
                AIMessage(content=f"SQL Synthesis Failed (Genie Route):\n{error_msg}")
            ]
        }


@measure_node_time("sql_execution")
def sql_execution_node(state: AgentState) -> dict:
    """
    SQL execution node wrapping SQLExecutionAgent class.
    Combines OOP modularity with explicit state management.
    
    OPTIMIZED: Uses minimal state extraction to reduce token usage
    
    Returns: Dictionary with only the state updates (for clean MLflow traces)
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    print("\n" + "="*80)
    print("🚀 SQL EXECUTION AGENT (Token Optimized)")
    print("="*80)
    
    # OPTIMIZATION: Extract only minimal context needed for execution
    context = extract_execution_context(state)
    print(f"📊 State optimization: Using {len(context)} fields (vs {len([k for k in state.keys() if state.get(k) is not None])} in full state)")
    
    sql_query = context.get("sql_query")
    
    if not sql_query:
        print("❌ No SQL query to execute")
        # Return error update
        return {
            "execution_error": "No SQL query provided"
        }
    
    # Emit validation start event
    writer({"type": "sql_validation_start", "query": sql_query[:200]})
    
    # Emit execution start event
    writer({"type": "sql_execution_start", "estimated_complexity": "standard"})
    
    # Use OOP agent with SQL Warehouse
    execution_agent = SQLExecutionAgent(warehouse_id=SQL_WAREHOUSE_ID)
    result = execution_agent(sql_query)
    
    # Prepare updates based on result
    updates = {
        "execution_result": result,
        "next_agent": "summarize",
        "messages": []
    }
    
    if result["success"]:
        print(f"✓ Query executed successfully!")
        print(f"📊 Rows returned: {result['row_count']}")
        print(f"📋 Columns: {', '.join(result['columns'])}")
        
        # Emit execution complete event
        writer({"type": "sql_execution_complete", "rows": result['row_count'], "columns": result['columns']})
        
        updates["messages"].append(
            SystemMessage(content=f"Execution successful: {result['row_count']} rows returned")
        )
    else:
        print(f"❌ SQL execution failed: {result.get('error', 'Unknown error')}")
        updates["execution_error"] = result.get("error")
        
        updates["messages"].append(
            SystemMessage(content=f"Execution failed: {result.get('error')}")
        )
    
    return updates


@measure_node_time("summarize")
def summarize_node(state: AgentState) -> dict:
    """
    Result summarize node wrapping ResultSummarizeAgent class.
    
    This is the final node that all workflow paths go through.
    Generates a natural language summary AND preserves all workflow data.
    
    OPTIMIZED: Uses minimal state extraction to reduce token usage
    
    Returns: Dictionary with only the state updates (for clean MLflow traces)
    """
    from langgraph.config import get_stream_writer
    
    writer = get_stream_writer()
    
    print("\n" + "="*80)
    print("📝 RESULT SUMMARIZE AGENT (Token Optimized)")
    print("="*80)
    
    # OPTIMIZATION: Extract only minimal context needed for summarization
    context = extract_summarize_context(state)
    print(f"📊 State optimization: Using {len(context)} fields (vs {len([k for k in state.keys() if state.get(k) is not None])} in full state)")
    
    # Emit summary start event
    writer({"type": "summary_start", "content": "Generating comprehensive summary..."})
    
    # OPTIMIZATION: Use cached agent instance
    summarize_agent = get_cached_summarize_agent()
    track_agent_model_usage("summarize", LLM_ENDPOINT_SUMMARIZE)
    summary = summarize_agent(context)
    
    # Display what's being returned
    print(f"\n📦 State Fields Being Returned:")
    print(f"  ✓ final_summary: {len(summary)} chars")
    if context.get("sql_query"):
        print(f"  ✓ sql_query: {len(context['sql_query'])} chars")
    if context.get("execution_result"):
        exec_result = context["execution_result"]
        if exec_result.get("success"):
            print(f"  ✓ execution_result: {exec_result.get('row_count', 0)} rows")
        else:
            print(f"  ✓ execution_result: Failed - {exec_result.get('error', 'Unknown')[:50]}...")
    if context.get("sql_synthesis_explanation"):
        print(f"  ✓ sql_synthesis_explanation: {len(context['sql_synthesis_explanation'])} chars")
    if state.get("execution_plan"):
        print(f"  ✓ execution_plan: {state['execution_plan'][:80]}...")
    if state.get("synthesis_error"):
        print(f"  ⚠ synthesis_error: {state['synthesis_error'][:50]}...")
    if state.get("execution_error"):
        print(f"  ⚠ execution_error: {state['execution_error'][:50]}...")
    
    print("="*80)
    
    # Emit summary completion event
    writer({"type": "summary_complete", "content": f"✅ Summary generated ({len(summary)} chars)"})
    
    # Build a concise final message for AIMessage (avoid duplication with final_summary)
    # Only include execution results and errors (summary goes to final_summary field)
    final_message_parts = []
    
    # 1. Execution Results (if available)
    exec_result = state.get("execution_result")
    if exec_result and exec_result.get("success"):
        results = exec_result.get("result", [])
        if results:
            try:
                import pandas as pd
                df = pd.DataFrame(results)
                
                # Display DataFrame in notebook
                print("\n" + "="*80)
                print("📊 QUERY RESULTS (Pandas DataFrame)")
                print("="*80)
                try:
                    display(df)  # Use Databricks display() for interactive view
                except:
                    print(df.to_string())  # Fallback to string representation
                print("="*80 + "\n")
                
                # Add compact results info to message
                final_message_parts.append(f"\n📊 **Query Results:** {df.shape[0]} rows × {df.shape[1]} columns")
                final_message_parts.append(f"\nPreview (first 5 rows):\n```\n{df.head().to_string()}\n```")
                
            except Exception as e:
                final_message_parts.append(f"\n⚠️ Could not format results: {e}")
                final_message_parts.append(f"Raw results (first 3): {results[:3]}")
    
    # 2. Error messages (if any) 
    if state.get("synthesis_error"):
        final_message_parts.append(f"\n❌ **SQL Synthesis Error:** {state['synthesis_error']}")
    if state.get("execution_error"):
        final_message_parts.append(f"\n❌ **Execution Error:** {state['execution_error']}")
    
    # Combine into final message (results/errors only - summary in final_summary field)
    # If no results or errors, use a simple completion message
    final_message = "\n".join(final_message_parts) if final_message_parts else "✅ Execution complete"
    
    print(f"\n✅ AIMessage created with results/errors ({len(final_message)} chars)")
    print(f"✅ Summary stored in final_summary field ({len(summary)} chars)")
    
    # Route to END via fixed edge (summarize → END)
    # Return: final_summary (displayed once) + AIMessage (results/errors only)
    return {
        "final_summary": summary,
        "messages": [
            AIMessage(content=final_message)
        ]
    }

print("✓ All node wrappers defined (including summarize)")

# ==============================================================================
# Business Logic Integration Hooks (NEW)
# ==============================================================================

class BusinessLogicIntegration:
    """
    Example integration points for business logic using intent metadata.
    
    This demonstrates how to use the intent_metadata from intent detection
    for billing, analytics, routing, and personalization.
    """
    
    @staticmethod
    def calculate_usage_cost(state: AgentState) -> Dict[str, Any]:
        """Calculate usage cost based on intent type and complexity."""
        intent_metadata = state.get("intent_metadata", {})
        intent_type = intent_metadata.get("intent_type", "new_question")
        complexity = intent_metadata.get("complexity", "moderate")
        
        base_rates = {
            "new_question": 0.10,
            "refinement": 0.05,
            "continuation": 0.07,
            "clarification_response": 0.00
        }
        complexity_multipliers = {"simple": 1.0, "moderate": 1.5, "complex": 2.0}
        
        base_cost = base_rates.get(intent_type, 0.10)
        multiplier = complexity_multipliers.get(complexity, 1.5)
        
        return {
            "total_cost": base_cost * multiplier,
            "intent_type": intent_type,
            "complexity": complexity
        }
    
    @staticmethod
    def log_analytics_event(state: AgentState) -> Dict[str, Any]:
        """Log analytics event for conversation analysis."""
        intent_metadata = state.get("intent_metadata", {})
        current_turn = state.get("current_turn", {})
        turn_history = state.get("turn_history", [])
        
        event = {
            "event_type": "query_processed",
            "intent_type": intent_metadata.get("intent_type"),
            "complexity": intent_metadata.get("complexity"),
            "turn_count": len(turn_history),
            "clarification_requested": state.get("pending_clarification") is not None
        }
        print(f"📊 Analytics: {event['intent_type']} | {event['complexity']}")
        return event

print("✓ Business logic integration hooks defined")

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
    
    # Add nodes - SIMPLIFIED with unified node
    workflow.add_node("unified_intent_context_clarification", unified_intent_context_clarification_node)  # NEW: Unified node
    workflow.add_node("planning", planning_node)
    workflow.add_node("sql_synthesis_table", sql_synthesis_table_node)
    workflow.add_node("sql_synthesis_genie", sql_synthesis_genie_node)
    workflow.add_node("sql_execution", sql_execution_node)
    workflow.add_node("summarize", summarize_node)  # Final summarization node
    
    # Define routing logic based on explicit state
    def route_after_unified(state: AgentState) -> str:
        """Route after unified node: planning or END (clarification/meta-question)"""
        # Check if meta-question - go directly to END with answer
        if state.get("is_meta_question", False):
            return END
        
        # Check if question is clear - proceed to planning
        if state.get("question_clear", False):
            return "planning"
        
        # Otherwise, end for clarification
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
        return "summarize"  # Summarize if synthesis error
    
    # Add edges with conditional routing
    # NEW: Entry point is now unified node
    workflow.set_entry_point("unified_intent_context_clarification")
    
    # Route from unified node to planning or END (clarification)
    workflow.add_conditional_edges(
        "unified_intent_context_clarification",
        route_after_unified,
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
    print("  1. Unified Intent+Context+Clarification Node (SIMPLIFIED - no kumc_poc imports)")
    print("  2. Planning Agent (OOP)")
    print("  3. SQL Synthesis Agent - Table Route (OOP)")
    print("  4. SQL Synthesis Agent - Genie Route (OOP)")
    print("  5. SQL Execution Agent (OOP)")
    print("  6. Result Summarize Agent (OOP) - FINAL NODE")
    print("\n✓ Single LLM call for intent + context + clarity (faster, cheaper)")
    print("✓ Smart clarification rate limiting (1 per 5 turns, sliding window)")
    print("✓ Self-contained implementation (no external imports)")
    print("✓ Conditional routing configured")
    print("✓ All paths route to summarize node before END")
    print("✓ Checkpointer will be added at runtime (distributed serving)")
    print("\n✅ Simplified Hybrid Super Agent workflow created successfully!")
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
    
    def make_json_serializable(self, obj):
        """
        Convert LangChain objects and other non-serializable objects to JSON-serializable format.
        
        Args:
            obj: Object to convert
            
        Returns:
            JSON-serializable version of the object
        """
        from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage, AIMessageChunk
        from uuid import UUID
        
        # Handle None
        if obj is None:
            return None
        
        # Handle UUID objects
        if isinstance(obj, UUID):
            return str(obj)
        
        # Handle bytes
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8', errors='ignore')
            except:
                return f"<bytes:{len(obj)}>"
        
        # Handle set
        if isinstance(obj, set):
            return [self.make_json_serializable(item) for item in obj]
        
        # Handle LangChain message objects
        if isinstance(obj, BaseMessage):
            msg_dict = {
                "type": obj.__class__.__name__,
                "content": str(obj.content) if obj.content else ""
            }
            if hasattr(obj, 'id') and obj.id:
                msg_dict["id"] = str(obj.id)
            if hasattr(obj, 'name') and obj.name:
                msg_dict["name"] = obj.name
            if hasattr(obj, 'tool_calls') and obj.tool_calls:
                # Recursively serialize tool calls
                msg_dict["tool_calls"] = [
                    self.make_json_serializable(tc) for tc in obj.tool_calls[:2]
                ]  # Limit to 2 for brevity
            return msg_dict
        
        # Handle dictionaries recursively
        if isinstance(obj, dict):
            return {str(k): self.make_json_serializable(v) for k, v in obj.items()}
        
        # Handle lists and tuples recursively
        if isinstance(obj, (list, tuple)):
            return [self.make_json_serializable(item) for item in obj]
        
        # Handle primitives
        if isinstance(obj, (str, int, float, bool)):
            return obj
        
        # For anything else, convert to string representation
        try:
            return str(obj)
        except Exception:
            return f"<{type(obj).__name__}>"
    
    def format_custom_event(self, custom_data: dict) -> str:
        """
        Format custom streaming events for user-friendly display.
        
        Args:
            custom_data: Dictionary containing custom event data with 'type' key
            
        Returns:
            Formatted string with emoji and readable event description
        """
        event_type = custom_data.get("type", "unknown")
        
        formatters = {
            # Existing formatters
            "agent_thinking": lambda d: f"💭 {d['agent'].upper()}: {d['content']}",
            "agent_start": lambda d: f"🚀 Starting {d['agent']} agent for: {d.get('query', '')[:50]}...",
            "intent_detection": lambda d: f"🎯 Intent: {d['result']} - {d.get('reasoning', '')}",
            "clarity_analysis": lambda d: f"✓ Query {'clear' if d['clear'] else 'unclear'}: {d.get('reasoning', '')}",
            "vector_search_start": lambda d: f"🔍 Searching vector index: {d['index']}",
            "vector_search_results": lambda d: f"📊 Found {d['count']} relevant spaces: {[s.get('space_id', 'unknown') for s in d.get('spaces', [])]}",
            "plan_formulation": lambda d: f"📋 Execution plan: {d.get('strategy', 'unknown')} strategy",
            "uc_function_call": lambda d: f"🔧 Calling UC function: {d['function']}",
            "sql_generated": lambda d: f"📝 SQL generated: {d.get('query_preview', '')}...",
            "sql_validation_start": lambda d: f"✅ Validating SQL query...",
            "sql_execution_start": lambda d: f"⚡ Executing SQL query...",
            "sql_execution_complete": lambda d: f"✓ Query complete: {d.get('rows', 0)} rows, {len(d.get('columns', []))} columns",
            "summary_start": lambda d: f"📄 Generating summary...",
            "genie_agent_call": lambda d: f"🤖 Calling Genie agent for space: {d.get('space_id', 'unknown')}",
            
            # New clean streaming formatters
            "llm_streaming_start": lambda d: f"🤖 Streaming response from {d.get('agent', 'LLM')}...",
            "llm_token": lambda d: d.get('content', ''),  # Just the token content, no decoration
            "intent_detected": lambda d: f"\n🎯 Intent: {d.get('intent_type', 'unknown')} (confidence: {d.get('confidence', 0):.0%})",
            "meta_question_detected": lambda d: f"\n💡 Meta-question detected",
            "clarification_requested": lambda d: f"\n❓ Clarification needed: {d.get('reason', 'unknown')}",
            "clarification_skipped": lambda d: f"\n⏭️ Clarification skipped: {d.get('reason', 'unknown')}",
            "agent_step": lambda d: f"\n📍 {d.get('agent', 'agent').upper()}: {d.get('content', d.get('step', 'processing'))}",
            "agent_result": lambda d: f"\n✅ {d.get('agent', 'agent').upper()}: {d.get('result', 'completed')} - {d.get('content', '')}",
            "sql_synthesis_start": lambda d: f"\n🔧 Starting SQL synthesis via {d.get('route', 'unknown')} route for {len(d.get('spaces', []))} space(s)",
            "tools_available": lambda d: f"\n🛠️ Tools ready: {', '.join(d.get('tools', []))}",
            "summary_complete": lambda d: f"\n✅ Summary complete",
            
            # Markdown content formatters - return content directly for UI display
            "meta_answer_content": lambda d: f"\n\n{d.get('content', '')}",
            "clarification_content": lambda d: f"\n\n{d.get('content', '')}",
        }
        
        # Bulletproof JSON fallback handler
        def json_fallback(obj):
            """Final fallback for json.dumps() - converts anything to string."""
            try:
                return str(obj)
            except:
                return f"<{type(obj).__name__}>"
        
        # Fallback formatter now uses make_json_serializable with json_fallback
        formatter = formatters.get(
            event_type,
            lambda d: f"ℹ️ {event_type}: {json.dumps(self.make_json_serializable(d), indent=2, default=json_fallback)}"
        )
        
        try:
            return formatter(custom_data)
        except Exception as e:
            logger.warning(f"Error formatting custom event {event_type}: {e}")
            # Enhanced error handling with serialization fallback
            try:
                serialized = self.make_json_serializable(custom_data)
                return f"ℹ️ {event_type}: {json.dumps(serialized, indent=2, default=json_fallback)}"
            except Exception as e2:
                logger.warning(f"Error serializing custom event {event_type}: {e2}")
                return f"ℹ️ {event_type}: {str(custom_data)}"
    
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
        
        SIMPLIFIED API: All conversation turns use the same simple format.
        The agent auto-detects clarification responses and follow-ups from message history.
        
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
            
        Yields:
            ResponsesAgentStreamEvent for each step in the workflow
            
        Usage in Model Serving (ALL scenarios use same format):
            # First query in a conversation
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Show me patient data"}],
                "context": {
                    "conversation_id": "session_001",
                    "user_id": "user@example.com"
                }
            }
            
            # Clarification response (SIMPLIFIED - auto-detected!)
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Patient count by age group"}],
                "context": {
                    "conversation_id": "session_001",  # Same thread_id
                    "user_id": "user@example.com"
                }
            }
            
            # Follow-up query (agent remembers context automatically)
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Now show by gender"}],
                "context": {
                    "conversation_id": "session_001",  # Same thread_id
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
        
        # PHASE 3 OPTIMIZATION: Track workflow timing (TTFT and TTCL)
        workflow_start_time = time.time()
        first_token_time = None
        _performance_metrics["workflow_metrics"]["total_requests"] += 1
        
        # Ensure MLflow tracing doesn't cause issues in streaming context
        # This safeguard prevents NonRecordingSpan context attribute errors
        try:
            import mlflow.tracing
            # Verify tracing is properly initialized, otherwise disable to prevent errors
            if not hasattr(mlflow.tracing, '_is_enabled') or not mlflow.tracing._is_enabled():
                logger.debug("MLflow tracing not enabled, continuing without tracing")
        except Exception as e:
            logger.debug(f"MLflow tracing check skipped: {e}")
        
        # Convert request input to chat completions format
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        
        # Get the latest user message
        latest_query = cc_msgs[-1]["content"] if cc_msgs else ""
        
        # Configure runtime with thread_id and user_id
        run_config = {"configurable": {"thread_id": thread_id}}
        if user_id:
            run_config["configurable"]["user_id"] = user_id
        
        # SIMPLIFIED: Unified state initialization for all scenarios
        # CheckpointSaver will restore previous conversation context automatically
        # The intent_detection_node runs first and creates current_turn
        initial_state = {
            **RESET_STATE_TEMPLATE,  # Reset all per-query execution fields
            "original_query": latest_query,
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
            ]
            # NOTE: current_turn, intent_metadata, turn_history are NOT in RESET_STATE_TEMPLATE
            # They are managed by unified_intent_context_clarification_node and persist via CheckpointSaver
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
            
            # Stream the workflow execution with enhanced visibility modes
            # CheckpointSaver will:
            # 1. Restore previous state from thread_id (if exists) from Lakebase
            # 2. Merge with initial_state (initial_state takes precedence)
            # 3. Preserve conversation history across distributed instances
            # Stream modes:
            # - updates: State changes after each node
            # - messages: LLM token-by-token streaming
            # - custom: Agent-specific events (thinking, decisions, progress)
            for event in app.stream(initial_state, run_config, stream_mode=["updates", "messages", "custom"]):
                event_type = event[0]
                event_data = event[1]
                
                # Handle streaming text deltas (messages mode)
                if event_type == "messages":
                    try:
                        # Extract the message chunk
                        chunk = event_data[0] if isinstance(event_data, (list, tuple)) else event_data
                        
                        # Stream text content as deltas for real-time visibility in Playground
                        if isinstance(chunk, AIMessageChunk) and (content := chunk.content):
                            # PHASE 3: Track TTFT (Time To First Token)
                            if first_token_time is None:
                                first_token_time = time.time()
                                ttft = first_token_time - workflow_start_time
                                _performance_metrics["workflow_metrics"]["ttft_seconds"].append(ttft)
                                logger.info(f"⚡ TTFT: {ttft:.3f}s")
                            
                            yield ResponsesAgentStreamEvent(
                                **self.create_text_delta(delta=content, item_id=chunk.id),
                            )
                    except Exception as e:
                        logger.warning(f"Error processing message chunk: {e}")
                
                # Handle node updates (updates mode)
                elif event_type == "updates":
                    events = event_data
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
                        # Emit node name as a step indicator with enhanced details
                        if events:
                            node_name = tuple(events.keys())[0]
                            node_update = events[node_name]
                            updated_keys = [k for k in node_update.keys() if k != "messages"]
                            
                            # Enhanced step indicator with state keys
                            step_text = f"🔹 Step: {node_name}"
                            if updated_keys:
                                step_text += f" | Keys updated: {', '.join(updated_keys)}"
                            
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.done",
                                item=self.create_text_output_item(
                                    text=step_text, id=str(uuid4())
                                ),
                            )
                            
                            # Emit routing decision if next_agent changed
                            if "next_agent" in node_update:
                                next_agent = node_update["next_agent"]
                                yield ResponsesAgentStreamEvent(
                                    type="response.output_item.done",
                                    item=self.create_text_output_item(
                                        text=f"🔀 Routing decision: Next agent = {next_agent}",
                                        id=str(uuid4())
                                    ),
                                )
                    
                    # Process messages for tool calls, tool results, and final text
                    for msg in new_msgs:
                        # Check if message has tool calls
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            # Emit function call items for tool invocations
                            for tool_call in msg.tool_calls:
                                try:
                                    yield ResponsesAgentStreamEvent(
                                        type="response.output_item.done",
                                        item=self.create_function_call_item(
                                            id=str(uuid4()),
                                            call_id=tool_call.get("id", str(uuid4())),
                                            name=tool_call.get("name", "unknown"),
                                            arguments=json.dumps(tool_call.get("args", {})),
                                        ),
                                    )
                                except Exception as e:
                                    logger.warning(f"Error emitting tool call: {e}")
                        # Handle ToolMessage for tool results
                        elif hasattr(msg, '__class__') and msg.__class__.__name__ == 'ToolMessage':
                            try:
                                tool_name = getattr(msg, 'name', 'unknown')
                                tool_content = str(msg.content)[:200] if msg.content else "No content"
                                yield ResponsesAgentStreamEvent(
                                    type="response.output_item.done",
                                    item=self.create_text_output_item(
                                        text=f"🔨 Tool result ({tool_name}): {tool_content}...",
                                        id=str(uuid4())
                                    ),
                                )
                            except Exception as e:
                                logger.warning(f"Error emitting tool result: {e}")
                        else:
                            # Emit regular message content
                            yield from output_to_responses_items_stream([msg])
                
                # Handle custom mode (agent-specific events)
                elif event_type == "custom":
                    try:
                        custom_data = event_data
                        formatted_text = self.format_custom_event(custom_data)
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=self.create_text_output_item(
                                text=formatted_text,
                                id=str(uuid4())
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"Error processing custom event: {e}")
        
        # PHASE 3: Track TTCL (Time To Completion)
        workflow_end_time = time.time()
        ttcl = workflow_end_time - workflow_start_time
        _performance_metrics["workflow_metrics"]["ttcl_seconds"].append(ttcl)
        
        logger.info(f"Workflow execution completed (thread: {thread_id})")
        logger.info(f"⏱️  Performance: TTFT={first_token_time - workflow_start_time if first_token_time else 'N/A'}s, TTCL={ttcl:.3f}s")


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
print("\n🎉 Enhanced Granular Streaming Features:")
print("  ✓ Agent thinking and reasoning visibility")
print("  ✓ Intent detection (new question vs follow-up)")
print("  ✓ Clarity analysis with reasoning")
print("  ✓ Vector search progress and results")
print("  ✓ Execution plan formulation")
print("  ✓ UC function calls and Genie agent invocations")
print("  ✓ SQL generation progress")
print("  ✓ SQL validation and execution progress")
print("  ✓ Tool calls and tool results")
print("  ✓ Routing decisions between agents")
print("  ✓ Summary generation progress")
print("  ✓ Custom events for detailed execution tracking")
print("="*80)

# Set the agent for MLflow tracking
# Enable autologging with run_tracer_inline for proper async context propagation
try:
    mlflow.langchain.autolog(run_tracer_inline=True)
    logger.info("✓ MLflow LangChain autologging enabled with async context support")
except Exception as e:
    logger.warning(f"⚠️ MLflow autolog initialization failed: {e}")
    logger.warning("Continuing without MLflow tracing...")

mlflow.models.set_model(AGENT)

# COMMAND ----------

# DBTITLE 1,Load Back the AGENT
from agent import AGENT

# COMMAND ----------

# or load the notebook with magic run
%run ./agent.py

# COMMAND ----------

# DBTITLE 1,Test Enhanced Granular Streaming
"""
Test the enhanced granular streaming to verify all execution steps are visible.
This will show agent thinking, tool calls, intermediate results, and routing decisions.

Stream modes enabled:
- updates: State changes after each node
- messages: LLM token-by-token streaming  
- custom: Agent-specific events (thinking, decisions, progress)
"""

from mlflow.types.responses import ResponsesAgentRequest
from uuid import uuid4

test_query = "Show me the top 10 active plan members over 50 years old and with diabetes"

print(f"\n{'='*80}")
print(f"Testing Enhanced Granular Streaming")
print(f"{'='*80}")
print(f"Query: {test_query}\n")

# Create streaming request
thread_id = f"test-streaming-{str(uuid4())[:8]}"
print("thread_id in use:", thread_id)
request = ResponsesAgentRequest(
    input=[{"role": "user", "content": test_query}],
    custom_inputs={"thread_id": f"{thread_id}"}
)

# Stream all events and count them by type
event_counts = {"custom": 0, "updates": 0, "messages": 0, "tool_calls": 0, "tool_results": 0, "routing": 0}

print("Streaming events:")
print("-" * 80)

for event in AGENT.predict_stream(request):
    if event.type == "response.output_item.done":
        item = event.item
        if hasattr(item, 'text') and item.text:
            text = item.text
            
            # Detect if this is a streaming token (no emoji prefix, short text, no newline)
            is_token = (
                not text.startswith(("💭", "🚀", "🎯", "✓", "🔍", "📊", "📋", "🔧", "📝", "✅", "⚡", "📄", "🔹", "🔀", "🔨", "🤖", "💡", "❓", "⏭️", "📍", "🛠️")) 
                and not text.startswith("\n")
                and len(text) < 100
            )
            
            if is_token:
                # Stream token without newline for smooth real-time display
                print(text, end='', flush=True)
            else:
                # Structured event with newline
                # Categorize event types for summary
                if text.startswith("💭") or text.startswith("🚀") or text.startswith("🎯") or text.startswith("✓") or text.startswith("🔍") or text.startswith("📊") or text.startswith("📋") or text.startswith("🔧") or text.startswith("📝") or text.startswith("✅") or text.startswith("⚡") or text.startswith("📄") or text.startswith("🤖") or text.startswith("💡") or text.startswith("❓") or text.startswith("⏭️") or text.startswith("📍") or text.startswith("🛠️"):
                    event_counts["custom"] += 1
                elif text.startswith("🔹 Step:"):
                    event_counts["updates"] += 1
                elif text.startswith("🔀 Routing"):
                    event_counts["routing"] += 1
                elif text.startswith("🔨 Tool result"):
                    event_counts["tool_results"] += 1
                
                # Print event (truncate long events)
                display_text = text if len(text) <= 150 else text[:150] + "..."
                print(f"  {display_text}")
                
        elif hasattr(item, 'function_call'):
            event_counts["tool_calls"] += 1
            print(f"  🛠️ Function call: {item.function_call.name}")

print("-" * 80)
print("\nEvent Summary:")
print(f"  Custom events (agent thinking/progress): {event_counts['custom']}")
print(f"  Node updates (state changes): {event_counts['updates']}")
print(f"  Routing decisions: {event_counts['routing']}")
print(f"  Tool calls: {event_counts['tool_calls']}")
print(f"  Tool results: {event_counts['tool_results']}")
print(f"  Total events: {sum(event_counts.values())}")
print(f"\n{'='*80}")
print("✅ Enhanced streaming test complete!")
print("All agent execution steps are now visible to users in real-time.")
print(f"{'='*80}\n")


# COMMAND ----------

# DBTITLE 1,clarification msg
follow_up_msg =  "Patients currently enrolled in a plan (based on enrollment date ranges); use diabetes code (E10-E14)"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,no clarify but actaully a new question msg
follow_up_msg =  "What are top 10 patients with highest medical charges?"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,continution msg
follow_up_msg =  "Now I want to look at medical and pharmacy cost combined"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,switch to new topic
follow_up_msg =  "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group? use Genie route"
# thread_id = f"test-streaming-{str(uuid4())[:8]}"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

follow_up_msg =  "now I want to include extra filter for members also diagnosed with CHF"
# thread_id = f"test-streaming-{str(uuid4())[:8]}"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,new thread new topic
follow_up_msg =  "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group? use table route"
thread_id = f"test-streaming-{str(uuid4())[:8]}"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,response to clarify
follow_up_msg =  "you decide"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,refinement msg
follow_up_msg =  "remove the active plan requirement, add their plan date_start AND date_end info"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------

# DBTITLE 1,refinement msg
follow_up_msg =  "now I only want to see those NOT from Medicare plan type, give also top 10"
print("thread_id in use:", thread_id)
# follow up of thread from above, update here
# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": f"{thread_id}"}
))

# COMMAND ----------



# COMMAND ----------

# DBTITLE 1,Test Agent with Short-term Memory (multiple chat rounds)
"""
Test short-term memory: Agent remembers context within a conversation thread.
This works across distributed Model Serving instances via CheckpointSaver.
"""

# Example 1: Start a new conversation
thread_id = str(uuid4())
print(f"Starting conversation with thread_id: {thread_id}")

from mlflow.types.responses import ResponsesAgentRequest

# First message
result1 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "Show me patient demographics"}],
    custom_inputs={"thread_id": thread_id}
))
print("\n--- Response 1 ---")
print(result1.model_dump(exclude_none=True))

# Second message - agent should remember context
result2 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "Filter by age > 50"}],
    custom_inputs={"thread_id": thread_id}  # Same thread_id
))
print("\n--- Response 2 (with context) ---")
print(result2.model_dump(exclude_none=True))

# Third message without thread_id - fresh conversation
result3 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "What was I asking about?"}]
))
print("\n--- Response 3 (no context) ---")
print(result3.model_dump(exclude_none=True))

# COMMAND ----------

# Second message to follow-up/refine - agent should remember context
result2 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "Filter patients where current age (as of today) is greater than 50"}],
    custom_inputs={"thread_id": thread_id}  # Same thread_id
))
print("\n--- Response 2 (with context) ---")
print(result2.model_dump(exclude_none=True))

# COMMAND ----------

# third message - agent should know this is a totally new question in the same thread
result2 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group?"}],
    custom_inputs={"thread_id": thread_id}  # Same thread_id
))
print("\n--- Response 2 (with context) ---")
print(result2.model_dump(exclude_none=True))

# COMMAND ----------

# cause agent may need us to clarify the previous question as agent knows the previous question is a totally new question, we need to follow up here.
follow_up_msg = """
1. line allowed
2. aggregate by medical claim
3. age thing your call
"""
# clarify message -
result2 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": f"{follow_up_msg}"}],
    custom_inputs={"thread_id": thread_id}
))
print("\n--- Response 2 (with context) ---")
print(result2.model_dump(exclude_none=True))


# COMMAND ----------

thread_id = str(uuid4)
# new message -
result2 = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group? Use Genie Route"}],
    custom_inputs={"thread_id": thread_id}  # new thread_id
))
print("\n--- Response 2 (with context) ---")
print(result2.model_dump(exclude_none=True))

# COMMAND ----------

# DBTITLE 1,Test Agent with Long-term Memory (User Preferences)
"""
Test long-term memory: Agent can save and recall user preferences across sessions.
Uses DatabricksStore with semantic search to find relevant memories.
"""

# Example 2: Using ChatContext for user_id (preferred for Model Serving)
# from mlflow.types.responses import ResponsesAgentRequest, ChatContext
# 
# user_email = "test.user@databricks.com"
# conversation_id = str(uuid4())
# 
# # Agent can save user preferences
# result1 = AGENT.predict(ResponsesAgentRequest(
#     input=[{"role": "user", "content": "I prefer viewing data as bar charts, and I usually work with patient demographics and clinical trials data"}],
#     context=ChatContext(
#         conversation_id=conversation_id,
#         user_id=user_email
#     )
# ))
# print("\n--- Saved User Preferences ---")
# print(result1.model_dump(exclude_none=True))
# 
# # In a new session, agent can recall preferences
# new_conversation_id = str(uuid4())
# result2 = AGENT.predict(ResponsesAgentRequest(
#     input=[{"role": "user", "content": "Show me the data I usually work with"}],
#     context=ChatContext(
#         conversation_id=new_conversation_id,  # Different conversation
#         user_id=user_email  # Same user
#     )
# ))
# print("\n--- Recalled User Preferences ---")
# print(result2.model_dump(exclude_none=True))

# COMMAND ----------

# DBTITLE 1,📡🔍Helper: Find All Required Resources for Deployment
"""
Run this helper to automatically discover all resources needed for deployment.
This ensures you don't miss any Genie spaces, tables, or UC functions.
"""

# Uncomment to discover resources
from databricks.sdk import WorkspaceClient
from pyspark.sql.functions import from_json, col
from pyspark.sql.types import MapType, StringType


print("="*80)
print("DISCOVERING DEPLOYMENT RESOURCES")
print("="*80)

# 1. Genie Space IDs (from config)
print("\n[1/4] Genie Space IDs:")
for space_id in GENIE_SPACE_IDS:
    print(f"  - {space_id}")

# 2. SQL Warehouse ID (from config - already loaded at line 65)
print("\n[2/4] SQL Warehouse ID:")
print(f"  ✓ Using SQL Warehouse ID from config: {SQL_WAREHOUSE_ID}")
print(f"  Source: config.table_metadata.sql_warehouse_id")
print(f"  Configured via: .env file → SQL_WAREHOUSE_ID environment variable")
if not SQL_WAREHOUSE_ID:
    print("  ⚠️ WARNING: SQL_WAREHOUSE_ID is empty!")
    print("  Set it in .env file: SQL_WAREHOUSE_ID=your-warehouse-id")
    print("  Get warehouse ID from: SQL Warehouses UI → Click warehouse → Copy ID from URL or Details")

# 3. Query underlying tables used by Genie spaces
print("\n[3/4] Querying underlying tables from metadata...")
try:
    query = f"""
    SELECT DISTINCT * 
    FROM {TABLE_NAME}
    WHERE table_name IS NOT NULL and chunk_type = 'table_overview'
    ORDER BY table_name
    """
    
    df = spark.sql(query)
    df_with_json = df.withColumn("metadata_json_parsed", from_json(col("metadata_json"), MapType(StringType(), StringType())))
    UNDERLYING_TABLES = df_with_json.select(col("metadata_json_parsed")["table_identifier"].alias("table_identifier")).toPandas().squeeze().tolist()
    print("UNDERLYING_TABLES:")
except Exception as e:
    print(f"Error: {e}")

for t in UNDERLYING_TABLES:
    print(f"  - {t}")

# 4. Generate resource list code
print("\n[4/4] Generated Resources Code:")
print("="*80)
print("""
# Copy this into your deployment cell:


resources = [
    # LLM endpoints - Diversified by Agent Role
    DatabricksServingEndpoint(LLM_ENDPOINT_CLARIFICATION),
    DatabricksServingEndpoint(LLM_ENDPOINT_PLANNING),
    DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_TABLE),
    DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_GENIE),
    DatabricksServingEndpoint(LLM_ENDPOINT_EXECUTION),
    DatabricksServingEndpoint(LLM_ENDPOINT_SUMMARIZE),
    DatabricksServingEndpoint(EMBEDDING_ENDPOINT),
    
    # Lakebase for state management
    DatabricksLakebase(database_instance_name=LAKEBASE_INSTANCE_NAME),
    
    # Vector Search
    DatabricksVectorSearchIndex(index_name=VECTOR_SEARCH_INDEX),
    
    # SQL Warehouse
    DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
    
    # Genie Spaces (from config)
    *[DatabricksGenieSpace(genie_space_id=space_id) for space_id in GENIE_SPACE_IDS],
    
    # Tables
    DatabricksTable(table_name=TABLE_NAME),  # Metadata table
    *[DatabricksTable(table_name=table) for table in UNDERLYING_TABLES],
    
    # UC Functions
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_summary"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_table_overview"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_column_detail"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_details"),
]
""")
print("="*80)

# COMMAND ----------

# DBTITLE 1,🚀🤖Deploy Agent to Model Serving with Memory Support
"""
Register and deploy the agent with Lakebase resources for automatic authentication.
This enables the agent to access Lakebase in Model Serving without manual credentials.

⚠️ IMPORTANT: Before deploying, run the helper cell above to discover all required resources!

Per Databricks docs: "if you log a Genie Space, you must also log its tables, 
SQL Warehouses, and Unity Catalog functions"
Ref: https://docs.databricks.com/aws/en/generative-ai/agent-framework/agent-authentication
"""

# Step 1: Log model with resources
import mlflow
import logging
from mlflow.models.resources import (
    DatabricksServingEndpoint,
    DatabricksLakebase,
    DatabricksFunction,
    DatabricksVectorSearchIndex,
    DatabricksGenieSpace,
    DatabricksSQLWarehouse,
    DatabricksTable,
)
from pkg_resources import get_distribution

# # Declare all resources the agent needs
# resources = [
#     # LLM endpoints - Diversified by Agent Role
#     DatabricksServingEndpoint(LLM_ENDPOINT_CLARIFICATION),
#     DatabricksServingEndpoint(LLM_ENDPOINT_PLANNING),
#     DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_TABLE),
#     DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_GENIE),
#     DatabricksServingEndpoint(LLM_ENDPOINT_EXECUTION),
#     DatabricksServingEndpoint(LLM_ENDPOINT_SUMMARIZE),
#     DatabricksServingEndpoint(EMBEDDING_ENDPOINT),
#     
#     # Lakebase for state management (CRITICAL!)
#     DatabricksLakebase(database_instance_name=LAKEBASE_INSTANCE_NAME),
#     
#     # Vector Search Index
#     DatabricksVectorSearchIndex(index_name=VECTOR_SEARCH_INDEX),
#     
#     # SQL Warehouse (required for Genie spaces and UC functions)
#     DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
#     
#     # Genie Spaces (IMPORTANT: Must declare all Genie spaces used by the agent!)
#     *[DatabricksGenieSpace(genie_space_id=space_id) for space_id in GENIE_SPACE_IDS],
#     
#     # Tables (metadata enrichment table + underlying Genie tables)
#     # Metadata enrichment table used by UC functions
#     DatabricksTable(table_name=TABLE_NAME),
#     # TODO: Add underlying tables that Genie spaces access
#     # Example: DatabricksTable(table_name=f"{CATALOG}.{SCHEMA}.patient_demographics"),
#     # You can query these from: SELECT DISTINCT table_name FROM enriched_genie_docs_chunks
#     
#     # UC Functions (metadata querying tools)
#     DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_summary"),
#     DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_table_overview"),
#     DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_column_detail"),
#     DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_details"),
# ]

resources = [
    # LLM endpoints - Diversified by Agent Role
    DatabricksServingEndpoint(LLM_ENDPOINT_CLARIFICATION),
    DatabricksServingEndpoint(LLM_ENDPOINT_PLANNING),
    DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_TABLE),
    DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS_GENIE),
    DatabricksServingEndpoint(LLM_ENDPOINT_EXECUTION),
    DatabricksServingEndpoint(LLM_ENDPOINT_SUMMARIZE),
    DatabricksServingEndpoint(EMBEDDING_ENDPOINT),
    
    # Lakebase for state management
    DatabricksLakebase(database_instance_name=LAKEBASE_INSTANCE_NAME),
    
    # Vector Search
    DatabricksVectorSearchIndex(index_name=VECTOR_SEARCH_INDEX),
    
    # SQL Warehouse
    DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
    
    # Genie Spaces (from config)
    *[DatabricksGenieSpace(genie_space_id=space_id) for space_id in GENIE_SPACE_IDS],
    
    # Tables
    DatabricksTable(table_name=TABLE_NAME),  # Metadata table
    *[DatabricksTable(table_name=table) for table in UNDERLYING_TABLES],
    
    # UC Functions
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_summary"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_table_overview"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_column_detail"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_details"),
]


input_example = {
    "input": [{"role": "user", "content": "Show me patient data"}],
    "custom_inputs": {"thread_id": "example-123"},
    "context": {"conversation_id": "sess-001", "user_id": "user@example.com"}
}

with mlflow.start_run():
    # Log LLM model choices for each agent (for monitoring and cost analysis)
    mlflow.log_param("llm_endpoint_clarification", LLM_ENDPOINT_CLARIFICATION)
    mlflow.log_param("llm_endpoint_planning", LLM_ENDPOINT_PLANNING)
    mlflow.log_param("llm_endpoint_sql_synthesis_table", LLM_ENDPOINT_SQL_SYNTHESIS_TABLE)
    mlflow.log_param("llm_endpoint_sql_synthesis_genie", LLM_ENDPOINT_SQL_SYNTHESIS_GENIE)
    mlflow.log_param("llm_endpoint_execution", LLM_ENDPOINT_EXECUTION)
    mlflow.log_param("llm_endpoint_summarize", LLM_ENDPOINT_SUMMARIZE)
    mlflow.log_param("embedding_endpoint", EMBEDDING_ENDPOINT)
    
    # Log agent configuration strategy
    mlflow.set_tag("llm_diversification", "enabled")
    mlflow.set_tag("agent_config_version", "v2.0_diversified")
    
    logged_agent_info = mlflow.pyfunc.log_model(
        name="super_agent_hybrid_with_memory",
        # ⚠️ IMPORTANT: Reference agent.py for clean MLflow deployment
        # agent.py contains runtime-essential components extracted from this notebook
        # This follows MLflow best practices with mlflow.langchain.autolog() and mlflow.models.set_model()
        python_model="./agent.py",  # Path relative to Notebooks/ folder
        input_example=input_example,
        resources=resources,
        # ⚠️ CRITICAL: Pass production config via ModelConfig (Databricks best practice!)
        # This config overrides the development_config in agent.py
        model_config="../prod_config.yaml",  # Production configuration
        pip_requirements=[
            f"databricks-sdk=={get_distribution('databricks-sdk').version}",  # Required for Config() unified auth
            f"databricks-sql-connector=={get_distribution('databricks-sql-connector').version}",  # Required for SQLExecutionAgent
            f"databricks-langchain[memory]=={get_distribution('databricks-langchain').version}",
            f"databricks-agents=={get_distribution('databricks-agents').version}",
            f"databricks-vectorsearch=={get_distribution('databricks-vectorsearch').version}",
            f"langgraph=={get_distribution('langgraph').version}",  # Required for StateGraph
            f"mlflow[databricks]=={mlflow.__version__}"
        ]
    )
    print(f"✓ Model logged: {logged_agent_info.model_uri}")
    print(f"✓ Configuration: prod_config.yaml")

# Step 2: Register to Unity Catalog
mlflow.set_registry_uri("databricks-uc")
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.super_agent_hybrid"

uc_model_info = mlflow.register_model(
    model_uri=logged_agent_info.model_uri,
    name=UC_MODEL_NAME
)
print(f"✓ Model registered: {UC_MODEL_NAME} version {uc_model_info.version}")

# Step 3: Deploy to Model Serving (No environment_vars needed!)
from databricks import agents

# ✅ With ModelConfig, configuration is packaged with the model
# No need for environment_vars parameter!
deployment_info = agents.deploy(
    UC_MODEL_NAME,
    uc_model_info.version,
    scale_to_zero=True,      # Cost optimization
    workload_size="Small",   # Start small, can scale up later
    # ✅ NO environment_vars needed - config is in model package!
)
print(f"✓ Deployed to Model Serving: {deployment_info.endpoint_name}")
print("\n" + "="*80)
print("✅ DEPLOYMENT COMPLETE")
print("="*80)
print(f"Model: {UC_MODEL_NAME} v{uc_model_info.version}")
print(f"Endpoint: {deployment_info.endpoint_name}")
print(f"Configuration: prod_config.yaml (packaged with model)")
print("\nMemory Features Enabled:")
print("  ✓ Short-term: Multi-turn conversations via CheckpointSaver")
print("  ✓ Long-term: User preferences via DatabricksStore")
print("  ✓ Distributed serving: State shared across all instances")
print("\nAdvantages of ModelConfig:")
print("  ✓ Configuration versioned with model")
print("  ✓ No environment_vars parameter needed")
print("  ✓ Easy to test different configs")
print("  ✓ Type-safe and structured")
print("="*80)

# COMMAND ----------

# DBTITLE 1,Query Lakebase State (Monitoring)
"""
Query Lakebase to monitor checkpoint and memory usage.
"""

# # View recent checkpoints
# query_checkpoints = f"""
# SELECT 
#     thread_id,
#     checkpoint_id,
#     (checkpoint::json->>'ts')::timestamptz AS timestamp,
#     parent_checkpoint_id
# FROM checkpoints
# ORDER BY timestamp DESC
# LIMIT 20;
# """
# 
# # View user memories
# query_memories = f"""
# SELECT 
#     namespace,
#     key,
#     value,
#     updated_at
# FROM public.store
# WHERE namespace LIKE '%user_memories%'
# ORDER BY updated_at DESC
# LIMIT 50;
# """
# 
# print("Use these queries in your Lakebase SQL editor to monitor state:")
# print("\n1. Recent Checkpoints:")
# print(query_checkpoints)
# print("\n2. User Memories:")
# print(query_memories)

# COMMAND ----------

# DBTITLE 1,Helper Function: Invoke Hybrid Super Agent
def invoke_super_agent_hybrid(query: str, thread_id: str = "default") -> Dict[str, Any]:
    """
    Invoke the Hybrid Super Agent with a user query.
    
    Args:
        query: User's question
        thread_id: Thread ID for conversation tracking (default: "default")
    
    Returns:
        Final state with execution results
    """
    print("\n" + "="*80)
    print("🚀 INVOKING HYBRID SUPER AGENT")
    print("="*80)
    print(f"Query: {query}")
    print(f"Thread ID: {thread_id}")
    print("="*80)
    
    # Initialize state with reset template to clear per-query fields
    # NOTE: Workflow entry point is "intent_detection", so no need to set next_agent
    initial_state = {
        **RESET_STATE_TEMPLATE,  # Reset all per-query execution fields
        "original_query": query,  # DEPRECATED: Kept for backward compatibility
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
            HumanMessage(content=query)
        ]
    }
    
    # Configure with thread
    config = {"configurable": {"thread_id": thread_id}}
    
    # MLflow autologging is enabled globally at agent initialization
    # No need to call it again here to avoid context issues
    
    # Invoke the workflow
    final_state = super_agent_hybrid.invoke(initial_state, config)
    
    print("\n" + "="*80)
    print("✅ HYBRID SUPER AGENT EXECUTION COMPLETE")
    print("="*80)
    
    return final_state

# COMMAND ----------

# DBTITLE 1,Helper Function: Respond to Clarification (DEPRECATED - Use invoke_super_agent_hybrid)
def respond_to_clarification(
    clarification_response: str, 
    previous_state: Dict[str, Any] = None,  # No longer needed but kept for backward compatibility
    thread_id: str = "default"
) -> Dict[str, Any]:
    """
    SIMPLIFIED: Respond to a clarification request and continue the workflow.
    
    NOTE: This function is now just a wrapper around invoke_super_agent_hybrid().
    The agent auto-detects clarification responses from message history.
    You can call invoke_super_agent_hybrid() directly with the same thread_id.
    
    Args:
        clarification_response: Your clarification/answer to the agent's question
        previous_state: DEPRECATED - No longer needed, kept for backward compatibility
        thread_id: Thread ID for conversation tracking (must match previous call)
    
    Returns:
        Final state with execution results
    
    Example:
        # First call
        state1 = invoke_super_agent_hybrid("Show me the data", thread_id="session_001")
        
        # If clarification needed - SIMPLIFIED API!
        if not state1['question_clear']:
            clarification = state1.get('pending_clarification')
            if clarification:
                print("Clarification needed:", clarification['reason'])
                print("Options:", clarification['options'])
            
            # Just call invoke again with same thread_id
            state2 = respond_to_clarification(
                "Show me patient count by age group",
                thread_id="session_001"  # previous_state no longer needed!
            )
            
            # Or call invoke_super_agent_hybrid() directly:
            # state2 = invoke_super_agent_hybrid("Show me patient count by age group", thread_id="session_001")
    """
    print("\n" + "="*80)
    print("💬 RESPONDING TO CLARIFICATION (SIMPLIFIED)")
    print("="*80)
    print(f"User Response: {clarification_response}")
    print(f"Thread ID: {thread_id}")
    print("="*80)
    
    # SIMPLIFIED: Just call invoke_super_agent_hybrid with the same thread_id
    # The clarification_node will auto-detect this is a clarification response
    # by examining the message history
    return invoke_super_agent_hybrid(clarification_response, thread_id=thread_id)

# COMMAND ----------

# DBTITLE 1,Helper Function: Follow-Up Query
def ask_follow_up_query(
    new_query: str,
    thread_id: str = "default"
) -> Dict[str, Any]:
    """
    SIMPLIFIED: Ask a follow-up query in the same conversation thread.
    
    NOTE: This function is now just a wrapper around invoke_super_agent_hybrid().
    You can call invoke_super_agent_hybrid() directly with the same thread_id.
    
    Args:
        new_query: The new question to ask
        thread_id: Thread ID for conversation tracking (use same thread_id as previous calls)
    
    Returns:
        Final state with execution results
    
    Example:
        # First query
        state1 = invoke_super_agent_hybrid("Show me patient count", thread_id="session_001")
        display_results(state1)
        
        # Follow-up query - SIMPLIFIED API!
        # Option 1: Use this helper (deprecated but still works)
        state2 = ask_follow_up_query(
            "Now show me the average age by gender",
            thread_id="session_001"
        )
        
        # Option 2: Call invoke_super_agent_hybrid directly (recommended)
        state2 = invoke_super_agent_hybrid(
            "Now show me the average age by gender",
            thread_id="session_001"
        )
    """
    print("\n" + "="*80)
    print("💬 FOLLOW-UP QUERY (SIMPLIFIED)")
    print("="*80)
    print(f"New Query: {new_query}")
    print(f"Thread ID: {thread_id}")
    print("✓ This query will have access to previous conversation context")
    print("="*80)
    
    # SIMPLIFIED: Just call invoke_super_agent_hybrid with the same thread_id
    # CheckpointSaver will automatically restore conversation context
    return invoke_super_agent_hybrid(new_query, thread_id=thread_id)

# COMMAND ----------

# DBTITLE 1,Helper Function: Display Results
def display_results(final_state: Dict[str, Any]):
    """
    Display the results from the Hybrid Super Agent execution.
    Shows SQL query, execution results, plans, and any errors.
    """
    print("\n" + "="*80)
    print("📊 FINAL RESULTS")
    print("="*80)
    
    # Display Summary (if available)
    if final_state.get('final_summary'):
        print(f"\n📝 Summary:")
        print(f"  {final_state.get('final_summary')}")
        print()
    
    # Display Original Query
    print(f"\n🔍 Original Query:")
    print(f"  {final_state.get('original_query', 'N/A')}")
    
    # Display Clarification Info (if any)
    if not final_state.get('question_clear', True):
        clarification = final_state.get('pending_clarification')
        if clarification:
            print(f"\n⚠️  Clarification Needed:")
            print(f"  Reason: {clarification.get('reason', 'N/A')}")
            if clarification.get('options'):
                print(f"  Options:")
                for i, opt in enumerate(clarification.get('options', []), 1):
                    print(f"    {i}. {opt}")
    
    # Display Execution Plan
    if final_state.get('execution_plan'):
        print(f"\n📋 Execution Plan:")
        print(f"  {final_state.get('execution_plan')}")
        print(f"  Strategy: {final_state.get('join_strategy', 'N/A')}")
    
    # Display SQL Synthesis Explanation
    if final_state.get('sql_synthesis_explanation'):
        print(f"\n💭 SQL Synthesis Explanation:")
        print(f"  {final_state.get('sql_synthesis_explanation')}")
    
    # Display SQL
    if final_state.get('sql_query'):
        print(f"\n💻 Generated SQL:")
        print("─"*80)
        print(final_state.get('sql_query'))
        print("─"*80)
    
    # Display Execution Results
    exec_result = final_state.get('execution_result')
    if exec_result and exec_result.get('success'):
        print(f"\n✅ Execution Successful:")
        print(f"  Rows: {exec_result.get('row_count', 0)}")
        print(f"  Columns: {', '.join(exec_result.get('columns', []))}")
        
        # Display results preview
        results = exec_result.get("result", [])
        if results:
            print(f"\n📊 Query Results (first 10 rows):")
            for i, row in enumerate(results[:10], 1):
                print(f"  Row {i}: {row}")
    elif exec_result and not exec_result.get('success'):
        print(f"\n❌ Execution Failed:")
        print(f"  Error: {exec_result.get('error', 'Unknown error')}")
    
    # Display Errors
    if final_state.get('synthesis_error'):
        print(f"\n❌ Synthesis Error:")
        print(f"  {final_state.get('synthesis_error')}")
    if final_state.get('execution_error'):
        print(f"\n❌ Execution Error:")
        print(f"  {final_state.get('execution_error')}")
    
    print("\n" + "="*80)

# COMMAND ----------

# DBTITLE 1,Helper Function: Get Results as DataFrame
def get_results_as_dataframe(final_state: Dict[str, Any]):
    """
    Convert execution results to pandas DataFrame for easy analysis.
    
    Args:
        final_state: The final state from invoke_super_agent_hybrid()
        
    Returns:
        pandas.DataFrame or None if no results
        
    Example:
        final_state = invoke_super_agent_hybrid("Show claims")
        df = get_results_as_dataframe(final_state)
        if df is not None:
            print(df.describe())
            df.plot()
    """
    import pandas as pd
    
    exec_result = final_state.get('execution_result')
    if not exec_result or not exec_result.get('success'):
        print("⚠️ No successful execution results to convert")
        return None
    
    results = exec_result.get('result', [])
    if not results:
        print("⚠️ No data in results")
        return None
    
    try:
        df = pd.DataFrame(results)
        print(f"✅ Converted {len(results)} rows to pandas DataFrame")
        print(f"Shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        return df
    except Exception as e:
        print(f"❌ Error converting to DataFrame: {e}")
        return None

print("✓ Helper functions defined")

# COMMAND ----------

# DBTITLE 1,Test Start Here
# Example test query
test_query = "What is the average cost of medical claims per claim in 2024?"
# Invoke Hybrid Super Agent
final_state = invoke_super_agent_hybrid(test_query, thread_id="test_hybrid_001")

# COMMAND ----------

# DBTITLE 1,same query for genie route
# Example test query
test_query = "What is the average cost of medical claims per claim in 2024? Use genie route"
# Invoke Hybrid Super Agent
final_state = invoke_super_agent_hybrid(test_query, thread_id="test_hybrid_001_genie")

# COMMAND ----------

# Example test query
test_query = "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group?"
# Invoke Hybrid Super Agent
final_state = invoke_super_agent_hybrid(test_query, thread_id="test_hybrid_003_table")

##----clarify quetsions-----
#  Options:
#      1. Which specific diabetes diagnosis codes (ICD-10) should be included in the analysis (e.g., E10.x for Type 1, E11.x for Type 2, or all diabetes-related codes)?
#      2. Which cost metric should be used: line charges, allowed amounts, patient copays, or another financial measure from the claims data?
#      3. Should the analysis include only claims where diabetes is the primary diagnosis, or any claim where diabetes appears as a secondary diagnosis?

# COMMAND ----------

#-------
follow_up = """
 1. E10-E14
  2. both line charges and allowed
  3. any claim where a diabetes diagnosis appears

"""
# User provides clarification
final_state = respond_to_clarification(
    follow_up,
    previous_state=final_state,
    thread_id="test_hybrid_003_table"
)

# COMMAND ----------

# Example test query
test_query = "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group? Use genie route"
# Invoke Hybrid Super Agent
final_state = invoke_super_agent_hybrid(test_query, thread_id="test_hybrid_003_genie")

##----clarify quetsions-----
#  Options:
#      1. Which specific diabetes diagnosis codes (ICD-10) should be included in the analysis (e.g., E10.x for Type 1, E11.x for Type 2, or all diabetes-related codes)?
#      2. Which cost metric should be used: line charges, allowed amounts, patient copays, or another financial measure from the claims data?
#      3. Should the analysis include only claims where diabetes is the primary diagnosis, or any claim where diabetes appears as a secondary diagnosis?

# COMMAND ----------

#-------
follow_up = """
  1. both line charges and allowed
  2. you decide
  3. E10-E14

"""
# User provides clarification
final_state = respond_to_clarification(
    follow_up,
    previous_state=final_state,
    thread_id="test_hybrid_003_genie"
)

# COMMAND ----------

final_state

# COMMAND ----------

# DBTITLE 1,Test Hybrid Super Agent (table route)
# Display results
display_results(final_state)

# COMMAND ----------

# DBTITLE 1,Test Hybrid Super Agent (genie route)
# Example test query
test_query = "What is the average cost of medical claims  per claim in 2024? use genie route"

# Invoke Hybrid Super Agent
final_state = invoke_super_agent_hybrid(test_query, thread_id="test_hybrid_002")

# Display results
display_results(final_state)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Additional Test Cases

# COMMAND ----------

# DBTITLE 1,Test Case 1: Simple Single-Space Query
test_query_1 = "How many patients are in the dataset?"
result_1 = invoke_super_agent_hybrid(test_query_1, thread_id="test_hybrid_simple")
display_results(result_1)

# COMMAND ----------

# DBTITLE 1,Test Case 2: Multi-Space Query with JOIN (Table Route)
test_query_2 = "What is the average cost of medical claims for patients diagnosed with diabetes?"
result_2 = invoke_super_agent_hybrid(test_query_2, thread_id="test_hybrid_fast")
display_results(result_2)

# COMMAND ----------

# DBTITLE 1,Test Case 3: Multi-Space Query with JOIN (Genie Route - Explicit)
test_query_3 = "What is the average cost of medical claims for patients diagnosed with diabetes? Use genie route"
result_3 = invoke_super_agent_hybrid(test_query_3, thread_id="test_hybrid_slow")
display_results(result_3)

# COMMAND ----------

# DBTITLE 1,Test Case 4: Complex Multi-Space Query
test_query_4 = "What is the average cost of medical claims for patients diagnosed with diabetes, broken down by insurance payer type and patient age group? Dont clarify. Use Genie Route."
result_4 = invoke_super_agent_hybrid(test_query_4, thread_id="test_hybrid_complex")
display_results(result_4)

# COMMAND ----------

# DBTITLE 1,Test Case 5: Clarification Flow (Vague Query → Clarify → Continue)
# Test with an intentionally vague query
test_query_5 = "How many?"  # Vague - should trigger clarification
result_5a = invoke_super_agent_hybrid(test_query_5, thread_id="test_hybrid_clarification")
display_results(result_5a)

# If clarification was requested, respond to it
if not result_5a.get('question_clear'):
    print("\n" + "="*80)
    print("📝 PROVIDING CLARIFICATION")
    print("="*80)
    
    # User provides clarification
    result_5b = respond_to_clarification(
        "I want to know how many patients are in the dataset",
        previous_state=result_5a,
        thread_id="test_hybrid_clarification"
    )
    
    # Display final results after clarification
    display_results(result_5b)
else:
    print("✓ No clarification needed - query was clear enough")

# COMMAND ----------

# DBTITLE 1,Test Case 6: Another Clarification Example
# Test with another vague query
test_query_6 = "Show me the data"  # Vague - should trigger clarification
result_6a = invoke_super_agent_hybrid(test_query_6, thread_id="test_hybrid_clarification2")
display_results(result_6a)

# If clarification was requested, respond to it
if not result_6a.get('question_clear'):
    print("\n" + "="*80)
    print("📝 PROVIDING CLARIFICATION")
    print("="*80)
    
    # User chooses one of the suggested options
    result_6b = respond_to_clarification(
        "Show me patient count grouped by age group",
        previous_state=result_6a,
        thread_id="test_hybrid_clarification2"
    )
    
    # Display final results after clarification
    display_results(result_6b)
else:
    print("✓ No clarification needed - query was clear enough")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Clarification Flow Summary
# MAGIC
# MAGIC The clarification system now works as follows:
# MAGIC
# MAGIC 1. **Lenient by Default**: Only asks for clarification on truly vague queries
# MAGIC 2. **Max 1 Clarification**: Won't ask endlessly - at most one clarification request
# MAGIC 3. **Easy Response Flow**: Use `respond_to_clarification()` to provide feedback
# MAGIC 4. **Proceeds Automatically**: After clarification, continues to planning and execution
# MAGIC
# MAGIC **Example Flow:**
# MAGIC ```python
# MAGIC # Step 1: Try with vague query
# MAGIC state1 = invoke_super_agent_hybrid("How many?", thread_id="session_001")
# MAGIC
# MAGIC # Step 2: Check if clarification needed
# MAGIC if not state1['question_clear']:
# MAGIC     # Step 3: Provide clarification
# MAGIC     state2 = respond_to_clarification(
# MAGIC         "How many patients are in the dataset?",
# MAGIC         previous_state=state1,
# MAGIC         thread_id="session_001"
# MAGIC     )
# MAGIC     # Step 4: Get results
# MAGIC     display_results(state2)
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC ```
# MAGIC ===================================================================================
# MAGIC HYBRID SUPER AGENT - BEST OF BOTH WORLDS
# MAGIC ===================================================================================
# MAGIC
# MAGIC This notebook implements a hybrid architecture combining:
# MAGIC
# MAGIC 1. OOP AGENT CLASSES (from agent.py)
# MAGIC    ✅ Modular and testable
# MAGIC    ✅ Clean separation of concerns
# MAGIC    ✅ Reusable across projects
# MAGIC    ✅ Easy to extend and maintain
# MAGIC
# MAGIC 2. EXPLICIT STATE MANAGEMENT (from Super_Agent.py)
# MAGIC    ✅ Full observability
# MAGIC    ✅ Easy debugging
# MAGIC    ✅ Clear data flow
# MAGIC    ✅ Type-safe state tracking
# MAGIC
# MAGIC ARCHITECTURE:
# MAGIC ══════════════
# MAGIC
# MAGIC Agent Classes (OOP):
# MAGIC - PlanningAgent
# MAGIC - SQLSynthesisTableAgent
# MAGIC - SQLSynthesisGenieAgent
# MAGIC - SQLExecutionAgent
# MAGIC - ResultSummarizeAgent
# MAGIC
# MAGIC Node Wrappers:
# MAGIC - unified_intent_context_clarification_node(state) → unified intent detection + context + clarity check
# MAGIC - planning_node(state) → calls PlanningAgent, updates state
# MAGIC - sql_synthesis_table_node(state) → calls SQLSynthesisTableAgent, updates state
# MAGIC - sql_synthesis_genie_node(state) → calls SQLSynthesisGenieAgent, updates state
# MAGIC - sql_execution_node(state) → calls SQLExecutionAgent, updates state
# MAGIC - summarize_node(state) → calls ResultSummarizeAgent, preserves ALL state fields
# MAGIC
# MAGIC State Management:
# MAGIC - AgentState(TypedDict) with explicit fields
# MAGIC - Full observability at every step
# MAGIC - Easy to debug and monitor
# MAGIC - ALL fields preserved in final state (sql_query, results, explanations, errors, summary)
# MAGIC
# MAGIC BENEFITS:
# MAGIC ═════════
# MAGIC
# MAGIC ✅ Production Ready - Clean OOP design for maintainability
# MAGIC ✅ Easy Debugging - Explicit state shows exactly what's happening
# MAGIC ✅ Modular - Agent classes can be tested independently
# MAGIC ✅ Observable - All state transitions are visible
# MAGIC ✅ Extensible - Easy to add new agents or modify existing ones
# MAGIC ✅ Team-Friendly - Clear contracts and interfaces
# MAGIC
# MAGIC USAGE:
# MAGIC ══════
# MAGIC
# MAGIC # Simple invocation
# MAGIC final_state = invoke_super_agent_hybrid("Your question here", thread_id="session_123")
# MAGIC display_results(final_state)
# MAGIC
# MAGIC # Access ALL preserved fields programmatically
# MAGIC summary = final_state['final_summary']  # Natural language summary
# MAGIC sql = final_state.get('sql_query')  # Generated SQL
# MAGIC explanation = final_state.get('sql_synthesis_explanation')  # SQL generation explanation
# MAGIC plan = final_state.get('execution_plan')  # Execution plan
# MAGIC
# MAGIC if final_state['execution_result']['success']:
# MAGIC     data = final_state['execution_result']['result']  # Query results
# MAGIC     row_count = final_state['execution_result']['row_count']  # Number of rows
# MAGIC     columns = final_state['execution_result']['columns']  # Column names
# MAGIC else:
# MAGIC     error = final_state['execution_result'].get('error')  # Execution error
# MAGIC     synthesis_error = final_state.get('synthesis_error')  # SQL generation error
# MAGIC
# MAGIC NEXT STEPS:
# MAGIC ═══════════
# MAGIC
# MAGIC 1. Deploy to Databricks as a ResponsesAgent endpoint
# MAGIC 2. Monitor with MLflow tracing in production
# MAGIC 3. Extend with additional specialized agents
# MAGIC 4. Integrate with Genie UI
# MAGIC
# MAGIC ===================================================================================
# MAGIC ```

# COMMAND ----------

# DBTITLE 1,Example: Complete Clarification Flow with Context Preservation
# MAGIC %md
# MAGIC ### Example: Clarification Flow with Context Preservation
# MAGIC
# MAGIC This example demonstrates how the agent:
# MAGIC 1. Detects vague queries and asks for clarification
# MAGIC 2. **PRESERVES** original query, clarification message, and user response separately
# MAGIC 3. **COMBINES** all context for planning agent
# MAGIC 4. Continues workflow seamlessly
# MAGIC
# MAGIC """
# MAGIC # Example 1: Clarification Flow with Context Combination
# MAGIC session_id = "demo_clarification_001"
# MAGIC
# MAGIC # Step 1: Ask a vague query
# MAGIC print("="*80)
# MAGIC print("STEP 1: Initial vague query")
# MAGIC print("="*80)
# MAGIC state1 = invoke_super_agent_hybrid(
# MAGIC     "Show me the data about patients",  # Vague - what data? which patients?
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC
# MAGIC # Check if clarification is needed
# MAGIC if not state1.get('question_clear'):
# MAGIC     print("\n" + "="*80)
# MAGIC     print("CLARIFICATION REQUESTED BY AGENT")
# MAGIC     print("="*80)
# MAGIC     print(f"Original Query (preserved): {state1['original_query']}")
# MAGIC     clarification = state1.get('pending_clarification')
# MAGIC     if clarification:
# MAGIC         print(f"Clarification Needed: {clarification['reason']}")
# MAGIC         print(f"Options: {clarification['options']}")
# MAGIC     
# MAGIC     # Step 2: User provides clarification
# MAGIC     print("\n" + "="*80)
# MAGIC     print("STEP 2: User provides clarification")
# MAGIC     print("="*80)
# MAGIC     state2 = respond_to_clarification(
# MAGIC         "Show me patient count grouped by age group",
# MAGIC         previous_state=state1,
# MAGIC         thread_id=session_id
# MAGIC     )
# MAGIC     
# MAGIC     # Verify context was properly combined
# MAGIC     print("\n" + "="*80)
# MAGIC     print("CONTEXT VERIFICATION")
# MAGIC     print("="*80)
# MAGIC     print(f"✓ Original Query Preserved: {state2.get('original_query')}")
# MAGIC     # NEW: Access clarification through pending_clarification object
# MAGIC     clarification = state2.get('pending_clarification')
# MAGIC     if clarification:
# MAGIC         print(f"✓ Clarification Reason: {clarification.get('reason', 'N/A')[:100]}...")
# MAGIC     # NEW: Context is now in current_turn.context_summary (from intent detection)
# MAGIC     current_turn = state2.get('current_turn')
# MAGIC     if current_turn:
# MAGIC         print(f"✓ Context Summary Created: {current_turn.get('context_summary') is not None}")
# MAGIC     
# MAGIC     display_results(state2)
# MAGIC else:
# MAGIC     display_results(state1)
# MAGIC """

# COMMAND ----------

# DBTITLE 1,Example: Follow-Up Queries with Conversation Continuity
# MAGIC %md
# MAGIC ### Example: Follow-Up Queries with Conversation Continuity
# MAGIC
# MAGIC This example demonstrates conversation continuity across multiple queries:
# MAGIC - Each new query has access to previous conversation context
# MAGIC - Thread-based memory preserves state across invocations
# MAGIC - Users can ask related follow-up questions naturally
# MAGIC
# MAGIC """
# MAGIC # Example 2: Multi-Turn Conversation with Follow-Ups
# MAGIC session_id = "demo_followup_001"
# MAGIC
# MAGIC # Turn 1: First query
# MAGIC print("="*80)
# MAGIC print("TURN 1: Initial Query")
# MAGIC print("="*80)
# MAGIC state1 = invoke_super_agent_hybrid(
# MAGIC     "How many active plan members do we have?",
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC display_results(state1)
# MAGIC
# MAGIC # Turn 2: Follow-up query building on Turn 1
# MAGIC print("\n" + "="*80)
# MAGIC print("TURN 2: Follow-Up Query")
# MAGIC print("="*80)
# MAGIC state2 = ask_follow_up_query(
# MAGIC     "What's the breakdown by age group?",  # Refers to "active plan members" from Turn 1
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC display_results(state2)
# MAGIC
# MAGIC # Turn 3: Another follow-up
# MAGIC print("\n" + "="*80)
# MAGIC print("TURN 3: Second Follow-Up")
# MAGIC print("="*80)
# MAGIC state3 = ask_follow_up_query(
# MAGIC     "Now show me the gender distribution for the 50+ age group",  # Builds on previous context
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC display_results(state3)
# MAGIC
# MAGIC # Turn 4: Completely new question in same thread
# MAGIC print("\n" + "="*80)
# MAGIC print("TURN 4: New Question (but same thread)")
# MAGIC print("="*80)
# MAGIC state4 = ask_follow_up_query(
# MAGIC     "Which medications are most prescribed for diabetes patients?",  # New topic
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC display_results(state4)
# MAGIC
# MAGIC print("\n" + "="*80)
# MAGIC print("✅ CONVERSATION SUMMARY")
# MAGIC print("="*80)
# MAGIC print(f"Session ID: {session_id}")
# MAGIC print(f"Total Turns: 4")
# MAGIC print(f"✓ All queries had access to previous conversation context")
# MAGIC print(f"✓ Thread-based memory preserved state across invocations")
# MAGIC print("="*80)
# MAGIC """

# COMMAND ----------

# DBTITLE 1,Example: Clarification + Follow-Up Combined
# MAGIC %md
# MAGIC ### Example: Clarification + Follow-Up Combined
# MAGIC
# MAGIC This example shows the complete workflow:
# MAGIC 1. Vague query → Clarification requested
# MAGIC 2. User clarifies → Workflow completes
# MAGIC 3. Follow-up query → Uses context from Turn 1+2
# MAGIC
# MAGIC """
# MAGIC # Example 3: Complete Multi-Turn Workflow
# MAGIC session_id = "demo_complete_001"
# MAGIC
# MAGIC # Turn 1: Vague query triggers clarification
# MAGIC print("="*80)
# MAGIC print("TURN 1: Vague Query")
# MAGIC print("="*80)
# MAGIC state1 = invoke_super_agent_hybrid(
# MAGIC     "Show me patient costs",  # Vague - what costs? which patients?
# MAGIC     thread_id=session_id
# MAGIC )
# MAGIC
# MAGIC if not state1.get('question_clear'):
# MAGIC     # Turn 2: Respond to clarification
# MAGIC     print("\n" + "="*80)
# MAGIC     print("TURN 2: Clarification Response")
# MAGIC     print("="*80)
# MAGIC     state2 = respond_to_clarification(
# MAGIC         "Show me average total claim costs for diabetic patients by insurance type",
# MAGIC         previous_state=state1,
# MAGIC         thread_id=session_id
# MAGIC     )
# MAGIC     display_results(state2)
# MAGIC     
# MAGIC     # Turn 3: Follow-up question
# MAGIC     print("\n" + "="*80)
# MAGIC     print("TURN 3: Follow-Up After Clarification")
# MAGIC     print("="*80)
# MAGIC     state3 = ask_follow_up_query(
# MAGIC         "What about only Medicare patients over 65?",  # Refines previous query
# MAGIC         thread_id=session_id
# MAGIC     )
# MAGIC     display_results(state3)
# MAGIC     
# MAGIC     # Turn 4: Another follow-up
# MAGIC     print("\n" + "="*80)
# MAGIC     print("TURN 4: Second Follow-Up")
# MAGIC     print("="*80)
# MAGIC     state4 = ask_follow_up_query(
# MAGIC         "Compare that to Medicaid patients in the same age group",
# MAGIC         thread_id=session_id
# MAGIC     )
# MAGIC     display_results(state4)
# MAGIC     
# MAGIC     print("\n" + "="*80)
# MAGIC     print("✅ WORKFLOW SUMMARY")
# MAGIC     print("="*80)
# MAGIC     print(f"Session ID: {session_id}")
# MAGIC     print(f"Turn 1: Vague query → Clarification requested")
# MAGIC     print(f"Turn 2: User clarified → Context combined and preserved")
# MAGIC     print(f"Turn 3-4: Follow-ups → Used combined context from Turn 1+2")
# MAGIC     print(f"✓ Original query always preserved")
# MAGIC     print(f"✓ Clarification context properly combined")
# MAGIC     print(f"✓ Thread memory maintained conversation continuity")
# MAGIC     print("="*80)
# MAGIC """

# COMMAND ----------

# DBTITLE 1,Example: Multiple Conversations with Different Threads
# MAGIC %md
# MAGIC ### Example: Multiple Parallel Conversations
# MAGIC
# MAGIC Thread IDs enable multiple independent conversations:
# MAGIC - Each thread maintains its own conversation context
# MAGIC - Different users or sessions don't interfere with each other
# MAGIC
# MAGIC """
# MAGIC # Example 4: Multiple Independent Conversations
# MAGIC # Conversation A: Patient demographics
# MAGIC thread_a = "user_alice_session_001"
# MAGIC stateA1 = invoke_super_agent_hybrid("Show patient count by age", thread_id=thread_a)
# MAGIC stateA2 = ask_follow_up_query("Now by gender", thread_id=thread_a)
# MAGIC stateA3 = ask_follow_up_query("Focus on 50+ age group", thread_id=thread_a)
# MAGIC
# MAGIC # Conversation B: Medication analysis (completely independent)
# MAGIC thread_b = "user_bob_session_001"
# MAGIC stateB1 = invoke_super_agent_hybrid("Which drugs are most prescribed?", thread_id=thread_b)
# MAGIC stateB2 = ask_follow_up_query("For diabetes patients only", thread_id=thread_b)
# MAGIC
# MAGIC # Conversation C: Cost analysis (independent)
# MAGIC thread_c = "user_charlie_session_001"
# MAGIC stateC1 = invoke_super_agent_hybrid("Average claim costs", thread_id=thread_c)
# MAGIC
# MAGIC print("\n" + "="*80)
# MAGIC print("✅ MULTIPLE CONVERSATIONS")
# MAGIC print("="*80)
# MAGIC print(f"Thread A ({thread_a}): 3 turns about patient demographics")
# MAGIC print(f"Thread B ({thread_b}): 2 turns about medications")
# MAGIC print(f"Thread C ({thread_c}): 1 turn about costs")
# MAGIC print(f"✓ All threads maintained independent conversation contexts")
# MAGIC print(f"✓ No cross-contamination between threads")
# MAGIC print("="*80)
# MAGIC """

# COMMAND ----------

# DBTITLE 1,Test: Refactored SQLExecutionAgent with SQL Warehouse
# MAGIC %md
# MAGIC ### Test: SQLExecutionAgent with Databricks SQL Warehouse
# MAGIC
# MAGIC This test verifies the refactored SQLExecutionAgent works correctly with databricks-sql-connector.
# MAGIC The agent now uses SQL Warehouse instead of spark.sql, making it compatible with Model Serving.

# COMMAND ----------

# Test the refactored SQLExecutionAgent
print("="*80)
print("🧪 TESTING REFACTORED SQLExecutionAgent")
print("="*80)
print(f"Using SQL Warehouse ID: {SQL_WAREHOUSE_ID}")
print("="*80)

# Create test agent instance
test_agent = SQLExecutionAgent(warehouse_id=SQL_WAREHOUSE_ID)

# Test query - simple query to verify functionality
test_query = """
SELECT 
    'Test' as test_column,
    123 as number_column,
    CURRENT_DATE() as date_column
LIMIT 5
"""

print("\n📝 Test Query:")
print(test_query)
print("\n🔄 Executing test query...")

# Execute test query
result = test_agent.execute_sql(test_query, max_rows=5, return_format="dict")

# Verify results
print("\n" + "="*80)
print("📊 TEST RESULTS")
print("="*80)

if result["success"]:
    print("✅ SUCCESS: Query executed via SQL Warehouse")
    print(f"✓ Rows returned: {result['row_count']}")
    print(f"✓ Columns: {result['columns']}")
    print(f"✓ Result format: {type(result['result'])}")
    print(f"\n📄 Sample result:")
    if result['result']:
        print(f"   {result['result'][0]}")
    print("\n✅ SQLExecutionAgent refactoring SUCCESSFUL!")
    print("✅ Agent is now compatible with Model Serving")
else:
    print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
    print("⚠️  Please check SQL Warehouse ID and permissions")

print("="*80)

# COMMAND ----------

# DBTITLE 1,Test: SQLExecutionAgent with Real Healthcare Query
# MAGIC %md
# MAGIC ### Test: Real Healthcare Query via SQL Warehouse
# MAGIC
# MAGIC Test with an actual healthcare data query to verify full functionality.

# COMMAND ----------

# Test with a real healthcare query
print("="*80)
print("🧪 TESTING WITH REAL HEALTHCARE QUERY")
print("="*80)

real_query = """
SELECT 
    COUNT(DISTINCT patient_id) as patient_count,
    COUNT(DISTINCT claim_id) as claim_count
FROM healthverity_claims_sample_patient_dataset.hv_claims_sample.diagnosis
LIMIT 10
"""

print("\n📝 Healthcare Query:")
print(real_query)
print("\n🔄 Executing via SQL Warehouse...")

result = test_agent.execute_sql(real_query, max_rows=10, return_format="dict")

print("\n" + "="*80)
print("📊 HEALTHCARE QUERY RESULTS")
print("="*80)

if result["success"]:
    print("✅ SUCCESS: Healthcare query executed")
    print(f"✓ Rows returned: {result['row_count']}")
    print(f"\n📄 Results:")
    for row in result['result']:
        print(f"   {row}")
    print("\n✅ FULL INTEGRATION TEST PASSED!")
else:
    print(f"❌ FAILED: {result.get('error', 'Unknown error')}")

print("="*80)

# COMMAND ----------

# DBTITLE 1,Production Deployment Guide for Model Serving
# MAGIC %md
# MAGIC ### 🚀 Production Deployment Guide: SQLExecutionAgent to Model Serving
# MAGIC
# MAGIC This guide shows how to deploy the SQLExecutionAgent to Databricks Model Serving with proper authentication configuration.
# MAGIC
# MAGIC #### Prerequisites
# MAGIC 1. SQL Warehouse ID configured in your `.env` file (for development) or Model Serving endpoint (for production)
# MAGIC 2. Databricks secrets scope created
# MAGIC 3. Access token stored in Databricks secrets
# MAGIC 4. SQL Warehouse ID obtained from: SQL Warehouses UI → Click warehouse → Copy ID from URL or Details
# MAGIC
# MAGIC #### Step 1: Store SQL Warehouse Access Token in Databricks Secrets
# MAGIC
# MAGIC ```bash
# MAGIC # Create a secret scope (if not exists)
# MAGIC databricks secrets create-scope sql_warehouse_scope
# MAGIC
# MAGIC # Store your access token
# MAGIC databricks secrets put-secret sql_warehouse_scope warehouse_token
# MAGIC # (you will be prompted to enter the token)
# MAGIC ```
# MAGIC
# MAGIC #### Step 2: Register Agent with Resources (Recommended - Automatic Authentication)
# MAGIC
# MAGIC **Best Practice: Use automatic authentication passthrough by registering resources**
# MAGIC
# MAGIC When you register resources during agent deployment, Databricks automatically handles authentication:
# MAGIC
# MAGIC ```python
# MAGIC from mlflow.models.resources import DatabricksSQLWarehouse
# MAGIC
# MAGIC resources = [
# MAGIC     DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
# MAGIC     # ... other resources (Vector Search, Genie Spaces, etc.)
# MAGIC ]
# MAGIC
# MAGIC mlflow.langchain.log_model(
# MAGIC     lc_model=agent,
# MAGIC     artifact_path="agent",
# MAGIC     resources=resources,  # Enables automatic authentication
# MAGIC     # ... other parameters
# MAGIC )
# MAGIC ```
# MAGIC
# MAGIC **What happens automatically:**
# MAGIC - Databricks creates a service principal for your agent
# MAGIC - OAuth credentials are injected into the Model Serving environment
# MAGIC - Credentials are automatically rotated (no manual management needed)
# MAGIC - Agent code uses `Config()` to read credentials transparently
# MAGIC
# MAGIC **No manual environment variable configuration needed!**
# MAGIC
# MAGIC #### Step 2 (Alternative): Manual Authentication Configuration (Legacy)
# MAGIC
# MAGIC If you're NOT using resource registration, manually configure environment variables:
# MAGIC
# MAGIC **Via Serving UI:**
# MAGIC 1. Navigate to: Serving → Your Endpoint → Configuration → Advanced configurations
# MAGIC 2. Click "Add environment variable"
# MAGIC 3. Add the following variables:
# MAGIC
# MAGIC | Variable Name | Value | Type | Required |
# MAGIC |---------------|-------|------|----------|
# MAGIC | `DATABRICKS_HOST` | `your-workspace.cloud.databricks.com` | Plain text | Yes* |
# MAGIC | `DATABRICKS_TOKEN` | `{{secrets/sql_warehouse_scope/warehouse_token}}` | Secret | Yes* |
# MAGIC | `SQL_WAREHOUSE_ID` | `your-production-warehouse-id` | Plain text | Optional** |
# MAGIC
# MAGIC \* Not required if using automatic authentication with registered resources
# MAGIC \** Only needed if production warehouse differs from development warehouse
# MAGIC
# MAGIC **Via REST API (manual auth):**
# MAGIC ```python
# MAGIC {
# MAGIC   "name": "super-agent-endpoint",
# MAGIC   "config": {
# MAGIC     "served_entities": [{
# MAGIC       "entity_name": "catalog.schema.super_agent_model",
# MAGIC       "entity_version": "1",
# MAGIC       "workload_size": "Small",
# MAGIC       "scale_to_zero_enabled": true,
# MAGIC       "environment_vars": {
# MAGIC         "DATABRICKS_HOST": "your-workspace.cloud.databricks.com",
# MAGIC         "DATABRICKS_TOKEN": "{{secrets/sql_warehouse_scope/warehouse_token}}",
# MAGIC         "SQL_WAREHOUSE_ID": "your-production-warehouse-id"  # Optional
# MAGIC       }
# MAGIC     }]
# MAGIC   }
# MAGIC }
# MAGIC ```
# MAGIC
# MAGIC #### Step 3: Package Model with MLflow
# MAGIC
# MAGIC When packaging your model for deployment:
# MAGIC
# MAGIC ```python
# MAGIC import mlflow
# MAGIC
# MAGIC class SuperAgentModel(mlflow.pyfunc.PythonModel):
# MAGIC     def load_context(self, context):
# MAGIC         # Initialize SQL Execution Agent with warehouse ID
# MAGIC         import os
# MAGIC         warehouse_id = os.getenv("SQL_WAREHOUSE_ID") or "your-default-warehouse-id"
# MAGIC         self.sql_agent = SQLExecutionAgent(warehouse_id=warehouse_id)
# MAGIC         # Authentication handled automatically via Config() - reads injected credentials
# MAGIC     
# MAGIC     def predict(self, context, model_input):
# MAGIC         # Use the agent - Config() transparently handles OAuth
# MAGIC         result = self.sql_agent.execute_sql(query)
# MAGIC         return result
# MAGIC
# MAGIC # Log model with resources for automatic authentication
# MAGIC from mlflow.models.resources import DatabricksSQLWarehouse
# MAGIC resources = [DatabricksSQLWarehouse(warehouse_id=warehouse_id)]
# MAGIC mlflow.pyfunc.log_model("model", python_model=SuperAgentModel(), resources=resources)
# MAGIC ```
# MAGIC
# MAGIC #### Step 4: Verify Deployment
# MAGIC
# MAGIC After deployment, test your endpoint:
# MAGIC
# MAGIC ```python
# MAGIC import requests
# MAGIC
# MAGIC response = requests.post(
# MAGIC     "https://your-workspace.cloud.databricks.com/serving-endpoints/super-agent-endpoint/invocations",
# MAGIC     headers={"Authorization": f"Bearer {token}"},
# MAGIC     json={"inputs": {"query": "SELECT * FROM table LIMIT 10"}}
# MAGIC )
# MAGIC print(response.json())
# MAGIC ```
# MAGIC
# MAGIC #### Security Best Practices
# MAGIC
# MAGIC ✅ **DO:**
# MAGIC - **Use automatic authentication passthrough with resource registration (recommended)**
# MAGIC - Implement least-privilege access controls on SQL Warehouse
# MAGIC - Use service principals (automatic with resource registration)
# MAGIC - Let Databricks handle credential rotation automatically
# MAGIC - Store sensitive credentials in Databricks secrets (if using manual auth)
# MAGIC
# MAGIC ❌ **DON'T:**
# MAGIC - Hard-code tokens in your model code
# MAGIC - Use plain text environment variables for sensitive data
# MAGIC - Share tokens across multiple applications
# MAGIC - Use personal access tokens in production
# MAGIC - Manually manage token rotation (use automatic passthrough instead)
# MAGIC
# MAGIC #### Troubleshooting
# MAGIC
# MAGIC **With Automatic Authentication (Resource Registration):**
# MAGIC
# MAGIC **Error: "Authentication failed" or "Access denied"**
# MAGIC - Verify SQL Warehouse was registered as a resource during model logging
# MAGIC - Check that the deploying user has access to the SQL Warehouse
# MAGIC - Ensure the agent's service principal has been granted necessary permissions
# MAGIC - Verify resources list includes: `DatabricksSQLWarehouse(warehouse_id=...)`
# MAGIC
# MAGIC **With Manual Authentication (Legacy):**
# MAGIC
# MAGIC **Error: Config() cannot find credentials**
# MAGIC - Set DATABRICKS_HOST and DATABRICKS_TOKEN environment variables
# MAGIC - Verify secret exists: `databricks secrets list-secrets sql_warehouse_scope`
# MAGIC - Verify environment variable uses correct syntax: `{{secrets/scope/key}}`
# MAGIC - Ensure endpoint creator has READ access to the secret
# MAGIC
# MAGIC **Error: "Authentication failed"**
# MAGIC - Verify token has not expired
# MAGIC - Check SQL Warehouse permissions for the token owner
# MAGIC - Verify workspace URL is correct (without https://)
# MAGIC
# MAGIC #### References
# MAGIC - [Agent Authentication (Automatic Passthrough)](https://docs.databricks.com/generative-ai/agent-framework/agent-authentication)
# MAGIC - [Configure access to resources from model serving endpoints](https://docs.databricks.com/machine-learning/model-serving/store-env-variable-model-serving.html)
# MAGIC - [Databricks unified authentication](https://docs.databricks.com/dev-tools/auth/unified-auth.html)
# MAGIC - [Model Serving endpoints API](https://docs.databricks.com/api/workspace/servingendpoints)

# COMMAND ----------


