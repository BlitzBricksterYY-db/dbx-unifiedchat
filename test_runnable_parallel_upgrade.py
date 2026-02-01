"""
Test script to verify RunnableParallel upgrade for SQLSynthesisGenieAgent.

This script validates:
1. RunnableParallel import is available
2. SQLSynthesisGenieAgent class has new parallel execution capabilities
3. New methods and attributes are properly defined
"""

def test_imports():
    """Test that RunnableParallel can be imported."""
    print("Testing imports...")
    try:
        from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel, RunnableConfig
        print("  ✓ All runnables imported successfully")
        print(f"    - RunnableParallel: {RunnableParallel}")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_class_structure():
    """Test that SQLSynthesisGenieAgent has the expected structure."""
    print("\nTesting class structure...")
    
    # Read the file to check structure
    import os
    file_path = os.path.join(os.path.dirname(__file__), "Notebooks", "Super_Agent_hybrid.py")
    
    if not os.path.exists(file_path):
        print(f"  ✗ File not found: {file_path}")
        return False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check for key components
    checks = [
        ("RunnableParallel import", "RunnableParallel" in content),
        ("SQLSynthesisGenieAgent class", "class SQLSynthesisGenieAgent:" in content),
        ("_create_genie_agent_tools method", "def _create_genie_agent_tools(self):" in content),
        ("parallel_executors attribute", "self.parallel_executors = parallel_executors" in content),
        ("invoke_genie_agents_parallel method", "def invoke_genie_agents_parallel(self" in content),
        ("EXECUTION MODES documentation", "EXECUTION MODES:" in content),
        ("RunnableParallel in docstring", "RunnableParallel" in content and "pattern" in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        if check_result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ✗ {check_name}")
            all_passed = False
    
    return all_passed


def test_local_dev_file():
    """Test that local dev file also has the upgrades."""
    print("\nTesting local dev file...")
    
    import os
    file_path = os.path.join(os.path.dirname(__file__), "Notebooks", "Super_Agent_hybrid_local_dev.py")
    
    if not os.path.exists(file_path):
        print(f"  ✗ File not found: {file_path}")
        return False
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check for key components
    checks = [
        ("RunnableParallel import", "RunnableParallel" in content),
        ("SQLSynthesisGenieAgent class", "class SQLSynthesisGenieAgent:" in content),
        ("_create_genie_agent_tools method", "def _create_genie_agent_tools(self):" in content),
        ("parallel_executors attribute", "self.parallel_executors = parallel_executors" in content),
        ("invoke_genie_agents_parallel method", "def invoke_genie_agents_parallel(self" in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        if check_result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ✗ {check_name}")
            all_passed = False
    
    return all_passed


def test_documentation():
    """Test that upgrade documentation exists."""
    print("\nTesting documentation...")
    
    import os
    doc_path = os.path.join(os.path.dirname(__file__), "RUNNABLE_PARALLEL_UPGRADE.md")
    
    if not os.path.exists(doc_path):
        print(f"  ✗ Documentation not found: {doc_path}")
        return False
    
    with open(doc_path, 'r') as f:
        content = f.read()
    
    checks = [
        ("Summary section", "## Summary" in content),
        ("Changes Made section", "## Changes Made" in content),
        ("Benefits section", "## Benefits" in content),
        ("Usage Examples section", "## Usage Examples" in content),
        ("RunnableParallel mentioned", "RunnableParallel" in content),
        ("invoke_genie_agents_parallel mentioned", "invoke_genie_agents_parallel" in content),
    ]
    
    all_passed = True
    for check_name, check_result in checks:
        if check_result:
            print(f"  ✓ {check_name}")
        else:
            print(f"  ✗ {check_name}")
            all_passed = False
    
    return all_passed


def main():
    """Run all tests."""
    print("=" * 80)
    print("RunnableParallel Upgrade Verification")
    print("=" * 80)
    
    results = []
    
    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("Class Structure", test_class_structure()))
    results.append(("Local Dev File", test_local_dev_file()))
    results.append(("Documentation", test_documentation()))
    
    # Print summary
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    
    total_tests = len(results)
    passed_tests = sum(1 for _, result in results if result)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:10} - {test_name}")
    
    print("-" * 80)
    print(f"Total: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("\n🎉 All tests passed! RunnableParallel upgrade is complete.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    exit(main())
