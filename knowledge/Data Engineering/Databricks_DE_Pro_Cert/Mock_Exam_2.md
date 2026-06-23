# Databricks Certified Data Engineer Professional — FULL MOCK EXAM #2

> 59 questions, weighted to the official Nov 30 2025 objectives. Completely fresh scenarios — no overlap with Mock #1 or the per-topic MCQ bank.
> Distribution: Developing Code 13 · Cost & Performance 8 · Monitoring & Alerting 6 · Transform/Quality 6 · Security & Compliance 6 · Debugging & Deploying 6 · Data Ingestion 4 · Governance 4 · Data Modelling 3 · Sharing & Federation 3.
> Single best answer. Answer key with explanations follows the questions.

---

## Developing Code (Q1–Q13)

1. A data team's Databricks Asset Bundle (DAB) keeps the same `databricks.yml` config but must deploy to a `dev` target (per-developer sandbox, prefixed resource names, paused schedules) and a `prod` target (shared, real schedules, service-principal run-as) from one repo. Which DAB mechanism is purpose-built for this single-source, multi-environment behavior?
   - A. Define `targets` with `mode: development` and `mode: production` presets; the presets auto-apply the dev prefixing/pausing and the prod validation/scheduling
   - B. Maintain two separate `databricks.yml` files, one per environment, and switch between them with a shell alias
   - C. Put the prod values in environment variables and run `databricks bundle deploy` twice with different `export`s
   - D. Use a single target and rely on Git Folders to check out a different branch per environment

2. An engineer wants a DAB to build the team's Python source into a wheel and install that wheel on the job's compute as part of every deploy, so tasks import the packaged code rather than `%run`-ing notebooks. Which bundle construct does this?
   - A. The `artifacts` mapping with `type: whl`, referenced from the job task's `libraries` as `whl: ./dist/*.whl` — `bundle deploy` builds and uploads the wheel and installs it
   - B. A `for_each_task` that pip-installs each module file at runtime
   - C. The `sync` block, which compiles `.py` files into a wheel automatically on deploy
   - D. Setting `mode: production`, which bakes all `src/` modules into the runtime image

3. A scalar Python UDF computes a SHA-256 hash of an email column over 4 billion rows and dominates job runtime. The logic is a pure string transform with no third-party deps. What is the most performant correct replacement?
   - A. Use the built-in `sha2(email, 256)` Spark SQL function — native (JVM/Catalyst) execution avoids the per-row Python serialization the UDF pays
   - B. Wrap the same Python logic in a Series→Series `@pandas_udf` to keep the Python code but vectorize it
   - C. Mark the UDF `@udf(useArrow=True)` so it runs inside Catalyst as native code
   - D. Cache the UDF results with `@functools.lru_cache` so duplicate emails are hashed once

4. A Lakeflow Spark Declarative Pipeline (SDP) ingests JSON files landing continuously and must process each file exactly once with low latency, while a downstream gold table must always reflect a fresh full re-aggregation of that data and be queryable as a normal table. Which dataset-type pairing is correct?
   - A. Bronze ingest → streaming table (incremental, each file once); gold aggregation → materialized view (reflects current source state on refresh)
   - B. Bronze ingest → materialized view; gold aggregation → streaming table
   - C. Both → streaming tables, because materialized views can't be queried as tables
   - D. Both → materialized views, because streaming tables can't do low-latency ingest

5. A source delivers an ordered CDC feed with `op` (I/U/D) and a `sequence_num`, but records sometimes arrive out of order and a few are hard deletes. The team must maintain a current-state SCD Type 1 target in SDP without writing MERGE. Which construct fits?
   - A. `AUTO CDC` / `APPLY CHANGES INTO` with `KEYS (...) SEQUENCE BY sequence_num`, `APPLY AS DELETE WHEN op = 'D'`, `STORED AS SCD TYPE 1` against a streaming-table target
   - B. A materialized view over the feed — MV refresh dedupes by key automatically
   - C. `AUTO CDC FROM SNAPSHOT`, since any CDC feed is treated as a snapshot
   - D. A `foreachBatch` MERGE inside a Structured Streaming job, the only supported path in SDP

6. A team needs a custom streaming sink that writes each micro-batch to an external REST service with their own retry/idempotency logic, plus manual control of the checkpoint location and a 30-second processing-time trigger, as a standalone job. Which approach is correct?
   - A. Use Spark Structured Streaming directly with `writeStream.foreachBatch(...)`, an explicit `checkpointLocation`, and `Trigger.ProcessingTime("30 seconds")` — SDP abstracts checkpoints/orchestration away from you
   - B. Use an SDP materialized view, since `foreachBatch` is an MV refresh policy
   - C. Use an SDP streaming table, since custom external sinks are only allowed inside declarative pipelines
   - D. Use a Jobs `for_each_task`, since `foreachBatch` is implemented as a job-level loop

7. A pytest module factors transforms as DataFrame→DataFrame functions and chains them. The test asserts only that column names and types match an expected schema, regardless of row data, because the data fixture is large. Which PySpark testing utility is the right tool?
   - A. `assertSchemaEqual(actual.schema, expected.schema)` — compares schemas only, not row data
   - B. `assertDataFrameEqual(actual, expected)`, which by default ignores data and checks only schema
   - C. `DataFrame.transform`, which raises if the schema diverges
   - D. `assertDataFrameEqual(actual, expected, checkRowOrder=True)` to force a schema-only comparison

8. An engineer uses `DataFrame.transform` to compose `df.transform(add_keys).transform(dedupe).transform(enrich)`. A reviewer asks why this is preferred over nesting calls like `enrich(dedupe(add_keys(df)))`. What is the correct rationale?
   - A. `DataFrame.transform` applies a DataFrame→DataFrame function and returns a DataFrame, enabling readable left-to-right chaining of independently unit-testable steps; it does not change execution semantics
   - B. `DataFrame.transform` forces each step to execute eagerly, which is faster
   - C. `DataFrame.transform` parallelizes the three functions across executors
   - D. `DataFrame.transform` caches intermediate DataFrames automatically between steps

9. A serverless notebook task loads a large model object and runs heavy single-node pandas post-processing on the driver, intermittently failing with driver-side `MemoryError`. The Spark stages are fine. What's the correct, minimal fix?
   - A. Set the task's Environment memory to **High (32 GB)** — it raises REPL/driver Python memory, which is what the single-node pandas work consumes; it does not change Spark executor/session memory
   - B. Increase `spark.executor.memory`, since driver pandas runs on executors
   - C. Enable deletion vectors to shrink the data the driver materializes
   - D. Disable serverless auto-optimization so the task stops retrying the OOM

