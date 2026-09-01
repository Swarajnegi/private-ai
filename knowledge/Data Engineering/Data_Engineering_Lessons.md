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

### Scope Handles: Pass One Token, Not the Payload
Instead of passing 22,000 table names between jobs, regions and notebooks, pass **one opaque token** and let each consumer re-derive the same working set from a shared audit table. Cheap to pass, precise, and it survives the set being large. **Recognising when a token can replace a payload is the reusable idea.**

But the enabling condition has to be stated plainly: **"give me a run_id and I'll tell you every table that run touched" is NOT a built-in platform capability.** It worked here only because the clone framework writes its **own** audit table — one row per object per run, carrying `run_id`, catalog/schema/object, `run_ts`, `status`, `error_message`, a size signal, and stream name. That table is application code someone chose to write. **Do not assume the capability exists on a platform where nobody built it.**

- **Match the handle to the question's shape.** A `run_id` answers *"which objects did **this run** touch."* It cannot answer *"which objects have been incrementally cloned **since some point in time**"* — that spans many runs and needs a **timestamp** as the handle, filtering the same audit table on `run_ts > T`. Same table, different handle, because the questions have different shapes. Reaching for run_id when the question is temporal is how you end up with an unanswerable scope.
- **The platform *does* record provenance, just table-first rather than run-first.** Delta's `DESCRIBE HISTORY` identifies the job and notebook behind each commit, so per table you can ask "which run wrote this." The limitation is *direction*: you must already have candidate tables to inspect. Going run → tables needs either your audit table or UC lineage/system tables (`system.access.*`), and the latter is subject to enablement and retention. **Verify what your workspace actually exposes before designing on it.**
- **The audit table earns its keep by carrying what lineage cannot.** Per-object `status` and `error_message` distinguish *"the process never produced this object"* from *"it produced a bad copy"* — a distinction lineage has no concept of, and the one that makes a downstream comparison report meaningful rather than just a list of mismatches.
- **Carry a size or cost signal in the audit row.** A `copied_file_size` recorded at write time became the input for size-tiering the downstream validation clusters — the only size signal available early enough to route work, because the obvious alternative is computed by the very task the routing decides. **Audit rows are a good place to stash cheap facts a later stage will need before it can afford to measure them itself.**
- **If you will ever need to ask "what did run X touch", design that table before the first run.** Retrofitting it from history or lineage is possible, lossy, and slow — and the data you most want (*why* a given object failed) was never captured by anything but the writer at the time.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### DR/Migration Validation: Scope First, Resolve Versions Second, Check Feasibility Third
When validating a bulk migration/DR clone operation (e.g. Databricks Deep Clone across regions), don't validate the whole catalog — scope to exactly what one `run_id` touched. Three-step pattern:
1. **Scope**: query the clone operation's own metadata for the exact list of objects (tables/views/volumes) it touched for that `run_id`. Output as a manifest (e.g. CSV to an external location) — everything downstream works from this scope, not from "all tables."
2. **Resolve versions**: for each scoped table, find the exact source-side version the target was cloned FROM (not just "the current source version") — see the `DESCRIBE HISTORY` lesson in §6.
3. **Check feasibility before querying**: a resolved source version is a fact, not a guarantee it's still queryable — see the retention-window lesson in §6. Skip (don't error) rows that fail feasibility.

Comparing counts/data only makes sense between resolved-and-feasible version pairs — a naive "compare current state on both sides" test would silently compare mismatched points in time.

Two more details worth building in from the start:
- **Pin resolved versions, don't re-resolve "latest."** Write the resolved src/tgt versions to their own persisted output (e.g. two CSVs) at resolution time, and have every downstream query read from that pinned value — never re-query "latest CLONE version" mid-run. Otherwise a clone that re-runs while your validation is still executing silently invalidates the version you scoped against.
- **Report skips, don't just omit them.** A table skipped for retention infeasibility should show up in the final output as a counted, explicit skip — not just be absent, which would look identical to "validated and fine."
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-08)

### Three Verdicts, Not Two: PASS / FAIL / NOT MEASURED
A binary pass/fail hides the difference between **"wrong"** and **"couldn't tell."** A target extract that hit `PERMISSION_DENIED` on 10 of 19 columns reports as "FAIL 35/35", which reads as *the clone lost all the data* when the truth is *we were not allowed to look*. Those are opposite conclusions and must never collapse into the same alarming number.

The rule that makes it work: **NOT MEASURED is never folded into FAIL.** Permission errors, extractor bugs and unsafe time-travel windows all produce it. And note the related trap — an extractor that collapses "denied" into a plain `false` is indistinguishable from a real absence when read in isolation, so any object with a permission error on *any* column should be marked extraction-blocked wholesale, with its boolean-false checks reported NOT MEASURED rather than FAIL. Always show the blocked count; never hide it.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-22)

### A Failure Count Is Not a Finding — Group Before You Report
A recovered validation run showed 465 passes and **88 failures**, which read as a serious clone defect. The breakdown changed the story completely: all 88 were **source-side** (three storage accounts, all in the source region), **zero** were row-count mismatches, and the causes were 52 `FAILED_READ_FILE.DBR_FILE_NOT_EXIST` plus 35 `FileNotFoundException` 404s — source files vacuumed away between clone time and validation time. Not one said anything about the clone.

**Forward rule:** group by side, by error class, and by object *before* reporting. The grouping usually **is** the diagnosis, and an ungrouped count sends people to debug the wrong component.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Guard Against "Confident Wrong Answer" Harder Than Against "Crash"
A function that returns `0` or `{}` on an edge case it cannot actually handle is **worse** than one that raises. The caller can route an exception to NOT MEASURED; a silently-wrong zero looks exactly like a real, passing measurement. Same failure shape as unpopulated `operationMetrics` (§6) and as a mis-split fan-out (§10) — in every case the system produced a number nobody could tell was meaningless.
(Source: BUPA — Region Migration project, 2026-08-22)

### Comparing an Evolving Source Against a Frozen Target Is Not a Fair Test
No comparator is good enough to fix this. The remedy belongs at the **measurement** layer — pin both sides to the same version — not in how differences are reported afterward. Any live-only read (`DESCRIBE DETAIL`, `SHOW TBLPROPERTIES`, anything in UC) paired against a version-pinned counterpart has this defect built in.
(Source: BUPA — Region Migration project, 2026-08-22)

### A Mode Switch Beats a Parallel Implementation — With One Condition
Adding a second family of checks as an `inc=true/false` mode on the existing notebooks, rather than duplicating them, avoided copying ~1,800 lines of renderer and comparator logic that would then have drifted. **The condition for this being safe is that the two modes are genuinely mutually exclusive** — if both could run at once you are building a flag, not a mode.

