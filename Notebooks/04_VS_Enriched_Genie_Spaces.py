# Databricks notebook source
# MAGIC %md
# MAGIC # Vector Search Index for Enriched Genie Spaces
# MAGIC 
# MAGIC This notebook creates a vector search index on enriched Genie space metadata.
# MAGIC The index enables semantic search to find relevant Genie spaces for user questions.

# COMMAND ----------

# MAGIC %pip install -U databricks-vectorsearch
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import os
import time
from databricks.vector_search.client import VectorSearchClient

# COMMAND ----------

# DBTITLE 1,Setup Parameters

dbutils.widgets.removeAll()

dbutils.widgets.text("catalog_name", os.getenv("CATALOG_NAME", "yyang"))
dbutils.widgets.text("schema_name", os.getenv("SCHEMA_NAME", "multi_agent_genie"))
dbutils.widgets.text("source_table", os.getenv("SOURCE_TABLE", "enriched_genie_docs_chunks"))
dbutils.widgets.text("vs_endpoint_name", os.getenv("VS_ENDPOINT_NAME", "genie_multi_agent_vs"))
dbutils.widgets.text("embedding_model", os.getenv("EMBEDDING_MODEL", "databricks-gte-large-en"))
dbutils.widgets.text("pipeline_type", os.getenv("PIPELINE_TYPE", "TRIGGERED"))

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")
source_table = dbutils.widgets.get("source_table")
vs_endpoint_name = dbutils.widgets.get("vs_endpoint_name")
embedding_model = dbutils.widgets.get("embedding_model")
pipeline_type = dbutils.widgets.get("pipeline_type")

# Construct fully qualified table names
source_table_name = f"{catalog_name}.{schema_name}.{source_table}"
index_name = f"{catalog_name}.{schema_name}.{source_table}_vs_index"

print(f"Source Table: {source_table_name}")
print(f"VS Endpoint: {vs_endpoint_name}")
print(f"Index Name: {index_name}")
print(f"Embedding Model: {embedding_model}")
print(f"Pipeline Type: {pipeline_type}")
print("\nNote: Using multi-level chunks table with space_summary, table_overview, and column_detail chunks")

# COMMAND ----------

# DBTITLE 1,Verify Source Table

# Check if source table exists
try:
    df_source = spark.table(source_table_name)
    print(f"✓ Source table exists with {df_source.count()} records")
    display(df_source.limit(5))
except Exception as e:
    raise Exception(f"Source table {source_table_name} not found. Please run 02_Table_MetaInfo_Enrichment.py first.") from e

# COMMAND ----------

# DBTITLE 1,Enable Change Data Feed

