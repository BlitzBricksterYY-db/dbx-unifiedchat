# ModelConfig Refactoring - Databricks Best Practice

## Overview

Refactored from `environment_vars` approach to **ModelConfig** following [Databricks best practices for parametrizing agent code across environments](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent?language=LangGraph#parametrize-code-for-deployment-across-environments).

---

## Why ModelConfig is Better

### Before (environment_vars approach)

```python
# ❌ OLD: Pass env vars during deployment
environment_vars = {
    "CATALOG_NAME": os.getenv("CATALOG_NAME", "yyang"),
    "SCHEMA_NAME": os.getenv("SCHEMA_NAME", "multi_agent_genie"),
    # ... 15 more variables
}

agents.deploy(
    UC_MODEL_NAME,
    version,
    environment_vars=environment_vars  # Must pass every time
)
```

**Problems:**
- ❌ Not versioned with model
- ❌ Must pass env vars every deployment
- ❌ No type safety
- ❌ Not the Databricks-recommended approach

### After (ModelConfig approach)

```python
# ✅ NEW: Config packaged with model
mlflow.pyfunc.log_model(
    python_model="../agent.py",
    model_config="../prod_config.yaml",  # Versioned with model!
    ...
)

agents.deploy(
    UC_MODEL_NAME,
    version,
    # ✅ NO environment_vars parameter!
)
```

**Benefits:**
- ✅ **Configuration versioned with model** - immutable, auditable
- ✅ **Databricks best practice** - explicitly designed for this use case
- ✅ **Cleaner deployment** - no env vars to pass
- ✅ **Type-safe YAML** - structured and validated
- ✅ **Easy testing** - swap configs without changing code

---

## What Changed

### 1. Created Config Files

**`dev_config.yaml`** - For local development
```yaml
catalog_name: yyang
schema_name: multi_agent_genie
llm_endpoint: databricks-claude-sonnet-4-5
lakebase_instance_name: multi-agent-genie-system-state-db
genie_space_ids:
  - 01f0eab621401f9faa11e680f5a2bcd0
  - 01f0eababd9f1bcab5dea65cf67e48e3
  - 01f0eac186d11b9897bc1d43836cc4e1
sql_warehouse_id: 148ccb90800933a1
# ... all other config
```

**`prod_config.yaml`** - For production deployment
```yaml
catalog_name: yyang
schema_name: multi_agent_genie
llm_endpoint: databricks-claude-sonnet-4-5
lakebase_instance_name: multi-agent-genie-system-state-db
# ... can be different from dev if needed
```

### 2. Updated `agent.py`

**Before:**
```python
# OLD: Used config.py with .env file
from config import get_config
config = get_config()
CATALOG = config.unity_catalog.catalog_name
```

**After:**
```python
# NEW: Uses ModelConfig with YAML
from mlflow.models import ModelConfig

development_config = {
    "catalog_name": "yyang",
    "schema_name": "multi_agent_genie",
    # ... all config
}

model_config = ModelConfig(development_config=development_config)
CATALOG = model_config.get("catalog_name")
```

### 3. Updated Deployment Code

**Before:**
```python
# OLD: Pass environment_vars
mlflow.pyfunc.log_model(
    python_model="../agent.py",
    resources=resources,
)

agents.deploy(..., environment_vars=environment_vars)
```

**After:**
```python
# NEW: Pass model_config
mlflow.pyfunc.log_model(
    python_model="../agent.py",
    resources=resources,
    model_config="../prod_config.yaml",  # ✅ Config versioned with model!
)

agents.deploy(...)  # ✅ No environment_vars needed!
```

---

## How ModelConfig Works

### Development (Local Testing)

```python
# agent.py
model_config = ModelConfig(development_config={...})  # Uses inline dict
# Or
model_config = ModelConfig(development_config="dev_config.yaml")  # Uses YAML

# Test locally
from agent import AGENT
response = AGENT.predict(request)
```

**Flow:**
1. `agent.py` loads `development_config` (inline dict or YAML)
2. `ModelConfig` uses the development config
3. ✅ Works locally!

### Deployment (Model Serving)

```python
# Deployment code
mlflow.pyfunc.log_model(
    python_model="agent.py",
    model_config="prod_config.yaml",  # ⚠️ This overrides development_config!
)
```

**Flow:**
1. MLflow packages `agent.py` + `prod_config.yaml`
2. When loaded in Model Serving, `ModelConfig` uses `prod_config.yaml`
3. `development_config` is **ignored** (overridden by prod config)
4. ✅ Works in Model Serving with production config!

---

## File Structure (Updated)

```
KUMC_POC_hlsfieldtemp/
├── agent.py                    # ⭐ Runtime agent (uses ModelConfig)
├── dev_config.yaml             # ⭐ NEW! Dev configuration
├── prod_config.yaml            # ⭐ NEW! Prod configuration
├── config.py                   # (Still used by notebook for setup)
├── .env                        # (Still used by notebook for setup)
└── Notebooks/
    └── Super_Agent_hybrid.py   # Deployment code
```

**What's packaged for deployment:**
- ✅ `agent.py`
- ✅ `prod_config.yaml` (versioned with model!)
- ✅ `requirements.txt`

**What's NOT packaged:**
- ❌ `.env` (not needed!)
- ❌ `config.py` (not needed!)
- ❌ `dev_config.yaml` (dev only)

---

## Configuration Management Strategy

### Development
```python
# For local testing, edit dev_config.yaml or use inline dict
model_config = ModelConfig(development_config="dev_config.yaml")
```

### Production
```yaml
# Edit prod_config.yaml
catalog_name: yyang
lakebase_instance_name: prod-lakebase-instance
```

### Testing Different Configs
```python
# Test with staging config
mlflow.pyfunc.log_model(..., model_config="staging_config.yaml")

# Test with dev config
mlflow.pyfunc.log_model(..., model_config="dev_config.yaml")

# Each model version has its own config!
```

---

## Comparison: environment_vars vs ModelConfig

| Feature | environment_vars | ModelConfig |
|---------|-----------------|-------------|
| **Databricks docs** | General purpose | ✅ Explicitly recommended |
| **Versioned with model** | ❌ No | ✅ Yes |
| **Deployment param** | `agents.deploy()` | `log_model()` |
| **Type safety** | ❌ Strings only | ✅ Structured YAML/dict |
| **Easy to test** | ❌ Must change env vars | ✅ Swap YAML files |
| **Code required** | Must build env dict | ❌ None (just pass file path) |
| **Documentation** | General | [Explicit guide](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent?language=LangGraph#parametrize-code-for-deployment-across-environments) |

**Winner:** ✅ ModelConfig

---

## Updated Deployment Workflow

### Step 1: Edit Production Config

Update `prod_config.yaml` with your production values:
```yaml
lakebase_instance_name: your-prod-instance  # Update!
genie_space_ids:  # Update with prod space IDs
  - space1
  - space2
```

### Step 2: Log Model with Config

```python
# In notebook deployment cell
with mlflow.start_run():
    logged_agent_info = mlflow.pyfunc.log_model(
        python_model="../agent.py",
        model_config="../prod_config.yaml",  # ⚠️ Config versioned here!
        resources=resources,
        ...
    )
```

### Step 3: Deploy (Simple!)

```python
# Clean, no environment_vars needed!
agents.deploy(UC_MODEL_NAME, version)
```

### Step 4: Done!

Configuration is packaged with the model and versioned. ✅

---

## Local Testing

### Test with Dev Config

```python
# agent.py automatically uses dev_config.yaml for local testing
from agent import AGENT
from mlflow.types.responses import ResponsesAgentRequest

request = ResponsesAgentRequest(
    input=[{"role": "user", "content": "Show me data"}]
)

response = AGENT.predict(request)
print(response)
```

### Test with Different Config

```python
# Create test config
test_config = {
    "catalog_name": "test_catalog",
    "schema_name": "test_schema",
    # ... test values
}

# Log with test config
mlflow.pyfunc.log_model(
    python_model="agent.py",
    model_config=test_config,  # Can pass dict or YAML path
    ...
)
```

---

## Migration Summary

### Files Created
- ✅ `dev_config.yaml` - Development configuration
- ✅ `prod_config.yaml` - Production configuration
- ✅ `MODELCONFIG_REFACTORING.md` - This guide

### Files Updated
- ✅ `agent.py` - Now uses `ModelConfig` instead of `config.py`
- ✅ `Notebooks/Super_Agent_hybrid.py` - Deployment code uses `model_config` parameter
- ✅ `DEPLOYMENT_GUIDE.md` - Updated to reflect ModelConfig approach

### Files No Longer Needed for Deployment
- ⚠️ `config.py` - Still used by notebook for setup, but NOT packaged with agent
- ⚠️ `.env` - Still used by notebook for setup, but NOT packaged with agent

---

## Advantages Gained

### 1. Configuration is Immutable with Model Version

```python
# Model version 1: dev config
mlflow.pyfunc.log_model(..., model_config="dev_config.yaml")

# Model version 2: prod config
mlflow.pyfunc.log_model(..., model_config="prod_config.yaml")

# Each version has its own immutable config!
```

### 2. Cleaner Deployment Code

**Before:**
```python
# 30+ lines to build environment_vars dict
environment_vars = { ... }
agents.deploy(..., environment_vars=environment_vars)
```

**After:**
```python
# 1 line!
agents.deploy(UC_MODEL_NAME, version)
```

### 3. Easy Environment Management

```bash
# Just edit YAML files
prod_config.yaml   # Production
staging_config.yaml  # Staging
dev_config.yaml    # Development
```

### 4. Type-Safe Access

```python
# Get config values with type hints
catalog: str = model_config.get("catalog_name")
dims: int = model_config.get("lakebase_embedding_dims")
spaces: list = model_config.get("genie_space_ids")
```

---

## Testing the Refactoring

### 1. Test Local Development

```python
# Should work without any changes
python agent.py
```

### 2. Test Config Loading

```python
from mlflow.models import ModelConfig

# Test dev config
dev_config = ModelConfig(development_config="dev_config.yaml")
print(f"Catalog: {dev_config.get('catalog_name')}")

# Test prod config
prod_config = ModelConfig(development_config="prod_config.yaml")
print(f"Lakebase: {prod_config.get('lakebase_instance_name')}")
```

### 3. Test Deployment

```python
# Run deployment cell in notebook
# Should work without environment_vars parameter
```

---

## Troubleshooting

### Issue: "ModelConfig requires development_config"
**Cause:** Running old version of agent.py  
**Solution:** Ensure `agent.py` has `development_config` in `ModelConfig()` initialization

### Issue: "Config value not found"
**Cause:** Key missing in YAML file  
**Solution:** Check `prod_config.yaml` has all required keys from `dev_config.yaml`

### Issue: "Agent uses wrong config in Model Serving"
**Cause:** `model_config` not passed during `log_model()`  
**Solution:** Verify deployment code includes:
```python
mlflow.pyfunc.log_model(..., model_config="../prod_config.yaml")
```

---

## Key Takeaways

### ✅ What Was Achieved

1. **Switched to Databricks best practice** - ModelConfig explicitly recommended for this use case
2. **Eliminated environment_vars complexity** - 30+ lines reduced to 1 YAML file reference
3. **Configuration versioned with model** - immutable, auditable, traceable
4. **Cleaner code** - separation of config (YAML) from logic (Python)
5. **Better testing** - swap configs easily without code changes

### 📚 Documentation Created

- ✅ `dev_config.yaml` - Development configuration
- ✅ `prod_config.yaml` - Production configuration
- ✅ `MODELCONFIG_REFACTORING.md` - This guide
- ✅ Updated `agent.py` - Uses ModelConfig
- ✅ Updated `Super_Agent_hybrid.py` - Deployment uses model_config
- ✅ Updated `DEPLOYMENT_GUIDE.md` - Reflects ModelConfig approach

### 🎯 What You Need to Do

1. ✅ **Review configs** - Check `dev_config.yaml` and `prod_config.yaml`
2. ✅ **Update prod values** - Edit `prod_config.yaml` with your production settings
3. ✅ **Test locally** - Run `agent.py` to verify dev config works
4. ✅ **Deploy** - Run deployment cell (now simpler!)

---

## Complete Example

### dev_config.yaml (Local Testing)

```yaml
catalog_name: yyang
schema_name: multi_agent_genie
llm_endpoint: databricks-claude-sonnet-4-5
lakebase_instance_name: dev-lakebase-instance
genie_space_ids:
  - space1_dev
  - space2_dev
sample_size: 20  # Smaller for dev
```

### prod_config.yaml (Production)

```yaml
catalog_name: yyang
schema_name: multi_agent_genie
llm_endpoint: databricks-claude-sonnet-4-5
lakebase_instance_name: prod-lakebase-instance
genie_space_ids:
  - space1_prod
  - space2_prod
sample_size: 100  # Larger for prod
```

### agent.py (Runtime Code)

```python
from mlflow.models import ModelConfig

# Load config
model_config = ModelConfig(development_config="dev_config.yaml")

# Use config
CATALOG = model_config.get("catalog_name")
LAKEBASE_INSTANCE_NAME = model_config.get("lakebase_instance_name")
GENIE_SPACE_IDS = model_config.get("genie_space_ids")

# ... rest of agent code

# MLflow setup
mlflow.langchain.autolog()
mlflow.models.set_model(AGENT)
```

### Deployment Code

```python
# Log with prod config
with mlflow.start_run():
    logged_agent_info = mlflow.pyfunc.log_model(
        python_model="../agent.py",
        model_config="../prod_config.yaml",  # Prod config versioned with model!
        resources=resources,
        ...
    )

# Register to Unity Catalog
mlflow.set_registry_uri("databricks-uc")
uc_model_info = mlflow.register_model(
    model_uri=logged_agent_info.model_uri,
    name=UC_MODEL_NAME
)

# Deploy - clean and simple!
deployment_info = agents.deploy(
    UC_MODEL_NAME,
    uc_model_info.version,
    scale_to_zero=True,
    workload_size="Small"
    # ✅ NO environment_vars parameter!
)
```

---

## Reference Documentation

### Databricks Documentation
- [Parametrize code for deployment across environments](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent?language=LangGraph#parametrize-code-for-deployment-across-environments)
- Explicitly recommends ModelConfig for this use case

### MLflow Documentation
- [ModelConfig API](https://www.mlflow.org/docs/latest/python_api/mlflow.models.html#mlflow.models.ModelConfig)
- Details on YAML and dict formats

---

## Common Questions

### Q: Do I still need .env file?
**A:** Yes, for the **notebook** (setup and deployment code). No, for the **agent** (runtime).

- Notebook uses `.env` + `config.py` for setup (UC functions, vector search, etc.)
- Agent uses `ModelConfig` + YAML for runtime (inference in Model Serving)

### Q: Can I use both environment_vars and model_config?
**A:** Yes, but not recommended. ModelConfig is sufficient and cleaner.

### Q: What if I need to change config after deployment?
**A:** Create a new model version with updated config:
```python
# Log with updated config
mlflow.pyfunc.log_model(..., model_config="updated_prod_config.yaml")
# Register new version
mlflow.register_model(...)
# Deploy new version
agents.deploy(UC_MODEL_NAME, new_version)
```

### Q: Can I use environment variables for secrets?
**A:** Yes! For truly secret values (API keys, tokens), use `environment_vars`:
```python
# Use ModelConfig for general config
mlflow.pyfunc.log_model(..., model_config="prod_config.yaml")

# Use environment_vars for secrets only
agents.deploy(
    UC_MODEL_NAME,
    version,
    environment_vars={
        "OPENAI_API_KEY": "{{secrets/scope/key}}",  # Secret syntax
    }
)
```

---

## Migration Checklist

### Completed ✅
- [x] Created `dev_config.yaml`
- [x] Created `prod_config.yaml`
- [x] Updated `agent.py` to use ModelConfig
- [x] Updated deployment code to pass `model_config`
- [x] Removed `environment_vars` from deployment
- [x] Updated all documentation

### Your Actions
- [ ] Review `dev_config.yaml` - verify dev values
- [ ] Review `prod_config.yaml` - update prod values if different
- [ ] Test locally with dev config
- [ ] Deploy with prod config
- [ ] Verify deployed endpoint uses correct config

---

## Summary

### What We Did
✅ Refactored from `environment_vars` to `ModelConfig`  
✅ Created YAML configuration files (dev + prod)  
✅ Updated `agent.py` to use `ModelConfig`  
✅ Simplified deployment code (no environment_vars!)  
✅ Updated all documentation  

### Why This Is Better
✅ **Databricks best practice** - explicitly designed for this use case  
✅ **Configuration versioned with model** - immutable and auditable  
✅ **Cleaner deployment** - no complex env vars dict  
✅ **Easier testing** - swap configs without code changes  
✅ **Better separation** - dev vs prod configs  

### Status
✅ **COMPLETE** - Ready to deploy with ModelConfig!

---

**Reference:** 
- [Databricks: Parametrize code for deployment](https://docs.databricks.com/aws/en/generative-ai/agent-framework/author-agent?language=LangGraph#parametrize-code-for-deployment-across-environments)
- [MLflow: ModelConfig API](https://www.mlflow.org/docs/latest/python_api/mlflow.models.html#mlflow.models.ModelConfig)

**Ready to deploy with ModelConfig!** 🚀
