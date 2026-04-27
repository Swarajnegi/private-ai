# Data Engineering Knowledge Base

> Personal knowledge base from data engineering projects (Apollo Dynamics 365, LRC & PeopleSoft).
> Everything here was encountered, debugged, and solved during development.
> Written for revision and learning — not as framework documentation.
> **Scope**: Pure data engineering — Databricks, DLT, Spark, Delta Lake, CDC, testing, deployment, security. No framework-specific (LHP) content.

---

## 1. Architecture & Pipeline Design

### End-to-End Flow (Apollo Gen2)

```
Dynamics 365
    ↓ (Synapse Link — automated export)
ADLS: preprocessing/replicate/<timestamp>/
    ├── model.json (delta entity schemas)
    ├── <entity>/*.csv (headerless delta data, multiple files per entity)
    └── OptionsetMetadata/ (all 5 full load CSVs, headerless)
    ↓ (Job 1: Preprocessing Notebook)
ADLS: incoming/
    ├── <entity>/<timestamp>_<entity>.csv (delta: WITH headers from model.json)
    └── <EntityName>/<timestamp>_<EntityName>.csv (full load: WITH headers from schemas.json)
    ↓ (Job 2: DLT STG→BRZ via LHP)
Databricks Unity Catalog:
    ├── stg_apollo_g2.<entity> (streaming tables, raw, all STRING)
    └── brz_apollo_g2.<entity> (CDC SCD2, typed, column-filtered)
```

### Two-Job Pattern

**Job 1: `apollo_preprocessing_job`** (notebook task on general-purpose cluster)
- Validates data files against schema sources (model.json / schemas.json)
- Merges headers with headerless CSVs
- Splits full load folder into per-entity folders
- Fails hard on validation errors (no silent routing)

**Job 2: `apollo_stg_brz_job`** (422 DLT pipeline tasks)
- Stage 1: 211 STG pipelines (parallel) — Autoloader CSV → streaming tables
- Stage 2: 211 BRZ pipelines (each depends_on its STG) — CDC SCD2 → typed tables

**Why two jobs, not one:**
- Different compute needs: preprocessing = single node, DLT = autoscaling
- Independent failure domains: preprocessing failure doesn't waste DLT startup time
- Clean separation of concerns: file operations vs streaming CDC

### Scale (Apollo)

- 211 entities total (206 delta load + 5 full load)
- 422 DLT pipelines (211 STG + 211 BRZ)
- 206 BRZ schema files
- 1 preprocessing schemas.json (5 full load entities)

### Layer Responsibility Separation
- STG = raw append. BRZ = CDC + typing. Silver = business logic. Mixing them makes debugging impossible.
- **Lesson**: Separate concerns across layers. Each layer has one job.

### Idempotency by Design
- Delete the checkpoint → Autoloader re-reads ALL files from scratch → duplicates on existing data
- **Lesson**: Design for idempotent reprocessing. BRZ CDC deduplicates by PK naturally, but STG append doesn't.

### Schema-as-Code: Single Source of Truth
- Have one schema definition per entity, referenced everywhere
- Don't maintain separate copies in preprocessing, STG, and BRZ
- **Lesson**: When a column changes, update in one place — not three

### Medallion Architecture — Silver & Gold

**Why Silver Views Instead of Tables:**
1. No storage cost — Silver doesn't duplicate Bronze data
2. Always fresh — reads latest Bronze state at query time
3. No orchestration needed — Gold reads the view, view reads Bronze automatically
4. When to materialize: only if a Silver view is too slow for Gold reads

**The `_mrg` Pattern (Gen1 → Gen2 Translation):**
- Gen1: Gold writes to `_mrg` temp table → Control Framework applies load type → final table
- Gen2: Single write directly to target Gold table with load strategy in YAML

**EDP Columns — Backward Compatibility:**
- Gen1 auto-adds `edp_pk_hash`, `edp_is_current`, `edp_record_type`, `edp_effective_dttm`
- Gen2 doesn't — create materialized views that add them for downstream compatibility
- Replace `WHERE edp_is_current AND edp_record_type <> 'D'` with `WHERE __end_at IS NULL`

**Gold Load Strategies:**
- **Append (I)** — daily snapshots, incremental facts. Historical preserved, new records added.
- **Truncate-and-Load (T)** — fully recomputed datasets. Entire table rebuilt each run.

**Scheduling and Freshness:**
- Gold runs on schedule regardless of upstream state
- Silver views make this possible — no "Silver job" to wait for
- Availability over absolute freshness; SLA monitoring flags gaps separately

**Dependency Resolution:**
- Execution order resolved automatically from dataset lineage
- Gold dimensions are independent (parallel). Only facts have ordering constraints.

---

## 2. Pipeline Flows & CDC

### STG Pipeline (Delta Load)
```
incoming/<entity>/<ts>_<entity>.csv (WITH headers)
    ↓ Autoloader (cloudFiles, header=true, schemaEvolution=addNewColumns)
    ↓ + operational metadata columns (processing timestamp, file path, etc.)
    ↓
stg_apollo_g2.<entity> (streaming table, CDF enabled, all columns STRING)
```
- Schema evolution ON — new Dataverse columns auto-added
- Corrupt files silently skipped (`ignoreCorruptFiles: true`)
- Append-only — no updates, no deletes, no type casting

### STG Pipeline (Full Load)
Same as delta load. By the time data reaches STG, full load CSVs already have headers from preprocessing.

### BRZ Pipeline (Delta Load)
```
stg → load view → validated view → filtered view (schema transform) → typed view (SQL transform) → CDC SCD2 write
```
4-view chain: load → validate → filter/cast → timestamp fix → CDC write

### BRZ Pipeline (Full Load)
```
stg → py_functions/snapshot_cdc_func.py (processes snapshots sequentially) → Snapshot CDC SCD2 write
```
No intermediate views — snapshot function reads STG directly and feeds CDC.

### Delta Load CDC (SCD Type 2, No Deletes)
- **Keys:** entity PK (usually single column, sometimes composite)
- **Sequence by:** file modification time (file-level, not row-level)
- **SCD Type:** 2 (full history with `__start_at` / `__end_at`)
- **track_history_except:** operational metadata columns — prevents false versions from metadata-only changes
- **No delete handling:** Records absent from a batch are simply ignored. No I/U/D operation column.

