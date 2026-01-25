# Deployment Quick Start - Super Agent with Memory

## 🚀 Deploy in 5 Steps

This quick start assumes you've already:
- ✅ Created Lakebase instance
- ✅ Run one-time setup (checkpoint/store tables)
- ✅ Tested agent locally

---

## Step 1: Update Production Config (2 minutes)

Edit `prod_config.yaml`:

```yaml
# ⚠️ TODO: Update these values
lakebase_instance_name: multi-agent-genie-system-state-db  # Your actual instance
sql_warehouse_id: 148ccb90800933a1  # Your actual warehouse ID

# ⚠️ TODO: Update if different from dev
genie_space_ids:
  - 01f0eab621401f9faa11e680f5a2bcd0
  - 01f0eababd9f1bcab5dea65cf67e48e3
  - 01f0eac186d11b9897bc1d43836cc4e1
```

---

## Step 2: Find Underlying Tables (2 minutes)

Run this SQL in Databricks:

```sql
SELECT DISTINCT table_name 
FROM yyang.multi_agent_genie.enriched_genie_docs_chunks
WHERE table_name IS NOT NULL
ORDER BY table_name;
```

**Example output:**
```
yyang.multi_agent_genie.patient_demographics
yyang.multi_agent_genie.clinical_trials
```

---

## Step 3: Update Deployment Code (1 minute)

In `Notebooks/Super_Agent_hybrid.py` (Line ~2620), update:

```python
# Update these two lines:
SQL_WAREHOUSE_ID = "148ccb90800933a1"  # From Step 1

UNDERLYING_TABLES = [
    f"{CATALOG}.{SCHEMA}.patient_demographics",
    f"{CATALOG}.{SCHEMA}.clinical_trials",
    # ... tables from Step 2
]
```

---

## Step 4: Uncomment Deployment Cell (30 seconds)

In `Notebooks/Super_Agent_hybrid.py` (Line ~2577), uncomment the deployment cell.

---

## Step 5: Run and Wait (20 minutes)

Run the deployment cell. Grab coffee while it deploys! ☕

---

## Complete Deployment Code

Here's what you're running (already in your notebook):

```python
# DBTITLE 1,Deploy Agent to Model Serving

from mlflow.models.resources import (
    DatabricksServingEndpoint, DatabricksLakebase, DatabricksFunction,
    DatabricksVectorSearchIndex, DatabricksGenieSpace, DatabricksSQLWarehouse,
    DatabricksTable
)
from databricks import agents
from pkg_resources import get_distribution

# Configuration from notebook
GENIE_SPACE_IDS = config.table_metadata.genie_space_ids
SQL_WAREHOUSE_ID = "148ccb90800933a1"  # ⚠️ Update!
UNDERLYING_TABLES = [
    # ⚠️ Add your tables here!
]

# Declare all resources
resources = [
    # LLM endpoints
    DatabricksServingEndpoint(LLM_ENDPOINT_CLARIFICATION),
    DatabricksServingEndpoint(LLM_ENDPOINT_PLANNING),
    DatabricksServingEndpoint(LLM_ENDPOINT_SQL_SYNTHESIS),
    DatabricksServingEndpoint(LLM_ENDPOINT_SUMMARIZE),
    DatabricksServingEndpoint(EMBEDDING_ENDPOINT),
    
    # Lakebase (CRITICAL for memory!)
    DatabricksLakebase(database_instance_name=LAKEBASE_INSTANCE_NAME),
    
    # Vector Search
    DatabricksVectorSearchIndex(index_name=VECTOR_SEARCH_INDEX),
    
    # SQL Warehouse
    DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID),
    
    # Genie Spaces
    *[DatabricksGenieSpace(genie_space_id=sid) for sid in GENIE_SPACE_IDS],
    
    # Tables
    DatabricksTable(table_name=TABLE_NAME),
    *[DatabricksTable(table_name=table) for table in UNDERLYING_TABLES],
    
    # UC Functions
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_summary"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_table_overview"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_column_detail"),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.get_space_details"),
]

# Log model with ModelConfig
input_example = {
    "input": [{"role": "user", "content": "Show me patient data"}],
    "custom_inputs": {"thread_id": "example-123"},
}

with mlflow.start_run():
    logged_agent_info = mlflow.pyfunc.log_model(
        name="super_agent_hybrid_with_memory",
        python_model="../agent.py",
        model_config="../prod_config.yaml",  # ✅ ModelConfig!
        input_example=input_example,
        resources=resources,
        pip_requirements=[
            f"databricks-langchain[memory]=={get_distribution('databricks-langchain').version}",
            f"databricks-agents=={get_distribution('databricks-agents').version}",
            f"databricks-vectorsearch=={get_distribution('databricks-vectorsearch').version}",
            f"mlflow[databricks]=={mlflow.__version__}",
        ]
    )

# Register to Unity Catalog
mlflow.set_registry_uri("databricks-uc")
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.super_agent_hybrid"
uc_model_info = mlflow.register_model(logged_agent_info.model_uri, UC_MODEL_NAME)

# Deploy to Model Serving
deployment_info = agents.deploy(
    UC_MODEL_NAME,
    uc_model_info.version,
    scale_to_zero=True,
    workload_size="Small"
)

print("\n" + "="*80)
print("✅ DEPLOYMENT COMPLETE")
print("="*80)
print(f"Model: {UC_MODEL_NAME} v{uc_model_info.version}")
print(f"Endpoint: {deployment_info.endpoint_name}")
print(f"Configuration: prod_config.yaml (versioned with model)")
print("="*80)
```

