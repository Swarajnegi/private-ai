Bronze — streaming table, Auto Loader CSV + notifications + expectation

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

-- SQL: no per-query notification flag — enable "file events" on the external location.

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
Silver — streaming table from the bronze stream + multi-expectations

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
Gold — materialized view + expectation

@dp.materialized_view(name="daily_revenue_gold")
@dp.expect_or_fail("non_negative_revenue", "revenue >= 0")
def daily_revenue_gold():
    return (spark.read.table("orders_silver")                 # batch read for an MV
        .filter(col("status") == "completed")
        .groupBy(col("order_ts").cast("date").alias("order_date"))
        .agg(expr("sum(amount) AS revenue"), expr("count(*) AS n_orders")))

CREATE OR REFRESH MATERIALIZED VIEW daily_revenue_gold (
  CONSTRAINT non_negative_revenue EXPECT (revenue >= 0) ON VIOLATION FAIL UPDATE
)
AS SELECT CAST(order_ts AS DATE) AS order_date,
          sum(amount) AS revenue, count(*) AS n_orders
   FROM orders_silver                                         -- no STREAM = batch
   WHERE status = 'completed'
   GROUP BY CAST(order_ts AS DATE);
Temporary view (in-pipeline only)

@dp.temporary_view
def high_value_orders():
    return spark.read.table("orders_silver").filter(col("amount") >= 10000)

-- "temporary" datasets are now the PRIVATE clause in SQL
CREATE OR REFRESH PRIVATE MATERIALIZED VIEW high_value_orders
AS SELECT * FROM orders_silver WHERE amount >= 10000;
Auto CDC — SCD Type 1 and Type 2

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
Auto CDC from snapshot — Python only (no SQL)

@dp.temporary_view
def customer_snapshot():
    return spark.read.table("customers_snapshot_raw")

dp.create_streaming_table(name="customers_from_snapshot")
dp.create_auto_cdc_from_snapshot_flow(
    target="customers_from_snapshot",
    source="customer_snapshot",            # or a lambda returning (DataFrame, version)
    keys=["customer_id"], stored_as_scd_type=2)

-- ❌ AUTO CDC FROM SNAPSHOT is not supported in the SQL interface — Python only.
Append flow — many streaming sources → one streaming table

dp.create_streaming_table(
    name="orders_all_regions",
    expect_all_or_drop={"positive_amount": "amount > 0"})     # NOT allowed inside @append_flow

@dp.append_flow(target="orders_all_regions")
def from_us():  return spark.readStream.table("orders_us_bronze")

@dp.append_flow(target="orders_all_regions")
def from_eu():  return spark.readStream.table("orders_eu_bronze")

CREATE OR REFRESH STREAMING TABLE orders_all_regions (
  CONSTRAINT positive_amount EXPECT (amount > 0) ON VIOLATION DROP ROW
);
CREATE FLOW from_us AS INSERT INTO orders_all_regions BY NAME
SELECT * FROM STREAM(orders_us_bronze);

CREATE FLOW from_eu AS INSERT INTO orders_all_regions BY NAME
SELECT * FROM STREAM(orders_eu_bronze);
Update flow + sink — Python only (Public Preview, sinks not Delta)

dp.create_sink("order_counts_sink", "kafka",
    {"kafka.bootstrap.servers": "broker:9092", "topic": "order_counts"})

@dp.update_flow(target="order_counts_sink", name="order_counts_flow")
def order_counts():
    return spark.readStream.table("orders_silver").groupBy("status").count()

-- ❌ update_flow / create_sink have no SQL form — Python only (Public Preview).
Python decorator ↔ SQL keyword map
PySpark (SDP)	SQL (SDP)
@dp.table	CREATE OR REFRESH STREAMING TABLE
@dp.materialized_view	CREATE OR REFRESH MATERIALIZED VIEW
@dp.temporary_view	CREATE OR REFRESH PRIVATE … (temp → PRIVATE)
@dp.expect(d,c)	CONSTRAINT d EXPECT (c) (no ON VIOLATION)
@dp.expect_or_drop	… ON VIOLATION DROP ROW
@dp.expect_or_fail	… ON VIOLATION FAIL UPDATE
@dp.expect_all{…}	just list multiple CONSTRAINT … clauses
spark.readStream.format("cloudFiles")	STREAM read_files(…)
spark.readStream.table("x")	STREAM(x)
spark.read.table("x")	x (no STREAM)
dp.create_auto_cdc_flow	CREATE FLOW … AS AUTO CDC INTO …
dp.create_auto_cdc_from_snapshot_flow	❌ Python only
@dp.append_flow	CREATE FLOW … AS INSERT INTO … BY NAME SELECT …
@dp.update_flow + dp.create_sink	❌ Python only (Preview)
SQL can't do (say this if asked why you'd pick Python): AUTO CDC FROM SNAPSHOT, update_flow/sinks, PIVOT (needs eager load), and metaprogramming. Everything else has a clean SQL twin.

-----------------------------------------------------------------------------------------------------------------------------------------

A flow is the simplest unit in SDP: a query + a target. It's the thing that actually moves data into a table. Most of the time you never write one explicitly — defining a table creates one for you (the "default flow"). You only reach for explicit flows in specific cases. Here's the whole set:

The flow types — where / why / how

Flow	When you use it (why)	How (marker):

Default	The normal case: one source → one target, defined in a single step. SDP makes it for you, named the same as the table.	just @dp.table / @dp.materialized_view with a query
Append	Many sources → one target, or add a source later without a full refresh. Append-only.	dp.create_streaming_table + multiple @dp.append_flow(target=...)
Auto CDC	Source is a change feed (insert/update/delete + a sequence col); you want upserts / SCD 1 or 2 without hand-writing MERGE.	create_streaming_table + dp.create_auto_cdc_flow(...)
Auto CDC from snapshot	No change feed — only periodic full snapshots; let SDP diff them into changes.	dp.create_auto_cdc_from_snapshot_flow(...) (Python only)
Update	Stream stateful aggregates to a sink (Kafka), emitting only changed rows.	dp.create_sink + @dp.update_flow(...) (Preview, Python only)
Two rules worth knowing: any number of append flows can write to one target, but a table that's an Auto CDC target can only be targeted by other Auto CDC flows — you can't mix append + CDC into the same table.