**Key Insight:** If a record disappears from subsequent batches, it stays ACTIVE forever (`__END_AT = NULL`). Delta load SCD2 only shows INSERTs and UPDATEs — never deletes. This is by design.

### Full Load CDC (Snapshot SCD Type 2, With Soft Deletes)
- **Keys:** Composite (varies per entity)
- **Mechanism:** Compares consecutive full snapshots
- New key → INSERT | Changed attribute → close old + INSERT new | Absent key → SOFT DELETE | Reappears → RE-INSERT

### Why STG Count > BRZ Count for Full Loads
STG appends every CSV. If 2 snapshots (118 + 250 rows), STG has 368. BRZ active count reflects only the latest snapshot (250). This is expected, not a bug.

### Preprocessing Design

**Delta Load (206 entities):**
```
replicate/<ts>/<entity>/*.csv (headerless)
    → Read model.json → extract column names
    → Validate column count
    → Apply headers → write to incoming/
```

**Full Load (5 metadata entities):**
```
replicate/<ts>/OptionsetMetadata/GlobalOptionsetMetadata.csv (headerless)
    → Read schemas.json → get column names + types
    → Handle trailing comma
    → Apply headers + type casting → write to incoming/
```

---

## 3. Schema & Type Casting

### Single Source of Truth Principle

| Entity Type | Schema Source | Used By | Location |
|---|---|---|---|
| Delta load (preprocessing) | `model.json` | Preprocessing notebook | ADLS `replicate/<ts>/model.json` |
| Delta load (BRZ) | BRZ schema YAML | Schema transform (column filter + type cast) | `schemas/brz/<entity>.yaml` |
| Full load (preprocessing) | `schemas.json` | Preprocessing notebook | `schemas/preprocessing/schemas.json` |
| Full load (BRZ) | None needed | Snapshot CDC uses `SELECT *` | — |

**Key insight:** Full load schemas are NOT enforced again in BRZ because preprocessing already applied the correct columns. Enforce once, trust downstream.

### BRZ Schema YAML Format
```yaml
columns:
  - "Id: STRING"
  - "SinkCreatedOn"              # Untyped — handled by SQL transform
  - "statecode: BIGINT"
  - "bupa_premiumamount: DECIMAL(38,10)"
  - "createdon: TIMESTAMP"       # ISO format — .cast() works
```

### What Happens When Schema Changes
- **Delta load:** New column in model.json → preprocessing adds header → STG Autoloader `addNewColumns` picks it up → BRZ `enforcement: strict` will DROP it unless added to schema file
- **Full load:** Update schemas.json → redeploy → flows through automatically via `SELECT *`

### The Type Casting Chain
```
Source (Dynamics 365) → CSV (all text) → STG (all STRING) → BRZ (typed)
```

**Mechanism 1: Schema Transform (.cast)** — For ISO dates, numbers, booleans:
```python
df = df.withColumn("statecode", F.col("statecode").cast("BIGINT"))
```

**Mechanism 2: SQL Transform (to_timestamp)** — For US-format dates:
```sql
SELECT * EXCEPT(SinkCreatedOn, SinkModifiedOn),
  to_timestamp(SinkCreatedOn, 'M/d/yyyy h:mm:ss a') AS SinkCreatedOn
FROM stream(v_<entity>_filtered)
```

**Why Two Mechanisms?** `.cast("TIMESTAMP")` parses ISO 8601 but CANNOT parse US format — returns NULL silently.

### The Silent NULL Problem
Most dangerous bug. Pipeline succeeded, data looked complete, but timestamp columns were all NULL. No error, no warning. Discovered only by manual inspection.
- **Lesson**: Always verify type-cast columns have non-NULL values after first run.

### Full Type Mapping Reference

| Dynamics 365 Type | CSV Value | STG Type | BRZ Cast | Notes |
|---|---|---|---|---|
| String | raw text | STRING | STRING | No cast needed |
| Int64 | `"123"` | STRING | BIGINT | `.cast()` works |
| Boolean | `"True"` | STRING | BOOLEAN | `.cast()` works |
| DateTime | ISO 8601 | STRING | TIMESTAMP | `.cast()` works |
| DateTimeOffset | ISO with offset | STRING | TIMESTAMP | `.cast()` works |
| Decimal | `"123.45"` | STRING | DECIMAL(38,10) | `.cast()` works |
| (Synapse Sink) | US date | STRING | TIMESTAMP | Needs `to_timestamp` |

### Schema Enforcement — Do It Once, at the Right Layer
- Enforcing in both STG and BRZ is redundant
- If STG preserves source schema faithfully, BRZ schema enforcement is the single gate
- **Lesson**: Pick ONE layer as the schema gate. Everything before it preserves raw data. Everything after it trusts the gate

### System Column Naming Conventions
- Columns added by the pipeline (processing timestamp, source file path) should be visually distinct from business columns
- Convention: prefix with `_` (underscore) — e.g., `_processing_timestamp`, `_source_file_path`
- Older convention: `edp_processing_timestamp` — works but couples name to platform acronym
- **Lesson**: Choose a system column naming convention early. Renaming later cascades through SQL, tests, downstream consumers

---

## 4. Data Quality & Testing

### SCD2 Integrity Cannot Be Assumed — Test It
- Active row uniqueness (only one `__END_AT IS NULL` per key) can silently break if CDC processes overlap
- Late arrival detection (`__START_AT > __END_AT`) catches temporal corruption
- Cross-batch dedup catches the same key appearing active in multiple processing batches
- **Lesson**: SCD2 is a write pattern, not a guarantee. Every SCD2 table needs: active uniqueness, temporal ordering, and cross-batch dedup checks

### NULL Aggregation on Empty Sets Is a Silent Killer
- `SUM()`, `AVG()`, `MAX()` over zero rows return `NULL`, not `0`
- Downstream comparisons like `result = 0` evaluate to `NULL` (falsy) — tests fail silently
- **Fix**: Always `COALESCE(SUM(...), 0)` when the WHERE clause can legitimately return zero rows

### Test Execution Is Not Sequential With Data Writes
- In streaming/DLT architectures, data writes and validation queries run in parallel
- A test querying a table being written to may see zero rows
- **Lesson**: Either accept first-run failures, or design tests against stable state only

### First Load vs Incremental Load Behave Differently
- First load: all CDC records are inserts, all SCD2 records are active
- Incremental: CDC detects updates/deletes, SCD2 closes old records
- **Lesson**: Test suites should distinguish "first load validation" from "steady state validation"

