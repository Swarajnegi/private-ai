# Databricks Data Engineer Professional — MCQ Bank

Consolidated practice multiple-choice questions across all exam domains, assembled from the per-domain banks in `mcq/`. Each domain section contains its questions followed by its answers & explanations.

**Total questions: 93**

## Domain Index

| # | Domain | Exam Weight | Source | Questions |
|---|--------|-------------|--------|-----------|
| 1 | Developing Code (Python/SQL) | 22% | `mcq/code.md` | 18 |
| 2 | Data Ingestion & Acquisition | 7% | `mcq/ingestion.md` | 6 |
| 3 | Data Transformation, Cleansing & Quality | 10% | `mcq/transform.md` | 8 |
| 4 | Data Sharing & Federation | 5% | `mcq/sharing.md` | 6 |
| 5 | Monitoring & Alerting | 10% | `mcq/monitoring.md` | 12 |
| 6 | Cost & Performance Optimisation | 13% | `mcq/costperf.md` | 12 |
| 7 | Security & Compliance | 10% | `mcq/security.md` | 10 |
| 8 | Data Governance | 7% | `mcq/governance.md` | 6 |
| 9 | Debugging & Deploying | 10% | `mcq/debugdeploy.md` | 10 |
| 10 | Data Modelling | 6% | `mcq/modeling.md` | 5 |
| | **Total** | | | **93** |

---

# 1. Developing Code (Python/SQL) — Practice MCQs (22%)

1. A team has a Databricks Asset Bundle whose `databricks.yml` references notebooks that contain ~600 lines of transformation logic each. The notebooks pass manual review but the team cannot get any of the logic under automated pytest coverage, and CI keeps shipping regressions. Following Databricks' recommended scalable project structure, which change most directly enables off-cluster unit testing?
   - A. Move the transformation logic into importable `.py` modules under `src/<package>/` and keep the notebooks as thin orchestration that calls those functions
   - B. Convert every notebook task into a `for_each_task` so each transformation runs as an isolated iteration that can be tested independently
   - C. Add `mode: production` to the dev target so the deployed notebooks are locked from UI editing and therefore frozen for testing
   - D. Increase the notebook task to High memory (32 GB) so a full pytest suite can run inside the notebook REPL

2. An engineer runs `databricks bundle deploy -t prod` against a target configured with `mode: production`. The deploy fails validation. The target sets only `workspace.host` and lists `run_as: { user_name: alice@corp.com }`. Which fix aligns with how the `production` preset behaves?
   - A. Provide `workspace.root_path` as well, or change `run_as` to a service principal — `production` requires host + root_path unless run-as is a service principal
   - B. Add `default: true` to the prod target, because `production` mode is only valid on the default target
   - C. Switch the target to `mode: development`, since `production` cannot be deployed via the CLI and must be deployed from the UI
   - D. Remove the `run_as` mapping entirely, because `production` mode always deploys as the calling user

3. A production job was hand-built in the Jobs UI months ago and now needs to come under Databricks Asset Bundle control so future config changes are versioned. The team wants the bundle to update that exact job, not create a second copy. Which approach is correct?
   - A. Use `databricks bundle generate job --existing-job-id <id>` to emit YAML, then `databricks bundle deployment bind` the resource to the existing job id before deploying
   - B. Run `databricks bundle deploy` with the new YAML; the CLI matches resources by name and will reuse the existing job automatically
   - C. Run `databricks bundle destroy` first to remove the old job, then `deploy` the bundle to recreate it cleanly
   - D. Use a Git Folder to import the job's JSON, since DABs cannot manage jobs that were created outside a bundle

4. Two workspaces (staging and prod) must receive identical jobs AND identical schedules/pipeline configuration from a single Git repo, reproducibly, on every merge to main. The team currently uses Databricks Git Folders to sync code. Why is that insufficient, and what should they use?
   - A. Git Folders version only code files, not job/pipeline configuration; use Databricks Asset Bundles, which version code and resource config together
   - B. Git Folders cannot connect to GitHub Actions; switch to Bundles, which is the only tool with a GitHub Actions integration
   - C. Git Folders only work in the dev workspace; Bundles are required because Git Folders are blocked in production workspaces
   - D. Nothing is wrong — Git Folders already version schedules and cluster configs, so they should keep Git Folders and add a cron

5. An engineer installs a new PyPI package via the cluster's Libraries tab while a teammate has a notebook already attached to that cluster. The teammate runs `import newpkg` and gets `ModuleNotFoundError`, even after the library shows as Installed on the cluster. What is happening?
   - A. A newly installed cluster library is not visible to an already-attached notebook until a new session (detach/reattach or restart) starts
   - B. Cluster-scoped libraries are write-protected; the teammate must reinstall the package with `%pip install` to make it importable
   - C. The install silently failed because cluster libraries cannot be sourced from PyPI — only Maven coordinates are allowed on a cluster
   - D. The package needs `STRICT ISOLATION` enabled on the cluster before any notebook can import it

6. A serverless job task must install a pinned set of dependencies reproducibly, including one package only available as a locally built wheel and the rest from PyPI. The task is a notebook with no cluster to attach to. Which is the correct, supported install path?
   - A. Install via the notebook Environment side-pane / base-environment (or `%pip`), referencing PyPI by pinned name and the wheel by its Unity Catalog volume path
   - B. Add the wheel and PyPI packages to the cluster Libraries tab, since serverless tasks inherit the workspace default cluster's libraries
   - C. Place the wheel on the DBFS root and `%pip install` it from `dbfs:/`, which is the recommended location for serverless dependencies
   - D. Use `databricks bundle destroy` then `deploy` so the artifacts mapping reinstalls the wheel as a runtime-baked package

7. A scalar `@udf`-decorated Python function applied to a billion-row DataFrame is the job's bottleneck; the Spark UI shows large Python-worker serialization time. Rewriting it as a `@pandas_udf` Series→Series function is expected to be dramatically faster. What is the underlying reason?
   - A. The Pandas UDF transfers data in Apache Arrow record batches (default 10,000 rows) and processes them vectorized, amortizing the serialize/transfer cost a plain Python UDF pays row-at-a-time
   - B. The Pandas UDF runs entirely inside the JVM via Catalyst, eliminating the Python process altogether
   - C. The Pandas UDF caches its output in the Spark session memory, so repeated rows are computed only once
   - D. The Pandas UDF disables data skipping, which removes the file-pruning overhead that slows the plain Python UDF

8. A `@pandas_udf("double")` Series→Scalar function is used in `df.groupBy("customer_id").agg(...)`. Most groups are small, but a handful of customers have hundreds of millions of rows, and those tasks fail with executor OOM. What is the correct explanation and mitigation?
   - A. Grouped-aggregate Pandas UDFs load all data for a group into memory and do not apply the batch-size limit per group; rewrite using a built-in aggregate or de-skew the large groups
   - B. Series→Scalar UDFs ignore `spark.sql.execution.arrow.maxRecordsPerBatch`; setting it lower will cap per-group memory
   - C. Enabling High memory (32 GB) on the task fixes it because that raises the Spark executor heap for grouped aggregates
   - D. The OOM is from row-order checking; passing `checkRowOrder=False` to the UDF disables the in-memory sort

9. A Lakeflow Jobs If/else condition task evaluates `{{tasks.validate.values.error_count}} == 0` to decide whether to skip a quarantine task. The upstream task sets `error_count` to the float `0.0`. The branch behaves unexpectedly. What is the root cause?
   - A. `==` in an If/else task does a string comparison, so `"0.0" == "0"` is false; use a numeric operator like `<= 0` for numeric logic
   - B. If/else tasks only support `>` and `<`; `==` is silently ignored and always evaluates false
   - C. Task values cannot be compared in If/else conditions — only job parameters are allowed as operands
   - D. The condition fails because If/else tasks require compute, and none was attached to evaluate the equality

10. An engineer drives a `for_each_task` from a SQL task that returns 4,000 rows, each containing a full JSON config blob, by referencing `{{tasks.read_config.output.rows}}` directly as the iteration input. Some iterations silently never run. Which design fact explains this and what is the fix?
    - A. For each inputs are size-limited (≈5,000 chars in the Inputs box, up to ~48 KB via a task-value reference); pass lightweight keys (e.g. ids) through the For each and have the nested task look up the full config from a table
    - B. For each tasks cap at 100 iterations; split the array into batches of 100 across separate For each tasks
    - C. Nested For each tasks are required for more than 1,000 rows; wrap the For each inside another For each
    - D. The default concurrency of 1 drops any iteration beyond the first; set concurrency to 4,000 to run them all

11. A job must run a cleanup/notification task only when an upstream ingestion task fails, while the normal success path proceeds otherwise. Which orchestration construct correctly models this?
    - A. Set the cleanup task's `Run if` dependency to "At least one failed" (branch on upstream task status)
    - B. Add an If/else condition task comparing the upstream task's exit code `== 1`
    - C. Use a For each task over the upstream task's outputs and filter to the failed ones
    - D. Enable serverless auto-optimization so the failed task auto-retries and triggers cleanup on the final attempt

12. A serverless notebook task fails with OOM inside a `result_pdf = big_df.toPandas()` call that pulls a large result to the driver. The engineer sets the task's Environment Memory to High (32 GB) and the error disappears. Which statement about why this worked is correct?
    - A. High memory raises the REPL (driver-side Python) memory, which is exactly what a `toPandas()` collect to the driver consumes; it does not change Spark executor/session memory
    - B. High memory raises the Spark executor heap, so the distributed scan that feeds `toPandas()` no longer spills
    - C. High memory enables deletion vectors, reducing the data volume that `toPandas()` has to materialize
    - D. High memory disables auto-optimization retries, so the task no longer re-runs the OOM-prone collect

13. A serverless workflow runs a non-idempotent task that appends rows with a plain `INSERT` (not a `MERGE`). Operators notice duplicate rows after transient failures. They want strict at-most-once execution. What is the correct configuration change?
    - A. In the task's Retry Policy dialog, uncheck "Enable serverless auto-optimization (may include additional retries)" to disallow the silent retries
    - B. Set the task retry count to 0 in the notebook with `spark.conf.set("spark.task.maxRetries", 0)`
    - C. Switch the target to `mode: production`, which disables all task retries by default
    - D. Lower `spark.sql.execution.arrow.maxRecordsPerBatch` so each insert batch is small enough not to retry

14. In a Lakeflow Spark Declarative Pipeline, a gold dataset must reflect the latest aggregation over the full silver history and be queryable as a normal table, where each refresh reflects the current source state. A different bronze dataset must ingest an append-only file stream incrementally, processing each file exactly once. Which mapping of dataset type to use case is correct?
    - A. Gold aggregation → materialized view (refreshed — full recompute or incremental — from current source state); bronze append-only ingest → streaming table (each input processed once)
    - B. Gold aggregation → streaming table (append-only); bronze append-only ingest → materialized view (full recompute each run)
    - C. Both should be materialized views, since streaming tables cannot be queried as tables
    - D. Both should be streaming tables, since materialized views cannot aggregate over history

15. A source emits a change feed with insert/update/delete operations and a monotonically increasing `seq_num`, arriving out of order. The pipeline must maintain a current-state target with correct upserts and deletes without hand-writing MERGE. Which SDP construct is designed for this?
    - A. A streaming table target plus the AUTO CDC / APPLY CHANGES API (`FLOW AUTO CDC ... KEYS ... SEQUENCE BY seq_num`, with `APPLY AS DELETE WHEN`), which handles out-of-order records and deletes
    - B. A materialized view over the change feed, since MV refresh automatically deduplicates by primary key
    - C. A `for_each_task` that applies one MERGE per change record in sequence order
    - D. A Series→Scalar Pandas UDF that reduces each key group to its latest record

16. A team needs fine-grained, imperative control over a streaming query — a custom `foreachBatch` sink that writes to an external system, manual checkpoint-location management, and arbitrary trigger intervals as a standalone job — rather than a managed declarative dataset graph. Which approach fits, and why?
    - A. Use Spark Structured Streaming directly, because it gives standalone imperative control over `writeStream.foreachBatch`, manual checkpoint locations, and custom triggers; SDP manages orchestration, checkpoints, and retries for you
    - B. Use SDP streaming tables, because `foreachBatch` and manual checkpoint locations are only available inside declarative pipelines
    - C. Use a materialized view, since `foreachBatch` is a refresh policy option on MVs
    - D. Use a For each task, because `foreachBatch` is implemented as a job-level For each loop

17. A CI/CD pipeline must create and update a multi-task ETL job's full definition (tasks, dependencies, schedule, cluster config) reproducibly across dev and prod from version control, and trigger runs programmatically. Which combination is the Databricks-recommended path?
    - A. Define the job in a Databricks Asset Bundle (`resources.jobs.*`, keys mirroring the Jobs REST create payload) and use `databricks bundle deploy` / `run` in CI; the Jobs REST API/CLI can trigger runs
    - B. Build the job entirely by clicking through the Jobs UI in each workspace and export screenshots into the repo for reproducibility
    - C. Use only the Jobs REST API `runs/submit` endpoint, which permanently persists the job definition and schedule in source control automatically
    - D. Store the job as a Git Folder so that its tasks, schedule, and cluster config are version-controlled along with code

18. A pytest test factors a transformation as `actual = src.transform(with_flags)` and asserts `assertDataFrameEqual(actual, expected)`. The test intermittently fails even though the rows look identical: sometimes a row-order difference, sometimes tiny differences in a computed `double` column. Which statement correctly describes the defaults and the right fix?
    - A. `assertDataFrameEqual` ignores row order by default (`checkRowOrder=False`) and compares floats with tolerances (`rtol=1e-5`, `atol=1e-8`); the float failures mean the computed doubles drift beyond tolerance, so widen `rtol`/`atol`
    - B. `assertDataFrameEqual` checks row order by default, so the test must pre-sort both DataFrames; floats are compared exactly and cannot be tolerated
    - C. `assertDataFrameEqual` only compares schemas; use `assertSchemaEqual` to also compare row data
    - D. `DataFrame.transform` is non-deterministic, so transformations must never be unit-tested with `assertDataFrameEqual`

## Answers & Explanations

1. **A** — Databricks' scalable-structure guidance is to minimize business logic in notebooks: put core logic in importable modules under `src/` (or `src/py/`), keep notebooks as thin orchestration/visualization layers, and run pytest from outside the notebook. Only then can functions be imported and unit-tested off-cluster. B confuses orchestration looping with testability. C is about deployment presets/UI editability, unrelated to testing. D raises driver REPL memory, not test coverage; tests should live outside notebooks. (Objective: S1 — scalable Python project structure for DABs)

2. **A** — The `production` preset requires an explicit `workspace.host` **and** `root_path` unless `run_as` is set to a service principal; it also validates that `run_as`/`permissions` are specified and that paths are not overridden to a specific user. A user-name run-as plus only host trips validation — supply `root_path` or use a service-principal run-as. B is fabricated (defaults are unrelated to mode). C is false — production deploys fine via CLI/CI. D is backwards — production with a service-principal run-as is exactly the recommended path. (Objective: S1 — DAB deployment modes: development vs production presets)

