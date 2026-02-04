# Streaming UI Implementation Guide

## Overview

This guide shows how to implement clean, human-readable streaming in Databricks Playground or any web UI, based on the improvements made to the agent's event formatting.

## Key Concepts

### Event Types

The agent emits two types of events:

1. **Streaming Tokens** - LLM response content, streamed word-by-word
2. **Structured Events** - Status updates, milestones, metadata (with emoji prefixes)

### Clean Display Strategy

- **Tokens:** Display inline, no newlines, accumulate continuously
- **Structured Events:** Display on separate lines with formatting

## Implementation Examples

### 1. Python Console (Databricks Notebook)

```python
from kumc_poc.responses_agent import ResponsesAgent, ResponsesAgentRequest

agent = ResponsesAgent()
request = ResponsesAgentRequest(
    input=[{"role": "user", "content": "What can I do here?"}],
    custom_inputs={"thread_id": "user-session-123"}
)

# Stream events with smart handling
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
                # Stream without newline
                print(text, end='', flush=True)
            else:
                # Structured event on new line
                print(f"\n{text}")
```

### 2. Web UI (JavaScript/TypeScript)

```typescript
interface StreamEvent {
  type: string;
  item?: {
    text?: string;
    function_call?: {
      name: string;
      arguments?: string;
    };
  };
}

async function streamAgentResponse(query: string) {
  const response = await fetch('/api/agent/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      input: [{ role: 'user', content: query }],
      custom_inputs: { thread_id: 'user-session-123' }
    })
  });

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  
  let streamingContainer = document.getElementById('streaming-output');
  let currentTokenSpan: HTMLSpanElement | null = null;

  while (true) {
    const { done, value } = await reader!.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const events: StreamEvent[] = chunk.split('\n')
      .filter(line => line.trim())
      .map(line => JSON.parse(line));

    for (const event of events) {
      if (event.type === 'response.output_item.done' && event.item?.text) {
        const text = event.item.text;
        const isToken = !text.match(/^[💭🚀🎯✓🔍📊📋🔧📝✅⚡📄🤖💡❓⏭️📍🛠️\n]/) && text.length < 100;

        if (isToken) {
          // Accumulate tokens in same element
          if (!currentTokenSpan) {
            currentTokenSpan = document.createElement('span');
            currentTokenSpan.className = 'streaming-token';
            streamingContainer?.appendChild(currentTokenSpan);
          }
          currentTokenSpan.textContent += text;
        } else {
          // Structured event on new line
          currentTokenSpan = null;
          const eventDiv = document.createElement('div');
          eventDiv.className = 'structured-event';
          eventDiv.textContent = text;
          streamingContainer?.appendChild(eventDiv);
        }
      }
    }
  }
}
```

### 3. React Component

```tsx
import React, { useState, useEffect, useRef } from 'react';

interface StreamingChatProps {
  query: string;
  threadId: string;
}

const StreamingChat: React.FC<StreamingChatProps> = ({ query, threadId }) => {
  const [events, setEvents] = useState<string[]>([]);
  const [currentToken, setCurrentToken] = useState<string>('');
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const streamResponse = async () => {
      const response = await fetch('/api/agent/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input: [{ role: 'user', content: query }],
          custom_inputs: { thread_id: threadId }
        })
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader!.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n').filter(line => line.trim());

        for (const line of lines) {
          try {
            const event = JSON.parse(line);
            if (event.type === 'response.output_item.done' && event.item?.text) {
              const text = event.item.text;
              const isToken = !text.match(/^[💭🚀🎯✓🔍📊📋🔧📝✅⚡📄🤖💡❓⏭️📍🛠️\n]/) && text.length < 100;

              if (isToken) {
                setCurrentToken(prev => prev + text);
              } else {
                // Flush current tokens and add structured event
                if (currentToken) {
                  setEvents(prev => [...prev, currentToken]);
                  setCurrentToken('');
                }
                setEvents(prev => [...prev, text]);
              }
            }
          } catch (e) {
            console.error('Failed to parse event:', e);
          }
        }
      }

      // Flush remaining tokens
      if (currentToken) {
        setEvents(prev => [...prev, currentToken]);
        setCurrentToken('');
      }
    };

    streamResponse();
  }, [query, threadId]);

  useEffect(() => {
    // Auto-scroll to bottom
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [events, currentToken]);

  return (
    <div ref={streamRef} className="streaming-container">
      {events.map((text, idx) => (
        <div 
          key={idx} 
          className={text.match(/^[💭🚀🎯✓🔍📊📋🔧📝✅⚡📄🤖💡❓⏭️📍🛠️]/) ? 'structured-event' : 'token-content'}
        >
          {text}
        </div>
      ))}
      {currentToken && (
        <span className="token-content streaming">{currentToken}</span>
      )}
    </div>
  );
};
```

### 4. CSS Styling