10. A team installs a third-party library two ways and sees different behavior. With `%pip install pkg==1.2` in the first notebook cell, every notebook on the shared cluster suddenly fails an `import` of an unrelated package. What explains this, and the safer alternative?
   - A. A notebook-scoped `%pip install` restarts the Python interpreter for that notebook and can change the shared environment; for reproducible isolation, pin deps in the job/serverless environment (or use cluster libraries deliberately) rather than ad-hoc `%pip` on shared compute
   - B. `%pip` installs are Maven-only and corrupt PyPI packages; switch to the cluster Libraries tab which is PyPI-only
   - C. `%pip` writes to DBFS root, which all clusters share by design; move the install to `/tmp`
   - D. `%pip` requires `STRICT ISOLATION`; enable it and the conflict disappears

11. A CI pipeline must, on every merge to `main`, deploy a multi-task ETL job (tasks, dependencies, schedule, cluster spec) reproducibly to a staging workspace and then trigger one run to validate. Which combination is the Databricks-recommended path?
   - A. Define the job under `resources.jobs` in a DAB, run `databricks bundle deploy -t staging` then `databricks bundle run <job>` in the CI step
   - B. Use the Jobs `runs/submit` REST endpoint in CI, which persists the versioned job + schedule in Git automatically
   - C. Click-build the job in the staging Jobs UI and commit screenshots as the spec
   - D. Sync the repo with a Git Folder; schedules and cluster specs version with the code

12. An SDP pipeline must run a different downstream branch depending on whether an upstream validation step found any quarantined rows. The pipeline is orchestrated by a Lakeflow Job. Which control-flow construct evaluates the condition and branches?
   - A. An **If/else condition task** in the job, reading the upstream task value (e.g. `{{tasks.validate.values.bad_count}}`) with a numeric operator like `> 0`
   - B. A `for_each_task` over the quarantine rows, which inherently branches
   - C. An SDP expectation with `ON VIOLATION FAIL UPDATE`, which routes to the alternate branch
   - D. Setting the branch task's `Run if` to "All succeeded", which branches on the value

13. A job task appends rows with a non-idempotent `INSERT` and must never double-write on transient retries; the team needs strict at-most-once. The task runs on serverless. Which configuration enforces this?
   - A. In the task's **Retry Policy** dialog, uncheck **"Enable serverless auto-optimization (may include additional retries)"** so the silent extra retries are disallowed
   - B. Set `spark.task.maxRetries = 0` in the notebook
   - C. Switch the deploy target to `mode: production`, which disables retries
   - D. Lower `spark.sql.shuffle.partitions` so each insert is atomic

---

## Cost & Performance (Q14–Q21)

14. A platform team manages 400+ Unity Catalog **managed** Delta tables and wants Databricks to handle OPTIMIZE/VACUUM/ANALYZE automatically based on usage, eliminating their hand-scheduled maintenance jobs. What should they enable?
   - A. **Predictive optimization** on the catalog/schema, so Databricks runs OPTIMIZE, VACUUM, and statistics maintenance on managed tables when beneficial
   - B. Convert the tables to external and orchestrate maintenance externally to cut cost
   - C. Disable statistics collection so writes are cheaper and reads rely on caching
   - D. Set the warehouse to auto-scale so OPTIMIZE finishes faster

15. A high-write table receives thousands of small `DELETE FROM t WHERE id = ?` statements per hour; each rewrites large Parquet files for one changed row. Which feature removes this write amplification by marking rows deleted in a side file instead of rewriting whole files?
   - A. **Deletion vectors** — DELETE/UPDATE/MERGE soft-mark affected rows; the data file is rewritten lazily during later OPTIMIZE
   - B. ZORDER on `id` so all targeted rows colocate into one cheaply-rewritten file
   - C. Lowering `delta.targetFileSize` so every file is tiny and cheap to rewrite
   - D. Partitioning by `id` so each delete touches only one directory

16. A fact table is partitioned by `event_date`, but queries now filter mostly by `tenant_id` and `country`, causing skew and small files. The team wants a layout that adapts to new filters and can be re-tuned later **without rewriting all existing data**. Best choice?
   - A. Enable **liquid clustering** `CLUSTER BY (tenant_id, country)`; keys can be changed later via `ALTER TABLE` and only future writes/OPTIMIZE reorganize, with no full rewrite
   - B. Re-partition by `tenant_id`
   - C. Keep date partitions and add `ZORDER BY (tenant_id, country)`
   - D. Sub-partition by `(event_date, country)`

17. `SELECT * FROM txns WHERE amount > 10000` over a large Delta table reads ~all files; the query profile shows **"files pruned: 0"** and full-table bytes read. The predicate column has no clustering/partitioning. Which change most directly enables file pruning?
   - A. Add liquid clustering on `amount` (or ZORDER) so per-file min/max stats align with the predicate and files whose range can't match are skipped
   - B. Cache the table in warehouse memory
   - C. Replace `SELECT *` with explicit columns to enable pruning
   - D. Increase warehouse size to finish the scan faster

18. A downstream Delta table must stay in sync with an upstream Delta table that receives inserts, updates, and deletes. A plain `spark.readStream` on the upstream throws on the UPDATE/DELETE commits (Structured Streaming expects append-only by default). What's the correct low-latency fix?
   - A. Enable **Change Data Feed (CDF)** on the upstream and read its change feed (`readChangeFeed=true`), applying `insert`/`update_postimage`/`delete` change types to the target
   - B. Add `.option("skipChangeCommits","true")` so deletes are emitted as removal events the target applies
   - C. Use `Trigger.AvailableNow` and full-overwrite the target every micro-batch
   - D. Convert the upstream to a materialized view so deletes propagate to readers automatically

19. A point lookup `WHERE device_id = 'X12'` on a very wide table scans every file (`files pruned: 0`) even though `device_id` is a clustering key and the table was just OPTIMIZEd. `device_id` is the 90th column. What's the cause and fix?
   - A. Delta collects min/max stats only on the first **32** columns by default; `device_id` is past that boundary, so no skipping stats exist. Move it into the leading columns or raise `delta.dataSkippingNumIndexedCols` / set `delta.dataSkippingStatsColumns`, then re-run OPTIMIZE
   - B. Switch `device_id` to a partition column so directory pruning replaces stats
   - C. Add a secondary B-tree index on `device_id`
   - D. Increase warehouse size; wide tables can't do data skipping

20. The query profile for a join between a 3-billion-row fact and a 2,000-row dimension shows a **SortMergeJoin** with very large shuffle bytes on both sides and heavy time in exchange operators. The dimension fits easily in memory. What does this indicate and the fix?
   - A. The optimizer didn't broadcast the tiny dimension; broadcast the small side (e.g. `broadcast(dim)` / ensure it's under the broadcast threshold) to avoid shuffling the fact table
   - B. Add ZORDER on the join key so the sort phase is skipped
   - C. Collect stats on the dimension to enable file pruning during the join
   - D. Run OPTIMIZE on both tables so fewer files reduce the shuffle

21. A streaming table feeding analytics has growing end-to-end latency, and an audit shows downstream consumers each re-scan the whole streaming table to detect what changed. Which feature directly addresses this row-level-change latency limitation?
   - A. Enable **Change Data Feed** so consumers read only the row-level changes (`table_changes`) instead of full re-scans, lowering latency and cost
   - B. Increase the trigger interval so fewer micro-batches run
   - C. Convert the streaming table to a materialized view
   - D. Disable deletion vectors to speed reads