3. **A** — `bundle generate job --existing-job-id` reverse-engineers YAML from the existing job; `bundle deployment bind` links the bundle resource key to that job's id so the next `deploy` *updates* it instead of creating a duplicate (docs warn that a plain deploy of generated config creates a new resource). B is wrong — bundles key on resource identity, not the UI job name. C needlessly destroys the production job and its run history. D is false; DABs explicitly support adopting existing jobs/pipelines/dashboards via generate + bind. (Objective: S1 — DAB lifecycle and adopting existing resources)

4. **A** — Git Folders source-control only code files; job/pipeline/schedule/cluster configuration is not captured. DABs version both code and resource configuration together, making jobs + schedules reproducible across workspaces — the recommended full CI/CD path. B and C are fabricated limitations. D is false: Git Folders do not version schedules or cluster configs. (Objective: S1 — DABs vs Git Folders for CI/CD)

5. **A** — Per the cluster-libraries docs: "When you install a library on a cluster, a notebook already attached to that cluster will not immediately see the new library. You must start a new session for the notebook to see the new library" (detach/reattach or restart). B misstates the mechanism (a `%pip` reinstall is unnecessary). C is false — PyPI is a supported cluster-library source. D conflates Unity Catalog batch-UDF isolation with library visibility. (Objective: S1 — third-party library scope and troubleshooting)

6. **A** — Serverless tasks have no cluster Libraries tab; dependencies are installed through the notebook **Environment** side-pane / base-environment YAML (or `%pip`). A local wheel is referenced from a Unity Catalog volume path (`/Volumes/<catalog>/<schema>/<volume>/<file>.whl`) and PyPI packages by pinned name. B is wrong — there is no cluster to attach to. C is wrong — DBFS-root installs are "Not recommended" (files in DBFS root are modifiable by any workspace user). D misuses destroy/deploy and the artifacts mapping. (Objective: S1 — library sources for serverless / reproducibility)

7. **A** — Pandas (vectorized) UDFs use Apache Arrow to transfer data in record batches (default 10,000 rows via `spark.sql.execution.arrow.maxRecordsPerBatch`) and process them with pandas, amortizing serialization across thousands of rows — documented as up to ~100× faster than a row-at-a-time Python UDF. B is false: a Python worker process is still involved (only built-in/SQL/Scala functions run natively in the JVM). C and D invent mechanisms unrelated to UDF execution. (Objective: S1 — Pandas UDFs vs Python UDFs performance mechanism)

8. **A** — For grouped Pandas operations (grouped-aggregate / `groupBy().applyInPandas`), "all data for a group is loaded into memory before the function is applied. This can lead to out of memory exceptions, especially if the group sizes are skewed," and the `maxRecordsPerBatch` limit "is not applied on groups." So large groups OOM; fix by using a built-in aggregate or de-skewing. B is wrong — the batch-size config governs scalar batches, not whole-group loading. C raises driver REPL memory (notebook-task-only), not executor heap. D conflates a DataFrame-equality test parameter with UDF execution. (Objective: S1 — Pandas UDF grouped-aggregate OOM risk)

9. **A** — Per the If/else docs: the `==` and `!=` operators perform **string** comparison (`12.0 == 12` evaluates to false; a float `0.0` serializes to `"0.0"`, which is not `"0"`), while `>`, `>=`, `<`, `<=` perform numeric comparison. Use a numeric operator such as `<= 0`/`> 0`. B is wrong — `==`/`!=` are supported. C is false — task values, job parameters, and dynamic values are all valid operands. D is false — If/else condition tasks need no compute. (Objective: S1 — If/else task numeric vs string comparison)

10. **A** — For each inputs are size-limited: the Inputs text box is ~5,000 characters and a task-value reference resolves to a value up to ~48 KB; passing full per-row config blobs exceeds these limits and iterations are silently dropped/truncated. The documented metadata-driven fix is to pass small keys through the For each and have the nested task look up the heavy config (e.g., from a JSON file or table). B's 100-iteration cap is fabricated. C is wrong — a For each task cannot be nested inside another For each. D misstates concurrency, which controls parallelism, not whether iterations run (default concurrency is 1). (Objective: S1 — For each task limits and metadata-driven looping)

11. **A** — `Run if` dependencies branch on upstream task **status**; valid conditions include "All succeeded," "At least one succeeded," "None failed," "All done," "At least one failed," and "All failed." "At least one failed" runs a task only when an upstream dependency fails — exactly the failure-only cleanup pattern. B is wrong — If/else branches on values, not run status, and there is no standard exit-code operand. C is iteration, not error handling. D — auto-optimization retries are unrelated to running a cleanup task on failure. (Objective: S1 — Run if vs If/else, branching on upstream status)

12. **A** — Per the serverless docs, the high-memory setting (Standard 16 GB / High 32 GB) "increases the size of the REPL memory used when running code in the notebook. It doesn't affect the memory size of the Spark session." A `toPandas()` collect loads all data into driver memory, so raising REPL memory fixes local-Python OOM. High memory is notebook-task-only. B is the classic misconception (it does not change Spark executor/session memory). C and D conflate unrelated features (deletion vectors; auto-optimization retries). (Objective: S1 — serverless high-memory: REPL vs Spark session)

13. **A** — Serverless auto-optimization "automatically optimizes the compute... and retries failed tasks" (at-least-once), which double-writes a non-idempotent `INSERT`. To enforce at-most-once, open the task's **Retry Policy** dialog and uncheck **Enable serverless auto-optimization (may include additional retries)**. B is a fabricated Spark conf for this purpose. C is wrong — production mode does not disable retries. D is unrelated to retry semantics. (Objective: S1 — disallow retries for non-idempotent jobs)

14. **A** — A materialized view holds the result of its defining query and is refreshed (full recompute, or incremental on serverless when cheaper) to reflect current source state — the right fit for a gold aggregation queryable as a table. A streaming table processes new records/files incrementally, each input exactly once — the right fit for append-only ingestion; the docs explicitly recommend streaming tables (not MVs) where records should be processed only once. B inverts both. C and D state false limitations (both are queryable tables; MVs can aggregate over history). (Objective: S1 — streaming tables vs materialized views tradeoffs)

15. **A** — The AUTO CDC / APPLY CHANGES API (`FLOW AUTO CDC ... KEYS (...) SEQUENCE BY seq_num`, optionally `APPLY AS DELETE WHEN ...`, `STORED AS SCD TYPE 1|2`) writes to a streaming-table target and "automatically handles out-of-order records by processing events in the order defined by the sequencing column," applying upserts and deletes without hand-written `MERGE`. B is wrong: MV refresh does not perform CDC dedup by key. C is an anti-pattern (per-record MERGE in a loop). D is a UDF, not a CDC mechanism, and would not maintain deletes/state. (Objective: S1 — APPLY CHANGES / AUTO CDC for CDC ingestion)

16. **A** — When you need standalone imperative control — a custom `streamingDF.writeStream.foreachBatch(...)` sink to an external system, manual `checkpointLocation` management, and arbitrary trigger intervals — use Spark Structured Streaming directly. SDP abstracts orchestration, checkpoints (managed per flow), and retries declaratively. (SDP does expose a ForEachBatch sink, but it runs inside managed pipeline orchestration with pipeline-managed checkpoints, so it is not the fully-standalone imperative path described.) B inverts the abstraction level. C and D confuse `foreachBatch` (a Structured Streaming sink API) with MV refresh policies and job control-flow loops. (Objective: S1 — Spark Structured Streaming vs SDP)

17. **A** — DABs are the recommended way to define a job's full configuration as code — its `resources.jobs` keys mirror the Jobs REST create payload — deploy reproducibly across dev/prod targets, and trigger runs via `bundle run` or the Jobs REST API/CLI. B is not reproducible automation. C is wrong — `runs/submit` launches a one-off run and does not persist a versioned job definition. D is wrong — Git Folders version only code, not job/schedule/cluster config. (Objective: S1 — automate ETL via Jobs UI/API/CLI/DABs)

18. **A** — `assertDataFrameEqual` defaults to `checkRowOrder=False` (order-insensitive comparison) and compares floating-point values using relative/absolute tolerances (`rtol=1e-5`, `atol=1e-8` by default). Therefore a genuine row-order difference would not fail by default, and the intermittent `double` mismatches indicate the computed values drifted beyond tolerance — widen `rtol`/`atol`. B inverts both defaults. C swaps roles — `assertDataFrameEqual` compares schema **and** data; `assertSchemaEqual` is schema-only. D is false; `DataFrame.transform` just chains DataFrame→DataFrame functions and is fully testable. (Objective: S1 — unit testing with assertDataFrameEqual / transform)

---

# 2. Data Ingestion & Acquisition — Practice MCQs (7%)

1. A team has two new ingestion requirements. Source 1 is a continuously growing folder of CSV files landing in an S3 bucket; source 2 is a real-time clickstream published to an Apache Kafka topic. They want incremental, exactly-once ingestion into separate Delta tables with minimal custom code. Which approach correctly maps each source to a supported Databricks ingestion mechanism?

   A. Use Auto Loader (`cloudFiles`) for the S3 CSV folder, and Spark Structured Streaming with the `kafka` source for the Kafka topic.
   B. Use Auto Loader (`cloudFiles`) for both sources, setting `cloudFiles.format` to `kafka` for the Kafka topic.
   C. Use `COPY INTO` for the S3 CSV folder, and Auto Loader (`cloudFiles`) for the Kafka topic.
   D. Use Spark Structured Streaming with the `kafka` source for both, pointing the file path option at the S3 bucket for the CSV folder.

2. An engineer reads a folder of scanned PDF documents for a downstream OCR job using Auto Loader: `spark.readStream.format("cloudFiles").option("cloudFiles.format", "binaryFile").load(path)`. Which statement about the resulting DataFrame is correct?

   A. The DataFrame has a fixed schema of `path`, `modificationTime`, `length`, and `content`, where `content` holds the raw file bytes; no OCR or text parsing is performed.
   B. The DataFrame parses each PDF into structured text columns automatically, since `binaryFile` performs document text extraction before loading.
   C. The DataFrame contains only a single `value` string column holding the file path; the bytes must be fetched in a later step.
   D. The schema is inferred per file, so PDFs with different internal structures produce different column sets in the same DataFrame.

3. An engineer must incrementally ingest XML order files from cloud storage, where each `<order>` element should map to one row. They start: `spark.readStream.format("cloudFiles").option("cloudFiles.format", "xml").load(path)`. The stream fails to produce the expected one-row-per-order structure. What is the most likely fix?

   A. Specify the `rowTag` option (e.g., `.option("rowTag", "order")`) so Auto Loader knows which XML element maps to a DataFrame row.
   B. XML is not a supported Auto Loader format; switch to converting the files to JSON before ingestion.
   C. Add `.option("multiLine", "true")`, which is what defines the per-row element boundary for XML.
   D. Set `.option("cloudFiles.format", "text")` and parse the XML manually with a UDF, since `cloudFiles` cannot read XML.

4. A streaming job reads from Kafka and writes to a Delta table that downstream consumers stream from. Requirements: append-only semantics, exactly-once delivery, and the ability to resume after a cluster restart without duplicating or losing records. Which `writeStream` configuration meets all three?

   A. `.writeStream.outputMode("append").option("checkpointLocation", "/path/_checkpoints").toTable("catalog.schema.events")`
   B. `.writeStream.outputMode("complete").toTable("catalog.schema.events")` with no checkpoint, relying on Delta's transaction log for recovery.
   C. `.write.mode("append").saveAsTable("catalog.schema.events")` inside a `foreachBatch` loop with manual offset tracking in a Python list.
   D. `.writeStream.outputMode("update").option("checkpointLocation", "/path/_checkpoints").toTable("catalog.schema.events")`

5. An engineer is incrementally ingesting a folder of files with Auto Loader and wants to avoid defining or maintaining a schema manually while keeping schema-inference cost low. The same logical data is available in two layouts in the landing zone: CSV and Parquet. Which choice and reasoning is correct?

   A. Ingest the Parquet files; Parquet embeds its schema and column types in the file metadata, so Auto Loader reads types directly rather than inferring CSV columns as strings (or sampling).
   B. Ingest the CSV files; CSV is self-describing and carries explicit data types, so no inference is needed.
   C. Either is identical for schema handling, because Auto Loader always requires an explicit `cloudFiles.schemaHints` map regardless of format.
   D. Ingest the CSV files, because Auto Loader cannot infer schema from Parquet and requires a user-supplied schema for all columnar formats.

6. An Auto Loader stream ingesting from cloud storage is healthy at low volume, but the source directory now receives millions of new files per hour and directory-listing latency dominates each micro-batch. The engineer wants Auto Loader to discover new files without repeatedly listing the entire directory. Which configuration addresses this, and what is its scope?

   A. Use file notification mode (e.g., `cloudFiles.useNotifications=true`, or file events on the external location), which subscribes to cloud-storage file events via a notification/queue service and scales to millions of files per hour — and it applies only to cloud object storage sources.
   B. Switch the stream to a Kafka source, since file notification mode is implemented on top of Kafka topics under the hood.
   C. Increase `cloudFiles.maxFilesPerTrigger`; directory listing mode is already the most scalable discovery method and notification mode does not exist.
   D. Set `cloudFiles.backfillInterval` to `0` to disable all directory listing, which is what enables event-based discovery without any notification service.

## Answers & Explanations

1. **A** — Auto Loader (`cloudFiles`) ingests incrementally from cloud object storage only (S3, ADLS, GCS, UC volumes, Blob); its `cloudFiles.format` accepts exactly `avro`, `binaryFile`, `csv`, `json`, `orc`, `parquet`, `text`, `xml` — never `kafka`. Message buses are read with Structured Streaming's native `kafka` source (`readStream.format("kafka")`), which provides exactly-once delivery into Delta via a checkpoint. B and C invent a Kafka capability Auto Loader does not have; D misuses the `kafka` source for object storage. *(Objective: S2 Data Ingestion — choosing the correct ingestion mechanism per source type)*

2. **A** — The `binaryFile` data source "reads binary files and converts each file into a single record containing the file's raw content and metadata," producing a fixed schema of `path (StringType)`, `modificationTime (TimestampType)`, `length (LongType)`, and `content (BinaryType)`. It does no parsing or OCR — `content` is the raw bytes. B is wrong (no text extraction). C is wrong (there is a `content` column, not just a path). D is wrong: `binaryFile` is a fixed-schema format (it is explicitly listed as "Not applicable (fixed-schema)" for schema inference/evolution), so all files share one schema. *(Objective: S2 Data Ingestion — ingest Binary from cloud storage; binaryFile output schema)*

3. **A** — Native XML is a supported Auto Loader format in Databricks Runtime 14.3 LTS and above, but the row boundary is defined by the `rowTag` option, which identifies the element that becomes a DataFrame Row — without it the structure is wrong. B and D are false: XML is natively supported by `cloudFiles` with no external jar. C is wrong: `multiLine` does not define the per-row element for XML; `rowTag` does. *(Objective: S2 Data Ingestion — ingest XML from cloud storage; required rowTag option)*

