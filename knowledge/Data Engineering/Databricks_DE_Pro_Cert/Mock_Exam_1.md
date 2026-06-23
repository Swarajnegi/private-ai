# Databricks Certified Data Engineer Professional — FULL MOCK EXAM #1

> **Objectives basis:** Official exam guide (Nov 30, 2025). 59 scenario MCQs, 4 options each, one defensible answer.
> **Domain distribution (scored):** Developing Code 13 · Cost & Performance 8 · Monitoring & Alerting 6 · Transform/Quality 6 · Security & Compliance 6 · Debugging & Deploying 6 · Data Ingestion 4 · Governance 4 · Data Modelling 3 · Sharing & Federation 3 = **59**.
> **Verification:** Each item grounded against current Databricks docs (docs.databricks.com, June 2026) via WebFetch on the relevant topic page (AUTO CDC, liquid clustering, deletion vectors, streaming tables vs MVs, CDF, system tables, row filters/column masks, Delta Sharing D2D/D2O, DABs, Auto Loader, job repair, Lakehouse Federation, Pandas UDFs, data skipping, UC managed tables).
> **Usage:** Answer all 59 before scrolling to the Answer Key. Passing target ~80%.

---

## Section A — Questions

### 1.
A data engineering team wants a single repository that defines jobs, Lakeflow Spark Declarative Pipelines, and per-environment (dev/prod) workspace targets, version-controlled and deployable through CI/CD. Which Databricks artifact and file are the correct foundation?

- A. A `.dbc` archive exported from the workspace and re-imported per environment
- B. A Databricks Asset Bundle defined in a `databricks.yml` file with `targets` for each environment
- C. A Terraform module that calls the Jobs REST API directly for each notebook
- D. A `requirements.txt` committed to a Git Folder and synced on each run

### 2.
A bundle has `mode: development` on the `dev` target and `mode: production` on the `prod` target. A developer deploys to `dev`. Which statement best describes the behavior of `mode: development`?

- A. It deploys resources with a `[dev <user>]` name prefix and pauses schedules/triggers so dev deploys don't run on production schedules
- B. It enforces that all jobs run on a shared production job cluster to save cost
- C. It blocks deployment unless a Git tag is present, ensuring reproducibility
- D. It automatically grants `CAN_MANAGE` on all resources to every workspace user

### 3.
A pipeline must use a vendor's proprietary parsing logic packaged as a local `.whl` file plus one PyPI package pinned to an exact version, installed deterministically as part of deployment. What is the most maintainable approach?

- A. `pip install` the wheel inside the notebook's first cell at runtime, every run
- B. Declare both as environment/library dependencies in the bundle/job configuration so they install at cluster/environment provisioning
- C. Copy the wheel's source code into the notebook to avoid managing the binary
- D. Add the wheel to the cluster's init script with `dbutils.fs.cp` on each start

### 4.
A team is choosing between a streaming table and a materialized view for a Lakeflow Declarative Pipelines dataset that joins a large fact stream to a slowly changing dimension, where downstream consumers require results that always reflect the latest dimension values. Which is the better fit and why?

- A. Streaming table, because each input row is processed exactly once and joins are recomputed when the dimension changes
- B. Materialized view, because it recomputes results when underlying data (including the dimension) changes, keeping joins correct
- C. Streaming table, because materialized views cannot perform joins
- D. Materialized view, because it processes each input row only once with the lowest possible latency

### 5.
Using the AUTO CDC (formerly APPLY CHANGES) API, an engineer must process a CDC feed where late-arriving events can appear out of order, deletes are flagged by `op = 'D'`, and full version history must be retained. Which combination of clauses is required?

- A. `SEQUENCE BY event_ts`, `APPLY AS DELETE WHEN op = 'D'`, `STORED AS SCD TYPE 2`
- B. `ORDER BY event_ts`, `WHERE op != 'D'`, `STORED AS SCD TYPE 1`
- C. `SEQUENCE BY event_ts`, `APPLY AS TRUNCATE WHEN op = 'D'`, `STORED AS SCD TYPE 1`
- D. `PARTITION BY event_ts`, `APPLY AS DELETE WHEN op = 'D'`, `STORED AS SCD TYPE 2`

### 6.
A Python UDF calling a pure-Python scoring function is the bottleneck in a transform over 2 billion rows. Profiling shows most time is spent serializing rows between the JVM and the Python worker. Which change yields the largest, lowest-risk speedup while keeping the same logic in Python?

- A. Increase `spark.sql.shuffle.partitions` to 2000
- B. Convert the row-at-a-time Python UDF to a vectorized Pandas UDF that processes Apache Arrow batches
- C. Broadcast the UDF closure to all executors
- D. Cache the input DataFrame before applying the UDF

### 7.
An engineer writes a unit test for a transformation and wants to assert that the produced DataFrame matches an expected DataFrame in both rows and schema, ignoring row order. Which API should they use?

- A. `assert df1 == df2`
- B. `pyspark.testing.assertDataFrameEqual(actual, expected)`
- C. `df1.subtract(df2).count() == 0` only
- D. `df1.collect() == df2.collect()`

### 8.
A Lakeflow Declarative Pipeline must conditionally run a backfill dataset only when a parameter `run_backfill` is true, and otherwise run the incremental path. Which pipeline capability supports this branching cleanly?

- A. There is no branching; you must maintain two separate pipelines
- B. Pipeline control-flow operators such as if/else (and for/each for iteration)
- C. A `WHERE 1=0` predicate that no-ops the dataset
- D. Pausing the dataset manually in the UI before each run

### 9.
A notebook task performs an in-memory aggregation that occasionally OOMs the driver. The team wants this specific task to run on a high-memory configuration without affecting other tasks. Where is the correct place to set this?

