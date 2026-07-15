# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Reusable Source-Ingestion Notebook (child)
# MAGIC
# MAGIC Parameterized, secret-driven ingestion of **one** source system into **Raw → Enriched** layers.
# MAGIC
# MAGIC Answers:
# MAGIC - **Q1** — parameterize across sources/environments (widgets + job parameters)
# MAGIC - **Q2** — keep DB credentials out of the code (secret scopes)
# MAGIC - **Q3 (part 1)** — return a value via `dbutils.notebook.exit` so a parent can chain on it
# MAGIC
# MAGIC > Runs anywhere: if no secret scope is supplied it falls back to synthetic data, so you can execute the demo without a real database.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q1 — Parameterize across sources / environments
# MAGIC `widgets` give the notebook inputs; when run as a **Job task**, a **job parameter** with the same key overrides the widget default. One notebook, every source, every env.

# COMMAND ----------

dbutils.widgets.text("env", "dev", "Environment (dev/prod)")
dbutils.widgets.text("source_system", "customers", "Source system / table name")
dbutils.widgets.text("catalog", "main", "Target catalog (use one you can CREATE in)")
dbutils.widgets.text("secret_scope", "", "Secret scope for DB creds (blank = demo mode)")

env = dbutils.widgets.get("env")
source_system = dbutils.widgets.get("source_system")
catalog = dbutils.widgets.get("catalog")
secret_scope = dbutils.widgets.get("secret_scope")

# Per-environment, per-source target names — derived, not hardcoded
schema = f"de_pro_demo_{env}"
raw_table = f"{catalog}.{schema}.raw_{source_system}"
enriched_table = f"{catalog}.{schema}.enriched_{source_system}"

print(f"env={env}  source={source_system}")
print(f"  raw      -> {raw_table}")
print(f"  enriched -> {enriched_table}")

# COMMAND ----------

# Requires CREATE SCHEMA on `catalog`. If you can't create in `main`, set the
# `catalog` widget to a sandbox catalog you own.
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q2 — Keep DB credentials out of the code
# MAGIC Credentials live in a **secret scope**, never in the notebook or Git. Secret values are **auto-redacted** in cell output (a `print` shows `[REDACTED]`). The real path below uses JDBC + secrets; with no scope set it generates demo data so the notebook still runs.

# COMMAND ----------

from pyspark.sql import functions as F


def read_source(source_system: str):
    """Read the source via JDBC using secret-scoped credentials.
    Falls back to synthetic data when no secret scope is configured."""
    if secret_scope:
        # --- REAL PATTERN: credentials never appear in code or output ---
        jdbc_host = dbutils.secrets.get(scope=secret_scope, key="jdbc_host")
        jdbc_user = dbutils.secrets.get(scope=secret_scope, key="jdbc_user")
        jdbc_pwd = dbutils.secrets.get(scope=secret_scope, key="jdbc_password")
        print("Loaded JDBC creds from scope:", jdbc_user, jdbc_pwd)  # prints [REDACTED] [REDACTED]
        return (
            spark.read.format("jdbc")
            .option("url", f"jdbc:postgresql://{jdbc_host}:5432/bank")
            .option("dbtable", source_system)
            .option("user", jdbc_user)
            .option("password", jdbc_pwd)
            .load()
        )
    # --- DEMO FALLBACK: synthetic rows so the notebook runs without a DB ---
    print("No secret scope set -> generating synthetic source data for the demo.")
    return (
        spark.range(0, 1000)
        .withColumnRenamed("id", "record_id")
        .withColumn("source_system", F.lit(source_system))
        .withColumn("amount", (F.rand(seed=42) * 1000).cast("decimal(10,2)"))
        .withColumn("is_active", (F.rand(seed=7) > 0.1))
    )


src_df = read_source(source_system)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load → Raw, then Transform → Enriched  (this is **ELT**)
# MAGIC **Raw** = land the source as-is + ingestion metadata (the *L*). **Enriched** = cleanse/standardize with Spark (the *T*).

# COMMAND ----------

# RAW (the "L"): land as-is + lineage/metadata columns
raw_df = (
    src_df
    .withColumn("_ingest_ts", F.current_timestamp())
    .withColumn("_env", F.lit(env))
    .withColumn("_source_system", F.lit(source_system))
)
raw_df.write.mode("overwrite").saveAsTable(raw_table)

# COMMAND ----------

# ENRICHED (the "T"): dedup on the business key + basic data-quality filter
enriched_df = (
    spark.table(raw_table)
    .dropDuplicates(["record_id"])
    .filter(F.col("amount").isNotNull() & (F.col("amount") >= 0))
)
enriched_df.write.mode("overwrite").saveAsTable(enriched_table)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q3 (part 1) — return a value so a parent notebook can chain on the result
# MAGIC `dbutils.notebook.exit(value)` returns a **string**. We return JSON so the caller can parse counts (a tiny reconciliation signal).

# COMMAND ----------

import json

raw_count = spark.table(raw_table).count()
enriched_count = spark.table(enriched_table).count()

dbutils.notebook.exit(
    json.dumps(
        {
            "source_system": source_system,
            "env": env,
            "raw_count": raw_count,
            "enriched_count": enriched_count,
            "dropped_by_dq": raw_count - enriched_count,
        }
    )
)
