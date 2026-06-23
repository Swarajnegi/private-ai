# Monitoring & Alerting — Practice MCQs (10%)

1. A platform lead must produce a monthly report of estimated list cost per job for the last 30 days, broken down by job, without enabling any third-party cost tool. They have access to the `system` catalog. Which approach correctly produces list-priced cost attributable to each job?
   - A. Query `system.billing.usage`, filter `usage_metadata.job_id IS NOT NULL`, and join to `system.billing.list_prices` on `sku_name` and the usage date range to multiply `usage_quantity` by the list price
   - B. Query `system.billing.usage` alone and sum `usage_quantity`, since that column is already denominated in the account's currency
   - C. Query `system.access.audit` for `runCommand` events and multiply the count of job runs by the DBU rate shown in the workspace pricing page
   - D. Read each job's `system.compute.node_timeline` CPU utilization and convert utilization percentages directly to dollars

2. A managed Delta table in Unity Catalog disappeared overnight and the team needs to identify which principal dropped it and when. No DESCRIBE HISTORY is possible because the table no longer exists. Which is the correct way to find the responsible identity?
   - A. Query `system.access.audit` filtering on `action_name = 'deleteTable'` and inspect `user_identity.email` and `event_time`, narrowing on `request_params.full_name_arg` for the table's full name
   - B. Restore the table with `RESTORE TABLE ... TO VERSION AS OF 0` and read the operation metrics from its Delta transaction log
   - C. Query `system.billing.usage` and look for a negative `usage_quantity` entry corresponding to the drop
   - D. Open the Query Profiler in Databricks SQL and search query history for a DROP TABLE statement

3. A Lakeflow Spark Declarative Pipeline defines an expectation `@dp.expect_or_drop("valid_id", "id IS NOT NULL")`. The team wants a scheduled query that tracks, per run, how many records each expectation dropped so they can alert on regressions. Which query against the pipeline event log gives the per-expectation pass/fail counts?
   - A. `SELECT timestamp, details FROM event_log('<pipeline-id>') WHERE event_type = 'flow_progress'` then parse the `details:flow_progress.data_quality.expectations` JSON for `passed_records`/`failed_records`
   - B. `SELECT * FROM event_log('<pipeline-id>') WHERE event_type = 'user_action'` and read the `message` column for dropped-row text
   - C. `DESCRIBE HISTORY <target_table>` and read the `operationMetrics.numDroppedRows` field
   - D. `SELECT * FROM system.access.audit WHERE action_name = 'expectationFailed'`

4. A daily Auto Loader job lands an orders table. The team wants an automatic notification only when more than 100 rows fail a freshness/null check. They build a query `SELECT count(*) AS bad_rows FROM orders WHERE order_ts IS NULL`. What is the correct way to operationalize the alert in Databricks SQL?
   - A. Create a Databricks SQL Alert on that query with a schedule, set the evaluation to compare the `bad_rows` source column against the threshold value `100` with operator `>`, and configure a notification destination
   - B. Wrap the query in a materialized view and rely on Unity Catalog to email owners when the view refreshes with non-zero rows
   - C. Add a `@dp.expect_or_fail` to the query so the SQL warehouse halts and pages on-call
   - D. Schedule the query in the SQL editor; Databricks automatically emails the query owner whenever any result row is returned

5. A DBSQL analyst reports a dashboard query is intermittently slow. The engineer opens the query profile and sees one operator with very high "bytes spilled to disk" values. Within the Query Profiler, what does this finding most directly indicate?
   - A. The operator ran low on memory and pushed intermediate data to disk; the engineer should reduce shuffle/skew or increase warehouse size to relieve memory pressure
   - B. Data skipping failed and the query scanned every file, which is unrelated to memory
   - C. Network egress charges were incurred because data left the region
   - D. The Delta table needs OPTIMIZE because spill is a symptom of too few small files

