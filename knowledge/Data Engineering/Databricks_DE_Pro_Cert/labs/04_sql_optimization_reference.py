# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · SQL Development & Query Optimization Reference
# MAGIC
# MAGIC Read-and-learn SQL reference for the HDFC ingestion role + the cert. Every pattern = a short note + a **runnable `%sql` cell** (the setup cell builds all sample data, so just **Run All**).
# MAGIC
# MAGIC **Part A — SQL development patterns** · **Part B — query optimization** (`EXPLAIN`, data skipping, broadcast, the framework, + the Trino angle).
# MAGIC
# MAGIC Set the widgets if you can't write to `main` (Part A runs on temp views = no privileges; Part B + MERGE need a schema you can CREATE in).

# COMMAND ----------

# Setup — build all sample objects (run once)
dbutils.widgets.text("catalog", "main", "Catalog you can CREATE in")
dbutils.widgets.text("schema", "de_pro_sql", "Scratch schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")   # so bare names + temp views resolve in %sql cells

# --- temp views (session-scoped, no privileges needed) ---
spark.createDataFrame(
    [
        (100, 10, 150.00, "2024-06-01 09:00:00", "POSTED"),
        (101, 10, 200.50, "2024-06-01 10:00:00", "POSTED"),
        (102, 10, 50.00, "2024-06-01 10:00:00", "POSTED"),   # SAME ts as 101 -> a tie (for the frame demo)
        (103, 11, 75.25, "2024-06-02 11:00:00", "REVERSED"),
        (104, 12, 500.00, "2024-06-02 12:00:00", "POSTED"),
    ],
    "txn_id int, account_id int, amount double, txn_ts string, status string",
).createOrReplaceTempView("txns")

spark.createDataFrame(
    [(1, "2024-06-01"), (1, "2024-06-02"), (1, "2024-06-03"), (1, "2024-06-06"), (1, "2024-06-07")],
    "user_id int, login_date string",
).createOrReplaceTempView("logins")

spark.createDataFrame([(10,), (11,), (12,)], "account_id int").createOrReplaceTempView("source_accts")
spark.createDataFrame([(10,), (11,)], "account_id int").createOrReplaceTempView("loaded_accts")

spark.createDataFrame(
    [(10, "Asha", "IN"), (11, "Ben", "US"), (12, "Cy", "IN")],
    "account_id int, name string, country string",
).createOrReplaceTempView("customers")

spark.createDataFrame(
    [(1, '{"acct":10,"lines":[{"sku":"A","amt":50},{"sku":"B","amt":100}]}')],
    "order_id int, body string",
).createOrReplaceTempView("orders_json")

# --- managed Delta tables (need CREATE) for Part B + MERGE ---
spark.sql("DROP TABLE IF EXISTS txns_delta")
spark.createDataFrame(
    [(100 + i, 10 + (i % 3), float(100 + i), "2024-06-01") for i in range(300)],
    "txn_id int, account_id int, amount double, dt string",
).write.mode("overwrite").saveAsTable("txns_delta")
spark.sql("ALTER TABLE txns_delta CLUSTER BY (account_id)")   # liquid clustering (DBR 13.3+)
spark.sql("OPTIMIZE txns_delta")                              # materialize the clustering

spark.sql("DROP TABLE IF EXISTS dim_account")
spark.sql("CREATE TABLE dim_account (account_id INT, status STRING)")
spark.sql("INSERT INTO dim_account VALUES (10,'ACTIVE'),(11,'ACTIVE')")

