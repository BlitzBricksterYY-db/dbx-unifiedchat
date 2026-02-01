"""
Test script for topic-aware context isolation.

This tests the new get_topic_root() and get_current_topic_turns() functions
to ensure strict topic isolation between different questions in the same thread.

Test Scenarios:
1. Question 1 → refine → refine → Question 2 → refine
2. Long refinement chain (10+ turns)
"""

import sys
from pathlib import Path

# Add kumc_poc to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from kumc_poc.conversation_models import (
    ConversationTurn,
    create_conversation_turn,
    get_topic_root,
    get_current_topic_turns
)


def print_separator(title=""):
    """Print a formatted separator."""
    if title:
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}\n")
    else:
        print(f"\n{'-'*80}\n")


def test_scenario_1_topic_isolation():
    """
    Test Scenario 1: Q1 → refine → refine → Q2 → refine
    
    Expected: When processing refinement of Q2, context should only include Q2 and its refinement.
    """
    print_separator("TEST 1: Topic Isolation (Q1 → refine → Q2 → refine)")
    
    # Build turn history
    turn_history = []
    
    # Turn 1: Question 1
    turn1 = create_conversation_turn(
        query="Show me patient counts by state",
        intent_type="new_question",
        context_summary=None
    )
    turn_history.append(turn1)
    print(f"Turn 1 [new_question]: {turn1['query']}")
    print(f"  Turn ID: {turn1['turn_id']}")
    
    # Turn 2: Refinement of Question 1
    turn2 = create_conversation_turn(
        query="Only patients age 50 and above",
        intent_type="refinement",
        parent_turn_id=turn1['turn_id'],
        context_summary="Refining patient counts to filter by age"
    )
    turn_history.append(turn2)
    print(f"Turn 2 [refinement]: {turn2['query']}")
    print(f"  Parent: {turn2['parent_turn_id']}")
    
    # Turn 3: Another refinement of Question 1
    turn3 = create_conversation_turn(
        query="Break down by gender as well",
        intent_type="refinement",
        parent_turn_id=turn1['turn_id'],
        context_summary="Adding gender breakdown to age-filtered patient counts"
    )
    turn_history.append(turn3)
    print(f"Turn 3 [refinement]: {turn3['query']}")
    print(f"  Parent: {turn3['parent_turn_id']}")
    
    # Turn 4: Question 2 (NEW TOPIC)
    turn4 = create_conversation_turn(
        query="Show me medication costs by drug type",
        intent_type="new_question",
        context_summary=None
    )
    turn_history.append(turn4)
    print(f"Turn 4 [new_question]: {turn4['query']} ← NEW TOPIC")
    print(f"  Turn ID: {turn4['turn_id']}")
    
    # Turn 5: Refinement of Question 2
    turn5 = create_conversation_turn(
        query="Filter for diabetes medications only",
        intent_type="refinement",
        parent_turn_id=turn4['turn_id'],
        context_summary="Refining medication costs to diabetes drugs"
    )
    turn_history.append(turn5)
    print(f"Turn 5 [refinement]: {turn5['query']}")
    print(f"  Parent: {turn5['parent_turn_id']}")
    
    print_separator()
    
    # Test: Get topic root for Turn 5
    print("TEST: get_topic_root(turn5)")
    root = get_topic_root(turn_history, turn5)
    print(f"  Root Turn ID: {root['turn_id']}")
    print(f"  Root Query: {root['query']}")
    
    if root['turn_id'] == turn4['turn_id']:
        print("  ✅ PASS: Root is Turn 4 (Question 2)")
    else:
        print(f"  ❌ FAIL: Expected Turn 4, got {root['turn_id']}")
    
    print_separator()
    
    # Test: Get current topic turns for Turn 5
    print("TEST: get_current_topic_turns(turn5, max_recent=3)")
    topic_turns = get_current_topic_turns(turn_history, turn5, max_recent=3)
    
    print(f"  Topic turns count: {len(topic_turns)}")
    for i, turn in enumerate(topic_turns, 1):
        print(f"  {i}. [{turn['intent_type']}] {turn['query']}")
    
    # Verify strict isolation
    turn_ids_in_context = [t['turn_id'] for t in topic_turns]
    
    has_turn1 = turn1['turn_id'] in turn_ids_in_context
    has_turn2 = turn2['turn_id'] in turn_ids_in_context
    has_turn3 = turn3['turn_id'] in turn_ids_in_context
    has_turn4 = turn4['turn_id'] in turn_ids_in_context
    has_turn5 = turn5['turn_id'] in turn_ids_in_context
    
    print("\n  Verification:")
    print(f"    Turn 1 (Q1) in context: {has_turn1} {'❌ FAIL' if has_turn1 else '✅ PASS (excluded)'}")
    print(f"    Turn 2 (Q1 refine) in context: {has_turn2} {'❌ FAIL' if has_turn2 else '✅ PASS (excluded)'}")
    print(f"    Turn 3 (Q1 refine) in context: {has_turn3} {'❌ FAIL' if has_turn3 else '✅ PASS (excluded)'}")
    print(f"    Turn 4 (Q2 root) in context: {has_turn4} {'✅ PASS (included)' if has_turn4 else '❌ FAIL'}")
    print(f"    Turn 5 (Q2 refine) in context: {has_turn5} {'✅ PASS (included)' if has_turn5 else '❌ FAIL'}")
    
    if not has_turn1 and not has_turn2 and not has_turn3 and has_turn4 and has_turn5:
        print("\n  ✅ TEST PASSED: Strict topic isolation maintained!")
        return True
    else:
        print("\n  ❌ TEST FAILED: Topic isolation broken!")
        return False


