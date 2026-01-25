# Environment Variables in Model Serving Deployment

## ⚠️ CRITICAL: .env File is NOT Uploaded

**Important:** When deploying to Databricks Model Serving, the `.env` file is **NOT** automatically uploaded. You **MUST** pass environment variables explicitly via `agents.deploy()`.

---

## How It Works

### Local Development
```python
# config.py uses load_dotenv() to load from .env
from dotenv import load_dotenv
load_dotenv()  # ✅ Loads from .env file

# Then uses os.getenv() with defaults
CATALOG = os.getenv("CATALOG_NAME", "yyang")
```

**Flow:**
1. `.env` file exists locally
2. `load_dotenv()` reads it
3. `os.getenv()` gets values from environment
4. ✅ Works!

---

### Model Serving Deployment
```python
# config.py tries to load from .env
from dotenv import load_dotenv
load_dotenv()  # ⚠️ .env file doesn't exist! (but this is safe - no error)

# Then uses os.getenv() with defaults
CATALOG = os.getenv("CATALOG_NAME", "yyang")  # ❌ Returns default, not your value!
```

**Flow:**
1. ❌ `.env` file does NOT exist in Model Serving
2. `load_dotenv()` does nothing (safely)
3. `os.getenv()` only gets default values
4. ❌ Configuration is WRONG!

---

## The Solution

**Pass environment variables explicitly during deployment:**

```python
# In deployment code
import os
from databricks import agents

# ⚠️ CRITICAL: Prepare environment variables
environment_vars = {
    # Unity Catalog
    "CATALOG_NAME": os.getenv("CATALOG_NAME", "yyang"),
    "SCHEMA_NAME": os.getenv("SCHEMA_NAME", "multi_agent_genie"),
    
    # LLM Endpoint
    "LLM_ENDPOINT": os.getenv("LLM_ENDPOINT", "databricks-claude-sonnet-4-5"),
    
    # Vector Search
    "VS_ENDPOINT_NAME": os.getenv("VS_ENDPOINT_NAME", "genie_multi_agent_vs"),
    "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "databricks-gte-large-en"),
    
    # Lakebase (CRITICAL for memory!)
    "LAKEBASE_INSTANCE_NAME": os.getenv("LAKEBASE_INSTANCE_NAME", "multi-agent-genie-system-state-db"),
    "LAKEBASE_EMBEDDING_ENDPOINT": os.getenv("LAKEBASE_EMBEDDING_ENDPOINT", "databricks-gte-large-en"),
    "LAKEBASE_EMBEDDING_DIMS": os.getenv("LAKEBASE_EMBEDDING_DIMS", "1024"),
    
    # Genie Spaces
    "GENIE_SPACE_IDS": os.getenv("GENIE_SPACE_IDS", ""),
    
    # Optional
    "SAMPLE_SIZE": os.getenv("SAMPLE_SIZE", "100"),
    "MAX_UNIQUE_VALUES": os.getenv("MAX_UNIQUE_VALUES", "50"),
}

# Deploy with environment variables
deployment_info = agents.deploy(
    model_name,
    version,
    scale_to_zero=True,
    workload_size="Small",
    environment_vars=environment_vars  # ⚠️ CRITICAL!
)
```

**Flow:**
1. ✅ Environment variables passed to Model Serving
2. ✅ Model Serving sets them in the container
3. ✅ `os.getenv()` gets correct values
4. ✅ Configuration is CORRECT!

---

## Why This Pattern Works

### 1. Local Development
```bash
# Your .env file
CATALOG_NAME=yyang
SCHEMA_NAME=multi_agent_genie
LAKEBASE_INSTANCE_NAME=multi-agent-genie-system-state-db
```

```python
# When you run locally
os.getenv("CATALOG_NAME", "yyang")  # ✅ Gets "yyang" from .env
```

### 2. Deployment Preparation
```python
# When preparing deployment (still local)
environment_vars = {
    "CATALOG_NAME": os.getenv("CATALOG_NAME", "yyang"),  # ✅ Gets "yyang" from .env
}
```

### 3. Model Serving Runtime
```python
# In Model Serving container
# Environment variables were passed via agents.deploy()
os.getenv("CATALOG_NAME", "yyang")  # ✅ Gets "yyang" from passed env vars
```

---

## Complete Example

### Step 1: Your `.env` File (Local)
```bash
# .env
CATALOG_NAME=yyang
SCHEMA_NAME=multi_agent_genie
LLM_ENDPOINT=databricks-claude-sonnet-4-5
LAKEBASE_INSTANCE_NAME=multi-agent-genie-system-state-db
LAKEBASE_EMBEDDING_ENDPOINT=databricks-gte-large-en
LAKEBASE_EMBEDDING_DIMS=1024
GENIE_SPACE_IDS=space1,space2,space3
```

### Step 2: Deployment Code
```python
# Notebooks/Super_Agent_hybrid.py (deployment cell)
import os
from databricks import agents

# Read from YOUR .env file (locally)
environment_vars = {
    "CATALOG_NAME": os.getenv("CATALOG_NAME"),          # Gets "yyang" from .env
    "SCHEMA_NAME": os.getenv("SCHEMA_NAME"),            # Gets "multi_agent_genie" from .env
    "LLM_ENDPOINT": os.getenv("LLM_ENDPOINT"),          # Gets "databricks-claude-sonnet-4-5" from .env
    "LAKEBASE_INSTANCE_NAME": os.getenv("LAKEBASE_INSTANCE_NAME"),  # Gets your instance name
    "LAKEBASE_EMBEDDING_ENDPOINT": os.getenv("LAKEBASE_EMBEDDING_ENDPOINT"),
    "LAKEBASE_EMBEDDING_DIMS": os.getenv("LAKEBASE_EMBEDDING_DIMS"),
    "GENIE_SPACE_IDS": os.getenv("GENIE_SPACE_IDS"),
}

# These values are NOW passed to Model Serving
agents.deploy(
    UC_MODEL_NAME,
    version,
    environment_vars=environment_vars  # ⚠️ CRITICAL!
)
```