6. An engineer wants to diagnose a slow workload that is a Photon-backed Databricks SQL warehouse query. They are deciding which tool to open first. Which statement correctly distinguishes the Query Profiler from the Spark UI for this case?
   - A. The Query Profiler, opened from query history, visualizes per-operator metrics (time, rows, memory, spill) for the SQL query and is the right first stop; the Spark UI is still reachable for lower-level stage/task detail
   - B. The Spark UI is the only tool that can show SQL query operator metrics; the Query Profiler only shows cluster CPU graphs
   - C. The Query Profiler and Spark UI are the same UI under two names, so it does not matter which is opened
   - D. Neither tool applies to DBSQL; query performance for warehouses is only visible in `system.billing.usage`

7. An external orchestration service must poll Databricks to know whether a triggered job run has finished and whether it succeeded, without scraping the UI. Using the Jobs REST API Get-run endpoint, which combination of fields correctly determines completion and success?
   - A. Check that `state.life_cycle_state` is `TERMINATED` and `state.result_state` is `SUCCESS`
   - B. Call Get-run-output and treat any HTTP 200 as success regardless of the run state
   - C. Poll `system.billing.usage` until a usage record for the run appears, which means it succeeded
   - D. Check only `state.result_state`; `life_cycle_state` is irrelevant because `result_state` is populated the moment the run is submitted

8. A team wants to be alerted both when a critical job fails AND when an individual long-running task exceeds an expected runtime, using only native Databricks Jobs capabilities. Which configuration meets both needs?
   - A. Configure job-level notifications on failure plus a Duration Warning notification driven by the task/job expected-duration threshold, routed to email or a configured system notification destination
   - B. Add a `SELECT raise_error()` call at the end of the job so failures bubble up as exceptions to the workspace admin's inbox automatically
   - C. Rely on `system.access.audit` polling, since Databricks does not support runtime-duration alerts natively
   - D. Use a Databricks SQL Alert pointed at the job's notebook, because Jobs cannot send notifications on their own

9. Leadership asks for a trend of which scheduled jobs failed most often over the past quarter and their run durations, queryable in SQL and retained historically. Which source best satisfies this without standing up custom logging?
   - A. Query the Lakeflow jobs system tables (`system.lakeflow.job_run_timeline` joined to `system.lakeflow.jobs`) which record run terminations, result states, and timing across the account
   - B. Scrape the Jobs UI run list each day and store screenshots in a Delta table for later parsing
   - C. Use `DESCRIBE HISTORY` on each job's output table to infer failures from gaps in write versions
   - D. Query `system.billing.list_prices`, since price-change frequency correlates with job failures

10. An engineer suspects a recurring jobs-compute cluster is under-provisioned and wants minute-level CPU and memory utilization across its nodes to right-size it, queryable in SQL. Which system table provides this?
   - A. `system.compute.node_timeline`, which captures per-node resource utilization (`cpu_user_percent`, `mem_used_percent`, network) at minute granularity
   - B. `system.billing.usage`, which reports per-minute CPU percentages for each node
   - C. `system.access.audit`, which logs the cluster's memory pressure events
   - D. `system.compute.clusters`, which stores live per-minute utilization snapshots

11. A Lakeflow Declarative Pipeline run shows status "completed" but a downstream materialized view has far fewer rows than expected. The team wants to confirm, per flow, how many rows were actually written and whether expectations dropped records during that specific run. What is the most direct way to investigate?
   - A. Query the pipeline event log for `flow_progress` events and inspect the `details` JSON for `num_output_rows` and the expectation `dropped_records`/`failed_records` metrics for that run
   - B. Open the SQL Alerts page; a successful pipeline run guarantees row counts so the discrepancy must be a UI caching bug
   - C. Run `OPTIMIZE` on the materialized view to materialize the missing rows
   - D. Check `system.billing.list_prices` to see whether a pricing change throttled the pipeline's writes