# Enable CDC for delta sync
try:
    spark.sql(f"ALTER TABLE {source_table_name} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    print(f"✓ Enabled Change Data Feed on {source_table_name}")
except Exception as e:
    print(f"Note: {str(e)}")

# COMMAND ----------

# DBTITLE 1,Create or Get Vector Search Endpoint

client = VectorSearchClient()

# Format endpoint name (lowercase, max 49 chars)
vs_endpoint_name = f"vs_endpoint_{vs_endpoint_name}".lower()[:49]

# Check if endpoint exists
try:
    endpoints = client.list_endpoints().get('endpoints', [])
    endpoint_names = [ep['name'] for ep in endpoints]
    
    if vs_endpoint_name in endpoint_names:
        print(f"✓ VS endpoint '{vs_endpoint_name}' already exists")
        endpoint = client.get_endpoint(vs_endpoint_name)
    else:
        print(f"Creating VS endpoint '{vs_endpoint_name}'...")
        endpoint = client.create_endpoint(
            name=vs_endpoint_name, 
            endpoint_type="STANDARD"
        )
        print(f"✓ Created VS endpoint '{vs_endpoint_name}'")
except Exception as e:
    print(f"Error with endpoint: {str(e)}")
    raise

# COMMAND ----------

# DBTITLE 1,Wait for Endpoint to be Ready

print(f"Waiting for endpoint '{vs_endpoint_name}' to be ready...")
client.wait_for_endpoint(vs_endpoint_name, "ONLINE")
print(f"✓ Endpoint '{vs_endpoint_name}' is online and ready")

# COMMAND ----------

# DBTITLE 1,Create Delta Sync Vector Search Index

print(f"Creating vector search index: {index_name}")
print(f"  Source: {source_table_name}")
print(f"  Embedding column: searchable_content")
print(f"  Primary key: chunk_id")
print(f"  Embedding model: {embedding_model}")

try:
    # Check if index already exists
    try:
        existing_index = client.get_index(index_name=index_name)
        print(f"Index '{index_name}' already exists. Deleting and recreating...")
        client.delete_index(index_name=index_name)
        time.sleep(5)  # Wait for deletion to complete
    except Exception:
        print(f"Index does not exist, creating new...")
    
    # Create new index with metadata filters
    index = client.create_delta_sync_index(
        endpoint_name=vs_endpoint_name,
        source_table_name=source_table_name,
        index_name=index_name,
        pipeline_type=pipeline_type,
        primary_key="chunk_id",
        embedding_source_column="searchable_content",
        embedding_model_endpoint_name=embedding_model
    )
    
    print(f"✓ Vector search index creation initiated: {index_name}")
    print(f"  Metadata fields available for filtering:")
    print(f"    - chunk_type (space_summary, table_overview, column_detail)")
    print(f"    - table_name, column_name")
    print(f"    - is_categorical, is_temporal, is_identifier, has_value_dictionary")
    
except Exception as e:
    print(f"Error creating index: {str(e)}")
    raise

# COMMAND ----------

# DBTITLE 1,Wait for Index to be Online

print("Waiting for index to be ONLINE...")
max_wait_time = 600  # 10 minutes
start_time = time.time()

while time.time() - start_time < max_wait_time:
    try:
        index_status = index.describe()
        detailed_state = index_status.get('status', {}).get('detailed_state', '')
        
        print(f"  Current state: {detailed_state}")
        
        if detailed_state.startswith('ONLINE'):
            print(f"✓ Index is ONLINE and ready to use!")
            break
        elif 'FAILED' in detailed_state:
            print(f"✗ Index creation failed: {detailed_state}")
            print(f"Full status: {index_status}")
            raise Exception(f"Index creation failed: {detailed_state}")
        
        time.sleep(10)
    except Exception as e:
        if time.time() - start_time >= max_wait_time:
            raise Exception(f"Timeout waiting for index to be online: {str(e)}")
        time.sleep(10)

print("\nIndex Details:")
display(index.describe())

# COMMAND ----------

# DBTITLE 1,Test Vector Search with Multi-Level Chunks

print("\n" + "="*80)
print("Testing Vector Search with Multi-Level Chunks")
print("="*80)

# Test 1: General queries across all chunk types
print("\n" + "="*80)
print("Test 1: General Semantic Search (All Chunk Types)")
print("="*80)

test_queries = [
    "patient age and demographics information",
    "medication prescriptions and drug information",
    "cancer diagnosis and staging"
]

for query in test_queries:
    print(f"\nQuery: {query}")
    print("-" * 80)
    
    try:
        result_df = spark.sql(f"""
            SELECT chunk_id, chunk_type, space_title, table_name, column_name, score
            FROM vector_search(
                index => '{index_name}',
                query => '{query}',
                num_results => 5
            )
            ORDER BY score DESC
        """)
        
        display(result_df)
    except Exception as e:
        print(f"Error searching: {str(e)}")

# Test 2: Space-level queries (filtered to space_summary chunks)
print("\n" + "="*80)
print("Test 2: Space Discovery (Space Summary Chunks Only)")
print("="*80)

space_queries = [
    "What data is available for patient claims analysis?",
    "What tables contain medical claims information?"
]

for query in space_queries:
    print(f"\nQuery: {query}")
    print("-" * 80)
    
    try:
        result_df = spark.sql(f"""
            SELECT chunk_id, chunk_type, space_title, score
            FROM vector_search(
                index => '{index_name}',
                query => '{query}',
                num_results => 3,
                filters => 'chunk_type = "space_summary"'
            )
            ORDER BY score DESC
        """)
        
        display(result_df)
    except Exception as e:
        print(f"Error searching: {str(e)}")

# Test 3: Table-level queries (filtered to table_overview chunks)
print("\n" + "="*80)
print("Test 3: Table Selection (Table Overview Chunks Only)")
print("="*80)

table_queries = [
    "What tables have date fields for temporal analysis?",
    "Which tables contain patient demographics?"
]

for query in table_queries:
    print(f"\nQuery: {query}")
    print("-" * 80)
    
    try:
        result_df = spark.sql(f"""
            SELECT chunk_id, chunk_type, space_title, table_name, is_temporal, score
            FROM vector_search(
                index => '{index_name}',
                query => '{query}',
                num_results => 5,
                filters => 'chunk_type = "table_overview"'
            )
            ORDER BY score DESC
        """)
        
        display(result_df)
    except Exception as e:
        print(f"Error searching: {str(e)}")

# Test 4: Column-level queries with metadata filters
print("\n" + "="*80)
print("Test 4: Column Discovery with Metadata Filters")
print("="*80)

# Find categorical columns
print("\nFind categorical columns with valid value sets:")
try:
    result_df = spark.sql(f"""
        SELECT chunk_id, table_name, column_name, score
        FROM vector_search(
            index => '{index_name}',
            query => 'location or place of service',
            num_results => 5,
            filters => 'chunk_type = "column_detail" AND has_value_dictionary = true'
        )
        ORDER BY score DESC
    """)
    display(result_df)
except Exception as e:
    print(f"Error searching: {str(e)}")

# Find identifier columns
print("\nFind patient identifier columns:")
try:
    result_df = spark.sql(f"""
        SELECT chunk_id, table_name, column_name, is_identifier, score
        FROM vector_search(
            index => '{index_name}',
            query => 'patient identifier or patient id',
            num_results => 5,
            filters => 'chunk_type = "column_detail" AND is_identifier = true'
        )
        ORDER BY score DESC
    """)
    display(result_df)
except Exception as e:
    print(f"Error searching: {str(e)}")

# Find temporal columns
print("\nFind date/time columns:")
try:
    result_df = spark.sql(f"""
        SELECT chunk_id, table_name, column_name, is_temporal, score
        FROM vector_search(
            index => '{index_name}',
            query => 'service date or claim date',
            num_results => 5,
            filters => 'chunk_type = "column_detail" AND is_temporal = true'
        )
        ORDER BY score DESC
    """)
    display(result_df)
except Exception as e:
    print(f"Error searching: {str(e)}")

# COMMAND ----------

# DBTITLE 1,Create Helper Functions for Agents

# Create UDF-style helper functions for use in multi-agent system

def create_genie_chunk_search_function():
    """
    Returns a function that can be used by agents to search for relevant chunks.
    Supports filtering by chunk type and metadata.
    """
    def search_genie_chunks(query: str, 
                           num_results: int = 5, 
                           chunk_type: str = None,
                           filter_categorical: bool = None,
                           filter_temporal: bool = None,
                           filter_identifier: bool = None):
        """
        Search for relevant chunks based on a query with optional filters.
        
        Args:
            query: Natural language query
            num_results: Number of results to return
            chunk_type: Filter by chunk type (space_summary, table_overview, column_detail)
            filter_categorical: If True, only return categorical columns
            filter_temporal: If True, only return temporal columns
            filter_identifier: If True, only return identifier columns
            
        Returns:
            List of Row objects with chunk information
        """
        # Build filter string
        filters = []
        if chunk_type:
            filters.append(f'chunk_type = "{chunk_type}"')
        if filter_categorical is not None:
            filters.append(f'is_categorical = {str(filter_categorical).lower()}')
        if filter_temporal is not None:
            filters.append(f'is_temporal = {str(filter_temporal).lower()}')
        if filter_identifier is not None:
            filters.append(f'is_identifier = {str(filter_identifier).lower()}')
        
        filter_clause = " AND ".join(filters) if filters else None
        
        # Build query
        if filter_clause:
            sql = f"""
                SELECT chunk_id, chunk_type, space_id, space_title, table_name, column_name, 
                       is_categorical, is_temporal, is_identifier, has_value_dictionary, score
                FROM vector_search(
                    index => '{index_name}',
                    query => '{query}',
                    num_results => {num_results},
                    filters => '{filter_clause}'
                )
                ORDER BY score DESC
            """
        else:
            sql = f"""
                SELECT chunk_id, chunk_type, space_id, space_title, table_name, column_name,
                       is_categorical, is_temporal, is_identifier, has_value_dictionary, score
                FROM vector_search(
                    index => '{index_name}',
                    query => '{query}',
                    num_results => {num_results}
                )
                ORDER BY score DESC
            """
        
        result_df = spark.sql(sql)
        return result_df.collect()
    
    return search_genie_chunks


def create_genie_space_search_function():
    """
    Convenience function for space-level search (space_summary chunks only).
    """
    chunk_search = create_genie_chunk_search_function()
    
    def search_genie_spaces(query: str, num_results: int = 3):
        """
        Search for relevant Genie spaces based on a query.
        
        Args:
            query: Natural language query
            num_results: Number of results to return
            
        Returns:
            List of Row objects with space information
        """
        return chunk_search(query, num_results=num_results, chunk_type="space_summary")
    
    return search_genie_spaces


def create_column_search_function():
    """
    Convenience function for column-level search (column_detail chunks only).
    """
    chunk_search = create_genie_chunk_search_function()
    
    def search_columns(query: str, 
                      num_results: int = 5,
                      categorical_only: bool = False,
                      temporal_only: bool = False,
                      identifier_only: bool = False):
        """
        Search for relevant columns based on a query.
        
        Args:
            query: Natural language query
            num_results: Number of results to return
            categorical_only: Only return categorical columns with value dictionaries
            temporal_only: Only return date/time columns
            identifier_only: Only return identifier columns
            
        Returns:
            List of Row objects with column information
        """
        return chunk_search(
            query, 
            num_results=num_results, 
            chunk_type="column_detail",
            filter_categorical=categorical_only if categorical_only else None,
            filter_temporal=temporal_only if temporal_only else None,
            filter_identifier=identifier_only if identifier_only else None
        )
    
    return search_columns


# Test the functions
print("\n" + "="*80)
print("Testing Helper Functions")
print("="*80)

# Test 1: General chunk search
print("\nTest 1: General chunk search")
chunk_search_fn = create_genie_chunk_search_function()
results = chunk_search_fn("patient demographics", num_results=3)
for r in results:
    print(f"  [{r.chunk_type}] {r.space_title} - {r.table_name if r.table_name else 'N/A'} - {r.column_name if r.column_name else 'N/A'} (Score: {r.score:.4f})")

# Test 2: Space-level search
print("\nTest 2: Space-level search")
space_search_fn = create_genie_space_search_function()
results = space_search_fn("What spaces contain patient data?", num_results=2)
for r in results:
    print(f"  Space: {r.space_title} (ID: {r.space_id}) - Score: {r.score:.4f}")

# Test 3: Column search with filters
print("\nTest 3: Column search - categorical columns only")
column_search_fn = create_column_search_function()
results = column_search_fn("type of healthcare facility", num_results=3, categorical_only=True)
for r in results:
    print(f"  Column: {r.table_name}.{r.column_name} - Categorical: {r.is_categorical} - Score: {r.score:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Vector Search Tool as UC Function (Optional)
# MAGIC 
# MAGIC This creates a Unity Catalog function that can be called by agents.

# COMMAND ----------

# DBTITLE 1,Create UC Functions for Vector Search

# Function 1: General chunk search
uc_chunk_search_name = f"{catalog_name}.{schema_name}.search_genie_chunks"

try:
    spark.sql(f"DROP FUNCTION IF EXISTS {uc_chunk_search_name}")
except:
    pass

create_chunk_search_sql = f"""
CREATE OR REPLACE FUNCTION {uc_chunk_search_name}(
    query STRING,
    num_results INT
)
RETURNS TABLE(
    chunk_id INT, 
    chunk_type STRING, 
    space_id STRING, 
    space_title STRING, 
    table_name STRING,
    column_name STRING,
    is_categorical BOOLEAN,
    is_temporal BOOLEAN,
    is_identifier BOOLEAN,
    has_value_dictionary BOOLEAN,
    score DOUBLE
)
LANGUAGE SQL
COMMENT 'Search for relevant chunks (space/table/column level) based on natural language query'
RETURN SELECT chunk_id, chunk_type, space_id, space_title, table_name, column_name,
              is_categorical, is_temporal, is_identifier, has_value_dictionary, score
FROM vector_search(
    index => '{index_name}',
    query => query,
    num_results => num_results
)
ORDER BY score DESC
"""

spark.sql(create_chunk_search_sql)
print(f"✓ Created UC function: {uc_chunk_search_name}")

# Function 2: Space-level search (space_summary chunks only)
uc_space_search_name = f"{catalog_name}.{schema_name}.search_genie_spaces"

try:
    spark.sql(f"DROP FUNCTION IF EXISTS {uc_space_search_name}")
except:
    pass

create_space_search_sql = f"""
CREATE OR REPLACE FUNCTION {uc_space_search_name}(
    query STRING,
    num_results INT
)
RETURNS TABLE(space_id STRING, space_title STRING, score DOUBLE)
LANGUAGE SQL
COMMENT 'Search for relevant Genie spaces (space-level only) based on natural language query'
RETURN SELECT space_id, space_title, score
FROM vector_search(
    index => '{index_name}',
    query => query,
    num_results => num_results,
    filters => 'chunk_type = "space_summary"'
)
ORDER BY score DESC
"""

spark.sql(create_space_search_sql)
print(f"✓ Created UC function: {uc_space_search_name}")

# Function 3: Column-level search with metadata filter
uc_column_search_name = f"{catalog_name}.{schema_name}.search_columns"

try:
    spark.sql(f"DROP FUNCTION IF EXISTS {uc_column_search_name}")
except:
    pass

create_column_search_sql = f"""
CREATE OR REPLACE FUNCTION {uc_column_search_name}(
    query STRING,
    num_results INT
)
RETURNS TABLE(
    chunk_id INT,
    table_name STRING,
    column_name STRING,
    is_categorical BOOLEAN,
    is_temporal BOOLEAN,
    is_identifier BOOLEAN,
    has_value_dictionary BOOLEAN,
    score DOUBLE
)
LANGUAGE SQL
COMMENT 'Search for relevant columns (column-level only) based on natural language query'
RETURN SELECT chunk_id, table_name, column_name, is_categorical, is_temporal, 
              is_identifier, has_value_dictionary, score
FROM vector_search(
    index => '{index_name}',
    query => query,
    num_results => num_results,
    filters => 'chunk_type = "column_detail"'
)
ORDER BY score DESC
"""

spark.sql(create_column_search_sql)
print(f"✓ Created UC function: {uc_column_search_name}")

# Test the functions
print("\n" + "="*80)
print("Testing UC Functions")
print("="*80)

# Test chunk search
print("\n1. General chunk search:")
test_result = spark.sql(f"""
    SELECT chunk_type, space_title, table_name, column_name, score
    FROM {uc_chunk_search_name}(
        'patient age demographics',
        5
    )
""")
display(test_result)

# Test space search
print("\n2. Space-level search:")
test_result = spark.sql(f"""
    SELECT * FROM {uc_space_search_name}(
        'What spaces contain claims data?',
        3
    )
""")
display(test_result)

# Test column search
print("\n3. Column-level search:")
test_result = spark.sql(f"""
    SELECT table_name, column_name, is_categorical, has_value_dictionary, score
    FROM {uc_column_search_name}(
        'location or facility type',
        3
    )
""")
display(test_result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC 
# MAGIC This notebook has:
# MAGIC 1. ✓ Created vector search endpoint
# MAGIC 2. ✓ Built managed delta sync vector search index on multi-level chunks
# MAGIC 3. ✓ Tested semantic search with metadata filtering across all chunk types:
# MAGIC    - **Space Summary**: Overview of available spaces and tables
# MAGIC    - **Table Overview**: Column lists and table structure
# MAGIC    - **Column Detail**: Full descriptions, sample values, value dictionaries
# MAGIC 4. ✓ Created helper functions for agent integration with filtering support
# MAGIC 5. ✓ Registered UC functions for easy agent access:
# MAGIC    - `search_genie_chunks()`: General search across all chunk types
# MAGIC    - `search_genie_spaces()`: Space-level search only
# MAGIC    - `search_columns()`: Column-level search only
# MAGIC 
# MAGIC **Key Outputs:**
# MAGIC - Vector Search Index: `{index_name}`
# MAGIC - UC Functions: 
# MAGIC   - `{catalog_name}.{schema_name}.search_genie_chunks`
# MAGIC   - `{catalog_name}.{schema_name}.search_genie_spaces`
# MAGIC   - `{catalog_name}.{schema_name}.search_columns`
# MAGIC 
# MAGIC **Metadata Filters Available:**
# MAGIC - `chunk_type`: Filter by granularity (space_summary, table_overview, column_detail)
# MAGIC - `table_name`, `column_name`: Filter to specific schema objects
# MAGIC - `is_categorical`, `is_temporal`, `is_identifier`: Filter by column characteristics
# MAGIC - `has_value_dictionary`: Find columns with enumerated value sets
# MAGIC 
# MAGIC Next: Build multi-agent system that uses this index (05_Multi_Agent_System.py)

