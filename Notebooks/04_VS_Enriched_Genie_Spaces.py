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
dbutils.widgets.text("source_table", os.getenv("SOURCE_TABLE", "enriched_genie_docs_flattened"))
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
print(f"  Primary key: id")
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
    
    # Create new index
    index = client.create_delta_sync_index(
        endpoint_name=vs_endpoint_name,
        source_table_name=source_table_name,
        index_name=index_name,
        pipeline_type=pipeline_type,
        primary_key="id",
        embedding_source_column="searchable_content",
        embedding_model_endpoint_name=embedding_model
    )
    
    print(f"✓ Vector search index creation initiated: {index_name}")
    
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

# DBTITLE 1,Test Vector Search

print("\n" + "="*80)
print("Testing Vector Search")
print("="*80)

# Test queries
test_queries = [
    "patient age and demographics information",
    "medication prescriptions and drug information",
    "cancer diagnosis and staging",
    "laboratory test results and biomarkers",
    "treatment procedures and surgeries"
]

for query in test_queries:
    print(f"\nQuery: {query}")
    print("-" * 80)
    
    try:
        # SQL-based similarity search
        result_df = spark.sql(f"""
            SELECT space_id, space_title, score
            FROM vector_search(
                index => '{index_name}',
                query => '{query}',
                num_results => 3
            )
        """)
        
        display(result_df)
    except Exception as e:
        print(f"Error searching: {str(e)}")

# COMMAND ----------

# DBTITLE 1,Create Helper Functions for Agents

# Create UDF-style helper function for use in multi-agent system
def create_genie_space_search_function():
    """
    Returns a function that can be used by agents to search for relevant Genie spaces.
    """
    def search_genie_spaces(query: str, num_results: int = 5):
        """
        Search for relevant Genie spaces based on a query.
        
        Args:
            query: Natural language query
            num_results: Number of results to return
            
        Returns:
            List of dictionaries with space_id, space_title, and score
        """
        result_df = spark.sql(f"""
            SELECT space_id, space_title, score
            FROM vector_search(
                index => '{index_name}',
                query => '{query}',
                num_results => {num_results}
            )
        """)
        
        return result_df.collect()
    
    return search_genie_spaces

# Test the function
search_fn = create_genie_space_search_function()
results = search_fn("How many patients are older than 50?", num_results=3)

print("\nFunction Test Results:")
for r in results:
    print(f"  Space: {r.space_title} (ID: {r.space_id}) - Score: {r.score:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Vector Search Tool as UC Function (Optional)
# MAGIC 
# MAGIC This creates a Unity Catalog function that can be called by agents.

# COMMAND ----------

# DBTITLE 1,Create UC Function for Vector Search

uc_function_name = f"{catalog_name}.{schema_name}.search_genie_spaces"

# Drop if exists
try:
    spark.sql(f"DROP FUNCTION IF EXISTS {uc_function_name}")
except:
    pass

# Create function SQL
create_function_sql = f"""
CREATE OR REPLACE FUNCTION {uc_function_name}(
    query STRING,
    num_results INT
)
RETURNS TABLE(space_id STRING, space_title STRING, score DOUBLE)
LANGUAGE SQL
COMMENT 'Search for relevant Genie spaces based on natural language query'
RETURN SELECT space_id, space_title, score
FROM vector_search(
    index => '{index_name}',
    query => query,
    num_results => num_results
)
"""

spark.sql(create_function_sql)
print(f"✓ Created UC function: {uc_function_name}")

# Test the function
test_result = spark.sql(f"""
    SELECT * FROM {uc_function_name}(
        'patient demographics and age information',
        3
    )
""")

print("\nUC Function Test:")
display(test_result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC 
# MAGIC This notebook has:
# MAGIC 1. ✓ Created vector search endpoint
# MAGIC 2. ✓ Built managed delta sync vector search index on enriched Genie docs
# MAGIC 3. ✓ Tested semantic search for finding relevant Genie spaces
# MAGIC 4. ✓ Created helper functions for agent integration
# MAGIC 5. ✓ Registered UC function for easy agent access
# MAGIC 
# MAGIC **Key Outputs:**
# MAGIC - Vector Search Index: `{index_name}`
# MAGIC - UC Search Function: `{uc_function_name}`
# MAGIC 
# MAGIC Next: Build multi-agent system that uses this index (agent.py)

