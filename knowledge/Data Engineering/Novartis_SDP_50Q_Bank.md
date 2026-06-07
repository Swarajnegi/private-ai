# Novartis Client Round — Spark Declarative Pipelines (SDP / Lakeflow) 50-Question Bank

> Prep 2026-06-04 for the Novartis client round (interviewer: Nitesh); 2nd internal round may fall on Monday. **Naming:** the interviewer's questions say 'DLT'; answered here entirely in current **SDP (Spark Declarative Pipelines / Lakeflow)** terms — the Python module is now `from pyspark import pipelines as dp`. A legacy name is mapped only where a question literally uses it (Q7 'Live Tables', Q18 'deprecated auto-CDC'). All factual claims doc-verified via a multi-agent generate + adversarial-verify pass (2026-06-04).

---

## Contents

- [Caveats — where to hedge (don't over-claim)](#caveats--where-to-hedge-dont-over-claim)
- [Category 1.1 — Pipeline Structure, Capabilities & Design Thinking (Q1–Q4)](#category-11--pipeline-structure-capabilities--design-thinking-q1q4)
- [Category 1.2–1.3 — Object Model, Pipeline Modes & Full Refresh (Q5–Q9)](#category-1213--object-model-pipeline-modes--full-refresh-q5q9)
- [Category 2 — Materialized Views Deep Dive (Q10–Q13)](#category-2--materialized-views-deep-dive-q10q13)
- [Category 3 — Data Ingestion & Source Integration (Q14–Q16)](#category-3--data-ingestion--source-integration-q14q16)
- [Category 4 — Change Data Capture (CDC) & Apply Changes (Q17–Q21)](#category-4--change-data-capture-cdc--apply-changes-q17q21)
- [Category 5.1 — Basic Streaming Operations (Q22–Q24)](#category-51--basic-streaming-operations-q22q24)
- [Category 5.2 — Advanced Streaming Joins & Watermarks (Q25–Q27)](#category-52--advanced-streaming-joins--watermarks-q25q27)
- [Category 6 — SQL Implementation & Aggregations (Q28–Q31)](#category-6--sql-implementation--aggregations-q28q31)
- [Category 7 — Data Quality & Constraints (Q32–Q35)](#category-7--data-quality--constraints-q32q35)
- [Category 8 — Performance Optimization & Tuning (Q36–Q39)](#category-8--performance-optimization--tuning-q36q39)
- [Category 9 — Unity Catalog & Security (Q40–Q42)](#category-9--unity-catalog--security-q40q42)
- [Category 10–11 — Schema Evolution, Monitoring & Troubleshooting (Q43–Q45)](#category-1011--schema-evolution-monitoring--troubleshooting-q43q45)
- [Category 12–13 — Strategic Decisions & Practical Experience (Q46–Q50)](#category-1213--strategic-decisions--practical-experience-q46q50)
- [Advanced Topics — Deep Dive](#advanced-topics--deep-dive)
  - [Stream–Stream Joins](#streamstream-joins)
  - [Stream–Snapshot (Stream–Static) Joins](#streamsnapshot-streamstatic-joins)
  - [Late-Arriving Data](#late-arriving-data)
  - [Triggered vs Continuous Execution Mode](#triggered-vs-continuous-execution-mode)
  - [Streaming Optimization](#streaming-optimization)
  - [Streaming Table — Full Refresh vs Incremental Refresh](#streaming-table--full-refresh-vs-incremental-refresh)
  - [Auto Loader (cloudFiles) — Important Options & Configs](#auto-loader-cloudfiles--important-options--configs)
  - [SDP-Specific Optimization Configs](#sdp-specific-optimization-configs)
  - [Stateful Processing](#stateful-processing)
  - [Materialized View — Optimization](#materialized-view--optimization)
  - [Materialized View — Full vs Incremental Refresh](#materialized-view--full-vs-incremental-refresh)
  - [Backfill](#backfill)
  - [Append Flow & AUTO CDC Flow (SCD1 and SCD2)](#append-flow--auto-cdc-flow-scd1-and-scd2)
  - [Limitations of ST, MV, SDP, Flows & Expectations (consolidated)](#limitations-of-st-mv-sdp-flows--expectations-consolidated)
  - [Use Cases of All (decision guide)](#use-cases-of-all-decision-guide)
  - [Expectations — Everything (types, actions, where logged)](#expectations--everything-types-actions-where-logged)
  - [Event Log — Where, What & How to Read](#event-log--where-what--how-to-read)
  - [Deployment Mode — Development vs Production](#deployment-mode--development-vs-production)
  - [Product Editions — CORE, PRO, ADVANCED](#product-editions--core-pro-advanced)
- [Clarifications & Deep-Dive (round 2)](#clarifications--deep-dive-round-2)
  - [C1 — Incremental MV refresh: supported vs unsupported queries (serverless vs classic)](#c1--incremental-mv-refresh-supported-vs-unsupported-queries-serverless-vs-classic)
  - [C2 — Which flows can write to the same ST/MV](#c2--which-flows-can-write-to-the-same-stmv)
  - [C3 — Auto Loader schema evolution (`addNewColumns`) in depth](#c3--auto-loader-schema-evolution-addnewcolumns-in-depth)
  - [C4 — All `schemaEvolutionMode` modes](#c4--all-schemaevolutionmode-modes)
  - [C5 — `pipelines.reset.allowed = false`](#c5--pipelinesresetallowed--false)
  - [C6 — Watermarks + why an ST join doesn't recompute on dimension change](#c6--watermarks--why-an-st-join-doesnt-recompute-on-dimension-change)
  - [C7 — `deletionVectors` / `rowTracking` / `changeDataFeed`](#c7--deletionvectors--rowtracking--changedatafeed)
  - [C8 — Why MVs are "always correct" without watermarks](#c8--why-mvs-are-always-correct-without-watermarks)
  - [C9 — CDC tombstone retention (`pipelines.cdc.tombstoneGCThresholdInSeconds`)](#c9--cdc-tombstone-retention-pipelinescdctombstonegcthresholdinseconds)
  - [C10 — Schema hints vs full schema (keeping `addNewColumns`)](#c10--schema-hints-vs-full-schema-keeping-addnewcolumns)
  - [C11 — Stream–stream join internals (symmetric hash, 4 state stores, watermark)](#c11--streamstream-join-internals-symmetric-hash-4-state-stores-watermark)
  - [C12 — Selective checkpoint reset](#c12--selective-checkpoint-reset)
  - [C13 — MV + expectations: incremental-refresh exceptions](#c13--mv--expectations-incremental-refresh-exceptions)
  - [C14 — One pipeline across multiple `.py` / `.sql` files](#c14--one-pipeline-across-multiple-py--sql-files)
  - [C15 — REPLACE WHERE flows](#c15--replace-where-flows)
  - [C16 — The windowed streaming aggregate, explained](#c16--the-windowed-streaming-aggregate-explained)
  - [C17 — Reading expectation metrics from the event log (code)](#c17--reading-expectation-metrics-from-the-event-log-code)
  - [C18 — Quarantine pattern (preserve bad rows instead of dropping)](#c18--quarantine-pattern-preserve-bad-rows-instead-of-dropping)
  - [C19 — Event log: query every aspect of a pipeline (event_type catalog + recipes)](#c19--event-log-query-every-aspect-of-a-pipeline-event_type-catalog--recipes)
  - [C20 — Runtime channels: `current` vs `preview`](#c20--runtime-channels-current-vs-preview)


## Caveats — where to hedge (don't over-claim)

> Spots where current docs are ambiguous, version-pinned, or environment-dependent. **State the hedge — don't assert.** (From the adversarial doc-verification pass.)

- **Dev vs Prod modes (Q8) — highest risk.** Current SDP docs tie cluster-reuse + retries to the *update trigger source* (UI Run-now = fast-start/no-retry; Jobs/API/continuous = auto-retry), with `development` as a flag. Be ready to state **both** the legacy "development mode = cluster reuse + no retries" framing and the current one. Retry defaults: `numUpdateRetryAttempts`=5 triggered / unlimited continuous; `maxFlowRetryAttempts`=2.
- **MV + expectations conflict.** Pipeline-defined MVs support expectations (incrementally refreshable, with caveats); the standalone Databricks-SQL `CREATE MATERIALIZED VIEW` page lists them *unsupported*. Answer per your surface (pipeline vs DBSQL).
- **`__apply_changes_storage_` backing table + tombstone view (Q20) = Hive metastore only, NOT Unity Catalog.** Apollo/Novartis pipelines are UC → don't lean on that as the "gold not reflecting deletes" explanation.
- **Incremental MV requires serverless.** Solid, but it's a synthesis of two doc statements (refresh always runs on serverless internally; classic-compute *pipelines* fully recompute), not one verbatim sentence.
- **Per-function aggregate incrementality.** Don't claim COUNT/SUM/MIN/MAX individually incrementalize — it's cost-model-decided at plan time (`GROUP_AGGREGATE` / `GENERIC_AGGREGATE` techniques, visible in the `planning_information` event log).
- **Deletion vectors default (Q37) = rollout/workspace-dependent.** "Check the admin UI / table property" is the safe answer, not a fixed default.
- **Preview/Beta — don't call GA:** `create_sink` + update flows (Public Preview), REPLACE WHERE flows (Beta, Preview channel), standalone DBSQL `FLOW AUTO CDC` (Public Preview). The pipeline `AUTO CDC INTO` / `create_auto_cdc_flow` form **is** GA.
- **Oracle `_change_ts` (Q14) is a project column, not a Databricks field.** Confirm the real source column (Dynamics exposes `SinkModifiedOn`). The query-based connector runs serverless-by-default (classic = Beta/API-only).
- **Tombstone GC.** "2 days" is grounded; don't quote `172800s` as a verbatim doc figure. Set via the `pipelines.cdc.tombstoneGCThresholdInSeconds` table property on the target ST.
- **`expect_or_fail` sibling-flow behavior.** The per-flow failure model is right, but "fails only that flow, siblings still commit" wasn't pinned to a doc sentence — frame as per-flow and offer to confirm if probed.
- **AUTO CDC API signature.** `stored_as_scd_type`, `sequence_by`, `keys`, `apply_as_deletes` match current convention; do a final glance at the AUTO CDC reference page for the exact `stored_as_scd_type=1` (int) vs `"2"` (str) form before the round.
- **Runtime-pinned numbers.** AQE `autoBroadcastJoinThreshold`=30MB, ABAC DBR 16.4+ floors, `addNewColumnsWithTypeWidening` (Preview) — all DBR-version-dependent; current channel = DBR 17.3. Anchor to the fleet's runtime if cited.

## Category 1.1 — Pipeline Structure, Capabilities & Design Thinking (Q1–Q4)

### Q1 — Complete structure & full capability surface of an SDP pipeline
**Question:** Explain the complete structure of a DLT pipeline and describe all the features and capabilities that can be implemented within a single DLT pipeline.

*("DLT pipeline" = SDP / Lakeflow Declarative Pipeline; I answer in current SDP terms.)*

**What an SDP pipeline IS**
- **Pipeline** = the unit of development + execution. You declare *datasets* and *flows*; SDP parses ALL source files first, builds a **dataflow (dependency) graph**, then orchestrates execution order + parallelism automatically. You never write the orchestration.
- An **update** = one run: starts compute, validates the graph (bad column names, missing deps, syntax) BEFORE running anything, then creates/refreshes datasets.

**The 3 dataset types (the nouns)**

| Object | SDP API | Read semantics | Use for |
|---|---|---|---|
| Streaming table (ST) | `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` | `spark.readStream` — incremental, append-only source, each row processed once | Bronze ingest, row-level silver, CDC targets |
| Materialized view (MV) | `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` | `spark.read` — batch; refreshed incrementally **only on serverless** (else full recompute) | Joins, aggregations, gold marts |
| Temporary view | `@dp.temporary_view` / `CREATE TEMPORARY VIEW` | in-pipeline only, not published | intermediate reuse |

*ST vs MV in one line: only difference in the basic body is `spark.readStream` (ST) vs `spark.read` (MV). (`@dp.table` is the ST decorator; `@dp.materialized_view` is the MV decorator — the legacy `@dlt.table` made both, so I always name the MV explicitly.)*

**The flow types (the verbs that write into a target)**
- **Append flow** (`@dp.append_flow`) — default flow of an ST; adds new rows per trigger. Multiple append flows can fan-in to ONE streaming table (union of sources).
- **AUTO CDC flow** (`dp.create_auto_cdc_flow` / `CREATE FLOW ... AS AUTO CDC INTO`) — upsert/delete with out-of-order handling; SCD Type 1 or 2.
- **AUTO CDC FROM SNAPSHOT** (`dp.create_auto_cdc_from_snapshot_flow`) — diffs full snapshots into CDC.
- **Update flow** (`@dp.update_flow`) and **Sinks** (`dp.create_sink` → Delta / Kafka / Event Hubs / custom Python sink) for streaming egress.

**Everything you can put in ONE pipeline**
- **Quality:** expectations — `@dp.expect` / `expect_or_drop` / `expect_or_fail` / `expect_all` / `expect_all_or_drop` / `expect_all_or_fail` (SQL: `CONSTRAINT name EXPECT (expr) [ON VIOLATION DROP ROW | FAIL UPDATE]`).
- **CDC / SCD2** via AUTO CDC, `__START_AT`/`__END_AT` history columns auto-maintained (same data type as `sequence_by`).
- **Schema controls:** column masks, PK/FK informational constraints, `CLUSTER BY` (liquid clustering — Databricks recommends it for all new STs/MVs, replacing `PARTITIONED BY` + `ZORDER`; `CLUSTER BY AUTO` lets the engine pick keys).
- **Mixed languages** (Python + SQL files in the same pipeline), multiple bronze→silver→gold layers, fan-in append flows, sinks, and a built-in **event log** (Delta table) for lineage, expectation metrics, and `flow_progress` events.

```python
from pyspark import pipelines as dp

@dp.table
@dp.expect_or_drop("valid_id", "id IS NOT NULL")
def bronze_orders():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", "/chk/orders")
            .load("/Volumes/cat/sch/incoming/orders"))

@dp.materialized_view
def gold_orders_by_state():
    return (spark.read.table("bronze_orders")
            .groupBy("state").count())
```
```sql
CREATE OR REFRESH STREAMING TABLE bronze_orders(
  CONSTRAINT valid_id EXPECT (id IS NOT NULL) ON VIOLATION DROP ROW
) AS SELECT * FROM STREAM read_files('/Volumes/cat/sch/incoming/orders', format => 'csv');

CREATE OR REFRESH MATERIALIZED VIEW gold_orders_by_state
AS SELECT state, count(*) AS n FROM bronze_orders GROUP BY state;
```

**One-liner:** An SDP pipeline is a declared dependency graph of streaming tables, materialized views, and views — wired together by append / AUTO CDC / update flows and sinks, with expectations, SCD2, and an event log all managed by the engine, not hand-orchestrated.

### Q2 — Key concepts you must master to work with SDP
**Question:** What are the key concepts that must be well understood when working with DLT?

**Declarative, not imperative**
- You declare WHAT each dataset is; SDP decides execution ORDER and parallelism from the graph. **Order of code ≠ order of execution.**
- Source is evaluated MULTIPLE times during planning — so **no side effects** in dataset functions. The docs explicitly ban these inside dataset code: `collect()`, `count()`, `toPandas()`, `save()`, `saveAsTable()`, `start()`, `toTable()` — i.e. anything that writes or forces execution. (This is exactly why my Apollo Gen2 preprocessing lives in a separate notebook job — arbitrary Python / `dbutils.fs` doesn't belong in a dataset function.)

**ST vs MV (the most-tested distinction)**

| | Streaming table | Materialized view |
|---|---|---|
| Read | `spark.readStream` | `spark.read` |
| Source must be | append-only | any (batch) |
| Recompute | incremental, processes each new row once | incremental refresh **only on serverless**; classic compute (or an unsupported query) → full recompute |
| Mutable source | **breaks** (needs append-only) | fine |

**Flows** — a flow reads a source, transforms, writes a target. Append / AUTO CDC / Update. Multiple flows can target one ST (fan-in); a dataset can otherwise be the target of only one operation across all pipelines.

**AUTO CDC mechanics** (`create_auto_cdc_flow`):
- `keys` (business key), `sequence_by` (logical ordering, sortable type, handles out-of-order; a `struct(...)` breaks ties), `apply_as_deletes`, `stored_as_scd_type` (**default = 1**), `track_history_except_column_list` / `track_history_column_list`.
- **Gotcha I hit:** if you don't EXCEPT every operational-metadata column (`_processing_timestamp`, `_source_file_path`) from history tracking, each re-run flips those values and forges a false SCD2 version.
- Deletes are kept as **tombstones** for **2 days** by default (`pipelines.cdc.tombstoneGCThresholdInSeconds`, table property on the target ST) to absorb late/out-of-order deletes.

**Expectations** — warn (default, row kept), drop, fail; a `fail` only fails THAT flow, not sibling flows.

**Schema evolution (Auto Loader)** — `cloudFiles.schemaEvolutionMode` default `addNewColumns` (when no schema supplied; `none` if you supply one — `addNewColumns` isn't allowed with a provided schema unless given as a schema hint). On a new column the stream throws `UnknownFieldException` and stops; restart resumes with the evolved schema. It only ADDS columns — never removes/renames/retypes. A **dropped source column lands silently as NULL** (soft delete). Type mismatch → `_rescued_data` (which Auto Loader auto-adds as `_rescued_data` whenever it infers the schema). (`addNewColumnsWithTypeWidening`, Public Preview in DBR 16.4+, also widens e.g. `int`→`long`.)

**The event log** — Delta table; query via the `event_log('<pipeline-id>')` TVF (callable only by the ST/MV owner, on a shared cluster or SQL warehouse) for lineage, `flow_progress`, and expectation pass/fail counts (in the `details` JSON).

**One-liner:** Master five things — declarative graph (no side effects), ST-vs-MV read semantics (and that MV incremental refresh needs serverless), the flow types, AUTO CDC's keys/sequence_by/SCD-type/track-history defaults, and the event log — and SDP becomes predictable.

### Q3 — How to structure your thinking when designing an SDP pipeline
**Question:** How should the thought process be structured and clarified when designing a DLT pipeline?

This is an approach question, so here is the decision sequence I actually run.

**Approach (the design interrogation, in order)**
1. **Source contract:** Is the source append-only or mutable? Append-only → streaming table. Mutable → batch MV, or first stabilize via a CDC feed. (I learned this the hard way: streaming-on-mutable-source breaks the ST.)
2. **Is it already CDC / already SCD?** If the source is *already* SCD2, do NOT run AUTO CDC on top of it — you double-version. Collapse to current-only or map columns directly. Only run AUTO CDC on a raw change feed.
3. **Grain & key:** What uniquely identifies a row (`keys`)? What column gives a real, logical event order (`sequence_by`, sortable type — use a `struct(...)` if one column isn't enough to break ties)? `file_modification_time` is too coarse — if many rows share one file, ties resolve arbitrarily. Need true per-row granularity.
4. **History need:** Current-state only → SCD1 (the default). Full audit trail → SCD2, and decide which columns are *meaningful* history vs noise → `track_history_except_column_list` for every operational-metadata column.
5. **Where does schema get enforced?** Enforce ONCE, at one layer (bronze). Don't re-validate the same contract three times.
6. **Quality policy per constraint:** integrity (PK, SCD2, CDC) → `expect_or_fail` (hard gate); observability (freshness, schema drift) → `expect` (warn). In Apollo Gen2 SIT I warn-in-dev then fail-in-prod across 17 cases.
7. **What does NOT belong in SDP?** Arbitrary Python, `dbutils.fs`, file ops, anything that calls `save`/`start`/`collect`/`count` → split into a preprocessing **notebook job** chained via `depends_on`. Different compute + independent failure domains is a feature, not a workaround.
8. **Layer mapping:** bronze = ST (raw, minimal transform, replayable); silver = ST for row-level cleaning / MV for enrichment joins; gold = MV aggregations.

**Design principles I hold**
- Silent failures beat loud failures — but a *removed* column landing NULL is a silent failure, so add a freshness/schema-drift WARN to surface it.
- Generated code is an artifact, not source of truth — I batch-generate 422 SDP pipelines (211 STG + 211 BRZ SCD2) from one script; edit config + regenerate, never hand-edit output.
- Design around framework limits, don't fight them.

**One-liner:** Start from the source contract (append-only vs mutable, raw-CDC vs already-SCD), pin down key + true sequence column, decide SCD1 vs SCD2 with explicit history-column exclusions, enforce schema once, set per-constraint fail/warn policy, and push anything non-declarative into a chained notebook job.

### Q4 — Architecture for Bronze/Silver/Gold when S3 gets a new file daily
**Question:** How would you design the architecture for Bronze, Silver, and Gold layers if S3 receives a new file daily?

**Approach (end-to-end design)**
- **Ingest = Auto Loader, not a directory read.** A daily file is incremental file arrival — `cloudFiles` tracks processed files via `schemaLocation`, so I never reprocess yesterday's file and never need manual high-watermark bookkeeping. (In SDP, Auto Loader auto-manages the schema + checkpoint dirs.)
- **Trigger:** daily file → triggered (scheduled) pipeline update, not continuous. Cheaper, matches the cadence.
- **Bronze (streaming table):** raw landing, minimal transform, every row carries operational metadata (`_source_file_path`, `_processing_timestamp`). Replayable — silver/gold can rebuild from bronze if logic changes. Schema enforced HERE, once.
- **Silver (streaming table for row-level clean, or AUTO CDC if the daily file is a change feed):** dedupe, cast, validate. If the daily file is a full/changed snapshot of a dimension, use AUTO CDC → SCD1/SCD2 here.
- **Gold (materialized view):** aggregations/metrics for dashboards; incremental refresh recomputes only what changed — **but only on a serverless pipeline**; on classic compute (or an unsupported query) each refresh is a full recompute.

**Schema-evolution call:** Auto Loader `schemaEvolutionMode = addNewColumns` (default, no schema supplied) — new vendor column → stream throws `UnknownFieldException` and stops, schema evolves, restart picks it up (run under a Lakeflow Job so it auto-restarts). It will NOT catch a *removed* source column — that lands as NULL silently — so I add a WARN expectation on freshness/null-rate to surface it.

```python
from pyspark import pipelines as dp

@dp.table  # BRONZE
def bronze_sales():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", "/Volumes/cat/sch/_schema/sales")
            .load("s3://bucket/incoming/sales/")
            .selectExpr("*", "_metadata.file_path AS _source_file_path",
                        "current_timestamp() AS _processing_timestamp"))

dp.create_streaming_table("silver_customers")  # SILVER as SCD2 if daily file is CDC
dp.create_auto_cdc_flow(
    target="silver_customers", source="bronze_sales",
    keys=["customer_id"], sequence_by="event_ts",
    apply_as_deletes="op = 'DELETE'", stored_as_scd_type=2,
    track_history_except_column_list=["op", "_source_file_path", "_processing_timestamp"])

@dp.materialized_view  # GOLD
def gold_daily_revenue():
    return (spark.read.table("silver_customers")
            .where("__END_AT IS NULL")
            .groupBy("region").sum("amount"))
```
```sql
CREATE OR REFRESH STREAMING TABLE bronze_sales
AS SELECT *, _metadata.file_path AS _source_file_path, current_timestamp() AS _processing_timestamp
FROM STREAM read_files('s3://bucket/incoming/sales/', format => 'csv');

CREATE OR REFRESH STREAMING TABLE silver_customers;
CREATE FLOW silver_cdc AS AUTO CDC INTO silver_customers
FROM STREAM(bronze_sales) KEYS (customer_id)
APPLY AS DELETE WHEN op = 'DELETE' SEQUENCE BY event_ts
COLUMNS * EXCEPT (op, _source_file_path, _processing_timestamp) STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW gold_daily_revenue
AS SELECT region, sum(amount) FROM silver_customers WHERE __END_AT IS NULL GROUP BY region;
```

**Best-practice note:** Databricks recommends separating ingestion (bronze) from transformation (silver/gold) into distinct pipelines so a transform failure doesn't block new data from landing — this mirrors my Apollo Gen2 two-job split (preprocessing notebook → SDP pipeline via `depends_on`).

**One-liner:** Auto Loader streaming-table bronze (incremental, replayable, metadata-tagged), a streaming/AUTO-CDC SCD silver, and a materialized-view gold, run as a daily triggered update — with `addNewColumns` evolution plus a freshness WARN to catch the silent dropped-column NULL.

## Category 1.2–1.3 — Object Model, Pipeline Modes & Full Refresh (Q5–Q9)

### Q5 — Object types in a Spark Declarative Pipeline
**Question:** What types of objects can be created in Delta Live Tables (DLT)? (DLT = SDP / Lakeflow Declarative Pipelines — answered in SDP terms.)

**The object model (verified, current SDP docs).** A pipeline declares three **dataset** types plus two **plumbing** primitives:

| Object | SDP decorator / SQL | Backed by | Persisted? | Use |
|---|---|---|---|---|
| **Streaming table (ST)** | `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` | UC-managed Delta | Yes (published to UC) | Incremental ingest; each row processed **exactly once**; assumes an append-only source |
| **Materialized view (MV)** | `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` | UC-managed Delta | Yes (published to UC) | Transforms/joins/aggregations; **results pre-computed and cached**, incrementally refreshed |
| **Temporary view** | `@dp.temporary_view` / `CREATE TEMPORARY VIEW` | nothing (logic only) | No (pipeline-scoped) | Intermediate steps, no downstream readers |
| **Flow** | `@dp.append_flow`, `dp.create_auto_cdc_flow`, `dp.create_auto_cdc_from_snapshot_flow`, `@dp.update_flow` | — | — | A query→target unit; multiple flows can feed one ST |
| **Sink** | `dp.create_sink` | Delta or Kafka (`format="delta"` / `"kafka"`) | external | Append/update records to an external target |

**Flow types under the hood (per the SDP flows doc):** **Append** (the default flow created with any ST or MV — append flows back materialized views too), **Auto CDC** (previously *apply changes*; SCD1/SCD2; ST-only target), and **Update** (Public Preview, Python-only, emits changed aggregate records to a sink). A streaming table can have many flows written into it; an MV's default append flow is defined implicitly.

**Sink note:** `create_sink` (Public Preview) takes `format="delta"` or `format="kafka"` only — the `kafka` format also covers Azure Event Hubs via its Kafka-compatible interface; arbitrary targets need a Python custom data source or a `@dp.foreach_batch_sink`. Sinks accept only **append** and **update** flows — not `create_auto_cdc_flow`. A full refresh does **not** clear data already written to a sink.

**PySpark — one of each:**
```python
from pyspark import pipelines as dp

@dp.table  # streaming table
def bronze_accounts():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "csv").load("/incoming/accounts")

@dp.temporary_view  # not persisted
def accounts_clean():
    return spark.read.table("bronze_accounts").dropDuplicates(["accountid"])

@dp.materialized_view  # persisted, incrementally refreshed
def accounts_by_country():
    return spark.read.table("accounts_clean").groupBy("country").count()
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE bronze_accounts
AS SELECT * FROM STREAM read_files('/incoming/accounts', format => 'csv');

CREATE TEMPORARY VIEW accounts_clean AS SELECT DISTINCT * FROM bronze_accounts;

CREATE OR REFRESH MATERIALIZED VIEW accounts_by_country
AS SELECT country, count(*) AS n FROM accounts_clean GROUP BY country;
```

**Apollo Gen2 note (first person):** In my JOB2 SDP pipeline I only use STs and MVs — STG layer is `@dp.table` streaming tables fed by Auto Loader, BRZ layer is SCD2 streaming tables fed by `dp.create_auto_cdc_flow`. Temporary views I use sparingly for intermediate dedup before the CDC flow.

**One-liner:** SDP gives you three dataset objects — streaming tables, materialized views, temporary views — plus flows and sinks as the plumbing that writes into them.

### Q6 — DLT view vs materialized view
**Question:** What is the difference between a DLT view and a materialized view? When should each be used?

**Core distinction = materialization.** A **view (temporary view, `@dp.temporary_view`)** stores **no data** — its query is recomputed every time it is read, and it exists only inside the pipeline. A **materialized view (MV, `@dp.materialized_view`)** stores its results in a UC-managed Delta table and keeps them up to date via incremental refresh; it is queryable from outside the pipeline.

| Dimension | Temporary view | Materialized view (MV) |
|---|---|---|
| Data stored | No (logic only) | Yes (Delta table in UC) |
| When computed | Every read (on demand) | At pipeline update; cached between updates |
| Visible outside pipeline | No (pipeline-scoped) | Yes (published to catalog.schema) |
| Storage/compute cost | None | Storage + refresh compute |
| Incremental refresh | N/A | Yes on **serverless**; classic compute = full recompute every update |

**Use a temporary view when:**
- Breaking a large query into readable steps with no downstream persistence.
- You want zero storage cost and no external consumers.

**Use an MV when:**
- Multiple downstream queries/pipelines/jobs consume the result (a view is re-run on every read; an MV is computed once).
- You need fast dashboard/analytic reads (gold layer).
- You want to inspect results during development (MVs are queryable; views are not).

**PySpark:**
```python
from pyspark import pipelines as dp

@dp.temporary_view
def filtered():                       # recomputed each reference, not stored
    return spark.read.table("bronze_orders").where("amount > 0")

@dp.materialized_view
def daily_revenue():                  # stored + incrementally refreshed
    return spark.read.table("filtered").groupBy("order_date").sum("amount")
```

**SQL equivalent:**
```sql
CREATE TEMPORARY VIEW filtered AS SELECT * FROM bronze_orders WHERE amount > 0;

CREATE OR REFRESH MATERIALIZED VIEW daily_revenue AS
SELECT order_date, SUM(amount) AS revenue FROM filtered GROUP BY order_date;
```

**Gotcha (call out the invisible cost):** incremental MV refresh only happens when the backing pipeline runs on **serverless** compute and only for supported query shapes; on classic compute, or with an unsupported expression, the MV is **fully recomputed** every update — silently more expensive than expected. (Note: an MV expressing an expectation needs the older `CREATE LIVE VIEW` form if you want the constraint on a non-materialized view; a plain `CREATE TEMPORARY VIEW` does not carry expectations.)

**One-liner:** A view recomputes its query on every read and never leaves the pipeline; a materialized view stores its results as a Delta table and refreshes them incrementally, so use views for cheap intermediate logic and MVs for reused, persisted transforms.

### Q7 — Live Tables vs Live Streaming Tables
**Question:** What is the difference between Live Tables and Live Streaming Tables in DLT? When would you use each type?

**Legacy→SDP mapping (one clause):** legacy "Live Table" = **materialized view (MV)** and legacy "Live Streaming Table" = **streaming table (ST)**; answering in SDP terms below.

**The difference is the processing model:**

| | Streaming table (ST) | Materialized view (MV) |
|---|---|---|
| Processing | Each input row processed **exactly once** (incremental, append) | Results computed to be **correct for current state**; incrementally refreshed |
| Source requirement | **Append-only** stream (`spark.readStream` / `STREAM(...)`) | Any batch query (`spark.read`) |
| Reacts to source updates/deletes | No (append-only assumption; throws on a change/delete commit) | Yes — recomputes to reflect deletes/updates |
| State/checkpoint | Maintains streaming checkpoint per flow | No streaming checkpoint |
| Typical layer | Bronze ingest, silver row-level transforms, CDC targets | Silver enrichment joins, gold aggregations/dashboards |

**Use a streaming table when:**
- Source grows continuously/incrementally (cloud files, Kafka, CDC feed).
- You want high throughput, low latency, and want to read each record only once.
- It is the target of `dp.create_auto_cdc_flow` (AUTO CDC).

**Use a materialized view when:**
- The query is a transform/join/aggregation that must always reflect the **current** state of mutable sources.
- Downstream consumers need fast pre-computed reads.

**PySpark:**
```python
from pyspark import pipelines as dp

@dp.table  # streaming table: read each event once
def events_bronze():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "json").load("/incoming/events")

@dp.materialized_view  # recomputes to current correct state
def events_per_user():
    return spark.read.table("events_bronze").groupBy("user_id").count()
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE events_bronze
AS SELECT * FROM STREAM read_files('/incoming/events', format => 'json');

CREATE OR REFRESH MATERIALIZED VIEW events_per_user
AS SELECT user_id, count(*) AS n FROM events_bronze GROUP BY user_id;
```

**Apollo Gen2 hard incident (first person):** My signature failure here is **streaming-on-mutable-source** — a `@dp.table` streaming table assumes an append-only source. When I pointed one at an upstream that was being updated/deleted in place, the stream threw on the change commit; the fix is either make the source append-only, switch to a materialized view (no append-only restriction), or set `skipChangeCommits` when reading the source ST (an `spark.readStream.option(...)` flag — note it cannot be used when that source ST is itself the target of a `create_auto_cdc_flow`).

**One-liner:** A streaming table reads an append-only source exactly once for incremental ingest, while a materialized view recomputes a batch query to stay correct against mutable sources — STs for ingest/CDC, MVs for transforms and aggregations.

### Q8 — Development vs production mode
**Question:** What are the differences between development and production modes in a DLT pipeline?

**What the toggle is.** `development` is a boolean pipeline setting (default **`false`**, surfaced as a Development/Production UI toggle). It does **not** change the target catalog/schema or where tables are published — only cluster lifecycle and how runtime upgrades are handled.

**Important current-docs nuance.** In current SDP docs the cluster-reuse-vs-teardown and retry behavior is described as **"update run behavior" determined by how you trigger the update**, not strictly by the dev/prod flag:
- **Fast-start / debugging behavior** — used by **UI "Run now"** and ad-hoc updates: **reuses the cluster** (clusters run **2 h** by default, tunable via `pipelines.clusterShutdown.delay`) and **disables retries** so errors surface immediately.
- **Automatic retry and restart behavior** — used by **Jobs, the Pipelines API, and continuous pipelines**: restarts the cluster on recoverable errors (memory leaks, stale credentials), retries on errors like cluster-launch failure, and **shuts the cluster down immediately after the run**.

Development mode aligns you with the fast-start behavior (warm cluster, fail-loud) during iteration; production mode aligns with the reliable, cost-efficient teardown-and-retry path for scheduled runs.

| Behavior | Development | Production |
|---|---|---|
| Cluster lifecycle | Reuses the cluster across updates (default **2 h** idle, `pipelines.clusterShutdown.delay`) | Cluster **shuts down immediately** after each run |
| Retries | Effectively off for ad-hoc/UI runs — errors surface immediately | Automatic retry/restart on recoverable errors |
| Update retry count | n/a for ad-hoc/Validate runs | `pipelines.numUpdateRetryAttempts` default **5** (triggered) / **unlimited** (continuous) |
| Flow retry count | n/a | `pipelines.maxFlowRetryAttempts` default **2** (3 total attempts incl. the original) |
| Runtime auto-revert on a bad upgrade | No | Yes — SDP reverts to the last known-good runtime **only for pipelines running in production mode with `channel` = `current`** |
| Goal | Rapid debug loop | Reliability + cost efficiency |

**Note (avoid a common confusion):** dev/prod is distinct from **triggered vs continuous** pipeline mode (the `continuous` flag, default `false`), which controls whether the pipeline stops after processing all data vs runs always-on. Dev/prod is about cluster reuse + upgrade handling; triggered/continuous is about scheduling/latency.

**Approach (how I'd answer "how do you promote dev→prod"):**
- Develop with the pipeline in **development** mode so the cluster stays warm and failures stop loudly for debugging.
- Use **Declarative Automation Bundles**: a target with `mode: development` deployed via `databricks bundle deploy -t dev` marks pipelines `development: true`, prefixes resource names with `[dev ${workspace.current_user.short_name}]`, and pauses schedules/triggers; a `mode: production` target deployed via `databricks bundle deploy -t prod` validates all pipelines are `development: false`, validates the configured Git branch, and recommends a service-principal `run_as`.
- Flip to **production** mode for the scheduled/Jobs run so the cluster tears down per-run and transient failures auto-retry.

**One-liner:** The `development` flag (default false) plus the update trigger source decide cluster lifecycle and retries — development/Run-now keeps the cluster warm and fails loud for a fast debug loop; production/Jobs tears the cluster down per run and auto-retries for reliable, cost-efficient scheduled execution — neither changes where data is published.

### Q9 — Full refresh
**Question:** Explain the concept of a full refresh in DLT and when it should be used.

**What it is.** A **full refresh reprocesses every record from the source under the table's latest definition.** Contrast with the default refresh, which is **incremental** (STs process only new rows once; MVs incrementally update where possible). The two refresh types behave very differently on the two dataset types:

| Target | Default (incremental) refresh | **Full** refresh (`FULL`) |
|---|---|---|
| Materialized view | Incremental on serverless; else full recompute | Recomputes all source data; **returns the same results as a default refresh** (it clears the MV's stored results + checkpoints, but the output is identical) |
| Streaming table | Reads only new rows once | **Truncates** the table, **clears the flows' checkpoints/state**, and reprocesses all available source data |

**SQL:**
```sql
-- Streaming table: truncate + reprocess from scratch
REFRESH STREAMING TABLE cat.schema.bronze_accounts FULL;

-- Materialized view: recompute all source data (same result as default)
REFRESH MATERIALIZED VIEW cat.schema.daily_revenue FULL;
```
In a pipeline, you trigger it via the UI ("Full refresh all" / select tables), the Pipelines API `start-update` with full-refresh selection, or `databricks pipelines start-update`.

**When to use it:**
- Schema or logic change in a stateful/streaming query (e.g., changed watermark, aggregation columns) — old checkpoint state is incompatible and must be rebuilt.
- Corrupted/inconsistent target, or a backfill where you must reprocess the full history.
- Recovering from a streaming checkpoint failure or corruption (full refresh is one of the documented recovery paths; the others are backup-then-backfill, or a selective checkpoint reset that preserves the data).

**When NOT to use it (the dangerous part — call out the silent data loss):**
- Sources with **short retention** (Kafka) or **lifecycle-expired** object-storage files: a full refresh on a streaming table **truncates first**, then can only reload what the source still has — records no longer in the source are **dropped** from the target. (The same applies to an MV: removed source records are not reflected in the recomputed results.)
- An SCD2 history table: a full refresh wipes the accumulated history.
- Protect critical tables with the table property **`pipelines.reset.allowed = false`** to block full refresh entirely.

**Approach (scenario "you changed a silver aggregation, downstream numbers are wrong"):**
1. Confirm the source still holds the full history needed to rebuild (else you lose data).
2. For a single table, run a **selective** full refresh on just that table to limit blast radius and compute.
3. For an append-only need where you only want new data without truncation, prefer an **`@dp.append_flow`** instead of a full refresh.

**Apollo Gen2 note (first person):** On my BRZ SCD2 tables I keep a `pipelines.reset.allowed=false` mindset, because a full refresh would truncate the streaming table and destroy SCD2 history; if I genuinely need to rebuild, I confirm the ADLS `incoming/` files still cover the full window first, since Synapse Link replicate output is not infinite-retention.

**One-liner:** A full refresh reprocesses all source records under the latest definition — for a streaming table it truncates the table and resets the flows' checkpoints/state, for an MV it recomputes to the same result — use it for schema/logic changes or backfills, but never on short-retention sources, because anything no longer in the source is dropped.

## Category 2 — Materialized Views Deep Dive (Q10–Q13)

### Q10 — Challenges and limitations of materialized views (MV) in SDP
**Question:** What are the challenges or limitations of using materialized views (MV) in DLT (SDP)?

**Term:** MV (materialized view) = a `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` dataset in SDP (Spark Declarative Pipelines / Lakeflow). It is a Unity Catalog managed table with a **batch flow**: the query result is precomputed and stored, then kept in sync with sources on each pipeline trigger — incrementally when possible, else by full recompute.

**Hard limitations (verified, current docs):**
- **Incremental refresh is serverless-only.** For an MV defined in SDP, the pipeline must be configured to use serverless; on classic compute the MV is **always fully recomputed** — no incremental path exists. (Note: refresh operations themselves always run on serverless pipelines; the serverless-vs-classic distinction is about the *pipeline's* configured compute.) This is the single biggest gotcha.
- **`PIVOT` is not supported at all in pipelines** — not "falls back to full recompute," it's an unsupported clause. `pivot` requires eager loading of input data to compute the output schema, which pipelines don't support.
- **Not all queries can be incrementalized** (these still run, but force `FULL_RECOMPUTE`): recursive CTEs (`WITH RECURSIVE`); non-deterministic functions other than the time functions `current_date()`/`current_timestamp()`/`now()`, which are supported only in `WHERE`; volumes / external locations / foreign catalogs as sources; foreign Iceberg tables (Unity Catalog managed Iceberg v2/v3 *are* supported).
- **Source must survive full-refresh semantics.** Even an incrementalizable MV may fall back to full recompute, which **rescans the whole source**. If the source deletes/archives old rows (retention threshold), a full refresh silently drops those rows from the result and may even change the schema. So MVs are wrong for sources that retain no history (Kafka) or process-once ingest (Auto Loader).
- **Not low-latency.** Update latency is seconds-to-minutes, not milliseconds. Not for real-time.
- **Read-only output.** You cannot `INSERT`/`UPDATE`/`DELETE` an MV directly — the query definition is the only control. To delete data you must delete from the source and refresh.
- **Single-pipeline ownership.** An MV is defined and updated by exactly one pipeline; no other pipeline can write it.
- **No `CLONE`** — you cannot use an MV as the source or target of a deep or shallow clone.
- **No `OPTIMIZE` / `VACUUM`** — maintenance is automatic; those commands are disallowed.
- **UDF drift risk.** SDP attempts to detect when a UDF changes behavior and full-refresh, but a UDF that calls other functions/libraries may change behavior undetected; then it's your responsibility to trigger a full refresh or the MV silently serves stale logic.
- **Incremental refresh needs Delta features on sources.** Many techniques require **row tracking** (a Delta-only feature); row filters / column masks on a source force a **full refresh** every time (they disable incremental refresh).
- **Identity columns may be recomputed** on MV updates — Databricks recommends identity columns only on streaming tables. (The pipelines `CREATE MATERIALIZED VIEW` reference goes further and lists generated/identity/default columns as unsupported.)

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import count, sum as _sum

@dp.materialized_view  # batch flow; on a serverless pipeline => can incrementally refresh
def transaction_summary():
    return (spark.read.table("transactions_table")
            .groupBy("account_id")
            .agg(count("*").alias("txn_count"),
                 _sum("txn_amount").alias("account_revenue")))
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW transaction_summary AS
SELECT account_id, COUNT(txn_id) AS txn_count, SUM(txn_amount) AS account_revenue
FROM transactions_table
GROUP BY account_id;
```

**Inspect which path ran** (catches the silent full-recompute trap): query the event log for `planning_information` — technique is `ROW_BASED` / `GROUP_AGGREGATE` / `GENERIC_AGGREGATE` / `APPEND_ONLY` / `PARTITION_OVERWRITE` / `WINDOW_FUNCTION` (all incremental) vs `FULL_RECOMPUTE` (`NO_OP` = nothing changed).
```sql
SELECT timestamp, message
FROM event_log(TABLE(my_catalog.my_schema.transaction_summary))
WHERE event_type = 'planning_information'
ORDER BY timestamp DESC;
```
(To check incrementalizability *before* shipping, prepend `EXPLAIN` to the create statement: `EXPLAIN CREATE MATERIALIZED VIEW ...` — but it confirms only structural eligibility, not that the `AUTO` cost model will actually pick incremental at runtime.)

**Apollo Gen2 grounding:** In my pipeline the bronze SCD2 layer is built with `create_auto_cdc_flow` on **streaming tables**, not MVs, precisely because the Synapse-Link source is process-once / append-style and an MV's full-recompute fallback would rescan everything and lose deleted-record history. I reserve MVs for gold-layer aggregations where full recompute is tolerable and the source is a stable Delta table.

**One-liner:** An MV is a precomputed batch result that's only incrementally refreshed on a serverless pipeline, falls back to full recompute on unsupported queries or classic compute (and rejects `PIVOT` outright), is read-only, isn't low-latency, and must never sit on a process-once source.

### Q11 — When to prefer a materialized view over a streaming table
**Question:** When should I prefer a materialized view over a streaming table in my pipeline architecture?

**Core distinction:** **Streaming table** (`@dp.table`) = **streaming flow**, append-only semantics, each input row read **exactly once**. **MV** (`@dp.materialized_view`) = **batch flow**, result equals re-running the full batch query, kept fresh by incremental refresh when possible.

**Decision table:**
| Need | Pick | Why |
|---|---|---|
| Ingest from cloud storage / Kafka / message bus | Streaming table | Each record processed once; high volume, append-only |
| CDC inserts/updates/deletes | Streaming table (target of `create_auto_cdc_flow` / `AUTO CDC ... INTO`) | Ordered, deduplicated SCD1/SCD2 |
| Source is continuously/incrementally **growing** & must be processed once | Streaming table | Exactly-once; checkpointed |
| Source mutates (rows updated/deleted in place) | **MV** | Streaming needs append-only source; MV reflects updates correctly |
| Complex aggregations / multi-table joins (gold) | **MV** | Result always correct even for late/out-of-order data; incrementally refreshed |
| Dashboard / BI query acceleration | **MV** | Precomputed result; fast reads |
| Full recompute would be cost-prohibitive (huge table) | Streaming table | Avoids rescan; guarantees exactly-once |
| Dimension enrichment in silver (join recomputes when dimension changes) | MV | Streaming-table joins do **not** recompute when a dimension changes; an MV recomputes the join, so it stays correct |

**Approach (the mental test I apply):**
1. **Is the source append-only and must each row be seen once?** Yes -> streaming table. (Process-once ingest, Kafka, Auto Loader.)
2. **Does the source mutate in place, or do I need the *current correct aggregate/join* regardless of arrival order?** -> MV. An MV guarantees batch-equivalent correctness even with late/out-of-order data; a streaming aggregate would need watermarks and still drop late data, and a streaming-table join won't recompute when its dimension changes.
3. **Would a worst-case full recompute be affordable?** MV may fall back to full recompute. If the source is enormous and recompute is prohibitive, use a streaming table instead.
4. **Medallion mapping:** bronze/silver row-level = streaming tables; silver enrichment joins + gold aggregates = MVs.

```python
from pyspark import pipelines as dp

@dp.table  # streaming table: append-only ingest, exactly-once
def orders_bronze():
    return spark.readStream.table("raw_orders")

@dp.materialized_view  # batch flow: correct aggregate, incrementally refreshed on a serverless pipeline
def daily_orders_by_state():
    return (spark.read.table("orders_silver")
            .groupBy("state", "order_date").count())
```

```sql
CREATE OR REFRESH STREAMING TABLE orders_bronze
  AS SELECT * FROM STREAM read_files('/mnt/raw/orders', format => 'json');

CREATE OR REFRESH MATERIALIZED VIEW daily_orders_by_state AS
SELECT state, order_date, COUNT(*) AS n
FROM orders_silver GROUP BY state, order_date;
```

**Apollo Gen2 grounding:** All 422 of my pipelines use **streaming tables** at STG and BRZ because the source is a process-once Synapse-Link replicate feed and BRZ is SCD2 via `create_auto_cdc_flow` (AUTO CDC) — exactly the streaming case. I hit the "streaming-on-mutable-source" incident first-hand: a streaming table needs an append-only source, and a mutable upstream breaks it. If I were building a gold sales summary on top of stable BRZ Delta tables, that layer would be an MV.

**One-liner:** Use a streaming table when the source is append-only and each row must be processed exactly once; use an MV when you need a batch-correct aggregate or join over a possibly-mutating source and can tolerate an occasional full recompute.

### Q12 — MV behavior on serverless vs standard clusters, and the 10MB-of-1M-rows case
**Question:** How do materialized views behave differently on serverless clusters vs. standard clusters? For example, if only 10MB of data changes in a 1-million-row dataset, how will MV performance differ?

**The hard rule:** Incremental refresh is available **only when the SDP pipeline runs on serverless**. On a **classic/standard** pipeline the MV is **always fully recomputed**. (Refresh operations always execute on serverless pipelines internally; the distinction here is the *configured pipeline compute* — an MV defined in a classic-compute SDP pipeline gets full recompute.)

| | Serverless pipeline | Standard (classic) pipeline |
|---|---|---|
| Incremental refresh | Yes (best-effort, cost-model chosen) | **No — always FULL_RECOMPUTE** |
| 10MB changed of 1M rows | Detects changed rows/groups, recomputes only those | Re-reads & re-aggregates all 1M rows |
| Cost driver | Proportional to **change size** | Proportional to **full dataset size** |
| Decision logic | Cost analysis picks cheaper of incremental vs full | Full recompute only |

**The 10MB / 1M-row example (the answer they want):**
- **Serverless:** SDP detects that only ~10MB changed since the last refresh. For an aggregate (`GROUP BY`), it recomputes **only the affected groups** (technique `GROUP_AGGREGATE`, or `ROW_BASED` for row-level changes), then merges. Work scales with the **delta**, not the table. Cheap and fast. If nothing changed, technique is `NO_OP` — zero work.
- **Standard:** It rescans and recomputes **all 1,000,000 rows** every trigger, regardless that only 10MB moved. Same correct result, but far more compute than the serverless incremental path in this example.

**Approach — to actually get the cheap path on serverless:**
1. Run the pipeline on **serverless**.
2. Enable the optimization features on **source** tables (Databricks recommends all three on every MV source table):
```sql
ALTER TABLE source_tbl SET TBLPROPERTIES (
  delta.enableDeletionVectors = true,
  delta.enableRowTracking = true,
  delta.enableChangeDataFeed = true);
```
Row tracking is required by many incremental techniques; without it those operations fall back to full recompute. (Row filters / column masks on the source force a full refresh entirely.)
3. Keep the query incrementalizable (deterministic, supported constructs; no `PIVOT`, no recursive CTE).
4. **Verify** the technique actually used — don't assume:
```sql
SELECT timestamp, message FROM event_log(TABLE(cat.sch.my_mv))
WHERE event_type = 'planning_information' ORDER BY timestamp DESC;
-- look for GROUP_AGGREGATE / ROW_BASED (incremental) vs FULL_RECOMPUTE
```
5. To **force** behavior, set a refresh policy:
```python
@dp.materialized_view(refresh_policy='incremental_strict')  # fail rather than silently full-recompute
def my_mv():
    return spark.read.table("source_tbl")
```
```sql
CREATE MATERIALIZED VIEW my_mv REFRESH POLICY INCREMENTAL STRICT
AS SELECT a, SUM(b) AS sum_b FROM source_tbl GROUP BY a;
```
Policies: `AUTO` (default, cost-based), `INCREMENTAL` (prefer; fall back to full if the plan no longer supports incremental), `INCREMENTAL STRICT` (fail the update if not incrementalizable), `FULL` (always full).

**One-liner:** On a serverless pipeline an MV with 10MB changed in 1M rows recomputes only the affected groups (work scales with the delta); on a classic pipeline there is no incremental path so it re-aggregates all 1M rows every refresh.

### Q13 — How an MV refreshes incrementally yet still aggregates the whole dataset
**Question:** How does a materialized view process data incrementally while still performing aggregations on the entire dataset?

**The apparent paradox:** A `GROUP BY` is a whole-table operation, yet SDP claims to refresh "only the changed data." Resolution: the **result** is always batch-correct (equals re-running the full query), but the **work** to reach that result is incremental. SDP maintains internal state so it never re-scans unchanged data.

**Mechanism (concrete trace):**
- MV: `SELECT country, SUM(amount) FROM txns GROUP BY country`. Suppose stored result is USA=100, UK=80, NL=50.
- A trigger adds 5,000 new `txns` rows touching only **USA** and **NL**.
- SDP uses **Change Data Feed + row tracking** on the source to read **only the changed rows** (the delta), not all of `txns`.
- It computes a **partial aggregate** over just those rows: +30 USA, +10 NL.
- It **merges** the partial into the stored groups: USA 100->130, NL 50->60. **UK is untouched** — its group is never recomputed.
- Final MV is identical to a full `GROUP BY` over all rows, but only 2 of 3 groups did any work.

**Why it's still "entire dataset" correct:**
- For incrementalizable aggregates SDP keeps **internal tables that support incremental refresh** — Databricks creates these to back the MV; they appear in `system.information_schema.tables` but are **not visible in Catalog Explorer or other workspace UI surfaces**. They hold per-group running state, so adding the delta to that state == aggregating everything.
- It's **additive aggregate maintenance**: `SUM`, `COUNT`, `GROUP BY` compose from partial results. The technique shows as `GROUP_AGGREGATE` (or `GENERIC_AGGREGATE`) in the event log.
- Late/out-of-order rows still land in the correct group on the next refresh — that's why MVs are "always correct" without watermarks (unlike a streaming aggregate).
- If a change can't be expressed as a partial merge (e.g., upstream deletes that need group recomputation without row tracking, or a non-incrementalizable construct), SDP falls back to `FULL_RECOMPUTE` — same answer, higher cost.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum as _sum

@dp.materialized_view  # GROUP_AGGREGATE incremental maintenance on a serverless pipeline
def revenue_by_country():
    return (spark.read.table("txns")
            .groupBy("country")
            .agg(_sum("amount").alias("revenue")))
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW revenue_by_country AS
SELECT country, SUM(amount) AS revenue
FROM txns GROUP BY country;
```

**Requirements to keep it incremental:** serverless pipeline; deterministic query; row tracking (and ideally deletion vectors + CDF) enabled on the source; supported constructs only (`GROUP BY`, `SUM`/`COUNT`, inner/left/right/full joins, `WHERE`/`HAVING`, `UNION ALL`, window functions with `PARTITION BY` specified). Verify with the `planning_information` event-log query.

**One-liner:** The MV's output always equals a full batch aggregate, but SDP reaches it by reading only the changed rows via change-data-feed plus row tracking, computing a partial aggregate, and merging it into per-group state held in hidden internal tables — so untouched groups are never recomputed.

## Category 3 — Data Ingestion & Source Integration (Q14–Q16)

### Q14 — Ingesting Oracle into an SDP pipeline + optimizations
**Question:** How do you ingest data from Oracle into your DLT pipeline? What optimizations can be applied? (DLT = SDP — Spark Declarative Pipelines / Lakeflow Declarative Pipelines.)

**Key fact (verified):** There is **no CDC (gateway/binlog) connector for Oracle**. Lakeflow Connect's managed *database CDC* connectors cover only MySQL, PostgreSQL, and SQL Server. Oracle is still a **first-class managed source** — it is supported by Lakeflow Connect's **query-based connector** (foreign-connection ingestion; the other listed query-based sources are Teradata, SQL Server, MySQL, MariaDB, PostgreSQL). So Oracle reaches SDP through one of two supported paths — pick based on whether the source has a usable cursor column.

**The two real options (most-managed first):**

| Path | What it is | When to use | Writes to |
|---|---|---|---|
| **Query-based connector** (Lakeflow Connect) | Managed connector that queries Oracle directly each run via a Unity Catalog (UC) connection (foreign-connection ingestion) or a Lakehouse Federation foreign catalog; tracks a **cursor column** (single monotonic timestamp/int) as a high-water mark; no gateway, no staging volume; runs on **serverless** on a schedule (not continuous); created via UI or Declarative Automation Bundles | Oracle table has an `updated_at` / monotonic id; you want minimal code | a **streaming table** (`@dp.table`) |
| **Generic JDBC read inside a flow** | `spark.read.format("jdbc")` (or SQL `remote_query()`) over a UC **JDBC connection**, wrapped in an SDP dataset | No clean cursor column, custom SQL, or you need full control | `@dp.materialized_view` (batch snapshot) or `@dp.table` |

- **MV (materialized view) vs streaming table:** a full JDBC read sees a **mutable, non-append-only** source — a re-read sees changed/deleted rows. A streaming table (`@dp.table`) needs an **append-only** source, so pointing one straight at a mutable Oracle table errors out. So a raw full JDBC read lands in an **MV** (recomputed on refresh). Note: MVs on a **serverless** pipeline attempt *incremental* refresh, but a mutable external JDBC source generally can't be incrementalized, so it falls back to a **full recompute**. True incrementality comes from the cursor-column query-based connector, not from a full JDBC read.

**PySpark — generic JDBC read as an SDP materialized view (`from pyspark import pipelines as dp`):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import current_timestamp

@dp.materialized_view(name="brz_oracle_customers")
def brz_oracle_customers():
    return (
        spark.read.format("jdbc")
        .option("databricks.connection", "oracle_uc_conn")  # UC JDBC connection hides URL + creds
        .option("dbtable", "SALES.CUSTOMERS")               # allow-listed user option (or 'query')
        .option("partitionColumn", "CUSTOMER_ID")           # parallel read — must be numeric/indexed
        .option("lowerBound", "1")
        .option("upperBound", "10000000")
        .option("numPartitions", "16")                      # all four params required together
        .option("fetchsize", "100000")                      # rows per round trip; raise to cut latency
        .load()
        .withColumn("_ingest_ts", current_timestamp())
    )
```

**SQL equivalent (`remote_query` via Lakehouse Federation):**
```sql
CREATE OR REFRESH MATERIALIZED VIEW brz_oracle_customers AS
SELECT *, current_timestamp() AS _ingest_ts
FROM remote_query(
  'oracle_uc_conn',
  service_name => 'ORCL',          -- Oracle uses service_name, not database
  dbtable      => 'SALES.CUSTOMERS',
  partitionColumn => 'CUSTOMER_ID',
  lowerBound   => '1',
  upperBound   => '10000000',
  numPartitions => '16',
  fetchsize    => '100000'
);
```

**Optimizations (verified defaults):**
- **Parallel reads** — `partitionColumn` + `lowerBound` + `upperBound` + `numPartitions` (all four mandatory together; must use `dbtable`, not `query`). Bounds set the *stride only* — they do **not** filter rows; every row in the table is still partitioned and returned. Partition column must be numeric (or date/timestamp/string for the managed connector), evenly distributed, and ideally indexed.
- **`fetchSize`** — default is `0` (use driver default; often tiny, and most JDBC connectors fetch atomically, which can OOM). Set ~`100,000` so worker nodes read in batches. This batches per worker but is **not** parallel — that's what `numPartitions` is for.
- **Pushdown** — Lakehouse Federation pushes down filters, column projection, `LIMIT`, and many aggregates to Oracle by default. Push filters and projection down so Oracle does the work, not Spark.
- **Cursor-column incremental** — for the query-based connector, only rows with `cursor > stored_high_water_mark` are pulled each run; NULL-cursor rows are skipped, and the cursor must be a single monotonic column. Avoids full-table scans on a hot Oracle instance.
- **Don't over-partition** — too many parallel JDBC connections can crash the source DB; keep `numPartitions` in the low tens, not hundreds.

**Approach (how I'd answer the client):**
1. Check Oracle for a reliable single cursor column (`LAST_MODIFIED`/sequence). If present → **query-based connector**, write to a streaming table, schedule it. If not → **generic JDBC read** into an MV.
2. Stand up the **UC connection** once (URL + creds hidden in the connection, never inlined; allow-listed options exposed via `externalOptionsAllowList`) — reusable across compute.
3. Land raw in **bronze** with operational metadata (`_ingest_ts`, source name); enforce schema once here.
4. Tune parallel reads + `fetchSize`; push filters down; add `@dp.expect` quality gates on bronze.

> *Apollo Gen2 note:* my project ingests **Dynamics 365 → Synapse Link → ADLS CSV → SDP**, so my bronze source is files (Auto Loader), not JDBC. For an Oracle source I'd reuse the same medallion + SCD2 bronze pattern, but swap the file reader for a UC JDBC connection / query-based connector as the bronze flow's source.

**One-liner:** Oracle has no CDC/gateway connector, so I ingest it either via the Lakeflow **query-based connector** (single-cursor-column high-water mark into a streaming table) or a **generic UC JDBC read** into a materialized view, then tune it with parallel reads (`partitionColumn`/bounds/`numPartitions`), a large `fetchSize` (~100k), and filter pushdown.

### Q15 — Handling soft deletes (active flags vs other methods)
**Question:** How do you handle soft deletes in the data source — through active flags or another method?

**Definition first:** A **soft delete** = the source never physically removes the row; it flags it (`IsActive=0`, `IsDeleted=1`, or sets `DeletedDate`). A **hard delete** = the row physically disappears from the source. The handling differs because a soft delete still arrives as a normal change row, a hard delete arrives as nothing (the row is just absent).

**The decision: turn the soft-delete flag into a real CDC DELETE.** In SDP, `dp.create_auto_cdc_flow` (AUTO CDC) treats every event as an upsert *unless* `apply_as_deletes` matches — so I map the source's active/deleted flag into that predicate. The row is then removed from the *current* view, and under SCD2 it's closed off with `__END_AT`.

| Source pattern | SDP handling |
|---|---|
| `IsActive` boolean flag | `apply_as_deletes = "IsActive = false"` |
| `IsDeleted` / `RecordStatus` | `apply_as_deletes = expr("IsDeleted = 1")` |
| `DeletedDate` populated | `apply_as_deletes = "DeletedDate IS NOT NULL"` |
| Lakeflow query-based connector (no AUTO CDC) | API-only param `deletion_condition` (e.g. `"deleted_at IS NOT NULL"`) marks soft-deleted rows |

**Verified mechanics that matter in the interview:**
- **SCD2 + delete → tombstone:** when `apply_as_deletes` fires on an SCD2 target, the deleted row is **temporarily retained as a tombstone** in the underlying Delta table; a metastore **view filters tombstones out** so consumers don't see them. This exists to handle **out-of-order** events.
- **Tombstone retention default = two days**, configurable via the target table property `pipelines.cdc.tombstoneGCThresholdInSeconds`. If late/out-of-order deletes can arrive after two days, **raise this** so a late re-insert can't resurrect a row (set it above your worst-case event-arrival-to-pipeline-run delay).
- `apply_as_deletes` does **not** drop the row from history under SCD2 — it ends the current version (sets `__END_AT`). Under SCD1 it removes the row from current state.

**PySpark — soft-delete flag → SCD2 close-out (AUTO CDC):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("brz_customers")

dp.create_auto_cdc_flow(
    target              = "brz_customers",
    source              = "stg_customers",         # append-only streaming source
    keys                = ["CustomerId"],
    sequence_by         = "_change_ts",            # real per-row ordering, not file mod time
    apply_as_deletes    = expr("IsDeleted = 1"),   # soft-delete flag -> CDC DELETE
    except_column_list  = ["IsDeleted", "_change_ts", "_source_file_path"],
    stored_as_scd_type  = 2,
)
```

**SQL equivalent (SDP AUTO CDC):**
```sql
CREATE OR REFRESH STREAMING TABLE brz_customers;

CREATE FLOW customers_cdc AS AUTO CDC INTO brz_customers
FROM stream(stg_customers)
KEYS (CustomerId)
APPLY AS DELETE WHEN IsDeleted = 1
SEQUENCE BY _change_ts
COLUMNS * EXCEPT (IsDeleted, _change_ts, _source_file_path)
STORED AS SCD TYPE 2;
```

**Approach (scenario walk-through):**
1. **Identify the flag** — confirm with the source team which column carries the soft delete (`IsActive`/`IsDeleted`/`DeletedDate`) and its exact "deleted" value.
2. **Decide the semantic** — do downstream consumers need *history of when it was deactivated* (→ SCD2, close with `__END_AT`) or only *current active rows* (→ SCD1, drop from current)?
3. **Map flag → `apply_as_deletes`** in AUTO CDC so the framework handles ordering/dedup — never hand-roll a `MERGE`.
4. **Set tombstone retention** (`pipelines.cdc.tombstoneGCThresholdInSeconds`) to exceed worst-case late-delete latency.
5. **Don't blindly filter `WHERE IsActive=1` in bronze** — that loses the deactivation event silently. Keep the flag, let CDC act on it, and surface "active only" as a downstream view.

**One-liner:** Soft deletes are just flagged rows, so I map the source's active/deleted flag into `apply_as_deletes` (SQL `APPLY AS DELETE WHEN`) in AUTO CDC — which on SCD2 closes the row's `__END_AT` and parks it as a tombstone (retention default two days, tunable via `pipelines.cdc.tombstoneGCThresholdInSeconds`) rather than letting me silently filter the event away.

### Q16 — Propagating CDC from a CSV source into Delta, and which layer
**Question:** How do you propagate CDC changes from a CSV source into Delta tables? In which layer is CDC handled?

**Which layer — short answer:** CDC is applied at the **bronze layer** (the first persisted Delta layer). Auto Loader incrementally ingests the raw CSVs into an append-only staging streaming table, and `dp.create_auto_cdc_flow` materializes the de-duplicated, ordered current/historical state into the bronze SCD table. Silver/gold then read clean Delta — they never re-solve CDC.

**The flow (verified path):**
```
CSV in ADLS ──Auto Loader──▶ stg streaming table (@dp.table, append-only)
                                   │
                          dp.create_auto_cdc_flow  (AUTO CDC — handles order/dedup/deletes)
                                   ▼
                          brz SCD2 Delta table (current + __START_AT/__END_AT history)
```

**Why a staging table sits in between:** AUTO CDC's source **must be a streaming, append-only source** — if a streaming read encounters a change or deletion to an existing record, it throws an error (it is safest to read from static or append-only sources). New CSV files are append-only on arrival, so Auto Loader → `@dp.table` gives a clean append-only stream; AUTO CDC then resolves the actual upserts/deletes into bronze.

**PySpark — CSV → bronze SCD2 via AUTO CDC:**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr, current_timestamp, col

@dp.table(name="stg_customers")            # append-only landing of raw CSV
def stg_customers():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", "/Volumes/.../_schema/customers")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")  # default when no schema given
        .option("header", "true")
        .load("/Volumes/.../incoming/customers/")
        .withColumn("_source_file_path", col("_metadata.file_path"))
        .withColumn("_processing_ts", current_timestamp())
    )

dp.create_streaming_table("brz_customers")

dp.create_auto_cdc_flow(
    target             = "brz_customers",
    source             = "stg_customers",
    keys               = ["CustomerId"],
    sequence_by        = "_change_ts",          # real per-row ordering column
    apply_as_deletes   = expr("Operation = 'DELETE'"),
    except_column_list = ["Operation", "_change_ts", "_source_file_path", "_processing_ts"],
    stored_as_scd_type = 2,
)
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE stg_customers
AS SELECT *, _metadata.file_path AS _source_file_path, current_timestamp() AS _processing_ts
FROM STREAM read_files('/Volumes/.../incoming/customers/', format => 'csv', header => true);

CREATE OR REFRESH STREAMING TABLE brz_customers;

CREATE FLOW customers_cdc AS AUTO CDC INTO brz_customers
FROM stream(stg_customers)
KEYS (CustomerId)
APPLY AS DELETE WHEN Operation = 'DELETE'
SEQUENCE BY _change_ts
COLUMNS * EXCEPT (Operation, _change_ts, _source_file_path, _processing_ts)
STORED AS SCD TYPE 2;
```

**Two flavours of CSV CDC (know both):**
- **Change-feed CSVs** (each file is a row of inserts/updates/deletes with an `Operation` column) → `dp.create_auto_cdc_flow`.
- **Full-snapshot CSVs** (each file is the whole table state, no op column) → `dp.create_auto_cdc_from_snapshot_flow`, which diffs successive snapshots to derive the changes (Python interface only; snapshots must be processed in ascending version order, and you can't target the same streaming table with both flow types).

**Pitfalls I'd flag (from real CSV/Synapse work):**
- **`sequence_by` granularity** — `file_modification_time` is **too coarse** when many rows share one file; on ties CDC picks arbitrarily, and NULL sequence values aren't supported. Use a real per-row timestamp/sequence number.
- **Exclude operational-metadata columns the right way.** Two distinct levers: `except_column_list` *removes a column from the target table entirely*; `track_history_except_column_list` *keeps the column but doesn't open a new SCD2 version when only it changes*. If you leave `_processing_ts` / `_source_file_path` **in** the target and history-tracked, every re-run sees a "changed" metadata value and writes a **false SCD2 version** — so either drop them via `except_column_list` (as above) or, if you need to keep them, exclude them from history via `track_history_except_column_list`.
- **`schemaEvolutionMode` behavior (default `addNewColumns`)** — `addNewColumns` does **not** silently absorb a new column: the stream **fails with `UnknownFieldException`**, adds the new column to the schema location, and resumes on restart (run under a Lakeflow Job so it auto-restarts). It never removes/renames/retypes existing columns; a **dropped** source column is a soft delete — new rows land NULL. (Default is `addNewColumns` only when no schema is provided; if you supply a schema the default is `none`, and `addNewColumns` isn't allowed unless given as a schema hint.)
- **Headerless / trailing-comma CSVs** (Synapse Link) — fix in a preprocessing step before SDP, since SDP transformations can't run arbitrary file ops.

**Approach (Apollo Gen2, first person):**
On Apollo Gen2 (Dynamics 365 → Synapse Link → ADLS CSV → SDP, 211 entities) I do exactly this: a **JOB1 preprocessing notebook** adds headers from `model.json`, drops the phantom trailing-comma column, validates, and splits per entity into `incoming/` — because **SDP transformations can't run arbitrary Python** (`dbutils.fs`, file ops). **JOB2** is the SDP pipeline: Auto Loader → 211 STG streaming tables → `create_auto_cdc_flow` → 211 **bronze SCD2** tables, chained via `depends_on`. The 5 full-load entities use `create_auto_cdc_from_snapshot_flow` instead. CDC lives entirely in **bronze**; I never re-run CDC on an already-SCD2 source (that was a real incident — you collapse to current-only or map columns directly instead).

**One-liner:** I land raw CSV append-only via Auto Loader into a staging streaming table, then resolve CDC at the **bronze layer** with `dp.create_auto_cdc_flow` (snapshot CSVs use `create_auto_cdc_from_snapshot_flow`) into an SCD2 Delta table — sequenced by a real per-row column and excluding operational-metadata columns (via `except_column_list`, or from history via `track_history_except_column_list`) so re-runs don't create phantom versions.

## Category 4 — Change Data Capture (CDC) & Apply Changes (Q17–Q21)

### Q17 — When to apply CDC; streaming table vs materialized view for CDC
**Question:** When using Change Data Capture (CDC), in which scenarios would you apply it? How do you decide between using Live Tables and Live Streaming Tables for CDC operations?

*(Legacy mapping, one clause: "Live Table" = **MV (materialized view)**, "Live Streaming Table" = **streaming table**; SDP (Spark Declarative Pipelines) renamed these. Answer below is in SDP terms.)*

**When to apply CDC (AUTO CDC):** use `dp.create_auto_cdc_flow` (Python) / `AUTO CDC ... INTO` (SQL) when any of these is true:
- Source emits a **CDF (Change Data Feed)** — insert/update/delete rows with an operation column.
- You read a **Delta table with Change Data Feed enabled**.
- A relational DB feed arrives via **Debezium / Oracle GoldenGate** (the patterns Databricks docs name explicitly) and you need ordered, deduplicated upserts.
- You need SCD (Slowly Changing Dimension) Type 1 (overwrite) or Type 2 (history) **without hand-writing MERGE + out-of-order handling**.

> Edition gate (docs): AUTO CDC requires **serverless** SDP or the **`PRO`** / **`ADVANCED`** edition. The default `CORE` edition cannot run CDC.

**Where the CDC target must live — this is the real decision:**

| Question | Answer |
|---|---|
| Can AUTO CDC write into an MV? | **No.** An AUTO CDC flow targets a **streaming table only** (`@dp.table` / `CREATE OR REFRESH STREAMING TABLE`). Per docs, a streaming table that is the target of an AUTO CDC flow can only be targeted by other AUTO CDC flows. |
| Why not an MV? | An MV is a **batch flow** that recomputes from sources; it has no incremental upsert/delete keyed by `sequence_by`. |
| What about reading the CDC result downstream? | The AUTO CDC target produces **updates/deletes**, so a **downstream streaming table cannot read it as an append-only source** (the stream errors on a non-append change). Two valid options: consume it with an **MV** in gold, or stream from the AUTO CDC target's **own Change Data Feed** (the target table can emit a CDF for downstream consumers). |

**Decision rule (medallion):**
- **Bronze / silver CDC apply target → streaming table** (it is the only legal AUTO CDC target).
- **Gold / aggregations over the CDC table → materialized view** (incremental refresh on serverless, fast dashboard reads).

**Apollo Gen2 (first person):** In my Novartis CRM pipeline I run **211 STG streaming tables + 211 BRZ SCD2 streaming tables = 422 SDP pipelines**. Bronze is a streaming table because that is the only thing an AUTO CDC flow can write SCD2 into. Anything that aggregates across the SCD2 history I expose as an MV so it incrementally refreshes instead of re-scanning all versions.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_account")          # AUTO CDC target MUST be a streaming table

dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",                          # streaming source
    keys=["accountid"],
    sequence_by="_processing_timestamp",
    stored_as_scd_type=2,
)

@dp.materialized_view                              # gold rollup over the SCD2 table -> MV
def account_active_count():
    return spark.sql("SELECT COUNT(*) AS n FROM brz_account WHERE __END_AT IS NULL")
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account;

CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account)
KEYS (accountid)
SEQUENCE BY _processing_timestamp
STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW account_active_count
AS SELECT COUNT(*) AS n FROM brz_account WHERE __END_AT IS NULL;
```

**One-liner:** Apply AUTO CDC whenever the source is a change/snapshot feed — the apply target is always a streaming table (the only legal AUTO CDC target), while gold aggregations over it are materialized views.

### Q18 — Effectively applying changes (vs the deprecated auto-CDC feature)
**Question:** How to effectively apply changes (with reference to the deprecated auto-CDC feature)?

*(One-clause legacy mapping: the legacy `apply_changes()` / `APPLY CHANGES INTO` was **renamed** — same signature — to `dp.create_auto_cdc_flow()` / `AUTO CDC ... INTO`; `apply_changes_from_snapshot()` → `create_auto_cdc_from_snapshot_flow()`. Use the new names.)*

**The current API surface (SDP):**

| Capability | Python (SDP) | SQL (SDP) |
|---|---|---|
| Apply a change feed | `dp.create_auto_cdc_flow(...)` | `CREATE FLOW ... AS AUTO CDC INTO` |
| Apply from snapshots | `dp.create_auto_cdc_from_snapshot_flow(...)` | (Python only — no SQL surface) |
| Create the target | `dp.create_streaming_table("t")` | `CREATE OR REFRESH STREAMING TABLE t` |

**Effective-use checklist (what makes AUTO CDC correct, not just runnable):**
- **`keys`** — full natural/composite key that uniquely identifies a row. Wrong key = wrong upsert grain.
- **`sequence_by`** — a **monotonically increasing**, non-NULL column giving event order; AUTO CDC reorders out-of-sequence events for you. NULL sequencing values are not supported, and the column must hold **one distinct update per key per sequencing value** (use a `struct()` if a single column can't guarantee that — see Q21).
- **`apply_as_deletes`** — expr marking delete events (e.g. `"Operation = 'DELETE'"`); without it, deletes are treated as upserts.
- **`stored_as_scd_type`** — `1` (overwrite, **default**) or `2` (history with `__START_AT`/`__END_AT`).
- **`track_history_except_column_list` / `track_history_column_list`** — control which columns trigger a new SCD2 version. By default SCD2 versions on **any** changed column, so exclude operational metadata to avoid false history. (`except_column_list` / `COLUMNS * EXCEPT` instead controls which columns are *included in the target at all*.)
- **`ignore_null_updates`** (default **False**) — set **True** when the source sends only changed columns, so NULLs don't wipe unchanged columns. Default behavior is to overwrite existing columns with the incoming NULL.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_contact")

dp.create_auto_cdc_flow(
    target="brz_contact",
    source="stg_contact",
    keys=["contactid"],
    sequence_by="_processing_timestamp",
    apply_as_deletes="IsDelete = true",
    stored_as_scd_type=2,
    track_history_except_column_list=[          # critical in Apollo Gen2 (see one-liner)
        "_processing_timestamp", "_source_file_path", "SinkModifiedOn",
    ],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_contact;

CREATE FLOW contact_cdc AS AUTO CDC INTO brz_contact
FROM stream(stg_contact)
KEYS (contactid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY _processing_timestamp
COLUMNS * EXCEPT (_processing_timestamp, _source_file_path, SinkModifiedOn)
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (_processing_timestamp, _source_file_path, SinkModifiedOn);
```

> Note on the SQL surface: `COLUMNS * EXCEPT (...)` drops those columns from the *target*; `TRACK HISTORY ON * EXCEPT (...)` keeps them in the target but stops them from *triggering a new SCD2 version*. The Python equivalents are `except_column_list` and `track_history_except_column_list` respectively. The incident below is specifically about the **history-tracking** list.

**Apollo Gen2 incident (first person):** My biggest "effective apply" lesson was `track_history_except_column_list`. If I don't exclude every operational-metadata column (`_processing_timestamp`, `_source_file_path`, etc.) from *history tracking*, each re-run sees a "changed" value and closes the current SCD2 row + opens a new one — a **false history version on every pipeline run**. Listing those columns in the track-history-except list is what keeps SCD2 honest.

**One-liner:** `apply_changes` was renamed to `create_auto_cdc_flow` (same signature) — and applying changes *effectively* means correct `keys` + a monotonic, non-NULL `sequence_by` + explicit `apply_as_deletes` + excluding operational metadata from **history tracking** so re-runs don't fabricate SCD2 versions.

### Q19 — SCD Type 2 in SDP vs hand-written PySpark
**Question:** How do you apply SCD Type 2 logic in both DLT and standard PySpark pipelines?

*(DLT here = SDP; answered in SDP terms.)*

**SCD2 in one line of intent:** preserve full history — every change closes the prior row (`__END_AT` set) and opens a new current row (`__END_AT = NULL`).

**A. SDP way (declarative — what I use in production):**
- Set `stored_as_scd_type=2`. SDP auto-adds **`__START_AT`** and **`__END_AT`** populated from your `sequence_by` value (same data type as `sequence_by`) and handles dedup + out-of-order + delete tombstoning for you.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_account")
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account",
    keys=["accountid"], sequence_by="_processing_timestamp",
    apply_as_deletes="IsDelete = true", stored_as_scd_type=2,
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account;
CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account) KEYS (accountid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY _processing_timestamp
COLUMNS * EXCEPT (_processing_timestamp, _source_file_path)
STORED AS SCD TYPE 2;
```

**B. Standard PySpark way (the manual MERGE you avoid):**

```python
from delta.tables import DeltaTable
from pyspark.sql import functions as F

tgt = DeltaTable.forName(spark, "brz_account")
incoming = spark.read.table("stg_account")

# 1) rows whose key already exists AND value changed -> need a new version
changed = (incoming.alias("s")
    .join(tgt.toDF().alias("t"),
          (F.col("s.accountid") == F.col("t.accountid")) & (F.col("t.__END_AT").isNull()))
    .where(F.col("s.hashdiff") != F.col("t.hashdiff"))
    .select("s.*"))

# 2) staged union: NULL-key rows force the "close current row" branch; real rows insert
staged = (changed.withColumn("mergeKey", F.lit(None))
          .unionByName(incoming.withColumn("mergeKey", F.col("accountid"))))

(tgt.alias("t").merge(
    staged.alias("s"),
    "t.accountid = s.mergeKey AND t.__END_AT IS NULL")
 .whenMatchedUpdate(condition="t.hashdiff <> s.hashdiff",
                    set={"__END_AT": "s._processing_timestamp"})          # close old
 .whenNotMatchedInsert(values={                                            # open new
     "accountid": "s.accountid", "hashdiff": "s.hashdiff",
     "__START_AT": "s._processing_timestamp", "__END_AT": "null"})
 .execute())
```

| Aspect | SDP AUTO CDC | Hand-written PySpark MERGE |
|---|---|---|
| Out-of-order events | Auto (via `sequence_by`) | You must order + watermark yourself |
| Dedup per key per seq | Auto | Manual window/dedup |
| `__START_AT`/`__END_AT` | Auto-generated | You manage the two-branch NULL-key MERGE |
| Deletes | `apply_as_deletes` + tombstone | Custom delete branch |
| LOC for 211 entities | ~6 lines × config | hundreds of lines, brittle |

**Apollo Gen2 incident (first person):** The trap is **SCD2-on-SCD2** — if the source is *already* SCD2, do **not** run AUTO CDC SCD2 on top of it (you'd version the versions). I either collapse to current-only or preserve the existing history via direct column mapping.

**One-liner:** In SDP I set `stored_as_scd_type=2` and let `sequence_by` populate `__START_AT`/`__END_AT`; the equivalent raw-PySpark is a two-branch NULL-merge-key Delta MERGE that closes the old version and inserts the new one.

### Q20 — APPLY CHANGES set in silver but not reflected in gold
**Question:** If APPLY CHANGES is enabled in a silver layer but not reflected in the gold layer, what could be the issue?

*(APPLY CHANGES = SDP AUTO CDC; answered in SDP terms.)*

**Approach (diagnose top-down):** the AUTO CDC target in silver is a **streaming table that emits updates and deletes**. Gold's failure to reflect it almost always comes from *how gold consumes that mutable table*.

| # | Likely cause | Why gold goes stale / errors | Fix |
|---|---|---|---|
| 1 | **Gold is a streaming table reading the silver CDC table directly** | A streaming table needs an **append-only** source; an AUTO CDC target produces updates/deletes → the stream throws on the first non-append change (it does not silently "stall") | Make **gold an MV** (it recomputes incrementally over the mutable table); or stream from the silver target's **own Change Data Feed** instead of the table |
| 2 | **Gold reads only current rows but query forgets the SCD2 filter** | All historical versions counted, or stale versions shown | Filter `WHERE __END_AT IS NULL` for current-state gold |
| 3 | **Gold not refreshed / triggered** | Silver updated, gold update never ran | Trigger the gold pipeline / verify schedule; check decoupled bronze-silver vs gold pipelines. (Incremental MV refresh runs only on **serverless** — a non-serverless MV falls back to full recompute, which can look like lag) |
| 4 | **Deletes invisible at gold via the wrong object** | On **Hive metastore**, AUTO CDC creates a *view* over an internal `__apply_changes_storage_<name>` backing table that filters out delete tombstones; querying the backing table directly shows tombstoned rows | Read the **published view/table** by its declared name, never the `__apply_changes_storage_` backing table |
| 5 | **Expectation `expect_or_drop` upstream** | Rows dropped in silver never reach gold | Check data-quality metrics; relax/quarantine instead of drop |
| 6 | **`skipChangeCommits` misunderstanding** | `skipChangeCommits` lets a downstream streaming table *ignore* updates/deletes on a source — so deletes/updates would never propagate **by design**. But note: it **cannot be set when the source IS an AUTO CDC target** (docs explicitly disallow it there), so this only applies to ordinary mutable streaming sources, not the CDC target | Don't reach for `skipChangeCommits` to "fix" gold over a CDC target — switch gold to an MV |

```sql
-- WRONG: streaming table over a mutable AUTO CDC target -> errors on the first update/delete
CREATE OR REFRESH STREAMING TABLE gold_bad
AS SELECT * FROM STREAM(silver_cdc);

-- RIGHT: MV recomputes incrementally over the mutable silver table
CREATE OR REFRESH MATERIALIZED VIEW gold_good
AS SELECT region, COUNT(*) AS active
   FROM silver_cdc WHERE __END_AT IS NULL
   GROUP BY region;
```
```python
@dp.materialized_view
def gold_good():
    return spark.sql("""
        SELECT region, COUNT(*) AS active
        FROM silver_cdc WHERE __END_AT IS NULL GROUP BY region""")
```

**Apollo Gen2 (first person):** I hit exactly cause #1 — **streaming-on-mutable-source**. A gold streaming table off an SCD2 silver target errors on the first update/delete; the moment I switched gold to an MV with a `__END_AT IS NULL` filter it reflected correctly.

**One-liner:** 90% of the time it's that gold is a streaming table reading a mutable AUTO CDC target — switch gold to a materialized view (and filter `__END_AT IS NULL` for current state).

### Q21 — Preventing invalid records during APPLY CHANGES; sequenceBy and friends
**Question:** During APPLY CHANGES, how can we prevent invalid records from reaching the target table? What configurations can we set (e.g., sequenceBy)?

*(APPLY CHANGES = SDP AUTO CDC; answered in SDP terms.)*

**Approach — two distinct defenses, don't conflate them:**

**1. Correctness configs on `create_auto_cdc_flow` (prevent *wrong* upserts):**

| Config | Role | Default | Gotcha |
|---|---|---|---|
| `sequence_by` | Orders CDC events; AUTO CDC keeps the **latest per key**, reorders out-of-order events | required | Must be **monotonic + non-NULL**, with **one distinct update per key per sequencing value**; if a single column can tie, docs say to combine columns in a `struct()` |
| `keys` | Upsert grain | required | Wrong/partial key = merged or duplicated rows |
| `apply_as_deletes` | Marks delete events | none (treated as upsert) | Omit and deletes resurrect as rows |
| `ignore_null_updates` | Keep existing value when update column is NULL | **False** | Leave False and partial updates blank out columns (default overwrites with NULL) |
| `stored_as_scd_type` | 1 overwrite / 2 history | **1** | SCD2 needs `__START_AT`/`__END_AT` |
| `except_column_list` | Drop columns from the target | all included | exclude `operation`, metadata |
| `pipelines.cdc.tombstoneGCThresholdInSeconds` | How long SCD2 delete tombstones are retained for out-of-order deletes | **2 days (172800s)** | Raise it above max event-arrival lag |

**2. Data-quality expectations (block *invalid* rows before they apply):** expectations attach to the **target streaming table definition** and run on every row.

| Action | Python | SQL | Effect |
|---|---|---|---|
| warn (default) | `@dp.expect` | `EXPECT (...)` | row written, metric logged |
| drop | `@dp.expect_or_drop` | `... ON VIOLATION DROP ROW` | invalid row dropped pre-write |
| fail | `@dp.expect_or_fail` | `... ON VIOLATION FAIL UPDATE` | update fails (the failing run aborts) |
| many at once | `@dp.expect_all` / `_all_or_drop` / `_all_or_fail` | one CONSTRAINT each | granular metrics (collective action is Python-only) |

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import struct

dp.create_streaming_table(
    name="brz_account",
    expect_all_or_drop={                       # gate invalid rows BEFORE AUTO CDC applies
        "valid_key": "accountid IS NOT NULL",
        "valid_seq": "_processing_timestamp IS NOT NULL",
    },
)
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account", keys=["accountid"],
    sequence_by=struct("_processing_timestamp", "accountid"),   # break ties (see incident)
    apply_as_deletes="IsDelete = true", stored_as_scd_type=2,
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account (
  CONSTRAINT valid_key EXPECT (accountid IS NOT NULL)            ON VIOLATION DROP ROW,
  CONSTRAINT valid_seq EXPECT (_processing_timestamp IS NOT NULL) ON VIOLATION FAIL UPDATE
);

CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account) KEYS (accountid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY STRUCT(_processing_timestamp, accountid)
STORED AS SCD TYPE 2;
```

**Apollo Gen2 incident (first person):** My `sequence_by` was `file_modification_time`, but **many rows share one file**, so the sequencing column had multiple updates at the same value for a key — which AUTO CDC does not support, and the per-key winner was undefined. Fix: a **`struct()` sequence** (`struct(file_modification_time, real_per_row_key)`) to restore one distinct update per key per sequence value. Pattern I hold: **warn-in-dev, fail-in-prod** — FAIL = integrity gates (PK, SCD2, CDC), WARN = observability (freshness, schema drift), so I catch silent failures, not just hard ones.

**One-liner:** Two layers — `expect_or_drop`/`expect_or_fail` constraints gate invalid rows before they apply, while `sequence_by` (monotonic, non-NULL, one distinct update per key per value, tie-broken with a `struct()`), correct `keys`, and `apply_as_deletes` keep AUTO CDC from producing *wrong* upserts.

## Category 5.1 — Basic Streaming Operations (Q22–Q24)

### Q22 — Unioning streaming tables in SDP
**Question:** How do you perform union operations between streaming tables in DLT (SDP)?

**Short answer:** In SDP (Spark Declarative Pipelines — the question's "DLT" is the same engine) the idiomatic union is **not** a `UNION` in the query — it is **multiple append flows targeting one streaming table**. `@dp.append_flow` (Python) / `CREATE FLOW ... INSERT INTO` (SQL) lets several streaming sources fan-in to a single target.

**Two ways, and why one wins:**

| Approach | Mechanism | Cost of adding a new source |
|---|---|---|
| `UNION` inside one streaming query | one flow, one checkpoint over the unioned plan | Changes the query plan → forces a **full refresh** (re-reads all sources from scratch) |
| Multiple append flows → one ST (streaming table) | one **independent checkpoint per flow** | Add a new `@dp.append_flow`; existing flows keep their offsets, **no full refresh** |

- **Append flow** = the default flow type for a streaming table; new source rows are appended on each update (Structured Streaming append mode). Any number of append flows can write to one target.
- Each flow is keyed by its **flow name** → that name identifies its checkpoint. Rename a flow and the checkpoint does not carry over (it becomes a brand-new flow); you cannot reuse a flow name in a pipeline because the existing checkpoint won't match the new flow definition.
- **Constraint:** expectations (`@dp.expect`) must be defined on the **target** streaming table (in `create_streaming_table(...)` or the table definition), **not** inside `@dp.append_flow`.
- All source schemas must align with the target (use `BY NAME` in SQL to match by column name).

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

dp.create_streaming_table("customers_us")          # single target ST

@dp.append_flow(target="customers_us")
def from_west():
    return spark.readStream.table("customers_us_west")

@dp.append_flow(target="customers_us")
def from_east():
    return spark.readStream.table("customers_us_east")
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE customers_us;

CREATE FLOW from_west
AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_west);

CREATE FLOW from_east
AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_east);
```

**Approach (what I'd say in the room):** "If the union set is fixed and rebuilds are cheap, a `UNION` in one `@dp.table` is fine. But in production — where new regions/sources arrive over time — I use one append flow per source into a shared streaming table. Each source then has its own checkpoint, so onboarding a new source is purely additive and never triggers a full refresh of the others. For a one-time historical merge I'd use `INSERT INTO ONCE` / `once=True` so the backfill runs once and isn't replayed unless the table is fully refreshed."

**Apollo Gen2 grounding:** Our 211 entities each land in their own STG streaming table, so we didn't union sibling sources there — but the append-flow-over-UNION rule is exactly what I'd reach for if Synapse Link ever split one entity across multiple `replicate/` drop paths: one append flow per path into one STG table, independent checkpoints, zero full-refresh risk.

**One-liner:** In SDP you union by attaching multiple `@dp.append_flow`s to one streaming table rather than using `UNION`, because each flow carries its own checkpoint and adding a source stays incremental instead of forcing a full refresh.

### Q23 — What enables SDP to join two streaming sources, and what happens behind the scenes
**Question:** What enables DLT (SDP) to join two streaming sources — what happens behind the scenes?

**The enabler:** a **watermark on BOTH sides** plus a **time-bounded join condition**. Those two together let the engine bound and evict state; without them a stream-stream join's state grows unbounded → OOM (out-of-memory).

**Behind the scenes (the machinery):**
- The operator is a **symmetric-hash join** (operator name `symmetricHashJoin` in the streaming state-operator metrics). Each incoming row from stream A is buffered in a state store and probed against buffered rows of stream B, and vice-versa — symmetric because either side can arrive first.
- **State stores:** a stream-stream join initializes **four state-store instances per shuffle partition** (vs. one per partition for most stateful operators) — exposed as `numStateStoreInstances` in `StreamingQueryProgress`. This is the concrete "what happens" detail interviewers want.
- **Watermark eviction:** the engine tracks max event-time per input, computes a watermark per stream, then keeps **one global watermark = the *minimum* across streams** (default policy `min`, so the slowest stream gates eviction and you don't drop matchable rows). The **time-interval condition** tells the engine when no further match is possible, so rows past that bound are evicted from state.
- Streams can use **different** watermark thresholds; setting `spark.sql.streaming.multipleWatermarkPolicy=max` follows the fastest stream but **drops** slow-stream data — Databricks recommends using it with caution.
- Supported stream-stream join types: inner, left outer, right outer, full outer, left semi. For outer joins watermarking is mandatory; stream-stream joins only support append output mode.

**Stream-static is different (and cheaper):** joining a stream to a static Delta table is a **stateless** join — no watermark needed. The **latest valid version of the static table is re-read at the start of each micro-batch**, so late-arriving dimension rows are NOT retroactively applied to facts already processed, and the result is non-deterministic if the static side changes between runs.

**PySpark (SDP, stream-stream):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

@dp.table
def impressions_with_clicks():
    impressions = (spark.readStream.table("impressions")
                   .withWatermark("impression_time", "10 seconds"))
    clicks = (spark.readStream.table("clicks")
              .withWatermark("click_time", "3 minutes"))
    return impressions.join(
        clicks,
        expr("""
          impressions.ad_id = clicks.ad_id AND
          click_time BETWEEN impression_time AND impression_time + INTERVAL 3 MINUTES
        """),
        "inner")
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE impressions_with_clicks AS
SELECT i.*, c.click_time
FROM STREAM(impressions) i
  WATERMARK impression_time DELAY OF INTERVAL 10 SECONDS
JOIN STREAM(clicks) c
  WATERMARK click_time DELAY OF INTERVAL 3 MINUTES
ON i.ad_id = c.ad_id
AND c.click_time BETWEEN i.impression_time AND i.impression_time + INTERVAL 3 MINUTES;
```

**Approach:** "First I decide stream-stream vs stream-static. If the right side is a slowly-changing dimension Delta table, I make it a stream-static stateless join — no watermark, low latency, snapshot refreshed per micro-batch. If both sides are genuinely unbounded streams, I add a watermark on each side and a time-bound (`BETWEEN ... + INTERVAL`) so state stays finite. I also enable the RocksDB state store for large joins so state spills to disk instead of heap — and on serverless SDP the state store is managed automatically (RocksDB is the default state provider from Databricks Runtime 17.2)."

**Apollo Gen2 grounding:** Most of my joins are silver enrichments against reference data, which are stream-static — and I lean on the per-micro-batch snapshot semantics: a Dynamics 365 lookup that updates mid-run won't retroactively rewrite already-processed CRM rows, which is the behavior we want for auditability.

**One-liner:** SDP joins two streams via a symmetric-hash join backed by four state-store instances per partition, and what *makes it bounded* is a watermark on both sides plus a time-interval condition that lets the engine evict state once no further match is possible — whereas a stream-static join is stateless and just re-reads the latest Delta snapshot each micro-batch.

### Q24 — How SDP determines where to start in a stream (offsets, checkpointing)
**Question:** How does DLT (SDP) determine where to start processing data in a stream (offset, checkpointing, etc.)?

**The mechanism:** SDP is built on Spark Structured Streaming and **manages the checkpoint for you, one checkpoint per flow**, in an internal location you cannot access. The checkpoint persists three things:

| Checkpoint contents | What it does |
|---|---|
| **Progress / offsets** | which source offsets have already been processed (the "where to start" answer) |
| **Intermediate state** | state across micro-batches for stateful ops (aggregations, joins, dedupe) |
| **Metadata** | streaming-query execution info |

**The decision rule (precise):**
1. **First-ever run of a flow** → start position comes from the **source's starting-offset option**.
   - **Kafka / `read_kafka`:** `startingOffsets` default = **`latest`** for streaming (only new data after start; default is `earliest` for batch). Set `earliest` to read existing data, or a JSON offset map (`-2`=earliest, `-1`=latest) per topic-partition.
   - **Auto Loader / `read_files`:** `cloudFiles.includeExistingFiles` (default **`true`** → ingests files already in the path on first run, then continues incrementally; set `false` to ingest only files created after stream start). Note: Auto Loader always performs a full directory listing on the first run even when `includeExistingFiles=false` — the flag controls only whether pre-existing files are *ingested*, not whether listing happens.
   - **Delta source:** optional `startingVersion` / `startingTimestamp`; otherwise from the current table version.
2. **Every subsequent run** → SDP **ignores the starting-offset option and resumes from the checkpoint**. This is the gotcha interviewers test: changing `startingOffsets` after the first run does nothing. Newly discovered Kafka partitions mid-stream start at **earliest**.
3. **Exactly-once:** checkpointed offsets + idempotent Delta sink = each record processed once across failures/restarts.

**When the checkpoint is the problem — recovery (SDP-specific):** Some changes make a streaming query unable to safely resume from its checkpoint — e.g., changing aggregation grouping keys or aggregate functions, adding/removing an aggregation, changing join keys or join types, adding/removing a join, or changing deduplication columns. The flow then hard-fails and cannot progress. Three recovery options:

| Option | Data loss | Note |
|---|---|---|
| **Full refresh** | possible (if source no longer retains history) | resets the table + wipes existing data, then rebuilds; lets you change logic |
| **Full refresh + backup/backfill** | none | expensive; last resort |
| **Selective checkpoint reset** | none if reset carefully | `reset_checkpoint_selection` in the pipelines REST API `updates` request; pass fully-qualified `catalog.schema.flow_name` |

- Flow name = checkpoint identity. Default flow name = fully-qualified target table (`catalog.schema.table`); a custom `flow_name` (or `name`) overrides it, in which case the fully-qualified flow name is `catalog.schema.flow_name`. Passing a simple (non-qualified) name to `reset_checkpoint_selection` fails the update with an `IllegalArgumentException`. For a stream-stream join/union recovery you must reset **all** participating source flows.

**PySpark (SDP) — first-run start position is set on the source, not a checkpoint path:**
```python
from pyspark import pipelines as dp

@dp.table  # SDP owns the checkpoint internally — no .option("checkpointLocation", ...)
def kafka_bronze():
    return (spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", "...:9092")
            .option("subscribe", "orders")
            .option("startingOffsets", "earliest")   # honored ONLY on first run
            .load())
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE kafka_bronze AS
SELECT * FROM STREAM read_kafka(
  bootstrapServers => '...:9092',
  subscribe        => 'orders',
  startingOffsets  => 'earliest'   -- first run only; restarts use the checkpoint
);
```

**Approach:** "I never hand-manage `checkpointLocation` in SDP — the engine keeps one checkpoint per flow internally. So 'where does it start?' has two cases: first run = the source's `startingOffsets` / `includeExistingFiles` setting; every run after = the checkpoint, which is why flipping `startingOffsets` later is a no-op. If I genuinely need to rewind, I do a selective `reset_checkpoint_selection` on the specific fully-qualified flow name to preserve existing table data, and reserve full refresh for when I'm also changing stateful logic."

**Apollo Gen2 grounding:** Our STG streaming tables read Synapse Link CSV drops via Auto Loader, so first-run start was governed by `includeExistingFiles=true` to pull the existing `incoming/` backlog, then incremental from the per-flow checkpoint. Because each of the 211 STG tables is its own flow with its own checkpoint, when one entity's logic changed we could reset just that flow rather than full-refreshing all 211 — exactly the selective-checkpoint-reset path.

**One-liner:** SDP keeps one Structured-Streaming checkpoint per flow that records processed offsets, state, and metadata; the first run starts from the source's `startingOffsets`/`includeExistingFiles` setting and every run after resumes from that checkpoint — so to rewind you do a selective `reset_checkpoint_selection` on the fully-qualified flow name, not a change to the offset option.

## Category 5.2 — Advanced Streaming Joins & Watermarks (Q25–Q27)

### Q25 — Bounding stream-stream left-join state under large arrival gaps
**Question:** When joining two streaming tables using left joins, how do you handle scenarios where data arrives at different times with large gaps (e.g., a 12-hour delay) without causing out-of-memory issues due to large watermark settings?

**The core mechanism (verified against current SDP docs):**
- A stream-stream join keeps **both** sides buffered in state until the engine can prove no future row can match. Two things let it evict that state:
  1. A **watermark on BOTH sides** (`WATERMARK ... DELAY OF INTERVAL` in SQL / `.withWatermark()` in PySpark). For an **outer/left join, a watermark is MANDATORY**, not optional.
  2. A **time-bounded join condition** — a range predicate on the two event-time columns, using the same fields the watermarks are defined on. This interval is what tells the engine "after this point, no further match is possible," so it can drop state. Omit either the watermarks OR the time bound and **state grows without bound → OOM**.
- The trap in the question: people try to absorb a 12-hour gap by setting a **12-hour watermark**. That is the wrong knob. A 12-hour watermark forces the engine to retain ~12 hours of BOTH streams' join keys in the state store — that is exactly what blows memory. Stream-stream joins also allocate **four state-store instances per partition** (confirmed in the `numStateStoreInstances` metric docs), so the blow-up is multiplied.

**Approach (how I'd actually solve a 12-hour skew):**
- **Don't widen the watermark to swallow the gap.** Keep the watermark at a realistic lateness tolerance (minutes/low hours) and set the **time-bound join window** to the real business horizon. The two are separate dials: watermark = "how late a row may arrive," join interval = "how far apart two matching rows may be."
- **If the late side is a slowly-changing dimension, don't stream-stream join it at all** — that is the wrong tool. Make it a **stream-static / stream-snapshot join** (stateless, no watermark, low memory) or a `dp.create_auto_cdc_flow` SCD target you join against. A 12-hour-delayed dimension does not belong in a symmetric-hash stream-stream join.
- **Watch the global watermark.** With two watermarks the engine takes the **minimum** of the two as the global watermark (default `spark.sql.streaming.multipleWatermarkPolicy = min`). If one stream stalls for 12 hours, the **min policy holds the whole join's watermark back**, state piles up, and output is delayed. That is correct (safe) but memory-heavy. Setting the policy to `max` advances with the fast stream but then **drops the slow stream's data** — only acceptable if losing the laggard is tolerable.
- **Monitor the state, don't guess:** check `stateOperators.numRowsTotal`, `memoryUsedBytes`, and `numStateStoreInstances` in the streaming progress / pipeline event log to confirm state is actually being evicted.

**PySpark (SDP — left/outer join with watermark on both sides + time bound):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("impression_clicks")

@dp.append_flow(target="impression_clicks")
def join_impressions_and_clicks():
    impressions = (spark.readStream.table("ad_impressions")
                   .withWatermark("impression_time", "30 minutes"))   # lateness tolerance, NOT the gap
    clicks = (spark.readStream.table("user_clicks")
              .withWatermark("click_time", "30 minutes"))
    return impressions.alias("imp").join(
        clicks.alias("clk"),
        expr("""
            imp.ad_id = clk.ad_id
            AND clk.click_time BETWEEN imp.impression_time
                                   AND imp.impression_time + INTERVAL 3 MINUTES
        """),                                                          # time-bound = match horizon
        "leftOuter"
    )
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE impression_clicks AS
SELECT imp.ad_id, imp.impression_time, clk.click_time
FROM STREAM(ad_impressions)
       WATERMARK impression_time DELAY OF INTERVAL 30 MINUTES imp
LEFT JOIN STREAM(user_clicks)
       WATERMARK click_time DELAY OF INTERVAL 30 MINUTES clk
  ON imp.ad_id = clk.ad_id
 AND clk.click_time BETWEEN imp.impression_time
                        AND imp.impression_time + INTERVAL 3 MINUTES;
```

**Apollo Gen2 grounding (first person):** In our Synapse-Link feeds the join-key skew came from entities landing in different files at different times. We deliberately did **not** stream-stream-join the slow side; the dimension-like entities were materialized as SCD2 bronze via `create_auto_cdc_flow` and joined as static/snapshot downstream, so the only true stream-stream joins kept a tight watermark and never had to buffer a half-day of state.

**One-liner:** I bound state with a watermark on both sides plus a time-bounded join condition, and I size the watermark to real lateness — not to the gap — because absorbing a 12-hour skew belongs in the join interval (or a stateless stream-static join), not in an oversized watermark that OOMs the state store.

### Q26 — Late-arriving matches and the null rows from a left outer join
**Question:** In streaming pipelines, when left outer joins produce null records due to late-arriving data, how do you ensure these null records get corrected when matching data eventually arrives?

**The hard truth first (verified):**
- Stream-stream joins support **append output mode only**. In append mode a row, once written, is **final — it cannot be retracted or updated**.
- For an outer join, an **unmatched left row is NOT emitted immediately**. The engine holds it in state and only writes the null-filled row **after the lateness threshold passes** and it has proven no match can still arrive (per the "Watermarks and output modes for stream-stream joins" docs).
- Consequence: **a null is only ever written when the engine already gave up waiting.** So there is no "null now, correct it later" in a single append-mode join — by construction, if the match arrives **within** the watermark window you get a matched row and **no null is ever written**; if it arrives **after** the window, the null was already emitted and the late match is dropped. **You cannot retroactively patch the null in the same join.**

**Approach — so how do you "correct" it? You design so the correction never needs to happen, or you push it to a layer that allows updates:**

| Strategy | Mechanism | When to use |
|---|---|---|
| **Right-size the watermark/join interval** | Make the lateness threshold ≥ the realistic max delay of the right side, so the match lands *before* the null is emitted. The null then never occurs. | Default fix. Bounded, known lateness. |
| **Push correction into a CDC/MV layer** | Land the join result, then resolve nulls downstream with `create_auto_cdc_flow` (SCD1 upsert) or a `@dp.materialized_view` that re-joins against the now-complete dimension. MVs/CDC targets **can update rows**; the append-only join cannot. | Unbounded or very long delays (the 12-hour case). |
| **Stream-static / snapshot join instead** | If the "late" side is a dimension, join the stream against the static Delta snapshot — no nulls-from-lateness semantics at all. | Right side is slowly-changing reference data. |
| **Backfill / full refresh** | Reprocess from bronze (full history retained) once late data lands, rebuilding the gold join. | Correctness-critical, batch-tolerant. |

**Key reasoning to say out loud:** the null is not a bug you fix in place — it is the engine's *final answer* under append semantics. Either you widen the time the engine waits (watermark) so the match arrives in time, or you move the join to a layer (MV / `create_auto_cdc_flow` SCD1) whose update semantics let a later row overwrite the earlier null.

**PySpark (correction layer: append-only join → CDC upsert that overwrites nulls):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

# Layer 1: append-only left join (may emit null-filled rows after the lateness threshold)
dp.create_streaming_table("orders_enriched_raw")

@dp.append_flow(target="orders_enriched_raw")
def join_orders_customers():
    orders = spark.readStream.table("orders").withWatermark("order_ts", "2 hours")
    cust   = spark.readStream.table("customers").withWatermark("cust_ts", "2 hours")
    return orders.alias("o").join(cust.alias("c"),
        expr("o.cust_id = c.cust_id AND c.cust_ts BETWEEN o.order_ts - INTERVAL 2 HOURS AND o.order_ts + INTERVAL 2 HOURS"),
        "leftOuter")

# Layer 2: SCD1 upsert keyed by order_id — a later, fully-matched row OVERWRITES the earlier null row
dp.create_streaming_table("orders_enriched")
dp.create_auto_cdc_flow(
    target="orders_enriched",
    source="orders_enriched_raw",
    keys=["order_id"],
    sequence_by="order_ts",          # latest version wins
    stored_as_scd_type=1,
)
```

**SQL equivalent (correction layer = AUTO CDC SCD1):**
```sql
CREATE OR REFRESH STREAMING TABLE orders_enriched;

CREATE FLOW fix_nulls AS AUTO CDC INTO orders_enriched
FROM STREAM(orders_enriched_raw)
KEYS (order_id)
SEQUENCE BY order_ts
STORED AS SCD TYPE 1;
```

**Apollo Gen2 grounding (first person):** I hit the mutable-source version of this — a streaming table needs an append-only source, and when an upstream row mutated, the append-only flow couldn't "correct" it in place. The fix was the same shape as above: keep the streaming/join layer append-only, then resolve corrections in a `create_auto_cdc_flow` SCD layer keyed by the entity PK with `sequence_by`, so the latest complete version overwrites the earlier partial/null one. We never tried to mutate an append-mode output.

**One-liner:** An append-mode left join writes the null only after it has stopped waiting, so it can't be patched in place — I either size the watermark so the match arrives before the null is emitted, or I land the join append-only and resolve nulls in a downstream SCD1 `create_auto_cdc_flow` / materialized view whose update semantics let the complete row overwrite the earlier null.

### Q27 — Effect of window length, and data arriving outside the watermark
**Question:** What is the effect of using different window lengths in streaming aggregations? What happens if data arrives outside the defined watermark window?

**Window length — two separate dials (window vs watermark):**
- **Window length** = the size of the time bucket you aggregate over (`window(event_time, '1 minute')`). **Watermark** = how long the engine waits for late rows before finalizing/evicting that window. They are independent; people conflate them.
- Effect of window length:

| Window length | Effect on result | Effect on state/memory | Effect on latency |
|---|---|---|---|
| **Short** (e.g. 1 min) | Fine-grained, more output rows | Many concurrent windows, each small; high row count | Results finalize sooner (window end reached quickly) |
| **Long** (e.g. 1 hour) | Coarse, fewer rows | Fewer windows but each holds more accumulated state | Results delayed until the long window closes + watermark passes |

- **Window types** (all need a watermark to bound state):
  - **Tumbling** — fixed, non-overlapping; each row in exactly one window.
  - **Sliding** — fixed size, overlapping by `slideDuration` (≤ window length); **one row lands in multiple windows → multiplies state**, so memory cost is higher than tumbling for the same window length.
  - **Session** — variable size; opens on a row, closes after a `gapDuration` of silence.

**A window finalizes when:** the latest observed event time reaches `window_end + watermark`. At that point no new data is accepted for the window, the aggregate is emitted (in append mode) and **the window's state is dropped**. So: longer window OR longer watermark = state held longer = more memory + higher latency; that is the throughput/lateness tradeoff.

**What happens to data outside the watermark window (verified):**
- A row whose event time is **older than `(max_event_time_seen − watermark)`** is **too late**: its window's state has already been dropped, so the row is **dropped from the aggregation** — it does **not** update the already-emitted result.
- Important nuance from the docs: the guarantee is one-directional. Rows **within** the threshold are **always** processed. Rows **outside** the threshold **might still** be processed, but it is **not guaranteed** — so you must treat anything past the watermark as "may silently vanish."
- It is **silent** — no error, no failure. The only signal is the metric **`stateOperators.numRowsDroppedByWatermark`** in the streaming progress / pipeline event log. Per the metric docs this counts **post-aggregation** rows for streaming aggregations and is **not precise** — it is an indication that late data is being dropped, not an exact input-row count.
- **Output mode interaction:** `append` drops old window state after the threshold (bounded memory, late data lost); `complete` keeps **all** window state and rewrites the target each trigger (no drop, no memory bound — only viable for small key spaces). In SDP, append + watermark is the norm precisely to bound memory.

**Approach (operationalizing it — mirrors how I'd test it):** because the drop is silent, late-data loss is an **observability concern, not a hard gate**. I'd surface `numRowsDroppedByWatermark` as a **WARN** signal (freshness/drift class) rather than fail the pipeline, and only fail on integrity violations — the same warn-in-dev/fail-in-prod split we used for SIT.

**PySpark (SDP — tumbling window + watermark):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window, sum as _sum

@dp.table
def revenue_per_minute():
    return (spark.readStream.table("orders")
            .withWatermark("event_time", "3 minutes")              # late tolerance
            .groupBy(window("event_time", "1 minute"), "region")   # window length
            .agg(_sum("amount").alias("revenue")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE revenue_per_minute AS
SELECT window(event_time, '1 minute') AS time_window, region, SUM(amount) AS revenue
FROM STREAM(orders)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY window(event_time, '1 minute'), region;
```

**Apollo Gen2 grounding (first person):** This is the "silent failures beat loud failures" principle in practice — a row past the watermark just disappears with no exception, so I never relied on the absence of errors to mean correctness; I watched `numRowsDroppedByWatermark` and treated late-drop as an observability WARN, the same way we classified freshness and schema-drift as warn-class rather than the PK/SCD2/CDC integrity gates we set to FAIL.

**One-liner:** Window length sets the aggregation granularity (and longer windows or sliding overlap cost more state and latency), while the watermark sets how long each window waits before finalizing — and any row arriving past `max_event_time − watermark` is silently dropped from the aggregate, observable only via the (imprecise, post-aggregation) `numRowsDroppedByWatermark` metric.

## Category 6 — SQL Implementation & Aggregations (Q28–Q31)

### Q28 — Where complex SQL logic lives in SDP
**Question:** How do you implement complex SQL logic in DLT? Where exactly do you write the SQL logic in the DLT framework syntax? (DLT = SDP, Spark Declarative Pipelines / Lakeflow Declarative Pipelines)

**Core idea — the SQL goes in the `AS SELECT` body of a dataset definition.** SDP (Spark Declarative Pipelines) is declarative: you do **not** write imperative `INSERT`/`MERGE`. You declare a dataset (MV / streaming table / view) and put your logic in the query that defines it. The engine evaluates every definition across all source files, builds a dataflow graph, then orchestrates execution order itself.

**The places SQL logic can live (pick by purpose):**

| Object | SDP keyword / decorator | When to put logic here |
|---|---|---|
| MV (materialized view) | `CREATE OR REFRESH MATERIALIZED VIEW` / `@dp.materialized_view` | Complex transforms, joins, aggregations; results cached + (best-effort) incrementally refreshed on serverless; **batch-correct** |
| Streaming table | `CREATE OR REFRESH STREAMING TABLE` / `@dp.table` | Append-only / low-latency ingestion + row-level transforms; each row processed once |
| Temporary view | `CREATE TEMPORARY VIEW` / `@dp.temporary_view` | Pipeline-scoped intermediate step; **no storage cost**, not in catalog — ideal for breaking up big logic |
| Persisted view | `CREATE VIEW` (pipelines) | Standard view recomputed on read; usable only inside the defining pipeline (for cross-pipeline reuse, materialize as an MV) |

- The `STREAM` keyword in the `FROM` clause (`FROM STREAM(src)` or `FROM STREAM src`) marks a source as read with streaming semantics; omit it for batch (MV) semantics. **Do not** use `STREAM` when defining a materialized view.
- Data-quality logic is also "SQL logic" here — declared inline as a `CONSTRAINT <name> EXPECT (<expr>) ON VIOLATION DROP ROW | FAIL UPDATE`. (Note: an MV that carries an expectation can still be incrementally refreshed, with the exceptions documented for `DROP` expectations over `NOT NULL` columns.)
- Reference other pipeline datasets by name via `spark.read.table("name")` / `spark.readStream.table("name")`. The legacy `LIVE.` schema prefix and `dlt.read*` helpers still parse but are superseded — just reference by name.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

@dp.temporary_view()                          # intermediate logic, no storage
def orders_clean():
    return spark.read.table("orders_bronze").where("amount > 0")

@dp.materialized_view()                        # complex join/agg lands in an MV (batch read)
def orders_enriched():
    o = spark.read.table("orders_clean")
    c = spark.read.table("customers")
    return o.join(c, "customer_id").selectExpr(
        "customer_id", "state", "amount", "cast(order_ts as date) as order_date")
```

**SQL equivalent (SDP):**
```sql
CREATE TEMPORARY VIEW orders_clean AS
SELECT * FROM orders_bronze WHERE amount > 0;     -- batch read; this view feeds a batch MV

CREATE OR REFRESH MATERIALIZED VIEW orders_enriched (
  CONSTRAINT valid_amt EXPECT (amount > 0) ON VIOLATION DROP ROW
) AS
SELECT o.customer_id, c.state, o.amount, CAST(o.order_ts AS DATE) AS order_date
FROM orders_clean o JOIN customers c ON o.customer_id = c.customer_id;
```

**One-liner:** In SDP you never write procedural SQL — the logic goes in the `AS SELECT` body of a `CREATE OR REFRESH MATERIALIZED VIEW` (or streaming table / temporary view), and the engine wires up execution order from the dataflow graph.

### Q29 — Running a 1000+ line SQL query inside SDP
**Question:** If you have a very large SQL query (1000+ lines) that needs to be applied to source data in DLT, how do you implement and execute this within the Spark context?

**Approach — decompose the monolith into a DAG of small datasets; do not paste one 1000-line query.** SDP is built to fan one huge query out into many named datasets and re-assemble them via the dataflow graph. This is faster (each node is independently optimized + parallelized), debuggable (you can inspect each node in the pipeline graph), and re-runnable (a transient failure retries at the most granular level — Spark task, then flow, then the whole pipeline — not the whole monolith).

**Decomposition recipe:**
- **Break CTEs / sub-queries into `CREATE TEMPORARY VIEW`s** — each former CTE becomes a named, pipeline-scoped view. Zero storage cost, not added to the catalog, and references resolve to the temp view inside the pipeline.
- **Promote heavy/reused stages to MVs** so they materialize once and are (best-effort) incrementally refreshed on serverless instead of recomputed.
- **Final result = one MV** that selects from the chain. SDP topologically sorts and parallelizes the whole graph automatically.
- **Multiple source files allowed:** SDP evaluates dataset definitions across *all* source files in the pipeline before running anything — so a 1000-line query can be split across several `.sql`/`.py` files for readability.
- **`SELECT`-order ≠ execution-order:** the order statements appear defines code-evaluation order only; the engine decides actual run order from dependencies.

**Two SDP-specific escape hatches when "SQL" alone can't express it:**
- **Python UDFs callable from SDP SQL** — define the UDF in a Python source file first, then call it in the SQL `SELECT`.
- **REPLACE WHERE flows (Beta, PREVIEW channel)** — declared via the inline `FLOW REPLACE WHERE <predicate> BY NAME` clause on a `CREATE STREAMING TABLE` (or `replace_where=` in Python). They recompute/overwrite only the predicate-matched slice of a streaming-table target — built for incremental *batch* processing of late-arriving data, selective reprocessing, and backfills without streaming semantics, not as a generic large-join helper.

```sql
-- file 1: stage the heavy sub-queries as temp views
CREATE TEMPORARY VIEW stg_a AS SELECT ... FROM STREAM(src_a) WHERE ...;   -- ~200 lines
CREATE TEMPORARY VIEW stg_b AS SELECT ... FROM src_b GROUP BY ...;        -- ~300 lines

-- file 2: assemble; engine parallelizes stg_a/stg_b, then builds the MV
CREATE OR REFRESH MATERIALIZED VIEW final_report AS
SELECT a.*, b.metric FROM stg_a a JOIN stg_b b USING (key);
```

```python
from pyspark import pipelines as dp

@dp.temporary_view()
def stg_a(): return spark.read.table("src_a").where("...")   # chunk 1

@dp.temporary_view()
def stg_b(): return spark.read.table("src_b").groupBy("key").sum("amount")  # chunk 2

@dp.materialized_view()
def final_report():
    return spark.read.table("stg_a").join(spark.read.table("stg_b"), "key")
```

**Apollo Gen2 first-person note:** I batch-generate ~200 entities' pipeline code from one Python script (generated code is an artifact, not the source of truth — I edit the config and regenerate). For wide entity logic I split definitions across files and lean on temporary views so the pipeline graph stays inspectable rather than one opaque query.

**One-liner:** I never run a 1000-line monolith in SDP — I decompose it into a DAG of named temporary views and MVs (optionally across multiple source files, with Python UDFs for the parts SQL can't express), and let the engine optimize, parallelize, and retry each node independently.

### Q30 — Aggregations in SDP: which object type
**Question:** How can aggregations be performed in a DLT pipeline? When performing SQL-based aggregations in DLT, which object type should be used — a view, table (streaming table), or materialized view?

**Answer: use a materialized view (MV) for aggregations.** This is the Databricks-recommended default and the only object that returns a *batch-correct* result over the whole dataset.

**Object comparison for aggregation:**

| Object | Correct over whole dataset? | Cost behavior | Verdict |
|---|---|---|---|
| MV (materialized view) | **Yes — equivalent to a batch query** | Pre-computed; on serverless, best-effort incremental refresh reprocessing only changed data | ✅ **Recommended default** |
| Streaming table | Only with watermark + windowing; stateful, sees each row once | Incremental but **not** a full-dataset aggregate | ⚠️ Only for windowed/append-only streaming aggregates |
| `CREATE VIEW` | Correct but recomputes **from scratch on every query** | No caching → slow & expensive at scale | ❌ Not for heavy aggregation |

**Why MV is correct:** Databricks states a stateful streaming aggregate "should not be used to calculate statistics over an entire dataset" — use an MV. An MV guarantees a result *equivalent to recomputing the aggregate with a batch query*, even for late/out-of-order data. On serverless the engine makes a best-effort incremental refresh (reprocessing only changed data rather than the full result); whether a given aggregate query incrementalizes depends on the query — the engine reports the technique chosen (`GROUP_AGGREGATE`, `GENERIC_AGGREGATE`, `FULL_RECOMPUTE`, etc.) in the `planning_information` event log. On classic (non-serverless) compute an MV is always fully recomputed.

**MV aggregation gotchas (verified):**
- Non-column-reference expressions **require an alias**: `SUM(col2) AS sum_col2` is required; bare `SUM(col2)` is rejected. A plain column reference does not need an alias.
- `SUM` over a nullable column returns **0, not NULL**, when the last non-null value for a group is removed.
- MVs don't support `OPTIMIZE`/`VACUUM` (maintenance is automatic), identity/generated/default columns, or rename. `NOT NULL` must be specified explicitly alongside `PRIMARY KEY`.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import count, sum as _sum, max as _max

@dp.materialized_view()
def daily_orders_by_state():
    return (spark.read.table("orders_enriched")
              .groupBy("state", "order_date")
              .agg(count("*").alias("order_count"),
                   _sum("amount").alias("total_amt"),
                   _max("amount").alias("max_amt")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH MATERIALIZED VIEW daily_orders_by_state AS
SELECT state, order_date,
       COUNT(*)   AS order_count,
       SUM(amount) AS total_amt,
       MAX(amount) AS max_amt
FROM orders_enriched
GROUP BY state, order_date;
```

**One-liner:** Aggregations belong in a materialized view — it's the only SDP object that returns a batch-correct, full-dataset result while still refreshing incrementally on serverless; streaming tables only do windowed/watermarked aggregates and plain views recompute on every read.

### Q31 — Full-dataset aggregation when the source feeds via auto-CDC
**Question:** When using streaming tables with auto-CDC for aggregation operations (MAX, MIN, COUNT, SUM), how do you ensure aggregation operations work on the complete dataset rather than just incremental records?

**Approach — separate the two layers: AUTO CDC builds the *current full state*, then aggregate that with a materialized view.** The trap is trying to aggregate inside the streaming/CDC layer, where a stateful streaming aggregate only ever sees the *incremental* batch and (without a watermark) builds unbounded state. The fix is architectural, not a flag.

**Why a streaming aggregate sees only increments:**
- A streaming table processes **each input row exactly once**; a stateful aggregate on it tracks state across micro-batches and emits per-batch deltas, not a full-dataset answer.
- Databricks is explicit: *"You should not use a stateful aggregate to calculate statistics over an entire dataset — use materialized views for incremental aggregate calculation on an entire dataset."*
- Without a `WATERMARK`, state grows unbounded → OOM; *with* a watermark you get correct **windowed** results but still not a single whole-dataset total.

**The correct two-layer pattern (this is what I run in Apollo Gen2):**

| Layer | SDP object | Role |
|---|---|---|
| Silver | streaming table + `dp.create_auto_cdc_flow` | AUTO CDC folds inserts/updates/deletes into the **current** SCD1/SCD2 state |
| Gold | **materialized view** | Aggregates over that full current state → `MAX/MIN/COUNT/SUM` are batch-correct and refresh incrementally on serverless |

- **SCD1 target:** the table holds one current row per key (no `__START_AT`/`__END_AT` columns) — the MV aggregates it directly.
- **SCD2 target:** filter to current rows first — `WHERE __END_AT IS NULL` — then aggregate, so you don't double-count historical versions. (SCD2 propagates the `sequence_by` values into the `__START_AT` / `__END_AT` columns.)
- An MV over the CDC target gives a result equivalent to a full batch recompute — that is the "complete dataset" guarantee — while best-effort incrementally refreshing on serverless.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum as _sum, max as _max, count

# Silver: AUTO CDC -> current SCD2 state (NOT where you aggregate)
dp.create_streaming_table("orders_scd2")
dp.create_auto_cdc_flow(
    target="orders_scd2", source="orders_cdc",
    keys=["order_id"], sequence_by="op_ts",
    apply_as_deletes="op = 'DELETE'", stored_as_scd_type="2")

# Gold: MV aggregates the COMPLETE current dataset
@dp.materialized_view()
def orders_rollup():
    return (spark.read.table("orders_scd2")
              .where("__END_AT IS NULL")               # current rows only (SCD2)
              .groupBy("state")
              .agg(count("*").alias("cnt"),
                   _sum("amount").alias("total_amt"),
                   _max("amount").alias("max_amt")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE orders_scd2;

CREATE FLOW orders_cdc_flow AS AUTO CDC INTO orders_scd2
FROM STREAM(orders_cdc)
KEYS (order_id)
APPLY AS DELETE WHEN op = 'DELETE'
SEQUENCE BY op_ts
STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW orders_rollup AS
SELECT state, COUNT(*) AS cnt, SUM(amount) AS total_amt, MAX(amount) AS max_amt
FROM orders_scd2
WHERE __END_AT IS NULL          -- aggregate the complete CURRENT state, not CDC deltas
GROUP BY state;
```

**If you truly must aggregate in the streaming layer** (low-latency windowed roll-ups), it has to be a **windowed** aggregate with a watermark, and even then it answers per-window, not whole-dataset:
```sql
CREATE OR REFRESH STREAMING TABLE per_min_counts AS
SELECT window(event_time, '1 minute') AS w, state, COUNT(*) AS cnt
FROM STREAM(events) WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY w, state;   -- incremental only because of the watermark
```

**One-liner:** Let `create_auto_cdc_flow` build the current full state in a streaming table, then put `MAX/MIN/COUNT/SUM` in a materialized view over that table (filtering `__END_AT IS NULL` for SCD2) — the MV gives a batch-correct whole-dataset answer, whereas aggregating inside the CDC/streaming layer only ever sees the incremental batch.

## Category 7 — Data Quality & Constraints (Q32–Q35)

### Q32 — Applying data quality expectations (types + where DQ errors surface)
**Question:** How do you apply data quality expectations? Explain in detail with types and where DQ errors can be checked.

**What an expectation is**
- An **expectation** is an optional clause on a SDP (Spark Declarative Pipelines / Lakeflow) dataset — `@dp.table` (streaming table), `@dp.materialized_view` (MV — a pre-computed query result), or `@dp.temporary_view` — that runs a **boolean SQL expression on every row** and reacts per a chosen violation policy.
- Unlike a Delta `CHECK` constraint (which hard-rejects writes), expectations are **flexible**: you choose warn / drop / fail.

**The three types (verified — current SDP API)**

| Action | Python | SQL | Behavior on a bad row |
|---|---|---|---|
| **warn** (default) | `@dp.expect` | `EXPECT (...)` | Bad row is still **written** to the target; only counted in metrics |
| **drop** | `@dp.expect_or_drop` | `EXPECT (...) ON VIOLATION DROP ROW` | Bad row dropped before write; drop count logged alongside other dataset metrics |
| **fail** | `@dp.expect_or_fail` | `EXPECT (...) ON VIOLATION FAIL UPDATE` | Update stops on the first bad row; if it's a table update the transaction is **atomically rolled back**; manual intervention required before reprocessing |

> Note: a fail affects only the offending flow — if a pipeline has multiple parallel flows, one flow failing does NOT fail the others (verified).

**Grouping (Python only):** `@dp.expect_all`, `@dp.expect_all_or_drop`, `@dp.expect_all_or_fail` take a dict `{name: constraint}` and apply one collective action — reusable across datasets. SQL allows multiple `CONSTRAINT` clauses but no collective grouping (verified).

**Constraint rules:** must be a valid SQL boolean expression evaluated per row.

**PySpark example**
```python
from pyspark import pipelines as dp

@dp.table
@dp.expect("valid_customer_age", "age BETWEEN 0 AND 120")            # warn
@dp.expect_or_drop("non_null_pk", "customer_id IS NOT NULL")        # drop
@dp.expect_or_fail("non_negative_price", "price >= 0")             # fail
def customers():
    return spark.readStream.table("catalog.raw.customers")
```

**SQL equivalent**
```sql
CREATE OR REFRESH STREAMING TABLE customers(
  CONSTRAINT valid_customer_age  EXPECT (age BETWEEN 0 AND 120),
  CONSTRAINT non_null_pk         EXPECT (customer_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT non_negative_price  EXPECT (price >= 0)              ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM(catalog.raw.customers);
```

**Where DQ errors / metrics can be checked**
- **Pipeline UI:** Jobs & Pipelines -> click the pipeline -> click the dataset -> **Data quality** tab (right sidebar). Shows tracking metrics for **warn** and **drop** only.
- **Event log (Delta table):** query `event_type = 'flow_progress'`; expectation metrics live under `details:flow_progress.data_quality.expectations` (per-expectation `name`, `dataset`, `passed_records`, `failed_records`), and the dropped-row count lives under `details:flow_progress.data_quality.dropped_records`. By default the event log is a hidden Delta table named `event_log_{pipeline_id}` in the pipeline's default catalog and schema, queried via the `event_log(<pipeline-id>)` table-valued function; only the pipeline's run-as user can query it by default.
- **Caveat:** **fail** does NOT record tracking metrics (the update fails on detection before metrics are recorded) — its evidence is the error message instead (see Q34).

**Apollo Gen2 (my experience):** Across 422 SDP pipelines (211 STG streaming tables + 211 BRZ SCD2), I split expectations by intent in my 17-case SIT suite — **FAIL = integrity gates** (PK present, SCD2 sequence valid, CDC keys), **WARN = observability** (freshness, schema drift). I warn-in-dev, then flip to fail-in-prod once the rule is trusted.

**One-liner:** Expectations are row-level boolean SQL checks on `@dp.table`/`@dp.materialized_view`/`@dp.temporary_view` with three policies — warn (default, keeps the row), drop (`expect_or_drop`), fail (`expect_or_fail`, atomic rollback of the failing flow) — and their pass/fail/drop metrics surface in the pipeline UI Data Quality tab (warn + drop only) and the `flow_progress` event-log `data_quality.expectations` object.

### Q33 — Default handling of bad records in the source
**Question:** If bad records are present in the source, how does DLT handle them by default?

**Key clarification first**
- "DLT" = SDP (Spark Declarative Pipelines / Lakeflow); same engine, current name.
- "Default" splits into two distinct questions — **(a)** default with NO expectation, **(b)** default action of an expectation you declared.

**(a) No expectation declared**
- SDP does **no row-level validation**. A "bad" record (wrong value, malformed field) is treated as ordinary data and **written through** to the target. Garbage in -> garbage stored.
- Malformed-at-parse rows are a separate, ingestion-layer concern (e.g., Auto Loader's `_rescued_data` column / `rescuedDataColumn` mode), not an expectations concern.

**(b) Expectation declared but action unspecified -> warn (default)**

| | Default = warn |
|---|---|
| Row written to target? | **Yes** |
| Counted in metrics? | Yes — `failed_records` in event log + Data Quality tab |
| Pipeline fails? | No |

**Why warn is the default (DE principle):** silent-failure avoidance — SDP keeps the row and *makes the failure visible* rather than dropping data you might need. You opt **up** to drop/fail only where the rule is critical.

**PySpark — bad rows kept and counted**
```python
@dp.table
@dp.expect("valid_timestamp", "event_ts > '2012-01-01'")   # default warn: row stays, just flagged
def events():
    return spark.readStream.table("catalog.raw.events")
```

**SQL equivalent**
```sql
CREATE OR REFRESH STREAMING TABLE events(
  CONSTRAINT valid_timestamp EXPECT (event_ts > '2012-01-01')   -- no ON VIOLATION => warn
) AS SELECT * FROM STREAM(catalog.raw.events);
```

**Approach (how I'd answer the client's scenario framing):**
1. Confirm whether an expectation exists — if not, bad rows land unfiltered; the fix is to add an expectation, not to assume SDP filters.
2. If one exists with no `ON VIOLATION`, it is **warn** — rows are retained, so downstream tables inherit the bad data; check the Data Quality tab to size the problem.
3. Escalate the policy: `expect_or_drop` to keep the clean set flowing, or `expect_or_fail` for integrity-critical columns, or **quarantine** (two flows: drop from main, write rejects to a side streaming table) when I must preserve bad rows for investigation.

**One-liner:** With no expectation SDP writes bad source records straight through, and even a declared expectation defaults to **warn** — the bad row is still written and merely counted — so retention is the default and you must explicitly choose `expect_or_drop` or `expect_or_fail` to filter or fail.

### Q34 — Tracing records when a fail-expectation isn't in the event log
**Question:** If an expectation is defined to fail on bad records but they don't appear in the event log, how can we trace or debug those records?

**Why they're not in the event log (the trap)**
- For `@dp.expect_or_fail` / `ON VIOLATION FAIL UPDATE`, the update **fails on the first violating row and (for a table update) atomically rolls back**. Because `fail` causes the update to fail when an invalid record is detected, SDP **does not record tracking metrics** for that action — verified. So querying `data_quality.expectations` in the event log returns nothing for that constraint. This is expected, not a bug.

**Where the evidence actually lives: the dedicated error message**
- Expectations configured to fail modify the **Spark query plan** of the transformation to track the information needed to detect and report violations, and SDP emits a dedicated structured error condition `EXPECTATION_VIOLATION` (`SQLSTATE 22000`). At full verbosity the message template is:
```console
[EXPECTATION_VIOLATION.VERBOSITY_ALL] Flow '<flowName>' failed to meet the expectation.
Violated expectations: '<expectationsViolated>'.
Input data: '<inputData>'.
Output record: '<outputRecord>'.
Missing input data: <missingInputData>
```
With a concrete row that resolves to, for example: `Violated expectations: 'temperature_in_valid_range'. Input data: '{"id":"TEMP_001","temperature":-500}'. Output record: '{"sensor_id":"TEMP_001","temperature":-500}'. Missing input data: false`. (Other verbosity levels exist: `VERBOSITY_NONE` and `VERBOSITY_OUTPUT`, which omits the input data.)
- Found in: the **failed update's error / event details** in the pipeline UI, and the corresponding `flow_progress` event with `status = FAILED` (one of the documented flow-progress statuses) — not in the `data_quality` metrics object.

**How to trace the full set (not just the first row)**
Convert the hard gate into a **counting/quarantine query** so every bad row is captured before any fail decision:

**PySpark — diagnostic MV that lists violators**
```python
@dp.materialized_view(name="bad_temperature_audit", comment="All rows that violate the temp rule")
def bad_temperature_audit():
    return (spark.read.table("sensor_raw")
            .where("NOT (temperature BETWEEN -50 AND 150)"))   # inverse of the failing predicate
```

**SQL — same audit, plus a quarantine split**
```sql
-- 1) Enumerate every violator (no fail, so it always completes and is queryable)
CREATE OR REFRESH MATERIALIZED VIEW bad_temperature_audit AS
SELECT * FROM sensor_raw WHERE NOT (temperature BETWEEN -50 AND 150);

-- 2) Quarantine pattern: drop bad from main, route bad rows to a side table
CREATE OR REFRESH STREAMING TABLE sensor_clean(
  CONSTRAINT temp_ok EXPECT (temperature BETWEEN -50 AND 150) ON VIOLATION DROP ROW
) AS SELECT * FROM STREAM(sensor_raw);

CREATE OR REFRESH STREAMING TABLE sensor_quarantine
AS SELECT * FROM STREAM(sensor_raw) WHERE NOT (temperature BETWEEN -50 AND 150);
```

**Approach (debug runbook I use):**
1. Read the failed update's `EXPECTATION_VIOLATION.VERBOSITY_ALL` message — it names the violated expectation and dumps the input + output record (the first offender SDP could attribute).
2. Don't expect `data_quality` metrics for a fail — query the event log only for `event_type='flow_progress' AND details:flow_progress.status='FAILED'` to find the flow, and read its `error` field.
3. Build the inverse-predicate audit MV / quarantine table to enumerate **all** violators, fix root cause, then re-run (fail requires manual intervention before reprocessing).

**Apollo Gen2 tie-in:** my hard FAIL gates (PK present, valid SCD2 sequence) are exactly the ones that produce no metrics on trip — so my SIT design always pairs a fail gate with a parallel warn/quarantine query, otherwise the failing row is invisible in the `data_quality` metrics.

**One-liner:** A fail expectation fails the update before tracking metrics are recorded, so the bad row never appears in the event-log `data_quality` object — you trace it via the `EXPECTATION_VIOLATION.VERBOSITY_ALL` error message (it dumps the offending input/output record) and enumerate the full set with an inverse-predicate audit MV or an `expect_or_drop` quarantine table.

### Q35 — Ensuring column uniqueness in a Delta table (no enforced PK)
**Question:** How can you ensure uniqueness of a column in a Delta table? If Delta doesn't enforce primary keys by default, how can uniqueness be guaranteed?

**The core fact (verified)**
- On Databricks, table constraints are either **enforced** or **informational**. **Primary key and foreign key constraints are informational only and NOT enforced** — they aid the optimizer and document intent, but do **not** block duplicate inserts.
- The enforced constraints cover other things: **`NOT NULL`** (can only be enabled on an existing table if no current rows are null; blocks future null inserts) and **`CHECK`** (validated against existing and new rows). Neither enforces uniqueness.
- So uniqueness must be **guaranteed by your pipeline logic**, not by the table.

**Ways to guarantee uniqueness**

| Mechanism | Enforced? | Use |
|---|---|---|
| Informational `PRIMARY KEY` | No | Documents intent + optimizer hints only |
| SDP `expect_or_fail` on a dedup-count query | Yes (in pipeline) | Hard gate: fail update if any dup exists |
| `create_auto_cdc_flow` (AUTO CDC) `keys=[...]` | Yes (upsert) | De-dup by merging on key -> one row per key |
| Pre-write dedup (`dropDuplicates` / `ROW_NUMBER` window) | Yes (logic) | Collapse dups before write |
| `GENERATED ALWAYS AS IDENTITY` | Surrogate uniqueness | Unique `BIGINT` surrogate key (unique and incrementing, but **not guaranteed contiguous**; declaring it **disables concurrent transactions** on the table) |

**1. SDP expectation as a uniqueness gate (the canonical SDP answer)**

The official SDP PK-uniqueness pattern declares this on a temporary view (`@dp.view`) with `@dp.expect_or_fail`; an MV works too. Both are shown:
```python
@dp.view(name="report_pk_tests", comment="Validates primary key uniqueness")
@dp.expect_or_fail("unique_pk", "num_entries = 1")
def validate_pk_uniqueness():
    return (spark.read.table("report")
            .groupBy("pk").count()
            .withColumnRenamed("count", "num_entries"))
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW report_pk_tests(
  CONSTRAINT unique_pk EXPECT (num_entries = 1) ON VIOLATION FAIL UPDATE
) AS SELECT pk, count(*) AS num_entries FROM report GROUP BY pk;
```
Any `pk` with `num_entries > 1` trips the fail and rolls back the update.

**2. Guarantee one-row-per-key at write time via AUTO CDC (how I actually do it in BRZ)**
```python
dp.create_streaming_table("account_bronze")
dp.create_auto_cdc_flow(
    target="account_bronze",
    source="account_stg",
    keys=["accountid"],                      # uniqueness key — upsert collapses dups
    sequence_by="_processing_timestamp",     # latest wins on the key
    stored_as_scd_type=2,
    apply_as_deletes="_change_type = 'delete'",
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"]
)
```
```sql
CREATE OR REFRESH STREAMING TABLE account_bronze;
CREATE FLOW account_cdc AS AUTO CDC INTO account_bronze
FROM STREAM(account_stg)
KEYS (accountid)
SEQUENCE BY _processing_timestamp
STORED AS SCD TYPE 2;
```

**3. Pre-write dedup (when source itself has dups)**
```python
from pyspark.sql.window import Window
from pyspark.sql.functions import row_number, col

w = Window.partitionBy("accountid").orderBy(col("_processing_timestamp").desc())
deduped = src.withColumn("_rn", row_number().over(w)).where("_rn = 1").drop("_rn")
```

**Approach (what I'd tell the client):**
1. State plainly: Delta PKs are informational/not enforced — never rely on the declared `PRIMARY KEY` to stop duplicates.
2. For a streaming table fed by CDC, the **AUTO CDC `keys`** upsert already guarantees one row per key — that's my primary mechanism in Apollo Gen2 bronze.
3. Add an **`expect_or_fail` uniqueness gate** (`num_entries = 1` per key) as a SIT integrity check to *prove* uniqueness in tests.
4. Use `GENERATED ALWAYS AS IDENTITY` only for a synthetic surrogate, knowing it disables concurrent transactions and isn't guaranteed contiguous.

**Apollo Gen2 tie-in:** my hard incident here is **`sequence_by` on `file_modification_time` being too coarse** — when many rows share one CSV file, the CDC upsert can pick an arbitrary row on ties, silently violating per-key uniqueness intent. Fix: a real per-row sequence column, plus a `unique_pk` fail-gate in SIT to catch it.

**One-liner:** Delta PRIMARY KEY constraints are informational and not enforced, so uniqueness is guaranteed by the pipeline — `create_auto_cdc_flow` with `keys=[...]` upserts to one row per key, an `@dp.expect_or_fail("unique_pk", "num_entries = 1")` count check fails the update if any duplicate exists, and `GENERATED ALWAYS AS IDENTITY` supplies a unique (non-contiguous) surrogate when needed.

## Category 8 — Performance Optimization & Tuning (Q36–Q39)

### Q36 — SDP-specific performance tuning techniques implemented
**Question:** What performance tuning techniques specific to DLT (SDP) have you implemented, excluding general techniques like broadcast joins and caching?

**Framing:** SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) is declarative — you do not hand-tune executors or shuffle stages the way you would in a raw Spark job. The pipeline-specific levers are about *how the dataflow graph is shaped, refreshed, and laid out*, not low-level Spark knobs.

**SDP-native techniques (the framework owns these):**
- **Right dataset type per layer.** `@dp.materialized_view` (MV — cached result, incrementally refreshed on serverless when possible, otherwise fully recomputed) vs `@dp.table` (streaming table — each record processed exactly once, assuming an append-only source). Picking streaming for incremental ingest avoids recomputing the whole table every run.
- **Incremental refresh for MVs.** On serverless, MVs attempt an incremental refresh (processing only upstream changes since the last update) and fall back to a full recompute when the query isn't incrementally supported or the compute is classic. Databricks runs a cost analysis and picks the cheaper of incremental vs full each update. Keeping aggregation queries simple and deterministic (no non-deterministic functions like `current_timestamp()`, no non-deterministic UDFs) is the single biggest cost lever — it keeps the refresh on the delta-only path instead of forcing `FULL_RECOMPUTE`.
- **Liquid clustering via `CLUSTER BY` / `CLUSTER BY AUTO`** instead of `PARTITIONED BY` — self-tuning, skew-resistant data layout (see Q39).
- **Enhanced autoscaling + vertical autoscaling (serverless).** Horizontal (worker count) + vertical (cost-efficient instance type chosen to avoid OOM). Standard performance mode for cost-tolerant triggered batch (fewer DBUs, typically 4–6 min startup) vs performance-optimized (faster startup) for latency-sensitive work.
- **Avoid small files.** Match trigger interval to data volume; over-frequent triggers on low-volume sources spray tiny files and degrade reads (each file is a separate metadata lookup + I/O round trip).
- **`track_history_except_column_list` in `create_auto_cdc_flow`.** Not "performance" in the shuffle sense, but it prevents *false SCD2 versions* — if an operational-metadata column changes every run and isn't excluded from history tracking, it generates a new history row each run, exploding table size and slowing reads.
- **Predictive optimization** automatically runs `OPTIMIZE`, `VACUUM`, and `ANALYZE` on Unity Catalog managed tables (including SDP streaming tables and MVs) — I rely on it rather than scheduling manual maintenance.

**From Apollo Gen2 (first person):** Across 211 entities / 422 pipelines (211 STG streaming tables + 211 BRZ SCD2), my biggest SDP-specific wins were: (1) STG as streaming tables (`@dp.table`) so each source file is ingested incrementally rather than reprocessing the full entity each run; (2) BRZ SCD2 via `create_auto_cdc_flow` with a correct `track_history_except_column_list` listing every operational column (`_processing_timestamp`, `_source_file_path`, etc.) so re-runs did not generate phantom SCD2 versions and bloat the history; (3) full-load entities via `create_auto_cdc_from_snapshot_flow` to avoid re-streaming static snapshots.

```python
from pyspark import pipelines as dp

# Streaming table for incremental STG ingest (process each file once)
@dp.table(name="stg_account", cluster_by=["accountid"])
def stg_account():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .load("/Volumes/apollo/incoming/account/"))

dp.create_streaming_table(name="brz_account")
dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",
    keys=["accountid"],
    sequence_by="SinkModifiedOn",
    stored_as_scd_type=2,
    apply_as_deletes="_is_delete = true",
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE stg_account CLUSTER BY (accountid)
AS SELECT * FROM STREAM read_files('/Volumes/apollo/incoming/account/', format => 'csv');

CREATE OR REFRESH STREAMING TABLE brz_account;
CREATE FLOW brz_account_cdc AS AUTO CDC INTO brz_account
FROM STREAM(stg_account)
KEYS (accountid)
APPLY AS DELETE WHEN _is_delete = true
SEQUENCE BY SinkModifiedOn
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (_processing_timestamp, _source_file_path);
```

**One-liner:** "In SDP my tuning is declarative — pick streaming-table vs materialized-view per layer, keep MV queries simple and deterministic so they stay on the incremental-refresh path, lay out with `CLUSTER BY AUTO`, and set `track_history_except_column_list` correctly so SCD2 doesn't explode — then let predictive optimization handle OPTIMIZE/VACUUM/ANALYZE."

### Q37 — Are deletion vectors enabled by default in SDP?
**Question:** Do you need to manually enable deletion vectors in DLT (SDP), or are they enabled by default?

**Definition:** Deletion vectors (DV) are a Delta storage optimization. Instead of rewriting a whole Parquet file when a few rows change, `DELETE`/`UPDATE`/`MERGE` mark rows as soft-deleted in a side file; reads skip them. Faster writes, slightly slower reads (extra metadata check on scan).

**The honest answer — it depends on the workspace setting, not on SDP itself:**
- DV is a **Delta table property** (`delta.enableDeletionVectors`). SDP tables are Delta tables, so they inherit whatever the workspace default produces at create time. As of the 2025-06-26 release, new SDP streaming tables and materialized views follow the workspace deletion-vectors setting.
- The relevant control is the workspace admin setting **Auto-Enable Deletion Vectors** (applies to SQL warehouses + DBR 14.0+). Options: **Default** (varies by region), **New UC managed and Databricks SQL tables** (explicitly includes new MVs and streaming tables), **All new tables**, **Disabled**.
- Databricks is rolling this out so that, once complete, **Default** flips from **Disabled** → **All new tables**. Workspaces still in the introductory period have **Default** behaving as **Disabled**.

| Question | Answer |
|---|---|
| Is DV always on for SDP tables? | No — depends on the workspace **Auto-Enable Deletion Vectors** setting |
| Can SDP/UC managed tables get it automatically? | Yes, if admin picks "New UC managed and Databricks SQL tables" or "All new tables" |
| Can I force it per table? | At create time via `TBLPROPERTIES ('delta.enableDeletionVectors' = true)`. Note: you **cannot** `ALTER` a streaming table or MV to add/remove DV — set it at creation. |
| Delta protocol needed | Reader v3 / Writer v7 (older external readers break) |

**Important interview nuance (don't overstate):** Don't claim "DV is on by default in DLT/SDP." The correct statement is **DV is controlled by a workspace-level Delta default, not by the pipeline engine** — so you verify the workspace setting, and if you need it guaranteed (e.g., GDPR deletes on bronze), you set the table property explicitly at creation.

```python
from pyspark import pipelines as dp

@dp.table(
    name="brz_patient",
    table_properties={"delta.enableDeletionVectors": "true"},
)
def brz_patient():
    return spark.readStream.table("stg_patient")
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_patient
TBLPROPERTIES ('delta.enableDeletionVectors' = true)
AS SELECT * FROM STREAM(stg_patient);
```

**Cleanup behavior to mention:** With DV on, `OPTIMIZE` automatically purges files where more than 5% of records are referenced by deletion vectors — so routine maintenance (predictive optimization on SDP) handles most cleanup. For hard physical removal below that 5% threshold (e.g., GDPR), run `REORG TABLE ... APPLY (PURGE)` then `VACUUM`.

**One-liner:** "Deletion vectors aren't an SDP feature — they're a Delta property governed by the workspace 'Auto-Enable Deletion Vectors' admin setting, and as of mid-2025 new SDP streaming tables and MVs follow it, so I verify that setting and, where I need them guaranteed, set `delta.enableDeletionVectors=true` in the table's `table_properties` at creation (you can't ALTER it on afterward)."

### Q38 — Configuring tuning parameters for a slow/failing join in SDP
**Question:** If a join in DLT (SDP) is taking too long or failing, how can you configure performance tuning parameters within the pipeline?

**Approach (diagnose → choose the right scope → apply):**

**1. Diagnose first.** A join that is slow/failing is almost always (a) a shuffle of a large side that should be broadcast, (b) **data skew** — a few hot keys land on a few tasks (heavy tail in the Spark UI; big gap between median and max task time), or (c) OOM from too-coarse partitioning.

**2. SDP gives you THREE scopes to set Spark properties — pick the narrowest that fixes it:**

| Scope | Where | Use when |
|---|---|---|
| Per dataset/flow | `spark_conf={...}` in the decorator (`@dp.table`, `@dp.materialized_view`) | Only this join needs the tweak — preferred, least blast radius |
| Per compute resource | pipeline JSON `clusters[].spark_conf` | Classic compute, applies to that cluster |
| Whole pipeline | pipeline settings → Advanced → Spark config (`configuration` map in pipeline JSON) | Pipeline-wide default |

**3. Concrete levers (Databricks AQE current defaults — verified):**
- **AQE is ON by default** (`spark.databricks.optimizer.adaptive.enabled=true`) — it already coalesces partitions, flips sort-merge → broadcast at runtime, and does skew-join handling. So first confirm it wasn't disabled.
- **Broadcast a small dimension** with a hint — this is the documented SDP join fix for the dimension-join case (not a "general technique" exclusion).
- **Skew:** AQE skew handling is automatic (split + replicate skewed tasks when a partition exceeds the median × `spark.sql.adaptive.skewJoin.skewedPartitionFactor`, default 5); for severe in-flight skew, **salt** the hot key (append a random bucket suffix, aggregate in two stages). Use **liquid clustering** for skew in the *stored* table.
- **Shuffle partitions:** `spark.sql.shuffle.partitions` defaults to `auto` on serverless (auto-optimized shuffle) and `200` on classic — raise for large joins, lower to avoid tiny-file/overhead on small ones. (Note: for stateful streaming this cannot change across restarts from the same checkpoint.)
- **`spark.databricks.adaptive.autoBroadcastJoinThreshold`** (the Databricks AQE runtime threshold) default `30MB` — raise it so AQE auto-broadcasts a slightly larger dimension at runtime. (Distinct from the static planner threshold `spark.sql.autoBroadcastJoinThreshold`, default `10MB`.)
- **Serverless caveat:** serverless pipelines/notebooks only allow a *restricted* set of Spark properties; cluster-shape properties like `spark.master`, `spark.driver.host`, `spark.jars` aren't settable. Vertical autoscaling already picks bigger instances to dodge OOM.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import broadcast

@dp.materialized_view(
    name="enriched_orders",
    spark_conf={
        "spark.sql.shuffle.partitions": "auto",
        "spark.databricks.adaptive.autoBroadcastJoinThreshold": "100MB",
    },
)
def enriched_orders():
    orders = spark.read.table("orders")
    products = spark.read.table("products")          # small dimension
    return orders.join(broadcast(products), "product_id")
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW enriched_orders AS
SELECT /*+ BROADCAST(p) */ o.*, p.product_name, p.category
FROM orders o JOIN products p ON o.product_id = p.product_id;
```
Pipeline-wide JSON equivalent (under `configuration`):
```json
{ "configuration": { "spark.sql.shuffle.partitions": "auto" } }
```

**One-liner:** "Set Spark properties at the narrowest scope — `spark_conf` in the dataset decorator for just that join — broadcast the small side, lean on AQE's on-by-default skew-join + auto-shuffle, salt or cluster a genuinely skewed key, and remember serverless only allows a restricted Spark-conf set."

### Q39 — Why choose liquid clustering at specific medallion layers
**Question:** Why would you choose optimization techniques such as liquid clustering at certain layers of the medallion architecture?

**Definition:** Liquid clustering (LC) replaces static `PARTITIONED BY` and `ZORDER`. It's self-tuning, skew-resistant, and incremental — it only rewrites the data that needs reorganizing, and you can change clustering keys anytime *without rewriting the whole table*. `CLUSTER BY (cols)` picks keys yourself; `CLUSTER BY AUTO` lets Databricks pick/adapt keys from the observed query workload (requires predictive optimization; intelligent key selection relies on metadata from DBR 15.4 LTS+; supported for MVs and streaming tables in SDP — GA for SDP since 2025-08-25). LC and `PARTITIONED BY` are mutually exclusive.

**Why layer choice matters (the real answer: cluster where reads happen on predictable keys, skip where they don't):**

| Layer | Access pattern | LC decision |
|---|---|---|
| **Bronze (raw/SCD2)** | Append-heavy, ingest-ordered, rarely point-queried by business keys | Often skip explicit LC, or `CLUSTER BY` the CDC/business key if downstream merges filter on it. Don't over-invest. |
| **Silver (cleaned/conformed)** | Joins + merges on business keys; this is where data skew bites | **Strong LC candidate** — cluster by the high-cardinality join/merge key(s) to kill shuffle skew and speed CDC merges |
| **Gold (aggregates/serving)** | Filtered/grouped by a few well-known BI dimensions (date, region, customer) | **Best LC payoff** — cluster by the columns analysts filter on for maximum data-skipping |

**Approach / reasoning:**
- LC's value is **data skipping** — files are organized so a filtered query reads fewer files. That only pays off where queries *filter or join on predictable keys*, i.e. silver/gold, not raw bronze landing.
- LC is **skew-resistant** where static partitioning isn't: partitioning by an uneven column (e.g. country) creates giant/tiny partitions; LC self-balances. So at silver, where a CDC merge keys on an uneven business key, LC beats partitioning. (Databricks docs explicitly recommend LC to handle skew in stored tables.)
- LC is **incremental + re-keyable**: as gold query patterns evolve, change keys without a full rewrite — critical for long-lived serving tables.
- **`CLUSTER BY AUTO`** is Databricks' recommended default: let predictive optimization observe the workload and pick keys, especially at gold where query patterns shift. (Note: AUTO may decline to select keys for tables that are too small, already well-ordered, or infrequently queried — it's cost-aware.)

**From Apollo Gen2 (first person):** My STG and BRZ SCD2 tables are bronze-tier and ingest-ordered, so I cluster only on the CDC business key where a downstream layer merges on it. The bigger LC payoff would be at the silver/serving layer Novartis builds on top (CRM entities filtered by account/territory) — there I'd use `CLUSTER BY AUTO` so data skipping tracks how analysts actually slice the data, rather than guessing partition columns up front.

```python
from pyspark import pipelines as dp

# Silver: cluster by the merge/join key to fight skew
@dp.table(name="slv_account", cluster_by=["accountid", "modifiedon"])
def slv_account():
    return spark.readStream.table("brz_account")

# Gold: let Databricks adapt keys to BI query patterns
@dp.materialized_view(name="gold_account_summary", cluster_by_auto=True)
def gold_account_summary():
    return spark.read.table("slv_account").groupBy("territoryid").count()
```
```sql
CREATE OR REFRESH STREAMING TABLE slv_account CLUSTER BY (accountid, modifiedon)
AS SELECT * FROM STREAM(brz_account);

CREATE OR REFRESH MATERIALIZED VIEW gold_account_summary CLUSTER BY AUTO
AS SELECT territoryid, COUNT(*) FROM slv_account GROUP BY territoryid;
```

**One-liner:** "I apply liquid clustering where reads filter or join on predictable keys — `CLUSTER BY` the merge key at silver to beat CDC skew and `CLUSTER BY AUTO` at gold so data-skipping adapts to BI query patterns — and skip it at append-ordered bronze where there's no read pattern to optimize."

## Category 9 — Unity Catalog & Security (Q40–Q42)

### Q40 — Unity Catalog and its role in SDP pipelines
**Question:** What is Unity Catalog and how is it used in DLT (SDP / Lakeflow Declarative Pipelines) pipelines?

**What UC (Unity Catalog) is:**
- UC = Databricks' central **governance layer** for data + AI across all workspaces in a metastore. One place for access control, lineage, audit, and discovery.
- **Three-level namespace:** `catalog.schema.table` (replaces the old two-level Hive `database.table`).
- Governs more than tables: schemas, **views, materialized views, streaming tables**, volumes (files), functions/UDFs, models, external locations, storage credentials, connections.
- Securables form a hierarchy; privileges **inherit** downward (grant `SELECT` on a schema → applies to all current + future tables in it).

**How SDP uses UC (current default):**
- For pipelines created on/after **2025-02-05**, UC is the **default** publishing target (and the new pipeline default is also **serverless compute + Unity Catalog + Current channel**). Pick a **default catalog** + **default schema** at pipeline config time.
- The pipeline **publishes every `@dp.table` (streaming table) and `@dp.materialized_view` (MV)** into the configured catalog.schema. They become real UC-governed objects, queryable from SQL warehouses, notebooks, other pipelines.
- **Legacy contrast (one clause):** the old `LIVE` virtual schema (legacy publishing mode, pre-2025-02-05 pipelines) is no longer used in the default publishing mode — the `LIVE` keyword is now **silently ignored**; unqualified identifiers resolve to the current schema and you publish to a concrete `catalog.schema`.
- **Three-tier identifier resolution:** unqualified names resolve to the pipeline's default catalog/schema; fully-qualify (`main.stores.regional_sales`) to write/read across catalogs. `USE CATALOG` / `USE SCHEMA` set the scope inside a source file.

**Required privileges for the identity that runs a UC SDP pipeline (verified — these are the pipeline owner / run-as identity's UC grants):**

| Privilege | On | Why |
|---|---|---|
| `USE CATALOG` | target catalog | enter the catalog |
| `USE SCHEMA` | target schema | enter the schema |
| `CREATE TABLE` | target schema | create streaming tables (`@dp.table`) |
| `CREATE MATERIALIZED VIEW` | target schema | create MVs (`@dp.materialized_view`) |
| `MODIFY` | existing tables the pipeline updates | write into tables it doesn't create |
| `CREATE SCHEMA` | catalog | only if the pipeline creates new schemas |

`CREATE TABLE` and `CREATE MATERIALIZED VIEW` are distinct UC privileges — both are grantable at schema or catalog level, and the combined grant syntax is `GRANT CREATE { MATERIALIZED VIEW | TABLE } ON SCHEMA …`.

**Compute requirement:** UC-enabled pipelines run on either **serverless** (the recommended default for new pipelines — serverless pipelines always use UC) or **classic** compute. On classic compute, UC requires **standard** or **dedicated** access mode (the legacy "shared"/"single-user" names) — pipelines manage their own cluster lifecycle, so you don't set the access mode the way you would for a notebook cluster. The standard-vs-dedicated distinction matters mainly when *querying* pipeline-created ST/MV from outside the pipeline: a non-owner on dedicated compute needs DBR 15.4+ and a serverless-enabled workspace.

**Cross-catalog write (PySpark):**
```python
from pyspark import pipelines as dp

@dp.materialized_view(name="main.stores.regional_sales")
def regional_sales():
    return spark.read.table("apollo.silver.partners")
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW main.stores.regional_sales
  AS SELECT * FROM apollo.silver.partners;
```

**Apollo Gen2 (first person):** All 422 of my SDP pipelines publish into UC. Each entity lands as a `<catalog>.<schema>.STG_<entity>` streaming table plus a `BRZ_<entity>` SCD2 (Slowly Changing Dimension type 2) bronze table. UC gives me one governed lineage graph from `incoming/` Auto Loader ingest → STG → BRZ, plus consistent GRANTs so analysts query bronze without touching my raw ADLS landing zone.

**One-liner:** Unity Catalog is Databricks' central catalog.schema.table governance layer, and in SDP it's the default publish target — every streaming table and materialized view becomes a UC-governed object with inherited privileges, lineage, and audit, replacing the legacy `LIVE` schema.

### Q41 — Handling and resolving access issues in SDP pipelines
**Question:** How do you handle and resolve access-related issues in DLT (SDP)?

**First, the two identities involved (verified):**
- **Pipeline run identity** = the **pipeline owner / run-as user**. The update reads sources, creates tables, and writes data **as that identity**, not as whoever clicked Run. Databricks recommends setting a **service principal** as owner/run-as so prod doesn't break when a person leaves. (Owner ≠ run-as can diverge: changing **Run as** to a service principal reassigns the executing identity.)
- **Caller identity** = whoever runs/edits the pipeline. Needs a pipeline **ACL**: `CAN VIEW`, `CAN RUN`, `CAN MANAGE`, or `IS OWNER`. Running an update requires `CAN RUN`, `CAN MANAGE`, or `IS OWNER`. Managing permissions requires `CAN MANAGE` or `IS OWNER`.

**The common access failures and fixes:**

| Symptom | Root cause | Fix |
|---|---|---|
| Pipeline update fails creating ST/MV | run-as identity lacks `CREATE TABLE` / `CREATE MATERIALIZED VIEW` + `USE SCHEMA`/`USE CATALOG` on target | GRANT the create + use privileges to the owner/SP |
| Update fails writing an existing table | run-as identity lacks `MODIFY` on a table it updates but didn't create | `GRANT MODIFY` on that table to the owner/SP |
| "dataset does not exist" on a source read | run-as identity lacks `SELECT` (or `USE CATALOG`/`USE SCHEMA`) on the upstream — UC reports "not found" instead of "denied" | grant read chain: `USE CATALOG` + `USE SCHEMA` + `SELECT` |
| Analyst can't query the published table | by default **only the pipeline owner** can query pipeline-created ST/MV | `GRANT SELECT` to the consumer group |
| Auto Loader can't read landing zone | run-as identity lacks `READ FILES` on the UC **external location** / volume | grant `READ FILES` on the external location |
| `UNITY_CATALOG_INITIALIZATION_FAILED` | UC misconfig — required catalog/schema missing or not accessible, or the cluster lacks UC access; often a storage-credential / RBAC gap behind it | verify catalog + schema exist and are reachable; fix the storage credential's RBAC (e.g. **Storage Blob Data Contributor** on the ADLS account) |
| Non-admin can't see driver logs to debug | by default only the owner + workspace admins see driver logs | set pipeline config `spark.databricks.acl.needAdminPermissionToViewLogs=false` to let any `CAN VIEW` / `CAN RUN` / `CAN MANAGE` user view the driver logs |
| `PIPELINE_PERMISSION_DENIED_NOT_OWNER` mid-operation | an operation (e.g. refresh of a pipeline-managed table) requires ownership | run as / own the pipeline with a stable SP; don't depend on a personal account |

**The full read chain to remember:** to read one table a principal needs **`USE CATALOG` (parent catalog) + `USE SCHEMA` (parent schema) + `SELECT` (table)** — all three. Missing any one surfaces as "does not exist," which is the #1 misdiagnosed access bug.

**Resolution code:**
```sql
-- let owner/SP create + write bronze
GRANT USE CATALOG ON CATALOG apollo TO `apollo_sp`;
GRANT USE SCHEMA ON SCHEMA apollo.bronze TO `apollo_sp`;
GRANT CREATE { MATERIALIZED VIEW | TABLE } ON SCHEMA apollo.bronze TO `apollo_sp`;
-- write tables it updates but didn't create
GRANT MODIFY ON TABLE apollo.bronze.BRZ_account TO `apollo_sp`;

-- expose published bronze to analysts (default = owner-only)
GRANT SELECT ON TABLE apollo.bronze.BRZ_account TO `analysts`;
REVOKE SELECT ON TABLE apollo.bronze.BRZ_account FROM `intern@novartis.com`;

-- read the ADLS landing zone via external location
GRANT READ FILES ON EXTERNAL LOCATION incoming_zone TO `apollo_sp`;
```
```python
# diagnostic: confirm the read chain from a notebook before blaming the pipeline
spark.sql("SHOW GRANTS `apollo_sp` ON TABLE apollo.silver.partners").show()
```

**Approach (how I triage in production):**
1. **Identify which identity failed** — pipeline run-as identity (write/create) or caller (run/edit). Read the error class: `*_PERMISSION_DENIED` / "does not exist" → run-as read/write grant; `PIPELINE_PERMISSION_DENIED_NOT_OWNER` → ownership; greyed-out ACL dialog → caller `CAN MANAGE`.
2. **Walk the read chain top-down** — `USE CATALOG` → `USE SCHEMA` → `SELECT`/`CREATE`/`MODIFY`. Verify with `SHOW GRANTS`.
3. **Check the storage layer** — for ingest failures it's almost always the external location `READ FILES` grant or the storage-credential managed-identity RBAC role, not the table grant.
4. **Prefer least-privilege group grants over user grants**, and run/own the pipeline with a **service principal** so access doesn't depend on a person.

**Apollo Gen2 (first person):** My pipelines run as a service principal, so a UC SDP run never depends on my personal account. The recurring access ticket was analysts not seeing bronze — expected, since pipeline tables default to owner-only; I fixed it once with a schema-level `GRANT SELECT ... TO analysts` so inheritance covered all BRZ tables in that schema going forward instead of granting table-by-table.

**One-liner:** Access issues in SDP are almost always a missing link in the `USE CATALOG` → `USE SCHEMA` → `SELECT`/`CREATE`/`MODIFY` chain or a storage-credential RBAC gap — I run the pipeline as a service principal, diagnose with `SHOW GRANTS`, and fix at the schema level so privilege inheritance covers all tables.

### Q42 — What to restrict vs. expose in an SDP implementation
**Question:** What information should be restricted or hidden vs. what information should be exposed or revealed in a DLT (SDP) implementation?

**Principle:** publish the **governed, curated layer**; restrict **raw landing data, credentials, and PII**. Lean on UC privilege inheritance, **row filters / column masks / dynamic views / ABAC policies**, and Databricks **secret scopes** — never hardcode.

**Restrict / hide:**

| Restrict | Mechanism |
|---|---|
| Storage credentials, SAS tokens, connection strings | **Databricks secret scopes** + `dbutils.secrets.get(...)`; never in source/notebook params |
| Raw ADLS landing zone (`replicate/`, `incoming/`) | don't grant `READ FILES` to consumers; only the pipeline SP gets it |
| Bronze/raw + operational metadata internals | publish to a **restricted schema**; don't `GRANT SELECT` to broad groups |
| PII columns (patient/HCP identifiers in pharma) | **column masks** or **dynamic views** gated on `is_account_group_member()` |
| Sensitive rows (per-region, per-cohort) | **row filters** (table-level `SET ROW FILTER`) or **ABAC row-filter policies** for cross-table scale |
| Pipeline ACLs to non-operators | keep `CAN MANAGE` / `IS OWNER` to the platform team |

**Expose / reveal:**

| Expose | How |
|---|---|
| Curated silver/gold ST + MV | `GRANT SELECT` to consumer groups (schema-level for inheritance) |
| **Data lineage** | automatic in Catalog Explorer — column-level (DBR 13.3 LTS+ for SDP column lineage), links back to the pipeline; viewers need `BROWSE` on the catalog plus `CAN VIEW` on the pipeline to see the pipeline link. Reveal it (aids trust + impact analysis) |
| Data-quality expectation results | `@dp.expect` metrics in the pipeline event log / quality dashboards — expose to data stewards |
| Schema + table metadata, tags, descriptions | UC discovery / `BROWSE` privilege so consumers find data without reading it |

**Column mask via dynamic view (verified — `is_account_group_member` is account-level and Databricks-recommended over the workspace-level `is_member`):**
```sql
CREATE VIEW apollo.gold.contact_redacted AS
SELECT
  contact_id,
  CASE WHEN is_account_group_member('hcp_auditors') THEN email
       ELSE regexp_extract(email, '^.*@(.*)$', 1) END AS email,
  country, segment
FROM apollo.silver.contact;
```
```python
# credentials NEVER hardcoded — pulled from a secret scope
sas = dbutils.secrets.get(scope="apollo", key="adls_sas")
```

**Approach (governance design I'd defend):**
1. **Tiered schemas:** `bronze` (SP-only) → `silver`/`gold` (analysts). Restriction is the **default** (pipeline tables are owner-only until granted), so exposure is a deliberate `GRANT`.
2. **PII via FGAC, not separate tables:** row filters / column masks / dynamic views keep one table but mask per-group — avoids duplicate "redacted" copies drifting out of sync. Reach for **ABAC tag-based policies** when the rule must apply consistently across many tables (they attach at catalog/schema level on governed tags). Note: serverless or DBR 16.4+ is required for ABAC-secured tables, and dynamic views require a SQL warehouse / standard / dedicated (DBR 15.4+) compute.
3. **Secret scopes for every credential**; the storage-credential managed identity is the only thing that touches ADLS.
4. **Expose lineage + DQ openly** — transparency about *quality and provenance* builds trust; secrecy is reserved for *credentials and PII*.

**Apollo Gen2 (first person):** Bronze SCD2 tables carry operational metadata (`_processing_timestamp`, `_source_file_path`) that's internal plumbing — I never expose those to analysts; consumers get curated downstream views. Synapse Link credentials live in a secret scope, never in the preprocessing notebook. For Novartis pharma data, HCP/patient identifiers would be masked with dynamic views or column masks gated on an auditors group, so the same governed table serves both privileged and non-privileged readers.

**One-liner:** Restrict credentials (secret scopes), raw landing data, and PII (row filters / column masks / dynamic views / ABAC), but openly expose curated silver/gold tables, lineage, and data-quality metrics — in SDP the default is owner-only, so every exposure is a deliberate least-privilege `GRANT`.

## Category 10–11 — Schema Evolution, Monitoring & Troubleshooting (Q43–Q45)

### Q43 — Schema evolution when a column is added; evolution modes
**Question:** How do you handle schema evolution when an additional column is added? What types of schema evolution modes are available?

**Where this lives in SDP:** Schema evolution is owned by the **connector** (Auto Loader / `read_files`) at the bronze ingest, *not* by the SDP table. The streaming table (`@dp.table`) just persists whatever the connector hands it. Auto Loader keeps a **schema location** (a `_schemas` directory). Inside SDP you don't set it — SDP manages both the schema location and the streaming checkpoint automatically; these are internal pipeline-managed directories, *separate* from the event log. On each micro-batch Auto Loader merges newly seen columns to the **end** of the inferred schema (initial inference samples the first 50 GB or 1000 files, whichever comes first).

**Mechanism on a new column (default `addNewColumns`):**
- Auto Loader detects the new field and throws `UnknownFieldException` → the **stream stops** (a controlled hard-stop, not data loss).
- Before throwing, it has already written the widened schema to the schema location.
- In an SDP **job/continuous** pipeline this triggers **automatic retry/restart**; the next attempt resumes with the new column populated. Rows read *before* the evolution carry `NULL` for the new column. Existing column **data types never change** under `addNewColumns`.

**`cloudFiles.schemaEvolutionMode` values (verified, current docs):**

| Mode | Behavior on a new column |
|---|---|
| `addNewColumns` **(default when NO schema is provided)** | Stream fails with `UnknownFieldException`, column appended to schema, restart resumes. Existing types unchanged. |
| `addNewColumnsWithTypeWidening` | Same as above **plus** widens supported types (`int`→`long`, `float`→`double`). Unsupported changes (`int`→`string`) go to rescued data. Public Preview, DBR 16.4+. |
| `rescue` | Schema **never** evolves, stream **never** fails; all unmatched columns land in `_rescued_data`. |
| `failOnNewColumns` | Stream fails and **will not restart** until you update the provided schema / schema hint or remove the offending file. |
| `none` | Schema not evolved, new columns **silently ignored** (lost unless `rescuedDataColumn` is set). No failure. |

**Critical non-obvious default (call it out — this is a silent trap):** `addNewColumns` is the default **only when you do NOT provide a schema**. The moment you pass an explicit schema, the default flips to **`none`** — meaning new source columns are silently dropped. In fact `addNewColumns` is *not allowed* with an explicit fixed schema; to still evolve you must pass your schema as a **schema hint** (`cloudFiles.schemaHints`), not a fixed `.schema(...)`. This is exactly the kind of "silent failure" I design against.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

@dp.table(name="stg_account", comment="Bronze ingest with addNewColumns evolution")
def stg_account():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")  # explicit, even though default
            .option("rescuedDataColumn", "_rescued_data")               # catch type-mismatched values
            .load("/mnt/incoming/account/")
    )
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE stg_account AS
SELECT * FROM STREAM read_files(
  '/mnt/incoming/account/',
  format        => 'csv',
  schemaEvolutionMode => 'addNewColumns',
  rescuedDataColumn   => '_rescued_data'
);
```

**Apollo Gen2 grounding (first person):** On my Novartis project the upstream is **Dynamics 365 → Synapse Link → ADLS**, and `schemaEvolutionMode = addNewColumns` is exactly the behavior I rely on: it only **adds** columns — it never removes, renames, or retypes. The trap I document for my team is the asymmetry: when D365 *adds* a CRM attribute, Auto Loader picks it up and old rows get `NULL`; but when a source column is *removed* upstream, the column does **not** disappear from the streaming table — new rows just land `NULL` for it (the docs call this a "soft delete"). I also keep `_rescued_data` on so a type drift (e.g. a US-format `SinkModifiedOn` that fails `to_timestamp()`) is captured rather than dropped. For the bronze SCD2 layer, when a new column appears mid-stream I must remember to add it to `track_history_except_column_list` if it is operational metadata, otherwise every backfill row spawns a false SCD2 version.

**One-liner:** Auto Loader's `addNewColumns` (the default only when no schema is supplied — it flips to `none`, and is disallowed outright, the instant you give a fixed schema) appends new columns and hard-stops the stream so the SDP job auto-restarts with the widened schema, never altering existing column types.

### Q44 — Event logs, checkpoints, and retry mechanisms in SDP
**Question:** Explain event logs, checkpoints, and retry mechanisms in DLT.

*(DLT = SDP / Lakeflow Declarative Pipelines; answered in SDP terms.)*

**1. Event log — the observability backbone**
- Every SDP pipeline auto-writes a structured **Delta table** capturing: audit logs, **data-quality (expectation) results**, pipeline progress, **data lineage**, and resource/error detail. Always on; you don't enable it.
- **Default location (current default publishing mode):** a *hidden* Delta table in the pipeline's default catalog/schema named `event_log_{pipeline_id}` (the system UUID with dashes → underscores). It appears in `system.information_schema.tables` but is **not** visible in Catalog Explorer; by default only the pipeline's **run-as user** can query it. You can optionally *publish* it to a named catalog/schema/table via the pipeline's `event_log` advanced setting.
- **Query it** via the `event_log()` TVF (table-valued function) by pipeline ID, then wrap in a view. The TVF must run on a **shared cluster or SQL warehouse**, can be called only by the pipeline/table owner, and the resulting view can't be shared with other users:
```sql
CREATE VIEW event_log_raw AS SELECT * FROM event_log('<pipeline-id>');
```
- Key `event_type` values to know: `flow_progress` (rows in/out, backlog, **data_quality.expectations** pass/fail/dropped), `flow_definition` (lineage: `input_datasets` → `output_dataset`), `update_progress` (run state), `operation_progress` (snapshot %/listing progress), `autoscale` / `cluster_resources` (classic compute only). `level` ∈ INFO / WARN / ERROR / METRICS.

```sql
-- Expectation (data-quality) metrics for the latest update
SELECT e.dataset, e.name,
       SUM(e.passed_records) AS passed,
       SUM(e.failed_records) AS failed
FROM (
  SELECT explode(from_json(
    details:flow_progress:data_quality:expectations,
    'array<struct<name:string,dataset:string,passed_records:int,failed_records:int>>')) e
  FROM event_log_raw WHERE event_type = 'flow_progress'
) GROUP BY e.dataset, e.name;
```
- **Do not delete** the event log or its parent catalog/schema — future updates fail (`EVENT_LOG_TABLE_DELTA_MISSING_DATA_FILES` class).

**2. Checkpoints — fault tolerance for streaming tables**
- A checkpoint persists **(a) source offsets processed, (b) intermediate state** for stateful ops (aggregations, dedupe, `flatMapGroupsWithState`), and **(c) query metadata**. For Auto Loader the file-discovery state lives in a RocksDB key-value store inside that checkpoint. This is what gives **exactly-once** processing (offsets + idempotent Delta sink) and lets a failed run **resume from the last committed batch** instead of reprocessing from zero.
- In SDP, checkpoints are **fully managed and internal** — one checkpoint per **flow** writing to a streaming table; you don't set a `checkpointLocation`. The `flow_id` in the event log is your handle: as long as `flow_id` is stable, the flow is refreshing **incrementally**; it changes on a full refresh / checkpoint reset.
- **When checkpoints break:** changing a **stateful operator** (adding/removing `dropDuplicates()`, changing aggregation keys, adding/removing a union source) causes a hard failure like `Streaming stateful operator name does not match ... in state metadata` (SQLSTATE 42K03). Recovery options:

| Recovery | Data loss | Cost | When |
|---|---|---|---|
| **Full refresh** | Possible (if source files gone) | Medium | Simplest; also lets you change code |
| **Full refresh + backup/backfill** | None | High | Last resort, must preserve data |
| **Reset table checkpoint** + resume incrementally (`startingVersion` / `startingTimestamp`) | None (if done carefully) | Low | Must keep existing data, continue incrementally |

**3. Retry / restart — how SDP self-heals**
SDP retries transient failures from the most granular unit outward: **Spark task → flow → entire pipeline update**. Whether automatic restart kicks in depends on **how the update is triggered**, not on table type:

| Trigger | Behavior |
|---|---|
| **UI "Run now" / ad-hoc / Validate** | Fast-start, debug mode: **retries DISABLED** (fail fast), cluster reused (default 2 h via `pipelines.clusterShutdown.delay`) |
| **Jobs / Pipelines API / continuous** | **Automatic retry + restart**: restarts cluster on recoverable errors (memory leak, stale creds), retries on cluster-start failures, cluster shuts down right after run |

Verified retry defaults (pipeline properties):
- `pipelines.maxFlowRetryAttempts` — **default 2 retries** → a retryable flow runs **3 times total** (original + 2) before the update fails.
- `pipelines.numUpdateRetryAttempts` — retries the **whole update** as a full update; default **5 for triggered**, **unlimited for continuous**; applies only to automatic-retry pipelines (never for ad-hoc/Validate).
- Continuous serverless pipelines additionally **recover automatically from failures** and keep running until manually stopped.

**Apollo Gen2 grounding (first person):** My 422 SDP pipelines run as **jobs chained via `depends_on`** (preprocessing notebook JOB1 → SDP JOB2), so they're squarely in the automatic-retry path — a transient cluster-start blip self-heals without me touching it, while a genuine integrity failure surfaces after the bounded retries instead of looping forever. I lean on the event log heavily for SIT: my 17 SIT cases read `flow_progress.data_quality.expectations` to assert PK/SCD2/CDC integrity gates (FAIL) and freshness/schema-drift observability (WARN). The one checkpoint scar I carry is **streaming-on-mutable-source**: a streaming table needs an append-only source; when an upstream was mutable the flow failed on the change commit, and the fix was either making the source append-only, setting `skipChangeCommits` on the read, or switching to a snapshot/MV pattern — not fighting the checkpoint.

**One-liner:** The event log is an always-on hidden Delta table (`event_log_{pipeline_id}`) queried via `event_log('<id>')` on a warehouse/shared cluster for lineage, quality and progress; checkpoints are SDP-managed per-flow offset+state stores giving exactly-once resume; and retries escalate task→flow→update, automatic only for job/API/continuous runs (2 flow retries → 3 attempts; 5 update retries triggered, unlimited continuous), while UI "Run now" disables them so you fail fast.

### Q45 — Production issues faced during SDP pipeline execution and resolution
**Question:** What production issues have you faced during pipeline execution using DLT, and how did you resolve them?

*(DLT = SDP; answered in SDP terms, first person from Apollo Gen2 — Dynamics 365 → Synapse Link → ADLS → SDP, 211 entities, 422 pipelines.)*

**Approach (how I triage any SDP failure):**
1. Read the **event log** `flow_progress` / `update_progress` for the failing `flow_name` and error class.
2. Classify: **integrity gate** (PK/SCD2/CDC) vs **observability** (freshness/schema drift) vs **framework limit**.
3. Apply the smallest fix that preserves data (prefer checkpoint reset / config + regenerate over full refresh).

**The incidents I can name, with resolution:**

| # | Incident | Root cause | Resolution |
|---|---|---|---|
| 1 | **SCD2-on-SCD2** | Source was *already* SCD2; I ran `create_auto_cdc_flow` on top → double-historized garbage | Stopped running CDC on an already-SCD2 source. Either **collapse to current-only** or **preserve history via direct column mapping** (map the source's history columns straight through) instead of re-deriving SCD2. |
| 2 | **Streaming-on-mutable-source** | A `@dp.table` (streaming table) needs an **append-only** source; the upstream was mutable (in-place updates) → the stream failed on the change commit | Set `skipChangeCommits` on the read to ignore non-append commits, switched the feed to an append-only landing, or moved that entity to a **snapshot** pattern (`create_auto_cdc_from_snapshot_flow`) / MV. A streaming table can't propagate updates/deletes from a mutable source. |
| 3 | **Coarse `sequence_by`** | `sequence_by = file_modification_time` — multiple rows shared one file, so on ties CDC picked an **arbitrary** winner | Replaced with a **real per-row** ordering key (true event/sequence timestamp); for tie-breaks I use a `struct(...)` of (event_time, id) so `create_auto_cdc_flow` orders deterministically. |
| 4 | **False SCD2 versions on every re-run** | Operational-metadata columns (`_processing_timestamp`, `_source_file_path`) changed every run, so SCD2 saw a "new version" each time | Added every operational-metadata column to **`track_history_except_column_list`** so they're ignored for change detection. |
| 5 | **Phantom empty column (full-load CSVs)** | Synapse full-load CSVs carry **trailing commas** → an extra empty column; headerless CSVs got mis-aligned headers | In JOB1 preprocessing: if `col_count == expected + 1`, **drop the trailing phantom column**; add headers from `model.json`/`schemas.json`. |
| 6 | **US-format timestamps** | `SinkCreatedOn`/`SinkModifiedOn` are Synapse metadata in **US date format**; naive cast misread day/month | Explicit `to_timestamp(col, 'M/d/yyyy h:mm:ss a')` in preprocessing before the SDP layer; kept `_rescued_data` on to catch stragglers. |
| 7 | **Path/folder quirks** | Case-sensitive ADLS paths + folder names with **stray spaces** caused "path not found" | Normalized paths and `.strip()` on folder names in JOB1. |
| 8 | **"SDP can't run dbutils.fs"** | SDP pipeline code forbids arbitrary file ops / `dbutils.fs` inside the declarative graph | This is *why* I run the **two-job pattern**: preprocessing is a separate single-node notebook JOB1 chained via `depends_on` to the SDP JOB2 — different compute, independent failure domains, and SDP only ever sees clean per-entity files. |

**Cross-cutting principle I applied:** *design around the framework's limits, don't fight them.* The two-job split, the snapshot-vs-CDC choice, and `track_history_except_column_list` are all "work with SDP's contract" decisions. And the generated SDP code is an **artifact, not source-of-truth** — I edit the config and **regenerate** all 211 entities from one script rather than hand-patching 422 pipelines.

**One-liner:** My worst production failures were all "wrong source shape for the chosen flow" — SCD2-on-SCD2, streaming-on-a-mutable-source, and tie-breaking on a coarse `sequence_by` — and I resolved each by matching the flow type to the source contract (collapse/preserve, append-only/`skipChangeCommits` or snapshot CDC, real per-row ordering) plus the two-job pattern that keeps arbitrary file ops out of SDP entirely.

## Category 12–13 — Strategic Decisions & Practical Experience (Q46–Q50)

### Q46 — Benefits of migrating an existing PySpark pipeline to SDP
**Question:** What are the benefits of migrating an existing PySpark pipeline to Delta Live Tables (now Spark Declarative Pipelines / Lakeflow)?

**Naming note:** "DLT" was renamed to **Lakeflow Spark Declarative Pipelines (SDP)** (2025). The Python module is `from pyspark import pipelines as dp` (it was previously `dlt`). I answer in SDP terms.

**What you give up writing by hand (the core win)**
SDP replaces hundreds of lines of imperative PySpark + Structured Streaming + `MERGE` orchestration with a few declarative decorators. You declare *what* each dataset is; the engine figures out *how* and *in what order* to build it.

| Hand-rolled PySpark you delete | SDP replacement |
|---|---|
| `foreachBatch` + `MERGE INTO` for CDC, manual out-of-order/dedup logic | `dp.create_auto_cdc_flow(...)` (AUTO CDC) — SCD1/SCD2 declaratively |
| Manual checkpoint dirs, `writeStream` plumbing per table | `@dp.table` (streaming table) manages checkpoints/state |
| Custom DAG / `depends_on` between transforms | Auto dataflow-graph + parallelization from `spark.readStream.table(...)` references |
| `if df.filter(bad).count() > 0: raise` data-quality guards | `@dp.expect_or_drop` / `@dp.expect_or_fail` |
| Bespoke retry/backoff wrappers | Built-in retry: Spark task → flow → pipeline |

**Concrete benefits (verified against current Lakeflow docs)**
- **Automatic orchestration:** SDP evaluates all dataset definitions, builds the dependency graph, runs flows in correct order with automatic parallelization, and retries transient failures granularly (task → flow → pipeline) — no manual `depends_on`.
- **Declarative CDC:** AUTO CDC handles out-of-order events, dedup, and SCD2 history without you knowing watermark internals.
- **Incremental processing for free:** Write a materialized view (MV) with batch semantics; on a serverless pipeline the engine attempts to incrementally refresh only changed upstream rows instead of full recompute. (On classic compute, MVs are always fully recomputed — see Q49.)
- **Built-in data quality + lineage:** Expectations emit pass/fail/drop metrics to the event log (for `warn` and `drop`; `fail` aborts and records no metrics); lineage and the dataflow graph come automatically.
- **Unity Catalog managed tables + auto maintenance:** streaming tables and MVs are UC-managed Delta tables; pipelines run `OPTIMIZE`/`VACUUM` on a predictive-optimization cadence.

**PySpark before → SDP after**
```python
# BEFORE: imperative structured streaming + manual merge
def upsert(batch_df, _):
    batch_df.createOrReplaceTempView("u")
    spark.sql("MERGE INTO bronze t USING u s ON t.id=s.id WHEN MATCHED ...")
(spark.readStream.format("cloudFiles").load(path)
   .writeStream.foreachBatch(upsert).option("checkpointLocation", ckpt).start())
```
```python
# AFTER: SDP
from pyspark import pipelines as dp

dp.create_streaming_table("bronze")

dp.create_auto_cdc_flow(
    target="bronze", source="stg_account",
    keys=["accountid"], sequence_by="_seq",
    stored_as_scd_type=2,
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
-- SQL equivalent
CREATE OR REFRESH STREAMING TABLE bronze;
CREATE FLOW apply_cdc AS AUTO CDC INTO bronze
  FROM STREAM(stg_account)
  KEYS (accountid) SEQUENCE BY _seq STORED AS SCD TYPE 2;
```

**From my Apollo Gen2 experience:** Migrating to SDP is exactly why I could batch-generate **422 pipelines (211 STG streaming tables + 211 BRZ SCD2 tables)** from one config-driven script. Each entity is `@dp.table` + `create_auto_cdc_flow`; I never wrote a single `MERGE` or checkpoint path. Edit config, regenerate — generated code is an artifact, not source-of-truth.

**One-liner:** Migrating to SDP collapses hand-written streaming, MERGE-based CDC, DAG wiring, and quality checks into declarative decorators with automatic orchestration, incremental MV refresh on serverless, granular retries, and built-in lineage and data-quality metrics.

### Q47 — When to prefer SDP over hand-written Structured Streaming
**Question:** When would you prefer using DLT (SDP) over a traditional Structured Streaming solution?

**Decision rule:** Prefer **SDP** when you want a *managed, declarative, multi-table medallion pipeline*; keep **raw Structured Streaming** when you need a *single low-level stream with custom operators SDP doesn't expose*.

**Prefer SDP when**
- You have **many interdependent tables** (bronze → silver → gold) and want auto-orchestration + lineage instead of wiring `depends_on` yourself.
- You need **SCD1/SCD2 CDC** — AUTO CDC (`create_auto_cdc_flow`) handles ordering/dedup/deletes; doing this in raw streaming means `foreachBatch` + `MERGE` + manual out-of-order handling.
- You want **declarative data quality** via `@dp.expect*` with event-log metrics.
- You want **incremental MVs** for aggregations/joins (batch semantics, engine incrementalizes on serverless).
- You want **managed checkpoints, enhanced autoscaling, and granular retries** without ops code.

**Prefer raw Structured Streaming when**
- You need operators **not supported** in SDP real-time mode: `flatMapGroupsWithState`, `mapPartitions`, arbitrary `foreachBatch`/`foreach`, stream-stream joins in real-time mode, or custom sinks beyond the `dp.create_sink` set.
- You need a **single stream** with bespoke trigger control (`Trigger.AvailableNow`, custom processing-time) and full control of the `writeStream` lifecycle.
- You need to do **arbitrary Python / file ops** (`dbutils.fs`, REST calls) with side effects in the same job — SDP forbids side-effecting Python in dataset-definition functions.

| Need | Choose |
|---|---|
| Medallion ETL, multiple tables, lineage | SDP |
| SCD2 CDC from a change feed | SDP (AUTO CDC) |
| Incremental aggregations/joins for BI | SDP (MV) |
| Custom stateful op (`flatMapGroupsWithState`) | Structured Streaming |
| Arbitrary file/Python orchestration | Plain notebook/job |

**Approach (how I'd frame it in Apollo Gen2):** My pipeline is fundamentally medallion CDC at scale — 211 entities, SCD2 history, quality gates. That's the SDP sweet spot. But preprocessing (reading headerless CSVs, attaching headers from `model.json`, splitting per-entity, `dbutils.fs` operations) is **arbitrary side-effecting Python that SDP won't run in a dataset definition**, so I keep it as a separate notebook JOB1 chained via `depends_on` to the SDP JOB2. So my real answer is *both*: a Structured-Streaming-style notebook for the messy I/O prep, SDP for the declarative medallion core.

**One-liner:** I reach for SDP whenever the workload is a multi-table medallion pipeline with CDC and quality gates; I drop to raw Structured Streaming only for custom stateful operators or arbitrary-Python I/O that SDP won't run.

### Q48 — Main challenges of implementing SDP instead of building with PySpark
**Question:** What are the main challenges you face when implementing DLT (SDP) instead of building solutions with PySpark?

**The trade:** SDP buys you orchestration and incremental engines, but charges you in **flexibility and debuggability**. You design *around* the framework's guardrails.

**Challenges (each grounded in something I hit)**
- **No arbitrary side-effecting Python in dataset definitions.** SDP dataset functions can't run `dbutils.fs`, arbitrary file moves, or REST calls with side effects. In Apollo Gen2 this forced the **two-job pattern**: a preprocessing notebook (JOB1) chained by `depends_on` to the SDP pipeline (JOB2). Reasons: (1) SDP forbids side-effecting Python in dataset definitions; (2) different compute — single-node notebook vs autoscaling SDP; (3) independent failure domains.
- **Declarative graph, not procedural control.** SDP evaluates *all* dataset definitions and builds the dataflow graph before running. Source order = code-evaluation order, **not** execution order. You can't `print`/step through a `writeStream` lifecycle; you reason about the graph.
- **Full refresh is the blunt tool for logic changes.** A streaming table sees each row once; if you change query logic (e.g., add `UPPER()`), only new rows reflect it. Reprocessing history needs a **full refresh**, which on a short-retention source can lose data.
- **CDC config footguns.** `create_auto_cdc_flow` needs `track_history_except_column_list` to list **every** operational-metadata column (`_processing_timestamp`, `_source_file_path`, etc.), or every re-run creates a false SCD2 version. `sequence_by` must have true per-row granularity — `file_modification_time` is too coarse and CDC picks arbitrarily on ties. (Note: `stored_as_scd_type` defaults to **1**, so SCD2 must be set explicitly.)
- **Source-shape assumptions break streaming tables.** A streaming table needs an **append-only / naturally-bounded** source; a mutable upstream (records changed or deleted) throws an error under streaming read. And running CDC on an **already-SCD2** source (SCD2-on-SCD2) doubles history — you must collapse to current-only or map columns directly.
- **Incremental MV is serverless-only and fragile to query shape.** Incremental refresh only runs on serverless pipelines; on classic compute the MV is **always fully recomputed**. Non-deterministic functions (except temporal functions in `WHERE`), unsupported sources (volumes, external locations, foreign catalogs, foreign Iceberg), recursive CTEs, etc., fall back to full recompute (cost spike).
- **Generated-code volume + governance.** 422 pipelines is a lot of artifact; you must treat generated code as artifact, not source-of-truth (edit config + regenerate).

**Approach to mitigate (what I actually do):**
```python
# Guardrail: every operational column listed so SCD2 doesn't false-version
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account",
    keys=["accountid"], sequence_by="SinkModifiedOn",   # real per-row timestamp, not file mtime
    apply_as_deletes=expr("_change_type = 'delete'"),
    stored_as_scd_type=2,                                # explicit; default is SCD type 1
    track_history_except_column_list=[
        "_processing_timestamp", "_source_file_path", "_ingest_date",
    ],
)
```

**One-liner:** The main challenges are that SDP forbids side-effecting Python in dataset definitions (forcing my two-job pattern), replaces step-through debugging with declarative-graph reasoning, makes logic changes require full refreshes, and has CDC/streaming footguns I design around — listing every metadata column, setting SCD type explicitly, using real per-row sequence keys, and never running CDC on a mutable or already-SCD2 source.

### Q49 — Limitations of SDP, streaming tables, materialized views, and expectations
**Question:** What are the limitations of DLT (SDP), streaming tables, materialized views, and expectations?

**Naming note:** "Live Tables vs Live Streaming Tables" in legacy DLT maps to **materialized view (MV)** vs **streaming table** in SDP. (`CREATE OR REFRESH LIVE TABLE` is deprecated in favor of `CREATE OR REFRESH MATERIALIZED VIEW`.) I answer in SDP terms. All limits below verified against current Lakeflow docs.

**Pipeline-level (SDP) limits**
- Workspace cap of **1000 concurrent pipeline updates**.
- Source-file limits: if the config references *only* individual files/notebooks, the limit is **100 source files** per pipeline; if it includes folders, you can have up to **50 source entries** (files or folders) indirectly referencing up to **1000 files**.
- A dataset can be **defined only once** (target of a single owning operation across all pipelines) — *exception:* a streaming table can take multiple append flows (`@dp.append_flow`).
- MVs/streaming tables published from a pipeline are accessible only to Azure Databricks clients/applications; to expose externally, use the sink API (`dp.create_sink`).
- `PIVOT` / the `pivot()` function is **not supported** (it requires eager schema inference).
- Delta time-travel works on streaming tables but **not** on MVs; Iceberg reads (UniForm) can't be enabled on either.

**Streaming table limits**
- **Append-only / naturally-bounded source required** — state is bounded by watermarks; an unbounded/mutable source grows state without bound (OOM risk), and reading a source whose existing records change/delete throws an error (use `SkipChangeCommits` to tolerate).
- **Limited evolution:** each row is seen once; changing the query only affects rows processed *after* the change — reprocessing history needs a **full refresh**.
- **Joins don't recompute:** when a dimension changes, an already-emitted joined row is *not* recomputed ("fast-but-wrong"). For always-correct joins use an MV.
- **Stream-stream join** needs watermarks on **both** sides + a time-bound condition; omit either and state grows unbounded. Late/out-of-order data beyond the watermark is dropped, not auto-corrected.
- Identity columns are **not supported** on tables that are AUTO CDC targets.

**Materialized view limits**
- **Not low-latency** — refresh is seconds-to-minutes, not milliseconds.
- **Incremental refresh runs only on serverless pipelines**; MVs not on serverless are **always fully recomputed**. Even on serverless, the engine cost-compares and may still choose full recompute.
- Not all queries incrementalize: recursive CTEs (`WITH RECURSIVE`), most non-deterministic functions (temporal ones like `current_timestamp()` allowed in `WHERE`), and unsupported sources (volumes, external locations, foreign catalogs, foreign Iceberg) → **full recompute fallback**.
- Some operators (joins, filters, window functions, `UNION ALL`, etc.) require **row tracking** enabled on source tables to incrementalize.
- UDF behavior changes may not be detected → you must full-refresh manually.

**Expectations limits**
- Three actions: **warn (default, `expect` / `EXPECT`)** writes the bad row to the target and logs metrics, **drop** (`expect_or_drop` / `ON VIOLATION DROP ROW`), **fail** (`expect_or_fail` / `ON VIOLATION FAIL UPDATE`).
- `fail` records **no quality metrics** (it aborts the flow and rolls back the transaction); a single flow failure does **not** fail sibling parallel flows.
- Expectations are **row-level boolean checks only** — no native cross-row/quarantine routing; quarantine needs a manual two-flow pattern.
- Supported only on streaming tables, MVs, and (temporary) views; **not** on sinks, and **not** with `AUTO CDC FROM SNAPSHOT`. (Constraints `WHERE`-checks can't reference subqueries on other tables, custom Python functions, or external service calls.)
- Only **Python** can group expectations (`expect_all` / `expect_all_or_drop` / `expect_all_or_fail`); SQL can't specify collective actions.

```python
# warn vs drop vs fail
@dp.table
@dp.expect("recent_ts", "ts > '2012-01-01'")                 # warn (default): row kept, metric logged
@dp.expect_or_drop("has_pk", "accountid IS NOT NULL")        # drop: bad row removed, drop count logged
@dp.expect_or_fail("positive_amt", "amount > 0")             # fail: aborts flow + rollback, no metric
def silver(): return spark.readStream.table("bronze")
```
```sql
CREATE OR REFRESH STREAMING TABLE silver(
  CONSTRAINT recent_ts    EXPECT (ts > '2012-01-01'),
  CONSTRAINT has_pk       EXPECT (accountid IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_amt EXPECT (amount > 0)            ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM(bronze);
```

**From Apollo Gen2:** My **17-case SIT** is built precisely around these limits — FAIL on integrity gates (PK, SCD2, CDC correctness), WARN on observability (freshness, schema drift), warn-in-dev then fail-in-prod, and explicit tests for *silent* failures. The clearest silent case: a column **removed** upstream lands NULL in subsequent rows with no error (mode-independent). By contrast, a brand-**new** source column under the Auto Loader default `cloudFiles.schemaEvolutionMode=addNewColumns` does the opposite — it halts the stream with `UnknownFieldException` until the pipeline restarts with the merged schema. My SIT tests both: the loud new-column halt and the silent removed-column NULL.

**One-liner:** SDP caps concurrency and source files; streaming tables need append-only sources and don't recompute joins; MVs aren't low-latency and only incrementally refresh on serverless with supported query shapes; and expectations are row-level warn/drop/fail checks that lose metrics on fail, can't group in SQL, and don't work with `AUTO CDC FROM SNAPSHOT` or on sinks.

### Q50 — Rating my practical SDP experience; can I handle these challenges independently?
**Question:** Based on real-time challenges (stream joins with high watermark ranges, aggregation challenges with streaming tables), how would you rate your practical DLT (SDP) experience? Can you handle these challenges independently in a production environment?

**Self-rating:** Solid production-level on declarative CDC and medallion design; competent and improving on heavy stateful streaming (wide-watermark stream-stream joins, large-window aggregations). **Yes — I handle these independently in prod**, with the discipline of verifying against current docs before committing a state-changing design.

**Stream-stream joins with high watermark ranges**
- **Mechanism:** A stream-stream join needs a watermark on **both** sides plus a **time-bound** join condition; the interval tells the engine when no further match is possible so it can evict state. Wide watermark ranges = larger retained state = OOM/latency risk. (Stream-stream joins emit in append mode only; outer joins require watermarks.)
- **How I handle it:** Set the watermark to the *minimum* lateness the business tolerates (state cost scales with the range); enforce a time-bound predicate; and where late dimensions must retroactively apply, switch the join to an **MV** (which recomputes joins when dimensions change) instead of a streaming table (which doesn't).
```python
@dp.table
def impressions_with_clicks():
    imp = spark.readStream.table("impressions").withWatermark("imp_time", "3 minutes")
    clk = spark.readStream.table("clicks").withWatermark("click_time", "3 minutes")
    return imp.join(clk,
        expr("""imp_id = click_imp_id AND
                click_time BETWEEN imp_time AND imp_time + INTERVAL 3 MINUTES"""))
```
```sql
-- WATERMARK is a clause on each relation (WATERMARK <col> DELAY OF INTERVAL ...),
-- placed after the relation and before the table alias.
CREATE OR REFRESH STREAMING TABLE impressions_with_clicks AS
SELECT i.*, c.click_time
FROM STREAM(impressions) WATERMARK imp_time DELAY OF INTERVAL 3 MINUTES AS i
JOIN STREAM(clicks)      WATERMARK click_time DELAY OF INTERVAL 3 MINUTES AS c
  ON i.imp_id = c.click_imp_id
 AND c.click_time BETWEEN i.imp_time AND i.imp_time + INTERVAL 3 MINUTES;
```

**Aggregation challenges with streaming tables**
- **Mechanism:** Streaming aggregations *must* have a watermark or state grows unbounded; the docs are explicit that without a watermark the aggregation is **fully recomputed on each update** rather than incrementally maintained. Changing aggregation columns or the watermark invalidates state → requires **full refresh**.
- **How I handle it:** Use a windowed aggregation + watermark for incremental, bounded state; keep group cardinality limited; for complex/late-correct aggregations move to an **MV** (incremental refresh on serverless), or use a `REPLACE WHERE` flow for targeted incremental-batch recompute of joins/aggregations — noting `FLOW REPLACE WHERE ... BY NAME` is currently **Beta** and requires the Pipelines Preview channel.
```python
@dp.table
def event_counts():
    return (spark.readStream.table("events_raw")
            .withWatermark("event_time", "3 minutes")
            .groupBy(window("event_time", "1 minute"), "region").count())
```
```sql
-- WATERMARK clause sits after the relation, before GROUP BY.
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

**Evidence I can do this independently (Apollo Gen2, first person):**
- I built and operate **422 SDP pipelines** (211 STG streaming tables + 211 BRZ SCD2 tables) for 211 Dynamics 365 entities, batch-generated from one config script.
- I diagnosed and fixed real incidents: **SCD2-on-SCD2** (collapsed to current-only instead of CDC-on-CDC), **streaming-on-mutable-source** (rebuilt the source as append-only), and **`sequence_by` on `file_modification_time` ties** (moved to a real per-row timestamp).
- I own a **17-case SIT** that separates integrity FAIL gates from observability WARN gates and explicitly tests silent failures.
- I work around framework limits structurally (the **two-job pattern** for arbitrary-Python prep) and treat generated code as artifact.

**Honest gap:** My highest-volume work is CDC/SCD2 ingestion, not multi-day-watermark analytics joins. For those I lean on the documented contract (watermark on both sides + time-bound condition, MV when correctness on late dimensions matters) and **verify defaults against current Databricks docs** before shipping — I don't trust memory on state-changing behavior.

**One-liner:** I rate myself production-ready — I run 422 SDP pipelines and have debugged real SCD2, mutable-source, and sequencing incidents; I handle wide-watermark stream-stream joins and streaming aggregations independently by bounding state with watermarks plus time-bound conditions and escalating to materialized views when late-arriving correctness matters.


## Advanced Topics — Deep Dive

> Deeper reference on the topics flagged for the Novartis round (stream/snapshot joins, late data, refresh semantics, Auto Loader configs, SDP optimization, stateful processing, expectations & event-log internals, deployment modes, editions). SDP-only, doc-verified 2026-06-04. All Python/SQL in fenced code blocks.

### Stream–Stream Joins

**What it is**

A stream–stream join joins two *streaming* sources (both growing/unbounded) on a key, inside an SDP streaming table or `@dp.append_flow`. Unlike a stream–static join (stateless — the static Delta side is just re-snapshotted at the start of each microbatch), a stream–stream join is **stateful on BOTH sides**: each row from each stream must be buffered in a state store because its matching partner may arrive in a *later* microbatch on the *other* stream. SDP supports five join types (verified against Databricks docs):

| Join type | Emits unmatched rows? | Watermark requirement |
|---|---|---|
| Inner | No | **Recommended** (optional) on both sides — without it state grows unbounded |
| Left outer | Yes (NULLs for right) | **Mandatory** on both sides + time-bound condition |
| Right outer | Yes (NULLs for left) | **Mandatory** on both sides + time-bound condition |
| Full outer | Yes (NULLs either side) | **Mandatory** on both sides + time-bound condition |
| Left semi | No | **Mandatory** on the right + time-bound condition (left side optional, but recommended for full state cleanup; Databricks recommends watermarks on both sides of all stream–stream joins) |

Stream–stream joins only support **append** output mode — matched rows are appended to the target streaming table; nothing is ever updated/retracted.

**How it works (mechanics)**

- **Two state stores, keyed by join key.** When a microbatch arrives on stream A, every A-row is (a) matched against B-rows already in B's state store, AND (b) stored in A's state store so future B-rows can match it. Symmetric for B. Without eviction, both stores grow forever → OOM.
- **The two mandatory ingredients for bounded state:**
  1. **A watermark on BOTH sides** — `withWatermark(eventTimeCol, lateness)` (Python) / `WATERMARK col DELAY OF INTERVAL ...` (SQL). A watermark = a moving timestamp threshold ("I will not accept events older than max_seen_event_time − lateness").
  2. **A time-bound (interval) predicate in the join condition** — e.g. `click.ts BETWEEN imp.ts AND imp.ts + interval 3 minutes`. This is what tells the engine *when no further match is possible*, so it can drop rows from state. Watermark alone is not enough; the engine needs the interval to reason about cross-stream matchability. The interval predicate must reference the **same columns** the watermarks are defined on.
- **Global watermark = the slowest stream.** Each stream tracks its own max event time and derives its own watermark. The engine then computes ONE *global* watermark and, by default, takes the **minimum** across streams. Rationale: if stream B stalls (upstream outage), a min-based global watermark keeps moving at B's slow pace so the engine doesn't wrongly flag still-pending A-rows as un-matchable and emit premature/incorrect output. Safety over latency.
- **State eviction.** A buffered row is dropped once the global watermark advances past the latest event time at which any partner could still legally arrive (derived from the interval predicate + watermark). After eviction, no further match for that row is attempted.
- **Delayed OUTER NULL emission (the subtle, must-say point).** For outer joins, an unmatched row must NOT immediately emit a NULL-padded result — a match might still arrive in a later microbatch. The engine holds the unmatched row and only emits the `(row, NULLs)` result **once the watermark guarantees no match can ever arrive** (i.e., the time window for a partner has fully closed). This is why outer joins *require* watermarks: without them the engine can never prove "no match will come," so it could never correctly emit NULLs. Consequence: outer-join NULL rows are emitted **late** (after the lateness/interval window elapses), not in the triggering microbatch. Spark's wording: "The outer NULL results will be generated with a delay that depends on the specified watermark delay and the time range condition." A further subtlety: because the micro-batch engine advances watermarks at the *end* of a microbatch and only triggers a microbatch when there is new data, the outer NULL result can be delayed further if no new data arrives in the stream.

**Key configs / syntax**

Python — inner stream–stream join inside an append flow (canonical impressions × clicks, click within 3 min of impression):

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("adImpressionClicks")

@dp.append_flow(target="adImpressionClicks")
def joinClicksAndImpressions():
    clicksDf = (
        spark.readStream.table("rawClicks")
            .withWatermark("clickTimestamp", "3 minutes")
    )
    impressionsDf = (
        spark.readStream.table("rawAdImpressions")
            .withWatermark("impressionTimestamp", "3 minutes")
    )
    return (
        impressionsDf.alias("imp").join(
            clicksDf.alias("click"),
            expr("""
                imp.userId = click.userId AND
                clickAdId = impressionAdId AND
                clickTimestamp >= impressionTimestamp AND
                clickTimestamp <= impressionTimestamp + interval 3 minutes
            """),
            "inner"
        ).select("imp.userId", "impressionAdId", "clickTimestamp", "impressionSeconds")
    )
```

Python — left outer (only the join-type string changes; watermark + interval predicate become MANDATORY, and NULL-padded rows emit only after the 3-min window closes):

```python
joinDf = impressionsDf.alias("imp").join(
    clicksDf.alias("click"),
    expr("""
        imp.userId = click.userId AND
        clickAdId = impressionAdId AND
        clickTimestamp >= impressionTimestamp AND
        clickTimestamp <= impressionTimestamp + interval 3 minutes
    """),
    "leftOuter"
)
```

Python — different lateness per stream (allowed; engine still derives one global watermark = min of the two):

```python
impressionsDf = spark.readStream.table("rawAdImpressions").withWatermark("impressionTimestamp", "1 hour")
clicksDf      = spark.readStream.table("rawClicks").withWatermark("clickTimestamp", "2 hours")
```

SQL — same inner join as a streaming table (note `WATERMARK ... DELAY OF INTERVAL` attached to each `STREAM(...)` side, plus the interval predicate in `ON`):

```sql
CREATE OR REFRESH STREAMING TABLE silver.adImpressionClicks
AS SELECT
  imp.userId, impressionAdId, clickTimestamp, impressionSeconds
FROM STREAM (bronze.rawAdImpressions)
  WATERMARK impressionTimestamp DELAY OF INTERVAL 3 MINUTES imp
INNER JOIN STREAM (bronze.rawClicks)
  WATERMARK clickTimestamp DELAY OF INTERVAL 3 MINUTES click
ON imp.userId = click.userId
  AND clickAdId = impressionAdId
  AND clickTimestamp >= impressionTimestamp
  AND clickTimestamp <= impressionTimestamp + interval 3 minutes
```

Tuning configs (verified):

| Config | Default | Effect |
|---|---|---|
| `spark.sql.streaming.multipleWatermarkPolicy` | `min` | Global-watermark policy. `max` = use fastest stream (lower latency) but **drops** data from slower streams — Databricks recommends applying with caution. |
| `spark.sql.streaming.stateStore.providerClass` | **RocksDB** in Databricks Runtime 17.3+ (`com.databricks.sql.streaming.state.RocksDBStateStoreProvider`); HDFS-backed (in-memory) only on DBR < 17.3 | On older runtimes, explicitly set the RocksDB provider for large join state to avoid executor OOM. Serverless SDP pipelines manage the state store automatically. |
| `WATERMARK ... DELAY OF INTERVAL` | n/a | Must be a positive interval **less than a month**. |

**Use cases**

- Correlating two real-time event streams within a bounded time window: ad impression ↔ click, order ↔ payment, request ↔ response, sensor-A ↔ sensor-B readings.
- Enriching one stream with another stream whose records arrive around the same time (not a slowly-changing dimension — that's stream–static).
- In an Apollo Gen2-style medallion flow, this would live in a **Silver** streaming table correlating two Bronze event streams; my actual Gen2 work was overwhelmingly CDC SCD2 (`dp.create_auto_cdc_flow` / `dp.create_auto_cdc_from_snapshot_flow`) rather than stream–stream joins, because the entities were mutable D365 dimensions, not paired event streams.

**Limitations & gotchas**

- **No watermark or no interval predicate → unbounded state → OOM.** This is the #1 failure. Both are required; one without the other still grows state.
- **Outer joins make watermark non-negotiable**, and their NULL rows are emitted **late** by design — downstream consumers must tolerate delayed unmatched rows, not treat absence-so-far as a final NULL.
- **Append mode only.** No `update`/`complete`. If you need update-mode semantics, late-row re-joins after watermark expiry, or many-to-many joins, the built-in join can't do it — you drop to `transformWithState` (custom stateful operator, DBR 16.2+) instead.
- **`min` global watermark stalls output if one stream lags** — a stalled source delays *all* join output; monitor per-source freshness.
- **Changing a stateful join's logic** (watermark threshold, keys, interval) makes existing checkpointed state incompatible → requires a **full refresh** to rebuild state, which can lose data if a source (e.g. short-retention Kafka) no longer holds history. Keep Bronze minimally-transformed so Silver/Gold can recompute with full history.
- **Time interval predicate columns must match the watermark columns**; mismatched columns won't let the engine bound state.

**When to prefer a Materialized View instead**

Use an MV (`@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW`) when one side is effectively a **dimension/lookup that changes and must be retroactively applied**. A stream–stream (or stream–static) join never re-applies a late dimension update to facts already emitted. An MV recomputes from full inputs (incrementally where possible — note **incremental MV refresh is only available on serverless** SDP/Databricks SQL compute; on classic compute every refresh is a full recompute) so the latest dimension state is always reflected — at the cost of batch-style recompute latency instead of low-latency incremental append. Rule of thumb: paired event streams correlated within a time window → stream–stream join; fact + mutable dimension where correctness requires retroactive joins → MV.

**Interview soundbite:** A stream–stream join keeps a keyed state store on both sides, so it needs a watermark on each side plus a time-bound interval predicate to let the engine evict state and — for outer joins — delay emitting NULLs until the global (slowest-stream) watermark proves no match can still arrive; drop either ingredient and state grows unbounded.

### Stream–Snapshot (Stream–Static) Joins

**What it is**

A stream–static join (Databricks docs also call it a "stream–snapshot join") joins a **streaming source** (the fact stream — append-only, incrementally growing) to a **static/batch source** (a dimension table, read with `spark.read.table(...)` rather than `readStream`). It is the canonical pattern for **dimension enrichment / lookup**: attach customer name, region, product attributes, etc., to a fast-moving fact stream. In SDP it is the natural way to build an enriched silver streaming table.

It is **stateless** — there is no watermark, no state store, no checkpointed join state for the static side. This is the key distinction from a stream–stream join (which requires a watermark on *both* sides plus a time-bounded condition to evict state). Because there is no state, you get low latency and no unbounded-state risk.

**How it works (mechanics)**

- Per microbatch, only the **new fact rows** from the streaming source are processed (incremental). They are joined against a **snapshot** of the static Delta table — which snapshot depends on execution mode (table below).
- The static side is read as a **point-in-time snapshot** of the latest valid Delta version; there is no incremental read of the static side. *Which* version that is depends on execution mode:

| SDP execution mode | Static-side snapshot used |
|---|---|
| **Triggered** | The static table as of **the time the update started** — one consistent snapshot for the whole update. |
| **Continuous** | The **most recent version** of the static table is queried **each time the table processes an update** (i.e., the snapshot advances during the run). |

  (Pipeline mode is set in pipeline settings, not defaulted in the join code; note that materialized views and streaming tables defined in Databricks SQL always refresh in triggered mode.)
- Determinism caveat (verified, Structured Streaming join doc): if the static table changes between runs, **reprocessing the same streaming data can produce different results** — a stream–static join is non-deterministic when the static side is mutating, because each microbatch binds to whatever version is current at processing time.

**Key configs / syntax**

PySpark — stream side via `spark.readStream`, static side via `spark.read` (the asymmetry IS the join type):

```python
from pyspark import pipelines as dp

@dp.table
def customer_sales():
    return (
        spark.readStream.table("sales")
        .join(spark.read.table("customers"), ["customer_id"], "left")
    )
```

Broadcast the small static side explicitly so it ships to every executor and avoids a shuffle (the dimension is the small side):

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import broadcast

@dp.table
def customer_sales_broadcast():
    facts = spark.readStream.table("sales")
    dim = spark.read.table("customers")
    return facts.join(broadcast(dim), ["customer_id"], "left")
```

SQL — the streaming side is wrapped in `STREAM(...)`, the dimension is referenced plainly (no `STREAM`):

```sql
CREATE OR REFRESH STREAMING TABLE customer_sales
AS SELECT s.*, c.customer_name, c.region
FROM STREAM(sales) AS s
LEFT JOIN customers AS c
  USING (customer_id)
```

(The SDP doc's own snippet shows `INNER JOIN LEFT customers USING (customer_id)` — that is a doc typo; the valid form is a single join type, `LEFT JOIN` or `INNER JOIN`, as above.) You can also stream-read files directly on the fact side with `STREAM read_files(...)` and still join to a static dimension table.

**Use cases**

| Scenario | Why stream–static fits |
|---|---|
| Fact-stream dimension enrichment (orders + customer, events + device) | Dimension is slowly-changing; facts are append-only and high-volume. |
| Denormalizing a silver streaming table before gold | Stateless, low-latency, each fact row processed once. |
| Lookup against a small reference/config table | Broadcast the static side — zero shuffle. |
| My Apollo Gen2 silver layer | Enrich an STG/BRZ streaming entity (e.g., a transactional fact) against a small full-load dimension entity by reading the dimension with `spark.read.table(...)` while the fact stays `readStream`. |

**Limitations & gotchas**

- **No retroactive correction (the critical one).** Late-arriving or updated dimension rows are **NOT applied to facts already processed**. A fact joined yesterday against `customer_id=42` keeps yesterday's `customers` row even if `customers` is corrected today. SDP docs are explicit: results "are not recalculated unless a full refresh is performed." Fixes:
  - **Full refresh** the streaming table — re-joins all facts against the now-current dimension. Expensive; and dangerous if the streaming source has limited retention (a full refresh can lose data when the source no longer holds history — e.g., a short-retention Kafka source — so keep raw history in a bronze table and recompute silver/gold from it).
  - **Restructure as a materialized view (MV)** or restructure the pipeline — an MV recomputes (incremental batch recompute), so it reflects the latest dimension. Use this when retroactive accuracy matters more than streaming-once semantics. This is the SDP-doc-recommended remedy.
- **Static side must be slowly-changing.** The pattern assumes the dimension changes slowly. Rapidly mutating dimensions break the "approximately current" assumption and amplify the non-determinism above.
- **Static side assumed Delta.** The documented snapshot behavior assumes the static data is stored using Delta Lake.
- **Stale snapshot under long-running triggered updates.** In triggered mode the snapshot is frozen at update start; a very long update enriches late facts with an already-stale dimension.
- **Broadcast only when small.** If the "static" table isn't actually small, `broadcast()` can OOM executors; let the optimizer pick a shuffle/sort-merge join instead. (In SDP real-time mode specifically, only broadcast stream-to-static joins are supported — stream-to-stream joins are not.)
- **Not a stream–stream join.** No watermark, no time-bound condition, no state — do not confuse the two. If the dimension is itself a high-velocity stream you need time-bounded matching, that is a stream–stream join with watermarks on both sides.
- **Output.** A stream–static join supports append-style output; it does not produce retractions for prior dimension changes (consistent with the no-retroactive-correction rule).

**Interview soundbite:** A stream–static join is a stateless dimension lookup that snapshots the static Delta table (at update start in triggered mode, latest version each update in continuous mode), so it's fast and watermark-free — but late dimension updates never flow back into already-processed facts, so when I need retroactive correctness I either full-refresh the streaming table or rebuild it as a materialized view, and I `broadcast()` the dimension to kill the shuffle.

### Late-Arriving Data

**What it is**
A *late-arriving record* is an event whose true event-time is older than data the pipeline has already processed — it shows up "out of order." Two distinct sub-problems hide under one name: (1) **out-of-order events within a key** (a CDC update for `id=5` at `seq=4` arrives after `seq=6` already landed), and (2) **late events against a time-window aggregation** (a click timestamped 10:00 arrives at 10:09 after the 10:00–10:05 window looked closed). SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) gives a *different* mechanism for each, and each mechanism makes a different latency-vs-completeness trade. The whole topic is one tension: **streaming bounds state to stay fast and therefore drops late data; batch/MV recomputes everything and therefore loses nothing but pays latency.**

**How it works (mechanics) — the five mechanisms**

| # | Mechanism | What it handles | The trade it makes | Late record's fate |
|---|---|---|---|---|
| 1 | **Watermark** (`WATERMARK ... DELAY OF INTERVAL` / `withWatermark`) | Late events in stateful aggregations / dedup / stream-stream joins | Latency/state vs completeness | **Dropped** if beyond threshold |
| 2 | **AUTO CDC `sequence_by`** | Out-of-order CDC upserts/updates per key | None on correctness — reorders by sequence, not arrival | SCD1: stale row ignored; SCD2: lands in correct history slot |
| 3 | **Tombstone retention** (`pipelines.cdc.tombstoneGCThresholdInSeconds`, default 2 days) | Late `DELETE`s arriving out of order (SCD2) | Storage vs delete-correctness | Applied correctly if within retention; mis-applied/ignored after GC |
| 4 | **Materialized view (MV) recompute** | Any late data feeding an aggregation | Latency vs completeness (opposite of watermark) | **Never dropped** — absorbed on next refresh |
| 5 | **REPLACE WHERE flow (Beta)** | Targeted backfill / correction of a predicate range | Manual targeting vs full reprocessing | Re-evaluated into the predicate window, no streaming state |

**Mechanism 1 — Watermark: bounds state, DROPS beyond threshold.** A watermark declares a timestamp column plus a lateness tolerance. Structured Streaming tracks the max event-time seen, subtracts the threshold, and once a window's end falls below that line it closes the window and **evicts the state**. Records arriving after that are dropped (records *within* the threshold are always processed; records outside *might* be processed but it is not guaranteed). This is mandatory for incremental aggregations — without a watermark, aggregations either grow state unbounded (OOM on long-running pipelines) or fall back to full recompute every update.

```sql
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window

@dp.table
def event_counts():
    return (
        spark.readStream.table("events_raw")
            .withWatermark("event_time", "3 minutes")
            .groupBy(window("event_time", "1 minute"), "region")
            .count()
    )
```

Smaller threshold = lower latency, more drops, less state. Larger threshold = more completeness, higher latency, bigger state (more compute). For **stream-stream joins** you must set a watermark on *both* sides plus a time-bound (interval) join condition, or state grows without bound; for **outer joins** watermarking is mandatory and unmatched rows are emitted with NULLs for the missing side only **after** the lateness threshold passes (append mode delays the NULL emission until the window can no longer match). With multiple input streams the engine takes the **minimum** as the global watermark by default (safe — paces to the slowest stream); `spark.sql.streaming.multipleWatermarkPolicy = max` uses the fastest stream's watermark to cut latency **but drops data from slower streams** (Databricks says apply with caution). Note: changing a watermark threshold (or any stateful-query logic) makes the existing state incompatible — you must do a **full refresh** to rebuild state.

**Mechanism 2 — AUTO CDC `sequence_by`: reorders, does NOT drop.** This is the one that matters most for my Apollo Gen2 bronze layer. `dp.create_auto_cdc_flow` (SQL: `CREATE FLOW ... AS AUTO CDC INTO`) takes a `sequence_by` column that defines the *logical* event order, independent of arrival order. The engine reorders by sequence value, so a late row (older sequence) arriving after a newer one does the right thing automatically:
- **SCD Type 1:** the older-sequence late row will **not overwrite** a newer value already applied (the stale update is effectively dropped — the docs' own example drops the `sequenceNum=5` update because `=6` already arrived).
- **SCD Type 2:** the late row lands in its **correct historical slot** with the right `__START_AT` / `__END_AT` boundaries (these carry the propagated sequence values), rather than being appended as the latest version.

`sequence_by` must be a monotonically increasing, sortable type, with one distinct update per key per sequencing value, and **non-NULL** (NULL sequencing values are not supported). Ties or multi-column ordering use a `struct()`.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("customers_brz")

dp.create_auto_cdc_flow(
    target="customers_brz",
    source="customers_stg",
    keys=["id"],
    sequence_by="operation_date",
    apply_as_deletes="operation = 'DELETE'",
    except_column_list=["operation", "operation_date", "_rescued_data"],
    stored_as_scd_type="2",
)
```

```sql
CREATE OR REFRESH STREAMING TABLE customers_brz;

CREATE FLOW customers_brz_cdc AS AUTO CDC INTO
  customers_brz
FROM STREAM(customers_stg)
KEYS (id)
APPLY AS DELETE WHEN operation = 'DELETE'
SEQUENCE BY operation_date
COLUMNS * EXCEPT (operation, operation_date, _rescued_data)
STORED AS SCD TYPE 2;
```

> **My production scar tissue:** in Apollo Gen2 the bronze SCD2 tables sequenced by **file modification time** broke exactly here. File-mod-time is too coarse — multiple genuine CDC events for the same key shared one timestamp, so `sequence_by` had more than one update per sequencing value (which AUTO CDC requires to be distinct) and out-of-order rows landed in wrong history slots. The fix is a finer, genuinely monotonic sequence column (a source change-version / commit LSN), or a `struct(file_mod_time, secondary_monotonic_col)` to break ties.

**Mechanism 3 — Tombstone retention for late DELETEs.** With `APPLY AS DELETE WHEN` on an SCD Type 2 target, a delete cannot just remove the row — a *later-sequenced* event might still arrive and would need to "un-see" the delete. So the deleted row is temporarily retained as a **tombstone** in the underlying Delta table, and a metastore view filters tombstones out of normal reads. The tombstone is garbage-collected after `pipelines.cdc.tombstoneGCThresholdInSeconds`, **default 2 days**. If a late event for that key arrives within the window, ordering stays correct; if it arrives after GC, the tombstone is gone and correctness is lost. Set this table property to exceed your worst-case arrival-to-processing delay — Databricks explicitly recommends raising it when using Auto Loader + AUTO CDC, because Auto Loader does not guarantee file discovery/processing order in either directory-listing or file-notification mode.

```sql
CREATE OR REFRESH STREAMING TABLE customers_brz
  TBLPROPERTIES ('pipelines.cdc.tombstoneGCThresholdInSeconds' = '604800');  -- 7 days
```

**Mechanism 4 — MV recompute absorbs late data with NO drops.** A `@dp.materialized_view` (SQL: `CREATE OR REFRESH MATERIALIZED VIEW`) is a *batch* flow. You write batch semantics; on serverless pipelines the engine reprocesses only new data and changes in the sources whenever possible (incremental refresh) and falls back to full recompute otherwise — note incremental refresh is **serverless-only** (classic compute always fully recomputes; for SDP-defined MVs you must configure the pipeline as serverless). Because it re-reads the source rather than maintaining bounded streaming state, **late-arriving rows are simply picked up on the next refresh — nothing is dropped, no watermark needed.** The rule: **push late-sensitive aggregations to a materialized view.** You trade the streaming table's low latency for guaranteed completeness.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window

@dp.materialized_view
def event_counts_complete():
    return (
        spark.read.table("events_raw")
            .groupBy(window("event_time", "1 minute"), "region")
            .count()
    )
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW event_counts_complete AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM events_raw
GROUP BY time_window, region;
```

**Mechanism 5 — REPLACE WHERE flow (Beta) for targeted backfill/correction.** A `FLOW REPLACE WHERE <predicate>` defines a predicate on the target; on each run all rows matching the predicate are deleted and replaced by re-evaluating the source query for that same range — rows outside the predicate are untouched. The source must be a **batch (non-streaming) source** (a streaming source throws), so this handles late data, upstream reprocessing, and backfills **without streaming semantics (no watermark management)**, and can target a window the streaming engine would have dropped. Requires the **`PREVIEW` channel** (set the `pipelines.channel` table property to `"PREVIEW"`); Databricks recommends Unity Catalog + serverless (incremental refresh of the flow is serverless-only). `BY NAME` is required and the predicate must be deterministic. Gotcha: a **full refresh re-runs the source query using only the current predicate** — if a 7-day-predicate pipeline ran for a year, a full refresh leaves only the last 7 days and permanently deletes older rows. Guard with `pipelines.reset.allowed = 'false'`. (`REPLACE WHERE` and `ONCE` are mutually exclusive.)

```sql
CREATE OR REFRESH STREAMING TABLE orders_enriched
  TBLPROPERTIES (
    'pipelines.channel' = 'PREVIEW',
    'pipelines.reset.allowed' = 'false'
  )
  FLOW REPLACE WHERE event_date >= date_add(current_date(), -7) BY NAME
  AS SELECT * FROM source_orders;
```

(Classic one-shot backfill without REPLACE WHERE uses an append-once flow — `@dp.append_flow(once=True)` / SQL `CREATE FLOW ... AS INSERT INTO ... ONCE ... BY NAME` — which runs exactly once and re-runs only on full refresh.)

**Use cases**
- Windowed metrics tolerant of small drops, low-latency dashboards → **watermark** on a streaming table.
- CDC bronze ingestion (my 211 BRZ SCD2 tables) → **`sequence_by`** handles out-of-order updates; **tombstone retention** handles late deletes.
- Late-sensitive financial/regulatory aggregations where dropping is unacceptable → **materialized view**.
- One-off correction of a bad day's data or initial historical load → **REPLACE WHERE (Beta)** or **append-once** flow.

**Limitations & gotchas**
- **The stream-snapshot non-retroactive trap.** When a streaming table joins a *static* dimension (a stream-static / stream-snapshot join), the static side is snapshotted at stream/update start (triggered pipelines query the static table as of update start; continuous pipelines query the latest version each update). A late-arriving *dimension* update is **not retroactively applied** to facts already processed. There is no watermark or `sequence_by` for the static side. If retroactive correction is required, restructure as a **materialized view** (recomputes the join) or stream both sides.
- Watermark drops are **silent** — beyond-threshold records vanish with no error. The `numRowsDroppedByWatermark` state-operator metric in `StreamingQueryProgress` gives an (imprecise) signal; monitor it before trusting a threshold.
- `sequence_by` on a too-coarse column (file modification time) silently violates the one-distinct-update-per-sequencing-value requirement and mis-orders ties — the Apollo Gen2 incident. Use a genuinely monotonic key.
- Tombstone GC at 2 days is often too short for batch/daily file-drop pipelines; a late DELETE after GC corrupts SCD2 history.
- AUTO CDC source must be a true streaming, append-only source; reading a *mutable* source as a stream throws on encountering a change/deletion (my "streaming-on-mutable-source" incident — fix with the `skipChangeCommits` reader option, or read it as an MV which has no append-only restriction).
- Stacking SCD2 on top of an SCD2 source double-counts history boundaries (my "SCD2-on-SCD2" incident) — sequence the downstream off the upstream's `__START_AT`, or consume the upstream as a non-historized view.

**Interview soundbite:** "Late data is a latency-vs-completeness dial: a streaming table with a watermark bounds state and silently drops anything past the threshold, AUTO CDC `sequence_by` reorders out-of-order events losslessly per key (and tombstone retention — default 2 days — covers late deletes), while a materialized view recompute drops nothing at the cost of latency — so I push late-sensitive aggregations to an MV and only stream what can tolerate drops."

### Triggered vs Continuous Execution Mode

**What it is**
Execution mode is the **pipeline-level lifecycle setting** for a Spark Declarative Pipelines (SDP) / Lakeflow Declarative Pipelines update. It answers one question: *after the pipeline computes its tables, does it stop or keep running?* Two values:

- **Triggered** — refresh every table once based on the data available when the update started, then **stop** and tear the cluster down. Batch-like, cheap, the default.
- **Continuous** — keep the cluster alive and ingest new data **as it arrives** to keep every table fresh until you manually stop it. Always-on, low-latency, costlier.

This is controlled by a single boolean pipeline property, `continuous`, whose **default value is `false`** (i.e. triggered). It is set via the **Pipeline mode** option in pipeline settings, or directly in the pipeline JSON. Pipeline mode is **independent of table type** — both `@dp.table` streaming tables and `@dp.materialized_view` materialized views run under either mode.

**Critical distinction — execution mode is NOT deployment mode.** These are two orthogonal axes that interview candidates routinely conflate:

| Axis | Values | Controls | Where set |
|---|---|---|---|
| **Execution / trigger mode** (this topic) | Triggered vs Continuous | Does the update stop or stay running? | `continuous: true/false` pipeline property |
| **Deployment mode** | Development vs Production | Cluster reuse, retry behavior, dev-tagging, schedule pausing | `development: true/false` (set by Databricks Asset Bundle `mode: development`/`production`, or the Dev/Prod toggle in the UI) |

A pipeline can be any of the four combinations — e.g. *triggered + development* (fast-iterate ETL), or *continuous + production* (always-on stream). Mixing them up ("continuous mode means production") is a wrong answer.

**How it works (mechanics)**

*Triggered:* The update starts a cluster, discovers the dataset graph, computes each dataset exactly once against the snapshot of source data at update start, writes results, and shuts the cluster down. New data that lands *after* the update started is not processed until the next trigger. Triggering can come from the **Run now** button, a schedule, the Pipelines API, or — importantly — a **Pipeline task inside a Lakeflow Job** (only triggered pipelines can be a job task; continuous pipelines cannot, since triggering an always-on pipeline is redundant).

*Continuous:* The cluster stays up and each flow runs as a long-lived streaming/repeating query. To avoid wasted recompute, SDP **automatically monitors dependent Delta tables and performs an update on a downstream dataset only when the contents of those dependent tables actually change** — so a continuous pipeline isn't blindly recomputing materialized views every interval. Continuous pipelines use automatic retry/restart behavior (restart the cluster for specific recoverable errors such as memory leaks and stale credentials; retry on errors such as a failure to start a cluster), the same reliability profile that Jobs- and API-triggered updates get.

**Inside Structured Streaming (the layer below pipeline mode).** Each flow in an SDP pipeline is ultimately a Structured Streaming query, and Structured Streaming has its own `trigger(...)` on the `DataStreamWriter`. Pipeline mode maps onto these:

| Streaming trigger | Syntax | Semantics | Maps to pipeline mode |
|---|---|---|---|
| `availableNow=True` | `.trigger(availableNow=True)` | Process **all available data in multiple micro-batches, then terminate**. Supports sizing (e.g. `maxBytesPerTrigger` / `maxFilesPerTrigger`; sizing options vary by source). This is the engine behind triggered SDP. | Triggered |
| `processingTime='10 seconds'` | `.trigger(processingTime='10 seconds')` | Fixed-interval micro-batches; checks for new data every interval. Balances cost vs latency. | Continuous (via `pipelines.trigger.interval`) |
| Unspecified (default) | N/A | Equivalent to `processingTime='0 seconds'` — runs as fast as possible, processing continuously as long as new data arrives (general-purpose ~3–5 s latency per the docs). Can drive high cloud-storage API cost. | n/a (raw streaming) |
| `realTime='5 minutes'` | `.trigger(realTime='5 minutes')` | Real-time mode; end-to-end tail latency under 1 s (commonly ~300 ms, as low as ~5 ms). The string sets the long-running batch duration. Public Preview. | Continuous + real-time |
| `continuous='1 second'` | `.trigger(continuous='1 second')` | Spark OSS experimental continuous *processing* (experimental since Spark 2.3). **Not supported / not recommended on Databricks** — use real-time mode instead. Unrelated to SDP "continuous pipeline mode" despite the name collision. | — |

Note: `Trigger.Once` is **deprecated** (since Databricks Runtime 11.3 LTS) — migrate to `Trigger.AvailableNow`. On **serverless** compute, only `Trigger.AvailableNow()` and `Trigger.Once()` are supported (Databricks recommends `AvailableNow`); time-based triggers (`Trigger.ProcessingTime`/`Trigger.Continuous`) are blocked, and a streaming query with **no** explicit trigger fails with `INFINITE_STREAMING_TRIGGER_NOT_SUPPORTED` (because Spark defaults to `Trigger.ProcessingTime("0 seconds")`). For an always-on stream on serverless you must use an SDP pipeline in continuous mode.

**Key configs / syntax**

Setting the mode in the pipeline JSON / settings:

```json
{
  "continuous": false
}
```

```json
{
  "continuous": true
}
```

For a continuous pipeline you tune freshness/cost with `pipelines.trigger.interval` — how often each flow starts an update. This setting is **only meaningful in continuous mode** (a triggered pipeline processes each table once). Databricks recommends setting it **per table** because streaming vs complete (batch) queries have different defaults.

Per-table in Python:

```python
from pyspark import pipelines as dp

@dp.table(
    spark_conf={"pipelines.trigger.interval": "10 seconds"}
)
def events_bronze():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "json")
        .load("/Volumes/main/raw/events")
    )
```

Per-table in SQL:

```sql
SET pipelines.trigger.interval = 10 seconds;

CREATE OR REFRESH STREAMING TABLE events_bronze
AS SELECT * FROM STREAM read_files('/Volumes/main/raw/events', format => 'json');
```

Whole-pipeline (rarely needed) via the `configuration` object:

```json
{
  "continuous": true,
  "configuration": {
    "pipelines.trigger.interval": "10 seconds"
  }
}
```

`pipelines.trigger.interval` **defaults by flow type:**

| Flow type | Default interval |
|---|---|
| Streaming queries | 5 seconds |
| Complete (batch) queries, all inputs Delta | 1 minute |
| Complete (batch) queries, some inputs non-Delta | 10 minutes |

Valid units: `second(s)`, `minute(s)`, `hour(s)`, `day(s)` — singular or plural, e.g. `"30 second"`, `"1 hour"`.

Real-time mode (continuous + sub-second, requires an explicit update flow) layers on top:

```python
from pyspark import pipelines as dp

dp.create_sink(
    "alerts_out",
    "kafka",
    {"kafka.bootstrap.servers": "<server:port>", "topic": "alerts"},
)

@dp.update_flow(
    name="realtime_flow",
    target="alerts_out",
    spark_conf={
        "pipelines.trigger": "RealTime",
        "pipelines.trigger.interval": "5 minutes",
    },
)
def realtime_flow():
    return (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", "<server:port>")
        .option("subscribe", "txns")
        .load()
    )
```

with `spark.databricks.streaming.realTimeMode.enabled = true` set in the pipeline Spark config. Real-time mode is Public Preview on Databricks Runtime 18.1.3 (SDP preview channel).

**Use cases**

- **Triggered** — the right choice for the vast majority of pipelines. Scheduled batch/incremental ETL with 10-minute, hourly, or daily freshness. Cluster spins up, processes the backlog, tears down → minimal cost. Required if you want to orchestrate the pipeline as a **Lakeflow Job task**.
- **Continuous** — only when freshness needs to be in the **seconds-to-minutes** range (the docs target ~10 s to a few minutes). Operational dashboards, low-latency ingest where always-on cost is justified.
- **Real-time mode** (continuous variant) — ultra-low-latency operational workloads needing sub-second response: fraud detection, real-time personalization.

For my Apollo Gen2 pipelines (211 STG streaming tables + 211 Bronze SCD2 tables fed from ADLS `incoming/`), every SDP pipeline runs **triggered**: JOB2 is kicked off after JOB1's preprocessing notebook lands the files, so there's no benefit to an always-on cluster — the data arrives in discrete batches from the Synapse Link → ADLS flow, and triggered mode lets the cluster tear down between runs to keep cost down. Continuous would burn an always-on cluster waiting on a source that only updates in batches.

**Limitations & gotchas**

- **`continuous` defaults to `false`** — forgetting this and assuming always-on is a common error.
- **Continuous = always-on cluster = significantly more expensive.** Don't reach for it just to "be modern"; justify it with a real sub-minute SLA.
- **Continuous pipelines can't be a Job task** — only triggered pipelines can be triggered by a Pipeline task in a Lakeflow Job.
- **DBSQL-defined** materialized views and streaming tables **always refresh in triggered mode**, regardless of any pipeline setting.
- **`pipelines.trigger.interval` is ignored in triggered mode** — it only governs continuous flows.
- **Name-collision trap:** Structured Streaming's experimental `Trigger.Continuous` (`continuous='1 second'`) is *not* the same thing as SDP continuous pipeline mode, and Databricks does not support that streaming trigger — use real-time mode. Stating they're the same is wrong.
- **Serverless:** time-based streaming triggers are unavailable; an always-on stream on serverless must be an SDP continuous pipeline, not a hand-rolled `.trigger(processingTime=...)` query. A serverless streaming query with no explicit trigger fails with `INFINITE_STREAMING_TRIGGER_NOT_SUPPORTED`.
- **Don't conflate with dev/prod deployment mode** — different axis, different property (`development` vs `continuous`).

**Interview soundbite:** "Triggered vs continuous is the SDP execution axis — `continuous` defaults to false, so the pipeline refreshes every table once off the data available at start and tears the cluster down (cheap, schedulable as a Job task); flip `continuous: true` only for a real seconds-to-minutes SLA, where the cluster stays up and `pipelines.trigger.interval` governs freshness — and it's a completely separate axis from the dev/prod *deployment* mode."

### Streaming Optimization

**What it is**
A toolkit of levers to make Spark Declarative Pipelines (SDP / Lakeflow Declarative Pipelines) streaming tables — `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` — run with bounded state, bounded memory, predictable latency, and clean file layout. In Apollo Gen2 these matter directly: 211 STG streaming tables feeding 211 Bronze SCD2 tables (`create_auto_cdc_flow`) — any unbounded state or small-files problem multiplies across 422 pipelines. The two-job split exists precisely because SDP can't run arbitrary Python, so all tuning happens via dataset decorators, the pipeline `configuration` / `spark_conf`, and source-reader options.

**How it works (mechanics)**

Each lever attacks one cost: state size, microbatch size, file layout, skew, or checkpoint latency. Define each term on first use; concrete defaults below are doc-verified against current Databricks docs.

**1. Watermark — bound state for stateful ops.**
A *watermark* is a time threshold telling Spark "no more late data past this point" so it can evict (drop) intermediate state and emit results. Without it, aggregations / joins / dedup grow state without bound → high latency → out-of-memory (OOM). For aggregations, watermark is *mandatory* for incremental processing — otherwise the materialized result is fully recomputed each update. Concretely: a 3-minute watermark on a stream-stream join means once event time advances 3 min past a row, that row's state is purged; a click arriving 4 min after its impression is dropped. Trade-off: smaller threshold = lower latency + smaller state but more dropped late records; larger threshold = more completeness but more state and compute.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window

@dp.table()
def profit_by_hour():
    return (
        spark.readStream.table("sales")
            .withWatermark("timestamp", "1 hour")
            .groupBy(window("timestamp", "1 hour").alias("time"))
            .aggExpr("sum(profit) AS profit")
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE gold.adImpressionSeconds AS
SELECT impressionAdId,
       window(clickTimestamp, "5 minutes") AS impressions_window,
       sum(impressionSeconds) AS totalImpressionSeconds
FROM STREAM(silver.adImpressionClicks)
WATERMARK clickTimestamp DELAY OF INTERVAL 3 MINUTES
GROUP BY impressionAdId, window(clickTimestamp, "5 minutes");
```

Stream-stream join: watermark on **both** sides + a time-bounded join condition — omit either and state grows forever. Because each source has an incomplete view, the streaming engine keeps one global watermark based on the slowest stream.

```sql
CREATE OR REFRESH STREAMING TABLE silver.adImpressionClicks AS
SELECT imp.userId, impressionAdId, clickTimestamp, impressionSeconds
FROM STREAM(bronze.rawAdImpressions)
  WATERMARK impressionTimestamp DELAY OF INTERVAL 3 MINUTES imp
INNER JOIN STREAM(bronze.rawClicks)
  WATERMARK clickTimestamp DELAY OF INTERVAL 3 MINUTES click
ON imp.userId = click.userId
AND clickAdId = impressionAdId
AND clickTimestamp >= impressionTimestamp
AND clickTimestamp <= impressionTimestamp + interval 3 minutes;
```

**2. Trigger interval matched to data volume — fix the small-files problem.**
*Cause:* every microbatch commit writes at least one file per shuffle partition per stateful table. Triggering too frequently on a low-volume source (e.g., continuous mode on a trickle) produces thousands of tiny files. *Why it hurts reads:* each file needs a separate metadata lookup + I/O round trip, and cloud-storage LIST APIs throttle at scale — so downstream reads (and the next SCD2 layer) crawl. *Fix:* pick a trigger cadence that lets a meaningful amount of data accumulate between updates. Databricks default and recommendation is **triggered mode on a schedule**, not continuous, for the vast majority of pipelines. Continuous mode is only for seconds-to-minutes latency; real-time mode for sub-second. In Apollo Gen2, JOB2 running triggered on a schedule (rather than continuous) is the correct default — it batches each entity's incoming files into fewer, larger Bronze files.

```python
from pyspark import pipelines as dp

@dp.table()
def stg_account():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.maxFilesPerTrigger", 1000)
            .load("/Volumes/raw/incoming/account")
    )
```

| Pipeline mode | Latency | File-layout effect | When |
|---|---|---|---|
| Triggered (default) | minutes–hours | Larger files, fewer commits | Default; vast majority of pipelines (Apollo JOB2) |
| Continuous | seconds–minutes | More commits → small-files risk | Only if sub-minute freshness required |
| Real-time (`spark.databricks.streaming.realTimeMode.enabled`) | sub-second / ms | N/A (Kafka source+sink) | Fraud, ops alerting; Public Preview, requires continuous=true + an `@dp.update_flow` with `pipelines.trigger="RealTime"`; Kafka/Event Hubs/MSK only, Delta not supported as source or sink |

**3. RocksDB state store + changelog checkpointing — handle large state.**
RocksDB is an embedded key-value store that spills state to local disk instead of holding it all in JVM heap, so it survives large state (big joins, wide dedup) without OOM. *Changelog checkpointing* writes only records that changed since the last checkpoint (a delta) to durable storage, instead of snapshotting + uploading whole SST files every batch — cutting checkpoint duration and end-to-end latency. Defaults (doc-verified): RocksDB is the **default state store provider in DBR 17.3 and above** and changelog checkpointing is **enabled by default in 17.3 and above** (changelog checkpointing itself is available from DBR 13.3 LTS). Below 17.3 you must enable both explicitly. **Serverless pipelines manage state store config automatically** — you don't set this. For classic-compute SDP, set in the pipeline JSON `configuration`:

```json
{
  "configuration": {
    "spark.sql.streaming.stateStore.providerClass":
      "com.databricks.sql.streaming.state.RocksDBStateStoreProvider"
  }
}
```

```python
spark.conf.set(
    "spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled", "true")
```

Gotcha: the state-management scheme can't change across restarts — switching to RocksDB on an existing checkpoint requires a **new checkpoint location** (full refresh). (Note: changelog checkpointing alone *can* be enabled on an existing stream while preserving state; it's the in-memory→RocksDB provider switch that forces a new checkpoint.)

**4. numShufflePartitions sized to state — state stores are per shuffle partition.**
State is sharded one store instance per shuffle partition, so partition count *is* your state parallelism. Too few = giant per-partition stores + skew; too many = file/metadata overhead. Databricks recommendation for stateful queries: set shuffle partitions to **1–2× the total cores** in the cluster.

```json
{ "configuration": { "spark.sql.shuffle.partitions": "64" } }
```

Critical gotcha (verified): partition count is **fixed at checkpoint creation** — changing `spark.sql.shuffle.partitions` has no effect on an existing stateful checkpoint; you'd need a new checkpoint. (Stateless queries support dynamic shuffle-partition changes without a new checkpoint in DBR 18.0+; on-demand stateful repartitioning via `spark.sql.streaming.stateStore.partitions` without losing state exists only in DBR 18.3+, and requires the RocksDB state store.) On serverless SDP, leave shuffle partitions to the platform, so don't hand-tune unless on classic compute.

**5. maxFilesPerTrigger / maxBytesPerTrigger — bound the microbatch.**
*Admission controls* cap how much each microbatch ingests, preventing one huge batch from causing spill, OOM, or cascading delays.

| Option | Default | Meaning |
|---|---|---|
| `maxFilesPerTrigger` (`cloudFiles.maxFilesPerTrigger` for Auto Loader) | 1000 (Delta & Auto Loader; no max for other file sources) | Hard upper bound on files per microbatch |
| `maxBytesPerTrigger` (`cloudFiles.maxBytesPerTrigger`) | None | Soft max on bytes; can exceed if smallest input unit is bigger (e.g., 10g limit + 3 GB files → processes 12 GB) |
| `maxOffsetsPerTrigger` (Kafka) | None | Approx records per microbatch from Kafka |

When both file and byte limits are set, the batch stops at whichever is hit **first** (the lower limit). Two notes for Apollo Gen2: (a) on **serverless SQL-warehouse** streaming tables, leave both unset to let dynamic admission control auto-scale; (b) in **DBR 18.0+**, `cloudFiles.maxFilesPerTrigger` is dynamically configured and need not be set manually (this DBR 18.0 auto-config applies to the *files* limit, not `maxBytesPerTrigger`). This is the direct lever when JOB1 dumps an unusually large incoming/ batch and JOB2's STG read would otherwise OOM.

```python
from pyspark import pipelines as dp

@dp.table()
def stg_account():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .option("cloudFiles.maxBytesPerTrigger", "10g")
            .load("/Volumes/raw/incoming/account")
    )
```

**6. Liquid clustering — layout & pruning.**
Liquid clustering replaces static `PARTITIONED BY` + `ZORDER` with self-tuning, skew-resistant, incremental data layout; you can change clustering keys without rewriting the table. It clusters data so queries filtering on the keys skip (prune) irrelevant files. Supported on streaming tables and materialized views, including in SDP. `CLUSTER BY AUTO` lets Databricks pick keys from workload history (requires predictive optimization, which runs the key selection + clustering asynchronously as a maintenance op). Mutually exclusive with `PARTITIONED BY`.

```sql
CREATE OR REFRESH STREAMING TABLE events
CLUSTER BY AUTO
AS SELECT * FROM STREAM read_files("/Volumes/raw/events", format => "parquet");
```

```python
from pyspark import pipelines as dp

# Explicit keys:
@dp.table(cluster_by=["event_date", "region"])
def events():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "parquet")
            .load("/Volumes/raw/events"))

# Automatic key selection: @dp.table(cluster_by_auto=True)
```

For Apollo Bronze SCD2, clustering on the business key + `__START_AT` makes point-in-time and current-version reads prune hard.

**7. Salt skewed join / groupBy keys.**
*Skew* = a few key values hold most rows, so a few tasks do all the work (hotspots) and stretch update time. *Salt* = append a random bucket suffix to the hot key, aggregate in **two stages** (partial per salted key, then re-aggregate dropping the salt), spreading the load. For skew in *stored* tables, use liquid clustering instead.

```python
from pyspark.sql.functions import col, floor, rand

partial = (df.withColumn("salt", floor(rand() * 16))
             .groupBy("hot_key", "salt").agg({"amount": "sum"}))
final = partial.groupBy("hot_key").agg({"sum(amount)": "sum"})
```

**8. Broadcast small dimensions.**
If one join side is a small dim table, broadcast it to every executor and skip the shuffle entirely — far cheaper than a shuffle (sort-merge) join. Use a `BROADCAST` hint (SQL) or `broadcast()` (Python). In SDP real-time mode, only stream-to-static **broadcast** joins are supported (stream-stream is not).

```sql
CREATE OR REFRESH MATERIALIZED VIEW enriched_orders AS
SELECT o.*, /*+ BROADCAST(p) */ p.product_name, p.category
FROM orders o JOIN products p ON o.product_id = p.product_id;
```

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import broadcast

@dp.materialized_view
def enriched_orders():
    orders = spark.read.table("orders")
    products = spark.read.table("products")
    return orders.join(broadcast(products), "product_id")
```

**9. asyncProgressTracking — cut offset-commit latency.**
Normally Spark must persist offsets (`offsetLog`) and commits (`commitLog`) *before* the next microbatch proceeds, so offset I/O sits on the critical path. Async progress tracking commits offsets/commits asynchronously, removing that blocking step. Options: `asyncProgressTrackingEnabled` (default `false`), `asyncProgressTrackingCheckpointIntervalMs` (default `1000`). Limits (verified): for **Kafka sinks, async progress tracking only supports stateless pipelines**; incompatible with `Trigger.once` / `Trigger.availableNow` (the query fails if enabled); no exactly-once guarantee (offset ranges can shift on failure). This is a high-throughput Kafka-sink lever, not for Apollo's Delta-sink SCD2 tables.

```python
(stream.writeStream
    .format("kafka")
    .option("topic", "out")
    .option("checkpointLocation", "/Volumes/cat/sch/vol/cp")
    .option("asyncProgressTrackingEnabled", "true")
    .option("asyncProgressTrackingCheckpointIntervalMs", "5000")
    .start())
```

**10. Drop unnecessary stateful ops.**
Every stateful operator (aggregation, `dropDuplicates`/`dropDuplicatesWithinWatermark`, stream-stream join, custom `transformWithState`) keeps state, adds a shuffle, and adds checkpoint cost. Cheapest state is the state you never keep: filter/project before the stateful op; use a static broadcast join instead of stream-stream where one side is a slow-changing dim; push dedup upstream so downstream tables stay stateless. In Apollo Gen2, the STG layer is deliberately a near-passthrough streaming table (stateless append) so all the SCD2 state lives in exactly one place — the Bronze `create_auto_cdc_flow` — rather than being duplicated across both layers (the SCD2-on-SCD2 incident is what you get when you don't).

**Key configs / syntax**

| Lever | Knob | Default | Set where |
|---|---|---|---|
| Watermark | `withWatermark()` / `WATERMARK ... DELAY OF INTERVAL` | none | dataset query |
| Trigger cadence | triggered vs continuous | triggered | pipeline mode |
| RocksDB | `spark.sql.streaming.stateStore.providerClass` | RocksDB in DBR 17.3+ | pipeline `configuration` (auto on serverless) |
| Changelog ckpt | `...rocksdb.changelogCheckpointing.enabled` | true in 17.3+ | spark conf |
| Shuffle partitions | `spark.sql.shuffle.partitions` | platform-managed on serverless | pipeline config; fixed at checkpoint |
| File admission | `cloudFiles.maxFilesPerTrigger` | 1000 (auto-configured in DBR 18.0+) | source reader option |
| Byte admission | `cloudFiles.maxBytesPerTrigger` | None | source reader option |
| Kafka admission | `maxOffsetsPerTrigger` | None | Kafka reader option |
| Layout/pruning | `CLUSTER BY AUTO` / `cluster_by=[...]` / `cluster_by_auto=True` | off | DDL / `@dp.table` |
| Async commits | `asyncProgressTrackingEnabled` | false | writeStream option (Kafka sink, stateless) |

**Use cases**
- High-cardinality aggregation / dedup with growing memory → watermark + RocksDB + changelog.
- Trickle source writing thousands of tiny files → triggered mode + longer interval (small-files fix).
- One executor stuck at 100% while others idle → salt the skewed key, or liquid-cluster the table.
- Star-schema enrichment → broadcast the dimension.
- Catch-up after backlog blows up the microbatch → `maxFilesPerTrigger` / `maxBytesPerTrigger`.
- Kafka-to-Kafka stateless throughput → asyncProgressTracking.

**Limitations & gotchas**
- Shuffle-partition count and state-store scheme are **frozen at checkpoint creation** — changing them on an existing stateful stream requires a new checkpoint (full refresh) unless you're on DBR 18.3+ on-demand stateful repartitioning (DBR 18.0+ for stateless dynamic shuffle partitions).
- Stream-stream join without watermarks on **both** sides + a time-bound condition = unbounded state.
- `maxBytesPerTrigger` is a **soft** max — a single oversized input unit overshoots it.
- asyncProgressTracking: Kafka sink = stateless only, fails under `Trigger.availableNow`/`Trigger.once`, no exactly-once.
- On **serverless** SDP, don't hand-set RocksDB/shuffle/admission configs — serverless manages state config and uses dynamic admission control; manual settings can hurt.
- Liquid clustering: updated rows aren't auto-re-clustered (`OPTIMIZE` needed); can't combine with `PARTITIONED BY`; can't change clustering keys of a streaming table / MV via `ALTER TABLE`.
- Watermark too small drops late data silently; too large bloats state and compute — must be tuned + monitored against the event-log `flow_progress` metrics.

**Interview soundbite:** "I bound state with watermarks, bound the microbatch with maxFilesPerTrigger/maxBytesPerTrigger, size shuffle partitions to 1–2x cores knowing state stores are per-partition and frozen at the checkpoint, run RocksDB with changelog checkpointing for large state, fix small-files by matching trigger cadence to volume, and kill skew with salting plus liquid clustering — and on serverless I let SDP manage most of that automatically."

### Streaming Table — Full Refresh vs Incremental Refresh

**What it is**

A streaming table (ST) in SDP (Spark Declarative Pipelines — `@dp.table` in Python, `CREATE OR REFRESH STREAMING TABLE` in SQL) is a *stateful, append-only* sink built on Structured Streaming. Every flow writing into it owns an internal **checkpoint** (an offset log that records "where in the source I last read"). The *update mode* you pick decides whether that checkpoint is honored or wiped:

| Mode | What it does to data | What it does to checkpoints | Reads from source |
|---|---|---|---|
| **Refresh (default / incremental)** | Keeps existing rows, **appends** new ones | Honored — resumes from last committed offset | Only NEW records since last checkpoint |
| **Full refresh** | **Truncates** all existing data + metadata | **Removed** + new checkpoints created per flow | ALL records the source still retains, from the beginning |
| **Reset streaming flow checkpoints** | Keeps existing rows (no truncate) | Cleared for selected flows only | Reprocesses all source records into the existing table |

Incremental is the normal, every-update behavior. Full refresh is the explicit "clear and rebuild from scratch" button — and it is the dangerous one when the source no longer holds full history.

**How it works (mechanics)**

*Incremental (default `REFRESH`):* The per-flow checkpoint is keyed by **flow name**. If you set no explicit flow name, the default flow name is the fully qualified target table name (`catalog.schema.table`); if you named the flow (e.g. `flow_name=` on `create_auto_cdc_flow`), it is `catalog.schema.flow_name`. On each pipeline update the flow reads the source's offset log, finds offsets greater than the last committed checkpoint, processes only those, and advances the checkpoint. This is why an append-only source (Auto Loader / `read_files`, Delta append, Kafka) is required — by default streaming tables require append-only sources. To incrementally consume a Delta source that has in-place updates/deletes, set `skipChangeCommits` on the `spark.readStream` (it ignores file-changing operations and processes only appends; in Databricks Runtime 12.2 LTS and above it replaces the legacy `ignoreChanges` option). `skipChangeCommits` cannot be used when the source ST is the target of `create_auto_cdc_flow`.

*Full refresh:* "discards all existing data and metadata and restarts the stream from the beginning." Concretely it **(1) truncates the streaming table, (2) removes all checkpoint data, (3) restarts the streaming process with new checkpoints for every flow writing to the table.** Because the checkpoint is gone, the flow re-reads the *entire current contents of the source* — not the data that was previously in the table. If the source has aged data out, those rows are simply gone:

| Data source | Reason input data is absent | Outcome of full refresh |
|---|---|---|
| Kafka | Short retention threshold (e.g. 24h) | Records no longer present in Kafka are dropped from the target |
| Files in object storage | Lifecycle / TTL policy aged files out | Deleted files are dropped from the target |
| Records in a table | Deleted for compliance | Only records still present in the source are processed |

This is the core trap: after a full refresh the table can have **fewer rows than before**, because "full" means "everything the source *currently* has," not "everything the table once had."

**When a full refresh is actually required** (doc-verified scenarios — a `REFRESH` alone will *not* pick up these because the checkpoint/state is incompatible):
- **Stateful-logic changes** — modifying aggregation grouping keys or aggregate functions; adding/removing aggregations; changing join keys/types; adding/removing joins; changing deduplication columns or dedup logic.
- **Schema changes (non-backward-compatible)** — renaming columns without column-mapping mode; changing dedup columns; type narrowing (`BIGINT→INT`, `DOUBLE→FLOAT`); incompatible type changes (`STRING→INT`); hard deletion of a column. (Adding a column is generally safe — no full refresh.)
- **Physical layout changes** — e.g. migrating legacy partitioning to a new clustering scheme.
- **Upstream source changes** — modifying source tables read by the query; switching source type (Kafka→Delta, Auto Loader→Kafka); changing source location/path/Kafka topic; dropping-and-recreating a source Delta table *even if the schema is identical*.
- **Corruption / data-continuity** — checkpoint directory or schema-tracking files corrupted/deleted; CDC logs expired.

**Key configs / syntax**

Trigger a full refresh of one ST in SQL. The grammar is `REFRESH { MATERIALIZED VIEW | [ STREAMING ] TABLE } table_name [ FULL | { SYNC | ASYNC } ]` — `STREAMING` is an optional keyword, so `REFRESH STREAMING TABLE` and `REFRESH TABLE` are equivalent (not a legacy form):

```sql
REFRESH STREAMING TABLE sales FULL;
-- STREAMING is optional in the grammar; this is equivalent:
REFRESH TABLE sales FULL;
```

In SDP you usually trigger full refresh from the **pipeline UI** ("Full Refresh" button) or selectively via the REST API. **Selective full refresh of chosen tables** (refresh only specific tables full while others run a normal refresh) uses `full_refresh_selection`, which takes a list of *tables/datasets* (not flow names):

```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{ "full_refresh_selection": ["my_catalog.my_schema.sales"] }' \
  https://<host>/api/2.0/pipelines/<pipeline-id>/updates
```

**Reset only the checkpoint** (reprocess all source rows into the *existing* table without truncating — the safer middle ground; risk is duplicate rows unless the writer is idempotent, e.g. an AUTO CDC target). `reset_checkpoint_selection` takes a list of **flow names** that MUST be fully qualified `catalog.schema.flow_name`; a bare name throws `IllegalArgumentException` (the default flow name equals the fully qualified target table name):

```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{ "reset_checkpoint_selection": ["my_catalog.my_schema.customers_incremental_flow"] }' \
  https://<host>/api/2.0/pipelines/<pipeline-id>/updates
```

**Protect a table from being wiped** — `pipelines.reset.allowed` (default `true`). Set to `false` to forbid full refresh on that table (does NOT block incremental writes / new data flowing in — it only blocks the destructive reset). This is the guardrail for any table holding data the source can no longer replay (backfilled data, manual deletes you want retained):

```sql
CREATE OR REFRESH STREAMING TABLE raw_user_table
TBLPROPERTIES (pipelines.reset.allowed = false)
AS SELECT * FROM STREAM read_files("/Volumes/.../data-user", format => "csv");

CREATE OR REFRESH STREAMING TABLE bmi_table
AS SELECT userid, (weight/2.2) / pow(height*0.0254, 2) AS bmi
FROM STREAM(raw_user_table);
```

Same protection in Python:

```python
from pyspark import pipelines as dp

@dp.table(
    name="raw_user_table",
    table_properties={"pipelines.reset.allowed": "false"},
)
def raw_user_table():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .load("/Volumes/.../data-user")
    )

@dp.table(name="bmi_table")
def bmi_table():
    return (
        spark.readStream.table("raw_user_table")
            .selectExpr("userid", "(weight/2.2) / pow(height*0.0254, 2) AS bmi")
    )
```

**Medallion mitigation** — keep a **full-history bronze ST** (flexible types like `STRING`/`VARIANT`, ideally `pipelines.reset.allowed=false`) so that when a downstream silver/gold ST needs a full refresh (stricter types, schema change), it rebuilds from the durable bronze table instead of from a short-retention raw source. The bronze table absorbs source volatility; the downstream tables become safely re-refreshable. **Append-once backfill** (`@dp.append_flow(once=True)` in Python / `CREATE FLOW ... AS INSERT INTO ONCE` in SQL) lets you re-add historical data after a full refresh without re-running a full refresh on the bronze table; the `once` flow stays idle in the graph and auto-reruns only when the pipeline is fully refreshed.

**Use cases**

- **Incremental:** every normal scheduled/triggered update — the 211 STG streaming tables in Apollo Gen2 run incremental on each JOB2 run, consuming only the new files JOB1 dropped into `incoming/`.
- **Full refresh:** one-off recovery or migration — corrupted checkpoint, a stateful-logic change, a non-backward-compatible schema change, or switching a flow's source.
- **Selective full refresh:** dev iteration on a single table, or rebuilding just the failed table without re-running the whole pipeline.
- **Checkpoint reset:** rewind-and-replay when you must preserve existing rows but reprocess source (only safe with idempotent writers like AUTO CDC targets).

**Limitations & gotchas**

- A full refresh "does not reprocess data unless your source retains the full historical dataset" — on Kafka/aged-out files this **silently shrinks** the table. This is invisible until you compare row counts.
- **Downstream cascade:** if an ST is full-refreshed, dependent downstream tables fail until they are *also* full-refreshed — unless the upstream ST has `skipChangeCommits` enabled. Downstream materialized views must be full-refreshed too.
- Full refresh on large tables is costly/slow; downstream consumers may see incomplete results mid-refresh.
- In **Apollo Gen2** terms: a careless full refresh of a Bronze SCD2 table fed by `create_auto_cdc_flow` would wipe the SCD2 history and re-derive it from whatever the source still has — if the upstream `incoming/` files were lifecycle-deleted, the rebuilt history is incomplete. Protect SCD2 bronze with `pipelines.reset.allowed=false` and rely on checkpoint reset + idempotent AUTO CDC instead, since the AUTO CDC writer is idempotent on the target table.
- For materialized views, full vs incremental return the **same result** (MV refresh is cost-driven and idempotent); the destructive asymmetry is unique to streaming tables — never conflate the two.
- `reset_checkpoint_selection` requires fully qualified **flow names** (`catalog.schema.flow_name`); a bare name throws `IllegalArgumentException`. `full_refresh_selection`/`refresh_selection`, by contrast, take **table/dataset** names — the flow-name fully-qualified-or-fail rule is documented only for `reset_checkpoint_selection`.

**Interview soundbite:** Incremental refresh resumes from each flow's checkpoint and appends only new rows, while a full refresh truncates the streaming table, deletes all checkpoints, and re-reads only what the source *still* retains — so on short-retention sources it can leave you with fewer rows than before, which is why we put a full-history bronze ST in the medallion and set `pipelines.reset.allowed=false` to fence off any table we can't safely rebuild.

### Auto Loader (cloudFiles) — Important Options & Configs

**What it is**
Auto Loader is Databricks' incremental file-ingestion source, invoked through the Structured Streaming connector `cloudFiles`. It discovers new files in cloud object storage (ADLS `abfss://`, Unity Catalog Volumes `/Volumes/`, S3 `s3://`, GCS `gs://`, Azure Blob `wasbs://`) as they land and ingests each exactly once, tracking which files it has already processed in a RocksDB key-value store in its checkpoint. In **SDP (Spark Declarative Pipelines / Lakeflow)** it is the canonical ingestion engine behind a `@dp.table` streaming table — and crucially, SDP **manages the schema location and checkpoint for you** (you do NOT set `cloudFiles.schemaLocation` or `checkpointLocation` inside a pipeline). In my Apollo Gen2 work, every one of the 211 STG streaming tables is an Auto Loader `read_files`/`cloudFiles` reader over the per-entity `incoming/` folder produced by the JOB1 preprocessing notebook.

**How it works (mechanics)**
- File discovery runs in one of two detection modes (directory listing = default, or file notification — see below) and emits each newly-seen file path into a micro-batch.
- Auto Loader normally keys "have I seen this?" on the **file path** alone (one file = one ingest). With `cloudFiles.allowOverwrites=true` it additionally keys on the file's last-modified timestamp so an overwritten/appended file is re-ingested.
- Schema inference (when no schema provided): samples the **most recent (by modification time) 50 GB or 1000 files, whichever limit is crossed first**, writes the inferred schema to a `_schemas` directory under `schemaLocation`, and infers untyped formats (JSON/CSV/XML) as **all strings** unless `inferColumnTypes=true`. (Sample size is tunable via the SQL configs `spark.databricks.cloudFiles.schemaInference.sampleSize.numBytes` and `.numFiles`.)
- Schema evolution on a newly-seen column: stream **fails with `UnknownFieldException`** after merging the new column to the end of the stored schema → on **restart** the evolved schema is used. Configure the stream with Lakeflow Jobs / SDP so this restart is automatic, making the "failure" just a one-cycle pause.

**Key configs / syntax**

Core / schema options (defaults verified against the Spark API options reference):

| Option | Default | Meaning |
|---|---|---|
| `cloudFiles.format` | None (**required**) | `avro`, `binaryFile`, `csv`, `json`, `orc`, `parquet`, `text`, `xml`. |
| `cloudFiles.schemaLocation` | None (required to infer schema **outside** SDP) | Directory storing inferred schema + drift history (`_schemas`). **Managed automatically by SDP — do not set it in a pipeline.** |
| `cloudFiles.schemaEvolutionMode` | `addNewColumns` when no schema provided; `none` when a schema IS provided | Controls behavior on a new column (table below). |
| `cloudFiles.inferColumnTypes` | `false` | If `false`, JSON/CSV/XML columns inferred as **strings**; `true` infers real types (int/double/timestamp etc.). Note: the SQL `read_files` TVF flips this default to **`true`**. |
| `cloudFiles.schemaHints` | None | SQL-syntax type overrides for known columns (e.g. `"id long, ts timestamp"`) without supplying a full schema. `addNewColumns` still works when the schema arrives only as a hint. |
| `rescuedDataColumn` | None (column itself is **on by default** as `_rescued_data` for Auto Loader) | Name of the column that captures unparseable values (type mismatch, missing-in-schema, case difference). Set this to rename it. |
| `cloudFiles.partitionColumns` | None | Comma-separated Hive-style partition keys (`year=2022/month=2/...`) inferred from the directory path; set `""` to ignore them. |
| `readerCaseSensitive` | `true` | When `true`, columns differing only by case are rescued into `_rescued_data`; set `false` to read case-insensitively. (DBR 13.3+; supersedes the deprecated `parserCaseSensitive`.) |

`schemaEvolutionMode` behavior on encountering a new column (valid values: `addNewColumns`, `none`, `rescue`, `failOnNewColumns`):

| Mode | Behavior on a new column |
|---|---|
| `addNewColumns` (default, no schema given) | Stream fails with `UnknownFieldException`, adds column to schema; resumes on restart. Existing column types unchanged. On a *type change* (vs new column) the type does NOT evolve: mismatched values are set to `NULL` and routed to `_rescued_data`. |
| `rescue` | Never evolves, never fails on schema change; all new columns land in `_rescued_data`. |
| `failOnNewColumns` | Stream fails and will **not** restart until you update the provided schema/schema hints or remove the offending file. |
| `none` | Ignores new columns silently; no data rescued unless `rescuedDataColumn` is set; never fails on schema change. |

Separately, `addNewColumnsWithTypeWidening` is a distinct mode (**Public Preview, DBR 16.4+**, not in the standard valid-values list): same as `addNewColumns`, **plus** it widens supported types (`int`→`long`, `float`→`double`); unsupported widenings (e.g. `int`→`string`) go to `_rescued_data`.

Throughput / rate-limit and discovery options:

| Option | Default | Meaning |
|---|---|---|
| `cloudFiles.maxFilesPerTrigger` | `1000` | Max new files per micro-batch — a **hard** limit. In DBR 18.0+ this is dynamically auto-configured and need not be set. |
| `cloudFiles.maxBytesPerTrigger` | None | **Soft** byte cap per micro-batch (e.g. `10g`); if a single file is bigger it still goes whole. Used with `maxFilesPerTrigger` → whichever limit hits **first** wins. In DBR 18.0+ this is dynamically auto-configured. |
| `cloudFiles.includeExistingFiles` | `true` | Whether to ingest files already present at first start. **Evaluated only on the first stream start** — changing it after restart has no effect. |
| `cloudFiles.allowOverwrites` | `false` | If `true`, re-ingests appended/overwritten files (also keys on last-modified time). Default `false` = exactly-once on immutable files. |
| `cloudFiles.useNotifications` | `false` | `true` = file notification mode; `false` = directory listing mode. |
| `cloudFiles.useManagedFileEvents` | `false` | `true` = use Unity Catalog **file events** (recommended modern path; one queue/subscription per external location). DBR 14.3 LTS+. Do not combine with `backfillInterval`/`useNotifications`/`fetchParallelism`/`pathRewrites`/`resourceTags`. |
| `cloudFiles.backfillInterval` | None | Async backfill cadence (e.g. `1 week`) to re-scan and catch files missed by classic notifications. **Not needed** with file events — Databricks handles backfill automatically (the file-events service runs periodic full directory listings as a safety net). |

**Detection modes — directory listing vs file notification**

| Aspect | Directory listing (default) | File notification mode (`useNotifications=true`) |
|---|---|---|
| Discovery | Lists the input directory via storage `LIST` calls | Subscribes to a cloud queue; cost scales with file count, not directory size |
| Azure plumbing | None | **Azure Event Grid (subscription) + Azure Queue Storage (queue)** — Auto Loader can auto-create them given a service principal |
| AWS plumbing | None | **SNS (subscription) + SQS (queue)** |
| Permissions to auto-create (Azure) | — | `cloudFiles.subscriptionId`, `cloudFiles.resourceGroup`, `cloudFiles.tenantId`, `cloudFiles.clientId`, `cloudFiles.clientSecret` (or reuse an existing queue via `cloudFiles.queueName` + `cloudFiles.connectionString`) |
| When to use | Simplest start, low file volume | Millions of files/hour, lower `LIST` cost |

Databricks now recommends **file events** (`useManagedFileEvents`) on a Unity Catalog external location over both — it gives notification-grade performance without per-stream queue setup. Note: classic file notification mode is **not supported on Azure premium storage accounts**, because premium accounts don't support queue storage. (Per-storage-account classic limit on ADLS/Blob is 500 concurrent notification pipelines.)

PySpark in an SDP pipeline (schema/checkpoint managed by SDP — note the absence of `schemaLocation`/`checkpointLocation`):

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import col

@dp.table(name="stg_accounts")
def stg_accounts():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("rescuedDataColumn", "_rescued_data")
        .option("cloudFiles.maxFilesPerTrigger", "1000")
        .load("/Volumes/novartis/apollo/incoming/accounts/")
    )
```

Plain Structured Streaming outside SDP (here you DO manage both locations):

```python
(
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", "/Volumes/novartis/apollo/_schemas/accounts")
    .option("cloudFiles.inferColumnTypes", "true")
    .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
    .load("/Volumes/novartis/apollo/incoming/accounts/")
    .writeStream
    .option("checkpointLocation", "/Volumes/novartis/apollo/_ckpt/accounts")
    .trigger(availableNow=True)
    .toTable("stg_accounts")
)
```

File notification mode (classic, Azure — Auto Loader auto-provisions Event Grid + Queue):

```python
(
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.useNotifications", "true")
    .option("cloudFiles.subscriptionId", "<sub-id>")
    .option("cloudFiles.resourceGroup", "<rg>")
    .option("cloudFiles.tenantId", "<tenant-id>")
    .option("cloudFiles.clientId", "<sp-app-id>")
    .option("cloudFiles.clientSecret", dbutils.secrets.get("scope", "sp-secret"))
    .option("cloudFiles.schemaLocation", "/Volumes/.../_schemas/events")
    .load("abfss://container@account.dfs.core.windows.net/events/")
    .writeStream.option("checkpointLocation", "/Volumes/.../_ckpt/events")
    .toTable("stg_events")
)
```

SQL surface — `read_files` (the table-valued function that wraps Auto Loader; used inside `CREATE OR REFRESH STREAMING TABLE ... STREAM read_files(...)`). Options drop the `cloudFiles.` prefix. Note: in `read_files`, `inferColumnTypes` defaults to `true` (the opposite of the `cloudFiles` reader):

```sql
CREATE OR REFRESH STREAMING TABLE stg_accounts AS
SELECT *
FROM STREAM read_files(
  '/Volumes/novartis/apollo/incoming/accounts/',
  format            => 'parquet',
  inferColumnTypes  => true,
  schemaEvolutionMode => 'addNewColumns',
  rescuedDataColumn => '_rescued_data',
  maxFilesPerTrigger => 1000
);
```

```sql
-- Ad-hoc batch read (not streaming) with the same engine:
SELECT * FROM read_files('/Volumes/.../events/', format => 'json', multiLine => true);
```

**Use cases**
- The default landing-zone ingestor for any SDP bronze/staging layer reading files from ADLS or Volumes — exactly my 211 STG streaming tables in Apollo Gen2, each Auto-Loading the entity's `incoming/` folder.
- Vendor feeds with drifting schemas: `addNewColumns` + `_rescued_data` lets the pipeline self-heal on a new column instead of breaking.
- High-fan-in directories with millions of files/hour: switch to file events / notification mode to escape `LIST` cost.

**Limitations & gotchas**
- **In SDP, never set `schemaLocation` or `checkpointLocation`** — the pipeline owns them. Setting them manually fights the runtime, and a full refresh won't touch the manually-configured directories.
- A **new column** triggers `UnknownFieldException` and a one-cycle stream restart — expected, not a bug; rely on Lakeflow Jobs/SDP auto-restart.
- A **dropped column** is a soft delete: existing data keeps its values, new rows get `NULL`. A **type mismatch** that can't widen lands in `_rescued_data` (and the column value is set to `NULL`) rather than failing — so monitor that column or you silently lose visibility into bad data.
- `cloudFiles.includeExistingFiles` and the detection mode's first listing are **first-run-only** — toggling `includeExistingFiles=false` later does nothing.
- `allowOverwrites=true` in notification mode can **double-ingest** a file (notification event time vs modification time differ) — you must dedupe downstream. Auto Loader is built for **immutable** files; this is exactly the "streaming-on-mutable-source" trap I hit on Apollo Gen2.
- Without a schema, JSON/CSV/XML come in as **strings** unless `inferColumnTypes=true` — a silent behavior that bites people expecting typed columns.

**Interview soundbite:** Auto Loader is the `cloudFiles` streaming source that incrementally and exactly-once ingests files from object storage, with `_rescued_data` to capture parse failures and `schemaEvolutionMode=addNewColumns` to self-heal on new columns — and in SDP I let the pipeline manage the schema location and checkpoint rather than setting them myself.

### SDP-Specific Optimization Configs

These are the knobs that ship *inside* Lakeflow Spark Declarative Pipelines (SDP — the current name for the engine formerly called DLT). They split into two scopes: **table properties** (set per dataset via `TBLPROPERTIES` in SQL or `table_properties={...}` / dedicated kwargs in the `from pyspark import pipelines as dp` decorators) and **pipeline settings** (set in the pipeline JSON `configuration`/top-level fields, or the UI). Knowing which scope a knob lives in is itself an interview discriminator — setting a pipeline-level field as a table property silently does nothing.

**What it is**

The SDP-native optimization surface, distinct from generic Spark tuning (`spark.sql.shuffle.partitions`, AQE, broadcast hints). These knobs control file compaction, full-refresh protection, micro-batch cadence, data layout, runtime version, edition, and compute scaling — all things SDP manages on your behalf unless you override them.

**How it works (mechanics)**

For Unity Catalog managed tables, SDP delegates physical maintenance (`OPTIMIZE`, `VACUUM`, `ANALYZE`) to **predictive optimization (PO)**, which runs these asynchronously as queued maintenance operations chosen by cost-aware heuristics (it only queues an operation when the predicted data-skipping/storage savings outweigh the maintenance cost). On liquid-clustered tables, the `OPTIMIZE` that PO runs performs *incremental* clustering, not a full rewrite, and PO never runs `ZORDER`. PO is enabled by default for accounts created on or after 2024-11-11; older accounts are being enabled via a gradual rollout (expected to complete ~Aug 2026), so confirm with `DESCRIBE` / the PO status check rather than assuming it. The properties below either feed or override that automation. The single most operationally important one in my experience is `pipelines.reset.allowed`, because it changes the blast radius of a full refresh.

**Key configs / syntax**

Lead-with-these-four ranked by interview value:

| Knob | Scope | Default | What it does |
|---|---|---|---|
| `pipelines.reset.allowed` | Table property | `true` | When `false`, blocks **full refresh** of that table (full refresh resets streaming-table state/checkpoints and re-derives from source, dropping records if the source no longer has them). Incremental writes and new data still flow in. Protects backfilled / manually-corrected / short-retention-source tables. |
| `pipelines.autoOptimize.managed` | Table property | `true` | Enables/disables SDP's automatically-scheduled optimization (file compaction + layout) for that table. **Not used** when the table is governed by predictive optimization. |
| `pipelines.trigger.interval` | Table property (via `spark_conf` / `SET`) *or* pipeline `configuration` | Streaming queries: **5 s**; complete (batch) queries all-Delta sources: **1 min**; complete queries with any non-Delta source: **10 min** | Micro-batch cadence per flow. Because a triggered pipeline processes each table once, it is honored only in **continuous** pipelines. Set per-table — streaming and batch defaults differ, so a pipeline-wide value is usually wrong. |
| `CLUSTER BY AUTO` / `cluster_by_auto=True` | Table clause / decorator kwarg | off | Automatic liquid clustering — predictive optimization picks and maintains clustering keys from query history (requires PO; needs DBR 15.4 LTS+ for intelligent key selection). Replaces `PARTITIONED BY` and Z-ordering; skew-resistant and incremental. |

Other SDP-specific knobs:

| Knob | Scope | Default | Notes |
|---|---|---|---|
| `pipelines.autoOptimize.zOrderCols` | Table property | None | Comma-separated Z-order columns. **Legacy** — docs recommend `CLUSTER BY AUTO` instead. |
| `cluster_by=[...]` / `CLUSTER BY (cols)` | Table clause / kwarg | off | Manual liquid clustering keys. Mutually exclusive with `PARTITIONED BY`. |
| `pipelines.cdc.tombstoneGCThresholdInSeconds` | Table property (on the AUTO CDC target) | `172800` (2 days) | How long SCD2 delete **tombstones** are retained before GC. AUTO CDC keeps a deleted row as a hidden tombstone to handle out-of-order deletes, then exposes a metastore view that filters them. Raise it above your worst-case event-to-pipeline delay. |
| `channel` | Pipeline setting | `current` | Runtime version: `current` (prod) or `preview` (test upcoming runtime). Can also be set per-statement in SQL via the `pipelines.channel` TBLPROPERTY (`"CURRENT"`/`"PREVIEW"`, default `"CURRENT"`). |
| `edition` | Pipeline setting | `ADVANCED` | `CORE` = streaming ingest only; `PRO` = + CDC (AUTO CDC); `ADVANCED` = + expectations. Pick the cheapest that covers your features. (Edition also sets UI/API update-history retention: Core 5 days, Pro/Advanced 30 days.) |
| `photon` | Pipeline setting | `false` | Enables the Photon engine. Billed at a different DBU rate. You enable it via this field; you cannot set the cluster `runtime_engine` directly. |
| `pipelines.maxFlowRetryAttempts` | Pipeline setting | 2 retries (3 total attempts) | Bounds per-flow retries on retryable failures. |
| `pipelines.numUpdateRetryAttempts` | Pipeline setting | 5 (triggered) / unlimited (continuous) | Bounds whole-update retries. Applies only to pipelines using automatic retry/restart behavior; not to ad-hoc/`Validate` updates from the editor. |

`pipelines.reset.allowed=false` — the canonical backfill-protection pattern:

```sql
CREATE OR REFRESH STREAMING TABLE raw_user_table
TBLPROPERTIES(pipelines.reset.allowed = false)
AS SELECT * FROM STREAM read_files("/Volumes/raw/users", format => "csv");
```

```python
from pyspark import pipelines as dp

@dp.table(
    table_properties={"pipelines.reset.allowed": "false"}
)
def raw_user_table():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .load("/Volumes/raw/users")
    )
```

Auto file compaction + optimized writes (managed optimization on, explicit), plus disabling it for a hot append-only table:

```python
from pyspark import pipelines as dp

@dp.table(
    table_properties={"pipelines.autoOptimize.managed": "true"}
)
def compacted_table():
    return spark.readStream.table("upstream")

@dp.table(
    table_properties={"pipelines.autoOptimize.managed": "false"}
)
def hot_append_table():
    return spark.readStream.table("upstream")
```

Per-table trigger interval (continuous pipeline):

```python
from pyspark import pipelines as dp

@dp.table(
    spark_conf={"pipelines.trigger.interval": "10 seconds"}
)
def fast_stream():
    return spark.readStream.table("source")
```

```sql
SET pipelines.trigger.interval=10 seconds;

CREATE OR REFRESH MATERIALIZED VIEW agg_daily
AS SELECT day, count(*) FROM events GROUP BY day;
```

Pipeline-scoped trigger interval (JSON `configuration`):

```json
{
  "configuration": {
    "pipelines.trigger.interval": "1 hour"
  }
}
```

Automatic liquid clustering (preferred over partitioning/Z-order):

```python
from pyspark import pipelines as dp

@dp.table(cluster_by_auto=True)
def events():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load("/Volumes/raw/events")
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE events
CLUSTER BY AUTO
AS SELECT * FROM STREAM read_files("/Volumes/raw/events", format => "parquet");
```

Explicit clustering keys when you know the predicates (note: SQL can't give *initial-key hints* with `AUTO` — only the Python API can seed `cluster_by` + `cluster_by_auto=True` together):

```python
from pyspark import pipelines as dp

@dp.table(cluster_by=["event_date", "region"])
def events_clustered():
    return spark.readStream.table("raw_events")
```

CDC tombstone retention for SCD2 (raise above worst-case file-arrival delay — directly relevant to my out-of-order Auto Loader incidents):

```sql
CREATE OR REFRESH STREAMING TABLE customer_history
TBLPROPERTIES(pipelines.cdc.tombstoneGCThresholdInSeconds = 604800);
```

**Use cases**

- `pipelines.reset.allowed=false`: any table where source data can't recreate current state — Bronze SCD2 tables built by `dp.create_auto_cdc_flow`, manually-corrected records, or short-retention sources (Kafka, object-store lifecycle policies). On my Apollo Gen2 211 Bronze SCD2 tables, this is the guardrail that stops an accidental full refresh from re-deriving history from the latest snapshot only.
- `cluster_by_auto`: high-cardinality filter columns where query patterns shift (entity-keyed Bronze tables queried by different downstream consumers).
- `tombstoneGCThresholdInSeconds`: I tie this to JOB1→JOB2 lag — when `sequence_by` on file modification time was too coarse and deletes arrived out of order, a longer tombstone window kept SCD2 deletes correct.
- `trigger.interval` raised on low-volume sources to avoid the small-files problem.
- `edition=PRO` is the floor for any CDC pipeline; `ADVANCED` only if you run `@dp.expect*` constraints.

**Limitations & gotchas**

- `reset.allowed=false` blocks full refresh but **not** incremental writes — it is not a freeze. Downstream tables still recompute on update.
- `autoOptimize.managed` is **ignored** when predictive optimization governs the table; don't expect it to do anything on a PO-managed UC table.
- `trigger.interval` is a **no-op in triggered pipelines** — each table runs once per update regardless. Only continuous mode honors it.
- `CLUSTER BY` is mutually exclusive with `PARTITIONED BY`. Liquid-clustered tables use Delta writer v7 / reader v3 — older clients can't read them, and you can't downgrade the protocol.
- Cluster attributes like `runtime_engine`, `spark_version`, `autotermination_minutes`, `data_security_mode` are **system-set and not user-overridable** — SDP owns the cluster lifecycle. Photon is the only runtime-engine lever, via the `photon` field.
- Serverless pipelines block most session-level `spark_conf` overrides; the SDP table-/flow-scoped `spark_conf` in decorators still works, but general session Spark tuning is limited.
- **Serverless enhanced autoscaling** = horizontal (more executors) **plus vertical** (auto-picks larger/smaller instance types — driver, workers, or both — on OOM, scales down when memory is underutilized). Vertical is serverless-only and covers DBSQL MVs/streaming tables too. Photon billing differs from non-Photon.

**Interview soundbite:** "The four SDP knobs I reach for are `pipelines.reset.allowed=false` to fence backfilled SCD2 tables from a destructive full refresh, `pipelines.autoOptimize.managed` for auto-compaction, per-table `pipelines.trigger.interval` for continuous-mode cadence, and `CLUSTER BY AUTO` for self-tuning data layout — and I always keep straight that reset/autoOptimize/tombstoneGC are table properties while channel/edition/photon and pipeline-scope trigger live in the pipeline settings."

### Stateful Processing

**What it is**

*State* is intermediate data that a streaming query must remember **across microbatches** to compute a correct result. A *stateless* query (a plain `@dp.table` doing filter/project/`read_files` append) only tracks which source offsets it has consumed — it never needs to look back. A *stateful* query must carry forward partial results: running aggregates, in-flight join rows waiting for a match, or seen-keys for dedup. JARVIS/Apollo Gen2 angle: my 211 STG streaming tables are mostly stateless appends, but `dp.create_auto_cdc_flow` (SCD2 bronze) is internally a stateful operator — it keeps per-key history to apply ordered changes — which is why a coarse `sequence_by` corrupts ordering and why "SCD2-on-SCD2" double-stateful chains are fragile.

Stateful operations recognized by Spark: streaming aggregation, `distinct`, `dropDuplicates` / `dropDuplicatesWithinWatermark`, stream-stream joins, and arbitrary stateful (`transformWithState` / legacy `flatMapGroupsWithState`).

**How it works (mechanics)**

- Each microbatch reads new source rows, **merges** them into the state store (keyed by grouping key / join key / dedup key), emits output, and **persists** the updated state to the checkpoint so a crashed task replays from the last committed microbatch (exactly-once on state).
- State is partitioned by **shuffle partitions**. Spark schedules one state-store instance per shuffle partition per stateful operator, so total state-store instances ≈ shuffle_partitions × num_stateful_operators.
- **Watermarks are what make state finite.** Without a watermark, the engine cannot know when a key/window is "done," so it keeps every key forever → unbounded state → OOM. With a watermark, once event-time passes `window_end + watermark_threshold`, the engine emits the final result and **evicts** that state. Critically, a watermark is *also* what makes aggregations **incremental** rather than fully recomputed on every update — the docs are explicit: "To ensure queries that perform aggregations are processed incrementally and not fully recomputed with each update, you must use watermarks."
- A watermark = `(timestamp_column, late_data_threshold)`. The current watermark is computed as `MAX(event_time seen across all partitions) − threshold`; because coordinating this value across partitions has a cost, the watermark used is only guaranteed to be at least `threshold` behind the true max event time. Rows older than the current watermark are treated as late and may be dropped.

**Key configs / syntax**

| Config / API | Value / default | Purpose |
|---|---|---|
| `spark.sql.streaming.stateStore.providerClass` | RocksDB is **default in DBR 17.3+**; below 17.3 set to `com.databricks.sql.streaming.state.RocksDBStateStoreProvider` | Off-heap state store; avoids JVM GC pauses / OOM on large state. Serverless pipelines manage this automatically. |
| `spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled` | available DBR 13.3 LTS+; **`true` by default in DBR 17.3+**; else set `true` | Writes only changed records per checkpoint (not a full snapshot) → lower checkpoint duration + end-to-end latency. |
| `spark.sql.shuffle.partitions` | default 200 | Sets stateful parallelism. **Fixed at checkpoint creation** for stateful queries — changing it is ignored by an existing checkpoint. |
| `spark.sql.streaming.stateStore.partitions` | DBR 18.3+ (requires RocksDB) | On-demand state repartitioning — resize partitions *without* losing checkpoint state (stop → set → restart; repartition runs after the last planned microbatch). Takes precedence over `spark.sql.shuffle.partitions`. (Separately, DBR 18.0+ lets *stateless* queries change shuffle partitions on restart.) |
| `spark.sql.streaming.noDataMicroBatches.enabled` | default `true` | When `true`, the engine runs empty (no-data) microbatches so watermark/timeout-driven emits fire on time. Set `false` to skip empty microbatches — but then watermark/timeout emits wait until new data arrives. |
| `withWatermark("col", "3 minutes")` / SQL `WATERMARK col DELAY OF INTERVAL 3 MINUTES` | — | Declares the watermark. |

Tuning recommendation from docs: shuffle partitions = 1–2× cluster cores; use compute-optimized workers for heavy state; cap RocksDB per-node memory (automatic in 17.3+).

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window

@dp.table
def event_counts():
    return (
        spark.readStream.table("events_raw")
            .withWatermark("event_time", "3 minutes")
            .groupBy(window("event_time", "1 minute"), "region")
            .count()
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

**Window types** (`window()` / `session_window()` — `timeColumn` must be `TimestampType`/`TimestampNTZType`; microsecond precision, months-and-longer not supported; use `current_timestamp()` for processing-time windows):

| Window | Definition | A row belongs to | Args |
|---|---|---|---|
| **Tumbling (fixed)** | Fixed-size, non-overlapping, contiguous | exactly one window | `window(col, "1 hour")` (slide omitted ⇒ tumbling) |
| **Sliding** | Fixed-size, overlapping; advances by slide | possibly many windows | `window(col, "6 hours", slideDuration="1 hour")`; `slideDuration ≤ windowDuration` |
| **Session** | Dynamic length; opens on first row, extended by each row within `gapDuration`, closes after a `gapDuration` idle gap | one dynamic session | `session_window(col, gapDuration="30 minutes")` |

```python
from pyspark.sql.functions import session_window, sum

sessionized = (activity
  .withWatermark("timestamp", "1 hour")
  .groupBy("user_id", session_window("timestamp", gapDuration="30 minutes"))
  .agg(sum("page_views").alias("total_page_views")))
```

**Stream-stream join** — watermark required on **both** sides + a time-range condition (using the same fields the watermarks are defined on); the engine maintains one global watermark from the slowest stream:

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("adImpressionClicks")

@dp.append_flow(target="adImpressionClicks")
def join_clicks_impressions():
    clicks = spark.readStream.table("rawClicks").withWatermark("clickTimestamp", "3 minutes")
    impressions = spark.readStream.table("rawAdImpressions").withWatermark("impressionTimestamp", "3 minutes")
    return impressions.alias("imp").join(
        clicks.alias("click"),
        expr("""imp.userId = click.userId AND clickAdId = impressionAdId
                AND clickTimestamp >= impressionTimestamp
                AND clickTimestamp <= impressionTimestamp + interval 3 minutes"""),
        "inner").select("imp.userId", "impressionAdId", "clickTimestamp", "impressionSeconds")
```

```sql
CREATE OR REFRESH STREAMING TABLE silver.adImpressionClicks AS
SELECT imp.userId, impressionAdId, clickTimestamp, impressionSeconds
FROM STREAM(bronze.rawAdImpressions)
  WATERMARK impressionTimestamp DELAY OF INTERVAL 3 MINUTES imp
INNER JOIN STREAM(bronze.rawClicks)
  WATERMARK clickTimestamp DELAY OF INTERVAL 3 MINUTES click
ON imp.userId = click.userId AND clickAdId = impressionAdId
   AND clickTimestamp >= impressionTimestamp
   AND clickTimestamp <= impressionTimestamp + interval 3 minutes;
```

> Note on outer joins: an inner stream-stream join only emits matched pairs. With a left/right **outer** join, unmatched rows are NULL-padded and emitted **only after** the watermark guarantees no future match can arrive — so outer-join NULL rows are delayed by the watermark, not produced immediately. (Inner joins, as above, never emit NULL-padded rows.)

**Deduplication** — `dropDuplicates(["k"])` keeps all seen keys forever unless bounded by a watermark; `dropDuplicatesWithinWatermark(["k"])` (DBR 13.3 LTS+) bounds state by the watermark and tolerates duplicates whose timestamps differ. Records arriving within the watermark threshold are always deduplicated; records outside it *may* be (not guaranteed). Set the watermark threshold larger than the max timestamp gap between duplicates to guarantee they collapse:

```python
clicksDedupDf = (
  spark.readStream
    .option("withEventTimeOrder", "true")
    .table("rawClicks")
    .withWatermark("clickTimestamp", "5 seconds")
    .dropDuplicatesWithinWatermark(["userId", "clickAdId"]))
```

`withEventTimeOrder` (Python-only) processes the initial Delta snapshot in event-time order so out-of-order initial reads don't jump the watermark ahead and drop legitimately-old rows. Declare it inline as above, or pipeline-wide via `spark_conf` → `spark.databricks.delta.withEventTimeOrder.enabled = "true"`.

**Arbitrary stateful processing** — `transformWithState` / `transformWithStateInPandas` (DBR 16.2+; Python standard-access 16.3+, Scala standard-access 17.3+) is the current recommended API for custom per-key state, replacing legacy `flatMapGroupsWithState` / `applyInPandasWithState` / `mapGroupsWithState`. You subclass `StatefulProcessor`, declare `ValueState`/`ListState`/`MapState`, implement `handleInputRows` (fires only when a key has rows in the microbatch) and `handleExpiredTimer` (fires on a timer even with no rows). State is isolated per grouping key — you cannot compare/update across keys (use a `MapState` second key, e.g. `ip_address` under `user_id`, for sub-session tracking).

**Inspecting state** — the state reader (`format("state-metadata")` for operator metadata: `operatorId`, `operatorName` such as `stateStoreSave` / `dedupeWithinWatermark`, `stateStoreName`, `numPartitions`, `minBatchId`, `maxBatchId`; and `format("statestore")` for key/value rows) and the SQL TVFs `read_state_metadata(path)` / `read_statestore(path, operatorId => ...)` are **batch read-only** tools that operate on a raw Structured Streaming **checkpoint path**:

```python
df = spark.read.format("state-metadata").load("<checkpointLocation>")
left = spark.read.format("statestore").option("operatorId", 1).load("<checkpointLocation>")
```

```sql
SELECT * FROM read_state_metadata('/checkpoint/path');
SELECT * FROM read_statestore('/checkpoint/path', operatorId => 1);
```

> **Hard limitation (interview trap):** per the docs, you **cannot** query state information for Lakeflow Spark Declarative Pipelines, streaming tables, or materialized views, and you **cannot** use these readers on serverless compute. They require a raw Structured Streaming checkpoint on DBR 16.3+ standard access mode, or DBR 14.3 LTS+ on dedicated / no-isolation access mode. So for my 422 SDP pipelines these readers do **not** apply directly — SDP state is observed via the **pipeline event log** and `StreamingQueryProgress` metrics instead.

**Use cases**

- Windowed aggregations (hourly/rolling/session metrics) over event-time streams.
- Stream-stream enrichment joins (impressions ⋈ clicks) with bounded matching windows.
- Idempotent ingestion from at-least-once sources (Kafka/Event Hubs) via `dropDuplicatesWithinWatermark`.
- SCD2 history maintenance — Apollo Gen2 bronze `dp.create_auto_cdc_flow` is an internal stateful operator that orders changes by `sequence_by`.

**Limitations & gotchas**

- **No watermark ⇒ unbounded state.** Windowed/dedup/distinct queries without a watermark grow state forever and OOM; aggregations also become full-recompute instead of incremental.
- **Changing stateful logic invalidates state.** Altering grouping keys/aggregates, join schema/equi-join keys/type (inner↔outer), dedup columns, or user-state schema is **not allowed across restarts** — the checkpointed state schema must stay identical. In SDP, changing a watermark threshold or aggregation columns forces a **full refresh** to rebuild state from scratch.
- **Shuffle-partition count is frozen at checkpoint creation** for stateful queries. Pre-18.3 you cannot retune it without a new checkpoint (state loss). DBR 18.3+ `spark.sql.streaming.stateStore.partitions` repartitions without checkpoint loss.
- **Watermark threshold is a latency↔correctness tradeoff.** Too small ⇒ late rows silently dropped; too large ⇒ more state, more memory, later emits.
- Out-of-order initial-snapshot processing can jump the watermark ahead and then drop legitimately-old rows — use `withEventTimeOrder` (Python-only) for ordered initial processing.
- `dropDuplicates()` / `dropDuplicatesWithinWatermark()` can fail the state-schema compatibility check when switching compute **access modes**.
- Pack too many state partitions on one executor and per-node maintenance (snapshot upload/cleanup) starves → slow recovery. Use RocksDB + changelog checkpointing; cap RocksDB memory per node (automatic in 17.3+).
- Output mode for windowed aggregations: `append` (watermark-bounded, evicts state) vs `complete` (keeps all window state indefinitely — only for small, finite key spaces).

**Interview soundbite:** "State is the partial result the engine carries between microbatches for aggregations, joins, and dedup; the watermark is non-negotiable — it bounds that state so it doesn't OOM and makes aggregations incremental instead of full-recompute — and because state lives in the RocksDB-backed checkpoint, any change to the stateful logic invalidates it and forces a full refresh. And one trap: the state-reader TVFs don't work on SDP pipelines or serverless — for SDP I read the event log and StreamingQueryProgress, not `read_statestore`."

### Materialized View — Optimization

A materialized view (MV — a Lakeflow/SDP dataset that caches a query result and keeps it in sync with upstream Delta tables) is "optimized" almost entirely by one lever: **getting it to refresh incrementally instead of fully recomputing every run.** A `FULL_RECOMPUTE` re-scans and re-aggregates the entire source on each pipeline trigger; an incremental refresh processes only the rows that changed since the last update. On my Apollo Gen2 pipeline the Bronze SCD2 layer is built from streaming tables (`@dp.table` + `create_auto_cdc_flow`), but any roll-up or dimension-enrichment layer I model as an MV (`@dp.materialized_view`) lives or dies on this distinction — a 200M-row entity that full-recomputes on every 15-minute trigger is a cost incident waiting to happen.

**What it is**

Optimizing an MV = (1) diagnosing whether it currently incrementalizes, and (2) reshaping the query, the base tables, and the refresh policy so the engine can keep choosing incremental. The output of incremental vs. full is identical (equivalent to the batch query); the difference is purely compute cost and latency.

**How it works (mechanics)**

- **Cost model picks the technique.** By default (`REFRESH POLICY AUTO`) Databricks runs a cost analysis on every refresh and picks the cheaper of incremental or full recompute — even when the query *is* incrementalizable, a large changeset can make full cheaper, and it will pick full.
- **Incremental requires serverless.** Refreshes always run on serverless pipelines. An MV on classic (non-serverless) compute is *always* fully recomputed — no exceptions. For an SDP-defined MV you must configure the pipeline to use serverless; for a Databricks SQL MV the serverless pipeline is used automatically (the workspace doesn't even need serverless SDP enabled).
- **The chosen technique is logged.** Each refresh emits a `planning_information` event in the pipeline event log naming the technique: `FULL_RECOMPUTE`, `NO_OP` (no base change), or an incremental technique. The full set of incremental techniques is `ROW_BASED`, `PARTITION_OVERWRITE`, `WINDOW_FUNCTION`, `APPEND_ONLY`, `GROUP_AGGREGATE`, `GENERIC_AGGREGATE`. When it's full, the event carries a *reason code* telling you exactly why it fell back.

**Step 1 — Diagnose: is it actually refreshing incrementally?**

Two complementary tools. Use `EXPLAIN CREATE MATERIALIZED VIEW` for *structural* eligibility before/without running, and the event log for what *actually* happened at runtime.

Query the event log for the refresh technique (in current SDP it is the `event_log()` table-valued function — there is no legacy `system.event_log`):

```sql
SELECT timestamp, message
FROM event_log(TABLE(my_catalog.my_schema.my_mv))
WHERE event_type = 'planning_information'
ORDER BY timestamp DESC;
```

A healthy line reads `Flow 'my_mv' has been planned ... to be executed as GROUP_AGGREGATE.` A bad one reads `... as FULL_RECOMPUTE.` plus a reason code.

Test structural eligibility without a run (Databricks SQL; Databricks Runtime 17.3 and above). Strip expectations and fully qualify sources first, because `CREATE MATERIALIZED VIEW` queries from a pipeline may not run under `EXPLAIN` as-is:

```sql
EXPLAIN CREATE MATERIALIZED VIEW dim_account
AS SELECT account_id, SUM(txn_amount) AS revenue
FROM my_catalog.bronze.transactions
GROUP BY account_id;
```

A pass returns `The Materialized View can be incrementally refreshed.` Important caveat: `EXPLAIN` confirms *structural* eligibility only — under `AUTO` the cost model can still choose full at runtime. Only `REFRESH POLICY INCREMENTAL`/`INCREMENTAL STRICT` override that.

**Fall-back reason codes (from the `planning_information` event) — map symptom to fix**

| Reason code | Meaning | Fix lever |
|---|---|---|
| `CHANGE_SET_MISSING` | First-ever compute of the MV | Expected once; ignore |
| `PLAN_NOT_DETERMINISTIC` | A non-deterministic operator/expression in the definition (event reports `operator_name` / `expression_name`) | Remove `rand()`, `uuid()`, non-WHERE `current_timestamp()` |
| `PLAN_NOT_INCREMENTALIZABLE` | An operator isn't incrementalizable (e.g. `WITH RECURSIVE`) | Rewrite the query shape |
| `QUERY_FINGERPRINT_CHANGED` | MV definition changed (or an SDP release changed plans) | Expected after an edit; one full run then steady |
| `CONFIGURATION_CHANGED` | A key config changed (e.g. `spark.sql.ansi.enabled`) | Pin configs; avoid churning them |
| `ROW_TRACKING_NOT_ENABLED` | A base table lacks row tracking | `ALTER TABLE ... SET TBLPROPERTIES('delta.enableRowTracking'=true)` |
| `EXPECTATIONS_NOT_SUPPORTED` | An expectation case blocks incremental (MV reads a view with expectations, or has a `DROP` expectation + `NOT NULL` columns in schema) | See expectation rule below |
| `TOO_MANY_FILE_ACTIONS` / `TOO_MANY_PARTITIONS_CHANGED` | Changeset too large for incremental | Reduce base-table file/partition churn; lower trigger frequency |
| `INCREMENTAL_PLAN_REJECTED_BY_COST_MODEL` | Cost model judged full cheaper | Override with `REFRESH POLICY INCREMENTAL` if you know better |
| `MAP_TYPE_NOT_SUPPORTED` | Map-typed column in the MV | Restructure to avoid map types |
| `SERIALIZATION_VERSION_CHANGED` | Query-fingerprinting logic changed | Expected across runtime upgrades; transient |

(The event-log schema also documents `DATA_HAS_CHANGED`, `TIME_ZONE_CHANGED`, and `PRIOR_TIMESTAMP_MISSING` as additional full-recompute reasons.)

**Step 2 — Fix the query so it stays incrementalizable**

The query must use only operations the engine can incrementalize. Verified support table (from the SDP incremental-refresh docs):

| Construct | Incremental? | Note |
|---|---|---|
| `SELECT` of deterministic built-ins + immutable UDFs | Yes | Non-deterministic funcs break it (time funcs allowed only in `WHERE`) |
| `GROUP BY` with supported aggregates | Yes | `GROUP_AGGREGATE` / `GENERIC_AGGREGATE` |
| `WHERE`, `HAVING` | Yes | `current_date()`/`current_timestamp()`/`now()` allowed *only here* |
| `INNER` / `LEFT OUTER` / `RIGHT OUTER` / `FULL OUTER JOIN` | Yes | Starred in docs: require row tracking on the joined sources |
| `OVER` (window functions) | Yes | Must specify `PARTITION BY` columns |
| `QUALIFY` | Yes | |
| `UNION ALL`, `WITH` (CTE) | Yes | CTEs only if their bodies use supported clauses |
| `WITH RECURSIVE` | No | Always full recompute |
| Expectations (`@dp.expect`) | Mostly yes | NOT incremental if the MV reads a view that has expectations, or has a `DROP` expectation + `NOT NULL` columns in schema |

Things that force `FULL_RECOMPUTE` and how to handle each:

- **`COUNT(DISTINCT col)`** — has a documented privacy gotcha: the MV's underlying files store the actual distinct values of the column to support refresh, even though the column isn't in the MV schema. (Treat its incremental eligibility as not guaranteed — verify per-query with `EXPLAIN CREATE MATERIALIZED VIEW`; the SDP support table does not list distinct-count among the incrementalizable aggregates and validating it is the safe move.) Fix: pre-aggregate distinct keys in an upstream staging layer, or accept approximate counts via a sketch column maintained upstream.
- **Non-deterministic functions** (`rand()`, `uuid()`, `current_timestamp()` outside `WHERE`, time-zone-sensitive expressions) — replace with deterministic equivalents or push the timestamp into a `WHERE` filter. Non-deterministic time functions (`current_date()`, `current_timestamp()`, `now()`) are supported *only* in `WHERE`.
- **Changed UDFs** — the engine tries to detect a UDF behavior change and trigger full refresh, but a UDF that calls external libs can change silently and *not* be detected, leaving stale results. After editing any UDF, you own running a manual full refresh: `REFRESH MATERIALIZED VIEW mv FULL`.
- **Unsupported sources** — volumes, external locations, foreign catalogs, and foreign Iceberg tables don't incrementalize. Supported: Delta tables (Unity Catalog managed + external Delta-backed), other MVs, streaming tables (including `AUTO CDC ... INTO` targets), and Unity Catalog managed Iceberg tables (v2 and v3; v3 recommended for best incremental support). Source tables with row filters or column masks also block incremental.

Enable the Delta features the engine needs on **every base table** (row tracking is the one that silently causes `ROW_TRACKING_NOT_ENABLED`):

```sql
ALTER TABLE my_catalog.bronze.transactions SET TBLPROPERTIES (
  delta.enableRowTracking = true,
  delta.enableDeletionVectors = true,
  delta.enableChangeDataFeed = true
);
```

**Step 3 — Override the cost model when you know better**

If `EXPLAIN` says incrementalizable but the log keeps showing `INCREMENTAL_PLAN_REJECTED_BY_COST_MODEL`, force it. Behavior differs by phase: on a normal refresh, `INCREMENTAL` falls back to full if the plan can't incrementalize, whereas `INCREMENTAL STRICT` *fails the refresh* instead of silently full-recomputing — the right choice when an unexpected full recompute would blow an SLA or cost budget. On `CREATE`/re-initialization, *both* `INCREMENTAL` and `INCREMENTAL STRICT` fail outright if the query is not incrementalizable (only `AUTO`/`FULL` would proceed).

```sql
CREATE OR REFRESH MATERIALIZED VIEW dim_account
REFRESH POLICY INCREMENTAL
AS SELECT account_id, SUM(txn_amount) AS revenue
FROM my_catalog.bronze.transactions GROUP BY account_id;
```

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum

@dp.materialized_view(refresh_policy="incremental_strict")
def dim_account():
    return (
        spark.read.table("my_catalog.bronze.transactions")
        .groupBy("account_id")
        .agg(sum("txn_amount").alias("revenue"))
    )
```

(`refresh_policy` is Beta; accepted values are `auto`, `incremental`, `incremental_strict`, `full`; default `auto`.) On an `INCREMENTAL STRICT` refresh failure you get a non-incrementalizable error with the offending operator/expression named, so the cause is debuggable rather than silent.

**Step 4 — Reduce per-refresh work even when incremental**

- **Broadcast small-dimension joins.** A `/*+ BROADCAST(dim) */` hint ships the small table to every executor and skips the shuffle. Why: shuffle joins are the dominant cost in star-schema enrichment MVs.

```sql
CREATE OR REFRESH MATERIALIZED VIEW enriched_orders AS
SELECT /*+ BROADCAST(p) */ o.*, p.product_name, p.category
FROM my_catalog.bronze.orders o
JOIN my_catalog.bronze.products p ON o.product_id = p.product_id;
```

- **`CLUSTER BY` on the MV (and base tables).** Liquid clustering data-skips at read time and is self-tuning, skew-resistant, and incremental (rewrites only data that needs reorganizing), unlike static `PARTITIONED BY` (mutually exclusive with it). Why: smaller scan footprint per refresh and per downstream query. Name keys explicitly, or use `CLUSTER BY AUTO` (SQL) / `cluster_by_auto=True` (Python) to let Databricks pick keys — automatic key selection *requires predictive optimization* (it runs asynchronously as a maintenance op). Note: you cannot change MV/ST clustering keys via `ALTER TABLE` — set them at create time.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum

@dp.materialized_view(cluster_by=["account_id", "txn_date"])
def dim_account():
    return (
        spark.read.table("my_catalog.bronze.transactions")
        .groupBy("account_id", "txn_date")
        .agg(sum("txn_amount").alias("revenue"))
    )
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW dim_account
CLUSTER BY (account_id, txn_date) AS
SELECT account_id, txn_date, SUM(txn_amount) AS revenue
FROM my_catalog.bronze.transactions GROUP BY account_id, txn_date;
```

- **Salt skewed keys.** When a join/`GROUP BY` key is lopsided (a few keys hold most rows), a handful of tasks hotspot and stretch refresh time. Append a bucket suffix, aggregate in two stages (per-salt, then re-aggregate), then drop the salt. Why: spreads the hot key across partitions for the in-flight computation that clustering can't fix.

```python
from pyspark.sql import functions as F
from pyspark import pipelines as dp

@dp.materialized_view()
def revenue_by_account():
    salted = (
        spark.read.table("my_catalog.bronze.transactions")
        .withColumn("salt", F.pmod(F.hash("account_id"), F.lit(16)))
        .groupBy("account_id", "salt")
        .agg(F.sum("txn_amount").alias("partial"))
    )
    return salted.groupBy("account_id").agg(F.sum("partial").alias("revenue"))
```

Note the tension: a *random* salt (`F.rand()`) is non-deterministic and will block incremental refresh, so either reserve random salting for an MV you accept as full-recompute, or salt **deterministically** (e.g. `pmod(hash(natural_key), 16)`, as above) to keep incremental eligibility.

- **Pre-aggregate in a staging ST/MV.** Split one heavy MV into a lightweight upstream layer (e.g. a streaming table or MV that pre-rolls counts) feeding a thin final MV. Why: keeps each layer's per-refresh changeset small and isolates a distinct-count or window step so only that layer pays the full-recompute tax, not the whole chain.
- **Reduce refresh cadence.** Match the pipeline trigger interval to data volume. Why: triggering a low-volume source too often writes many tiny files (each a metadata lookup + I/O round trip; cloud listing throttles at scale) and pays fixed per-refresh overhead with little new data. Let data accumulate between updates.

**Use cases**

- A dashboard-acceleration roll-up over a Bronze SCD2 table that must refresh cheaply every 15 min → MV with deterministic `GROUP BY` + `INCREMENTAL STRICT` + row tracking on the base.
- Star-schema enrichment of a fact against small dims → MV with `BROADCAST` hints + `CLUSTER BY` on the join key.
- A distinct-count metric → pre-aggregate layer upstream, thin MV downstream, so a `COUNT(DISTINCT)` doesn't full-recompute a 200M-row entity.

**Limitations & gotchas**

- Classic compute = always full recompute; incremental needs serverless. This is the single most common "why won't it incrementalize" answer.
- `EXPLAIN` eligibility ≠ guaranteed incremental under `AUTO` — the cost model still decides.
- MVs don't support identity/surrogate columns, CDF reads *from* the MV, or time travel.
- `SUM` over a NULL-able column where only `NULL` values remain returns `0`, not `NULL`.
- Editing the MV definition or a UDF triggers a one-time full recompute (`QUERY_FINGERPRINT_CHANGED`); that's expected, but a *silently* changed UDF can leave stale data — force a full refresh yourself.
- Underlying MV files may store upstream raw values (incl. PII) to support incremental refresh even if those columns aren't in the MV schema (the docs use `COUNT(DISTINCT field_a)` as the example) — don't share the storage with untrusted consumers.

**Interview soundbite:** "First I check the `planning_information` event in `event_log()` — if it says `FULL_RECOMPUTE` I read the reason code, confirm the pipeline is serverless and base tables have row tracking on, make the query deterministic with supported aggregates (no `rand()`; validate any `COUNT(DISTINCT)` with `EXPLAIN`), and if the cost model is being conservative I pin `REFRESH POLICY INCREMENTAL STRICT`; then I trim per-refresh work with broadcast joins, `CLUSTER BY`, deterministic salting, and a staging pre-aggregation layer."

### Materialized View — Full vs Incremental Refresh

**What it is**

A materialized view (MV) in Spark Declarative Pipelines (SDP / Lakeflow Declarative Pipelines) is a Delta table whose contents are the precomputed result of a `SELECT`, kept in sync with its sources by the pipeline. Every refresh guarantees **batch-equivalent results** — the MV always equals what you'd get by rerunning the full query from scratch. SDP gets there one of two ways:

| Refresh type | What it does | Where it runs |
|---|---|---|
| **Incremental refresh** | Detects only the changed rows in upstream sources since the last refresh and applies the delta (append/merge) to the MV. Cheaper. | **Serverless ONLY** |
| **Full recompute (full refresh)** | Clears the table + all checkpoints and reprocesses the entire source dataset. | Serverless or classic |

The output is **identical** either way — incremental is purely a cost optimization. SDP runs a cost analysis and picks the cheaper of the two per run (under the default `AUTO` policy).

**How it works (mechanics)**

- **Incremental is gated on serverless.** MVs updated on **classic compute are ALWAYS fully recomputed**. No serverless = no incremental, full stop. (Note: standalone MVs defined in Databricks SQL auto-use a serverless pipeline for refresh even if the workspace isn't serverless-enabled for SDP; SDP-defined MVs require you to configure the pipeline as serverless.)
- **AUTO cost model (default).** Per run, SDP checks (a) is the query structurally incrementalizable, and (b) given the actual changeset size, is incremental cheaper than full. A large changeset can make full recompute cheaper even for an eligible query — so AUTO may still choose `FULL_RECOMPUTE`.
- **Technique selection.** When it does go incremental, the planner picks a specific technique based on the query shape. These are the human-readable technique names you see in the `planning_information` event-log message (`Flow '...' has been planned ... to be executed as ROW_BASED.`); the raw event payload spells them as the `MaintenanceType` enum (`MAINTENANCE_TYPE_ROW_BASED`, etc.):

| Technique (event-log message) | Incremental? | Triggered by |
|---|---|---|
| `FULL_RECOMPUTE` | No | Query not incrementalizable, or full is cheaper |
| `NO_OP` | n/a | No changes detected on base tables — refresh skipped |
| `APPEND_ONLY` | Yes | Source only got inserts (no upserts/deletes) |
| `ROW_BASED` | Yes | Modular changesets for `JOIN`/`FILTER`/`UNION ALL` composed via row tracking |
| `PARTITION_OVERWRITE` | Yes | Changes localized to whole partitions (MV co-partitioned with a source), rewritten as units |
| `GROUP_AGGREGATE` | Yes | Associative aggregates (`count`/`sum`/`mean`/`stddev`) at the top level of the query |
| `GENERIC_AGGREGATE` | Yes | Non-associative aggregates (e.g. `median`) at the top level — only affected groups recomputed |
| `WINDOW_FUNCTION` | Yes | Top-level `OVER (PARTITION BY ...)` window queries — only changed partitions recomputed |

  This mapping is **plan-decided, not guaranteed per function** — the same `SUM`/`COUNT` query can resolve to `GROUP_AGGREGATE`, `GENERIC_AGGREGATE`, or even `FULL_RECOMPUTE` depending on sources, changeset, and row-tracking state. Don't promise a technique in an interview; say "the cost model plans it."

- **MV recompute absorbs late data.** Because each refresh re-derives batch-equivalent state from the source (full or incremental delta), late-arriving rows in the source are naturally folded in on the next refresh — there's no watermark dropping them like there would be in a stateful streaming table. This is a reason to choose an MV over a streaming aggregate when correctness on late data matters more than exactly-once cost control.

**What forces a full recompute**

- **Classic (non-serverless) compute** — always full.
- **Non-deterministic functions** in the body (e.g. `rand()`); exception: non-deterministic *time* functions (`current_date()`, `current_timestamp()`, `now()`) are allowed **in `WHERE`** only. (In the event log these surface as `PlanNotDeterministicSubType` values `NON_DETERMINISTIC_EXPRESSION` / `TIME_FUNCTION`.)
- **Unsupported operations** — `WITH RECURSIVE` CTEs, reads from views that contain expectations, an MV with a `DROP` expectation plus `NOT NULL` columns in its schema, subquery expressions, aggregates/window functions not at the top of the plan, `DISTINCT` aggregates, `MAP` types.
- **Unsupported sources** — volumes, external locations, foreign catalogs, foreign Iceberg tables. (Supported incremental sources: Delta tables incl. UC managed/external, MVs, streaming tables incl. `AUTO CDC ... INTO` targets, UC managed Iceberg v2/v3 — v3 recommended for best incremental support.)
- **Changed UDF** — SDP attempts to detect a UDF behavior change and full-refresh; but a UDF that calls other libraries can change silently, and then **you** must trigger the full refresh manually. Only deterministic UDFs are incrementalizable.
- **Re-initialization / change events** (`IssueType` enum in the `planning_information` payload) — schema change (`DATA_SCHEMA_CHANGED`), time-zone change (`TIME_ZONE_CHANGED`), data changed in a non-incrementalizable way (`DATA_HAS_CHANGED`), missing last-run timestamp (`PRIOR_TIMESTAMP_MISSING`), CDF disabled (`CDF_UNAVAILABLE`), row tracking off (`ROW_TRACKING_NOT_ENABLED`), vacuumed source files (`DATA_FILE_MISSING`), or first compute (`CHANGE_SET_MISSING`).
- **Row-tracking off** — many techniques (the starred ones in the support matrix: most joins, `UNION ALL`, `WHERE`/`HAVING`, `SELECT` exprs) require `delta.enableRowTracking` on the source; disabling it drops eligibility (`ROW_TRACKING_NOT_ENABLED`).

**Key configs / syntax**

`REFRESH POLICY` overrides the AUTO cost model. Default is `AUTO` if omitted.

| Policy | Incremental available | Incremental NOT available | Re-init required |
|---|---|---|---|
| `AUTO` (default) | cost model picks cheaper | full refresh | full refresh |
| `INCREMENTAL` | incremental | **falls back to full** | full if incrementalizable; **fails on `CREATE` if query can never incrementalize** |
| `INCREMENTAL STRICT` | incremental | **refresh FAILS** | full if incrementalizable, else fails |
| `FULL` | always full | always full | full |

Use `INCREMENTAL STRICT` when an unexpected full recompute would blow an SLA/cost budget — you want it to fail loudly so you can debug, not silently burn compute.

```sql
-- SQL surface (Databricks SQL / SDP MV)
CREATE OR REFRESH MATERIALIZED VIEW transaction_summary
REFRESH POLICY INCREMENTAL STRICT
AS SELECT account_id, COUNT(txn_id) AS txn_count, SUM(txn_amount) AS account_revenue
   FROM transactions_table
   GROUP BY account_id;
```

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import count, sum

@dp.materialized_view(
    refresh_policy="incremental_strict"
)
def transaction_summary():
    return (
        spark.read.table("transactions_table")
        .groupBy("account_id")
        .agg(
            count("*").alias("txn_count"),
            sum("txn_amount").alias("account_revenue"),
        )
    )
```

Force a one-off full recompute (Databricks SQL standalone MV):

```sql
REFRESH MATERIALIZED VIEW transaction_summary FULL;
```

In an SDP pipeline you full-refresh selected datasets or the whole pipeline via the pipeline's refresh semantics (the **Full refresh / Full refresh all** option on the update), not a per-MV SQL keyword.

Optimize the source tables to maximize incremental eligibility (Databricks recommends all three):

```sql
ALTER TABLE transactions_table SET TBLPROPERTIES (
  delta.enableRowTracking      = true,
  delta.enableChangeDataFeed   = true,
  delta.enableDeletionVectors  = true
);
```

**Check eligibility before you ship** — `EXPLAIN CREATE MATERIALIZED VIEW` confirms *structural* incrementalizability (it does NOT guarantee AUTO will choose incremental at runtime; the cost model can still pick full). Strip `CONSTRAINT ... EXPECT` clauses and fully-qualify sources first:

```sql
EXPLAIN CREATE MATERIALIZED VIEW foo
AS SELECT k, sum(v) FROM source.src_schema.tbl GROUP BY k;
-- == Incremental Update Eligibility ==
-- The Materialized View can be incrementally refreshed.
```

**Determine what actually happened** — query the pipeline event log for the planning decision:

```sql
SELECT timestamp, message
FROM event_log(TABLE(my_catalog.my_schema.transaction_summary))
WHERE event_type = 'planning_information'
ORDER BY timestamp DESC;
-- e.g. "Flow 'transaction_summary' has been planned ... to be executed as GROUP_AGGREGATE."
```

(In the raw `planning_information` payload the `MaintenanceType` enum maps the same way: anything other than `MAINTENANCE_TYPE_COMPLETE_RECOMPUTE` or `MAINTENANCE_TYPE_NO_OP` is an incremental technique. The `technique_information.incrementalization_issues[].issue_type` field, e.g. `INCREMENTAL_PLAN_REJECTED_BY_COST_MODEL`, tells you *why* it fell back.)

**Use cases**

- **Gold-layer aggregations / metrics** served to dashboards — large `GROUP BY` rollups where incremental refresh turns a full re-scan into a cheap delta apply.
- **Silver enrichment joins** against dimension tables where you want batch-correct, late-data-absorbing results without managing streaming state.
- In my Apollo Gen2 work the Bronze SCD2 tables are streaming (`@dp.table` + `dp.create_auto_cdc_flow`), but a gold reporting rollup over those Bronze entities is the natural MV candidate — `INCREMENTAL` policy on serverless, so daily JOB2 runs only reprocess the day's changed accounts instead of all 211 entities' history.

**Limitations & gotchas**

- **Serverless is mandatory for incremental** — the single most common "why is my MV always full-recomputing" answer is classic compute.
- **Be robust to full refresh even if the query is incrementalizable** — a full recompute against a source that has since deleted/archived old rows (retention threshold) will silently lose those rows and can even change the schema if columns disappeared. If records must be processed exactly once, use a **streaming table**, not an MV.
- **`AUTO` can full-recompute an eligible query** when the changeset is large enough that full is cheaper — eligibility (`EXPLAIN`) ≠ guaranteed incremental execution. Pin with `INCREMENTAL`/`INCREMENTAL STRICT` if you need predictability.
- **Per-technique incrementality is plan-decided, not per-function** — never claim "`SUM` is always `GROUP_AGGREGATE`."
- **Expectations narrow eligibility** — reading from a view with expectations, or a `DROP` expectation combined with `NOT NULL` schema columns, forces full recompute (`EXPECTATIONS_NOT_SUPPORTED` for the read-through-view case).
- **Row filters / column masks** on a source kill incremental refresh entirely.
- **UDF drift** is on you — if a UDF's behavior changes via an external library SDP can't see, manually full-refresh or the MV serves stale results.

**Interview soundbite:** An SDP materialized view always returns batch-equivalent results; on serverless it tries an incremental refresh — picking a plan-decided technique like `GROUP_AGGREGATE` or `ROW_BASED` and falling back to `FULL_RECOMPUTE` when the query is non-incrementalizable or a full recompute is simply cheaper — and I pin that behavior with `REFRESH POLICY INCREMENTAL STRICT` plus `event_log(...)` `planning_information` checks when an unexpected full refresh would break my SLA.

### Backfill

**What it is**
Backfilling is retroactively pushing historical data through a pipeline that was designed for current/streaming data — without disturbing the live incremental flow and without a full refresh. In SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) the canonical pattern is **multiple flows into ONE streaming table**: a continuous incremental flow (e.g. Auto Loader) plus one or more **one-time BATCH backfill flows** flagged with `ONCE`. Any number of append flows can write to a single target; each is an independent, separately-checkpointed `@dp.append_flow` / `CREATE FLOW`.

In Apollo Gen2 terms: the BRZ/STG streaming tables are fed by their default incremental flow off `ADLS incoming/`. When a new historical partition (or a corrected re-extract) shows up for one of the 211 entities, I add a `ONCE` backfill flow into the same streaming table instead of running a full refresh that would re-tear-down the SCD2 history.

**How it works (mechanics)**
- A streaming table can host **N flows**. The default flow (same name as the table) is created with the table; additional flows are declared standalone against an existing `create_streaming_table` target.
- The incremental flow is a **streaming read** (must return a streaming DataFrame). The backfill flow is flagged `ONCE`, which flips it to a **BATCH read** (must return a batch DataFrame) that runs exactly once.
- `ONCE` semantics: the flow runs on first pipeline update, then becomes **idle** and is **skipped on every subsequent normal update**. It remains in the pipeline graph (clear audit trail). The ONLY thing that re-runs it is a **full refresh**, which re-executes all flows to recreate state.
- This is the trap to protect against: a full refresh re-runs the `ONCE` flow AND clears all state/checkpoints, rebuilding the streaming table from its sources. If the backfill source directory is gone, or you don't want history rebuilt, set the table property `pipelines.reset.allowed = false` to forbid full refresh entirely (it still allows incremental writes — it only blocks the destructive reset).
- **Independent checkpoints, keyed by flow name.** Each flow's streaming checkpoint is identified by its flow name. Consequences: renaming a flow orphans its checkpoint (the renamed flow is treated as brand new and reprocesses), and you cannot reuse a flow name within a pipeline (the old checkpoint won't match the new definition). Name backfill flows deterministically (e.g. `..._backfill_2024`). To reset one flow's checkpoint without a full table refresh, pass its fully-qualified `catalog.schema.flow_name` to `reset_checkpoint_selection` on the pipeline update API (the simple name fails with `IllegalArgumentException`).

**Key configs / syntax**

| Knob | Python | SQL | Notes |
| --- | --- | --- | --- |
| One-time flag | `once=True` on `@dp.append_flow` | `INSERT INTO ONCE` (or `AUTO CDC ONCE`) | Flow-level, NOT a reader option |
| Backfill read type | `spark.read...` (batch DF) | plain `read_files(...)` (no `STREAM`) | Must be batch when `ONCE` |
| Incremental read type | `spark.readStream...` (streaming DF) | `STREAM read_files(...)` / `STREAM(table)` | Default flow stays streaming |
| Flow name | `name="..."` (defaults to fn name) | `CREATE FLOW <flow_name>` | Keys the checkpoint |
| Target | `target="<st>"` | `INSERT INTO <st> BY NAME` | `BY NAME` = column-name match |
| Protect backfilled data | `table_properties={"pipelines.reset.allowed": "false"}` | `TBLPROPERTIES (pipelines.reset.allowed = false)` | Default is `true`; set on the target ST |

`@dp.append_flow` parameters: `function` (the decorated fn, required), `target` (required), `name` (defaults to fn name), `once` (default `False`), `comment`, `spark_conf`. The function must return a streaming DataFrame normally, or a **batch** DataFrame when `once=True`.

Continuous incremental flow + one-time batch backfill into the SAME streaming table (Python):

```python
from pyspark import pipelines as dp

source_root = spark.conf.get("registration_events_source_root_path")
incremental_path = f"{source_root}/*/*/*"

# Target streaming table (protect history against accidental full refresh)
dp.create_streaming_table(
    name="registration_events_raw",
    comment="Raw registration events",
    table_properties={"pipelines.reset.allowed": "false"},
)

# 1) Continuous incremental Auto Loader flow (streaming read)
@dp.append_flow(
    target="registration_events_raw",
    name="flow_registration_events_raw_incremental",
)
def ingest():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("modifiedAfter", "2024-12-31T23:59:59.999+00:00")
        .load(incremental_path)
    )

# 2) One-time BATCH backfill flow, flagged ONCE (note spark.read, NOT readStream)
def setup_backfill_flow(year: str):
    backfill_path = f"{source_root}/year={year}/*/*"
    @dp.append_flow(
        target="registration_events_raw",
        once=True,
        name=f"flow_registration_events_raw_backfill_{year}",
        comment=f"Backfill {year} raw registration events",
    )
    def backfill():
        return (
            spark.read
            .format("json")
            .option("inferSchema", "true")
            .load(backfill_path)
        )

for year in ["2024", "2023", "2022"]:
    setup_backfill_flow(year)
```

Same pattern in SQL — incremental `STREAM` flow plus `INSERT INTO ONCE` backfill flows into one streaming table:

```sql
-- Target streaming table; block destructive full refresh
CREATE OR REFRESH STREAMING TABLE registration_events_raw
  TBLPROPERTIES (pipelines.reset.allowed = false);

-- Continuous incremental flow (streaming read)
CREATE FLOW registration_events_raw_incremental
AS INSERT INTO registration_events_raw BY NAME
SELECT * FROM STREAM read_files(
  "/Volumes/gc/demo/event_registration/*/*/*",
  format => "json",
  inferColumnTypes => true,
  schemaEvolutionMode => "addNewColumns",
  modifiedAfter => "2024-12-31T23:59:59.999+00:00"
);

-- One-time BATCH backfill flow (ONCE => no STREAM keyword)
CREATE FLOW registration_events_raw_backfill_2024
AS INSERT INTO ONCE registration_events_raw BY NAME
SELECT * FROM read_files(
  "/Volumes/gc/demo/event_registration/year=2024/*/*",
  format => "json",
  inferColumnTypes => true
);
```

`CREATE FLOW` grammar (both backfill-capable):

```sql
CREATE FLOW flow_name [COMMENT comment] AS
{
  AUTO CDC [ONCE] INTO target_table create_auto_cdc_flow_spec |
  INSERT [ONCE] INTO target_table BY NAME query
}
```

**AUTO CDC backfill subtlety:** `AUTO CDC ... ONCE` also exists (one-time CDC hydration), but unlike append flows the AUTO CDC source must still be a **streaming** source even when `ONCE` is set (the docs state this explicitly). So for Apollo Gen2 BRZ SCD2 tables fed by `create_auto_cdc_flow`, a one-time CDC backfill uses `once=True` on the CDC flow with a streaming source — not a batch read. The `name` and `once` parameters on `create_auto_cdc_flow` (Python) and `AUTO CDC [ONCE] INTO` (SQL) are the supported way to run both an incremental CDC flow and a one-time CDC hydration into the same target.

**REPLACE WHERE flow (targeted predicate backfill, Beta):** a `REPLACE WHERE` flow re-materializes only the rows matching a predicate, so you can backfill/restate a slice. It is in **Beta** and **requires the Preview pipelines channel** (set the table property `pipelines.channel = "PREVIEW"`); `BY NAME` is required. It exists in two forms — inside an SDP pipeline, and for standalone streaming tables created in Databricks SQL. For the standalone case, direct DML is the simpler restatement path:

```sql
INSERT INTO orders_enriched
SELECT * FROM orders_enriched_legacy
WHERE date < '2025-01-01';
```

Warning on `REPLACE WHERE`: a full refresh re-runs the flow with ONLY its current predicate. A 7-day predicate running for a year, then fully refreshed, leaves the table with just the last 7 days — everything else is permanently deleted. Same fix: `pipelines.reset.allowed = false`.

**Use cases**
- Hydrate a streaming table with years of historical partitions on top of a live incremental feed (one `ONCE` flow per year for parallelism).
- Re-extract / correct one Apollo Gen2 entity's history without nuking SCD2 on the whole BRZ table.
- Complex one-shot load that must be batch (e.g. a heavy aggregation) before insertion, which streaming semantics can't express.
- Consolidating multiple historical sources into one ST instead of `UNION` (avoids full refresh).

**Limitations & gotchas**
- **The classic slip:** `ONCE` is a **flow-level** flag and the backfill is a **BATCH** read — it is NOT an Auto Loader option and NOT a streaming read. `once=True` requires `spark.read` (Python) / no `STREAM` keyword (SQL). Returning a streaming DataFrame with `once=True` is an error.
- `ONCE` re-runs on full refresh. Without `pipelines.reset.allowed=false`, an accidental full refresh re-injects the backfill AND clears state, rebuilding the ST from source — silently duplicating or dropping data (a full refresh drops records the source no longer retains).
- Backfill is append-only into the target; the pipeline must **tolerate duplicates** if the same data lands twice (idempotency is on you).
- Schema of historical data must be compatible with current schema. `cloudFiles.schemaEvolutionMode` defaults to `addNewColumns` when no schema is provided (and to `none` when a schema is provided); `addNewColumns` adds new columns but does NOT evolve existing column types — type changes land in the rescued data column.
- Flow names key checkpoints: don't rename, don't reuse. Reset a single flow's checkpoint via `reset_checkpoint_selection` with the fully-qualified flow name.
- Expectations can't live in the `@dp.append_flow` body — declare them on the target streaming table / `create_streaming_table`.
- AUTO CDC `ONCE` still needs a streaming source; only append-flow `ONCE` is a batch read.

**Interview soundbite:** "Backfill in SDP is just a second flow into the same streaming table — a one-time BATCH `@dp.append_flow(once=True)` (`INSERT INTO ONCE ... BY NAME` in SQL) running alongside the continuous Auto Loader flow; `ONCE` is flow-level and re-fires only on a full refresh, so I set `pipelines.reset.allowed=false` on the target to protect the backfilled history."

### Append Flow & AUTO CDC Flow (SCD1 and SCD2)

**What it is**

Two flow *types* that write into a streaming table (ST) target in SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines). A **flow** is the unit of data movement; every ST/MV gets a *default* append flow at creation (named the same as the target), and you can attach extra named flows to the same target.

| Flow type | API (Python / SQL) | What it does | Target rule |
|---|---|---|---|
| **Append** | `@dp.append_flow` / `CREATE FLOW ... AS INSERT INTO ... BY NAME` | Appends new rows each update (structured-streaming append mode). Many append flows can fan-in to one ST. | ST or sink |
| **AUTO CDC** | `dp.create_auto_cdc_flow` / `CREATE FLOW ... AS AUTO CDC INTO` | Upsert/delete from a change feed (CDF) into an ST as SCD1 or SCD2. | ST only; an ST targeted by AUTO CDC can be targeted *only* by other AUTO CDC flows |
| **AUTO CDC FROM SNAPSHOT** | `dp.create_auto_cdc_from_snapshot_flow` / SQL equivalent | Diffs successive *full snapshots* to synthesize a change feed, then applies it as SCD1/SCD2. | ST only; cannot share a target with `create_auto_cdc_flow` |

Naming note: `create_auto_cdc_flow` replaces the legacy `apply_changes()` (same signature); SQL `AUTO CDC INTO` replaces legacy `APPLY CHANGES INTO`. Use the AUTO CDC names.

**How it works (mechanics)**

- **Append flow fan-in:** instead of `spark.readStream.table(a).union(...)`, declare one ST and attach N `@dp.append_flow` functions, each reading a different streaming source. Each flow keeps its **own checkpoint** (keyed by flow name), so you add a source without a full refresh. Renaming a flow orphans its checkpoint — it becomes a brand-new flow and re-reads from scratch; you also cannot reuse a flow name in a pipeline.
- **AUTO CDC upsert default:** for each `INSERT`/`UPDATE` event, match on `keys`; matching row → update, no match → insert. `apply_as_deletes` reclassifies an event as a delete. Out-of-order events are reordered by `sequence_by` automatically (this is the whole point vs. hand-rolled `MERGE INTO`).
- **Tombstones:** an AUTO CDC delete is retained temporarily as a tombstone in the backing Delta table (to handle out-of-order arrivals), and a metastore view filters it out, so late out-of-order events still resolve correctly. Retention defaults to **two days**, configurable via the `pipelines.cdc.tombstoneGCThresholdInSeconds` **table property**. Set it above your max event-arrival delay if Auto Loader feeds the source (Auto Loader gives no file-ordering guarantee). Docs frame the tombstone/GC mechanism specifically around out-of-order **delete** handling for SCD type 2 sources.
- **SCD1 vs SCD2:** SCD1 = current-state only (overwrite in place; a delete removes the row, no `__START_AT`/`__END_AT`). SCD2 = full history; SDP adds `__START_AT` / `__END_AT` columns (same dtype as `sequence_by`), closes the prior version's `__END_AT` when a new version arrives, and a delete closes out the current version (sets `__END_AT`) rather than hard-deleting.
- **Backing objects (Hive metastore only):** declaring an AUTO CDC target `foo` creates a *view* `foo` plus an internal backing table named by prepending `__apply_changes_storage_` to the target name (`__apply_changes_storage_foo`) — query the view, never the backing table. (Applies to `AUTO CDC` only, not `AUTO CDC FROM SNAPSHOT`, and only under Hive metastore, not Unity Catalog.)

**Key configs / syntax**

`create_auto_cdc_flow` full signature and parameter semantics (doc-verified against `ldp-python-ref-apply-changes`):

| Param | Type | Default | Notes |
|---|---|---|---|
| `target` | str | — required | ST created via `dp.create_streaming_table()` |
| `source` | str | — required | streaming change feed |
| `keys` | list | — required | primary key column(s); list of strings or `col()` (no qualifiers) |
| `sequence_by` | str / `col()` / `struct(...)` | — required | sortable per-row ordering; use `struct("ts","id")` to break ties. NULL sequencing values are not supported |
| `ignore_null_updates` | bool | `False` | `True` = nulls in event keep existing target value (partial updates); also applies to nested columns |
| `apply_as_deletes` | str / `expr()` | `None` | e.g. `"operation = 'DELETE'"` |
| `apply_as_truncates` | str / `expr()` | `None` | **SCD1 only**; SCD2 does not support truncate |
| `column_list` / `except_column_list` | list | all columns | which source cols land in target |
| `stored_as_scd_type` | str / int | **`1`** | `1` or `2` (or `"1"`/`"2"`) |
| `track_history_column_list` / `track_history_except_column_list` | list | all columns | SCD2 only: which cols trigger a new history version |
| `name` | str | = `target` | flow name (= checkpoint id) |
| `once` | bool | `False` | one-time backfill; return value must be a batch DF |

Critical gotcha to verbalize: `track_history_except_column_list`. If you don't exclude operational-metadata columns (ingestion timestamp, `_rescued_data`, a re-run marker), every pipeline re-run that touches only those cols spawns a **false SCD2 version** — history balloons with no real business change.

**Append flow — fan-in union (PySpark):**

```python
from pyspark import pipelines as dp

dp.create_streaming_table("customers_us")

@dp.append_flow(target="customers_us", name="us_west")
def append_west():
    return spark.readStream.table("customers_us_west")

@dp.append_flow(target="customers_us", name="us_east")
def append_east():
    return spark.readStream.table("customers_us_east")
```

**Append flow — fan-in union (SQL):**

```sql
CREATE OR REFRESH STREAMING TABLE customers_us;

CREATE FLOW us_west AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_west);

CREATE FLOW us_east AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_east);
```

**Append flow — one-time backfill (SQL):**

```sql
CREATE FLOW backfill AS INSERT INTO ONCE customers_us BY NAME
SELECT * FROM read_files("/mnt/hist/customers", "csv");
```

**AUTO CDC — SCD1 (PySpark).** Target-level expectations go on `create_streaming_table` as dict params, NOT on the flow:

```python
from pyspark import pipelines as dp

dp.create_streaming_table(
    name="customers_current",
    expect_all_or_drop={"valid_id": "id IS NOT NULL"},
)

dp.create_auto_cdc_flow(
    target="customers_current",
    source="customers_cdc_clean",
    keys=["id"],
    sequence_by="operation_date",
    apply_as_deletes="operation = 'DELETE'",
    except_column_list=["operation", "operation_date", "_rescued_data"],
    stored_as_scd_type=1,
)
```

**AUTO CDC — SCD1 (SQL):**

```sql
CREATE OR REFRESH STREAMING TABLE customers_current
  (CONSTRAINT valid_id EXPECT (id IS NOT NULL) ON VIOLATION DROP ROW);

CREATE FLOW customers_current_cdc AS AUTO CDC INTO
  customers_current
FROM stream(customers_cdc_clean)
KEYS (id)
APPLY AS DELETE WHEN operation = 'DELETE'
SEQUENCE BY operation_date
COLUMNS * EXCEPT (operation, operation_date, _rescued_data)
STORED AS SCD TYPE 1;
```

**AUTO CDC — SCD2 (PySpark).** This is the Apollo Gen2 Bronze pattern — STG streaming table feeds a BRZ SCD2 table per entity:

```python
from pyspark import pipelines as dp

dp.create_streaming_table("account_brz")

dp.create_auto_cdc_flow(
    target="account_brz",
    source="account_stg",
    keys=["accountId"],
    sequence_by="SinkModifiedOn",
    apply_as_deletes="IsDelete = 'true'",
    except_column_list=["IsDelete", "_rescued_data"],
    stored_as_scd_type="2",
    track_history_except_column_list=["SinkModifiedOn", "_ingest_ts"],
)
```

**AUTO CDC — SCD2 (SQL).** Note `TRACK HISTORY ON * EXCEPT (...)` — the `*` is required (clause grammar is `TRACK HISTORY ON {columnList | * EXCEPT (exceptColumnList)}`):

```sql
CREATE OR REFRESH STREAMING TABLE account_brz;

CREATE FLOW account_brz_cdc AS AUTO CDC INTO
  account_brz
FROM stream(account_stg)
KEYS (accountId)
APPLY AS DELETE WHEN IsDelete = 'true'
SEQUENCE BY SinkModifiedOn
COLUMNS * EXCEPT (IsDelete, _rescued_data)
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (SinkModifiedOn, _ingest_ts);
```

**AUTO CDC FROM SNAPSHOT — for the 5 full-load entities (PySpark).** No change feed exists, so SDP diffs snapshots:

```python
from pyspark import pipelines as dp

dp.create_streaming_table("region_brz")

dp.create_auto_cdc_from_snapshot_flow(
    target="region_brz",
    source="region_snapshot",
    keys=["regionId"],
    stored_as_scd_type=2,
)
```

**Use cases**

- **Append fan-in:** consolidate per-region / per-Kafka-topic / multi-directory streams into one ST without `UNION` and without full refresh; `INSERT INTO ONCE` for one-time historical backfill (re-runs only on full refresh).
- **AUTO CDC SCD1:** current-state dimensions where history is not needed (latest customer address).
- **AUTO CDC SCD2:** auditable history — exactly the 211 BRZ tables in Apollo Gen2 (`account_stg` → `account_brz` via `sequence_by=SinkModifiedOn`), tracking every D365 change.
- **FROM SNAPSHOT:** the 5 full-load entities with no CDF — diff today's vs. yesterday's full dump.

**Limitations & gotchas**

- AUTO CDC source must be a **streaming** source read with `STREAM(...)`; if the read sees an update/delete on an existing record it errors — that's the SCD2-on-SCD2 / streaming-on-mutable-source incident. Fix: read from append-only sources, or add the `skipChangeCommits` read option (camelCase in `option()`; SQL `WITH (SKIPCHANGECOMMITS)`) to tolerate change commits. Note: `skipChangeCommits` cannot be set on a source that is itself the target of an AUTO CDC flow.
- `sequence_by` must be strictly orderable and fine-grained, and NULL sequencing values are unsupported. File-modification-time was too coarse in Apollo Gen2 (many rows shared a tick → nondeterministic version order); switch to a real event timestamp or `struct(ts, id)` to break ties.
- **Expectations cannot be declared on `@dp.append_flow` or on the AUTO CDC flow** — they must live on the target ST (`create_streaming_table(expect_all=...)` or the `CONSTRAINT` clause). For SCD2 with an explicit schema you must include `__START_AT`/`__END_AT` (same dtype as `sequence_by`).
- `apply_as_truncates` / `APPLY AS TRUNCATE WHEN` is **SCD1-only**.
- Skipping `track_history_except_column_list` on SCD2 = false versions on every metadata-only re-run (default is `TRACK HISTORY ON *`, i.e. track all columns).
- For-loop / fan-out: each generated flow reads the full source independently (throughput hit on Kafka); you must explicitly pass a Python value into the flow-defining function (same rule as creating tables in a `for` loop); and never *shrink* the loop's value list — a dropped value silently drops its target data.

**Interview soundbite:** Append flows fan multiple streaming sources into one streaming table without `UNION` or full refresh, while `create_auto_cdc_flow` upserts a change feed into that table as SCD1 (current-only) or SCD2 (history via `__START_AT`/`__END_AT`), reordering out-of-order events by `sequence_by` and using `track_history_except_column_list` (SQL: `TRACK HISTORY ON * EXCEPT`) to keep operational-metadata columns from spawning phantom history versions.

### Limitations of ST, MV, SDP, Flows & Expectations (consolidated)

**What it is**
A single reference of the hard constraints across the five SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) building blocks: streaming tables (ST = `@dp.table` / `CREATE OR REFRESH STREAMING TABLE`), materialized views (MV = `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW`), the pipeline/runtime itself, flows (`@dp.append_flow`, `dp.create_auto_cdc_flow`, `@dp.update_flow`, `dp.create_sink`, REPLACE WHERE), and expectations (`@dp.expect*` / `CONSTRAINT ... EXPECT`). Knowing where each object *breaks* is what separates "I've used SDP" from "I've operated SDP in production" — every Apollo Gen2 incident I hit maps to one row below.

**How it works (mechanics)**
Each object inherits the processing model of its underlying engine: ST inherits Spark Structured Streaming's append-only semantics (a stream throws if the source mutates); MV inherits batch recompute semantics with an optional incremental fast-path that only exists on serverless; flows are the foundational read-process-write unit and gate which CDC/aggregate/sink patterns are even legal; expectations are row-level boolean filters injected into the query plan. The limitations fall out of those models, not from arbitrary product gating.

#### Consolidated limitations by object

| Object | Limitation | Mechanism / why | Workaround |
|---|---|---|---|
| **Streaming Table (ST)** | Source must be **append-only** | Structured Streaming throws on `UPDATE`/`DELETE`/`MERGE INTO`/`OVERWRITE` in the source | Use `skipChangeCommits` (processes only appends) **or** switch to an MV |
| **ST** | `skipChangeCommits` **cannot** be used when the ST is the **target of an AUTO CDC flow** (`create_auto_cdc_flow`) | The flag is a `spark.readStream.option()` on the read side; AUTO CDC owns the write side | Read the upstream's Change Data Feed instead, or stage to an intermediate ST first |
| **ST** | Reading from the **target of an `AUTO CDC ... INTO`** (or any update-producing op) as a streaming source fails | Those ops emit updates, not appends; STs reject update inputs (set `skipChangeCommits` on the read, or use an MV) | Make the downstream an MV, or read with `skipChangeCommits` |
| **ST** | **Late data past the watermark is dropped** | `WATERMARK col DELAY OF INTERVAL n` closes the time window; later records are silently discarded | Widen the delay (costs state/memory) or backfill via REPLACE WHERE |
| **ST** | **Full refresh is destructive** on short-retention sources (Kafka, file sources past retention) | `REFRESH STREAMING TABLE t FULL` truncates and reprocesses from source; missing source data = permanent loss | Keep a bronze ST with full history; set `pipelines.reset.allowed='false'` |
| **ST** | Changing **stateful logic** (watermark threshold, aggregation/window keys) forces a **full refresh** | Existing checkpoint state is incompatible with new logic | Plan logic changes; recompute from a full-history bronze layer |
| **ST** | `TRIGGER ON UPDATE`: max **10 upstream tables** (and 30 upstream views) per ST; max **1000** STs/MVs with `TRIGGER ON UPDATE` per workspace; `AT MOST EVERY INTERVAL` defaults to and cannot be **< 1 minute** | Trigger-scheduling limits | Reduce sources or use scheduled/continuous trigger |
| **Materialized View (MV)** | **Incremental refresh only on serverless** | Incremental refresh requires serverless pipelines; classic compute always full-recomputes | Run the pipeline on serverless |
| **MV** | Many ops **force full recompute** even on serverless: non-deterministic functions (`rand()`, etc.), unsupported query shapes/operators (e.g. complex joins) | Cost model can't compute a delta for these; the cost model also picks `FULL_RECOMPUTE` when it is cheaper | Use `EXPLAIN CREATE MATERIALIZED VIEW` (DBR 17.3+, strip `CONSTRAINT...EXPECT` first) to check structural eligibility; rewrite to deterministic, simple aggregates; pin `REFRESH POLICY INCREMENTAL` / `INCREMENTAL STRICT` to override the cost model |
| **MV** | **Not low-latency** | Batch flow; recomputes on trigger, not row-by-row | Use an ST for freshness/low latency |
| **MV** | **No identity columns / surrogate keys**; identity values **may be recomputed** on refresh | Recompute can re-issue identity values | Databricks recommends identity columns only on STs (per Pipeline Limitations); identity columns are also unsupported on AUTO CDC targets |
| **SDP pipeline / runtime** | **`PIVOT` clause is not supported** | `pivot` requires eager loading of input to compute the output schema, which pipelines do not support | Pre-compute the pivot upstream |
| **MV** | No `OPTIMIZE`/`VACUUM` (auto-managed); `CONSTRAINT...EXPECT` clauses must be stripped before `EXPLAIN CREATE MATERIALIZED VIEW` | Maintenance is engine-owned | n/a |
| **SDP pipeline / runtime** | **Cannot run arbitrary Python** in dataset functions; dataset fns must **return a Spark DataFrame** | SDP evaluates dataset code multiple times during planning + runs; side effects break this | Do imperative work in a *separate* upstream job (my Apollo Gen2 two-job pattern: JOB1 notebook preprocesses → JOB2 SDP pipeline) |
| **SDP** | **Banned** ops inside dataset fns: `collect()`, `count()`, `toPandas()`, `save()`, `saveAsTable()`, `start()`, `toTable()` | These materialize/trigger/write outside the declarative graph | Express logic as transformations on the returned DataFrame |
| **SDP** | Each **dataset defined once**; target of a **single operation** across all pipelines | Declarative graph requires one owner per dataset | Exception: STs accept **multiple append flows** (fan-in) |
| **SDP** | Workspace concurrency: **1000 concurrent pipeline updates**; **100 source files** if only individual files/notebooks are referenced; **50 source entries** (files or folders), with up to **1000 files** referenced via folders | Workspace/pipeline quotas | Organize source into folders; split pipelines |
| **SDP** | Requires the **Premium plan**; **expectations** additionally require the **Advanced product edition** (vs `Core` ingest-only / `Pro` CDC) | Product gating | Set pipeline `edition` to `Advanced` (the all-features edition) |
| **Flows — AUTO CDC** (`create_auto_cdc_flow`) | Source **must be a streaming, append-only** source; target **must be an ST** | AUTO CDC is a streaming flow type | Stage CDC data into a streaming bronze first |
| **Flows — AUTO CDC** | An ST that is an AUTO CDC target can **only** be targeted by **other AUTO CDC flows** (not append flows) | Mixed write semantics on one target are disallowed | Keep CDC targets pure |
| **Flows — Update flow** (`@dp.update_flow`) — **Python-only** | Writes only to **sinks**; emits only changed records of non-watermarked streaming aggregates; used by real-time mode (`pipelines.trigger = "RealTime"`) | New flow type, sink-scoped | n/a |
| **Flows — Sinks** (`dp.create_sink`) — **Public Preview** | **Python only** (no SQL); **streaming only** (no batch); **only `append_flow` + `update_flow`** can write (no `create_auto_cdc_flow`); **expectations not supported**; can't read a sink in a dataset def; full refresh **does not clear** the sink (data is re-appended); Delta table names must be **fully qualified** (UC: `catalog.schema.table`; HMS: `schema.table`) | Sinks are external streaming targets outside the managed graph | Use Kafka/EventHubs/Delta formats (or custom Python data source) |
| **Flows — REPLACE WHERE** — **Beta** | Requires **PREVIEW** channel (`pipelines.channel='PREVIEW'`); target must be **created in the pipeline**; **one** REPLACE WHERE flow per target; target **can't** also be an AUTO CDC/append target; **expectations not supported**; **`BY NAME` required**; full refresh re-runs only the **current predicate** (older predicate-override/DML rows are permanently deleted); incremental refresh requires **serverless** | Selective overwrite-by-predicate semantics | Set `pipelines.reset.allowed='false'`; backfill history via `INSERT INTO` |
| **Expectations** | **Cannot mix actions** in one `expect_all` dict | A single `expect_all*` decorator applies **one** collective action (warn/drop/fail) | Use separate `expect_all`, `expect_all_or_drop`, `expect_all_or_fail` decorators |
| **Expectations** | **Row-level only** — `expectation_expr` may use literals, column identifiers, and **deterministic built-in SQL functions/operators**, but **no aggregate, analytic window, ranking window, or table-valued generator functions**, and **no subqueries**; no custom Python / no external service calls | Evaluated per-row in the query plan | Compute aggregates upstream and expect on the result column |
| **Expectations** | **FAIL** (`expect_or_fail` / `ON VIOLATION FAIL UPDATE`) **stops the update on the first invalid record** and atomically rolls back the table-update transaction; **no metrics recorded** for FAIL; failure of one flow does **not** fail other parallel flows | First bad row stops that flow's update | Use `warn`/`drop` if you need metrics + continuity |
| **Expectations** | **Not supported** on: **sinks**, **AUTO CDC FROM SNAPSHOT** (`create_auto_cdc_from_snapshot_flow`), and **REPLACE WHERE** targets | Those flow/object types lack the expectation surface | For SNAPSHOT: apply SCD1 to an intermediate table, read its CDF, then AUTO CDC to the final table with expectations |
| **Expectations** | Multiple expectations with **grouped collective** actions are **Python-only** (SQL supports multiple expectations but not grouped collective actions) | Decorator-based grouping is a Python API feature | Repeat individual `CONSTRAINT ... EXPECT` clauses in SQL |

**Key configs / syntax**
The append-only escape hatch on an ST (note: illegal if the ST is an AUTO CDC target):

```python
from pyspark import pipelines as dp

@dp.table
def silver_b():
    return spark.readStream.option("skipChangeCommits", "true").table("bronze_a")
```

```sql
-- WITH read options require Databricks Runtime 17.3+
CREATE OR REFRESH STREAMING TABLE silver_b
AS SELECT * FROM STREAM bronze_a WITH (SKIPCHANGECOMMITS);
```

Multiple grouped expectations (Python-only collective action) — each decorator carries exactly one action:

```python
@dp.table
@dp.expect_all_or_drop({"valid_id": "id IS NOT NULL", "valid_ts": "ts > '2012-01-01'"})
@dp.expect_all("soft_checks", {"has_region": "region IS NOT NULL"})
def events():
    return spark.readStream.table("raw_events")
```

```sql
CREATE OR REFRESH STREAMING TABLE events(
  CONSTRAINT valid_id EXPECT (id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_ts EXPECT (ts > '2012-01-01') ON VIOLATION DROP ROW
) AS SELECT * FROM STREAM(raw_events);
```

Watermark to bound state and define the late-drop threshold (records past `DELAY OF INTERVAL` are dropped):

```sql
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

Check MV incrementalization eligibility (the `event_log` TVF; `event_type = 'planning_information'` reports the technique, e.g. `ROW_BASED`, `GROUP_AGGREGATE`, or `FULL_RECOMPUTE`):

```sql
SELECT timestamp, message
FROM event_log(TABLE(catalog.schema.my_mv))
WHERE event_type = 'planning_information'
ORDER BY timestamp DESC;
```

**Use cases**
- Picking ST vs MV: append-only growing source + low latency → ST; CDC/aggregate targets, automatic change propagation, can tolerate latency → MV (these are exactly the inputs that *break* an ST).
- The "SDP can't run arbitrary Python" limit is the architectural reason for a two-job pattern: in Apollo Gen2, JOB1 (a plain notebook) does the imperative preprocessing that's banned inside dataset functions, lands files in ADLS `incoming/`, and JOB2 (the SDP pipeline) declaratively builds 211 STG STs + 211 BRZ SCD2 tables.

**Limitations & gotchas**
- **Preview/Beta flags matter in an interview**: sinks are **Public Preview** and **Python-only**; the update flow is **Python-only** (no SQL surface); REPLACE WHERE is **Beta** and needs the **PREVIEW** channel. Naming a Beta feature as GA is a credibility hit.
- **Expectations are blocked on more surfaces than people expect** — sinks, AUTO CDC FROM SNAPSHOT, and REPLACE WHERE targets. I hit the SNAPSHOT one directly on my 5 full-load entities (`create_auto_cdc_from_snapshot_flow`): the documented fix is SCD1 to an intermediate table → read its CDF → AUTO CDC to the final table with the expectations attached. (Note: at the product-edition level, expectations also require the `Advanced` edition.)
- **Full refresh is a footgun** in three different objects (ST, REPLACE WHERE, and MV-from-Kafka) — all three can silently shrink your table if the source no longer retains the data.

**Interview soundbite:** "Every SDP object's limits trace back to its engine model — STs reject mutating sources because Structured Streaming is append-only, MVs only refresh incrementally on serverless, dataset functions ban `collect`/`saveAsTable` because the graph re-evaluates them, and expectations are row-level booleans blocked on sinks, snapshot CDC, and REPLACE WHERE — which is exactly why Apollo Gen2 splits imperative work into JOB1 and keeps JOB2 purely declarative."

### Use Cases of All (decision guide)

**What it is**
A single-page routing reference for picking the correct SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) primitive for a given job. Two orthogonal decisions are made on every node of the dataflow graph: (1) the **dataset type** — what kind of object you publish (streaming table, materialized view, temporary view), and (2) the **flow type** — how data lands into a streaming-table target (append, AUTO CDC, AUTO CDC FROM SNAPSHOT, or update flow into a sink). A "flow" is the unit of processing that writes into a target; a streaming table can have many flows fanning into it, while a materialized view has exactly one implicit flow.

**How it works (mechanics)**
- Dataset type is decided by **read semantics**: `spark.readStream` / `STREAM(...)` → streaming table (incremental, append-only consumption of the source); `spark.read` / plain `SELECT` → materialized view (you write full-recompute logic; the engine does an incremental refresh under the hood *only on serverless* — on classic compute an MV is always fully recomputed); not published at all → temporary view.
- Flow type is decided by **what the source emits**: append-only rows → default append flow; a row-level change feed (insert/update/delete events) → AUTO CDC; only periodic full extracts with no change feed → AUTO CDC FROM SNAPSHOT; need to push results out of the lakehouse → update flow into a sink.
- Every Python pipeline imports the module the same way; all decorators hang off `dp`. Import the SQL functions you reference (`col`, `expr`, `struct`) explicitly.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import col, expr, struct
```

**Key configs / syntax — Dataset type decision table**

| Dataset type | API (Python / SQL) | Read semantics | Published to UC? | Medallion layer | Concrete scenario |
|---|---|---|---|---|---|
| **Streaming table** | `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` | `spark.readStream` / `STREAM(...)` | Yes | Bronze (and incremental silver) | Apollo Gen2: 211 `*_STG` streaming tables ingesting Synapse-Link delta exports from ADLS `incoming/` via `read_files` — append-only, high-volume, never reprocess old files |
| **Materialized view** | `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` | `spark.read` / batch `SELECT` | Yes | Silver/Gold marts | Join `BRZ` patient + study tables into a gold "active enrollments per site" mart that must always be correct as upstream SCD2 rows change (incrementally refreshed only on serverless; full recompute on classic) |
| **Temporary view** | `@dp.temporary_view` / `CREATE TEMPORARY VIEW` | either | No (intermediate only) | any (glue) | Cleansed/typed projection of a raw `_STG` table reused by 3 downstream tables; you do not want to publish or pay storage for it |

```python
@dp.table()
def customers_stg():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load("/Volumes/.../incoming/customers")
    )

@dp.materialized_view()
def regional_sales():
    partners = spark.read.table("partners")
    sales = spark.read.table("sales")
    return partners.join(sales, on="partner_id", how="inner")

@dp.temporary_view()
def customers_typed():
    return spark.readStream.table("customers_stg").withColumn("id", col("id").cast("int"))
```

```sql
CREATE OR REFRESH STREAMING TABLE customers_stg
  AS SELECT * FROM STREAM read_files('/Volumes/.../incoming/customers', format => 'parquet');

CREATE OR REFRESH MATERIALIZED VIEW regional_sales
  AS SELECT * FROM partners INNER JOIN sales ON partners.partner_id = sales.partner_id;

CREATE TEMPORARY VIEW customers_typed
  AS SELECT CAST(id AS INT) AS id, * FROM STREAM(customers_stg);
```

**Key configs / syntax — Flow type decision table** (all flows below target a **streaming table**, except the MV which is implicit)

| Flow type | API (Python / SQL) | Source shape | SCD support | Medallion layer | Concrete scenario |
|---|---|---|---|---|---|
| **Append (default)** | implicit, or `@dp.append_flow` / `CREATE FLOW ... AS INSERT INTO ... BY NAME` | One or many append-only streams | n/a (no upsert) | Bronze ingest, fan-in silver | Union region-A + region-B + region-C `clicks` topics into one `clicks_bronze` ST without a `UNION` (each region is its own append flow, so adding a 4th region needs no full refresh) |
| **AUTO CDC** | `dp.create_auto_cdc_flow` / `CREATE FLOW ... AS AUTO CDC INTO` | Row-level change feed (CDF / Debezium / GoldenGate) | SCD1 **or** SCD2 | Bronze→Silver dimension | Apollo Gen2: 211 `BRZ` SCD2 tables — each `_STG` feed carries change rows; `sequence_by` orders events, `apply_as_deletes` handles tombstones, `track_history_except_column_list` excludes audit cols from history triggers |
| **AUTO CDC FROM SNAPSHOT** | `dp.create_auto_cdc_from_snapshot_flow` (Python only) | Periodic **full extracts**, no change feed | SCD1 **or** SCD2 | Bronze→Silver dimension | Apollo Gen2: the 5 full-load entities — each run is a complete snapshot; SDP diffs consecutive snapshots to derive inserts/updates/deletes, including deriving deletes for keys that vanished |
| **Update flow + Sink** | `@dp.update_flow` + `dp.create_sink` (Python only) | A streaming query | n/a | Gold egress / reverse-ETL | Push enriched fraud-scored events to a Kafka topic, or write gold aggregates to an external Delta table consumed outside Unity Catalog |

```python
dp.create_streaming_table("customers_brz")

dp.create_auto_cdc_flow(
    target="customers_brz",
    source="customers_stg",
    keys=["customer_id"],
    sequence_by="_change_ts",
    apply_as_deletes=expr("op = 'DELETE'"),
    stored_as_scd_type=2,
    track_history_except_column_list=["_change_ts", "_ingest_file"],
)
```

```python
dp.create_streaming_table("products_brz")

dp.create_auto_cdc_from_snapshot_flow(
    target="products_brz",
    source="products_snapshot_stg",
    keys=["product_id"],
    stored_as_scd_type=2,
)
```

```python
dp.create_sink(
    name="fraud_alerts_kafka",
    format="kafka",
    options={"kafka.bootstrap.servers": "broker:9092", "topic": "fraud_alerts"},
)

@dp.update_flow(target="fraud_alerts_kafka")
def to_kafka():
    return (
        spark.readStream.table("scored_events_gold")
        .selectExpr("CAST(event_id AS STRING) AS key", "to_json(struct(*)) AS value")
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE customers_brz;

CREATE FLOW customers_cdc AS AUTO CDC INTO customers_brz
  FROM STREAM(customers_stg)
  KEYS (customer_id)
  APPLY AS DELETE WHEN op = 'DELETE'
  SEQUENCE BY _change_ts
  STORED AS SCD TYPE 2
  TRACK HISTORY EXCEPT (_change_ts, _ingest_file);
```

**Use cases — one-glance "if you see X, reach for Y"**

| If the requirement is… | Dataset type | Flow type |
|---|---|---|
| High-volume raw ingest, never reprocess old files | Streaming table | Append (`read_files`/Auto Loader) |
| Merge several append-only sources into one target | Streaming table | `@dp.append_flow` ×N (not `UNION`) |
| Replicate an OLTP dimension that has a CDC feed, keep history | Streaming table | AUTO CDC, `stored_as_scd_type=2` |
| Same, but only nightly full dumps exist (no feed) | Streaming table | AUTO CDC FROM SNAPSHOT |
| Always-correct aggregation / join over changing sources | Materialized view | implicit (engine incremental refresh — serverless only; classic = full recompute) |
| Reusable intermediate not worth publishing | Temporary view | n/a |
| Stream results out to Kafka / external Delta (reverse-ETL) | (sink) | `create_sink` + `@dp.update_flow` (or `@dp.append_flow`) |

**Limitations & gotchas**
- **Defaults:** AUTO CDC and AUTO CDC FROM SNAPSHOT both default to `stored_as_scd_type=1` — you must explicitly set `2` to get history (`__START_AT`/`__END_AT` columns). Forgetting this silently gives SCD1 and no audit trail.
- **Snapshot semantics:** AUTO CDC FROM SNAPSHOT auto-derives deletes (a key present in target but absent from the new snapshot is closed/removed); AUTO CDC only deletes when you pass `apply_as_deletes` / `APPLY AS DELETE WHEN`.
- **Same target, one CDC API:** you cannot point both `create_auto_cdc_flow` and `create_auto_cdc_from_snapshot_flow` at the same streaming table.
- **Sink constraints:** `create_sink` accepts only `append_flow` and `update_flow` — not AUTO CDC; sinks are Python-only, streaming-only, and expectations are **not** enforced on sink writes. Full refresh does **not** clear a sink (data is re-appended).
- **Expectations + CDC:** expectations are **not supported with AUTO CDC FROM SNAPSHOT**; for AUTO CDC (feed-based), define the `CONSTRAINT ... EXPECT` on the target table. You also cannot define expectations inside an `@dp.append_flow` body — put them on the `create_streaming_table()` target.
- **AUTO CDC sequencing:** `sequence_by` must be a monotonically increasing representation of the correct event order, with one distinct update per key at each sequencing value; `NULL` sequence values are **not supported**. This is exactly the Apollo Gen2 incident where file-modification-time was too coarse (ties → non-deterministic ordering) — fix by combining columns to break ties: Python `sequence_by=struct("ts", "id")`, SQL `SEQUENCE BY STRUCT(ts, id)`.
- **Streaming-on-mutable-source:** AUTO CDC targets are themselves mutable; a plain `spark.readStream` off an SCD2 BRZ table for another flow throws on the first update/delete because streaming reads assume append-only sources. Consume the change feed instead, or set `skipChangeCommits` (Python) when reading the source, or target a materialized view (no append-only restriction).
- **Python-only flows:** AUTO CDC FROM SNAPSHOT, `update_flow`, and `create_sink` have no SQL surface; AUTO CDC and append flows exist in both. The AUTO CDC APIs require SDP `Pro` or `Advanced` edition, or serverless (`Core` runs streaming ingest only; the `edition` default is `ADVANCED`).
- **MV vs ST cost:** materialized views recompute (incrementally where possible, **serverless only** — classic compute always full-recomputes) and can full-recompute on non-incremental ops; streaming tables never reprocess consumed input — pick ST whenever append-only incremental is acceptable.

**Interview soundbite:** "I choose the dataset type by read semantics — streaming table for append-only incremental bronze, materialized view for always-correct silver/gold marts (incrementally refreshed on serverless), temporary view for unpublished glue — and the flow type by source shape: append for fan-in, AUTO CDC for change feeds, AUTO CDC FROM SNAPSHOT for periodic full extracts, and update-flow-into-a-sink for reverse-ETL egress, which is exactly the 211 STG-append + 211 BRZ AUTO-CDC-SCD2 split in our Apollo Gen2 pipelines."

### Expectations — Everything (types, actions, where logged)

**What it is**
Expectations are optional data-quality clauses attached to a Spark Declarative Pipelines (SDP) dataset (a streaming table, materialized view, or temporary view). Each is a triple: a **name/description** (unique per dataset, used as the metric identifier), a **constraint** (a SQL boolean expression evaluated row-by-row), and an **action** (what to do when the row fails). Unlike a database `CHECK` constraint — which rejects the write outright — an expectation lets you choose: keep the bad row and just count it, drop it, or fail the flow. There are exactly **six Python decorators** (`@dp.expect`, `@dp.expect_or_drop`, `@dp.expect_or_fail` for a single constraint; `@dp.expect_all`, `@dp.expect_all_or_drop`, `@dp.expect_all_or_fail` for a dict of constraints) plus the equivalent SQL `CONSTRAINT ... EXPECT ...` clause.

**How it works (mechanics)**

Three actions exist. Default is **warn**.

| Action | Python (single) | Python (plural / dict) | SQL clause | What happens to the row | Metrics recorded? |
|---|---|---|---|---|---|
| **warn** (default) | `@dp.expect` | `@dp.expect_all` | `EXPECT (...)` (no `ON VIOLATION`) | Violating row **written to target** anyway; pass/fail counted | Yes — `passed_records` / `failed_records` |
| **drop** | `@dp.expect_or_drop` | `@dp.expect_all_or_drop` | `EXPECT (...) ON VIOLATION DROP ROW` | Violating row **dropped before write**; counted | Yes — adds `dropped_records` |
| **fail** | `@dp.expect_or_fail` | `@dp.expect_all_or_fail` | `EXPECT (...) ON VIOLATION FAIL UPDATE` | First violation **aborts the flow**; if the operation is a table update, the transaction is atomically rolled back. Manual intervention required before reprocessing | **No** — `fail` records no data_quality metrics (the update died) |

Critical singular-vs-plural semantics:
- **Singular** decorators take two positional args: `(description, constraint)`. Stack multiple singular decorators to apply several independent checks, each with its own action and its own metric line.
- **Plural** decorators take **one Python dict** `{description: constraint, ...}`. The combining logic differs by action:
  - `expect_all` (warn): each constraint is **counted independently** — every key produces its own pass/fail metric, all rows still written.
  - `expect_all_or_drop`: a row is dropped if it **violates ANY** constraint in the dict (logical AND of all constraints must hold to survive). Per-constraint metrics still reported individually.
  - `expect_all_or_fail`: the flow fails if **ANY** row violates **ANY** constraint in the dict.
- You **cannot mix actions inside one dict**. One dict = one action. To mix warn + drop + fail, use three separate decorators / dicts.
- SQL supports multiple expectations per dataset (comma-separated `CONSTRAINT` clauses), but **only Python lets you group expectations into a dict and apply a collective action** (`expect_all*`). There is no `expect_all` keyword in SQL.

`fail`'s blast radius is **one flow, not the whole pipeline**: if you have multiple parallel flows, one flow failing on an expectation does not kill the others. (Apollo Gen2 relevance: with 422 SDP pipelines / many flows, an `expect_or_fail` on one STG entity rolls back only that entity's update — sibling entity flows keep running.)

**Key configs / syntax**

Singular decorators, stacked, on a streaming table:

```python
from pyspark import pipelines as dp

@dp.table
@dp.expect("valid_timestamp", "timestamp > '2012-01-01'")
@dp.expect_or_drop("valid_current_page", "current_page_id IS NOT NULL AND current_page_title IS NOT NULL")
@dp.expect_or_fail("valid_count", "count > 0")
def customers():
    return spark.readStream.table("datasets.samples.raw_customers")
```

Plural / dict decorators (reuse the same dict across many datasets — this is the portability win):

```python
from pyspark import pipelines as dp

valid_pages = {
    "valid_count": "count > 0",
    "valid_current_page": "current_page_id IS NOT NULL AND current_page_title IS NOT NULL",
}

@dp.table
@dp.expect_all(valid_pages)            # warn: each counted independently, all rows kept
def raw_data():
    return spark.readStream.table("source")

@dp.table
@dp.expect_all_or_drop(valid_pages)    # drop row if it violates ANY key (AND)
def prepared_data():
    return spark.read.table("raw_data")

@dp.table
@dp.expect_all_or_fail(valid_pages)    # fail flow if ANY row violates ANY key
def customer_facing_data():
    return spark.read.table("prepared_data")
```

SQL surface (each constraint comma-separated inside the table's column/constraint list):

```sql
CREATE OR REFRESH STREAMING TABLE customers(
  CONSTRAINT valid_customer_age EXPECT (age BETWEEN 0 AND 120),
  CONSTRAINT valid_current_page EXPECT (current_page_id IS NOT NULL AND current_page_title IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_count EXPECT (count > 0) ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM(datasets.samples.raw_customers);
```

Note SQL has no `expect_all` equivalent — Databricks docs recommend merging multiple checks into a single `EXPECT` with `AND` when you want one action/one metric line in SQL.

**Expectations on CDC / AUTO CDC targets.** `create_auto_cdc_flow` / `@dp.append_flow` write into a target created by `dp.create_streaming_table`. You cannot decorate the CDC/append flow function itself — you put the expectations on the **target table declaration** via the `expect_all=`, `expect_all_or_drop=`, `expect_all_or_fail=` dict parameters of `dp.create_streaming_table` (these params provide the same behavior and syntax as the decorators, just as keyword arguments). Same "can't mix actions in one dict" rule applies. (Apollo Gen2: this is exactly how you'd guard the 211 BRZ SCD2 tables built by `create_auto_cdc_flow` — expectations attach to the `create_streaming_table` target, not to the flow.)

```python
from pyspark import pipelines as dp

dp.create_streaming_table(
    name="brz_account",
    expect_all_or_drop={
        "valid_pk": "account_id IS NOT NULL",
        "valid_seq": "SinkModifiedOn IS NOT NULL",
    },
)

dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",
    keys=["account_id"],
    sequence_by="SinkModifiedOn",
    stored_as_scd_type=2,
    apply_as_deletes="Op = 'D'",
    track_history_except_column_list=["SinkModifiedOn"],
)
```

SQL equivalent puts the `CONSTRAINT` in the target's `CREATE STREAMING TABLE`, then the `AUTO CDC` flow targets it:

```sql
CREATE OR REFRESH STREAMING TABLE brz_account(
  CONSTRAINT valid_pk EXPECT (account_id IS NOT NULL) ON VIOLATION DROP ROW
);

CREATE FLOW brz_account_cdc AS AUTO CDC INTO brz_account
FROM STREAM(stg_account)
KEYS (account_id)
APPLY AS DELETE WHEN Op = 'D'
SEQUENCE BY SinkModifiedOn
STORED AS SCD TYPE 2;
```

**Where it is logged.** Two completely different destinations depending on action — this is the high-leverage interview detail:

1. **warn and drop → the pipeline EVENT LOG** (a queryable Delta table). The relevant events have `event_type = 'flow_progress'`, and the metrics live in nested JSON under `details:flow_progress.data_quality`:
   - `details:flow_progress.data_quality.dropped_records` — count dropped (drop action).
   - `details:flow_progress.data_quality.expectations` — an array of per-constraint objects, each with `name`, `dataset`, `passed_records`, `failed_records`. `failed_records` only says the row violated the check — per the docs it "tracks whether the expectation was met, but does not describe what happens to the records (warn, fail, or drop)."
   - Also visible in the UI: pipeline → dataset → **Data quality** tab.
2. **fail → NOT in data_quality metrics.** Because the update aborts, no metrics are written. Instead an `EXPECTATION_VIOLATION` error appears in the **failed update's error details**. With verbosity `VERBOSITY_ALL` the error message includes the violated expectation(s), the offending **input record**, and the **output record**, letting you pinpoint the bad row (verbosity `VERBOSITY_OUTPUT` shows only the output record; `VERBOSITY_NONE` shows neither):

```console
[EXPECTATION_VIOLATION] Flow 'sensor-pipeline' failed to meet the expectation.
Violated expectations: 'temperature_in_valid_range'.
Input data: '{"id":"TEMP_001","temperature":-500,"timestamp_ms":"1710498600"}'.
Output record: '{"sensor_id":"TEMP_001","temperature":-500,"change_time":"2024-03-15 10:30:00"}'.
Missing input data: false
```

Query the event log to build a DQ dashboard. The `event_log()` TVF takes either a pipeline ID string or `TABLE(<st_or_mv_name>)`, and can be called only by the pipeline / table owner (use a shared cluster or SQL warehouse):

```sql
SELECT
  timestamp,
  expectation.name        AS constraint_name,
  expectation.dataset     AS dataset,
  expectation.passed_records,
  expectation.failed_records,
  details:flow_progress.data_quality.dropped_records AS dropped_records
FROM event_log('<pipeline-id>')
LATERAL VIEW EXPLODE(
  FROM_JSON(details:flow_progress.data_quality.expectations, 'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')
) AS expectation
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC;
```

**Quarantine pattern** (keep bad rows for triage instead of silently dropping). Add a boolean flag column computed from the inverse of your rules, attach `expect_all` (warn) so metrics still flow, then split into valid/invalid views downstream:

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

rules = {
    "valid_pickup_zip": "(pickup_zip IS NOT NULL)",
    "valid_dropoff_zip": "(dropoff_zip IS NOT NULL)",
}
quarantine_rules = "NOT({0})".format(" AND ".join(rules.values()))

@dp.temporary_view
def raw_trips_data():
    return spark.readStream.table("samples.nyctaxi.trips")

@dp.table(temporary=True, partition_cols=["is_quarantined"])
@dp.expect_all(rules)
def trips_data_quarantine():
    return spark.readStream.table("raw_trips_data").withColumn("is_quarantined", expr(quarantine_rules))

@dp.temporary_view
def valid_trips_data():
    return spark.read.table("trips_data_quarantine").filter("is_quarantined = false")

@dp.temporary_view
def invalid_trips_data():
    return spark.read.table("trips_data_quarantine").filter("is_quarantined = true")
```

```sql
CREATE OR REFRESH TEMPORARY STREAMING TABLE trips_data_quarantine(
  CONSTRAINT quarantined_row EXPECT (pickup_zip IS NOT NULL OR dropoff_zip IS NOT NULL)
)
PARTITIONED BY (is_quarantined)
AS SELECT *, NOT ((pickup_zip IS NOT NULL) AND (dropoff_zip IS NOT NULL)) AS is_quarantined
   FROM STREAM(raw_trips_data);
```

**Use cases**
- **warn**: ingestion / bronze where you must keep every row but want a quality trend (e.g., counting null `SinkModifiedOn` on STG entities without dropping them).
- **drop**: bad rows are expected and must not propagate (range/outlier filtering, null-key filtering before a join).
- **fail**: critical invariants where any bad row signals an upstream break — primary-key uniqueness (`@dp.expect_or_fail("unique_pk", "num_entries = 1")` over a `groupBy(pk).count()`), row-count conservation across a transform, no-missing-records after a left join.
- **quarantine**: regulated / pharma data (Novartis) where you can neither lose rows nor ship dirty rows — divert and reprocess.

**Limitations & gotchas**
- Constraints are **deterministic built-in SQL only** — no aggregate functions, no analytic/ranking window functions, no table-valued generator functions, and **no subqueries** referencing other tables (no custom Python UDFs / external calls). (Use a prior view to compute the value, then EXPECT on it.)
- Expectations / data-quality metrics are supported **only** on streaming tables, materialized views, temporary views — **not on sinks** (`dp.create_sink`).
- **Not supported with `AUTO CDC FROM SNAPSHOT`** (`create_auto_cdc_from_snapshot_flow`). So Apollo Gen2's full-load entities built via snapshot CDC cannot carry expectations on the snapshot flow.
- `fail` records **no** data_quality metrics — don't build a dashboard expecting fail counts; you watch the update error / `EXPECTATION_VIOLATION` instead.
- `failed_records` measures violations, **not** the disposition of the row — a warn'd row and a dropped row both increment `failed_records`; only `dropped_records` tells you it left the dataset.
- Views compute lazily, so a view's DQ metrics may be missing, or duplicated (one set per downstream consumer).
- Metric capture can require `pipelines.metrics.flowTimeReporter.enabled`; a `COMPLETED` flow may report nothing while a `RUNNING` micro-batch carries the metrics.
- Expectation descriptions must be **unique within a dataset** (reusable across datasets).

**Interview soundbite:** Six operators — `expect`/`expect_or_drop`/`expect_or_fail` for single and the `expect_all*` trio for a dict; warn keeps and counts, drop discards before write, fail rolls back the single flow; warn/drop land in the event log's `flow_progress.data_quality` (per-constraint `passed_records`/`failed_records` plus `dropped_records`) while fail emits an `EXPECTATION_VIOLATION` error in the update details with no metrics, and on CDC targets the expectations live on the `create_streaming_table` `expect_all*` params, not on the AUTO CDC flow.

### Event Log — Where, What & How to Read

**What it is**

The event log is the primary observability primitive in SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines). Every pipeline update (a "run") writes one structured row per event to a **Delta table**. It captures execution progress, data-quality (expectation) metrics, planning decisions (incremental vs full recompute), data lineage, user/audit actions, and resource usage. Because it is a Delta table, you query it with normal SQL and the `:` JSON-path operator — no log scraping.

In my Apollo Gen2 setup (422 SDP pipelines = 211 STG streaming tables + 211 BRZ SCD2 tables), the event log is how I triage which of the 211 entities failed a `dp.create_auto_cdc_flow` SCD2 write, prove SCD2 row counts to the client, and confirm whether a Bronze materialized-view refresh went incremental or fell back to `FULL_RECOMPUTE`.

**How it works (mechanics)**

- **Default publishing mode (Unity Catalog):** the pipeline writes the event log to a *hidden* Delta table in the pipeline's default catalog/schema, named `event_log_{pipeline_id}` (system UUID with dashes → underscores). It appears in `system.information_schema.tables` but is invisible in Catalog Explorer. By default only the pipeline **run-as user** can query it — but in default mode the hidden table "can still be queried by all sufficiently privileged users," so this is a privilege boundary, not a hard owner-only lock.
- **Two ways to read it:**
  1. **Direct table query (default publishing mode).** Query the hidden table via `event_log(<pipelineId>)`, or — if you've published it (below) — the named UC table directly. This path is governable: you can `GRANT SELECT` to share.
  2. **The `event_log()` table-valued function (TVF).** Available in Databricks SQL and DBR 13.3 LTS+. This is the *only* path for **legacy publishing mode** pipelines. Two call forms:

```sql
-- By pipeline ID (system UUID from the Pipeline details panel)
SELECT * FROM event_log("04c78631-3dd7-4856-b2a6-7d84e9b2638b");

-- By a streaming table or materialized view it owns/created
SELECT * FROM event_log(TABLE(my_catalog.my_schema.stg_account));
```

- **Hard access constraints on the TVF path (interview gotchas — these apply to the `event_log()` TVF specifically):**
  - The TVF can be called **only by the dataset/pipeline OWNER** (pipeline owner / ST or MV owner).
  - Must run on a **shared cluster or a SQL warehouse** (e.g., SQL Editor on a warehouse) — not a single-user/dedicated cluster.
  - You **cannot** read multiple pipelines' logs in one `event_log()` call, and a view created over the TVF **can be queried only by the owner and cannot be shared** with other users.
- **Standard pattern — wrap in a view once, query many times** (this view is referenced by all queries below):

```sql
CREATE VIEW event_log_raw AS
SELECT * FROM event_log("<pipeline-id>");
```

- **Streaming the log** (in Unity Catalog, views support streaming reads):

```python
df = spark.readStream.table("event_log_raw")
```

**Row schema (top-level columns)**

| Column | Type | Meaning |
|---|---|---|
| `id` | STRING | Unique event record id |
| `sequence` | STRING (JSON) | Ordering metadata |
| `origin` | STRING (JSON) | `pipeline_id`, `pipeline_name`, `update_id` (= run id), `flow_name`, `flow_id`, `cluster_id`, region, etc. |
| `timestamp` | TIMESTAMP | Event time in **UTC** |
| `message` | STRING | Human-readable description |
| `level` | STRING | `INFO`, `WARN`, `ERROR`, `METRICS` (METRICS = high-volume, Delta-only, not shown in UI) |
| `maturity_level` | STRING | `STABLE`, `EVOLVING`, `DEPRECATED`, or `NULL` (NULL = stable record predating the field, release 2022.37) — do **not** build alerts on EVOLVING/DEPRECATED fields |
| `error` | STRING | Error detail if any |
| `details` | STRING (JSON) | **The payload** — shape depends on `event_type`; parse with `details:...` |
| `event_type` | STRING | Discriminator for `details` (see below) |

**`event_type` values and what they carry**

| `event_type` | What it tells you |
|---|---|
| `create_update` | A new run started; captures full effective config (incl. `effective_publishing_mode`) + `cause`. Use it to find the latest `update_id`. |
| `update_progress` | Run lifecycle `state`: terminal states are `COMPLETED` / `FAILED` / `CANCELED`. |
| `flow_progress` | Per-flow `status` + metrics (`num_output_rows`, `num_upserted_rows`, `num_deleted_rows`, `backlog_bytes`/`backlog_files`) + **data_quality** (expectation pass/fail/drop). The workhorse event. |
| `flow_definition` | **Lineage** + query plan: `input_datasets`, `output_dataset`, `flow_type`, `explain_text`, `schema`. `flow_type` ∈ {`COMPLETE`, `CHANGE` (= `dp.create_auto_cdc_flow` / AUTO CDC), `SNAPSHOT_CHANGE` (= `dp.create_auto_cdc_from_snapshot_flow` / AUTO CDC from snapshot), `APPEND`, `MATERIALIZED_VIEW`, `VIEW`}. (Docs still describe `CHANGE`/`SNAPSHOT_CHANGE` with the legacy `APPLY CHANGES INTO` wording — same mechanism, AUTO CDC is the current SDP name.) |
| `planning_information` | Why a refresh was **incremental vs FULL_RECOMPUTE** — `technique_information` (chosen + considered techniques) + `incrementalization_issues` + source/target table info. |
| `dataset_definition` | `dataset_type` (ST vs MV), `num_flows`, attached `expectations`. |
| `sink_definition` | `dp.create_sink` `format` + `options`. |
| `user_action` | Audit: `CREATE`, `START`, etc. + `user_name`. |
| `runtime_details` | DBR version used for the update (`runtime_version.dbr_version`). |
| `cluster_resources` / `autoscale` | Slot utilization, executor counts — **classic compute only** (not serverless). |
| `operation_progress` | `type` ∈ {`AUTO_LOADER_LISTING`, `AUTO_LOADER_BACKFILL`, `CONNECTOR_FETCH`, `CDC_SNAPSHOT`}; `status`, `duration_ms`. |
| `stream_progress` | StreamingQueryListener-style metrics (offsets, batchId, durationMs). |
| `hook_progress` | Event-hook (`name`, `status`). |
| `deprecation` / `behavior_change_in_spark_connect` | Deprecated-API warnings; environment-version / Spark Connect compat scan findings. |

**Publishing the event log to a durable UC table**

By default the log lives in a hidden table tied to the pipeline. For durable, governable, cross-team querying, publish it to a named UC table via the pipeline's Advanced settings (default publishing mode only — legacy mode errors with `EVENT_LOG_PICKER_FEATURE_NOT_SUPPORTED`):

```json
{
  "id": "ec2a0ff4-d2a5-4c8c-bf1d-d9f12f10e749",
  "name": "billing_pipeline",
  "event_log": {
    "catalog": "catalog_name",
    "schema": "schema_name",
    "name": "event_log_table_name"
  }
}
```

Then query the table directly (still wrap in a view for convenience). Note: the event-log location also serves as the schema location for Auto Loader queries, so Databricks recommends creating a view and granting on the view rather than sharing the table directly:

```sql
CREATE VIEW event_log_raw
AS SELECT * FROM catalog_name.schema_name.event_log_table_name;
```

**Key configs / syntax**

| Concern | Value / rule |
|---|---|
| Call forms (TVF) | `event_log("<pipeline-id>")` or `event_log(TABLE(<fq-ST-or-MV>))` |
| Caller (TVF path) | Dataset/pipeline **OWNER** only; TVF-backed view is non-shareable |
| Caller (published-table path) | Any user with `SELECT` (default mode is governable; grant on a view) |
| Compute (TVF path) | **Shared cluster or SQL warehouse** only |
| Default location | hidden `event_log_{pipeline_id}` in pipeline's default catalog.schema |
| Scope | one pipeline per `event_log()` call |
| Time zone | `timestamp` is **UTC** |
| JSON parse | `details:flow_progress.status`, `from_json(...)`, `explode(...)` (`:` enters JSON; nested hops via `.` or `:`) |
| Latest run | filter `event_type='create_update'`, `ORDER BY timestamp DESC LIMIT 1` → `origin.update_id` |

**Use cases (verbatim SQL queries)**

1) Expectation pass/fail trend for the latest update (data-quality triage on Bronze SCD2 entities):

```sql
WITH latest_update AS (
  SELECT origin.update_id AS id
  FROM event_log_raw
  WHERE event_type = 'create_update'
  ORDER BY timestamp DESC
  LIMIT 1
)
SELECT
  row_expectations.dataset        AS dataset,
  row_expectations.name           AS expectation,
  SUM(row_expectations.passed_records) AS passing_records,
  SUM(row_expectations.failed_records) AS failing_records
FROM (
  SELECT explode(
    from_json(
      details:flow_progress:data_quality:expectations,
      "array<struct<name: string, dataset: string, passed_records: int, failed_records: int>>"
    )
  ) AS row_expectations
  FROM event_log_raw, latest_update
  WHERE event_type = 'flow_progress'
    AND origin.update_id = latest_update.id
)
GROUP BY row_expectations.dataset, row_expectations.name;
```

2) MV refresh technique — was it incremental or FULL_RECOMPUTE, and why:

```sql
WITH latest_update AS (
  SELECT origin.pipeline_id, origin.update_id AS latest_update_id
  FROM event_log_raw
  WHERE event_type = 'create_update'
  ORDER BY timestamp DESC
  LIMIT 1
),
parsed_planning AS (
  SELECT
    origin.flow_name,
    from_json(
      details:planning_information,
      'struct<technique_information: array<struct<
         maintenance_type: string, is_chosen: boolean, is_applicable: boolean, cost: double,
         incrementalization_issues: array<struct<issue_type: string,
           prevent_incrementalization: boolean, operator_name: string>>>>>'
    ) AS parsed
  FROM event_log_raw
  JOIN latest_update lu ON origin.update_id = lu.latest_update_id
  WHERE details:planning_information IS NOT NULL
)
SELECT
  flow_name,
  FILTER(parsed.technique_information, t -> t.is_chosen = true)[0].maintenance_type AS chosen_technique,
  parsed.technique_information AS all_considered_techniques
FROM parsed_planning;
```

Read it as: `maintenance_type = MAINTENANCE_TYPE_COMPLETE_RECOMPUTE` means full recompute, and `MAINTENANCE_TYPE_NO_OP` means nothing changed (neither is incremental). Any *other* value (`MAINTENANCE_TYPE_ROW_BASED`, `..._APPEND_ONLY`, `..._GROUP_AGGREGATE`, `..._GENERIC_AGGREGATE`, `..._WINDOW_FUNCTION`, `..._PARTITION_OVERWRITE`) is incremental. Common forced-full reasons in `incrementalization_issues.issue_type`: `CHANGE_SET_MISSING` (first compute), `EXPECTATIONS_NOT_SUPPORTED`, `ROW_TRACKING_NOT_ENABLED`, `PLAN_NOT_DETERMINISTIC`, `PLAN_NOT_INCREMENTALIZABLE`, `INCREMENTAL_PLAN_REJECTED_BY_COST_MODEL`, `QUERY_FINGERPRINT_CHANGED`, `CONFIGURATION_CHANGED`.

3) Lineage (build the DAG edges):

```sql
WITH latest_update AS (
  SELECT origin.update_id AS id
  FROM event_log_raw
  WHERE event_type = 'create_update'
  ORDER BY timestamp DESC
  LIMIT 1
)
SELECT
  details:flow_definition.output_dataset AS flow_name,
  details:flow_definition.input_datasets AS input_flow_names,
  details:flow_definition.flow_type      AS flow_type
FROM event_log_raw
JOIN latest_update ON origin.update_id = latest_update.id
WHERE details:flow_definition IS NOT NULL
ORDER BY timestamp;
```

4) Failure triage — pull the failed flows and their error from the latest run:

```sql
WITH latest_update AS (
  SELECT origin.update_id AS id
  FROM event_log_raw
  WHERE event_type = 'create_update'
  ORDER BY timestamp DESC
  LIMIT 1
)
SELECT
  timestamp,
  origin.flow_name,
  details:flow_progress.status AS status,
  level,
  message,
  error
FROM event_log_raw
JOIN latest_update ON origin.update_id = latest_update.id
WHERE event_type = 'flow_progress'
  AND details:flow_progress.status IN ('FAILED', 'SKIPPED', 'STOPPED')
ORDER BY timestamp;
```

5) Audit — who started/created the pipeline:

```sql
SELECT timestamp,
       details:user_action:action    AS action,
       details:user_action:user_name AS user_name
FROM event_log_raw
WHERE event_type = 'user_action';
```

**Limitations & gotchas**

- **TVF path = owner-only + shared/SQL-warehouse-only.** A teammate on a single-user/dedicated cluster cannot read it via the TVF, and the TVF-backed view can't be shared. To share, publish to a UC table (default mode) and grant `SELECT` on a view. This is the #1 trip-up.
- **One pipeline per `event_log()` call**; no cross-pipeline union. For 422 pipelines like Apollo Gen2, publish each log to a UC table to run fleet-wide quality dashboards.
- **Legacy vs default publishing mode diverge.** In legacy publishing mode you *must* use the TVF and *cannot* publish the log to UC (`EVENT_LOG_PICKER_FEATURE_NOT_SUPPORTED`); legacy is deprecated. Default mode writes to a hidden table in the pipeline's default catalog/schema and can be published to a named UC table. Also: migrating legacy→default changes the `flow_progress` dataset name from `table` to fully qualified `catalog.schema.table`, so update any event-log queries.
- **Never delete the event log** (or its parent catalog/schema) — future updates can fail. Missing data files / truncated Delta log surface as `EVENT_LOG_TABLE_MISSING_DATA_FILES` / `EVENT_LOG_TABLE_DELTA_TRUNCATED_TRANSACTION_LOG`; recovery is restore-to-earlier-version or drop.
- `cluster_resources` and `autoscale` events are **classic-compute only** — empty on serverless pipelines.
- **Incremental MV refresh requires serverless.** Materialized views updated on classic compute are *always* fully recomputed; only serverless pipelines can incrementally refresh (and only when the query plan supports it). So a `FULL_RECOMPUTE` in `planning_information` may just mean the pipeline isn't serverless.
- Timestamps are **UTC**; convert before showing to stakeholders.
- Don't build alerting on fields whose `maturity_level` is `EVOLVING` or `DEPRECATED`; `stream_progress` is EVOLVING.
- `expect_or_fail` (`ON VIOLATION FAIL UPDATE`) records **no** pass/fail metrics — it fails the flow on the first bad row. Per docs it fails only that single flow (not the whole pipeline), so your data-quality query sees a `FAILED` flow status, not a failed-record count.

**Interview soundbite:** The SDP event log is a per-run Delta table. In default publishing mode it lives as a hidden `event_log_{pipeline_id}` table you query (and can publish to a named UC table for grants); the `event_log('<pipeline-id>')` / `event_log(TABLE(<st-or-mv>))` TVF is the owner-only, shared-cluster/SQL-warehouse path required for legacy-mode pipelines. Wrap it in a view, filter by `event_type` — `flow_progress` for data quality, `planning_information` for incremental-vs-FULL_RECOMPUTE, `flow_definition` for lineage — and publish to UC when you need durable, shareable, fleet-wide monitoring.

### Deployment Mode — Development vs Production

**What it is**

A pipeline-level operational setting that controls how an SDP (Spark Declarative Pipelines / Lakeflow Spark Declarative Pipelines) update behaves around **compute lifecycle** (does the cluster stay warm or tear down?) and **failure handling** (does it retry/recover automatically or fail loud immediately?). It is *not* the same axis as triggered-vs-continuous, which controls **execution** (does the update stop when caught up, or run forever?). Both axes are orthogonal — you can have a development+triggered pipeline or a production+continuous one.

There are two framings in current Databricks docs, and a strong interviewer expects you to reconcile them:

| Framing | What flips the behavior | Where it lives in docs |
|---|---|---|
| **Deployment mode** (classic framing) | The `development` boolean on the pipeline (default `false` = production) | Pipeline settings / `development` field / bundle `mode` |
| **Update run behavior** (current framing) | The **update trigger source** — UI **Run now**/ad-hoc vs Jobs/API/continuous | "Run a pipeline update" → "Update run behavior" page |

These describe the *same two behavior bundles* (fast-start/no-retry vs auto-retry/teardown) but attribute the trigger to different things. State both.

**How it works (mechanics)**

**Development / fast-start behavior (debugging-focused — UI Run now and ad-hoc updates):**

| Behavior | Detail |
|---|---|
| Cluster reuse | Cluster is **reused** across updates to avoid restart overhead. |
| Cluster idle window | By default the cluster runs for **2 hours**, governed by `pipelines.clusterShutdown.delay` (default `2 hours` in this mode). |
| Retries | **Disabled.** Pipeline retries are turned off so errors surface immediately and you can fix and rerun fast. |
| Runtime auto-revert | **Not active** (revert only happens in production mode + channel `current`). |

**Production / automatic retry and restart behavior (Jobs, Pipelines API, continuous):**

| Behavior | Detail |
|---|---|
| Cluster lifecycle | The cluster **shuts down immediately** after the run completes (`pipelines.clusterShutdown.delay` default `0 seconds` in this mode) — no warm reuse across updates. |
| Recovery restarts | Restarts the cluster for specific recoverable errors (e.g. memory leaks, stale credentials). |
| Retries | **Automatic** for specific errors (e.g. cluster-launch failures): a bounded **flow** retry (`maxFlowRetryAttempts`) and a bounded **update** retry (`numUpdateRetryAttempts`), with the flow retry as the finer-grained unit before the whole update is re-run. |
| Runtime auto-revert | If a versionless-runtime upgrade prevents the pipeline from starting, the runtime is **pinned back to the last known-good version** — but **only** when the pipeline runs in **production mode AND `channel = current`**. Databricks support is auto-notified. |

The granularity matters for the soundbite: SDP retries the failing flow up to its bound before escalating to re-running the whole update.

**Key configs / syntax**

The `development` boolean in the pipeline JSON settings (default `false`):

```json
{
  "name": "apollo_gen2_brz_account",
  "development": false,
  "continuous": false,
  "channel": "current",
  "configuration": {
    "pipelines.numUpdateRetryAttempts": "5",
    "pipelines.maxFlowRetryAttempts": "2",
    "pipelines.clusterShutdown.delay": "0s"
  }
}
```

Retry-related properties (set under `configuration`):

| Property | Type | What it bounds | Default |
|---|---|---|---|
| `pipelines.numUpdateRetryAttempts` | int | Max retries of the **whole update** before permanent failure (each retry is a full update). Applies only to pipelines using automatic retry/restart behavior — not editor ad-hoc updates or `Validate` updates. | **5** for triggered; **unlimited** for continuous |
| `pipelines.maxFlowRetryAttempts` | int | Max retries of a **single flow** on a retryable failure before failing the update — stops one flaky flow from stalling the whole update. | **2** (so 3 total attempts including the original) |
| `pipelines.clusterShutdown.delay` | duration | How long the cluster lingers after the update. | `2 hours` (fast-start), `0 seconds` (automatic retry/restart) |

Toggling via **bundles** (Declarative Automation Bundles, formerly Databricks Asset Bundles — the CI/CD-correct way) — `databricks bundle deploy -t dev` vs `-t prod`:

```yaml
targets:
  dev:
    mode: development
  prod:
    mode: production
    git:
      branch: main
```

```bash
databricks bundle deploy -t dev
databricks bundle deploy -t prod
```

`mode: development` on deploy:
- Marks every related deployed SDP pipeline as `development: true`.
- Prepends a `[dev ${workspace.current_user.short_name}]` prefix to non-file/non-notebook resource names and tags each deployed job and pipeline with a `dev` tag.
- **Pauses all schedules and triggers**, enables concurrent runs on jobs, allows `--cluster-id` (or the `cluster_id` mapping) to override cluster definitions for reuse, and disables the deployment lock — all for fast iteration.

`mode: production` on deploy:
- **Validates** that all related deployed SDP pipelines are `development: false` (deploy fails otherwise — a hard guardrail against shipping a dev pipeline to prod).
- Validates the current Git branch matches the target's `git.branch` (override with `--force`).
- Disallows cluster-definition overrides (`--compute-id` / `compute_id`); recommends `run_as` a service principal.

You can also flip the mode interactively in the pipeline UI via the **Development / Production** toggle in the editor/settings.

**Use cases**

| Scenario | Mode | Why |
|---|---|---|
| Iterating on a new STG streaming table or a `create_auto_cdc_flow` definition; rerunning every few minutes | Development (UI Run now) | Warm cluster reuse + immediate error surfacing kills the restart tax. |
| Scheduled nightly JOB2 run of the 422 Apollo Gen2 pipelines via Lakeflow Jobs | Production | Cluster teardown after the run + auto-retry rides out transient ADLS / cluster-start failures unattended. |
| Continuous low-latency streaming table | Production (continuous) | Unlimited update retries keep it alive; flow retries bounded at 2 so one bad flow fails fast. |
| Promoting validated code from a feature branch | `bundle deploy -t prod` | Enforces `development: false` + branch check before it lands. |

In the Apollo Gen2 two-job pattern, JOB1 (the preprocessing notebook that lands files in `incoming/`) is plain Lakeflow Jobs compute, but the JOB2 SDP pipelines are exactly where this matters: during a Novartis entity onboarding I run the pipeline in development mode to debug SCD2 behavior on a single STG→BRZ pair with a reused cluster, then flip `development: false` and let the scheduled job run it in production with the 5-attempt update retry envelope.

**Limitations & gotchas**

- **Two framings, one behavior set.** If you say "dev mode reuses the cluster" an interviewer may counter "but the docs tie that to UI Run now." Both are right — UI **Run now**/ad-hoc = fast-start/no-retry, while Jobs/API/continuous = auto-retry/teardown. The `development` boolean is the persisted pipeline-level switch; the trigger source is the per-run switch. (For triggered pipelines you can also override per-run via **Run now with different settings**.) Say both.
- **`numUpdateRetryAttempts` does NOT apply to ad-hoc updates** — editor/ad-hoc runs and `Validate`/dry-run updates never retry the update regardless of the setting.
- **Continuous defaults to unlimited update retries**, which is intentional (a streaming pipeline should self-heal), but means a genuinely broken continuous pipeline can retry forever — bound it explicitly if you want it to fail closed.
- **Runtime auto-revert is conditional.** It only fires in **production mode + `channel = current`**. A dev pipeline, or a prod pipeline on `channel = preview`, gets no automatic revert if a versionless upgrade breaks it — relevant because Lakeflow is a versionless product that upgrades the runtime under you.
- **`autotermination_minutes` is illegal** on SDP compute — the runtime owns cluster lifecycle via `clusterShutdown.delay`, so a compute policy that sets `autotermination_minutes` throws an error.
- **Bundle prod deploy fails if any related pipeline is `development: true`** — a feature, not a bug; it stops a half-configured dev pipeline reaching production.
- **Dev cluster lingering 2 hours costs money** — convenient for iteration, but a forgotten dev/ad-hoc run keeps a classic cluster warm; lower `clusterShutdown.delay` or use serverless if cost-sensitive.

**Interview soundbite:** "Development/fast-start mode reuses the cluster (default 2-hour `clusterShutdown.delay`) for fast iteration and disables retries so errors surface immediately; production/automatic-retry mode tears the cluster down right after the run (`clusterShutdown.delay` default 0s), restarts it on recoverable errors, and auto-retries at flow then update granularity — `maxFlowRetryAttempts` defaulting to 2 (3 attempts total) and `numUpdateRetryAttempts` to 5 for triggered / unlimited for continuous — and only a production pipeline on channel `current` auto-reverts the runtime to last-known-good; current docs map this same split to the trigger source, where UI Run now/ad-hoc is fast-start/no-retry and Jobs/API/continuous get the auto-retry path."

### Product Editions — CORE, PRO, ADVANCED

**What it is**

SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) ships in three *product editions* — `CORE`, `PRO`, `ADVANCED` — that gate the feature set a pipeline may use and the corresponding billing rate. You pick one per pipeline via the `edition` pipeline field. Editions are *additive*: each tier is a strict superset of the one below it. CORE = streaming ingest/transform only; PRO = CORE + change data capture (CDC / AUTO CDC / SCD Type 1 & 2); ADVANCED = PRO + data-quality *expectations* (CONSTRAINT ... EXPECT). Default = `ADVANCED`.

**How it works (mechanics)**

- `edition` is a top-level pipeline setting (set in the pipeline UI dropdown or the JSON spec), not per-table. Every dataset in that pipeline runs under the one chosen edition.
- At the *Validate / start-update* phase, SDP discovers all tables/views and checks for analysis errors. If any flow uses a feature above the selected edition (e.g. an expectation in a CORE pipeline, or `AUTO CDC` in a CORE pipeline), the update fails closed with an explicit error message explaining the reason; you then edit the pipeline to select the appropriate edition. It does not silently downgrade behavior.
- Edition is independent of compute type, channel (`current`/`preview`), and `photon` (whose own default is `false`). It is also independent of pipeline mode (triggered vs. continuous).
- **Serverless caveat (CDC):** the docs state CDC requires "serverless SDP **or** the SDP `Pro` or `Advanced` editions." So on *serverless* SDP, CDC works without raising the classic-compute edition lever — the edition lever for CDC matters mainly for *classic-compute* pipelines. Serverless bills on its own serverless DBU model. New pipelines default to serverless + Unity Catalog + current channel. (Whether serverless similarly waives the ADVANCED requirement for *expectations* is not stated in the docs — see riskFlag; assume expectations still need ADVANCED unless you confirm otherwise.)
- Edition also controls **past-update retention** in the UI / Pipelines API (see table below); active non-terminal updates always show regardless, and the underlying event log keeps everything either way.

**Key configs / syntax**

The edition is set as the `edition` field. Type `string`; valid values `CORE`, `PRO`, `ADVANCED`; optional; default `ADVANCED`.

```json
{
  "name": "apollo_gen2_brz_account",
  "catalog": "novartis_prod",
  "schema": "bronze",
  "serverless": false,
  "edition": "PRO",
  "channel": "CURRENT",
  "photon": true,
  "libraries": [
    { "file": { "path": "/Workspace/.../transformations/brz_account.py" } }
  ]
}
```

A PRO-tier feature (CDC) that forces `edition` to be at least `PRO` (or serverless):

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_account")

dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",
    keys=["account_id"],
    sequence_by="sys_change_version",
    apply_as_deletes="operation = 'DELETE'",
    stored_as_scd_type=2,
    track_history_except_column_list=["operation", "_ingest_ts"],
)
```

An ADVANCED-tier feature (expectations enforcement) that forces `edition` to be `ADVANCED`:

```python
from pyspark import pipelines as dp

@dp.table(name="stg_account")
@dp.expect_or_drop("valid_account_id", "account_id IS NOT NULL")
@dp.expect_or_fail("valid_version", "sys_change_version > 0")
def stg_account():
    return spark.readStream.format("cloudFiles").load("/mnt/incoming/account/")
```

SQL surface for the same two tiers:

```sql
-- PRO: CDC / AUTO CDC into a streaming table
CREATE OR REFRESH STREAMING TABLE brz_account;

CREATE FLOW brz_account_cdc
AS AUTO CDC INTO brz_account
FROM STREAM(stg_account)
KEYS (account_id)
APPLY AS DELETE WHEN operation = 'DELETE'
SEQUENCE BY sys_change_version
COLUMNS * EXCEPT (operation, _ingest_ts)
STORED AS SCD TYPE 2;

-- ADVANCED: expectations with enforcement
CREATE OR REFRESH STREAMING TABLE stg_account (
  CONSTRAINT valid_account_id EXPECT (account_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT valid_version    EXPECT (sys_change_version > 0) ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM read_files('/mnt/incoming/account/');
```

**Feature matrix by edition**

| Capability | CORE | PRO | ADVANCED |
|---|---|---|---|
| Streaming tables (`@dp.table` / `CREATE ... STREAMING TABLE`) | ✅ | ✅ | ✅ |
| Materialized views (`@dp.materialized_view`) | ✅ | ✅ | ✅ |
| Auto Loader / `read_files` ingest, transforms, flows, sinks | ✅ | ✅ | ✅ |
| CDC: `create_auto_cdc_flow` / `AUTO CDC INTO` (SCD1 & SCD2) | ❌ | ✅ | ✅ |
| `create_auto_cdc_from_snapshot_flow` / `AUTO CDC FROM SNAPSHOT` | ❌ | ✅ | ✅ |
| Expectations (`@dp.expect` warn, `_or_drop`, `_or_fail`; `ON VIOLATION DROP ROW` / `FAIL UPDATE`) | ❌ | ❌ | ✅ |
| Past-update retention (UI + Pipelines API) | 5 days | 30 days | 30 days |
| Default edition | — | — | ✅ (`ADVANCED`) |

> Note on `@dp.expect` (warn-only): warn is the *default* violation policy (`@dp.expect` / SQL `EXPECT` with no `ON VIOLATION` clause), but it is still the data-quality *expectations* feature and belongs to ADVANCED along with drop/fail. CORE has no expectations at all. Pick ADVANCED for any pipeline that declares a `CONSTRAINT ... EXPECT`, even warn-only.

**Use-case-per-edition**

| Edition | Pick it when... | Concrete example |
|---|---|---|
| `CORE` | Plain append-only streaming ingest/transform, no history tracking, no quality gates | A raw landing streaming table that just `read_files()`s NDJSON from ADLS `incoming/` into a Delta streaming table, no dedup, no SCD, no constraints |
| `PRO` | You need CDC / upserts / SCD1 or SCD2 but enforce no expectations | My Apollo Gen2 BRZ layer: 211 SCD2 tables built via `create_auto_cdc_flow` (`sequence_by`, `apply_as_deletes`, `track_history_except_column_list`) + the 5 full-load entities via `create_auto_cdc_from_snapshot_flow`. CDC = needs at least PRO (or serverless) |
| `ADVANCED` | You enforce row-level data-quality constraints (drop/fail), or just want every feature + the default | My STG streaming tables that drop/fail on bad keys or out-of-range `sequence_by` values before they ever reach the SCD2 BRZ layer; also the safe default when you don't want to think about it |

**Limitations & gotchas**

- **Default is ADVANCED, which is the most expensive tier.** If you leave `edition` unset on classic compute you silently pay the top rate even for a plain-ingest pipeline. Cost rule: pick the *lowest* edition that covers your features — CORE for plain ingest, PRO if you do CDC, ADVANCED only if you enforce expectations.
- **Fail-closed on feature mismatch.** A CORE pipeline containing any `AUTO CDC` flow, or a CORE/PRO pipeline containing any expectation (even warn-only), errors with an explicit message; read it, bump the edition, re-run.
- **Edition is per-pipeline, not per-table.** One expensive feature on one table pulls the whole pipeline up to that edition. In a fan-out design like 422 pipelines, you can give each pipeline its own edition — e.g. CORE for any pure-landing pipelines, PRO for the CDC/SCD2 ones — rather than forcing all to ADVANCED.
- **Serverless changes the CDC lever.** On serverless, CDC works without the Pro/Advanced edition requirement, and billing follows serverless DBU rates — so the CORE/PRO cost optimization for CDC only bites on classic compute. (The expectations side of this is unconfirmed in docs; do not assume serverless waives ADVANCED for expectations.)
- **Retention side effect.** CORE keeps only 5 days of past updates visible in the UI/API vs 30 for PRO/ADVANCED; if you downgrade a pipeline to CORE for cost, you also shorten its visible update history (older updates are excluded from list responses but the underlying event log still retains the records).
- **Tags ≠ billing attribution by edition.** Pipeline tags are *not* associated with billing; to attribute cost use cluster tags / `system.billing.usage`. Edition + `photon` are the real billing-rate levers.

**Interview soundbite:** SDP editions are additive feature-and-billing tiers set per pipeline via the `edition` field — CORE for plain streaming ingest, PRO adds CDC / AUTO CDC / SCD1 & SCD2, ADVANCED adds data-quality expectations — and since the default is ADVANCED (the priciest), on classic compute you should always drop each pipeline to the lowest edition its features actually need; note that serverless satisfies the CDC requirement on its own (docs: "serverless SDP or the Pro/Advanced editions").


## Clarifications & Deep-Dive (round 2)

> Follow-up clarifications on the bank above (prep 2026-06-06). SDP-only; all Python/SQL in fenced code blocks. C1 & C13 doc-verified against the incremental-refresh page (2026-05-28).

### C1 — Incremental MV refresh: supported vs unsupported queries (serverless vs classic)

**Compute rule is absolute:** incremental refresh happens **only on serverless**. On **classic compute the MV is always fully recomputed**, regardless of query. On serverless the query shape decides eligibility — and even then the `AUTO` cost model may still pick full recompute if cheaper (override with `REFRESH POLICY INCREMENTAL` / `INCREMENTAL STRICT`).

**Supported (incrementalizable):**

| Clause | Notes |
|---|---|
| `SELECT` expressions | deterministic built-ins + **immutable** UDFs |
| `GROUP BY` aggregations | supported |
| `WITH` (CTEs) | supported |
| `UNION ALL` | supported |
| `WHERE`, `HAVING` | filters supported |
| `INNER / LEFT / RIGHT / FULL OUTER JOIN` | supported |
| `OVER` window functions | must specify `PARTITION BY` |
| `QUALIFY` | supported |
| `EXPECTATIONS` | yes — with 2 exceptions (see C13) |
| Non-deterministic **time** funcs (`current_date()`, `current_timestamp()`, `now()`) | **only in `WHERE`** |

**Unsupported → forces FULL recompute:** `WITH RECURSIVE`; any **other** non-deterministic function (`rand()`, time funcs outside `WHERE`); a **UDF whose behavior changed**; **unsupported sources** (volumes, external locations, foreign catalogs, foreign Iceberg); sources with **row filters / column masks**; anything not expressible via the supported clauses.

**Two silent demoters:** most supported clauses (joins, filters, windows, `UNION ALL`, `SELECT` exprs, expectations) **require row-tracking** on the source; and source **updates/deletes** that can't be tracked → full recompute. Check eligibility with `EXPLAIN CREATE MATERIALIZED VIEW` and the actual run via the `planning_information` event-log technique (`ROW_BASED` etc. vs `FULL_RECOMPUTE`).

**One-liner:** *Classic = always full; serverless = incremental only if the query uses supported clauses AND sources have row-tracking/CDF, else it silently falls back to full recompute.*

### C2 — Which flows can write to the same ST/MV

| Target | What can write to it |
|---|---|
| **Streaming table** | **Multiple `append_flow`s** → fan-in/union into one ST (the multi-source + backfill pattern). An **AUTO CDC flow** also targets a streaming table — but it *owns* that table's upsert/delete identity, so you don't normally also append-flow into a CDC target. |
| **Materialized view** | **No** — an MV is a **single defining query**, not a multi-flow fan-in target. |
| **`update_flow`** | Targets **sinks only** (`create_sink` → Delta/Kafka). **Not** an ST or MV. |

All append flows into one ST must produce a compatible schema (`BY NAME`).

**One-liner:** *Only streaming tables take multiple flows (append fan-in, or one AUTO CDC writer); MVs are single-query; update flows feed sinks, not ST/MV.*

### C3 — Auto Loader schema evolution (`addNewColumns`) in depth

**Scenario — an `orders` CSV feed:**
- **Day 1** schema `{id, amount}`. Auto Loader infers it, persists it in the **schemaLocation**, auto-adds `_rescued_data`.
- **Day 5** source adds `discount_code`. With **`addNewColumns`** (default, no schema supplied): the stream **throws `UnknownFieldException` and stops**, records the new column in the schemaLocation, and on **restart resumes** with the evolved schema. Under a Lakeflow **Job** the auto-restart makes it seamless. Pre-Day-5 rows keep `discount_code = NULL`.
- **Dropped column:** `addNewColumns` **never removes** — if the source stops sending `amount`, new rows land `amount = NULL` (**silent soft delete**; add a DQ check if it matters).
- **Type mismatch:** `amount` int → source sends `"12.5"` → bad value goes to **`_rescued_data`** (column keeps its type). `addNewColumnsWithTypeWidening` (Preview, DBR 16.4+) **applies** a widening change (`int→long`) instead of rescuing.

`_rescued_data` is auto-added whenever Auto Loader infers a schema; it captures any field that doesn't match so data is never silently lost.

**One-liner:** *`addNewColumns` fails-then-resumes on a new column, only ever ADDS — drops become NULLs, type mismatches go to `_rescued_data`.*

### C4 — All `schemaEvolutionMode` modes

| Mode | Behavior |
|---|---|
| **`addNewColumns`** (default when no schema provided) | New column → stream **fails**, records it, resumes on restart. |
| **`rescue`** | Never fails/evolves; new + mismatched data captured in **`_rescued_data`**; stream keeps running. |
| **`failOnNewColumns`** | Stream **fails and stays failed** on a new column until you fix the schema manually. |
| **`none`** (default when you **provide** a schema) | New columns **ignored** — not loaded, not rescued, no failure. |
| **`addNewColumnsWithTypeWidening`** (Preview, DBR 16.4+) | Like `addNewColumns` **plus** widens existing types (`int→long`) instead of rescuing. |

### C5 — `pipelines.reset.allowed = false`

**What:** a **table property**; when `false`, a **full refresh is blocked** for that table — it's **skipped** during full refresh, preserving data + checkpoint. **Why:** protect tables whose source **can't be replayed** (backfilled tables; bronze fed from Kafka/files that age out). **Where / on what:** set on **streaming tables or materialized views** in the dataset definition.

```python
@dp.table(name="bronze_orders", table_properties={"pipelines.reset.allowed": "false"})
def bronze_orders():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .load("/Volumes/cat/sch/incoming/orders"))
```
```sql
CREATE OR REFRESH STREAMING TABLE bronze_orders
  TBLPROPERTIES ('pipelines.reset.allowed' = 'false')
AS SELECT * FROM STREAM read_files('/Volumes/cat/sch/incoming/orders', format => 'csv');
```

**One-liner:** *A per-table property that makes full refresh skip the table — set it on any ST/MV whose source history you can't replay.*

### C6 — Watermarks + why an ST join doesn't recompute on dimension change

**Watermark in a streaming aggregate:** the engine keeps per-group state; **watermark = max(event_time) − threshold**, a moving cutoff. Once it passes a window, that group is finalized, emitted, and its state **evicted**; a row arriving with event_time **below** the watermark is **late → dropped** (contribution lost). No watermark → state grows unbounded.

**ST join freezes the dimension:** a streaming table joining a fact **stream** to a **dimension** processes each fact **once, at arrival**, against the dimension *as it was then*. A later dimension edit does **not** re-join already-processed facts (the stream only sees new rows), so old facts keep stale dimension values. An **MV** recomputes the join over the *current* dimension → corrects everything.

**One-liner:** *Streaming aggregates drop data past the watermark and streaming joins freeze the dimension at arrival — need current-correct results despite late/edited data → MV.*

### C7 — `deletionVectors` / `rowTracking` / `changeDataFeed`

| Property | What it does | Why it helps SDP |
|---|---|---|
| `delta.enableDeletionVectors` | Deletes/updates mark rows in a side file (merge-on-read) instead of rewriting whole files. | Cheap deletes/updates/MERGE → faster CDC & SCD2 writes. |
| `delta.enableRowTracking` | Stable row-id + commit-version per row; engine knows exactly which rows changed. | **Required** for most incremental MV techniques (`ROW_BASED`) — apply only changed rows, not full recompute. |
| `delta.enableChangeDataFeed` | Readable row-level change feed (`_change_type`). | Downstream reads just the changes; underpins incremental/CDC reads. |

Databricks **recommends all three on every MV source table** — together they make "what changed?" cheap, enabling incremental over full recompute.

```sql
ALTER TABLE source_tbl SET TBLPROPERTIES (
  delta.enableDeletionVectors = true,
  delta.enableRowTracking = true,
  delta.enableChangeDataFeed = true);
```

**One-liner:** *Deletion vectors = cheap updates; row tracking = which rows changed (key to incremental MV); CDF = readable change feed — enable all three on MV sources.*

### C8 — Why MVs are "always correct" without watermarks

The guarantee is **batch-equivalence**: each refresh produces the same result a fresh batch query over the current base data would. A late/out-of-order row that has landed in the base table is simply **included next refresh** — there's no "window closed" concept, because the answer is **re-derived**, not accumulated. The per-row "tracking" lives on the **source Delta tables** (`enableRowTracking` + CDF), not in the MV; it just lets the engine apply only the **delta** (incremental). If it can't, it recomputes fully — either way the result equals the batch query.

**One-liner:** *The MV doesn't remember rows — it re-derives the batch-correct answer each refresh; source row-tracking only makes that re-derivation incremental.*

### C9 — CDC tombstone retention (`pipelines.cdc.tombstoneGCThresholdInSeconds`)

On an AUTO CDC **delete** (`apply_as_deletes`), the engine keeps a **tombstone** ("key X was deleted") so a **late/out-of-order** event for X is handled correctly (no resurrecting a deleted row from a stale update). Tombstones are GC'd after a retention period — **default 2 days**, set via the **target streaming table** property `pipelines.cdc.tombstoneGCThresholdInSeconds` (seconds). **Risk:** a late event for a deleted key arriving **after** GC can **resurrect** the row. **Fix:** set the threshold **above your worst-case event-arrival-to-pipeline delay**. Trade-off: longer retention = more state/storage.

**One-liner:** *Tombstones let CDC ignore late events for deleted keys (default 2-day GC); raise it above your worst late-arrival window so a late re-insert can't resurrect a row.*

### C10 — Schema hints vs full schema (keeping `addNewColumns`)

Providing a **full fixed schema** (`.schema(...)`) flips evolution to **`none`**. To keep **`addNewColumns`** *and* pin some types, don't pass a full schema — pass **`cloudFiles.schemaHints`** (partial). Hints type the named columns and let Auto Loader still infer + evolve the rest. ("unless given as a schema hint" = provide your typing via hints, not `.schema()`.)

```python
@dp.table(name="bronze_orders")
def bronze_orders():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaHints", "id LONG, amount DECIMAL(10,2)")  # partial typing
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")          # still evolves
            .load("/Volumes/cat/sch/incoming/orders"))
```

**One-liner:** *Pin types with `schemaHints`, not a full `.schema()` — that's the only way to keep `addNewColumns` while controlling some types.*

### C11 — Stream–stream join internals (symmetric hash, 4 state stores, watermark)

**Setup:** join `impressions` ⨝ `clicks` on `ad_id`, "click within 3 min of impression." Either side can arrive first, so both sides are **buffered** in state and each new row probes the other side — a **symmetric hash join**.

**Why 4 state-store instances (per shuffle partition):** each side needs two structures:

| Side | Keyed buffer | Match tracker |
|---|---|---|
| impressions | impressions waiting, keyed by `ad_id` | which matched (for outer-join NULLs) |
| clicks | clicks waiting, keyed by `ad_id` | which matched |

2 sides × 2 = **4** (most stateful ops use 1).

**Data flow + eviction** (watermark 3 min, interval 3 min):

| time | event | state | output | watermark |
|---|---|---|---|---|
| 10:00 | impression A (7) | buffer A | — | 10:00 |
| 10:02 | click (7) | probe → match A | **(A, click)** | 10:02 |
| 10:05 | impression B (9) | buffer B | — | 10:05 |
| 10:09 | time advances | wm=10:06 → B's window closed → **evict B**; outer join emits **(B, NULL)** | (B, NULL) | 10:06 |
| 10:10 | **late** click (9) | B already evicted → **dropped** | — | — |

The engine keeps one **global watermark = min across streams** (slowest stream gates eviction so matchable rows aren't dropped); the **time-interval condition** says when no further match is possible → evict. `multipleWatermarkPolicy=max` follows the fastest stream but drops slow-stream data (use with caution). Outer joins **require** watermarks; output is **append-only**. **Stream–static** is stateless (no watermark; static side re-read at each micro-batch start; late dim edits not retroactive).

**One-liner:** *Both sides buffered (4 stores = keyed-buffer + match-tracker × 2); the min global watermark + interval condition decide when buffered rows can't match and get evicted — later arrivals are dropped.*

### C12 — Selective checkpoint reset

`reset_checkpoint_selection` resets specific flows' checkpoints (reprocess from scratch) while leaving everything else intact. Flow names must be **fully qualified** (`catalog.schema.flow_name`) — a bare name throws `IllegalArgumentException`. For a join/union, reset **all participating source flows**.

```python
dp.create_streaming_table("main.sales.joined")

@dp.append_flow(target="main.sales.joined", name="orders_src")   # -> main.sales.orders_src
def orders_src():
    return spark.readStream.table("main.raw.orders")

@dp.append_flow(target="main.sales.joined", name="returns_src")  # -> main.sales.returns_src
def returns_src():
    return spark.readStream.table("main.raw.returns")
```
```bash
# update-time parameter (Pipelines API / CLI), not a decorator; confirm exact field in your workspace
databricks pipelines start-update <pipeline-id> \
  --reset-checkpoint-selection main.sales.orders_src main.sales.returns_src
```

**One-liner:** *Name your flows, reset their checkpoints by fully-qualified name at update time, and for a join/union reset all source flows together.*

### C13 — MV + expectations: incremental-refresh exceptions

An MV with expectations **can** still be incrementally refreshed, **except** (→ full recompute):
1. **The MV reads from a view that contains expectations** (the logic is outside the MV's incremental plan).
2. **The MV has a `DROP` expectation AND `NOT NULL` columns in its schema** (row-removal + NOT-NULL enforcement can't be reasoned about incrementally).

**Practical:** apply expectations **directly on the MV** (not via a view), and **avoid pairing `DROP` with `NOT NULL` columns** (use `WARN`, or enforce NOT-NULL upstream in the ST).

**One-liner:** *Expectations don't block incremental MV refresh — except a `DROP` expectation alongside `NOT NULL` columns, or reading from a view that holds the expectations.*

### C14 — One pipeline across multiple `.py` / `.sql` files

SDP parses **all** source files into one dependency graph before running, so datasets reference each other by name across files.

```python
# transforms/customers.py
from pyspark import pipelines as dp
from pyspark.sql.functions import udf
from pyspark.sql.types import StringType

@udf(StringType())
def norm_region(r):
    return (r or "").strip().upper()

@dp.temporary_view
def stg_customers():
    return (spark.read.table("main.raw.customers")
            .select("cust_id", norm_region("region").alias("region")))
```
```sql
-- transforms/orders.sql
CREATE TEMPORARY VIEW stg_orders AS
SELECT cust_id, amount FROM main.raw.orders WHERE amount > 0;
```
```sql
-- transforms/gold.sql
CREATE OR REFRESH MATERIALIZED VIEW gold_region_revenue AS
SELECT c.region, SUM(o.amount) AS revenue
FROM stg_customers c JOIN stg_orders o USING (cust_id)
GROUP BY c.region;
```
SDP resolves `stg_customers` (Python) and `stg_orders` (SQL) as upstream nodes of the MV automatically.

**One-liner:** *Datasets reference each other by name across `.py` and `.sql`; SDP builds one graph from all files, so a Python temp view and a SQL temp view can feed the same MV.*

### C15 — REPLACE WHERE flows

Recompute and **overwrite only the slice** of a streaming table matching a predicate, without streaming semantics — it **deletes** the predicate-matched rows and **re-inserts** the re-evaluated batch source for that predicate. **Use:** late-arriving data for a range, selective reprocessing/correction, backfills.

**Scenario:** `sales` partitioned by `sale_date`; `2026-06-01` was wrong upstream and got corrected. Recompute just that day instead of a full refresh.

```sql
CREATE OR REFRESH STREAMING TABLE sales
  TBLPROPERTIES ('pipelines.channel' = 'PREVIEW');

CREATE FLOW sales_fix AS INSERT INTO sales BY NAME
  REPLACE WHERE sale_date = '2026-06-01'
  SELECT * FROM cleaned_sales_batch;   -- batch source; engine auto-applies the predicate
```
```python
@dp.append_flow(target="sales", replace_where="sale_date = '2026-06-01'")
def sales_fix():
    return spark.read.table("cleaned_sales_batch")   # batch read
```

**Rules:** **Beta** — `pipelines.channel='PREVIEW'`; **batch (non-streaming)** source; **`BY NAME`**; **deterministic** predicate; **mutually exclusive with `ONCE`**; don't add the predicate to the source query (auto-applied). Not a generic big-join helper.

**One-liner:** *"Recompute just this slice" — delete + re-insert the predicate-matched rows from a batch source, fixing one partition/day instead of full-refreshing.*

### C16 — The windowed streaming aggregate, explained

```sql
CREATE OR REFRESH STREAMING TABLE per_min_counts AS
SELECT window(event_time, '1 minute') AS w, state, COUNT(*) AS cnt
FROM STREAM(events) WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY w, state;
```
- `FROM STREAM(events)` — read `events` as a stream.
- `WATERMARK event_time DELAY OF INTERVAL 3 MINUTES` — tolerate up to 3 min late; later events are **dropped**.
- `window(event_time, '1 minute')` — 1-minute **tumbling** buckets.
- `GROUP BY w, state` + `COUNT(*)` — count per (window, state).

Result is **per-window**, not a running total:

| w | state | cnt |
|---|---|---|
| 10:00–10:01 | CA | 42 |
| 10:01–10:02 | CA | 39 |

**"incremental only because of the watermark":** the watermark lets the engine finalize+emit a window after 3 min and **evict** its state (bounded memory, incremental). Without it, state grows forever. Cost: events >3 min late aren't counted.

**One-liner:** *Counts events per 1-minute bucket per state; the 3-minute watermark closes+evicts each window (bounded, incremental) at the price of dropping anything >3 min late.*

### C17 — Reading expectation metrics from the event log (code)

**Where it lives:** the event log is a hidden Delta table `event_log_{pipeline_id}` in the pipeline's default catalog/schema, queried via the **`event_log(<pipeline-id>)`** TVF (or `event_log(TABLE(catalog.schema.dataset))`). Only the pipeline's **run-as user** can query it by default (publish it to a UC table to share). Expectation metrics sit in `event_type = 'flow_progress'` under `details:flow_progress:data_quality` — an `expectations[]` array (each with `name`, `dataset`, `passed_records`, `failed_records`) plus a top-level `dropped_records`.

```sql
-- Per-expectation pass/fail (explode the array)
SELECT
  row_exp.dataset,
  row_exp.name                AS expectation,
  SUM(row_exp.passed_records) AS passed,
  SUM(row_exp.failed_records) AS failed
FROM (
  SELECT explode(
    from_json(
      details:flow_progress:data_quality:expectations,
      'array<struct<name STRING, dataset STRING, passed_records BIGINT, failed_records BIGINT>>'
    )
  ) AS row_exp
  FROM event_log('<pipeline-id>')          -- or event_log(TABLE(main.sales.orders))
  WHERE event_type = 'flow_progress'
)
GROUP BY 1, 2
ORDER BY failed DESC;

-- Dropped-row count per flow_progress event
SELECT timestamp,
       details:flow_progress:data_quality:dropped_records::bigint AS dropped
FROM event_log('<pipeline-id>')
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC;
```
```python
metrics = spark.sql("""
  SELECT explode(from_json(
           details:flow_progress:data_quality:expectations,
           'array<struct<name STRING, dataset STRING, passed_records BIGINT, failed_records BIGINT>>'
         )) AS e
  FROM event_log('<pipeline-id>')
  WHERE event_type = 'flow_progress'
""")
(metrics.select("e.dataset", "e.name", "e.passed_records", "e.failed_records")
        .groupBy("dataset", "name")
        .sum("passed_records", "failed_records")
        .show(truncate=False))
```

**One-liner:** *Expectation pass/fail/drop counts live in the hidden `event_log_{pipeline_id}` Delta table under `flow_progress.data_quality`; explode `expectations` from the `event_log(<pipeline-id>)` TVF (run-as user only) to build a DQ dashboard.*

### C18 — Quarantine pattern (preserve bad rows instead of dropping)

**Problem:** `expect_or_drop` removes bad rows but you **lose them** — only a count survives in the event log. When you must keep bad rows **for investigation** (fix upstream, then re-ingest), use **quarantine**: tag rows valid/invalid once, then split into a **clean** table and a **side quarantine** streaming table.

```sql
-- 1) tag once with a validity flag
CREATE TEMPORARY VIEW orders_tagged AS
SELECT *, (id IS NOT NULL AND amount > 0) AS is_valid
FROM STREAM bronze_orders;

-- 2) clean table = valid rows only
CREATE OR REFRESH STREAMING TABLE orders_clean AS
SELECT * EXCEPT (is_valid) FROM STREAM orders_tagged WHERE is_valid;

-- 3) quarantine side table = the bad rows, preserved (with a timestamp / reason)
CREATE OR REFRESH STREAMING TABLE orders_quarantine AS
SELECT *, current_timestamp() AS quarantined_at
FROM STREAM orders_tagged WHERE NOT is_valid;
```
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr, current_timestamp

RULES = {"valid_id": "id IS NOT NULL", "valid_amount": "amount > 0"}
is_valid = " AND ".join(RULES.values())

@dp.temporary_view
def orders_tagged():
    return spark.readStream.table("bronze_orders").withColumn("is_valid", expr(is_valid))

@dp.table(name="orders_clean")
@dp.expect_all(RULES)                       # WARN -> still get pass/fail metrics in the event log
def orders_clean():
    return spark.readStream.table("orders_tagged").where("is_valid").drop("is_valid")

@dp.table(name="orders_quarantine")         # side table preserves the rejects
def orders_quarantine():
    return (spark.readStream.table("orders_tagged").where("NOT is_valid")
            .withColumn("quarantined_at", current_timestamp()))
```

Two flows read the **same tagged upstream**: `orders_clean` keeps `is_valid` rows (the `@dp.expect_all` is WARN, so you still get DQ metrics while the filter does the split), and `orders_quarantine` keeps `NOT is_valid` rows with a timestamp/reason — so you can inspect failures, correct the source, and re-ingest, none of which a plain `DROP` allows.

**One-liner:** *Quarantine = tag rows valid/invalid once, route valid → clean table and invalid → a side streaming table (with reason + timestamp), preserving bad rows for investigation instead of silently dropping them.*


### C19 — Event log: query every aspect of a pipeline (event_type catalog + recipes)

**Where it lives:** a hidden Delta table `event_log_{pipeline_id}` in the pipeline's default catalog/schema (shows in `system.information_schema.tables`, not Catalog Explorer). Query via the **`event_log()` TVF**; **only the run-as user** can query by default. Publish it (Advanced settings → `event_log: {catalog, schema, name}`) and put a **view** over it before granting (sharing the raw table can leak schema metadata). Never delete the event log / its catalog / schema.

```sql
SELECT * FROM event_log('<pipeline-id>');             -- run-as user
SELECT * FROM event_log(TABLE(main.sales.orders));    -- scoped to one dataset
CREATE VIEW event_log_raw AS SELECT * FROM event_log('<pipeline-id>');  -- working view (streamable)
```

**Top-level columns (every row):** `id`, `sequence`, `origin` (struct: `pipeline_id`, `pipeline_name`, `pipeline_type`, `update_id`, **`flow_id`**, `flow_name`, `batch_id`, `cluster_id`, `cloud`, `region`, `org_id`, `table_name`, `dataset_name`, `sink_name`, `request_id`), `timestamp` (UTC), `message`, `level` (`INFO`/`WARN`/`ERROR`/**`METRICS`** = Delta-only, hidden from UI), `maturity_level` (`STABLE`/`EVOLVING`/`DEPRECATED`/`NULL`), `error`, **`details`** (JSON whose shape depends on `event_type`), `event_type`.

`origin.flow_id` is the **incremental identity** — stable while a flow refreshes incrementally; it **changes on MV full refresh, checkpoint reset, or full recompute**. `pipeline_type` ∈ `WORKSPACE`/`DBSQL`/`MANAGED_INGESTION`/`BRICKSTORE`/`BRICKINDEX`.

**The `event_type` catalog (16):**

| `event_type` | Tells you | `details` path |
|---|---|---|
| `create_update` | run started; config, `run_as`, `cause` | `details:create_update` |
| `update_progress` | whole-run state → `COMPLETED`/`FAILED`/`CANCELED` | `details:update_progress.state` |
| `user_action` | audit: `CREATE`/`START`/cancel + who | `details:user_action.{action,user_name}` |
| `runtime_details` | DBR version | `details:runtime_details.dbr_version` |
| `flow_definition` | lineage + schema + query plan (DAG edges) | `details:flow_definition.{output_dataset,input_datasets,flow_type}` |
| `dataset_definition` | a dataset (flow source/dest) | `details:dataset_definition` |
| `sink_definition` | a sink | `details:sink_definition` |
| `flow_progress` | **per-flow** lifecycle + row metrics + data quality | `details:flow_progress.{status,metrics.*,data_quality.*}` |
| `planning_information` | **why a MV went incremental vs full** | `details:planning_information.technique_information` |
| `operation_progress` | Auto Loader listing/backfill, connector fetch, CDC snapshot | `details:operation_progress.{type,status,duration_ms}` |
| `stream_progress` | Structured-Streaming per-microbatch metrics | `details:stream_progress.progress` |
| `cluster_resources` | **classic compute only** — slot utilization, autoscale state | `details:cluster_resources.*` |
| `autoscale` | **classic compute only** — resize requests | `details:autoscale.*` |
| `hook_progress` | event-hook status | `details:hook_progress.{name,status}` |
| `deprecation` | deprecated features in use | `details:deprecation` |
| `behavior_change_in_spark_connect` | env-version compat-scan flags | `details:behavior_change_in_spark_connect` |

`flow_progress.status` ∈ `QUEUED/STARTING/RUNNING/COMPLETED/FAILED/SKIPPED/STOPPED/IDLE/EXCLUDED`; `operation_progress.type` ∈ `AUTO_LOADER_LISTING/AUTO_LOADER_BACKFILL/CONNECTOR_FETCH/CDC_SNAPSHOT`.

**Recipe book (over `event_log_raw`):**

```sql
-- run history: status + duration
SELECT origin.update_id,
       MIN(CASE WHEN event_type='create_update' THEN timestamp END) AS started,
       MAX_BY(details:update_progress.state, timestamp) AS final_state
FROM event_log_raw WHERE event_type IN ('create_update','update_progress')
GROUP BY origin.update_id ORDER BY started DESC;

-- per-flow row metrics + dropped-by-DQ
SELECT origin.flow_name, details:flow_progress.status AS status,
       details:flow_progress.metrics.num_output_rows::bigint   AS out_rows,
       details:flow_progress.metrics.num_upserted_rows::bigint AS upserts,
       details:flow_progress.metrics.num_deleted_rows::bigint  AS deletes,
       details:flow_progress.data_quality.dropped_records::bigint AS dq_dropped
FROM event_log_raw WHERE event_type='flow_progress';

-- expectation pass/fail
SELECT e.dataset, e.name, SUM(e.passed_records) passed, SUM(e.failed_records) failed
FROM (SELECT explode(from_json(details:flow_progress:data_quality:expectations,
        'array<struct<name STRING,dataset STRING,passed_records BIGINT,failed_records BIGINT>>')) AS e
      FROM event_log_raw WHERE event_type='flow_progress') GROUP BY 1,2;

-- lineage
SELECT details:flow_definition.output_dataset AS output,
       details:flow_definition.input_datasets AS inputs
FROM event_log_raw WHERE details:flow_definition IS NOT NULL;

-- why full vs incremental (MV)
SELECT timestamp, origin.flow_name, message
FROM event_log_raw WHERE event_type='planning_information' ORDER BY timestamp DESC;

-- Auto Loader ingestion · backlog · autoscaling · audit · runtime · streaming
SELECT * FROM event_log_raw WHERE event_type='operation_progress'
  AND details:operation_progress.type IN ('AUTO_LOADER_LISTING','AUTO_LOADER_BACKFILL');
SELECT timestamp, details:flow_progress.metrics.backlog_bytes::double AS backlog
  FROM event_log_raw WHERE event_type='flow_progress';
SELECT * FROM event_log_raw WHERE event_type IN ('autoscale','cluster_resources');   -- classic only
SELECT timestamp, details:user_action:action, details:user_action:user_name
  FROM event_log_raw WHERE event_type='user_action';
SELECT origin.update_id, details:runtime_details:runtime_version:dbr_version
  FROM event_log_raw WHERE event_type='runtime_details';
SELECT parse_json(get_json_object(details,'$.stream_progress.progress_json'))
  FROM event_log_raw WHERE event_type='stream_progress';
```

**Gotchas:** run-as only (publish + view to share); `level='METRICS'` rows are hidden from the UI; `flow_id` change = that flow full-refreshed/reset; **`FAIL` expectations record NO data-quality metrics** (the update fails before metrics are written — evidence is the `error` field / message, not `data_quality`); expectation metrics can be absent for some datasets; `planning_information.technique_information.incrementalization_issues` (e.g. `DATA_HAS_CHANGED`, `TIME_ZONE_CHANGED`, `PRIOR_TIMESTAMP_MISSING`) explains *why* a MV went full.

**One-liner:** *Every aspect of a pipeline is one `event_type` filter on the `event_log()` TVF — `update_progress` (runs), `flow_progress` (per-flow metrics + DQ), `flow_definition` (lineage), `planning_information` (incremental-vs-full), `operation_progress` (Auto Loader), `cluster_resources`/`autoscale` (classic compute), `user_action` (audit).*


### C20 — Runtime channels: `current` vs `preview`

`channel` selects **which version of the SDP/Lakeflow runtime** runs your pipeline. There are exactly **two** values (no separate stable/beta/LTS tiers):

| Channel | What it is | Use for |
|---|---|---|
| **`current`** (default) | The current/stable runtime — **all GA *and* Public Preview features live here** | **Production** (Databricks' recommendation) |
| **`preview`** | The **next** runtime version — test upcoming engine changes before they become `current` | Staging/test pipelines; a few features gated to it (some Beta flows, MLflow models in a UC pipeline) |

**Two scopes for the same knob:**
- **Pipeline setting `channel`** — whole pipeline (config field; default `current`).
- **Table property `pipelines.channel`** — per-dataset, used for **standalone** (DBSQL-created) MV/ST and to opt a table into a preview-gated feature:
```sql
CREATE OR REPLACE MATERIALIZED VIEW sales
TBLPROPERTIES ('pipelines.channel' = 'preview')
AS ...;
```

**Gotchas:**
- Default is `current`; **GA + Public Preview features are already in `current`**, so `preview` is *not* needed for most Public Preview things — it's specifically for testing the **next runtime**.
- **Version mapping rolls** (don't memorize): as of Apr–May 2026, `current` = DBR 17.3, `preview` = DBR 18.1 (earlier in 2026 both were 17.3). Find the actual version per run via the event-log `runtime_details` event.
- **Serverless gotcha:** standalone MV/ST on serverless generic compute **reject `preview`** — only `current` (error `STANDALONE_MATERIALIZED_VIEW_STREAMING_TABLE_PREVIEW_CHANNEL_NOT_SUPPORTED` → "remove `pipelines.channel` or set it to `CURRENT`").
- A change that works on `preview` **may behave differently on `current`** — validate before deploying to prod.
- **Best practice:** keep prod on `current`; run a **staging pipeline on `preview` weekly** with failure alerts to catch breakage before the next runtime auto-upgrades into `current`.
- Runtime **auto-revert** to last-known-good happens only on **production mode + `channel=current`** (see C-section on deployment modes / Q8).

**One-liner:** *`channel` picks the runtime — `current` (default, stable, has all GA + Public Preview features) or `preview` (test the next runtime); set it pipeline-wide via `channel` or per-table via `pipelines.channel`, but `preview` isn't supported for serverless standalone MV/ST.*