4. **A** — Append-only streaming ingestion to Delta uses `outputMode("append")` (the default) plus a `checkpointLocation`; the checkpoint stores Kafka offsets and write progress, and the Delta transaction log "guarantees exactly-once processing," so the job resumes without duplicates or loss after a restart. B drops the checkpoint (no offset recovery) and `complete` is for full-result aggregations. C uses a non-streaming batch write with in-memory offsets that vanish on restart. D is invalid: per the docs, the Delta Lake sink supports append and complete modes but **not** update mode. *(Objective: S2 Data Ingestion — append-only streaming pipeline with Delta; exactly-once writes)*

5. **A** — Parquet (like ORC/Avro) encodes its schema and column types in the file metadata, so Auto Loader reads them directly. For formats that don't encode data types (JSON, CSV, XML), Auto Loader infers all columns as strings by default, and enabling type inference requires sampling files, which is costlier and error-prone. B reverses reality — CSV is text with no typed schema. C is false: `schemaHints` is optional. D is false: Auto Loader infers schema from Parquet via its metadata, no user schema required (Parquet schema inference is supported in DBR 11.3 LTS+). *(Objective: S2 Data Ingestion — columnar/self-describing formats; format-vs-schema tradeoff)*

6. **A** — Auto Loader defaults to directory listing mode; for high file volumes it offers file notification mode (classic `cloudFiles.useNotifications=true`, or the recommended file-events-on-external-location path), which "leverages file notification and queue services in your cloud infrastructure account" and "can scale Auto Loader to ingest millions of files an hour," avoiding repeated full listings. It is specific to cloud object storage. B is wrong — notification mode uses the cloud provider's native event service, not Kafka. C wrongly denies notification mode exists; `maxFilesPerTrigger` only caps batch size, not listing cost. D misuses `backfillInterval` (it schedules periodic backfill listings) and does not turn on event-based discovery. *(Objective: S2 Data Ingestion — incremental ingestion at scale; Auto Loader discovery mode selection)*

---

# 3. Data Transformation, Cleansing & Quality — Practice MCQs (10%)

1. An analyst writes the following Spark SQL to compute a daily running revenue total per store on a large fact table:

   ```sql
   SELECT store_id, sale_date, amount,
          SUM(amount) OVER (PARTITION BY store_id ORDER BY sale_date) AS running_total
   FROM sales;
   ```

   Multiple sales can occur on the same sale_date. The analyst expects running_total to accumulate row-by-row, but values for rows sharing the same sale_date all show the same (summed) total. Which explanation is correct?

   - A. Because no explicit frame was specified, Spark applies the default RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW, so all rows tied on sale_date are collapsed into the same cumulative value; switching to ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW gives the row-by-row accumulation.
   - B. Window aggregates ignore the ORDER BY clause entirely, so SUM is computed over the whole partition; an explicit ORDER BY inside the OVER clause is required to make it cumulative.
   - C. Spark SQL does not support cumulative SUM in window functions; the analyst must use a self-join on sale_date <= sale_date to get a running total.
   - D. The PARTITION BY clause forces a global aggregation; removing PARTITION BY and keeping only ORDER BY would produce the per-store running total.

2. A PySpark batch job joins a 4 TB transactions fact DataFrame to a 60 MB country_codes dimension DataFrame on country_id. The query profile shows a large shuffle (SortMergeJoin) and one straggler task. The cluster has ample driver and executor memory. Which single change most directly removes the shuffle for this size of dimension?

   - A. Wrap the small dimension in an explicit broadcast(country_codes) hint so it is sent to every executor and joined map-side, eliminating the shuffle of the 4 TB fact table.
   - B. Repartition both DataFrames by country_id with a high partition count so the SortMergeJoin tasks are evenly sized, which removes the shuffle.
   - C. Cache the 4 TB fact DataFrame before the join so the join reads from memory and skips the shuffle stage.
   - D. Convert the join to a crossJoin and filter on country_id afterward to avoid the shuffle introduced by the join key.

3. A join between two large tables on customer_id runs for hours; the Spark UI shows a handful of reduce tasks processing tens of GB each while most finish in seconds. Investigation reveals a few customer_id values (e.g., a 'GUEST' sentinel) account for most rows. Both tables are large, so broadcast is not viable. Which approach correctly mitigates the skew?

   - A. Rely on Adaptive Query Execution skew-join handling (which splits and, if needed, replicates skewed partitions into roughly evenly sized tasks) and/or salt the hot keys by appending a random suffix on the fact side and replicating those buckets on the dimension side.
   - B. Increase spark.sql.shuffle.partitions to a very large number, which guarantees the skewed key is spread evenly across the new partitions.
   - C. Add a coalesce(1) before the join so all data is processed in a single partition, removing the imbalance between tasks.
   - D. Replace the SortMergeJoin with a broadcast join of the larger table to bypass the shuffle entirely.

4. In a Lakeflow Spark Declarative Pipeline (SDP), a data engineer adds this constraint to a streaming table:

   ```python
   @dp.expect_or_fail("valid_amount", "amount > 0")
   ```

   During an update, a batch arrives containing some rows with amount <= 0. What is the documented behavior, and what should the engineer use instead if the goal is to keep the pipeline running while removing only the offending rows from the target?

   - A. expect_or_fail (ON VIOLATION FAIL UPDATE) fails the pipeline update when any record violates the constraint and atomically rolls back the transaction; to drop only the bad rows and continue, use expect_or_drop (ON VIOLATION DROP ROW).
   - B. expect_or_fail silently drops the violating rows and logs a metric; to instead halt the pipeline, the engineer should switch to expect_or_drop.
   - C. expect_or_fail writes violating rows to a _rescued_data column automatically; to fully reject them the engineer should use expect (the default) which deletes them.
   - D. expect_or_fail retains the bad rows but flags them; expect_or_drop is identical and only differs in the metric name reported in the event log.

5. Requirements: every incoming record must be persisted (none dropped or rejected), but downstream consumers should only read records passing all data-quality rules, while a separate review process reads the failing records. Using SDP expectations, which design implements this 'quarantine' pattern as documented by Databricks?

   - A. Materialize a (temporary) streaming table that tags each row with is_quarantined = NOT(all rules combined), then expose two views: a valid view filtering is_quarantined = false and an invalid view filtering is_quarantined = true.
   - B. Apply expect_or_drop for the rules on the target table; the dropped rows are automatically written to a sibling <table>_quarantine table that downstream review jobs can query.
   - C. Apply expect_or_fail and configure ON VIOLATION QUARANTINE so violating rows are routed to a quarantine table while valid rows continue to the target.
   - D. Set pipelines.quarantine = true in the pipeline settings so SDP creates separate good/bad tables automatically without writing any custom rule logic.

6. A classic (non-SDP) Structured Streaming job uses Auto Loader to ingest JSON files whose schema drifts over time. The team needs (1) records with unexpected/extra fields or type mismatches preserved rather than lost, and (2) genuinely malformed/corrupt JSON records isolated for inspection. Which configuration meets both needs?

   - A. Keep the default _rescued_data column to capture fields that don't match the current schema (wrong type, unknown column, case mismatch) as a JSON blob, and set badRecordsPath to capture incomplete/malformed JSON records.
   - B. Set mode = FAILFAST so the stream stops on the first bad record, then manually move the offending file to a quarantine folder for inspection.
   - C. Drop the _rescued_data column and rely solely on badRecordsPath, which captures both schema-mismatched fields and malformed records in one location.
   - D. Enable cloudFiles.inferColumnTypes = false so all columns load as strings, which removes the possibility of bad records entirely.

7. A PySpark transform must produce, for each customer_id, the single most recent event row (all columns) from a multi-billion-row events table that has an event_ts column. Which approach is the most efficient and correct on large data?

   - A. Use a window: ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY event_ts DESC) and filter rn = 1, which returns exactly one full row per customer even when timestamps tie.
   - B. GROUP BY customer_id and SELECT MAX(event_ts) along with the other columns directly, which returns the full latest row per customer in one shuffle.
   - C. Use dropDuplicates(['customer_id']) which is guaranteed to keep the row with the maximum event_ts for each customer_id.
   - D. Use FIRST(*) with a GROUP BY customer_id; FIRST always returns the row with the latest event_ts regardless of ordering.

8. A transform on a 2 TB Delta table currently does df.repartition(2000).filter("status = 'ACTIVE'").select(...). The query profile shows the full table being shuffled before the filter, and the filter eliminates ~95% of rows. The table has stats collected on status. Which change most improves efficiency?

   - A. Apply the filter first so predicate pushdown and Delta data skipping prune files before any shuffle, and drop the explicit repartition unless a later wide operation actually needs it.
   - B. Increase the repartition count to 8000 so the post-shuffle partitions are smaller and the filter runs faster on each.
   - C. Replace repartition with coalesce(2000) before the filter, which avoids the shuffle while keeping the same partition count.
   - D. Cache the DataFrame immediately after repartition so the shuffle only happens once across the whole job.

## Answers & Explanations

1. **A** — Per the Databricks Window reference, when ordering is defined but no frame is given, the default is a growing window frame: RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW. A RANGE frame is value-based — it includes all peer rows sharing the same ORDER BY value — so every tie on sale_date receives one identical cumulative total. Specifying ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW makes the frame positional (row offsets), giving a true row-by-row running total. B is wrong: ORDER BY is present and is exactly what makes the aggregate cumulative. C is wrong: Spark fully supports cumulative window SUM. D is wrong: removing PARTITION BY would accumulate across all stores and is not the cause of the tie behavior. *(Objective: S3 Transform/Quality — efficient Spark SQL/PySpark transforms, window functions)*

2. **A** — A broadcast hash join sends the small dimension to every executor and joins map-side, so the 4 TB fact table is never shuffled. The key correction: 60 MB exceeds both auto-broadcast defaults (static spark.sql.autoBroadcastJoinThreshold = 10 MB; Databricks AQE spark.databricks.adaptive.autoBroadcastJoinThreshold = 30 MB), so Spark will NOT auto-broadcast it — an explicit broadcast() hint is required, and per the Databricks Hints documentation the BROADCAST hint broadcasts the relation regardless of autoBroadcastJoinThreshold. B reduces skew within a SortMergeJoin but still shuffles the 4 TB fact table, which is exactly what we want to avoid. C caching does not change the join strategy; a SortMergeJoin still shuffles. D crossJoin produces a Cartesian explosion and is far worse. *(Objective: S3 Transform/Quality — efficient joins on large data, broadcast vs shuffle)*

3. **A** — Skew comes from too many rows hashing to one key, so they all land in one partition. Per the Databricks AQE documentation, skew-join handling dynamically splits oversized skewed partitions (replicating the matching side as needed) into roughly evenly sized tasks for sort merge join and shuffle hash join. Salting — appending a random bucket suffix to the hot key on the fact side and replicating those buckets on the dimension side — manually spreads one hot key across many partitions; the Databricks best-practices guidance explicitly recommends salting highly-skewed keys. B fails because all rows with the same key still hash to the same partition regardless of partition count. C coalesce(1) makes it strictly worse (single task). D broadcasting a large table will OOM the executors and is not viable here. *(Objective: S3 Transform/Quality — efficient transforms on skewed joins, salting / AQE skew handling)*

4. **A** — Per the Databricks expectations documentation, expect_or_fail maps to ON VIOLATION FAIL UPDATE: it stops execution immediately when a record fails validation and, for a table update, atomically rolls back the transaction; because the update fails, per-record metrics are not recorded. To keep the pipeline running while removing only the violating rows from the target, use expect_or_drop (ON VIOLATION DROP ROW), which drops the bad rows and continues, logging the dropped count. B inverts the two operators. C is wrong: _rescued_data is an Auto Loader feature, not an expectation action, and the plain expect operator retains (does not delete) bad rows. D is wrong: expect (warn, the default) keeps violating rows while expect_or_drop removes them — a material difference, not just a metric name. *(Objective: S3 Transform/Quality — quarantine bad data in SDP, expectations + ON VIOLATION)*

5. **A** — The documented SDP quarantine pattern ingests ALL rows into a single (temporary) streaming table partitioned by is_quarantined, adds an is_quarantined column computed as NOT(all rules combined) — i.e., the inverse of the AND of the expectation constraints — then defines two filtered views: valid (is_quarantined = false) and invalid (is_quarantined = true). This keeps every record while separating the consumption paths. B is wrong: expect_or_drop discards rows; it does not auto-write them to a quarantine table. C is wrong: there is no ON VIOLATION QUARANTINE action — the only actions are warn (EXPECT), drop (DROP ROW), and fail (FAIL UPDATE). D is wrong: there is no pipelines.quarantine setting that auto-splits tables. *(Objective: S3 Transform/Quality — quarantine bad data in SDP, inverted-rule quarantine pattern)*

6. **A** — Per the Auto Loader schema documentation, the _rescued_data column (added automatically when the schema is inferred) captures any field that doesn't match the current schema — wrong type, unknown/missing column, or case mismatch — as a JSON blob with the source file path, satisfying need (1). The badRecordsPath option captures incomplete/malformed JSON or CSV records that cannot be parsed at all, satisfying need (2). The docs state the two are complementary: when rescuedDataColumn is in use, data type mismatches are NOT treated as bad records, so only genuinely corrupt records go to badRecordsPath. B FAILFAST halts the entire stream rather than quarantining. C is wrong: badRecordsPath does not capture mere type/schema mismatches when rescuedDataColumn is used; those go to _rescued_data. D loading as strings does not eliminate corrupt/unparseable records and discards type information. *(Objective: S3 Transform/Quality — quarantine bad data in Auto Loader classic jobs)*

7. **A** — ROW_NUMBER() partitioned by customer_id and ordered by event_ts DESC assigns rank 1 to the latest row; filtering rn = 1 returns exactly one complete row per customer, with ties broken deterministically by ROW_NUMBER. B is invalid SQL semantics: you cannot select arbitrary non-aggregated columns alongside MAX(event_ts) and get the matching row's values without a join or window. C dropDuplicates keeps an arbitrary row per key, not the latest. D FIRST without an explicit ordered window returns a non-deterministic row, not necessarily the latest. *(Objective: S3 Transform/Quality — efficient aggregations on large data, deduplication semantics)*

8. **A** — repartition() is a wide transformation that shuffles the entire 2 TB before the filter even runs, materializing data the filter then discards. Filtering first lets Spark push the predicate down and lets Delta data skipping prune files using the min/max statistics collected on status (Delta collects stats on the first 32 columns by default), so ~95% of data is eliminated before any expensive shuffle. The explicit repartition should be removed unless a downstream wide operation actually needs that layout. B shuffles even more data. C coalesce on 2 TB into 2000 partitions still forces data movement and still happens before the filter. D caching a needless shuffle just pays the cost once instead of removing it. *(Objective: S3 Transform/Quality — efficient Spark transforms, avoiding wide vs narrow misuse)*

---

# 4. Data Sharing & Federation — Practice MCQs (5%)