- A. Hardcode `spark.driver.memory` inside the notebook with `spark.conf.set`
- B. Configure a task-level environment/compute spec (high-memory cluster) for that task in the job/bundle configuration
- C. Increase `maxResultSize` to unlimited globally for the workspace
- D. Wrap the aggregation in a `try/except` and retry on failure

### 10.
A job's tasks must NOT be automatically retried because a retry would double-write to an external system. Which configuration is correct?

- A. Set `max_retries = -1` (infinite) so it eventually succeeds
- B. Set the task retry policy to 0 retries (disallow retries)
- C. Enable auto-optimization, which prevents retries
- D. Set the cluster autoscaling minimum to 0

### 11.
A team is structuring a scalable Python project for deployment via DABs and wants reusable transformation logic importable across notebooks and jobs, plus unit-testable functions. What is the recommended structure?

- A. Put all logic inline in one giant notebook and copy-paste across jobs
- B. Package shared logic into a Python module/wheel inside the bundle, import it in thin notebook/entry-point tasks, and test the module with pytest
- C. Store logic in a Delta table and `eval()` it at runtime
- D. Use `%run` to chain twenty notebooks together with no module boundaries

### 12.
A team must choose between hand-coded Spark Structured Streaming and Lakeflow Spark Declarative Pipelines (SDP) for a new multi-stage medallion pipeline. Which is the strongest reason to choose SDP?

- A. SDP gives lower-level control over checkpoint paths and trigger semantics than Structured Streaming
- B. SDP provides declarative dependency resolution between datasets, managed orchestration, built-in data quality expectations, and event logs out of the box
- C. SDP is the only way to read from Kafka
- D. SDP cannot run in continuous mode, forcing simpler batch semantics

### 13.
A data steward wants to attach governed, searchable classifications (e.g., `PII`, `sensitivity=high`) to columns across many tables so they can be discovered and policy-managed centrally in Unity Catalog. Which mechanism is the correct fit?

- A. Unity Catalog tags (key-value tags on catalogs/schemas/tables/columns), which are governed and queryable for discovery and policy
- B. Free-text comments only, parsed by a nightly regex job
- C. Column name prefixes like `pii_` enforced by code review
- D. A spreadsheet maintained outside Databricks

### 14.
A scheduled ETL must be created and version-controlled so it deploys identically across staging and prod, with the ability to trigger ad-hoc runs and inspect run history programmatically. Which combination of interfaces is most appropriate end-to-end?

- A. Jobs UI only, manually recreated per environment
- B. Define the job in a DAB (IaC) and operate it via the Jobs REST API / Databricks CLI for triggering and run inspection
- C. Cron on a driver node calling `spark-submit`
- D. A notebook widget that a user clicks each morning

### 15.
A streaming table downstream of a bronze table only needs to react to rows that changed, but the upstream table receives `MERGE` updates (not just appends). Reading it as a streaming source fails because of the non-append changes. Which feature resolves this?

- A. Enable Change Data Feed (CDF) on the upstream table and stream its `readChangeFeed` output
- B. Add `ignoreChanges = true` and accept silently dropping deletes
- C. Convert the upstream table to Parquet
- D. Disable deletion vectors on the upstream table

### 16.
Using the `DataFrame.transform` method to compose pipeline steps offers which concrete benefit for testability and readability?

- A. It forces lazy evaluation off so each step runs eagerly for debugging
- B. It lets you chain named, individually unit-testable functions that each take and return a DataFrame
- C. It automatically caches every intermediate DataFrame
- D. It converts the DataFrame to Pandas for the duration of the chain

### 17.
An engineer wants to assert that two DataFrames have identical schemas (names, types, nullability) in a test, independent of the data. Which is the most precise tool?

- A. `assertSchemaEqual(actual_schema, expected_schema)` from `pyspark.testing`
- B. `df1.printSchema() == df2.printSchema()`
- C. Comparing `len(df1.columns) == len(df2.columns)`
- D. `df1.dtypes == df2.dtypes` only

### 18.
A team troubleshoots a job failing with `ModuleNotFoundError` for a PyPI library that works locally. The library is installed only on a notebook session via `%pip install` in a different notebook on a shared cluster. What is the correct durable fix?

- A. Re-run `%pip install` in every notebook at the top, forever
- B. Declare the library as a cluster/job/environment dependency (or via the bundle) so it installs for all tasks on that compute deterministically
- C. Add the package to the Spark config `spark.jars.packages`
- D. Switch to a single-user cluster so the install persists across all jobs globally

### 19.
A team wants Git-based CI/CD where a merge to `main` triggers tests and a bundle deploy to prod. Which combination matches Databricks' recommended pattern?

- A. Databricks Git Folders (Repos) for source + Databricks Asset Bundles deployed from a CI runner (`databricks bundle deploy -t prod`)
- B. Manually export notebooks as `.py` and email them to prod admins
- C. Store notebooks in DBFS and copy with `dbutils.fs.cp` on merge
- D. Use the workspace UI "Clone" button into a prod workspace

### 20.
A table receives frequent single-row `DELETE`s for GDPR requests. Without deletion vectors, each delete rewrites entire Parquet files. After enabling deletion vectors, what is the immediate effect of a `DELETE`?

- A. Rows are marked as removed via a deletion vector (soft delete) and files are not rewritten until a later OPTIMIZE/PURGE
- B. The whole table is rewritten in copy-on-write fashion but faster
- C. Deletes are queued and applied only at VACUUM
- D. The deleted rows remain readable until `REFRESH TABLE` is run

### 21.
A 5 TB table is partitioned by a high-cardinality `customer_id`, producing millions of tiny files and slow queries. The team wants flexible data layout that adapts as query patterns change and can evolve keys without rewriting all data. What should they adopt?