print(f"Sample data ready in {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part A — SQL development patterns

# COMMAND ----------

# MAGIC %md
# MAGIC ## A1 · Window + QUALIFY — latest-per-key / top-N without a subquery
# MAGIC `QUALIFY` filters on a window function's result directly (Databricks supports it) — no wrapping subquery.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- latest txn per account
# MAGIC SELECT *
# MAGIC FROM txns
# MAGIC QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY txn_ts DESC, txn_id DESC) = 1;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A2 · Running total (window frame) — and the ROWS-vs-default nuance
# MAGIC `partition + order + SUM()` already gives a running total via the **default `RANGE … UNBOUNDED PRECEDING TO CURRENT ROW`** frame. Spell out `ROWS BETWEEN …` only for physical-row tie semantics or a different frame. Account 10 has a tie at 10:00 — compare the two columns.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT account_id, txn_ts, amount,
# MAGIC        SUM(amount) OVER (PARTITION BY account_id ORDER BY txn_ts)                  AS running_default_RANGE,
# MAGIC        SUM(amount) OVER (PARTITION BY account_id ORDER BY txn_ts, txn_id
# MAGIC                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)         AS running_explicit_ROWS
# MAGIC FROM txns
# MAGIC ORDER BY account_id, txn_ts, txn_id;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A3 · Gaps-and-islands (consecutive-day streaks)
# MAGIC Trick: `date − row_number()` is **constant within a consecutive run**, so group by that anchor.

# COMMAND ----------

# MAGIC %sql
# MAGIC WITH r AS (
# MAGIC   SELECT user_id, CAST(login_date AS DATE) AS d,
# MAGIC          DATE_SUB(CAST(login_date AS DATE),
# MAGIC                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_date)) AS grp
# MAGIC   FROM logins
# MAGIC )
# MAGIC SELECT user_id, MIN(d) AS streak_start, MAX(d) AS streak_end, COUNT(*) AS days
# MAGIC FROM r GROUP BY user_id, grp ORDER BY streak_start;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A4 · Reconciliation — LEFT ANTI JOIN / NOT EXISTS / EXCEPT
# MAGIC Find missing keys and diff rows — the core of "validation and reconciliation."

# COMMAND ----------

# MAGIC %sql
# MAGIC -- (a) keys in source but missing from target
# MAGIC SELECT s.account_id FROM source_accts s LEFT ANTI JOIN loaded_accts l ON s.account_id = l.account_id;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- (b) same thing with NOT EXISTS, plus row & control-total comparison
# MAGIC SELECT
# MAGIC   (SELECT COUNT(*) FROM source_accts) AS source_rows,
# MAGIC   (SELECT COUNT(*) FROM loaded_accts) AS target_rows,
# MAGIC   (SELECT COUNT(*) FROM source_accts) - (SELECT COUNT(*) FROM loaded_accts) AS row_diff;
# MAGIC -- row-level diff: SELECT * FROM source_accts EXCEPT SELECT * FROM loaded_accts;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A5 · Aggregation depth — GROUPING SETS · agg FILTER · approx_count_distinct
# MAGIC `GROUPING SETS`/`ROLLUP`/`CUBE` = multiple grain rollups in one pass. `FILTER (WHERE …)` = conditional aggregate without a CASE.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT account_id, status,
# MAGIC        SUM(amount) AS total,
# MAGIC        COUNT(*) FILTER (WHERE status = 'POSTED') AS posted_cnt,
# MAGIC        APPROX_COUNT_DISTINCT(txn_id) AS approx_distinct_txns
# MAGIC FROM txns
# MAGIC GROUP BY GROUPING SETS ((account_id), (status), ())
# MAGIC ORDER BY account_id NULLS LAST, status NULLS LAST;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A6 · Semi-structured in SQL — `:` path · from_json · explode · VARIANT
# MAGIC The `:` operator navigates JSON in a **string** column (no schema). `from_json` + `explode` flattens arrays. `parse_json` makes a **VARIANT** (DBR 15.3+).

# COMMAND ----------

# MAGIC %sql
# MAGIC -- (a) colon path on a STRING column (no schema), with ::cast
# MAGIC SELECT order_id, body:acct::int AS acct, body:lines[0].sku::string AS first_sku
# MAGIC FROM orders_json;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- (b) parse + explode an array into rows
# MAGIC SELECT order_id, j.acct, l.sku, l.amt
# MAGIC FROM (
# MAGIC   SELECT order_id, from_json(body, 'STRUCT<acct INT, lines ARRAY<STRUCT<sku STRING, amt INT>>>') AS j
# MAGIC   FROM orders_json
# MAGIC ) LATERAL VIEW EXPLODE(j.lines) AS l;

# COMMAND ----------

# MAGIC %md
# MAGIC ## A7 · Set operations
# MAGIC `UNION` (dedups) vs `UNION ALL` (keeps dupes — cheaper, no shuffle) · `INTERSECT` · `EXCEPT`.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT account_id FROM source_accts
# MAGIC EXCEPT
# MAGIC SELECT account_id FROM loaded_accts;   -- in source, not in target

# COMMAND ----------

# MAGIC %md
# MAGIC ## A8 · MERGE — SQL upsert (SCD1)
# MAGIC The upsert primitive (managed Delta table `dim_account`).

# COMMAND ----------

# MAGIC %sql
# MAGIC MERGE INTO dim_account t
# MAGIC USING (SELECT * FROM VALUES (11,'DORMANT'),(12,'ACTIVE') AS s(account_id, status)) s
# MAGIC   ON t.account_id = s.account_id
# MAGIC WHEN MATCHED THEN UPDATE SET t.status = s.status
# MAGIC WHEN NOT MATCHED THEN INSERT (account_id, status) VALUES (s.account_id, s.status);
# MAGIC SELECT * FROM dim_account ORDER BY account_id;

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part B — Query optimization
# MAGIC
# MAGIC The framework, in priority order: **① read less → ② shuffle less → ③ de-skew.**

# COMMAND ----------

# MAGIC %md
# MAGIC ## B1 · Read the plan with EXPLAIN
# MAGIC `EXPLAIN FORMATTED` shows the physical plan. Look for: **PushedFilters** (predicate pushdown), **PartitionFilters** (pruning), the **join type**, and **Exchange** (= a shuffle).

# COMMAND ----------

# MAGIC %sql
# MAGIC EXPLAIN FORMATTED
# MAGIC SELECT account_id, SUM(amount) FROM txns_delta WHERE account_id = 10 GROUP BY account_id;

# COMMAND ----------

# MAGIC %md
# MAGIC ## B2 · ① Read less — data skipping, pruning, liquid clustering
# MAGIC `txns_delta` is `CLUSTER BY (account_id)` (liquid clustering). A filter on the clustered column lets Delta **skip files** via min/max stats. In the plan above, the `account_id = 10` predicate appears as a **PushedFilter** — the scan reads only matching files, not the whole table. (Clustering replaces legacy `PARTITIONED BY` + `ZORDER`; cluster on your common filter/join keys.)

# COMMAND ----------

# MAGIC %md
# MAGIC ## B3 · ② Shuffle less — broadcast the small side
# MAGIC A small dimension joined to a big fact → **broadcast** it (replicate to every executor, no shuffle). AQE auto-broadcasts under a threshold; the hint forces it. Look for **BroadcastHashJoin** (good) vs **SortMergeJoin** (shuffles both sides).

# COMMAND ----------

# MAGIC %sql
# MAGIC EXPLAIN FORMATTED
# MAGIC SELECT /*+ BROADCAST(c) */ t.account_id, c.name, SUM(t.amount)
# MAGIC FROM txns_delta t JOIN customers c ON t.account_id = c.account_id
# MAGIC GROUP BY t.account_id, c.name;

# COMMAND ----------

# MAGIC %md
# MAGIC ## B4 · The optimization framework (what to say in the interview)
# MAGIC
# MAGIC > *"I read the plan first — **Query Profile** (DBSQL) or **Spark UI** or `EXPLAIN`. Then three checks, in order:"*
# MAGIC
# MAGIC | Lever | Symptom in the plan/profile | Fix |
# MAGIC |---|---|---|
# MAGIC | **① Read less** | full table scan, no `PushedFilters`/`PartitionFilters` | filter early · `SELECT` only needed cols · `CLUSTER BY` the filter/join key · partition pruning |
# MAGIC | **② Shuffle less** | big `Exchange`, `SortMergeJoin` on a small dim | `/*+ BROADCAST(dim) */` · filter/aggregate **before** the join · drop needless `DISTINCT`/`ORDER BY` |
# MAGIC | **③ De-skew** | one task ≫ others (Max ≫ p75), spill | AQE skew-join (usually automatic) · salt the hot key |
# MAGIC
# MAGIC Fix the **dominant** cost, then re-measure.

# COMMAND ----------

# MAGIC %md
# MAGIC ## B5 · The Trino / Presto angle (you can't run it here — but know it)
# MAGIC Same instinct (read less, shuffle less), different knobs:
# MAGIC - **Predicate + partition pushdown** to the connector (filters run at the Delta/source scan).
# MAGIC - **Dynamic filtering** — Trino's signature join optimization: builds a filter from the build side and pushes it into the probe-side scan to prune splits.
# MAGIC - **Join distribution**: `BROADCAST` (small build side, replicated) vs `PARTITIONED` (both sides hash-shuffled); the **cost-based optimizer** chooses using **table stats** → run `ANALYZE <table>` to populate them.
# MAGIC - Read plans with **`EXPLAIN`** / **`EXPLAIN ANALYZE`** (actual rows + timings).

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cleanup (optional)

# COMMAND ----------

# spark.sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{SCHEMA} CASCADE")
print("Done. SQL reference notebook complete.")
