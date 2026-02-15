"""
FastAPI routes following APX patterns.
All routes have response_model and operation_id (required for OpenAPI generation).
"""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from .models import *
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from databricks.sdk.service.jobs import Task, NotebookTask, JobEnvironment, Source
from databricks.sdk.service.compute import Environment
from databricks import sql
import uuid
import threading
import os
import json
import asyncio
from datetime import datetime

# Initialize SDK
config = Config()
client = WorkspaceClient(config=config)
warehouse_id = "a4ed2ccbda385db9"

# In-memory storage
_selection: TableSelectionOut = TableSelectionOut(table_fqns=[], count=0)
_graph_data: Optional[GraphDataOut] = None
_genie_rooms = []
_genie_creation_status: Optional[GenieCreationStatusOut] = None

api = APIRouter(prefix="/api")

# ============================================================================
# UC CATALOG BROWSER ROUTES
# ============================================================================

@api.get("/uc/catalogs", response_model=List[CatalogOut], operation_id="listCatalogs")
async def list_catalogs():
    """List all catalogs."""
    try:
        catalogs = list(client.catalogs.list())
        return [CatalogOut(
            name=cat.name,
            comment=cat.comment,
            owner=cat.owner
        ) for cat in catalogs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/uc/catalogs/{catalog}/schemas", response_model=List[SchemaOut], operation_id="listSchemas")
async def list_schemas(catalog: str):
    """List schemas in a catalog."""
    try:
        schemas = list(client.schemas.list(catalog_name=catalog))
        return [SchemaOut(
            name=schema.name,
            catalog_name=schema.catalog_name,
            comment=schema.comment,
            owner=schema.owner
        ) for schema in schemas]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/uc/catalogs/{catalog}/schemas/{schema}/tables", response_model=List[TableOut], operation_id="listTables")
async def list_tables(catalog: str, schema: str):
    """List tables in a schema."""
    try:
        tables = list(client.tables.list(catalog_name=catalog, schema_name=schema))
        return [TableOut(
            name=table.name,
            catalog_name=table.catalog_name,
            schema_name=table.schema_name,
            table_type=table.table_type.value if table.table_type else 'TABLE',
            comment=table.comment,
            owner=table.owner,
            fqn=f"{table.catalog_name}.{table.schema_name}.{table.name}"
        ) for table in tables]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/uc/tables/{fqn:path}/columns", response_model=List[ColumnOut], operation_id="getTableColumns")
async def get_table_columns(fqn: str):
    """Get columns for a table."""
    try:
        table = client.tables.get(full_name=fqn)
        if not table.columns:
            return []
        
        return [ColumnOut(
            name=col.name,
            type_text=col.type_text,
            type_name=col.type_name.value if col.type_name else col.type_text,
            comment=col.comment or '',
            nullable=col.nullable if col.nullable is not None else True,
            position=col.position
        ) for col in table.columns]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.post("/uc/selection", response_model=TableSelectionOut, operation_id="saveSelection")
async def save_selection(selection: TableSelectionIn):
    """Save table selection."""
    global _selection
    _selection = TableSelectionOut(
        table_fqns=selection.table_fqns,
        count=len(selection.table_fqns)
    )
    return _selection


@api.get("/uc/selection", response_model=TableSelectionOut, operation_id="getSelection")
async def get_selection():
    """Get current table selection."""
    return _selection


# ============================================================================
# ENRICHMENT ROUTES - DATABRICKS JOB SUBMISSION
# ============================================================================

# Configuration for enrichment job
ENRICHMENT_SCRIPT_PATH = os.getenv(
    "ENRICHMENT_SCRIPT_PATH", 
    "/Workspace/Users/yang.yang@databricks.com/tables_to_genies/etl/enrich_tables_direct.py"
)

@api.post("/enrichment/run", response_model=EnrichmentJobOut, operation_id="runEnrichment")
async def run_enrichment(enrichment_in: EnrichmentRunIn):
    """Run table enrichment job on Databricks."""
    
    # Prepare parameters for the job
    table_fqns_str = ','.join(enrichment_in.table_fqns)
    
    # Job name for persistent job definition
    job_name = "Table Enrichment Job"
    
    # Check if job already exists
    existing_jobs = list(client.jobs.list(name=job_name))
    
    if existing_jobs:
        # Use existing job
        job_id = existing_jobs[0].job_id
        print(f"Using existing job: {job_id}")
    else:
        # Create new persistent job using notebook task
        print(f"Creating new job: {job_name}")
        job = client.jobs.create(
            name=job_name,
            tasks=[
                Task(
                    task_key="enrich_tables",
                    notebook_task=NotebookTask(
                        notebook_path=ENRICHMENT_SCRIPT_PATH,
                        source=Source.WORKSPACE
                        # base_parameters will be overridden on each run via run_now()
                    ),
                    environment_key="serverless_env"
                )
            ],
            environments=[
                JobEnvironment(
                    environment_key="serverless_env",
                    spec=Environment(
                        client="1"  # Serverless environment
                    )
                )
            ]
        )
        job_id = job.job_id
        print(f"Created job: {job_id}")
    
    # Run the job with notebook parameters
    run_result = client.jobs.run_now(
        job_id=job_id,
        notebook_params={
            "tables": table_fqns_str,
            "sample_size": "20",
            "max_unique_values": "50",
            "llm_endpoint": "databricks-claude-sonnet-4-5",
            "metadata_table": enrichment_in.metadata_table,
            "chunks_table": enrichment_in.chunks_table,
            "write_mode": enrichment_in.write_mode
        }
    )
    
    # Get run details to access run_page_url
    run_details = client.jobs.get_run(run_id=run_result.run_id)
    job_url = run_details.run_page_url
    
    return EnrichmentJobOut(
        run_id=run_result.run_id,
        job_url=job_url,
        status=EnrichmentStatus.PENDING,
        table_count=len(enrichment_in.table_fqns),
        submitted_at=datetime.now().isoformat()
    )


@api.get("/enrichment/status/{run_id}", response_model=EnrichmentJobStatusOut, operation_id="getEnrichmentStatus")
async def get_enrichment_status(run_id: int):
    """Get Databricks job status."""
    
    try:
        run = client.jobs.get_run(run_id=run_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Job run not found: {str(e)}")
    
    # Map Databricks states to our status
    life_cycle_state = run.state.life_cycle_state.value if run.state.life_cycle_state else None
    result_state = run.state.result_state.value if run.state.result_state else None
    
    status = EnrichmentStatus.PENDING
    if life_cycle_state == "RUNNING" or life_cycle_state == "PENDING":
        status = EnrichmentStatus.RUNNING
    elif life_cycle_state == "TERMINATING":
        status = EnrichmentStatus.RUNNING  # Still considered running
    elif life_cycle_state == "TERMINATED":
        if result_state == "SUCCESS":
            status = EnrichmentStatus.COMPLETED
        elif result_state == "FAILED":
            status = EnrichmentStatus.FAILED
        elif result_state == "CANCELED":
            status = EnrichmentStatus.CANCELLED
        else:
            status = EnrichmentStatus.FAILED  # Default to failed for unknown result states
    elif life_cycle_state == "SKIPPED":
        status = EnrichmentStatus.CANCELLED
    elif life_cycle_state == "INTERNAL_ERROR":
        status = EnrichmentStatus.FAILED
    
    # Use the correct job URL from Databricks
    job_url = run.run_page_url
    
    return EnrichmentJobStatusOut(
        run_id=run_id,
        status=status,
        job_url=job_url,
        life_cycle_state=life_cycle_state,
        result_state=result_state,
        state_message=run.state.state_message,
        start_time=run.start_time,
        end_time=run.end_time,
        duration_ms=(run.end_time - run.start_time) if run.end_time and run.start_time else None
    )


@api.get("/enrichment/results", response_model=List[EnrichmentResultListOut], operation_id="listEnrichmentResults")
async def list_enrichment_results():
    """List enriched tables from Unity Catalog."""
    
    try:
        # Query enriched results from UC table
        conn = sql.connect(
            server_hostname=config.host,
            http_path=f"/sql/1.0/warehouses/{warehouse_id}",
            credentials_provider=lambda: config.authenticate,
        )
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_fqn, enriched_doc 
            FROM yyang.multi_agent_genie.enriched_tables_direct 
            WHERE enriched = true
            ORDER BY id DESC
            LIMIT 100
        """)
        
        results = []
        for row in cursor.fetchall():
            table_fqn = row[0]
            enriched_doc = json.loads(row[1])
            
            results.append(EnrichmentResultListOut(
                fqn=table_fqn,
                column_count=enriched_doc.get('total_columns', 0),
                enriched=enriched_doc.get('enriched', False)
            ))
        
        cursor.close()
        conn.close()
        
        return results
        
    except Exception as e:
        print(f"Error fetching enrichment results: {e}")
        return []


@api.get("/enrichment/results/{fqn:path}", response_model=EnrichmentResultOut, operation_id="getEnrichmentResult")
async def get_enrichment_result(fqn: str):
    """Get enrichment result for specific table from Unity Catalog."""
    
    try:
        conn = sql.connect(
            server_hostname=config.host,
            http_path=f"/sql/1.0/warehouses/{warehouse_id}",
            credentials_provider=lambda: config.authenticate,
        )
        
        cursor = conn.cursor()
        cursor.execute(
            "SELECT enriched_doc FROM yyang.multi_agent_genie.enriched_tables_direct WHERE table_fqn = ?",
            (fqn,)
        )
        
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Table {fqn} not found")
        
        enriched_doc = json.loads(row[0])
        
        # Convert to response model
        return EnrichmentResultOut(
            fqn=enriched_doc['table_fqn'],
            catalog=enriched_doc['catalog'],
            schema=enriched_doc['schema'],
            table=enriched_doc['table'],
            column_count=enriched_doc['total_columns'],
            columns=[
                ColumnEnriched(
                    name=col['column_name'],
                    type=col['data_type'],
                    comment=col.get('enhanced_comment', col.get('comment', '')),
                    sample_values=col.get('sample_values', [])
                )
                for col in enriched_doc['enriched_columns'][:10]
            ],
            enriched=enriched_doc['enriched'],
            timestamp=enriched_doc['enrichment_timestamp']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching result: {str(e)}")


# ============================================================================
# GRAPH ROUTES
# ============================================================================

@api.post("/graph/build", response_model=GraphBuildStatusOut, operation_id="buildGraph")
async def build_graph():
    """Build table relationship graph."""
    global _graph_data
    
    if not _enrichment_results:
        raise HTTPException(status_code=400, detail="No enrichment results available")
    
    try:
        # Simplified graph building (full GraphRAG implementation in graph_builder.py)
        import networkx as nx
        
        G = nx.Graph()
        
        # Add nodes
        for result in _enrichment_results:
            parts = result.fqn.split('.')
            G.add_node(result.fqn, **{
                'label': parts[2],
                'catalog': parts[0],
                'schema': parts[1],
                'column_count': result.column_count,
                'community': 0
            })
        
        # Add edges (same schema)
        nodes = list(G.nodes(data=True))
        for i, (node1, data1) in enumerate(nodes):
            for node2, data2 in nodes[i+1:]:
                if data1['schema'] == data2['schema']:
                    G.add_edge(node1, node2, weight=5, types='same_schema')
        
        # Convert to Cytoscape format
        elements = []
        for node, data in G.nodes(data=True):
            elements.append({'data': {'id': node, **data}})
        for source, target, data in G.edges(data=True):
            elements.append({'data': {'source': source, 'target': target, **data}})
        
        _graph_data = GraphDataOut(
            elements=elements,
            node_count=G.number_of_nodes(),
            edge_count=G.number_of_edges()
        )
        
        return GraphBuildStatusOut(job_id="graph-1", status=GraphBuildStatus.COMPLETED)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api.get("/graph/data", response_model=GraphDataOut, operation_id="getGraphData")
async def get_graph_data():
    """Get graph data."""
    if not _graph_data:
        raise HTTPException(status_code=404, detail="Graph not built yet")
    return _graph_data


# ============================================================================
# GENIE ROOM ROUTES
# ============================================================================

@api.post("/genie/rooms", response_model=GenieRoomOut, operation_id="createGenieRoom")
async def create_genie_room(room_in: GenieRoomIn):
    """Create a Genie room definition."""
    room = GenieRoomOut(
        id=f"room-{str(uuid.uuid4())[:8]}",
        name=room_in.name,
        tables=room_in.table_fqns,
        table_count=len(room_in.table_fqns)
    )
    _genie_rooms.append(room)
    return room


@api.get("/genie/rooms", response_model=List[GenieRoomListOut], operation_id="listGenieRooms")
async def list_genie_rooms():
    """List all planned Genie rooms."""
    return [GenieRoomListOut(
        id=r.id,
        name=r.name,
        table_count=r.table_count
    ) for r in _genie_rooms]


@api.delete("/genie/rooms/{room_id}", operation_id="deleteGenieRoom")
async def delete_genie_room(room_id: str):
    """Delete a planned room."""
    global _genie_rooms
    _genie_rooms = [r for r in _genie_rooms if r.id != room_id]
    return {"message": "Room deleted"}


def _create_rooms_task():
    """Background task for creating Genie spaces."""
    global _genie_creation_status
    
    try:
        for i, room in enumerate(_genie_creation_status.rooms):
            try:
                room['status'] = 'creating'
                
                # Create Genie space
                space = client.genie.create_space(
                    display_name=room['name'],
                    description=f"Genie space with {room['table_count']} tables"
                )
                
                # Update with table identifiers
                client.genie.update_space(
                    id=space.id,
                    display_name=room['name'],
                    table_identifiers=room['tables'],
                    sql_warehouse_id=warehouse_id
                )
                
                room['status'] = 'created'
                room['space_id'] = space.id
                room['url'] = f"https://{config.host}/sql/genie/{space.id}"
                
            except Exception as e:
                room['status'] = 'failed'
                room['error'] = str(e)
        
        _genie_creation_status.status = 'completed'
        
    except Exception as e:
        _genie_creation_status.status = 'failed'


@api.post("/genie/create-all", response_model=GenieCreationStatusOut, operation_id="createAllGenieRooms")
async def create_all_genie_rooms():
    """Create all planned Genie rooms."""
    global _genie_creation_status
    
    if not _genie_rooms:
        raise HTTPException(status_code=400, detail="No rooms planned")
    
    _genie_creation_status = GenieCreationStatusOut(
        status='creating',
        rooms=[{
            'id': r.id,
            'name': r.name,
            'tables': r.tables,
            'table_count': r.table_count,
            'status': 'pending',
            'space_id': None,
            'url': None,
            'error': None
        } for r in _genie_rooms]
    )
    
    thread = threading.Thread(target=_create_rooms_task)
    thread.daemon = True
    thread.start()
    
    return _genie_creation_status


@api.get("/genie/create-status", response_model=GenieCreationStatusOut, operation_id="getGenieCreationStatus")
async def get_genie_creation_status():
    """Get creation status."""
    if not _genie_creation_status:
        raise HTTPException(status_code=404, detail="No creation in progress")
    return _genie_creation_status


@api.get("/genie/created", response_model=List[CreatedGenieRoomOut], operation_id="listCreatedGenieRooms")
async def list_created_genie_rooms():
    """List created Genie rooms."""
    if not _genie_creation_status or _genie_creation_status.status != 'completed':
        return []
    
    return [CreatedGenieRoomOut(
        id=r['id'],
        name=r['name'],
        space_id=r['space_id'],
        url=r['url'],
        table_count=r['table_count'],
        status=GenieRoomStatus.CREATED
    ) for r in _genie_creation_status.rooms if r['status'] == 'created']


def _execute_preview_query(table_fqn: str):
    """Helper function to execute preview queries using Spark SQL."""
    from pyspark.sql import SparkSession
    from datetime import date, datetime
    from decimal import Decimal
    
    # Get or create Spark session
    spark = SparkSession.builder.getOrCreate()
    
    # Get row count
    count_df = spark.sql(f"SELECT COUNT(*) as count FROM {table_fqn}")
    row_count = count_df.collect()[0][0]
    
    # Get sample rows
    sample_df = spark.sql(f"SELECT * FROM {table_fqn} LIMIT 10")
    
    # Get column names
    columns = sample_df.columns
    
    # Convert rows to dictionaries with JSON-serializable types
    rows = []
    for row in sample_df.collect():
        row_dict = {}
        for col in columns:
            val = row[col]
            
            # Convert to JSON-serializable types
            if val is None:
                row_dict[col] = None
            elif isinstance(val, (date, datetime)):
                row_dict[col] = val.isoformat()
            elif isinstance(val, Decimal):
                row_dict[col] = float(val)
            elif isinstance(val, (bytes, bytearray)):
                row_dict[col] = val.hex()
            elif isinstance(val, (list, dict)):
                row_dict[col] = str(val) if len(str(val)) < 1000 else str(val)[:1000] + "..."
            else:
                val_str = str(val)
                row_dict[col] = val_str if len(val_str) < 1000 else val_str[:1000] + "..."
        
        rows.append(row_dict)
    
    return row_count, columns, rows

@api.get("/enrichment/preview/{table_fqn:path}", response_model=TablePreviewOut, operation_id="previewEnrichmentTable")
async def preview_enrichment_table(table_fqn: str):
    """Preview a table from Unity Catalog."""
    
    try:
        # Parse table FQN
        parts = table_fqn.split(".")
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail="Table FQN must be in format catalog.schema.table")
        
        catalog_name, schema_name, table_name = parts
        
        # Run blocking SDK call in thread pool to avoid blocking event loop
        row_count, columns, rows = await asyncio.to_thread(_execute_preview_query, table_fqn)
        
        return TablePreviewOut(
            table_fqn=table_fqn,
            row_count=row_count,
            columns=columns,
            sample_rows=rows
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview table: {str(e)}")
