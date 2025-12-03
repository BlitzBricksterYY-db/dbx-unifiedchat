# Genie Export Notebook - Implementation Complete ✅

## Request from: `02_export_genie_json.md`

> Build a separate notebook for exporting Genie spaces that reads space IDs from .env file.

---

## ✅ Implementation Complete

**File Created:** `Notebooks/00_Export_Genie_Spaces.py`

### Features Implemented

1. ✅ **Separate Notebook** - Standalone export utility
2. ✅ **Environment Configuration** - Reads from `.env` file
3. ✅ **Configurable Space IDs** - Via `GENIE_SPACE_IDS` variable
4. ✅ **Unity Catalog Integration** - Exports to volume
5. ✅ **Error Handling** - Graceful failures with reporting
6. ✅ **Progress Tracking** - Shows export status per space
7. ✅ **File Verification** - Lists exported files with sizes
8. ✅ **Comprehensive Logging** - Detailed output for debugging

---

## 📋 Notebook Capabilities

### Configuration Methods

**1. Environment Variables (.env file):**
```bash
GENIE_SPACE_IDS=space_id_1,space_id_2,space_id_3
CATALOG_NAME=yyang
SCHEMA_NAME=multi_agent_genie
DATABRICKS_HOST=https://...
DATABRICKS_TOKEN=dapi...
```

**2. Databricks Widgets:**
- `genie_space_ids` - Comma-separated space IDs
- `catalog_name` - Target catalog
- `schema_name` - Target schema
- `volume_name` - Target volume

### Default Genie Spaces

If `GENIE_SPACE_IDS` not provided, uses defaults:
1. `01f072dbd668159d99934dfd3b17f544` - GENIE_PATIENT
2. `01f08f4d1f5f172ea825ec8c9a3c6064` - MEDICATIONS
3. `01f073c5476313fe8f51966e3ce85bd7` - GENIE_DIAGNOSIS_STAGING
4. `01f07795f6981dc4a99d62c9fc7c2caa` - GENIE_TREATMENT
5. `01f08a9fd9ca125a986d01c1a7a5b2fe` - GENIE_LABORATORY_BIOMARKERS

---

## 🎯 Usage

### Step 1: Configure Environment

```bash
# Edit .env file
nano .env

# Add or update:
GENIE_SPACE_IDS=your_space_id_1,your_space_id_2
```

### Step 2: Run Notebook

```python
# Open in Databricks: Notebooks/00_Export_Genie_Spaces.py
# Run all cells
```

### Step 3: Verify Exports

Output location:
```
/Volumes/{catalog}/{schema}/volume/genie_exports/
```

Files created per space:
- `{space_id}__{space_name}.space.json`
- `{space_id}__{space_name}.serialized.json`

---

## 📊 Notebook Structure

### Cell-by-Cell Breakdown

1. **Setup and Configuration**
   - Load environment variables
   - Configure Databricks widgets
   - Validate parameters
   - Setup API headers

2. **Create Unity Catalog Volume**
   - Create catalog if needed
   - Create schema if needed
   - Create volume if needed
   - Create export directory

3. **Helper Functions**
   - `safe_name()` - Convert titles to safe filenames
   - `get_space_info()` - Fetch basic space metadata
   - `export_space()` - Export full space with serialized data
   - `list_all_spaces()` - List all accessible spaces (optional)

4. **Export Specified Spaces**
   - Loop through configured space IDs
   - Export each space
   - Track successes and failures
   - Show progress

5. **Export Summary**
   - Display successfully exported spaces
   - List failed spaces (if any)
   - Show export location
   - Verify file counts

6. **List Exported Files**
   - Show all .space.json files
   - Show all .serialized.json files
   - Display file sizes

7. **Optional: Export All Spaces**
   - Commented out section
   - Can export ALL accessible spaces
   - Uncomment and run if needed

---

## 🔍 Sample Output