### Step 3: Model Serving Runtime
```python
# agent.py (running in Model Serving)
from config import get_config

# config.py does:
# CATALOG_NAME = os.getenv("CATALOG_NAME", "yyang")
# ✅ Gets "yyang" from environment variables passed during deployment

config = get_config()  # ✅ Works correctly!
```

---

## What Gets Uploaded vs. What Doesn't

### ✅ Uploaded to Model Serving
- `agent.py` (your agent code)
- `config.py` (configuration logic)
- `requirements.txt` (Python packages)
- Any additional Python files you reference

### ❌ NOT Uploaded to Model Serving
- `.env` file
- `.env.example` file
- Notebook files (`.py` notebooks)
- Any files not referenced by `agent.py`

---

## Common Mistakes

### ❌ WRONG: Not passing environment variables
```python
agents.deploy(
    UC_MODEL_NAME,
    version,
    scale_to_zero=True,
    workload_size="Small"
    # ❌ Missing environment_vars!
)
```

**Result:** Agent fails with configuration errors or uses default values

---

### ❌ WRONG: Hardcoding values
```python
environment_vars = {
    "CATALOG_NAME": "yyang",  # ❌ Hardcoded!
}
```

**Problem:** Not flexible, must edit code to change

---

### ✅ CORRECT: Reading from .env
```python
environment_vars = {
    "CATALOG_NAME": os.getenv("CATALOG_NAME", "yyang"),  # ✅ Reads from .env, falls back to default
}
```

**Benefits:** 
- Flexible (edit .env, not code)
- Same values in dev and production
- Safe fallback to defaults

---

## Verification

### Check Local Environment
```python
import os
from dotenv import load_dotenv

load_dotenv()
print(f"CATALOG_NAME: {os.getenv('CATALOG_NAME')}")
print(f"LAKEBASE_INSTANCE_NAME: {os.getenv('LAKEBASE_INSTANCE_NAME')}")
```

### Check Deployed Environment (via logs)
```python
# Add to agent.py for debugging
import os
import logging

logger = logging.getLogger(__name__)
logger.info(f"CATALOG_NAME: {os.getenv('CATALOG_NAME')}")
logger.info(f"LAKEBASE_INSTANCE_NAME: {os.getenv('LAKEBASE_INSTANCE_NAME')}")
```

Then check Model Serving logs to verify values.

---

## Troubleshooting

### Issue: "Configuration error" in Model Serving
**Cause:** Environment variables not passed  
**Solution:** Add `environment_vars` parameter to `agents.deploy()`

### Issue: Agent uses wrong catalog/schema
**Cause:** Using default values instead of your .env values  
**Solution:** Verify you're passing environment variables with correct names

### Issue: "LAKEBASE_INSTANCE_NAME not found"
**Cause:** Lakebase config not passed  
**Solution:** Ensure Lakebase env vars are in `environment_vars` dict

---

## Best Practices

### 1. Always Pass All Required Env Vars
```python
# Create a comprehensive environment_vars dict
environment_vars = {
    # All Unity Catalog settings
    "CATALOG_NAME": os.getenv("CATALOG_NAME", "default_catalog"),
    "SCHEMA_NAME": os.getenv("SCHEMA_NAME", "default_schema"),
    
    # All LLM settings
    "LLM_ENDPOINT": os.getenv("LLM_ENDPOINT", "default_llm"),
    
    # All Lakebase settings (CRITICAL for memory!)
    "LAKEBASE_INSTANCE_NAME": os.getenv("LAKEBASE_INSTANCE_NAME", "default_instance"),
    # ...
}
```

### 2. Use Defaults as Fallbacks
```python
# Good: Provides fallback
"CATALOG_NAME": os.getenv("CATALOG_NAME", "yyang")

# Bad: No fallback (fails if not set)
"CATALOG_NAME": os.getenv("CATALOG_NAME")
```

### 3. Document Required Env Vars
Keep `.env.example` up to date with all required variables

### 4. Validate Before Deployment
```python
# Check that critical env vars are set
required_vars = ["CATALOG_NAME", "SCHEMA_NAME", "LAKEBASE_INSTANCE_NAME"]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    raise ValueError(f"Missing required environment variables: {missing}")
```

---

## Summary

### Key Points
1. ❌ `.env` file is **NOT** uploaded to Model Serving
2. ✅ Must pass environment variables via `agents.deploy(environment_vars={...})`
3. ✅ `config.py` uses `os.getenv()` which works with passed env vars
4. ✅ `load_dotenv()` is safe (does nothing if .env doesn't exist)
5. ✅ Same pattern works locally and in Model Serving

### Checklist Before Deployment
- [ ] All required env vars defined in `.env`
- [ ] `environment_vars` dict prepared in deployment code
- [ ] All critical settings included (Catalog, Schema, Lakebase, etc.)
- [ ] `agents.deploy()` includes `environment_vars` parameter
- [ ] Tested locally with same env vars

---

**Remember:** The `.env` file is for local development convenience. For Model Serving, you **MUST** pass environment variables explicitly! 🚀
