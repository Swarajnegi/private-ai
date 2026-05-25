# Data Engineering — Transferable Lessons

> A curated digest of every generalizable lesson distilled from `knowledge.md` and `LHP_Reference.md`. Project-specific entity/table/template names have been stripped or demoted to examples. Every lesson cites its source line range so you can dive back for full context.
>
> **Scope**: Concepts, patterns, gotchas, and principles that apply on *any* Databricks/DLT/Spark/Delta Lake project — not tied to one codebase or one framework (LHP).
>
> **How to read**: Each lesson is a short principle + why it matters + one concrete example. Read top-to-bottom for breadth, or jump to a section when you hit that problem on a future project.

---

## Table of Contents

1. Architecture & Design Principles
2. Schema, Types, and Data Integrity
3. CDC & SCD2 Patterns
4. Data Quality & Testing
5. Spark / PySpark Gotchas
6. DLT / Autoloader / Delta Lake Behavior
7. Performance & Compute
8. Errors & Silent Failures (generalizable)
9. Deployment & Environment
10. Orchestration & Jobs
11. Security & Secrets
12. Source System Quirks (generalizable)
13. Meta-Lessons (Aphorisms)

---

## 1. Architecture & Design Principles

### Layer Responsibility Separation
Every layer in a medallion architecture has ONE job. If you mix responsibilities (e.g., type casting in STG instead of BRZ), debugging becomes impossible — when BRZ has NULLs, you can't tell whether the source was NULL or STG corrupted it. Keep STG raw/append-only so you can always compare source vs STG vs BRZ to pinpoint where data changed.

| Layer | Responsibility | Do NOT |
|---|---|---|
| Preprocessing | File validation, header merge, schema application | Type casting, dedup, CDC |
| Staging (STG) | Raw ingestion, append-only, preserve source format | Type casting, column filtering, business logic |
| Bronze (BRZ) | CDC/SCD2, type casting, column filtering, DQ expectations | Aggregations, joins, business transforms |
| Silver | Business logic, joins, conforming | Raw ingestion, CDC |
| Gold | Serve consumption — dimensions, facts, aggregates | Raw ingestion |

(Source: `knowledge.md` L55–L57, `LHP_Reference.md` L4853–L4864)

### Silver as Views, Not Tables (When Possible)
Default Silver to *views* over Bronze. You get zero storage duplication, always-fresh reads, and no orchestration chain (Gold reads the view, view reads Bronze automatically). Materialize only when a view is too slow for Gold's access pattern.
(Source: `knowledge.md` L68–L98)

### Gold Load Strategies — Append vs Truncate-and-Load
Two canonical patterns: **Append (I)** for daily snapshots and incremental facts (history preserved, new rows added); **Truncate-and-Load (T)** for fully recomputed datasets (entire table rebuilt each run). Pick based on whether history matters.
(Source: `knowledge.md` L85–L87)

### Two-Job Pattern for Mixed Workloads
When your pipeline needs both arbitrary Python (`dbutils.fs`, file ops, validation) AND streaming CDC, don't try to force them into one job. Put the general-purpose work in a notebook job, and the streaming/CDC work in a DLT job, and chain them. Reasons: different compute profiles (single node vs autoscale), independent failure domains, DLT cannot run arbitrary Python.
(Source: `knowledge.md` L31–L46, `LHP_Reference.md` L4942–L4958)

### Idempotency by Design
Every component must be safe to re-run without producing duplicates or losing state. Map each component's idempotency mechanism explicitly: Autoloader → checkpoint; CDC → PK + sequence_by; snapshot CDC → file_modification_time watermark. If you delete a checkpoint but NOT the data, reprocessing produces duplicates — clean both together.
(Source: `knowledge.md` L59–L61, `LHP_Reference.md` L4905–L4916)

### Schema-as-Code: Single Source of Truth
For any entity, exactly ONE place defines its columns and types. Defining columns in three places (pipeline YAML, schema YAML, and a JSON metadata file) guarantees they'll drift apart. When a column changes, you update one file, not three.
(Source: `knowledge.md` L63–L66, `LHP_Reference.md` L4928–L4940)

### Fail Fast, Fail Specific — Don't Route to `/unprocessed/`
When validation fails, raise a specific, loud error. Do NOT move the file to an `/unprocessed/` folder and hope someone checks — nobody does. `/unprocessed/` folders are where data goes to die. Use `raise ValueError(f"Entity {name}: expected {n} cols, got {m}")`. Databricks alerts will catch it.
(Source: `knowledge.md` L408–L410, `LHP_Reference.md` L4918–L4926)

### Generated Code Is an Artifact, Not Source of Truth
In any code-generation architecture (LHP, dbt, Terraform, OpenAPI codegen, etc.), identify the generation boundary and never make manual changes below it. Every manual edit to a generated file is a future regression. If you find yourself editing generated code, you're solving the wrong problem — edit the source config and regenerate.
(Source: `knowledge.md` L491–L494, `LHP_Reference.md` L4960–L4971)

### Framework Limitations Are Architectural Constraints
When your framework can't do something, don't fight it — design around it. Examples: if the framework can't inject headers for headerless CSVs, do the header application in a preprocessing notebook before the framework touches it. Fighting the framework creates a maintenance burden that compounds with every framework upgrade.
(Source: `LHP_Reference.md` L4960–L4971)

### Developer Isolation Requires Full-Stack Namespacing
If multiple engineers share a dev environment and each needs their own tables, the `{developer_name}` suffix must propagate through every reference: table names, event log tables, view names in SQL, table references in Python functions, infrastructure config. Missing the suffix in ONE place causes `TABLE_NOT_FOUND` or `TABLE_ALREADY_EXISTS`.
(Source: `knowledge.md` L486–L489)

---

## 2. Schema, Types, and Data Integrity

### The Silent NULL Problem
`.cast("TIMESTAMP")` on a non-ISO date string returns NULL silently. Pipeline succeeds, row counts match, data looks complete — but the timestamp column is all NULL. This is the single most dangerous bug you'll encounter on a DE project because nothing fails. Always verify type-cast columns have non-NULL values after first run.
(Source: `knowledge.md` L212–L214, L372–L375, L616, `LHP_Reference.md` L4877–L4889)

### Use Explicit Parsers for Non-ISO Formats
For US dates (`M/d/yyyy h:mm:ss a`) or any non-ISO format, use `to_timestamp(col, 'format_pattern')` — never `.cast("TIMESTAMP")`. `.cast()` is safe for ISO 8601 and will silently destroy anything else. Two-step pattern works well: schema transform for safe casts, SQL transform for special formats.
(Source: `knowledge.md` L198–L210, `LHP_Reference.md` L4330–L4411)

### CSV Ingestion Makes Everything STRING
CSV Autoloader reads every column as STRING regardless of source-system type. There is no type promotion. The question is always "where and how do you cast?" — and the answer should be consistent for all entities of the same source type. Document the type mapping chain explicitly:

```
Source System → CSV Serialization → Spark Read → STG (STRING) → BRZ (typed)
```
(Source: `knowledge.md` L193–L226, `LHP_Reference.md` L4989–L5005)

### Schema Enforcement — Do It Once, at the Right Layer
Don't enforce the same schema in multiple places. Pick ONE layer as the "schema gate" and trust layers before/after it. If preprocessing already enforces a JSON schema, don't re-enforce in BRZ — that's pure maintenance burden. Anti-pattern: defining columns in pipeline config AND schema YAML AND a metadata JSON — three sources that WILL drift apart.
(Source: `knowledge.md` L228–L231, `LHP_Reference.md` L4866–L4875, L4928–L4940)

### System Column Naming — Use `_` Prefix, Not Acronyms
Pipeline-added columns (processing timestamp, source file path) should be visually distinct from business columns. Convention: prefix with `_` (e.g., `_processing_timestamp`, `_source_file_path`). Avoid framework-specific prefixes (`edp_`, `ctlfwk_`) — they couple your naming to a platform acronym and make migration painful.
(Source: `knowledge.md` L233–L239)

### Column Name Casing Creates Silent Data Corruption
Different sources may produce `Line_Of_Business` vs `Line_of_Business`. In case-sensitive engines (Spark SQL), these become **two separate columns** in a UNION — you silently double the schema and NULL-pad half the rows. Establish a canonical column name registry and enforce it at the earliest ingestion point.
(Source: `knowledge.md` L304–L307, L665–L676)

### Schema Metadata Queries Are Case-Sensitive in Unity Catalog
`information_schema.columns` stores table names in **lowercase**, regardless of how they were created. Querying `WHERE table_name = 'MyTable'` returns zero rows. Always `LOWER()` both sides when querying `information_schema`.
(Source: `knowledge.md` L309–L312, `LHP_Reference.md` L1755–L1772)

