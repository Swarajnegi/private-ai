# Databricks DE Professional — Last-Day Cheat Sheet

**Exam logistics:** 59 questions · 120 min (~2 min/Q) · pass **70%** · **no API/doc reference** during exam · names renamed: DABs = Declarative Automation Bundles · DLT = Lakeflow SDP · Repos = Git folders · Delta Sharing = OpenSharing · Workflows = Lakeflow Jobs.

## System tables (`system.<schema>.<table>`)
| Table | What it gives | Don't-miss |
|---|---|---|
| `billing.usage` | DBU/usage fact, cost attribution | **DBUs not $** — join `list_prices`; **global**; no `job_id` for all-purpose; `usage_metadata.{job_id,dlt_pipeline_id,warehouse_id}` are join keys |
| `billing.list_prices` | SKU price history (× usage = $) | time-bounded join (`price_end_time IS NULL`=active) |
| `access.audit` | Who did what (Preview) | account events use `workspace_id=0`; `request_params` untyped |
| `compute.clusters` (SCD2) / `node_timeline` | cluster configs / minute-grain CPU+mem | **excludes serverless + SQL warehouses** (those = `compute.warehouses`/`warehouse_events`) |
| `lakeflow.jobs/job_tasks` (SCD2), `job_run_timeline`/`job_task_run_timeline` (fact) | job/pipeline defs + run timelines | long runs hour-**sliced**: `result_state`/`termination_code` only on **terminal row** → filter `result_state IS NOT NULL`; `workflow`==`lakeflow` |
| `lakeflow.pipelines`/`pipeline_update_timeline` | SDP runs | join via `dlt_pipeline_id` |
| `query.history` | SQL-warehouse + serverless statements (Preview) | `statement_text`=`<Redacted>` unless in `databricks_pii_access` group; **no classic clusters** |
| `storage.predictive_optimization_operations_history` | PO maintenance cost | 180-day retention |
Access: UC required; account admin enables each schema + grants `USE CATALOG`+`USE SCHEMA`+`SELECT`. Most retention 365d. SCD2 current state: `QUALIFY ROW_NUMBER() OVER (PARTITION BY workspace_id,id ORDER BY change_time DESC)=1`.

## Anonymization — 4 methods
| Method | Mechanism | Reversible | Primitive |
|---|---|---|---|
| **Hashing** (pseudonymize) | one-way digest, join-safe | No | `SHA2(val,256)` — **salt/version it** (small domain = brute-forceable) |
| **Tokenization** | random surrogate, map in separate vault | Yes | mapping table |
| **Suppression** | drop/null/redact | No | `mask()`, `'***'`, NULL |
| **Generalization** | reduce precision (DOB→year) | No | `regexp_extract`, `date_trunc`, binning |
*Docs: deletion beats all obfuscation when re-identification risk must be eliminated.* `mask(str)` → upper→X, lower→x, digit→n, other→unchanged.

## DABs commands & modes
`databricks bundle validate` → `deploy -t <target>` → `run -t <target> <name>` → `destroy` (deletes resources, **not data/tables**). Adopt existing: `generate` + `deployment bind`.
- `mode: development` → `[dev <user>]` prefix, schedules **paused**, editable. `mode: production` → no prefix, schedules active, UI editing **locked**, needs `host`+`root_path` unless `run_as`=SP.
- `resources` YAML keys = REST create-payload fields. DABs version code **and** config; Git folders code **only**. Bundle vars resolve at **deploy time** (wrap in job params to override at run).

## Liquid clustering vs partition/ZORDER
- **Use liquid clustering for all new tables.** ≤ **4** keys; only on **stat-collected** (first 32) columns; **can't mix** `CLUSTER BY` + `PARTITIONED BY`; can't ZORDER a clustered table.
- Change keys = no rewrite; `ALTER TABLE…CLUSTER BY(new)` applies only on next `OPTIMIZE` (incremental); `OPTIMIZE FULL` forces.
- `CLUSTER BY AUTO` = UC-managed only + PO (DBR 15.4 LTS+).
- **Don't partition < 1 TB; only partition if each partition ≥ 1 GB.** PO never runs ZORDER, never on external tables.

## AQE knobs (on by default; does NOT reorder joins — keep `broadcast()` hints)
| Knob | Default |
|---|---|
| `…optimizer.adaptive.enabled` | true |
| `…adaptive.autoBroadcastJoinThreshold` | 30 MB |
| `spark.sql.shuffle.partitions` | 200 (or `auto`) |
| `…adaptive.advisoryPartitionSizeInBytes` | 64 MB |
| `…skewJoin.skewedPartitionFactor` | 5 |
| `…skewJoin.skewedPartitionThresholdInBytes` | 256 MB |
**Skew = partition > 256 MB AND > 5× median.** Spark UI skew: Max ≥ 1.5× p75.

## APPLY CHANGES (AUTO CDC) API
```python
dlt.apply_changes(
  target="silver", source="bronze",
  keys=["id"],
  sequence_by=col("ts"),          # ordering / dedup
  apply_as_deletes=expr("op='DELETE'"),
  except_column_list=["op","ts"],
  stored_as_scd_type=2)           # 1 or 2
```

## Delta Sharing — D2D vs D2O
| | **D2D** (Databricks→Databricks) | **D2O** (Databricks→Open) |
|---|---|---|
| Recipient | UC workspace, by **metastore ID** | any platform, **token** or **OIDC** |
| Extra assets | **notebooks, volumes, models** | tabular + views only |
| Creds | auto-rotate | manual rotate; activation URL→cred file (1 download); tokens ≤ 1 yr |
`WITH HISTORY` default on DBR 16.2+ (perf parity) but **no benefit for partitioned tables**. Can't share tables with table-level row filters/column masks. `CREATE RECIPIENT x USING ID '…'` (D2D) vs `CREATE RECIPIENT x;` (token). Rotate: `databricks recipients rotate-token x 0`.

## Job repair + parameter override
- `databricks jobs repair-run <id> --rerun-all-failed-tasks --rerun-dependent-tasks --json '{"job_parameters":{...}}'` — re-runs **only failed+dependent** tasks; **≥2-task jobs only**; uses **current** settings; run must not be in progress.
- Repair-dialog params override **for that repair only**; reset = clear **both key and value**.
- `run-now {job_parameters}` = fresh run. **Job params beat task params** on key collision.

## Fast traps
String compare in If/else: `==` → `12.0==12` is **false** (use `>=`). `assertDataFrameEqual` ignores row order by default (floats via `rtol/atol`). High-memory task = REPL/driver only, not Spark session. `breakpoint()` broken → `import pdb; pdb.set_trace()`. Cached query = no Query Profile (bust cache). DELETE is logical: VACUUM default **7d** (`delta.deletedFileRetentionDuration`), history default **30d**; deletion vectors need `REORG…APPLY(PURGE)` then `VACUUM`. Streaming source breaks on UPDATE/DELETE → `skipChangeCommits` or CDF. `event_log()` owner-only, 1 pipeline/call. `is_account_group_member` (account) not `is_member` (workspace) for UC. SELECT alone can't read — need `USE CATALOG`+`USE SCHEMA`; metastore grants don't inherit. Federation = read-only (except internal Hive); non-pushable predicates silently re-applied locally.
