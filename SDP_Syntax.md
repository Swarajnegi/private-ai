# Lakeflow Spark Declarative Pipelines (SDP) — Syntax Cheat-Sheet

PySpark decorators and their SQL equivalents, side by side, across the medallion layers and every flow type.

---

## Bronze — streaming table, Auto Loader CSV + notifications + expectation

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import col, expr, current_timestamp, struct

@dp.table(name="orders_bronze", table_properties={"quality": "bronze"})
@dp.expect("has_order_id", "order_id IS NOT NULL")            # warn + keep
def orders_bronze():
    return (spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.useNotifications", "true")        # ← per-stream notifications (Python only)
        .option("cloudFiles.schemaLocation", "/Volumes/main/sales/_schemas/orders_bronze")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("header", "true")
        .load("/Volumes/main/sales/landing/orders/")
        .withColumn("_ingested_at", current_timestamp()))
```

SQL: no per-query notification flag — enable "file events" on the external location.

```sql
CREATE OR REFRESH STREAMING TABLE orders_bronze (
  CONSTRAINT has_order_id EXPECT (order_id IS NOT NULL)        -- no ON VIOLATION = warn + keep
)
TBLPROPERTIES ("quality" = "bronze")
AS SELECT *, current_timestamp() AS _ingested_at
   FROM STREAM read_files(
     "/Volumes/main/sales/landing/orders/",
     format => "csv",
     header => "true",
     schemaEvolutionMode => "addNewColumns"
   );
```

---

## Silver — streaming table from the bronze stream + multi-expectations

```python
@dp.table(name="orders_silver")
@dp.expect_or_drop("positive_amount", "amount > 0")           # drop
@dp.expect_all_or_fail({                                      # fail update
    "has_customer": "customer_id IS NOT NULL",
    "valid_status": "status IN ('completed','cancelled','pending')",
})
def orders_silver():
    return (spark.readStream.table("orders_bronze")
        .select(col("order_id").cast("int"), col("customer_id").cast("int"),
                col("amount").cast("double"), col("status"),
                col("order_ts").cast("timestamp")))
```

```sql
CREATE OR REFRESH STREAMING TABLE orders_silver (
  CONSTRAINT positive_amount EXPECT (amount > 0)              ON VIOLATION DROP ROW,
  CONSTRAINT has_customer    EXPECT (customer_id IS NOT NULL) ON VIOLATION FAIL UPDATE,
  CONSTRAINT valid_status    EXPECT (status IN ('completed','cancelled','pending')) ON VIOLATION FAIL UPDATE
)
AS SELECT CAST(order_id AS INT) AS order_id,
          CAST(customer_id AS INT) AS customer_id,
          CAST(amount AS DOUBLE) AS amount,
          status,
          CAST(order_ts AS TIMESTAMP) AS order_ts
   FROM STREAM(orders_bronze);                                -- STREAM() = streaming read
```

---

## Gold — materialized view + expectation

```python
@dp.materialized_view(name="daily_revenue_gold")
@dp.expect_or_fail("non_negative_revenue", "revenue >= 0")
def daily_revenue_gold():
    return (spark.read.table("orders_silver")                 # batch read for an MV
        .filter(col("status") == "completed")
        .groupBy(col("order_ts").cast("date").alias("order_date"))
        .agg(expr("sum(amount) AS revenue"), expr("count(*) AS n_orders")))
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW daily_revenue_gold (
  CONSTRAINT non_negative_revenue EXPECT (revenue >= 0) ON VIOLATION FAIL UPDATE
)
AS SELECT CAST(order_ts AS DATE) AS order_date,
          sum(amount) AS revenue, count(*) AS n_orders
   FROM orders_silver                                         -- no STREAM = batch
   WHERE status = 'completed'
   GROUP BY CAST(order_ts AS DATE);
```

---

## Temporary view (in-pipeline only)

```python
@dp.temporary_view
def high_value_orders():
    return spark.read.table("orders_silver").filter(col("amount") >= 10000)
