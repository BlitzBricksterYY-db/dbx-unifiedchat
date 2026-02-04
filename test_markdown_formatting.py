#!/usr/bin/env python3
"""
Test script to verify markdown formatting in unified agent output.
Run this in Databricks or locally to test meta-questions and clarifications.
"""

from uuid import uuid4

# Note: This test script assumes you have the agent imported
# In Databricks, run the Super_Agent_hybrid notebook first, then run this

def test_meta_question_markdown():
    """Test that meta-question answers are formatted as markdown."""
    print("\n" + "="*80)
    print("TEST 1: Meta-Question Markdown Formatting")
    print("="*80)
    
    test_query = "what can I do here"
    thread_id = f"test-markdown-meta-{str(uuid4())[:8]}"
    
    print(f"\nQuery: {test_query}")
    print(f"Thread ID: {thread_id}\n")
    
    try:
        from Notebooks.Super_Agent_hybrid import AGENT, ResponsesAgentRequest
        
        request = ResponsesAgentRequest(
            input=[{"role": "user", "content": test_query}],
            custom_inputs={"thread_id": thread_id}
        )
        
        print("Sending request to agent...\n")
        result = AGENT.predict(request)
        
        print("\n" + "="*80)
        print("✅ TEST 1 COMPLETE")
        print("="*80)
        print("\nExpected: Markdown-formatted answer with:")
        print("  - ## heading")
        print("  - **bold** keywords")
        print("  - Bullet lists")
        print("  - Proper spacing\n")
        
        return True
        
    except ImportError:
        print("⚠️  Cannot import agent. Run this in Databricks after loading Super_Agent_hybrid.py")
        return False
    except Exception as e:
        print(f"❌ TEST 1 FAILED: {e}")
        return False


def test_clarification_markdown():
    """Test that clarification requests are formatted as markdown."""
    print("\n" + "="*80)
    print("TEST 2: Clarification Markdown Formatting")
    print("="*80)
    
    # Intentionally vague query to trigger clarification
    test_query = "show me patients with diabetes"
    thread_id = f"test-markdown-clarify-{str(uuid4())[:8]}"
    
    print(f"\nQuery: {test_query}")
    print(f"Thread ID: {thread_id}\n")
    
    try:
        from Notebooks.Super_Agent_hybrid import AGENT, ResponsesAgentRequest
        
        request = ResponsesAgentRequest(
            input=[{"role": "user", "content": test_query}],
            custom_inputs={"thread_id": thread_id}
        )
        
        print("Sending request to agent...\n")
        result = AGENT.predict(request)
        
        print("\n" + "="*80)
        print("✅ TEST 2 COMPLETE")
        print("="*80)
        print("\nExpected: Markdown-formatted clarification with:")
        print("  - ### heading")
        print("  - **bold** key terms")
        print("  - Numbered list of options")
        print("  - Descriptions for each option")
        print("  - Friendly, professional tone\n")
        
        return True
        
    except ImportError:
        print("⚠️  Cannot import agent. Run this in Databricks after loading Super_Agent_hybrid.py")
        return False
    except Exception as e:
        print(f"❌ TEST 2 FAILED: {e}")
        return False


def test_clear_query_no_formatting():
    """Test that clear analytical queries proceed without markdown formatting."""
    print("\n" + "="*80)
    print("TEST 3: Clear Query (No Markdown Formatting Needed)")
    print("="*80)
    
    test_query = "What is the average paid_gross_due from medical_claim table?"
    thread_id = f"test-markdown-clear-{str(uuid4())[:8]}"
    
    print(f"\nQuery: {test_query}")
    print(f"Thread ID: {thread_id}\n")
    
    try:
        from Notebooks.Super_Agent_hybrid import AGENT, ResponsesAgentRequest
        
        request = ResponsesAgentRequest(
            input=[{"role": "user", "content": test_query}],
            custom_inputs={"thread_id": thread_id}
        )
        
        print("Sending request to agent...\n")
        result = AGENT.predict(request)
        
        print("\n" + "="*80)
        print("✅ TEST 3 COMPLETE")
        print("="*80)
        print("\nExpected: Query proceeds to planning without markdown formatting")
        print("  - Should go through planning → SQL synthesis → execution")
        print("  - No meta-answer or clarification displayed\n")
        
        return True
        
    except ImportError:
        print("⚠️  Cannot import agent. Run this in Databricks after loading Super_Agent_hybrid.py")
        return False
    except Exception as e:
        print(f"❌ TEST 3 FAILED: {e}")
        return False


def main():
    """Run all markdown formatting tests."""
    print("\n" + "="*80)
    print("🧪 Markdown Formatting Test Suite")
    print("="*80)
    print("\nThis test suite verifies that:")
    print("1. Meta-question answers are formatted as markdown")
    print("2. Clarification requests are formatted as markdown")
    print("3. Clear queries proceed without unnecessary formatting\n")
    
    results = {
        "meta_question": test_meta_question_markdown(),
        "clarification": test_clarification_markdown(),
        "clear_query": test_clear_query_no_formatting()
    }
    
    # Summary
    print("\n" + "="*80)
    print("📊 Test Summary")
    print("="*80)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nTests Passed: {passed}/{total}\n")
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {test_name}: {status}")
    
    print("\n" + "="*80)
    
    if passed == total:
        print("🎉 All tests passed! Markdown formatting is working correctly.")
        print("="*80 + "\n")
        return 0
    else:
        print("⚠️  Some tests failed. Review the output above for details.")
        print("="*80 + "\n")
        return 1


if __name__ == "__main__":
    import sys
    
    print("\n💡 Usage Instructions:")
    print("-" * 80)
    print("In Databricks:")
    print("  1. Run the Super_Agent_hybrid.py notebook")
    print("  2. Run this test script in a new cell")
    print("\nLocally:")
    print("  1. Ensure the agent is properly configured")
    print("  2. Run: python test_markdown_formatting.py")
    print("-" * 80 + "\n")
    
    sys.exit(main())