### Warn vs Fail Is an Operational Maturity Decision
- **Fail** = hard gate, stops pipeline. Use for data integrity (PK, SCD2, CDC)
- **Warn** = observability, data flows through. Use for freshness, metadata, schema drift
- **Lesson**: Start with `warn` during development. Promote to `fail` for production once baseline is established

### Test Cost Scales With Key Cardinality
- `GROUP BY` on 16 columns is orders of magnitude more expensive than on 1 column
- Full table scans for SCD2 tests are unavoidable
- **Lesson**: Tables with high composite key cardinality will be the test bottleneck

### Source Type Determines Test Applicability
- CloudFiles/Autoloader: natural batches (one file = one batch) with file modification time
- API/custom data sources: no file concept, no natural batch boundary
- Tests designed around "latest batch" don't apply to API sources
- **Lesson**: Test applicability must be determined by **source type**, not by layer

### Materialized Views Have No Batch Column
- MVs are fully recomputed each run — no incremental batch to filter on
- Tests requiring a `batch_column` either need alternative columns or don't apply
- **Lesson**: Design tests with the target's write pattern in mind (streaming vs CDC vs full refresh)

### Data Freshness Is Source-Dependent, Not Layer-Dependent
- CloudFiles: freshness = file modification time
- API: freshness = last API call timestamp
- Bronze SCD2: inherited from source
- Silver MV: pipeline run time, not data timestamp
- **Lesson**: "Data freshness" means different things at different layers

### Source Type Compatibility Matrix

| Test Concept | CloudFiles (File-based) | Custom Datasource (API) | Materialized View |
|---|:---:|:---:|:---:|
| PK uniqueness per batch | Yes | **No** (no batch boundary) | **No** (no batch column) |
| Row count (view vs table) | Yes | **No** (streaming mismatch) | No |
| Data freshness (file timestamp) | Yes | **No** (no file metadata) | **No** (no timestamp) |
| Schema evolution (_rescued_data) | Yes | **No** | No |
| SCD2 integrity | N/A at STG | Yes (BRZ SCD2) | No (MV, no SCD2) |
| Metadata column existence | Yes | Yes (different columns) | Depends |
| API connectivity | No | Yes | No |

### Column Name Casing Creates Silent Data Corruption
- Different sources may produce `Line_Of_Business` vs `Line_of_Business`
- In case-sensitive engines (Spark SQL), these become **two separate columns** in a UNION
- **Fix**: Establish a canonical column name registry. Enforce at the earliest ingestion point.

### Schema Metadata Queries Are Case-Sensitive
- `information_schema.columns` in Unity Catalog stores table names in lowercase
- Querying with original casing returns zero rows
- **Lesson**: Always `LOWER()` on both sides when querying `information_schema`

### Financial Data Has Negative Values — Don't Assume >= 0
- P&L entries, balance sheet movements, credits, reversals are naturally negative
- `Amount >= 0` produces false positives on ~80% of financial data
- **Lesson**: Validate ranges (`BETWEEN -1B AND 1B`) not signs

### Streaming Views Cannot Be Read in Batch Context
- A view created by `spark.readStream` cannot be queried by `spark.sql("SELECT ...")`
- **Fix**: Read from persisted table, or disable incompatible view check
- **Lesson**: Tests should read from persisted tables, not intermediate streaming views

### SIT Testing Patterns (Apollo)

**13 SIT Cases + 4 Custom:**
| ID | Test | What It Validates |
|---|---|---|
| SIT-01 | New Record Insertion | Basic CDC insert works |
| SIT-02 | Standard Update | SCD2 closes old, opens new |
| SIT-03 | Absent from Batch | Delta load ignores absent records |
| SIT-04 | No-Change Record | track_history_except prevents false versions |
| SIT-05 | Out-of-Order Arrival | sequence_by resolves ordering |
| SIT-06/09 | Full Load Insert/Update | Snapshot CDC works |
| SIT-07/08 | Soft Delete / Resurrection | Snapshot CDC lifecycle |
| SIT-10 | Schema Drift | Autoloader addNewColumns |
| SIT-12 | Null PK Drop | DQE expect_all_or_drop |
| SIT-13 | Pipeline Recovery | Checkpoint recovery, no duplicates |
| SIT-14 | Metadata Enforcement | Operational columns present and non-null |
| SIT-15/16 | Date Format Handling | US dates vs ISO dates |

**What We DON'T Test (and why):**
- Schema strict enforcement — hard gate, pipeline fails if violated
- Column count validation — hard gate, preprocessing raises ValueError
- **Principle**: Don't test hard gates. Focus on silent failures.

**SIT Best Practices:**
- Query-only validation sufficient for most cases. Don't need to upload test data.
- Tests needing minimum data conditions should auto-skip, not fail.
- HTML report with Reasoning column is critical for client handoff.
- Segregate tests into Generic vs Use-Case Specific.

---

## 5. Errors Encountered & Solutions

### Error 1: Duplicate Column Names (`_LEGACY_ERROR_TEMP_118`)
- **When:** Schema definition included operational metadata columns that are auto-injected
- **Fix:** Never include auto-managed columns in schema definitions
- **Lesson**: When a framework auto-manages certain columns, don't also declare them manually

### Error 2: Double Braces in Code-Generated YAMLs
- **When:** Python scripts generating YAMLs produced `{{variable}}` instead of `{variable}`
- **Fix:** Use string concatenation or `.format()` instead of f-strings when generating brace-based substitution files
- **Lesson**: When your generation tool and target format both use braces, pick a non-conflicting method

### Error 3: `SQL_CONF_NOT_FOUND` — Spark Config Missing at Runtime
- **When:** Pipeline reading `spark.conf.get("source_table")` but config never set
- **Fix:** Declare all runtime configs in pipeline configuration. Use `spark.conf.get("key", "default")` for optional configs
- **Lesson**: Runtime Spark configs are invisible dependencies. Clear contract needed for who sets them

### Error 4: Silent NULL — `.cast("TIMESTAMP")` on Non-ISO Dates
- **When:** US date format `M/d/yyyy h:mm:ss a` → `.cast("TIMESTAMP")` returns NULL silently
- **Fix:** Use `to_timestamp(col, 'M/d/yyyy h:mm:ss a')` with explicit format pattern
- **Lesson**: `.cast()` is safe for ISO dates but silently destroys non-ISO dates