### Financial Data Has Negative Values — Don't Assume `>= 0`
P&L entries, balance sheet movements, credits, reversals are naturally negative. `Amount >= 0` produces false positives on ~80% of financial data. Validate bounded ranges (`BETWEEN -1B AND 1B`) not signs.
(Source: `knowledge.md` L314–L317)

### DECIMAL ↔ DOUBLE Type Widening Is NOT Supported by Delta
Delta's type widening supports: INT → LONG, FLOAT → DOUBLE, DECIMAL(p1,s1) → DECIMAL(p2,s2) where p2≥p1 and s2≥s1. It does NOT support DECIMAL ↔ DOUBLE (different families — one would lose precision, the other would need quantization). If two writers land on the same streaming table with mismatched types, runtime failure. Always cast to match the creator's type when multiple writers target the same table.
(Source: `knowledge.md` L791–L808)

### Streaming Delta Tables — Columns From All Writers Persist Forever
When a DLT streaming table is written by multiple `@dp.append_flow` flows (e.g., historical batch + ongoing streaming), Delta unions their schemas. Once a writer produces a column, it's in the table permanently — subsequent writes that don't produce it simply land NULL. Removing it requires drop+recreate because DLT-managed streaming tables don't have column mapping mode enabled.

Lesson: normalize column schemas across all writers into a streaming table before they ever run, or accept permanent NULL-padding.
(Source: `knowledge.md` L1062–L1071)

### Schema Transform `enforcement: strict` Has Passthrough Quirks
A schema transform with strict enforcement filters *business* columns to what's listed — but columns declared at the project level as operational metadata may pass through even when not in the schema file. If you want to genuinely prevent an `_` prefixed operational column from reaching the target, remove it from the load SQL AND from the project-level operational metadata config — not just the schema YAML.

Also: commented-out columns in a schema YAML (`#- "X: INT"`) get **dropped** from the output. If the dropped column is used as a CDC key downstream, the pipeline fails with `UNRESOLVED_COLUMN`.
(Source: `knowledge.md` L820–L826, `LHP_Reference.md` L5759–L5765)

### Single-Column Rename at the Migration Boundary
When migrating from an old table (with one naming convention) to a new one (with a normalized convention), the cleanest rename point is at the historical-backfill boundary — the schema transform that reads old-format data and writes new-format STG. One code change, localized. Every downstream layer stays on the new name.

Don't rename downstream (CDC keys, Silver SQL, tests, hash computations all reference one name — diverging names break CDC). Don't rename in the incremental source (it already produces the new name — only historical differs).
(Source: `knowledge.md` L1073–L1086, `LHP_Reference.md` L5781–L5793)

### Use Arrow-Rename Syntax in Schema YAMLs for Old→New Column Renames
Historical backfill schemas can do rename + cast + filter in one step:
```yaml
columns:
  - "old_col -> new_col: STRING"
```
Downstream layers see only `new_col`. No separate SQL transform needed.
(Source: `LHP_Reference.md` L5781–L5793, `knowledge.md` L732–L745)

