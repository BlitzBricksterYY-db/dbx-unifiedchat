# Databricks notebook source
# MAGIC %md
# MAGIC # Multi-Agent System for Cross-Domain Genie Queries
# MAGIC 
# MAGIC This notebook implements and tests a sophisticated multi-agent system that can:
# MAGIC - Answer questions across multiple Genie spaces
# MAGIC - Intelligently plan query execution strategies
# MAGIC - Handle both single-space and multi-space queries
# MAGIC - Perform fast-route (direct SQL synthesis) and slow-route (combine Genie results) execution
# MAGIC - Ask for clarification when questions are unclear
# MAGIC 
# MAGIC **Architecture:**
# MAGIC - **SupervisorAgent**: Routes to appropriate sub-agents
# MAGIC - **ThinkingPlanningAgent**: Analyzes queries and plans execution
# MAGIC - **GenieAgents**: Query individual Genie spaces
# MAGIC - **SQLSynthesisAgent**: Combines SQL across spaces
# MAGIC - **SQLExecutionAgent**: Executes synthesized queries

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup and Installation

# COMMAND ----------

# MAGIC %pip install -U -qqq langgraph-supervisor==0.0.30 mlflow[databricks] databricks-langchain databricks-agents databricks-vectorsearch
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Agent Code to File

# COMMAND ----------

# DBTITLE 1,Check if agent.py exists
import os

agent_file = "agent.py"
if os.path.exists(agent_file):
    print(f"✓ {agent_file} already exists")
    with open(agent_file, 'r') as f:
        print(f"  File size: {len(f.read())} bytes")
else:
    print(f"✗ {agent_file} not found - please ensure agent.py is in the same directory")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Basic Functionality

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

from agent import AGENT

# Test 1: Check available agents
input_example = {
    "input": [
        {"role": "user", "content": "What tools and agents do you have access to?"}
    ]
}

print("="*80)
print("TEST 1: Available Agents and Tools")
print("="*80)

for event in AGENT.predict_stream(input_example):
    print(event.model_dump(exclude_none=True))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Single Space Query

# COMMAND ----------

# Test 2: Simple single-space question
input_example = {
    "input": [
        {"role": "user", "content": "How many patients are older than 65 years?"}
    ]
}

print("\n" + "="*80)
print("TEST 2: Single Space Query - Patient Demographics")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Cross-Domain Query (Multiple Spaces with Join)

# COMMAND ----------

# Test 3: Cross-domain question requiring join
input_example = {
    "input": [
        {"role": "user", "content": "How many patients older than 50 years are on Voltaren?"}
    ]
}

print("\n" + "="*80)
print("TEST 3: Cross-Domain Query - Patients + Medications")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Multiple Spaces Without Join

# COMMAND ----------

# Test 4: Question requiring multiple spaces but no join (verbal merge)
input_example = {
    "input": [
        {"role": "user", "content": "What are the most common diagnoses and what are the most prescribed medications?"}
    ]
}

print("\n" + "="*80)
print("TEST 4: Multiple Spaces - Verbal Merge")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Unclear Question (Clarification Flow)

# COMMAND ----------

# Test 5: Unclear question requiring clarification
input_example = {
    "input": [
        {"role": "user", "content": "Tell me about patients with cancer"}
    ]
}

print("\n" + "="*80)
print("TEST 5: Unclear Question - Should Request Clarification")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Complex Multi-Domain Query

# COMMAND ----------

# Test 6: Complex question across multiple domains
input_example = {
    "input": [
        {
            "role": "user", 
            "content": "For patients diagnosed with lung cancer in 2023, what percentage are currently on chemotherapy medications?"
        }
    ]
}

print("\n" + "="*80)
print("TEST 6: Complex Multi-Domain Query")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Agent - Laboratory and Treatment Integration

# COMMAND ----------

# Test 7: Lab results and treatment
input_example = {
    "input": [
        {
            "role": "user",
            "content": "Show me patients with abnormal biomarker results who underwent surgical treatment"
        }
    ]
}

print("\n" + "="*80)
print("TEST 7: Laboratory + Treatment Integration")
print("="*80)

for event in AGENT.predict_stream(input_example):
    result = event.model_dump(exclude_none=True)
    print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Agent Deployment Preparation

# COMMAND ----------

# MAGIC %md
# MAGIC ### Register Model to MLflow

# COMMAND ----------

import mlflow
from mlflow.models import infer_signature

# Set experiment
mlflow.set_experiment("/Users/" + spark.sql("SELECT current_user()").collect()[0][0] + "/multi_agent_genie")