Four things that made it work, all reusable:
- **Put the mode gate at the single point every path already passes through.** One four-line guard inside the function every check card renders through beat wrapping twenty-odd call sites — and it cannot be forgotten when a new card is added later. *Finding that convergence point is usually the whole design.*
- **Derive the output shape from one named set, never a second list.** Column ordering, the extractor loop and the written schema all deriving from a single `ACTIVE_CHECKS` list means a mode switch changes one line. An earlier version iterated a *different* dict for column headers and would have emitted nine all-NaN columns that look exactly like measurements nobody took.
- **Prove the old path is unchanged; don't assert it.** Executing the registry cells from the pre-change commit and from HEAD, then diffing the resulting check lists element-by-element, turns "I only added an else branch" into evidence — and catches the reordering a set comprehension or dict-iteration change silently introduces.
- **Choose deliberately what the new mode does *not* fold in, and record why.** Excluding a 22-hour full diff from the incremental report was a design decision, not an omission: including it would have serialised a four-hour report behind it. Write the reasoning next to the exclusion or someone "fixes" it later.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### An Absolute Threshold Is an Absolute Answer to a Relative Question
A fixed 50 GB tier boundary was applied to an estate whose largest table was under 50 GB, so **every** table classified "small": the large-tier cluster started, found zero tables and exited after eight minutes while the small tier ran past twelve hours.

Switching to a population statistic is the right instinct — but the *median* was also degenerate here, because most tables reported zero size, and the median of a zero-heavy population is zero, which routes the entire estate the other way. The **mean over non-zero values** was the workable choice.

**Forward rule:** derive split points from the data, but inspect the distribution first — count the zeros and nulls before choosing a statistic, and keep a sanity check that raises when a computed threshold would put every item on one side.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Verify Your Tiering Key Correlates With Cost Before Tiering On It
Tables were split into tiers by **bytes**, assuming bigger tables cost more to validate. The measurements disagreed: an **18:1** split by table count produced only a **5:1** split in runtime — meaning the extractor's cost was *per-table* (Delta log reads, metadata calls) and almost independent of table size. The estate was being load-balanced on a variable that barely predicted the thing being optimised.

**Forward rule:** ratio your candidate key against observed runtime before committing to it. If the ratios don't track, you're balancing on the wrong axis — and the right lever changes with it: **per-item cost wants more workers (more chunks); per-byte cost wants bigger ones.**
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Know Your Recovery-Source Hierarchy Before You Need It — the Friendliest Artifact Is Often the Lossy One
A 12-hour run was cancelled before writing output. The results still existed in two places and they were **not** equally good:

| Source | Recovered | Integrity |
|---|---|---|
| Notebook HTML export | 452 of 547 | **Silently truncated** — `*** WARNING` marker, visible gaps |
| Driver stdout | 553 (171 + 169 + 213) | Complete, zero gaps |

The polished, shareable artifact lost **17%** of the data; the raw log lost none.

**Forward rule:** when reconstructing from logs, prefer the rawest source available and **verify completeness independently**. A sequence counter or expected total in the output is what turns "looks complete" into "is complete" — design it in deliberately. It costs one integer, and here it was the only reason the truncation was detectable at all.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### `exceptAll` Is a Full Shuffle of Every Column on Both Sides
Spark rewrites it to a `GROUP BY` over all columns with a ±1 sentinel — deductive and exact, but the cost is proportional to **total row bytes moved across the network**, not to how different the tables actually are. Two near-identical billion-row tables cost the same as two completely different ones.

Three consequences worth holding together:
- **Row counts are usually free; set differences never are.** Delta answers `COUNT(*)` from log statistics in most cases; there is no equivalent shortcut for an exact multiset comparison.
- **A checksum/hash comparison is a different kind of claim, not a faster version of the same claim.** `exceptAll` is deductive — mathematically complete. Summing per-row hashes is probabilistic: overwhelmingly reliable, but not "we compared every row." Surface that distinction *before* it goes into a sign-off.
- **One-sided set difference can prove full equality**, given a side condition: if `|A| = |B|` and `B \ A = ∅` then `A = B`. A two-sided guarantee from the cheaper one-sided computation.

(Source: BUPA — Region Migration project, 2026-08-22)

### `spark.conf.set` Is Session-Global, Which Breaks "Tune Per Workload" Thinking
You cannot safely give different threads different shuffle-partition counts inside one SparkSession. The fix is **phased or tiered execution** — all the giants together under one setting, then all the small tables under another — not per-thread config.

Relatedly, **"just set shuffle partitions high" has a real cost on the small end.** AQE coalesces partitions only *after* the shuffle write, so a 10-file table still pays for planning against 2,048 partitions even though most collapse away. `spark.sql.shuffle.partitions = "auto"` lets AQE size it per query from actual input statistics instead of one static guess applied to every table.
(Source: BUPA — Region Migration project, 2026-08-22)

### PySpark / pandas Gotchas Worth Recognizing On Sight
- **`dict(a_spark_row)` doesn't do what it looks like.** `Row` iterates over its *values*, not `(key, value)` pairs, so `dict()` misreads it. Use `.asDict()`.
- **`spark.read.json()` infers any nested JSON object as a STRUCT, never a true `MapType`** — even for a field that is logically `map<string,string>`. Code expecting a dict must normalize explicitly regardless of source.
- **CSV round-trips between pandas and Spark need explicit escape handling.** `pandas.to_csv()` doubles embedded quotes (RFC 4180); Spark's reader defaults to backslash-escaping. Without `.option("escape", '"')`, a quoted value with an internal comma **silently shifts every later column** — no error, just corrupted rows. Add `.option("multiLine", "true")` too when the reader rewrites the file in place, or a cell with an embedded newline becomes phantom rows.
- **A pandas CSV round-trip silently converts an integer column containing any blank into float.** A version written as `836` returns as `836.0`, and `"836.0" != "836"` fails every downstream string comparison — on *every* row, so it reads as a total mismatch rather than a formatting artifact. One NA promotes the whole column, because pandas has no default integer dtype with missing values. Normalise through `int(float(x))` at every read boundary or use nullable `Int64`. **Be suspicious of any comparison that fails 100% rather than partially — that pattern is nearly always a type or format issue, not a data issue.**
- **`~col.isin([...])` silently drops NULLs**, because SQL's `NOT IN` is three-valued: `NULL != 'X'` is NULL, not true, so rows with a null in the filtered column vanish from scope. In a scope-building filter that is silent data loss at the very first step. Decide explicitly what NULL should mean, and **count the nulls you drop**.
- **`groupBy().agg(F.max(col))` doesn't guarantee other columns come from that same max row.** For several columns tied to "the latest row", use `row_number() over partitionBy(...).orderBy(... desc())` — an aggregate can silently mix values from different rows.
- **Multi-statement `%sql` cells only display the last statement's result.** The earlier ones ran; their output just isn't rendered. Easy to misread as "didn't execute."
- **Serverless / Spark Connect blocks reading certain Spark confs outright**, which is distinct from "the value isn't set." The error looks like a runtime failure but is a compute-tier restriction.
- **Databricks notebooks compile each cell independently, so control flow cannot span cells.** An `if` opened in one cell does not indent the next — the result is `unexpected indent` on every following cell, which reads as a dozen unrelated syntax errors rather than one structural mistake. To gate a lot of notebook code, find the one function every path already funnels through and put the guard *inside* it. Related: `from __future__ import annotations` in any cell but the first makes the whole file fail `py_compile` while remaining valid at runtime — so validate notebooks **cell-by-cell** (`ast.parse` per cell), not as one file.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### `DESCRIBE HISTORY` + `operationParameters.sourceVersion` Reveals Exact Clone Lineage
Filtering a table's `DESCRIBE HISTORY` by `operation = 'CLONE'` and taking the latest such row gives you `operationParameters.sourceVersion` — the *exact* source-side version that specific clone was made from. This is the authoritative way to map a cloned target back to its source version; don't assume "latest source version" or try to infer it from timestamps — Delta Lake already records it.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-08)

