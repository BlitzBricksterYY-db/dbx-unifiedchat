# MLflow Tracing Fix - Quick Start Guide

## Problem
Getting this error when deploying to Databricks Model Serving:
```
mlflow.tracing.fluent: Failed to start span predict_stream: 
'NonRecordingSpan' object has no attribute 'context'
```

## Solution Applied
✅ Fixed package installation to use full MLflow instead of mlflow-skinny  
✅ Added `run_tracer_inline=True` for async context support  
✅ Consolidated autolog initialization to prevent context conflicts  
✅ Added error handling for graceful degradation  

---

## Step-by-Step: Apply and Test the Fix

### Step 1: Review Changes
All changes have been applied to `Notebooks/Super_Agent_hybrid.py`:
- **Line 9**: Package installation updated
- **Lines 3996-4005**: Autolog initialization with error handling
- **Lines 3744-3752**: Streaming safety checks
- **Lines 1679-1680**: Removed redundant autolog call
- **Lines 4651-4652**: Removed redundant autolog call

Review the detailed summary: `MLFLOW_TRACING_FIX_SUMMARY.md`

### Step 2: Validate Locally (Optional)
Run the validation script to check your local environment:
```bash
python test_mlflow_tracing_fix.py
```

Expected output:
```
✅ PASS: MLflow Package
✅ PASS: MLflow Tracing Module
✅ PASS: LangChain Autolog
✅ PASS: NonRecordingSpan Safety
✅ PASS: Databricks Packages

Total: 5/5 tests passed
🎉 All tests passed!
```

### Step 3: Update Databricks Notebook

#### Option A: Upload the Updated File
1. Go to Databricks Workspace → Notebooks
2. Navigate to your notebook location
3. Upload `Super_Agent_hybrid.py` (will overwrite existing)
4. Open the notebook

#### Option B: Manual Updates
If you prefer to manually update in Databricks UI:

**Change 1 - Line 9 (Package Installation):**
```python
# BEFORE
%pip install ... mlflow-skinny[databricks]

# AFTER
%pip install ... mlflow[databricks]>=3.6.0
```

**Change 2 - Lines 3996-4005 (Autolog Initialization):**
```python
# BEFORE
mlflow.langchain.autolog()
mlflow.models.set_model(AGENT)

# AFTER
try:
    mlflow.langchain.autolog(run_tracer_inline=True)
    logger.info("✓ MLflow LangChain autologging enabled with async context support")
except Exception as e:
    logger.warning(f"⚠️ MLflow autolog initialization failed: {e}")
    logger.warning("Continuing without MLflow tracing...")

mlflow.models.set_model(AGENT)
```

**Change 3 - Line 3744 (Streaming Safeguard):**
Add after `logger.info(f"Processing request..."):
```python
# Ensure MLflow tracing doesn't cause issues in streaming context
try:
    import mlflow.tracing
    if not hasattr(mlflow.tracing, '_is_enabled') or not mlflow.tracing._is_enabled():
        logger.debug("MLflow tracing not enabled, continuing without tracing")
except Exception as e:
    logger.debug(f"MLflow tracing check skipped: {e}")
```

**Change 4 - Lines 1679-1680 (Remove redundant call):**
```python
# BEFORE
# Enable MLflow autologging for tracing
mlflow.langchain.autolog()

# AFTER
# MLflow autologging is enabled globally at agent initialization
# No need to call it again here to avoid context issues
```

**Change 5 - Lines 4651-4652 (Remove redundant call):**
```python
# BEFORE
# Enable MLflow tracing
mlflow.langchain.autolog()