- A. Increase the number of partitions and add ZORDER on top of partitioning
- B. Convert to liquid clustering (`CLUSTER BY`), which avoids the small-file/over-partitioning problem and allows changing keys without full rewrite
- C. Keep partitioning but enable `optimizeWrite` only
- D. Bucket the table by `customer_id` into 10,000 buckets

### 22.
For a Delta table using liquid clustering, an engineer changes the clustering keys with `ALTER TABLE ... CLUSTER BY (...)`. What is true about existing data after this command?

- A. All existing data is immediately re-clustered synchronously by the ALTER statement
- B. Existing data is unchanged until subsequent `OPTIMIZE` (or `OPTIMIZE FULL`) and new writes apply the new clustering
- C. The table becomes unreadable until a full rewrite finishes
- D. The clustering keys cannot be changed once set

### 23.
Why does column ordering matter for data skipping on a Delta table that relies on default statistics collection?

- A. Delta collects min/max/null statistics on the first 32 columns by default; filter columns placed beyond that get no stats and cannot prune files
- B. Spark reads columns left-to-right and stops at the first match
- C. Parquet only compresses the first 32 columns
- D. Column order changes the physical sort order automatically

### 24.
A streaming table that aggregates and joins has unacceptable latency and re-reads large upstream tables every micro-batch. Which technique most directly reduces this by feeding only changed rows downstream?

- A. Use Change Data Feed (CDF) on the upstream Delta tables so downstream consumes only changed rows instead of full re-reads
- B. Increase the trigger interval to once per hour
- C. Disable schema inference
- D. Switch the sink to Parquet

### 25.
A team wants to minimize ongoing operational overhead — no manual OPTIMIZE/VACUUM scheduling, automatic statistics and clustering maintenance. Which choice best achieves this?

- A. External tables on a manually managed S3 prefix with a nightly maintenance job
- B. Unity Catalog managed tables, which use predictive optimization to run OPTIMIZE/VACUUM/ANALYZE and auto-clustering automatically
- C. Hive metastore managed tables with a cron-based VACUUM
- D. Parquet tables registered as external

### 26.
A query profile shows a large `Exchange` (shuffle) stage dominating runtime on a `GROUP BY` over a skewed key where one key holds 60% of rows. Which is the most targeted fix?

- A. Address skew (e.g., enable AQE skew handling / salt the hot key) to break up the oversized partition
- B. Increase driver memory
- C. Disable data skipping
- D. Add a broadcast hint to the GROUP BY

### 27.
A query profile shows a `SortMergeJoin` spilling heavily on a join between a 2 TB fact and a 40 MB dimension that easily fits in executor memory. What is the most effective optimization?

- A. Force a broadcast hash join of the small dimension (e.g., `broadcast()` / ensure it is under the broadcast threshold)
- B. Increase `spark.sql.shuffle.partitions` to reduce spill
- C. Repartition the fact table by the join key into 50 partitions
- D. Cache the fact table before joining

### 28.
After enabling deletion vectors and running many deletes, an auditor requires that the physically deleted PII be unrecoverable from the underlying Parquet files. Which command must be run (in addition to VACUUM) to materialize the soft-deletes?

- A. `REORG TABLE ... APPLY (PURGE)` to rewrite files removing deletion-vector-marked rows
- B. `REFRESH TABLE`
- C. `MSCK REPAIR TABLE`
- D. `ALTER TABLE ... SET TBLPROPERTIES (delta.deletionVectors = false)` alone

### 29.
An engineer must observe how much DBU cost each job and SQL warehouse consumed last month, attributed by tag. Which system table is the authoritative source?

- A. `system.billing.usage` (joined with `system.billing.list_prices` for dollarized cost)
- B. `system.access.audit`
- C. `system.compute.clusters`
- D. `information_schema.tables`

### 30.
A security team must answer "who accessed table X, and from which workspace, over the last 90 days?" Which system table answers this?

- A. `system.access.audit`
- B. `system.billing.usage`
- C. `system.compute.warehouses`
- D. `system.lakeflow.jobs`

### 31.
An engineer needs to find the exact stage where a slow SQL query spends most of its time, including whether the optimizer chose a broadcast vs shuffle join and how many files were pruned. Which tool is purpose-built for this?

- A. The Query Profiler UI (query profile) for the SQL query
- B. The cluster's Ganglia metrics
- C. The Jobs run list
- D. `EXPLAIN` output pasted into a notebook only

### 32.
A Lakeflow Declarative Pipeline silently produced fewer rows than expected. Where should the engineer look first to see expectation (data quality) results, dataset-level metrics, and flow progress for that pipeline run?

- A. The SDP event log (pipeline event log / pipeline-events system table)
- B. The billing usage table
- C. The workspace audit log only
- D. The Spark history server on a terminated cluster

### 33.
An on-call engineer must programmatically poll the status of running jobs and pipelines and react in an external system. Which interface is appropriate?

- A. The Jobs/Pipelines REST API (or Databricks CLI) to query run state
- B. Reading the cluster's `stderr` log file over SSH
- C. The Query Profiler UI
- D. The Delta transaction log directly

### 34.
A job should notify a Slack/email channel on failure and on prolonged runtime (a duration threshold being exceeded). Where is this configured natively?

- A. Job-level notifications in the Jobs UI/API (on start/success/failure and run-duration thresholds)
- B. Only via a custom webhook written inside each notebook
- C. In the cluster init script
- D. Through `system.access.audit` triggers

### 35.
An engineer must build observability of executor memory pressure on a long-running job, inspecting GC time, shuffle read/write, and task-level spill. Which tool surfaces these metrics?