def test_scenario_2_long_chain():
    """
    Test Scenario 2: Long refinement chain (10+ turns)
    
    Expected: Should return root + last 3 refinements (configurable with max_recent).
    """
    print_separator("TEST 2: Long Refinement Chain (10+ turns)")
    
    # Build turn history with 10 refinements
    turn_history = []
    
    # Root question
    root = create_conversation_turn(
        query="Show me patient demographics",
        intent_type="new_question",
        context_summary=None
    )
    turn_history.append(root)
    print(f"Turn 1 [new_question]: {root['query']}")
    
    # Add 10 refinements
    for i in range(2, 12):
        refinement = create_conversation_turn(
            query=f"Refinement {i-1}: Add filter/grouping #{i-1}",
            intent_type="refinement",
            parent_turn_id=root['turn_id'],
            context_summary=f"Refining query with additional criteria #{i-1}"
        )
        turn_history.append(refinement)
        print(f"Turn {i} [refinement]: {refinement['query']}")
    
    print_separator()
    
    # Test with max_recent=3
    print("TEST: get_current_topic_turns(last_turn, max_recent=3)")
    last_turn = turn_history[-1]
    topic_turns = get_current_topic_turns(turn_history, last_turn, max_recent=3)
    
    print(f"  Total turns in history: {len(turn_history)}")
    print(f"  Topic turns returned: {len(topic_turns)}")
    print(f"\n  Turns in context:")
    for i, turn in enumerate(topic_turns, 1):
        query_short = turn['query'][:50]
        print(f"    {i}. {query_short}")
    
    # Verify: Should be root + last 3 refinements = 4 turns
    expected_count = 4  # root + 3 recent
    
    if len(topic_turns) == expected_count:
        print(f"\n  ✅ PASS: Got {expected_count} turns (root + 3 recent)")
        
        # Verify first is root
        if topic_turns[0]['turn_id'] == root['turn_id']:
            print(f"  ✅ PASS: First turn is root question")
            
            # Verify last 3 are the most recent refinements
            last_3_expected = turn_history[-3:]
            last_3_actual = topic_turns[1:]
            
            if [t['turn_id'] for t in last_3_actual] == [t['turn_id'] for t in last_3_expected]:
                print(f"  ✅ PASS: Last 3 turns are most recent refinements")
                print("\n  ✅ TEST PASSED: Long chain handled correctly!")
                return True
            else:
                print(f"  ❌ FAIL: Last 3 turns don't match expected")
                return False
        else:
            print(f"  ❌ FAIL: First turn is not root")
            return False
    else:
        print(f"  ❌ FAIL: Expected {expected_count} turns, got {len(topic_turns)}")
        return False


def test_scenario_3_clarification_response():
    """
    Test Scenario 3: Clarification response should stay in same topic
    
    Expected: Clarification response should link back to the question that triggered it.
    """
    print_separator("TEST 3: Clarification Response Topic Association")
    
    turn_history = []
    
    # Turn 1: Question with ambiguity
    turn1 = create_conversation_turn(
        query="Show me patient counts",
        intent_type="new_question",
        context_summary=None,
        triggered_clarification=True
    )
    turn_history.append(turn1)
    print(f"Turn 1 [new_question, triggered clarification]: {turn1['query']}")
    
    # Turn 2: Clarification response
    turn2 = create_conversation_turn(
        query="By state",
        intent_type="clarification_response",
        parent_turn_id=turn1['turn_id'],
        context_summary="User clarified: group patient counts by state"
    )
    turn_history.append(turn2)
    print(f"Turn 2 [clarification_response]: {turn2['query']}")
    print(f"  Parent: {turn2['parent_turn_id']}")
    
    print_separator()
    
    # Test: Get topic root for clarification response
    print("TEST: get_topic_root(turn2)")
    root = get_topic_root(turn_history, turn2)
    print(f"  Root Turn ID: {root['turn_id']}")
    print(f"  Root Query: {root['query']}")
    
    if root['turn_id'] == turn1['turn_id']:
        print("  ✅ PASS: Clarification response correctly links to original question")
        return True
    else:
        print(f"  ❌ FAIL: Expected Turn 1, got different root")
        return False


def run_all_tests():
    """Run all test scenarios."""
    print_separator("TOPIC-AWARE CONTEXT ISOLATION TESTS")
    
    results = []
    
    # Run tests
    results.append(("Topic Isolation", test_scenario_1_topic_isolation()))
    results.append(("Long Chain", test_scenario_2_long_chain()))
    results.append(("Clarification Response", test_scenario_3_clarification_response()))
    
    # Summary
    print_separator("TEST SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  🎉 ALL TESTS PASSED! Topic isolation working correctly.")
        return True
    else:
        print(f"\n  ⚠️  {total - passed} test(s) failed.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