### A Governed Delta Table Has THREE Stores on THREE Different Clocks — Find the Store and the Clock Follows
> **Corrected 2026-08-22.** The earlier version of this lesson said "Delta's default retention window is 7 days (168h); gate every resolved historical version on `now() - commit_ts > 168h`." That was the *then-current implementation*, not the rule, and the framework has since disproved it (`RETENTION_HOURS` is now 720). The error was distilling a **threshold** instead of a **mechanism** — thresholds are consequences and don't survive a fix. Recorded rather than silently overwritten, because a wrong reason is worse than no reason.

A version number existing in `DESCRIBE HISTORY` doesn't mean you can query it — but *which* thing expires depends entirely on which store answers your question. There are three, and they are governed by different clocks (or none):

| Store | Governed by | Default | Answers |
|---|---|---|---|
| Physical data files | `deletedFileRetentionDuration` (VACUUM) | **7 d** | Anything reading row *values* |
| `_delta_log` (commit JSONs + checkpoint Parquet) | `logRetentionDuration` | **30 d** | Schema, file counts, sizes, properties, partitioning, comments, all history |
| Unity Catalog metastore | **neither** | — | Registration, tags, PK/FK constraints, grants |

**What only the data files can answer** — and therefore the *only* checks the 7-day clock can break: set comparison (`exceptAll`), row sampling / decode probes, checksums, and any aggregate over a column. A much shorter list than it feels like.

**What the log answers alone**, valid the full 30 days *after* VACUUM has removed every data file: column names/types/nullability (`metaData.schemaString`); ordinal column order; file count and total bytes (replay AddFile minus RemoveFile by path); table properties (reconstructable from `metaData.configuration` + `protocol`); partition columns; table and column comments; column-mapping mode; deletion-vector settings; and every `DESCRIBE HISTORY` question.

**The third store is where most confusion lives.** UC has *no time travel over any of it*, so pairing a live UC read against a version-pinned Delta read silently compares **now** on one side against **then** on the other. That's a liveness problem, not a retention problem, and no larger window fixes it.

**Why this matters more than it sounds:** applying the 7-day data-file gate to all twelve checks in a validation suite, when only two of them touch data files, discarded roughly **20,000 valid log-sourced measurements per run**. A gate's blast radius should match its actual cause.

Two refinements worth carrying:
- **`COUNT(*)` is the interesting edge case.** Delta usually serves it from per-file `numRecords` statistics in the log rather than scanning, so it behaves like a log-only read — pinned row counts kept succeeding long past the 7-day window on a real estate. But that's an *optimisation, not a contract*: absent stats, it falls back to reading files. Treat it as "usually log, occasionally data" and don't build a guarantee on it.
- **Log replay needs a checkpoint at or before your target version**, not just the commits. If log cleanup removed that checkpoint, the AddFiles from the missing range are simply absent and a naive replay silently **under-counts** — which looks exactly like a table that legitimately shrank. Detect the gap and raise.

(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-08; corrected and expanded from `SESSION_LEARNINGS.md`, 2026-08-22)

### `SELECT * WHERE 1=0` Is a Free Full Schema Read
The predicate is unsatisfiable, so Spark plans a scan of nothing and returns the real schema from `metaData` — a complete column/type/nullability signature with **zero file reads**. Reusable anywhere you want a schema without paying for a read, and it survives VACUUM because it never touches a data file.

Related: fetch the `metaData`/`protocol` pair **once** and pass it to every dependent check. Partitioning, table comment, column comments, column-mapping mode and deletion vectors are all fields of that same pair — letting each check re-trigger its own log walk is the difference between one scan and five.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-22)

### Prefer the Log Over Convenient SQL When You Need Time Travel
`DESCRIBE DETAIL` and `SHOW TBLPROPERTIES` are friendlier, and both are **live-only** — no `VERSION AS OF` variant exists for either. Comparing one against a version-pinned counterpart silently compares live-now against frozen-then. Reconstructing the same facts from the transaction log is more work and buys both time travel and 30-day durability. Note `SHOW TBLPROPERTIES` is not merely `metaData.configuration`: protocol-derived entries surface there too, so a faithful reconstruction must merge both.

Also: workspace-level Delta defaults (`spark.databricks.delta.properties.defaults.<prop>`) are a distinct thing from per-table properties. `SHOW TBLPROPERTIES` on an existing table only shows an override if one was explicitly set — absence means "inheriting the built-in default", not "unset".
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-22)

### A CLONE Commit Records Far More Than "A Clone Happened"
Beyond `operationParameters.sourceVersion`, a CLONE row in `DESCRIBE HISTORY` carries `operationMetrics` — `numCopiedFiles`, `copiedFilesSize`, `sourceNumOfFiles`, `numRemovedFiles` — plus the commit `timestamp`. One query on the target yields both sides' versions, the volume actually copied, and when. **Read the full `operationMetrics` map for any operation before building an audit table to record what Delta already recorded.**

- **Counting CLONE commits is a truthful incrementality test.** Two or more means a previous clone exists, so this one is genuinely incremental; exactly one is a first load; zero means never cloned. Stronger evidence than a `sync_type` column in your own audit log, because it comes from the engine's record rather than from what the orchestrator *believed* it was doing.
- **`operationMetrics` is only populated if the writer collected it.** A clone path running with metrics collection disabled leaves `numCopiedFiles` and `copiedFilesSize` structurally zero — measured at zero for all 13,574 tables in one environment. That zero means "not measured", not "nothing copied", and anything that averages or sums it produces a confident wrong answer.
- **`MAX(version)` survives log truncation.** Comparing the version recorded at clone time against the source's current maximum tells you whether the source has moved since — and unlike a pinned read it needs no specific commit to still exist, so it stays valid past `logRetentionDuration`. A check built this way can be deliberately *exempted* from the retention gate that pinned reads require.

(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-22)

### Deep Clone Copies Data Files, Not Unity Catalog Metadata
PK/FK constraints, table tags and column tags live in UC's own catalog, not in the Delta transaction log. **A clone can be byte-perfect on data and still lose all of it.** Any DR sign-off that only compares data has not compared the thing most likely to be missing.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-22)

### The UC Path and the Direct Delta Path Are Two Different Routes to the Same Table
`SELECT ... FROM catalog.schema.table` (Unity Catalog path) and `SELECT ... FROM delta.\`abfss://...\`` (direct storage path) can hit different permission models even though they read the same underlying data. Two consequences worth knowing:
- If a UC grant is missing or a query pattern isn't UC-compatible, the direct delta path is a legitimate fallback — not a hack — as long as you have storage-level access.
- If storage (e.g. ADLS) is reachable from both regions/workspaces, a script running on ONE side can query BOTH sides' tables via their direct delta paths — you don't need compute co-located with the data for read-only validation.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-08)

