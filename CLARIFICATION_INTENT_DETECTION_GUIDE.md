# Clarification Intent Detection - Implementation Guide

## Overview

The Super Agent now uses **LLM-based intent detection** to intelligently determine whether a user query is a new question or a follow-up. This allows clarification to happen once per unique question while maintaining conversation continuity.

## How It Works

### Before (Thread-Level Tracking)
- Clarification count: **Once per entire thread**
- Problem: New questions in same thread couldn't get clarification

### After (Intent-Based Tracking)
- Clarification count: **Once per new question** (resets intelligently)
- Solution: LLM detects new vs follow-up queries

## Implementation Details

### 1. New State Field

Added to `AgentState`:
```python
last_clarified_query: Optional[str]  # Track last query that received clarification
```

### 2. Intent Detection Function

New function `is_new_question()`:
- Analyzes conversation history
- Uses LLM to compare current query with last clarified query
- Returns `True` for new questions, `False` for follow-ups

### 3. Clarification Node Enhancement

The `clarification_node()` now:
1. Checks if `clarification_count > 0`
2. Calls `is_new_question()` to detect intent
3. Resets count to 0 for new questions
4. Keeps count for follow-ups

## Usage Examples

### Example 1: New Question After Clarification

```python
# Turn 1: Vague query
state1 = invoke_super_agent_hybrid("Show me the data", thread_id="session_001")
# Output: "I need clarification: What type of data would you like to see?"

# Turn 2: User clarifies
state2 = invoke_super_agent_hybrid("Show patient count by age group", thread_id="session_001")
# Output: Query executes successfully

# Turn 3: NEW QUESTION - different topic
state3 = invoke_super_agent_hybrid("Show medication costs by insurance type", thread_id="session_001")
# Intent Detection: NEW QUESTION
# Output: "I need clarification: Which cost metric would you like..."
```

### Example 2: Follow-Up After Clarification

```python
# Turn 1: Vague query
state1 = invoke_super_agent_hybrid("Show patient data", thread_id="session_002")
# Output: "I need clarification: What patient data metrics?"

# Turn 2: User clarifies
state2 = invoke_super_agent_hybrid("Show total patient count", thread_id="session_002")
# Output: Query executes, returns count

# Turn 3: FOLLOW-UP - refinement of same topic
state3 = invoke_super_agent_hybrid("Can you break that down by gender?", thread_id="session_002")
# Intent Detection: FOLLOW-UP
# Output: Query executes WITHOUT re-clarification (uses context from Turn 2)
```

### Example 3: Refinement Pattern

```python
# Turn 1: Clear initial query
state1 = invoke_super_agent_hybrid("Show active member count", thread_id="session_003")
# Output: Returns 50,000 active members

# Turn 2: Refinement
state2 = invoke_super_agent_hybrid("Same but by state", thread_id="session_003")
# Intent Detection: FOLLOW-UP
# Output: Breaks down by state without clarification

# Turn 3: Another refinement
state3 = invoke_super_agent_hybrid("Now show only California over age 65", thread_id="session_003")
# Intent Detection: FOLLOW-UP
# Output: Further refines without clarification
```

## Intent Detection Logic

The LLM evaluates queries using these criteria:

### Classified as NEW QUESTION:
- ✅ Different data domain (patients → medications)
- ✅ Different topic (claims → providers)
- ✅ Unrelated question (diabetes data → insurance metrics)
- ✅ Complete change of subject

### Classified as FOLLOW-UP:
- ✅ Refinement ("break down by age")
- ✅ Drill-down ("show only California")
- ✅ Related query ("what about inactive members?")
- ✅ Continuation ("same but with...")

## Benefits

1. **Intelligent Context Awareness**: LLM naturally understands question relationships
2. **No Manual Tracking**: No need for complex hash-based tracking systems
3. **User-Friendly**: Users can ask multiple distinct questions in one session
4. **Prevents Over-Clarification**: Follow-ups and refinements don't trigger re-clarification
5. **Minimal Code**: Only ~40 lines of new code added

## Debug Output

When intent detection runs, you'll see:

```
🔄 Checking if query is new question or follow-up...
   Intent Detection: NEW QUESTION
✓ New question detected - resetting clarification count to 0
```

Or:

```
🔄 Checking if query is new question or follow-up...
   Intent Detection: FOLLOW-UP
✓ Follow-up detected - keeping clarification count at 1
```

## Edge Cases Handled

1. **No Previous Clarification**: Always treated as new question
2. **Intent Detection Failure**: Defaults to new question (safe fallback)
3. **Empty Message History**: Skips intent detection
4. **First Query in Thread**: No intent detection needed

## Testing Scenarios

### Test 1: New Question Triggers Clarification
```python
thread = "test_001"
invoke_super_agent_hybrid("Show patient data", thread_id=thread)  # Clarification needed
invoke_super_agent_hybrid("Show patient count by age", thread_id=thread)  # Answer
invoke_super_agent_hybrid("Show medication costs", thread_id=thread)  # NEW - should clarify
```

### Test 2: Follow-Up Skips Clarification
```python
thread = "test_002"
invoke_super_agent_hybrid("Show data", thread_id=thread)  # Clarification needed
invoke_super_agent_hybrid("Show active members", thread_id=thread)  # Answer
invoke_super_agent_hybrid("Break that down by state", thread_id=thread)  # FOLLOW-UP - no clarification
```

### Test 3: Mixed Pattern
```python
thread = "test_003"
invoke_super_agent_hybrid("Show claims", thread_id=thread)  # Vague - clarification
invoke_super_agent_hybrid("Show claim totals by year", thread_id=thread)  # Answer
invoke_super_agent_hybrid("What about 2024 only?", thread_id=thread)  # FOLLOW-UP - no clarification
invoke_super_agent_hybrid("Show provider metrics", thread_id=thread)  # NEW - should clarify if vague
```

## Configuration

The intent detection uses the same LLM endpoint as clarification:
```python
LLM_ENDPOINT_CLARIFICATION = config.llm.endpoint_name
```

No additional configuration needed!

## Backward Compatibility

- `clarification_count` field still exists and works
- Existing saved states are compatible
- Old behavior: once per thread
- New behavior: once per new question (with intelligent reset)

## Summary

This implementation provides a **simple, robust, and user-friendly** way to handle clarification in multi-turn conversations. It leverages the LLM's natural language understanding to make intelligent decisions about when to ask for clarification, resulting in a more conversational and helpful experience.
