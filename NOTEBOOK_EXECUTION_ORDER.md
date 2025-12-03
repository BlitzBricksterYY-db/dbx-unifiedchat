# Notebook Execution Order

Execute notebooks in this specific order for successful setup.

## 📋 Execution Sequence

### Step 0: Export Genie Spaces ✅
**Notebook:** `00_Export_Genie_Spaces.py`  
**Duration:** ~3 minutes  
**Purpose:** Export Genie space metadata to Unity Catalog volume

**Prerequisites:**
- Databricks workspace access
- Genie spaces configured
- `.env` file with credentials

**What it does:**
1. Reads Genie space IDs from environment
2. Connects to Databricks Genie API
3. Exports space.json and serialized.json files
4. Saves to `/Volumes/{catalog}/{schema}/volume/genie_exports/`

**Outputs:**
- `{space_id}__{space_name}.space.json`
- `{space_id}__{space_name}.serialized.json`

**Verify:**
```python
# Check exports exist
ls /Volumes/yyang/multi_agent_genie/volume/genie_exports/
# Should see .space.json and .serialized.json files
```

---

### Step 1: Enrich Table Metadata ✅
**Notebook:** `02_Table_MetaInfo_Enrichment.py`  
**Duration:** ~5 minutes  
**Purpose:** Enrich Genie exports with detailed table metadata

**Prerequisites:**
- Step 0 completed (Genie exports exist)
- LLM endpoint access
- Unity Catalog write permissions

**What it does:**
1. Loads exported Genie space.json files
2. Samples column values from all tables
3. Builds value dictionaries
4. Enhances descriptions using LLM
5. Saves enriched docs to Unity Catalog

**Outputs:**
- `{catalog}.{schema}.enriched_genie_docs` (Delta table)
- `{catalog}.{schema}.enriched_genie_docs_flattened` (View)

**Verify:**
```sql
SELECT count(*) FROM yyang.multi_agent_genie.enriched_genie_docs;
-- Should return number of exported spaces
```

---

### Step 2: Build Vector Search Index ✅
**Notebook:** `04_VS_Enriched_Genie_Spaces.py`  
**Duration:** ~3 minutes  
**Purpose:** Create vector search index for semantic space discovery

**Prerequisites:**
- Step 1 completed (enriched docs exist)
- Vector Search endpoint capability
- Embedding model access

**What it does:**
1. Creates/validates vector search endpoint
2. Enables Change Data Feed on source table
3. Builds delta sync vector search index
4. Registers UC function for agent access
5. Tests semantic search

**Outputs:**
- Vector search endpoint: `vs_endpoint_{name}`
- Vector search index: `{catalog}.{schema}.enriched_genie_docs_flattened_vs_index`
- UC function: `{catalog}.{schema}.search_genie_spaces`

**Verify:**
```sql
SELECT * FROM yyang.multi_agent_genie.search_genie_spaces(
    'patient age demographics',
    3
);
-- Should return relevant spaces with scores
```

---

### Step 3: Test and Deploy Multi-Agent System ✅
**Notebook:** `05_Multi_Agent_System.py`  
**Duration:** ~10 minutes  
**Purpose:** Test, log, and deploy the multi-agent system

**Prerequisites:**
- Step 2 completed (vector search index online)
- `agent.py` file exists
- Model Serving endpoint capability

**What it does:**
1. Imports and tests agent system
2. Runs comprehensive test suite
3. Logs model to MLflow
4. Registers to Model Registry
5. Deploys to Model Serving endpoint
6. Runs performance benchmarks

**Outputs:**
- MLflow model: `multi_agent_genie_system`
- Model Serving endpoint: `multi-agent-genie-endpoint`
- Performance metrics
- Test results

**Verify:**
```python
from agent import AGENT

result = AGENT.predict({
    "input": [{"role": "user", "content": "How many patients over 50?"}]
})
print(result)
# Should return structured response
```

---

## 🎯 Quick Reference

### Execution Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Step 0: Export Genie spaces
# Open and run: Notebooks/00_Export_Genie_Spaces.py

# Step 1: Enrich metadata
# Open and run: Notebooks/02_Table_MetaInfo_Enrichment.py

# Step 2: Build vector search
# Open and run: Notebooks/04_VS_Enriched_Genie_Spaces.py

# Step 3: Test and deploy
# Open and run: Notebooks/05_Multi_Agent_System.py
```

---

## ⚠️ Important Notes

### Do NOT skip steps
Each notebook depends on outputs from previous notebooks.

### Run in order
```
00 → 02 → 04 → 05
```

### Check outputs between steps
Verify each step completed successfully before proceeding.

### Common Issues

**Issue 1:** "Space files not found"  
**Solution:** Run `00_Export_Genie_Spaces.py` first

**Issue 2:** "Enriched docs table not found"  
**Solution:** Run `02_Table_MetaInfo_Enrichment.py`

**Issue 3:** "Vector search index not online"  
**Solution:** Wait 5-10 minutes for index to build, or check `04_VS_Enriched_Genie_Spaces.py` output

**Issue 4:** "Agent import error"  
**Solution:** Ensure `agent.py` is in same directory, activate venv

---

## 📊 Execution Time Estimates

| Step | Notebook | Typical Duration |
|------|----------|------------------|
| 0 | Export Genie Spaces | 2-3 minutes |
| 1 | Enrich Metadata | 5-7 minutes |
| 2 | Vector Search Index | 3-5 minutes |
| 3 | Test & Deploy | 10-15 minutes |
| **Total** | | **20-30 minutes** |

*Times vary based on:*
- Number of Genie spaces
- Number of tables per space
- Cluster size
- LLM endpoint latency

---

## ✅ Success Criteria

After completing all steps, you should have:

- [x] Genie spaces exported to volume
- [x] Enriched metadata in Unity Catalog
- [x] Vector search index online
- [x] UC search function working
- [x] Agent system tested
- [x] Model registered in MLflow
- [x] Serving endpoint deployed

Test the complete system:
```python
from agent import AGENT

AGENT.predict({
    "input": [{"role": "user", "content": "How many patients over 50 are on Voltaren?"}]
})
```

Expected: Multi-agent system analyzes query, routes through appropriate agents, returns answer with SQL and reasoning.

---

**Last Updated:** December 1, 2025  
**Status:** Complete execution guide