- A. The Spark UI (stages/tasks tab, executors tab)
- B. The billing usage system table
- C. SQL Alerts
- D. The Catalog Explorer lineage tab

### 36.
A query-profile analysis shows "bad data skipping": for a selective `WHERE region = 'APAC'` filter (2% of rows) almost no files are pruned, because the large table is randomly ordered. What is the correct remediation?

- A. Cluster (liquid clustering) or ZORDER the table on `region` to co-locate matching rows into fewer files, improving file pruning
- B. Add more shuffle partitions
- C. Convert the filter to a `LIKE` predicate
- D. Disable the Photon engine

### 37.
An engineer wants an automatic notification when a daily data-quality metric (e.g., null rate in a key column) crosses a threshold, evaluated on a schedule against a query result. Which Databricks feature is designed for this?

- A. Databricks SQL Alerts (schedule a query and trigger when a condition is met)
- B. Spark UI thresholds
- C. Delta `NOT NULL` table constraints
- D. A manual dashboard refresh

### 38.
A pipeline must quarantine records that fail a quality rule (e.g., negative amounts) so good data still flows while bad data is captured for review. In Lakeflow Declarative Pipelines, which mechanism implements this quarantine pattern?

- A. Expectations: route failing rows to a quarantine dataset (e.g., an expectation flag column / separate flow) while valid rows continue downstream
- B. Drop the whole micro-batch if any row fails
- C. Disable the dataset until the data is fixed manually
- D. Cast the bad values to NULL silently and continue

### 39.
An engineer must enforce that only members of the `pii_readers` account group can see the full `email` column, while everyone else sees a hashed value, without creating a separate view. Which Unity Catalog feature applies?

- A. A column mask (SQL UDF) applied via `ALTER TABLE ... ALTER COLUMN email SET MASK`, using `is_account_group_member('pii_readers')` to branch
- B. A row filter on the table
- C. Table ACL `DENY SELECT` on the column
- D. A dynamic view replacing the table for non-members

### 40.
A compliance requirement states analysts in region EU may only see rows where `region = 'EU'`, enforced at the table level for all queries regardless of client tool. Which feature is correct?

- A. A row filter (SQL UDF returning a boolean) attached via `ALTER TABLE ... SET ROW FILTER`
- B. A `WHERE` clause that analysts are asked to remember to add
- C. A column mask on `region`
- D. Partitioning by `region`

### 41.
For irreversible de-identification of a customer identifier so the original can never be recovered, while still allowing joins across datasets on the same identifier, which anonymization technique is most appropriate?

- A. Deterministic hashing (e.g., SHA-256 with a consistent salt) — same input maps to same token, original not recoverable
- B. Generalization to age buckets
- C. Suppression (dropping the column)
- D. Reversible tokenization with a lookup vault

### 42.
A streaming PII-masking pipeline must mask emails before data lands in the silver layer and remain compliant for both the streaming path and a backfill batch path. What is the most robust design?

- A. Apply the same masking transformation (column mask UDF or shared in-pipeline function) consistently in both the streaming and batch code paths
- B. Mask only in the streaming path; the batch backfill is internal so it can stay raw
- C. Mask at the BI dashboard layer only
- D. Rely on table ACLs to hide the raw email column from the silver table

### 43.
A retention policy requires records older than 7 years be permanently purged from a Delta table including from underlying files. Which sequence is correct?

- A. `DELETE` the aged rows, then after the retention window `VACUUM` (and, with deletion vectors, run `REORG ... PURGE`) so old files are physically removed
- B. `DROP TABLE` and recreate it empty
- C. Set `delta.logRetentionDuration` to 0
- D. `TRUNCATE TABLE` regardless of age

### 44.
An admin must enforce least-privilege on workspace objects (notebooks, jobs, folders). Which statement reflects correct ACL practice?

- A. Grant the minimum permission level needed (e.g., `CAN_VIEW`/`CAN_RUN`) per principal and prefer group-based grants over per-user grants
- B. Grant `CAN_MANAGE` to all developers for convenience
- C. Use the workspace admin account for all job runs
- D. Disable ACLs and rely on network isolation

### 45.
A job intermittently fails at task 4 of 6; tasks 1–3 succeeded and are expensive to recompute. The engineer fixes a bad parameter. What is the most cost-effective remediation?

- A. Use a repair run, which re-runs only the failed/skipped tasks (and their dependents), reuses successful upstream tasks, and accepts a corrected parameter override
- B. Clone the job and run it from scratch
- C. Re-run the entire job with `run now`
- D. Delete the job history and recreate it

### 46.
A Spark job fails with `Job aborted due to stage failure: ... java.lang.OutOfMemoryError` on executors during a wide aggregation. Which diagnostic path correctly localizes the cause?

- A. Inspect the Spark UI (stages/tasks, GC time, spill, shuffle read/write) and executor logs to confirm the OOM stage, then address skew/partitioning
- B. Read `system.billing.usage` to find the cost
- C. Increase the job's max retries to 10
- D. Switch the job to a single-node cluster

### 47.
A failed SDP pipeline run must be diagnosed: which datasets failed, which expectations dropped rows, and the underlying Spark errors. Which two surfaces are the correct first stops?

- A. The SDP event log (for flow/expectation/dataset events) and the Spark UI (for task-level errors)
- B. The billing usage table and the Query Profiler
- C. The Git Folder history and the notebook revision log
- D. The DNS resolver logs and the workspace audit log

### 48.
During deployment, `databricks bundle validate` passes but `databricks bundle deploy -t prod` fails with a permissions error on a target schema. What is the correct interpretation?

- A. Validate only checks configuration syntax/resolution; deploy actually provisions and needs the deploying principal to hold the required UC privileges on the target
- B. Validate should have caught the permission issue; this is a CLI bug
- C. The bundle must be re-initialized from scratch
- D. Permissions cannot be the cause; it must be a network timeout

