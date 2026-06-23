# Databricks DE Professional — S5: Monitoring & Alerting

> **Exam objective S5 (10% of the exam)** — *"system tables for resource/cost/audit/workload observability; Query Profiler UI + Spark UI; REST API/CLI for monitoring jobs+pipelines; SDP event logs; SQL Alerts for data quality; Jobs UI/API notifications."*
> **Source grounding:** every fact below is cited inline to current `learn.microsoft.com/azure/databricks` docs (verified June 2026). Schemas verified column-by-column against the live system-table reference pages — these change frequently, so the citations matter.
> **Audience assumption:** you already operate 422 SDP pipelines (Apollo Gen2). This doc does **not** re-teach expectations / AUTO CDC / Auto Loader / SCD2. It teaches the *observability surface around* them — the part that shows up on the exam and that you touch less day-to-day.

---

## Why this matters (the mental model)

Monitoring on Databricks splits cleanly into **two planes**, and the exam tests whether you know which tool lives on which plane:

| Plane | Question it answers | Primary tools |
|---|---|---|
| **Observability (read-after-the-fact)** | "What happened? Who did it? What did it cost? Why was it slow?" | System tables, Query Profiler, Spark UI, SDP event log |
| **Alerting (act-on-the-fact)** | "Tell me *when* X happens." | SQL Alerts, Lakeflow Jobs notifications, event hooks |

The trap the exam loves: conflating these. A **system table** is a passive Delta table you query — it does not push anything. A **SQL Alert** is the thing that pushes. You build alerting *on top of* observability data (often by pointing a SQL Alert at a query over a system table).

The most important architectural fact: **system tables are governed by Unity Catalog, are account-wide (all workspaces in the same cloud region), are read-only, and are delivered to your metastore via Delta Sharing from a Databricks-hosted storage account.** ([System tables reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/)) That single sentence answers ~3 exam questions on its own.

---

## S5.1 — System tables

### What they are and how access works

System tables live in the `system` catalog (one per Unity Catalog metastore), organized into schemas (`access`, `billing`, `compute`, `lakeflow`, `query`, `storage`, …). Key invisible behaviors the exam probes:

