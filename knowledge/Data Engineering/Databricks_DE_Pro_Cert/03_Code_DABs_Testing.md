# Day 3 — Developing Code: DABs, Testing, UDFs

> **Exam weight:** Section 1 "Developing Code" is **22%** — the single biggest slice of the 59-question exam (~13 questions). This file targets the *new/gap* sub-topics only: Databricks Asset Bundles (DABs), third-party library management, Pandas vs Python UDFs, pipeline control-flow operators, compute/dependency configs, and the unit/integration testing toolkit (`assertDataFrameEqual`, `assertSchemaEqual`, `DataFrame.transform`, pytest, the built-in debugger).
>
> You already own SDP, AUTO CDC, SCD2, expectations, Auto Loader, streaming-tables-vs-MVs, and `APPLY CHANGES` from Apollo Gen2 (422 SDP pipelines) — those are **not** re-taught here. The exam objectives list them under Section 1 too, but for you they are revision, not new material. Lean on `SDP_Syntax.md` and `Novartis_SDP_50Q_Bank.md` for that half.
>
> **Naming caveat (read this first):** Databricks renamed "Databricks Asset Bundles" to **"Declarative Automation Bundles"** in the docs during 2025. The CLI command group, the file (`databricks.yml`), and every flag are **unchanged** — only the marketing name moved. The exam (objectives dated Nov 30 2025) still says "Databricks Asset Bundles (DABs)". When you see either name, they are the same thing. I use "DAB" throughout. ([What are Declarative Automation Bundles?](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/))

---

## 1. Databricks Asset Bundles — `databricks.yml` anatomy

**What a DAB is:** an Infrastructure-as-Code (IaC) packaging format. You describe Databricks resources (jobs, pipelines, notebooks, clusters, dashboards, even UC catalogs) as YAML + source files in one folder, then `validate` / `deploy` / `run` them programmatically. The folder *is* the bundle the moment it contains a `databricks.yml` at its root — the CLI auto-detects it. ([Settings](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/settings))

The smallest legal `databricks.yml`:

```yaml
bundle:
  name: my_bundle      # required top-level mapping

targets:
  dev:
    default: true       # this target is used when -t is omitted
```

The five top-level mappings you must recognize on the exam:

| Mapping | Role | Concrete content |
|---|---|---|
| `bundle` | Identity | `name:` (required). A bundle's **unique identity = name + target + deployer identity**. Two bundles with all three identical will *clobber each other on deploy* — silent interference. ([Develop bundles](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/work-tasks)) |
| `include` | Modularity | List of other YAML files to pull in, e.g. `resources/*.yml`. Keeps `databricks.yml` thin. |
| `targets` | Environments | `dev` / `staging` / `prod`. Each can set `mode`, `workspace.host`, `workspace.root_path`, `run_as`, and its own `resources` overrides. |
| `resources` | What gets deployed | Map keyed by resource type (`jobs`, `pipelines`, `clusters`, …). Each resource's keys are the **create-request fields of the matching REST API object**, expressed as YAML. ([resources reference](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/reference#resources)) |
| `artifacts` | Build steps | Things to build at deploy time (e.g. a Python wheel). See §2. |

**The single most testable fact about `resources`:** the YAML keys for a job/pipeline are *exactly* the fields of that object's REST API create payload — there is no separate "bundle schema". So `databricks bundle validate` warns on *unknown* resource properties, and `databricks bundle schema` can emit the full JSON schema for IDE autocomplete. ([resources](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/resources))

### Worked example: a job + pipeline bundle with dev/prod overrides

```yaml
bundle:
  name: apollo_ingest

include:
  - resources/*.yml

variables:
  catalog:
    description: UC catalog for output tables
    default: dev_catalog

targets:
  dev:
    mode: development          # see deployment modes below
    default: true
    workspace:
      host: https://adb-dev.azuredatabricks.net
  prod:
    mode: production
    workspace:
      host: https://adb-prod.azuredatabricks.net
      root_path: /Workspace/Users/sp-apollo@corp.com/.bundle/${bundle.name}/${bundle.target}
    run_as:
      service_principal_name: sp-apollo@corp.com
    variables:
      catalog: prod_catalog     # override the dev default per target
```

```yaml
# resources/ingest_job.yml
resources:
  jobs:
    ingest_job:
      name: "[${bundle.target}] apollo ingest"
      tasks:
        - task_key: bronze
          notebook_task:
            notebook_path: ../src/bronze.py
```

**Deployment modes — a guaranteed exam point.** `mode: development` and `mode: production` are *presets* that silently change behavior:

- `mode: development` — prefixes every deployed resource name with `[dev <your-username>]`, pauses schedules/triggers, tags resources `dev`, and makes things editable in the UI. This is why your dev job shows up as `[dev swaraj] ingest_job`.
- `mode: production` — no name prefix, schedules active, **editing is always disabled in the UI**, and validation *requires* `workspace.host` + `root_path` unless `run_as` is a service principal. ([deployment modes](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/deployment-modes); [CI/CD for Apps](https://learn.microsoft.com/azure/databricks/dev-tools/databricks-apps/cicd-github-actions#step-3-configure-your-bundle-for-production-deployments))

The `${bundle.target}` / `${bundle.name}` / `${var.catalog}` syntax is **substitution** — resolved at deploy time, not committed. That is how the same YAML produces a `[dev ...]` job in dev and a clean-named job in prod.

> **Recap:** A DAB is one folder with one `databricks.yml`; its `resources` keys mirror REST API create payloads; `targets` + `mode` presets silently rewrite resource names/schedules/editability — `development` prefixes and pauses, `production` locks editing and demands an explicit host/root_path.

---

## 2. Modular Python project structure + the wheel artifact

The exam objective is literally "scalable Python project structure for DABs enabling modular dev + deployment automation + CI/CD". The canonical structure comes from `databricks bundle init default-python`. ([templates](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/templates); [Python wheel tutorial](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/python-wheel))

```
my_project/
├── databricks.yml            # bundle root — CLI detects the bundle here
├── pyproject.toml            # build config (default-python now uses uv + pyproject.toml)
├── resources/
│   └── my_project_job.yml    # job/pipeline definitions, pulled in via include:
├── src/
│   └── my_package/
│       ├── __init__.py
│       ├── main.py
│       └── my_module.py      # ← the reusable business logic lives here
└── tests/
    └── test_main.py          # ← pytest lives here, imports from src/
```

The architectural rule Databricks pushes (and the exam rewards): **minimize business logic in notebooks.** Put core logic in importable `.py` modules under `src/`; keep notebooks as thin orchestration/visualization that *call* those functions. This is what makes the code unit-testable off-cluster. ([best practices](https://learn.microsoft.com/azure/databricks/developers/best-practices#general-development))

**Building a wheel via the `artifacts` mapping.** A Python wheel (`.whl`) is a pre-built, installable Python package archive. You tell the bundle to build (and test) it at deploy time:

```yaml
artifacts:
  default:
    type: whl
    build: |-
      # run tests first — a failing test aborts the build/deploy
      python -m pytest tests/ -v

      # then build the artifact
      python setup.py bdist_wheel
    path: .
```

When you `databricks bundle deploy`, the CLI runs the `build` command, uploads the resulting `.whl`, and a `python_wheel_task` in your job installs and runs it. ([artifacts reference](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/reference#artifacts)) Note the silent ordering: **tests run as part of the build**, so a red test stops the deploy — that is the integration point between testing and deployment.

> Two newer template facts worth knowing: the `default-python` template **defaults to serverless compute** (since CLI 0.257.0) and **uses `uv` + `pyproject.toml`** to build wheels (since CLI 0.258.0). `uv` is a fast Python package/dependency installer; the template requires it installed locally. ([bundle release notes](https://learn.microsoft.com/azure/databricks/release-notes/dev-tools/bundles))

> **Recap:** Scalable = logic in `src/<package>/`, tests in `tests/`, thin notebooks; the `artifacts: {type: whl, build: ...}` mapping builds (and runs pytest on) the wheel at deploy time, so a failing test fails the deploy.

---

## 3. The bundle lifecycle: `validate` → `deploy` → `run` → `destroy`

These four CLI verbs are the most-tested DAB facts. Run them from the bundle root (or set `BUNDLE_ROOT`). ([bundle commands](https://learn.microsoft.com/azure/databricks/dev-tools/cli/bundle-commands); [work-tasks](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/work-tasks))

```bash
databricks bundle validate                  # check YAML against object schemas; warns on unknown keys
databricks bundle deploy -t dev              # sync files + create/update resources in the dev target
databricks bundle run -t dev ingest_job      # trigger a deployed resource (job or pipeline) by name
databricks bundle summary                    # show deployed host/user/path + resource URLs
databricks bundle destroy                    # permanently delete the deployed resources (prompts y/N)
```

Execution trace of a first deploy to `dev`:
1. `validate` parses `databricks.yml` + everything in `include`, resolves `${...}` substitutions, and checks each resource's fields against its REST object schema. Success prints a summary (name, target, host, user).
2. `deploy -t dev` uploads source files to `/Workspace/Users/<you>/.bundle/<bundle>/dev/files/...`, builds artifacts, then creates the resources — a dev job lands named `[dev swaraj] ingest_job` with schedule paused.
3. `run -t dev ingest_job` starts a run and prints a **Run URL**.
4. `destroy` deletes the job and the deployed folder — **but not side effects** (tables/files the job created). Those you clean up manually.

Two related verbs the exam likes:
- `databricks bundle generate job --existing-job-id <id> -t dev` — reverse-engineer YAML from a job that already exists in the workspace (migration path).
- `databricks bundle deployment bind <resource> <id> -t dev` — link bundle config to an *existing* workspace resource so deploy updates it instead of creating a duplicate. ([migrate-resources](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/migrate-resources)) This is the answer to "how do I bring my hand-built prod job under DAB control without creating a second copy?"

### CI/CD wiring (Git + GitHub Actions)

Databricks' recommended flow: trunk-based branching, single repo for code + bundle config, versioned artifacts (Git SHA), and a **service principal** for deploy. ([CI/CD flows](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/flows); [GitHub Actions](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/github))

```yaml
# .github/workflows/deploy.yml (skeleton)
jobs:
  deploy:
    runs-on: ubuntu-latest
    env:
      DATABRICKS_HOST: ${{ vars.DATABRICKS_HOST }}
      DATABRICKS_TOKEN: ${{ secrets.SP_TOKEN }}   # service-principal token, not a user PAT
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - run: databricks bundle validate
      - run: databricks bundle deploy -t prod
```

Exam-critical CI/CD points:
- **Use a service principal, not a personal token,** for non-dev automation — and use *separate* SPs for deploy (minimal data access) vs. runtime/run-as (scoped to the workload's data). ([best practices](https://learn.microsoft.com/azure/databricks/developers/best-practices#general-development))
- **DABs vs. Git Folders.** DABs are the *recommended* full CI/CD path because they version code **and** resource config (jobs/pipelines/schedules). Git Folders (and "Git with jobs") version **only code files** — job/pipeline configuration is *not* source-controlled. If a question asks "what deploys jobs+config reproducibly across workspaces?" the answer is DABs; Git Folders is the lighter option when you have no external CI/CD. ([CI/CD tools](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/#available-tools))

> **Recap:** `validate` (schema-check) → `deploy -t <target>` (sync + create) → `run -t <target> <name>` (trigger) → `destroy` (delete resources, not data). Use `generate` + `deployment bind` to adopt existing resources without duplicating; deploy via a service principal; DABs version code *and* config, Git Folders version only code.

---

## 4. Third-party library management (PyPI, wheels, source archives, requirements)

The exam objective: "manage/troubleshoot third-party libs (PyPI, local wheels, source archives)". The decisive concept is **scope** — where a library is visible. ([Install libraries](https://learn.microsoft.com/azure/databricks/libraries/))

| Scope | How | Visibility | When |
|---|---|---|---|
| **Notebook-scoped** | `%pip install` inside the notebook | Only the current notebook's isolated session | Per-notebook custom env; safe experimentation |
| **Compute-scoped (cluster)** | Cluster **Libraries** tab / policy / Jobs API | Every notebook + job on that cluster | Shared dependency for a cluster |
| **Job task dependent libs** | Task's **Dependent libraries** field | That task only | Per-task deps without polluting the cluster |
| **Serverless environment** | Environment side-pane / base-environment YAML | The serverless task | Serverless jobs (no cluster to attach to) |

**Sources** you can install from: PyPI (package name), Maven (JVM coordinate), CRAN (R), **workspace files**, **Unity Catalog volumes**, **cloud object storage** (full URI), and a **local path**. DBFS-root install is *deprecated and off by default in DBR 15.1+* because any workspace user can modify files there — a security/troubleshooting gotcha worth memorizing. ([cluster libraries](https://learn.microsoft.com/azure/databricks/libraries/cluster-libraries#install-a-library-on-a-cluster); [compute-scoped](https://learn.microsoft.com/azure/databricks/libraries/#compute-scoped-libraries))

Concrete install commands (notebook-scoped):

```python
# PyPI by name, pinned version (pin for serverless reproducibility)
%pip install matplotlib==3.8.4

# Local wheel (a built binary package) from a UC volume
%pip install /Volumes/main/lib/wheels/mypackage-0.0.1-py3-none-any.whl

# requirements.txt (a list of packages, one per line) from workspace files
%pip install -r /Workspace/shared/prod_requirements.txt

# Source archive / VCS install (a git source tree, built on install)
%pip install git+https://github.com/databricks/databricks-cli
```

`requirements.txt` is itself a supported source — both for notebook `%pip -r` and for cluster/job dependent-library installs (DBR 15.1+ added cluster-library support for `requirements.txt`). Each line is a package spec; on **No-isolation-shared** clusters only PyPI packages are allowed inside it (no nested file references). ([requirements file](https://learn.microsoft.com/azure/databricks/libraries/notebooks-python-libraries#use-a-requirements-file-to-install-libraries); [DBR 15.1 notes](https://learn.microsoft.com/azure/databricks/release-notes/runtime/15.1))

### Troubleshooting facts the exam tests (the silent behaviors)

- **A cluster library is invisible to an already-attached notebook until you start a new session.** Installing it does *not* hot-load into a running notebook. ([cluster libraries](https://learn.microsoft.com/azure/databricks/libraries/cluster-libraries#install-a-library-on-a-cluster))
- A library install that exceeds **2 hours** is auto-marked **failed**.
- **You cannot `%pip uninstall` a library baked into the Databricks Runtime or installed as a cluster library.** `%pip uninstall` only reverts to the runtime/cluster version; it can't remove the built-in one. `-y` is required on `%pip uninstall`.
- **Private PyPI mirror** (Nexus/Artifactory): `%pip install --index-url ...` with secrets — supported for notebook-scoped, **not** for compute-scoped or Jobs-API libraries. You can also set `DATABRICKS_PIP_INDEX_URL` / `DATABRICKS_PIP_EXTRA_INDEX_URL` as cluster env vars (DBR 15.1+). ([Python env management](https://learn.microsoft.com/azure/databricks/libraries/#python-environment-management))
- `%pip`, `%sh pip`, and `!pip` all install notebook-scoped on DBR 11.3 LTS+; on older runtimes only `%pip` is reliable. `%uv pip` is the faster serverless variant. ([%pip differences](https://learn.microsoft.com/azure/databricks/libraries/notebooks-python-libraries#differences-between-%60%25pip%60,-%60%25sh-pip%60,-and-%60!pip%60))

> **Recap:** Pick scope (notebook / cluster / task / serverless) before source (PyPI / wheel / requirements.txt / VCS / volume / object-storage). DBFS-root is deprecated; a freshly installed cluster lib needs a new session to appear; you can't uninstall runtime/cluster-baked libs; private mirrors via `--index-url` are notebook-scoped only.

---

## 5. Pandas UDFs vs Python UDFs

**UDF = User-Defined Function:** custom logic you can't express with built-in DataFrame/SQL functions. ([UDF overview](https://learn.microsoft.com/azure/databricks/udf/))

**The performance hierarchy (memorize the order):**
1. Built-in functions and SQL UDFs — fastest; the Catalyst optimizer runs them natively on the JVM.
2. Scala UDFs — run in the JVM, avoid (unisolated) or minimize (isolated) cross-runtime data movement.
3. **Python UDFs** — slowest. Each executor spawns a separate Python process; Spark must **serialize each row out of the JVM to Python and the result back** — row-at-a-time.
4. **Pandas (vectorized) UDFs** — up to **100× faster than Python UDFs** because they use **Apache Arrow** (a columnar in-memory format) to transfer data in *batches* and process them with pandas. ([performance considerations](https://learn.microsoft.com/azure/databricks/udf/#performance-considerations))

**Why the gap exists (the invisible cost):** a plain Python UDF converts Spark's internal columnar data → serialize → ship to Python → run → serialize back → deserialize into JVM, *per row*. A Pandas UDF does the same trip but on Arrow **record batches** (default 10,000 rows each), so the serialize/transfer overhead is amortized across thousands of rows. ([Spark UDF best practices](https://learn.microsoft.com/fabric/data-engineering/spark-best-practices-basics#udf-best-practices))

### Plain Python (scalar) UDF

```python
from pyspark.sql.functions import udf
from pyspark.sql.types import IntegerType

@udf(returnType=IntegerType())
def add_one(x):              # called once PER ROW
    return x + 1

df.select(add_one("age"))
```

> **DBR/Spark note that flips an old exam answer:** Arrow optimization for plain Python UDFs is **enabled by default since Spark 4.2**. You can still force the old pickle-based path with `@udf(returnType=..., useArrow=False)`. So "plain Python UDFs are always non-vectorized" is no longer strictly true on the newest runtimes — but the *Pandas UDF is still the canonical vectorized answer* on the exam. ([udf reference](https://learn.microsoft.com/azure/databricks/pyspark/reference/functions/udf#examples))

### Pandas UDF — the four type-hint signatures

You declare a Pandas UDF with the `@pandas_udf` decorator and a **Python type hint** that tells Spark which of four shapes it is. ([pandas UDFs](https://learn.microsoft.com/azure/databricks/udf/pandas))

**(a) Series → Series** (vectorized scalar; use with `select`/`withColumn`):

```python
import pandas as pd
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import LongType

@pandas_udf(LongType())
def multiply(a: pd.Series, b: pd.Series) -> pd.Series:   # batch in, same-length batch out
    return a * b

df.select(multiply(col("x"), col("x")))
```

**(b) Iterator[Series] → Iterator[Series]** — when you need expensive one-time setup (e.g. load an ML model once, then score every batch):

```python
from typing import Iterator

@pandas_udf("long")
def plus_one(batch_iter: Iterator[pd.Series]) -> Iterator[pd.Series]:
    # model = load_model()   # initialize state ONCE, before the loop
    for x in batch_iter:
        yield x + 1
```

**(c) Iterator[Tuple[Series, ...]] → Iterator[Series]** — same idea, multiple input columns:

```python
from typing import Iterator, Tuple

@pandas_udf("long")
def multiply_two(it: Iterator[Tuple[pd.Series, pd.Series]]) -> Iterator[pd.Series]:
    for a, b in it:
        yield a * b
```

**(d) Series → Scalar** (grouped aggregate; use with `groupBy().agg()` or `Window`):

```python
@pandas_udf("double")
def mean_udf(v: pd.Series) -> float:
    return v.mean()

df.groupby("id").agg(mean_udf(df["v"]))
```

Two silent behaviors on Pandas UDFs:
- **Batch size** is `spark.sql.execution.arrow.maxRecordsPerBatch` (default **10,000**). Large/wide rows can spike JVM memory when partitions convert to Arrow batches — lower it to avoid OOM. ([usage](https://learn.microsoft.com/azure/databricks/udf/pandas#usage))
- **Series→Scalar does NOT support partial aggregation** — *all* data for each group is loaded into memory. A huge group can OOM.
- **Timestamps are silently converted**: Spark→pandas truncates to the session time zone and to nanoseconds; pandas→Spark converts to UTC microseconds and **truncates any nanosecond precision**. ([timestamp semantics](https://learn.microsoft.com/azure/databricks/udf/pandas#usage))

> **UC governance distinction:** scalar Python UDFs run on serverless + standard-access clusters (DBR 13.3 LTS+); non-scalar (`pandas_udf`, `mapInPandas`, `applyInPandas`) need DBR 14.3 LTS+. Batch UC Python UDFs share an isolation environment by default (DBR 17.1+) unless you add `STRICT ISOLATION` (needed for UDFs that `eval`/`exec`, write files, or mutate global/env state). ([UC governed UDFs](https://learn.microsoft.com/azure/databricks/udf/#unity-catalog-governed-vs-session-scoped-udfs); [batch UDFs](https://learn.microsoft.com/azure/databricks/udf/python-batch-udf))

> **Recap:** Built-in/SQL > Scala > Pandas (Arrow, batched, ~100× faster) > plain Python (row-at-a-time serialization). Pandas UDFs come in 4 type-hinted shapes; the Iterator forms exist for one-time state init; Series→Scalar can OOM (no partial agg). Default Arrow batch = 10,000 rows.

---

## 6. Pipeline control-flow operators (If/else, For each, Run if)

This is the **Lakeflow Jobs** control-flow toolkit — orchestration *between* tasks, distinct from SDP's declarative dataset graph. ([control flow](https://learn.microsoft.com/azure/databricks/jobs/control-flow))

### If/else condition task

A boolean branch in the job DAG. The task itself needs **no compute**, supports no retries/notifications, and evaluates `operand <op> operand` where operands reference **task values**, **job parameters**, or **dynamic values**. ([If/else](https://learn.microsoft.com/azure/databricks/jobs/if-else))

```
Condition:  {{tasks.process_records.values.bad_records}}  >  0
```

Operators: `==`, `!=`, `>`, `>=`, `<`, `<=`. Downstream tasks attach to the `(true)` or `(false)` branch.

**The trap that costs people the question — numeric vs string comparison:**
- `==` and `!=` do **string** comparison → `12.0 == 12` is **false** (different strings).
- `>`, `>=`, `<`, `<=` do **numeric** comparison → `12.0 >= 12` is **true**.
- Non-numeric task values are serialized to strings (a boolean becomes `"true"`/`"false"`).
- An If/else task **fails** if the upstream task that supplies its condition value is disabled. ([If/else notes](https://learn.microsoft.com/azure/databricks/jobs/if-else))

### For each task

Runs one **nested task** per element of an input array — looping. ([For each](https://learn.microsoft.com/azure/databricks/jobs/for-each))

- **Inputs** = a JSON array, a task-value reference, or a job parameter. Reference the current element with `{{input}}`, or a field with `{{input.<key>}}`.
- **Concurrency** (default **1**) sets how many iterations run in parallel.
- You **cannot nest a For each inside a For each**.
- Size limits (silent failure points): the **Inputs** text box is **5,000 chars**; task-value references resolve to up to **48 KB**; job parameters up to **10 KB**. Bigger than that → use a lookup table (pass keys, not data). ([parameter types](https://learn.microsoft.com/azure/databricks/jobs/for-each#parameter-types-for-the-%60for-each%60-task); [lookup table](https://learn.microsoft.com/azure/databricks/jobs/for-each-lookup-example))

The metadata-driven pattern (control table → SQL task → For each): a SQL task emits `{{tasks.read_markets.output.rows}}`, the For each iterates each row, the nested task reads `{{input.market}}`. Add a new source = add a table row, no redeploy. ([control-table tutorial](https://learn.microsoft.com/azure/databricks/jobs/how-to/foreach-sql-lookup-tutorial))

In a DAB, this is `for_each_task` with `concurrency`, `inputs`, and a nested `task`:

```yaml
tasks:
  - task_key: process_markets
    for_each_task:
      concurrency: 2
      inputs: "{{tasks.read_markets.output.rows}}"
      task:
        task_key: run_iteration
        notebook_task:
          notebook_path: ../src/analyze.py
          base_parameters:
            market: "{{input.market}}"
```
([job-task-types](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/job-task-types#task-settings))

### Run if dependencies (don't confuse with If/else)

`Run if` controls whether a task runs based on the *status* of its upstream tasks — six options: **All succeeded · At least one succeeded · None failed · All done · At least one failed · All failed**. Use this for cleanup/error-handling branches (e.g. a task that runs only if an upstream `failed`). ([Run if](https://learn.microsoft.com/azure/databricks/jobs/run-if))

> **Recap:** If/else = value branch (`==`/`!=` are string compares — `12.0 == 12` is false; `>`/`<` are numeric); For each = loop with `{{input}}`/`{{input.<key>}}`, `concurrency` defaults to 1, can't be nested, watch the 5,000-char input limit; Run if = branch on upstream *status* (All succeeded / At least one failed / …), used for cleanup.

---

## 7. Configs: environments/deps, high-memory tasks, auto-optimization / disallow-retries

These four serverless-jobs settings are explicit exam objectives. ([run serverless jobs](https://learn.microsoft.com/azure/databricks/jobs/run-serverless-jobs))

**Environment & dependencies (serverless).** Serverless tasks have no cluster Libraries tab — install via the notebook **Environment** side-pane, a base-environment YAML, or `%pip install`. Only a whitelisted set of Spark configs is settable, **session-level only** (set them in a notebook in the same job). ([serverless dependencies](https://learn.microsoft.com/azure/databricks/compute/serverless/dependencies))

**High-memory notebook tasks (Public Preview).** If a notebook hits OOM, open the **Environment** side-pane → **Memory** → **High**:
- **Standard = 16 GB**, **High = 32 GB** total REPL memory.
- **Critical silent detail:** this raises only the **REPL (driver-side Python) memory — it does NOT change the Spark session memory.** So it fixes OOM in *local Python/pandas* code (e.g. a big `toPandas()` or a Series→Scalar UDF), not Spark executor OOM.
- High memory is **notebook-task-only** and has a **higher DBU emission rate**. ([high memory](https://learn.microsoft.com/azure/databricks/compute/serverless/dependencies#use-high-memory-serverless-compute))

**Auto-optimization & disallow-retries.** Serverless-for-workflows **auto-optimization** auto-tunes compute *and silently retries failed tasks* — on by default. For a **non-idempotent** job that must run **at most once**, you must turn it off:
1. Next to **Retries**, click **Add**/edit.
2. In the Retry Policy dialog, **uncheck "Enable serverless auto-optimization (may include additional retries)"**.
3. Confirm → Save task. ([disallow retries](https://learn.microsoft.com/azure/databricks/jobs/run-serverless-jobs#configure-serverless-compute-auto-optimization-to-disallow-retries))

The reasoning the exam wants: auto-optimization's hidden retries are great for *at-least-once* delivery, but dangerous for non-idempotent work (e.g. an `INSERT` that isn't a `MERGE`) where a retry double-writes. Disallow retries to enforce at-most-once.

**Performance mode (serverless):** *Performance optimized* ON = faster start, more DBUs; OFF = standard, 4–6 min startup latency, fewer DBUs, same SKU. ([performance mode](https://learn.microsoft.com/azure/databricks/jobs/run-serverless-jobs#select-a-performance-mode))

Config-hygiene rules (also tested): don't hardcode Spark configs like `spark.executor.memory` (overrides built-in optimizations → wasted spend); avoid init scripts and compute-scoped libs (env drift) — prefer `%pip` or an environment spec. ([config hygiene](https://learn.microsoft.com/azure/databricks/compute/cluster-config-best-practices#configuration-hygiene))

> **Recap:** Serverless deps go in the Environment pane / `%pip`; High memory (32 GB) raises **REPL/driver Python memory only, not Spark session** and is notebook-task-only; auto-optimization silently retries (at-least-once) — uncheck it to disallow retries for non-idempotent / at-most-once jobs.

---

## 8. Testing: `assertDataFrameEqual`, `assertSchemaEqual`, `DataFrame.transform`, pytest

### `DataFrame.transform` — the testable building block

`transform(func, *args, **kwargs)` returns a new DataFrame and is **concise syntax for chaining custom transformations**: `func` takes a DataFrame and returns a DataFrame. ([transform](https://learn.microsoft.com/azure/databricks/pyspark/reference/classes/dataframe/transform)) Its value for testing is that it lets you factor each transformation into a small, importable, independently-testable function:

```python
from pyspark.sql import DataFrame
from pyspark.sql.functions import col

def with_flags(df: DataFrame) -> DataFrame:
    return (df.withColumn("is_high", col("total_spend") > 100.0)
              .withColumn("is_low",  col("total_spend") < 20.0))

def only_active(df: DataFrame) -> DataFrame:
    return df.filter(col("status") == "active")

# Compose — readable left-to-right, and each func is unit-testable in isolation
result = raw_df.transform(with_flags).transform(only_active)
```

### `assertDataFrameEqual` and `assertSchemaEqual` (from `pyspark.testing`)

These are the two assertions the objective names explicitly. Import path: `from pyspark.testing import assertDataFrameEqual, assertSchemaEqual`. ([pyspark.testing — Apache Spark API](https://spark.apache.org/docs/latest/api/python/reference/pyspark.testing.html))

**`assertSchemaEqual`** — compares two schemas only (no data):

```python
assertSchemaEqual(
    actual, expected,
    ignoreNullable=False,     # True → don't fail on nullable mismatch
    ignoreColumnOrder=False,  # True → column order doesn't matter
    ignoreColumnName=False,   # True → compare by position, not name
    ignoreColumnType=False,   # True → don't fail on type mismatch
)
```

**`assertDataFrameEqual`** — compares schema **and** row data:

```python
assertDataFrameEqual(
    actual, expected,
    checkRowOrder=False,      # default False → order-insensitive row compare
    rtol=1e-5,                # relative tolerance for float compare
    atol=1e-8,                # absolute tolerance for float compare
    ignoreNullable=False,
    ignoreColumnOrder=False,
    ignoreColumnName=False,
    ignoreColumnType=False,
)
```

Two facts the exam can hinge on:
- **`checkRowOrder` defaults to `False`** — so two DataFrames with the same rows in different order are considered **equal** unless you set `checkRowOrder=True`. (Spark output order is non-deterministic, so order-insensitive is the sane default.)
- **Float comparison uses tolerances** (`rtol`/`atol`) — so `0.1 + 0.2` vs `0.3` passes. Set them when comparing computed doubles; otherwise tiny floating-point drift fails the test. On a mismatch the assertion raises a `PySparkAssertionError` showing the differing rows/schema.

> Heads-up on exact defaults: Spark's source sets `rtol`/`atol` to small nonzero values for float tolerance; the doc-rendered signature varies slightly by version. The *behavior to remember* is: rows compared order-insensitively by default, floats compared with tolerance. Don't memorize the exact float constant.

### Worked pytest example (off-cluster, the recommended pattern)

Databricks recommends storing functions and their tests **outside notebooks** so a real test framework can run them; pytest auto-discovers files named `test_*.py` and functions named `test_*`. ([unit testing](https://learn.microsoft.com/azure/databricks/notebooks/testing); [test notebooks](https://learn.microsoft.com/azure/databricks/notebooks/test-notebooks))

```python
# tests/test_transforms.py
import pytest
from pyspark.sql import SparkSession
from pyspark.testing import assertDataFrameEqual, assertSchemaEqual
from src.my_package.transforms import with_flags

@pytest.fixture(scope="session")
def spark():
    return SparkSession.builder.master("local[*]").appName("tests").getOrCreate()

def test_with_flags(spark):
    src = spark.createDataFrame([(1, 150.0), (2, 5.0)], ["id", "total_spend"])
    actual = src.transform(with_flags)
    expected = spark.createDataFrame(
        [(1, 150.0, True, False), (2, 5.0, False, True)],
        ["id", "total_spend", "is_high", "is_low"],
    )
    assertSchemaEqual(actual.schema, expected.schema)   # structure first
    assertDataFrameEqual(actual, expected)              # then data (order-insensitive)
```

```bash
$ pytest
==================== test session starts ====================
collected 1 item
tests/test_transforms.py .                          [100%]
===================== 1 passed ======================
```

Testing facts the exam tests:
- **Unit test against fake/non-production data** — never run mutating tests against prod tables. Build small in-memory DataFrames as fixtures. ([unit testing](https://learn.microsoft.com/azure/databricks/notebooks/testing#write-unit-tests))
- **Run pytest locally** for functions that take/return DataFrames in local memory; use **Databricks Connect** (set `"databricks": true` in the VS Code launch config) when the test needs a real cluster `SparkSession`. ([VS Code pytest](https://learn.microsoft.com/azure/databricks/dev-tools/vscode-ext/pytest))
- In-notebook quick tests: `unittest` works, or use a `dbutils.widgets.dropdown("Mode", ...)` to switch Test/Normal runs. Failures show in the cell output.

> **Recap:** Factor logic into `df.transform(func)`-style functions; test with `assertSchemaEqual` (structure) + `assertDataFrameEqual` (data — **row order ignored by default**, floats compared with `rtol`/`atol`); run via pytest (`test_*.py`/`test_*`) against fake data, locally or via Databricks Connect.

---

## 9. The built-in interactive debugger (Python notebooks)

Databricks notebooks ship an **interactive debugger for Python only** — breakpoints, step-through, variable inspection. ([debugger](https://learn.microsoft.com/azure/databricks/notebooks/debugger))

**Requirements / enabling:**
- Compute: serverless, **Standard** access (DBR 14.3 LTS+), **Dedicated** (DBR 13.3 LTS+), or No-isolation-shared (DBR 13.3 LTS+).
- Enable: **Settings → Developer → Editor settings → "Python Notebook Interactive Debugger"** ON.

**Using it:**
- Click the gutter to set a breakpoint, then **Run → Debug cell** (or **Option/Alt + Shift + D**). You can also click **Debug** on a cell that errored.
- Toolbar / keys: **F8** next line · **F9** step into · **Shift+F9** step out.
- **Breakpoints stop *before* the line runs, not after.**
- **Variable explorer** (right pane) shows live variable values; on DBR 12.2 LTS+ Python values update as the cell runs. Local function vars are tagged `[local]`.
- **Debug console** evaluates Python at a breakpoint — but `display` is unsupported (use `df.show()`), and it **times out after 15 s** per evaluation; the session auto-ends after **30 min** idle.
- You can **step into functions defined in other workspace files** (needs notebook/file tabs enabled) — but **not** into Python libraries or other notebooks.

**The single most-tested debugger gotcha:** `breakpoint()` does **NOT** work in Databricks notebooks (IPython limitation). Use **`import pdb; pdb.set_trace()`** instead (requires DBR 11.3 LTS+). ([Python debugger](https://learn.microsoft.com/azure/databricks/languages/python#tutorials))

> **Recap:** Python-only interactive debugger; enable in Developer settings; breakpoints fire *before* the line; variable explorer + debug console (no `display`, 15 s eval timeout); can step into other *workspace files* but not libraries/notebooks; `breakpoint()` is broken — use `import pdb; pdb.set_trace()`.

---

## 10. Common exam traps

> ⚠️ **Trap box — the ones that flip an answer:**
>
> 1. **`==` in an If/else task is a STRING compare.** `12.0 == 12` → **false**. Use `>=`/`<=` for numeric logic.
> 2. **`assertDataFrameEqual` ignores row order by default** (`checkRowOrder=False`). Same rows, different order → passes. Floats need `rtol`/`atol` or trivial drift fails.
> 3. **High-memory notebook task raises REPL/driver Python memory only — NOT the Spark session.** It fixes local-Python OOM, not executor OOM.
> 4. **Disallow retries = uncheck "Enable serverless auto-optimization".** Auto-optimization *silently* retries (at-least-once); turn it off for non-idempotent / at-most-once jobs.
> 5. **A new cluster library isn't visible to an already-attached notebook** until a new session starts.
> 6. **`breakpoint()` doesn't work in notebooks** — use `import pdb; pdb.set_trace()`.
> 7. **Pandas UDF Series→Scalar has no partial aggregation** — whole group loaded into memory → can OOM on big groups.
> 8. **`mode: production` disables UI editing and requires `host`+`root_path`** (unless `run_as` is a service principal); `mode: development` silently prefixes names with `[dev <user>]` and pauses schedules.
> 9. **DABs version code *and* resource config; Git Folders version only code.** "Reproducible jobs+schedules across workspaces" → DABs.
> 10. **`bundle destroy` deletes resources, not the data/tables they created.** Side effects are manual cleanup.
> 11. **Resource YAML keys = the REST API create-payload fields** of that object. There's no separate schema — `validate` only *warns* on unknown keys.
> 12. **Use `generate` + `deployment bind`** to bring an existing job under a bundle without creating a duplicate.

---

## 11. Hands-on lab (your workspace, ~60–75 min)

Do these in order; they cover every gap above with the least clicking.

**Lab A — Build & deploy a minimal DAB (~25 min)**
1. Install/verify CLI: `databricks -v` (need 0.218.0+; 0.283.0+ for pipeline init). Auth: `databricks auth login --host <your-workspace-url>`.
2. `databricks bundle init default-python` → name `cert_lab`, **serverless = yes**, include sample Python package = **yes**, give it an existing UC catalog.
3. Inspect the generated tree: note `src/<pkg>/`, `tests/`, `resources/*.yml`, and the `artifacts` wheel block in `databricks.yml`.
4. `databricks bundle validate` → read the summary.
5. `databricks bundle deploy -t dev` → in **Jobs & Pipelines**, confirm the job is named **`[dev <you>] ...`** (proves dev-mode prefixing).
6. `databricks bundle run -t dev <job_name>` → open the printed Run URL.
7. `databricks bundle summary` to see the deployed path; finish with `databricks bundle destroy` (answer `y`).

**Lab B — Unit test with `assertDataFrameEqual` (~15 min)**
1. In the bundle's `src/<pkg>/`, add a `with_flags(df)` transform (copy §8).
2. In `tests/`, write `test_with_flags` using `assertSchemaEqual` + `assertDataFrameEqual` (copy §8).
3. Run `pytest tests/ -v` locally (or via the bundle: re-run `bundle deploy` and watch the `artifacts.build` step run pytest). Intentionally break the expected data → watch the `PySparkAssertionError` show the diff.

**Lab C — Pandas vs Python UDF (~10 min)**
1. In a serverless notebook, define a plain `@udf` `add_one` and a `@pandas_udf` Series→Series `multiply`.
2. Run both on `spark.range(1_000_000)`; eyeball the wall-clock gap. Open the **Spark UI** for the Python-UDF stage and find the Python-worker serialization time.

**Lab D — Control flow + config (~15 min)**
1. Build a 3-task job: a SQL/notebook task that sets a task value `bad_records`, an **If/else** task `{{tasks.t1.values.bad_records}} > 0`, and two branch tasks on `(true)`/`(false)`.
2. Add a **For each** task with Inputs `["a","b","c"]`, concurrency 2, a nested notebook reading `{{input}}`.
3. On a serverless task: open Environment pane → set **Memory: High**; then edit **Retries** and **uncheck** "Enable serverless auto-optimization" — observe both are config toggles, not code.

**Lab E — Debugger (~10 min)**
1. Settings → Developer → enable the Python debugger.
2. Set a gutter breakpoint, **Debug cell**, step with F8/F9, inspect a variable in the variable explorer.
3. Try `breakpoint()` (fails) then `import pdb; pdb.set_trace()` (works).

---

## 12. One-page recap table

| Topic | The fact that wins the question | Doc |
|---|---|---|
| `databricks.yml` | `bundle.name` required; identity = name+target+deployer; `resources` keys = REST create-payload fields | [settings](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/settings) |
| Deployment modes | `development` → `[dev <user>]` prefix + paused schedules + editable; `production` → no prefix, schedules on, UI editing locked, needs host+root_path | [modes](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/deployment-modes) |
| Lifecycle verbs | `validate` → `deploy -t` → `run -t <name>` → `destroy` (data survives); `generate`+`deployment bind` to adopt existing | [bundle commands](https://learn.microsoft.com/azure/databricks/dev-tools/cli/bundle-commands) |
| Project structure | logic in `src/<pkg>/`, tests in `tests/`, thin notebooks; `artifacts:{type:whl,build:pytest+bdist_wheel}` | [python-wheel](https://learn.microsoft.com/azure/databricks/dev-tools/bundles/python-wheel) |
| CI/CD | service principal (separate deploy vs run-as); DABs version code+config, Git Folders code-only | [ci-cd flows](https://learn.microsoft.com/azure/databricks/dev-tools/ci-cd/flows) |
| Library scope | notebook (`%pip`) / cluster / task / serverless; DBFS-root deprecated; new cluster lib needs new session | [libraries](https://learn.microsoft.com/azure/databricks/libraries/) |
| Library sources | PyPI, wheel (`.whl`), `requirements.txt` (`-r`), VCS (`git+`), UC volume, object storage | [notebook libs](https://learn.microsoft.com/azure/databricks/libraries/notebooks-python-libraries) |
| UDF performance | built-in/SQL > Scala > Pandas (Arrow, ~100×) > plain Python (row-at-a-time serialize) | [udf perf](https://learn.microsoft.com/azure/databricks/udf/#performance-considerations) |
| Pandas UDF shapes | Series→Series, Iterator[Series], Iterator[Tuple], Series→Scalar (no partial agg); batch=10,000 | [pandas](https://learn.microsoft.com/azure/databricks/udf/pandas) |
| If/else task | `==`/`!=` = string compare (`12.0==12` false); `>`/`<` numeric; fails if upstream disabled | [if-else](https://learn.microsoft.com/azure/databricks/jobs/if-else) |
| For each task | `{{input}}`/`{{input.<key>}}`; concurrency default 1; can't nest; 5,000-char Inputs / 48 KB taskvalue | [for-each](https://learn.microsoft.com/azure/databricks/jobs/for-each) |
| Run if | branch on upstream status: All succeeded / None failed / At least one failed / All done … | [run-if](https://learn.microsoft.com/azure/databricks/jobs/run-if) |
| High memory | Standard 16 GB / High 32 GB **REPL only** (not Spark session); notebook-task-only; higher DBU | [high memory](https://learn.microsoft.com/azure/databricks/compute/serverless/dependencies#use-high-memory-serverless-compute) |
| Disallow retries | uncheck "Enable serverless auto-optimization" → at-most-once for non-idempotent jobs | [disallow retries](https://learn.microsoft.com/azure/databricks/jobs/run-serverless-jobs#configure-serverless-compute-auto-optimization-to-disallow-retries) |
| `assertDataFrameEqual` | row order ignored by default (`checkRowOrder=False`); floats via `rtol`/`atol` | [pyspark.testing](https://spark.apache.org/docs/latest/api/python/reference/pyspark.testing.html) |
| `assertSchemaEqual` | structure-only; `ignoreNullable`/`ignoreColumnOrder`/`ignoreColumnName`/`ignoreColumnType` | [pyspark.testing](https://spark.apache.org/docs/latest/api/python/reference/pyspark.testing.html) |
| `DataFrame.transform` | `transform(func)` chains DataFrame→DataFrame functions → each unit-testable | [transform](https://learn.microsoft.com/azure/databricks/pyspark/reference/classes/dataframe/transform) |
| pytest | files `test_*.py`, funcs `test_*`; test fake data; local or Databricks Connect | [testing](https://learn.microsoft.com/azure/databricks/notebooks/testing) |
| Debugger | Python-only; breakpoint fires *before* line; `breakpoint()` broken → use `import pdb; pdb.set_trace()` | [debugger](https://learn.microsoft.com/azure/databricks/notebooks/debugger) |

*Grounded in current Databricks docs (learn.microsoft.com/azure/databricks + Apache Spark API), fetched 2026-06-18, against the official Nov-30-2025 exam objectives. "Declarative Automation Bundles" = "Databricks Asset Bundles" — same product, renamed.*