### 49.
A nightly job failed and the engineer wants to rerun only the failed task with a different `process_date` parameter without altering the saved job definition. Which capability supports this?

- A. A repair run with a parameter override for that run only
- B. Editing the job JSON permanently and re-running
- C. Cloning the workspace
- D. There is no way to override parameters per run

### 50.
A team must ingest data arriving from a Kafka-style message bus and from cloud object storage, landing it append-only into Delta with schema tracking. Which pairing is correct?

- A. Structured Streaming `readStream` from the message bus and Auto Loader (`cloudFiles`) for the object-storage path, both writing append-only to Delta
- B. `COPY INTO` for Kafka and `cloudFiles` for storage
- C. JDBC reads for both
- D. `spark.read.json` in a loop for both

### 51.
An engineer must ingest a directory of AVRO files and a separate set of binary image files into Delta. Which statement is accurate about format support?

- A. Auto Loader / Spark read AVRO (and JSON/CSV/Parquet/ORC/text/binaryFile) directly; the `binaryFile` format ingests raw bytes plus path/length/modificationTime metadata
- B. AVRO must be converted to JSON first; binary files cannot be ingested
- C. Only Parquet and Delta are supported as ingestion sources
- D. Binary files must be base64-encoded into a CSV before ingestion

### 52.
When ingesting semi-structured JSON whose schema occasionally adds new fields, an engineer wants any data that does not conform to the inferred schema to be preserved rather than silently dropped. Which Auto Loader feature provides this?

- A. The `_rescued_data` column, which captures fields that don't match the inferred schema
- B. `mergeSchema = true` on every read
- C. `badRecordsPath`, which deletes malformed rows
- D. `cloudFiles.maxFilesPerTrigger` set to 1

### 53.
A batch ingestion must be strictly append-only into a Delta table and must not duplicate rows if the job is re-run after a partial failure. Which design ensures this with Auto Loader?

- A. Auto Loader's checkpoint tracks processed files, so re-running resumes without reprocessing already-ingested files (exactly-once at file granularity), writing in append mode
- B. Use `overwrite` mode so re-runs replace everything
- C. Disable the checkpoint to force a clean reread
- D. Manually delete the checkpoint before every run

### 54.
A provider on Databricks wants to share live Delta tables, notebooks, and ML models with another organization that also runs Databricks on Unity Catalog, with no credential file exchange. Which sharing model applies?

- A. Delta Sharing Databricks-to-Databricks (D2D), which requires UC on both sides and supports tables, notebooks, volumes, and models without token files
- B. Open sharing (D2O) with a bearer-token credential file
- C. Lakehouse Federation foreign catalog
- D. A nightly export to a shared S3 bucket

### 55.
An external partner runs only Pandas/Power BI (no Databricks) and must read a shared Delta table. Which sharing approach is correct?

- A. Delta Sharing open protocol (D2O) using a bearer token / credential file (or OIDC federation) that the partner's client uses to read the share
- B. D2D sharing, since it works for any platform
- C. Grant them a Databricks login and a single-user cluster
- D. Email Parquet extracts daily

### 56.
A team must run governed, read-only analytical queries directly against an operational PostgreSQL database without ingesting/ETL-ing the data into the lakehouse, while still applying Unity Catalog access controls and lineage. Which feature fits?

- A. Lakehouse Federation: create a connection and a foreign catalog over PostgreSQL; UC governs access and query pushdown minimizes data movement
- B. Delta Sharing D2D
- C. Auto Loader from the PostgreSQL data directory
- D. `COPY INTO` from a JDBC URL

### 57.
A data steward wants tables and columns to be discoverable in Catalog Explorer with business context. Which governance practice directly supports discoverability?

- A. Add descriptions/comments and metadata (table/column `COMMENT`, tags) so assets are searchable and self-describing in Unity Catalog
- B. Rename every column to a numeric code
- C. Store documentation only in an external wiki
- D. Hide table metadata to reduce clutter

### 58.
A user is granted `SELECT` on a catalog in Unity Catalog. According to the UC permission inheritance model, what is the effect on schemas and tables within that catalog?

- A. The privilege is inherited downward: `SELECT` on the catalog applies to all current and future schemas and tables within it (unless overridden)
- B. The grant applies only to the catalog object and must be re-granted on every table individually
- C. Inheritance flows upward from tables to the catalog
- D. Catalog grants are ignored unless a matching workspace ACL exists

### 59.
An admin must ensure a new schema created tomorrow under an existing catalog is automatically usable by the analytics group without re-granting. Which approach leverages UC inheritance correctly?

- A. Grant `USE CATALOG` + `SELECT` (and `USE SCHEMA` as needed) at the catalog level so future schemas/tables inherit the privilege
- B. Grant on each table after it is created, via a nightly script
- C. Add the group to the workspace admins
- D. There is no inheritance; every object must be granted explicitly

---

## Answer Key & Explanations

> Format: **Q# — Answer** · explanation · `[Domain]`. Each question carries exactly one primary domain tag; the tags sum to the required distribution (13/8/6/6/6/6/4/4/3/3).

**Q1 — B.** A Databricks Asset Bundle (`databricks.yml`) is the IaC unit bundling jobs + pipelines + per-environment `targets` under source control and CI/CD. `.dbc` archives and ad-hoc REST/Terraform calls don't give the unified, declarative, environment-targeted deployment DABs provide. `[Developing Code]`

**Q2 — A.** `mode: development` prefixes resource names with `[dev <user>]` and pauses schedules/triggers so dev deploys don't fire on prod cadence, isolating per-developer deployments. It does not force shared clusters, require Git tags, or grant blanket permissions. `[Developing Code]`