1. Your team manages a Unity Catalog (UC) metastore and needs to share a Delta table, a UC volume of reference images, and a registered ML model with a partner company. The partner also runs on Databricks with their own UC metastore. You want the most secure, lowest-maintenance setup with no credential files to rotate. Which approach should you use, and what does it support?

   A. Create a Databricks-to-Databricks (D2D) share and add the recipient by their UC sharing identifier (`<cloud>:<region>:<uuid>`); this avoids exchanging bearer tokens and supports sharing tables, volumes, models, and notebooks.
   B. Create an open-protocol (D2O) recipient and email them the activation URL; D2D is only for tables, so volumes and models require the open protocol.
   C. Create a D2D share, but volumes and models cannot be shared via Delta Sharing at all, so share only the table and copy the volume and model manually.
   D. Create a D2D share and generate a long-lived bearer token for the partner's metastore, since even Databricks-to-Databricks recipients authenticate with downloaded credential files.

2. A pandas-based analytics consultancy that does NOT use Databricks (no Unity Catalog metastore) must read a shared Delta table from your lakehouse using open-source Delta Sharing connectors. As the provider, which sequence correctly establishes this access under the open sharing protocol (bearer-token flow)?

   A. Create an open recipient (authentication type `TOKEN`), which generates a one-time activation URL the recipient opens to download a credential file containing the sharing endpoint and a bearer token; they then read the share with the open Delta Sharing connector.
   B. Add the consultancy to the share using their Unity Catalog sharing identifier, then have them attach the share as a foreign catalog in their own metastore.
   C. Enable Lakehouse Federation, create a connection to the consultancy's warehouse, and push the table to them via a foreign catalog.
   D. Create an open recipient and grant them a Databricks personal access token (PAT) scoped to your workspace; the consultancy uses the PAT with the Databricks SQL connector.

3. Analysts need to join customer dimension data living in an external PostgreSQL database against Delta fact tables in your lakehouse, with UC row filters and column masks enforced, and without running an ingestion pipeline to copy the Postgres data. Some analysts also want to UPDATE a few corrected rows back in Postgres from Databricks. Which statement accurately describes what Lakehouse Federation provides here?

   A. Create a connection and a foreign catalog over the PostgreSQL database; analysts can query it through Unity Catalog (with row/column controls and query pushdown) without copying data, but foreign tables accessed through federation are read-only, so the UPDATEs back to Postgres are not supported.
   B. Create a foreign catalog; both federated reads and writes (INSERT/UPDATE/DELETE) flow through Unity Catalog to PostgreSQL, so the corrected rows can be written back directly.
   C. Lakehouse Federation cannot enforce row filters or column masks on foreign tables, so you must first ingest the Postgres data into a managed Delta table to apply governance.
   D. Lakehouse Federation does not support PostgreSQL; you must use Delta Sharing's open protocol to read the Postgres tables.