### UC Row-Filters/Column-Masks Block Time Travel — Bypass via Delta Path on a Non-UC Cluster
Tables with Unity Catalog row filters or column masks applied can't be time-traveled through the normal UC-enabled query path — the governance layer doesn't have defined behavior for "show me this masked/filtered view as of version N." Workaround: query the table's direct delta path from a cluster that isn't enforcing UC's masking/row-filter policies, which reads the raw data without the policy layer in between. Find which tables need this treatment proactively via Unity Catalog's `information_schema` row-filter and column-mask metadata — don't wait to discover it from a failed query.
(Source: BUPA — Region Migration project, DeepClone validation framework, 2026-08-08)

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

### Cloud vCPU Quota Is Per VM *Family*, Per Region, Per Subscription
Not per pool, per cluster, or per workload. On Azure the buckets have names like `standardESv5Family`, `standardDDSv5Family`, `standardDSv5Family`, and an `AZURE_QUOTA_EXCEEDED_EXCEPTION` names the one you exhausted.

The practical consequence is unintuitive: **changing node size can change which quota you draw from**, so a "smaller, cheaper" node may succeed where a larger one failed purely because it lands in a different, emptier bucket. Spreading a fleet across families is a legitimate capacity strategy, not a hack.

- **Compute peak concurrent vCPU before shipping a fan-out, and do it as a sum.** Every chunk of a parallel fan-out is its own cluster, and independent tiers run *at the same time*, so peak = Σ over all chunks of (workers + 1 driver) × cores-per-node. One job at concurrency 3 and 12 needed **1,344 cores of one family against a limit of 350** — a 4× overrun entirely predictable from the YAML, and unpredicted only because nobody did the arithmetic.
- **Spot draws from a *separate* quota, and it can be far larger.** Same region, same subscription: 350 cores for the on-demand family versus **10,000** for `Total Regional Spot vCPUs` — and the spot pool was the *same VM*. When a per-family limit blocks you, moving to spot is not a hardware downgrade; it's a change of accounting bucket, and it may be the only way to keep your intended concurrency while a quota increase is pending.
- **Quota is not capacity.** Headroom in the limit says nothing about whether the provider has spare VMs of that SKU in that region right now — which matters most for spot. "Quota available" and "allocation will succeed" are two separate questions.
- **Insufficient quota does not always fail loudly.** Sometimes you get a clean exception; sometimes the cluster simply sits **pending** and the fan-out waits on it indefinitely. That second mode is how a run silently becomes a two-day run. **Loud failure is the good case.**
- **A pool with no `max_capacity` cannot be a contention point.** If pools are uncapped, two clusters sharing one pool draw the same VMs from the same quota as two clusters on two pools — splitting them to "avoid contention" buys nothing. Scarcity lives at the **quota** layer, not the pool layer. Check `max_capacity` and `min_idle_instances` before designing around imagined pool contention.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### VM *Generation* Can Be a Compliance Gate, Independent of Everything Else
One region enforced a standard requiring VNet encryption, which only v4/v5 SKUs support: `INVALID_PARAMETER_VALUE … must use instances that support Azure Virtual Network encryption`. That is a property of the **VM generation alone** — orthogonal to spot vs on-demand, to size, and to price. So a region can have pools that *exist*, are *quota-available*, and still cannot start a single cluster.

- **Compliance rules shrink usable inventory dramatically, and asymmetrically between regions.** Of 12 pools in the constrained region, 8 were v5 and startable; of those, 4 were on-demand. An "on-demand only" policy plus a v5-only rule left exactly **four** usable pools, and only **two** memory-optimised — both drawing on the same 350-core family. **Enumerate the intersection of all constraints early**; the answer is usually far smaller than the pool list suggests.
- **The same pool *name* can be different hardware in different regions.** One region's `ondemand_memory_optimised_32core_256gb` was E32s_v5, the other's E32s_v3; a 4-core standard pool was D4s_v5 in one and DS3_v2 in the other. Name-based resolution is what lets one config serve two regions — and it is also what hides the fact that the two regions run different silicon.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Spot Eviction Loses Shuffle State, Not Just Compute
An evicted executor's shuffle files disappear with it, so every downstream task waiting on them fails and the stage re-runs — on more spot capacity that may get evicted again. That's a correctness-adjacent infrastructure failure mode, not a tuning problem. Graceful decommissioning (migrate shuffle blocks on eviction) is the mitigation; keeping the **driver** on-demand while workers stay spot is the cheap structural fix, since one driver eviction kills the whole job.

Two adjacent levers worth knowing:
- **Node shape affects shuffle locality.** Fewer, larger nodes at the same total core count keep more shuffle traffic node-local instead of crossing the network — a real lever independent of instance family.
- **Photon doesn't accelerate every operator.** Enabling it on a cluster doesn't guarantee it's engaging on your expensive step. Check the query plan for the Photon badge on the actual exchange/aggregate nodes.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Idle Workers Can Mean a Driver Bottleneck, Not Over-Provisioning
A tier running a thread pool **on the driver** logged ~70 autoscaler resizes in 3h17m, oscillating 1→3→2→1 on a 40–90 second cycle, and looked massively over-sized. It wasn't: 24 Python threads were running on an 8-core / 64 GB driver, each holding a Delta-log file list in driver heap, and the same log recorded four `DRIVER_NOT_RESPONDING … likely due to GC` stalls. **The workers idled because the work never reached them.** Cutting worker count would have been the intuitive fix and the wrong one.

- **For a driver-hosted thread pool, the metric is memory per concurrent thread.** 64 GB ÷ 24 threads = 2.7 GB/thread stalled; 256 GB ÷ 24 = 10.7 GB fixed it with **no change to concurrency**. Deriving that ratio turns "the driver feels small" into a number you can size against — and it tells you which lever to pull, since halving threads and doubling the driver reach the same ratio at very different throughput.
- **The Spark UI Executors tab identifies which failure mode you're in.** Low GC time rules out memory pressure. `Shuffle Write >> Shuffle Read` is the signature of work done, discarded, and redone. Executors that appear and die with zero tasks means the cloud provider isn't granting capacity at all.
- **Diagnose the tier that is slow, not the tier that looks wasteful.** The same job had one tier finishing in 39 minutes and another in 3h17m. Effort spent trimming the fast one is invisible; the slow one is the only thing that moves wall clock. Easy to invert when the *fast* tier is the one with the alarming-looking event log.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Classify Every Task as Compute-Bound or Wall-Clock-Bound Before Choosing Its Compute
Serverless bills for the wall-clock you hold it, so **the worst possible fit is a long-lived task that does no compute.** A live progress dashboard — sleep 60s, list a few small files, one API call, render text — sat on serverless for **22h46m** on a single run, because it exits only once every sibling task is terminal. It performed no Spark work in that entire window and was billed at a rate meant for real query compute. Moving it to the cheapest classic single-node cluster cost ~5 minutes of startup, irrelevant against a 22-hour run.

