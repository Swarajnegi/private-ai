# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Python + PySpark Reference & Drill Notebook
# MAGIC
# MAGIC A read-it-and-learn reference for the HDFC ingestion role. Every concept = a short note + a **runnable** example (the notebook builds its own sample data, so just **Run All**).
# MAGIC
# MAGIC **Part A** — PySpark must-haves · **Part B** — Pure Python must-haves · **Part C** — Automation · **Part D** — the 8 banking drills (worked).
# MAGIC
# MAGIC This version imports functions **directly** (`col(...)`, `when(...)`) instead of the `F.` alias. Set the two widgets if you can't write to `main` (the MERGE + Delta cells need a schema you can CREATE in).

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Catalog you can CREATE in")
dbutils.widgets.text("schema", "de_pro_ref", "Scratch schema")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# Direct imports (no `F.` prefix). NOTE: importing sum/max/min/count by name
# SHADOWS the Python builtins of the same name — harmless here (we never use the
# builtins), but in mixed code prefer `import pyspark.sql.functions as F` to avoid it.
from pyspark.sql.functions import (
    col, lit, when, broadcast, count, sum, avg, max, min,
    row_number, rank, lag, to_date, date_sub,
    regexp_extract, regexp_replace, from_json, explode, get_json_object,
    udf, pandas_udf,
)
from pyspark.sql.window import Window
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, LongType, DoubleType,
    DecimalType, TimestampType, DateType, ArrayType,
)

