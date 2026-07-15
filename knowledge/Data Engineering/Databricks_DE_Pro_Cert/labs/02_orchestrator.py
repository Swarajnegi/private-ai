# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Orchestrator / Driver Notebook (parent)
# MAGIC
# MAGIC Runs `01_ingest_source` for several sources, collects each child's returned value, and shows a reconciliation summary.
# MAGIC
# MAGIC Answers:
# MAGIC - **Q3 (part 2)** — chain notebooks: `dbutils.notebook.run` (separate context, returns a string) vs `%run` (inlines into this context) vs Jobs `taskValues`
# MAGIC - **Q4** — when to move OFF notebooks to packaged code
# MAGIC
# MAGIC > Import this notebook into the **same folder** as `01_ingest_source` so the relative path `./01_ingest_source` resolves.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q3 (part 2) — chain with `dbutils.notebook.run` and read the returned value
# MAGIC Each child runs in its **own context** and returns a **string** (our JSON). Set `SECRET_SCOPE` to your scope name to exercise the real JDBC path; leave it blank for demo mode.

# COMMAND ----------

import json

ENV = "dev"
CATALOG = "main"          # set to a catalog you can CREATE in
SECRET_SCOPE = ""          # blank = demo data; else the scope holding jdbc_host/jdbc_user/jdbc_password
SOURCES = ["customers", "accounts", "transactions"]

results = []
for src in SOURCES:
    payload = dbutils.notebook.run(
        "./01_ingest_source",                 # relative path to the child (same folder)
        600,                                   # timeout_seconds
        {                                       # arguments -> the child's widgets
            "env": ENV,
            "source_system": src,
            "catalog": CATALOG,
            "secret_scope": SECRET_SCOPE,
        },
    )
    results.append(json.loads(payload))        # child returned a JSON string via dbutils.notebook.exit

# COMMAND ----------

# MAGIC %md
# MAGIC ### Reconciliation summary across all sources

# COMMAND ----------

summary = spark.createDataFrame(results).select(
    "source_system", "env", "raw_count", "enriched_count", "dropped_by_dq"
)
display(summary)

# COMMAND ----------

# MAGIC %md
# MAGIC ### `%run` vs `dbutils.notebook.run` vs Jobs `taskValues` (the three ways to chain)
# MAGIC
# MAGIC **1. `dbutils.notebook.run("./child", timeout, args)`** — used above. Runs the child in a **separate execution context**; returns only a **string** (`dbutils.notebook.exit`). Best for fan-out / passing parameters per call.
# MAGIC
# MAGIC **2. `%run ./_shared_helpers`** — *inlines* another notebook into **this** context: its functions/variables become available here (same session, no return value). Use it for **shared helper code**, e.g.:
# MAGIC ```python
# MAGIC # %run ./_shared_helpers      # (a sibling notebook that defines log_run)
# MAGIC # log_run("ingestion batch complete", results)
# MAGIC ```
# MAGIC
# MAGIC **3. Jobs `taskValues`** — when these notebooks are **tasks in a Lakeflow Job**, pass values task→task (not exit strings):
# MAGIC ```python
# MAGIC # upstream "ingest" task:
# MAGIC dbutils.jobs.taskValues.set(key="rows", value=raw_count)
# MAGIC # downstream task:
# MAGIC n = dbutils.jobs.taskValues.get(taskKey="ingest", key="rows", default=0, debugValue=0)
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ## Q4 — When to move OFF notebooks to packaged code
# MAGIC
# MAGIC | Stay in notebooks | Graduate to packaged Python + Databricks Asset Bundles (DABs) |
# MAGIC |---|---|
# MAGIC | Exploration / ad-hoc analysis / one-off backfill | Logic reused across more than one notebook or pipeline |
# MAGIC | A single transform wired in as a Job task | Needs **unit tests** (`assertDataFrameEqual`, `assertSchemaEqual`, `pytest`) |
# MAGIC | Prototyping | **CI/CD** + environment promotion (dev → prod) |
# MAGIC | Quick demo (like this one) | Versioned **config-as-code** — Git folders version *code only*; DABs version code **and** job/pipeline config |
# MAGIC
# MAGIC **Rule of thumb:** the moment shared logic is copy-pasted into a second notebook, extract it into a **Python module inside a Databricks Asset Bundle** (`databricks.yml`), `import` it, and unit-test it. Notebooks become **thin entry points**; the real logic lives in tested, deployable packages.
# MAGIC
# MAGIC ```
# MAGIC my_bundle/
# MAGIC ├── databricks.yml            # targets: dev / prod  (deploy + run)
# MAGIC ├── src/ingestion/transforms.py   # tested, importable logic
# MAGIC ├── tests/test_transforms.py      # pytest + assertDataFrameEqual
# MAGIC └── resources/ingest_job.yml      # the job/pipeline definition as code
# MAGIC ```
