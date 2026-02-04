#!/usr/bin/env python3
"""
Test script to verify clean streaming output formatting.
Tests the format_custom_event logic without requiring full agent setup.
"""

import json
import sys

# Ensure UTF-8 encoding for emojis
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def format_custom_event(custom_data: dict) -> str:
    """
    Format custom streaming events for user-friendly display.
    This is the improved version from Super_Agent_hybrid.py
    """
    event_type = custom_data.get("type", "unknown")
    
    formatters = {
        # Existing formatters
        "agent_thinking": lambda d: f"💭 {d['agent'].upper()}: {d['content']}",
        "agent_start": lambda d: f"🚀 Starting {d['agent']} agent for: {d.get('query', '')[:50]}...",
        "intent_detection": lambda d: f"🎯 Intent: {d['result']} - {d.get('reasoning', '')}",
        "clarity_analysis": lambda d: f"✓ Query {'clear' if d['clear'] else 'unclear'}: {d.get('reasoning', '')}",
        "vector_search_start": lambda d: f"🔍 Searching vector index: {d['index']}",
        "vector_search_results": lambda d: f"📊 Found {d['count']} relevant spaces: {[s.get('space_id', 'unknown') for s in d.get('spaces', [])]}",
        "plan_formulation": lambda d: f"📋 Execution plan: {d.get('strategy', 'unknown')} strategy",
        "uc_function_call": lambda d: f"🔧 Calling UC function: {d['function']}",
        "sql_generated": lambda d: f"📝 SQL generated: {d.get('query_preview', '')}...",
        "sql_validation_start": lambda d: f"✅ Validating SQL query...",
        "sql_execution_start": lambda d: f"⚡ Executing SQL query...",
        "sql_execution_complete": lambda d: f"✓ Query complete: {d.get('rows', 0)} rows, {len(d.get('columns', []))} columns",
        "summary_start": lambda d: f"📄 Generating summary...",
        "genie_agent_call": lambda d: f"🤖 Calling Genie agent for space: {d.get('space_id', 'unknown')}",
        
        # New clean streaming formatters
        "llm_streaming_start": lambda d: f"🤖 Streaming response from {d.get('agent', 'LLM')}...",
        "llm_token": lambda d: d.get('content', ''),  # Just the token content, no decoration
        "intent_detected": lambda d: f"\n🎯 Intent: {d.get('intent_type', 'unknown')} (confidence: {d.get('confidence', 0):.0%})",
        "meta_question_detected": lambda d: f"\n💡 Meta-question detected",
        "clarification_requested": lambda d: f"\n❓ Clarification needed: {d.get('reason', 'unknown')}",
        "clarification_skipped": lambda d: f"\n⏭️ Clarification skipped: {d.get('reason', 'unknown')}",
        "agent_step": lambda d: f"\n📍 {d.get('agent', 'agent').upper()}: {d.get('content', d.get('step', 'processing'))}",
        "agent_result": lambda d: f"\n✅ {d.get('agent', 'agent').upper()}: {d.get('result', 'completed')} - {d.get('content', '')}",
        "sql_synthesis_start": lambda d: f"\n🔧 Starting SQL synthesis via {d.get('route', 'unknown')} route for {len(d.get('spaces', []))} space(s)",
        "tools_available": lambda d: f"\n🛠️ Tools ready: {', '.join(d.get('tools', []))}",
        "summary_complete": lambda d: f"\n✅ Summary complete",
    }
    
    # Bulletproof JSON fallback handler
    def json_fallback(obj):
        """Final fallback for json.dumps() - converts anything to string."""
        try:
            return str(obj)
        except:
            return f"<{type(obj).__name__}>"
    
    # Fallback formatter now uses make_json_serializable with json_fallback
    formatter = formatters.get(
        event_type,
        lambda d: f"ℹ️ {event_type}: {json.dumps(d, indent=2, default=json_fallback)}"
    )
    
    try:
        return formatter(custom_data)
    except Exception as e:
        # Enhanced error handling with serialization fallback
        try:
            return f"ℹ️ {event_type}: {json.dumps(custom_data, indent=2, default=json_fallback)}"
        except Exception as e2:
            return f"ℹ️ {event_type}: {str(custom_data)}"


def is_streaming_token(text: str) -> bool:
    """Check if text is a streaming token vs structured event."""
    emoji_prefixes = ("💭", "🚀", "🎯", "✓", "🔍", "📊", "📋", "🔧", "📝", "✅", "⚡", "📄", "🤖", "💡", "❓", "⏭️", "📍", "🛠️")
    return (
        not text.startswith(emoji_prefixes)
        and not text.startswith("\n")
        and len(text) < 100
    )


