# Quick Start Guide

Get the Multi-Agent Genie System up and running in 15 minutes.

## Prerequisites

✅ Databricks workspace  
✅ Unity Catalog access  
✅ Genie spaces configured  
✅ Access to LLM endpoint  

## Step 1: Environment Setup (2 minutes)

1. **Copy environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your values:**
   ```bash
   DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   DATABRICKS_TOKEN=dapi_your_token_here
   CATALOG_NAME=your_catalog
   SCHEMA_NAME=your_schema
   ```

3. **Verify configuration:**
   ```python
   python config.py
   ```

## Step 2: Export Genie Spaces (3 minutes)

Run the Genie export notebook:

```python
# Open and execute: Notebooks/00_Export_Genie_Spaces.py

# This notebook will:
# 1. Read Genie space IDs from environment or widgets
# 2. Export each space to Unity Catalog volume
# 3. Create both space.json and serialized.json files
# 4. Verify exports and show summary
```

**Configuration:**
The notebook uses Genie space IDs from `.env`:
```bash
GENIE_SPACE_IDS=space_id_1,space_id_2,space_id_3
```

Default spaces (if not configured):
- `01f072dbd668159d99934dfd3b17f544` - GENIE_PATIENT
- `01f08f4d1f5f172ea825ec8c9a3c6064` - MEDICATIONS
- `01f073c5476313fe8f51966e3ce85bd7` - GENIE_DIAGNOSIS_STAGING
- `01f07795f6981dc4a99d62c9fc7c2caa` - GENIE_TREATMENT
- `01f08a9fd9ca125a986d01c1a7a5b2fe` - GENIE_LABORATORY_BIOMARKERS

**Expected output:**
```
✓ Successfully exported: 5 spaces
Export location: /Volumes/{catalog}/{schema}/volume/genie_exports/
```

Files created:
- `{space_id}__{space_name}.space.json` files
- `{space_id}__{space_name}.serialized.json` files

## Step 3: Run Table Metadata Enrichment (5 minutes)

```python
# Open and run: Notebooks/02_Table_MetaInfo_Enrichment.py

# This notebook will:
# 1. Sample column values from all tables
# 2. Build value dictionaries
# 3. Enhance descriptions with LLM
# 4. Save enriched docs to Unity Catalog
```

**Expected output:**
```
✓ Saved enriched docs to: {catalog}.{schema}.enriched_genie_docs
✓ Created flattened view: {catalog}.{schema}.enriched_genie_docs_flattened
```

## Step 4: Build Vector Search Index (3 minutes)

```python
# Open and run: Notebooks/04_VS_Enriched_Genie_Spaces.py

# This notebook will:
# 1. Create vector search endpoint
# 2. Build delta sync index
# 3. Register UC search function
# 4. Test semantic search
```

**Expected output:**
```
✓ VS endpoint 'vs_endpoint_genie_multi_agent_vs' is online
✓ Vector search index creation initiated
✓ Index is ONLINE and ready to use!
✓ Created UC function: {catalog}.{schema}.search_genie_spaces
```

## Step 5: Test Multi-Agent System (2 minutes)

```python
# Open and run: Notebooks/05_Multi_Agent_System.py

# Run test cells to verify:
# 1. Agent availability
# 2. Single-space queries
# 3. Multi-space queries
# 4. Clarification flow
```

**Sample test:**
```python
from agent import AGENT

input_example = {
    "input": [
        {"role": "user", "content": "How many patients are older than 65?"}
    ]
}

response = AGENT.predict(input_example)
print(response)
```

**Expected output:**
```
✓ Query analyzed by ThinkingPlanningAgent
✓ Routed to GENIE_PATIENT agent
✓ Result: [Table with count]
```

## Step 6: Deploy to Model Serving (Optional)

If you want to deploy the agent as an endpoint:

```python
# Continue in: Notebooks/05_Multi_Agent_System.py

# Run deployment cells:
# 1. Register model to MLflow
# 2. Register to Model Registry
# 3. Deploy to Model Serving endpoint
```

**Expected output:**
```
✓ Model logged successfully!
✓ Model registered as: multi_agent_genie_system
✓ Created endpoint: multi-agent-genie-endpoint
```

## Verification Checklist

- [ ] Environment variables configured
- [ ] Virtual environment activated with all packages
- [ ] Genie spaces exported to volume (00_Export_Genie_Spaces.py)
- [ ] Enriched metadata saved to Unity Catalog (02_Table_MetaInfo_Enrichment.py)
- [ ] Vector search index online (04_VS_Enriched_Genie_Spaces.py)
- [ ] UC search function created
- [ ] Agent responds to test queries (05_Multi_Agent_System.py)
- [ ] Model deployed to endpoint (optional)

## Quick Test Queries

Try these queries to verify everything works:

### Simple Query (Single Space)
```python
"How many patients are older than 50?"
```
**Expected:** Direct answer from GENIE_PATIENT

### Complex Query (Multi-Space with Join)
```python
"How many patients older than 50 are on Voltaren?"
```
**Expected:** Combined result from GENIE_PATIENT + MEDICATIONS

### Multi-Part Query (No Join)
```python
"What are the most common diagnoses and medications?"
```
**Expected:** Separate answers verbally merged

### Unclear Query (Clarification)
```python
"Tell me about cancer patients"
```
**Expected:** Clarification options provided

## Common Issues & Solutions

### Issue: Vector search index not found
**Solution:**
```python
# Verify index exists:
from databricks.vector_search.client import VectorSearchClient
client = VectorSearchClient()
index = client.get_index("{catalog}.{schema}.enriched_genie_docs_flattened_vs_index")
print(index.describe())

# If missing, rerun: 04_VS_Enriched_Genie_Spaces.py
```

### Issue: Genie space access denied
**Solution:**
```sql
-- Grant permissions:
GRANT USE CATALOG ON CATALOG {catalog} TO `your_user`;
GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO `your_user`;
GRANT SELECT ON TABLE {catalog}.{schema}.* TO `your_user`;
```

### Issue: LLM endpoint timeout
**Solution:**
```python
# Check endpoint status:
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
endpoint = w.serving_endpoints.get("databricks-claude-sonnet-4-5")
print(endpoint.state)

# If not ready, wait or use alternative endpoint
```

### Issue: Agent returns errors
**Solution:**
```python
# Check MLflow traces:
import mlflow
mlflow.set_experiment("/Users/{user}/multi_agent_genie")
# View latest run in MLflow UI for detailed trace
```

## Performance Tips

1. **First Query Slow?** 
   - Vector search index warming up
   - LLM endpoint cold start
   - Wait 30 seconds and retry

2. **Want Faster Responses?**
   - Use fast route for multi-space joins
   - Enable caching (coming soon)
   - Scale endpoint to Medium/Large

3. **High Query Volume?**
   - Enable continuous pipeline for vector search
   - Increase endpoint workload size
   - Consider dedicated compute

## Next Steps

Once everything is working:

1. **Customize** - Add your own Genie spaces to `agent.py`
2. **Tune** - Adjust prompts for better accuracy
3. **Monitor** - Set up alerts and dashboards
4. **Scale** - Upgrade endpoint for production load

## Support

- **Documentation**: See `README.md`
- **Implementation Details**: See `IMPLEMENTATION_STATUS.md`
- **Code Reference**: See `Notebooks/agent.py`

## Success! 🎉

You now have a fully functional multi-agent system that can answer complex questions across multiple Genie spaces!

Try asking it:
```
"How many patients diagnosed with lung cancer in 2023 are currently on chemotherapy?"
```

Watch it:
1. Analyze the query
2. Find relevant Genie spaces
3. Synthesize SQL across spaces
4. Execute and return results

All automatically! 🚀