**Q3 — B.** Declare the local wheel and the pinned PyPI package as bundle/job/environment library dependencies so they install deterministically at provisioning. Runtime `pip install` per run is non-deterministic and slow; copying source or init-script hacks add debt. `[Developing Code]`

**Q4 — B.** Materialized views recompute when underlying data (including the dimension) changes, so the join stays correct. Streaming tables process each row once with "fast-but-wrong" join semantics and do not recompute against dimension changes. MVs can perform joins, so C is false. `[Data Modelling]`

**Q5 — A.** `SEQUENCE BY` orders out-of-order events; `APPLY AS DELETE WHEN op='D'` flags deletes; `STORED AS SCD TYPE 2` retains full history (`__START_AT`/`__END_AT`). SCD Type 1 discards history; `ORDER/PARTITION BY` and `APPLY AS TRUNCATE` are not the CDC clauses. `[Developing Code]`

**Q6 — B.** A vectorized Pandas UDF transfers data in Apache Arrow columnar batches and runs per-batch, eliminating per-row JVM↔Python serialization — up to ~100× faster while keeping the Python logic. Shuffle/broadcast/cache don't address the serialization bottleneck. `[Transform/Quality]`

**Q7 — B.** `pyspark.testing.assertDataFrameEqual` compares rows and schema with order-insensitivity and clear diffs. `==`, `collect()==`, and one-sided `subtract` are fragile or incomplete. `[Transform/Quality]`

**Q8 — B.** Lakeflow Declarative Pipelines support control-flow operators (if/else, for/each) for conditional/iterative dataset execution. Maintaining two pipelines or no-op predicates are anti-patterns. `[Developing Code]`

**Q9 — B.** Set a task-level environment/compute spec (a high-memory cluster) for that one task in the job/bundle config, isolating it. Notebook `spark.conf.set` won't change driver memory at runtime; global `maxResultSize` is blunt; retrying doesn't fix OOM. `[Developing Code]`

**Q10 — B.** Set the task retry policy to 0 (disallow retries) so a non-idempotent external write isn't duplicated. Infinite retries worsen it; "auto-optimization prevents retries" and autoscaling min are unrelated. `[Developing Code]`

**Q11 — B.** Package shared logic into an importable module/wheel inside the bundle, keep notebooks/entry points thin, and unit-test the module with pytest. Giant notebooks, `eval()` from a table, and 20-deep `%run` chains create debt and aren't testable. `[Developing Code]`

**Q12 — B.** SDP gives declarative inter-dataset dependency resolution, managed orchestration, built-in expectations, and event logs out of the box — the strongest reason over hand-coded Structured Streaming. Lower-level checkpoint control is a Structured Streaming trait; SDP can read Kafka and supports continuous mode. `[Developing Code]`

**Q13 — A.** Unity Catalog tags are governed key-value pairs attachable to catalogs/schemas/tables/columns; they are centrally queryable (via `information_schema`/system tables) for discovery and policy management. Free-text comments, naming conventions, and external spreadsheets are not governed or reliably queryable. `[Governance]`

**Q14 — B.** Define the job as IaC in a DAB for identical multi-environment deploys, then trigger and inspect runs via the Jobs REST API / Databricks CLI. UI-only recreation, driver cron, and manual widgets don't scale or reproduce. `[Developing Code]`

**Q15 — A.** Enable Change Data Feed on the upstream table and stream `readChangeFeed`; this lets a streaming consumer handle non-append (MERGE) changes by reading the change rows. `ignoreChanges` silently mishandles deletes; format/DV changes don't solve it. `[Transform/Quality]`

**Q16 — B.** `DataFrame.transform` chains named functions that each take and return a DataFrame, so each step is independently unit-testable and the pipeline reads top-to-bottom. It doesn't disable laziness, auto-cache, or convert to Pandas. `[Developing Code]`

**Q17 — A.** `assertSchemaEqual` precisely compares names, types, and nullability independent of data. `printSchema()` returns None, column-count equality is too weak, and `dtypes` ignores nullability. `[Transform/Quality]`

**Q18 — B.** The durable fix is declaring the library as a cluster/job/environment (or bundle) dependency so every task on that compute gets it deterministically. Re-running `%pip` per notebook is fragile; `spark.jars.packages` is for JVM jars; switching cluster modes doesn't make a session install global. `[Developing Code]`

**Q19 — A.** Databricks Git Folders (Repos) hold the source; CI runs tests and executes `databricks bundle deploy -t prod` (DABs) on merge — the recommended Git-based CI/CD pattern. Emailing `.py`, DBFS copies, and UI "Clone" are not CI/CD. `[Developing Code]`

**Q20 — A.** With deletion vectors, a `DELETE` is a soft delete: affected rows are marked in a deletion vector and Parquet files are not rewritten until a later OPTIMIZE/auto-compaction/PURGE (merge-on-read). It's not copy-on-write, not deferred-to-VACUUM, and deleted rows are immediately filtered on read. `[Cost & Performance]`

**Q21 — B.** Liquid clustering replaces partitioning here: it avoids over-partitioning/small files on high-cardinality keys and lets keys evolve without full rewrite. More partitions+ZORDER, write-optimize alone, or heavy bucketing don't solve the small-file/rigidity problem. `[Data Modelling]`

**Q22 — B.** Changing `CLUSTER BY` keys does not rewrite existing data; the new clustering applies on subsequent `OPTIMIZE`/`OPTIMIZE FULL` and new writes. The ALTER isn't synchronous, the table stays readable, and keys are changeable (a core liquid-clustering benefit). `[Data Modelling]`

