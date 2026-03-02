import json
import time
import logging
from uuid import uuid4
from typing import Dict, List, Optional, Any, Generator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AIMessageChunk
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import StateGraph

from databricks_langchain import CheckpointSaver, DatabricksStore

from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    output_to_responses_items_stream,
    to_chat_completions_input,
)

from .state import RESET_STATE_TEMPLATE
# from .config import get_config

logger = logging.getLogger(__name__)

#########################################################
"""
Load configuration from dev_config.yaml for testing.

This uses the same YAML configuration that deployment uses,
but loads it for testing purposes.
"""
#########################################################
# Lazy load config if not set
LAKEBASE_INSTANCE_NAME = None
if LAKEBASE_INSTANCE_NAME is None:
    try:
        from ..core.config import get_config
        config = get_config()
        if LAKEBASE_INSTANCE_NAME is None:
            LAKEBASE_INSTANCE_NAME = config.lakebase.instance_name
    except Exception as e:
        print(f"⚠️ Failed to load config: {e}")

print(f"Lakebase Instance: {LAKEBASE_INSTANCE_NAME}")
print("="*80)


# Performance metrics storage
_performance_metrics = {
    "node_timings": {},
    "cache_stats": {
        "space_context_hits": 0,
        "space_context_misses": 0,
        "vector_search_hits": 0,
        "vector_search_misses": 0,
        "agent_cache_hits": 0,
        "agent_cache_misses": 0,
        "llm_pool_hits": 0,
        "llm_pool_misses": 0
    },
    "workflow_metrics": {
        "ttft_seconds": [],
        "ttcl_seconds": [],
        "total_requests": 0
    }
}
class SuperAgentHybridResponsesAgent(ResponsesAgent):
    """
    Enhanced ResponsesAgent with both short-term and long-term memory for distributed Model Serving.
    
    Features:
    - Short-term memory (CheckpointSaver): Multi-turn conversations within a session
    - Long-term memory (DatabricksStore): User preferences across sessions with semantic search
    - Connection pooling and automatic credential rotation
    - Works seamlessly in distributed Model Serving (multiple instances)
    
    Memory Architecture:
    - Short-term: Stored per thread_id in Lakebase checkpoints table
    - Long-term: Stored per user_id in Lakebase store table with vector embeddings
    """
    
    def __init__(self, workflow: StateGraph):
        """
        Initialize the ResponsesAgent wrapper.
        
        Args:
            workflow: The uncompiled LangGraph StateGraph workflow
        """
        self.workflow = workflow
        self.lakebase_instance_name = LAKEBASE_INSTANCE_NAME
        self._store = None
        self._memory_tools = None
        self._last_first_token_time = None
        if self.lakebase_instance_name:
            print("✓ SuperAgentHybridResponsesAgent initialized with Lakebase memory support")
        else:
            print("⚠️  SuperAgentHybridResponsesAgent initialized WITHOUT Lakebase - using in-memory MemorySaver fallback")
            print("   Multi-turn memory will NOT be shared across Model Serving replicas.")

    def _build_checkpointer(self):
        """
        Build a checkpointer for the workflow graph.

        Returns (checkpointer, using_lakebase) where using_lakebase indicates
        whether the returned checkpointer is a CheckpointSaver context manager
        (True) or an in-memory MemorySaver (False).
        """
        if self.lakebase_instance_name:
            try:
                return CheckpointSaver(instance_name=self.lakebase_instance_name), True
            except Exception as e:
                logger.warning(f"Lakebase unavailable ({e}). Falling back to in-memory MemorySaver.")
        from langgraph.checkpoint.memory import MemorySaver
        logger.warning(
            "Using in-memory MemorySaver. State will NOT persist across replicas or restarts."
        )
        return MemorySaver(), False

    def _stream_workflow(self, checkpointer, initial_state, run_config, cc_msgs, workflow_start_time):
        """
        Compile the graph with the given checkpointer and stream all events.

        This is a generator that yields ResponsesAgentStreamEvent objects.
        After iteration completes, self._last_first_token_time is set so the
        caller can compute TTFT.
        """
        first_message = True
        seen_ids = set()
        first_token_time = None

        app = self.workflow.compile(checkpointer=checkpointer)
        logger.info("Executing workflow with checkpointer")

        for event in app.stream(initial_state, run_config, stream_mode=["updates", "messages", "custom", "tasks"]):
            event_type = event[0]
            event_data = event[1]

            # Handle streaming text deltas (messages mode)
            if event_type == "messages":
                try:
                    chunk = event_data[0] if isinstance(event_data, (list, tuple)) else event_data
                    if isinstance(chunk, AIMessageChunk) and (content := chunk.content):
                        if first_token_time is None:
                            first_token_time = time.time()
                            ttft = first_token_time - workflow_start_time
                            _performance_metrics["workflow_metrics"]["ttft_seconds"].append(ttft)
                            logger.info(f"TTFT: {ttft:.3f}s")
                        yield ResponsesAgentStreamEvent(
                            **self.create_text_delta(delta=content, item_id=chunk.id),
                        )
                except Exception as e:
                    logger.warning(f"Error processing message chunk: {e}")

            # Handle node updates (updates mode)
            elif event_type == "updates":
                events = event_data
                new_msgs = [
                    msg
                    for v in events.values()
                    for msg in v.get("messages", [])
                    if hasattr(msg, 'id') and msg.id not in seen_ids
                ]

                if first_message:
                    seen_ids.update(msg.id for msg in new_msgs[: len(cc_msgs)])
                    new_msgs = new_msgs[len(cc_msgs) :]
                    first_message = False
                else:
                    seen_ids.update(msg.id for msg in new_msgs)
                    if events:
                        node_name = tuple(events.keys())[0]
                        node_update = events[node_name]
                        updated_keys = [k for k in node_update.keys() if k != "messages"]

                        step_text = f"🔹 Step: {node_name}"
                        if updated_keys:
                            step_text += f" | Keys updated: {', '.join(updated_keys)}"

                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=self.create_text_output_item(text=step_text, id=str(uuid4())),
                        )

                        if "next_agent" in node_update:
                            next_agent = node_update["next_agent"]
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.done",
                                item=self.create_text_output_item(
                                    text=f"🔀 Routing decision: Next agent = {next_agent}",
                                    id=str(uuid4()),
                                ),
                            )

                for msg in new_msgs:
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            try:
                                yield ResponsesAgentStreamEvent(
                                    type="response.output_item.done",
                                    item=self.create_function_call_item(
                                        id=str(uuid4()),
                                        call_id=tool_call.get("id", str(uuid4())),
                                        name=tool_call.get("name", "unknown"),
                                        arguments=json.dumps(tool_call.get("args", {})),
                                    ),
                                )
                            except Exception as e:
                                logger.warning(f"Error emitting tool call: {e}")
                    elif hasattr(msg, '__class__') and msg.__class__.__name__ == 'ToolMessage':
                        try:
                            tool_name = getattr(msg, 'name', 'unknown')
                            tool_content = str(msg.content)[:200] if msg.content else "No content"
                            yield ResponsesAgentStreamEvent(
                                type="response.output_item.done",
                                item=self.create_text_output_item(
                                    text=f"🔨 Tool result ({tool_name}): {tool_content}...",
                                    id=str(uuid4()),
                                ),
                            )
                        except Exception as e:
                            logger.warning(f"Error emitting tool result: {e}")
                    else:
                        yield from output_to_responses_items_stream([msg])

            # Handle custom mode (agent-specific events)
            elif event_type == "custom":
                try:
                    formatted_text = self.format_custom_event(event_data)
                    yield ResponsesAgentStreamEvent(
                        type="response.output_item.done",
                        item=self.create_text_output_item(text=formatted_text, id=str(uuid4())),
                    )
                except Exception as e:
                    logger.warning(f"Error processing custom event: {e}")

            # Handle tasks mode (node lifecycle events)
            elif event_type == "tasks":
                try:
                    task_event = event_data
                    event_name = task_event.get("event", "unknown")
                    node_name = task_event.get("name", "unknown")

                    if event_name == "start":
                        logger.debug(f"Task started: {node_name}")
                    elif event_name == "end":
                        duration = task_event.get("duration")
                        if duration:
                            logger.info(f"Task completed: {node_name} ({duration:.3f}s)")
                            if "node_timings" not in _performance_metrics["workflow_metrics"]:
                                _performance_metrics["workflow_metrics"]["node_timings"] = {}
                            _performance_metrics["workflow_metrics"]["node_timings"][node_name] = duration
                        else:
                            logger.info(f"Task completed: {node_name}")
                    elif event_name == "error":
                        error = task_event.get("error", "Unknown error")
                        logger.error(f"Task failed: {node_name} - {error}")
                        yield ResponsesAgentStreamEvent(
                            type="response.output_item.done",
                            item=self.create_text_output_item(
                                text=f"❌ Error in {node_name}: {error}",
                                id=str(uuid4()),
                            ),
                        )
                except Exception as e:
                    logger.warning(f"Error processing task event: {e}")

        self._last_first_token_time = first_token_time

    @property
    def store(self):
        """Lazy initialization of DatabricksStore for long-term memory.

        Returns None if Lakebase is not configured.
        """
        if not self.lakebase_instance_name:
            return None
        if self._store is None:
            logger.info(f"Initializing DatabricksStore with instance: {self.lakebase_instance_name}")
            self._store = DatabricksStore(
                instance_name=self.lakebase_instance_name,
                embedding_endpoint=EMBEDDING_ENDPOINT,
                embedding_dims=EMBEDDING_DIMS,
            )
            self._store.setup()  # Creates store table if not exists
            logger.info("DatabricksStore initialized")
        return self._store
    
    @property
    def memory_tools(self):
        """Create memory tools for long-term memory access."""
        if self._memory_tools is None:
            logger.info("Creating memory tools for long-term memory")
            
            @tool
            def get_user_memory(query: str, config: RunnableConfig) -> str:
                """Search for relevant user information using semantic search.
                
                Use this tool to retrieve previously saved information about the user,
                such as their preferences, facts they've shared, or other personal details.
                
                Args:
                    query: The search query to find relevant memories
                    config: Runtime configuration containing user_id
                """
                if not self.store:
                    return "Long-term memory not available - Lakebase is not configured."
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Memory not available - no user_id provided."

                namespace = ("user_memories", user_id.replace(".", "-"))
                results = self.store.search(namespace, query=query, limit=5)
                
                if not results:
                    return "No memories found for this user."
                
                memory_items = [f"- [{item.key}]: {json.dumps(item.value)}" for item in results]
                return f"Found {len(results)} relevant memories (ranked by similarity):\n" + "\n".join(memory_items)
            
            @tool
            def save_user_memory(memory_key: str, memory_data_json: str, config: RunnableConfig) -> str:
                """Save information about the user to long-term memory.
                
                Use this tool to remember important information the user shares,
                such as preferences, facts, or other personal details.
                
                Args:
                    memory_key: A descriptive key for this memory (e.g., "preferences", "favorite_visualization")
                    memory_data_json: JSON string with the information to remember. 
                        Example: '{"preferred_chart_type": "bar", "default_spaces": ["patient_data"]}'
                    config: Runtime configuration containing user_id
                """
                if not self.store:
                    return "Long-term memory not available - Lakebase is not configured."
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot save memory - no user_id provided."

                namespace = ("user_memories", user_id.replace(".", "-"))
                
                try:
                    memory_data = json.loads(memory_data_json)
                    if not isinstance(memory_data, dict):
                        return f"Failed: memory_data must be a JSON object, not {type(memory_data).__name__}"
                    self.store.put(namespace, memory_key, memory_data)
                    return f"Successfully saved memory with key '{memory_key}' for user"
                except json.JSONDecodeError as e:
                    return f"Failed to save memory: Invalid JSON format - {str(e)}"
            
            @tool
            def delete_user_memory(memory_key: str, config: RunnableConfig) -> str:
                """Delete a specific memory from the user's long-term memory.
                
                Use this when the user asks you to forget something or remove
                a piece of information from their memory.
                
                Args:
                    memory_key: The key of the memory to delete
                    config: Runtime configuration containing user_id
                """
                if not self.store:
                    return "Long-term memory not available - Lakebase is not configured."
                user_id = config.get("configurable", {}).get("user_id")
                if not user_id:
                    return "Cannot delete memory - no user_id provided."

                namespace = ("user_memories", user_id.replace(".", "-"))
                self.store.delete(namespace, memory_key)
                return f"Successfully deleted memory with key '{memory_key}' for user"
            
            self._memory_tools = [get_user_memory, save_user_memory, delete_user_memory]
            logger.info(f"✓ Created {len(self._memory_tools)} memory tools")
        
        return self._memory_tools
    
    def _get_or_create_thread_id(self, request: ResponsesAgentRequest) -> str:
        """Get thread_id from request or create a new one.
        
        Priority:
        1. Use thread_id from custom_inputs if present
        2. Use conversation_id from chat context if available
        3. Generate a new UUID
        """
        ci = dict(request.custom_inputs or {})
        
        if "thread_id" in ci:
            return ci["thread_id"]
        
        # Use conversation_id from ChatContext as thread_id
        if request.context and getattr(request.context, "conversation_id", None):
            return request.context.conversation_id
        
        # Generate new thread_id
        return str(uuid4())
    
    def _get_user_id(self, request: ResponsesAgentRequest) -> Optional[str]:
        """Extract user_id from request context.
        
        Priority:
        1. Use user_id from chat context (preferred for Model Serving)
        2. Use user_id from custom_inputs
        """
        if request.context and getattr(request.context, "user_id", None):
            return request.context.user_id
        
        if request.custom_inputs and "user_id" in request.custom_inputs:
            return request.custom_inputs["user_id"]
        
        return None
    
    def make_json_serializable(self, obj):
        """
        Convert LangChain objects and other non-serializable objects to JSON-serializable format.
        
        Args:
            obj: Object to convert
            
        Returns:
            JSON-serializable version of the object
        """
        from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, ToolMessage, AIMessageChunk
        from uuid import UUID
        
        # Handle None
        if obj is None:
            return None
        
        # Handle UUID objects
        if isinstance(obj, UUID):
            return str(obj)
        
        # Handle bytes
        if isinstance(obj, bytes):
            try:
                return obj.decode('utf-8', errors='ignore')
            except:
                return f"<bytes:{len(obj)}>"
        
        # Handle set
        if isinstance(obj, set):
            return [self.make_json_serializable(item) for item in obj]
        
        # Handle LangChain message objects
        if isinstance(obj, BaseMessage):
            msg_dict = {
                "type": obj.__class__.__name__,
                "content": str(obj.content) if obj.content else ""
            }
            if hasattr(obj, 'id') and obj.id:
                msg_dict["id"] = str(obj.id)
            if hasattr(obj, 'name') and obj.name:
                msg_dict["name"] = obj.name
            if hasattr(obj, 'tool_calls') and obj.tool_calls:
                # Recursively serialize tool calls
                msg_dict["tool_calls"] = [
                    self.make_json_serializable(tc) for tc in obj.tool_calls[:2]
                ]  # Limit to 2 for brevity
            return msg_dict
        
        # Handle dictionaries recursively
        if isinstance(obj, dict):
            return {str(k): self.make_json_serializable(v) for k, v in obj.items()}
        
        # Handle lists and tuples recursively
        if isinstance(obj, (list, tuple)):
            return [self.make_json_serializable(item) for item in obj]
        
        # Handle primitives
        if isinstance(obj, (str, int, float, bool)):
            return obj
        
        # For anything else, convert to string representation
        try:
            return str(obj)
        except Exception:
            return f"<{type(obj).__name__}>"
    
    def format_custom_event(self, custom_data: dict) -> str:
        """
        Format custom streaming events for user-friendly display.
        
        Args:
            custom_data: Dictionary containing custom event data with 'type' key
            
        Returns:
            Formatted string with emoji and readable event description
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
            
            # Markdown content formatters - return content directly for UI display
            "meta_answer_content": lambda d: f"\n\n{d.get('content', '')}",
            "clarification_content": lambda d: f"\n\n{d.get('content', '')}",
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
            lambda d: f"ℹ️ {event_type}: {json.dumps(self.make_json_serializable(d), indent=2, default=json_fallback)}"
        )
        
        try:
            return formatter(custom_data)
        except Exception as e:
            logger.warning(f"Error formatting custom event {event_type}: {e}")
            # Enhanced error handling with serialization fallback
            try:
                serialized = self.make_json_serializable(custom_data)
                return f"ℹ️ {event_type}: {json.dumps(serialized, indent=2, default=json_fallback)}"
            except Exception as e2:
                logger.warning(f"Error serializing custom event {event_type}: {e2}")
                return f"ℹ️ {event_type}: {str(custom_data)}"
    
    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """
        Make a prediction (non-streaming).
        
        Args:
            request: The request containing input messages
            
        Returns:
            ResponsesAgentResponse with output items
        """
        outputs = [
            event.item
            for event in self.predict_stream(request)
            if event.type == "response.output_item.done"
        ]
        return ResponsesAgentResponse(output=outputs, custom_outputs=request.custom_inputs)
    
    def predict_stream(
        self,
        request: ResponsesAgentRequest,
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        """
        Make a streaming prediction with both short-term and long-term memory.
        
        SIMPLIFIED API: All conversation turns use the same simple format.
        The agent auto-detects clarification responses and follow-ups from message history.
        
        Memory Systems:
        - Short-term (CheckpointSaver): Preserves conversation state across distributed instances
        - Long-term (DatabricksStore): User preferences accessible via memory tools
        
        Args:
            request: The request containing:
                - input: List of messages (user query is the last message)
                - context.conversation_id: Used as thread_id (preferred)
                - context.user_id: Used for long-term memory (preferred)
                - custom_inputs: Dict with optional keys:
                    - thread_id (str): Thread identifier override
                    - user_id (str): User identifier override
            
        Yields:
            ResponsesAgentStreamEvent for each step in the workflow
            
        Usage in Model Serving (ALL scenarios use same format):
            # First query in a conversation
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Show me patient data"}],
                "context": {
                    "conversation_id": "session_001",
                    "user_id": "user@example.com"
                }
            }
            
            # Clarification response (SIMPLIFIED - auto-detected!)
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Patient count by age group"}],
                "context": {
                    "conversation_id": "session_001",  # Same thread_id
                    "user_id": "user@example.com"
                }
            }
            
            # Follow-up query (agent remembers context automatically)
            POST /invocations
            {
                "messages": [{"role": "user", "content": "Now show by gender"}],
                "context": {
                    "conversation_id": "session_001",  # Same thread_id
                    "user_id": "user@example.com"
                }
            }
        """
        # Get identifiers
        thread_id = self._get_or_create_thread_id(request)
        user_id = self._get_user_id(request)
        
        # Update custom_inputs with resolved identifiers
        ci = dict(request.custom_inputs or {})
        ci["thread_id"] = thread_id
        if user_id:
            ci["user_id"] = user_id
        request.custom_inputs = ci
        
        logger.info(f"Processing request - thread_id: {thread_id}, user_id: {user_id}")
        
        # PHASE 3 OPTIMIZATION: Track workflow timing (TTFT and TTCL)
        workflow_start_time = time.time()
        first_token_time = None
        _performance_metrics["workflow_metrics"]["total_requests"] += 1
        
        # Ensure MLflow tracing doesn't cause issues in streaming context
        # This safeguard prevents NonRecordingSpan context attribute errors
        try:
            import mlflow.tracing
            # Verify tracing is properly initialized, otherwise disable to prevent errors
            if not hasattr(mlflow.tracing, '_is_enabled') or not mlflow.tracing._is_enabled():
                logger.debug("MLflow tracing not enabled, continuing without tracing")
        except Exception as e:
            logger.debug(f"MLflow tracing check skipped: {e}")
        
        # Convert request input to chat completions format
        cc_msgs = to_chat_completions_input([i.model_dump() for i in request.input])
        
        # Get the latest user message
        latest_query = cc_msgs[-1]["content"] if cc_msgs else ""
        
        # Configure runtime with thread_id and user_id
        run_config = {"configurable": {"thread_id": thread_id}}
        if user_id:
            run_config["configurable"]["user_id"] = user_id
        
        # SIMPLIFIED: Unified state initialization for all scenarios
        # CheckpointSaver will restore previous conversation context automatically
        # The intent_detection_node runs first and creates current_turn
        initial_state = {
            **RESET_STATE_TEMPLATE,  # Reset all per-query execution fields
            "original_query": latest_query,
            "messages": [
                SystemMessage(content="""You are a multi-agent Q&A analysis system.