```

```sql
-- "temporary" datasets are now the PRIVATE clause in SQL
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW high_value_orders
AS SELECT * FROM orders_silver WHERE amount >= 10000;
```

---

## Auto CDC — SCD Type 1 and Type 2

```python
@dp.temporary_view
def customers_cdc():
    return spark.readStream.table("customers_cdc_raw")        # cols: customer_id,name,city,op,seq_num

# SCD 1
dp.create_streaming_table(
    name="customers_scd1",
    expect_all_or_drop={"has_key": "customer_id IS NOT NULL"} # CDC-target expectations go on the table
)
dp.create_auto_cdc_flow(
    target="customers_scd1", source="customers_cdc", keys=["customer_id"],
    sequence_by=col("seq_num"),                               # struct("seq_num","id") for tie-breaks
    apply_as_deletes=expr("op = 'DELETE'"),
    apply_as_truncates=expr("op = 'TRUNCATE'"),
    except_column_list=["op", "seq_num"], stored_as_scd_type=1)

# SCD 2 — full history; don't version `city`
dp.create_streaming_table(name="customers_scd2")
dp.create_auto_cdc_flow(
    target="customers_scd2", source="customers_cdc", keys=["customer_id"],
    sequence_by=col("seq_num"), apply_as_deletes=expr("op = 'DELETE'"),
    except_column_list=["op", "seq_num"], stored_as_scd_type="2",
    track_history_except_column_list=["city"])
```

```sql
-- SCD 1
CREATE OR REFRESH STREAMING TABLE customers_scd1 (
  CONSTRAINT has_key EXPECT (customer_id IS NOT NULL) ON VIOLATION DROP ROW
);
CREATE FLOW cdc_scd1 AS AUTO CDC INTO customers_scd1
FROM stream(customers_cdc)
KEYS (customer_id)
APPLY AS DELETE   WHEN op = 'DELETE'
APPLY AS TRUNCATE WHEN op = 'TRUNCATE'
SEQUENCE BY seq_num
COLUMNS * EXCEPT (op, seq_num)
STORED AS SCD TYPE 1;

-- SCD 2 — full history; don't version `city`
CREATE OR REFRESH STREAMING TABLE customers_scd2;
CREATE FLOW cdc_scd2 AS AUTO CDC INTO customers_scd2
FROM stream(customers_cdc)
KEYS (customer_id)
APPLY AS DELETE WHEN op = 'DELETE'
SEQUENCE BY seq_num
COLUMNS * EXCEPT (op, seq_num)
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (city);
```

---

## Auto CDC from snapshot — Python only (no SQL)

```python
@dp.temporary_view
def customer_snapshot():
    return spark.read.table("customers_snapshot_raw")

dp.create_streaming_table(name="customers_from_snapshot")
dp.create_auto_cdc_from_snapshot_flow(
    target="customers_from_snapshot",
    source="customer_snapshot",            # or a lambda returning (DataFrame, version)
    keys=["customer_id"], stored_as_scd_type=2)
```

```sql
-- ❌ AUTO CDC FROM SNAPSHOT is not supported in the SQL interface — Python only.
```

---

## Append flow — many streaming sources → one streaming table

```python
dp.create_streaming_table(
    name="orders_all_regions",
    expect_all_or_drop={"positive_amount": "amount > 0"})     # NOT allowed inside @append_flow

@dp.append_flow(target="orders_all_regions")
def from_us():  return spark.readStream.table("orders_us_bronze")

@dp.append_flow(target="orders_all_regions")
def from_eu():  return spark.readStream.table("orders_eu_bronze")
```

```sql
CREATE OR REFRESH STREAMING TABLE orders_all_regions (
  CONSTRAINT positive_amount EXPECT (amount > 0) ON VIOLATION DROP ROW
);
CREATE FLOW from_us AS INSERT INTO orders_all_regions BY NAME
SELECT * FROM STREAM(orders_us_bronze);

