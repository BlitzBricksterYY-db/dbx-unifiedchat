# Virtual Environment Guide

## ✅ Installation Complete!

All necessary libraries have been successfully installed in `.venv/`.

---

## 📦 Installed Packages

### Core Agent Framework
- ✅ `langgraph-supervisor` (0.0.30)
- ✅ `langchain` (latest)
- ✅ `langchain-core` (latest)

### Databricks Integration
- ✅ `mlflow[databricks]` (3.6.0)
- ✅ `databricks-langchain`
- ✅ `databricks-agents`
- ✅ `databricks-vectorsearch`
- ✅ `databricks-sdk`

### Data Processing
- ✅ `pandas` (2.2.3)
- ✅ `numpy` (latest)
- ✅ `pyarrow` (latest)

### Configuration
- ✅ `pydantic` (2.12.5)
- ✅ `python-dotenv`

### Development Tools
- ✅ `pytest` (testing)
- ✅ `jupyter` (notebooks)
- ✅ `ipykernel` (kernel support)

---

## 🚀 Quick Start

### Activate Virtual Environment

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```cmd
.venv\Scripts\activate.bat
```

### Verify Installation
```bash
python verify_installation.py
```

### Deactivate Virtual Environment
```bash
deactivate
```

---

## 💻 Usage Examples

### 1. Run Notebooks in VS Code

With the virtual environment activated:
```bash
# Install Jupyter kernel
python -m ipykernel install --user --name=multi_agent_venv --display-name="Multi-Agent System"

# Open VS Code and select the kernel
code .
```

In VS Code:
1. Open any `.ipynb` or `.py` notebook
2. Click "Select Kernel" in top right
3. Choose "Multi-Agent System"

### 2. Run Python Scripts

```bash
# Activate venv
source .venv/bin/activate

# Run config check
python config.py

# Run agent
python -c "from agent import AGENT; print('Agent loaded successfully!')"
```

### 3. Run Tests

```bash
source .venv/bin/activate
pytest tests/  # If you add tests
```

### 4. Install Additional Packages

```bash
source .venv/bin/activate
pip install package-name
pip freeze > requirements.txt  # Update requirements
```

---

## 🔍 Troubleshooting

### Issue: "Command not found: source"
**Solution (Windows):**
```cmd
.venv\Scripts\activate.bat
```

### Issue: Import errors in notebooks
**Solution:**
```bash
# Reinstall kernel
source .venv/bin/activate
python -m ipykernel install --user --name=multi_agent_venv --display-name="Multi-Agent System" --force
```

### Issue: Package conflicts
**Solution:**
```bash
# Recreate venv
rm -rf .venv
./setup_venv.sh
```

### Issue: Permission denied on setup_venv.sh
**Solution:**
```bash
chmod +x setup_venv.sh
./setup_venv.sh
```

---

## 📋 Verification Checklist

Run these commands to verify everything works:

```bash
# Activate venv
source .venv/bin/activate

# Check Python version
python --version
# Expected: Python 3.11.9 or higher

# Check pip version
pip --version
# Expected: pip 25.3 or higher

# Verify key imports
python -c "import langgraph_supervisor; print('✓ LangGraph')"
python -c "import mlflow; print('✓ MLflow')"
python -c "from databricks.sdk import WorkspaceClient; print('✓ Databricks SDK')"
python -c "from databricks.vector_search.client import VectorSearchClient; print('✓ Vector Search')"
python -c "import databricks_langchain; print('✓ Databricks LangChain')"

# All imports at once
python verify_installation.py
```

Expected output: All checks pass ✅

---

## 🔄 Update Dependencies

### Update All Packages
```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

### Update Single Package
```bash
source .venv/bin/activate
pip install --upgrade package-name
```

### Check Outdated Packages
```bash
source .venv/bin/activate
pip list --outdated
```

---

## 📝 Environment Variables

Create `.env` file from template:
```bash
cp .env.example .env
# Edit .env with your values
```

Required variables:
```bash
DATABRICKS_HOST=https://your-workspace.databricks.com
DATABRICKS_TOKEN=dapi_your_token
CATALOG_NAME=your_catalog
SCHEMA_NAME=your_schema
LLM_ENDPOINT=databricks-claude-sonnet-4-5
```

---

## 🎯 Next Steps

1. **✅ Virtual environment ready** - All packages installed
2. **Configure environment** - Edit `.env` file
3. **Run metadata pipeline** - Execute `02_Table_MetaInfo_Enrichment.py`
4. **Build vector search** - Execute `04_VS_Enriched_Genie_Spaces.py`
5. **Test multi-agent** - Execute `05_Multi_Agent_System.py`

See **QUICKSTART.md** for detailed instructions.

---

## 🛠️ IDE Integration

### VS Code

Add to `.vscode/settings.json`:
```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true,
  "jupyter.kernels.filter": [
    {
      "path": "${workspaceFolder}/.venv/bin/python",
      "type": "pythonEnvironment"
    }
  ]
}
```

### PyCharm

1. File → Settings → Project → Python Interpreter
2. Click gear icon → Add
3. Select "Existing environment"
4. Choose `.venv/bin/python`

### Jupyter

```bash
source .venv/bin/activate
jupyter notebook
# Select "Multi-Agent System" kernel
```

---

## 📊 Package Size

Total installation size: ~2.5 GB
- Python packages: ~2.3 GB
- Virtual environment: ~200 MB

---

## 🔒 Security Notes

- ✅ Virtual environment isolates dependencies
- ✅ `.env` file gitignored (credentials protected)
- ✅ `.venv` folder gitignored (not committed)
- ⚠️ Never commit `.env` or credentials

---

## 📚 Additional Resources

- **Requirements:** `requirements.txt`
- **Setup Script:** `setup_venv.sh` (macOS/Linux) or `setup_venv.bat` (Windows)
- **Verification:** `verify_installation.py`
- **Configuration:** `config.py`
- **Documentation:** `README.md`, `QUICKSTART.md`, `ARCHITECTURE.md`

---

## ✨ Summary

```bash
# Installation completed successfully!
✓ Python 3.11.9
✓ 13 core packages installed
✓ All imports verified
✓ Development tools ready
✓ Jupyter kernel configured

# You're ready to build!
```

**Status:** 🟢 Ready for Development

---

**Last Updated:** December 1, 2025  
**Python Version:** 3.11.9  
**Virtual Environment:** `.venv/`