**Q23 — A.** Delta collects min/max/null stats on the first 32 columns by default (`delta.dataSkippingNumIndexedCols`); filter columns beyond that get no stats and can't drive file pruning, so column order/placement matters. Spark doesn't scan left-to-right stopping at a match; Parquet compression and physical sort are unrelated. `[Cost & Performance]`

**Q24 — A.** Change Data Feed lets downstream consume only changed rows instead of re-reading entire upstream tables each micro-batch, directly cutting latency/work — the documented way to address streaming-table latency limitations. Longer triggers raise latency; schema/sink changes don't address re-reads. `[Cost & Performance]`

**Q25 — B.** Unity Catalog managed tables use predictive optimization to run OPTIMIZE/VACUUM/ANALYZE and auto-clustering automatically, minimizing operational overhead. External/Hive/Parquet-external options require manual maintenance jobs. `[Cost & Performance]`

**Q26 — A.** A single dominant key is data skew; the targeted fix is AQE skew handling or salting the hot key to split the oversized shuffle partition. Driver memory, disabling skipping, and a broadcast hint on a GROUP BY don't address the skewed shuffle. `[Transform/Quality]`

**Q27 — A.** A 40 MB dimension fits the broadcast threshold; broadcasting it converts the spilling SortMergeJoin into a broadcast hash join with no fact-table shuffle. More shuffle partitions, repartitioning, or caching don't eliminate the shuffle. `[Cost & Performance]`

**Q28 — A.** `REORG TABLE ... APPLY (PURGE)` rewrites files to physically remove deletion-vector-marked rows; combined with VACUUM (after the retention window) the PII becomes unrecoverable. `REFRESH`/`MSCK`/just disabling DV don't materialize the purge. `[Cost & Performance]`

**Q29 — A.** `system.billing.usage` records DBU usage (taggable for attribution) and joins with `system.billing.list_prices` to dollarize cost. Audit/compute/info_schema tables don't carry billable usage. `[Monitoring & Alerting]`

**Q30 — A.** `system.access.audit` logs who did what — including table access events — by workspace, with ~365-day retention; it's the authoritative access/audit source. Billing/compute/jobs tables don't answer "who accessed." `[Monitoring & Alerting]`

**Q31 — A.** The Query Profiler UI (query profile) shows per-operator time, join strategy (broadcast vs shuffle), files pruned, and spill — purpose-built for finding SQL query bottlenecks (bad data skipping, join type, shuffle). Ganglia/Jobs list/raw EXPLAIN are coarser. `[Cost & Performance]`

**Q32 — A.** The SDP event log (pipeline event log / pipeline-events system table) records expectations results, dataset metrics, and flow progress for each pipeline run. Billing/audit/Spark-history aren't where pipeline quality and flow events live. `[Monitoring & Alerting]`

**Q33 — A.** The Jobs/Pipelines REST API (or Databricks CLI) exposes run state for programmatic polling and external reaction. SSH log scraping, the Query Profiler, and reading the Delta log are not the monitoring interface. `[Monitoring & Alerting]`

**Q34 — A.** Job-level notifications (Jobs UI/API) support start/success/failure and run-duration-threshold alerts to email/Slack/webhook destinations natively. Per-notebook webhooks, init scripts, and audit-table triggers aren't the native mechanism. `[Monitoring & Alerting]`

**Q35 — A.** The Spark UI (stages/tasks and executors tabs) surfaces GC time, shuffle read/write, and task-level spill for a running/finished job. Billing tables, SQL Alerts, and lineage don't expose executor memory metrics. `[Debugging & Deploying]`

**Q36 — A.** "Bad data skipping" on a randomly ordered table is fixed by co-locating matching rows via liquid clustering (or ZORDER) on `region`, so file pruning eliminates non-matching files. Shuffle partitions, `LIKE`, and disabling Photon don't improve pruning. `[Cost & Performance]`

**Q37 — A.** Databricks SQL Alerts schedule a query and trigger (notify) when a condition is met — ideal for a data-quality threshold. Spark UI has no alerting; `NOT NULL` constraints reject writes rather than alert on a metric; manual refresh isn't automated alerting. `[Monitoring & Alerting]`

**Q38 — A.** SDP expectations implement the quarantine pattern: failing rows are routed to a quarantine dataset (via an expectation flag / separate flow) while valid rows continue downstream — neither dropping the whole batch, pausing the dataset, nor silently nulling values. `[Transform/Quality]`

**Q39 — A.** A column mask is a SQL UDF set via `ALTER TABLE ... ALTER COLUMN email SET MASK`, branching on `is_account_group_member('pii_readers')` to return clear vs hashed values — applied on the table itself, no separate view. Row filters drop rows; column-level DENY isn't the UC mechanism; a dynamic view is the thing being avoided. `[Security & Compliance]`

**Q40 — A.** A row filter is a SQL UDF returning a boolean, attached via `ALTER TABLE ... SET ROW FILTER`, enforcing row-level access for all queries regardless of client tool. A remembered `WHERE`, a column mask, or partitioning don't enforce row-level security. `[Security & Compliance]`

**Q41 — A.** Deterministic salted hashing (e.g., SHA-256) is irreversible (original not recoverable) yet consistent, so the same identifier still joins across datasets. Generalization/suppression destroy join ability or the column; reversible tokenization keeps a recoverable mapping, violating "never recovered." `[Security & Compliance]`

**Q42 — A.** Apply the same masking transformation consistently across both the streaming and batch paths (shared logic or a column mask) so silver is compliant regardless of path. Masking only one path, only at BI, or relying on ACLs over raw data leaves PII exposed somewhere. `[Security & Compliance]`

**Q43 — A.** Compliant purging: `DELETE` the aged rows, then after the retention window `VACUUM` (and, with deletion vectors, `REORG ... PURGE`) to physically remove the underlying files. Dropping/recreating loses the table; log-retention=0 and `TRUNCATE` don't selectively purge by age. `[Security & Compliance]`

