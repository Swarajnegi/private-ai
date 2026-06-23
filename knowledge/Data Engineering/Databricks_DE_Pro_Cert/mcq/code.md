# Developing Code (Python/SQL) — Practice MCQs (22%)

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

---

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