---

## Monitoring & Alerting (Q22–Q27)

22. A FinOps lead must attribute last month's DBU spend by workspace, SKU, and custom cost-center tag, joining usage to list prices, all in SQL with no extra tooling. Which system tables support this?
   - A. `system.billing.usage` joined to `system.billing.list_prices` (with `custom_tags` on usage rows for cost-center attribution)
   - B. `system.compute.clusters` joined to `system.access.audit`
   - C. `system.query.history` joined to `system.lakeflow.jobs`
   - D. `system.information_schema.tables` joined to `system.billing.usage`

23. A security team needs an authoritative, queryable record of *who accessed which table and when*, including failed access attempts, retained centrally for audit. Which system table is authoritative?
   - A. `system.access.audit` — the audit-log system table capturing account/workspace actions including data access events
   - B. `system.billing.usage`
   - C. `system.compute.warehouses`
   - D. `system.query.history`

24. An engineer wants to find why one SQL query in a dashboard is slow: which operator dominates, whether data skipping failed, the join type chosen, and where shuffle/spill happens. Which Databricks tool is the right starting point?
   - A. The **Query Profile** UI for that query (graph + per-operator metrics: rows, bytes read, pruning, join type, shuffle, spill)
   - B. The cluster's Ganglia/metrics tab
   - C. `system.billing.usage`
   - D. The DAB deployment logs

25. A team must alert when a daily SDP table's null-rate on a critical column exceeds 1%, sending a Slack/email notification automatically on a schedule. Which Databricks feature fits with least custom code?
   - A. A **Databricks SQL Alert** on a scheduled query that computes the null-rate, with a threshold condition and notification destination
   - B. A Spark UI watcher that polls stage metrics
   - C. A `for_each_task` that emails per row
   - D. An SDP expectation alone, since expectations send Slack messages

26. A platform team wants to monitor a running pipeline's update status, recent events, and data-quality metric outcomes programmatically from CI, without opening the UI. Which sources are correct?
   - A. The **SDP event log** (queryable, exposes `flow_progress`/expectation metrics) plus the **Pipelines REST API / CLI** for update status
   - B. Only the Spark UI, since pipeline status isn't exposed via API
   - C. `system.billing.usage`, which records pipeline events
   - D. The Jobs UI screenshots exported to the repo

27. An engineer must be notified when any task in a production job fails, is skipped due to an upstream failure, or runs longer than its expected duration. Where is this configured natively?
   - A. The job's/task's **notifications** settings (on start/success/failure and **duration/streaming-backlog thresholds**), delivered to email or a system destination (e.g. Slack/PagerDuty)
   - B. The Query Profile UI alert tab
   - C. `system.access.audit` triggers
   - D. A cluster init script that watches logs

---

## Transform / Quality (Q28–Q33)

28. A query computes, per customer, a 7-row trailing moving average of `daily_spend` ordered by `day`. Which Spark SQL construct is correct and efficient?
   - A. `AVG(daily_spend) OVER (PARTITION BY customer_id ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)`
   - B. A self-join of the table to itself on a 7-day date range, then `GROUP BY customer_id`
   - C. `AVG(daily_spend) OVER (PARTITION BY customer_id ORDER BY day RANGE BETWEEN 6 PRECEDING AND CURRENT ROW)` for a fixed 7-row window
   - D. A correlated subquery returning the average for each row

29. To keep only the latest record per `order_id` from a CDC staging table (by `updated_at`), which approach is the most efficient single-pass Spark SQL?
   - A. `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC)` then filter `rn = 1`
   - B. `GROUP BY order_id` selecting `MAX(updated_at)` then join back on `(order_id, updated_at)`
   - C. `DISTINCT order_id` then a correlated subquery per id
   - D. Collect all rows to the driver and dedupe in pandas

30. In an SDP pipeline, the team wants invalid rows (failing `amount >= 0`) **dropped from the target but the pipeline kept running**, with the drop counted in metrics. Which expectation form is correct?
   - A. `CONSTRAINT valid_amount EXPECT (amount >= 0) ON VIOLATION DROP ROW`
   - B. `CONSTRAINT valid_amount EXPECT (amount >= 0) ON VIOLATION FAIL UPDATE`
   - C. `CONSTRAINT valid_amount EXPECT (amount >= 0)` with no action (default), which drops rows
   - D. A `WHERE amount >= 0` in the query, which records drop metrics automatically

31. The team must **quarantine** bad rows (route them to a separate table for inspection) rather than drop or fail, while letting valid rows flow to the clean target. What's the documented SDP pattern?
   - A. Tag rows with a validity flag (an expression that is the inverse of the expectation) and write valid rows to the clean table and invalid rows to a separate quarantine table
   - B. Use `ON VIOLATION FAIL UPDATE`, which auto-creates a quarantine table
   - C. Use `ON VIOLATION DROP ROW`, which writes dropped rows to a hidden quarantine table
   - D. Quarantine is only possible in Auto Loader, never in SDP

32. An Auto Loader classic (non-SDP) batch/stream job must separate malformed records that don't match the schema into their own column for later inspection rather than failing. Which mechanism does this?
   - A. The `_rescued_data` column (rescued data column) — fields that don't match the schema are captured as a JSON blob with their source file path
   - B. `cloudFiles.schemaEvolutionMode = failOnNewColumns`, which routes bad rows to a column
   - C. `mode = DROPMALFORMED`, which keeps malformed rows in `_corrupt_record`
   - D. Deletion vectors, which mark malformed rows

33. A wide aggregation `GROUP BY` over billions of rows is slow with large shuffle; the cardinality of group keys is moderate (~hundreds). The query profile shows huge shuffle exchange. Which is a sound optimization without changing results?
   - A. Ensure pre-aggregation/partial aggregation happens (it does by default in Spark) and verify enough shuffle partitions so each reducer's working set fits memory, avoiding spill; consider clustering on the group keys to reduce input scanned
   - B. Replace the `GROUP BY` with a Python UDF that aggregates row-by-row
   - C. Broadcast the fact table to all executors
   - D. Disable Adaptive Query Execution so the shuffle is skipped

---

## Security & Compliance (Q34–Q39)

34. A table must show full `salary` to HR but `NULL` to everyone else, enforced at query time without copying data. Which Unity Catalog feature and DDL applies it to an existing table?
   - A. A column-mask SQL UDF, applied with `ALTER TABLE t ALTER COLUMN salary SET MASK <mask_fn>`
   - B. A row filter, applied with `ALTER TABLE t SET ROW FILTER <fn> ON (salary)`
   - C. A view with a `CASE` expression — the only supported approach
   - D. `REVOKE SELECT ON COLUMN salary`, which masks the column