4. Two Databricks organizations each have their own Unity Catalog metastore. Org B's data scientists need read-only access to several large Delta tables that physically live in Org A's lakehouse. Org A wants Org B to read the actual Delta data directly (no per-query round-trip through Org A's compute) and to be able to time-travel and run Structured Streaming reads on the tables. Which option best fits this requirement?

   A. Use Delta Sharing (D2D) and share the tables WITH HISTORY, so Org B reads the Delta data directly and can perform time travel and Structured Streaming reads.
   B. Use Lakehouse Federation: have Org B create a foreign catalog pointing at Org A's metastore, since federation is the recommended way to get read-only access to tables in a different metastore.
   C. Use Lakehouse Federation so all of Org B's reads execute on Org A's SQL warehouse, preserving a single point of governance and the ability to stream.
   D. Copy the tables into Org B's metastore with a scheduled job, because cross-metastore live access is not supported by either Delta Sharing or Lakehouse Federation.

5. You share a high-volume Delta orders table with a recipient via Delta Sharing. The recipient currently re-reads the entire table on every refresh to detect new and updated rows, which is slow and expensive. You want them to consume only the incremental changes instead, without you replicating or exporting the data. Which provider-side action enables this?

   A. Enable Change Data Feed (CDF) on the source Delta table BEFORE you share it WITH HISTORY; the recipient can then read only inserts/updates/deletes via the `table_changes()` function (or `readChangeFeed`) instead of full snapshots.
   B. Switch the share from Delta Sharing to a nightly batch export of CSV diffs so the recipient ingests only changed rows.
   C. Convert the table to a materialized view before sharing; materialized views automatically stream only changed rows to Delta Sharing recipients.
   D. Recipients of a Delta Sharing table cannot read change data feeds; CDF is only available to consumers inside the provider's own metastore.

6. After creating a foreign catalog over a Snowflake source via Lakehouse Federation, a data engineer runs: `SELECT region, SUM(amount) FROM snowflake_cat.sales.orders WHERE order_date >= '2026-01-01' GROUP BY region`. They notice the cluster pulls far fewer rows than the full table size. Which statement best explains the behavior and the governance model?

   A. Lakehouse Federation pushes supported predicates and aggregations down to Snowflake so filtering/aggregation happens at the source, reducing data transferred; UC still governs access with lineage and table-level row/column controls on the foreign tables.
   B. Federation always copies the entire foreign table into the cluster first, so the reduced row count must be caused by Delta data skipping on a local cache, not by pushdown.
   C. Pushdown means the query result is materialized as a managed Delta table in Unity Catalog automatically, which is why fewer rows are scanned on subsequent runs.
   D. Because federation runs the query, Unity Catalog cannot apply lineage or access controls to Snowflake foreign tables; governance must be enforced inside Snowflake only.

## Answers & Explanations

**1. A** — *(Objective: S4 — Delta Sharing D2D: recipient identity model and supported asset types)*
D2D sharing is used when the recipient also has a UC metastore. The provider adds the recipient by their sharing identifier — a string of the form `<cloud>:<region>:<uuid>` (e.g. `aws:eu-west-1:b0c978c8-...`), obtained by the recipient via `SELECT CURRENT_METASTORE()` or Catalog Explorer. Authentication runs over the secure UC-to-UC channel with no token exchange or credential file to rotate, which is the security/maintenance advantage over the open protocol. Per docs, "Databricks-to-Databricks also supports notebook, volume, and model sharing, which is not available in Databricks-to-Open sharing," so D2D is the only mode that shares these non-tabular assets. B is wrong: D2D supports volumes and models, and the open protocol is the one that uses an activation URL/credential file. C is wrong: volumes and models ARE shareable via D2D. D describes the open-protocol (D2O) bearer-token model, not D2D — token-based credential files are exactly what D2D avoids.

**2. A** — *(Objective: S4 — Delta Sharing D2O open protocol to external/non-Databricks platforms)*
Open-protocol (D2O) sharing targets recipients not on Databricks. With no UC metastore (and thus no sharing identifier), the provider creates an open recipient — created with `authentication_type` of `TOKEN` — which produces a single-use activation URL; opening it downloads a credential file holding the Delta Sharing endpoint URL and a bearer token. Open connectors (pandas, Apache Spark, Power BI, etc.) use that profile to read the share, which is read-only. (Docs note an OIDC token-federation flow as an alternative to bearer tokens, but the bearer-token credential-file flow in A is the canonical open-sharing path and is fully correct.) B is the D2D flow and requires the recipient to have a UC metastore/sharing identifier — they don't. C describes Lakehouse Federation, an inbound query-virtualization feature, not outbound sharing, and federation does not "push" tables to recipients. D conflates credential models: open recipients use a Delta Sharing bearer token in a credential profile, not a Databricks workspace PAT against the Databricks SQL connector.

**3. A** — *(Objective: S4 — Lakehouse Federation: governed read-only access to external sources via foreign catalogs)*
Lakehouse Federation provides "governed, read-only access to external data through Unity Catalog foreign catalogs, with automatic query pushdown and fine-grained access controls at the table level." You create a connection plus a foreign catalog mirroring the PostgreSQL database (a supported source) inside UC, giving in-place querying with predicate/query pushdown — no ETL copy required — and UC table-level row filters and column masks apply to foreign tables. Crucially, "all foreign tables accessed through Lakehouse Federation are read-only" (the only write exception is catalog federation over an *internal* federated Hive metastore — not PostgreSQL query federation), so the requested UPDATEs back to Postgres are not supported via federation. B is wrong because PostgreSQL federation is read-only. C is wrong: federation supports UC row/column controls on foreign tables, so a pre-ingestion copy is unnecessary for governance. D is wrong: PostgreSQL is a supported federation source, and Delta Sharing is for sharing data out, not connecting to an external operational database.

**4. A** — *(Objective: S4 — Choosing Delta Sharing vs Lakehouse Federation for cross-metastore Databricks access)*
The Databricks-to-Databricks Lakehouse Federation doc states explicitly: "If you want read-only access to data in a Databricks workspace attached to a different Unity Catalog metastore, whether in your Azure Databricks account or not, OpenSharing [Delta Sharing] is a better choice. There is no need to set up Lakehouse Federation." D2D lets Org B read the underlying Delta data directly, and sharing WITH HISTORY enables time travel (`VERSION AS OF` / `TIMESTAMP AS OF`) and Spark Structured Streaming reads on the share. B inverts the guidance — D2D Federation is recommended only for another workspace's Hive/Glue metastore, and it does not let the recipient read the Delta files directly. C contradicts the "no per-query round-trip through Org A's compute" requirement (federation pushes queries to the remote system). D is false — both features provide live cross-boundary access without copying.

**5. A** — *(Objective: S4 — Sharing live data without replication; incremental consumption via Change Data Feed)*
Delta Sharing shares live data in place with no replication. Per the ALTER SHARE / create-share docs: "If, in addition to doing time travel queries and streaming reads, you want your recipients to query a table's change data feed (CDF) using the `table_changes()` function, you must enable CDF on the table before you share it WITH HISTORY." The recipient then pulls only inserts/updates/deletes since their last read via `table_changes('catalog.schema.table', startVersion, endVersion)` or `.option("readChangeFeed", "true")`, avoiding full-snapshot re-reads. Order matters: CDF must be enabled on the source table *before* the WITH HISTORY share. B abandons live sharing for an export pipeline (replication), which the requirement forbids. C is fabricated — materialized views don't auto-stream CDF to recipients and aren't required for incremental sharing. D is false: CDF over Delta Sharing is explicitly supported for recipients once CDF is enabled and the table is shared WITH HISTORY.

**6. A** — *(Objective: S4 — Lakehouse Federation governance scope and pushdown behavior across supported sources)*
Lakehouse Federation translates Databricks SQL and pushes supported operations — predicates (the WHERE filter) and aggregations (GROUP BY/SUM) — down to the source (Snowflake, a supported source with aggregation/join pushdown GA), so filtering and aggregation execute remotely and only the smaller result set crosses the wire (verifiable via `EXPLAIN FORMATTED`). This is the core performance/cost mechanism and explains the reduced row volume. Governance is unified: UC applies lineage, tags, and table-level row/column controls to foreign tables. B is wrong — federation does NOT copy the whole table locally (that is the opposite of pushdown), and result/disk caching is not even supported for federated queries. C is wrong — federated reads are not auto-materialized into managed Delta tables. D is wrong — UC DOES extend governance and lineage to foreign tables; that is a stated benefit of federation.

---

# 5. Monitoring & Alerting — Practice MCQs (10%)

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

---

# 6. Cost & Performance Optimisation — Practice MCQs (13%)

1. A team owns 200+ Delta tables in Unity Catalog. Engineers currently run nightly OPTIMIZE and VACUUM jobs on a dedicated job cluster, and they keep tuning ZORDER columns by hand as query patterns drift. Leadership wants to cut both the maintenance-engineering time and the standing compute cost of these jobs without degrading query performance. The tables are UC managed tables. Which approach best meets this goal?
   - A. Convert the tables to external tables and schedule OPTIMIZE/VACUUM through an external orchestrator so the maintenance compute is billed separately and can be turned off on weekends
   - B. Enable predictive optimization for the catalog so Databricks automatically runs OPTIMIZE and VACUUM on the managed tables when beneficial, and remove the hand-rolled maintenance jobs
   - C. Increase the nightly job cluster's autoscaling maximum so OPTIMIZE finishes faster and the cluster terminates sooner, lowering the per-run cost
   - D. Disable Delta statistics collection on the tables to make writes cheaper, then rely solely on ZORDER to preserve read performance

2. A compliance pipeline issues many small, scattered single-row DELETE and UPDATE statements against a large Delta table throughout the day (e.g., DELETE FROM events WHERE event_id = ?). Each statement is slow and produces large data churn. Performance traces show that each delete rewrites entire multi-hundred-MB Parquet files even though only one row changed. Which change most directly removes this write amplification?
   - A. Enable deletion vectors on the table so DELETE/UPDATE/MERGE mark rows as soft-deleted in a side file instead of rewriting the whole Parquet file
   - B. Run OPTIMIZE with ZORDER on event_id before the deletes so the affected rows are colocated into a single small file that is cheap to rewrite
   - C. Lower spark.databricks.delta.optimize.maxFileSize so all Parquet files are tiny, making any single-file rewrite inexpensive
   - D. Switch the table to partitioned-by-event_id layout so each delete only touches one partition directory

3. A fast-growing fact table is currently partitioned by transaction_date. Analysts increasingly filter by customer_id and region instead of by date, and the partition-by-date layout now causes severe data skew (holiday spikes) and many small files. The team wants a layout that adapts to the new access patterns without a costly full rewrite, and that they can re-tune again later as query patterns keep changing. Which choice best fits?
   - A. Re-partition the table by customer_id, since it is the new dominant filter column
   - B. Enable liquid clustering on customer_id and region; clustering keys can be redefined later without rewriting existing data, and it is self-tuning and skew-resistant
   - C. Keep the date partitioning and add ZORDER BY (customer_id, region) on top of it to cover the new filters
   - D. Sub-partition by (transaction_date, region) to keep date pruning while adding region pruning

4. A query `SELECT * FROM orders WHERE order_amount > 5000` over a large Delta table reads nearly every data file even though only ~2% of rows qualify. The query profile shows 'files pruned: 0' and bytes read close to full table size. The table has no clustering or partitioning on order_amount. Which action most directly enables file pruning for this predicate?
   - A. Add liquid clustering on order_amount so per-file min/max statistics align with the predicate and let Delta skip files whose value range cannot match
   - B. Cache the table in the SQL warehouse memory so subsequent scans avoid reading from cloud storage
   - C. Rewrite the query to SELECT only the needed columns instead of SELECT *, which lets Delta prune the unqualified files
   - D. Increase the cluster size so the full scan completes faster within the SLA

5. A downstream Delta table must stay in sync with an upstream Delta table that receives a mix of inserts, updates, and deletes. The current job re-reads the entire upstream table on each run and overwrites the target, which is high-latency and expensive. A plain Structured Streaming read of the upstream Delta table also fails when upstream rows are updated/deleted (Structured Streaming accepts append-only input by default and throws on UPDATE/DELETE/MERGE/OVERWRITE). Which approach best addresses this?
   - A. Enable Change Data Feed on the upstream table and stream from its change feed (readChangeFeed=true), writing explicit handling for the insert/update/delete change types into the downstream table
   - B. Add .option('skipChangeCommits', 'true') to the streaming read; this will emit the deletes and updates as removal events the downstream can apply directly
   - C. Switch the streaming read to Trigger.AvailableNow and full-overwrite the target each micro-batch to guarantee correctness
   - D. Materialize the upstream as a streaming table and let it propagate row-level deletes automatically to all readers

6. In the query profile for a join between a 2-billion-row fact table and a 5,000-row dimension table, the profile shows a SortMergeJoin with a very large 'shuffle bytes written' on both sides and significant time in the exchange (shuffle) operators. The dimension table easily fits in memory. What does the profile most likely indicate, and what is the fix?
   - A. The optimizer chose a shuffle-based SortMergeJoin instead of broadcasting the tiny dimension table; broadcast the small side so it is shipped to executors and the shuffle of the fact table is avoided
   - B. The fact table needs ZORDER on the join key so the SortMergeJoin's sort phase is skipped
   - C. The shuffle indicates a data-skipping failure; collect statistics on the dimension table to enable file pruning during the join
   - D. The shuffle is caused by too few output files; run OPTIMIZE on both tables so the join reads fewer files and shuffles less

7. A heavy aggregation query meets its SLA most days but intermittently runs 4x slower. The query profile for the slow runs shows large 'spill (memory)' and 'spill (disk)' metrics on the aggregate and shuffle stages, while fast runs show none. Cluster size is unchanged. What is the most accurate read of this profile, and the most direct remedy?
   - A. Spill means Spark ran low on memory and moved intermediate data to disk; reduce per-task memory pressure (e.g., increase shuffle partitions / use a higher-memory instance or larger warehouse) so the working set fits in memory
   - B. Spill means data-skipping failed; add liquid clustering on the group-by keys to eliminate the spill
   - C. Spill is a normal sign of broadcast joins; disable broadcast joins to remove it
   - D. Spill indicates too many small input files; run OPTIMIZE so fewer, larger files are read and the spill disappears

8. A selective point-lookup query `SELECT * FROM sensor_readings WHERE device_id = 'A93'` scans the whole table. The query profile shows 'files read = total files, files pruned = 0' even though device_id is one of the table's clustering keys and the table was recently OPTIMIZEd. On inspection, the team finds that device_id is column #137 in a very wide table, and Delta collects min/max statistics only on the first 32 columns by default. What is the correct fix?
   - A. Reorder/select the columns so device_id falls within the statistics-collected leading columns (or raise delta.dataSkippingNumIndexedCols / set delta.dataSkippingStatsColumns), then re-run OPTIMIZE so per-file min/max stats exist for the predicate column to enable skipping
   - B. Switch device_id from a clustering key to a partition column so directory pruning replaces statistics-based skipping
   - C. Add a secondary index on device_id; Delta will use it to prune files at query time
   - D. Increase the SQL warehouse size so the full scan finishes within SLA, since wide tables cannot support data skipping

9. A team is enabling liquid clustering on a large events table to speed up its two dominant query shapes: filters on event_type (low cardinality, ~12 values) and filters on user_id (very high cardinality). They want one clustering configuration that improves data skipping for both predicates. Which configuration is the best starting point?
   - A. CLUSTER BY (event_type, user_id) so the layout colocates data for both common predicates and enables file pruning on either column
   - B. CLUSTER BY (event_type) only, because clustering is only effective on low-cardinality columns
   - C. Partition by event_type and ZORDER by user_id, combining both techniques for maximum pruning
   - D. CLUSTER BY a new monotonically increasing surrogate id so files are evenly sized, then rely on event_type for pruning

10. During a design review, a team must choose between Unity Catalog managed tables and external tables for a new analytics layer. A stated priority is minimizing ongoing operational/maintenance overhead and automatically getting storage-layout optimizations over time. Which statement correctly guides the decision?
    - A. Use managed tables: they are eligible for automatic features like predictive optimization (auto OPTIMIZE/VACUUM/ANALYZE), so Databricks handles layout maintenance and reduces operational overhead
    - B. Use external tables: only external tables can be optimized with OPTIMIZE and VACUUM, so they minimize maintenance work
    - C. It makes no difference; managed and external tables receive identical automatic optimization from Unity Catalog
    - D. Use external tables: managed tables cannot use liquid clustering, so external tables are required to keep layout tuned

11. A table has deletion vectors enabled. A GDPR request requires that specific deleted rows be physically removed from the underlying Parquet files (not merely logically hidden) so the bytes no longer exist on storage. The rows were already DELETEd (and are correctly invisible to queries) via deletion vectors. Which operation actually rewrites the files to physically remove the soft-deleted data?
    - A. REORG TABLE ... APPLY (PURGE), which rewrites data files to physically materialize the deletion-vector soft-deletes (followed by VACUUM to remove the old, now-unreferenced files)
    - B. A second DELETE statement on the same predicate, which forces a synchronous physical rewrite
    - C. Disabling deletion vectors on the table, which immediately purges all previously soft-deleted rows from storage
    - D. Setting the table's data retention to zero, which causes the next read to physically drop soft-deleted rows

12. A nightly Spark SQL job recomputes an aggregate summary by scanning the entire 5 TB source table every run, even though only ~0.1% of rows change daily. The cost and runtime are dominated by re-reading unchanged data. The team wants to process only the rows that changed since the last run to cut both latency and compute cost. Which capability most directly enables this incremental pattern?
    - A. Enable Change Data Feed on the source table and consume only the changed rows (by version range, via table_changes() or readChangeFeed) each run, so the job processes deltas instead of rescanning 5 TB
    - B. Add liquid clustering to the source table so the nightly full scan reads fewer files
    - C. Increase the job cluster size so the 5 TB scan completes within the latency target
    - D. Enable deletion vectors so the unchanged rows are skipped automatically during the full scan

## Answers & Explanations

1. **B** — Predictive optimization is the UC-managed-table feature that automatically runs maintenance operations (OPTIMIZE, VACUUM, ANALYZE) on managed tables when they are cost-justified, eliminating the standing maintenance jobs and the manual tuning effort. Per Microsoft Learn ("Predictive optimization for Unity Catalog managed tables" and "Best practices: Delta Lake"), Databricks recommends enabling it for all managed tables to reduce storage and compute costs, and it "eliminates the need to manually manage maintenance operations for Delta tables." A is wrong: external tables are *not eligible* for predictive optimization (it is unique to managed tables) and you remain responsible for maintaining/optimizing them. C only makes the manual jobs marginally faster and keeps a standing job. D is harmful: disabling statistics cripples data skipping/file pruning and degrades reads. *(Objective: S6 Cost & Performance — UC managed tables reduce ops overhead via predictive optimization)*

2. **A** — Deletion vectors are the Delta optimization built for exactly this pattern. Per Microsoft Learn ("What is predictive I/O?" / "Deletion vectors"), with deletion vectors enabled, DELETE/UPDATE/MERGE record affected rows as soft-deletes in a deletion-vector side file "rather than rewriting all records in a data file," eliminating the per-row file rewrite; the physical rewrite is deferred to a later OPTIMIZE/auto-compaction/REORG PURGE. B doesn't help: even colocated, the containing file is still fully rewritten on each delete, and ZORDER itself rewrites data. C trades write amplification for a flood of tiny files that wrecks read performance and metadata. D is a misconception — event_id is high-cardinality, so partitioning by it creates a tiny-partition/tiny-file explosion and is explicitly discouraged. *(Objective: S6 Cost & Performance — delta optimization via deletion vectors)*

3. **B** — Liquid clustering is purpose-built for changing access patterns and skew. Per Microsoft Learn ("Use liquid clustering for tables"): it "replaces table partitioning and ZORDER," you "can redefine clustering keys without rewriting existing data," and it benefits tables with heavy skew, high-cardinality filter columns, fast growth, and varied/changing access patterns — exactly the stated requirements. A repeats the rigid high-cardinality partitioning problem (tiny-file explosion, rigid to change). C is invalid because liquid clustering replaces (is not combined with) partitioning/ZORDER. D keeps rigid partitioning and addresses neither skew nor cheap re-tuning. *(Objective: S10 Data Modelling / S6 — liquid clustering vs partitioning/ZORDER)*

4. **A** — File skipping (data skipping) works on per-file min/max statistics: Delta skips a file only when its value range for the predicate column proves no row can match. Per Microsoft Learn ("File skipping for Delta tables"), when predicate values are scattered across all files, every file's min/max range overlaps the predicate and nothing is pruned ('files pruned: 0'). Clustering on order_amount colocates similar values so per-file ranges become narrow and selective, enabling pruning; Databricks recommends liquid clustering specifically for data skipping. B (caching) speeds repeat reads of the same bytes but does not enable pruning. C confuses *column* pruning with *file/row* pruning; SELECT * vs specific columns does not change which files match a WHERE predicate. D just throws compute at a full scan. *(Objective: S6 Cost & Performance — query optimization via data skipping / file pruning)*

5. **A** — Per Microsoft Learn ("Delta Lake table streaming reads and writes — Handle changes to source Delta Lake tables"), Structured Streaming accepts only append inputs and throws on UPDATE/DELETE/MERGE/OVERWRITE of the source; for workloads that must process all change types, "use the Delta Lake change data feed... allowing you to stream those changes and write logic to handle each change type." Databricks recommends streaming from the CDF feed (readChangeFeed=true) rather than directly from the table. B is a known trap: skipChangeCommits (the current replacement for the legacy ignoreChanges) does NOT propagate deletes/updates — it "disregards file-changing operations entirely" and only processes appends, so it suppresses the failure without giving change semantics. C reintroduces the expensive full-overwrite pattern. D is wrong — streaming tables are append-only and do not automatically propagate row-level deletes to downstream readers; that limitation is precisely what CDF addresses. *(Objective: S6 Cost & Performance — CDF to address streaming-table limitations/latency)*

6. **A** — A SortMergeJoin shuffles BOTH inputs across the network on the join key, which is wasteful when one side is tiny. Per Microsoft Learn (Synapse/HDInsight Spark optimization and Databricks AQE docs), "a Broadcast join is best suited for smaller data sets, or where one side of the join is much smaller than the other side... broadcasts one side to all executors," eliminating the shuffle; AQE can also dynamically convert a SortMergeJoin to a broadcast hash join. The profile signal — large shuffle on both sides for a join where one side fits in memory — points to a missed broadcast join. B is wrong: ZORDER affects file layout/skipping, not whether a join shuffles. C confuses shuffle (data movement during the join) with data skipping (file pruning during scan). D misdiagnoses: output file count is not what drives the join shuffle; the join strategy is. *(Objective: S6 Cost & Performance — query profile to find bottlenecks: shuffle / join type)*

7. **A** — Per Microsoft Learn ("Skew and spill"), "Spill is what happens when Spark runs low on memory. It starts to move data from memory to disk, and this can be quite expensive. It is most common during data shuffling." The Query performance insight DATA_SPILL recommends "increase the warehouse size to add memory" and "reduce the number of rows, columns, or the size of large columns," and the Spark memory-issues doc lists "too few shuffle partitions" as a cause. The intermittent slowdown (spill only when per-task data volume is large) confirms memory pressure; remedies are to reduce per-task working-set size (more shuffle partitions) or add memory. B confuses spill with data-skipping/file pruning. C is false: spill is not a hallmark of broadcast joins, and disabling broadcast adds shuffle. D addresses small-file scan overhead, not in-memory spill during aggregation/shuffle. *(Objective: S6 Cost & Performance — query profile to find bottlenecks: spill)*

8. **A** — Per Microsoft Learn ("File skipping for Delta tables"), Delta collects per-file min/max statistics only for the first 32 columns by default (controlled by delta.dataSkippingNumIndexedCols), and "columns beyond that threshold don't get file-level statistics and can't participate in file skipping." The same doc notes that clustering keys must be columns that have statistics collected. A clustering key at column #137 has no collected statistics, so Delta cannot prune any files ('files pruned = 0'). The fix is to bring device_id within the statistics-collected leading columns (reorder, raise dataSkippingNumIndexedCols, or set dataSkippingStatsColumns) and re-run OPTIMIZE. B is a regression to rigid high-cardinality partitioning. C is wrong: Delta has no user-defined secondary indexes for file pruning. D wrongly claims wide tables cannot skip — they can, once the predicate column is within the indexed columns. *(Objective: S6 Cost & Performance — query profile to find bottlenecks: bad data skipping)*

9. **A** — Per Microsoft Learn ("Use liquid clustering for tables"), liquid clustering supports up to four clustering keys and is recommended for tables filtered on high-cardinality columns and for skewed data — it "handles high cardinality naturally; bins data into right-sized files." Clustering on both event_type and user_id colocates data to enable file pruning for either dominant predicate. B carries over a ZORDER misconception; liquid clustering explicitly works well on high-cardinality columns like user_id. C is invalid: liquid clustering replaces (is not combined with) partitioning and ZORDER. D clusters on a value nobody filters on, giving even file sizes but no data-skipping benefit for the actual predicates. *(Objective: S10 Data Modelling / S6 — liquid clustering key choice)*

10. **A** — Per Microsoft Learn ("Unity Catalog managed tables" and "Best practices for performance efficiency"), the features unique to managed tables (and unavailable to external/foreign tables) include predictive optimization, which automatically runs OPTIMIZE/VACUUM/ANALYZE; "for managed tables, Databricks manages the entire data lifecycle, including file layout and the automatically enabled predictive optimization." B is false — OPTIMIZE/VACUUM work on both managed and external tables, so that is not a differentiator. C is false — predictive optimization and automatic management favor managed tables; they are not identical. D is false — liquid clustering is available on (and recommended for) managed tables. *(Objective: S6 Cost & Performance — managed vs external for optimization)*

11. **A** — Per Microsoft Learn ("Prepare your data for GDPR compliance" and the deletion-vectors docs), with deletion vectors enabled, deletes are soft-deletes that logically hide rows; to "permanently delete underlying records" you must run REORG TABLE ... APPLY (PURGE), which rewrites the affected data files to physically materialize the deletes and remove the deletion-vector files. VACUUM then removes the old, now-unreferenced files from storage after the retention threshold. B is wrong: a duplicate DELETE on already-deleted rows is a no-op and doesn't force physical removal. C is incorrect — toggling the feature off does not purge prior soft-deleted bytes. D misunderstands retention/VACUUM; reads never physically rewrite files. *(Objective: S6 Cost & Performance — deletion vectors physical purge / compliance)*

12. **A** — Per Microsoft Learn ("Use change data feed with Delta tables" and "Change data capture and snapshots"), Change Data Feed records row-level changes between table versions; using table_changes()/readChangeFeed you read only the changed rows by version range, so incremental ETL processes just the ~0.1% of changed rows instead of rescanning 5 TB — directly cutting latency and compute. B (clustering) only improves pruning for selective predicates; a full recompute still reads all data. C just pays for a faster full scan rather than avoiding it. D misunderstands deletion vectors — they accelerate deletes/updates and don't make an aggregation job read only changed rows. *(Objective: S6 Cost & Performance — CDF for incremental processing vs full recompute)*

---

# 7. Security & Compliance — Practice MCQs (10%)

1. A team must ensure that analysts in the `pii_viewers` account group see plaintext `email` values while everyone else sees a masked value, without maintaining separate copies of the `customers` table. They write this UDF:

   ```sql
   CREATE FUNCTION mask_email(email STRING)
   RETURNS STRING
   RETURN CASE WHEN is_account_group_member('pii_viewers') THEN email
               ELSE '***' END;
   ```

   Which statement correctly applies this as a column mask on the existing table?

   - A. `ALTER TABLE customers ALTER COLUMN email SET MASK mask_email`
   - B. `ALTER TABLE customers SET ROW FILTER mask_email ON (email)`
   - C. `CREATE VIEW customers_masked AS SELECT mask_email(email) FROM customers`
   - D. `GRANT MASK ON COLUMN customers.email TO mask_email`

2. A `transactions` table must be restricted so each analyst sees only rows for the region group they belong to, enforced centrally regardless of how the table is queried. An engineer defines a UDF to use as a Unity Catalog row filter on the `region` column. Which UDF definition is valid for use as a row filter?

   - A. `CREATE FUNCTION region_filter(region STRING) RETURNS BOOLEAN RETURN is_account_group_member('admins') OR is_account_group_member(region)`
   - B. `CREATE FUNCTION region_filter(region STRING) RETURNS STRING RETURN CASE WHEN region = 'APAC' THEN region ELSE NULL END`
   - C. `CREATE FUNCTION region_filter() RETURNS BOOLEAN RETURN true`
   - D. `CREATE FUNCTION region_filter(region STRING) RETURNS TABLE(region STRING) RETURN SELECT region`

3. A compliance officer requires that customer support staff be able to recover the original national-ID value for a flagged fraud case using a securely stored mapping, but the analytics warehouse must never expose the raw value. The data team is choosing a de-identification technique. Which technique satisfies the recoverability requirement?

   - A. Tokenization, where each ID is replaced by a token that maps back to the original value via a secured vault
   - B. SHA-256 hashing of the ID with a per-row random salt that is discarded
   - C. Generalization, replacing the exact ID with only its issuing-state prefix
   - D. Suppression, replacing the ID column entirely with NULL

4. A Delta table `users` has deletion vectors enabled. To satisfy a GDPR erasure request, an engineer runs `DELETE FROM users WHERE user_id = 42` and confirms the row no longer appears in queries. An auditor still finds the raw PII inside the underlying Parquet files in cloud storage. Which sequence permanently removes the data from storage?

   - A. `DELETE` the rows, then `REORG TABLE users APPLY (PURGE)`, then `VACUUM users`
   - B. `DELETE` the rows, then `VACUUM users` with `RETAIN 0 HOURS` only
   - C. `DELETE` the rows, then `OPTIMIZE users ZORDER BY (user_id)` only
   - D. `DELETE` the rows, then `ALTER TABLE users DROP DELETION VECTORS`

5. A Structured Streaming job ingests raw clickstream events containing email and IP into a bronze table, and must publish a silver table where PII is de-identified before any consumer can read it. Bronze raw PII must be retained only for short-term replay by the data-engineering team. Which design is compliant and avoids leaking raw PII to silver consumers?

   - A. Apply deterministic SHA-256 hashing of email/IP inside the streaming transformation that writes silver, and restrict bronze to the data-engineering group via Unity Catalog privileges
   - B. Write raw PII to silver and add a downstream SQL Alert that emails the team if PII appears
   - C. Grant all consumers SELECT on bronze and rely on the BI tool to hide PII columns client-side
   - D. Disable Auto Loader schema inference so the email/IP columns are dropped automatically

6. A new contractor needs to trigger and cancel runs of an existing production job, but must not be able to edit its definition, change the cluster configuration, modify its permissions, or delete it. Following least privilege with job ACLs, which permission should they be granted on the job?

   - A. CAN MANAGE RUN on the job
   - B. CAN MANAGE on the job
   - C. IS OWNER on the job
   - D. CAN VIEW on the job only

7. A health analytics dataset must be released for cohort analysis. Exact birth dates and full 6-digit PIN codes create high re-identification risk, but analysts still need approximate age bands and broad geography. Which anonymization technique best preserves analytical value while reducing re-identification risk?

   - A. Generalization — replace birth date with a 10-year age band and PIN with its first 2 digits
   - B. Suppression — set birth date and PIN to NULL for every record
   - C. Tokenization — replace birth date and PIN with reversible tokens
   - D. Keep the raw columns but apply a column mask that only admins can bypass

8. Requirements: members of `finance` see full `salary`; members of `hr` see salary rounded to the nearest 10,000; everyone else sees NULL. Which SQL UDF body, when attached as a column mask on `salary`, implements this correctly?

   - A. `CASE WHEN is_account_group_member('finance') THEN salary WHEN is_account_group_member('hr') THEN round(salary, -4) ELSE NULL END`
   - B. `CASE WHEN current_user() = 'finance' THEN salary ELSE 0 END`
   - C. `is_account_group_member('finance') AND salary > 0`
   - D. `SELECT salary FROM employees WHERE is_account_group_member('finance')`

9. Auditors require two distinct controls on a `customers` Delta table (deletion vectors enabled): (1) most analysts must never see raw `phone`, and (2) when a customer invokes their right to be forgotten, their record must be physically removed from storage. Which combination correctly addresses both — and why are they not interchangeable?

   - A. A column mask on `phone` for control 1; `DELETE` + `REORG TABLE ... APPLY (PURGE)` + `VACUUM` for control 2, because masking only changes values at query time and never removes stored bytes
   - B. A column mask on `phone` for both, because a mask physically deletes the underlying data when applied
   - C. `DELETE` + `VACUUM` for both, because removing the row also satisfies the access-control requirement for remaining users
   - D. Row filters for control 1 and column masks for control 2, because filters delete rows and masks delete columns

10. An engineer must pseudonymize `email` in a silver table so that (a) the same email always maps to the same pseudonym to allow joins across tables, and (b) an attacker who obtains the table cannot trivially recover common emails via a precomputed rainbow table. Which approach best meets both?

    - A. SHA-256 of the email concatenated with a secret, access-controlled salt that is the same for all rows, in a function marked `DETERMINISTIC`
    - B. SHA-256 of the email with a fresh random salt generated per row and stored in an adjacent column
    - C. Replace email with a per-session random UUID generated at query time
    - D. Base64-encode the email

## Answers & Explanations

1. **A** — Column masks are bound to a column with `ALTER TABLE ... ALTER COLUMN <col> SET MASK <func>`. Per the Databricks docs, a column mask is a scalar SQL UDF that "takes the column value as input and returns the original value or a masked version," evaluated at query time and able to inspect the caller's group membership (here via `is_account_group_member`). B is wrong because `SET ROW FILTER` attaches a row filter — a BOOLEAN UDF that drops rows, not a mask. C is a manual dynamic-view workaround that does not use the UC mask mechanism and creates a second object to maintain, contradicting the "no separate copies" requirement. D is invented syntax; there is no `GRANT MASK` statement. *(Objective: S7 — Row filters + column masks — column mask UDF binding and signature)*

2. **A** — A row filter is a scalar SQL UDF returning BOOLEAN; per the docs, "rows where the function returns FALSE are excluded from query results." The UDF receives the filtered column as a parameter and may branch on the caller's identity/group, so A is valid (`admins` see all rows; others see only rows whose region matches a group they belong to). B returns STRING — that is a column-mask signature, not a row filter. C takes no parameter mapped to the filtered column, so it cannot be attached with `ALTER TABLE ... SET ROW FILTER ... ON (region)`. D returns a TABLE; row filters must be scalar BOOLEAN UDFs, not table-valued functions. *(Objective: S7 — Row filters — row filter UDF return type and semantics)*

3. **A** — Tokenization is pseudonymization: the value is replaced by a token, and a separately secured mapping (vault) allows authorized recovery — exactly the requirement. The Databricks GDPR guidance contrasts complete deletion against obfuscation techniques like pseudonymization, where recovery via a retained mapping is what distinguishes pseudonymization from anonymization. B (hashing with a discarded salt) is irreversible anonymization — with the salt thrown away the original cannot be recovered. C (generalization) is irreversible loss of precision. D (suppression to NULL) destroys the value. Only tokenization with a retained mapping is recoverable. *(Objective: S7 — Anonymization vs pseudonymization — reversibility distinction)*

4. **A** — With deletion vectors enabled, `DELETE` is a soft-delete: rows are logically hidden but the bytes remain in the existing Parquet files. The Databricks GDPR doc states that for tables with deletion vectors "after deleting records, you must also run `REORG TABLE ... APPLY (PURGE)` to permanently delete underlying records," then `VACUUM` removes the now-unreferenced rewritten files from cloud storage. B is insufficient: until files are rewritten by PURGE they are still actively referenced, so VACUUM will not delete them. C compacts/clusters files but does not provide the PURGE rewrite semantics and still requires VACUUM. D is not a valid command. *(Objective: S7 — Data purging for retention compliance — deletion vectors + REORG PURGE + VACUUM)*

5. **A** — A compliant streaming PII pipeline de-identifies in-band: the silver write applies a one-way transform (deterministic SHA-256 hashing preserves joinability while removing the plaintext value), and bronze raw PII is locked down with least-privilege Unity Catalog grants to only the engineering group — the same separation-of-tables pattern Databricks documents for raw-vs-redacted PII tables. B writes raw PII to silver (the exact leak being prevented); an alert is detective, not preventive. C exposes raw PII to all consumers and relies on client-side hiding, which is trivially bypassed. D is false — Auto Loader schema inference does not selectively drop sensitive columns. (Note: hashing low-entropy fields is only strong when combined with a secret salt and access controls, as in Q10; here it is the in-band placement plus locked-down bronze that makes A the only compliant option.) *(Objective: S7 — Compliant streaming PII-masking pipeline — where masking must occur)*

6. **A** — Per the Databricks job ACL table, CAN MANAGE RUN lets a principal run, run-with-different-parameters, and cancel runs of an existing job (and view its results/logs and Spark UI), but does NOT grant "Edit job settings," "Delete job," or "Modify permissions" — those require IS OWNER or CAN MANAGE. CAN MANAGE RUN is therefore the minimal grant satisfying the requirement. B (CAN MANAGE) grants full edit/delete and cluster-config rights, exceeding least privilege. C (IS OWNER) is broader still (adds permission management). D (CAN VIEW) cannot trigger runs, failing the functional need. *(Objective: S7 — ACLs on workspace objects — least privilege / policy enforcement)*

7. **A** — Generalization lowers precision (birth date to a 10-year age band, full PIN to a 2-digit prefix) so individuals are no longer uniquely identifiable while age bands and broad geography stay usable — the stated need. B (suppression to NULL) destroys analytical value. C (tokenization) is reversible pseudonymization, so it does not actually reduce re-identification risk for a holder of the mapping and yields no usable age bands. D keeps the raw high-risk values in the table and merely controls who can see them, which does not anonymize the released dataset itself. *(Objective: S7 — Anonymization techniques — generalization vs suppression for re-identification risk)*

8. **A** — A column mask UDF takes the column value as input and returns a value castable to the column's type. A branches on group membership via `is_account_group_member` to return the full value, a generalized (rounded) value, or NULL, matching all three tiers. B compares `current_user()` (an identity/email string) to the literal group name `'finance'`, which never matches, so finance would never see the full salary. C returns BOOLEAN — a row-filter signature, not a column mask. D is a query, not a scalar masking expression, and cannot be a mask body. *(Objective: S7 — Row filters + column masks — conditional dynamic masking by group)*

9. **A** — The two controls are orthogonal. A column mask is query-time access control: it changes what a principal sees, but the raw bytes remain in storage, so it cannot satisfy erasure. Physical erasure of a deletion-vector table requires `DELETE`, then `REORG TABLE ... APPLY (PURGE)` to rewrite the affected Parquet files, then `VACUUM` to drop the now-unreferenced files. B is wrong — masks never delete stored data. C conflates the controls: deleting one customer's row does nothing to restrict other analysts from seeing the remaining customers' raw phone numbers. D misstates the mechanisms — row filters hide rows at query time (they do not delete) and column masks transform values (they do not delete columns). *(Objective: S7 — Compliant batch PII-masking + retention — combining mask for access and purge for erasure)*

10. **A** — A keyed/salted hash with a single secret salt shared across all rows is deterministic (the same email yields the same pseudonym, preserving cross-table joins), and the secret, access-controlled salt defeats generic rainbow tables — satisfying both requirements. This matches the Databricks "Common patterns for row filtering and column masking" recipe, which uses a `DETERMINISTIC`-marked SHA2 function for consistent pseudonymization (`SHA2(CONCAT(val, ...), 256)`); marking it `DETERMINISTIC` also lets the engine optimize. B uses a fresh per-row salt, so the same email hashes to different values — breaking joins — and storing the salt adjacent weakens protection. C produces a different value every session, so it is unstable and unjoinable. D Base64 is reversible encoding, not hashing, and offers no protection. *(Objective: S7 — Pseudonymization with hashing — deterministic, salted, join-preserving design)*

---

# 8. Data Governance — Practice MCQs (7%)

1. A data engineer runs the following to set up access for the analytics team on a new catalog that will accumulate dozens of schemas and hundreds of tables over the next year:

   ```sql
   GRANT USE CATALOG ON CATALOG sales_prod TO `analysts`;
   GRANT USE SCHEMA, SELECT ON CATALOG sales_prod TO `analysts`;
   ```

   A teammate argues these grants will only cover the tables that exist today and that new tables created next month will be invisible to the analysts. Which statement is correct about how Unity Catalog will behave?

   - A. The grants apply to all current AND future schemas and tables in `sales_prod`, because a privilege granted on a container object is inherited by all current and future child objects.
   - B. The teammate is right; `SELECT` granted at the catalog level only resolves against tables that existed at grant time, so a nightly re-`GRANT` job is required for new tables.
   - C. `USE SCHEMA` and `SELECT` cannot be granted on a catalog; they must be granted on each schema individually, so only explicitly granted schemas will be accessible.
   - D. The grants apply to future tables only if AUTO INHERIT is first enabled on the catalog with `ALTER CATALOG sales_prod SET INHERIT = true`.

2. An analyst is granted `SELECT` directly on the table `prod.finance.gl_entries`, but no other privileges. When they run `SELECT * FROM prod.finance.gl_entries` they get a permission error. The analyst insists `SELECT` on the table should be sufficient. Which explanation correctly diagnoses the failure?

   - A. Reading a table also requires `USE CATALOG` on its parent catalog (`prod`) and `USE SCHEMA` on its parent schema (`finance`); `SELECT` alone on the table is insufficient.
   - B. `SELECT` must be granted on the schema, not the table; table-level `SELECT` grants are silently ignored by Unity Catalog.
   - C. The analyst additionally needs the `BROWSE` privilege on the table, because `BROWSE` is the prerequisite for any data read.
   - D. The catalog owner must first run `ALTER TABLE ... OWNER TO \`analyst\``, because only owners can issue `SELECT` against a managed table.

3. A platform admin wants every member of the `data_platform` group to be able to read all data in every catalog across the metastore with a single grant. They consider running `GRANT SELECT ON METASTORE TO \`data_platform\``. A reviewer pushes back. Which statement about metastore-level grants is correct?

   - A. Privileges granted at the metastore level do not inherit to catalogs, schemas, or tables; metastore grants govern only metastore-scoped operations such as `CREATE CATALOG` and `CREATE EXTERNAL LOCATION`, so a metastore grant could never confer `SELECT` on data.
   - B. It works as intended: a metastore-level `SELECT` grant cascades down through all catalogs and schemas to every table in the metastore.
   - C. Metastore-level grants are syntactically invalid in Unity Catalog; all privileges must originate at the catalog level or below.
   - D. It works, but only for catalogs created before the grant; catalogs created afterward would each need their own metastore-level re-grant.

4. A team lead owns the catalog `ml_features`. A new schema `ml_features.embeddings` is created inside it by another engineer. The team lead assumes that because they own the parent catalog, they automatically own the new schema and every table created within it. Which statement most accurately describes the relationship between catalog ownership and child objects in Unity Catalog?

   - A. Ownership does not inherit downward; the catalog owner does not become the owner of each child schema or table, but does automatically get the ability to manage all child objects (the equivalent of `MANAGE` on them).
   - B. Owning a catalog makes you the explicit owner of every current and future schema and table inside it, with full OWNER rights on each.
   - C. Catalog ownership grants no rights over child objects at all; the team lead would need a separate explicit grant to even see the new schema.
   - D. Child schemas inherit ownership only if they were created by the catalog owner; schemas created by other engineers are owned by no one until reassigned.

5. A governance team wants to bulk-document hundreds of legacy tables to improve discoverability and is evaluating Unity Catalog's AI-generated comments feature. A stakeholder proposes wiring it into a pipeline that auto-generates comments and saves them directly, and also wants to rely on it to flag which columns contain PII. Which recommendation is most consistent with Databricks guidance?

   - A. AI-generated comments must be reviewed by a human before saving and should not be relied upon for sensitive tasks like PII detection; they are a discoverability aid driven by object metadata such as the table schema and column names.
   - B. Auto-saving is the intended workflow because the underlying LLM reads the actual row-level data, making the generated comments authoritative enough to drive PII tagging.
   - C. The feature should be avoided entirely because AI-generated comments cannot be edited after generation and permanently overwrite any human-written comments.
   - D. It is safe to auto-save for tables, but PII detection requires first enabling a separate AI-PII-classifier privilege at the metastore level.

6. A central data team adds rich `COMMENT` descriptions and key-value tags (e.g., `domain='finance'`, `sensitivity='internal'`) to securables so analysts can find the right datasets via Catalog search. They want analysts to be able to read these comments and tags and locate the objects WITHOUT being able to query the underlying data, and without first granting `USE CATALOG` / `USE SCHEMA` on every container. Which approach satisfies this?

   - A. Grant the `BROWSE` privilege on the catalog, which lets users discover objects and view their metadata (including comments and tags) without `USE CATALOG` / `USE SCHEMA` and without granting access to the underlying data.
   - B. Grant `SELECT` on the catalog, since `SELECT` is the only privilege that exposes comments and tags, then rely on row filters to block the actual rows.
   - C. Grant `USE CATALOG` and `USE SCHEMA` everywhere, because metadata such as comments and tags is only visible to principals who already hold usage on the parent containers.
   - D. Tags and comments are visible to all workspace users by default regardless of privileges, so no grant is required; only data reads need privileges.

## Answers & Explanations

1. **A** — Catalogs and schemas are container objects. Per the Unity Catalog permissions model, "when you grant a privilege on a container object, that privilege automatically applies to all current and future child objects"; the docs use the exact pattern `GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG ... TO <group>` to grant read on all current and future tables. So no re-`GRANT` job is needed (B is the teammate's misconception); `USE SCHEMA` and `SELECT` are both valid catalog-scoped privileges (C is wrong); and there is no AUTO INHERIT / `INHERIT` flag — inheritance is the built-in default (D is fabricated). *(Objective: S8 — Governance: Unity Catalog permission inheritance model)*

2. **A** — The privileges reference states verbatim: "to read from a table, a user needs `SELECT` on the table, `USE CATALOG` on the parent catalog, and `USE SCHEMA` on the parent schema." All three are required (Option A). Table-level `SELECT` is fully valid and not ignored (B). `BROWSE` only enables metadata discovery and explicitly does NOT grant data access (C). Ownership is not required to read; `SELECT` plus the parent USE privileges suffices (D). *(Objective: S8 — Governance: table access prerequisites / usage privileges)*

3. **A** — The permissions-concepts doc flags this explicitly: "Privileges granted on a metastore do not inherit to child objects. Metastore-level grants control metastore-scoped operations like `CREATE CATALOG` and `CREATE EXTERNAL LOCATION`, not access to data within the metastore." The metastore privilege set is `CREATE CATALOG`, `CREATE EXTERNAL LOCATION`, `CREATE CONNECTION`, etc.; `SELECT` is not among them, so a metastore-level `SELECT` could never confer table read either way (Option A). B is the core misconception (no cascade). Metastore grants are valid syntax for metastore-scoped privileges, so C overstates it. D is irrelevant since no inheritance happens at all. *(Objective: S8 — Governance: metastore-level grants do not inherit)*

4. **A** — Per the docs: "Ownership doesn't inherit downward in Unity Catalog. However, object owners do automatically have the ability to manage all child objects. For example, if you own a catalog, you don't automatically own the child schemas within the catalog, but you can manage all child schemas" — functionally equivalent to `MANAGE` on each child, though Databricks does not explicitly assign `MANAGE` (Option A). B is the misconception that ownership flows downward like privileges. C understates the owner's reach (they do get manage capability over children, not nothing). D invents a "creator-based ownership inheritance" rule — the schema's owner is by default its creating principal, not nobody. *(Objective: S8 — Governance: ownership vs. inheritance)*

5. **A** — The AI-generated comments doc states comments "must be reviewed prior to saving," that Databricks "strongly recommends human review," and that "the model should not be relied on for data classification tasks such as detecting columns with PII." It also notes comments are "powered by a large language model (LLM) that takes into account object metadata, such as the table schema and column names" — not row-level data (Option A). B is wrong on both counts (no auto-save guidance; it does not read row data). C is fabricated — comments are editable via the UI or `ALTER`/`COMMENT ON`, and the human-review step exists precisely so nothing is blindly overwritten. D invents a non-existent "AI-PII-classifier privilege"; for actual sensitive-data tagging Databricks points to Data Classification, not AI comments. *(Objective: S8 — Governance: AI-generated comments for discoverability)*

6. **A** — `BROWSE` is purpose-built for this: per the docs it "allows users to discover objects and view their metadata without granting access to the underlying data. Users with `BROWSE` can see that an object exists, view its name, description, and tags, and request access to it without needing `USE CATALOG` or `USE SCHEMA`." For data objects, `BROWSE` is granted at the catalog level (Option A). `SELECT` would expose data and is not the metadata-visibility mechanism (B). C describes the pre-`BROWSE` limitation that `BROWSE` was designed to remove. D is wrong — metadata visibility is governed by privileges (`BROWSE`/`SELECT`/`USE`), not open to everyone by default. *(Objective: S8 — Governance: BROWSE, tags, comments for discoverability)*

---

# 9. Debugging & Deploying — Practice MCQs (10%)

1. A nightly join job between a 2 TB fact table and a dimension table has started running 3x longer. In the Spark UI Stage detail page for the join stage, you sort tasks by duration and notice that 197 of 200 tasks finish in under 30 seconds, but 3 tasks each run for over 25 minutes, and those same 3 tasks show shuffle read of ~5 GB while the median task shows ~40 MB. What does this pattern most directly indicate, and where should you look first to confirm?
   - A. Executor memory pressure causing disk spill across all tasks; check the Storage tab for cached RDD eviction
   - B. Data skew on the join key concentrating rows into a few partitions; confirm via the Max vs. 75th-percentile task duration and shuffle-read distribution in the Stage detail page
   - C. A driver-side bottleneck from collecting results; check the SQL/DataFrame query plan for a collect() node
   - D. Cluster autoscaling removed executors mid-stage; check the compute event log for downscale events

2. A multi-task Lakeflow job has 8 tasks. Task 5 failed because a downstream API was temporarily down; tasks 1-4 succeeded and tasks 6-8 (which depend on 5) were skipped. The transient issue is now resolved, and for the retry you also need to pass a corrected value for the job parameter run_date. What is the most cost-effective remediation?
   - A. Re-run the entire job from the start with the new run_date so all tasks execute against consistent inputs
   - B. Use Repair run, which re-runs only the failed task 5 and its dependent tasks 6-8, and enter the corrected run_date in the Repair job run dialog to override the original value
   - C. Clone the job, hardcode run_date in task 5's notebook, and trigger the clone once
   - D. Edit task 5 to add a retry policy of 3 attempts, then trigger a fresh run of the whole job

3. A Lakeflow Spark Declarative Pipelines (SDP) update that you expected to process only new rows incrementally instead performed a full recompute of a materialized view, blowing up the cost. You want to programmatically find out why the planner chose a full refresh over an incremental one. Which approach is correct?
   - A. Open the Spark UI for the pipeline cluster and inspect the DAG visualization for a FullScan node
   - B. Query the pipeline event log via the event_log() table-valued function for events where event_type = 'planning_information', and parse the details to see the chosen refresh type and its reason
   - C. Check the Delta transaction log (DESCRIBE HISTORY) on the materialized view's underlying table for a VACUUM operation
   - D. Re-run the pipeline in Development mode and read stdout from the driver logs

4. Your team develops in a 'dev' workspace and promotes to a 'prod' workspace using a Databricks Asset Bundle whose databricks.yml defines a dev target (development mode) and a prod target (production mode). During the prod deploy step in CI, the command fails validation before deploying. Which command was run, and what is the most likely cause of the validation failure under production mode?
   - A. databricks bundle deploy -t prod failed because a related Lakeflow Spark Declarative Pipeline is configured with development: true, which production mode disallows
   - B. databricks bundle deploy -t dev failed because the dev workspace host was unreachable
   - C. databricks bundle run -t prod failed because no job key was specified on the command line
   - D. databricks bundle validate failed because the YAML had a syntax error in the resources block

5. Your org runs production jobs from a production Databricks Git folder (a checkout created by an admin, outside user folders) pointing at the 'release' branch. After a PR is merged into 'release', the production jobs still execute the previous code. What is the correct, supported way to make production pick up the merged commit?
   - A. Have a developer open the production Git folder in the UI and click Pull, since production folders sync interactively like user folders
   - B. Trigger automation (e.g., a GitHub Actions step or a scheduled job) that calls the Databricks Repos/Git folders API (for example, w.repos.update(...)) to update the production Git folder to the latest commit on the release branch
   - C. Restart the job's cluster, since Git folders refresh from the remote on every cluster cold start
   - D. Delete and recreate the production Git folder on each merge so it always clones the newest commit

6. A scheduled job has been silently failing to start on some nights with no task-level error surfaced in the run's task list. You want to query historically across many runs to find why these runs did not start, using governed observability data rather than clicking through the Jobs UI run by run. Which is the most appropriate source and field?
   - A. The Spark UI of each failed run's cluster, reading the Executors tab for OOM messages
   - B. The system.lakeflow job run timeline tables (job_run_timeline / job_task_run_timeline), inspecting the termination_code column to learn why runs did not start
   - C. The Delta transaction history (DESCRIBE HISTORY) of the target output table to see missing commits
   - D. The Query Profiler UI, filtered to the job's SQL warehouse, sorted by failed queries

7. An analyst reports that a simple filtered query, SELECT * FROM sales WHERE event_date = '2026-06-01', is reading nearly the entire 4 TB table even though only one day is requested. You open the Query Profile for the query. Which metric pattern in the profile most directly confirms that file pruning / data skipping is NOT working, pointing to a layout problem rather than a join or shuffle issue?
   - A. High 'spill to disk' bytes on the final aggregate node
   - B. Files/bytes pruned is near zero while files/bytes read is close to the full table size on the scan node, despite the selective predicate
   - C. A broadcast exchange node showing a large broadcast relation
   - D. A high number of output rows on the result node relative to input rows

8. A job task on a classic all-purpose cluster fails intermittently with a generic 'Spark executor lost' message in the run output, but the run page gives no root cause. Your platform team has configured cluster log delivery to a storage location. Where in the delivered cluster logs should you look to find the actual reason an executor died (e.g., an OutOfMemoryError or a container kill), and why?
   - A. The driver's event log JSON only, because executor failures are always summarized there with full stack traces
   - B. The per-executor stderr/stdout logs (and Log4j output) under the delivered cluster logs, because executor-side fatal errors like OOM and JVM crashes are written there, not fully surfaced on the run page
   - C. The Spark UI SQL tab, because it persists executor JVM heap dumps after the cluster terminates
   - D. The system.billing usage table, because executor crashes are recorded as cost anomalies

9. An SDP pipeline has a streaming table with an expectation defined as EXPECT (amount > 0) ON VIOLATION DROP ROW. Stakeholders complain that downstream row counts are lower than the source, and you must quantify exactly how many records the expectation dropped per update without re-deriving it manually. What is the most direct method?
   - A. Open the Spark UI for the pipeline and count the difference in input vs. output rows on the streaming stage's task metrics
   - B. Query the pipeline event log (event_log() TVF) for flow_progress events and read the data_quality object in the details field, which records dropped_records and per-expectation passed_records / failed_records
   - C. Add a count(*) to the streaming table query and diff it against the source table count after the run
   - D. Enable verbose logging on the cluster and grep the executor stderr for 'EXPECT' messages

10. You are wiring a GitHub Actions pipeline for a Databricks Asset Bundle. On every push to a feature branch you want an isolated, prefixed, non-interfering deployment for testing; on merge to main you want the canonical production deployment. Given a databricks.yml with a 'dev' target (mode: development) and a 'prod' target (mode: production), how should the two CI steps invoke the bundle?
    - A. Feature branch: databricks bundle deploy -t dev (development mode prefixes resource names with [dev <short_name>] and pauses schedules/triggers); main: databricks bundle deploy -t prod (production mode, canonical names and active schedules)
    - B. Feature branch: databricks bundle deploy -t prod with a different --profile; main: databricks bundle deploy -t dev
    - C. Feature branch: databricks bundle validate only; main: databricks bundle deploy with no target so it uses both targets simultaneously
    - D. Feature branch and main both run databricks bundle run -t prod, relying on Git branch to pick the workspace

## Answers & Explanations

1. **B** — The signature of a few straggler tasks finishing far slower than the median, combined with those same tasks reading 10-100x more shuffle data than the median, is the classic Spark UI signal of data skew on the join key. The Databricks "Skew and spill" guide says to confirm skew on the Stage detail page's Summary Metrics by checking whether the **Max** task duration is much higher than the **75th-percentile** duration (a Max ~50% over the 75th percentile suggests skew), and skew shows as stages with large shuffle read/write concentrated in a few partitions. A: spill is read in the Spill (Memory/Disk) stats at the top of the stage page and is a memory symptom, not a 3-task concentration. C: a driver collect would not produce per-task shuffle-read skew within a stage. D: autoscaling downscale is unrelated to per-partition data concentration and would not selectively slow 3 high-shuffle-read tasks. *(Objective: S9 — Diagnose via Spark UI, data skew)*

2. **B** — Per "Troubleshoot and repair job failures," Repair run re-runs only the subset of unsuccessful tasks and any dependent tasks, leaving already-successful tasks 1-4 untouched, which "reduces the time and resources required to recover." The docs also state that parameters entered in the **Repair job run** dialog override existing values for the repaired tasks, so the corrected run_date is applied. A: re-running the whole job wastes compute re-doing tasks 1-4 that already succeeded. C: cloning and hardcoding abandons the original run's state and is not a repair. D: a retry policy helps future transient failures but does not recover the current failed run, nor supply a corrected parameter. *(Objective: S9 — Remediate failed runs with job repairs + parameter overrides)*

3. **B** — SDP writes structured events (progress, data quality, lineage, planning) to the pipeline event log. Per "Incremental refresh for materialized views," you query `event_log(TABLE(<mv>))` (or `event_log('<pipeline-id>')`) where `event_type = 'planning_information'`; these events expose the chosen refresh technique (e.g., FULL_RECOMPUTE vs ROW_BASED) and are explicitly described as "useful for seeing details related to the chosen refresh type ... can be used to help debug why an update is fully refreshed rather than incrementally refreshed." A: the Spark UI DAG shows task execution, not the planner's incremental-vs-full decision. C: DESCRIBE HISTORY shows committed operations, not planner reasoning; VACUUM is unrelated. D: driver stdout is unstructured and not the documented source. *(Objective: S9 — Debug SDP via event logs)*

4. **A** — Per "Declarative Automation Bundles deployment modes," deploying a target in production mode with `databricks bundle deploy -t <target>` runs extra validations: it (1) validates that all related deployed Lakeflow Spark Declarative Pipelines are marked `development: false`, and (2) validates the current Git branch equals the target's specified branch (overridable with `--force`). A pipeline left at `development: true` triggers exactly the first validation. B: an unreachable host is a connectivity error, not a production-mode validation, and `-t dev` is the development target. C: `bundle run` executes a resource and is not the deploy step. D: a YAML syntax error is caught generically by validate regardless of mode, not specific to production-mode checks. *(Objective: S9 — Deploy with Databricks Asset Bundles)*

5. **B** — Per "CI/CD with Databricks Git folders," production Git folders are created by admins outside user folders and "should be updated only by automation when PRs are merged into deployment branches." The documented mechanisms are external CI/CD (e.g., GitHub Actions pulling the latest commit on merge) or a scheduled job using the Repos API — the docs show `w.repos.update(w.workspace.get_status(path=...).object_id, branch="<branch>")`. A: production Git folders are not meant to be pulled interactively; that is the user-folder development flow, and access is restricted to run-only for most users. C: cluster restart does not refresh a Git folder from the remote. D: delete-and-recreate is not the documented pattern; the update API is the supported mechanism. *(Objective: S9 — Git-based CI/CD via Databricks Git Folders)*

6. **B** — Per the "Jobs system table reference," when a run never began execution it is represented by a `job_run_timeline` row where `period_start_time` equals `period_end_time`, and the docs state: "To understand why the run didn't start, check the `termination_code` column" (with values such as `MAX_CONCURRENT_RUNS_EXCEEDED`, `MAX_JOB_QUEUE_SIZE_EXCEEDED`, `RESOURCE_NOT_FOUND`, `CLOUD_FAILURE`). The `job_run_timeline` / `job_task_run_timeline` system tables provide governed, queryable history across many runs, which cross-run trend analysis needs. A: the Spark UI is per-run/per-cluster and won't exist for a run that never started. C: Delta history shows committed writes, not why a job failed to start. D: the Query Profiler covers SQL warehouse query execution; a run that never started issued no queries. *(Objective: S9 — Diagnose via system tables, failed runs)*

7. **B** — The Query Profile is the documented tool for diagnosing query execution, and per-scan it reports how many files/bytes were read versus pruned (data skipping). When a selective single-day predicate still reads nearly the whole 4 TB table and pruned bytes are near zero, file pruning/data skipping failed — pointing to a table layout problem (no clustering/ordering or missing Delta statistics on event_date) rather than execution. Query performance insights surface exactly this as layout recommendations to "reduce bytes read." A: spill on an aggregate is a memory/shuffle symptom, not a pruning symptom for a filter. C: a broadcast exchange concerns join strategy, not whether the scan pruned files. D: high output rows is about result cardinality, not whether the scan skipped files. *(Objective: S9 — Diagnose via query profiles, bad data skipping)*

8. **B** — Per "Debugging with the Spark UI," executor logs are helpful "if you see certain tasks are misbehaving"; you find the executor where a task ran and read its log4j output. With cluster log delivery configured, per-node driver and executor stdout/stderr (and Log4j) are delivered to the storage location, and executor-side fatal conditions (OutOfMemoryError, JVM crash, container kill) are written to the executor's own logs — the root cause the run page only summarizes as "executor lost." A: the driver log records job/stage events but may not contain the executor's full fatal stack trace. C: the Spark UI SQL tab shows query plans/metrics, not persisted heap dumps, and the UI is unavailable after the cluster terminates unless logs were delivered. D: billing system tables track cost/usage, not executor crash diagnostics. *(Objective: S9 — Diagnose via cluster logs)*

9. **B** — Per "Pipeline event log" advanced queries, expectation metrics are stored in the `flow_progress` event details: the number of records that passed/failed each expectation is in `details:flow_progress.data_quality.expectations` (per-expectation `passed_records` and `failed_records`), and the number of dropped records is in `details:flow_progress.data_quality` as `dropped_records`. Querying via the `event_log()` TVF gives an authoritative per-update count without manual derivation. A: Spark UI task metrics show partition-level row counts but do not attribute drops to a named expectation. C: manually diffing counts re-derives the number and is exactly what the question rules out. D: grepping executor stderr is unstructured and not the documented source. *(Objective: S9 — Debug SDP via event logs, data quality failure)*

10. **A** — Per "Declarative Automation Bundles deployment modes," development mode (`deploy -t dev`) is designed for isolated, non-interfering deployments: it prepends resources with the prefix `[dev ${workspace.current_user.short_name}]`, tags jobs/pipelines with a `dev` tag, marks pipelines `development: true`, pauses all schedules and triggers, and enables concurrent runs — ideal for per-feature-branch testing. Production mode (`deploy -t prod`) deploys with canonical names and active schedules and runs production validations, matching the merge-to-main step. B: inverts the modes. C: validate alone deploys nothing, and a deploy without a target selects the default single target, not "both targets simultaneously." D: `bundle run` executes resources rather than deploying them, and branch alone does not substitute for selecting the correct target/mode. *(Objective: S9 — Deploy with Databricks Asset Bundles, CI/CD targets)*

---

# 10. Data Modelling — Practice MCQs (6%)

1. A data engineer is creating a new Delta fact table `sales_events` expected to grow to several TB. Most analytic queries filter on `event_date` and a high-cardinality `customer_id`. The team's first instinct is `PARTITIONED BY (event_date)`, but query patterns are expected to shift over the next year as new dashboards are added. They want a layout that performs well now and can evolve without rewriting all the data. Which approach should they choose?

   A. Create the table with `CLUSTER BY (event_date, customer_id)` (liquid clustering), since clustering keys can be redefined later without rewriting existing data and it handles high-cardinality columns well
   B. Use `PARTITIONED BY (event_date)` and add a secondary `PARTITIONED BY (customer_id)` to cover both filter columns
   C. Partition by `event_date` and run `OPTIMIZE ... ZORDER BY (customer_id)` on every batch to combine partitioning with multi-column skipping
   D. Leave the table unpartitioned and rely solely on Delta's default file-level statistics with no clustering, since the table is large

2. An existing partitioned Delta table currently uses `OPTIMIZE ... ZORDER BY (region, product_id)`. The team wants to migrate it to liquid clustering so they can change the layout keys more easily as reporting needs evolve. A junior engineer proposes running `ALTER TABLE ... CLUSTER BY (region)` while keeping the existing `ZORDER` command in the nightly OPTIMIZE job. What is the correct guidance?

   A. Liquid clustering is not compatible with ZORDER (or partitioning); the table must be migrated to clustering and the ZORDER command dropped, after which clustering keys can be altered later without rewriting existing data
   B. Keep both: ZORDER handles multi-dimensional skipping while CLUSTER BY handles single-column skipping, and Databricks runs them in sequence during OPTIMIZE
   C. Liquid clustering only works on partitioned tables, so the ZORDER must stay but the partition spec must be removed first
   D. ZORDER and CLUSTER BY can coexist, but only if both reference the exact same columns in the same order

3. A team defines a clustering specification with six columns: `CLUSTER BY (country, state, city, store_id, product_id, event_hour)` on a 4 TB table whose most common query filters on just `country`. They report that single-column filters on `country` are slower than expected. Which statement reflects current Databricks guidance on liquid clustering key selection?

   A. Liquid clustering allows at most four clustering keys, and on tables under 10 TB using too many keys degrades single-column filter performance; keys should be the columns most frequently used in query filters, dropping one of any two highly correlated columns
   B. Liquid clustering supports unlimited keys, so the slowdown must be caused by missing partitions, not the number of clustering columns
   C. You should always cluster by every column referenced in any query to maximize data skipping, so six keys is correct and the slowdown is unrelated to key count
   D. Clustering keys must be the table's primary key columns in declaration order, so the fix is to reorder the six columns to match the primary key

4. An analytics team is migrating a heavily normalized (third normal form, 3NF) OLTP-style schema into a new Databricks lakehouse to power BI dashboards. They ask how to model the data for best query performance on Databricks. Which recommendation aligns with Databricks guidance for dimensional modeling on the lakehouse?

   A. Adopt a star or snowflake (dimensional) schema with wider, denormalized tables, since fewer joins and more fields per table let the optimizer skip large amounts of data using file-level statistics; note that primary and foreign keys are informational and not enforced
   B. Preserve the full 3NF normalized model, because Databricks enforces foreign-key constraints and uses them to guarantee referential integrity automatically
   C. Use a single fully denormalized table for everything and declare enforced primary/foreign keys so Databricks rejects any write that violates referential integrity
   D. Keep the 3NF model because more joins let the query optimizer skip more data than wide tables, and the gold layer should avoid dimensional models

5. A large managed Delta table backs many dashboards whose filter columns change frequently quarter to quarter, and the team does not want to keep manually re-tuning clustering keys. Predictive optimization is enabled for the workspace. Which configuration best matches Databricks' recommended approach for self-adapting layout?

   A. Define the table with `CLUSTER BY AUTO`, which lets Databricks analyze the table's historical query workload and automatically select and adapt clustering keys when predicted data-skipping savings outweigh the clustering cost
   B. Schedule a nightly job that drops and recreates the table with a new `PARTITIONED BY` spec computed from the prior day's most-filtered column
   C. Use `CLUSTER BY AUTO` but disable predictive optimization, since automatic key selection runs synchronously inside each query
   D. Set `CLUSTER BY (col1, col2, col3, col4)` with all current and anticipated filter columns and never change it, since manual keys always outperform automatic ones

## Answers & Explanations

1. **A** — Databricks recommends liquid clustering instead of partitioning for all new Delta tables. Per *Use liquid clustering for tables*, clustering particularly benefits "queries that filter on high cardinality columns" and "tables with varied or changing access patterns," and a key advantage is that "you can redefine clustering keys without rewriting existing data," letting the layout evolve. B is wrong: a Delta table has a single layout spec, and partitioning on high-cardinality `customer_id` would over-partition into tiny files. C is wrong: liquid clustering "replaces table partitioning and `ZORDER`," and ZORDER cannot be combined with clustering on the same table (error `DELTA_CLUSTERING_WITH_ZORDER_BY`); plain partitioning is also static and hard to alter. D abandons all layout optimization, giving poor data skipping on a multi-TB table. *(Objective: S10 Data Modelling — liquid clustering vs partitioning benefits for scalable Delta models)*

2. **A** — Per *Use liquid clustering for tables* and the error condition `DELTA_CLUSTERING_WITH_ZORDER_BY` ("`OPTIMIZE` command for Delta table with Liquid clustering cannot specify `ZORDER BY`"), clustering is not compatible with partitioning or ZORDER — they cannot coexist on the same table. Migration means dropping the ZORDER-based OPTIMIZE and using `CLUSTER BY`. A genuine benefit is that keys can be altered via `ALTER TABLE ... CLUSTER BY` without rewriting existing data; an `OPTIMIZE` (or `OPTIMIZE FULL` to force a recluster of already-written files) applies the new layout incrementally. B, C, and D all assert coexistence or a partition dependency that the documentation explicitly contradicts. *(Objective: S10 Data Modelling — liquid clustering vs ZORDER incompatibility, evolving keys)*

3. **A** — Per the *Choose clustering keys* guidance, you can specify "up to four clustering keys," and "for smaller tables (less than 10 TB), using more clustering keys can degrade performance when filtering on a single column. For example, filtering with four keys performs worse than filtering with two keys." (For very large tables this difference becomes negligible, but the scenario table is 4 TB, so the degradation applies.) The guidance is to choose "the columns most frequently used in query filters," and "if two columns are highly correlated, you only need to include one of them." The six-key spec is therefore both invalid (exceeds the four-key maximum) and counterproductive for a single-column `country` filter. B is false (there is a four-key cap and partitions are not required). C contradicts the single-column degradation guidance. D invents a primary-key requirement; clustering keys are chosen by filter usage and must be columns with collected statistics (first 32 columns by default), not primary-key columns. *(Objective: S10 Data Modelling — liquid clustering key selection limits for scalable models)*

4. **A** — Per *Data modeling*, "Databricks recommends against using a heavily normalized model such as third normal form (3NF)," and "models like the star schema or snowflake schema perform well on Azure Databricks, as there are fewer joins present in standard queries and fewer keys to keep in sync. In addition, having more data fields in a single table allows the query optimizer to skip large amounts of data using file-level statistics." The same page and *Constraints on Azure Databricks* confirm "primary and foreign keys are informational and not enforced." B and C are wrong because Databricks does not enforce primary/foreign-key constraints or guarantee referential integrity (only `NOT NULL` and `CHECK` are enforced). D inverts the join guidance — fewer joins, not more, improve performance, and dimensional models belong in the gold layer. *(Objective: S10 Data Modelling — dimensional models for analytics on the lakehouse)*

5. **A** — Per *Use liquid clustering for tables* (Automatic liquid clustering) and the `CLUSTER BY` clause reference, `CLUSTER BY AUTO` "directs Delta Lake to automatically determine and over time adapt to the best columns to cluster by," which is the recommended approach for tables with frequently changing query patterns. It "analyzes the table's historical query workload," "adapts to changes," and "changes clustering keys only when the predicted cost savings from data skipping improvements outweigh the data clustering cost." B reverts to rigid partitioning with costly full rewrites. C is wrong: automatic liquid clustering "requires predictive optimization" and "automatic key selection and clustering operations run asynchronously as a maintenance operation," not synchronously per query. D both exceeds practical key guidance and ignores the explicit need for self-adapting keys. *(Objective: S10 Data Modelling — liquid clustering for layout and query perf, CLUSTER BY AUTO)*