**Q44 — A.** Least privilege = grant the minimum level needed (e.g., `CAN_VIEW`/`CAN_RUN`) and prefer group-based grants for manageability. Blanket `CAN_MANAGE`, shared admin runs, and disabling ACLs violate least privilege. `[Security & Compliance]`

**Q45 — A.** A repair run reruns only failed/skipped tasks (and their dependents), reuses successful upstream tasks 1–3, and accepts a corrected parameter override — the cheapest correct recovery. Cloning or full reruns recompute the expensive successful tasks. `[Debugging & Deploying]`

**Q46 — A.** Use the Spark UI (stage/task metrics, GC, spill, shuffle read/write) plus executor logs to confirm the OOM stage and root cause (skew/partitioning), then fix layout. Billing cost, more retries, and single-node don't diagnose the OOM. `[Debugging & Deploying]`

**Q47 — A.** Diagnose SDP via the event log (failed flows, dropped-row expectation events, dataset status) and the Spark UI (task-level exceptions). Billing/profiler, Git history, and DNS/audit logs aren't the SDP debugging surfaces. `[Debugging & Deploying]`

**Q48 — A.** `bundle validate` only checks config syntax/variable resolution; `deploy` actually provisions and requires the deploying principal to hold the needed Unity Catalog privileges on the target schema. It's not a CLI bug, doesn't need re-init, and permissions absolutely can be the cause. `[Debugging & Deploying]`

**Q49 — A.** A repair run accepts a per-run parameter override (e.g., a new `process_date`) for just the failed task without changing the saved job definition. Editing the JSON is permanent; cloning the workspace is overkill; per-run overrides do exist. `[Debugging & Deploying]`

**Q50 — A.** Use Structured Streaming `readStream` for the message bus and Auto Loader (`cloudFiles`) for the object-storage path, both writing append-only to Delta. `COPY INTO`/JDBC for Kafka and `read.json` loops are wrong tools. `[Data Ingestion]`

**Q51 — A.** Spark/Auto Loader read AVRO (and JSON/CSV/Parquet/ORC/text) directly, and the `binaryFile` format ingests raw bytes plus `path`/`length`/`modificationTime` metadata. AVRO needs no JSON conversion; binary files don't need base64-in-CSV. `[Data Ingestion]`

**Q52 — A.** Auto Loader's `_rescued_data` column captures fields that don't match the inferred schema so nothing is silently dropped. `mergeSchema` changes the schema rather than preserving non-conforming data; `badRecordsPath` targets malformed records; `maxFilesPerTrigger` is throughput control. `[Data Ingestion]`

**Q53 — A.** Auto Loader's checkpoint tracks already-processed files (RocksDB key-value store), so a re-run after partial failure resumes without reprocessing — exactly-once at file granularity — while writing in append mode. `overwrite`, disabling, or deleting the checkpoint break idempotency. `[Data Ingestion]`

**Q54 — A.** Delta Sharing D2D requires Unity Catalog on both sides, exchanges no credential files, and can share tables, notebooks, volumes, and models. Open sharing (token file) is for non-UC/non-Databricks recipients; Federation and S3 export don't fit. `[Sharing & Federation]`

**Q55 — A.** A non-Databricks partner uses Delta Sharing open protocol (D2O) with a bearer token / credential file (or OIDC federation) read by Pandas/Power BI clients. D2D requires Databricks+UC on the recipient; provisioning logins or emailing extracts are wrong. `[Sharing & Federation]`

**Q56 — A.** Lakehouse Federation creates a connection + foreign catalog over PostgreSQL for governed, read-only queries with UC access controls/lineage and query pushdown — no ingestion needed. Delta Sharing, Auto Loader, and JDBC `COPY INTO` don't provide live federated UC governance. `[Sharing & Federation]`

**Q57 — A.** Adding descriptions/comments and metadata/tags (table and column `COMMENT`, tags) makes assets searchable and self-describing in Unity Catalog / Catalog Explorer. Numeric renames, external-only docs, and hiding metadata hurt discoverability. `[Governance]`

**Q58 — A.** UC privileges inherit downward: `SELECT` on a catalog applies to all current and future schemas/tables within it unless overridden lower down. Inheritance is top-down (catalog→schema→table), not per-object-only or upward, and isn't gated on a workspace ACL. `[Governance]`

**Q59 — A.** Granting `USE CATALOG` + `SELECT` (and `USE SCHEMA`) at the catalog level means future schemas/tables inherit the privilege automatically — no re-granting. Per-table nightly grants, workspace-admin membership, and "no inheritance" are wrong. `[Governance]`

---

### Domain map (primary tags — sum = 59)

| Domain | Questions | Count |
|---|---|---|
| Developing Code | Q1, Q2, Q3, Q5, Q8, Q9, Q10, Q11, Q12, Q14, Q16, Q18, Q19 | 13 |
| Cost & Performance | Q20, Q23, Q24, Q25, Q27, Q28, Q31, Q36 | 8 |
| Monitoring & Alerting | Q29, Q30, Q32, Q33, Q34, Q37 | 6 |
| Transform/Quality | Q6, Q7, Q15, Q17, Q26, Q38 | 6 |
| Security & Compliance | Q39, Q40, Q41, Q42, Q43, Q44 | 6 |
| Debugging & Deploying | Q35, Q45, Q46, Q47, Q48, Q49 | 6 |
| Data Ingestion | Q50, Q51, Q52, Q53 | 4 |
| Governance | Q13, Q57, Q58, Q59 | 4 |
| Data Modelling | Q4, Q21, Q22 | 3 |
| Sharing & Federation | Q54, Q55, Q56 | 3 |