CREATE FLOW from_eu AS INSERT INTO orders_all_regions BY NAME
SELECT * FROM STREAM(orders_eu_bronze);
```

---

## Update flow + sink — Python only (Public Preview, sinks not Delta)

```python
dp.create_sink("order_counts_sink", "kafka",
    {"kafka.bootstrap.servers": "broker:9092", "topic": "order_counts"})

@dp.update_flow(target="order_counts_sink", name="order_counts_flow")
def order_counts():
    return spark.readStream.table("orders_silver").groupBy("status").count()
```

```sql
-- ❌ update_flow / create_sink have no SQL form — Python only (Public Preview).
```

---

## Python decorator ↔ SQL keyword map

| PySpark (SDP) | SQL (SDP) |
|---|---|
| `@dp.table` | `CREATE OR REFRESH STREAMING TABLE` |
| `@dp.materialized_view` | `CREATE OR REFRESH MATERIALIZED VIEW` |
| `@dp.temporary_view` | `CREATE OR REFRESH PRIVATE …` (temp → PRIVATE) |
| `@dp.expect(d,c)` | `CONSTRAINT d EXPECT (c)` (no ON VIOLATION) |
| `@dp.expect_or_drop` | `… ON VIOLATION DROP ROW` |
| `@dp.expect_or_fail` | `… ON VIOLATION FAIL UPDATE` |
| `@dp.expect_all{…}` | just list multiple `CONSTRAINT …` clauses |
| `spark.readStream.format("cloudFiles")` | `STREAM read_files(…)` |
| `spark.readStream.table("x")` | `STREAM(x)` |
| `spark.read.table("x")` | `x` (no STREAM) |
| `dp.create_auto_cdc_flow` | `CREATE FLOW … AS AUTO CDC INTO …` |
| `dp.create_auto_cdc_from_snapshot_flow` | ❌ Python only |
| `@dp.append_flow` | `CREATE FLOW … AS INSERT INTO … BY NAME SELECT …` |
| `@dp.update_flow` + `dp.create_sink` | ❌ Python only (Preview) |

**SQL can't do** (say this if asked why you'd pick Python): AUTO CDC FROM SNAPSHOT, update_flow/sinks, PIVOT (needs eager load), and metaprogramming. Everything else has a clean SQL twin.

---

## Flows — the simplest unit in SDP

A flow is the simplest unit in SDP: a query + a target. It's the thing that actually moves data into a table. Most of the time you never write one explicitly — defining a table creates one for you (the "default flow"). You only reach for explicit flows in specific cases. Here's the whole set:

### The flow types — where / why / how

| Flow | When you use it (why) | How (marker) |
|---|---|---|
| **Default** | The normal case: one source → one target, defined in a single step. SDP makes it for you, named the same as the table. | just `@dp.table` / `@dp.materialized_view` with a query |
| **Append** | Many sources → one target, or add a source later without a full refresh. Append-only. | `dp.create_streaming_table` + multiple `@dp.append_flow(target=...)` |
| **Auto CDC** | Source is a change feed (insert/update/delete + a sequence col); you want upserts / SCD 1 or 2 without hand-writing MERGE. | `create_streaming_table` + `dp.create_auto_cdc_flow(...)` |
| **Auto CDC from snapshot** | No change feed — only periodic full snapshots; let SDP diff them into changes. | `dp.create_auto_cdc_from_snapshot_flow(...)` (Python only) |
| **Update** | Stream stateful aggregates to a sink (Kafka), emitting only changed rows. | `dp.create_sink` + `@dp.update_flow(...)` (Preview, Python only) |

**Two rules worth knowing:** any number of append flows can write to one target, but a table that's an Auto CDC target can only be targeted by other Auto CDC flows — you can't mix append + CDC into the same table.

---

## Table properties, refresh policy, watermarks & Auto Loader options

### A. Most important table properties (ST + MV)

Table properties tune full-refresh protection, auto-optimize, CDC tombstone GC, incremental-refresh eligibility on MV sources, and free-form tags. Set them as a Python `dict` on the decorator (`table_properties={...}`) or as a SQL `TBLPROPERTIES (...)` clause. Pipeline-managed tables don't accept `ALTER TABLE ... SET TBLPROPERTIES` — change the definition and re-run the update. Note: the runtime channel (`current`/`preview`) is a **pipeline-level setting**, not a table property — see the box below.

| Property | Default | Purpose |
|---|---|---|
| `pipelines.reset.allowed` | `true` | Set `'false'` to block full refresh on this table (protects backfilled / manually-deleted / `REPLACE WHERE` data); incremental writes and downstream recomputes still flow. |
| `pipelines.autoOptimize.managed` | `true` | Enable/disable SDP auto-scheduled optimization of this table. Not used when the pipeline is governed by predictive optimization (which runs full `OPTIMIZE`/`VACUUM` on its own cadence). |
| `pipelines.autoOptimize.zOrderCols` | None | Comma-separated columns to Z-order by, e.g. `'year,month'`. Databricks recommends liquid clustering (`CLUSTER BY` / `CLUSTER BY AUTO`) over Z-ordering for pipeline tables. |
| `pipelines.cdc.tombstoneGCThresholdInSeconds` | `172800` (2 days) | Delete-tombstone retention on an `AUTO CDC` target ST (SCD type 2 / out-of-order handling). Raise above your max event-arrival-to-run lag when the CDC source is Auto Loader (no file-order guarantee). |
| `delta.autoOptimize.optimizeWrite` | (unset) | Delta optimized writes — compact files at write time. On SDP this is generally managed; set explicitly only to override. |
| `delta.autoOptimize.autoCompact` | (unset) | Delta auto-compaction after writes. On SDP this is generally managed; set explicitly only to override. |
| `delta.enableChangeDataFeed` | `false` | Emit row-level change feed; recommended on MV **source** tables to make MV refresh incrementalizable. |
| `delta.enableRowTracking` | (unset) | Row tracking; required by many MV incremental-refresh operations on source tables. |
| `delta.enableDeletionVectors` | (unset) | Deletion vectors; recommended on MV source tables for incremental refresh. |
| `quality` | (user tag) | Free-form medallion tag, e.g. `'bronze'` / `'silver'` / `'gold'`. |

```python
from pyspark import pipelines as dp

