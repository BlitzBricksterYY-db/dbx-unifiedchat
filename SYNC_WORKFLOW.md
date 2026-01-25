# Sync Workflow: Notebook ↔ agent.py

## Overview

You have two options for maintaining `agent.py`:

1. **Option A (Recommended)**: Edit directly in `agent.py`, test in notebook
2. **Option B**: Use `%%writefile` cell in notebook to sync to `agent.py`

---

## Option A: Direct Editing (Recommended)

### Workflow

```
1. Edit agent.py directly
   ├─ Make your changes in agent.py
   └─ Save the file

2. Test in notebook
   ├─ Run: %run ../agent.py  (imports AGENT from agent.py)
   ├─ Test locally with AGENT.predict()
   └─ Iterate as needed

3. Deploy when ready
   ├─ agent.py is already up-to-date!
   └─ Run deployment cell
```

### Testing in Notebook

```python
# COMMAND ----------
# DBTITLE 1,Test agent.py (loads from file)

# Import agent from agent.py
%run ../agent.py

# Test it
from mlflow.types.responses import ResponsesAgentRequest
from uuid import uuid4

thread_id = str(uuid4())
result = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "Show me patient demographics"}],
    custom_inputs={"thread_id": thread_id}
))
print(result.model_dump(exclude_none=True))
```

**Advantages:**
- ✅ Simple - edit one file
- ✅ No sync required
- ✅ agent.py is always deployment-ready
- ✅ Can use IDE features (autocomplete, linting)

---

## Option B: %%writefile Cell (Alternative)

### Workflow

```
1. Edit in notebook
   ├─ Make changes to agent code in notebook cells
   └─ Test locally

2. Sync to agent.py
   ├─ Uncomment %%writefile ../agent.py in sync cell
   ├─ Run the sync cell
   └─ agent.py is now updated

3. Deploy
   └─ Run deployment cell
```

### How to Use %%writefile

**Step 1: Find the Sync Cell**

Look for this cell in the notebook (around Line 2577):
```python
# DBTITLE 1,⚙️ SYNC TO agent.py
# %%writefile ../agent.py  ← Uncomment this line!
```

**Step 2: Make Your Edits**

Edit the agent code in the notebook cells where it's defined.

**Step 3: Uncomment and Run**

```python
%%writefile ../agent.py  # ← Uncommented!
# ... rest of agent code ...
```

Run the cell. Output will show:
```
Writing ../agent.py
```

**Step 4: Verify**

```python
# Check that agent.py was updated
!head -20 ../agent.py
```

**Advantages:**
- ✅ Single source of truth (notebook)
- ✅ Explicit sync step
- ✅ Can see changes in git diff

**Disadvantages:**
- ⚠️ Must remember to sync before deploying
- ⚠️ Large cell (900 lines)

---

## Recommended Workflow (Hybrid Approach)

### For Development

```
1. Edit agent.py directly for quick iterations
2. Use IDE for editing (syntax highlighting, autocomplete)
3. Test in notebook with %run ../agent.py
```

### For Major Changes

```
1. Make changes in notebook cells (easier to test inline)
2. Test thoroughly
3. Use %%writefile to sync to agent.py
4. Verify with git diff
5. Deploy
```

---

## Current Setup

Your notebook already has the agent code defined in cells. Here's the structure:

```
Notebooks/Super_Agent_hybrid.py:
├─ Lines ~160-390: AgentState definition
├─ Lines ~400-500: Helper functions
├─ Lines ~500-1900: Agent classes
├─ Lines ~1900-2100: Workflow creation
├─ Lines ~2100-2500: ResponsesAgent wrapper
└─ Lines ~2500-2575: Agent instantiation
```

All this code is **also in agent.py** for deployment.

---

## Testing Strategy

### Local Testing (Before Syncing)

```python
# Test in notebook without agent.py
# Use the AGENT variable created in the notebook

from mlflow.types.responses import ResponsesAgentRequest
result = AGENT.predict(ResponsesAgentRequest(
    input=[{"role": "user", "content": "test query"}],
    custom_inputs={"thread_id": "test-123"}
))
print(result)
```

### Test agent.py (After Syncing)