Serverless is excellent for short bursty work and actively wrong for anything that mostly waits.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### Read the Error's Own Numbers Before Theorising
A quota failure stated *Current Limit 350, Current Usage 320, Additional Required 160, Minimum New Limit 480* — enough to compute both the immediate fix and the real ask (~1,400 for the full fan-out) without a single assumption. **Cloud errors are often far more quantitative than they look.**

And then: **ask for the number you actually need, not the minimum the error suggests.** 480 would have unblocked one cluster and failed on the next. The error tells you what the *current request* needed, not what your *workload* needs.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### When You Can't Run an Experiment, Look for One That Already Ran
Terminated-cluster history is free evidence. A 30-day cluster list showed three successful spot clusters and two successful runs on the exact SKU that later hit quota — proving *"spot works in this region"* and *"this SKU works in this region"* as **separate facts**, without creating anything.

That feeds the general move: **decompose an unknown into the parts already proven.** "Will spot E32s_v5 work here" split into three questions — does the pool exist (yes), is the SKU compliant (yes, v5), does spot allocate in this region (yes, evidenced on another SKU). What remained unproven was only the *combination* — a far smaller risk, and small enough to accept with a retry as cover.

Two corollaries about the instrumentation itself:
- **Identical round numbers across unrelated metrics are a smell.** Three different quota families all reading exactly "0 of 350" was the tell that the region filter was wrong — those were untouched defaults for a region nobody deploys to. **Real usage is lumpy.** (The cause: an autocomplete matched *Austria* East instead of *Australia* East. Any console with a region, subscription or environment selector will eventually hand you correct-looking numbers for the wrong scope.)
- **Verify you can perform the diagnostic action before you need it.** Cluster creation was denied, so an intended five-minute capacity smoke test was impossible — discovered mid-incident. Jobs create their own clusters as the run-as identity, so **a human can lack a permission the pipeline has**, and it only surfaces when you try to debug interactively.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### A Comment That Encodes a *Reason* Is Load-Bearing — and a Wrong One Is Worse Than None
*"SE-only, so the East VNet constraint does not apply"* was plausible, survived review, and **blocked a prod deploy** — because it forecloses the check it appears to have already performed. A reader trusts it and stops looking.

- When correcting one, **record what was wrong and why**, not just the new value.
- **Stale comments cause real regressions.** A note reading *"parallelism is cut to 8 because East cannot offer a driver larger than 32 GB"* was true for about a week; anyone acting on it afterwards would have undone the fix that replaced it. **Update the prose in the same commit as the value.**

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### Runtime Reachability and Deploy-Time Validation Are Different Properties
**The single most expensive confusion in an IaC migration.** A bundle deploys the whole job definition to *every* target, so **every cluster spec is validated in every region — including clusters for tasks that can never run there.** A comment reading *"this task is SE-only, so the East constraint doesn't apply"* was correct about runtime and wrong about deployment, and it blocked a prod deploy.

Ask the two questions separately: *will this task ever **execute** here?* and *will this spec ever be **validated** here?*

**Know exactly which checks happen at each stage:**

| Stage | Checks |
|---|---|
| Deploy time | Does the resource name resolve; does the spec satisfy any attached policy |
| Cluster start time | Quota, compliance rules, actual capacity |

A v3 pool that no region-local task uses will **deploy perfectly** and only fail if something eventually tries to start it — a latent trap rather than a visible one.

- **Referencing anything that exists in only one workspace breaks the other's deploy.** The error names the missing resource, not the reasoning that introduced it.
- **A resource referenced only by a never-running task is a standing fragility.** Nobody in that region has reason to keep it, and if it's cleaned up the deploy starts failing with an error unrelated to whatever change exposed it.
- **Deploying the same bundle twice with different config between runs leaves the repo correct for only one target at a time.** Any redeploy of the other region — a rollback, a hotfix, an automated pipeline run — then fails, and nothing in the repo records which region the committed state is aimed at. **Prefer configuration valid everywhere; where you can't, make the asymmetry loud in the file itself.**

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### A Cluster *Policy* Validates at Deploy, and Its Allowlist Can Be Fundamentally Incompatible With Yours
A single-node policy in one region allowed only **spot** pools. Combined with an organisational "on-demand only" rule, **no compliant configuration existed at all** — the two requirements were mutually exclusive and no amount of pool-swapping would satisfy both. When a policy blocks you, check whether the policy's allowlist and your own policy can *ever* both hold before hunting for the pool that squares them.

- **A policy that *requires* a property does not *impose* it.** A single-node policy rejected a cluster that hadn't declared itself single-node — the spec had the policy attached and none of `num_workers: 0`, the `ResourceClass` tag, or the `cluster.profile` conf. "Single node *via* the policy" was the assumption; "single node **or rejected by** the policy" was the reality.
- **Dropping a policy is a legitimate fix when nothing mandates one.** Twelve of fourteen cluster profiles in the repo carried no policy and deployed fine — in the very apply where the one policed cluster failed. That's direct evidence the workspace didn't require policies. **Matching the configuration that demonstrably works beats inferring what a policy wants from its error text.**

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### CLI and Shell Gotchas (Databricks CLI / PowerShell)
- **PowerShell's `` `v `` is a vertical-tab escape, not a literal "v".** So `` "standard$tag`v$ver`Family" `` silently produced `standardES3Family` instead of `standardESv3Family` — and a quota lookup against a family that doesn't exist returns clean-looking zeros. **Use `${}` around every variable in an interpolated string:** `"standard${tag}v${ver}Family"`.
- **Passing multi-line or quote-containing arguments to native executables from PowerShell is genuinely hostile.** Here-strings (`@'…'@`) need the terminator at column 0 and break inside `;`-chained commands; double quotes embedded in a single-quoted string still break argument boundaries when the call is reconstructed. For anything non-trivial, **write the text to a file and pass the file** (`git commit -F`), or use repeated single-line flags.
- **`Format-Table` truncates at console width and drops right-hand columns with no indication.** Pipe through `Out-String -Width 4096` when the output matters.
- **The Databricks CLI emits a UTF-8 BOM when redirected to a file**, which makes `json.load` fail with "Unexpected UTF-8 BOM". Read with `utf-8-sig`.
- **Prefer one API call that already returns what you need.** `instance-pools list` includes each pool's `stats` block, so per-pool `get` calls to fetch instance counts are wasted round-trips. **Check the list response's shape before fanning out.**

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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

### Job Parameters Silently Override Task Base Parameters of the Same Name
A job-level `max_parallel` beat **every** per-tier `base_parameter` of that name on every task, so per-tier tuning had no effect at all — and looked exactly like a stale deploy. Redeploying could never have fixed it.

