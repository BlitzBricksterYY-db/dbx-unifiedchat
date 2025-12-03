# Multi-Agent System for Cross-Domain Genie Queries

A sophisticated multi-agent system built with LangGraph and Databricks that enables intelligent querying across multiple Genie spaces (data sources).

## 🎯 Overview

This system allows users to ask complex questions that span multiple data domains (patients, medications, diagnoses, treatments, etc.) and automatically:
- Routes queries to the appropriate agents
- Breaks down complex questions into sub-tasks
- Synthesizes SQL across multiple data sources
- Provides clear, comprehensive answers with reasoning

## 🏗️ Architecture

```
User Query
    ↓
SupervisorAgent (orchestrates all agents)
    ↓
ThinkingPlanningAgent (analyzes & plans)
    ↓
    ├─ Single Space → GenieAgent
    ├─ Multiple Spaces (No Join) → Multiple GenieAgents → Verbal Merge
    └─ Multiple Spaces (Join) → Fast/Slow Route → SQLSynthesis → SQLExecution
```

### Key Components

1. **SupervisorAgent**: Central orchestrator that routes requests to appropriate sub-agents
2. **ThinkingPlanningAgent**: Analyzes queries, uses vector search to find relevant Genie spaces, and plans execution strategy
3. **GenieAgents**: Query individual Genie spaces for specific data domains
4. **SQLSynthesisAgent**: Combines SQL queries across multiple tables/spaces
5. **SQLExecutionAgent**: Executes synthesized SQL and returns results
6. **Vector Search Index**: Semantic search over enriched Genie space metadata

## 📁 Project Structure

```
KUMC_POC_hlsfieldtemp/
├── Notebooks/
│   ├── 00_Export_Genie_Spaces.py        # NEW: Export Genie spaces to volume
│   ├── 01_Table_MetaInfo_Update.py      # Original table metadata notebook
│   ├── 02_Table_MetaInfo_Enrichment.py  # NEW: Enhanced metadata enrichment pipeline
│   ├── 03_VS_generation.py              # Original vector search example
│   ├── 04_VS_Enriched_Genie_Spaces.py   # NEW: Vector search for enriched docs
│   ├── 05_Multi_Agent_System.py         # NEW: Main multi-agent system notebook
│   ├── Super_Agent.ipynb                # Reference implementation
│   └── agent.py                         # NEW: Core agent code
├── Instructions/
│   └── 01_overall.md                    # Original requirements
├── Workspace/
│   └── *.json                           # Genie space exports
├── README.md                            # This file
└── databricks.yml                       # Databricks configuration
```

## 🚀 Setup & Installation

### Prerequisites

- Databricks workspace with:
  - Unity Catalog enabled
  - Genie spaces configured
  - Vector Search endpoint capability
  - Model Serving endpoint capability
- Access to LLM endpoint (e.g., `databricks-claude-sonnet-4-5`)
- Environment variables in `.env`:
  ```bash
  DATABRICKS_HOST=https://your-workspace.databricks.com
  DATABRICKS_TOKEN=your-token
  CATALOG_NAME=your_catalog
  SCHEMA_NAME=your_schema
  LLM_ENDPOINT=databricks-claude-sonnet-4-5
  ```

### Installation Steps

1. **Export Genie Spaces**
   ```python
   # Execute: Notebooks/00_Export_Genie_Spaces.py
   # This will:
   # - Export specified Genie spaces to Unity Catalog volume
   # - Create space.json and serialized.json files
   # - Verify exports
   ```

2. **Run Table Metadata Enrichment Pipeline**
   ```python
   # Execute: Notebooks/02_Table_MetaInfo_Enrichment.py
   # This will:
   # - Sample column values from all Genie tables
   # - Build value dictionaries
   # - Enhance descriptions with LLM
   # - Save enriched docs to Unity Catalog
   ```

3. **Build Vector Search Index**
   ```python
   # Execute: Notebooks/04_VS_Enriched_Genie_Spaces.py
   # This will:
   # - Create vector search endpoint
   # - Build delta sync index on enriched docs
   # - Register UC function for agent access
   ```

4. **Deploy Multi-Agent System**
   ```python
   # Execute: Notebooks/05_Multi_Agent_System.py
   # This will:
   # - Test all agent components
   # - Log model to MLflow
   # - Register to Model Registry
   # - Deploy to Model Serving endpoint
   ```

## 💻 Usage

### Basic Query Examples

```python
from agent import AGENT

# Single-space query
input_example = {
    "input": [
        {"role": "user", "content": "How many patients are older than 65?"}
    ]
}
response = AGENT.predict(input_example)

# Cross-domain query (with join)
input_example = {
    "input": [
        {"role": "user", "content": "How many patients over 50 are on Voltaren?"}
    ]
}
response = AGENT.predict(input_example)

# Multi-domain query (no join)
input_example = {
    "input": [
        {"role": "user", "content": "What are the most common diagnoses and medications?"}
    ]
}
response = AGENT.predict(input_example)
```

### Query via Deployed Endpoint

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

w = WorkspaceClient()