Your role is to help users query and analyze cross-domain data.

Guidelines:
- Always explain your reasoning and execution plan
- Validate SQL queries before execution
- Provide clear, comprehensive summaries
- If information is missing, ask for clarification (max once)
- Use UC functions and Genie agents to generate accurate SQL
- Return results with proper context and explanations"""),
                HumanMessage(content=latest_query)
            ]
            # NOTE: current_turn, intent_metadata, turn_history are NOT in RESET_STATE_TEMPLATE
            # They are managed by unified_intent_context_clarification_node and persist via CheckpointSaver
        }
        
        # Add user_id to state for long-term memory access
        if user_id:
            initial_state["user_id"] = user_id
            initial_state["thread_id"] = thread_id
        
        # Build checkpointer: Lakebase (distributed, persistent) or MemorySaver (in-process fallback)
        checkpointer, using_lakebase = self._build_checkpointer()
        if using_lakebase:
            # CheckpointSaver is a context manager that manages the Lakebase connection
            with checkpointer:
                yield from self._stream_workflow(
                    checkpointer, initial_state, run_config, cc_msgs, workflow_start_time
                )
        else:
            # MemorySaver is a plain object, no context manager needed
            yield from self._stream_workflow(
                checkpointer, initial_state, run_config, cc_msgs, workflow_start_time
            )

        # Track TTCL (Time To Completion)
        workflow_end_time = time.time()
        ttcl = workflow_end_time - workflow_start_time
        _performance_metrics["workflow_metrics"]["ttcl_seconds"].append(ttcl)

        first_token_time = self._last_first_token_time
        logger.info(f"Workflow execution completed (thread: {thread_id})")
        logger.info(
            f"Performance: TTFT={first_token_time - workflow_start_time if first_token_time else 'N/A'}s, "
            f"TTCL={ttcl:.3f}s"
        )