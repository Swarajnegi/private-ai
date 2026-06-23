# Day 4 — Cost & Performance Optimisation (Section 6, 13%)

> **Exam objective S6 (13% — your second-heaviest domain, and your prior 61% "Data Processing" gap):** UC managed tables reduce ops overhead · Delta optimization (deletion vectors, liquid clustering) · query optimization (data skipping, file pruning) · CDF to address streaming-table limitations/latency · use the Query Profile to find bottlenecks (poor data skipping, wrong join type, shuffle/spill). Overlaps **S10 Data Modelling (6%)** on liquid clustering vs partitioning/ZORDER. Combined, this material is worth ~15–18% of the paper.

This deep-dive is **gap-only**. You already own SDP, AUTO CDC, SCD2, expectations, and Auto Loader from Apollo Gen2 (422 pipelines). Nothing here re-teaches those. The new surface area is: *what Databricks now does automatically* (predictive optimization, automatic liquid clustering, automatic CDF, deletion-vector merge-on-read) and *how to read the Query Profile like a tool, not a poster*.

Every fact below is grounded in current Databricks docs (Azure Databricks docs on `learn.microsoft.com`, current as of June 2026). URLs are cited inline.

**Terms defined once, used throughout:**
- **UC** = Unity Catalog: Databricks' governance layer that owns the metadata for tables, controls reads/writes, and (critically) *sees every query pattern* across the platform.
- **PO** = Predictive Optimization: the AI-driven service that runs maintenance (`OPTIMIZE`/`VACUUM`/`ANALYZE`) automatically on UC managed tables.
- **DV** = Deletion Vector: a tiny side-file marking individual rows as deleted so the big Parquet file need not be rewritten ("merge-on-read").
- **DBR** = Databricks Runtime (the Spark distribution version, e.g. DBR 15.4 LTS). **LTS** = Long-Term Support.
- **AQE** = Adaptive Query Execution: re-planning a Spark query *mid-flight* using real runtime statistics.
- **CDF** = Change Data Feed: a row-level change log (`insert`/`update`/`delete`) readable from a Delta table.

---

## 6.1 UC managed tables reduce operational overhead + Predictive Optimization

### What / Why