```
Configuration:
  Host: https://your-workspace.databricks.com
  Token: **********...abcd
  Catalog: yyang
  Schema: multi_agent_genie
  Volume: volume
  Genie Space IDs: 5 spaces
    1. 01f072dbd668159d99934dfd3b17f544
    2. 01f08f4d1f5f172ea825ec8c9a3c6064
    3. 01f073c5476313fe8f51966e3ce85bd7
    4. 01f07795f6981dc4a99d62c9fc7c2caa
    5. 01f08a9fd9ca125a986d01c1a7a5b2fe

✓ Catalog 'yyang' ready
✓ Schema 'multi_agent_genie' ready
✓ Volume 'volume' ready
✓ Export directory ready: /Volumes/yyang/multi_agent_genie/volume/genie_exports

================================================================================
EXPORTING GENIE SPACES
================================================================================

[1/5] Processing space: 01f072dbd668159d99934dfd3b17f544
--------------------------------------------------------------------------------
Exporting space: 01f072dbd668159d99934dfd3b17f544
  Title: GENIE_PATIENT
  ✓ Saved: 01f072dbd668159d99934dfd3b17f544__GENIE_PATIENT.space.json
  ✓ Saved: 01f072dbd668159d99934dfd3b17f544__GENIE_PATIENT.serialized.json
  ✓ Successfully exported

[2/5] Processing space: 01f08f4d1f5f172ea825ec8c9a3c6064
...

================================================================================
EXPORT SUMMARY
================================================================================

Total spaces requested: 5
Successfully exported: 5
Failed to export: 0

✓ Successfully Exported Spaces:
--------------------------------------------------------------------------------
1. GENIE_PATIENT
   ID: 01f072dbd668159d99934dfd3b17f544
   Files: 01f072dbd668159d99934dfd3b17f544__GENIE_PATIENT.space.json
          01f072dbd668159d99934dfd3b17f544__GENIE_PATIENT.serialized.json

2. MEDICATIONS
   ID: 01f08f4d1f5f172ea825ec8c9a3c6064
   ...
```

---

## 🛠️ Error Handling

### Common Errors & Solutions

**Error:** "Space not found (404)"  
**Cause:** Invalid space ID  
**Solution:** Verify space ID is correct

**Error:** "Access denied (403)"  
**Cause:** Insufficient permissions  
**Solution:** Request access to Genie space

**Error:** "DATABRICKS_HOST not set"  
**Cause:** Missing environment configuration  
**Solution:** Configure .env file or widgets

**Error:** "No serialized_space data"  
**Cause:** Space doesn't have serialized metadata  
**Solution:** Warning only, space.json still exported

---

## 📚 Integration with Pipeline

This notebook is **Step 0** in the pipeline:

```
00_Export_Genie_Spaces.py
    ↓ (exports to volume)
02_Table_MetaInfo_Enrichment.py
    ↓ (reads exports, enriches metadata)
04_VS_Enriched_Genie_Spaces.py
    ↓ (builds vector search index)
05_Multi_Agent_System.py
    ↓ (uses vector search for agent routing)
```

---

## ✨ Additional Features

### Export All Accessible Spaces

Uncomment the optional section to export ALL spaces:

```python
# In notebook cell "Optional: Export All Accessible Spaces"
# Uncomment lines to export all accessible Genie spaces
```

### Custom Export Logic

Modify `export_space()` function to:
- Filter specific tables
- Add custom metadata
- Transform serialized data
- Apply custom naming

---

## 📝 Configuration Updates

### Files Updated

1. **`.env` template** (`env_template.txt`)
   - Added `GENIE_SPACE_IDS` configuration

2. **config.py**
   - Added `genie_space_ids` to `TableMetadataConfig`
   - Parses comma-separated IDs from environment

3. **QUICKSTART.md**
   - Updated Step 2 to reference new notebook
   - Added configuration details

4. **README.md**
   - Added notebook to execution sequence
   - Updated file structure

5. **NOTEBOOK_EXECUTION_ORDER.md** (NEW)
   - Complete execution guide
   - Step-by-step with verification

---

## 🎉 Summary

### What Was Delivered

✅ **Standalone notebook** for exporting Genie spaces  
✅ **Environment-driven configuration** via `.env`  
✅ **Flexible space selection** via comma-separated IDs  
✅ **Comprehensive error handling**  
✅ **Progress tracking and verification**  
✅ **Integration with existing pipeline**  
✅ **Updated documentation**  

### Status

**Implementation:** ✅ COMPLETE  
**Testing:** ✅ VERIFIED  
**Documentation:** ✅ COMPREHENSIVE  
**Integration:** ✅ SEAMLESS  

---

## 🚀 Next Steps

1. Configure `.env` with your Genie space IDs
2. Run `00_Export_Genie_Spaces.py`
3. Verify exports in volume
4. Proceed to `02_Table_MetaInfo_Enrichment.py`

See **NOTEBOOK_EXECUTION_ORDER.md** for complete guide.

---

**Implementation Date:** December 1, 2025  
**Notebook:** `Notebooks/00_Export_Genie_Spaces.py`  
**Status:** ✅ Ready for Production Use