```python
# Import from agent.py file
%run ../agent.py

# Test the imported AGENT
result = AGENT.predict(ResponsesAgentRequest(...))
print(result)
```

### Test Deployment Package

```python
# Test the exact code that will be deployed
import mlflow
logged_agent = mlflow.pyfunc.load_model(logged_agent_info.model_uri)

# This uses agent.py + prod_config.yaml
result = logged_agent.predict(request)
print(result)
```

---

## Quick Commands

### Option A: Edit agent.py directly

```bash
# Edit agent.py
vim ../agent.py

# Test in notebook
%run ../agent.py
AGENT.predict(...)
```

### Option B: Sync from notebook

```python
# In notebook sync cell
%%writefile ../agent.py
# ... (agent code) ...

# Verify
!wc -l ../agent.py  # Should be ~900 lines
```

### Check Differences

```bash
# See what changed
!git diff ../agent.py
```

---

## Common Scenarios

### Scenario 1: Quick Bug Fix

```
1. Edit agent.py directly (Line XXX)
2. Test: %run ../agent.py
3. Works? Deploy!
```

**Time: 2 minutes**

### Scenario 2: Major Refactoring

```
1. Edit in notebook cells (easier to test incrementally)
2. Test each change inline
3. When done, sync to agent.py with %%writefile
4. Verify with git diff
5. Deploy
```

**Time: 20-60 minutes**

### Scenario 3: New Agent Added

```
1. Add new agent class in notebook cell
2. Test locally
3. Add to agent.py (either edit directly or use %%writefile)
4. Update deployment resources if needed
5. Deploy
```

**Time: 30-90 minutes**

---

## Troubleshooting

### Issue: agent.py and notebook out of sync

**Solution:**
```python
# Compare line counts
!wc -l ../agent.py
!echo "Notebook AGENT instantiation at line: ~2500"

# If different, either:
# Option 1: Edit agent.py to match notebook
# Option 2: Use %%writefile to sync from notebook
```

### Issue: Changes in agent.py not reflected in notebook

**Solution:**
```python
# Reload agent.py
%run ../agent.py

# Or restart kernel
dbutils.library.restartPython()
%run ../agent.py
```

### Issue: %%writefile creates file with incorrect content

**Solution:**
```python
# Check the cell carefully - %%writefile must be on the FIRST line
# Correct:
%%writefile ../agent.py
import mlflow
# ...

# Incorrect:
# This is a comment
%%writefile ../agent.py  # ← This won't work!
```

---

## Best Practices

### ✅ DO

- ✅ Edit agent.py directly for small changes
- ✅ Test with %run ../agent.py before deploying
- ✅ Use git to track changes
- ✅ Verify agent.py after syncing
- ✅ Keep agent.py and notebook in sync

### ❌ DON'T

- ❌ Edit agent.py and forget to test
- ❌ Use %%writefile without uncommenting properly
- ❌ Deploy without testing agent.py first
- ❌ Make changes in multiple places and lose track

---

## Summary

### Recommended Workflow

```
FOR QUICK CHANGES:
  └─ Edit agent.py directly → Test in notebook → Deploy

FOR MAJOR CHANGES:
  └─ Edit in notebook → Test → Sync with %%writefile → Deploy

ALWAYS:
  └─ Test before deploying!
```

### Files to Track

- ✅ `agent.py` - Runtime deployment code (track in git)
- ✅ `Super_Agent_hybrid.py` - Development notebook (track in git)
- ✅ `prod_config.yaml` - Production config (track in git)
- ⚠️ `.env` - Local only (don't commit)

---

## Quick Reference

| Task | Command |
|------|---------|
| Edit agent.py | `vim ../agent.py` |
| Test agent.py in notebook | `%run ../agent.py` |
| Sync from notebook | Uncomment `%%writefile ../agent.py` in sync cell |
| Check line count | `!wc -l ../agent.py` |
| View differences | `!git diff ../agent.py` |
| Verify sync | `!head -20 ../agent.py` |

---

**Ready to use your preferred workflow!** 🚀

Choose Option A (direct editing) for simplicity, or Option B (%%writefile) if you prefer notebook-centric development.