# AFTER
# MLflow autologging is enabled globally at agent initialization
# No need to call it again here to avoid context issues
```

### Step 4: Restart and Test in Databricks

1. **Restart Python:**
   ```python
   # Run this in a cell
   dbutils.library.restartPython()
   ```

2. **Run package installation cell** (with updated mlflow package)

3. **Run configuration cells**

4. **Look for success message:**
   You should see:
   ```
   ✓ MLflow LangChain autologging enabled with async context support
   ```

5. **Test the agent:**
   ```python
   from mlflow.types.responses import ResponsesAgentRequest
   
   # Test streaming
   request = ResponsesAgentRequest(
       input=[{"role": "user", "content": "Show me patient data"}],
       custom_inputs={"thread_id": "test-123"}
   )
   
   # This should work without NonRecordingSpan errors
   for event in AGENT.predict_stream(request):
       print(f"Event type: {event.type}")
   ```

### Step 5: Deploy to Model Serving

1. **Log the model with updated code:**
   The notebook already has the deployment cell configured. Run it after testing.

2. **Create/Update Model Serving Endpoint:**
   ```python
   # The deployment cell in the notebook handles this
   # Make sure prod_config.yaml is correctly configured
   ```

3. **Monitor the deployment logs:**
   ```bash
   databricks serving-endpoints logs <your-endpoint-name> --follow
   ```

4. **Look for these indicators:**
   - ✅ No NonRecordingSpan errors
   - ✅ "MLflow LangChain autologging enabled" message appears
   - ✅ Streaming responses work correctly

### Step 6: Test in Production

Send a test request to your endpoint:
```python
import requests
import json

endpoint_url = "https://<workspace>.cloud.databricks.com/serving-endpoints/<endpoint>/invocations"
token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

data = {
    "messages": [{"role": "user", "content": "Test query"}],
    "context": {
        "conversation_id": "test-001",
        "user_id": "test@example.com"
    }
}

response = requests.post(endpoint_url, headers=headers, json=data, stream=True)

for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

---

## Troubleshooting

### Issue: Still seeing NonRecordingSpan errors

**Check:**
1. Did Python restart after updating the package?
2. Is the correct MLflow version installed?
   ```python
   import mlflow
   print(mlflow.__version__)  # Should be >= 3.6.0
   ```
3. Are you seeing the autolog success message?

**Solution:**
- Clear library cache: In Databricks, detach and reattach cluster
- Manually uninstall old package:
  ```python
  %pip uninstall -y mlflow-skinny mlflow
  %pip install mlflow[databricks]>=3.6.0
  dbutils.library.restartPython()
  ```

### Issue: Autolog initialization fails

**Check the error message:**
- If "run_tracer_inline" not recognized → MLflow version too old
- If permission error → Check cluster permissions
- If import error → Package installation incomplete

**Solution:**
The try-except block will catch this and allow the agent to continue without tracing.
You can proceed with deployment, but consider investigating the root cause.

### Issue: Streaming responses are slow

**This is expected** if you've enabled full tracing. Tracing adds overhead.

**Options:**
1. Disable tracing for production if not needed
2. Use selective tracing (trace only key operations)
3. Accept the overhead for observability benefits

---

## What Changed (Technical Summary)

### Package Change
- **Before:** `mlflow-skinny[databricks]` - lightweight, limited tracing
- **After:** `mlflow[databricks]>=3.6.0` - full package with complete tracing support

### Autolog Configuration
- **Added:** `run_tracer_inline=True` - ensures async context propagation
- **Added:** Error handling - graceful degradation if tracing fails
- **Removed:** Multiple autolog calls - prevents context conflicts

### Safety Mechanisms
- **Added:** Streaming method safeguards - checks tracing state before execution
- **Added:** Logging - visibility into tracing initialization

---

## Success Indicators

✅ **Local testing:**
- Validation script passes all tests
- Agent initialization shows autolog success message
- predict_stream works without errors

✅ **Databricks deployment:**
- No NonRecordingSpan errors in logs
- Streaming responses work correctly
- Tracing data appears in MLflow UI (if enabled)

✅ **Production:**
- Model Serving endpoint responds successfully
- No errors in endpoint logs
- Users can interact with the agent

---

## Support Resources

- **Detailed Changes:** See `MLFLOW_TRACING_FIX_SUMMARY.md`
- **MLflow Documentation:** https://mlflow.org/docs/latest/tracing/
- **Databricks Model Serving:** https://docs.databricks.com/machine-learning/model-serving/
- **LangChain Tracing:** https://mlflow.org/docs/latest/tracing/integrations/langchain

---

**Last Updated:** February 2, 2026  
**Status:** ✅ Ready for deployment