35. A multi-tenant table must restrict each analyst to rows for their own `region`, enforced centrally and at query time. Which UC feature and DDL is correct?
   - A. A row-filter SQL UDF (returning a boolean predicate, e.g. using `is_account_group_member`), applied with `ALTER TABLE t SET ROW FILTER <fn> ON (region)`
   - B. A column mask on `region`
   - C. Partitioning by `region` so each analyst reads one partition
   - D. `GRANT SELECT ... WHERE region = ...`, an inline grant predicate

36. A compliance pipeline must replace direct identifiers (email, phone) with consistent surrogate values so the same person maps to the same token across tables, while keeping the data joinable. Which anonymization technique is this?
   - A. **Tokenization / pseudonymization** — replace identifiers with consistent surrogate tokens (e.g., deterministic hash or a token vault), preserving joinability without exposing raw PII
   - B. **Generalization** — coarsen values into ranges/buckets
   - C. **Suppression** — null out the column entirely
   - D. **Aggregation** — report only group counts

37. A streaming PII pipeline must mask Social Security numbers before they ever land in a Delta table, irreversibly, and the masking must apply to both the historical backfill (batch) and the live stream. Which design is compliant and consistent?
   - A. Apply the same deterministic masking transform (e.g., `sha2`/tokenization) in a shared transformation function used by both the batch backfill and the streaming write, so masked-at-rest values are identical and raw SSNs never persist
   - B. Apply a UC column mask only, which is enough because it rewrites the stored bytes
   - C. Store raw SSNs and rely on a row filter to hide them
   - D. Mask only the batch path; streaming data is ephemeral and needs no masking

38. For GDPR-style retention compliance, a team must permanently purge rows older than 7 years from a Delta table so the data is unrecoverable via time travel within the retention window. Which sequence is correct?
   - A. `DELETE` the expired rows, then `VACUUM` after the retention threshold so the underlying files holding only deleted data are physically removed (time travel beyond retention can no longer reconstruct them)
   - B. `DROP TABLE` and recreate it empty each year
   - C. Set `delta.deletedFileRetentionDuration` to 0 and rely on reads to skip old rows
   - D. Disable Change Data Feed so deleted rows can't be recovered

39. A workspace admin must enforce least privilege on a set of notebooks and jobs so a contractor group can run but not edit them, and cannot view secrets. Which mechanism enforces this on workspace objects?
   - A. **Access control lists (ACLs)** on the workspace objects (notebook/job permissions like CAN_VIEW/CAN_RUN/CAN_MANAGE) plus secret-scope ACLs, granting the contractor group only run/view
   - B. A row filter on the notebook
   - C. A column mask on the job parameters
   - D. Delta Sharing recipient tokens scoped to the contractor

---

## Debugging & Deploying (Q40–Q45)

40. A 12-task job fails at task 7 of 12. After fixing a bad config value, the team wants to re-run only task 7 and its downstream dependents (not the 6 successful upstream tasks), overriding one parameter for this attempt. Which feature does this?
   - A. **Repair run** — re-runs only the failed/skipped tasks plus their downstream dependents, and lets you enter parameter overrides in the Repair dialog
   - B. Clone the job and run the clone from scratch
   - C. `databricks bundle destroy` then `deploy`
   - D. Set `Run if = All done` on task 7 and resubmit

41. An SDP pipeline update fails partway. The team needs to find which flow failed, the exception, and which expectation thresholds were breached, programmatically. Which two sources should they use?
   - A. The **SDP event log** (query `flow_progress`/`details` for errors and expectation metrics) and the **Spark UI** for the failing flow's stage/executor detail
   - B. Only the cluster's Log4j file, since SDP doesn't emit structured events
   - C. `system.billing.usage` for the failed update's cost
   - D. The Query Profile UI, which is the only SDP debugging tool

42. A Spark job fails with a task-level exception that the run page summarizes but truncates. To get the full stack trace, executor stderr, and the exact failing stage/task, where does the engineer look?
   - A. The **Spark UI** (Stages/Tasks for the failing stage) and the **cluster/driver+executor logs** (stdout/stderr, Log4j)
   - B. The DAB `databricks.yml` validation output
   - C. `system.access.audit`
   - D. The Query Profile, which only covers SQL warehouse queries

43. A team wants Git-based CI/CD where notebooks are edited against a repo branch in the workspace and PRs trigger deployment, with code (not job config) version-controlled in the workspace UI. Which feature provides the in-workspace Git integration?
   - A. **Databricks Git Folders** (Repos) — connect the workspace to a Git provider, work on branches, commit/push; pair with DABs for job/pipeline config deployment
   - B. DBFS mounts of the Git repo
   - C. `%pip install git+https://...` per notebook
   - D. Delta Sharing of the repo

44. A bundle deploys fine to `dev` but `databricks bundle deploy -t prod` fails validation; the prod target sets only `workspace.host` and `run_as: { user_name: alice@corp.com }` under `mode: production`. Which fix aligns with the production preset's rules?
   - A. Provide `workspace.root_path` as well, or change `run_as` to a **service principal** — `production` requires host + root_path unless run-as is a service principal
   - B. Add `default: true` to the prod target
   - C. Switch to `mode: development`, since production can't deploy via CLI
   - D. Remove `run_as`; production always deploys as the calling user

45. After a deploy, an engineer realizes the bundle created a *second* job because the existing UI-built job wasn't linked to the bundle resource. How should they adopt the existing job so future deploys update it in place?
   - A. `databricks bundle generate job --existing-job-id <id>` to emit YAML, then `databricks bundle deployment bind` the resource key to that job id before the next deploy
   - B. `databricks bundle destroy` then redeploy
   - C. Rename the bundle resource to match the UI job name; deploy matches by name
   - D. Import the job JSON into a Git Folder

---

## Data Ingestion (Q46–Q49)