What it actually cost, observed live in one run: a chunk logged *"7 at a time"* (the job parameter's value) while its base parameter asked for 4, so seven concurrent billion-row `exceptAll`s ran on a cluster sized for four. Separately, a fan-out exited with *"chunk_index 7 >= total_chunks 5"* while its base parameter asked for 8, and another was handed 2,490 tables where its own setting wanted 3,113.

**Fix: namespace the job-level parameters** (`default_max_parallel`, `scope_chunks`) so a collision is impossible, rather than renaming the notebook widgets — that keeps every notebook runnable standalone with its familiar names. **Check for name collisions between the two layers before concluding a value "isn't taking effect."**
(Source: BUPA — Region Migration project, 2026-08-22)

### In a Fan-Out, the Chunk Divisor and the Scheduled Iteration Count Are Two Numbers — and Both Directions of Mismatch Matter
| Mismatch | Consequence |
|---|---|
| iterations > divisor | Wasteful but safe — surplus iterations exit on the guard |
| divisor > iterations | **Silent data loss** — whole modulo groups get no runner at all |

In the second case nothing fails; 2,490 tables were simply never processed and the only trace was an absent output file. Reconcile row-level coverage **before** overwriting the scope file, not after. This is common because platforms often can't expand a parameter into an array (Databricks Asset Bundles have no `range()` helper), so the divisor lives in a parameter and the iteration count in a fixed YAML literal — two places that must be edited together.

- **A `for_each` repair must resolve to the same iteration count as the original run.** Change the `inputs:` array from 8 entries to 12 and every in-flight or historical run becomes **permanently unrepairable** — the scheduler can't map old iterations onto the new array. Deploys that change pools, parameters or notebook code leave old runs repairable; deploys that change an `inputs:` array do not. Worth knowing before you promise someone a repair.
- **A default nobody runs with is a bug waiting to surface.** A concurrency default of 1 was survivable only because operators overrode it by hand every time; the first run that used the default would have been ~8× slower with no error. **Defaults should be the value you actually want.**
- **The UI task-edit is a real escape hatch when redeploys are expensive.** You can repoint a task's cluster in the Jobs UI and repair the run immediately, without another deploy; the next IaC deploy reverts it. That converts "we get one deploy attempt" into "one deploy attempt plus a manual override," which materially changes how much risk a change can carry.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### A Population Statistic Cannot Be Computed Inside a Fan-Out
A size threshold routing tables into large/small tiers was originally stamped by the per-chunk extractor — but that task was a 5-way `for_each`, so the "population mean" was computed **five times over five disjoint slices**, giving five different thresholds and a tiering that depended on which chunk a table landed in. The fix was to move the decision into the **merge** step, the only place that sees every row.

**Forward rule:** any statistic over the whole population — mean, median, percentile, total, rank — belongs in a **reduce** stage, never in the map stage. If a fanned-out task computes a number that other tasks compare against, **that number is wrong by construction.**
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Naive `index % N` Chunking Creates Stragglers
Splitting a workload into N parallel chunks by row position, when the underlying items vary wildly in size (a 1.08B-row table next to a 10-row one), makes total wall-clock a function of luck. **Size-aware bin-packing** — sort descending, assign each item to the currently-lightest bucket — is the standard fix.

Related, on scaling a fan-out: **scale OUT, not UP.** `+1 chunk` = one more *cluster* = genuinely more cores, with cores-per-in-flight-item held constant. `+1 max_parallel` divides the *same* cores among more items, so cores-per-item **falls**. The failure mode of getting this backwards is severe — see the livelock in §7 — and only one of the two levers actually adds capacity.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Checkpoint Incrementally, and Express the Interval Relative to the Work Unit
**A checkpoint interval larger than the work unit is identical to no checkpointing at all — and raising parallelism can silently create that state.** A full diff checkpointed every 250 comparisons. At ~400 items per chunk that fired once per run; when the chunk count was raised for speed, each chunk dropped to ~241 items and the checkpoint **could never fire**. A run cancelled at 171 of 400 therefore produced **no result file whatsoever** — despite checkpointing being implemented, reviewed, and believed to work.

**Forward rule:** express the interval as a *fraction of the expected work unit*, not an absolute count, and re-derive it whenever chunk counts or parallelism change. Any absolute interval is a hidden coupling to a number someone else is free to tune. **Cheap test: divide the smallest plausible unit by the interval — if the answer is under ~5, the interval is wrong.**

Write partial results with a **full-rewrite-not-append** pattern so the file is always valid mid-run.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Retries Belong on the Unit That Can Independently Fail and Independently Redo Its Work
On a fan-out that's the **inner** task, not the wrapper — a retry on the wrapper re-runs every sibling iteration, not the one that died. And a retry is only safe if that unit is **idempotent**: each chunk must re-derive its own slice and *rewrite* its own output rather than append, so a second attempt recomputes instead of duplicating.

**Retry count is a bet on the failure being transient.** Two attempts survives a one-off spot eviction or allocation miss without spending triple the runtime discovering a chunk is systematically broken. Choose it deliberately — with no checkpointing inside the unit, each retry redoes the whole chunk, and chunks here ran ~3h17m.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Skip-Lists Must Be Conservative in One Direction Only
A "don't re-check this, it already passed" list is safe to **under**-populate (you re-verify more than needed) but never safe to **over**-populate — anything that isn't a confirmed pass must re-run, or a real defect disappears silently as "not in scope."

- **A shared skip-list is scoped to the widest run that writes it.** If a narrow-scope run rebuilds the same file the full-scope run uses, it silently discards every entry the full run earned. Nothing fails; the *next* full run just re-does everything — one narrow run over ~500 items cost a later run the 13,320→497 narrowing it had banked. Either scope the file per mode, or make the narrow run **union** into the list rather than replace it.
- **Incremental and full modes support different claims, so make the mode an explicit parameter and stamp it into the output.** An incremental run can only say *"N items verified as of whenever each was last checked"*; only a full run can say *"the estate is verified as of today."* If the skip list is keyed on name with no version component, an item verified last week that has changed since is **not** re-checked. Without the mode recorded in the summary artifact, nobody reading it later can tell which claim it supports — and "12,823 matched" means very different things in each.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### An Observability Sidecar Must Be Structurally Incapable of Failing or Delaying the Run
Two properties made this true for a live progress dashboard, and both are counter-intuitive:

1. **Nothing depends on it** — so it can never block a successor.
2. **It carries no `timeout_seconds`** — because a Databricks task timeout marks the task *Failed*, and a failed task fails the whole run. A timeout on a monitoring task means a cosmetic component can kill a 22-hour validation. It self-exits on its own internal limit instead, with success.

**Forward rule:** for any observability or reporting sidecar, check *both* edges — can it block anything, and can it fail anything — and prefer an in-notebook self-exit over a platform timeout.

**And a task that watches the run it is part of must exclude itself.** The dashboard's exit condition was "all tasks terminal", which it can never observe — it is itself running whenever it asks. Without passing it its own task key to filter on, the condition is unsatisfiable and every run sits until the backstop limit. *If a watcher always runs to its maximum duration, this is the first thing to check.*
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Gate Off-Leg Tasks on the Control Plane, Not Inside the Notebook
When one job definition serves two variants (two regions, two directions, src/tgt), a notebook-level `if env != "src": exit()` is correct but expensive — the scheduler still **provisions the cluster** to run a notebook that immediately exits. A `condition_task` is evaluated on the control plane and starts **no compute**, so off-leg tasks are genuinely SKIPPED.

Concretely: two tasks on an 8–16 node cluster meant the off-leg spun that whole cluster up twice purely to exit two notebooks. With gates, it's never provisioned on that leg at all.

Keep the in-notebook self-gates anyway as defence in depth — they still matter for standalone and manual runs — but understand that in a *job* run the gates are what actually prevent execution.

**The join pattern this forces, and why the obvious alternatives are wrong.** A gate's downstream join must depend on **both** the previous gate's off-leg branch **and** the task that only runs on the other leg, with `run_if: AT_LEAST_ONE_SUCCESS`:

| `run_if` | Failure |
|---|---|
| `ALL_SUCCESS` (default) | The other-leg task never executes here, so the join is **permanently unreachable** on that leg |
| `ALL_DONE` | A *skip* satisfies it — so the pipeline continues even when the cross-region trigger genuinely **failed** |
| `AT_LEAST_ONE_SUCCESS` | ✅ Reachable on both legs **and** still halts the moment the trigger really fails |

(Source: BUPA — Region Migration project, `test_cases_orchestrator_job.yml`, 2026-08-22)

### Cross-Region Job Triggering Is Just the REST API Plus a Service Principal
A job in region A can fire and then await a job in region B with **no special "cross-workspace" feature to enable.** Region A obtains an OAuth token for a service principal, then calls region B's ordinary Jobs API with it. Once you have the token, the remote workspace is just a hostname.

**The auth flow** is Azure AD machine-to-machine client credentials: POST to `https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token` with `grant_type=client_credentials`, the SP's `client_id` and `client_secret`, and `scope={DATABRICKS_RESOURCE}/.default`. The response's `access_token` goes straight into `Authorization: Bearer …`.

**`DATABRICKS_RESOURCE` is a fixed, well-known Azure constant** — `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`, the AzureDatabricks first-party application ID. Identical for every tenant and every workspace on earth, so it belongs in code as a constant, not in config. Worth committing to memory: it's the piece that *looks* like it must be environment-specific and isn't.

**Full checklist, in the order things fail:** the tenant ID → a service principal that exists in the tenant **and has been granted access in the target workspace** (tenant registration alone is not enough) → the secret stored in a secret scope in the *calling* workspace → the target workspace host → the target `job_id`. Everything else is a normal API call.

Hard-won details:
- **`job_id` is workspace-scoped and is the fragile link.** A number that means nothing in the calling region, and it **changes if the target job is recreated rather than updated** — which in IaC terms means changing the resource key destroys and re-issues it. That single integer is the tightest coupling between the two regions; **treat it as an interface.** (Corollary: rename a job's `name`, never its resource key — the key rename destroys the job, the job_id, and every prior run.)
- **Preflight with `GET /api/2.1/jobs/get` before `run-now`.** One extra call proves the job exists *and* that the SP can see it, so a wrong ID and a missing grant surface as distinct clear errors rather than one opaque `run-now` failure. Two failure modes separated for the cost of one request.
- **`run-now` rejects any `job_parameters` key the target job does not declare.** That silently couples the two jobs' parameter lists: adding a parameter on the calling side and forwarding it breaks *every* run until the callee is redeployed. **Deploy the callee first, always.**
- **Serverless compute cannot make the call.** Serverless egress fails the cross-workspace trust check, so the triggering and waiting tasks must run on classic VNet compute — a constraint that only appears at runtime and forces a cluster into a job that otherwise wanted none.
- **Derive which region you are in at runtime; do not configure it.** One IaC target deploying byte-identically to two workspaces means a deploy-time "my region" value is correct in one and wrong in the other. Detect the executing workspace and fire the *opposite* one, making direction a **derived property**. Configured direction is a bug waiting for the second deployment.
- **Per-workspace names you assume are symmetric often aren't.** Two workspaces' Key Vault-backed secret scopes were named differently — same convention, different suffix, e.g. `secret-kvNNN` vs `secret-kvNN` — despite one bundle serving both. So the code carries **both** candidate scope names and selects once the region is known. Expect at least one such asymmetry per region pair, and note that only the scope *name* ever needs to travel through the bundle; the secret itself is read from the scope at run time.
- **`life_cycle_state` and `result_state` are two different fields and you need both.** `TERMINATED` covers success and failure alike; `result_state` says which. And some terminal states (`SKIPPED`, `INTERNAL_ERROR`) arrive with **no `result_state` at all**, so treating its absence as "still running" produces a poll loop that never exits.
- **Be generous with a wait task's timeout, or make it unbounded.** A wait that times out marks the task failed and fails the whole run — so the timeout is not a safety net, it's an additional way to lose a good run. 48 hours against a 22-hour job is the right shape of margin.
- **A cross-region trigger should fail loud, unlike a best-effort one.** If everything downstream is meaningless without the remote run, swallowing the error just moves the failure somewhere less diagnosable.

(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Fire-and-Exit, Then Wait Separately — and Wait on the *Task* You Need, Not the Whole Run
`run-now` returns as soon as the remote run is queued. Publish the returned `run_id` as a task value and consume it downstream. Splitting trigger from wait is what lets local work proceed in parallel with the remote run instead of blocking behind it.

**Then the higher-leverage move: `GET /api/2.1/jobs/runs/get` returns a `tasks[]` array with per-task state, so you can release local work the moment the one upstream task you actually depend on finishes.** That turns a full-run barrier into a precise synchronisation point.

**Watch the right task, though.** Watching a `for_each` *wrapper* releases you too early — the wrapper reaches SUCCESS as soon as the last chunk finishes, at which instant only per-chunk files exist. The merged file the downstream step reads doesn't exist until the **merge** task assembles it. Watch the merge.

Concrete payoff in this framework: moving the longest-running branch (22h24m of a 22h46m run) off the full-run barrier and onto the earlier, genuinely-sufficient guarantee let it run **concurrently** with the extractor chain it consumed nothing from, rather than serialised behind it. **Audit what each step actually reads — a dependency edge justified by "it needs both sides' data" may be a much later guarantee than the step truly requires.**
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md` + `test_cases_orchestrator_job.yml`, 2026-08-22)

### Make the Dangerous Direction Opt-In via the Default
The `env` parameter defaults to the **safe, self-contained leg** — the one that only extracts its own side and stops. The leg that fires a run in the opposite region and then compares must be requested explicitly. An operator doing that supplies several other parameters anyway, so naming one more costs nothing; the payoff is that a stray "Run now" on either workspace **cannot** fire a cross-workspace run.

Generalizes to any parameterized job with one destructive or outward-facing mode: make the default the mode you'd want an accidental click to take.
(Source: BUPA — Region Migration project, `test_cases_orchestrator_job.yml`, 2026-08-22)

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

### Row Filters and Column Masks Block Validation in Two Independent Ways
On a UC-governed session, a masked or row-filtered table refuses a **path-based** read (`PERMISSION_DENIED: Path-based access … row filter or column mask not supported`) *and separately* refuses **time travel by name** (`COLUMN_MASKS_FEATURE_NOT_SUPPORTED.TIME_TRAVEL`). Fixing one does nothing for the other, so it reads like two unrelated defects.

**The common cause is the session, not the syntax — that's the whole insight.** Both refusals come from **UC's own session-level analyzer**, which fires while resolving the read through UC's catalog metadata. So the fix is not a different query shape; it's a session that never consults UC at all.

**Therefore switching to a `delta.\`<path>\`` read is necessary but NOT sufficient.** A path read from a UC-governed cluster is exactly what the first error blocks — UC maps the path back to the table it governs and refuses.

**It is ONE decision with two consequences, not three ingredients:**

- **The decision** — `data_security_mode: NONE`. Note this *is* what "non-UC cluster" means; it is not something you switch on top of a UC-enabled cluster. `SINGLE_USER` and `USER_ISOLATION` are the UC-enabled values, and on either of them the analyzer is in the session and both blocks fire. **There is no configuration that keeps UC enabled and skips its masking checks** — that would be a governance hole, not a feature.
- **Consequence 1** — UC no longer brokers storage access, so the cluster must carry its own credential (direct SP OAuth on the storage account: `fs.azure.account.auth.type`, `…oauth.provider.type`, `…oauth2.client.id`, `…client.secret`, `…client.endpoint`, per account host). The secret is read from a scope at run time and lives in Spark conf on that cluster, and the set of accounts must be known up front.
- **Consequence 2** — there is no catalog to resolve a name against, so the read *must* be expressed by path. **Path syntax is the result of going non-UC, not the thing that defeats the mask.**

**When someone proposes a middle ground:** setting `fs.azure.account.*` credentials on a UC-enabled cluster and reading by path does not work, and in shared/`USER_ISOLATION` mode those confs are generally refused outright. **The governance mode is binary for this purpose.**

**The payoff is correctness, not just access.** Because the non-UC session can time-travel a masked table, *every* table gets compared at its real pinned version — no live-version fallback for the masked subset. That removes an entire class of "we compared now against then" error precisely where the temptation to fall back would have been strongest.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

### Going Non-UC Forces an Architectural Split, Because You Lose Everything UC Knows
Tags, PK/FK constraints, `information_schema`, registration — **none of it is reachable from a non-UC session.** So a validation suite cannot simply move to non-UC wholesale; it has to **split its checks across two clusters by which store answers them.** That split is the real design consequence of the workaround, and it turns out to be a benefit: log-only checks are latency-bound (thousands of small reads, wanting concurrency) while data-file checks are shuffle-bound (wanting cores per table). Those want opposite cluster shapes, and separating them lets each get one.

**The reusable shape: a UC "prep" task that resolves everything, then a non-UC executor that consumes plain values.** Prep runs on UC compute, resolves external-location names and config lookups, and publishes plain strings as task values; the non-UC task receives them pre-resolved and never needs a catalog. **Anything the executor would have had to *look up* becomes something it is *handed*.**

Costs to price in:
- **Serverless is off the table.** Serverless is UC-only, so going non-UC forces classic compute — cluster startup on every run, nodes held for the task's duration.
- **The reads become invisible to governance tooling.** Path reads from a non-UC cluster don't appear in UC audit or lineage. Worth stating out loud when the job doing them is itself compliance-adjacent.
- **Speed is not the reason to do this.** The dominant costs are unchanged — shuffle for a full comparison, per-table latency for metadata. Choose it for **capability**. (Two genuine secondary savings exist: mask and row-filter evaluation is real per-query CPU that raw file reads skip entirely, and there's no UC credential vending or permission resolution per query — small individually, non-trivial across thousands of tiny metadata reads.)
- **Direct `_delta_log` access is the underrated upside.** On a non-UC session the log is just files: list the directory, read the checkpoint Parquet and commit JSONs. That's what makes log-replay checks possible *at all*.
- **Cross-region reads need the path approach regardless of masking.** The other region's tables aren't registered in this workspace's metastore, so there's no name to read them by. Masking and cross-region are two independent reasons that happen to want the same mechanism.

### You Are Reading Unmasked Data — That Must Be a Deliberate, Authorised Decision
The mask exists for a reason and this bypasses it. What made it defensible in this case: it runs as a service principal with storage-level RBAC, and the checks emit **structure and counts, never row values**. A check that sampled and reported rows would be exfiltrating exactly what the mask protects.

**So when adding checks to a non-UC path, audit what they *output*, not just what they read.** Get the authorisation on the record before the first run, not after someone asks.
(Source: BUPA — Region Migration project, `SESSION_LEARNINGS.md`, 2026-08-22)

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
| Session — BUPA Region Migration | Second, distinct BUPA engagement (DeepClone cross-region DR validation, not the original DLT pipeline build). Distilled 5 new lessons into §4 (validation pattern) and §6 (`DESCRIBE HISTORY` clone lineage, retention-window feasibility, UC-path vs delta-path routing, masking/row-filter bypass) from the live validation framework build. |
| 2026-08-22 — Region Migration, full distillation | Read the framework source (156 py / 30 yml) and the 917-line `SESSION_LEARNINGS.md` written across two working days (Aug 12: Delta internals + Spark execution + testing methodology; Aug 20: cloud capacity, IaC, orchestration, and three prod failures in one day — a cluster-policy rejection, an Azure vCPU quota exhaustion, and a VM-generation compliance rule). Added ~35 lessons across §1, §4, §5, §6, §7, §8, §9, §10, §11. **Also CORRECTED the retention lesson in §6**, which had encoded a superseded 168h threshold as the general rule; it is now the three-stores / three-clocks model. |

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
- **`SESSION_LEARNINGS.md`** (917 lines) — raw learnings from the BUPA Region Migration / DeepClone DR framework, written by hand across 2026-08-12 and 2026-08-20. Held **outside this repo** in the gitignored `client_work/bupa_region_migration/` quarantine, alongside the framework source it describes, because that material is client IP. Only generalized lessons cross into this file; client source, storage accounts, workspace IDs and table names never do. Cited above as `SESSION_LEARNINGS.md`.

## Lessons NOT Extracted Here (Deliberately Excluded)

The following are LHP-framework-specific and don't generalize to non-LHP projects:
- LHP error code reference (`LHP-CFG-*`, `LHP-VAL-*`, `LHP-IO-*`, `LHP-ACT-*`, `LHP-DEP-*`)
- LHP template parameter substitution order (`%{var}` vs `{token}` vs `{{jinja}}`)
- LHP CLI commands (`lhp validate`, `lhp generate`, `lhp deps`)
- LHP presets / inheritance / template structure
- LHP `write_source_view` hook pattern (useful inside LHP, but the principle — "make templates extensible via optional parameters" — generalizes; see Section 1 "Framework Limitations Are Architectural Constraints").
- LHP packaging bugs (e.g., missing `.j2` files in a wheel)

If you move to a different framework (dbt, Dagster, Airflow + raw DLT, etc.), these don't carry over. The patterns and principles above do.