@dp.table(
    table_properties={
        "pipelines.reset.allowed": "false",
        "pipelines.autoOptimize.managed": "true",
        "pipelines.cdc.tombstoneGCThresholdInSeconds": "604800",
        "quality": "bronze",
    },
    cluster_by=["event_date", "region"],   # liquid clustering; mutually exclusive with partition_cols
)
def raw_user_table():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "csv") \
        .load("/databricks-datasets/iot-stream/data-user")

@dp.materialized_view(
    table_properties={
        "delta.enableChangeDataFeed": "true",
        "delta.enableRowTracking": "true",
        "delta.enableDeletionVectors": "true",
        "quality": "silver",
    },
    cluster_by_auto=True,                   # CLUSTER BY AUTO — Databricks picks/maintains keys
)
def user_summary():
    return spark.read.table("raw_user_table").groupBy("region").count()
```

```sql
CREATE OR REFRESH STREAMING TABLE raw_user_table
CLUSTER BY (event_date, region)            -- liquid clustering; cannot combine with PARTITIONED BY
TBLPROPERTIES (
  pipelines.reset.allowed = false,
  pipelines.autoOptimize.managed = true,
  pipelines.cdc.tombstoneGCThresholdInSeconds = 604800,
  quality = 'bronze'
)
AS SELECT * FROM STREAM read_files('/databricks-datasets/iot-stream/data-user', format => 'csv');

