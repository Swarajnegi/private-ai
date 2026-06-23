# 05 — Debugging, Deploying & Data Sharing / Federation

> Databricks Certified Data Engineer Professional (exam objectives effective **Nov 30 2025**).
> Covers exam domains **S9 Debugging & Deploying (10%)** and **S4 Sharing & Federation (5%)**, with the directly-overlapping observability/cost material from **S5 (10%)** and **S6 (13%)** where it touches Spark UI, system tables, and query profiles.
> Grounded in current Azure Databricks docs (learn.microsoft.com/azure/databricks). URLs cited inline.
> **Audience note:** written for a strong DE (~1 YOE, Apollo Gen2 = 422 SDP pipelines). SDP / AUTO CDC / SCD2 / expectations / Auto Loader basics are assumed — this doc is the *gap* material around them: how to debug, deploy, and share what you already build.

---

## Why this matters (and the naming landmine)

S9 + S4 together are ~15% of the exam, and they are the domains most likely to trip up someone who is strong at *writing* pipelines but hasn't operated the full lifecycle: diagnose a failed run, repair only the broken tasks, ship via a bundle through CI/CD, and expose a table to a partner. S5 (monitoring) and S6 (cost/perf) lean on the same primitives (Spark UI, query profile, system tables), so mastering the debugging toolset pays double.

**The single biggest 2025/2026 vocabulary trap on this exam:**