46. Auto Loader is ingesting JSON with `cloudFiles.schemaEvolutionMode` left at its default (no schema provided). A file arrives with a new field. What happens by default, and what must the caller ensure?
   - A. Default is `addNewColumns`: the stream throws `UnknownFieldException` on the first record with the new column and **must be restarted** to pick up the added column (Lakeflow Jobs/SDP can auto-restart; a bare `readStream` won't)
   - B. Default is `rescue`: the new field is silently dropped, no restart needed
   - C. Default is `none`: the field is added without any restart
   - D. Default is `failOnNewColumns`: the table is permanently halted

47. A pipeline must incrementally and exactly-once ingest **Avro** files continuously landing in cloud storage into a Delta bronze table, append-only, with schema inference. Which is the correct, supported configuration?
   - A. `spark.readStream.format("cloudFiles").option("cloudFiles.format","avro").load(path)` writing to a Delta streaming sink (Auto Loader supports Avro and tracks processed files for exactly-once)
   - B. Auto Loader supports only JSON/CSV; convert Avro to JSON first
   - C. Use a batch `read.format("avro")` re-reading all files every run; Auto Loader can't do append-only
   - D. Use Delta Sharing to ingest the Avro files

48. A team must ingest **binary** files (PDFs/images) into a Delta table for downstream ML feature extraction, capturing the file content plus path and modification time. Which source format is correct?
   - A. The `binaryFile` data source (`spark.read.format("binaryFile")`), which yields `path`, `modificationTime`, `length`, and `content` columns
   - B. The `text` source, which reads binary as UTF-8
   - C. `csv` with a binary delimiter
   - D. Auto Loader cannot read binary; mount the files and store paths only

49. A streaming pipeline reads JSON events from a **message bus** (Kafka) and appends to a Delta bronze table for exactly-once processing. Which is the correct shape?
   - A. `spark.readStream.format("kafka")...load()`, parse the value payload, then `writeStream.format("delta")` with a checkpoint — Structured Streaming + Delta gives exactly-once append semantics
   - B. Poll Kafka in a Python loop and `INSERT` each message, relying on Delta to dedupe
   - C. Use Auto Loader's `cloudFiles` to read Kafka topics directly
   - D. Use Lakehouse Federation to query Kafka as a foreign table

---

## Governance (Q50–Q53)

50. A data steward wants tables and columns to be discoverable, with searchable business descriptions and metadata that surface in Catalog Explorer and search. Which is the correct mechanism?
   - A. Add `COMMENT`/descriptions (and tags) on catalogs, schemas, tables, and columns in Unity Catalog so they appear in Catalog Explorer and search, improving discoverability
   - B. Store descriptions in a separate wiki only
   - C. Use a row filter to surface descriptions
   - D. Descriptions are only possible via Delta Sharing metadata

51. A user is granted `SELECT` on a catalog. They expect to read a new table later created in a schema under it. Under Unity Catalog's inheritance model, what is true?
   - A. Privileges granted on a securable are **inherited** by its children, so `SELECT` on the catalog applies to current and future schemas/tables within it (unless more specific grants intervene)
   - B. Privileges never inherit; you must grant on every table individually
   - C. `SELECT` on a catalog grants only metadata visibility, never data access
   - D. Inheritance flows upward — a table grant propagates to the catalog

52. To let a group query tables in a schema, which combination of Unity Catalog privileges is the minimum required, given the three-level namespace?
   - A. `USE CATALOG` on the catalog + `USE SCHEMA` on the schema + `SELECT` on the table (or schema)
   - B. `SELECT` on the table alone is sufficient
   - C. `MANAGE` on the catalog
   - D. `MODIFY` on the schema

53. A platform team wants to attach a governance tag (e.g., `pii=true`) once and have downstream policies and discoverability apply consistently across many tables. Which Unity Catalog capability supports tag-driven governance and search?
   - A. **Governed tags / tagging** on securables, queryable and usable for discovery (and for attribute-based policies), so a tag set once drives consistent governance
   - B. Column masks, which are the only way to mark PII
   - C. Delta Sharing recipient properties
   - D. Cluster policies

---

## Data Modelling (Q54–Q56)

54. A 5-TB events table needs a layout that gives good skipping on two evolving filter columns and avoids the small-file/skew problems of partitioning, with the ability to re-tune keys as access patterns drift. Which is the best Delta modelling choice and why?
   - A. **Liquid clustering** — self-tuning, skew-resistant, no directory explosion, keys redefinable via `ALTER TABLE` without rewriting existing data; preferred over partitioning/ZORDER for evolving patterns
   - B. Partition by both columns for guaranteed pruning
   - C. ZORDER on both columns and re-run on every write
   - D. Bucketing by a surrogate key

55. A team must decide between liquid clustering and partition + ZORDER for a table whose queries **always** filter on a single low-cardinality `region` (≈30 values) and never change. What's the most defensible statement?
   - A. For a stable, single low-cardinality filter, partitioning by `region` (optionally with ZORDER for a secondary key) is still effective; liquid clustering is the better default when filter columns are high-cardinality or change over time
   - B. Liquid clustering is always strictly superior, so partitioning is wrong here
   - C. Partitioning is deprecated and unsupported on Delta
   - D. ZORDER and liquid clustering cannot coexist conceptually, so neither applies

56. An analytics team is building a star schema: a large central `fact_sales` and several conformed dimensions (`dim_customer`, `dim_product`, `dim_date`). Which modelling guidance is correct for large-scale Delta?
   - A. Use a dimensional (star) model — narrow fact with surrogate keys to dimensions; cluster the fact on its common filter/join keys and keep dimensions small enough to broadcast in joins
   - B. Denormalize everything into one wide table always; dimensions are an anti-pattern on Delta
   - C. Partition every dimension by its surrogate key for pruning
   - D. Model facts and dimensions as materialized views only, never tables

---

## Sharing & Federation (Q57–Q59)

57. A provider must share live Delta tables with a partner who also runs a Unity Catalog–enabled Databricks workspace, with full governance, auditing, and no credential files to manage. Which Delta Sharing mode is correct?
   - A. **Databricks-to-Databricks (D2D)** sharing — recipient is identified by their UC sharing identifier; no bearer-token credential file is needed, and UC governance/auditing applies on both sides
   - B. Open protocol (D2O) with a bearer-token activation file, the only way to share live data
   - C. Lakehouse Federation, since Delta Sharing can't share live data
   - D. Copy the tables to the partner's storage nightly

58. A provider must share Delta tables with an external partner on a **non-Databricks** platform (e.g., a pandas/Spark client) over the open Delta Sharing protocol. What does the provider hand the recipient?
   - A. A recipient object with a **bearer token + activation link**; the recipient downloads a credential file and reads the share via the open protocol (D2O), no Databricks workspace required
   - B. A Unity Catalog metastore admin login
   - C. A liquid-clustering key file
   - D. A Git Folder containing the data

59. A team needs to run governed, **read-only** SQL queries against tables that live in an external Snowflake/PostgreSQL system **without ingesting/copying** the data, with Unity Catalog access control and lineage applied. Which capability is this?
   - A. **Lakehouse Federation** — create a connection + foreign catalog so UC governs access/lineage while queries execute against the external source (with pushdown), no data copy required
   - B. Delta Sharing D2O
   - C. Auto Loader pointed at the external DB
   - D. Predictive optimization

---

## Answer Key & Explanations

1. **A** — DAB `targets` with the `development` and `production` **presets** are the single-source multi-environment mechanism. `development` auto-prefixes resource names per developer, pauses schedules/triggers, and tags runs as dev; `production` enforces validation (host + root_path or service-principal run-as), keeps real schedules, and blocks dev-only behaviors. One `databricks.yml`, multiple targets. B/C/D defeat the single-source-of-truth purpose; Git Folders version only code, not target config. (S1 — DAB targets/presets, dev vs prod)

2. **A** — The bundle `artifacts` mapping (`type: whl`) builds your Python package into a wheel at `bundle deploy`, uploads it, and a job task referencing it under `libraries` (`whl: ./dist/*.whl`) installs it on compute. This is the recommended way to ship packaged code instead of `%run`. B/C/D are fabricated (`sync` only syncs files; production mode bakes nothing; `for_each` is iteration). (S1 — DAB artifacts/wheel packaging)

3. **A** — `sha2(col, 256)` is a native Spark SQL function evaluated in the JVM/Catalyst, eliminating the per-row Python serialization a scalar UDF pays — fastest and correct. B (pandas_udf) is faster than a scalar UDF but still slower than a built-in. C — `useArrow=True` speeds data transfer but the function still runs in a Python worker (not Catalyst-native). D — `lru_cache` doesn't help across distributed workers/partitions. (S1 — Python UDF vs built-in; performance)

4. **A** — Streaming table = incremental, append-style, each input file processed exactly once → correct for continuous bronze ingest with low latency. Materialized view = result of a query, refreshed to reflect current source state, queryable as a normal table → correct for the gold re-aggregation. B inverts them; C/D state false limitations (both are queryable tables; MVs aggregate fine; STs do low-latency ingest). (S1 — streaming tables vs materialized views)

5. **A** — `AUTO CDC` / `APPLY CHANGES INTO` with `KEYS`, `SEQUENCE BY`, `APPLY AS DELETE WHEN`, and `STORED AS SCD TYPE 1` writes to a streaming-table target, processes records in sequence order (handles out-of-order arrival), and applies upserts + deletes without hand-written MERGE. B — MV refresh doesn't do key-based CDC dedup. C — `FROM SNAPSHOT` is for sources that emit full periodic dumps, not an ordered op/seq feed. D — per-batch MERGE is the imperative anti-pattern this API replaces. (S1 — APPLY CHANGES / AUTO CDC for CDC)

6. **A** — Spark Structured Streaming gives the standalone imperative control needed: `foreachBatch` for a custom external sink with your own idempotency, an explicit `checkpointLocation`, and arbitrary `Trigger.ProcessingTime`. SDP abstracts orchestration/checkpoints/retries declaratively. B/C/D confuse `foreachBatch` (a Structured Streaming sink API) with MV refresh policies / declarative-only constraints / job loops. (S1 — Structured Streaming vs SDP)

7. **A** — `assertSchemaEqual` compares schemas (names + types + nullability) only, ignoring row data — exactly the schema-only assertion needed for a large fixture. B is false: `assertDataFrameEqual` compares schema **and** data. C — `DataFrame.transform` just chains functions; it isn't an assertion. D — `assertDataFrameEqual` still compares data; `checkRowOrder` only governs ordering. (S1 — PySpark testing utilities)

8. **A** — `DataFrame.transform` takes a DataFrame→DataFrame function and returns a DataFrame, so transforms chain left-to-right and read top-down; each step is an independently unit-testable pure function. It's syntactic/structural — execution semantics (lazy, distributed) are unchanged. B/C/D invent eager execution, parallelism, or auto-caching that `transform` does not provide. (S1 — DataFrame.transform composition + testing)

9. **A** — The serverless high-memory setting (Standard 16 GB / High 32 GB) raises the **REPL/driver Python** memory used when running notebook code; it does **not** change the Spark session/executor memory. Single-node pandas/model work on the driver consumes exactly REPL memory, so High fixes it. B is the classic misconception. C/D are unrelated features. (S1 — serverless high-memory: REPL vs Spark session)

10. **A** — `%pip install` is notebook-scoped and **restarts the Python interpreter** for that notebook; on shared compute, ad-hoc installs can shift the resolved environment and break unrelated imports. Reproducible practice: pin dependencies in the job/serverless environment (or use cluster libraries deliberately), not ad-hoc `%pip` on shared clusters. B/C/D fabricate Maven-only/DBFS-root/STRICT-ISOLATION mechanisms. (S1 — third-party library scope/troubleshooting)

11. **A** — DABs define the full job (`resources.jobs.*`, keys mirroring the Jobs REST payload) as code; `bundle deploy -t staging` deploys it reproducibly and `bundle run <job>` triggers a validation run — the recommended CI path. B — `runs/submit` launches a one-off and persists nothing in Git. C is not automation. D — Git Folders version code only, not schedule/cluster config. (S1 — automate ETL via DABs/Jobs API/CLI)

12. **A** — A Jobs **If/else condition task** evaluates an expression (here a task value `bad_count`) and branches the downstream graph; use a numeric operator (`> 0`) because `==`/`!=` do string comparison. B is iteration, not branching. C — `FAIL UPDATE` halts the pipeline, it doesn't branch a job. D — `Run if` branches on task **status**, not a value. (S1 — pipeline control-flow operators if/else)

13. **A** — Serverless auto-optimization may add retries (at-least-once), which double-writes a non-idempotent INSERT. Unchecking **"Enable serverless auto-optimization (may include additional retries)"** in the task's Retry Policy enforces at-most-once. B is a fabricated conf for this. C — production mode doesn't disable retries. D is unrelated. (S1 — disallow retries for non-idempotent jobs)

14. **A** — **Predictive optimization** lets Databricks automatically run OPTIMIZE/VACUUM (and statistics) on Unity Catalog **managed** tables when beneficial, removing hand-scheduled maintenance and standing compute. B/C/D increase work or degrade reads; managed tables are the ones eligible for these automatic features. (S6 — UC managed tables reduce ops overhead)

15. **A** — **Deletion vectors** soft-mark deleted/updated rows in a side file so DELETE/UPDATE/MERGE avoid rewriting whole Parquet files; the data file is reconciled lazily during a later OPTIMIZE — exactly removing per-statement write amplification. B/C/D (ZORDER, tiny files, partition-by-id) don't avoid the rewrite and add their own pathologies. (S6 — deletion vectors)

16. **A** — **Liquid clustering** is self-tuning and skew-resistant, avoids directory/small-file explosion, and its keys can be redefined via `ALTER TABLE` so only future writes/OPTIMIZE reorganize — no full rewrite of existing data. B/C/D are rigid (re-partition), additive-but-limited (ZORDER on top of date), or still partition-bound. (S6/S10 — liquid clustering vs partitioning)

17. **A** — File pruning relies on per-file **min/max statistics**. Liquid clustering (or ZORDER) on `amount` aligns those stats with the predicate so files whose value range can't satisfy `> 10000` are skipped. B (cache) doesn't enable pruning; C (column projection) doesn't prune rows by predicate; D just brute-forces the scan. (S6 — data skipping / file pruning)

18. **A** — Enable **Change Data Feed** and read its change feed (`readChangeFeed=true`); CDF exposes row-level `insert`/`update_preimage`/`update_postimage`/`delete` records so the downstream can apply updates/deletes correctly, low-latency. B (`skipChangeCommits`) *ignores* change commits rather than applying them. C is high-latency/expensive. D is false — MVs don't propagate row deletes to arbitrary readers as a feed. (S6 — CDF for streaming-table limitations)

19. **A** — Delta indexes (collects min/max stats on) only the **first 32 columns** by default; a predicate on column #90 has no stats, so no skipping. Fix: move `device_id` into the leading columns, or raise `delta.dataSkippingNumIndexedCols` / set `delta.dataSkippingStatsColumns`, then re-OPTIMIZE so stats exist. B/C/D (partition swap, fake secondary index, bigger warehouse) don't address missing stats. (S6 — data skipping stats column limit)

20. **A** — Large two-sided shuffle on a join with a tiny dimension means the optimizer chose a **SortMergeJoin** instead of a broadcast. Broadcasting the small side ships it to executors and eliminates the fact-table shuffle. B/C/D (ZORDER, dimension stats, OPTIMIZE) don't fix the join-strategy/shuffle issue. (S6 — query profile: join types, shuffle)

21. **A** — **Change Data Feed** lets downstream consumers read only row-level changes (`table_changes(...)`) instead of full re-scans, directly cutting the latency/cost of detecting what changed in a streaming table. B/C/D don't address the re-scan pattern. (S6 — CDF to address streaming-table latency)

22. **A** — Cost attribution is `system.billing.usage` (per-record DBU usage with workspace, SKU, and `custom_tags`) joined to `system.billing.list_prices` (SKU prices over time). The custom cost-center tag lives in `custom_tags` on usage. The others aren't billing-attribution tables. (S5 — system tables for cost)

23. **A** — `system.access.audit` is the audit-log system table recording account/workspace actions including data-access events and failures — the authoritative who/what/when record. Billing/compute/query tables aren't the audit log. (S5 — system tables for audit)

24. **A** — The **Query Profile** UI shows the per-operator execution graph with rows/bytes, files pruned (data skipping), the chosen join type, and shuffle/spill metrics — the right starting point for a single slow query. Ganglia/billing/DAB logs don't profile a query plan. (S5 — Query Profiler UI)

25. **A** — A **Databricks SQL Alert** runs a scheduled query (computing the null-rate), evaluates a threshold condition, and fires a notification to a destination (email/Slack/webhook) — least custom code. B/C are not alerting tools; D — expectations record metrics but don't themselves send Slack alerts. (S5 — SQL Alerts for data quality)

26. **A** — Programmatic pipeline monitoring uses the **SDP event log** (queryable; `flow_progress` carries data-quality/expectation metrics and errors) and the **Pipelines REST API/CLI** for update status — no UI needed. B/C/D are false (status is exposed via API; billing isn't event status). (S5 — SDP event logs + REST/CLI monitoring)

27. **A** — Job/task **notifications** natively fire on start/success/failure and on **duration / streaming-backlog** thresholds, delivered to email or a configured system destination (Slack/PagerDuty/webhook). The other options aren't job notification mechanisms. (S5 — Jobs UI/API notifications)

28. **A** — A 7-row trailing average is a window aggregate: `AVG(...) OVER (PARTITION BY customer_id ORDER BY day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)`. `ROWS` counts physical rows (7 rows). C's `RANGE` frames by value of `day`, not a fixed row count, so it's wrong for "7 rows." B/D are inefficient self-join/correlated patterns. (S3 — window functions)

29. **A** — `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at DESC)` then `WHERE rn = 1` keeps the latest per key in a single pass. B requires a second join; C is a correlated per-id subquery; D collects to the driver (won't scale). (S3 — window functions for dedup)

30. **A** — `EXPECT (...) ON VIOLATION DROP ROW` discards invalid rows from the target while the pipeline continues, and the drops are counted in pipeline metrics. B (`FAIL UPDATE`) stops the update. C — the default (no action) is **warn**: invalid rows are *kept* and flagged, not dropped. D — a `WHERE` filters but isn't an expectation and doesn't record expectation metrics. (S3 — quarantine/expectations in SDP)

31. **A** — The documented quarantine pattern adds a validity-flag expression (typically the inverse of the expectation) and routes valid rows to the clean table and invalid rows to a separate quarantine table — keeping bad data for inspection without dropping or failing. B/C fabricate auto-created quarantine tables; D is false (quarantine works in SDP). (S3 — quarantine bad data in SDP)

32. **A** — Auto Loader's **rescued data column** (`_rescued_data`) captures fields that don't match the schema as a JSON blob with the source file path, so malformed/unexpected data is preserved for inspection instead of failing. B (`failOnNewColumns`) halts; C — `_corrupt_record` is the CSV/JSON parser mode column, not the Auto Loader rescue mechanism described; D is unrelated. (S3 — quarantine bad data in Auto Loader classic)

33. **A** — Spark already does partial (map-side) pre-aggregation for `GROUP BY`; the practical levers are enough shuffle partitions so each reducer fits memory (avoid spill) and clustering on group keys to reduce scanned input — without changing results. B (row UDF) is far slower; C (broadcast the fact) is nonsensical; D (disable AQE) doesn't skip the shuffle and usually hurts. (S3 — efficient aggregations on large data)

34. **A** — A **column mask** is a SQL UDF returning the (possibly masked) value, applied with `ALTER TABLE t ALTER COLUMN salary SET MASK <fn>`; the mask can return the real value for HR and NULL otherwise based on group membership — enforced at query time, no copy. B is a row filter (wrong tool/syntax for masking a value). C/D aren't the UC masking feature. (S7 — column masks)

35. **A** — A **row filter** is a SQL UDF returning a boolean predicate (commonly using `is_account_group_member(...)`), applied with `ALTER TABLE t SET ROW FILTER <fn> ON (region)`; it restricts visible rows centrally at query time. B masks a value, not rows. C/D aren't UC row-level security mechanisms. (S7 — row filters)

36. **A** — Consistent surrogate values that preserve joinability = **tokenization / pseudonymization** (deterministic hash or token vault). Generalization coarsens, suppression nulls out, aggregation reports only group stats — none preserve the consistent joinable mapping required. (S7 — anonymization/pseudonymization techniques)

37. **A** — Compliant masking-before-persist uses the **same deterministic transform** (e.g., `sha2`/tokenization) in a shared function called by both the batch backfill and the streaming write, so at-rest values are identical and raw SSNs never land. B — a UC column mask hides at query time but the raw bytes are still stored. C stores raw PII. D leaves streaming unmasked. (S7 — compliant batch+streaming PII-masking pipeline)

38. **A** — Retention purge = `DELETE` the expired rows, then **`VACUUM`** after the retention threshold so files containing only deleted data are physically removed and can't be reconstructed via time travel within the window. B is destructive overkill; C — `deletedFileRetentionDuration=0` is unsafe and doesn't itself purge logical rows; D (CDF) is unrelated to physical purge. (S7 — data purging for retention compliance)

39. **A** — Workspace-object **ACLs** (notebook/job permission levels CAN_VIEW/CAN_RUN/CAN_MANAGE) plus **secret-scope ACLs** enforce least privilege: grant the contractor group run/view but not edit, and no secret read. B/C (row filter/column mask) govern table data, not workspace objects; D (Delta Sharing) is for external data sharing. (S7 — ACLs on workspace objects, least privilege)

40. **A** — **Repair run** re-executes only the failed/skipped tasks **plus their downstream dependents** (skipping the already-successful upstream tasks), and the Repair dialog accepts **parameter overrides** for the attempt — minimizing time/compute. B/C/D re-run everything or destroy resources. (S9 — repair runs + parameter overrides)

41. **A** — SDP debugging uses the **event log** (query `flow_progress`/`details` for flow errors and expectation metrics) and the **Spark UI** for the failing flow's stage/executor detail. B is false (SDP emits structured events); C is cost, not failure detail; D — Query Profile is for SQL warehouse queries, not SDP flows. (S9 — debug SDP via event logs + Spark UI)

42. **A** — Full stack traces, executor stderr, and the exact failing stage/task come from the **Spark UI** (Stages/Tasks) and the **cluster driver/executor logs** (stdout/stderr, Log4j). B/C/D (DAB validation, audit table, Query Profile) don't give task-level Spark exceptions. (S9 — diagnose via Spark UI + cluster logs)

43. **A** — **Databricks Git Folders (Repos)** provide the in-workspace Git integration: connect to a provider, branch, commit/push notebooks; for full CI/CD you pair Git Folders (code) with DABs (job/pipeline config). B/C/D are not the Git-Folders integration. (S9 — Git-based CI/CD via Git Folders)

44. **A** — The `production` preset requires explicit `workspace.host` **and** `root_path` unless `run_as` is a **service principal**; a user run-as with only host trips validation. Supply `root_path` or switch run-as to a service principal. B/C/D are fabricated (default flag, CLI restriction, run-as removal). (S9/S1 — DAB production preset validation)

45. **A** — To adopt an existing UI job so deploys update it in place: `databricks bundle generate job --existing-job-id <id>` to emit YAML, then `databricks bundle deployment bind` the resource key to that job id before deploying (a plain deploy of generated config creates a duplicate). B destroys history; C — bundles key on resource identity/binding, not UI name match; D — Git Folders don't manage jobs. (S9 — DAB adopting existing resources)

46. **A** — With no schema provided, `schemaEvolutionMode` defaults to `addNewColumns`: the first record carrying a new column throws `UnknownFieldException` and the stream **restarts** with the column added. A bare `spark.readStream` won't restart itself — Lakeflow Jobs or SDP handle the auto-restart. B/C/D misstate the default (rescue/none/failOnNewColumns are non-default). (S2 — Auto Loader schema evolution default)

47. **A** — Auto Loader (`cloudFiles`) supports **Avro** (and Parquet/ORC/JSON/CSV/XML/Text/Binary); set `cloudFiles.format=avro`, `readStream`, and write to a Delta streaming sink — Auto Loader tracks processed files for exactly-once incremental, append-only ingest. B is false (Avro is supported); C is the expensive full re-read it avoids; D is unrelated. (S2 — ingest Avro via Auto Loader, append-only)

48. **A** — The **`binaryFile`** data source reads each file as a row with `path`, `modificationTime`, `length`, and `content` (binary) — the supported way to land PDFs/images into Delta for ML. B/C corrupt binary; D is false (binary is supported). (S2 — ingest Binary files)

49. **A** — Reading a **message bus**: `readStream.format("kafka").load()`, parse `value`, then `writeStream.format("delta")` with a checkpoint — Structured Streaming + Delta provides exactly-once append semantics. B (manual poll + INSERT) is not exactly-once; C — Auto Loader reads cloud object storage, not Kafka topics; D — Federation queries SQL sources, not Kafka. (S2 — ingest from message buses)

50. **A** — Discoverability comes from **descriptions/COMMENTs and tags** on UC securables (catalog/schema/table/column), which surface in Catalog Explorer and search. B (wiki) isn't integrated; C/D aren't the metadata mechanism. (S8 — descriptions/metadata for discoverability)

51. **A** — Unity Catalog privileges **inherit downward**: a grant on a securable applies to its current and future children (catalog → schemas → tables), unless a more specific grant overrides. So `SELECT` on the catalog covers a later-created table. B/C/D contradict the inheritance model (no inheritance / metadata-only / upward flow). (S8 — UC permission inheritance)

52. **A** — The three-level namespace requires `USE CATALOG` on the catalog **and** `USE SCHEMA` on the schema as traversal privileges, plus `SELECT` on the table (or schema) to read — the minimum set. B (SELECT alone) fails without USE grants; C/D over-grant or are the wrong privilege. (S8 — UC inheritance/least privilege to read)

53. **A** — **Governed tags / tagging** on securables are queryable and drive consistent governance (and attribute-based policies) plus discovery: set the `pii=true` tag once and policies/search apply across tables. B (masks) marks one column; C/D are unrelated. (S8 — metadata/tags for governance)

54. **A** — **Liquid clustering** is the right large-Delta layout for two evolving filter columns: self-tuning, skew-resistant, no directory explosion, and keys redefinable via `ALTER TABLE` without rewriting existing data — preferred over partitioning/ZORDER when patterns drift. B/C/D reintroduce rigidity/rewrite cost or don't aid skipping. (S10 — liquid clustering for layout/query perf)

55. **A** — For a **stable, single low-cardinality** filter, partitioning by `region` (optionally + ZORDER for a secondary key) is still effective and can beat clustering by eliminating most files up front; liquid clustering is the better default when keys are high-cardinality or change. B overstates clustering; C/D are false. (S10 — liquid clustering vs partitioning/ZORDER tradeoffs)

56. **A** — A **dimensional star model** (narrow fact with surrogate keys → conformed dimensions) is the analytics-scale pattern; cluster the fact on common filter/join keys and keep dimensions small enough to broadcast in joins. B/C/D (always-denormalize, partition dims by surrogate, MV-only) are anti-patterns or false constraints. (S10 — dimensional models for analytics)

57. **A** — **Databricks-to-Databricks (D2D)** sharing identifies the recipient by their Unity Catalog sharing identifier — **no bearer-token credential file** — and applies UC governance/auditing on both provider and recipient, sharing live data. B (D2O token) is for non-Databricks recipients; C is federation (not sharing); D defeats live sharing. (S4 — Delta Sharing D2D)

58. **A** — For a **non-Databricks** recipient, the provider creates a recipient with a **bearer token + activation link**; the recipient downloads a credential file and reads the share via the **open protocol (D2O)** from any client — no Databricks workspace required. B/C/D are unrelated. (S4 — Delta Sharing D2O / open protocol)

59. **A** — **Lakehouse Federation**: create a connection + foreign catalog so Unity Catalog governs access and lineage while queries run against the external source (Snowflake/PostgreSQL/etc.) with pushdown — read-only, **no data copy/ingest**. B (D2O) is sharing out; C — Auto Loader reads object storage, not external SQL DBs; D is maintenance. (S4 — Lakehouse Federation with governance)

---

*Verified against current Databricks documentation (system tables, Auto Loader schema evolution, AUTO CDC/APPLY CHANGES, liquid clustering vs partitioning/ZORDER, deletion vectors, CDF, row filters/column masks DDL, repair runs, DAB presets/artifacts/bind, Delta Sharing D2D/D2O, Lakehouse Federation, SDP expectations) as of June 2026.*