CREATE OR REFRESH MATERIALIZED VIEW user_summary
CLUSTER BY AUTO                            -- Databricks chooses & maintains clustering keys
TBLPROPERTIES (
  delta.enableChangeDataFeed   = true,
  delta.enableRowTracking      = true,
  delta.enableDeletionVectors  = true,
  quality = 'silver'
)
AS SELECT region, count(*) AS cnt FROM raw_user_table GROUP BY region;
```

> **Runtime channel is a pipeline setting, not a table property.** Set `channel` in the pipeline JSON / settings: `current` (default, stable, production) or `preview` (test upcoming runtime changes). Values are lowercase, and it does **not** go in `TBLPROPERTIES` / `table_properties`.

---

### B. Refresh policy on a materialized view

`REFRESH POLICY` controls how a materialized-view refresh handles incrementalization. Omitting it defaults to `AUTO`. Incremental refresh runs only on **serverless** pipelines; on classic compute every refresh is a full recompute regardless of policy. The Python kwarg is `refresh_policy` (Beta, default `'auto'`) with lowercase values.

| Policy (SQL / Python) | Behavior |
|---|---|
| `AUTO` / `'auto'` (default) | Cost model picks incremental vs full per refresh; falls back to full when incremental isn't available or on create/re-init (e.g. schema change). |
| `INCREMENTAL` / `'incremental'` | Prefer incremental. **`CREATE` fails** if the query can't be incrementalized at all; once created, a refresh that can't go incremental (e.g. row-tracking turned off on a source) falls back to full. |
| `INCREMENTAL STRICT` / `'incremental_strict'` | Strictly require incremental. `CREATE` fails if not incrementalizable, and a refresh that can't go incremental **fails** instead of silently doing a full recompute (use for cost/SLA guarantees). Create/re-init still does a full refresh when incrementalization is otherwise possible. |
| `FULL` / `'full'` | Always full recompute, even when the query is incrementalizable. |

```python
from pyspark import pipelines as dp

@dp.materialized_view(refresh_policy="incremental_strict")   # Beta; needs serverless
def daily_sales():
    return spark.read.table("sales").groupBy("k").sum("v")
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW daily_sales
REFRESH POLICY INCREMENTAL STRICT          -- needs serverless; refresh fails rather than full-recompute
AS SELECT k, sum(v) AS total FROM sales GROUP BY k;
```

---

### C. Watermark syntax (streaming)

A watermark declares a timestamp column plus a late-data tolerance; records arriving after the threshold may be dropped. Watermarks are **required** to make stateful aggregations refresh incrementally (instead of full recompute each update) and to bound state in joins. Python uses `.withWatermark('event_ts', '3 minutes')` on the streaming DataFrame; SQL uses `WATERMARK event_ts DELAY OF INTERVAL 3 MINUTES` (the interval must be a positive value less than a month).

Windowed aggregation:

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window

@dp.table
def event_counts():
    return (
        spark.readStream.table("events_raw")
            .withWatermark("event_ts", "3 minutes")
            .groupBy(window("event_ts", "1 minute"), "region")
            .count()
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_ts, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_ts DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

Stream-stream join (watermark on **both** sides + a time-bound condition, or state grows unbounded):

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

@dp.table
def matched_clicks():
    impressions = spark.readStream.table("impressions").withWatermark("imp_ts", "3 minutes")
    clicks      = spark.readStream.table("clicks").withWatermark("click_ts", "3 minutes")
    return impressions.join(
        clicks,
        expr("ad_id = click_ad_id AND click_ts BETWEEN imp_ts AND imp_ts + INTERVAL 3 MINUTES"),
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE matched_clicks AS
SELECT i.ad_id, i.imp_ts, c.click_ts
FROM STREAM(impressions) WATERMARK imp_ts DELAY OF INTERVAL 3 MINUTES AS i
JOIN STREAM(clicks)      WATERMARK click_ts DELAY OF INTERVAL 3 MINUTES AS c
  ON i.ad_id = c.ad_id
 AND c.click_ts BETWEEN i.imp_ts AND i.imp_ts + INTERVAL 3 MINUTES;
```

> Across multiple watermarked streams the engine tracks one global watermark at the pace of the slowest stream (`min` policy by default; `spark.sql.streaming.multipleWatermarkPolicy = max` switches to the fastest at the cost of dropping slow-stream data). Changing a watermark threshold or aggregation keys invalidates existing streaming state — a full refresh is then required to rebuild it.

---

