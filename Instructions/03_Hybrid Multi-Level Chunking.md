# Chunking Strategies for Genie Space Metadata in Vector Search

For the hierarchical JSON metadata structure from Databricks Genie Spaces (containing space → tables → columns → sample values), the **Hybrid Multi-Level Chunking Strategy** is the recommended approach. This strategy creates chunks at multiple granularities while preserving the relationships inherent in your schema metadata.

## Recommended Strategy: Hybrid Multi-Level Chunking

Create three levels of chunks, each serving different query types:

### Level 1: Space Summary Chunk
A single chunk per Genie Space that provides an overview of all available tables, their purposes, and common join keys. This answers questions like *"What data is available?"* or *"What tables contain claims information?"*[3]

### Level 2: Table Overview Chunks
One chunk per table containing the table identifier, a list of all columns with their types, and summaries of key categorical fields. This level is optimal for table selection queries and understanding what analysis is possible with a given table[2].

### Level 3: Column Detail Chunks
One chunk per column with the full enhanced description, data type, limited sample values (3-5 examples rather than 100), and the top values from value dictionaries. These chunks answer specific questions like *"What does the NDC field mean?"* or *"What are valid values for location_of_care?"*[1]

## Chunk Structure Examples

**Column Detail Chunk (location_of_care):**
```
Column: location_of_care
Table: medical_claim
Space: HealthVerityClaims
Data Type: string (categorical)

Description: The type of healthcare facility or setting where 
services were rendered. Categorizes the place of service.

Top Values:
  - OFFICE/CLINIC: 146,301 records
  - HOSPITAL OP: 67,236 records
  - INDEPENDENT LAB: 22,167 records
  - HOSPITAL ER: 12,484 records
```

**Table Overview Chunk (medical_claim):**
```
Table: medical_claim
Full Path: healthverity_claims_sample_patient_dataset.hv_claims_sample.medical_claim
Space: HealthVerityClaims

Columns (6 total):
• claim_id (string): Unique claim identifier
• patient_id (string): Anonymized patient identifier
• date_service (date): Service start date
• date_service_end (date): Service end date
• location_of_care (string): Healthcare facility type
• pay_type (string): Insurance payer type

Key Categorical Fields:
• location_of_care: OFFICE/CLINIC, HOSPITAL OP, INDEPENDENT LAB
• pay_type: MEDICARE, COMMERCIAL, MEDICAID
```

## Metadata Fields for Filtered Retrieval

Each chunk should include searchable metadata fields that enable filtered queries in Databricks Vector Search[4]:

| Metadata Field | Purpose |
|----------------|---------|
| `chunk_type` | Filter by granularity (space_summary, table_overview, column_detail) |
| `table_name` | Filter to specific table context |
| `column_name` | Direct column lookup |
| `is_categorical` | Find enumerated fields with valid values |
| `is_temporal` | Find date/time columns |
| `is_identifier` | Find key/ID columns |
| `has_value_dictionary` | Find columns with known value sets |

## Query Strategy Examples

For different question types, you can combine semantic search with metadata filtering:

- **"What columns contain patient identifiers?"** → Search column_detail chunks, filter `is_identifier=true`
- **"What tables have date fields?"** → Search table_overview chunks (dates mentioned in column list)
- **"What are valid values for pay_type?"** → Search column_detail chunks, filter `has_value_dictionary=true`
- **"How do medical and pharmacy claims relate?"** → Search space_summary chunk for join keys

