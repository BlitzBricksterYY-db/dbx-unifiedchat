#!/usr/bin/env python3
"""
Verification script for Multi-Agent System installation.
Run this after setting up the virtual environment to ensure all dependencies are correctly installed.
"""

import sys
from typing import List, Tuple

def check_imports() -> Tuple[List[str], List[str]]:
    """Check if all required packages can be imported."""
    
    packages = {
        'langgraph_supervisor': 'LangGraph Supervisor',
        'langchain': 'LangChain',
        'langchain_core': 'LangChain Core',
        'mlflow': 'MLflow',
        'databricks_langchain': 'Databricks LangChain',
        'databricks.sdk': 'Databricks SDK',
        'databricks.vector_search.client': 'Databricks Vector Search',
        'databricks.agents': 'Databricks Agents',
        'pydantic': 'Pydantic',
        'dotenv': 'Python-dotenv',
        'pandas': 'Pandas',
        'numpy': 'NumPy',
        'requests': 'Requests',
    }
    
    success = []
    failed = []
    
    print("Checking package imports...")
    print("-" * 60)
    
    for module, name in packages.items():
        try:
            __import__(module)
            print(f"✓ {name:30s} OK")
            success.append(name)
        except ImportError as e:
            print(f"✗ {name:30s} FAILED: {str(e)}")
            failed.append(name)
    
    return success, failed


def check_versions():
    """Check versions of key packages."""
    print("\n" + "=" * 60)
    print("Package Versions")
    print("=" * 60)
    
    try:
        import langgraph_supervisor
        print(f"langgraph-supervisor: {langgraph_supervisor.__version__}")
    except:
        print("langgraph-supervisor: version unknown")
    
    try:
        import mlflow
        print(f"mlflow: {mlflow.__version__}")
    except:
        print("mlflow: version unknown")
    
    try:
        import databricks_langchain
        try:
            print(f"databricks-langchain: {databricks_langchain.__version__}")
        except:
            print("databricks-langchain: version unknown")
    except:
        print("databricks-langchain: not installed")
    
    try:
        import pandas
        print(f"pandas: {pandas.__version__}")
    except:
        print("pandas: version unknown")
    
    try:
        import pydantic
        print(f"pydantic: {pydantic.__version__}")
    except:
        print("pydantic: version unknown")


def check_python_version():
    """Check if Python version is compatible."""
    print("\n" + "=" * 60)
    print("Python Environment")
    print("=" * 60)
    
    version = sys.version_info
    print(f"Python Version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("⚠ Warning: Python 3.11 or higher is recommended")
        return False
    else:
        print("✓ Python version is compatible")
        return True


def main():
    """Main verification function."""
    print("=" * 60)
    print("Multi-Agent System - Installation Verification")
    print("=" * 60)
    
    # Check Python version
    python_ok = check_python_version()
    
    # Check package imports
    success, failed = check_imports()
    
    # Check versions
    check_versions()
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"✓ Packages successfully imported: {len(success)}")
    if failed:
        print(f"✗ Packages failed to import: {len(failed)}")
        print("\nFailed packages:")
        for pkg in failed:
            print(f"  - {pkg}")
        print("\nTry reinstalling with: pip install -r requirements.txt")
        return False
    else:
        print("✓ All packages successfully imported")
    
    if not python_ok:
        print("\n⚠ Python version issue detected")
        return False
    
    print("\n" + "=" * 60)
    print("✓ Installation verification successful!")
    print("=" * 60)
    print("\nYou're ready to run the multi-agent system.")
    print("Next steps:")
    print("  1. Configure your .env file")
    print("  2. Follow QUICKSTART.md for setup")
    print("  3. Run the notebooks in order")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