print(f"Writing scratch objects to {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part A — PySpark must-haves

# COMMAND ----------

# MAGIC %md
# MAGIC ## A1 · select / filter / withColumn / when().otherwise() / cast
# MAGIC The four verbs you use in every transform. `when/otherwise` = SQL CASE. `cast` changes type (silently nulls on bad parse — see A6).

# COMMAND ----------

customers = spark.createDataFrame(
    [
        (1, "Asha", "asha@bank.com", "IN", "750"),
        (2, "Ben", "ben@bank.com", "US", "640"),
        (3, "Cy", None, "IN", "580"),
    ],
    "customer_id int, name string, email string, country string, credit_score string",
)

out = (
    customers
    .select("customer_id", "name", "country", "credit_score")          # pick columns
    .filter(col("country") == "IN")                                     # row filter (== / & / |)
    .withColumn("credit_score", col("credit_score").cast("int"))        # string -> int
    .withColumn(
        "tier",
        when(col("credit_score") >= 700, "PRIME")
        .when(col("credit_score") >= 600, "NEAR_PRIME")
        .otherwise("SUBPRIME"),                                         # CASE WHEN
    )
)
display(out)

# COMMAND ----------

# MAGIC %md
# MAGIC ## A2 · Joins (all types) + broadcast
# MAGIC `how=` inner | left | right | outer | left_semi (keep left rows that match) | left_anti (keep left rows with NO match — great for reconciliation). `broadcast()` ships the small side to every executor (no shuffle).

# COMMAND ----------

accounts = spark.createDataFrame(
    [(10, 1), (11, 1), (12, 2), (13, 99)],
    "account_id int, customer_id int",
)

# inner / left
display(accounts.join(customers, "customer_id", "inner"))

# left_anti = accounts whose customer is missing from `customers` (orphans -> recon flag)
display(accounts.join(customers, "customer_id", "left_anti"))

# broadcast the small dim table
display(accounts.join(broadcast(customers), "customer_id", "left"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A3 · groupBy().agg()
# MAGIC Aggregations. Alias every agg. Multiple aggs in one `.agg(...)`.

# COMMAND ----------

txns = spark.createDataFrame(
    [
        (100, 10, "150.00", "2024-06-01 09:00:00", "POSTED"),
        (101, 10, "200.50", "2024-06-01 10:00:00", "POSTED"),
        (102, 11, "75.25", "2024-06-02 11:00:00", "REVERSED"),
        (103, 12, "500.00", "2024-06-02 12:00:00", "POSTED"),
    ],
    "txn_id int, account_id int, amount string, txn_ts string, status string",
)
txns = txns.withColumn("amount", col("amount").cast("decimal(12,2)"))

display(
    txns.groupBy("account_id").agg(
        count("*").alias("n_txns"),
        sum("amount").alias("total_amount"),
        avg("amount").alias("avg_amount"),
        max("amount").alias("max_amount"),
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## A4 · Window functions (row_number / rank / lag / lead / running sum)
# MAGIC `Window.partitionBy(key).orderBy(ts)`. `row_number` = dedup/keep-latest; `lag/lead` = previous/next row; running sum = `rowsBetween(unboundedPreceding, currentRow)`.

# COMMAND ----------

w_latest = Window.partitionBy("account_id").orderBy(col("txn_ts").desc())
w_running = Window.partitionBy("account_id").orderBy("txn_ts").rowsBetween(
    Window.unboundedPreceding, Window.currentRow
)

display(
    txns
    .withColumn("rn", row_number().over(w_latest))                  # 1 = latest per account
    .withColumn("rnk", rank().over(w_latest))
    .withColumn("prev_amount", lag("amount").over(Window.partitionBy("account_id").orderBy("txn_ts")))
    .withColumn("running_total", sum("amount").over(w_running))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## A5 · dropDuplicates / distinct · na.fill / na.drop
# MAGIC `dropDuplicates([keys])` = dedup on a subset; `distinct()` = whole row. `na.fill`/`na.drop` for nulls.

# COMMAND ----------

dupes = customers.unionByName(customers)                             # duplicate every row
print("after dropDuplicates on customer_id:", dupes.dropDuplicates(["customer_id"]).count())
display(customers.na.fill({"email": "UNKNOWN"}))                     # fill nulls
display(customers.na.drop(subset=["email"]))                        # drop rows with null email

# COMMAND ----------

# MAGIC %md
# MAGIC ## A6 · regexp_extract / regexp_replace · date parsing (explicit format!)
# MAGIC **Invisible trap:** `to_date`/`to_timestamp` return **NULL** on a format mismatch — always pass the explicit format and check for nulls.

# COMMAND ----------

raw_dates = spark.createDataFrame(
    [("2024-06-01",), ("01/06/2024",), ("garbage",)], "d string"
)
display(
    raw_dates
    .withColumn("iso", to_date("d", "yyyy-MM-dd"))                   # only first row parses; rest -> NULL
    .withColumn("masked_email", lit("asha@bank.com"))
    .withColumn("domain", regexp_extract("masked_email", r"@(.+)$", 1))
    .withColumn("masked", regexp_replace("masked_email", r"(^.).*(@.*$)", r"$1***$2"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## A7 · Semi-structured — from_json + schema, explode / posexplode, get_json_object
# MAGIC Parse a JSON string column with a schema, then `explode` an array into rows. `get_json_object` plucks a single path without a full schema.

# COMMAND ----------

events = spark.createDataFrame(
    [(1, '{"user":"asha","items":[{"sku":"A","qty":2},{"sku":"B","qty":1}]}')],
    "id int, payload string",
)
schema = StructType([
    StructField("user", StringType()),
    StructField("items", ArrayType(StructType([
        StructField("sku", StringType()),
        StructField("qty", IntegerType()),
    ]))),
])
parsed = events.withColumn("j", from_json("payload", schema))
display(
    parsed
    .select("id", "j.user", explode("j.items").alias("item"))       # one row per array element
    .select("id", "user", "item.sku", "item.qty")
)
# Single-path pluck without a schema:
display(events.select(get_json_object("payload", "$.user").alias("user")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A8 · unionByName · pivot · stack (unpivot)
# MAGIC `unionByName` aligns by column name (safer than `union`, which is positional). `pivot` long→wide; `stack` wide→long.

# COMMAND ----------

monthly = spark.createDataFrame(
    [(10, "jan", 100.0), (10, "feb", 150.0), (11, "jan", 80.0)],
    "account_id int, month string, amount double",
)
wide = monthly.groupBy("account_id").pivot("month").sum("amount")   # long -> wide (.sum here = GroupedData method)
display(wide)
# wide -> long again with stack
display(wide.selectExpr("account_id", "stack(2, 'jan', jan, 'feb', feb) as (month, amount)"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A9 · Delta MERGE — SQL and the DeltaTable Python API (upsert / SCD1)
# MAGIC The upsert primitive. Seed a target, then merge updates+inserts.

# COMMAND ----------

target = f"{CATALOG}.{SCHEMA}.dim_account"
spark.sql(f"DROP TABLE IF EXISTS {target}")
(spark.createDataFrame([(10, "ACTIVE"), (11, "ACTIVE")], "account_id int, status string")
 .write.saveAsTable(target))

spark.createDataFrame(
    [(11, "DORMANT"), (12, "ACTIVE")], "account_id int, status string"
).createOrReplaceTempView("updates")

# (a) SQL MERGE
spark.sql(f"""
    MERGE INTO {target} t
    USING updates s ON t.account_id = s.account_id
    WHEN MATCHED THEN UPDATE SET t.status = s.status
    WHEN NOT MATCHED THEN INSERT (account_id, status) VALUES (s.account_id, s.status)
""")
display(spark.table(target).orderBy("account_id"))

# COMMAND ----------

# (b) Same thing via the DeltaTable Python API
from delta.tables import DeltaTable

updates_df = spark.createDataFrame([(10, "CLOSED")], "account_id int, status string")
dt = DeltaTable.forName(spark, target)
(
    dt.alias("t")
    .merge(updates_df.alias("s"), "t.account_id = s.account_id")
    .whenMatchedUpdateAll()
    .whenNotMatchedInsertAll()
    .execute()
)
display(spark.table(target).orderBy("account_id"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## A10 · UDFs — and why to avoid Python UDFs
# MAGIC Order of preference: **built-in functions** > **Pandas (vectorized) UDF** > **Python UDF**. A plain Python UDF serializes row-by-row (slow, no Catalyst optimization). Use a built-in whenever one exists.

# COMMAND ----------

import pandas as pd

# Plain Python UDF (AVOID if a built-in exists — row-by-row, slow)
@udf(StringType())
def mask_py(email):
    return None if email is None else email[0] + "***" + email[email.find("@"):]

# Pandas UDF (vectorized — much faster when you truly need Python)
@pandas_udf(StringType())
def mask_pandas(s: pd.Series) -> pd.Series:
    return s.str.replace(r"(^.).*(@.*$)", r"\1***\2", regex=True)

# BEST: built-in, no UDF at all
display(
    customers
    .withColumn("py_udf", mask_py("email"))
    .withColumn("pandas_udf_col", mask_pandas("email"))
    .withColumn("builtin", regexp_replace("email", r"(^.).*(@.*$)", r"$1***$2"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part B — Pure Python must-haves

# COMMAND ----------

# Comprehensions, dict/list/set ops, f-strings
nums = [1, 2, 3, 4, 5]
squares = [n * n for n in nums]                       # list comp
evens = {n for n in nums if n % 2 == 0}               # set comp
by_parity = {("even" if n % 2 == 0 else "odd"): n for n in nums}  # dict comp
print(f"squares={squares}  evens={evens}  dict={by_parity}")

# *args / **kwargs
def make_table(*cols, **opts):
    return f"cols={cols}  opts={opts}"
print(make_table("id", "name", mode="overwrite", partition="dt"))

# COMMAND ----------

# try / except / finally + a custom exception
class DataQualityError(Exception):
    pass

def validate(row_count: int) -> None:
    try:
        if row_count == 0:
            raise DataQualityError("zero rows ingested")
        print(f"OK: {row_count} rows")
    except DataQualityError as e:
        print(f"DQ failure: {e}")
        raise
    finally:
        print("validation finished (always runs)")

validate(42)

# COMMAND ----------

# Context manager (with), type hints, dataclass
from dataclasses import dataclass
from contextlib import contextmanager

@dataclass
class SourceConfig:
    name: str
    pk: str
    full_load: bool = False

@contextmanager
def stage(label: str):
    print(f">> start {label}")
    try:
        yield
    finally:
        print(f"<< end   {label}")

cfg: SourceConfig = SourceConfig(name="customers", pk="customer_id")
with stage("ingest customers"):
    print("processing", cfg.name, "pk=", cfg.pk)

# COMMAND ----------

# logging, json/csv stdlib, pathlib, datetime
import logging, json, csv, io
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")
log.info("structured logging beats print() in production")

record = {"account_id": 10, "amount": 150.0}
s = json.dumps(record)                       # dict -> JSON string
back = json.loads(s)                         # JSON string -> dict
print("json round-trip:", back)

buf = io.StringIO()
csv.writer(buf).writerow(["account_id", "amount"])      # csv stdlib
print("csv row:", buf.getvalue().strip())

run_date = datetime(2024, 6, 1)
print("yesterday:", (run_date - timedelta(days=1)).date())   # datetime math
print("path parts:", Path("/Volumes/main/raw/file.csv").suffix)

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part C — Automation (the "reusable across 20 sources" answer)

# COMMAND ----------

# retry-with-backoff decorator
import time, functools

def retry(max_attempts: int = 3, backoff: float = 2.0):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 1
            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:                       # noqa: BLE001
                    if attempt >= max_attempts:
                        log.error("giving up after %d attempts: %s", attempt, e)
                        raise
                    log.warning("attempt %d failed (%s); retrying in %.1fs", attempt, e, backoff ** attempt)
                    time.sleep(backoff ** attempt)
                    attempt += 1
        return wrapper
    return deco

# config-driven loop: ONE function, N sources (DRY)
SOURCES = [
    SourceConfig("customers", "customer_id"),
    SourceConfig("accounts", "account_id"),
    SourceConfig("transactions", "txn_id"),
]

@retry(max_attempts=2, backoff=1.0)
def ingest(cfg: SourceConfig) -> int:
    log.info("ingesting %s (pk=%s)", cfg.name, cfg.pk)
    # ... real ingest would read source -> raw -> enriched ...
    return 100  # pretend row count

results = {cfg.name: ingest(cfg) for cfg in SOURCES}
print("ingested:", results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Databricks SDK — trigger / monitor jobs programmatically
# MAGIC `WorkspaceClient` uses unified auth (no tokens in code). The `me()` call proves the client works; job calls are commented (they need a real `job_id`).

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
print("Authenticated as:", w.current_user.me().user_name)

# Trigger a job and block until it finishes (illustrative — supply a real job_id):
# run = w.jobs.run_now(job_id=1234).result()
# print(run.state.result_state)
# List jobs:
# for j in w.jobs.list(): print(j.job_id, j.settings.name)

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Part D — The 8 banking drills (worked)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 1 · Schema standardization (all-string CSV -> typed; bad rows -> _rescued)
# MAGIC Cast safely, parse dates with an explicit format, and quarantine rows that fail parsing instead of silently nulling them.

# COMMAND ----------

raw = spark.createDataFrame(
    [("10", "150.00", "2024-06-01"), ("11", "bad", "01/06/2024"), ("12", "75.00", "2024-06-02")],
    "account_id string, amount string, txn_date string",
)
typed = (
    raw
    .withColumn("account_id", col("account_id").cast("int"))
    .withColumn("amount", col("amount").cast("decimal(12,2)"))
    .withColumn("txn_date", to_date("txn_date", "yyyy-MM-dd"))
)
# A row is "rescued" if any cast that should have worked produced NULL
typed = typed.withColumn(
    "_rescued",
    when(col("amount").isNull() | col("txn_date").isNull(), lit(True)).otherwise(lit(False)),
)
display(typed)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 2 · Keep-latest-per-key (CDC / SCD core)
# MAGIC Window by business key, order by sequence desc, keep `row_number() == 1`.

# COMMAND ----------

changes = spark.createDataFrame(
    [(10, "ACTIVE", "2024-06-01"), (10, "DORMANT", "2024-06-03"), (11, "ACTIVE", "2024-06-02")],
    "account_id int, status string, seq_ts string",
)
w = Window.partitionBy("account_id").orderBy(col("seq_ts").desc())
display(changes.withColumn("rn", row_number().over(w)).filter("rn = 1").drop("rn"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 3 · Gaps-and-islands (consecutive-day runs)
# MAGIC Trick: `date - row_number()` is constant within a consecutive run, so group by that constant.

# COMMAND ----------

logins = spark.createDataFrame(
    [(1, "2024-06-01"), (1, "2024-06-02"), (1, "2024-06-03"), (1, "2024-06-06"), (1, "2024-06-07")],
    "user_id int, d string",
).withColumn("d", to_date("d"))

w = Window.partitionBy("user_id").orderBy("d")
islands = (
    logins
    .withColumn("rn", row_number().over(w))
    # subtract rn days from the date -> same anchor for a consecutive streak
    .withColumn("grp", date_sub(col("d"), col("rn")))
    .groupBy("user_id", "grp")
    .agg(min("d").alias("streak_start"), max("d").alias("streak_end"), count("*").alias("days"))
    .drop("grp")
)
display(islands)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 4 · Reconciliation (source vs target: counts + control totals)
# MAGIC `left_anti` finds missing keys; aggregate both sides and compare totals.

# COMMAND ----------

source = spark.createDataFrame([(10, 150.0), (11, 75.0), (12, 500.0)], "account_id int, amount double")
loaded = spark.createDataFrame([(10, 150.0), (11, 75.0)], "account_id int, amount double")

missing = source.join(loaded, "account_id", "left_anti")
recon = spark.createDataFrame(
    [(
        source.count(), loaded.count(),
        float(source.agg(sum("amount")).first()[0]),
        float(loaded.agg(sum("amount")).first()[0]),
    )],
    "source_rows long, target_rows long, source_total double, target_total double",
).withColumn("row_diff", col("source_rows") - col("target_rows")) \
 .withColumn("amount_diff", col("source_total") - col("target_total"))
print("Missing keys:")
display(missing)
print("Reconciliation report:")
display(recon)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 5 · JSON flattening (semi-structured -> tabular)
# MAGIC (Same technique as A7, applied.) `from_json` + `explode`.

# COMMAND ----------

orders = spark.createDataFrame(
    [(1, '{"acct":10,"lines":[{"sku":"A","amt":50},{"sku":"B","amt":100}]}')],
    "order_id int, body string",
)
osch = StructType([
    StructField("acct", IntegerType()),
    StructField("lines", ArrayType(StructType([
        StructField("sku", StringType()), StructField("amt", IntegerType())]))),
])
display(
    orders.withColumn("j", from_json("body", osch))
    .select("order_id", "j.acct", explode("j.lines").alias("l"))
    .select("order_id", "acct", "l.sku", "l.amt")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 6 · MERGE upsert (SCD1) — done in A9 above
# MAGIC See cells **A9 (a)** SQL and **A9 (b)** DeltaTable API — that *is* drill 6.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 7 · Automation: retry decorator + config loop — done in Part C above
# MAGIC See the `retry(...)` decorator and the `SOURCES` config-driven loop in Part C.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Drill 8 · Pivot — long transactions -> per-account monthly matrix

# COMMAND ----------

tx = spark.createDataFrame(
    [(10, "2024-01", 100.0), (10, "2024-02", 150.0), (11, "2024-01", 80.0), (11, "2024-02", 60.0)],
    "account_id int, month string, amount double",
)
display(tx.groupBy("account_id").pivot("month").sum("amount"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cleanup (optional)
# MAGIC Uncomment to drop the scratch schema when you're done.

# COMMAND ----------

# spark.sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{SCHEMA} CASCADE")
print("Done. Reference notebook complete.")