| Old name (you'll still see it everywhere) | Current doc name | What changed |
|---|---|---|
| Databricks Asset Bundles (**DABs**) | **Declarative Automation Bundles** | Name only. `databricks bundle` CLI and all YAML are unchanged — non-breaking rename. ([faqs](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/faqs)) |
| Delta Live Tables (DLT) | **Lakeflow Spark Declarative Pipelines (SDP)** | The pipeline framework you run as Apollo Gen2. |
| Repos | **Git folders** | Visual Git client + Repos API. |
| Delta Sharing | **OpenSharing** (the protocol is now branded OpenSharing; "Delta Sharing" is still used for the product family) | D2D and D2O are sub-protocols. |
| Workflows / Jobs | **Lakeflow Jobs** | The orchestrator. |

The exam questions may use either name. Internalize the mapping; when in doubt, the *acronym* (DABs, DLT) is the legacy term and the *spelled-out Lakeflow/Declarative* form is current.

---

# Part S9 — Debugging & Deploying (10%)

## S9.1 Diagnose via Spark UI

**Spark UI** = the per-cluster web UI (Apache Spark's built-in monitoring server) that breaks a job into **jobs → stages → tasks** and shows I/O, shuffle, and memory metrics per stage. On classic compute you open it from **Compute → your cluster → Spark UI**. ([spark-ui-guide](https://learn.microsoft.com/azure/databricks/optimizations/spark-ui-guide/))

The doc's prescribed debugging walk is a fixed 5-step funnel — memorize the order, it maps to likely exam questions:

1. **Jobs Timeline** — find the major issue (gaps = driver-bound/scheduling, not compute).
2. **Longest stage** — sort stages by duration.
3. **Skew or spill** — the two cheapest wins.
4. **Is the longest stage I/O-bound?** — look at Input/Output/Shuffle Read/Shuffle Write columns.
5. **Other causes** of a slow low-I/O stage.

### Reading a stage: the two diagnoses that score points

**Spill** = Spark ran out of executor memory and started moving data from RAM to local disk. It is "invisible" in the sense that the job still *succeeds* — it just gets silently slow. You only see it if the stage page shows spill stats; **if there are no spill stats, the stage had no spill.** Most common during shuffle. ([long-spark-stage-page](https://learn.microsoft.com/azure/databricks/optimizations/spark-ui-guide/long-spark-stage-page))

**Skew** = one or a few tasks take far longer than the rest, wrecking cluster utilization. The exam's concrete heuristic, straight from the doc:

> Scroll to **Summary Metrics** on the stage page. Compare **Max** task duration to the **75th percentile**. **If Max is ≥ 50% higher than the 75th percentile, you likely have skew.** A healthy stage has 75th percentile ≈ Max.

**Execution trace — diagnosing a skewed join:**

```
Stage 14 (sortMergeJoin) — Summary Metrics, Duration:
  Min       2 s
  25th      3 s
  Median    4 s
  75th      5 s
  Max      71 s     <-- 71 is >> 1.5 x 5  => SKEW on one task
Shuffle Read: 75th = 40 MB, Max = 1.9 GB   <-- the hot task pulled a hot key
```

Remediation the exam expects you to name (in rough cost order):

```
1. Enable AQE (Adaptive Query Execution) — on by default in modern DBR;
   it coalesces post-shuffle partitions, flips sort-merge -> broadcast joins,
   and applies skew-join splitting at runtime.
2. broadcast() the small side to eliminate the shuffle entirely.
3. Key salting — append a random bucket to the hot key to spread it.
4. repartition() (shuffles, rebalances) vs coalesce() (no shuffle, only reduces).
```

Tune `spark.sql.shuffle.partitions` (default **200**) for shuffle-heavy stages. ([spark-monitoring-best-practices](https://learn.microsoft.com/fabric/data-engineering/spark-monitoring-best-practices))

> **Recap:** Spark UI funnel = Timeline → longest stage → skew/spill → I/O → other. Skew rule of thumb: Max ≥ 1.5× p75 task duration. Spill is silent — it succeeds but crawls.

---

## S9.2 Cluster logs

Cluster logs are *not* the Spark UI — they are the raw `stdout`/`stderr`/`log4j` files plus init-script output written to storage. The invisible behavior to call out: **by default these logs live only on the ephemeral cluster and vanish when it terminates.** To keep them you must configure **cluster log delivery** (Compute config → Logging → destination path). ([init-scripts/logs](https://learn.microsoft.com/azure/databricks/init-scripts/logs))

Once log delivery is on, paths are deterministic:

```
# Init-script logs (per container)
dbfs:/<cluster-log-path>/<cluster-id>/init_scripts/<cluster-id>_<container-ip>/
    <timestamp>_<log-id>_<init-script-name>.sh.stdout.log
    <timestamp>_<log-id>_<init-script-name>.sh.stderr.log

# Without log delivery configured, init logs are only at:
/databricks/init_scripts/        # readable from a %sh cell, gone on terminate
```

```bash
# List delivered init-script logs for a cluster
dbfs ls dbfs:/cluster-logs/1001-234039-abcde739/init_scripts
```

Two facts the exam likes:

- **A cluster-scoped init script that returns a non-zero exit code fails the entire cluster launch.** Troubleshoot it via cluster log delivery + the init-script log. ([cluster-scoped](https://learn.microsoft.com/azure/databricks/init-scripts/cluster-scoped))
- Init-script **start/finish events** (`INIT_SCRIPTS_STARTED`, `INIT_SCRIPTS_FINISHED`) appear in the **cluster event log** (Compute → cluster → Event log), but only for **one representative node**, not every node. The detailed per-container output is in the cluster *logs*, not the event log. ([init-scripts/logs](https://learn.microsoft.com/azure/databricks/init-scripts/logs))

For application logging inside notebooks/jobs: prefer **log4j** over `print()`. `print()` and Python's `logging` module run only on the **driver** and do **not** propagate to executor logs; log4j integrates with Spark's driver/executor log delivery. ([spark-best-practices-basics](https://learn.microsoft.com/fabric/data-engineering/spark-best-practices-basics))

```python
log4j = sc._jvm.org.apache.log4j.LogManager.getLogger("apollo.silver_ingest")
log4j.info("starting CDC merge for batch 2026-06-18")
log4j.error("schema drift detected on column event_ts")
```

> **Recap:** Cluster logs are ephemeral unless you enable cluster log delivery; init-script logs land under `<log-path>/<cluster-id>/init_scripts/`; a non-zero init script kills the launch; use log4j (not print) so executor logs are captured.

---

## S9.3 System tables

**System tables** = a read-only, Databricks-hosted analytical store of your account's operational data, living in the `system` catalog. **Requires Unity Catalog**; an account admin must enable each schema; you query them with plain SQL. ([system-tables](https://learn.microsoft.com/azure/databricks/admin/system-tables/))

The ones that appear on the exam (note retention and that several are still Public Preview):

| Table | Path | Use |
|---|---|---|
| Billable usage | `system.billing.usage` | Cost / DBU attribution. 365-day retention. |
| Pricing | `system.billing.list_prices` | SKU price history (× usage = $). |
| Audit logs | `system.access.audit` | Who did what (security/compliance). |
| Query history | `system.query.history` | Every query on SQL warehouses + serverless notebooks/jobs. |
| Clusters | `system.compute.clusters` | Slowly-changing history of compute configs. |
| Warehouse events | `system.compute.warehouse_events` | Start/stop/scale of SQL warehouses. |
| Job run timeline / task history | `system.lakeflow.*` | Job + pipeline run cost & duration. |
| Pipelines / pipeline update timeline | `system.lakeflow.pipelines`, `system.lakeflow.pipeline_update_timeline` | SDP runs and compute used. |

**Worked example — cost of one SDP pipeline (directly relevant to Apollo Gen2):**

```sql
SELECT
  sku_name,
  usage_date,
  SUM(usage_quantity) AS dbus
FROM system.billing.usage
WHERE usage_metadata.dlt_pipeline_id = '00732f83-cd59-4c76-ac0d-57958532ab5b'  -- from Pipeline Details tab
  AND usage_start_time >= '2026-06-01'
  AND usage_end_time   <  '2026-07-01'
GROUP BY ALL
ORDER BY usage_date DESC;
```

The `usage_metadata` struct is the join key for attribution: `dlt_pipeline_id`, `job_id`, `warehouse_id`, `schema_id`, etc. To turn DBUs into currency, join to `system.billing.list_prices` on `sku_name` + the price's effective date range. ([admin/usage/system-tables](https://learn.microsoft.com/azure/databricks/admin/usage/system-tables))

> **Recap:** System tables = UC-only `system` catalog, SQL-queryable operational history. `system.billing.usage` (+ `list_prices` for $), `system.query.history`, `system.access.audit` are the exam-critical three; attribute cost via the `usage_metadata` struct.

---

## S9.4 Query profiles

**Query Profile** = the per-query execution visualization for **SQL warehouses and serverless compute** (the equivalent of Spark UI for SQL). Open it from **Query History → click the query → See query profile**. It shows a **DAG (directed acyclic graph)** of operators on the right and summary metrics / **Top operators** on the left. ([sql/user/queries/query-profile](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))

What to look for (these are the S6 "find the bottleneck" answers):

- **Time spent / Rows / Memory peak** per operator — click a metric to recolor the DAG by it.
- **Exploding joins** — output rows ≫ input rows (a bad join condition).
- **Full table scans** — a Scan operator reading the whole table because **data skipping / file pruning failed** (no predicate pushdown, no clustering on the filter column).
- **Join type** — a `SortMergeJoin` where a `BroadcastHashJoin` would do means a small dimension wasn't broadcast.
- **Shuffle** — large exchange operators signal repartitioning cost.

Two silent behaviors to call out:

1. **A query profile is NOT available for queries served from the query cache** (Result Cache / Disk Cache). The UI shows "Query profile is not available." To force a profile, make a trivial change (e.g., tweak the `LIMIT`) to bust the cache. ([query-profile](https://learn.microsoft.com/azure/databricks/sql/user/queries/query-profile))
2. **Verbose mode is off by default** — some operators' metrics are hidden because they're "unlikely bottlenecks." Kebab menu → **Enable verbose mode** to see everything. You can also kebab → **Open in Spark UI** to drop into the lower-level view.

To view a profile you must own the query or have **CAN MONITOR** on the SQL warehouse.

> **Recap:** Query Profile = SQL/serverless DAG view; hunt exploding joins, full scans (failed skipping), sort-merge-that-should-broadcast, big shuffles. No profile for cached queries — bust the cache; turn on verbose mode for full metrics.

---

## S9.5 Job repairs + parameter overrides

This is the highest-yield S9 sub-topic. Two distinct mechanisms: **repair-run** (re-run only failed tasks of a *past* run) and **run-now with different parameters** (a fresh run with overrides).

### Repair run

After a multi-task job fails, **Repair run re-executes only the failed/skipped tasks and their dependents** — successful tasks and their downstream tasks are *not* re-run, saving time and compute. ([repair-job-failures](https://learn.microsoft.com/azure/databricks/jobs/repair-job-failures))

Exam-critical rules (each is a likely distractor):

- **Repair is only supported for jobs that orchestrate two or more tasks.** A single-task job cannot be repaired — you just re-run it. ([repair-job-failures](https://learn.microsoft.com/azure/databricks/jobs/repair-job-failures))
- Repaired tasks **use the *current* job/task settings**, not the settings from the original failed run. If you edit a notebook path or cluster config before repairing, the repair uses the new values.
- **If failed tasks shared a job cluster, the repair creates a *new* job cluster** (e.g., `my_job_cluster` → `my_job_cluster_v1`) so you can compare original vs repair compute.
- The **Duration** shown spans from the first run's start to the latest repair's finish (it's cumulative across all attempts).
- Repair decides what to re-run from each task's **run state**, not its disabled state. To force a *disabled* task to run during repair, include it in `rerun_tasks`.

**Parameter overrides during repair:** in the **Repair job run** dialog you can edit parameters; **values you enter override the existing values for this repair only.** To restore a parameter to its original value on a later repair, **clear both the key and value** in the dialog. ([repair-job-failures](https://learn.microsoft.com/azure/databricks/jobs/repair-job-failures))

**CLI:**

```bash
# Repair a finished (not in-progress) run by RUN_ID
databricks jobs repair-run 1234567890 \
  --rerun-all-failed-tasks \
  --rerun-dependent-tasks \
  --json '{"job_parameters": {"catalog": "prod", "mode": "full_refresh"}}'
```

Key flags: `--rerun-all-failed-tasks`, `--rerun-dependent-tasks` (also re-run previously-successful downstream tasks), `--latest-repair-id`. The run **must not be in progress.** ([cli/reference/jobs-commands](https://learn.microsoft.com/azure/databricks/dev-tools/cli/reference/jobs-commands))

### Run-now with parameter overrides

For a *fresh* run with different inputs (backfill, full refresh) use **Run now → run with different parameters**, or programmatically:

```json
// POST /api/2.2/jobs/run-now
{
  "job_id": 123,
  "job_parameters": { "catalog": "prod", "mode": "full_refresh" }
}
```

```bash
# Bundle CLI — double hyphens flag the values as job parameters
databricks bundle run my_job -- --catalog=prod --mode=full_refresh
```

**Precedence rule (frequently tested):** *Job parameters take precedence over task parameters.* If a job parameter and a task parameter share a key, **the job parameter wins.** ([job-parameters](https://learn.microsoft.com/azure/databricks/jobs/job-parameters))

**The bundle-variable gotcha (an exam-grade subtlety):** bundle variables (`${var.name}`) are resolved at **deploy time** and are **not** overridable at runtime. To make a value overridable on `run-now` without redeploying, **define it as a job parameter whose default is the bundle variable** — not as a `${var.name}` reference inside the task. ([bundles/job-parameters](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/job-parameters))

Notebook tasks read parameters via `dbutils.widgets.get("name")` — name must match exactly (case-sensitive).

> **Recap:** Repair re-runs only failed+dependent tasks (≥2-task jobs only), with current settings; repair-dialog params override for that repair, clear key+value to reset. Run-now params start a fresh run. Job params beat task params on key collision. Bundle vars are deploy-time, not runtime — wrap them in job parameters to override at run.

---

## S9.6 Debug SDP via event log + Spark UI

Apollo Gen2 is 422 SDP pipelines, so this is your home turf — the gap material is the *querying* of the event log, not the pipeline authoring.

The **event log** is the primary observability primitive for Lakeflow Spark Declarative Pipelines. **Every run writes structured records** covering execution progress, expectation (data-quality) results, lineage, and errors. It is itself a **Delta table** you can query. ([ldp/best-practices](https://learn.microsoft.com/azure/databricks/ldp/best-practices))

Access it three ways: **Pipeline UI** (Issues panel + Event log tab in the Lakeflow Pipelines Editor), **Pipelines API**, or **direct SQL** via the `event_log()` table-valued function (TVF).

```sql
-- TVF by pipeline ID (must run on a shared cluster or SQL warehouse)
SELECT * FROM event_log('<pipeline-id>')
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC
LIMIT 100;

-- Or by the table the pipeline owns
SELECT * FROM event_log(TABLE(my_catalog.my_schema.target_table));
```

TVF rules the exam tests:

- **Only the pipeline owner can call `event_log()`.**
- **You cannot query multiple pipelines' event logs in one call**, and a view created over the TVF **cannot be shared** with other users. ([ldp/live-schema](https://learn.microsoft.com/azure/databricks/ldp/live-schema))
- For **Hive metastore** pipelines (legacy), there's no TVF — the log is a Delta path: `/<storage>/system/events`, or default `/pipelines/<pipeline-id>/system/events` in DBFS. ([ldp/hive-metastore](https://learn.microsoft.com/azure/databricks/ldp/hive-metastore))

**Worked example — backpressure / streaming health from the event log:**

```sql
CREATE OR REPLACE TEMP VIEW event_log_raw AS SELECT * FROM event_log('<pipeline-id>');

SELECT
  timestamp,
  DOUBLE(details:flow_progress:metrics:backlog_bytes) AS backlog_bytes,
  DOUBLE(details:flow_progress:metrics:backlog_files) AS backlog_files
FROM event_log_raw
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC;
```

The `details` column is nested JSON — expectation pass/fail counts live there too, which is how you build a data-quality trend dashboard from a pipeline.

**Debugging "why did my materialized view fully refresh instead of incrementally?"** — query the event log for the most recent update's flow planning records. The `details` will carry one of the documented full-refresh reason codes. Memorize these because they're SDP-specific exam fodder ([ldp/monitor-event-log-schema](https://learn.microsoft.com/azure/databricks/ldp/monitor-event-log-schema)):

```
PLAN_NOT_DETERMINISTIC          - MV definition uses a non-deterministic function/operator
PLAN_NOT_INCREMENTALIZABLE      - an operator can't be maintained incrementally
EXPECTATIONS_NOT_SUPPORTED      - MV definition includes expectations (not incrementalizable)
ROW_TRACKING_NOT_ENABLED        - enable delta.enableRowTracking on base tables
QUERY_FINGERPRINT_CHANGED       - the MV definition (or SDP engine) changed
CONFIGURATION_CHANGED           - e.g. spark.sql.ansi.enabled flipped -> full recompute
TOO_MANY_FILE_ACTIONS / TOO_MANY_PARTITIONS_CHANGED  - churn exceeded incremental thresholds
INCREMENTAL_PLAN_REJECTED_BY_COST_MODEL  - full refresh judged cheaper
CHANGE_SET_MISSING              - first compute of the MV (expected)
```

**Event hooks** are Python functions that fire on pipeline events — use them for webhook/Slack/PagerDuty alerts on failure or expectation breach. ([ldp/event-hooks](https://learn.microsoft.com/azure/databricks/ldp/event-hooks))

For the lower level, SDP runs are still Spark jobs: the Lakeflow Pipelines Editor **Performance panel** surfaces query history + query profiles per flow, and you can open the underlying **Spark UI** for the pipeline's compute to chase skew/spill exactly as in S9.1. ([ldp/multi-file-editor](https://learn.microsoft.com/azure/databricks/ldp/multi-file-editor))

> **Recap:** SDP event log is a Delta table (`event_log()` TVF, owner-only, one pipeline per call); `flow_progress` rows carry backlog/throughput/expectation metrics in `details` JSON; full-refresh reason codes explain lost incrementalization; Performance panel + Spark UI cover query-level debugging.

---

## S9.7 Deploy with Declarative Automation Bundles (DABs)

A **bundle** is the end-to-end, YAML-defined, source-controllable definition of a project: infrastructure config + source files (notebooks, `.py`) + resource definitions (jobs, SDP pipelines, dashboards, model endpoints) + tests. **Recommended approach to CI/CD on Databricks.** ([dev-tools/bundles](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/))

The bundle root **must contain exactly one `databricks.yml`.** Minimal shape:

```yaml
bundle:
  name: apollo_silver

include:
  - resources/*.yml          # split resource defs into other files

targets:
  dev:
    mode: development        # default behaviors for iteration
    default: true            # used when -t is omitted
  prod:
    mode: production
    workspace:
      host: https://adb-prod.azuredatabricks.net
      root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}
    run_as:
      service_principal_name: <sp-app-id>
```

The **core workflow** (and the three commands you must know cold):

```bash
databricks bundle validate            # syntactically check databricks.yml
databricks bundle deploy -t dev       # push resources to the dev target workspace
databricks bundle run   -t dev my_job # run a deployed resource
```

### Deployment modes — the behavioral differences are heavily tested

`targets.<name>.mode` is `development` or `production`, and each sets a bundle of default behaviors. ([bundles/deployment-modes](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/deployment-modes))

| Behavior | `mode: development` | `mode: production` |
|---|---|---|
| Resource name prefix | `[dev ${user.short_name}]` prepended; jobs/pipelines tagged `dev` | none (optionally `name_prefix` via presets) |
| SDP pipelines | marked `development: true` | normal |
| Schedules & triggers | **paused** (so dev deploys don't fire on cron) | active |
| Concurrent runs | enabled (faster iteration) | per-config |
| Deployment lock | disabled | enabled |
| `--cluster-id` override | allowed (point all jobs at one interactive cluster) | not the intent |
| Editing resources in workspace | allowed | **disabled** |
| Validation requirement | lenient | requires explicit `host` + `root_path` unless `run_as` is a service principal |

That **schedules are paused in dev mode** is the classic gotcha: it prevents your development deploy from silently triggering production-cadence runs. ([bundles/deployment-modes](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/deployment-modes))

**Worked example — production preset that prefixes + tags everything:**

```yaml
targets:
  prod:
    mode: production
    presets:
      name_prefix: 'production_'
      tags:
        prod: true
```

### Bundle structure & best practices (S1 "scalable project structure")

- **Small, focused bundles over one mega-bundle.** One bundle per team/product, covering *all* environments (dev/staging/prod) as targets — not one bundle per environment. ([developers/best-practices](https://learn.microsoft.com/azure/databricks/developers/best-practices))
- Cross-bundle dependency (Bundle B needs Bundle A's outputs) is modeled in the **CI/CD/orchestration layer**, not by merging bundles.
- **Use Terraform only for external/cloud + admin resources** (workspace provisioning, networking). Use bundles for everything inside Databricks.
- **Custom bundle templates** encode org guardrails (permissions, cluster policies, tags, CI wiring); parameterize only what varies (project name, catalog, SP id, schedules) — keep guardrails fixed.

### Python wheels in bundles (S1 third-party libs)

A common CI pattern packages business logic into a **Python wheel** and deploys it via the bundle. The Jenkins/DevOps tutorials show a `dabdemo` package with `__init__.py`, `__main__.py`, `setup.py`, plus `pytest` tests (`test_addcol.py`) using `assertDataFrameEqual`. The bundle's `artifacts` mapping builds the wheel on deploy. ([ci-cd/jenkins](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/jenkins))

> **Recap:** A bundle = one `databricks.yml` + resources + source + tests; validate → deploy → run. Dev mode prefixes/tags resources, pauses schedules, disables locks; prod mode disables in-workspace editing and demands host+root_path (or SP run_as). Small per-team bundles spanning all envs; Terraform only for external infra.

---

## S9.8 Git-based CI/CD via Databricks Git folders

**Git folders** (formerly Repos) = a visual Git client + Repos REST API embedded in the workspace: clone, branch, commit/push, pull, diff, resolve conflicts on notebooks and files. ([repos/git-folders-concepts](https://learn.microsoft.com/azure/databricks/repos/git-folders-concepts))

Three flows you must distinguish:

1. **Admin flow** — admin creates **production Git folders** outside `/Workspace/Users/`, cloning a deployment branch (e.g., `main`). These should be **run-only for most users**; only admins + service principals can edit; kept in sync by automation. ([repos/ci-cd](https://learn.microsoft.com/azure/databricks/repos/ci-cd))
2. **User flow** — a developer creates a Git folder under `/Workspace/Users/<email>/`, works on a personal branch, pushes.
3. **Merge flow** — PR merged → automation (GitHub Actions etc.) pulls the change into the production Git folder via the Repos API.

**Worked example — scheduled-notebook sync (when no external CI/CD):**

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
w.repos.update(
    w.workspace.get_status(path="<git-folder-workspace-full-path>").object_id,
    branch="main",
)
```

### Git folders vs Bundles vs Git-with-jobs — the decision the exam asks

This is the one you must get right (the silent limitation is *what is and isn't source-controlled*):

| Approach | What's in source control | Use when |
|---|---|---|
| **Declarative Automation Bundles** (recommended) | **Everything** — code *and* job/pipeline config/infra as YAML | Full CI/CD, multi-environment, cross-workspace deploys |
| **Git folder** (production folder) | **Only code files** (notebooks, files). **Job/pipeline configs are NOT source-controlled.** | You only need to deploy code; works with external orchestrators (Airflow); no access to external CI/CD |
| **Git with jobs** (`git_source`) | **Only code files**; job takes a repo snapshot at run start. Job config (task sequence, compute, schedule) **not** versioned | Limited job task types; less suitable for multi-env |

So: if a question says "deploy jobs *and their configuration* across workspaces with full CI/CD," the answer is **bundles**; if it says "version only notebooks and let Airflow orchestrate," it's a **Git folder**. ([dev-tools/ci-cd](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/))

Databricks recommends a **trunk-based branching** strategy and **versioned artifacts** (Git commit hashes) on upload for traceability/rollback. The two patterns compose: author bundles *inside* a Git folder, commit, then a CI workflow runs `databricks bundle deploy` to the target workspace. ([dev-tools/ci-cd/flows](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/flows))

> **Recap:** Git folders = in-workspace Git client + API; production folders are admin-owned, run-only. Bundles source-control code **and config**; Git folders / Git-with-jobs source-control **code only**. Recommended: bundles authored in a Git folder, deployed by external CI on PR merge, trunk-based, commit-hash-versioned.

---

# Part S4 — Sharing & Federation (5%)

## S4.1 Delta Sharing — D2D and D2O

**Delta Sharing / OpenSharing** = Databricks' open protocol (donated to the Linux Foundation, `go.delta.io/sharing`) for secure, **live, zero-copy** data sharing across organizations and platforms — no data duplication, the recipient reads the provider's actual files. ([delta-sharing](https://learn.microsoft.com/azure/databricks/delta-sharing/))

Three flavors; the exam centers on the first two:

| Protocol | Provider | Recipient | Extra assets supported |
|---|---|---|---|
| **D2D (Databricks-to-Databricks)** | UC-enabled workspace | UC-enabled workspace (any account/cloud) | Notebooks, **volumes**, **models** — *D2D only*; full UC governance, auditing, usage tracking on both sides |
| **D2O (Databricks-to-Open)** | UC-enabled workspace | **Any platform** — Spark, pandas, Power BI, etc. (no Databricks needed) | Tabular data + views only |
| Open-source server | Any platform | Any platform | (not covered in Databricks docs) |

**Securable objects** in Unity Catalog (you'll be asked to name these):
- **Share** — a read-only collection of tables/volumes/views/notebooks/models you expose.
- **Recipient** — the entity you share *to*. In D2D the recipient is identified by their **metastore ID**; in D2O by a token/OIDC.
- **Provider** — in the recipient's metastore, the entity that shared the data.

### D2D workflow

```sql
-- Provider side
CREATE SHARE apollo_gold_share;
ALTER SHARE apollo_gold_share ADD TABLE prod.gold.daily_kpis WITH HISTORY;

-- Recipient identified by their metastore's sharing identifier (D2D => auth type DATABRICKS)
CREATE RECIPIENT partner_acme
  USING ID 'azure:eastus:12a3...';   -- recipient runs current_metastore() to get this
GRANT SELECT ON SHARE apollo_gold_share TO RECIPIENT partner_acme;
```

**History sharing (a performance fact the exam likes):** `WITH HISTORY` lets D2D table reads use temporary cloud credentials scoped to the table root, giving **performance comparable to direct source-table access.** On **DBR 16.2+ `WITH HISTORY` is the default**, and sharing a whole schema shares all tables with history. **Partitioned tables do NOT get the history-sharing performance benefit.** ([delta-sharing/share-data-databricks](https://learn.microsoft.com/azure/databricks/delta-sharing/share-data-databricks))

### D2O workflow

For D2O, the recipient is a **non-Databricks** consumer. Two auth methods:

1. **Bearer token** — provider generates a long-lived token + **activation URL**; recipient downloads a **credential file** (endpoint URL + token) and uses it from Spark/pandas/Power BI. ([delta-sharing/create-recipient-token](https://learn.microsoft.com/azure/databricks/delta-sharing/create-recipient-token))
2. **OIDC federation** — short-lived Databricks OAuth tokens exchanged for the recipient IdP's JWTs (no long-lived secret).

```sql
-- D2O: omitting the sharing identifier sets auth type = TOKEN, generating an activation link
CREATE RECIPIENT external_partner;        -- token-based
-- DESCRIBE RECIPIENT external_partner;   -- retrieve the activation link to send securely
```

```bash
# Rotate a leaked/expiring token; existing token expires in N seconds (0 = immediately)
databricks recipients rotate-token external_partner 0
```

Token / credential facts the exam tests ([create-recipient-token](https://learn.microsoft.com/azure/databricks/delta-sharing/create-recipient-token)):
- Recipient tokens are valid for **at most one year**.
- A recipient has **at most two tokens at once** (active + rotating). The credential file can be **downloaded only once**.
- If a token is compromised: **revoke share access → rotate with `--existing-token-expire-in-seconds 0` → resend the new activation URL over a secure channel.**
- **D2D providers (`DATABRICKS` auth) rotate automatically**; token/OIDC providers do not.

**Cloud-token / directory-based access (a 2026 detail with a security warning):** when eligible Delta tables are shared, Databricks can hand the recipient temporary cloud credentials scoped to the table's **root directory** so they read files directly. **This root scope grants read of the Delta *log* too — including commit history, committer identity, and deleted-but-unvacuumed data.** Vacuum and be deliberate about what's in history before sharing with `WITH HISTORY` / cloud tokens. ([create-share](https://learn.microsoft.com/azure/databricks/delta-sharing/create-share))

**Sharing limitations to remember:**
- Data must be **Delta or managed Iceberg** (convert Parquet via `CONVERT TO DELTA`).
- **Cannot share** tables with **table-level row filters or column masks**, `SHALLOW CLONE` tables, liquid-clustering-with-partition-filtering tables, or tables with collations.
- Tables with **ABAC** row filters/masks *can* be shared **only if the share owner is exempt** (in the policy's `EXCEPT` clause); the policy doesn't govern the recipient — recipients apply their own. ([abac/requirements](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/requirements))
- Sharing views/materialized views/streaming tables triggers **provider-side materialization = compute cost.**

> **Recap:** Delta Sharing = live zero-copy via OpenSharing. D2D (metastore-ID identified, adds notebooks/volumes/models, auto-rotating creds, `WITH HISTORY` default on DBR 16.2+). D2O (token or OIDC, activation URL → credential file downloadable once, ≤1-yr tokens, manual rotation). Can't share tables with table-level filters/masks; cloud-token access also exposes the Delta log/history.

---

## S4.2 Lakehouse Federation

**Lakehouse Federation** = Databricks' query-federation platform giving **governed, read-only** access to data in *external* systems through Unity Catalog **foreign catalogs**, with **automatic query pushdown** and table-level access control. You query live external data **without ingesting it.** ([query-federation](https://learn.microsoft.com/azure/databricks/query-federation/))

### Two types — and the difference is exam-tested

| | **Query federation** | **Catalog federation** |
|---|---|---|
| Query path | Pushed down to the foreign DB over **JDBC**; runs partly remote, partly on Databricks | Reads foreign tables **directly from object storage**; runs only on Databricks compute |
| Cost/perf | More network + remote compute | **More cost-effective & performance-optimized** (no remote engine) |
| Use case | Ad-hoc/PoC live access to operational DBs (Postgres, MySQL, Snowflake…) | Incremental UC migration / long-term hybrid (e.g., OneLake, federated Hive metastore) |
| Setup adds | connection + foreign catalog | connection + **storage credential + external location** + foreign catalog |

### Setup — three securables, then grants

```sql
-- 1. CONNECTION: a UC securable holding the server URL + credentials
CREATE CONNECTION postgres_conn TYPE postgresql
OPTIONS (
  host 'pg-demo.lb123.us-west-2.rds.amazonaws.com',
  port '5432',
  user 'pg_user',
  password 'secret'        -- prefer secrets; this is illustrative
);

-- 2. FOREIGN CATALOG: mirrors a remote database into UC, kept in sync
CREATE FOREIGN CATALOG pg_catalog USING CONNECTION postgres_conn
OPTIONS (database 'my_postgres_database');

-- 3. Govern + query with three-level UC names
GRANT USE CATALOG ON CATALOG pg_catalog TO `analysts`;
GRANT SELECT ON TABLE pg_catalog.public.orders TO `analysts`;
SELECT * FROM pg_catalog.public.orders WHERE region = 'APAC';
```

**Required privileges:** `CREATE CONNECTION` (metastore-level) to make the connection; `CREATE FOREIGN CATALOG` on the connection to register the catalog; then standard `USE CATALOG` / `USE SCHEMA` / `SELECT` for consumers. ([privileges-reference](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/privileges-reference))

### Governance & the read-only rule

Once registered, foreign catalogs behave like any UC securable — grant at catalog/schema/table level, and table-level **row filters/column masks/dynamic views** can govern them on the Databricks side.

**The hard rule:** **federated foreign tables are read-only.** The **only** exception is **catalog federation of a workspace's own internal/legacy Hive metastore**, where foreign tables are writeable. External Hive metastores and all query-federated sources are read-only. ([query-federation/database-federation](https://learn.microsoft.com/azure/databricks/query-federation/database-federation), [tables/foreign](https://learn.microsoft.com/azure/databricks/tables/foreign))

### Pushdown — what crosses the wire, and the silent failure mode

Databricks **pushes predicates/projections/limits/aggregates** down to the remote engine to fetch fewer rows. The invisible behavior: **if a predicate can't be translated to the remote dialect, it is silently dropped from the remote query and re-applied locally** — meaning the remote DB returns *more* rows than your `WHERE` implies. Mixed predicates joined by `AND` still push the translatable parts:

```sql
-- ILIKE has no remote translation; date comparison does.
SELECT * FROM pg_catalog.public.t
WHERE name ILIKE 'john' AND date > '2025-05-01';

-- Query actually sent to Postgres (ILIKE dropped, date kept):
--   SELECT * FROM catalog.schema.t WHERE date > '2025-05-01'
-- Name filtering then happens on Databricks.
```

**Verify pushdown** with `EXPLAIN FORMATTED`, or click the foreign-source Scan node in the **Query Profile**. ([query-federation/performance-recommendations](https://learn.microsoft.com/azure/databricks/query-federation/performance-recommendations))

Other federation facts/limitations:
- Queries are **read-only**; **Result Cache and Disk Cache do not apply** to federated queries (so `use_cached_result` is ignored).
- For each foreign table, Databricks runs a remote subquery and streams the result to **one** executor task — a too-large result can **OOM** that executor.
- Table/schema names are **lowercased** in UC; collisions are non-deterministic. Case-sensitive identifiers aren't supported for Synapse/Redshift.
- **Join pushdown** (Public Preview; GA for Redshift/Snowflake/BigQuery) pushes inner/left/right joins to the remote engine when all child nodes are pushable. ([query-federation/performance-recommendations](https://learn.microsoft.com/azure/databricks/query-federation/performance-recommendations))

When the source supports both Federation and **Lakeflow Connect** (managed ingestion), Databricks recommends **Lakeflow Connect** for high-volume / low-latency needs — federation is for *live ad-hoc* access, not bulk ETL.

> **Recap:** Lakehouse Federation = governed read-only foreign catalogs via UC (connection → foreign catalog → grant → query with 3-level names). Query federation pushes down over JDBC; catalog federation reads object storage directly (cheaper). Read-only except internal-Hive catalog federation. Non-pushable predicates are silently re-applied locally; verify with `EXPLAIN FORMATTED`; no caching; one-executor streaming can OOM on huge results.

---

## Common exam traps

> ⚠️ **Traps box — the answers graders bait you into getting wrong.**

1. **Repair vs re-run.** Repair only works on **multi-task (≥2)** jobs and re-runs **only failed/skipped + dependent** tasks with **current** settings. A single-task job has no repair.
2. **Repair param reset.** To reset an overridden parameter on the next repair, you must **clear both key and value** in the dialog — not blank the value.
3. **Job param vs task param.** On a key collision, the **job parameter wins.**
4. **Bundle variables are deploy-time.** They cannot be overridden at `run-now`. Wrap them as **job parameters** (with the var as default) for runtime overrides.
5. **Dev-mode schedules are paused.** Deploying a bundle in `mode: development` pauses schedules/triggers and prefixes resources `[dev ...]`. Production mode disables in-workspace editing.
6. **Git folder ≠ full CI/CD.** Git folders source-control **code only** — job/pipeline configs aren't versioned. Full config-as-code = **bundles**.
7. **Query profile not available?** The query hit the **cache**. Bust it with a trivial change. Verbose mode is off by default.
8. **Spill is silent.** The job succeeds; it's just slow. No spill stats on the stage = no spill.
9. **`event_log()` is owner-only, one pipeline per call**, and a view over it can't be shared.
10. **D2D vs D2O assets.** Notebooks, volumes, and models share **only over D2D**. D2O is tabular + views.
11. **Can't share filtered tables.** Tables with **table-level** row filters/column masks cannot be shared; ABAC-policy tables can be, only if the share owner is **EXCEPT**-exempt.
12. **Federation is read-only** — except catalog federation of an **internal** Hive metastore.
13. **Non-pushable predicate** → silently re-applied on Databricks; remote DB returns more rows than your filter implies.
14. **History sharing default** is `WITH HISTORY` on **DBR 16.2+**, but **partitioned tables get no perf benefit** from it.
15. **System tables need Unity Catalog** and per-schema admin enablement; cost attribution rides the `usage_metadata` struct.

---

## Hands-on lab (run in your own workspace)

Concrete, sequential steps. Use a **dev** target / scratch catalog; clean up at the end.

**Lab A — Repair a failing multi-task job**
1. Create a 3-task Lakeflow Job: `task_a` (ok) → `task_b` (a notebook that does `assert dbutils.widgets.get("mode") == "full"` — will fail with default) → `task_c` (depends on `task_b`).
2. Add a **job parameter** `mode` with default `incremental`. Run now → `task_b` and `task_c` fail/skip.
3. Open the failed run → **Repair run**. In the dialog, set `mode = full`. Observe only `task_b` + `task_c` re-run, both go green, and a new `..._v1` job cluster appears if they shared a job cluster.
4. Repeat with the CLI: `databricks jobs repair-run <run_id> --rerun-all-failed-tasks --rerun-dependent-tasks --json '{"job_parameters":{"mode":"full"}}'`.

**Lab B — Spark UI skew hunt**
1. Build a skewed join: a `df` where one key value has 10M rows, others have ~10. Join to a small dim.
2. Run on a classic cluster, open **Spark UI → SQL/Jobs → longest stage → Summary Metrics**. Confirm Max ≫ p75.
3. Wrap the small side in `broadcast()`, re-run, confirm the sort-merge stage disappears.

**Lab C — System tables cost query**
1. Find one of your SDP pipeline IDs (Pipeline Details tab).
2. Run the `system.billing.usage` query from S9.3 for the last 30 days; join `system.billing.list_prices` to get $.
3. Add a **SQL Alert** on the result so you're notified if daily DBUs exceed a threshold (ties to S5).

**Lab D — SDP event log**
1. Pick a pipeline you own. In SQL editor on a SQL warehouse: `CREATE OR REPLACE TEMP VIEW elr AS SELECT * FROM event_log('<id>');`
2. Query `event_type = 'flow_progress'` for backlog/throughput; query the most recent update's planning rows and look for a full-refresh reason code in `details`.

**Lab E — Deploy with a bundle**
1. `databricks bundle init` (default Python template) → inspect `databricks.yml` with `dev` (default) + `prod` targets.
2. `databricks bundle validate` → `databricks bundle deploy -t dev` → confirm the job appears prefixed `[dev <you>]` with schedule **paused**.
3. `databricks bundle run -t dev <job> -- --mode=full` to test a runtime param override. Then `databricks bundle destroy -t dev`.

**Lab F — Delta Sharing D2O (open)**
1. `CREATE SHARE lab_share; ALTER SHARE lab_share ADD TABLE <scratch.schema.table> WITH HISTORY;`
2. `CREATE RECIPIENT lab_open;` (no ID → token). `DESCRIBE RECIPIENT lab_open;` → copy the activation link.
3. Download the credential file once; read the table from a local pandas/`delta-sharing` client. Then `databricks recipients rotate-token lab_open 0` and confirm the old credential breaks.

**Lab G — Lakehouse Federation (if you have any external DB; else skip)**
1. `CREATE CONNECTION` to a Postgres/MySQL/another Databricks workspace.
2. `CREATE FOREIGN CATALOG ... USING CONNECTION ...`; `GRANT SELECT`; query with 3-level names.
3. Run a query with one pushable + one non-pushable predicate (`ILIKE`), then `EXPLAIN FORMATTED` to see what the remote query actually contains.

---

## One-page recap table

| Topic | The one thing to remember | Key syntax / path |
|---|---|---|
| Spark UI | Funnel: Timeline → longest stage → skew/spill → I/O. Skew = Max ≥ 1.5× p75. Spill is silent. | Compute → cluster → Spark UI |
| Cluster logs | Ephemeral unless **log delivery** configured; non-zero init script kills launch; log4j not print | `dbfs:/<log-path>/<cluster-id>/init_scripts/` |
| System tables | UC-only operational history; cost via `usage_metadata` | `system.billing.usage`, `system.query.history`, `system.access.audit` |
| Query Profile | SQL/serverless DAG; find exploding joins/full scans; none for cached queries | Query History → See query profile |
| Job repair | Re-runs only failed+dependent tasks (≥2-task jobs); current settings | `databricks jobs repair-run <id> --rerun-all-failed-tasks` |
| Param overrides | Job params beat task params; bundle vars are deploy-time | `run-now {job_parameters}`; `bundle run -- --k=v` |
| SDP debugging | Event log is a Delta table; `event_log()` owner-only, 1 pipeline/call; reason codes explain full refresh | `SELECT * FROM event_log('<id>') WHERE event_type='flow_progress'` |
| Bundles (DABs) | One `databricks.yml`; dev mode prefixes+pauses; prod disables editing | `bundle validate / deploy -t / run -t` |
| Git folders | Code only in source control; bundles version code **and** config | `w.repos.update(...)`; production folders run-only |
| Delta Sharing D2D | Metastore-ID identity; notebooks/volumes/models D2D-only; `WITH HISTORY` default DBR 16.2+ | `CREATE RECIPIENT ... USING ID ...`; `GRANT SELECT ON SHARE` |
| Delta Sharing D2O | Token or OIDC; activation URL → credential file (1 download); ≤1-yr tokens; manual rotation | `CREATE RECIPIENT x;` `databricks recipients rotate-token x 0` |
| Lakehouse Federation | Read-only foreign catalogs; query (JDBC pushdown) vs catalog (object-store, cheaper) federation | `CREATE CONNECTION` → `CREATE FOREIGN CATALOG` → `GRANT` |
| Federation pushdown | Non-pushable predicates silently re-applied locally; verify with `EXPLAIN FORMATTED`; no caching | `EXPLAIN FORMATTED SELECT ...` |

---

*Sources: all facts grounded in current Azure Databricks docs at learn.microsoft.com/azure/databricks — jobs/repair-job-failures, jobs/job-parameters, dev-tools/cli/reference/jobs-commands, dev-tools/bundles/* , dev-tools/bundles/deployment-modes, dev-tools/ci-cd/* , repos/ci-cd, repos/git-folders-concepts, admin/system-tables/* , admin/usage/system-tables, sql/user/queries/query-profile, optimizations/spark-ui-guide/* , init-scripts/logs, ldp/best-practices, ldp/observability, ldp/monitor-event-logs, ldp/monitor-event-log-schema, ldp/live-schema, ldp/multi-file-editor, delta-sharing/* , query-federation/* , data-governance/unity-catalog/* . Cited inline above.*
