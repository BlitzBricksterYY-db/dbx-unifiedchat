# Multi-Agent System Architecture

Detailed technical architecture for the Cross-Domain Genie Query System.

## Table of Contents

1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Data Flow](#data-flow)
4. [Agent Interaction Patterns](#agent-interaction-patterns)
5. [Decision Logic](#decision-logic)
6. [Technology Stack](#technology-stack)
7. [Scalability & Performance](#scalability--performance)

---

## System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            User Interface                            │
│                  (Databricks Model Serving Endpoint)                │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         SupervisorAgent                              │
│                      (LangGraph Supervisor)                          │
│  • Routes requests to sub-agents                                     │
│  • Manages message history                                           │
│  • Coordinates multi-agent workflows                                 │
└───────┬──────────────────────┬──────────────────────┬───────────────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Thinking &   │    │  Genie Agents    │    │  SQL Agents      │
│  Planning     │    │  (5 spaces)      │    │  (2 types)       │
│  Agent        │    │                  │    │                  │
└───────┬───────┘    └────────┬─────────┘    └────────┬─────────┘
        │                     │                       │
        ▼                     ▼                       ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Vector Search │    │ Genie Spaces     │    │ Unity Catalog    │
│ Index         │    │ (Data Sources)   │    │ (Delta Tables)   │
└───────────────┘    └──────────────────┘    └──────────────────┘
```

### Key Principles

1. **Modularity**: Each agent has a single, well-defined responsibility
2. **Composability**: Agents can be combined to handle complex queries
3. **Observability**: Full tracing via MLflow for debugging
4. **Scalability**: Horizontal scaling via Databricks Model Serving
5. **Privacy**: Built-in data protection at every layer

---

## Component Architecture

### 1. SupervisorAgent

**Technology:** LangGraph Supervisor  
**Purpose:** Central orchestrator for all sub-agents  
**Pattern:** Hub-and-spoke

**Responsibilities:**
- Accept user queries
- Route to appropriate agents
- Manage conversation state
- Aggregate responses
- Handle errors and retries

**Configuration:**
```python
create_supervisor(
    agents=[...],
    model=llm,
    prompt=supervisor_prompt,
    add_handoff_messages=False,
    output_mode="full_history"
)
```

### 2. ThinkingPlanningAgent

**Technology:** Custom Python class with LLM integration  
**Purpose:** Query analysis and execution planning  
**Pattern:** Strategy pattern

**Key Functions:**

1. **Clarity Check**
   - Input: User query
   - Output: Clear/Unclear + clarification options
   - Method: LLM prompt with structured JSON response

2. **Vector Search**
   - Input: User query
   - Output: Top 5 relevant Genie spaces
   - Method: Semantic similarity search via UC function

3. **Query Planning**
   - Input: Query + relevant spaces
   - Output: QueryPlan object with execution strategy
   - Method: LLM analysis with context

**Data Model:**
```python
@dataclass
class QueryPlan:
    question_clear: bool
    sub_questions: List[str]
    requires_multiple_spaces: bool
    relevant_space_ids: List[str]
    requires_join: bool
    join_strategy: str  # "fast_route" | "slow_route" | None
    execution_plan: str
```

### 3. GenieAgents (5 instances)

**Technology:** Databricks GenieAgent wrapper  
**Purpose:** Query individual Genie spaces  
**Pattern:** Adapter pattern

**Configured Spaces:**

| Space ID | Name | Domain | Tables |
|----------|------|--------|--------|
| 01f072db... | GENIE_PATIENT | Demographics | patient, ecog, biospecimen, appointments, insurance |
| 01f08f4d... | MEDICATIONS | Prescriptions | medications |
| 01f073c5... | GENIE_DIAGNOSIS_STAGING | Diagnoses | cancer_diagnosis, cancer_comorbidities |
| 01f07795... | GENIE_TREATMENT | Treatments | treatments, procedures, transplants |
| 01f08a9f... | GENIE_LABORATORY_BIOMARKERS | Lab Results | laboratory, biomarkers |

**Configuration:**
```python
GenieAgent(
    genie_space_id=space_id,
    genie_agent_name=name,
    description=description,
    include_context=True  # Returns reasoning + SQL + result
)
```

**Output Format:**
```python
{
    "messages": [
        {"name": "query_reasoning", "content": "..."},
        {"name": "query_sql", "content": "..."},
        {"name": "query_result", "content": "..."}
    ]
}
```

### 4. SQLSynthesisAgent

**Technology:** Custom Python class with LLM integration  
**Purpose:** Combine SQL across multiple tables/spaces  
**Pattern:** Builder pattern

**Two Modes:**

**Fast Route:**
- Input: Table metadata + original query
- Output: Direct SQL across multiple tables
- When: Metadata is sufficient, no need for Genie agents
- Performance: 3-5 seconds

**Slow Route:**
- Input: Multiple SQL queries from Genie agents
- Output: Combined SQL with JOINs/CTEs
- When: Need individual Genie context
- Performance: 5-10 seconds

**SQL Generation Strategy:**
```python
# Fast Route
prompt = """
Generate SQL to answer: {query}
Using tables: {table_metadata}
Include JOINs on patient_id
"""

# Slow Route
prompt = """
Combine these SQL queries:
Query 1 (Patient): {sql_1}
Query 2 (Medication): {sql_2}
Into unified query with JOIN
"""
```

### 5. SQLExecutionAgent

**Technology:** PySpark SQL execution  
**Purpose:** Execute SQL and format results  
**Pattern:** Executor pattern

**Process:**
1. Receive SQL from SQLSynthesisAgent
2. Execute via `spark.sql()`
3. Convert to pandas DataFrame
4. Format as markdown table
5. Return with metadata (row count, columns)

**Error Handling:**
- Syntax errors → Return error message
- Permission errors → Return access denied message
- Timeout → Return partial results with timeout notice

### 6. Vector Search System

**Technology:** Databricks Vector Search (managed)  
**Purpose:** Find relevant Genie spaces for queries  
**Pattern:** Retrieval pattern

**Architecture:**
```
User Query (text)
    ↓
Embedding Model (databricks-gte-large-en)
    ↓
Vector (1024 dimensions)
    ↓
Similarity Search (cosine)
    ↓
Top K Results (space_id, space_title, score)
```

**Index Configuration:**
- Source: `enriched_genie_docs_flattened`
- Primary Key: `id`
- Embedding Column: `searchable_content`
- Sync Type: Delta sync (automatic updates)
- Pipeline: TRIGGERED (manual refresh) or CONTINUOUS

**UC Function:**
```sql
CREATE FUNCTION search_genie_spaces(query STRING, num_results INT)
RETURNS TABLE(space_id STRING, space_title STRING, score DOUBLE)
```

---

## Data Flow

### Single-Space Query Flow

```
User: "How many patients are older than 50?"
    ↓
SupervisorAgent receives query
    ↓
Route to ThinkingPlanningAgent
    ↓
ThinkingPlanningAgent analyzes:
  • Query is clear ✓
  • Vector search → GENIE_PATIENT (score: 0.95)
  • Single space required ✓
  • No JOIN needed ✓
    ↓
Route to GENIE_PATIENT GenieAgent
    ↓
GenieAgent queries:
  • Reasoning: "Count patients where AGE_YEARS > 50"
  • SQL: "SELECT COUNT(DISTINCT patient_id) FROM patient WHERE AGE_YEARS > 50"
  • Result: "12,450 patients"
    ↓
SupervisorAgent returns to user:
  • Thinking process ✓
  • SQL used ✓
  • Result ✓
```

### Multi-Space Query Flow (Fast Route)

```
User: "How many patients over 50 are on Voltaren?"
    ↓
SupervisorAgent receives query
    ↓
Route to ThinkingPlanningAgent
    ↓
ThinkingPlanningAgent analyzes:
  • Query is clear ✓
  • Vector search → GENIE_PATIENT (0.89), MEDICATIONS (0.92)
  • Multiple spaces required ✓
  • JOIN needed (patient_id) ✓
  • Strategy: fast_route ✓
  • Sub-questions:
    - Patients > 50
    - Patients on Voltaren
    - Intersection via patient_id
    ↓
Route to SQLSynthesisAgent (fast_route)
    ↓
SQLSynthesisAgent:
  • Retrieves table metadata
  • Generates SQL:
    ```sql
    SELECT COUNT(DISTINCT p.patient_id)
    FROM genie.dbo.patient p
    INNER JOIN genie.dbo.medications m
      ON p.patient_id = m.patient_id
    WHERE p.AGE_YEARS > 50
      AND m.MEDICATION_NAME ILIKE '%voltaren%'
    ```
    ↓
Route to SQLExecutionAgent
    ↓
SQLExecutionAgent:
  • Executes SQL
  • Result: "3,245 patients"
    ↓
SupervisorAgent returns to user:
  • Thinking process ✓
  • SQL used ✓
  • Result ✓
  • Execution time: ~4 seconds
```

### Multi-Space Query Flow (Slow Route)

```
User: "Patients with lung cancer on chemotherapy?"
    ↓
SupervisorAgent receives query
    ↓
Route to ThinkingPlanningAgent
    ↓
ThinkingPlanningAgent analyzes:
  • Query is clear ✓
  • Vector search → GENIE_DIAGNOSIS (0.94), MEDICATIONS (0.87)
  • Multiple spaces required ✓
  • JOIN needed ✓
  • Strategy: slow_route (need Genie context)
  • Sub-questions:
    - Patients with lung cancer
    - Patients on chemotherapy
    ↓
Route to BOTH GenieAgents in PARALLEL:
    ↓                           ↓
GENIE_DIAGNOSIS            MEDICATIONS
    │                           │
    │ Query: lung cancer        │ Query: chemotherapy
    │ SQL: SELECT patient_id... │ SQL: SELECT patient_id...
    │ Result: 5,678 patients    │ Result: 12,340 patients
    │                           │
    └───────────┬───────────────┘
                ↓
Route to SQLSynthesisAgent (slow_route)
    ↓
SQLSynthesisAgent:
  • Receives both SQL queries
  • Combines with JOIN:
    ```sql
    WITH lung_cancer AS (
      SELECT DISTINCT patient_id FROM ...
    ),
    chemotherapy AS (
      SELECT DISTINCT patient_id FROM ...
    )
    SELECT COUNT(DISTINCT lc.patient_id)
    FROM lung_cancer lc
    INNER JOIN chemotherapy c ON lc.patient_id = c.patient_id
    ```
    ↓
Route to SQLExecutionAgent
    ↓
SQLExecutionAgent:
  • Executes combined SQL
  • Result: "1,234 patients"
    ↓
SupervisorAgent returns to user:
  • Thinking process ✓
  • Individual SQL queries ✓
  • Combined SQL ✓
  • Result ✓
  • Execution time: ~8 seconds
```

### Clarification Flow

```
User: "Tell me about cancer patients"
    ↓
SupervisorAgent receives query
    ↓
Route to ThinkingPlanningAgent
    ↓
ThinkingPlanningAgent analyzes:
  • Query is UNCLEAR ✗
  • Needs clarification
  • Generates options:
    1. "Total count of cancer patients?"
    2. "Demographics of cancer patients?"
    3. "Treatment information for cancer patients?"
    ↓
SupervisorAgent returns to user:
  • Clarification needed ✓
  • Options provided ✓
    ↓
User selects option 2
    ↓
SupervisorAgent re-triggers with refined query:
  "What are the demographics of cancer patients?"
    ↓
[Normal query flow resumes]
```

---

## Agent Interaction Patterns

### Pattern 1: Sequential Routing

```
SupervisorAgent
    → ThinkingPlanningAgent
    → GenieAgent
    → SupervisorAgent (response)
```

**Use Case:** Simple, single-space queries  
**Latency:** Low (2-3s)

### Pattern 2: Parallel Fan-Out

```
SupervisorAgent
    → ThinkingPlanningAgent
    → [GenieAgent1, GenieAgent2, GenieAgent3] (parallel)
    → SQLSynthesisAgent (aggregates)
    → SQLExecutionAgent
    → SupervisorAgent (response)
```

**Use Case:** Multi-space queries with join  
**Latency:** Medium (5-10s)

### Pattern 3: Progressive Response

```
SupervisorAgent
    → ThinkingPlanningAgent
    → Fast Route (immediate) → Response 1
    ↓
    → Slow Route (background) → Response 2 (when ready)
```

**Use Case:** Multi-space queries where user wants quick answer  
**Latency:** Fast route: 3-5s, Slow route: 5-10s

### Pattern 4: Clarification Loop

```
SupervisorAgent
    → ThinkingPlanningAgent
    → [Unclear] → Request Clarification
    ↓
User provides clarification
    ↓
SupervisorAgent
    → ThinkingPlanningAgent (with clarification)
    → [Normal flow]
```

**Use Case:** Ambiguous queries  
**Latency:** Dependent on user response time

---

## Decision Logic

### Routing Decision Tree

```
Query received
    ↓
Is query clear?
    ├─ No → Request clarification → Wait for user → Retry
    └─ Yes → Continue
        ↓
Vector search: Find relevant spaces
    ↓
How many spaces needed?
    ├─ 1 space → Route to single GenieAgent → Return
    └─ Multiple spaces → Continue
        ↓
Is JOIN required?
    ├─ No → Route to multiple GenieAgents (parallel)
    │        → Verbal merge → Return
    └─ Yes → Continue
        ↓
Which route?
    ├─ Fast Route:
    │   • Metadata sufficient
    │   • Direct SQL synthesis
    │   • SQLExecution
    │   • Return (3-5s)
    └─ Slow Route:
        • Need Genie context
        • Query each Genie (parallel)
        • Collect SQL results
        • SQLSynthesis combines
        • SQLExecution
        • Return (5-10s)
```

### Fast vs Slow Route Decision

**Use Fast Route When:**
- Table schemas are well-known
- Metadata includes sample values
- Query is straightforward
- No complex business logic needed

**Use Slow Route When:**
- Need Genie reasoning/context
- Complex domain-specific logic
- Business rules in Genie instructions
- User wants to see sub-query reasoning

---

## Technology Stack

### Core Technologies

| Component | Technology | Version |
|-----------|------------|---------|
| Agent Framework | LangGraph Supervisor | 0.0.30 |
| LLM Integration | Databricks LangChain | Latest |
| Model Tracking | MLflow | Latest |
| Vector Search | Databricks Vector Search | Managed |
| Data Platform | Unity Catalog | N/A |
| Compute | Databricks Clusters | DBR 14.3+ |
| Serving | Model Serving | Serverless |

### Python Dependencies

```python
langgraph-supervisor==0.0.30
mlflow[databricks]
databricks-langchain
databricks-agents
databricks-vectorsearch
databricks-sdk
pyspark
pandas
pydantic
python-dotenv
```

### Databricks Services

- **Unity Catalog**: Data governance and access control
- **Genie Spaces**: Pre-configured SQL agents for domains
- **Vector Search**: Semantic search over metadata
- **Model Serving**: Scalable agent deployment
- **SQL Warehouses**: Query execution
- **MLflow**: Experiment tracking and model registry

---

## Scalability & Performance

### Horizontal Scaling

**Model Serving Endpoint:**
- Auto-scaling based on load
- Scale-to-zero when idle
- Max concurrent requests: 100 (configurable)

**Vector Search:**
- Distributed index
- Parallel query execution
- Sub-second latency for top-K

**SQL Execution:**
- Leverages SQL Warehouse scaling
- Query caching
- Adaptive query execution

### Performance Optimizations

1. **Caching**
   - Vector search results cached
   - Common queries memoized
   - LLM responses cached for similar queries

2. **Parallel Execution**
   - Genie agents query in parallel
   - Async/await for non-blocking operations
   - Thread pools for I/O operations

3. **Query Optimization**
   - Predicate pushdown
   - Partition pruning
   - Broadcast joins for small tables

### Monitoring & Observability

**MLflow Traces:**
- Full execution trace for each query
- Agent routing decisions
- SQL generated at each step
- Execution times per component

**Metrics:**
- Query latency (P50, P95, P99)
- Success rate by query type
- Agent utilization
- Error rates and types

**Alerting:**
- Endpoint health checks
- Error rate thresholds
- Latency SLA violations
- Resource utilization limits

---

## Security & Privacy

### Access Control

**Unity Catalog:**
- Table-level permissions
- Column-level masking (optional)
- Row-level security (optional)

**Model Serving:**
- Authentication required
- API token management
- IP allowlisting (optional)

### Data Protection

**Privacy Controls:**
- No individual patient IDs returned
- Count thresholds (< 10 → "less than 10")
- Age bucketing (> 89 → "90+")
- PII filtering in responses

**Audit Trail:**
- All queries logged
- User attribution
- Timestamp tracking
- Result access logging

---

## Extensibility

### Adding New Genie Spaces

```python
# In agent.py, add to GENIE_SPACES list:
Genie(
    space_id="new_space_id",
    name="NEW_SPACE_NAME",
    description="Description of data domain..."
)
```

### Adding Custom Agents

```python
class CustomAgent:
    def __init__(self, llm):
        self.llm = llm
        self.name = "CustomAgent"
    
    def __call__(self, state):
        # Custom logic here
        return {"messages": [...]}

# Register with supervisor
agents.append(custom_agent)
```

### Adding UC Functions

```python
IN_CODE_AGENTS = [
    InCodeSubAgent(
        tools=["catalog.schema.my_custom_function"],
        name="CustomToolAgent",
        description="Uses my custom UC function"
    )
]
```

---

## Future Architecture Considerations

1. **Distributed Tracing**: OpenTelemetry integration
2. **Event-Driven**: Kafka/Delta Live Tables for real-time updates
3. **Multi-Tenancy**: Separate catalogs per customer
4. **Edge Caching**: CDN for common queries
5. **Federated Learning**: Local model fine-tuning

---

**Document Version:** 1.0  
**Last Updated:** December 1, 2025  
**Status:** Production-Ready

