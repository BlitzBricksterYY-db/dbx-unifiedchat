#!/usr/bin/env python3
"""
Test script to verify clean streaming output.
Run this in Databricks or locally to see the improved streaming display.
"""

from uuid import uuid4
from kumc_poc.responses_agent import ResponsesAgent, ResponsesAgentRequest

def test_clean_streaming():
    """Test streaming with clean, human-readable output."""
    
    print("\n" + "="*80)
    print("Testing Clean Streaming Display")
    print("="*80 + "\n")
    
    # Initialize agent
    agent = ResponsesAgent()
    
    # Test queries
    test_queries = [
        "what I can do here",
        "Show me patients with diabetes",
        "What is the average cost of medical claims?"
    ]
    
    for idx, query in enumerate(test_queries, 1):
        print(f"\n{'─'*80}")
        print(f"Test {idx}/{len(test_queries)}: {query}")
        print('─'*80 + "\n")
        
        # Create request
        thread_id = f"test-clean-stream-{str(uuid4())[:8]}"
        request = ResponsesAgentRequest(
            input=[{"role": "user", "content": query}],
            custom_inputs={"thread_id": thread_id}
        )
        
        # Stream events
        token_count = 0
        event_count = 0
        
        for event in agent.predict_stream(request):
            if event.type == "response.output_item.done":
                item = event.item
                if hasattr(item, 'text') and item.text:
                    text = item.text
                    
                    # Detect streaming token vs structured event
                    is_token = (
                        not text.startswith(("💭", "🚀", "🎯", "✓", "🔍", "📊", "📋", "🔧", "📝", "✅", "⚡", "📄", "🤖", "💡", "❓", "⏭️", "📍", "🛠️"))
                        and not text.startswith("\n")
                        and len(text) < 100
                    )
                    
                    if is_token:
                        # Stream token without newline for smooth real-time display
                        print(text, end='', flush=True)
                        token_count += 1
                    else:
                        # Structured event on new line
                        print(f"\n{text}")
                        event_count += 1
                        
                elif hasattr(item, 'function_call'):
                    print(f"\n🛠️ Function call: {item.function_call.name}")
                    event_count += 1
        
        # Summary
        print("\n\n" + "─"*80)
        print(f"Test {idx} Complete:")
        print(f"  - Streamed tokens: {token_count}")
        print(f"  - Structured events: {event_count}")
        print("─"*80 + "\n")
    
    print("\n" + "="*80)
    print("✅ All streaming tests completed successfully!")
    print("="*80 + "\n")


def test_streaming_visualization():
    """Visual demonstration of clean streaming."""
    import time
    
    print("\n" + "="*80)
    print("Streaming Visualization Demo")
    print("="*80 + "\n")
    
    # Simulate clean streaming
    print("🚀 Starting unified_intent_context_clarification agent...\n")
    time.sleep(0.3)
    
    print("🤖 Streaming response from unified_intent_context_clarification...\n")
    time.sleep(0.3)
    
    # Simulate token-by-token streaming
    response = """You have access to three healthcare analytics spaces with comprehensive claims data:

1. **HealthVerityClaims** - Medical and pharmacy claims analysis
2. **HealthVerityProcedureDiagnosis** - Diagnosis and procedure-level analysis  
3. **HealthVerityProviderEnrollment** - Patient enrollment patterns

What specific healthcare analytics question would you like to explore?"""
    
    for char in response:
        print(char, end='', flush=True)
        time.sleep(0.01)  # Simulate LLM streaming speed
    
    print("\n")
    time.sleep(0.3)
    
    # Structured events
    print("\n🎯 Intent: new_question (confidence: 92%)")
    print("💡 Meta-question detected")
    print("✅ Query analysis complete\n")
    
    print("="*80)
    print("✨ Notice the smooth, readable output!")
    print("="*80 + "\n")


if __name__ == "__main__":
    import sys
    
    # Check if running in Databricks
    try:
        import pyspark
        is_databricks = True
    except ImportError:
        is_databricks = False
    
    if is_databricks:
        print("🎯 Running in Databricks environment")
    else:
        print("🖥️ Running in local environment")
    
    # Run visualization demo first
    test_streaming_visualization()
    
    # Ask user if they want to run full test
    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        test_clean_streaming()
    else:
        print("\n💡 Tip: Run with --full flag to test actual agent streaming:")
        print("   python test_clean_streaming.py --full\n")