### Mixed Historical + Incremental STG — Expect NULL in `_source_file_path`
When STG holds rows from both a historical batch-Parquet load (`once=True`) AND an ongoing CloudFiles streaming load, `_source_file_path` will be NULL for historical rows (Parquet `read_files()` doesn't populate `_metadata.file_path`) and populated for incremental rows. This is expected, not a bug. If historical is 99.9% of rows, expect 99.9% NULL.

Gotcha: don't list `_source_file_path` in `track_history_except` if you run the pipeline with only historical data (no incremental yet) — the column doesn't exist, BRZ CDC fails with `UNRESOLVED_COLUMN`.
(Source: `knowledge.md` L810–L818)

---

## 3. CDC & SCD2 Patterns

### CDC vs Snapshot CDC — Decision Criteria
Using the wrong CDC mode causes **silent data corruption**, not errors. Choose based on what the source delivers:

| Criteria | `cdc` (APPLY CHANGES INTO) | `snapshot_cdc` (APPLY CHANGES FROM SNAPSHOT) |
|---|---|---|
| Input data | Partial: only changed/new rows | Complete: full table snapshot per batch |
| DLT behavior | Treats each row as an upsert event | Compares consecutive snapshots; detects I/U/D |
| Delete detection | Via operation column or `track_deletions` | Automatic — absent key = deleted |
| Best for | Incremental feeds (CDC streams, API deltas) | Full-file loads (periodic complete extracts) |

**Critical pitfall**: feed *partial* data to `snapshot_cdc`, and DLT will compare the partial batch against the full Bronze table and **soft-delete every row not in the batch**. 5 new records fed as a "snapshot" → DLT deletes the other 9,995 rows.
(Source: `LHP_Reference.md` L4650–L4670)

### Delta-Load CDC Never Shows Deletes
In delta-load CDC (partial upsert feed), records absent from a batch are simply ignored — they stay ACTIVE forever (`__END_AT = NULL`). Only INSERTs and UPDATEs flow through. If you need delete semantics from a partial-feed source, you need either (a) an explicit operation column from the source, or (b) switch to snapshot CDC.
(Source: `knowledge.md` L129–L136)

### Snapshot-Load CDC Handles All Four Lifecycle Events
Snapshot CDC compares consecutive full snapshots: new key → INSERT; changed attribute → close old, open new; absent key → SOFT DELETE; reappears → RE-INSERT. Count expectation: `STG count > BRZ active count` is normal, because STG appends every snapshot while BRZ active reflects only the latest.
(Source: `knowledge.md` L138–L144)

### `sequence_by` Determines the Winner in a Batch
Two records for the same PK in the same batch use `sequence_by` to decide which wins. If two records have the SAME sequence value (common when sequencing by file_modification_time and both rows came from the same file), CDC picks arbitrarily. Always pick a `sequence_by` column with real per-row granularity for sources where multiple records per key per batch are possible.
(Source: `knowledge.md` L624)

### `track_history_except` Prevents False SCD2 Versions
Operational metadata columns (`_processing_timestamp`, `_source_file_path`, etc.) change on every pipeline run even when business data doesn't. Without `track_history_except`, every re-run creates a false SCD2 version. Always list operational metadata columns in `track_history_except` — change detection should look at business columns only.

Independently of `sequence_by`: both concepts apply together. `sequence_by` (ordering) and `track_history_except` (change detection) are orthogonal.
(Source: `knowledge.md` L133, L623, L678–L684)

### Snapshot CDC Source Function Must Match CDC Keys
If the Python source function uses `cdc_keys` internally (for SQL `PARTITION BY` deduplication) and that diverges from the `keys=` parameter passed to `create_auto_cdc_from_snapshot_flow`, you get silent data corruption: dedup uses one column, CDC uses another. Align them at the template/config level — never let them drift.
(Source: `knowledge.md` L694–L701, `LHP_Reference.md` L5386–L5388)

### Auto-Coalesce Applies to AUTO CDC, NOT AUTO CDC FROM SNAPSHOT
The Jan 2026 "SCD2 auto-coalesce duplicate records with the same natural key" feature applies to **`create_auto_cdc_flow` only**. It does NOT cover `create_auto_cdc_from_snapshot_flow` despite the release note's generic phrasing.

**Why**: auto-coalesce works by deterministically picking a winner among `(key, sequence_by)` ties. AUTO CDC has a `sequence_by` parameter to provide this ordering. AUTO CDC FROM SNAPSHOT has no `sequence_by` — it uses an external snapshot version returned by the `source_function` for ordering *between* snapshots, but offers nothing for resolving duplicates *within* a single snapshot. The API contract assumes each snapshot has unique keys; in-snapshot duplicates remain undefined behavior.

**How to apply**: if your snapshot source can have in-snapshot duplicate keys (BYOD CSV exports, Oracle EPM dumps, third-party file feeds, anything that doesn't deduplicate at source), keep the manual `ROW_NUMBER() OVER (PARTITION BY keys ORDER BY tie_breaker DESC)` dedup inside the `source_function` or in an upstream `@dp.view` that the CDC flow consumes. The 2026 release does not eliminate this need.

### Snapshot CDC Is Incompatible With Continuous Mode
`create_auto_cdc_from_snapshot_flow` only works in triggered mode. The source function does batch operations (`.collect()`, `spark.sql` with MIN/MAX), which can't run in a streaming loop. The function's `(DataFrame, version)` return shape is also incompatible with continuous context. For near-real-time bronze with snapshot CDC, trigger more frequently (e.g., every 15 min via cron) — don't try to make it continuous.

Regular CDC (`mode: cdc`) works fine in continuous mode. Only snapshot CDC has this restriction.
(Source: `knowledge.md` L453–L468, `LHP_Reference.md` L5345–L5356)

### "Double SCD2" — Running CDC on Already-SCD2 Source Breaks Everything
Migrating from a Gen1 SCD2 table to a Gen2 SCD2 table by loading the old Parquet as-is through Gen2 CDC produces **100% wrong active rows** despite matching row counts. Multiple versions per PK exist in the source, all with the same `effective_dttm` → CDC picks arbitrarily. The expired version often has the latest `record_insert_dttm` → CDC picks the wrong (expired) row.

Fix: filter historical load to `WHERE is_current = True` before CDC. 1 row per PK → no ambiguity. You lose historical SCD2 versioning but preserve correct current data. Alternative: bypass CDC entirely with direct column mapping (`effective_dttm → __START_AT`, `expiry_dttm → __END_AT`).

Universal lesson: when the source is already SCD2, CDC re-applies SCD2 on top — this cannot be resolved by `sequence_by` alone. Either collapse to current-only before CDC, or preserve versions with direct column mapping.
(Source: `knowledge.md` L761–L789)

### `apply_changes` SCD1 ≠ MERGE With DELETE Unmatched
`create_auto_cdc_flow(..., stored_as_scd_type=1)` implements per-key overwrite semantics ONLY:
- Key in source, not in target → INSERT
- Key in both → UPDATE (overwrite)
- Key in target, NOT in source → **untouched** (row persists forever)

There is NO equivalent to `WHEN NOT MATCHED BY SOURCE DELETE`. SCD1 specifies history behavior for matched keys; it says nothing about orphan target rows.

When this bites:
- **Authoritative snapshot sources** — if a key disappears from the new snapshot, it stays forever in the target. "Soft-delete via snapshot absence" does NOT propagate in SCD1.
- **PK-column restatement** — if a business column feeding a key hash changes, the hash changes, so the restated row inserts as NEW and the old row orphans.

Options for delete-if-missing: switch to `snapshot_cdc` (natural absence-delete), or union with an anti-join DELETE candidate view using `apply_as_deletes`, or accept drift and monitor.
(Source: `knowledge.md` L1037–L1060)

### Same-Pipeline STG+BRZ Is Template-Dependent
Whether you can collapse STG + BRZ into a single DLT pipeline depends on your BRZ source shape:

| BRZ pattern | Same-pipeline? |
|---|---|
| Regular CDC (`mode: cdc`) with `source: type: delta` load | **YES** — LHP generates `@dp.view`, DLT sees it as dataset query |
| Snapshot CDC with `source_table` | **YES** — same reason |
| Snapshot CDC with `source_function` (Python callback) | **NO** — Python closure is opaque; triggers `REFERENCE_DLT_DATASET_OUTSIDE_QUERY_DEFINITION` |

Rule: if your BRZ uses a Python function as its source (common for snapshot CDC with per-snapshot dedup), STG and BRZ must live in separate pipelines, orchestrated via a job with `depends_on`. DLT's graph analyzer can see through SQL/Delta-source load actions but not through arbitrary Python closures.
(Source: `knowledge.md` L897–L907, L838–L878, `LHP_Reference.md` L5566–L5571)

### Cross-Batch Dedup Through CDC, Within-Batch Dedup Through Transform
For streaming facts where you need `ROW_NUMBER() OVER (...)` dedup, keep the chain BATCH all the way to the CDC write. Streaming + `ROW_NUMBER` raises `NON_TIME_WINDOW_NOT_SUPPORTED_IN_STREAMING`. The fix: `type: sql` load (always batch) → `transform_type: sql` dedup (batch) → `streaming_table + mode: cdc` write (`create_auto_cdc_flow` accepts batch sources).

Within-batch dedup lives in the transform (`ROW_NUMBER`). Cross-batch dedup lives in CDC's `sequence_by`. Each batch CDC runs as a discrete merge — batch semantics upstream, streaming target downstream.

Diagnostic for the error: inspect generated `.py` — you should see `@dp.temporary_view()` (not `@dp.temporary_streaming_view()`) upstream, and no `spark.readStream` anywhere.
(Source: `knowledge.md` L1004–L1035, `LHP_Reference.md` L5693–L5742)

### Multi-Writer Streaming Tables via `append_flow` — Exactly One Creator
DLT streaming tables support multiple writers when each uses `@dp.append_flow` with the same `target`. Common pattern: historical `once=True` batch + ongoing streaming. But exactly ONE writer must own table creation (`create_table: true`) — if none do, validation fails; if two do, conflict.

Move `create_table: true` to whichever writer will always run (usually the incremental), so toggling other flowgroups doesn't break creation.
(Source: `knowledge.md` L828–L836, `LHP_Reference.md` L5419–L5427)

---

## 4. Data Quality & Testing

### Test What Can Fail Silently — Not Hard Gates
Don't write tests for hard-gated validations (they fail on their own with clear errors). Focus your testing effort on things that can produce wrong data without any error:
- Silent NULL from wrong cast
- Cross-layer count mismatches that need interpretation (e.g., STG > BRZ for snapshot CDC is expected)
- Composite key correctness — wrong key = wrong CDC behavior, no error
- Edge cases (midnight times, single-digit months, timezone offsets)

Don't test: `enforcement: strict` dropping extras (hard gate), `expect_all_or_drop` on NULL PK (hard gate), column count validation that raises ValueError.
(Source: `knowledge.md` L342–L352, `LHP_Reference.md` L4973–L4987)

### SCD2 Integrity Cannot Be Assumed — Test It Explicitly
SCD2 is a *write pattern*, not a guarantee. Every SCD2 table needs three tests:
1. **Active-row uniqueness** — only one `__END_AT IS NULL` per key
2. **Temporal ordering** — `__START_AT ≤ __END_AT` (detects late-arrival corruption)
3. **Cross-batch dedup** — same key shouldn't appear active across overlapping batches

If CDC writes overlap or run concurrently, active-row uniqueness can silently break. Test these on every SCD2 table.
(Source: `knowledge.md` L243–L247)

### NULL Aggregation on Empty Sets Is a Silent Test Killer
`SUM()`, `AVG()`, `MAX()` over zero rows return **NULL**, not 0. Downstream comparisons like `result = 0` evaluate to NULL (falsy in WHERE) — tests "fail" silently because NULL is neither equal nor not-equal to 0.

**Fix**: always wrap with `COALESCE(SUM(...), 0)` when the WHERE clause could legitimately match zero rows.
(Source: `knowledge.md` L249–L252, `LHP_Reference.md` L1732–L1753)

### Test Execution Is Not Sequential With Streaming Writes
In streaming/DLT architectures, data writes and validation queries run in parallel. A test querying a table being written to may see zero rows on the first run. Either accept first-run failures as expected, or design tests against stable state only (e.g., require a completed run before running the test).

Specifically: on first run or full refresh, `target_count = 0` because the streaming `append_flow` hasn't committed yet.
(Source: `knowledge.md` L254–L257, `LHP_Reference.md` L1794–L1804)

### First Load vs Incremental Load Behave Differently
First load: all CDC records are inserts, all SCD2 records are active. Incremental load: CDC detects updates/deletes, SCD2 closes old records. Test suites should distinguish "first load validation" from "steady state validation" — assertions about active/expired row counts are different for each.
(Source: `knowledge.md` L259–L262)

### Warn vs Fail Is an Operational Maturity Decision
- **Fail** = hard gate, stops pipeline. Use for data integrity (PK uniqueness, SCD2 active uniqueness, CDC keys).
- **Warn** = observability, data flows through. Use for freshness, metadata completeness, schema drift, unusual-but-valid distributions.

Progression: start with `warn` during development. Promote to `fail` for production once the baseline is established and false positives have been tuned out.
(Source: `knowledge.md` L264–L267)

### Source Type Determines Test Applicability, Not Layer
A "latest batch" test designed for CloudFiles doesn't apply to an API source (no file concept, no batch boundary). A `batch_column` test doesn't apply to a materialized view (no batch column at all). Map test applicability to source shape:

| Test concept | CloudFiles | API (custom datasource) | Materialized View |
|---|---|---|---|
| PK uniqueness per batch | Yes | No (no batch boundary) | No (no batch column) |
| Row count (view vs table) | Yes | No (streaming mismatch) | No |
| Data freshness (file timestamp) | Yes | No (no file metadata) | No (no timestamp) |
| Schema evolution (_rescued_data) | Yes | No | No |
| SCD2 integrity | N/A at STG | Yes (BRZ SCD2) | No |
| API connectivity | No | Yes | No |

(Source: `knowledge.md` L274–L302)

### Data Freshness Means Different Things at Different Layers
- CloudFiles: freshness = file modification time
- API: freshness = last API call timestamp
- Bronze SCD2: inherited from source
- Silver MV: pipeline run time, not data timestamp

Don't build a single "freshness" dashboard pretending all layers mean the same thing — define a per-layer freshness metric.
(Source: `knowledge.md` L285–L290)

### Test Cost Scales With Key Cardinality
`GROUP BY` on 16 columns is orders of magnitude more expensive than on 1 column. Full table scans for SCD2 tests are unavoidable. Tables with high composite key cardinality will be your test bottleneck — plan accordingly (run during off-hours, or sample strategically).
(Source: `knowledge.md` L269–L272)

### Streaming Views Cannot Be Read in Batch Context
A view created by `spark.readStream` cannot be queried by `spark.sql("SELECT...")`. Tests should read from *persisted* tables, not intermediate streaming views. If you must test against a streaming view, either persist it first or disable the incompatible-view check.
(Source: `knowledge.md` L319–L322)

### Test Centralization — Don't Inline Tests in Data Templates
Placing test actions inside data templates (e.g., a completeness test inside a load template) creates tight coupling between the test and the template's internal schema/metadata. When operational metadata columns change, inline tests break silently. Centralize tests in a dedicated `templates/tests/` (or equivalent) directory as parameterized test flowgroups referenced from pipeline YAMLs.
(Source: `knowledge.md` L686–L692, `LHP_Reference.md` L5390–L5392)

### Row Count Tests on Append-Only Tables Need Latest-Batch Filtering
The naive "row count source vs target" test breaks on append-only STG tables: target accumulates across batches, source view sees only the current batch → false 2× mismatches on re-runs.

Fix: filter the target to the latest batch via a processing-timestamp window, e.g., `WHERE _processing_timestamp >= (SELECT MAX(_processing_timestamp) - INTERVAL 5 MINUTES FROM {table})`. DLT sets `_processing_timestamp = current_timestamp()` for all rows in a pipeline run, so a short window isolates exactly one batch.
(Source: `knowledge.md` L703–L713)

### PK Uniqueness Test on STG — Within-Batch, Not Full-Table
A PK uniqueness test at STG should check uniqueness *within a single file batch*, not across the full accumulated append-only table. If it fails, the **source file itself** has duplicates — genuine data quality issue from the source. BRZ snapshot CDC's `ROW_NUMBER() OVER (PARTITION BY)` dedup handles it downstream, but the STG test is a valuable early warning.

Decision: keep PK tests on STG. Change `on_violation` to `warn` for tables where source duplicates are expected/acceptable.
(Source: `knowledge.md` L715–L721)

### Source Duplicate Rows Are More Common Than You Think
Third-party exports (BYOD from ERP systems, CSV dumps from vendor pipelines) can contain duplicate rows within the same CSV file. Assume duplicates exist until proven otherwise — build CDC dedup in BRZ and test visibility at STG.
(Source: `knowledge.md` L723–L730)

### `on_violation` Cannot Mix Fail and Warn Within One Expectation Group
When a `custom_expectations` test has expectations with different `on_violation` values (some fail, some warn), some generators stack `@expect_all_or_fail` + `@expect_all` decorators on the same view → Databricks throws `NoSuchElementException` at runtime. Use the same `on_violation` for all expectations within one test action. If you need both, split into separate test actions.
(Source: `LHP_Reference.md` L4233–L4239)

---

## 5. Spark / PySpark Gotchas

### `spark.conf.get("key")` Throws If Missing — Always Provide a Default
`spark.conf.get("missing_key")` raises `SparkNoSuchElementException`. Use `spark.conf.get("key", "default_value")` for optional configs. Runtime Spark configs are invisible dependencies — establish a clear contract for who sets them (preferably the pipeline config, not scattered Python modules).
(Source: `knowledge.md` L367–L370, L631)

### `df.coalesce(1).write.csv()` Writes to a DIRECTORY, Not a File
Spark DataFrame writes produce a directory of part files. `coalesce(1)` gives you one part file, but you still get the directory wrapper. If you want a single named CSV file (e.g., for downstream consumers), you must copy or rename the `part-*.csv` out of the directory.
(Source: `knowledge.md` L629)

### `spark.read.csv(header=False)` Names Columns `_c0, _c1, _c2...`
No schema inference of headers when `header=False`. You get positional names. Build your header-application logic accordingly — match by position, not by column name.
(Source: `knowledge.md` L630)

### `COUNT(*)` vs `COUNT(1)` — No Performance Difference in Spark
Spark's query planner rewrites both to the same physical plan. Neither reads column data. The only meaningfully different variant is `COUNT(column_name)`, which excludes NULLs.
(Source: `LHP_Reference.md` L5382–L5384)

### Always Use Explicit `TIMESTAMP 'literal'` When Injecting Python Timestamps Into Spark SQL
`WHERE ts_col > '{python_ts}'` relies on Spark's implicit string→timestamp comparison, which is unreliable depending on the string representation of the Python object. Always wrap:
```python
WHERE ts_col > TIMESTAMP '{python_ts}'
```
Rule: never rely on implicit string→timestamp comparison when injecting Python values into Spark SQL.
(Source: `knowledge.md` L747–L759)

### `=` Is Valid SQL Comparison in DLT Expectations (Not `==`)
DLT expectations use Spark SQL syntax, which uses `=` not `==`. Common mistake for engineers coming from Python or Scala.
(Source: `LHP_Reference.md` L5373–L5376)

### `SELECT * EXCEPT(...)` for Column-Specific Transforms
When you need to transform only 2 columns out of 50, don't list all 50:
```sql
SELECT * EXCEPT(colA, colB),
  to_timestamp(colA, 'fmt') AS colA,
  to_timestamp(colB, 'fmt') AS colB
FROM source
```
Keeps SQL concise and robust to source schema changes.
(Source: `knowledge.md` L441–L449)

---

## 6. DLT / Autoloader / Delta Lake Behavior

### CSV Autoloader Reads Everything as STRING — Casting Is Explicit
There's no schema-inferred types on CSV; the engineering decision is *where* to cast, not whether to cast. Consistent answer: cast in BRZ, via a schema transform (for safe types) + SQL transform (for special formats). Everything before the cast layer preserves raw STRING.
(Source: `knowledge.md` L615)

### Autoloader Checkpoint = Processed Files Tracker — Delete at Your Peril
Autoloader's checkpoint tracks which source files have been processed. Delete the checkpoint → Autoloader re-reads ALL files → duplicates on top of existing data (unless the downstream layer dedups).

If you delete a DLT pipeline, Databricks also drops its managed streaming tables (including the checkpoint). Recreating the pipeline without also clearing STG data → Autoloader re-processes all files → STG duplicates (BRZ CDC deduplicates, so BRZ is fine). Always clean checkpoints + data together.
(Source: `knowledge.md` L619, L497–L500)

### `schemaEvolutionMode: addNewColumns` ONLY Adds Columns
It never removes, renames, or changes types. If your source removes or renames a column, Autoloader will NOT catch it — the column will just start landing NULL. Plan for this explicitly: a "schema drift" test should flag unexpected NULL patterns in previously-populated columns.
(Source: `knowledge.md` L617)

### DLT Streaming Tables Can't Be `INSERT INTO`
DLT manages them exclusively. All writes go through `@dp.append_flow`, `create_auto_cdc_flow`, or `create_auto_cdc_from_snapshot_flow`. You can't directly MERGE, INSERT, or UPDATE. If you need MERGE semantics, use regular Delta tables or work within DLT's CDC abstractions.
(Source: `knowledge.md` L618)

### `full_refresh: true` Drops All Data and Reprocesses
It recreates the streaming table from scratch. Use sparingly — it's fine for dev iteration, dangerous in prod (reprocessing cost + potential non-determinism in derived columns). Default to incremental runs; reserve full_refresh for schema changes and debugging.
(Source: `knowledge.md` L620)

### `REFERENCE_DLT_DATASET_OUTSIDE_QUERY_DEFINITION` — The Graph Analyzer Limit
DLT classifies every table created within a pipeline as an "internal dataset". Internal datasets can only be read from inside a `@dp.view` / `@dp.table` / `@dp.materialized_view` decorated function — i.e., a "dataset query definition". Reading them from plain Python code (e.g., a callback passed to `create_auto_cdc_from_snapshot_flow`) is forbidden.

Cross-pipeline reads (STG in one pipeline, BRZ in another) are external UC table reads — `spark.sql("SELECT * FROM catalog.schema.table")` works normally. But if you unify them into one pipeline, the same `spark.sql` inside a Python callback fails.

Consequence: snapshot CDC templates with Python source functions cannot be co-located with their STG. Decorated-view patterns can.
(Source: `knowledge.md` L838–L878)

### `type: sql` Load Is Always Batch — Unlike `type: delta`
Two load-source types with very different streaming semantics:

| Load type | Generated decorator | Evaluation mode |
|---|---|---|
| `delta` | `@dp.temporary_view()` wrapping `spark.read.table()` OR `spark.readStream.table()` | batch by default; streaming if `readMode: stream` |
| `sql` | `@dp.temporary_view()` wrapping `spark.sql("""...""")` | **always batch** — `readMode: stream` has no effect |

If you need to UNION multiple BRZ tables into a single feed for a `streaming_table + mode: cdc` write, `type: sql` (with UNION inlined in the SQL) is the right shape. Five `type: delta` loads + a UNION transform is NOT equivalent — the delta loads must each be stream-readable, cascading the streaming constraint everywhere.
(Source: `LHP_Reference.md` L5693–L5706)

### `transform_type: sql` Always Produces a Batch View
Pure SQL transforms generate `@dp.temporary_view()` over `spark.sql(...)` — plain batch DataFrame. No streaming-transform variant for SQL. Enables the ROW_NUMBER dedup pattern: even when the final target is streaming, the intermediate dedup view is batch-evaluated, so window functions are legal.

Caveat: if upstream of the transform is a streaming view, the transform inherits streaming semantics — `spark.sql` over a streaming source IS streaming, and non-time window functions get rejected. The only reliable way to keep a SQL transform batch is to make the upstream batch too.
(Source: `LHP_Reference.md` L5708–L5712)

### `create_auto_cdc_flow` Accepts Batch OR Streaming Sources
DLT's `create_auto_cdc_flow` doesn't enforce a streaming source at declaration time — it resolves the source at runtime. When the upstream is batch (e.g., `type: sql` load + SQL transform), DLT treats each pipeline update as a discrete batch CDC merge. Within-batch dedup happens in the transform; cross-batch dedup via `sequence_by`.

Note: distinct from `create_auto_cdc_from_snapshot_flow`, which requires a `source_function` Python callable returning `(DataFrame, version)` tuples. The two CDC modes are not interchangeable.
(Source: `LHP_Reference.md` L5714–L5731)

### Streaming Target Requires Pure-Append Upstream — SCD2 Source Breaks the Reader
A DLT `streaming_table` reads its upstream with append-only semantics. If the upstream is SCD2 (closes historical rows by updating `__END_AT`), the streaming reader treats those in-place updates as illegal source mutations and fails with `Detected a data update in the source table` — surfaced in the UI as "changes detected in Delta source". Any UPDATE / DELETE / MERGE on the source kills a streaming reader, by design.

Decision rule for target type:
- **Upstream is pure-append** (CloudFiles ingest, append-only event log, append-only STG, `@dp.append_flow` writers with no SCD2 closure) → target can be a `streaming_table`.
- **Upstream is SCD2 or otherwise mutable** (any BRZ SCD2, any CDC-written table where `__END_AT` updates, any MERGE target) → target must be a **materialized view**. MVs recompute from a snapshot of the source — they don't care if rows mutate.

Practical implication for facts: if **any** link in the upstream chain is SCD2, the fact must be an MV. Only facts whose entire upstream chain is append-only qualify as streaming. The mistake is easy to make — you build the fact as streaming because "facts are append-heavy", forgetting that the SCD2 dimension or SCD2 BRZ feeding it violates the reader's contract.

Escape hatches exist (`ignoreChanges` / `ignoreDeletes` reader options) but trade correctness for staying-streaming — they suppress the error at the cost of duplicates or missed deletes. Default to MV instead of patching with these flags.
(Source: personal experience, 2026-04-30 — fact built as streaming on SCD2 upstream)

---

## 7. Performance & Compute

### Continuous vs Triggered Mode
- `continuous: true` — pipeline runs indefinitely, polling for new data. Expensive, only worthwhile for low-latency streaming.
- `continuous: false` (default) — processes available data and stops. Cost-efficient for batch/daily loads.

Dev = triggered. Prod = depends on SLA. Configure per-environment.
(Source: `knowledge.md` L470–L473, `LHP_Reference.md` L5345–L5356)

### Serverless Compute Is NOT Infinite Parallelism
Serverless DLT starts small and autoscales — it doesn't hand you 200 slots on demand. Running multiple large pipelines simultaneously splits available capacity. Sequential execution often finishes faster than parallel on serverless. Orchestration order matters even with serverless.
(Source: `knowledge.md` L475–L479)

### Stop Continuous Pipelines Before Redeploying
A running pipeline uses OLD code after a deploy — conflicts possible (table locks, schema mismatches, stale resource references). Script a pre-deploy routine that lists + stops running pipelines via REST API. Don't rely on manual "remember to stop".
(Source: `knowledge.md` L481–L484)

### First Run vs Rerun — Counter-Intuitive Performance Curves
Observed in a real POC:
- Run 1 (full refresh): BRZ pipelines take longest — historical data materializing.
- Run 2 (rerun): snapshot-CDC BRZ drops dramatically (e.g., 14m → 3.7m) — historical already loaded, only incremental processed.
- Counter-intuitive: STG and regular-CDC BRZ can take LONGER on rerun — CloudFiles re-scanning, larger accumulated state, cold-compute variability.

Don't assume "second run is uniformly faster". Benchmark both first run and rerun before quoting SLAs. Different pipeline types have different perf curves.
(Source: `knowledge.md` L982–L989, L880–L895)

### Cross-Job Pipeline Overlap — No Queue, Second Update Fails
A Databricks job's `max_concurrent_runs: 1` only serializes runs of **the same job**. Two different jobs triggering the same DLT pipeline at overlapping times → the second pipeline update gets rejected fast (~1s) with "pipeline busy". There is no cross-job pipeline queue.

No DAB-native clean solution. Mitigations: schedule staggering (manual triggers still break it), task-level retries with 2-min backoff (gets wiped by regeneration), a master-job orchestrator via `run_job_task`, or consolidate to one owning job.

Lesson: shared pipelines triggered by multiple jobs → overlap failures are inevitable unless serialized externally. Plan retries + staggered schedules from day one.
(Source: `knowledge.md` L938–L955)

### Redeployment Safety — Clean Both Pipelines AND Tables
"Clean slate" = delete pipelines + drop tables + redeploy. Deleting only pipelines leaves tables behind; new pipelines re-read all source files → duplicates. Re-running preprocessing without cleanup overwrites `incoming/` files → Autoloader sees them as new → STG duplicates. BRZ CDC deduplicates, so BRZ is fine — but STG is corrupted.
(Source: `knowledge.md` L496–L500)

---

## 8. Errors & Silent Failures (generalizable)

### Don't Include Auto-Managed Columns in Schema Definitions
If a framework auto-injects certain columns (operational metadata: processing timestamp, source file path, etc.), don't also declare them in the schema YAML. The safety block that re-appends them will produce duplicates → `_LEGACY_ERROR_TEMP_118: DUPLICATE_COLUMN_NAMES`.

Universal rule: when a framework auto-manages certain columns, don't also declare them manually. Identify the boundary of framework ownership and respect it.
(Source: `knowledge.md` L357–L360, `LHP_Reference.md` L4058–L4098)

### Double Braces in Code-Generated YAMLs
When Python scripts generate YAMLs that use `{token}` substitution, f-strings produce `{{token}}` (escaping). The substitution engine can't resolve double-braced tokens.

Fix: use string concatenation or `.format()` instead of f-strings when generating brace-based substitution files. Generalizes: when your generation tool and target format both use braces, pick a non-conflicting generation method.
(Source: `knowledge.md` L362–L365)

### Never Hardcode Environment-Specific Resource IDs
`existing_cluster_id` is workspace-specific. Hardcode it and promotion to a new environment fails with "Cluster does not exist". Use `cluster_policy_id` (defines a cluster shape that can be instantiated anywhere) for production. Environment-specific IDs should live in per-env config files, not inline.
(Source: `knowledge.md` L387–L391)

### Trailing Commas in CSVs → Phantom Empty Column
Many source-system exports (Synapse Link is one) have trailing commas on every row. Spark reads an extra empty `_c<n>` column. Handle defensively:
```python
if len(df.columns) == len(expected_columns) + 1:
    df = df.drop(df.columns[-1])
```
Applied BEFORE column count validation.
(Source: `knowledge.md` L377–L380, L431–L436)

### Leading/Trailing Spaces in Folder Names → Entity Lookup Failure
Source systems can produce folders with leading spaces (`"  team"` vs `"team"`). Schema-lookup code that matches on folder name silently fails — entity not found. Either rename folders at the source, or add `.strip()` defensively in lookup code. Never trust folder/file names from upstream systems to be clean.
(Source: `knowledge.md` L382–L385)

### Template-Level Typos Propagate to ALL Consumers
One typo in a shared template (e.g., `edp_edp_effective_dttm` instead of `edp_effective_dttm`) propagates to every flowgroup that uses it. Runtime fails with `UNRESOLVED_COLUMN` on every table.

Lesson: test shared templates with at least one consumer after every change. Better: add a unit test that runs the template's SQL against a dummy source with expected column names.
(Source: `LHP_Reference.md` L5466–L5470)

---

## 9. Deployment & Environment

### Separate Workspaces AND Catalogs Per Environment
Each environment (dev/test/preprod/prod) should have its own workspace AND its own Unity Catalog. Sharing risks accidental data mutation — a dev pipeline misconfigured to write to a prod catalog will silently corrupt prod data.

Common pattern:
| Env | Workspace | Catalog | Permissions |
|---|---|---|---|
| Dev | own | `_dev_` | relaxed |
| Test | own | `_test_` | mirrors prod |
| Preprod | own | `_prpd_`/`_preprod_` | prod-like |
| Prod | own | `_prod_` | locked down |
(Source: `knowledge.md` L504–L513)

### Per-Environment Configuration Files (No Inheritance)
One config file per environment (`pipeline_config_dev.yaml`, `pipeline_config_prod.yaml`). Each fully self-contained — no inheritance, no conditional logic. Duplication in config is cheaper than debugging a wrong environment override at 2 AM.
(Source: `knowledge.md` L515–L518)

### File Path Casing Breaks on Linux CI/CD
Windows is case-insensitive (`Peoplesoft/` = `peoplesoft/`). Linux (CI/CD agents, Docker, Databricks workers) is case-sensitive (`Peoplesoft/` ≠ `peoplesoft/`). If you develop on Windows and deploy to Linux, case mismatches will pass local tests and fail in CI.

Rule: use lowercase_snake_case for all directory and file names in any repo that runs on Linux.
(Source: `knowledge.md` L520–L524)

### DLT Pipeline Permission Levels Are NOT a Superset of Job Permission Levels
Databricks exposes different permission-level vocabularies per resource type:

| Resource | Allowed levels |
|---|---|
| Job | `IS_OWNER`, `CAN_MANAGE`, `CAN_MANAGE_RUN`, `CAN_VIEW` |
| DLT pipeline | `IS_OWNER`, `CAN_MANAGE`, `CAN_RUN`, `CAN_VIEW` |

`CAN_MANAGE_RUN` is jobs-only; pipelines use `CAN_RUN` (same intent, different spelling). DAB bundle-level `permissions:` fans out to every resource in the bundle — so a level valid only for one resource type will break the deploy if posted to the other.

When copy-pasting permissions between job and pipeline config, re-validate the level names.
(Source: `knowledge.md` L540–L554)

### The "Cannot Remove Permissions" Error Is Misleading
`error: cannot create permissions: cannot remove permissions: allowed permissions levels: CAN_MANAGE, IS_OWNER` — two possible root causes:

1. **Invalid permission level for the resource type** (cheapest to check). Fix the level in YAML.
2. **Deploying user lacks `CAN_MANAGE` or `IS_OWNER` on the pre-existing resource**. To replace an ACL, the caller needs authority over that ACL.

The error always lists "CAN_MANAGE, IS_OWNER" regardless of which root cause applies — it's the set of levels that *would have authorized* the operation, not a diagnosis. Inspect YAML first, UI ACLs second.
(Source: `knowledge.md` L556–L570)

### DLT Pipeline ACLs — Three Sources, One Wins
For a DLT pipeline deployed via DAB, the effective ACL is the combination of:
1. Bundle-level `permissions:` in `databricks.yml` (fans to every resource)
2. Resource-level `permissions:` in generated pipeline YAML (often NOT emitted by the codegen)
3. Manual grants set in the Databricks UI out-of-band

DAB doesn't know about (3). A later `bundle deploy` notices the drift and attempts to remove it, triggering the authority check. Pick ONE source of truth — either bundle YAML (declarative, drift-safe) or UI (flexible, but DAB will fight you). Don't mix.
(Source: `knowledge.md` L572–L584)

### YAML Duplicate Keys Silently Collapse
A common authoring mistake:
```yaml
# WRONG — each user_name: overwrites the previous. Only the LAST survives.
permissions:
  - level: CAN_MANAGE
    user_name: "alice@co"
    user_name: "bob@co"
    user_name: "carol@co"    # only carol survives
```
YAML mapping semantics: duplicate keys → last wins. No error, no warning. Only a failed deploy or a UI audit reveals it.

Correct: one list item per grantee:
```yaml
- level: CAN_MANAGE
  user_name: "alice@co"
- level: CAN_MANAGE
  user_name: "bob@co"
```
Generalizes: any YAML field that takes a list of `{key, value}` pairs has this foot-gun. Always check generated output has the expected count.
(Source: `LHP_Reference.md` L5638–L5670)

### Environment Rename Has Wide Blast Radius
Renaming an env label (e.g., `prprd` → `preprod`) requires coordinated changes across: `databricks.yml` target keys, per-env config filenames (`substitutions/<env>.yaml`, `pipeline_config_<env>.yaml`), README/docs, CI/CD scripts, regeneration commands. The Unity Catalog name (e.g., `bdp4_prpd_lh`) is independent and should NOT be renamed unless separately intended.
(Source: `LHP_Reference.md` L5795–L5810)

### Databricks CLI Gotchas (assorted)
- `databricks pipelines delete` uses positional args, not flags.
- `databricks pipelines list-pipelines` outputs UTF-16 on Windows.
- Deleting a DLT pipeline drops its managed streaming tables (and checkpoints).
- `max_retries` is per-task, not per-job — must be added to each task.
- `notebook_path` in job YAML is relative to the YAML file, not bundle root.
- `${workspace.file_path}` resolves to the bundle deployment location — don't hardcode workspace paths.
- `databricks bundle deploy --force-lock` needed when a previous deploy didn't clean up.
- Windows + LHP emoji output → `UnicodeEncodeError`. Fix: `PYTHONIOENCODING=utf-8 lhp validate ...`
(Source: `knowledge.md` L526–L534)

---

## 10. Orchestration & Jobs

### Master Job Orchestration via `run_job_task`
When you've split a large job into domain-specific children but still need cross-domain ordering (e.g., all STG+BRZ complete before SLV), use a master job with `run_job_task` children:

```yaml
resources:
  jobs:
    master_finance:
      tasks:
        - task_key: run_stg_brz_a
          run_job_task:
            job_id: ${resources.jobs.stg_brz_a.id}
        - task_key: run_stg_brz_b
          run_job_task:
            job_id: ${resources.jobs.stg_brz_b.id}
        - task_key: run_slv
          depends_on:
            - task_key: run_stg_brz_a
            - task_key: run_stg_brz_b
          run_job_task:
            job_id: ${resources.jobs.slv.id}
```

Properties: child jobs remain independently runnable; `depends_on` expresses cross-job ordering; tasks without `depends_on` run in parallel. Databricks-native — no custom Python needed.
(Source: `knowledge.md` L909–L936)

### File-Arrival Trigger Syntax (DAB-Native)
Fire a Databricks job when new files land at a UC volume path. The trigger block goes on the **job** resource (not the pipeline):
```yaml
resources:
  jobs:
    <job_name>:
      trigger:
        pause_status: "PAUSED"   # or UNPAUSED
        file_arrival:
          url: "/Volumes/<catalog>/<schema>/incoming/"
          min_time_between_triggers_seconds: 60
          wait_after_last_change_seconds: 60
```

Key behaviors: `url` must be a UC volume path; subfolder recursion supported; `min_time_between_triggers_seconds` prevents rapid-fire. A job can have EITHER `schedule:` OR `trigger:`, not both.
(Source: `knowledge.md` L957–L980)

### Some Frameworks Only Partially Pass Through Job Config
Codegen frameworks (like LHP) emit job YAML from a schema-documented set of fields. Non-documented fields (`trigger:`, custom retry policies, `run_job_task`) get silently dropped. If you need a feature outside the framework's documented job-config schema, plan for manual post-edit OR a wrapper script from day one.

Implication: every re-run of the codegen wipes the manual edits. The only job YAMLs safe from regeneration are those the codegen didn't emit (e.g., a master orchestrator job with no flowgroup references).
(Source: `LHP_Reference.md` L5589–L5636)

---

## 11. Security & Secrets

### Never Store Credentials in Plaintext
Early dev often starts with plaintext values for speed. That's a security risk the moment the repo is shared, backed up, or pushed. Move all sensitive values to a secret store (Azure Key Vault, Databricks secrets) and reference via placeholder: `${secret:keyvault-name/secret-name}`.

Switch from plaintext to secret references is a **mandatory gate** before promoting code beyond dev.
(Source: `knowledge.md` L588–L592)

### OAuth Refresh Tokens Are Dynamic Secrets
Refresh tokens get overwritten on each API call — the token returned by the auth server replaces the previous. Storing as a *static* secret → stale by next pipeline run.

Solution: write the new refresh token back to the secret store after each successful auth exchange. Lesson: not all secrets are static. Identify which ones rotate and build write-back logic for those.
(Source: `knowledge.md` L594–L600)

---

## 12. Source System Quirks (generalizable)

### Browse Raw Data Before Building Pipelines — 30 Minutes Saves Days
Open actual files in storage. Check formats, count columns, look at edge values (midnight, negative, empty strings, unicode). Source system documentation almost always omits quirks — you only learn them by inspection.

Common quirks to look for:
- Headerless CSVs (header lives in a separate manifest or schema file)
- Trailing commas on every row
- Non-ISO date formats (US `M/d/yyyy`, regional)
- Case variation in folder/file names
- Leading/trailing spaces in folder names
- Multiple entities dumped into one folder (needs splitting)
- Metadata-only changes causing CDC churn (need `track_history_except`)
- Schema divergence across years of exports

30 minutes of data exploration saves days of debugging later.
(Source: `LHP_Reference.md` L4890–L4903, `knowledge.md` L606–L612)

### Source-Specific Date Format Awareness
Even within ONE vendor's export pipeline, different columns may use different date formats (e.g., business timestamps in ISO 8601, metadata timestamps in US format). Never assume "the source uses one format". Check every timestamp column individually. Don't rely on the source-system type label (`DateTime`, `DATETIMEOFFSET`) — it tells you what the source system calls the type, not how it's serialized.
(Source: `knowledge.md` L218–L226, `LHP_Reference.md` L4335–L4411)

### When Multiple Sources Feed the Same Layer, Standardize Names Early
If multiple data sources (API + BYOD + on-prem file dump) all feed the same Bronze table, standardize column names at the earliest point. A mismatch in one column name between source-function SQL and CDC keys causes silent data corruption or `UNRESOLVED_COLUMN` crashes.

The cheapest convergence point is the earliest one — the longer a mismatch propagates, the more places it has to be fixed.
(Source: `knowledge.md` L665–L676)

---

## 13. Meta-Lessons (Aphorisms)

A short list to internalize. Each is distilled from a concrete incident documented above:

1. **Silent failures are worse than loud failures.** A crash with a clear error is a gift — it tells you exactly where to look. Silent NULL / silent dedup / silent drop is debugging hell.
2. **Enforce schema once, at the boundary.** Redundant enforcement is pure maintenance burden. Pick the gate; trust both sides.
3. **Every row needs operational metadata.** Processing timestamp, source file path, source modification time. You will need them for debugging, reprocessing, and sequencing — always, eventually.
4. **Fail fast, fail specific.** `raise ValueError(f"...")` with context beats routing to `/unprocessed/`. Nobody watches dead-letter folders.
5. **Design around framework limitations, don't fight them.** Every workaround that edits generated code is a future regression.
6. **Generated code is an artifact, not a source of truth.** Edit the config and regenerate. If you can't express the change in config, the config is wrong.
7. **Batch-generate at scale.** 200 entities = one Python script generating 200 YAMLs, not 200 copies of copy-paste.
8. **Test with small data first, scale second.** Run the pipeline on 5 rows before 5 million.
9. **Document the type-mapping chain.** Source → CSV → Spark → STG → BRZ. Make the "where do I cast?" question have one answer, not three.
10. **Don't test hard gates. Test silent failures.** If it crashes loudly, you don't need a test. Test what can be wrong without looking wrong.
11. **Browse raw data before building pipelines.** The 30-minute investment is the highest-leverage thing you do on a new source.
12. **When the source is already SCD2, don't run CDC on top.** Double SCD2 breaks on `sequence_by` ambiguity. Collapse to current-only or preserve with direct column mapping.
13. **Two-job pattern beats forcing mixed workloads into one.** Notebooks for file ops, DLT for streaming CDC. Independent compute, independent failure domains.
14. **Layer responsibility separation.** Each layer has ONE job. Mixing responsibilities destroys debuggability.
15. **Developer isolation needs full-stack namespacing.** Missing the suffix in ONE reference breaks everything. Check every layer.
16. **Streaming target ↔ pure-append upstream. SCD2 source ↔ MV target.** Any UPDATE/DELETE/MERGE on the source kills a streaming reader. If the chain has any SCD2 link, the target must be a materialized view, not a streaming table.
(Source: `knowledge.md` L633–L650, `LHP_Reference.md` L4849–L5022)

---

## Learning Journey & Workspace Progress

> Snapshot of work completed beyond the original BUPA project. This section is a progress log — a record of what's been built, where to find it, and how it maps to the lessons above. Update as the journey continues.

### Timeline of major milestones

| When | What |
|---|---|
| Pre-session | First production project complete: BUPA / Apollo Gen2 (Databricks DLT + LHP framework, medallion architecture, Dynamics 365 + PeopleSoft + LRC API sources). All the original lessons in this digest came from that work. |
| Session start | Distilled the BUPA project knowledge files (`knowledge.md`, `LHP_Reference.md`) into this transferable digest — 13 thematic sections + meta-lessons. |
| Session — research | Catalogued every meaningful Lakeflow Spark Declarative Pipelines (SDP) feature released **November 2025 → April 2026**. Mapped each against the original BUPA lessons (which are now obsolete vs. still hold). |
| Session — notebook | Built `notebooks/sdp_2026_features.py` — a hands-on, runnable reference for all 18 new SDP/Lakeflow features with sample data and verification queries. |
| Session — deployment | Set up Databricks Asset Bundle (`databricks.yml`) targeting two workspaces. Established `dbdemos.myschema` as the canonical demo schema. |
| Session — consolidation pass 1 | Audited 35 legacy learning notebooks across 8 folders. Consolidated to 19 (16 fewer files, zero content lost). Modernized every deprecated API. Added setup data + concept markdown to every notebook. |
| Session — consolidation pass 2 | Topic-merged Databricks Features (3→1) and Databricks Prof. (2→1). Deleted Spark Read-Write (covered in PySpark §11). User-side: deleted Workflow folder, renamed PySpark → PySpark_Python_for_DE. **Final count: 12 notebooks across 7 folders.** |

### Workspace notebooks (deployed at `/Workspace/Users/swaraj.negi@celebaltech.com/Learning/`)

**Final state — 12 notebooks:**

| Folder | Notebook | What it demonstrates | Maps to digest section(s) |
|---|---|---|---|
| **DLT Learning** | `DLT_SQL_Pipeline` | Bronze → Silver → Gold in pure SQL with `AUTO CDC INTO` for SCD2 | §1 Architecture, §3 CDC, §6 DLT |
| | `DLT_PySpark_Pipeline` | Same pipeline in `pyspark.pipelines` (Python decorators) | §1, §3, §6 |
| **Optimization** | `Optimizations_SQL` | OPTIMIZE / ZORDER / Liquid Clustering / MERGE with pruning / CDF | §6 Delta, §7 Performance |
| | `Optimizations` | Spark-level: AQE knobs, repartition+partitionBy, broadcast, cluster sizing Q&A | §5 Spark gotchas, §7 Performance |
| **PySpark_Python_for_DE** | `PySpark_Comprehensive` | DataFrame API tour: filter/join/window/UDF/nested/dates/IO | §5 Spark gotchas, §6 Delta IO |
| | `Python_for_DE` | Python language patterns: strings/comprehensions/dataclasses/error handling | (general DE) |
| **Ingestion** | `Ingestion Learning` | PySpark ingestion: spark.read, COPY INTO, Auto Loader, JDBC writes | §6 Autoloader |
| | `Ingestion Serverless` | SQL ingestion: read_files, CTAS, COPY INTO, streaming-table Auto Loader | §6 Autoloader |
| **Practice** | `Practice_Python` | 12 PySpark drills: top-N, percent-of-total, lag, pivot, dedup, anti-join, self-join | §5 |
| | `Practice_SQL` | Matching SQL drills + recursive CTE + time travel | §6 |
| **Databricks Features** | `Databricks_Features` | **Comprehensive single-notebook reference** covering all 10 DBX features: `_metadata`, `read_files`, serial columns, `_rescued_data`, JSON parsing (`from_json`/`parse_json`/`schema_of_json`), `explode`, Change Data Feed + `table_changes`, hash-based MERGE for dedup-aware upserts, full DQE toolkit (CHECK constraints, `@dp.expect_*`, UC-stored expectations) | §2 Schema, §4 DQ, §6 Delta |
| **Databricks Prof.** | `Databricks_Advanced` | **Comprehensive single-notebook reference** covering: 3 SCD2 implementations (manual MERGE → foreachBatch + MERGE → AUTO CDC) + soft-delete pattern, `EXCEPT` + version diffs, stream-stream joins + watermarking, row filters + column masks (UC privacy), `information_schema` discovery, Delta file metadata inspection, programmatic `DeltaTable.merge()` upsert | §3 CDC, §6 Delta, §9 Deployment |

### Removed (deliberately)

| Removed | Reason |
|---|---|
| `Workflow/Book 1`, `Book 2`, `Book 3` | Deleted — minimal value as standalone learning artifacts; chained-job pattern is documented in this digest §10 if needed |
| `Spark Read-Write` (standalone) | Folded into `PySpark_Comprehensive` §11 — eliminated redundancy |
| `Databricks Features/CDF`, `DBX Features`, `Data Validation` | Merged into `Databricks_Features` (one comprehensive notebook covering all DBX-specific features) |
| `Databricks Prof./SCD 2`, `DBX Professional` | Merged into `Databricks_Advanced` (one comprehensive notebook covering all advanced patterns) |

Plus the standalone:

| Path | Purpose |
|---|---|
| `notebooks/sdp_2026_features.py` (deployed at `Learning/Consolidated Learnings/notebooks/`) | Full hands-on tour of every Nov-2025 → Apr-2026 SDP/Lakeflow release: API rename, ARM compute, AUTO CDC SCD1/2, auto-coalesce, multi-flow CDC, datetime rebase, AUTO CDC FROM SNAPSHOT, type widening, queued execution, `cascade=false`, cluster reuse, pipeline hooks, UC-stored expectations, SQL in foreachBatch, audit log, `COUNT(*)` myth-buster, cheatsheet. |

### Disciplines established this session

These are operational disciplines now baked into every notebook in the workspace. Treat them as *additional meta-lessons* on top of the §13 list:

1. **One canonical demo schema (`dbdemos.myschema`)** — every learning notebook uses the same target schema and the same `/Volumes/dbdemos/myschema/demo_volume` for files. Eliminates "wait, which schema does this expect?" friction.
2. **Setup section at the top of every notebook** — generates sample data via SQL `VALUES` or Python, so the notebook is self-contained. No external file dependencies that decay over time.
3. **Concept-explainer markdown above every code block** — answer "what does this teach? when would you reach for it in real work?" in 2-3 sentences before the code. Makes the notebook a learning artifact, not just a script.
4. **Modern API only in tutorial code** — `pyspark.pipelines` (not `dlt`), `AUTO CDC` (not `APPLY CHANGES`), `STREAMING TABLE` (not `INCREMENTAL LIVE TABLE`), `read_files()` (not `csv.\`<path>\``). Old syntax shown only as historical context.
5. **Decision matrices for multi-approach topics** — when a topic has multiple valid approaches (manual MERGE vs AUTO CDC; ZORDER vs Liquid Clustering; CDF vs version diffs), include a comparison table so the right call is obvious.
6. **Consolidation over diversification** — through two passes, 35 → 12 notebooks. Pass 1 merged trivially-related files (DLT Bronze/Silver/Gold layers, scattered optimization snippets, language-paired practice files). Pass 2 went further: topic-merging within a folder when the topics were "what makes Databricks different" (CDF + read_files + DQE → one comprehensive `Databricks_Features` notebook; SCD2 + advanced patterns → one `Databricks_Advanced` notebook). New rule of thumb: **"if a folder has multiple notebooks each demonstrating a different feature of the same product surface, merge them into one comprehensive runnable notebook."** Easier to navigate, easier to remember "where did I learn that?", and forces the writer to draw connections across features.

7. **Delete what doesn't teach** — `Workflow/Book 1/2/3` (chained job tasks) and `Spark Read-Write` (redundant with PySpark §11) were deleted entirely. A notebook that's hard to justify as a learning artifact is dead weight. Better to remove and restore from `learning_mirror/` if needed than to keep clutter that distracts from real learning material.

### Status of the original digest entries (post-2026-research)

The §3 CDC and §7 Performance sections of this digest were authored against the BUPA-era platform. Several lessons are now **partially or fully obsolete** because the 2026 platform releases fixed the underlying gaps. A status entry has been added to:

- §3 CDC: "Auto-Coalesce Applies to AUTO CDC, NOT AUTO CDC FROM SNAPSHOT" (added during the auto-coalesce/BYOD correction)
- §7 Performance: "Cross-Job Pipeline Overlap" — now solved by **queued execution mode** (Jan 2026)
- §9 Deployment: "DLT Pipeline ACLs" — partially solved by **MANAGE permissions auto-propagation** (Jan 2026)

The architectural and discipline lessons (§1 Architecture, §2 Schema discipline, §4 Testing philosophy, §13 Meta-Lessons) are timeless and remain unchanged.

### Outstanding artifacts on local disk

| Path | Purpose | Keep? |
|---|---|---|
| `notebooks/sdp_2026_features.py` | The Nov-2025 → Apr-2026 SDP feature tour | Yes — primary reference for the modern platform |
| `learning_mirror/**` | Full local backup of every workspace notebook (pre and post consolidation) | Yes — safety net for any rollback |
| `databricks.yml` + `.databrickscfg` profile | Bundle deployment config for both workspaces | Yes — used for ongoing iteration |
| `.gitignore` | Excludes secrets, state, venv | Yes |

### Suggested next learning steps

1. **Run the SDP 2026 features notebook end-to-end** — pick one section per session, run it, inspect the output. The `Setup` cell creates everything you need.
2. **Pair the Practice notebooks with timed self-tests** — read each drill's problem statement, time-box yourself for 5 min, then check against the worked solution.
3. **Re-read §3 CDC + §13 Meta-Lessons quarterly** — the BUPA SCD2-on-SCD2 trap (Meta #12) is the kind of lesson worth refreshing on. New projects expose new variants.
4. **Track new SDP releases** — Lakeflow Spark Declarative Pipelines release notes update monthly. The §3/§7 obsolescence pattern will continue; revisit and update this section every 3-6 months.

---

## Appendix — Source File Map

- **`knowledge.md`** (1086 lines) — data engineering knowledge, 11 sections. Originally organized by theme (architecture, CDC, schema, QA, errors, decisions, patterns, compute, deployment, security, platform checks).
- **`LHP_Reference.md`** (5823 lines) — LHP framework knowledge + universal lessons. Section 14 ("Lessons Learned") is explicitly marked "universal principles, not LHP-specific". Gen2 session learnings at the end have transferable DE nuggets mixed with LHP-specific bugs.
- **`index.md`** — auto-generated compact map of both files, with line ranges. Regenerate via `python "claude ref/build_index.py"` after any edits.

## Lessons NOT Extracted Here (Deliberately Excluded)

The following are LHP-framework-specific and don't generalize to non-LHP projects:
- LHP error code reference (`LHP-CFG-*`, `LHP-VAL-*`, `LHP-IO-*`, `LHP-ACT-*`, `LHP-DEP-*`)
- LHP template parameter substitution order (`%{var}` vs `{token}` vs `{{jinja}}`)
- LHP CLI commands (`lhp validate`, `lhp generate`, `lhp deps`)
- LHP presets / inheritance / template structure
- LHP `write_source_view` hook pattern (useful inside LHP, but the principle — "make templates extensible via optional parameters" — generalizes; see Section 1 "Framework Limitations Are Architectural Constraints").
- LHP packaging bugs (e.g., missing `.j2` files in a wheel)

If you move to a different framework (dbt, Dagster, Airflow + raw DLT, etc.), these don't carry over. The patterns and principles above do.