def test_formatting():
    """Test the formatting improvements."""
    print("\n" + "="*80)
    print("Testing Clean Streaming Formatting")
    print("="*80 + "\n")
    
    # Test cases: Before vs After
    test_cases = [
        {
            "name": "LLM Token Event",
            "event": {"type": "llm_token", "content": "You have"},
            "expected": "You have",  # Just content, no JSON
        },
        {
            "name": "LLM Streaming Start",
            "event": {"type": "llm_streaming_start", "agent": "unified_intent_context_clarification"},
            "expected": "🤖 Streaming response from unified_intent_context_clarification...",
        },
        {
            "name": "Intent Detected",
            "event": {"type": "intent_detected", "intent_type": "new_question", "confidence": 0.92},
            "expected": "\n🎯 Intent: new_question (confidence: 92%)",
        },
        {
            "name": "Meta Question Detected",
            "event": {"type": "meta_question_detected"},
            "expected": "\n💡 Meta-question detected",
        },
        {
            "name": "Agent Start",
            "event": {"type": "agent_start", "agent": "unified_intent_context_clarification", "query": "what I can do here"},
            "expected": "🚀 Starting unified_intent_context_clarification agent for: what I can do here...",
        },
        {
            "name": "SQL Synthesis Start",
            "event": {"type": "sql_synthesis_start", "route": "table", "spaces": ["HealthVerityClaims"]},
            "expected": "\n🔧 Starting SQL synthesis via table route for 1 space(s)",
        },
        {
            "name": "Tools Available",
            "event": {"type": "tools_available", "tools": ["get_space_summary", "get_table_overview"]},
            "expected": "\n🛠️ Tools ready: get_space_summary, get_table_overview",
        },
    ]
    
    print("📋 Testing Event Formatters:\n")
    all_passed = True
    
    for i, test in enumerate(test_cases, 1):
        result = format_custom_event(test["event"])
        passed = result == test["expected"]
        status = "✅ PASS" if passed else "❌ FAIL"
        
        print(f"{i}. {test['name']}: {status}")
        if not passed:
            print(f"   Expected: {repr(test['expected'])}")
            print(f"   Got:      {repr(result)}")
            all_passed = False
        else:
            print(f"   Output:   {result}")
        print()
    
    return all_passed


def test_token_detection():
    """Test token vs event detection logic."""
    print("\n" + "─"*80)
    print("Testing Token Detection Logic:\n")
    
    test_cases = [
        ("You have", True, "Simple token"),
        (" access to", True, "Token with space"),
        ("🚀 Starting agent...", False, "Structured event with emoji"),
        ("\n🎯 Intent detected", False, "Event starting with newline"),
        ("This is a very long token that exceeds the 100 character limit and should be treated as an event because it is way too long to be a single streaming token from an LLM", False, "Long text"),
        ("json", True, "Short token"),
        ("💡 Meta-question", False, "Event with emoji"),
    ]
    
    all_passed = True
    for text, expected_is_token, description in test_cases:
        result = is_streaming_token(text)
        passed = result == expected_is_token
        status = "✅" if passed else "❌"
        
        print(f"{status} {description}")
        print(f"   Text: {repr(text[:50])}")
        print(f"   Is Token: {result} (expected: {expected_is_token})")
        print()
        
        if not passed:
            all_passed = False
    
    return all_passed


def simulate_streaming():
    """Simulate clean streaming output."""
    print("\n" + "─"*80)
    print("Simulating Clean Streaming Output:\n")
    
    # Simulate events as they would come from the agent
    events = [
        {"type": "agent_start", "agent": "unified_intent_context_clarification", "query": "what I can do here"},
        {"type": "llm_streaming_start", "agent": "unified_intent_context_clarification"},
        {"type": "llm_token", "content": "```json\n"},
        {"type": "llm_token", "content": "{\n"},
        {"type": "llm_token", "content": "  \"is_meta_question\": true,\n"},
        {"type": "llm_token", "content": "  \"meta_answer\": \"You have access to three healthcare analytics spaces\"\n"},
        {"type": "llm_token", "content": "}\n"},
        {"type": "llm_token", "content": "```"},
        {"type": "intent_detected", "intent_type": "new_question", "confidence": 0.92},
        {"type": "meta_question_detected"},
    ]
    
    print("Simulated Agent Output:\n")
    
    for event in events:
        formatted = format_custom_event(event)
        
        # Apply token detection logic
        if is_streaming_token(formatted):
            # Stream token inline
            print(formatted, end='', flush=True)
        else:
            # Structured event on new line
            print(formatted)
    
    print("\n\n" + "─"*80)
    print("✨ Notice: Tokens stream smoothly, events appear on separate lines!")
    print("─"*80 + "\n")


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("🧪 Streaming Formatting Test Suite")
    print("="*80)
    
    # Test 1: Formatting
    formatting_passed = test_formatting()
    
    # Test 2: Token Detection
    detection_passed = test_token_detection()
    
    # Test 3: Simulation
    simulate_streaming()
    
    # Summary
    print("\n" + "="*80)
    print("📊 Test Summary:")
    print("="*80)
    print(f"  Event Formatting: {'✅ PASSED' if formatting_passed else '❌ FAILED'}")
    print(f"  Token Detection:  {'✅ PASSED' if detection_passed else '❌ FAILED'}")
    print(f"  Simulation:       ✅ COMPLETE")
    print("="*80)
    
    if formatting_passed and detection_passed:
        print("\n🎉 All tests passed! Streaming improvements are working correctly.")
        print("   Ready for Databricks deployment! 🚀\n")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the output above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