response = w.serving_endpoints.query(
    name="multi-agent-genie-endpoint",
    messages=[
        ChatMessage(
            role=ChatMessageRole.USER,
            content="How many patients are over 60 years old?"
        )
    ],
)
```

## 🎓 Query Types & Routing Logic

### 1. Single-Space Queries
**Example:** "How many patients live in Johnson County?"

**Routing:**
- ThinkingPlanningAgent identifies patient demographics domain
- Routes to GENIE_PATIENT agent
- Returns direct answer

### 2. Multi-Space with JOIN (Fast Route)
**Example:** "How many patients over 50 are on Voltaren?"

**Routing:**
- Identifies need for both patient and medication data
- Recognizes common key (patient_id) for JOIN
- SQLSynthesisAgent creates unified SQL
- SQLExecutionAgent executes across both tables
- Returns combined result quickly

### 3. Multi-Space with JOIN (Slow Route)
**Example:** "Show patients diagnosed with lung cancer who are on chemotherapy"

**Routing:**
- Queries each Genie agent separately
- Collects individual SQL queries
- SQLSynthesisAgent combines them
- SQLExecutionAgent runs final query
- Returns comprehensive result with full context

### 4. Multi-Space without JOIN (Verbal Merge)
**Example:** "What are common diagnoses and what are common medications?"

**Routing:**
- Runs separate queries on different spaces
- No JOIN needed - different question parts
- Verbally merges answers into coherent response

### 5. Unclear Queries (Clarification)
**Example:** "Tell me about cancer patients"

**Response:**
- ThinkingPlanningAgent identifies ambiguity
- Returns clarification options:
  1. "Do you mean the total count of cancer patients?"
  2. "Do you mean demographics of cancer patients?"
  3. "Do you mean treatment information for cancer patients?"
- User selects option, query re-executed

## 🔧 Configuration

### Genie Spaces

Configure available Genie spaces in `agent.py`:

```python
GENIE_SPACES = [
    Genie(
        space_id="01f072dbd668159d99934dfd3b17f544",
        name="GENIE_PATIENT",
        description="Patient demographics, age, ECOG scores, appointments, insurance"
    ),
    Genie(
        space_id="01f08f4d1f5f172ea825ec8c9a3c6064",
        name="MEDICATIONS",
        description="Patient medications, prescriptions, drug names, dosages"
    ),
    # ... more spaces
]
```

### Vector Search

Update vector search function in environment or code:

```python
VECTOR_SEARCH_FUNCTION = "catalog.schema.search_genie_spaces"
```

### LLM Endpoint

Configure LLM endpoint:

```python
LLM_ENDPOINT_NAME = "databricks-claude-sonnet-4-5"
```

## 📊 Monitoring & Observability

### MLflow Traces

All agent interactions are logged to MLflow with full traces:
- Query planning decisions
- Agent routing choices
- SQL generation steps
- Execution results

View traces in MLflow UI:
```
/ml/experiments/{experiment_id}/runs/{run_id}
```

### Performance Metrics

Monitor key metrics:
- Query response time
- Success rate by query type
- Agent routing accuracy
- SQL execution efficiency

### Serving Endpoint Metrics

View endpoint metrics in Databricks:
- Request latency
- Throughput
- Error rates
- Resource utilization

## 🛡️ Privacy & Security

### Data Protection

- **No PII exposure**: Individual patient IDs never returned
- **Count thresholds**: Results < 10 shown as "Count is less than 10"
- **Aggregations only**: Only aggregate statistics provided
- **Age bucketing**: Ages > 89 aggregated to "90 and over"

### Access Control

- Unity Catalog manages table-level permissions
- Model Serving enforces authentication
- Genie space permissions honored
- Audit logs track all queries

## 🧪 Testing

### Run Test Suite

```python
# Execute test cells in 05_Multi_Agent_System.py
# Tests include:
# - Available agents check
# - Single-space queries
# - Multi-space queries with/without joins
# - Clarification flow
# - Complex multi-domain queries
```

### Performance Benchmarks

Average response times (on small workload):
- Single-space queries: ~2-3 seconds
- Multi-space fast route: ~3-5 seconds
- Multi-space slow route: ~5-10 seconds
- Clarification requests: ~1-2 seconds

## 🐛 Troubleshooting

### Common Issues

**Issue:** Vector search index not found
```python
# Solution: Run 04_VS_Enriched_Genie_Spaces.py first
```

**Issue:** Genie space access denied
```python
# Solution: Verify Unity Catalog permissions and Genie space access
```

**Issue:** LLM endpoint timeout
```python
# Solution: Check endpoint status, increase timeout, or switch endpoint
```

**Issue:** SQL execution fails
```python
# Solution: Check table permissions, verify SQL syntax in traces
```

## 📚 Additional Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Databricks Agents Guide](https://docs.databricks.com/generative-ai/agent-framework/)
- [Databricks Genie Documentation](https://docs.databricks.com/genie/)
- [Vector Search Guide](https://docs.databricks.com/vector-search/)

## 🤝 Contributing

To extend the system:

1. **Add new Genie spaces**: Update `GENIE_SPACES` in `agent.py`
2. **Add new agents**: Create agent class and register with supervisor
3. **Enhance planning**: Modify `ThinkingPlanningAgent.analyze_query()`
4. **Improve SQL synthesis**: Enhance `SQLSynthesisAgent` prompts
5. **Add tools**: Register UC functions and add to `IN_CODE_AGENTS`

## 📝 License

Internal use only - KUMC POC project

## 👥 Authors

- Implementation based on requirements in `Instructions/01_overall.md`
- Built with Databricks LangGraph Supervisor framework
- Integrates Databricks Genie, Vector Search, and Model Serving

## 🎉 Acknowledgments

- Reference implementation: `Super_Agent.ipynb`
- Vector search example: `03_VS_generation.py`
- Table metadata pattern: `01_Table_MetaInfo_Update.py`