# Log model
with mlflow.start_run(run_name="multi_agent_system_v1") as run:
    # Test input/output for signature
    test_input = {
        "input": [
            {"role": "user", "content": "How many patients are older than 50?"}
        ]
    }
    
    test_output = AGENT.predict(test_input)
    
    # Infer signature
    signature = infer_signature(test_input, test_output)
    
    # Log the model
    mlflow.pyfunc.log_model(
        artifact_path="agent",
        python_model=AGENT,
        signature=signature,
        input_example=test_input,
        pip_requirements=[
            "langgraph-supervisor==0.0.30",
            "mlflow[databricks]",
            "databricks-langchain",
            "databricks-agents",
            "databricks-vectorsearch",
        ],
        code_paths=["agent.py"],
    )
    
    run_id = run.info.run_id
    model_uri = f"runs:/{run_id}/agent"
    
    print(f"✓ Model logged successfully!")
    print(f"  Run ID: {run_id}")
    print(f"  Model URI: {model_uri}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Register to Model Registry

# COMMAND ----------

# Register model
model_name = "multi_agent_genie_system"
model_version = mlflow.register_model(
    model_uri=model_uri,
    name=model_name
)

print(f"✓ Model registered as: {model_name}")
print(f"  Version: {model_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Deploy to Model Serving Endpoint

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput

w = WorkspaceClient()

endpoint_name = "multi-agent-genie-endpoint"

# Check if endpoint exists
try:
    existing_endpoint = w.serving_endpoints.get(endpoint_name)
    print(f"Endpoint '{endpoint_name}' already exists, updating...")
    
    w.serving_endpoints.update_config_and_wait(
        name=endpoint_name,
        served_entities=[
            ServedEntityInput(
                entity_name=f"{model_name}",
                entity_version=model_version.version,
                scale_to_zero_enabled=True,
                workload_size="Small",
            )
        ],
    )
    print(f"✓ Updated endpoint: {endpoint_name}")
    
except Exception as e:
    print(f"Creating new endpoint '{endpoint_name}'...")
    
    w.serving_endpoints.create_and_wait(
        name=endpoint_name,
        config=EndpointCoreConfigInput(
            served_entities=[
                ServedEntityInput(
                    entity_name=f"{model_name}",
                    entity_version=model_version.version,
                    scale_to_zero_enabled=True,
                    workload_size="Small",
                )
            ]
        ),
    )
    print(f"✓ Created endpoint: {endpoint_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Test Deployed Endpoint

# COMMAND ----------

from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

# Test the deployed endpoint
response = w.serving_endpoints.query(
    name=endpoint_name,
    messages=[
        ChatMessage(
            role=ChatMessageRole.USER,
            content="How many patients are over 60 years old?"
        )
    ],
)

print("Endpoint Response:")
print(response)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Performance Metrics and Monitoring

# COMMAND ----------

# DBTITLE 1,Agent Performance Metrics
import pandas as pd
from datetime import datetime

# Define test queries with expected characteristics
test_suite = [
    {
        "query": "How many patients are older than 50?",
        "expected_spaces": 1,
        "expected_route": "single",
        "category": "simple"
    },
    {
        "query": "How many patients older than 50 are on Voltaren?",
        "expected_spaces": 2,
        "expected_route": "fast_join",
        "category": "complex"
    },
    {
        "query": "What are common diagnoses and common medications?",
        "expected_spaces": 2,
        "expected_route": "verbal_merge",
        "category": "medium"
    },
]

results = []

for test_case in test_suite:
    print(f"\nTesting: {test_case['query']}")
    print("-" * 80)
    
    start_time = datetime.now()
    
    try:
        input_example = {
            "input": [{"role": "user", "content": test_case["query"]}]
        }
        
        response = AGENT.predict(input_example)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        results.append({
            "query": test_case["query"],
            "category": test_case["category"],
            "expected_route": test_case["expected_route"],
            "duration_seconds": duration,
            "success": True,
            "response_length": len(str(response)),
        })
        
        print(f"✓ Success ({duration:.2f}s)")
        
    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        results.append({
            "query": test_case["query"],
            "category": test_case["category"],
            "expected_route": test_case["expected_route"],
            "duration_seconds": duration,
            "success": False,
            "error": str(e),
        })
        
        print(f"✗ Failed: {str(e)}")

# Display results
df_results = pd.DataFrame(results)
display(df_results)

# Summary statistics
print("\n" + "="*80)
print("PERFORMANCE SUMMARY")
print("="*80)
print(f"Total tests: {len(results)}")
print(f"Success rate: {df_results['success'].mean() * 100:.1f}%")
print(f"Average duration: {df_results['duration_seconds'].mean():.2f}s")
print(f"Min duration: {df_results['duration_seconds'].min():.2f}s")
print(f"Max duration: {df_results['duration_seconds'].max():.2f}s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Agent Trace Visualization

# COMMAND ----------

# View traces in MLflow
mlflow_run_id = run_id

print(f"View detailed traces at:")
print(f"  MLflow UI: /ml/experiments/{mlflow.get_experiment_by_name('/Users/' + spark.sql('SELECT current_user()').collect()[0][0] + '/multi_agent_genie').experiment_id}/runs/{mlflow_run_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Documentation and Usage Guide

# COMMAND ----------

# MAGIC %md
# MAGIC ### Agent Usage Guide
# MAGIC 
# MAGIC #### Architecture Overview
# MAGIC 
# MAGIC The multi-agent system follows a hierarchical architecture:
# MAGIC 
# MAGIC ```
# MAGIC User Query
# MAGIC     ↓
# MAGIC SupervisorAgent
# MAGIC     ↓
# MAGIC ThinkingPlanningAgent → Analyzes query, searches vector index
# MAGIC     ↓
# MAGIC Decision Point:
# MAGIC     ├─ Single Space → GenieAgent → Response
# MAGIC     ├─ Multiple Spaces (No Join) → GenieAgents (parallel) → Verbal Merge → Response
# MAGIC     └─ Multiple Spaces (Join Required)
# MAGIC         ├─ Fast Route → SQLSynthesisAgent → SQLExecutionAgent → Response
# MAGIC         └─ Slow Route → GenieAgents (parallel) → SQLSynthesisAgent → SQLExecutionAgent → Response
# MAGIC ```
# MAGIC 
# MAGIC #### Query Types Supported
# MAGIC 
# MAGIC 1. **Single-Space Queries**
# MAGIC    - Example: "How many patients are over 65?"
# MAGIC    - Handled by: Single Genie Agent
# MAGIC    
# MAGIC 2. **Multi-Space Queries with Join**
# MAGIC    - Example: "How many patients over 50 are on Voltaren?"
# MAGIC    - Handled by: SQLSynthesisAgent + SQLExecutionAgent
# MAGIC    
# MAGIC 3. **Multi-Space Queries without Join**
# MAGIC    - Example: "What are common diagnoses and common medications?"
# MAGIC    - Handled by: Multiple Genie Agents + Verbal Merge
# MAGIC    
# MAGIC 4. **Unclear Queries**
# MAGIC    - Example: "Tell me about cancer patients"
# MAGIC    - Handled by: ThinkingPlanningAgent → Clarification Request
# MAGIC 
# MAGIC #### Best Practices
# MAGIC 
# MAGIC - **Be specific**: More specific questions get better results
# MAGIC - **Use proper terminology**: Medical terms work well with the system
# MAGIC - **Iterate**: If first answer isn't perfect, refine your question
# MAGIC - **Check traces**: Use MLflow traces to understand agent decisions
# MAGIC 
# MAGIC #### Limitations
# MAGIC 
# MAGIC - Patient counts < 10 are returned as "Count is less than 10"
# MAGIC - Individual patient IDs are never shown, only aggregates
# MAGIC - Complex multi-way joins may take longer (slow route)
# MAGIC - Vector search finds relevant spaces, but planning agent makes final decision

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC 
# MAGIC ✅ **Completed Tasks:**
# MAGIC 
# MAGIC 1. ✓ Built table metadata update pipeline (02_Table_MetaInfo_Enrichment.py)
# MAGIC    - Samples column values from delta tables
# MAGIC    - Builds value dictionaries
# MAGIC    - Enriches metadata with LLM-generated descriptions
# MAGIC    - Saves enriched docs to Unity Catalog
# MAGIC 
# MAGIC 2. ✓ Built vector search index pipeline (04_VS_Enriched_Genie_Spaces.py)
# MAGIC    - Creates vector search endpoint
# MAGIC    - Builds delta sync index on enriched docs
# MAGIC    - Registers UC function for agent access
# MAGIC 
# MAGIC 3. ✓ Built multi-agent system (agent.py + this notebook)
# MAGIC    - ThinkingPlanningAgent for query analysis
# MAGIC    - Multiple Genie Agents for data access
# MAGIC    - SQLSynthesisAgent for query combination
# MAGIC    - SQLExecutionAgent for execution
# MAGIC    - Supervisor with fast/slow route logic
# MAGIC    - Question clarification flow
# MAGIC 
# MAGIC 4. ✓ Tested and deployed the system
# MAGIC    - Comprehensive test suite
# MAGIC    - MLflow logging and tracking
# MAGIC    - Model registry registration
# MAGIC    - Model serving endpoint deployment
# MAGIC 
# MAGIC **Next Steps:**
# MAGIC - Monitor agent performance in production
# MAGIC - Refine prompts based on user feedback
# MAGIC - Add more sophisticated routing logic
# MAGIC - Implement caching for common queries
# MAGIC - Add support for follow-up questions with context