```css
.streaming-container {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  padding: 16px;
  background: #f8f9fa;
  border-radius: 8px;
  max-height: 600px;
  overflow-y: auto;
}

.structured-event {
  margin: 8px 0;
  padding: 4px 0;
  color: #1a73e8;
  font-weight: 500;
  line-height: 1.5;
}

.token-content {
  color: #202124;
  line-height: 1.6;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.streaming::after {
  content: '▊';
  animation: blink 1s infinite;
  color: #1a73e8;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* Emoji styling */
.structured-event {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.structured-event::before {
  font-size: 1.2em;
}
```

## Databricks Playground Integration

### Option 1: Model Serving Endpoint

Deploy the agent as a model serving endpoint that supports streaming:

```python
# In Databricks notebook
import mlflow

# Log model with streaming support
with mlflow.start_run():
    mlflow.pyfunc.log_model(
        artifact_path="agent_model",
        python_model=agent,
        pip_requirements=["langchain", "langgraph", "databricks-sdk"],
        signature=mlflow.models.infer_signature(
            model_input={"query": "test"},
            model_output={"response": "test"}
        )
    )

# Register and deploy
model_uri = f"runs:/{mlflow.active_run().info.run_id}/agent_model"
registered_model = mlflow.register_model(model_uri, "healthcare_agent")

# Enable streaming in serving endpoint config
```

### Option 2: Streamlit App on Databricks

```python
# app.py
import streamlit as st
from kumc_poc.responses_agent import ResponsesAgent, ResponsesAgentRequest

st.title("Healthcare Analytics Agent")

agent = ResponsesAgent()

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("What would you like to know?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        
        request = ResponsesAgentRequest(
            input=[{"role": "user", "content": prompt}],
            custom_inputs={"thread_id": st.session_state.get("thread_id", "default")}
        )
        
        for event in agent.predict_stream(request):
            if event.type == "response.output_item.done" and hasattr(event.item, 'text'):
                text = event.item.text
                is_token = not text.startswith(("💭", "🚀", "🎯", "✓")) and len(text) < 100
                
                if is_token:
                    full_response += text
                else:
                    full_response += f"\n\n{text}"
                
                response_placeholder.markdown(full_response + "▊")
        
        response_placeholder.markdown(full_response)
    
    st.session_state.messages.append({"role": "assistant", "content": full_response})
```

## Event Detection Pattern

Use this regex pattern to detect structured events vs tokens:

```python
import re

STRUCTURED_EVENT_PATTERN = re.compile(r'^[💭🚀🎯✓🔍📊📋🔧📝✅⚡📄🤖💡❓⏭️📍🛠️\n]')

def is_streaming_token(text: str) -> bool:
    """Check if text is a streaming token vs structured event."""
    return (
        not STRUCTURED_EVENT_PATTERN.match(text)
        and len(text) < 100
        and not text.startswith('\n')
    )
```

## Performance Tips

1. **Buffering:** Collect tokens in 50-100ms batches to reduce render thrashing
2. **Virtualization:** Use `react-window` or similar for long conversations
3. **Web Workers:** Process events in background thread for smooth UI
4. **RequestAnimationFrame:** Update DOM in RAF callback for 60fps rendering

## Example Output

**User:** "What can I do here?"

**Agent Streaming:**
```
🚀 Starting unified_intent_context_clarification agent...
🤖 Streaming response from unified_intent_context_clarification...
```json
{
  "is_meta_question": true,
  "meta_answer": "You have access to three healthcare analytics spaces..."
}
```
🎯 Intent: new_question (confidence: 92%)
💡 Meta-question detected
```

Clean, professional, and easy to read! ✨

## Troubleshooting

### Tokens Not Streaming Smoothly

**Problem:** Tokens appear in chunks instead of word-by-word

**Solution:** Ensure `flush=True` in print statements or call `sys.stdout.flush()`

### JSON Metadata Still Showing

**Problem:** Seeing `{"type": "llm_token", ...}` in output

**Solution:** Verify `format_custom_event()` has `"llm_token"` formatter that returns content directly

### Emojis Not Displaying

**Problem:** Emojis show as boxes or ��

**Solution:** 
- Set UTF-8 encoding: `sys.stdout.reconfigure(encoding='utf-8')`
- Use emoji-safe fonts: SF Mono, Segoe UI Emoji, Apple Color Emoji

### Events Out of Order

**Problem:** Structured events appear before their associated tokens

**Solution:** Ensure proper ordering in `predict_stream()` - emit `llm_streaming_start` BEFORE tokens

## Next Steps

1. ✅ Test the updated streaming in your Databricks notebook
2. ✅ Deploy to Databricks Playground or Streamlit
3. ✅ Add custom CSS for branding
4. ✅ Implement error handling for network issues
5. ✅ Add user feedback mechanisms (👍/👎 buttons)

## Resources

- [Databricks AI Playground Docs](https://docs.databricks.com/en/large-language-models/ai-playground.html)
- [Streamlit Deployment Guide](https://docs.streamlit.io/deploy/streamlit-community-cloud)
- [LangGraph Streaming](https://langchain-ai.github.io/langgraph/how-tos/streaming/)