A UC table is either **managed** (Databricks owns the storage location, file layout, and lifecycle) or **external** (you supply the object-storage path and you own all maintenance). The exam's framing — "managed tables reduce ops overhead" — is literal: with a managed table you stop writing `OPTIMIZE`/`VACUUM` jobs, because Databricks runs them for you via Predictive Optimization.
([tables/managed](https://learn.microsoft.com/azure/databricks/tables/managed), [optimizations/predictive-optimization](https://learn.microsoft.com/azure/databricks/optimizations/predictive-optimization))

**The three operations PO runs automatically** on UC managed tables:

| Operation | What it does | Why it matters |
|---|---|---|
| `OPTIMIZE` | Compacts small files into right-sized files; triggers **incremental** liquid clustering on enabled tables | Fixes the small-file problem from streaming/frequent writes |
| `VACUUM` | Deletes data files no longer referenced by the table | Cuts storage cost |
| `ANALYZE` | Incrementally updates column statistics | Feeds the cost-based optimizer + data skipping |

([predictive-optimization#what-operations](https://learn.microsoft.com/azure/databricks/optimizations/predictive-optimization#what-operations-does-predictive-optimization-run))

### Silent / invisible behavior to call out (these are exam landmines)

1. **`OPTIMIZE` run by PO does *not* run `ZORDER`.** On Z-ordered tables, PO **ignores the Z-ordered files entirely**. This is the doc's explicit warning — it's a direct push toward liquid clustering. (Same doc page.)
2. **PO billing is invisible until you look.** PO maintenance runs on **serverless compute** billed under a serverless jobs SKU. You don't provision a cluster, so the cost shows up only in the system table `system.storage.predictive_optimization_operations_history`. ([predictive-optimization#track](https://learn.microsoft.com/azure/databricks/optimizations/predictive-optimization#track-predictive-optimization-with-system-tables))
3. **`VACUUM` silently shortens your time-travel window.** PO's `VACUUM` honors `delta.deletedFileRetentionDuration` (default **7 days**). If you want longer time travel, you must set this *before* PO touches the table:
   ```sql
   ALTER TABLE my_table SET TBLPROPERTIES ('delta.deletedFileRetentionDuration' = '30 days');
   ```
4. **PO is now default-on for new accounts** (created on/after 2024-11-11); existing accounts are being rolled in gradually (rollout expected complete **August 2026**). So in your own workspace it may already be running. Verify, don't assume.
5. **PO never runs on external tables or OpenSharing recipient tables** — those are the two excluded types.

### Enable / inspect

```sql
-- Table-level control. Default for new tables is INHERIT (from schema).
ALTER TABLE my_table ENABLE PREDICTIVE OPTIMIZATION;
ALTER TABLE my_table {ENABLE | DISABLE | INHERIT} PREDICTIVE OPTIMIZATION;
```
([sql-ref-syntax-ddl-alter-table](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-alter-table#parameters))

### Worked example — the ops-overhead delta

Apollo Gen2 has 422 SDP pipelines. The *old* pattern: each silver/gold Delta table needs a scheduled `OPTIMIZE` job + a `VACUUM` job + occasional `ANALYZE`. That's hundreds of maintenance jobs you author, schedule, monitor, and pay cluster-uptime for.

With UC managed tables + PO: you author **zero** maintenance jobs. Databricks watches the actual query patterns, decides table-by-table whether maintenance is worth it, and runs it on serverless. The doc's exact phrasing — "eliminates unnecessary maintenance runs and the burden of tracking and troubleshooting performance manually." If you *also* run a scheduled `OPTIMIZE` while PO is on, Databricks recommends **disabling your scheduled `OPTIMIZE`** to avoid double work. ([tables/clustering#how-to-trigger](https://learn.microsoft.com/azure/databricks/tables/clustering#how-to-trigger-clustering))

> **Recap:** Managed table = Databricks owns layout + lifecycle; PO auto-runs `OPTIMIZE`/`VACUUM`/`ANALYZE` on serverless — but never `ZORDER`, never on external tables, and `VACUUM`'s 7-day default silently caps time travel.

---

## 6.2 Deletion vectors (merge-on-read)

### What / Why

Default Delta behavior is **copy-on-write**: deleting *one row* forces a rewrite of the *entire Parquet file* that contains it (write amplification). A deletion vector flips this to **merge-on-read**: `DELETE`/`UPDATE`/`MERGE` mark affected rows as soft-deleted in a tiny companion file; the big Parquet file stays put; readers apply the DV at query time to skip the marked rows.
([tables/features/deletion-vectors](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors))

This is the engine behind **Predictive I/O for updates** — on Photon-enabled compute, Databricks uses DVs to accelerate `DELETE`/`UPDATE`/`MERGE` by avoiding full-file rewrites. ([optimizations/predictive-io](https://learn.microsoft.com/azure/databricks/optimizations/predictive-io#use-predictive-i-o-to-accelerate-updates))

### Enable

```sql
-- New table
CREATE TABLE my_table (...) TBLPROPERTIES ('delta.enableDeletionVectors' = true);
-- Existing table
ALTER TABLE my_table SET TBLPROPERTIES ('delta.enableDeletionVectors' = true);
```
A workspace admin setting (`Auto-enable deletion vectors`) can turn DVs on by default for new tables; the default varies by region. ([admin/workspace-settings/deletion-vectors](https://learn.microsoft.com/azure/databricks/admin/workspace-settings/deletion-vectors))

### Silent / invisible behavior to call out

1. **Enabling DVs silently upgrades the table protocol.** After upgrade, **older Delta clients that don't support DVs can no longer read the table** (requires reader v3 / writer v7-class support). The doc gives a literal warning. To go back, in DBR 14.1+ you `DROP FEATURE deletionVectors`. ([deletion-vectors — Client compatibility](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors))
2. **Soft-deleted rows still physically exist** until a rewrite event happens. They are physically removed when: `OPTIMIZE` runs, auto-compaction rewrites the file, or `REORG TABLE ... APPLY (PURGE)` runs. Until then, the data is on disk — relevant for **GDPR/compliance purges**.
3. **For a hard compliance delete you need TWO steps, not one.** `REORG TABLE ... APPLY (PURGE)` rewrites the files (removing soft-deletes), then **`VACUUM` with the retention set to the purge timestamp** removes the old files from disk. One without the other leaves recoverable data. ([deletion-vectors — Physically delete old data](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors))
4. **Photon vs non-Photon write support differs by operation** (exam-favorite nuance):

   | Compute | Write DVs on |
   |---|---|
   | DBR **with Photon** | `MERGE`, `UPDATE`, `DELETE` (DBR 12.2 LTS+) |
   | DBR **without Photon** | `DELETE` (12.2 LTS+), `UPDATE` (14.1+), `MERGE` (14.3 LTS+) |

   Reading DV tables: any DBR **12.2 LTS+**. Recommended write runtime: **14.3 LTS+** for all optimizations.

### Maintenance interaction — REORG vs OPTIMIZE vs VACUUM

| Command | Job | Note |
|---|---|---|
| `OPTIMIZE` | Compacts files; on DV tables, files where DVs reference enough rows are rewritten as part of compaction | The everyday cleanup path |
| `REORG TABLE ... APPLY (PURGE)` | **Force**-rewrites files containing soft-deletes, materializing the deletes | Use for compliance / explicit control |
| `VACUUM` | Physically removes the now-unreferenced old files past retention | The disk-reclaim step |

### Worked example — write amplification

A `customers` table has 1 GB Parquet files (~5M rows each). A GDPR request deletes 50 rows in one file.
- **Copy-on-write (DVs off):** Databricks reads the 1 GB file, drops 50 rows, writes a fresh ~1 GB file. ~1 GB written for 50 rows.
- **Merge-on-read (DVs on):** Databricks writes a ~KB deletion vector marking 50 row positions. The 1 GB file is untouched. ~KB written. Reads skip those 50 rows.

That's the whole point: deletes/updates touching a small fraction of a big file go from gigabytes of write to kilobytes.

> **Recap:** DVs = merge-on-read; soft-delete a row instead of rewriting the file. Enabling upgrades the protocol (older readers locked out). Soft-deletes linger until `OPTIMIZE`/`REORG PURGE`; compliance deletes need `REORG ... APPLY (PURGE)` *then* `VACUUM`.

---

## 6.3 Liquid clustering (CLUSTER BY / CLUSTER BY AUTO) vs partitioning vs ZORDER — S6 + S10

### What / Why

**Liquid clustering** is Databricks' replacement for both Hive-style partitioning and `ZORDER`. It organizes data into right-sized files with tight value ranges on your clustering keys, **without directories** and **without a full rewrite** when you change keys. Databricks recommends it for **all new tables**, including streaming tables and materialized views.
([tables/clustering](https://learn.microsoft.com/azure/databricks/tables/clustering))

```sql
-- Explicit keys (up to 4):
CREATE TABLE events (event_date DATE, region STRING, ...) CLUSTER BY (event_date, region);

-- Let predictive optimization pick + adapt the keys (UC managed tables only):
CREATE OR REPLACE TABLE events (...) CLUSTER BY AUTO;

-- Change keys later — NO full table rewrite of existing data:
ALTER TABLE events CLUSTER BY (region, customer_id);
OPTIMIZE events;          -- only NEW/changed data is reclustered (incremental)

-- Switch an existing table to automatic key selection:
ALTER TABLE events CLUSTER BY AUTO;
-- Turn clustering off:
ALTER TABLE events CLUSTER BY NONE;
```
([sql-ref-syntax-ddl-cluster-by](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-cluster-by), [tables/clustering#auto-liquid](https://learn.microsoft.com/azure/databricks/tables/clustering#automatic-liquid-clustering))

### The three-way comparison (memorize this table — it's the S10 question)

| Aspect | Partitioning | ZORDER | Liquid clustering |
|---|---|---|---|
| Physical form | One **directory** per distinct value | Layout applied inside `OPTIMIZE`, **not stored** in metadata | File-level value ranges, **no directories**; keys stored in table metadata |
| High-cardinality keys | Creates thousands of tiny files/dirs (over-partitioning) | OK, but can't cross partition boundaries | Handles naturally; bins into right-sized files |
| Change the key | **Full table rewrite** | Must re-run `OPTIMIZE ZORDER BY (...)` with new cols each time | `ALTER TABLE ... CLUSTER BY` — applies on next `OPTIMIZE`, **no rewrite of old data** |
| Incremental | n/a | **No** incremental mode | **Yes** — `OPTIMIZE` only touches new/changed/unhealthy files |
| Multi-column curve | n/a | Z-order curve | Z-order for 1 col, **Hilbert curve** for 2+ (better locality) |
| Concurrent writes | conflicts unless partitioned on the predicate | — | Allows **row-level concurrency** → fewer conflicts |

([apply liquid clustering — benefits over partitioning/ZORDER](https://learn.microsoft.com/azure/databricks/tables/clustering), [tables/partitions](https://learn.microsoft.com/azure/databricks/tables/partitions))

### Hard rules to memorize

- **Up to 4 clustering keys.** For small tables (<10 TB), *more* keys can *hurt* single-column filtering. ([clustering#choose-clustering-keys](https://learn.microsoft.com/azure/databricks/tables/clustering#choose-clustering-keys))
- **Clustering keys must be columns that have statistics collected** (by default the first 32 columns). No stats → no skipping → clustering is pointless on that column.
- **Liquid clustering and partitioning/ZORDER are mutually incompatible.** You cannot combine `CLUSTER BY` with `PARTITIONED BY`. You cannot ZORDER a clustered table.
- **`CLUSTER BY AUTO` is UC-managed-only** and needs Predictive Optimization (DBR **15.4 LTS+** for the key-selection metadata). It analyzes historical query workload, picks keys, and **changes them only when the predicted skipping savings beat the reclustering cost** (cost-aware). ([clustering#auto-liquid](https://learn.microsoft.com/azure/databricks/tables/clustering#automatic-liquid-clustering))
- **Don't partition tables below 1 TB**, and only partition a column if each partition will hold ≥ 1 GB. Otherwise use liquid clustering. ([performance-efficiency best practices](https://learn.microsoft.com/azure/databricks/lakehouse-architecture/performance-efficiency/best-practices))

### Silent / invisible behavior to call out

1. **`ALTER TABLE ... CLUSTER BY (newcols)` does nothing to existing data until you run `OPTIMIZE`.** Old rows stay clustered by the *old* keys; only new/changed data picks up the new layout. To force a full re-cluster: `OPTIMIZE FULL`. ([clustering — Force reclustering](https://learn.microsoft.com/azure/databricks/tables/clustering))
2. **Converting a partitioned table** (DBR 18.1+) is a single statement that minimizes downtime:
   ```sql
   ALTER TABLE t REPLACE PARTITIONED BY WITH CLUSTER BY (day, id);
   OPTIMIZE t;
   -- or REPLACE PARTITIONED BY WITH CLUSTER BY AUTO;  (UC managed only)
   -- or REPLACE PARTITIONED BY WITH CLUSTER BY;       (reuse old partition cols as keys)
   ```
   Verify with `DESCRIBE EXTENDED` (new clustering columns) and `DESCRIBE HISTORY` (you'll see `REORG`, `UPGRADE PROTOCOL`, and `REPLACE PARTITIONED BY WITH CLUSTER BY` ops). ([clustering#enable](https://learn.microsoft.com/azure/databricks/tables/clustering#enable-liquid-clustering))

### Worked example — why partitioning bites and clustering doesn't

A `transactions` table partitioned by `txn_timestamp` (high cardinality, second-level). Result: one directory per *second*, each with a few KB of data — millions of micro-files. Query planning crawls; reads are dominated by file-open overhead. You can't fix it without rewriting the whole table to a coarser partition.

Switch to `CLUSTER BY (txn_timestamp, account_id)`: no directories, data binned into ~optimal-size files with tight `txn_timestamp` ranges, and if your queries shift to filtering on `merchant_id` next quarter, you just `ALTER TABLE ... CLUSTER BY (merchant_id)` + `OPTIMIZE` — no full rewrite.

> **Recap:** Liquid clustering replaces partitioning + ZORDER. ≤4 keys, on stat-collected columns, can't mix with `PARTITIONED BY`. Changing keys needs `OPTIMIZE` to take effect (incremental). `CLUSTER BY AUTO` (UC managed + PO, DBR 15.4 LTS+) lets Databricks pick and adapt keys cost-aware.

---

## 6.4 Data skipping + file pruning (stats, min/max)

### What / Why — the mechanism, traced

Every time a data file is written, Delta records per-file column statistics in the transaction log: **min**, **max**, and **null count** for each indexed column. At query time, the engine compares your `WHERE` predicate to each file's min/max range and **skips files whose range can't contain a match** — without opening them.
([tables/data-skipping](https://learn.microsoft.com/azure/databricks/tables/data-skipping), [file skipping](https://learn.microsoft.com/azure/databricks/tables/data-skipping))

**Execution trace** — `sales` table, 5 files, query `WHERE date = '2024-03-15'`:

| File | min/max `date` | Decision |
|---|---|---|
| 1 | 2024-01-01 .. 2024-02-28 | **skip** (15-Mar > max) |
| 2 | 2024-03-01 .. 2024-03-31 | **read** (15-Mar in range) |
| 3 | 2024-04-01 .. 2024-05-31 | **skip** |
| 4 | 2024-06-01 .. 2024-07-31 | **skip** |
| 5 | 2024-08-01 .. 2024-09-30 | **skip** |

4 of 5 files skipped → 80% less data scanned. Data layout (liquid clustering / ZORDER) **tightens** these ranges so more files skip; that's why layout and skipping are two halves of one optimization.

### Hard rules + silent behavior

1. **Stats are collected on the first 32 columns only** (`delta.dataSkippingNumIndexedCols`, default 32). Columns past position 32 get **no** file stats and **cannot** participate in skipping — a silent cliff. ([data-skipping](https://learn.microsoft.com/azure/databricks/tables/data-skipping))
2. **Long string columns are expensive to stat.** Move them past column 32 so they don't waste the budget:
   ```sql
   ALTER TABLE t ALTER COLUMN long_text_col AFTER last_indexed_col;
   ```
3. Raise the budget or pin exact columns:
   ```sql
   ALTER TABLE t SET TBLPROPERTIES ('delta.dataSkippingNumIndexedCols' = '40');
   ALTER TABLE t SET TBLPROPERTIES ('delta.dataSkippingStatsColumns' = 'order_date,region');
   ```
   (`dataSkippingStatsColumns` overrides the ordinal rule — only the named columns get stats.)
4. **Type-mismatch silently disables skipping.** If the predicate literal's type doesn't match the column type, the engine **can't use min/max** for that file — it falls back to scanning. The Query Profile reports this as `Unused` statistics (see 6.6). Filtering a `STRING` column with an integer literal is the classic trap.
5. **Not all types are eligible.** `BinaryType`, `BooleanType`, and whole `StructType` columns get no file stats (struct *leaf* fields are evaluated individually).
6. **Dynamic file pruning (DFP)** extends skipping to **join time**: the engine prunes files of the large (probe) table using values discovered from the small (build) table at runtime. Enabled by default in DBR 10.4 LTS+. ([optimizations/dynamic-file-pruning](https://learn.microsoft.com/azure/databricks/optimizations/dynamic-file-pruning))

> **Recap:** Delta stores min/max/null per file for the first 32 columns; queries skip non-matching files unopened. Past column 32 = no stats = no skipping. Type mismatch silently kills skipping. Layout (clustering) tightens ranges so more files skip.

---

## 6.5 CDF to address streaming-table latency/limitations

### The problem CDF solves

Structured Streaming reading a Delta table **only accepts appends**. If an upstream `UPDATE`, `DELETE`, `MERGE INTO`, or `OVERWRITE` modifies the source, the stream **throws an exception and fails**. ([structured-streaming/delta-lake](https://learn.microsoft.com/azure/databricks/structured-streaming/delta-lake#handle-changes-to-source-delta-lake-tables))

The doc lays out four ways to handle a changing source, with the tradeoffs:

| Approach | Pro | Con |
|---|---|---|
| `skipChangeCommits` | Simple; ignores modifications, processes only appends | **Doesn't propagate** updates/deletes |
| Full refresh | Simple | Expensive; reprocesses all downstream tables |
| **Change Data Feed** | Processes **all** change types (insert/update/delete) | You write per-change-type logic |
| Materialized view | Auto change propagation, no streaming code | **Higher latency** |

The exam's exact phrasing — "CDF to address streaming-table limitations/latency": when a streaming table can't keep up or chokes on non-append changes, **CDF lets you stream row-level changes (not full snapshots)**, which is both lower-latency than a full MV recompute and more complete than `skipChangeCommits`. Databricks: *"stream from the CDF of a Delta table rather than directly from the table whenever possible."*

### NEW in DBR 18: Automatic CDF vs Legacy CDF (this is current exam material)

Databricks now has **two** CDF mechanisms ([tables/features/change-data-feed](https://learn.microsoft.com/azure/databricks/tables/features/change-data-feed)):

| | **Automatic CDF** (Public Preview, DBR 18+) | **Legacy CDF** |
|---|---|---|
| When changes computed | At **read** time, using row tracking / row lineage | At **write** time, materialized to `_change_data` files |
| Per-table config | **None** — works automatically | Must set `delta.enableChangeDataFeed = true` |
| Write cost | **Lower** (no per-write change files for `MERGE`/`UPDATE`) | Higher (extra files written) |
| Storage cost | **Lower** | Higher |
| Formats | Delta (row tracking) + Iceberg v3 | Delta only |
| Requirement | DBR 18+, UC table, Delta w/ row tracking or Iceberg v3 | Any supported DBR |

Same read APIs for both: `readChangeFeed` and `table_changes()`.

```sql
-- Legacy: enable on a table
ALTER TABLE my_table SET TBLPROPERTIES (delta.enableChangeDataFeed = true);
```
```python
# Read CDF as a stream (incremental change processing)
(spark.readStream
  .option("readChangeFeed", "true")
  .table("sales.orders"))
```
```sql
-- Batch read a version range
SELECT * FROM table_changes('sales.orders', 120, 125);
SELECT * FROM table_changes('sales.orders', 0);  -- from v0 to latest
```

### CDF output columns (memorize)

| Column | Values |
|---|---|
| `_change_type` | `insert`, `update_preimage`, `update_postimage`, `delete` |
| `_commit_version` | the Delta version where the change committed |
| `_commit_timestamp` | commit timestamp of that version |

`preimage` = row *before* the update; `postimage` = row *after*.

### Silent / invisible behavior to call out

1. **First stream read replays the full snapshot as `insert`s, then goes incremental.** You don't seed the target separately — the first micro-batch *is* the baseline.
2. **CDF is not a permanent audit log.** Records are **transient**, kept only for the retention window; `VACUUM` removes old `_change_data` files. To keep permanent history, write the feed out to your own table (e.g. with `trigger(availableNow=True)`).
3. **Specifying a `startingVersion` that's already been vacuumed = the stream fails to start.** Managed tables auto-clean history, so *every* fixed starting version eventually disappears.
4. **You can't run legacy + automatic CDF together.** Migrating to automatic = `ALTER TABLE ... UNSET TBLPROPERTIES ('delta.enableChangeDataFeed')`.
5. **CDF can't span a non-additive schema change** (column rename/drop/type change) on a column-mapped table — split the read range around it.
6. **Legacy CDF is silent on insert-only / full-partition deletes** — those don't produce change-data files; Databricks computes the feed straight from the transaction log.

> **Recap:** Streaming a Delta source fails on non-append changes. CDF streams row-level changes (`insert`/`update`/`delete`) — lower latency than MV recompute, more complete than `skipChangeCommits`. New automatic CDF (DBR 18+) computes changes at read time, no per-table config, lower write/storage cost. CDF is transient (VACUUM eats it) — archive it if you need permanent history.

---

## 6.6 Using the Query Profile to find bottlenecks

### What / Why

The **Query Profile** (Query History → click a query → **See query profile**) visualizes the query's execution as a DAG (Directed Acyclic Graph — a flowchart of operators with no cycles), with per-operator metrics: time spent, rows, memory peak. Use it to find the slowest operator at a glance and spot the classic mistakes: exploding joins, full table scans, heavy shuffle/spill.
([sql/user/queries/query-profile](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))

Three left-panel tabs: **Details** (summary metrics), **Top operators** (most expensive ops — start here), **Query text**. For deep SQL-warehouse debugging, the kebab menu → **Open in Spark UI**. Hidden low-impact operators appear via **Enable verbose mode**.

### The operators that signal trouble

| Operator | What it means | Red flag |
|---|---|---|
| **Scan** | Reading a data source | Bytes read ≈ whole table → **data skipping failed** |
| **Join** | Combining relations | Output rows ≫ input → **exploding join** |
| **Shuffle** | Redistributing data across executors | Expensive — moves data between machines |
| **Hash / Sort** | Grouping by key for aggregation | Heavy memory user; watch for spill |
| **Filter** | Applying `WHERE` | If late in the plan, push it earlier |

### Performance Insights — the named diagnoses (these map 1:1 to exam wording)

The Query Profile's **Performance insights** tab surfaces named insights ranked by projected effect on task duration. The exam's three bottleneck categories map directly:
([sql/user/queries/performance-insights](https://learn.microsoft.com/azure/databricks/sql/user/queries/performance-insights))

**Poor data skipping →**
- `COVERAGE_STATS_DELTA` — Delta skipping stats are **missing/incomplete** for the scan's filters. Statuses: **Full / Partial / Unavailable / Unused** (`Unused` = the filter converted the data type, i.e. the type-mismatch trap from 6.4). Fix: collect stats / fix the predicate type.
- `COVERAGE_FILTER_KEYS_CLUSTERING` / `..._PARTITIONING` — the table is clustered/partitioned on keys your query **doesn't filter on**. Fix: filter on the layout keys, or re-cluster on the keys you actually filter.
- `AUTO_LIQUID_CLUSTERING` — table is manually optimized; would benefit from `CLUSTER BY AUTO`.

**Wrong join type / join shape →**
- `EXPLODING_JOIN` — join produces **far more rows than it reads** (usually a bad/missing join condition). Fix the condition or pre-filter inputs.
- `SELECTIVE_JOIN` — join produces **far fewer rows than it reads** → push filters *before* the join.

**Heavy shuffle / spill / skew →**
- `DATA_SPILL` — data didn't fit in memory and spilled to disk. Fix: bigger warehouse, or fewer/narrower rows.
- `DATA_SKEW` — uneven distribution across executors. Fix: **key salting** or pre-aggregation.
- `EXCESSIVE_QUEUE_TIME` (warehouse queued — add clusters) and `IO_THROTTLING` (cloud storage throttled).

### Spill & skew in the Spark UI (classic compute)

For classic compute (not SQL warehouses), use the **Spark UI**. On a long-running stage:
- **Spill** = Spark ran low on memory and moved data to disk (most common during shuffle). Check the stage's spill stats; no stats shown = no spill. ([spark-ui-guide — Spill](https://learn.microsoft.com/azure/databricks/optimizations/spark-ui-guide/long-spark-stage-page))
- **Skew** = a few tasks take far longer than the rest. In **Summary Metrics**, if **Max** task duration is **> 50% above the 75th percentile**, you have skew. (Healthy = Max ≈ 75th pct.)

### Silent behavior to call out

- **A query that hit the result cache has NO profile** — it shows "Query profile is not available." To force a fresh profile, make a trivial change (e.g. tweak/remove `LIMIT`) to bypass the cache. ([query-profile](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))

### Worked example — reading a slow query

A dashboard query times at 90s. Open the profile → **Top operators**: the `Join` operator owns 70s. The DAG shows the `Join` outputs 4 billion rows from 50M input rows → `EXPLODING_JOIN` insight fires. Cause: a join key was nullable and the ON clause matched nulls. Fix the condition; runtime drops to 6s. Without the profile you'd have blamed cluster size and scaled up — paying more for the same bug.

> **Recap:** Query Profile = per-operator DAG + named Performance Insights. Poor skipping → `COVERAGE_STATS_DELTA` (watch `Unused` = type mismatch). Bad join → `EXPLODING_JOIN`. Memory → `DATA_SPILL`/`DATA_SKEW`. Cached queries have no profile — change the SQL to bypass.

---

## 6.7 Spark performance refresher — AQE knobs, join selection, skew

**AQE re-optimizes a query mid-flight** using *real* statistics gathered at the end of each shuffle/broadcast stage (a "query stage") — the most accurate stats Databricks ever has. **On by default.** It applies to non-streaming queries with at least one exchange (join/aggregate/window) or sub-query.
([optimizations/aqe](https://learn.microsoft.com/azure/databricks/optimizations/aqe))

### AQE's four powers

1. **Sort-merge join → broadcast hash join** at runtime, once it learns a side is small.
2. **Coalesce shuffle partitions** — merge tiny post-shuffle partitions into right-sized ones (tiny tasks waste scheduling overhead).
3. **Skew join handling** — split (and replicate) skewed partitions into evenly sized tasks.
4. **Empty-relation propagation** — prune whole sub-plans that turn out empty.

### Knobs to recognize (with default values — exam loves the defaults)

| Property | Default | Effect |
|---|---|---|
| `spark.databricks.optimizer.adaptive.enabled` | `true` | Master AQE switch |
| `spark.databricks.adaptive.autoBroadcastJoinThreshold` | `30MB` | Runtime threshold to switch to broadcast join |
| `spark.sql.shuffle.partitions` | `200` (set to `auto` for auto-optimized shuffle) | Post-shuffle partition count |
| `spark.sql.adaptive.advisoryPartitionSizeInBytes` | `64MB` | Target size after coalescing |
| `spark.sql.adaptive.skewJoin.skewedPartitionFactor` | `5` | × median size to flag a skewed partition |
| `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` | `256MB` | Absolute size floor for "skewed" |

**Skew detection rule (both must be true):** `partition_size > 256MB` **AND** `partition_size > 5 × median_partition_size`.

### Join selection — the FAQ answers (commonly tested)

- **Should you still use a `broadcast()` hint with AQE on?** **Yes.** A *statically* planned broadcast is usually faster than AQE's dynamic one, because AQE may not switch to broadcast until *after* it has already shuffled both sides. If you know a table is small, hint it.
- **Skew hint vs AQE skew handling?** Prefer **AQE** — it's automatic and generally beats the manual hint.
- **AQE does NOT reorder joins.** Dynamic join reordering is not part of AQE. (And `LEFT OUTER JOIN` can't broadcast its left side.)
- **Cost-Based Optimizer (CBO)** is the *static* (compile-time) counterpart — it picks join type/order/build-side from `ANALYZE TABLE` statistics. AQE corrects it at runtime. Both want fresh stats; PO's `ANALYZE` feeds both. ([optimizations/cbo](https://learn.microsoft.com/azure/databricks/optimizations/cbo))

### Why no Python/Scala UDFs for hot paths

UDFs require **serialization** to move data between the JVM and Python — it kills query speed and blocks Catalyst/Photon optimization. Use native Spark SQL / PySpark functions; if you truly need Python, use a **Pandas UDF** (Apache Arrow moves data efficiently). ([performance-efficiency best practices](https://learn.microsoft.com/azure/databricks/lakehouse-architecture/performance-efficiency/best-practices)) Note Photon also can't accelerate UDF-heavy paths (`COVERAGE_PHOTON` insight).

> **Recap:** AQE (on by default) re-plans mid-query: SMJ→broadcast, coalesce partitions, handle skew, prune empties. Defaults: broadcast 30MB, shuffle 200, advisory 64MB, skew 5×/256MB. AQE doesn't reorder joins — keep your broadcast hints. CBO is the static stats-driven counterpart.

---

## Common exam traps (box)

> 1. **PO never runs `ZORDER`** and **never touches external tables** — only `OPTIMIZE`/`VACUUM`/`ANALYZE` on UC **managed** tables.
> 2. **`VACUUM` default retention is 7 days** — set `delta.deletedFileRetentionDuration` *before* enabling PO if you want longer time travel.
> 3. **Enabling deletion vectors upgrades the table protocol** — older Delta clients can no longer read it.
> 4. **Soft-deleted rows aren't gone.** Compliance delete = `REORG TABLE ... APPLY (PURGE)` **then** `VACUUM`.
> 5. **Liquid clustering ≠ partitioning ≠ ZORDER, and they don't mix.** No `CLUSTER BY` + `PARTITIONED BY`. ≤ 4 keys, on stat-collected columns.
> 6. **`ALTER TABLE ... CLUSTER BY (new)` doesn't re-layout old data until `OPTIMIZE`** (incremental); `OPTIMIZE FULL` forces it.
> 7. **`CLUSTER BY AUTO` is UC-managed-only + needs PO** (DBR 15.4 LTS+).
> 8. **Stats on first 32 columns only** — columns past 32 can't be skipped on. **Type mismatch silently disables skipping** (`Unused` in the profile).
> 9. **Streaming a Delta source fails on `UPDATE`/`DELETE`/`MERGE`/`OVERWRITE`** — that's the limitation CDF addresses.
> 10. **CDF is transient** (VACUUM removes it). A `startingVersion` that's been vacuumed makes the stream fail to start.
> 11. **Automatic CDF (DBR 18+)** computes changes at read time, needs no per-table property; **legacy CDF** needs `delta.enableChangeDataFeed=true` and writes change files.
> 12. **Cached queries have no Query Profile** — change the SQL to bypass the cache.
> 13. **AQE is on by default but does NOT reorder joins** — and keep your `broadcast()` hints (static beats dynamic).
> 14. **Skew rule:** partition `> 256MB` AND `> 5× median`.
> 15. **No Python UDF on hot paths** (serialization cost); use native functions or Pandas UDF (Arrow).

---

## Hands-on lab (your own Databricks workspace)

Use a UC-managed schema. ~45 min. Each step ends with what to *observe*.

**A. Predictive Optimization + managed table**
```sql
CREATE TABLE main.dev.lab_orders (order_id BIGINT, customer_id BIGINT, order_date DATE, status STRING, amount DECIMAL(10,2))
  CLUSTER BY AUTO;
ALTER TABLE main.dev.lab_orders ENABLE PREDICTIVE OPTIMIZATION;
DESCRIBE EXTENDED main.dev.lab_orders;   -- observe: clustering columns + PO setting
```
Then check what PO has done in your account:
```sql
SELECT operation_type, total_runtime, usage_unit, operation_metrics
FROM system.storage.predictive_optimization_operations_history
ORDER BY start_time DESC LIMIT 20;       -- observe: serverless maintenance + cost
```

**B. Deletion vectors — merge-on-read**
```sql
ALTER TABLE main.dev.lab_orders SET TBLPROPERTIES ('delta.enableDeletionVectors' = true);
-- insert a few thousand rows (use a generator or a SELECT from an existing table), then:
DELETE FROM main.dev.lab_orders WHERE status = 'cancelled';
DESCRIBE HISTORY main.dev.lab_orders;    -- observe: DELETE op writes a DV, not a full rewrite
-- compliance purge:
REORG TABLE main.dev.lab_orders APPLY (PURGE);
DESCRIBE HISTORY main.dev.lab_orders;    -- observe: REORG materializes the deletes
```

**C. Data skipping — prove min/max pruning**
```sql
-- Run a selective filter, then open the Query Profile:
SELECT count(*) FROM main.dev.lab_orders WHERE order_date = DATE'2024-03-15';
```
In Query History → the query → **See query profile** → click the **Scan** operator. Observe **files pruned / files read** and the **Performance insights** tab (look for `COVERAGE_STATS_DELTA`). Now run the **type-mismatch** version and compare:
```sql
SELECT count(*) FROM main.dev.lab_orders WHERE order_date = '2024-03-15';  -- string vs DATE
```
Observe the stats status flip toward `Unused`.

**D. Liquid clustering — change keys without a rewrite**
```sql
ALTER TABLE main.dev.lab_orders CLUSTER BY (customer_id, order_date);
OPTIMIZE main.dev.lab_orders;            -- observe: incremental; only new/changed files rewritten
DESCRIBE HISTORY main.dev.lab_orders;    -- observe: OPTIMIZE op with clustering, no full rewrite
```

**E. Change Data Feed**
```sql
ALTER TABLE main.dev.lab_orders SET TBLPROPERTIES (delta.enableChangeDataFeed = true);
UPDATE main.dev.lab_orders SET status = 'shipped' WHERE status = 'pending';
SELECT _change_type, _commit_version, * FROM table_changes('main.dev.lab_orders',
   (SELECT max(version)-2 FROM (DESCRIBE HISTORY main.dev.lab_orders)));
-- observe: update_preimage + update_postimage rows
```

**F. Query Profile bottleneck hunt**
Run a deliberately bad join (cross-ish join or a nullable key), open the profile, and find the `EXPLODING_JOIN` insight. Then run a query big enough to spill on a small warehouse and find `DATA_SPILL`. Fix each and re-profile to confirm the insight clears.

---

## One-page recap table

| Topic | Key fact | Default / threshold | Trap |
|---|---|---|---|
| UC managed tables | Databricks owns layout + lifecycle | — | External tables = you maintain |
| Predictive Optimization | Auto `OPTIMIZE`/`VACUUM`/`ANALYZE` on serverless | Default-on for accts ≥ 2024-11-11; rollout to Aug 2026 | **Never runs ZORDER; never external** |
| `VACUUM` retention | Removes unreferenced files | `delta.deletedFileRetentionDuration` = **7 days** | Silently caps time travel |
| Deletion vectors | Merge-on-read soft-delete | DBR 12.2 LTS+ read; 14.3 LTS+ write all ops | Upgrades protocol; soft-deletes linger |
| Compliance delete | Materialize + reclaim disk | — | `REORG ... APPLY (PURGE)` **then** `VACUUM` |
| Liquid clustering | Replaces partitioning + ZORDER | **≤ 4** keys; stat-collected cols only | Can't mix w/ `PARTITIONED BY` |
| `CLUSTER BY AUTO` | PO picks + adapts keys (cost-aware) | UC managed; DBR **15.4 LTS+** | Not for external tables |
| Change keys | `ALTER ... CLUSTER BY` | Applies on next `OPTIMIZE` (incremental) | No effect on old data until OPTIMIZE |
| Data skipping | Per-file min/max/null | First **32** columns | Past 32 = no skip; type mismatch = `Unused` |
| Dynamic file pruning | Skipping at join time | DBR 10.4 LTS+ default | — |
| Partition rule | Avoid over-partitioning | Don't partition < **1 TB**; ≥ **1 GB**/partition | High-cardinality = micro-files |
| Streaming Delta source | Appends only | — | `UPDATE`/`DELETE`/`MERGE`/`OVERWRITE` fail the stream |
| CDF | Row-level change log | `_change_type`/`_commit_version`/`_commit_timestamp` | Transient — VACUUM removes it |
| Automatic CDF | Read-time changes, no config | DBR **18+**, row tracking / Iceberg v3 | Can't run w/ legacy CDF together |
| Query Profile | Per-operator DAG + insights | — | Cached query → no profile |
| Insight: poor skipping | `COVERAGE_STATS_DELTA` | Full/Partial/Unavailable/**Unused** | `Unused` = type conversion |
| Insight: bad join | `EXPLODING_JOIN` / `SELECTIVE_JOIN` | — | Push filters before join |
| Insight: memory | `DATA_SPILL` / `DATA_SKEW` | — | Salt skewed keys |
| AQE | Mid-query re-plan, on by default | broadcast **30MB**, shuffle **200**, advisory **64MB** | **Doesn't reorder joins**; keep broadcast hints |
| Skew detection | Both conditions | **> 256MB** AND **> 5× median** | — |
| UDFs | Serialization cost | — | Use native / Pandas UDF (Arrow) |