12. In the Query Profiler for a slow query over a large Delta table, the engineer sees the scan operator reports "files read: 12,500" and "rows read: 4.1B" while the query has a selective `WHERE region = 'APAC'` predicate that should match a small fraction. Within the monitoring/diagnosis workflow, what does this profile most directly reveal?
   - A. Data skipping/file pruning is ineffective for this predicate (e.g. poor data layout for `region`), so the scan reads far more files than necessary — a layout/clustering problem surfaced by the profile
   - B. The warehouse is spilling to disk, which is why so many files are read
   - C. The join strategy chose a broadcast join, which forces a full file scan
   - D. The audit log retention is too short, inflating the file count shown in the profile

---

## Answers & Explanations

1. **A** — `system.billing.usage` records DBU `usage_quantity` and attributes it via `usage_metadata.job_id`, but it carries no dollar amounts. List cost is derived by joining to `system.billing.list_prices` (a SKU price-change log) on `sku_name` for the matching effective date and multiplying. The docs' "Which jobs consumed the most DBUs?" sample filters `usage_metadata.job_id IS NOT NULL`, and the "Join the pricing with usage tables" sample does exactly this join. B is wrong because usage is in DBUs, not currency. C uses the audit table, which records actions not consumption. D conflates utilization with billing; `node_timeline` carries no pricing. *(Objective: S5 — system tables for cost observability)*

2. **A** — `system.access.audit` is the audit log surfaced as a system table; per the Diagnostic log reference, the `deleteTable` action ("User deletes a table") records the acting `user_identity` and `event_time`, with `request_params.full_name_arg` holding the table's full name. B fails because the table is gone — there is no transaction log to restore from, and history wouldn't name the principal. C is nonsense: billing records consumption, not DDL. D only covers DBSQL query history (a managed-table drop may come from a notebook/job/API) and the Query Profiler is for performance analysis, not who-did-what auditing. *(Objective: S5 — system tables for audit observability)*

3. **A** — Expectation metrics are emitted in `flow_progress` events; per the Pipeline event log docs, per-expectation `passed_records`/`failed_records` live in `details:flow_progress.data_quality.expectations`, and the dropped count in `details:flow_progress.data_quality`. Querying `event_log('<pipeline-id>')` and parsing that JSON is the documented pattern. B targets the wrong event_type — `user_action` records pipeline operations (START/CREATE), not data quality. C: DESCRIBE HISTORY exposes Delta write metrics, not per-expectation drops. D: there is no `expectationFailed` audit action; expectation results live in the pipeline event log. *(Objective: S5 — SDP event logs for data-quality observability)*

4. **A** — Per the "Create an alert" docs, a Databricks SQL Alert runs a query on a schedule and notifies when a defined condition is met against the result. In the alerts-v2 evaluation model you choose a **source** column (`bad_rows`), a **comparison operator** (`>`), and a **threshold** value (`100`), and attach a notification destination. B: materialized views don't send threshold-based notifications. C: `@dp.expect_or_fail` is a pipeline (SDP) construct, not honored by a standalone SQL warehouse query. D: scheduling a query alone sends no notifications — alerting requires an Alert object with a condition. *(Objective: S5 — SQL Alerts for data quality)*

5. **A** — In the query profile, spill ("bytes spilled to disk") means the operator exceeded available memory and moved intermediate data to disk — expensive and most common during shuffles/skew (per the Skew and spill guide). The remedy is reducing shuffle volume/skew or giving the warehouse more memory (the `DATA_SPILL` performance insight recommends increasing warehouse size or reducing rows/columns). B describes a different symptom (high files-read from poor pruning), shown elsewhere in the profile. C invents a billing concept the profile doesn't report. D inverts the relationship: spill comes from execution-time memory pressure, not small-file count; OPTIMIZE addresses scan efficiency, not spill. *(Objective: S5 — Query Profiler UI for query bottleneck diagnosis)*

6. **A** — For a DBSQL/Photon query, the Query Profiler (reached via Query History) is the purpose-built tool: per the Query profile docs it renders the plan as operators with per-operator time, rows processed, and memory consumption, and lets you identify the slowest part at a glance. The Spark UI remains available for stage/task-level drill-down. B inverts their roles. C is false — they are distinct tools at different abstraction levels. D is wrong; billing system tables show consumption, not query execution detail. *(Objective: S5 — Query Profiler UI vs Spark UI scope)*