### Error 5: Column Count Mismatch — Trailing Comma
- **When:** All Synapse Link full load CSVs have trailing commas → extra empty column
- **Fix:** `if len(df.columns) == len(schema_cols) + 1: df = df.drop(df.columns[-1])`
- **Lesson**: Handle source system export quirks generically

### Error 6: Entity Not Found — Leading Spaces in Folder Names
- **When:** ADLS folder named `  team` (two leading spaces) → schema lookup fails
- **Fix:** Rename folder. Consider adding `.strip()` to folder name lookups defensively
- **Lesson**: Never assume folder/file names from source systems are clean

### Error 7: Cluster Does Not Exist
- **When:** Hardcoded `existing_cluster_id` was wrong/stale
- **Fix:** Use `cluster_policy_id` for production. Environment-specific resource IDs should never be hardcoded

---

## 6. Architectural Decisions

### Decision 1: Preprocessing in Notebooks, Not in Pipeline Framework
- Alternatives: headerless ingestion with schemaHints (failed), schema rename at STG level (worked but redundant)
- **Chosen**: Preprocessing notebook applies headers from schemas.json, all STG pipelines use `header: true`
- **Why**: Simplest, single schema enforcement point, same pattern for delta and full load

### Decision 2: No Schema Enforcement in BRZ for Full Loads
- schemas.json already enforces at preprocessing. STG Autoloader preserves. BRZ snapshot CDC does `SELECT *`.
- **Principle**: Enforce schema once, trust downstream layers.

### Decision 3: Two-Step Type Casting in BRZ
- Schema transform handles safe casts. SQL transform handles US-format dates.
- **Why not one step**: Schema transforms only do `.cast()`. Custom format patterns require SQL.

### Decision 4: Fail Hard, Not Route to Unprocessed
- Unprocessed folders are where data goes to die. Nobody monitors them.
- Pipeline failure triggers alerts. `raise ValueError` > silent routing.

### Decision 5: PascalCase Folder Names for Full Loads
- Don't fight the source system. Synapse Link creates PascalCase. Pipelines should match.

### Decision 6: Separate DQE Expectations File
- Same 3 expectations apply to all 206 delta entities. One JSON file, referenced by all. Change once, applies everywhere.

---

## 7. Reusable Patterns

### write_source_view Chain (4-View BRZ Pipeline)
```
v_<entity>_prebrz → v_<entity>_validated → v_<entity>_filtered → v_<entity>_typed
```
The `write_source_view` parameter points to the LAST view in the chain.

### schemas.json for Full Load Metadata
Custom JSON schema definition serving as both column name source and data type source. Single source of truth for entities that don't have a model.json.

### Trailing Comma Auto-Detection
```python
if len(df.columns) == len(expected_columns) + 1:
    df = df.drop(df.columns[-1])
```
Applied before column count validation — handles the quirk transparently.

### Batch Pipeline Generation via Python Scripts
For 200+ entities: parse Entity Mapping CSV → generate schema YAMLs, pipeline YAMLs, config entries, job tasks. One script, one run, consistent output.

### SELECT * EXCEPT for Column-Specific Transforms
```sql
SELECT * EXCEPT(SinkCreatedOn, SinkModifiedOn),
  to_timestamp(SinkCreatedOn, 'M/d/yyyy h:mm:ss a') AS SinkCreatedOn
FROM stream(v_<entity>_filtered)
```
Avoids listing all 50+ columns when you only need to transform 2.

---

## 8. Compute & Operations

### Snapshot CDC Is Incompatible With Continuous Mode