### D. Most important Auto Loader (cloudFiles) options

Auto Loader is the `cloudFiles` Structured Streaming source for incremental ingestion from cloud object storage. In SDP, set options on the reader (Python) or as named args to `read_files(...)` (SQL). **Inside a streaming-table query, SDP manages both the checkpoint and `cloudFiles.schemaLocation` — omit them; setting them manually means a full refresh won't reset those directories.**

| Option | Default | Purpose |
|---|---|---|
| `cloudFiles.format` | (required) | Source file format: `json`, `csv`, `xml`, `parquet`, `avro`, `orc`, `text`, `binaryFile`. |
| `cloudFiles.schemaLocation` | None (required outside SDP to infer schema) | Where inferred schema + evolution are stored. **Managed by SDP** — omit inside a streaming-table query. |
| `cloudFiles.schemaEvolutionMode` | `addNewColumns` (no schema given) / `none` (schema given) | New-column handling: `addNewColumns`, `addNewColumnsWithTypeWidening`, `rescue`, `failOnNewColumns`, `none`. |
| `cloudFiles.inferColumnTypes` | `false` | Infer real types (JSON/CSV/XML columns are inferred as strings by default). |
| `cloudFiles.schemaHints` | None | Override inferred types for named columns, e.g. `"id long, ts timestamp"`. |
| `rescuedDataColumn` | column named `_rescued_data` | Set this option to capture unparsed/mismatched/missing/case-mismatched fields (as a JSON blob + source path) instead of dropping them; value is the column name. |
| `cloudFiles.useNotifications` | `false` | `true` = classic file-notification mode; `false` = directory listing. Same option in Python and SQL. Databricks now recommends `cloudFiles.useManagedFileEvents` (file events) over classic notifications. |
| `cloudFiles.useManagedFileEvents` | `false` | `true` = use the managed file-events service for discovery (load path must be an external location with file events enabled). DBR 14.3 LTS+. |
| `cloudFiles.maxFilesPerTrigger` | `1000` | Max new files per microbatch (hard limit). DBR 18.0+ configures this dynamically. |
| `cloudFiles.maxBytesPerTrigger` | None | Max new bytes per microbatch (soft limit, e.g. `10g`). With both set, the lower limit wins. DBR 18.0+ configures this dynamically. |
| `cloudFiles.includeExistingFiles` | `true` | Process files already present at stream start; evaluated only on first start. |
| `cloudFiles.allowOverwrites` | `false` | Reprocess files when they're overwritten/changed in place (uses last-modified time; may cause duplicates). |
| `cloudFiles.backfillInterval` | None | Async backfill cadence (e.g. `1 day`) to catch files missed by notifications; no duplicates. Do not use with `cloudFiles.useManagedFileEvents = true`. |
| `cloudFiles.partitionColumns` | None | Hive-style partition columns to infer from the path (e.g. `year,month,day`). |

```python
from pyspark import pipelines as dp

@dp.table(table_properties={"quality": "bronze"})
def raw_events():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .option("cloudFiles.inferColumnTypes", "true")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .option("cloudFiles.schemaHints", "event_ts timestamp, user_id long")
            .option("rescuedDataColumn", "_rescued_data")
            .option("cloudFiles.maxFilesPerTrigger", "500")
            .option("cloudFiles.backfillInterval", "1 day")
            # no cloudFiles.schemaLocation / checkpointLocation — SDP manages both
            .load("/Volumes/main/raw/events")
    )
```

```sql
CREATE OR REFRESH STREAMING TABLE raw_events
TBLPROPERTIES (quality = 'bronze')
AS SELECT *
FROM STREAM read_files(
  '/Volumes/main/raw/events',
  format                => 'json',
  inferColumnTypes      => true,
  schemaEvolutionMode   => 'addNewColumns',
  schemaHints           => 'event_ts timestamp, user_id long',
  rescuedDataColumn     => '_rescued_data',
  maxFilesPerTrigger    => 500
  -- schemaLocation/checkpointLocation managed by SDP
);
```