- **Account-admins have access by default. Everyone else gets nothing** until a principal who is *both* a metastore admin *and* an account admin grants `USE CATALOG` on `system`, `USE SCHEMA` on the schema, and `SELECT` on the schema. ([Grant access](https://learn.microsoft.com/azure/databricks/admin/system-tables/#grant-access))
- **Schemas must be explicitly enabled.** Some schemas (e.g. `query`) ship disabled and an admin enables them per-account. Until enabled, the table simply doesn't exist for you.
- **Regional vs global.** `system.billing.usage` is **global** (every workspace, every region). Almost everything else (`compute.*`, `lakeflow.*`, `query.history`, `access.audit` workspace-level events) is **regional** — to see another region's records you must run the query *from a workspace in that region*. Account-level audit events are global. ([System tables reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/#which-system-tables-are-available))
- **Free retention is 365 days** for most tables. Exceptions: `data_quality_monitoring.table_results` is indefinite; `storage.predictive_optimization_operations_history` is 180 days; `compute.node_types` and `billing.list_prices` are indefinite.

> **Define-before-use:** *SCD2* = Slowly Changing Dimension Type 2. Instead of overwriting a row when a config changes, the table appends a *new* row and logically retires the old one. You reconstruct "current state" with a window function picking the latest `change_time` per key.

A subtle SCD2 retention nuance you'll get wrong if you skim: in the SCD2 tables (`lakeflow.jobs`, `lakeflow.job_tasks`, `lakeflow.pipelines`, `compute.clusters`, `compute.instance_pools`), Databricks **always retains the single most-recent record per entity even if it's older than 365 days** — but discards older historical rows beyond the window. So `WHERE change_time > now() - interval 365 days` can silently drop the latest config of a stale job. ([Jobs system table reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))

```sql
-- The canonical "give me current state of an SCD2 table" pattern.
-- You will write this constantly. Memorize it.
SELECT *
FROM system.lakeflow.jobs
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY workspace_id, job_id
  ORDER BY change_time DESC
) = 1;
```

---

### `system.billing.usage` — cost & resource attribution

This is the spine of cost observability. One row = one billable usage record. ([Billable usage reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/billing#billable-usage-table-schema))

**Columns you must know:**

| Column | Type | Why it's on the exam |
|---|---|---|
| `record_id` | string | Unique per usage record |
| `workspace_id` | string | Attribution dimension |
| `sku_name` | string | e.g. `STANDARD_ALL_PURPOSE_COMPUTE`, `PREMIUM_JOBS_SERVERLESS_COMPUTE` |
| `usage_start_time` / `usage_end_time` | timestamp | UTC (`+00:00` suffix) |
| `usage_date` | date | Use this for fast date aggregation — not `usage_start_time` |
| `usage_quantity` | decimal | **The number of units** consumed |
| `usage_unit` | string | The unit, e.g. `DBU` |
| `custom_tags` | map | Cost-center / env tags (includes serverless-policy-injected tags) |
| `billing_origin_product` | string | `JOBS`, `DLT`, `SQL`, `ALL_PURPOSE`, `MODEL_SERVING`, … |
| `usage_metadata` | struct | The join keys: `cluster_id`, `job_id`, `job_run_id`, `warehouse_id`, `dlt_pipeline_id`, … |
| `identity_metadata` | struct | `run_as` field — who incurred it |
| `record_type` | string | `ORIGINAL` / `RETRACTION` / `RESTATEMENT` (corrections) |

**Invisible behavior — call these out, the exam does:**

1. **`usage_quantity` is in DBUs, not money.** To get currency you must join `system.billing.list_prices` (a.k.a. the *Pricing* table at `system.billing.list_prices`) on `sku_name` with a time-bounded price window. ([Jobs cost join](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))
2. **`usage_metadata.job_id` is populated only for job/serverless compute — never for all-purpose compute.** So you cannot precisely cost a job that ran on an interactive cluster (multiple workloads share the cluster; no 1:1 mapping). ([Jobs cost — all-purpose caveat](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))
3. **Distributed double-counting illusion:** a single serverless job run can produce *multiple rows* with the same `job_run_id` but different DBU values in one timeframe. You must `SUM` them. ([Serverless billing](https://learn.microsoft.com/azure/databricks/admin/system-tables/serverless-billing))
4. **`WORKFLOW_RUN` (notebook-launched workflows) get no own `job_id` attribution** — their cost rolls up to the *parent notebook*.

```sql
-- DBUs -> currency. The time-bounded price join is the exam-tested part:
-- a SKU's price changes over time, so you must match the price record that
-- was active at usage_start_time (price_end_time IS NULL = currently active).
WITH jobs_usage AS (
  SELECT *, usage_metadata.job_id AS job_id, usage_metadata.job_run_id AS run_id
  FROM system.billing.usage
  WHERE billing_origin_product = 'JOBS'
)
SELECT
  j.job_id,
  j.run_id,
  SUM(j.usage_quantity * p.pricing.default) AS cost_usd
FROM jobs_usage j
LEFT JOIN system.billing.list_prices p
  ON  j.sku_name = p.sku_name
  AND p.price_start_time <= j.usage_start_time
  AND (p.price_end_time >= j.usage_start_time OR p.price_end_time IS NULL)
  AND p.currency_code = 'USD'
GROUP BY ALL
ORDER BY cost_usd DESC;
```

**Recap:** `usage` gives DBUs and join keys; you bring currency (`list_prices`), human names (`lakeflow.jobs`), and hardware (`compute.clusters`) by joining — and you only get clean per-job cost on dedicated/serverless compute.

---

### `system.access.audit` — who did what

One row per audit event. **Public Preview.** ([Audit log reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/audit-logs))

**Columns:** `account_id`, `workspace_id`, `version`, `event_time` (UTC), `event_date`, `source_ip_address`, `user_agent`, `session_id`, `user_identity` (struct with `.email`), `service_name`, `action_name`, `request_id`, `request_params` (map — varies by event type), `response` (struct: `statusCode`, `errorMessage`, `result`), `audit_level` (`WORKSPACE_LEVEL` / `ACCOUNT_LEVEL`), `event_id`, `identity_metadata`.

**Invisible behaviors:**
- **Account-level events record `workspace_id = 0`.** (Common WHERE-clause gotcha.)
- The shape of `request_params` is **entirely event-type-dependent** — it's an untyped map, so you dig in with `request_params.<key>`.
- `event_date` is a partition-friendly date; filter on it, not `event_time`, for cheap scans.

```sql
-- "Who queried this PII table in the last 7 days, and did it succeed?"
SELECT event_time, user_identity.email, action_name,
       request_params.full_name_arg AS object,
       response.statusCode
FROM system.access.audit
WHERE service_name = 'unityCatalog'
  AND action_name IN ('getTable', 'generateTemporaryTableCredential')
  AND request_params.full_name_arg = 'prod.customer.pii'
  AND event_date >= current_date() - INTERVAL 7 DAYS;
```

**Recap:** `access.audit` is the security/compliance ledger; key it on `service_name` + `action_name`, remember account events use `workspace_id = 0`, and dig into the untyped `request_params` map.

---

### `system.compute.*` — cluster fleet & utilization

Five tables. ([Compute system tables](https://learn.microsoft.com/azure/databricks/admin/system-tables/compute))

| Table | Grain | Key columns |
|---|---|---|
| `system.compute.clusters` | **SCD2**, one row per config version | `cluster_id`, `cluster_name`, `owned_by`, `driver_node_type`, `worker_node_type`, `worker_count`, `min/max_autoscale_workers`, `auto_termination_minutes`, `cluster_source` (`UI`/`API`/`JOB`/`PIPELINE`/`PIPELINE_MAINTENANCE`), `dbr_version`, `data_security_mode`, `policy_id`, `change_time` |
| `system.compute.node_timeline` | **minute-by-minute** utilization per node | `cluster_id`, `instance_id`, `start_time`/`end_time`, `driver` (bool), `cpu_user_percent`, `cpu_system_percent`, `cpu_wait_percent`, `mem_used_percent`, `network_sent/received_bytes`, `node_type` |
| `system.compute.node_types` | one row per available instance type | `node_type`, `core_count`, `memory_mb`, `gpu_count` |
| `system.compute.instance_events` (Preview) | state transitions | `instance_id`, `event_type`, `state` (`INSTANCE_LAUNCHING`/`READY`/`PLACED`/`TERMINATED`), `cluster_id`, `availability_type` (`ON_DEMAND`/`SPOT`) |
| `system.compute.instance_pools` (Preview) | **SCD2** pool configs | `instance_pool_id`, `min_idle_instances`, `max_capacity`, `idle_instance_autotermination_minutes` |

**Invisible behaviors — these are direct exam fodder:**
- `compute.*` covers **all-purpose, jobs, and SDP (pipeline) compute only**. It does **NOT** include **serverless compute or SQL warehouses** (those have separate tables: `system.compute.warehouses` and `warehouse_events`). ([Known limitations](https://learn.microsoft.com/azure/databricks/admin/system-tables/compute))
- **Nodes that ran < 10 minutes may never appear in `node_timeline`.**
- In `instance_events`, `cluster_id` is populated **only** when `state = 'INSTANCE_PLACED'` (null in all other states).
- `data_security_mode` decodes: `USER_ISOLATION` = Standard access mode, `SINGLE_USER` = Dedicated access mode.

```sql
-- Find under-utilized clusters: high cost, low CPU. The classic
-- "why is my bill so high" investigation.
SELECT cluster_id, driver,
       avg(cpu_user_percent + cpu_system_percent) AS avg_cpu,
       max(cpu_user_percent + cpu_system_percent) AS peak_cpu,
       avg(mem_used_percent)                       AS avg_mem
FROM system.compute.node_timeline
WHERE start_time >= now() - INTERVAL 1 DAY
GROUP BY cluster_id, driver
ORDER BY avg_cpu ASC;   -- low avg_cpu + still-running = wasted spend
```

**Recap:** `compute.*` is classic-compute telemetry (no serverless, no SQL warehouses); `clusters` is the SCD2 config dimension, `node_timeline` is the minute-grain utilization fact, and the join key back to `billing.usage` is `cluster_id`.

---

### `system.lakeflow.*` — jobs & pipelines (the DE bread-and-butter)

> **Note for the exam:** the `lakeflow` schema was previously `workflow`. **Content is identical.** Older docs/questions may say `system.workflow.job_runs`/`task_runs` — treat as aliases. ([Jobs system table reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))

Six tables:

| Table | Grain / type | Purpose |
|---|---|---|
| `system.lakeflow.jobs` | **SCD2** | job definitions (name, creator, tags, `trigger_type`, `paused`, `timeout_seconds`, `health_rules`) |
| `system.lakeflow.job_tasks` | **SCD2** | task definitions + `depends_on_keys` (the DAG edges) |
| `system.lakeflow.job_run_timeline` | **immutable fact** | one+ rows per *run*: `run_id`, `period_start/end_time`, `trigger_type`, `run_type`, `result_state`, `termination_code`, duration breakdown |
| `system.lakeflow.job_task_run_timeline` | **immutable fact** | per *task run*: adds `task_key`, `compute_ids`, per-phase durations |
| `system.lakeflow.pipelines` (Preview) | **SCD2** | SDP pipeline definitions: `pipeline_type`, `settings`, `configuration`, `run_as` |
| `system.lakeflow.pipeline_update_timeline` (Preview) | **immutable fact** | per *update*: `update_id`, `update_type` (`FULL_REFRESH`/`REFRESH`/`VALIDATE`), `result_state`, `trigger_type` |

**The enum values you should be able to recognize on sight:**

- `job_run_timeline.run_type`: `JOB_RUN` (standard), `SUBMIT_RUN` (one-time `runs/submit`, never written to `jobs`/`job_tasks`), `WORKFLOW_RUN` (notebook-launched, **only** in `job_run_timeline`, invisible in UI & API). ([Run types](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))
- `result_state`: `SUCCEEDED`, `FAILED`, `SKIPPED`, `CANCELLED`, `TIMED_OUT`, `ERROR`, `BLOCKED`, `NULL`.
- `termination_code`: `SUCCESS`, `CANCELLED`, `SKIPPED`, `DRIVER_ERROR`, `CLUSTER_ERROR`, `RUN_EXECUTION_ERROR`, `MAX_CONCURRENT_RUNS_EXCEEDED`, `LIBRARY_INSTALLATION_ERROR`, `UNAUTHORIZED_ERROR`, … (a `result_state=FAILED` row carries the *why* here).
- `pipelines.pipeline_type`: `ETL_PIPELINE`, `MATERIALIZED_VIEW`, `STREAMING_TABLE`, `INGESTION_PIPELINE`, `INGESTION_GATEWAY`.

**Invisible behaviors:**
1. **Hourly slicing.** A run longer than 1 hour is split across multiple rows with the same `run_id`. **`result_state` / `termination_code` / final durations are populated ONLY on the last (terminal) row** — intermediate rows have `NULL`. Always filter `result_state IS NOT NULL` when counting outcomes, or `SUM(period_end_time - period_start_time)` for true duration. ([Slicing logic](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))
2. **Slicing logic changed on 2026-01-19** from *run-start-aligned* hourly windows (4:47→5:47…) to *clock-hour-aligned* windows (4:47→5:00, 5:00→6:00…). New rows use the new logic; existing rows are untouched. (A genuinely new fact since older study material.)
3. **A run that never executed** is a single row where `period_start_time == period_end_time`; check `termination_code` for why (e.g. `MAX_JOB_QUEUE_SIZE_EXCEEDED`).
4. **`job_id` is unique only within a workspace** — always join/group on `(workspace_id, job_id)`.

```sql
-- Daily failure rate per job over the last 7 days. Note: result_state IS NOT NULL
-- excludes the intermediate hourly slices that would otherwise inflate counts.
SELECT to_date(period_start_time) AS d,
       job_id,
       count(DISTINCT run_id)                                      AS runs,
       count(DISTINCT IF(result_state='FAILED', run_id, NULL))     AS failed
FROM system.lakeflow.job_run_timeline
WHERE period_start_time > now() - INTERVAL 7 DAYS
  AND result_state IS NOT NULL
GROUP BY ALL
ORDER BY failed DESC;
```

```sql
-- "Which jobs are secretly running on all-purpose compute?" (a cost smell):
-- join the task-run fact to the clusters dimension, filtering cluster_source.
WITH clusters AS (
  SELECT * FROM system.compute.clusters
  WHERE cluster_source IN ('UI','API')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, cluster_id ORDER BY change_time DESC)=1
),
tasks AS (
  SELECT workspace_id, job_id, EXPLODE(compute_ids) AS cluster_id
  FROM system.lakeflow.job_task_run_timeline
  WHERE period_start_time >= current_date() - INTERVAL 30 DAY
)
SELECT t.job_id, c.cluster_name, c.owned_by
FROM tasks t JOIN clusters c USING (workspace_id, cluster_id);
```

**For your 422 pipelines:** enrich billing logs with pipeline metadata via `usage_metadata.dlt_pipeline_id` (the column is still `dlt_pipeline_id` even under the `lakeflow`/SDP rename) joined to `system.lakeflow.pipelines`. ([Pipelines join example](https://learn.microsoft.com/azure/databricks/admin/system-tables/jobs))

**Recap:** SCD2 *definition* tables + immutable *timeline* fact tables; the killer detail is that long runs are hour-sliced and only the terminal row carries `result_state` — get that wrong and every failure/duration query is wrong.

---

### `system.query.history` — every SQL statement

**Public Preview**, regional, 365-day retention, **`query` schema must be enabled by an admin**. Captures statements on **SQL warehouses and serverless compute for notebooks/jobs** — *not* statements on classic all-purpose clusters. ([Query history reference](https://learn.microsoft.com/azure/databricks/admin/system-tables/query-history))

**High-value columns:**

| Column | Use |
|---|---|
| `statement_id` | Paste into Query History UI to open the **query profile** |
| `execution_status` | `FINISHED` / `FAILED` / `CANCELED` |
| `statement_text` | **Redacted by default** (see below) |
| `error_message` | failure reason |
| `total_duration_ms`, `execution_duration_ms`, `compilation_duration_ms`, `waiting_for_compute_duration_ms`, `waiting_at_capacity_duration_ms`, `result_fetch_duration_ms` | latency breakdown |
| `total_task_duration_ms` | summed across all cores — can exceed wall-clock (parallelism) |
| `read_partitions`, `pruned_files`, `read_files` | **data-skipping effectiveness** |
| `read_rows`, `produced_rows`, `read_bytes`, `written_rows/bytes/files` | I/O volume |
| `spilled_local_bytes` | **spill to disk** (memory pressure signal) |
| `shuffle_read_bytes` | shuffle volume |
| `from_result_cache` | result served from cache |
| `compute` | struct: `type` = `WAREHOUSE` or `SERVERLESS_COMPUTE`, plus the resource id |
| `query_source` | struct linking statement → `alert_id` / `dashboard_id` / `notebook_id` / `job_info.{job_id,job_run_id,job_task_run_id}` / `genie_space_id` |
| `query_tags` | map — **only populated for SQL-warehouse queries**; set via `SET QUERY_TAGS` |
| `executed_by` vs `executed_as` | who *ran* it vs whose *privilege* it ran under (matters for `run as` views) |

**Invisible behaviors:**
1. **`statement_text` returns `<Redacted>`** for anyone who isn't an account admin or in the **`databricks_pii_access`** account-level group — which **doesn't exist until an admin manually creates it** (name is case-sensitive). Workspace admins are *not* auto-members. ([Redacted statement text](https://learn.microsoft.com/azure/databricks/admin/system-tables/query-history#access-redacted-statement-text))
2. With customer-managed keys configured, `statement_text` and `error_message` are **encrypted/empty** until a key config is added to the `system` catalog (up to 24h to take effect).
3. `query_source` can hold **multiple non-null IDs** simultaneously (e.g. a job result triggers an alert that runs a query → `job_info` + `alert_id` + `sql_query_id` all populated). They are **not** ordered by execution.

```sql
-- Find the slowest SQL-warehouse queries last 24h with poor data skipping.
-- read_files high relative to pruned_files = skipping isn't helping.
SELECT statement_id, executed_by, total_duration_ms,
       pruned_files, read_files, spilled_local_bytes, shuffle_read_bytes
FROM system.query.history
WHERE start_time > now() - INTERVAL 1 DAY
  AND execution_status = 'FINISHED'
  AND compute.type = 'WAREHOUSE'
ORDER BY total_duration_ms DESC
LIMIT 20;
-- Then copy statement_id -> Query History UI -> "See query profile".
```

**Recap:** `query.history` is the warehouse/serverless SQL fact table for latency and I/O forensics; `statement_id` is your bridge to the visual Query Profiler; and `statement_text` is redacted unless someone built the `databricks_pii_access` group.

---

## S5.2 — Query Profiler UI + Spark UI

These are the two *visual* drill-down tools. The exam wants you to know **which one to reach for**.

### Query Profiler (Databricks SQL — warehouses & serverless)

Open it: **Query History → click a query → See query profile**. ([Query profile](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))

- Left pane = **summary metrics** + **Top operators** (most expensive ops, ranked) + **Query text**.
- Right pane = the **DAG** of operators; switch the displayed metric between **Time spent / Memory peak / Rows**.
- Common operators to name: **Scan, Join, Union, Shuffle, Hash/Sort, Filter**.
- **Permission needed:** be the query owner *or* have **`CAN MONITOR`** on the SQL warehouse.
- **`Enable verbose mode`** (kebab menu) to see hidden/low-impact operator metrics.
- For DBSQL queries you can pivot into Spark UI via kebab → **Open in Spark UI**.

**Invisible behavior (exam-favorite):** **a query served from the result cache has NO profile** ("Query profile is not available"). To force a profile, make a trivial change (alter/remove the `LIMIT`) to bust the cache. ([Query profile — cache caveat](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))

**Performance insights** (Beta) surface ranked, actionable findings right in the profile. Codes you should recognize: `DATA_SPILL` (data didn't fit in memory → size up the warehouse / trim columns), `EXCESSIVE_QUEUE_TIME` (→ raise max clusters), `IO_THROTTLING` (cloud-storage request throttled). ([Query performance insights](https://learn.microsoft.com/azure/databricks/sql/user/queries/performance-insights))

**What you hunt for in a profile (S6/S9 overlap):** exploding joins, full table scans (bad data skipping → `pruned files` ≈ 0), spill, and skew. These map directly to S6 "find bottlenecks (bad data skipping, join types, shuffle)."

### Spark UI (classic compute)

For all-purpose / jobs / SDP **classic** clusters, the Spark UI is the drill-down. The exam's diagnostic flow ([Diagnosing a long job](https://learn.microsoft.com/azure/databricks/optimizations/spark-ui-guide/long-spark-stage), [Skew and spill](https://learn.microsoft.com/azure/databricks/optimizations/spark-ui-guide/long-spark-stage-page)):

1. **Find the longest stage** (sort stages by duration).
2. Read the stage's **Input / Output / Shuffle Read / Shuffle Write** columns to classify the work.
3. **Number of tasks = 1** → red flag (no parallelism).
4. **Spill:** check the stage page's spill stats. Spill = Spark ran out of memory and pushed data to disk (expensive; common during shuffle). No spill stats shown = no spill.
5. **Skew:** in **Summary Metrics**, compare **Max** task duration vs the **75th percentile**. **Max > ~1.5× the p75 → skew.** A healthy stage has Max ≈ p75.

> **Define-before-use:** *Shuffle* = redistributing/repartitioning data across executors over the network (e.g. for a wide join or `GROUP BY`). *Spill* = spilling in-memory data to local disk under memory pressure. *Skew* = one/few partitions far larger than the rest, so a few tasks dominate runtime.

**The clean decision rule for the exam:**

| You're on… | Use… |
|---|---|
| SQL warehouse / serverless | **Query Profiler** (and its Performance Insights) |
| Classic all-purpose / jobs / SDP classic cluster | **Spark UI** |
| Serverless **job** run | Query Profile metrics now surface *inside the job-run UI* (Beta: "Improved Lakeflow Performance Observability") — rows read/written, query count, insight lightbulbs — no separate profile needed. ([Serverless job query metrics](https://learn.microsoft.com/azure/databricks/jobs/monitor#view-query-performance-metrics-for-serverless-jobs)) |

**Recap:** Query Profiler = SQL warehouse/serverless DAG-and-metrics tool (cached queries have no profile); Spark UI = classic-cluster tool where you read Max-vs-p75 for skew and the stage spill stats for memory pressure.

---

## S5.3 — Monitoring jobs & pipelines via REST API + CLI

The CLI is a thin wrapper over the REST API: `databricks jobs get` → `GET /api/2.2/jobs/get`. ([Automate jobs](https://learn.microsoft.com/azure/databricks/jobs/automate)) **Jobs API is now 2.2** (2.1 capped at 100 tasks; >100 tasks *requires* 2.2 + CLI ≥ 0.244.0 / Python SDK ≥ 0.45.0). ([Large jobs](https://learn.microsoft.com/azure/databricks/jobs/large-jobs))

### Jobs — the monitoring command set

```bash
# Discover the surface area (do this in the workspace, it's the fastest reference):
databricks jobs -h
databricks jobs list-runs -h

# List runs, newest first; filter to failures in a time window:
databricks jobs list-runs --job-id 478701692316314 \
  --completed-only \
  --start-time-from 1718668800000 \
  --run-type JOB_RUN \
  --output json

# Inspect one run (status, task states, cluster, timing):
databricks jobs get-run <RUN_ID> --output json
databricks jobs get-run-output <RUN_ID>      # task output / error trace

# Re-run only the failed tasks of a run (S9 "remediate failed runs"):
databricks jobs repair-run <RUN_ID> --rerun-tasks task_a,task_b
```

Key flags the exam may reference: `list-runs` supports `--active-only` / `--completed-only`, `--run-type {JOB_RUN,SUBMIT_RUN,WORKFLOW_RUN}`, `--start-time-from/--start-time-to` (epoch ms), `--expand-tasks`, and `--page-token` for pagination. ([jobs command group](https://learn.microsoft.com/azure/databricks/dev-tools/cli/reference/jobs-commands))

**`submit` vs `run-now` — invisible behavior the exam loves:** `databricks jobs submit` creates a *one-time* run that is **never saved**, is **invisible in the UI**, and **cannot be serverless-auto-optimized on failure**. Use `jobs create` + `jobs run-now` for anything you want to monitor or retry. ([submit caveat](https://learn.microsoft.com/azure/databricks/dev-tools/cli/reference/jobs-commands#databricks-jobs-submit))

Equivalent REST call:

```bash
curl -s -X GET "https://${DATABRICKS_HOST}/api/2.2/jobs/get" \
  -H "Authorization: Bearer ${DATABRICKS_TOKEN}" \
  --data '{ "job_id": 11223344 }'
```

### Pipelines (SDP) — the monitoring command set

The `pipelines` command group is the SDP equivalent. The monitoring-relevant subcommands: ([CLI commands](https://learn.microsoft.com/azure/databricks/dev-tools/cli/commands#pipelines-commands))

```bash
databricks pipelines list-pipelines              # all pipelines
databricks pipelines get <PIPELINE_ID>           # config + latest update status
databricks pipelines list-updates <PIPELINE_ID>  # history of updates
databricks pipelines get-update <PIPELINE_ID> <UPDATE_ID>
databricks pipelines list-pipeline-events <PIPELINE_ID>   # <- the event log, via API
databricks pipelines start-update <PIPELINE_ID> --full-refresh
```

`list-pipeline-events` is the API/CLI path to the same event-log data you can also query as a Delta table (next section) — useful when you don't have SQL access but do have CLI creds. The Pipelines REST API is at `/api/2.0/pipelines/{pipeline_id}` (and `PUT` to update notification config). ([Pipeline maintenance](https://learn.microsoft.com/azure/databricks/ingestion/lakeflow-connect/pipeline-maintenance#set-up-alerts-and-notifications))

**Workspace limits worth memorizing (they show up as gotchas):** 2000 concurrent task runs (a `429 Too Many Requests` otherwise), 10,000 job creations/hour, 12,000 saved jobs, 1000 tasks/job. ([Lakeflow Jobs limits](https://learn.microsoft.com/azure/databricks/jobs/#monitoring-and-observability))

**Recap:** CLI = REST wrapper (Jobs API 2.2, >100 tasks needs it); `jobs get-run`/`get-run-output`/`repair-run` for run forensics + targeted re-run; `pipelines list-updates`/`get-update`/`list-pipeline-events` for SDP; and `jobs submit` runs are unsaved/invisible/non-retryable.

---

## S5.4 — SDP event logs (brief — you know these)

You run 422 pipelines, so just the exam-relevant edges:

- **The event log is a Delta table.** Query it without knowing its path via the **`event_log()` table-valued function** on a shared cluster or SQL warehouse: ([best practices](https://learn.microsoft.com/azure/databricks/ldp/best-practices#optimize-pipeline-performance))

```sql
SELECT * FROM event_log('<pipeline-id>')
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC LIMIT 100;
```

- **Row schema** (`event_log` TVF returns): `id`, `sequence`, `origin`, `timestamp`, `message`, `level` (`INFO`/`WARN`/`ERROR`/**`METRICS`**), `maturity_level` (`STABLE`/`EVOLVING`/`DEPRECATED`/`NULL`), `error`, `details` (JSON — the payload you parse with the `:` operator), `event_type`. ([event_log TVF](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/event_log#returns))
- **`event_type` values you should map to a use case:** `flow_progress` (lifecycle + **data quality metrics**), `update_progress` (update lifecycle states: `QUEUED`→…→`COMPLETED`/`FAILED`/`CANCELED`), `flow_definition` (**lineage** — `input_datasets`/`output_dataset`), `create_update`, `user_action`, `runtime_details` (DBR version), `cluster_resources`/`autoscale` (**classic compute only**), `planning_information` (MV full vs incremental recompute reason). ([event log schema](https://learn.microsoft.com/azure/databricks/ldp/monitor-event-log-schema#the-details-object))

- **Data-quality metrics live in `flow_progress`** under `details:flow_progress.data_quality.expectations` (per-expectation `passed_records`/`failed_records`) and `details:flow_progress.data_quality.dropped_records`. ([data quality metrics](https://learn.microsoft.com/azure/databricks/ldp/monitor-event-logs#advanced-queries))

```sql
-- Expectation pass/fail trend straight from the event log. Note level='METRICS'
-- events are stored in the Delta table but NOT shown in the pipelines UI.
SELECT timestamp,
       expectation.name,
       expectation.dataset,
       expectation.passed_records,
       expectation.failed_records,
       details:flow_progress.data_quality.dropped_records::bigint AS dropped
FROM event_log('<pipeline-id>'),
     LATERAL variant_explode(
       parse_json(details:flow_progress.data_quality.expectations)) AS expectation
WHERE event_type = 'flow_progress';
```

**Invisible behaviors worth re-confirming:** `fail`-policy expectations record **no** metrics (the update dies on the first bad record); data-quality metrics are absent if no expectations are defined, the flow has no updates, or `pipelines.metrics.flowTimeReporter.enabled` isn't set. ([expectation limitations](https://learn.microsoft.com/azure/databricks/ldp/expectations#manage-multiple-expectations)) And **never delete the event log or its parent catalog/schema** — future updates can fail. ([event log](https://learn.microsoft.com/azure/databricks/ldp/monitor-event-logs))

**Recap:** event log = a queryable Delta table (`event_log()` TVF); key on `event_type` (`flow_progress` for DQ, `flow_definition` for lineage), parse `details` JSON with `:`, and remember `METRICS`-level rows are table-only (invisible in the UI) and `fail` expectations log nothing.

---

## S5.5 — SQL Alerts for data quality

A **SQL Alert** = a Databricks SQL object that, on a schedule, runs a query on a SQL warehouse, evaluates a condition on the result, and notifies users/destinations if it's met. ([Create an alert](https://learn.microsoft.com/azure/databricks/sql/user/alerts/create))

**The seven editor parts:** Query editor, Compute (SQL warehouse — status indicator shows if running), Schedule (periodic / Quartz cron), Share (permissions), **Condition** (value + operator + threshold), **Notifications** (users / destinations + optional repeat frequency), Advanced.

**Lifecycle states:** `OK` ↔ `TRIGGERED` ↔ `ERROR`. You get notified on transitions; the schedule + notification frequency control repeat behavior while it stays `TRIGGERED`.

**Hard limitation (exam trap):** **alerts do NOT support parameterized queries.** ([create alert — parameters](https://learn.microsoft.com/azure/databricks/sql/user/alerts/create))

**Condition aggregations** (apply to a source column): `SUM`, `COUNT`, `COUNT_DISTINCT`, `AVG`, `MEDIAN`, `MIN`, `MAX`, `STDDEV`. The threshold can be a literal **or another column**. Comparison via a `comparison_operator` (e.g. `GREATER_THAN`). ([alert evaluation — bundle ref](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/resources#alert))

**Advanced settings worth knowing:** **Notify on OK** (recovery notice), **Empty result state** (status when 0 rows — note: don't use `UNKNOWN`, it's being deprecated), and **notification templates** with variables `{{ALERT_STATUS}}`, `{{ALERT_NAME}}`, `{{ALERT_URL}}`, `{{ALERT_CONDITION}}`, `{{ALERT_THRESHOLD}}`, `{{ALERT_COLUMN}}`, `{{QUERY_RESULT_TABLE}}` (first 100 rows; **HTML renders only in email destinations**), `{{QUERY_RESULT_VALUE}}`, etc. ([notification templates](https://learn.microsoft.com/azure/databricks/sql/user/alerts/create#review-alert-details))

**The data-quality pattern (this is the S5.5 answer):** write a query that returns a row (or count) *only when data is bad*, then alert when that count > 0.

```sql
-- Alert query: "how many orders failed the not-null SLA in the last hour?"
-- Point a SQL Alert at this with condition: COUNT(bad_rows) GREATER_THAN 0.
SELECT count(*) AS bad_rows
FROM prod.silver.orders
WHERE ingest_ts >= now() - INTERVAL 1 HOUR
  AND (customer_id IS NULL OR amount < 0);
```

You can also alert directly on **SDP expectation metrics** by pointing the query at the event log (S5.4), or on **cost** by pointing it at `system.billing.usage` (the docs literally ship "alert when a job exceeds {budget}" templates). ([serverless spend alerts](https://learn.microsoft.com/azure/databricks/admin/system-tables/serverless-billing#use-alerts-to-track-serverless-spend))

**CLI (two generations — know both exist):**

```bash
# v2 (current): explicit DISPLAY_NAME / QUERY_TEXT / WAREHOUSE_ID / EVALUATION / SCHEDULE
databricks alerts-v2 create-alert "Bad rows alert" \
  "SELECT count(*) AS bad_rows FROM prod.silver.orders WHERE amount < 0" \
  "a7066a8ef796be84" @evaluation.json @schedule.json

# legacy v1: condition object with op/operand/threshold
databricks alerts create --json '{"name":"High CPU Alert","query_id":"12345",
  "condition":{"op":"GREATER_THAN","operand":{"column":{"name":"cpu_usage"}},
  "threshold":{"value":{"double_value":80}}}}'
```

([alerts-v2](https://learn.microsoft.com/azure/databricks/dev-tools/cli/reference/alerts-v2-commands), [alerts v1](https://learn.microsoft.com/azure/databricks/dev-tools/cli/reference/alerts-commands))

**SQL Alert *task* in a Job** is distinct from a standalone alert: you add an **SQL Alert task** to a job (must use a **serverless or pro** warehouse), so the alert evaluation runs as part of an orchestrated DAG. ([SQL alert task](https://learn.microsoft.com/azure/databricks/jobs/alert))

**Recap:** SQL Alert = scheduled query + condition + notification; the DQ idiom is "return rows only when bad, alert on `COUNT > 0`"; it cannot use parameterized queries; templates' HTML only renders in email; and it has a job-task form for orchestration.

---

## S5.6 — Lakeflow Jobs notifications

Job/task notifications fire on run **events** and push to email or system destinations. ([Add notifications](https://learn.microsoft.com/azure/databricks/jobs/notifications))

**Event types you can subscribe to:** **Start**, **Success**, **Failure**, **Duration warning**, **Streaming backlog**. (Webhook `event_type` codes: `jobs.on_start`, `jobs.on_success`, `jobs.on_failure`, `jobs.on_duration_warning_threshold_exceeded`.)

**Destinations:** email, or **system destinations** = Slack, Microsoft Teams, PagerDuty, or generic **HTTP webhook**. **Only a workspace admin** can create system destinations (Admin settings → Edit system notifications → Create new destination). **Max 3 system destinations per event type per job/task.** ([third-party destinations](https://learn.microsoft.com/azure/databricks/jobs/notifications))

**Invisible behaviors — heavily exam-tested:**

1. **Job-level notifications are NOT sent on task retries.** A failing task that retries does not fire a job-level Failure each time — to alert on every failed attempt, configure **task-level** notifications. ([notifications](https://learn.microsoft.com/azure/databricks/jobs/notifications#configure-notifications-on-a-job))
2. **"Succeeded with failures" counts as Success**, not Failure. To be notified, subscribe to **Success**.
3. **Duration warning requires you to first set an expected-duration threshold** on the job/task (Metric thresholds → Run duration → Warning field). No threshold = no notification.
4. **Streaming backlog:** fires when the **10-minute average backlog** exceeds the threshold; then Databricks **waits 30 minutes** before re-notifying. Requires the Jobs service to track the streaming query — so **do not use `awaitTermination()`** in the job, or backlog tracking breaks. ([slow jobs](https://learn.microsoft.com/azure/databricks/jobs/notifications#configure-notifications-for-slow-jobs))
5. **Noise control:** "Mute notifications for skipped/canceled runs" and "Mute notifications until the last retry." Muting at the **job** level does **not** mute **task**-level notifications — you must mute both.
6. **Don't hard-code on message formatting:** Slack/Teams message content can change between releases; if you need a stable schema, use an **HTTP webhook**.

Example webhook payload (failure):

```json
{
  "event_type": "jobs.on_failure",
  "workspace_id": "your_workspace_id",
  "run": { "run_id": "run_id" },
  "job": { "job_id": "job_id", "name": "job_name" }
}
```

**SDP / materialized-view & streaming-table refresh notifications** are configured differently depending on how the refresh is scheduled: if scheduled **via a Job**, add notifications on the SQL task; if scheduled via a **`SCHEDULE` clause**, edit notifications in **Catalog Explorer → Overview → Refresh schedule** (by default the owner is notified **on failure only**). ([schedule refreshes](https://learn.microsoft.com/azure/databricks/ldp/dbsql/schedule-refreshes#get-notifications-for-scheduled-refreshes)) Lakeflow **Connect** ingestion pipelines auto-configure notifications you can customize. ([Connect notifications](https://learn.microsoft.com/azure/databricks/ingestion/lakeflow-connect/pipeline-maintenance#set-up-alerts-and-notifications))

**Recap:** subscribe to Start/Success/Failure/Duration-warning/Streaming-backlog; job-level notifications skip retries (use task-level); "succeeded with failures" = Success; duration/backlog need pre-set thresholds and backlog breaks under `awaitTermination()`; max 3 system destinations per event; muting is job-and-task separate.

---

## Common exam traps

> **Box of high-frequency gotchas. These are exactly the distractor patterns the exam uses.**

1. **System table ≠ alert.** A system table is passive (you query it). It never pushes a notification. Alerting requires a SQL Alert or Jobs notification sitting *on top*.
2. **`billing.usage` is global; almost everything else is regional.** To monitor another region's jobs/clusters/queries, run the query from a workspace in that region.
3. **`usage_quantity` is DBUs, not currency.** Currency needs the time-bounded join to `system.billing.list_prices`.
4. **All-purpose compute breaks per-job costing** — `usage_metadata.job_id` is null for it. Only job/serverless compute gives clean attribution.
5. **Long-run hourly slicing:** `result_state`/`termination_code` are non-null **only on the terminal row**. Filter `result_state IS NOT NULL` to count outcomes; `SUM(period_end - period_start)` for true duration.
6. **`compute.*` excludes serverless and SQL warehouses.** Those are `system.compute.warehouses` / `warehouse_events`.
7. **`query.history` excludes classic all-purpose clusters** — only warehouses + serverless notebooks/jobs.
8. **`statement_text` is `<Redacted>`** until an admin creates the case-sensitive `databricks_pii_access` group and adds the principal.
9. **No query profile for cached results** — bust the cache (tweak the `LIMIT`) to get one.
10. **Query Profiler is for SQL warehouses/serverless; Spark UI is for classic clusters.** Don't mix them.
11. **SQL Alerts can't use parameterized queries.**
12. **Job-level notifications don't fire on retries; "succeeded with failures" = Success; duration/backlog warnings need a pre-configured threshold.**
13. **Jobs API 2.2** is required for >100-task jobs (2.1 is capped at 100).
14. **`jobs submit` runs are unsaved, UI-invisible, and non-retryable** — never use them for things you must monitor.
15. **`workflow` schema == `lakeflow` schema** (identical content; legacy alias).
16. **Account-level audit events use `workspace_id = 0`.**

---

## Hands-on lab (run these in your own workspace)

> Goal: build a minimal end-to-end monitoring + alerting loop touching every S5 surface. Use a **serverless or pro SQL warehouse**. Prereq: ask an account admin to enable the `query` schema and grant you `SELECT` on the `system` schemas (or do it yourself if you're account admin).

**Step 1 — Verify system-table access.**
```sql
SELECT count(*) FROM system.billing.usage WHERE usage_date >= current_date() - 7;
SELECT count(*) FROM system.lakeflow.job_run_timeline WHERE period_start_time > now() - INTERVAL 7 DAYS;
SELECT count(*) FROM system.query.history WHERE start_time > now() - INTERVAL 1 DAY;
```
If any errors with "Table or view not found," that schema isn't enabled/granted — fix grants first.

**Step 2 — Cost attribution for your pipelines.** Adapt the `dlt_pipeline_id` join: rank your 422 SDP pipelines by 7-day DBU.
```sql
WITH p AS (
  SELECT * FROM system.lakeflow.pipelines
  QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC)=1
)
SELECT p.name, SUM(u.usage_quantity) AS dbus
FROM system.billing.usage u
JOIN p ON u.usage_metadata.dlt_pipeline_id = p.pipeline_id
WHERE u.usage_date >= current_date() - 7
GROUP BY p.name ORDER BY dbus DESC LIMIT 25;
```

**Step 3 — Failure forensics via CLI.** Pick a real job; pull its recent failed runs, open one, read the error.
```bash
databricks jobs list-runs --job-id <JOB_ID> --completed-only --output json \
  | jq '.runs[] | select(.state.result_state=="FAILED") | {run_id, start_time}'
databricks jobs get-run <RUN_ID> --output json | jq '.tasks[] | {task_key, state}'
databricks jobs get-run-output <RUN_ID>
```

**Step 4 — Query Profiler drill-down.** Find your slowest warehouse query (Step 1's `query.history`), copy its `statement_id`, open **Query History → paste statement_id → See query profile**. Check Top operators; toggle **Verbose mode**; look for a Scan with `pruned files` ≈ 0 (bad skipping) and any spill.

**Step 5 — SDP expectation metrics.** Pick one Apollo pipeline id and run the `event_log()` data-quality query from S5.4. Confirm `passed_records`/`failed_records`/`dropped` populate (they won't for `fail`-policy expectations).

**Step 6 — Build a data-quality SQL Alert.**
- New → Alert. Paste a "return count of bad rows" query (S5.5) against a real silver table.
- Pick your warehouse. Condition: aggregation `COUNT`, operator `GREATER_THAN`, threshold `0`.
- Schedule: every 15 min. Notifications: your email. Test condition → Save.

**Step 7 — Wire Jobs notifications + verify the retry trap.**
- On a test job, add a **task-level** Failure notification to your email and a **job-level** Failure notification.
- Force a task failure with a retry policy (e.g. retries=1). Observe: the **task-level** notification fires per attempt; the **job-level** one does not fire on the intermediate retry. That's trap #12 made concrete.

**Step 8 (optional) — System destination.** As workspace admin, Admin settings → add a Slack/webhook system destination, then route a job's Failure event to it. Confirm the webhook payload shape matches the `jobs.on_failure` JSON above.

---

## One-page recap table

| # | Surface | What it is | The one fact you must not miss |
|---|---|---|---|
| S5.1 | `system.billing.usage` | Global cost/usage fact | DBUs not $$ — join `list_prices`; no `job_id` for all-purpose |
| S5.1 | `system.access.audit` | Security audit ledger (Preview) | Account events use `workspace_id=0`; `request_params` is untyped |
| S5.1 | `system.compute.*` | Classic cluster config + utilization | **No** serverless/SQL-warehouse rows; `clusters`=SCD2, `node_timeline`=minute fact |
| S5.1 | `system.lakeflow.*` | Jobs + pipelines defs/timelines | Long runs are hour-sliced; `result_state` only on terminal row; `workflow`=`lakeflow` |
| S5.1 | `system.query.history` | SQL warehouse/serverless statements (Preview) | `statement_text` redacted unless `databricks_pii_access`; no classic clusters |
| S5.2 | Query Profiler | Visual DAG + metrics (DBSQL) | Cached query = no profile; need `CAN MONITOR`; insights `DATA_SPILL`/`EXCESSIVE_QUEUE_TIME` |
| S5.2 | Spark UI | Classic-cluster drill-down | Skew = Max > ~1.5× p75; check stage spill stats |
| S5.3 | REST/CLI | `jobs` + `pipelines` command groups | API 2.2 for >100 tasks; `repair-run` for partial re-run; `submit` runs are unsaved/invisible |
| S5.4 | SDP event log | Queryable Delta table via `event_log()` TVF | DQ in `flow_progress.data_quality`; `METRICS` rows are table-only; `fail` logs nothing |
| S5.5 | SQL Alerts | Scheduled query + condition + notify | No parameterized queries; DQ idiom = alert on `COUNT(bad) > 0`; HTML only in email |
| S5.6 | Jobs notifications | Start/Success/Failure/Duration/Backlog | Job-level skips retries (use task-level); succeeded-with-failures = Success; max 3 sys dests |

---

*All citations resolve to `learn.microsoft.com/azure/databricks` (Azure Databricks docs), verified current as of June 2026. AWS/GCP docs at `docs.databricks.com` carry equivalent schemas. Schemas in Public Preview (`access.audit`, `query.history`, `lakeflow.pipelines*`, `compute.instance_events`/`instance_pools`) can add columns — re-verify before relying on a specific column at exam time.*