`dp.create_auto_cdc_from_snapshot_flow` (DLT's APPLY CHANGES FROM SNAPSHOT) only works in **triggered mode** (`continuous: false`). Running it in continuous mode throws an error involving `.collect()` in the source function.

**Why:**
- Snapshot CDC's source function does batch operations (`.collect()`, `spark.sql()` with MIN/MAX over the full staging table)
- Continuous mode drives the function in a streaming loop, which can't handle batch actions
- The function returns `(DataFrame, version)` tuples — this shape is incompatible with continuous streaming context

**Solution:** Keep pipelines using snapshot CDC in triggered mode. For near-real-time bronze, trigger the job more frequently (e.g., every 15 min via cron) instead of enabling continuous mode.

**Affects:** All templates using `mode: snapshot_cdc` with `source_function`:
- TMPL008 (LRC NAS snapshot CDC)
- TMPL010 (PS snapshot CDC)

Regular CDC (`mode: cdc`) works fine in continuous mode — only snapshot CDC has this limitation.

### Continuous vs Triggered Mode
- `continuous: true` keeps compute running indefinitely — expensive, useful for low-latency streaming
- `continuous: false` processes available data and stops — cost-efficient for batch/daily loads
- **Lesson**: Pipeline execution mode should be configured per environment. Dev = triggered, Prod = depends on SLA

### Serverless Compute Is Not Infinite Parallelism
- Serverless DLT starts small and autoscales — doesn't give you 200 slots immediately
- Running multiple large pipelines simultaneously splits available capacity
- Sequential execution often finishes faster than parallel on serverless
- **Lesson**: Orchestration order matters even with serverless

### Stop Continuous Pipelines Before Redeployment
- Running pipeline uses old code after deploy — conflicts possible (table locks, schema mismatches)
- **Solution**: Pre-deploy script that lists and stops running pipelines via REST API
- **Lesson**: Redeployment safety should be scripted, not manual

### Developer Isolation Requires Full-Stack Namespacing
- Table names need suffixes (`{developer_name}`) — but so do event log tables, view names in SQL, table references in Python functions
- Missing the suffix in ONE place causes `TABLE_NOT_FOUND` or `TABLE_ALREADY_EXISTS`
- **Lesson**: Developer isolation is a substitution that must propagate through every layer: YAML, SQL, Python, and infrastructure config

### Generated Code Is an Artifact, Not a Source of Truth
- Editing generated files is always overwritten on next generation
- Persistent changes must go in the source configuration
- **Lesson**: In code-generation architectures, identify the generation boundary and never make manual changes below it

### Redeployment Safety
- Clean slate = delete pipelines + drop tables + redeploy. If you only delete pipelines, tables survive. New pipelines re-read all files → duplicates.
- Re-running preprocessing without cleanup overwrites `incoming/` files → Autoloader sees them as new → STG duplicates. BRZ CDC deduplicates, so BRZ is fine.

---

## 9. Deployment & Environment

### Separate Workspaces and Catalogs Per Environment
- Dev/test/preprod/prod should each have own workspace and catalog
- Sharing risks accidental data mutation (dev pipeline writing to prod tables)

| Environment | What to isolate |
|---|---|
| Dev | Own workspace, own catalog (`_dev_`), relaxed permissions |
| Test | Own workspace, own catalog (`_test_`), mirrors prod structure |
| Preprod | Own workspace, own catalog (`_prpd_`), production-like config |
| Prod | Own workspace, own catalog (`_prod_`), locked-down permissions |

### Per-Environment Configuration Files
- One config file per environment (e.g., `pipeline_config_dev.yaml`, `pipeline_config_prod.yaml`)
- Each file self-contained — no inheritance, no conditional logic
- **Lesson**: Duplication in config is cheaper than debugging a wrong environment override at 2 AM

### File Path Casing Breaks on Linux CI/CD
- Windows is case-insensitive: `Peoplesoft/` = `peoplesoft/`
- Linux (CI/CD agents, Docker, Databricks workers) is case-sensitive: `Peoplesoft/` ≠ `peoplesoft/`
- **Solution**: lowercase_snake_case for all directory and file names
- **Lesson**: If developing on Windows but deploying to Linux, treat casing as a potential breaking change

### Databricks CLI Gotchas
1. `databricks pipelines delete` uses positional args, not flags
2. `databricks pipelines list-pipelines` outputs UTF-16 on Windows
3. Deleting a DLT pipeline also drops its managed streaming tables. Recreating without dropping → Autoloader re-processes all files → duplicates
4. `max_retries: 0` is per-task, not per-job. Must be added to each task individually
5. `notebook_path` in job YAML is relative to the YAML file location, not the bundle root
6. `${workspace.file_path}` resolves to the bundle deployment location — don't hardcode workspace paths
7. `databricks bundle deploy --force-lock` needed when a previous deploy didn't clean up
8. `existing_cluster_id` is environment-specific — consider `cluster_policy_id` for production

### Notebook Generation Best Practices
- Generate `.ipynb` via Python scripts, not heredocs (JSON quoting breaks)
- Use `re.sub` with a mapping function for renumbering, not sequential replace (cascading bug)

---

## 10. Security

### Never Store Credentials in Plaintext Config Files
- Early dev starts with plaintext for speed, but this creates security risk
- **Solution**: Move all sensitive values to a secret store (Azure Key Vault, Databricks secrets)
- Reference via placeholder: `${secret:keyvault-name/secret-name}`
- **Lesson**: Switch from plaintext to secret references is a mandatory gate before promoting code beyond dev

### OAuth Refresh Tokens Are Dynamic Secrets
- Refresh tokens get overwritten on each API call — token returned by auth server replaces previous
- Storing as static secret → stale by next pipeline run
- **Solution**: Write new refresh token back to secret store after each successful auth exchange
- **Lesson**: Not all secrets are static. Identify which ones rotate and build write-back logic

---

## 11. Platform Knowledge Checks

Things that seem obvious in hindsight but cost real debugging time.

### Synapse Link / Dynamics 365
1. **SinkCreatedOn/SinkModifiedOn are NOT Dynamics 365 fields.** They're Synapse Link metadata — US date format, while Dynamics uses ISO 8601.
2. **All Synapse Link CSVs are headerless.** Headers come from model.json (delta) or schemas.json (full load).
3. **Full load CSVs always have trailing commas.** Every row ends with `,` → phantom empty column.
4. **Full load entities all live in one ADLS folder.** Must be split into separate folders by preprocessing.
5. **ADLS folder names are case-sensitive in practice.** Autoloader paths must match exact case.
6. **Synapse Link can create folders with leading/trailing spaces.**

### DLT / Autoloader
7. **CSV Autoloader reads everything as STRING.** No type promotion — casting is explicit in BRZ.
8. **`.cast("TIMESTAMP")` silently returns NULL on non-ISO dates.** Our most dangerous bug.
9. **`schemaEvolutionMode: addNewColumns` only adds columns.** Never removes, renames, or changes types.
10. **DLT streaming tables can't be `INSERT INTO`.** DLT manages them exclusively.
11. **Autoloader checkpoint = which files have been processed.** Delete checkpoint → re-reads ALL files.
12. **`full_refresh: true` recreates the streaming table from scratch.** Drops all data and reprocesses.

### CDC / SCD2
13. **`track_history_except` prevents duplicate versions on re-run.** Without it, metadata timestamp changes create false SCD2 versions.
14. **`sequence_by` determines which record "wins" in a batch.** Two records for same PK in same file have SAME sequence value.
15. **Snapshot CDC processes snapshots one at a time, in order.** If a snapshot fails, the next is never processed.
16. **STG count > BRZ count for full loads is normal.**

### Python / Spark
17. **`df.coalesce(1).write.csv()` writes to a directory, not a file.** Must copy/rename the part file.
18. **`spark.read.csv()` with `header=False` names columns `_c0, _c1, _c2...`**
19. **`spark.conf.get("key")` throws if key doesn't exist.** Use `spark.conf.get("key", "default")`.

### Best Practices Summary
1. Browse raw data before building pipelines — 30 minutes saves days of debugging
2. Silent failures are worse than loud failures
3. Enforce schema once, at the boundary
4. Every row needs operational metadata
5. Fail fast with specific messages — `raise ValueError(f"...")` > silent routing
6. Design around framework limitations, don't fight them
7. Never edit auto-generated files — edit the source and regenerate
8. Batch-generate at scale — Python scripts for 200+ config files
9. Test with small data first, then scale
10. Document the type mapping chain: Source → CSV → Spark → STG → BRZ

---

# LRC & PeopleSoft Gen2 — Learnings

> Learnings from the LRC & PeopleSoft Gen2 ingestion project (dp-dbricks-dab-gen2-ingestion).
> Builds on Apollo patterns but introduces multi-source (API + NAS/BYOD + PeopleSoft) complexity.

### Operational Metadata Standard

Two tiers based on source type:

| Source type | `operational_metadata` / `track_history_except` |
|---|---|
| **LRC API** (custom_datasource, no files) | `[_processing_timestamp]` only |
| **Everything else** (CloudFiles — CSV, JSON, PSV) | `[_source_file_path, _source_file_modification_time, _processing_timestamp]` |

- `_source_file_name` is **not used** — `_source_file_path` covers it and is more useful for debugging.
- `_source_file_size` and `_processing_date` are defined in `lhp.yaml` but not actively used by any template.
- Every column in `track_history_except` must actually exist in the data flowing into CDC. Listing non-existent columns won't error, but omitting existing metadata columns causes false SCD2 versions on every run.

### Column Naming: `CostCentre` Not `Cost_Centre`

The standard column name is **`CostCentre`** (no underscore) across all layers and both source types:
- LRC API data source schema defines `CostCentre`
- LRC NAS BYOD CSVs have header `CostCentre`
- Bronze CDC keys use `CostCentre`
- Silver SQL uses `CostCentre`
- Bronze rename SQL files do NOT rename this column

**Previous state (broken):** API source had `Cost_Centre`, BYOD had `CostCentre`, snapshot function had `Cost_Centre`, silver SQL had `Cost_Centre`. Multiple mismatches caused `UNRESOLVED_COLUMN` errors.

**Lesson:** When multiple data sources feed the same downstream layer, standardize column names at the earliest point. A mismatch in a single column name between source function SQL and CDC keys causes silent data corruption or crashes.

### CDC `sequence_by` for API Sources

LRC API bronze CDC uses `_processing_timestamp` as `sequence_by` (not a source-provided timestamp like `fetch_timestamp`).

- `_processing_timestamp` is added by LHP operational metadata at the extraction view level.
- It's also in `track_history_except` — this is valid because `sequence_by` (ordering) and `track_history_except` (change detection) are independent concepts in DLT CDC.
- Previously used `fetch_timestamp` (a custom column from the data source), but this was removed to simplify the schema.

### Test Centralization

All tests live in `templates/tests/` as dedicated test flowgroups. No inline test actions in data templates.

- **Previous state:** Some data templates (TMPL005, TMPL007, TMPL011, TMPL022, TMPL012, TMPL013) had inline test actions mixed with load/write actions.
- **Problem:** When operational metadata columns changed, inline tests broke silently (e.g., TMPL005 testing for `_source_file_name` after it was removed from operational metadata).
- **Fix:** Removed all inline tests from data templates. Tests are maintained separately and parameterized via pipeline YAML.

### Snapshot CDC Source Function Must Match CDC Keys

The `cdc_keys` variable inside the Python source function (used for SQL `PARTITION BY` deduplication) MUST match the `keys=` parameter passed to `dp.create_auto_cdc_from_snapshot_flow`. If they diverge:
- Source function SQL references column X → works if X exists in data
- CDC keys reference column Y → works if Y exists in data
- But dedup and CDC use different columns → silent data corruption

This happened with `Cost_Centre` vs `CostCentre` in the LRC NAS snapshot function.

### Row Count Test (TMPL018) — Latest Batch Filtering

The built-in LHP `row_count` test type compares total counts between two sources. For append-only STG tables, the target accumulates rows across batches while the source view only sees the current batch — causing false 2x mismatches after re-runs.

**Fix:** Replaced `test_type: row_count` with `test_type: custom_sql` in TMPL018. The custom SQL filters the target to the latest processing batch:
```sql
WHERE _processing_timestamp >= (
  SELECT MAX(_processing_timestamp) - INTERVAL 5 MINUTES FROM {table}
)
```
DLT sets `_processing_timestamp = current_timestamp()` for all rows in a pipeline run, so a 5-minute window isolates exactly one batch.

### PK Uniqueness Test (TMPL017) — Valid on STG

The PK uniqueness test (TMPL017) already filters to the latest batch via `batch_column` parameter (default: `_source_file_modification_time`). It checks uniqueness **within a single file batch**, not across the full accumulated table.

If the test fails at STG, it means the **source file itself** has duplicate rows with the same business key. This is a genuine data quality issue from the source system. Bronze snapshot CDC dedup (`ROW_NUMBER() OVER (PARTITION BY cdc_keys)`) handles these duplicates, so data is clean at BRZ — but the STG test correctly flags the source problem.

**Decision:** Keep PK tests on STG. They provide early warning about source data quality. Change `on_violation` to `warn` for tables where source duplicates are expected/acceptable.

### BYOD Source Data Quality — Duplicate Rows

LRC BYOD exports (e.g., `lrc_actual_BSMovementsTotal_byod`) can contain duplicate rows within the same CSV file. Confirmed: Entity `E321006` with accounts `A_010000` and `A_030000` appeared twice each in the same batch.

- **Root cause:** BYOD export from Oracle EPM drops duplicate records
- **Impact at STG:** PK uniqueness test fails (expected)
- **Impact at BRZ:** None — snapshot CDC `ROW_NUMBER()` dedup eliminates duplicates
- **Impact at Silver:** None — reads from deduplicated BRZ

### Schema Transform for Column Filtering + Type Casting + Renaming

LHP's schema transform with `enforcement: strict` can do three things in one step:
- **Filter:** Only columns listed in the schema file pass through; everything else dropped
- **Cast:** `"EFFDT: DATE"` casts the column to the target type
- **Rename:** `"edp_effective_dttm -> edp_source_file_modification_time"` renames in arrow syntax

This eliminates the need for a separate SQL transform when the only SQL logic is `SELECT * EXCEPT(...), col1 AS new_col1`.

**Pattern used in historical load template:**
```
load (parquet) → schema transform (strict: rename + cast + filter) → write
```
Schema files stored in `schemas/stg/{TABLE_NAME}_schema.yaml`, dynamically referenced via `{{ parquet_folder }}` template parameter.

### PeopleSoft Snapshot Function — TIMESTAMP Cast Fix (resolved 2026-04)

`brz_peoplesoft_snapshot_cdc_func.py` originally used bare string comparison:
```python
WHERE _source_file_modification_time > '{latest_snapshot_version}'
```
Fixed to match LRC pattern:
```python
WHERE _source_file_modification_time > TIMESTAMP '{latest_snapshot_version}'
```
Without the explicit cast, Spark's string→timestamp comparison is unreliable depending on the string representation of the Python object. Both comparison lines (line 34 and 44) needed the fix.

**Lesson**: Always use `TIMESTAMP 'literal'` when injecting a Python timestamp value into a Spark SQL string — never rely on implicit string→timestamp comparison.

### Gen1 BRZ SCD2 Migration Problem — Double SCD2 Breaks Active Records

**Scenario**: Migrating from Gen1 BRZ (already SCD2) to Gen2 BRZ (also SCD2). When Gen1 BRZ Parquet is exported "as-is" and loaded through Gen2 STG → BRZ CDC, **100% of active rows end up with wrong business values** despite row counts matching perfectly.

**Why it breaks**:
Gen1 BRZ tables contain multiple versions per PK (current + expired) with columns `edp_is_current`, `edp_effective_dttm`, `edp_expiry_dttm`. When all versions are loaded into Gen2 STG, Gen2's `apply_changes` CDC has to pick ONE winner per PK based on `sequence_by`. But:
- `edp_effective_dttm` is **identical for all versions** of the same PK → CDC picks arbitrarily
- `edp_record_insert_dttm` on the **expired version is often the latest** → CDC picks the wrong (expired) row

**Evidence (ITEM_TRANS)**:

| Metric | Result |
|---|---|
| Gen1 total / Gen1 `edp_is_current=True` | 1886 / 628 |
| Gen2 active (`__END_AT IS NULL`) | 628 ✓ count matches |
| ACCOUNT value mismatches | 628/628 (100%) |
| MONETARY_AMOUNT value mismatches | 623/628 (99%) — signs flipped |

Example PK with 3 versions:
- Row 2 (`is_current=True`, insert=09:46:35): ACCOUNT=258105, AMOUNT=-692
- Row 3 (`is_current=False`, insert=09:46:35): ACCOUNT=325770, AMOUNT=692
- Row 4 (`is_current=False`, insert=15:44:29): ACCOUNT=325770, AMOUNT=692 ← CDC picks this

**Fix options**:
1. Filter historical load to `WHERE edp_is_current = 'True'` — 1 row per PK, CDC ambiguity eliminated. Loses Gen1 SCD2 history but preserves correct current data.
2. Re-export Parquet with filter in the export notebook — cleaner source.
3. Load Gen1 BRZ Parquet directly into Gen2 BRZ mapping `edp_effective_dttm → __START_AT`, `edp_expiry_dttm/is_current → __END_AT` — preserves full SCD2 history but breaks DLT streaming table pattern.

**Lesson**: When the source is already SCD2, running CDC on it re-applies SCD2 on top — a "double SCD2" pattern that cannot be resolved by `sequence_by` alone. Either filter to current rows before CDC, or bypass CDC entirely with direct column mapping.

### DECIMAL ↔ DOUBLE Type Widening Is NOT Supported by Delta

**Scenario**: Historical load writes `Amount` as `DECIMAL(18,2)` (via schema transform with enforcement). Incremental API source returns `DOUBLE`. Both write to the same streaming table via separate `append_flow`s.

**Delta's type widening (`delta.enableTypeWidening`) supports**:
- INT → LONG
- FLOAT → DOUBLE
- DECIMAL(p1,s1) → DECIMAL(p2,s2) where p2 >= p1 and s2 >= s1

**Does NOT support**:
- DECIMAL → DOUBLE (would lose precision)
- DOUBLE → DECIMAL (would require quantization)

**Result**: If one flow writes DECIMAL and another writes DOUBLE to the same table, runtime failure — regardless of `addNewColumnsWithTypeWidening`.

**Fix**: Align types at the source — add an explicit `CAST(Amount AS DECIMAL(18,2))` transform in the incremental pipeline before write, so both sources produce the same type.

**Lesson**: Schema evolution in Delta is smarter than plain Spark, but it still respects type families. DECIMAL and DOUBLE live in different families. Always cast to match the creator's type when multiple writers target the same table.

### Mixed Historical + Incremental STG — `_source_file_path` NULL Percentage Is Expected

When STG contains rows from both historical (`once=True` batch Parquet load) and incremental (CloudFiles Autoloader streaming), the `_source_file_path` column will be NULL for historical rows (they don't have a source file path — `read_files()` SQL doesn't populate `_metadata.file_path`) and populated for incremental rows.

**Expected observation**: `_source_file_path` NULL% ≈ (historical_rows / total_rows). If 99.9% of rows are historical, you'll see 99.9% NULL for `_source_file_path`. This is NOT a bug.

**Gotcha**: If you put `_source_file_path` in `track_history_except` for BRZ CDC, and run the pipeline with ONLY historical data (no incremental yet), the BRZ CDC will fail with `UNRESOLVED_COLUMN: _source_file_path cannot be resolved` — because the STG table was created by the historical flow which doesn't add that column. Either:
- Ensure STG has both historical + incremental flows before running BRZ
- Or temporarily remove `_source_file_path` from `track_history_except` during historical-only validation runs

### Schema Transform with `enforcement: strict` Drops Commented Columns

When a schema YAML has a column commented out (e.g., `#- "DISTRIB_LINE_NUM: INT"`) and the transform uses `enforcement: strict`, that column is **dropped** from the output — even if the source has it.

**Downstream impact**: If the dropped column is later used as a CDC key in BRZ, pipeline fails with `UNRESOLVED_COLUMN` because the STG table doesn't have it.

**Fix**: Either uncomment the column in the schema (if source has it), or remove/comment it out from every downstream CDC key and test list. Schema columns and CDC keys must stay in sync.

### Delta Allows Multi-Writer Streaming Tables via append_flow

DLT streaming tables support **multiple writers** when each uses `@dp.append_flow` with the same `target`. Common pattern:
- Historical: `once=True` batch `append_flow` (writes once per full refresh)
- Incremental: streaming `append_flow` (ongoing)

Both define a `create_streaming_table()` in generated Python, but only ONE file does the creation (`create_table: true`) — the others just append. If nothing creates the table (e.g., the historical flow was removed), LHP validation fails with `LHP-VAL-009: Table creation validation failed — no creator`.

**Lesson**: Multi-writer DLT works, but exactly one writer must own table creation. Move `create_table: true` to whichever writer will always run (usually the incremental) to avoid breakage when flowgroups are toggled.

### DLT REFERENCE_DLT_DATASET_OUTSIDE_QUERY_DEFINITION — Same-Pipeline Dataset Access

Error: `Referencing pipeline dataset <catalog>.<schema>.<table> outside the dataset query definition (i.e., @dlt.table annotation) is not supported. Please read it instead inside the dataset query definition.`

**What it means**: DLT treats every table created within a pipeline as an "internal dataset." These datasets can only be read from inside a `@dp.view` / `@dp.table` / `@dp.materialized_view` decorated function (a "dataset query definition"). Reading them from plain Python code — e.g., a callback passed to `dp.create_auto_cdc_from_snapshot_flow(source=partial(my_func, ...))` — is forbidden.

**Why it matters**: Cross-pipeline reads (STG in one pipeline, BRZ in another) are classified as external UC table reads, which plain `spark.sql("SELECT * FROM catalog.schema.table")` handles normally. But if you unify STG and BRZ into one pipeline, that same `spark.sql` inside a Python callback hits this error because the STG table is now in-pipeline.

**Confirmed-failing pattern (snapshot_cdc with source_function)**:
```python
def next_snapshot_and_version(latest_snapshot_version, *, src_schema, src_table):
    staging_table = f"{catalog}.{src_schema}.{src_table}"
    df = spark.sql(f"SELECT * FROM {staging_table} WHERE ...")  # FAILS in same pipeline
    return (df, ts)

dp.create_auto_cdc_from_snapshot_flow(
    target="catalog.brz_schema.table",
    source=partial(next_snapshot_and_version, src_schema="stg_schema", src_table="table"),
    ...
)
```

**Working pattern (regular CDC with load action)**:
```yaml
- name: load_stg
  type: load
  readMode: stream
  source:
    type: delta
    catalog: "{catalog}"
    schema: "stg_schema"
    table: "my_table"
  target: v_my_table_prebrz
# LHP generates a @dp.view for this load — DLT accepts the read
```

**Options when you want same-pipeline STG+BRZ for snapshot_cdc**:
1. Keep split (STG pipeline + BRZ pipeline) — status quo, recommended.
2. Rewrite the snapshot logic as a `@dp.view` that the snapshot flow consumes via `source_table` instead of `source_function`. More invasive; loses the Python callback pattern.

**Lesson**: DLT's graph analyzer can see through SQL/Delta-source load actions (decorated views) but not through arbitrary Python closures. Pick your BRZ template based on this — regular CDC templates unify cleanly with their STG; snapshot_cdc templates with opaque Python source functions do not.

### POC Runtime Observations — 4-Job Split vs 1-Job Consolidated

POC split the outer `stg_brz_slv_finance_test` (single job, 13–16 min) into 4 jobs: `stg_brz_ps_test`, `stg_brz_lrc_byod_test`, `stg_brz_lrc_api_test`, `brz_slv_finance_test`.

Measured (jobs run one at a time):
- **Run 1 (full refresh)**: sequential total ~33m 12s. Longest single job 14m 6s.
- **Run 2 (normal rerun)**: sequential total ~30m 24s. Longest single job 10m 4s.

**Counter-intuitive finding**: On rerun, only snapshot-CDC BRZ pipelines got faster (`brz_ps`: 14m 6s → 3m 42s; `brz_lrc_byod` BRZ: 7m 3s → 3m 22s). STG and unified-CDC pipelines actually took LONGER on rerun:
- `stg_lrc_byod_test_pipeline`: 5m 23s → 8m 44s
- `stg_brz_ps_test_pipeline` (unified CDC): 5m 33s → 10m 4s
- `stg_ps_test_pipeline`: 9m 34s → 9m 44s

The net improvement comes from BRZ wins outweighing STG regressions. Don't assume "second run is uniformly faster" — snapshot-CDC BRZ benefits from historical being already present, but CloudFiles STG and regular-CDC pipelines are governed by different factors (file discovery, commit log compaction, serverless warmup).

**SLA trade-off**: Sequential 4-job execution is ~2x the single consolidated job. Running the 4 jobs in parallel via a master orchestrator (`run_job` tasks) bounds wall-clock by the longest child (~14 min Run 1, ~10 min Run 2) — restoring parity with or beating the consolidated baseline.

### Same-Pipeline STG+BRZ Pattern — When It Works vs When It Doesn't

Putting STG + BRZ flowgroups in a single DLT pipeline (unified) vs splitting them across two pipelines:

| BRZ pattern | Source model | Same-pipeline? | Notes |
|---|---|---|---|
| Regular CDC (`mode: cdc`, `apply_changes`) | `source: type: delta` (generates @dp.view) | **Yes — works** | DLT sees the view as a dataset query; dependency ordered correctly. LHP template TMPL009 / TMPL001 style. |
| Snapshot CDC (`mode: snapshot_cdc`) with `source_table` | Reads a DLT-defined view/table | **Yes — works** | Same reason as above. |
| Snapshot CDC with `source_function` (Python callback) | `spark.sql` inside plain Python | **No — fails with REFERENCE_DLT_DATASET_OUTSIDE_QUERY_DEFINITION** | Python closure is opaque to DLT's graph analyzer. Keep split across 2 pipelines. LHP templates TMPL008 / TMPL010 style. |

**Decision rule**: If your BRZ template injects a Python function as the source (common for snapshot CDC with per-snapshot dedup / window logic), the STG and BRZ MUST live in separate pipelines and be orchestrated via a job with `depends_on`. For everything else, unified pipelines are fine.

### Databricks Master Job Orchestration via `run_job_task`

Pattern for chaining multiple independent jobs into one master schedule — useful when you've split a single large job into domain-specific jobs but still need cross-domain ordering (e.g., all STG+BRZ jobs must complete before SLV):

```yaml
resources:
  jobs:
    master_finance_test:
      name: master_finance_test
      tasks:
        - task_key: run_ps
          run_job_task:
            job_id: ${resources.jobs.stg_brz_ps_test.id}
        - task_key: run_lrc_byod
          run_job_task:
            job_id: ${resources.jobs.stg_brz_lrc_byod_test.id}
        - task_key: run_slv
          depends_on:
            - task_key: run_ps
            - task_key: run_lrc_byod
          run_job_task:
            job_id: ${resources.jobs.brz_slv_finance_test.id}
```

**Properties**:
- Child jobs remain independently runnable (own schedule, own UI).
- `depends_on` expresses cross-job ordering; tasks without `depends_on` run in parallel.
- `run_job_task` is a Databricks-native task type; no custom Python needed.

**LHP limitation**: This master YAML cannot be generated by LHP (see LHP_Reference.md — "LHP Cannot Generate Master Jobs with `run_job` Tasks"). Create and maintain it manually in `resources/`.