7. **A** — A run's lifecycle is tracked by `state.life_cycle_state` (PENDING/RUNNING/TERMINATING/TERMINATED/INTERNAL_ERROR/SKIPPED); the CLI's `--no-wait`/`--timeout` flags confirm `TERMINATED` (or `SKIPPED`) is the terminal completion state. Only once terminal is `state.result_state` (SUCCESS/FAILED/CANCELED) meaningful, so you check both. B is wrong: Get-run-output returns notebook exit values and HTTP 200 doesn't imply job success. C uses billing as an orchestration proxy — usage can be recorded for failed runs and lags. D is wrong because `result_state` is only populated once the run reaches a terminal lifecycle state. *(Objective: S5 — REST API / CLI for monitoring job runs)*

8. **A** — Per the "Add notifications on a job" docs, Jobs support native notifications on Start, Success, Failure, and **Duration warning** (triggered when a run/task exceeds its configured expected-duration threshold), plus timeouts. Notifications route to email or system destinations (Slack/Microsoft Teams/PagerDuty/webhook). A covers both requirements. B is a hack and `raise_error` emails no one. C is false — duration thresholds are a built-in Jobs feature. D is false — Jobs send their own notifications; a SQL Alert evaluates query-result conditions, not job-run events. *(Objective: S5 — Jobs UI/API notifications)*

9. **A** — The Lakeflow jobs system tables expose job and run-timeline data: `system.lakeflow.job_run_timeline` carries `result_state` (SUCCEEDED/FAILED/TIMED_OUT/…) and start/end timing, and joins to `system.lakeflow.jobs` (SCD) for the job name — queryable Delta with 365-day retention, ideal for failure-rate and duration trending. B is manual and lossy. C infers failures indirectly and breaks for jobs without a single output table or with idempotent writes. D is irrelevant — `list_prices` tracks SKU pricing, not job outcomes. *(Objective: S5 — system tables for workload observability)*

10. **A** — Per the Compute system tables reference, `system.compute.node_timeline` records node-level utilization (`cpu_user_percent`, `cpu_system_percent`, `cpu_wait_percent`, `mem_used_percent`, network) at minute granularity for all-purpose and jobs compute — exactly the signal for right-sizing (caveat: nodes that ran under ~10 minutes might not appear, and serverless/SQL warehouses are excluded). B is wrong: `billing.usage` carries DBU consumption, not utilization percentages. C is the audit log (actions, not resource metrics). D: `system.compute.clusters` is an SCD configuration inventory of cluster definitions, not a utilization time-series. *(Objective: S5 — system tables for compute/resource observability)*

11. **A** — The pipeline event log's `flow_progress` events carry per-flow output metrics (`num_output_rows`, upserted/deleted) and data-quality results (`dropped_records`/`failed_records`) for each run — the precise place to see how many rows a flow wrote and how many expectations removed. A "completed" run with `expect_or_drop` expectations can legitimately drop rows, which the event log reveals. B is false reasoning. C: OPTIMIZE only compacts files — it cannot create rows. D: pricing changes don't throttle writes and aren't recorded as row counts. *(Objective: S5 — SDP event logs for pipeline run diagnosis)*

12. **A** — A high "files read" / "rows read" on the scan operator despite a selective predicate is the classic Query-Profiler signature of ineffective data skipping/file pruning — the data layout doesn't co-locate `region` values, so per-file min/max stats can't prune. The fix is layout (e.g. liquid clustering on `region`). B confuses scan volume with memory spill (a different operator metric). C: broadcast joins affect join-side data movement, not the scan's file-pruning. D is fabricated — audit retention has nothing to do with files-read metrics in a query profile. *(Objective: S5 — Query Profiler for diagnosing poor data skipping)*