---

## After Deployment

### Test Multi-turn Conversation

```python
import requests
import json
import time

endpoint_url = f"{workspace_url}/serving-endpoints/super_agent_hybrid/invocations"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Request 1: Initial query
print("Request 1: Show me patient demographics")
response1 = requests.post(
    endpoint_url,
    headers=headers,
    json={
        "messages": [{"role": "user", "content": "Show me patient demographics"}],
        "custom_inputs": {"thread_id": "test_session_001"}
    }
)
print(response1.json())

time.sleep(2)

# Request 2: Follow-up (should remember context!)
print("\nRequest 2: Filter by age > 50")
response2 = requests.post(
    endpoint_url,
    headers=headers,
    json={
        "messages": [{"role": "user", "content": "Filter by age > 50"}],
        "custom_inputs": {"thread_id": "test_session_001"}  # Same thread_id
    }
)
print(response2.json())

if "patient" in str(response2.json()).lower():
    print("\n✅ SUCCESS: Agent remembered context!")
else:
    print("\n⚠️ Context may not have been preserved")
```

---

## Checklist

### Before Deployment
- [ ] ✅ Lakebase instance created
- [ ] ✅ One-time setup completed (tables created)
- [ ] ✅ Agent tested locally
- [ ] ✅ `prod_config.yaml` updated
- [ ] ✅ SQL Warehouse ID found
- [ ] ✅ Underlying tables queried
- [ ] ✅ Deployment code updated (SQL_WAREHOUSE_ID, UNDERLYING_TABLES)

### During Deployment
- [ ] ⏳ Uncomment deployment cell
- [ ] ⏳ Run deployment cell
- [ ] ⏳ Wait 15-20 minutes

### After Deployment
- [ ] ⏳ Test multi-turn conversations
- [ ] ⏳ Verify state persistence
- [ ] ⏳ Monitor endpoint metrics

---

## Resource Count

Your deployment should include:

- ✅ **5** LLM Endpoints
- ✅ **1** Lakebase Instance
- ✅ **1** Vector Search Index
- ✅ **1** SQL Warehouse
- ✅ **3** Genie Spaces (from your .env)
- ✅ **N** Tables (1 metadata + underlying tables)
- ✅ **4** UC Functions

**Total: ~15+ resources** (depending on table count)

---

## Quick Commands

### Find SQL Warehouse ID
```sql
-- Go to SQL Warehouses in Databricks UI
-- Click your warehouse → Copy ID from URL or Details tab
```

### Query Underlying Tables
```sql
SELECT DISTINCT table_name 
FROM yyang.multi_agent_genie.enriched_genie_docs_chunks
WHERE table_name IS NOT NULL;
```

### Check Deployment Status
```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
endpoint = w.serving_endpoints.get(name="super_agent_hybrid")
print(f"Status: {endpoint.state.ready}")
```

---

## Need Help?

- **Full Guide**: `DEPLOYMENT_GUIDE.md`
- **ModelConfig Details**: `MODELCONFIG_REFACTORING.md`
- **Memory Guide**: `Notebooks/MEMORY_IMPLEMENTATION_GUIDE.md`
- **Troubleshooting**: `DEPLOYMENT_GUIDE.md` → Troubleshooting section

---

## Summary

### What Makes This Deployment Special

1. ✅ **Memory Support** - Multi-turn conversations and user preferences
2. ✅ **Distributed Serving** - State shared across all instances
3. ✅ **ModelConfig** - Databricks best practice for configuration
4. ✅ **Complete Resources** - All Genie spaces, tables, and dependencies
5. ✅ **Production Ready** - Proper authentication and monitoring

### Simple Deployment Command

```python
# Just 3 commands!
mlflow.pyfunc.log_model(..., model_config="prod_config.yaml")
mlflow.register_model(...)
agents.deploy(UC_MODEL_NAME, version)
```

**That's it!** Configuration is versioned with the model. No environment_vars needed. 🎉

---

**Ready to deploy?** Follow the 5 steps above and you'll be live in ~20 minutes! 🚀
