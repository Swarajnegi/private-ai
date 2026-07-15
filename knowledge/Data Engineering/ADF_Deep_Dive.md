# Azure Data Factory — Deep Dive

> Doc-grounded learning guide (sources: current Microsoft Learn docs, verified 2026-06-30). Built for Swaraj — Azure DE who works on Azure Databricks + Synapse Link; bridged to Databricks-native concepts throughout.

> Each section was authored then adversarially fact-checked against live MS Learn docs; see **Appendix: Verification Notes** for corrections applied and residual uncertainties.


---

## 0. Orientation

Azure Data Factory (ADF — Microsoft's managed cloud ETL/ELT and data-integration orchestration service) is best understood not by reading its feature list but by following a single request through it. So before any concept, walk the **life of an ingestion request** — the same mental exercise you'd do tracing a row through a Lakeflow Job at Apollo Gen2.

### Life of an ingestion request

Imagine the business need: *"every morning, pull yesterday's orders from an on-prem SQL Server and land them in ADLS Gen2, copying only the rows that changed."* Here is the whole machine, end to end, in the order ADF actually executes it:

1. **A trigger fires.** A *tumbling-window trigger* wakes at 02:00 UTC and computes the slice boundaries `windowStartTime = 2026-06-29T00:00Z` / `windowEndTime = 2026-06-30T00:00Z`. It instantiates a **pipeline run** and pours those window variables into the pipeline's *parameters* (the trigger can't talk to activities directly — only parameters cross that boundary). Databricks analog: a Lakeflow Job schedule passing `{{job.trigger.time}}` into a notebook widget — except ADF gives you *gap-free backfill* of missed windows, which a cron schedule does not.
2. **The control plane plans.** ADF's regional, multi-tenant *service* reads the pipeline JSON, evaluates the `@`-expressions, and walks the activity DAG. It moves no bytes — it dispatches.
3. **A Lookup reads metadata.** `@activity('GetTables').output.value` returns the list of tables to ingest from a *control table* — not the data, just the instructions (keep it small; the per-activity payload caps at 896 KB).
4. **A ForEach fans out.** It binds `@item()` to each control row and runs the loop body once per table, up to `batchCount` (default 20, max 50) in parallel.
5. **A parameterized Copy moves the bytes.** This is the *only* step on the **data plane**. Because the source is on-prem, the copy runs on a **SHIR (Self-Hosted Integration Runtime — ADF software you install on a Windows VM inside your network)** which reaches the private SQL Server outbound-only (no inbound firewall hole), reads `WHERE LastModified > @old AND <= @new`, and writes Parquet.
6. **A stored procedure advances the watermark.** The new high-water mark is written back to SQL so tomorrow's run starts where today's ended.
7. **Monitoring records it.** The run shows up in the Monitor hub (retained 45 days) and — if you wired diagnostics — in a Log Analytics `ADFPipelineRun` table you can query in KQL.

Everything in this guide is one of those seven moving parts. The recurring lens that ties them together: **the control plane carries small, capped orchestration metadata; the data plane (the Integration Runtime) carries the actual bytes.** When a limit surprises you, ask "is this value crossing the control plane?"

### Where ADF sits: ADF vs Lakeflow Jobs vs Airflow/Dagster

You already orchestrate on Databricks and you're studying the modern stack, so anchor ADF against both:

| | **ADF** | **Lakeflow Jobs** (Databricks-native) | **Airflow / Dagster** |
|---|---|---|---|
| Definition style | **Declarative JSON**, GUI-first | YAML/UI; tasks as a DAG | **Imperative Python** (Airflow) / asset-graph (Dagster) |
| Native compute | Azure IR for Copy + ADF-managed Spark for Data Flow | Databricks Spark (serverless/classic) | **None** — pure orchestrators |
| Built-in data movement | **Yes** — Copy activity + 90+ connectors + SHIR hybrid story | No (you write the read/write in Spark) | No |
| Looping/branching | ForEach/Until/If/Switch, evaluated **at runtime**, on the metered control plane | for-each / if-else tasks | Python control flow at DAG-build time (Airflow) / asset deps (Dagster) |
| Data-awareness | Pipeline-level (passes pointers) | Task-level | **Dagster: asset/lineage-aware** |
| Sweet spot | Azure data movement + **hybrid on-prem via SHIR** + visual transforms | Orchestrating work that **already lives on Databricks** | Vendor-neutral, code-first, multi-system DAGs |

The crucial point: these **interoperate more than they compete.** Databricks' own guidance is to use **Lakeflow Jobs** when you're only orchestrating Databricks workloads, and reach for **ADF (or Airflow)** when you must orchestrate *beyond* Databricks. The canonical hybrid — and exactly the shape you'd build at Apollo Gen2 — is **ADF as the outer orchestrator that reaches the private/on-prem source via SHIR, lands raw data, then dispatches a Databricks Notebook activity** for the Spark transform. ADF's tradeoff vs. Airflow/Dagster is the classic one: far more managed connectors and a hybrid SHIR story you'd otherwise hand-build, in exchange for less programmability (no Python — just `@`-expression interpolation + ~100 built-in functions) and a GUI-rendered-JSON source of truth.

One more framing you'll feel on every page: ADF spreads configurability across **seven parameter scopes** and routes a value through **up to four declarative objects** (linked service → dataset → pipeline → activity) where Databricks would do it in one notebook hop. That indirection is the *point* — it's what lets one dataset and one linked service serve hundreds of pipelines. That metadata-driven reuse is the climax this guide builds toward.


---

## Contents

1. [ADF Architecture & Building Blocks](#1-adf-architecture-building-blocks)
2. [Integration Runtimes & On-Prem Connectivity (SHIR)](#2-integration-runtimes-on-prem-connectivity-shir)
3. [The Activity Catalog](#3-the-activity-catalog)
4. [Parameters, Variables, Expressions & Their Scopes](#4-parameters,-variables,-expressions-their-scopes)
5. [Dynamic / Metadata-Driven Pipelines](#5-dynamic-metadata-driven-pipelines)
6. [Schema Evolution & Schema Drift](#6-schema-evolution-schema-drift)
7. [Triggers, Monitoring & CI/CD](#7-triggers,-monitoring-cicd)
8. Capstone — End-to-End Metadata-Driven Ingestion Framework
9. Master Cheat-Sheet
10. Appendix — Verification Notes


---

## 1. ADF Architecture & Building Blocks

Azure Data Factory (ADF — Azure's managed cloud ETL/ELT and data-integration orchestration service) is, at its core, a **declarative orchestrator**. You describe *what* should happen as a graph of JSON-defined resources; ADF figures out *where and how* to run it. If you live in Databricks, the mental model to carry in: ADF is to a Lakeflow Job what a conductor is to the orchestra — it sequences, branches, retries, and parameterizes, but the heavy lifting (Spark transforms, notebook execution) usually happens on compute it *dispatches to*, not compute it *is*.

### The six building blocks and how they nest

ADF is composed of six top-level concepts. They nest in a strict containment hierarchy, and understanding that hierarchy is the whole game.

| Concept | What it is | Databricks analogy |
|---|---|---|
| **Pipeline** | A logical grouping of activities that together perform a task; the unit you deploy, schedule, and monitor. | A **Lakeflow Job** |
| **Activity** | A single processing step inside a pipeline (copy, run-notebook, loop, branch). | A **task** within a job |
| **Dataset** | A *named view* of data — points at a table/file/folder; describes structure, not connection. | The path/table argument you'd pass a task (no direct equivalent — Databricks reads paths inline) |
| **Linked service** | A connection definition (connection string + auth) to a data store *or* a compute resource. | A **connection** / **secret scope** + cluster definition combined |
| **Integration runtime (IR)** | The compute that actually moves/transforms data or dispatches activities. | The **cluster** (classic or serverless) the task runs on |
| **Trigger** | The condition that kicks off a pipeline run. | The job's **trigger** (schedule/file-arrival) |

(Triggers, pipeline runs, parameters, and variables round out the core object model alongside these six.)

**The nesting, concretely:**

```
Data Factory (the resource)
└── Trigger ──fires──> Pipeline
                        └── Activity (e.g. Copy)
                              ├── input  Dataset ──refers to──> Linked Service ──runs on──> Integration Runtime
                              └── output Dataset ──refers to──> Linked Service
```

- **What / Mechanism:** A **trigger** instantiates a **pipeline run**. The pipeline contains **activities**. A Copy activity references **datasets** for source and sink. Each dataset references exactly one **linked service** (the connection). The linked service is bound to (or auto-resolves) an **integration runtime** that supplies the compute. Microsoft's own ordering rule: *you must create the linked service before the dataset*, because the dataset is meaningless without a connection to hang off of.
- **Example — the canonical "copy Blob → SQL" stack** requires two linked services (Azure Blob Storage, Azure SQL Database), two datasets (a DelimitedText dataset over the blob, an AzureSqlTable dataset over the table), and one Copy activity wiring them together inside one pipeline.
- **Gotcha:** A dataset is a *strongly-typed, reusable parameter* — it carries structure and format settings (delimiter, compression), NOT the connection. New engineers conflate "dataset = the data." It is a pointer + schema hint, nothing more.

> **Takeaway:** Linked service = the connection; dataset = the structure on top of that connection; activity = the verb; pipeline = the sentence; trigger = what makes you say it.

### Everything is JSON — including your expressions

Every ADF resource is an ARM (Azure Resource Manager) JSON document. The visual Studio canvas is a thin editor over JSON; CI/CD ships the JSON. This matters because (a) it's diffable in Git, and (b) the **expression language** is embedded *inside* the JSON as strings.

A minimal pipeline with a parameter and a Copy activity:

```json
{
  "name": "copyPipeline",
  "properties": {
    "parameters": {
      "sourceContainer": { "type": "String" },
      "runDate":         { "type": "String", "defaultValue": "2026-06-30" }
    },
    "activities": [
      {
        "name": "CopyBlobToSql",
        "type": "Copy",
        "inputs":  [ { "referenceName": "BlobInput",  "type": "DatasetReference",
                       "parameters": { "container": "@pipeline().parameters.sourceContainer" } } ],
        "outputs": [ { "referenceName": "SqlOutput",  "type": "DatasetReference" } ],
        "typeProperties": {
          "source": { "type": "DelimitedTextSource" },
          "sink":   { "type": "AzureSqlSink" }
        }
      }
    ]
  }
}
```

**The expression language** — every dynamic value starts with `@`, and string-interpolation uses `@{...}` inside a larger string:

- `@pipeline().parameters.sourceContainer` — read a pipeline parameter (read-only, set at run start; like a `dbutils.widgets.get()` value that *cannot* be reassigned mid-run). Parameter data types: String, Int, Float, Bool, Array, Object, SecureString.
- `@variables('flag')` — read a pipeline variable (mutable via the **Set Variable** activity; this is your `dbutils.widgets` *plus* a mutable local).
- `@item()` — the current element inside a **ForEach** loop (like the loop variable in a Databricks `for-each` task).
- `@activity('LookupTables').output.value` — the output of a prior activity. Deep access uses `[]` for sub-fields that are themselves expressions: `@activity('X').output.subfield1[pipeline().parameters.idx].subfield4`.
- `@concat('Test_', formatDateTime(utcnow(), 'yyyy-MM-dd'))` — a typical dynamic filename. (Note: a single expression is capped at 8,192 characters.)

- **No invisible operations — string interpolation auto-escapes:** When you type the JSON literal `{ "type": "@{if(equals(1,2),'Blob','Table')}", "name": "@{toUpper('myData')}" }` into the dynamic-content editor, ADF silently rewrites it on save into an escaped single expression string (`"{ \n \"type\": \"@{...}\", ... }"`) and evaluates it to `{ "type": "Table", "name": "MYDATA" }` at runtime. You don't see the escaping happen; the editor does it for you, which is why hand-editing the JSON later sometimes looks mangled.
- **No invisible operations — Execute Pipeline coerces arrays:** A documented gotcha is that the Execute Pipeline activity passes an **array parameter to a child pipeline as a string**. If the child expects a real array, you must re-parse it. ADF does not warn you.
- **Gotcha — the expression builder cannot validate references.** `@activity('Execute Pipeline1').output.pipelineReturnValue.keyName` is checked at *runtime only*. If `keyName` is absent in the child's payload, the run fails with "the expression can't be evaluated." Contrast Databricks, where a missing `dbutils.notebook.exit` key surfaces as a Python error you can catch.

> **Takeaway:** Treat the JSON as the source of truth and the canvas as a renderer. The `@` expression layer is your only dynamic logic — there's no Python; everything is interpolation + ~100 built-in functions.

### Control plane vs data plane

This split is the single most useful architectural lens, and it directly explains the limits below.

- **Control plane** = the ADF *service* itself: it stores your JSON, schedules triggers, orchestrates the activity DAG, evaluates expressions, manages state, and dispatches work. It is **regional, multi-tenant, and you never see its compute**. Activity *dispatch* is described by Microsoft as "a lightweight operation."
- **Data plane** = where bytes actually move and transform: the **Integration Runtime**. Copy activities, Data Flow Spark clusters, and SHIR file transfers live here.

- **Mechanism — why activity payloads are tiny:** Because the control plane carries activity config (including dataset + linked-service JSON) through its orchestration fabric, the **per-activity payload is capped at 896 KB** (an Azure subscription service limit). Pass a large Lookup result *into* a downstream activity's parameter and you blow this limit. The fix is to keep big data on the data plane (write to storage, pass a *pointer*), never marshal it through control-plane parameters.
- **Mechanism — why Lookup/Web outputs are capped:** Activity *outputs* round-trip through the control plane, so **Lookup returns at most 5,000 rows / 4 MB / 24 hours**, and **Web activity output is capped at 4 MB** (error code 2001). These aren't data limits — they're control-plane marshaling limits.
- **Gotcha:** The Databricks Delta Lake connector's Lookup caps at **1,000 rows**, not 5,000 — a connector-specific override of the general limit. If you `Lookup` a Databricks Delta table expecting 5,000 rows, you silently get the first 1,000.

> **Takeaway:** Orchestration metadata flows through the control plane (small, capped); real data flows through the data plane (the IR, scalable). When a limit surprises you, ask "is this value crossing the control plane?"

### Integration Runtimes — the data plane in detail

The IR is the bridge between an activity and a linked service; it supplies the compute and determines the network reach. There are exactly **three types**.

| IR type | What runs on it | Managed compute? | On-prem / private-network access | Closest you've used |
|---|---|---|---|---|
| **Azure IR** | Data movement (Copy), Mapping Data Flow Spark, activity dispatch — over public endpoints (or via Managed VNet for Private Link) | Yes (serverless, autoscale) | No (unless Managed VNet + Private Endpoint) | Databricks **serverless** compute |
| **Self-Hosted IR (SHIR)** | Data movement + activity dispatch against on-prem or VNet-locked sources; can host custom drivers | No — you install it on a Windows VM/box | Yes (the whole point) | A self-managed VM gateway; no Databricks equivalent for cloud-native work |
| **Azure-SSIS IR** | Lift-and-shift execution of SQL Server Integration Services packages | Yes (a managed cluster of Azure VMs) | Via VNet injection | SSIS legacy — irrelevant to a modern lakehouse shop |

- **What / Mechanism — SHIR (Self-Hosted Integration Runtime):** A piece of software you install on a machine inside your network. It registers outbound to ADF (HTTPS over port 443) and pulls work, so you never open inbound firewall ports. A single copy activity can **scale out across up to 4 SHIR nodes** (the documented maximum on the ADF limits page), partitioning its file set across them; you can also scale up the box. DIUs do **not** apply to SHIR (they're an Azure-IR-only concept).
- **What / Mechanism — DIU (Data Integration Unit):** A bundled measure of CPU+memory+network for a cloud-to-cloud Copy activity on **Azure IR only**. The allowed range is **4 to 256**; if you don't specify a value or choose "Auto," the service picks the optimal DIU based on your source-sink pair and data pattern. Loading petabytes Gen1→Gen2, Microsoft documents sustained throughput of 2 GBps and higher by maxing DIUs and parallel copies.
- **Gotcha — Azure IR network egress differs by product:** In **Data Factory**, Azure IR opens **all ports for outbound** public communication; in **Synapse**, the Managed VNet lets you restrict outbound. Same IR concept, different default blast radius.
- **Gotcha — SHIR is not shareable into Synapse or Fabric:** A SHIR "can only be shared between data factories. It can't be shared across Synapse workspaces or between a data factory and a Synapse workspace." If your shop is consolidating onto Synapse pipelines, you re-provision SHIRs. (A SHIR can be shared with many data factories — up to 120 — but never across the product boundary.)

> **Takeaway:** Azure IR for cloud-to-cloud at scale (tune DIUs); SHIR when the data is behind a firewall or needs a custom driver (scale to 4 nodes); Azure-SSIS only if you're dragging legacy SSIS along.

### Activities: the three families, and the loop/branch limits

ADF groups activities into three families. Knowing which family an activity belongs to tells you which plane it stresses.

| Family | Examples | Where it runs |
|---|---|---|
| **Data movement** | Copy | Azure IR or SHIR (data plane) |
| **Data transformation** | Mapping Data Flow, Databricks Notebook/Jar/Python, Azure Function, Stored Procedure, Synapse Notebook, HDInsight | Dispatched to external compute (or ADF-managed Spark for Data Flow) |
| **Control flow** | ForEach, Until, If Condition, Switch, Lookup, Get Metadata, Set Variable, Execute Pipeline, Wait, Web, Webhook, Fail, Filter, Validation | Control plane |

**Hard limits you will hit (verified, 2026):**

- **120 activities per pipeline** — this is a *hard limit* (Microsoft's limits table lists both the default and the maximum as 120; it is **not** raisable via support), and it **includes inner activities inside containers** like ForEach/Until. A loop body of 10 activities iterating doesn't multiply against this; the 10 definitions count, not the iterations.
- **ForEach** parallelism: `batchCount` controls concurrency, **default 20, maximum 50**; the collection itself can hold **up to 100,000 items**. Internally ADF builds `batchCount` queues, each running sequentially, queues running in parallel — and **queues are pre-created with no runtime rebalancing**, so an uneven workload can leave some queues idle while others churn (raising the degree of parallelism doesn't always raise throughput — Microsoft notes the for-each activity "will not always execute at" the batchCount value).
- **ForEach cannot nest** inside another ForEach (or an Until). Workaround: a two-level pipeline — outer ForEach calls Execute Pipeline, inner pipeline holds the second loop.
- **Set Variable inside a parallel ForEach is unsafe** — variables are pipeline-global, not loop-scoped, so they aren't thread-safe. This is the *exact* foot-gun a Databricks engineer expects to NOT exist (Spark closures are isolated); here it does. Use a sequential ForEach, or push the variable handling into the child pipeline via Execute Pipeline.

**Execution trace — Lookup → ForEach → Copy (the bulk-copy pattern):**

```
1. Lookup 'GetTables'  (firstRowOnly=false) → output: { "count": 2,
     "value": [ {"schema":"dbo","table":"Orders"}, {"schema":"dbo","table":"Items"} ] }
2. ForEach  items = @activity('GetTables').output.value   (isSequential=false, batchCount=2)
     iteration A: @item() = {"schema":"dbo","table":"Orders"}
     iteration B: @item() = {"schema":"dbo","table":"Items"}
3. Copy (inside loop): source query = @concat('SELECT * FROM ',
                                       item().schema, '.', item().table)
```

- **Gotcha:** With `firstRowOnly=true` (the default) the Lookup output is under `output.firstRow`; with `false` it's `output.value` (an array) plus `output.count`. Wire the wrong one into ForEach `items` and you either iterate a single object's keys or get nothing.

> **Takeaway:** Control-flow activities are your `if`/`for`/`call`, but they run on the metered control plane with real ceilings (120 activities, 50-wide ForEach, no nesting, no parallel-safe variables). Push data-heavy or deeply-nested logic into child pipelines or external compute.

### Mapping Data Flow vs Copy vs external compute (Databricks/Functions)

This is the choice you'll make on every transform. Three paths, very different cost/control profiles.

| | **Copy activity** | **Mapping Data Flow** | **External compute (Databricks/Function)** |
|---|---|---|---|
| Purpose | Move bytes, light schema mapping | Visual, code-free row/column transforms at scale | Arbitrary transform in *your* code |
| Engine | Azure IR / SHIR | **ADF-managed Apache Spark**, spun up/down per run | **Your** Databricks cluster / Function app |
| You write | Mappings in the UI | A visual graph (source→transforms→sink) | Notebook/JAR/Python/C# |
| Warm-up | None (fast) | **5–7 min cluster warm-up** (turn on Debug Mode first) | Cold cluster start (or instant if serverless/warm) |
| Best for | Ingestion, format conversion | Joins/aggregates/derived columns without code | Complex logic, ML, reusing existing Databricks code |

- **What / Mechanism — Mapping Data Flow:** A no-code transform that ADF **compiles to Spark code** and executes on a Spark cluster it manages for you ("you never have to manage or maintain clusters"). The visual graph (source, derived column, join, aggregate, alter-row, sink) becomes a "data flow script" under the hood. Update methods (insert/update/upsert/delete) require an **Alter Row** transformation to tag rows plus a **key column** — this is ADF's equivalent of a Databricks `MERGE`, except you express the merge keys and row policies in the GUI rather than SQL.
- **What / Mechanism — Databricks activity:** You orchestrate a Databricks **Notebook / Jar / Python / Job** via an **Azure Databricks linked service**. Pass inputs with `baseParameters` (the ADF-side analog of `dbutils.widgets`), and return a value with `dbutils.notebook.exit("returnValue")` — readable downstream as `@{activity('NB').output.runOutput}`, **with a 2 MB return-size cap**. JSON return values are accessible as `.output.runOutput.PropertyName`.
- **Gotcha — Data Flow Debug Mode bills a live cluster.** The debug slider warms a Spark cluster (5–7 min; default debug IR is an 8-core cluster with a 60-minute time-to-live) that stays billed while on. Engineers leave it on and pay idle Spark. (Databricks teaches you the same lesson with all-purpose clusters — same discipline applies.)
- **Gotcha — Power Query / Wrangling Data Flow is ADF-only, not Synapse.** If you've built code-free Power Query transforms, they don't port to Synapse pipelines.

> **Takeaway:** Copy to move; Mapping Data Flow for code-free transforms you don't want to maintain a cluster for; Databricks activity when the logic belongs in Spark/your codebase (your Apollo Gen2 muscle memory) — and remember Mapping Data Flow's MERGE is Alter Row + key columns, not SQL.

### Triggers: four kinds, two behavioral models

A trigger decides *when* a pipeline runs. There are four types, but the behavioral fork that matters is **fire-and-forget (Schedule)** vs **stateful, waits-for-completion (Tumbling Window)**.

| Trigger | Fires on | Key behavior |
|---|---|---|
| **Schedule** | Wall-clock calendar (minutes/hours/weekDays/monthDays) | Fire-and-forget; **many-to-many** (many triggers↔many pipelines); no backfill, no retry |
| **Tumbling Window (TW)** | Fixed-size, non-overlapping contiguous time windows from a start time | Stateful; **one-to-one**; **backfill** past windows; **retry** policy; concurrency 1–50 |
| **Storage event** | Blob created/deleted in a storage account (via Event Grid) | Event-driven; the file-arrival pattern |
| **Custom event** | Custom Event Grid topic message; filter on `subjectBeginsWith`/`eventType` | Parses a freeform `data` payload into pipeline params |

- **Mechanism — Tumbling Window is the one Databricks doesn't give you cleanly.** TW exposes `@trigger().outputs.windowStartTime` and `windowEndTime` (e.g. for the 1–2 AM window, `2017-09-01T01:00:00Z`→`…T02:00:00Z`), and it **waits for the triggered run to finish** — if the run is cancelled, the TW run is marked cancelled. This makes it ideal for gapless, replayable, time-sliced ingestion (process "yesterday's slice," backfill last month deterministically). A Databricks scheduled Job is closer to the **Schedule** trigger (fire-and-forget); reliable backfill of historical windows is something you'd hand-build in Databricks. (TW retry defaults to 0 retries; backfill runs execute oldest-to-newest, honoring the concurrency limit.)
- **Mechanism — Storage event trigger** uses Event Grid to subscribe to Blob events. This is the same idea as Databricks **Auto Loader** file-notification mode — but ADF's storage-event trigger starts an *orchestration*, whereas Auto Loader is a *streaming read inside* a notebook. ADF reacts at the pipeline level; Auto Loader reacts at the dataframe level.
- **Gotcha — restarting an event trigger replays history.** "If you stop and start an event-based trigger, it resumes [the] old trigger pattern which may result in unwanted trigger of the pipeline." Microsoft's guidance: delete and recreate to start fresh.
- **Example — custom-event parameterization:** `@triggerBody().event.data.fileName` parses the Event Grid payload into a parameter. If the referenced key is missing, the trigger run fails ("the expression can't be evaluated because the keyName property doesn't exist") and **no pipeline run is fired at all**.

> **Takeaway:** Schedule = cron-style fire-and-forget; Tumbling Window = stateful, backfillable, retrying, 1:1 (your time-slice workhorse); Storage/Custom event = reactive. TW backfill is ADF's standout feature versus a plain Databricks scheduled job.

### 2026 product reality: ADF vs Synapse pipelines vs Fabric Data Factory

This is the part most tutorials get wrong because the landscape moved. As of 2026, here is the live situation, straight from Microsoft Learn:

- **Standalone Azure Data Factory (PaaS)** — still GA, still supported, still receiving connectors. The docs now banner it with: *"Data Factory in Microsoft Fabric is the next generation of Azure Data Factory… If you're new to data integration, start with Fabric Data Factory."*
- **Azure Synapse pipelines** — the *same engine* as ADF embedded inside a Synapse workspace ("pipelines also implement Azure Data Factory within Azure Synapse"). It is a **feature subset**, not a superset. Differences (verified against Microsoft's ADF-vs-Synapse comparison table):

  | Feature | ADF | Synapse pipelines |
  |---|---|---|
  | Global parameters | ✅ | ❌ |
  | Power Query / Wrangling Data Flow | ✅ | ❌ |
  | Integration Runtime sharing | ✅ (across factories) | ❌ |
  | Cross-region IR for Data Flows | ✅ | ❌ |
  | Azure-SSIS IR | ✅ | ❌ (Synapse pipelines support only Azure or self-hosted IRs) |
  | Deploy via ARM templates | ✅ | ❌ (export/import JSON manually) |
  | Spark-job monitoring for Data Flow | ❌ | ✅ (Synapse Spark pools) |

- **Microsoft Fabric Data Factory (SaaS)** — explicitly **"the next generation of Azure Data Factory, with a simpler architecture, built-in AI, and new features."** It builds on the ADF PaaS engine but adds: native OneLake/Lakehouse/Warehouse integration, **Dataflow Gen2** (the successor to Mapping Data Flow / Power Query), built-in CI/CD via deployment pipelines (no external Git required), Copilot, and Teams/Outlook activities. Microsoft maintains **two separate roadmaps** and *does not backport* Fabric features into ADF/Synapse.

- **What's converging:** There is now a built-in, assessment-first **"Migrate to Fabric (Preview)"** experience inside the ADF authoring canvas. It categorizes each pipeline/activity as **Ready / Needs review / Coming soon / Not compatible**, lets you **mount** an existing ADF into a Fabric workspace for side-by-side review (a read-only snapshot — mounting alone migrates nothing), and migrates incrementally. Migration nuances to know:
  - **Global parameters are *not* migrated automatically** — neither the built-in upgrade nor the PowerShell tool moves them; you recreate them manually as Fabric **variable libraries** and rewrite `@globalParameters(...)` references to `@pipeline.libraryVariables.<name>`.
  - **Linked services map to Fabric connections** (and parameterized/dynamic linked services don't migrate — each permutation must become a separate connection).
  - **Triggers arrive disabled:** *schedule* triggers migrate automatically but disabled (you re-enable them); all other trigger types must be manually reconfigured — and **custom event triggers can't be migrated at all** (storage event support is "coming soon"; tumbling window becomes Fabric's interval-based scheduling, with watermark/backfill workloads requiring redesign).
  - Migrated pipelines are renamed `<SourceFactory>_<PipelineName>` to enforce workspace-unique names (a same-named pipeline is skipped).

- **What a learner should target in 2026:** Learn the **concepts** here on **standalone ADF** — it has the most complete docs, the GA tooling, ARM-based CI/CD, and every concept transfers 1:1 to Synapse (subset) and largely to Fabric (the engine and JSON shape are shared, though triggers, some connectors, and parameterization differ). But know the *strategic* direction is Fabric: if your org is greenfield or already on Fabric capacity, build new work in Fabric Data Factory. For a Synapse-Link/Databricks shop like Apollo Gen2, the pragmatic path is "author and reason in ADF, expect to mount-and-migrate to Fabric."

> **Takeaway:** ADF (PaaS) = learn here, fully supported. Synapse pipelines = same engine, fewer features. Fabric Data Factory = the SaaS future Microsoft is steering everyone toward. Concepts are portable; tooling and roadmap favor Fabric.

### Orchestrator positioning: ADF vs Lakeflow Jobs vs Airflow/Dagster

Where does ADF sit in the modern orchestration zoo you're studying?

| | **ADF** | **Lakeflow Jobs** | **Airflow / Dagster** |
|---|---|---|---|
| Definition style | **Declarative JSON** (GUI-first) | YAML/UI; tasks form a DAG | **Imperative Python** (Airflow) / asset-graph Python (Dagster) |
| Native compute | Azure IR (Copy) + ADF-managed Spark (Data Flow) | Databricks Spark (serverless or classic) | None — pure orchestrators; dispatch everywhere |
| Sweet spot | Azure data movement + hybrid (on-prem via SHIR) + visual transforms | Orchestrating workloads **that already live on Databricks** | Vendor-neutral, code-first, multi-system DAGs |
| Looping/branching | ForEach/Until/If/Switch (control plane, capped) | for-each / if-else tasks (visual) | Python control flow + dynamic task mapping (Airflow) / asset deps (Dagster) |
| Data-awareness | Pipeline-level (passes pointers) | Task-level | Airflow: task-level; **Dagster: asset/lineage-aware** |

- **Mechanism — they interoperate, not just compete.** Databricks' own guidance: use **Lakeflow Jobs** for orchestration whenever possible if you are only orchestrating workloads on Azure Databricks; use **ADF (or Airflow)** when you need to orchestrate **beyond** Databricks. The standard hybrid is ADF (or Airflow) as the *outer* orchestrator calling a Databricks Notebook/Job activity for the Spark step — which is exactly the shape you'd build at Apollo Gen2. (Lakeflow Jobs itself lists ADF as a standard external-system integration.)
- **Lakeflow concepts map cleanly to ADF:** Lakeflow **Job → Task → Trigger** mirrors ADF **Pipeline → Activity → Trigger**; both render tasks as a DAG; both support if/else and for-each. The difference is Lakeflow tasks are Databricks-native (notebook, **pipeline task** running a Lakeflow Spark Declarative Pipeline — the renamed DLT/SDP) while ADF activities dispatch broadly.
- **Where Airflow/Dagster differ fundamentally:** They're **code-first** — your DAG is Python you unit-test and version like any code, with no GUI source-of-truth and no managed data-movement engine (no built-in "Copy activity" or DIUs). **Dagster** goes further by being **asset/lineage-centric** (you declare data assets and their dependencies, not just task ordering) — closer to dbt's model than to ADF's task-graph. ADF's tradeoff is the opposite: less programmability, far more managed connectors (90+) and a hybrid SHIR story Airflow/Dagster make you build yourself.

> **Takeaway:** ADF is a *managed, declarative, Azure-centric* orchestrator with a built-in data-movement engine; Lakeflow Jobs is the *Databricks-native* orchestrator (use it when work is all on Databricks); Airflow/Dagster are *code-first, vendor-neutral* orchestrators with no native compute (Dagster adds asset-lineage). In practice you compose them — ADF/Airflow outside, Databricks doing the Spark inside.


---

## 2. Integration Runtimes & On-Prem Connectivity (SHIR)

An **Integration Runtime (IR — the compute substrate ADF uses to actually move/transform data and dispatch work)** is the single most misunderstood piece of ADF for someone coming from Databricks. In Databricks, "where does this run?" has one answer: a cluster (or serverless compute) you attached to the job. In ADF the pipeline definition is just metadata stored in the factory's region; the *execution* happens on an IR you bind indirectly through **linked services** (a linked service = ADF's connection object to a data store/compute, the rough analog of a Unity Catalog connection + a `dbutils.secrets`-backed credential). The IR is the bridge between an **activity** (the verb) and a **linked service** (the noun). Get the IR wrong and your pipeline either can't reach the data, leaks it across regions, or costs 5x what it should.

There are exactly three IR types. Everything in this section hangs off this table.

| IR type | Runs where | Does | On-prem / private-network reach | Synapse support |
|---|---|---|---|---|
| **Azure IR** | Microsoft-managed serverless compute in an Azure region | Data movement (cloud↔cloud), Data Flow (Spark), activity dispatch | Only via **managed VNet + managed private endpoints** | Yes |
| **Self-Hosted IR (SHIR)** | A Windows machine *you* run, inside your network | Data movement (cloud↔private), activity dispatch | Yes — this is its whole reason to exist | Yes |
| **Azure-SSIS IR** | Microsoft-managed cluster of Azure VMs | Natively executes lift-and-shifted SSIS packages | Via VNet injection | No (ADF only) |

Takeaway: **Azure IR for cloud-to-cloud, SHIR for anything behind a firewall, Azure-SSIS IR only if you're carrying legacy SSIS `.dtsx` packages.**

### Azure IR — the serverless default (auto-resolve vs. fixed region)

- **What:** A fully managed, serverless compute pool in Azure. No VMs to provision, patch, or scale — you pay only during actual utilization. It powers three distinct things: copy between cloud stores, Data Flow Spark execution, and lightweight activity dispatch (e.g. firing a Databricks Notebook activity).
- **Mechanism — auto-resolve (the default):** When you don't pin a region, the Azure IR is "AutoResolve." For a **copy activity**, ADF makes a *best-effort* attempt to detect the **sink** data store's region and runs the copy on an IR in that same region (or the closest one in the same geography); if the sink region isn't detectable, it falls back to the **factory's** region. This is an invisible operation worth calling out: a factory in East US copying to a Blob account in West US will silently execute the copy in **West US** if detection succeeds — but copying to Salesforce (region undetectable) runs in **East US**. For Lookup/GetMetadata/Delete, external-activity dispatch, and Data Flow, AutoResolve always uses the **factory's region**, not the sink's. (Note: if you enable Managed VNet *with* AutoResolve, even copy runs in the factory's region — the managed-VNet Azure IR can't auto-resolve to the sink region.)
- **Gotcha (data residency):** AutoResolve's "best effort" is not a compliance guarantee. If you have data-residency rules ("data must not leave UK South"), do **not** rely on AutoResolve — explicitly create a region-pinned Azure IR and point the linked service at it via `connectVia`:

```json
// Linked service pinned to a UK South Azure IR for residency
{
  "name": "UkBlobLinkedService",
  "properties": {
    "type": "AzureBlobStorage",
    "typeProperties": { "connectionString": "..." },
    "connectVia": { "referenceName": "AzureIR_UKSouth", "type": "IntegrationRuntimeReference" }
  }
}
```

- **Databricks bridge:** AutoResolve is conceptually like Databricks serverless ("just run it, I won't manage compute"), but the *region inference* has no Databricks equivalent — a Lakeflow Job runs in your workspace's region, full stop. The closest analog to region-pinning an IR is choosing your workspace/cluster region deliberately.

Takeaway: **AutoResolve is convenient but region-fuzzy; pin the region whenever residency, latency, or egress cost matters.**

#### Managed VNet IR + managed private endpoints

By default an Azure IR talks to data stores over **public** endpoints. To make a serverless Azure IR reach into private networking without you running any infrastructure, you enable a **managed virtual network (managed VNet)** on the factory and create **managed private endpoints**.

- **What:** A managed private endpoint is a private endpoint created *inside ADF's managed VNet* (a VNet that lives in a Microsoft subscription, not yours) that establishes a private link to a target Azure resource. Traffic between the IR and the data store then traverses the **Microsoft backbone**, never the public internet — this is the data-exfiltration defense.
- **Mechanism — the approval handshake:** When you create a managed private endpoint, the target resource's private-endpoint connection enters a **Pending** state and an approval workflow fires. The owner of the *target* resource must **approve** it before any traffic flows. Only an **Approved** managed private endpoint can send traffic. This is a real operational gate, not a formality — a copy will fail until approval lands.
- **Gotcha:** ADF's managed VNet and its private endpoints both live in a Microsoft subscription, so you can't peer your own customer VNet into it, and **custom DNS is not supported** inside it. You can't tweak its NSG rules either — it's Microsoft-managed. Outbound through the *public* endpoint from a managed VNet has **all ports opened** (this is the documented ADF behavior; Synapse's managed VNet can instead restrict outbound — a real product difference).
- **On-prem via managed VNet:** You *can* reach an on-prem SQL Server from a managed-VNet Azure IR, but only by standing up an Azure **Private Link Service** behind an internal Standard Load Balancer that fronts your on-prem source (reached over ExpressRoute/VPN). That's a heavy build. For most on-prem ingestion the answer is SHIR, below.

Takeaway: **Managed VNet IR = serverless Azure IR with private-link reach to Azure PaaS; great for "no public traffic to Storage/Synapse/Cosmos," but it is not your primary on-prem tool.**

### Self-Hosted IR (SHIR) — the on-prem workhorse (DEEP)

This is the IR you will actually install and babysit. **SHIR (Self-Hosted Integration Runtime — ADF software you run on a Windows machine inside your own network)** is what lets ADF copy from a SQL Server, Oracle box, file share, or SAP system that has no public endpoint.

#### The line-of-sight + outbound-only model (why security teams approve it)

- **What:** You install SHIR on a VM/host that has **network line-of-sight** to the on-prem source (can resolve and TCP-connect to it). The source itself stays completely private.
- **Mechanism (no inbound ports):** SHIR makes **outbound-only** HTTP/HTTPS connections. ADF never connects *in* to your network. The control channel rides a shared **Azure Relay** connection (think of it as a cloud message bus the SHIR polls); ADF queues a job + any credentials, and the SHIR **polls** the queue and pulls work. Data then moves directly from SHIR to the cloud store over a secure HTTPS channel. Concretely, at the corporate firewall you open **outbound 443** to:
  - `*.servicebus.windows.net` (Azure Relay — interactive authoring; skippable if "self-contained interactive authoring" is enabled)
  - `{datafactory}.{region}.datafactory.azure.net` (control connection to ADF)
  - `download.microsoft.com` (auto-update; skippable if disabled)
  - your Key Vault URL (if creds live there)
  
  No inbound rule, ever. (NSG note from the docs: Azure Relay has no service tag, so use the `AzureCloud`/`Internet` tag for Relay traffic and `DataFactoryManagement` for the ADF control connection.)
- **Gotcha — the SQL sink port:** Copying *to* Azure SQL DB / Synapse from SHIR wants outbound **1433**. If your firewall blocks 1433, use **staged copy** (SHIR pushes to a Blob staging area over 443, then the service loads from staging) so you only need 443. This is a classic exam-and-real-life trap.

#### Install footprint and prerequisites

- **Windows only**, **64-bit** (the 32-bit installer doesn't exist for production). Supported: Windows 10/11, Server 2016/2019/2022/2025. **Not** on a domain controller.
- **.NET Framework 4.7.2+** required.
- **Java runtime** is a *separate* dependency you must install if you read/write **Parquet, ORC, or Avro** (and you're not copying the files as-is) — file creation happens on the SHIR host via Java. The current docs require **64-bit JRE 8**, a JDK (currently JDK 23), or **OpenJDK / Microsoft Build of OpenJDK**, with `JAVA_HOME` set to the install folder (ORC additionally needs the Visual C++ 2010 Redistributable). This silently bites people: a copy that worked with CSV fails on Parquet with a Java error until a supported Java runtime is present.
- Recommended minimum host: **4 cores / 8 GB RAM / 80 GB disk**, and **disable hibernation** (a hibernating host = an offline SHIR = failed jobs).
- The Windows service runs as **`NT SERVICE\DIAHostService`**, which needs "Log on as a service" rights — and that same account needs read/execute on any third-party driver folder (e.g. the SAP HANA ODBC driver).

#### Credential handling

- **Two storage modes:** (1) **Azure Key Vault** (recommended) — the SHIR fetches secrets directly from Key Vault, sidestepping cross-node sync problems; or (2) **local** — credentials are encrypted with **Windows DPAPI (Data Protection API)** and stored on the SHIR machine.
- **Mechanism — multi-node credential sync:** With local creds and multiple nodes, each node holds its own DPAPI-encrypted copy, version-stamped; all nodes must carry the **same version number** to operate as one logical IR. Node-to-node state/credential sync (and PowerShell-set creds from another box) is gated by enabling **Remote access to intranet** (optionally hardened with a TLS/SSL cert). Data *in transit* from SHIR to other stores is always encrypted regardless of that cert.
- **Gotcha:** If the host crashes and you didn't back up creds (`dmgcmd -GenerateBackupFile`), pipelines break until you re-push credentials by re-editing each linked service. Back up the node.
- **Databricks bridge:** Key Vault-backed creds map almost 1:1 to a Databricks **secret scope** backed by Key Vault. The DPAPI-local mode has no Databricks equivalent — Databricks never stores your source credentials on a worker node the way local-mode SHIR does.

#### High availability and scalability (up to 4 nodes)

- **What:** A single *logical* SHIR can span up to **four physical nodes** (machines). This removes the single-point-of-failure and increases throughput.
- **Mechanism — multiple nodes, same key:** You add a node by installing SHIR on another machine and registering it with the **same authentication key** (no new IR object). The docs describe this as **active-active mode**; in practice ADF talks to the cluster as one logical IR and work is distributed across the nodes, and a single large file-based copy can be **partitioned across all nodes** for parallelism.
- **Scale-up vs scale-out:** *Scale up* = raise the **concurrent-jobs** cap on a node when CPU/RAM are underused but the node's job slots are saturated. *Scale out* = add a node when CPU is high / RAM is low or jobs are timing out. Precondition: enable **Remote access to intranet** on the first node *before* adding the second.
- **Gotcha:** Add nodes for resilience and throughput, but four nodes is the hard ceiling for a single logical SHIR.
- **Databricks bridge:** This is the opposite philosophy from Databricks autoscaling. A Databricks cluster elastically adds/removes workers within a job; a SHIR cluster is a fixed set of up-to-4 long-lived machines *you* own and patch. Closer to running your own static Spark workers than to serverless.

#### Sharing a SHIR across factories (Shared IR / Linked IR)

- **What:** You install **one** SHIR on physical infrastructure and let *other* data factories reuse it without re-installing. Terminology: the original is the **Shared IR**; a factory that references it creates a **Linked IR** (a logical pointer, no infrastructure of its own).
- **Mechanism:** The sharing factory grants the *consuming* factory's **managed identity** the **Contributor** role scoped to the Shared IR's resource ID; the consumer then creates a Linked IR pointing at that resource ID (`-SharedIntegrationRuntimeResourceId`). All traffic still flows through the Shared IR's nodes.
- **Gotchas:** (1) only **one** SHIR install per machine — if two factories need on-prem and you don't share, you need two hosts; (2) sharing works **only within the same Microsoft Entra tenant**; (3) **Synapse workspaces cannot share/link SHIRs** (ADF-only feature) — you build a separate SHIR per Synapse workspace; (4) the consuming factory **must** have a managed identity (auto-created in portal/PowerShell, but explicit in ARM/SDK), and granting the role requires Owner/User Access Administrator on the Shared IR.
- **CI/CD note:** ADF requires the **same IR name and type across all CI/CD stages**. A common pattern is a dedicated "shared-IR factory" that all environments reference as a Linked IR.

#### Supported on-prem sources (and the driver gotchas)

| Source | IR | Driver / dependency you must install on the SHIR host |
|---|---|---|
| **SQL Server** (on-prem) | SHIR | Built-in; open outbound 1433 to the source / sink |
| **Oracle** | SHIR | Built-in connector path; SHIR host needs network reach to the Oracle listener |
| **File shares** (SMB/UNC), local file system | SHIR | Built-in; a Java runtime (JRE 8 / JDK / OpenJDK) additionally needed for Parquet/ORC/Avro |
| **SAP HANA** | SHIR | **SAP HANA ODBC driver** ("SAP HANA CLIENT for Windows", from SAP) installed on the host; DIAHostService account needs read/execute on the driver folder |
| **SAP Table / SAP BW / SAP Open Hub** | SHIR | **64-bit SAP Connector for Microsoft .NET 3.0** (install assemblies to GAC); RFC over the SAP gateway/dispatcher ports derived from the instance number (SAP convention: dispatcher `32NN`, gateway `33NN`) |
| **SAP ECC** | **Either** Azure IR or SHIR | Azure IR reaches SAP via a public app gateway (OData); SHIR for the private path |

- **What/Mechanism:** SHIR is also the answer for any **bring-your-own-driver** store — the docs explicitly call out SAP HANA, MySQL, etc. The driver lives on the SHIR machine, not in Azure.
- **Gotcha:** "Treat it as on-prem behind a firewall even over **ExpressRoute**" — ExpressRoute gives you private connectivity but ADF still routes the data through the SHIR; ExpressRoute alone doesn't let an Azure IR see your private source. Also: if **all** of source, sink, and SHIR are on-prem, the data **never touches the cloud** — it stays entirely within your network.

Takeaway: **SHIR = a Windows host with line-of-sight to the source, outbound-only to ADF, up to 4 nodes, creds in Key Vault or DPAPI-local, shareable within one tenant (ADF only). Install the right per-source driver (a Java runtime — JRE 8 / JDK / OpenJDK — for Parquet/ORC/Avro, SAP HANA ODBC / SAP .NET Connector 3.0 for SAP).**

### Azure-SSIS IR — the legacy lift-and-shift

- **What:** A fully managed **cluster of Azure VMs** dedicated to natively executing **SQL Server Integration Services (SSIS — SQL Server's older ETL package engine)** `.dtsx` packages. You bring your own Azure SQL DB or SQL Managed Instance to host the **SSISDB** catalog.
- **Mechanism:** Scale **up** via node size, **out** via node count; manage cost by stopping/starting the IR. On-prem access requires **VNet injection** (joining the IR to a VNet connected to on-prem), or you can configure a **SHIR as a proxy** for the Azure-SSIS IR to reach on-prem data.
- **Gotcha:** **Not supported in Synapse** — ADF only. Editing/deleting it requires stopping it first.
- **Databricks bridge:** There is no Databricks analog; this exists purely to host pre-existing SSIS investments. If you're greenfield, you'd never create one — you'd build Data Flows or push transformation to Databricks/Spark.

Takeaway: **Azure-SSIS IR only matters if you're migrating existing SSIS packages; ignore it for new builds.**

### Data Flow integration runtime (the Spark compute knob)

Mapping Data Flows are ADF's visual, code-free Spark transformations — they run on a **Spark cluster that an Azure IR spins up for you**. This is the IR sub-config most relevant to your Databricks instinct, because here ADF *is* secretly running Spark.

- **Compute type:** `General` (default), `ComputeOptimized`, or `MemoryOptimized`.
- **Core count:** `coreCount` accepts exactly **{8, 16, 32, 48, 80, 144, 272}**. The default **AutoResolve** Azure IR gives Data Flow **4 worker cores**, General.
- **Mechanism — TTL / quick re-use (the cost lever):** By default every Data Flow activity spins up a **brand-new** Spark cluster — and **cold start takes several minutes** before any row is processed. Setting a **Time To Live (TTL, in minutes)** keeps the cluster **warm** for that window after a run; a job that starts within the TTL **reuses** the existing cluster and skips the cold start. After it finishes, the cluster again idles for the TTL.
  - `timeToLive` default is **0** (off).
  - **Invisible-operation callout:** TTL is **not available on the AutoResolve IR** — you *must* create your own Azure IR to use it. So the default IR can never give you warm clusters; that's a deliberate config you opt into.
  - **TTL helps only sequential Data Flows.** Only **one job runs per cluster at a time** — if two Data Flows fire in parallel, the second one spins up its **own** isolated cluster anyway, so TTL gives you nothing for parallel fan-out.
- **Microsoft's production minimum recommendation:** General, **8+8 (16 total vCores)**, **10-minute TTL** for most operationalized workloads.
- **Important gotcha:** The IR selected on the Data Flow activity applies **only to triggered (operationalized) runs**. **Debug** sessions run on whatever cluster the debug session started (the default debug cluster is 8 cores of General compute with a 60-minute TTL) — so your debug cluster size ≠ your production cluster size, and "it was fast in debug" tells you nothing about triggered-run cold starts.

```json
// Execute Data Flow activity pinned to a custom warm-cluster IR
{
  "name": "TransformDimensions",
  "type": "ExecuteDataFlow",
  "typeProperties": {
    "dataflow": { "referenceName": "dfDimCustomer", "type": "DataFlowReference" },
    "integrationRuntime": { "referenceName": "AzureIR_DF_Warm", "type": "IntegrationRuntimeReference" },
    "compute": { "coreCount": 16, "computeType": "General" }   // coreCount/computeType only settable on AutoResolve IR
  }
}
```

> Note the comment above is a real ADF constraint: `compute.coreCount` and `compute.computeType` can be set **inline only when using the AutoResolve IR**. If you bind a custom IR (to get TTL), the cores/type come from the IR definition, not the activity.

- **Databricks bridge:** TTL on an ADF Data Flow IR ≈ a Databricks cluster's **auto-termination + pool / warm-pool** behavior. The "cold start costs minutes" pain is the same one that pushed your team toward Databricks **pools** and serverless. The difference: ADF Data Flow Spark is a black box you tune by `coreCount`/`computeType`/`TTL`, whereas in Databricks you control the runtime, libraries, node types, and the actual SDP/Auto Loader code. For heavy transformation many teams skip Data Flows entirely and have ADF *dispatch* a Databricks Notebook activity (which uses an Azure IR only for the lightweight dispatch, then runs on **your** Databricks cluster) — keeping transformation logic in the lakehouse where you already live.

Takeaway: **Data Flow = managed Spark; the default IR is cold-start-prone with 4 cores; create a custom Azure IR with 16 vCores + 10-min TTL for warm, cheap-to-restart production Data Flows, and remember TTL only helps sequential runs.**

### Which IR do I need? (and how ADF picks when several apply)

- **Resolution precedence (when an activity touches multiple IRs):** **SHIR > managed-VNet Azure IR > global Azure IR.** Example: source linked service on a global Azure IR, sink on a managed-VNet Azure IR ⇒ both run on the managed-VNet IR. But if *either* side points to a **SHIR**, the **whole copy runs on the SHIR**.
- **Copy activity direction logic:**
  - cloud ↔ cloud ⇒ Azure IR (regional if pinned, else AutoResolve).
  - cloud ↔ private-network ⇒ if *either* side is SHIR, the copy runs on the **SHIR**.
  - private ↔ private ⇒ **both** linked services must reference the **same** IR instance, and that IR runs the copy.
- **Lookup / GetMetadata:** runs on the IR bound to the *data store's* linked service.
- **External transform (Databricks/HDInsight) dispatch:** runs on the IR bound to the *compute* linked service (lightweight dispatch — you don't size it).
- **Data Flow:** runs on its associated **Azure IR** only (SHIR can't run Data Flows).

### End-to-end: a copy from on-prem SQL Server to ADLS Gen2

Walk the "life of a request" for the canonical on-prem ingestion, the thing you'd build at Apollo Gen2 if a source lived in a corporate datacenter instead of in Azure:

1. **Install + register SHIR.** Stand up a Windows VM with line-of-sight to the SQL Server. Install SHIR, register it with the auth key (`Get-AzDataFactoryV2IntegrationRuntimeKey` → paste into the Configuration Manager, or express setup). Open outbound 443 to `*.servicebus.windows.net` + `{factory}.{region}.datafactory.azure.net`. Optionally register a 2nd node with the **same key** for HA.
2. **Linked services.** Create a SQL Server linked service whose `connectVia` = the SHIR; store the SQL credential in **Key Vault**. Create an ADLS Gen2 linked service (this one can use the Azure IR — but per the precedence rule, the copy will run on the **SHIR** because the source side is SHIR-bound).

```json
{
  "name": "OnPremSqlServer",
  "properties": {
    "type": "SqlServer",
    "typeProperties": {
      "connectionString": "Server=sqlprod01;Database=Sales;",
      "password": { "type": "AzureKeyVaultSecret",
                    "store": { "referenceName": "KV_LS", "type": "LinkedServiceReference" },
                    "secretName": "sqlprod-password" }
    },
    "connectVia": { "referenceName": "SHIR_DC1", "type": "IntegrationRuntimeReference" }
  }
}
```

3. **Pipeline with a parameterized, looped copy.** Use a Lookup to fetch the table list, then a ForEach to copy each table. Note the verified limits baked in here: **Lookup returns at most 5,000 rows / 4 MB**, and **ForEach `batchCount` maxes at 50** (default 20):

```json
{
  "name": "IngestOnPremTables",
  "activities": [
    {
      "name": "GetTableList", "type": "Lookup",
      "typeProperties": {
        "source": { "type": "SqlServerSource",
          "sqlReaderQuery": "SELECT schema_name, table_name FROM meta.tables_to_copy" },
        "firstRowOnly": false
      }
    },
    {
      "name": "CopyEachTable", "type": "ForEach",
      "dependsOn": [ { "activity": "GetTableList", "dependencyConditions": ["Succeeded"] } ],
      "typeProperties": {
        "items": { "value": "@activity('GetTableList').output.value", "type": "Expression" },
        "isSequential": false,
        "batchCount": 20,
        "activities": [
          {
            "name": "CopyTable", "type": "Copy",
            "typeProperties": {
              "source": { "type": "SqlServerSource",
                "sqlReaderQuery": {
                  "value": "SELECT * FROM [@{item().schema_name}].[@{item().table_name}]",
                  "type": "Expression" } },
              "sink": { "type": "ParquetSink" }
              // No dataIntegrationUnits: DIU applies to Azure IR only, NOT to SHIR.
            }
          }
        ]
      }
    }
  ]
}
```

   Trace, one iteration: `@activity('GetTableList').output.value` → `[{"schema_name":"dbo","table_name":"Orders"}, ...]`. ForEach binds `@item()` to `{"schema_name":"dbo","table_name":"Orders"}`, so `@{item().table_name}` interpolates to `Orders`, and the source query becomes `SELECT * FROM [dbo].[Orders]`.

4. **Execution.** ADF queues the copy + (if not in Key Vault) credentials onto Azure Relay. The **SHIR polls**, pulls the job, connects to SQL Server *inside your network*, reads rows, and writes Parquet to ADLS Gen2 over outbound **443** (requires a Java runtime — JRE 8 / JDK / OpenJDK — on the host for Parquet). DIU does **not** apply — that's an Azure-IR-only knob; on SHIR you scale by node count / concurrent-job cap. If you wrote Parquet without a Java runtime installed, the activity fails on the SHIR host with a Java error — the classic first-run trap.

- **Databricks bridge for the whole flow:** The end state (raw → Parquet in ADLS, ready for Bronze) is exactly what you'd land for Auto Loader / SDP to pick up. The difference is the *ingestion plumbing*: ADF+SHIR is purpose-built for reaching the private source; a Databricks-native approach would need the cluster itself to have VNet line-of-sight (VNet injection + private endpoints) to that SQL Server, which is often why teams keep ADF/SHIR as the on-prem "extractor" and hand off to Databricks for transformation. In a modern Airflow/Dagster stack the analog is a self-hosted worker/executor with network reach to the source — same "run the extractor where it can see the data" principle, different orchestrator.

Takeaway: **On-prem ingestion = SHIR-bound source linked service + Key Vault creds + a Java runtime (JRE 8 / JDK / OpenJDK) for columnar formats; the copy runs on the SHIR by precedence, DIU is irrelevant there, and the landed Parquet feeds your existing lakehouse Bronze layer.**


---

## 3. The Activity Catalog

An ADF pipeline is a DAG of *activities*. Microsoft groups them into exactly three buckets, and that grouping matters because it changes what knobs you get:

| Group | What it does | Key trait |
|---|---|---|
| **Data movement** | Copy data store -> data store | Exactly one: the **Copy** activity. Runs on an Integration Runtime (IR — the compute that actually moves bytes). |
| **Data transformation** | Push compute to an external engine (Spark, SQL, Functions, HDInsight) | "Execution activities" — they get an **activity policy** (timeout/retry). |
| **Control flow** | Loops, branches, variables, orchestration | Mostly run *inside* the ADF service. Control activities do **not** get a retry policy, but several of them (Until, Validation, Wait, the loop/timeout-bearing ones) *do* carry a `timeout` — see the dependency section. |

> Mental model vs. your world: an ADF pipeline ≈ a **Lakeflow Job** (formerly Databricks Workflows). ADF "activities" ≈ Job "tasks". The difference: ADF gives you *imperative* control flow primitives (ForEach, Until, If, Set Variable) inside one pipeline, whereas a Lakeflow Job expresses control flow as task dependencies in the DAG and pushes the looping/branching *into notebooks*. Airflow/Dagster sit between the two — they have Python-native loops/branches at DAG-build time, but ADF evaluates its loops at *runtime*.

There is a **soft limit of 120 activities per pipeline** (including inner activities in containers like ForEach). When you blow past it, you split into parent + child pipelines via Execute Pipeline.

**Takeaway:** three groups, and only the execution group (movement + transformation) gets a retry/timeout *policy* — that single fact explains half the gotchas below.

---

### 1. Data movement — the Copy activity

The Copy activity reads from one *source* and writes to one *sink* (exactly one of each — no fan-out). Its skeleton:

```json
{
  "name": "CopyBlobToSql",
  "type": "Copy",
  "typeProperties": {
    "source": { "type": "DelimitedTextSource" },
    "sink":   { "type": "AzureSqlSink", "writeBehavior": "upsert" },
    "translator": { "type": "TabularTranslator", "mappings": [ ] },
    "dataIntegrationUnits": 8,
    "parallelCopies": 4,
    "enableStaging": true,
    "stagingSettings": { "linkedServiceName": { "referenceName": "StagingBlob", "type": "LinkedServiceReference" } }
  },
  "inputs":  [ { "referenceName": "SrcDataset",  "type": "DatasetReference" } ],
  "outputs": [ { "referenceName": "SinkDataset", "type": "DatasetReference" } ]
}
```

#### DIUs (Data Integration Units)

- **What:** A **DIU (Data Integration Unit)** is a bundle of CPU + memory + network allocated to one Copy run. It applies **only to the Azure IR (Integration Runtime)** — the cloud-hosted, serverless compute. It does **not** apply to a **SHIR (Self-Hosted Integration Runtime** — a VM/agent you install to reach on-prem or VNet-locked sources).
- **Mechanism / numbers:** The allowed DIU range is **4 to 256**. `"Auto"` (the default) lets the service pick. For file-store-to-file-store copies the service auto-picks **between 4 and 32** based on file count/size. There are hard floors you cannot tune away: copy from **REST/HTTP source = 1 DIU**; loading into Synapse via **PolyBase or the COPY statement = effective DIU is always 2** (the Synapse engine does the work, so paying for more DIUs is wasted money).
- **Gotcha — invisible defaulting:** if you don't set `dataIntegrationUnits`, ADF silently chooses; a slow copy may be DIU-starved and you'd never see it in the JSON. Check the activity *output* (`usedDataIntegrationUnits`) in monitoring.
- **Bridge:** there's no clean Databricks analog — DIUs are a managed-service abstraction. The closest mental hook is "DBUs but for the copy engine, not a cluster you sized."

#### Parallel copy

- **What:** `parallelCopies` = max concurrent read/write threads inside one Copy activity. **Orthogonal to DIUs** — it's counted across all DIUs/SHIR nodes, not per-DIU.
- **Mechanism:** Between two file stores it parallelizes *at the file level* (actual parallelism ≤ number of files; `mergeFile` behavior kills file-level parallelism). For partitioned SQL sources it runs N parallel partition queries. Microsoft's tuning rule: set it to `(DIU or #SHIR nodes) × (2 to 4)`. (A single SHIR scales out to at most **4 nodes**, which caps the SHIR side of that formula.)
- **Gotcha:** Azure Synapse Analytics executes **a maximum of 32 queries at a moment** — set `parallelCopies` too high against a partitioned Synapse source and you trip server-side throttling, not a faster copy. (Microsoft Fabric Warehouse has its own concurrency ceiling; check its connector doc rather than assuming the same 32.)
- **Example — partitioned read:**
  ```json
  "source": { "type": "AzureSqlSource", "partitionOption": "PhysicalPartitionsOfTable" }
  ```

#### Staged copy

- **What:** Instead of source -> sink directly, route through interim Blob/ADLS Gen2 storage: source -> staging -> sink.
- **When it's mandatory, not optional:** loading Synapse via PolyBase/COPY when the source format isn't natively PolyBase-compatible — ADF auto-converts to a compatible format in staging, then bulk-loads. Same pattern for Snowflake's COPY command and Databricks Delta Lake when direct-copy criteria aren't met.
- **Config:** `enableStaging: true` + `stagingSettings` (a Blob/ADLS Gen2 linked service). Optional `enableCompression`. You must grant ADF **delete** permission on staging so it can clean up.
- **Gotchas (invisible behavior):** (1) you're **billed for two hops** — charged on copy duration + copy type, so a staged copy costs roughly double a direct one; (2) you **can't copy across two different SHIRs**, with or without staging — chain two explicit Copy activities (source -> staging blob, then staging blob -> sink) instead; (3) with compression enabled, service-principal/MSI auth on the staging Blob linked service is **not supported**.

#### Upsert

- **What:** `"writeBehavior": "upsert"` on a SQL-family sink does INSERT-or-UPDATE keyed on columns you name. If you omit `keys`, ADF falls back to the sink table's primary key.
  ```json
  "sink": {
    "type": "AzureSqlSink",
    "writeBehavior": "upsert",
    "upsertSettings": { "useTempDB": true, "keys": [ "CustomerId" ] }
  }
  ```
- **Bridge:** this is ADF's wrapper around what you'd write as a Databricks `MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN UPDATE ... WHEN NOT MATCHED THEN INSERT`. ADF generates the MERGE-equivalent for you against the SQL engine (it stages the incoming rows in an interim temp table — `useTempDB` — then merges). The `keys` array = your `ON` clause.
- **Gotcha:** **Fault tolerance is silently disabled when you use Upsert** (or a stored-proc SQL sink) — see next bullet.

#### Fault tolerance

- **What:** By default Copy aborts on the first incompatible row. Turn on skip+log to continue (`enableSkipIncompatibleRow`).
- **Three skip scenarios:** (1) source type -> sink type conversion failure (`123,456,abc` into an INT column); (2) column-count mismatch; (3) **primary-key violation** writing to SQL Server / Azure SQL Database / Azure Cosmos DB (first row wins, dupes skipped).
- **Config:** `enableSkipIncompatibleRow: true` plus `logSettings` pointing at a Blob/ADLS Gen2 linked service for the skipped-row CSV (adds `ErrorCode`/`ErrorMessage` columns).
- **Mechanism — what you see in output:**
  ```json
  "output": { "rowsCopied": 9, "rowsSkipped": 2, "logFilePath": "myfolder/<run-id>/" }
  ```
- **Gotchas:** does **not** apply to (a) Upsert into a SQL sink, (b) stored-procedure SQL sinks, (c) Amazon Redshift UNLOAD. For PolyBase, configure native reject policies via `polyBaseSettings` instead.

#### Additional columns

- **What:** Inject extra columns during copy via `additionalColumns` on the source.
  ```json
  "source": {
    "type": "DelimitedTextSource",
    "additionalColumns": [
      { "name": "SourceFile", "value": "$$FILEPATH" },
      { "name": "DupOfId",   "value": "$$COLUMN:Id" },
      { "name": "LoadedBy",  "value": { "value": "@pipeline().Pipeline", "type": "Expression" } },
      { "name": "Env",       "value": "prod" }
    ]
  }
  ```
- **Mechanism — the two reserved tokens:** `$$FILEPATH` = relative source file path (file-based sources only); `$$COLUMN:<source_column_name>` = duplicate an existing source column. Plus arbitrary expressions and static literals.
- **Gotcha (invisible):** these columns exist only if you also **map them in the Mapping tab** to sink columns; forget that and they vanish. They only work with the latest dataset model — if you don't see the option, recreate the dataset.
- **Bridge:** equivalent to `df.withColumn("source_file", input_file_name())` / `withColumn("loaded_by", lit(...))` in Spark — ADF just makes the lineage column declarative.

**Takeaway:** Copy = one source, one sink; DIUs (4–256, Azure IR only) buy raw power, `parallelCopies` buys threads, staging is a mandatory detour for PolyBase/Snowflake/Delta format mismatches, and Upsert/stored-proc sinks turn fault tolerance off.

---

### 2. Data transformation activities

These push compute to an external engine. All are *execution* activities, so all get the timeout/retry policy.

| Activity | Engine it drives | You give it |
|---|---|---|
| **Mapping Data Flow** (`ExecuteDataFlow`) | ADF-managed **Spark** cluster (serverless, JIT) | A visual/code-free data flow graph |
| **Databricks Notebook / Jar / Python** | Azure Databricks | `notebookPath` + `baseParameters` / class name / py path + `libraries` |
| **Synapse Notebook / Spark Job Defn** | Synapse Spark pool | Notebook ref + params |
| **HDInsight** (Hive, Pig, MapReduce, Streaming, Spark) | HDInsight Hadoop cluster | Script path + `defines` (Hive config values) |
| **Stored Procedure** | Azure SQL / Synapse / SQL Server | SP name + parameters |
| **Azure Function** | Azure Functions | `functionName`, `functionKey`, `functionAppUrl`, `method` |
| **Script** | Any SQL-family linked service | Raw SQL blocks (Query / NonQuery) |
| **Custom** | Azure Batch | A `.NET`/exe command |

#### Mapping Data Flow

- **What:** Visually-authored transformations that ADF compiles to Spark and runs on a *managed* (auto-resolve) Spark cluster — you never see the cluster.
- **Mechanism / numbers:** `compute.coreCount` allowed values are **8, 16, 32, 48, 80, 144, 272**; `compute.computeType` is `"General"` (others exist: `MemoryOptimized` / `ComputeOptimized`). These only apply with the **autoresolve Azure IR**. If `staging` is set and source/sink is Synapse, it uses PolyBase staging under the covers.
  ```json
  { "type": "ExecuteDataFlow",
    "typeProperties": {
      "dataflow": { "referenceName": "TransformOrders", "type": "DataFlowReference" },
      "compute": { "coreCount": 8, "computeType": "General" },
      "traceLevel": "Fine" } }
  ```
- **Gotcha:** **cluster startup is ~5 min cold** unless you keep a "TTL" warm pool on the IR; for tight SLAs that latency is invisible until it bites you. Debug mode runs against a *different* cluster than the IR you configured.
- **Bridge:** this is the activity you will personally use least at Apollo Gen2 — your transforms live in Databricks notebooks/SDP (Spark Declarative Pipelines, the engine behind DLT) already. Mapping Data Flow is ADF's "we'll spin up Spark for people who don't have Databricks" play. Prefer the Databricks Notebook activity to reuse your existing code.

#### Databricks Notebook activity (the one you'll actually wire up)

- **What:** Triggers an ephemeral or existing-cluster run of one notebook on your Databricks workspace (via a Databricks linked service).
- **Mechanism — params in:** `baseParameters` (key/value) land as **notebook widget values** — i.e. `dbutils.widgets.get("input")` reads them. So `baseParameters: { "input": "@pipeline().parameters.name" }` is exactly your `dbutils.widgets`.
  ```json
  { "type": "DatabricksNotebook",
    "linkedServiceName": { "referenceName": "AzureDatabricks", "type": "LinkedServiceReference" },
    "typeProperties": {
      "notebookPath": "/adftutorial/mynotebook",
      "baseParameters": { "input": { "value": "@pipeline().parameters.name", "type": "Expression" } } } }
  ```
- **Mechanism — value out:** call `dbutils.notebook.exit("returnValue")` in the notebook; ADF surfaces it as `@activity('Nb').output.runOutput`. If you exit a JSON string, drill in: `@activity('Nb').output.runOutput.PropertyName`. **Size limit 2 MB.**
- **Gotcha (invisible):** `baseParameters` arrive as **strings** — a notebook expecting an int must cast. And if the notebook doesn't declare a widget you passed, the value is silently ignored.
- **Bridge:** `baseParameters` = `dbutils.widgets`; `runOutput` = `dbutils.notebook.exit`. Same contract you already use inside a Lakeflow Job's notebook task — ADF is just the external orchestrator instead of Lakeflow.

#### Stored Procedure vs. Script — pick the right one

| | Stored Procedure activity | Script activity |
|---|---|---|
| Runs | a *named, pre-existing* SP | *ad-hoc* SQL text you paste in |
| Returns data to pipeline? | **No** (fire-and-forget; output params only) | **Yes** — `resultSets` consumable downstream |
| Block types | n/a | `Query` (default) or `NonQuery` (DML/DDL, returns `recordsAffected`) |
| Use for | encapsulated business logic, MERGE procs | TRUNCATE before load, CREATE/ALTER/DROP, save a rowset as output |

- **Script output numbers:** result rows limited to **5000 rows / 4 MB**, same as Lookup. When output overflows, ADF **truncates in order: logs -> parameters -> rows** and sets `outputTruncated: true` — an invisible operation you must watch for.
  ```json
  { "type": "Script",
    "typeProperties": {
      "scripts": [
        { "type": "NonQuery", "text": "TRUNCATE TABLE stage.orders" },
        { "type": "Query",    "text": "SELECT COUNT(*) AS n FROM dbo.orders" } ] } }
  ```

#### Azure Function activity

- **What:** Calls an HTTP-triggered Azure Function.
- **Mechanism / numbers:** supported HTTP methods are **GET, POST, PUT, DELETE, OPTIONS, HEAD, TRACE** (an unsupported verb fails with error 3602). The Function **must return a valid JSON object** (a non-JSON body fails with error 3603). Requires `functionName`, `functionKey`, `functionAppUrl`.
- **Gotcha:** non-JSON response = activity failure even if the function ran fine.

**Takeaway:** transformation activities are thin orchestration wrappers around external engines. For Apollo Gen2, the Databricks Notebook activity (`baseParameters` in via widgets, `runOutput` out via `dbutils.notebook.exit`, 2 MB cap) is your bread and butter; Script is your TRUNCATE/DDL utility; Mapping Data Flow you can largely ignore since you own Databricks.

---

### 3. Control-flow activities

These are the orchestration primitives. Most run inside the ADF service (no external compute) and most are **free of an activity *policy*** — no retry knob — *except* the iteration/timeout-bearing ones (Until, Wait, Validation carry their own `timeout`).

#### ForEach — the workhorse loop

- **What:** Iterate over a JSON array; `@item()` is the current element.
  ```json
  { "type": "ForEach",
    "typeProperties": {
      "isSequential": false,
      "batchCount": 20,
      "items": { "value": "@activity('LookupTables').output.value", "type": "Expression" },
      "activities": [ { "name": "CopyOne", "type": "Copy", "typeProperties": { } } ] } }
  ```
- **Mechanism / numbers (verified):** `isSequential: false` (the **default**) runs in parallel; `batchCount` is the concurrency ceiling — **default 20, maximum 50**. The array itself can hold **up to 100,000 items**. `batchCount` is documented as "the upper concurrency limit, but the for-each activity will not always execute at this number" — so it's a *ceiling*, not a guarantee; raising it past your actual parallelizable work does nothing.
- **Gotchas (these bite hard):**
  - **No nesting.** A ForEach cannot contain another ForEach or an Until. Workaround: inner pipeline + Execute Pipeline.
  - **Set Variable is unsafe inside a parallel ForEach.** Variables are **pipeline-global, not loop-scoped, not thread-safe** — parallel iterations race. Use `isSequential: true`, or push the variable work into a child pipeline via Execute Pipeline.
- **Bridge:** Airflow's *dynamic task mapping* (`.expand()`) / Dagster's *dynamic outputs* are the modern-stack analogs — but those map at the orchestration layer and don't share Airflow's "no real loop-local state" footgun the way ADF's global variables do. In Databricks, the equivalent is a **`for_each` task** in a Lakeflow Job (or just looping inside one notebook).

**Takeaway:** ForEach is parallel-by-default, capped at batchCount ≤ 50 over ≤ 100k items, can't nest, and will silently corrupt global variables under parallelism.

#### Lookup — read a config/control row

- **What:** Reads rows from any supported source and hands them to downstream activities.
- **Mechanism — the firstRow/array switch:** `firstRowOnly` defaults to **`true`**.
  - `true` -> `@activity('Lk').output.firstRow.tableName` (one object)
  - `false` -> `@activity('Lk').output.value` (an array; feed straight into ForEach `items`)
- **Numbers (verified, and they vary by connector — call this out):**
  - Default cap: **5,000 rows / 4 MB / 24-hour** timeout. Over the row cap, it silently returns only the first 5,000.
  - **Azure Databricks Delta Lake** source: capped at **1,000 rows**.
  - **Azure Data Explorer (Kusto)**: **5,000 rows / 2 MB / 1-hour** query timeout.
- **Gotchas:** a query/SP must return **exactly one result set** or Lookup fails.
- **Bridge:** Lookup ≈ reading a small control/config table; in a Databricks-native flow you'd `spark.read...collect()` a tiny config DataFrame or read a job parameter. The 5k/4MB cap is ADF-specific — never use Lookup to move data, only to fetch control metadata.

#### GetMetadata — inspect files/folders/tables

- **What:** Returns metadata (existence, size, child listing, schema) without reading data.
- **Mechanism — the `fieldList`:** you request fields explicitly:
  ```json
  { "type": "GetMetadata",
    "typeProperties": {
      "dataset": { "referenceName": "FolderDS", "type": "DatasetReference" },
      "fieldList": [ "exists", "childItems", "itemType", "lastModified" ] } }
  ```
  Fields: `itemName, itemType (File|Folder), size, created, lastModified, childItems, contentMD5, structure, columnCount, exists`. Max returned metadata **4 MB**.
- **The `exists` gotcha (invisible failure mode):** if `exists` is in the field list, the activity **does not fail** when the object is missing — it returns `exists: false`. If `exists` is **not** in the list, a missing object **fails the activity**. So "check if file exists" *requires* you to add `exists` to `fieldList`.
- **Other gotchas:** wildcard folder/file filters are **not supported**; `childItems` lists only the immediate folder (subfolders not recursed), and with `modifiedDatetimeStart/End` filters it enumerates *every* file in the folder to check mtime — avoid pointing it at huge folders.
- **Bridge:** `childItems` ≈ `dbutils.fs.ls(path)`; `exists` ≈ a `try/except` around `dbutils.fs.ls`. Auto Loader / SDP handle file discovery for you in Databricks — GetMetadata is ADF's manual equivalent for control-flow gating.

#### If Condition / Switch — branching

| | If Condition | Switch |
|---|---|---|
| Expression evaluates to | boolean | **string** (must resolve to a string per the docs/UI) |
| Branches | `ifTrueActivities` / `ifFalseActivities` | `cases[]` (each a value + activities) + `defaultActivities` |
| Branch limit | 2 | **max 25 cases** |
| No match | n/a | runs `defaultActivities` |

```json
{ "type": "Switch",
  "typeProperties": {
    "on": { "value": "@activity('GetMeta').output.itemType", "type": "Expression" },
    "cases": [
      { "value": "Folder", "activities": [ ] },
      { "value": "File",   "activities": [ ] } ],
    "defaultActivities": [ ] } }
```

- **Gotcha:** Switch `on` must resolve to a value that exactly string-matches a case value; no ranges/regex. `defaultActivities` is your `else`. Neither If nor Switch can be nested inside each other directly in many UI paths — push complex branching into child pipelines.

#### Until — do-while loop

- **What:** Runs inner activities repeatedly *until* a boolean expression is true (do-until: body runs at least once).
- **Mechanism / numbers (verified):** `timeout` format `d.hh:mm:ss` or `hh:mm:ss`; **default 7 days, maximum 90 days**. The loop exits on `expression == true` **or** timeout, whichever is first.
  ```json
  { "type": "Until",
    "typeProperties": {
      "expression": { "value": "@equals(variables('status'),'done')", "type": "Expression" },
      "timeout": "0.02:00:00",
      "activities": [ ] } }
  ```
- **Gotcha:** **if an inner activity fails, Until does NOT stop** — it keeps looping. You must explicitly check inner-activity status in the `expression` if you want failure to break the loop. Common pattern: Web/Lookup poll -> Set Variable -> Until checks the variable.
- **Bridge:** classic "poll an async job until done." In Databricks you'd just block on the job run; in Airflow you'd use a **sensor** (poke/reschedule mode) — far more ergonomic than ADF's Until + Wait + Set Variable triad.

#### Wait

- **What:** Sleep N seconds. `{ "type": "Wait", "typeProperties": { "waitTimeInSeconds": 30 } }`. Used inside Until poll loops to pace the polling.

#### Set Variable / Append Variable

- **Set Variable:** assigns String / Bool / Array. **No self-reference** — `@variables('x')` cannot appear in the value setting `x`. To increment, use a temp variable + a second Set Variable.
- **Append Variable:** appends one element to an **array** variable — safe way to accumulate inside a *sequential* ForEach.
- **Pipeline return value (this is how Set Variable returns data to a parent):** Set Variable has a special `Pipeline return value` mode. In the child, set keys; in the parent they appear as `@activity('ExecutePipeline1').output.pipelineReturnValue.keyName` (objects drill deeper, arrays index `[0]`). Total return JSON limited to **4 MB**.
- **Gotcha (repeat, because it's the #1 ADF bug):** variables are **pipeline-global and not thread-safe** — never Set/Append them inside a *parallel* ForEach.

#### Filter

- **What:** Applies a condition to an input array, returns the matching subset.
  ```json
  { "type": "Filter",
    "typeProperties": {
      "items":     { "value": "@activity('Lk').output.value", "type": "Expression" },
      "condition": { "value": "@endswith(item().name, '.csv')", "type": "Expression" } } }
  ```
- **Bridge:** `[x for x in items if cond]` / `df.filter(...)` — pure in-memory list filtering, no compute.

#### Execute Pipeline — call a child pipeline

- **What:** Invoke another pipeline (parent/child decomposition; the answer to the 120-activity limit and the no-nested-ForEach limit).
- **Mechanism — `waitOnCompletion` (defaults to TRUE per the ADF docs):**
  - `true` (**default** in the "Execute Pipeline activity" doc): parent blocks until child finishes, and the child's `pipelineReturnValue` becomes `@activity('ExecPipe').output.pipelineReturnValue.x`.
  - `false`: fire-and-forget; parent moves on immediately, child output is **not** available.
  - *Heads-up on a doc/SDK split:* the ARM/SDK property (`ExecutePipelineActivityTypeProperties.waitOnCompletion`) documents the default as **false**, while the ADF activity reference page documents it as **true**. Don't rely on the implicit default for anything load-bearing — set it explicitly.
  ```json
  { "type": "ExecutePipeline",
    "typeProperties": {
      "pipeline": { "referenceName": "ChildLoad", "type": "PipelineReference" },
      "waitOnCompletion": true,
      "parameters": { "tableName": "@item().table" } } }
  ```
- **Gotchas:** (1) you must have `waitOnCompletion: true` (default in the UI) to read any return value; (2) the parent does **not** validate that the `keyName` you reference actually exists in the child — a typo fails at runtime, not author time; (3) arrays passed as parameters can get stringified across the boundary (a documented behavior).
- **Bridge:** Execute Pipeline = a Lakeflow Job's "Run Job" task, or Airflow's `TriggerDagRunOperator` (with `wait_for_completion`).

#### Web vs. Webhook — call REST

| | Web activity | Webhook activity |
|---|---|---|
| Pattern | request -> wait for HTTP response | request -> **wait for a callback** to `callBackUri` |
| Blocks on | the HTTP response | the external system invoking your callback URL |
| Methods | GET, POST, PUT, PATCH, DELETE | POST |
| Fail control | non-2xx fails it | `reportStatusOnCallBack: true` lets the callback body set `StatusCode >= 400` to fail |

- **Web — numbers (corrected against docs):** `method` ∈ {GET, POST, PUT, PATCH, DELETE}; `body` is **required for POST/PUT/PATCH**, **optional for DELETE**, and not used for GET; `httpRequestTimeout` default **00:01:00 (1 minute)**, range **1–10 minutes** (this is the per-request response timeout, *separate* from the activity timeout). Can pass `datasets`/`linkedServices` to inject secrets/connection info.
  ```json
  { "type": "WebActivity",
    "typeProperties": {
      "url": "https://api.internal/trigger",
      "method": "POST",
      "headers": { "Content-Type": "application/json" },
      "body": { "value": "@concat('{\"run\":\"', pipeline().RunId, '\"}')", "type": "Expression" } } }
  ```
- **Webhook — mechanism:** ADF posts a `callBackUri` in the body; your endpoint must call it back (valid JSON, `Content-Type: application/json`) **before the activity timeout** (the Webhook `timeout` defaults to 10 minutes), else the activity ends as `TimedOut`. With `reportStatusOnCallBack: true`, the callback body shape is:
  ```json
  { "Output": { "testProp": "v" }, "Error": { "ErrorCode": "x", "Message": "m" }, "StatusCode": "403" }
  ```
- **Gotcha:** Web's 1-minute per-request HTTP timeout is unrelated to the activity timeout; long-running APIs should return HTTP 202 + you poll (or use Webhook's callback pattern). Don't confuse the two timeouts.

#### Validation — gate on a file/dataset

- **What:** Blocks the pipeline until a referenced dataset exists / meets criteria / times out.
- **Numbers (verified):** `timeout` default **12 hours** (`0.12:00:00`); `sleep` (retry interval) default **10 seconds**; `minimumSize` default **0** bytes; `childItems` — `true` = folder must have ≥1 item, `false` = folder must be empty, omitted = just exists.
- **Bridge:** an Airflow **sensor** in disguise. Use it to wait for an upstream landing file before kicking off Copy.

#### Fail — throw on purpose

- **What:** Deliberately fail the pipeline with a custom message + code.
  ```json
  { "type": "Fail", "typeProperties": { "message": "No rows matched", "errorCode": "500" } }
  ```
- **Numbers:** both `message` and `errorCode` are **required** (strings or expressions resolving to non-empty strings). If your dynamic expression resolves to null/empty, ADF substitutes its own `ErrorCodeNotString` error. Scope = whole pipeline, or the enclosing control activity.
- **Pattern:** Lookup returns empty -> If Condition -> True branch = Fail. Like a Python `raise ValueError(...)`.

#### Delete — clean up files

- **What:** Deletes files/folders from storage stores.
- **Numbers:** `recursive` default **false**; `maxConcurrentConnections` default **1**; optional logging writes a deleted-files manifest. **Deletes are irreversible** unless soft-delete is on. On-prem delete needs a SHIR with a **version greater than 3.14**.
- **Bridge:** `dbutils.fs.rm(path, recurse=True)`. The `maxConcurrentConnections: 1` default makes large cleanups slow — bump it.

**Takeaway:** control flow gives you imperative orchestration ADF evaluates at *runtime*. Memorize three defaults that cause real incidents: ForEach `isSequential=false` (parallel), Execute Pipeline `waitOnCompletion` (ADF docs say true, SDK says false — set it explicitly), and GetMetadata needs `exists` in the field list or it throws on a missing object.

---

### 4. Activity dependencies, retry, and timeout

This is how you wire activities together and is the most exam-tested, production-critical part.

#### The four dependency conditions

On every activity, `dependsOn` lists upstream activities + the condition under which this activity runs. The four conditions (verified against the ARM schema): **Succeeded, Failed, Completed, Skipped.**

```json
"dependsOn": [
  { "activity": "CopyData", "dependencyConditions": [ "Succeeded" ] }
]
```

| Condition | Downstream runs when upstream's final status is… | Use it for |
|---|---|---|
| **Succeeded** (default green arrow) | Succeeded | the happy path |
| **Failed** (red arrow) | Failed | error-handling / logging branch |
| **Completed** (blue arrow) | Succeeded **OR** Failed | "run regardless" cleanup |
| **Skipped** (grey arrow) | Skipped | rarely; reacts to a skip |

**The Skipped semantics you must internalize** (straight from docs): in a chain X -> Y -> Z where each depends on the prior with **Succeeded**, if **X fails**, then **Y is Skipped** (it never executes), and **Z is also Skipped** (cascade). "Skipped" is a real terminal status, not "didn't run."

**Critical multi-dependency gotcha (the #1 ADF orchestration trap):** when an activity has **multiple** `dependsOn` entries, ADF **ANDs** them. So a "common downstream after two parallel branches" with one Succeeded + one Failed arrow will **only fire if branch A succeeds AND branch B fails** — almost never what you want. The documented workaround for OR-style "run if any path is acceptable" is: connect everything with **Completed** arrows, then add an **If Condition** whose expression reads the upstream statuses:

```json
@or(equals(activity('BranchA').Status, 'Succeeded'), equals(activity('BranchB').Status, 'Succeeded'))
```

- **Bridge:** Airflow's `trigger_rule` (`all_success`, `all_done`, `one_failed`, `none_failed`) is the direct analog — and Airflow exposes OR-style rules (`one_success`) natively, whereas ADF forces you into the Completed-arrows-plus-If-Condition idiom because multiple dependsOn always AND. Databricks Lakeflow tasks default to `all_success` with a per-task "run if" rule similar to ADF.

#### Retry and timeout (the activity policy)

`policy` exists **only on execution activities** (Copy + transformations), not on pure control activities:

```json
"policy": {
  "timeout": "0.12:00:00",
  "retry": 2,
  "retryIntervalInSeconds": 60,
  "secureInput": false,
  "secureOutput": true
}
```

| Property | Default | Bounds | Notes |
|---|---|---|---|
| `retry` | **0** | integer ≥ 0 | max *ordinary* retry attempts |
| `retryIntervalInSeconds` | **30** | **min 30, max 86400** (24h) | delay between attempts |
| `timeout` | **12 hours** for execution activities (min 10 min). **7 days** for control/looping activities (Until, Validation) and the ARM/SDK default. | format `d.hh:mm:ss` | **this dual default is a real, documented inconsistency — call it out** |
| `secureInput` / `secureOutput` | false | bool | suppress logging of input/output (use for secrets) |

- **The timeout gotcha to flag explicitly:** the canonical "Pipelines and activities" page says execution-activity timeout default is **12 hours, minimum 10 minutes**; the ARM/SDK schema for the generic `ActivityPolicy` and for control activities (Until, Validation) says **7 days**. These are *not* contradictory — they apply to different activity classes — but the 7-day number you'll see in API docs is **not** what your Copy activity defaults to (12 h). Don't quote 7 days for a Copy.
- **`retry` mechanism:** retries are *whole-activity* re-executions after `retryIntervalInSeconds`. There's no exponential backoff knob — interval is fixed.
- **Bridge:** `retry` + `retryIntervalInSeconds` = Airflow's `retries` + `retry_delay` (but Airflow gives you `retry_exponential_backoff`; ADF does not). `secureOutput` ≈ marking a value as a Databricks secret so it's redacted in logs.

**Takeaway:** four conditions (Succeeded/Failed/Completed/Skipped); multiple dependencies always **AND** (use Completed + If Condition for OR); retry defaults to **0** with a fixed 30s–24h interval; and the activity timeout default is **12 hours for Copy/transform** vs **7 days for control/looping** — never conflate the two.


---

## 4. Parameters, Variables, Expressions & Their Scopes

Azure Data Factory (ADF — Microsoft's cloud ETL/orchestration service) has no first-class "task config" object the way Lakeflow Jobs (the Databricks-native job scheduler, formerly "Workflows/Jobs") hands you `dbutils.widgets` or job parameters in one place. Instead, ADF spreads configurability across **seven distinct scopes**, each with its own reference syntax and its own mutability rule. Getting these scopes straight is the single biggest source of confusion for engineers coming from Databricks, so this section makes the hierarchy explicit before drilling into the expression language that glues it all together.

### The mutability split: parameter vs variable (the #1 confusion)

This is the distinction that trips up everyone. Burn it in first.

| | **Parameter** | **Variable** |
|---|---|---|
| Who sets it | Caller from *outside* (trigger, parent pipeline, or you in the Debug panel) | The pipeline *itself*, via a Set Variable / Append Variable activity |
| When | Once, at run start | Any time *during* the run |
| Mutable mid-run? | **No** — read-only / immutable for the entire run | **Yes** — that is the whole point |
| Reference syntax | `@pipeline().parameters.<name>` | `@variables('<name>')` |
| Defined on | pipeline, dataset, linked service, data flow | pipeline only |
| Analogy | function argument | local variable |

The official wording from Microsoft Learn: *"Parameters are external and therefore passed into pipelines, datasets, linked services, and data flows, whereas variables are defined and used within a pipeline. Parameters are read-only, whereas variables can be modified within a pipeline by using the Set Variable activity."*

- **What:** A parameter is an input contract; a variable is mutable run-local state.
- **Mechanism:** When a run starts, ADF binds every parameter to its argument value (from the trigger, the parent's Execute Pipeline call, or the default) and *freezes it*. There is no "Set Parameter" activity — the API simply doesn't expose one. Variables, by contrast, start at their default and are rewritten in place by Set/Append Variable activities.
- **Databricks bridge:** A pipeline parameter is the ADF equivalent of a `dbutils.widgets.get("date")` value or a Lakeflow Jobs job parameter — passed in, read-only inside the run. There is no clean Databricks analogue to an ADF variable, because in a notebook you just reassign a Python/Scala variable; ADF has to model mutation as an explicit *activity* because the pipeline is declarative JSON, not imperative code.
- **Gotcha — variables are pipeline-global, not loop-local:** Microsoft Learn explicitly warns: *"Variables are currently scoped at the pipeline level. This means that they aren't thread safe and can cause unexpected and undesired behavior if they're accessed from within a parallel iteration activity such as a foreach loop, especially when the value is also being modified within that foreach activity."* If you `Append Variable` inside a parallel `ForEach`, two iterations can race on the same array and you silently lose appends — there is no per-iteration variable scope. Workaround per the docs: run the ForEach sequentially (`isSequential: true`), or push the variable logic into a child pipeline invoked via Execute Pipeline so each iteration gets its own pipeline instance (its own variable copy).

**Takeaway:** Parameter = frozen input; Variable = mutable, pipeline-global, *not* loop-safe.

---

### The seven scopes, top to bottom

Here is the full hierarchy, from factory-wide constants down to per-row loop context. The "Reference syntax" column is the exact string you type into the dynamic-content editor.

| Scope | Mutable? | Set by | Reference syntax | Typical use |
|---|---|---|---|---|
| **Global parameters** | No (constant; CI/CD-overridable) | Factory admin / ARM template | `pipeline().globalParameters.<name>` | env name, tenant URL, shared constants |
| **System variables** | No (engine-provided) | ADF runtime | `@pipeline().RunId`, `@trigger().startTime`, `@item()`, `@activity('X').output…` | run metadata, trigger time, loop item, upstream output |
| **Pipeline parameters** | No (per-run) | Trigger / parent pipeline / Debug panel | `@pipeline().parameters.<name>` | the run's inputs (date to load, file path) |
| **Pipeline variables** | **Yes** | Set / Append Variable activity | `@variables('<name>')` | counters, accumulators, computed state |
| **Dataset parameters** | No (per-reference) | The pipeline activity that uses the dataset | `@dataset().<name>` (inside the dataset) | folder/file path, table name |
| **Linked service parameters** | No (per-reference) | Whoever references the linked service | `@{linkedService().<name>}` (inside the LS) | DB name, server, username |
| **Data flow parameters** | No (immutable, `$`-prefixed) | The Execute Data Flow activity | `$<name>` (inside the data flow) | transform thresholds, column names |

Two things to notice immediately, because they catch Databricks engineers off guard:

1. **Global parameters and system variables are referenced *without* the `parameters` token** — it's `pipeline().globalParameters.x` and `@pipeline().RunId`, not `@pipeline().parameters.x`. Only the per-run user-defined parameters live under `.parameters`.
2. **Dataset, linked-service, and data-flow parameters use *their own* accessor** (`dataset()`, `linkedService()`, `$name`) — never `pipeline()`. The accessor word tells you which scope you're reading.

Now each scope in detail.

#### 1. Pipeline parameters — the run's frozen inputs

- **What:** Named, typed inputs declared on the pipeline. Allowed data types (from the Learn docs): **String, Int, Float, Bool, Array, Object, or SecureString.**
- **Mechanism:** Declared in JSON under `properties.parameters`; bound at run start; read with `@pipeline().parameters.<name>`. A default value is optional and is used only when the caller passes nothing. (Note: a factory has a hard cap of **50 parameters per pipeline** per the ADF service limits.)

```json
"properties": {
  "parameters": {
    "loadDate":   { "type": "String", "defaultValue": "2026-06-30" },
    "tableList":  { "type": "Array" }
  }
}
```

Reading one inside an activity: `@pipeline().parameters.loadDate`.

- **Gotcha — `SecureString`:** marking a parameter `SecureString` only redacts it from logs/monitoring; it is *not* a secret store. The docs are blunt about this: a `SecureString` is *"serialized as JSON within the `activity.json` file as plain text… This serialization is not truly secure, and is not intended to be secure. The intent is a hint to the service to mask the value in the Monitoring tab."* The recommendation elsewhere is explicit: *"We recommend not to parameterize passwords or secrets. Store all secrets in Azure Key Vault instead, and parameterize the Secret Name."* This mirrors the Databricks rule — `dbutils.secrets.get()` from a secret scope, never a hardcoded widget value.
- **Databricks bridge:** Direct analogue of a Lakeflow Jobs job parameter / notebook widget. Same "passed in once, read-only" semantics.

**Takeaway:** Declare typed inputs, bind at start, read via `@pipeline().parameters.x`; secrets go to Key Vault, not SecureString params.

#### 2. Pipeline variables — mutable run state via activities

- **What:** Pipeline-scoped mutable state. Allowed types are narrower than parameters: **String, Bool, or Array only** (no Int/Float/Object — confirmed in the Learn variable-definition steps).
- **Mechanism:** Two activities mutate them:
  - **Set Variable** — overwrites the value of a String/Bool/Array variable. Per the docs it can also set a *pipeline return value* (preview) for handing data back to a parent (key-value pairs, capped by the 4 MB returned-JSON size limit).
  - **Append Variable** — adds one element to an **Array** variable (`variableName` *"must be of type 'Array'"*). There is no append for String/Bool.
- **Read with** `@variables('<name>')`.

```json
{ "name": "AddFile", "type": "AppendVariable",
  "typeProperties": { "variableName": "processedFiles",
                      "value": "@item().name" } }
```

- **No invisible coercion to flag:** an Int does *not* exist as a variable type. If you need a numeric counter you store it as a String and convert on read with `int(...)` — the engine will *not* auto-cast `"5"` to `5` in arithmetic; `add(variables('c'), 1)` on a String var fails unless you wrap `int(variables('c'))`. (Note also the docs' self-reference limitation: Set Variable can't read the variable it's setting in the same activity, so an in-place counter increment needs a temp-variable + second Set Variable.)
- **Gotcha (repeated because it matters):** Set/Append Variable inside a parallel ForEach is unsafe — variables are global to the pipeline, not scoped to the loop.
- **Databricks bridge:** No real equivalent — in a notebook you reassign a variable in code. ADF forces mutation through declarative activities, which is why "increment a counter" is a whole activity, not `i += 1`.

**Takeaway:** Variables are String/Bool/Array, mutated only by Set/Append activities, read via `@variables('x')`, unsafe in parallel loops.

#### 3. Dataset parameters — parameterize the data shape/location

- **What:** A dataset (the strongly-typed pointer to *where/what* the data is) can declare its own parameters so one dataset definition serves many folders/tables.
- **Mechanism:** Declared under `parameters` in the dataset JSON; referenced *inside the dataset* with `@dataset().<name>`; the *value* is supplied by the activity that references the dataset (typically from a pipeline parameter or `@item()`).

```json
{
  "name": "BlobDataset",
  "properties": {
    "type": "AzureBlob",
    "typeProperties": { "folderPath": "@dataset().path" },
    "linkedServiceName": { "referenceName": "AzureStorageLinkedService",
                           "type": "LinkedServiceReference" },
    "parameters": { "path": { "type": "String" } }
  }
}
```

In the Copy activity, you'd bind `path` to, say, `@concat('raw/', pipeline().parameters.loadDate)`.

- **Databricks bridge:** Closest to a parameterized table path or an Auto Loader `cloudFiles` path templated by a widget — one definition, many targets. In SDP (Spark Declarative Pipelines, formerly Delta Live Tables) you'd template the source path in code; ADF templates it in JSON.

**Takeaway:** One parameterized dataset replaces N near-identical datasets; read with `@dataset().x`, value injected at the activity.

#### 4. Linked service parameters — parameterize the connection

- **What:** A linked service (the connection string / "how to connect") can itself be parameterized, so one linked service connects to many databases on the same server.
- **Mechanism:** Declared under `parameters` in the LS JSON; referenced inside the LS with **string interpolation** `@{linkedService().<name>}`; value flows down from the dataset (which got it from the pipeline).

```json
{
  "name": "SqlServerLS",
  "properties": {
    "type": "AzureSqlDatabase",
    "typeProperties": {
      "connectionString": "Server=tcp:myserver.database.windows.net;Database=@{linkedService().dbName};..."
    },
    "parameters": { "dbName": { "type": "String" } }
  }
}
```

- **Capability note (verified):** Per Learn, *"All the linked service types are supported for parameterization."* **50** linked-service types (Azure SQL, Blob, ADLS Gen2, Azure Databricks, Azure Databricks Delta Lake, Snowflake, SFTP, REST, etc.) get a native "Add dynamic content" UI; the rest are parameterized by editing the JSON directly via the "Specify dynamic contents in JSON format" checkbox under Advanced.
- **Gotcha — the `-` (hyphen) bug:** the docs carry an open-bug note: *avoid `-` in parameter names* (both for linked-service params and global params, where `pipeline().globalParameters.myparam-dbtest-url` throws an `InvalidTemplate` / `BadRequest` error). Use `_`.
- **Databricks bridge:** Like templating a JDBC URL's database segment, or pointing one Databricks connection at multiple catalogs. Same goal: kill connection-object sprawl.

**Takeaway:** Parameterize the *connection* to collapse one-LS-per-database into one LS; reference with `@{linkedService().x}`; never put the password here — parameterize the Key Vault *secret name*.

#### 5. Data flow parameters — the `$`-prefixed, immutable kind

- **What:** Mapping Data Flows (ADF's visual, Spark-backed transformation engine — the rough analogue of a no-code Spark job) have their *own* parameter system, distinct from pipeline parameters.
- **Mechanism (and the surprise):** Inside a data flow, parameters **begin with `$` and are immutable**, per Learn: *"Parameters can be referenced in any data flow expression. Parameters begin with `$` and are immutable."* So you write `$myThreshold`, **not** `@pipeline()...`. The value is supplied by the Execute Data Flow activity in the pipeline, where you map pipeline expressions onto the data flow's `$` parameters. Parameterized linked services can also be consumed by a data flow (for both dataset and inline source types).
- **Gotcha — two expression dialects:** the pipeline expression language and the data-flow expression language are **different**. Pipeline-side uses `@`/`@{}` and functions like `coalesce`; data-flow-side uses Spark-like syntax (`==`, `&&`, `iif()`, `equalsIgnoreCase`), single OR double quotes for strings, **one-based array indexing** (`myArray[1]` is the first element), and — notably — **no string interpolation** (you concatenate instead: `'part1' + $variable + 'part2'`). Don't paste a pipeline expression into a data flow or vice versa.
- **Databricks bridge:** A Mapping Data Flow *is* generated Spark under the hood (it spins up a Spark cluster on the integration runtime). Its `$` parameters are like arguments to a Spark transform function. If your shop runs the transform in a Databricks notebook instead, the equivalent is a notebook widget read inside the Spark job.

**Takeaway:** Data flow parameters are `$name`, immutable, and live in a *separate* expression dialect from pipeline expressions — mentally context-switch when you cross the Execute Data Flow boundary.

#### 6. Global parameters — factory-level constants

- **What:** *"Global parameters are constants across a data factory that pipelines can consume in any expression"* — one place for values shared by many pipelines (environment name, tenant base URL).
- **Mechanism:** Created in **Manage → Global parameters**; referenced as `pipeline().globalParameters.<parameterName>`. If a dataset/data flow needs one, you pass it down via that resource's own parameter.
- **CI/CD angle (relevant to a modern-stack engineer):** the recommended pattern is **Manage hub → ARM template → "Include global parameters in ARM template"**, which lets each environment (dev/test/prod) override the value at deployment — the ADF way of doing environment promotion. (An older flow under Manage hub → Global parameters → "Include in ARM template" still works but is deprecated.) This config is only available in **Git mode** — it's disabled in "Live mode"/"Data Factory" mode.
- **Naming gotcha:** as above, `-` is illegal in the name (`InvalidTemplate` error); use `_`.
- **Reference-syntax flag:** the canonical ADF property syntax is `pipeline().globalParameters.<name>`. In the *Fabric migration* docs you'll see a function-style `@globalParameters('<name>')` form referenced — that is the legacy expression Fabric's migration tooling rewrites *to* the new variable-library reference `@pipeline.libraryVariables.x`. In classic ADF, use the property form. **(Flag: the doc surfaces differ — the property form is the one documented on the dedicated ADF "Global parameters" page; trust that for ADF.)**
- **Databricks / modern-stack bridge:** Global parameters ≈ a shared config dict or environment-scoped variables. In Fabric (the next-gen successor) they are being replaced by **Variable Libraries** (`@pipeline.libraryVariables.x`); the built-in upgrade tooling does *not* migrate them automatically. In Airflow this is `Variable.get()` / Airflow Variables; in Dagster it's run config / resources. Conceptually all the same: factory-wide constants overridable per environment.

**Takeaway:** Global parameters are factory-wide, env-overridable-via-ARM constants; reference `pipeline().globalParameters.x`; no hyphens; Git mode only for the CI/CD include.

#### 7. System variables — engine-provided run metadata

These are *not* user-defined; the ADF runtime fills them in. They split by **scope** (pipeline scope vs trigger scope), and using the wrong one returns null. Verified from the Learn "System variables" page:

**Pipeline scope** (reference anywhere in pipeline JSON):

| Variable | Value |
|---|---|
| `@pipeline().DataFactory` | Name of the factory/workspace the run is in |
| `@pipeline().Pipeline` | Pipeline name |
| `@pipeline().RunId` | ID (GUID) uniquely identifying *this* run |
| `@pipeline().TriggerType` | e.g. `ScheduleTrigger`, `BlobEventsTrigger`, or `Manual` |
| `@pipeline().TriggerId` / `.TriggerName` | ID / name of the invoking trigger |
| `@pipeline().TriggerTime` | Time the trigger **actually fired** (may differ slightly from scheduled time) |
| `@pipeline().GroupId` | ID of the group the run belongs to |
| `@pipeline()?.TriggeredByPipelineName` | Parent pipeline name — only set when invoked via Execute Pipeline; null otherwise. **Note the `?`** (null-safe operator). |
| `@pipeline()?.TriggeredByPipelineRunId` | Parent run ID, same null-safe caveat |

**Trigger scope** (reference inside the *trigger* JSON, to map onto pipeline parameters):

| Variable | Trigger type | Value |
|---|---|---|
| `@trigger().scheduledTime` | Schedule / Tumbling | When the trigger was *scheduled* to fire |
| `@trigger().startTime` | Schedule / Tumbling / Event | When it *actually* fired |
| `@trigger().outputs.windowStartTime` / `.windowEndTime` | Tumbling window | The slice's window boundaries (backfill) |
| `@triggerBody().fileName` / `.folderPath` | Storage event (Blob) | The file that fired the event (folderPath's first segment is the container) |
| `@triggerBody().event.eventType` / `.subject` / `.data.<key>` | Custom event (Event Grid) | Event payload fields |

> In **Azure Synapse**, the trigger-body accessors differ: use `@trigger().outputs.body.fileName`/`.folderPath` (storage event) and `@trigger().outputs.body.event` (custom event) instead of `@triggerBody()`.

- **No invisible operation — the trigger→pipeline handoff is *not* automatic:** This is the part people miss. `@trigger().startTime` is only resolvable **inside the trigger JSON**. To use trigger metadata *in the pipeline*, you must (a) define a pipeline parameter, (b) in the trigger, assign `"scheduledRunTime": "@trigger().scheduledTime"` to that parameter, and (c) inside the pipeline read **`@pipeline().parameters.scheduledRunTime`** — *not* `@trigger()`. The Learn docs state this directly: *"you can achieve this behavior by using a pipeline parameter. The start time and scheduled time for the trigger are set as the value for the pipeline parameter."* The trigger's system variable is poured *into* a pipeline parameter at fire time; the pipeline never reads the trigger directly.
- **UTC flag:** *"Trigger-related date/time system variables (in both pipeline and trigger scopes) return UTC dates in ISO 8601 format, for example, `2017-06-01T22:20:00.4061448Z`."* If you need a local-date partition folder, you must `convertFromUtc(...)` yourself — ADF does **not** silently localize.
- **Databricks bridge:** `@pipeline().RunId` ≈ the Lakeflow `job.run_id` / `{{run_id}}` task value. `@trigger().scheduledTime` ≈ Airflow's `{{ logical_date }}` / `data_interval_start`. The tumbling-window `windowStartTime`/`windowEndTime` pair is ADF's backfill mechanism, directly analogous to Airflow's `data_interval_start`/`end` for idempotent per-interval reruns — Tumbling Window triggers even support running past windows (backfill) and concurrency limits between **1 and 50**, which the simpler Schedule trigger does not.

**Takeaway:** System variables are engine-filled; pick the right scope (`pipeline()` vs `trigger()`); trigger metadata reaches the pipeline only by being mapped into a pipeline parameter; dates are UTC, ISO 8601 — convert yourself.

---

### The expression language: `@` vs `@{}`, and the coercion you can't see

Every dynamic value in ADF is an **expression** evaluated at runtime. The syntax has exactly one subtlety that causes real bugs, and it's about *type*.

- **`@expression`** — the *entire* JSON string value is the expression. Result keeps its **native type**.
- **`@{expression}`** — **string interpolation**: the expression is embedded inside a string, and the result is **always coerced to a string** (this is the invisible operation).
- **`@@`** — escapes a literal `@` (so a string that must start with `@` is written `@@`).

The Learn docs give this exact truth table. Say `myNumber = 42` and `myString = "foo"`:

| JSON value you write | What you get back |
|---|---|
| `"@pipeline().parameters.myString"` | `foo` (string) |
| `"@{pipeline().parameters.myString}"` | `foo` (string) |
| `"@pipeline().parameters.myNumber"` | `42` (**number**) |
| `"@{pipeline().parameters.myNumber}"` | `42` (**string**) |
| `"Answer is: @{pipeline().parameters.myNumber}"` | `Answer is: 42` (string) |
| `"Answer is: @@{pipeline().parameters.myNumber}"` | literal `Answer is: @{pipeline().parameters.myNumber}` |

- **The bug this causes:** if a downstream field needs an *integer* (e.g. a numeric comparison) or a non-string type, and you pass `@{...}`, ADF hands it a string and the activity may fail or compare wrong. Use bare `@...` when you need to preserve Int/Bool/Array/Object type; use `@{...}` only when you're building a string (file names, messages, connection-string fragments). To embed a number *into* a string deliberately, wrap it: `@concat('Answer is: ', string(pipeline().parameters.myNumber))`.
- **Databricks bridge:** `dbutils.widgets.get()` *always* returns a String — so Databricks engineers are used to `int(dbutils.widgets.get("n"))`. ADF is sneakier: bare `@` *preserves* type, `@{}` *destroys* it. The trap is that both look almost identical in the dynamic-content box.

**Takeaway:** `@` keeps the type, `@{}` stringifies it — choose deliberately, because the coercion is silent.

#### Common functions you'll reach for

All verified against the Learn function reference. Expressions start with `@`; functions nest freely.

| Function | Signature & behavior | Example → result |
|---|---|---|
| `concat` | Combine 2+ strings | `concat('Hello','World')` → `"HelloWorld"` |
| `coalesce` | First non-null arg. **Note:** empty string/array/object are *not* null | `coalesce(null,'hello','world')` → `"hello"` |
| `if` | `if(<bool>, <thenAny>, <elseAny>)` — both branches must be supplied | `if(equals(1,1),'yes','no')` → `"yes"` |
| `equals` / `greater` / `less` | Logical comparisons returning Bool | `greater(10,5)` → `true` |
| `formatDateTime` | Render a timestamp in a format | `formatDateTime(utcnow(),'yyyy-MM-dd')` → `"2026-06-30"` |
| `json` | Parse a string/XML into a JSON value/object. **If the string is null, returns an empty object** (silent) | `json('{"fullName":"Sophia Owen"}')` → object |
| `split` | Split a string on a delimiter → array | `split('a_b_c','_')` → `["a","b","c"]` |
| `int` | Parse a string into an Integer | `int('10')` → `10` |
| `item` | The current element inside a `ForEach` (see below) | `@item().table` |

- **Gotcha — `coalesce` and "empty ≠ null":** the docs state *"Empty strings, empty arrays, and empty objects are not null."* So `coalesce(variables('s'), 'default')` will **not** fall back to `'default'` when `s` is `""` — it returns `""`. This bites people doing "use default if blank" logic; for that you need `if(empty(variables('s')), 'default', variables('s'))`.
- **Gotcha — deep sub-field access uses `[]` not `.`:** to index into activity output with a parameter, the docs require bracket syntax: `@activity('actName').output.subfield1.subfield2[pipeline().parameters.subfield3].subfield4`.

**Takeaway:** Functions nest freely; watch the two silent behaviors — `coalesce` treats empty-but-not-null as a value, and `json(null)` returns `{}`.

---

### How a value flows down the chain (end-to-end trace)

This is the mental model to keep. A value originates at the **trigger** and cascades **trigger → pipeline parameter → dataset/linked-service parameter → the actual API call**, with reads at each layer using that layer's accessor.

**Worked trace — a scheduled daily load:**

1. **Trigger fires** at 02:00 UTC. The Schedule trigger JSON maps a system variable onto a pipeline parameter:
   ```json
   "parameters": { "loadDate": "@trigger().scheduledTime" }
   ```
2. **Pipeline run starts.** `loadDate` is now frozen, readable as `@pipeline().parameters.loadDate` (e.g. `"2026-06-30T02:00:00Z"`). `@pipeline().RunId` is assigned a fresh GUID.
3. **A Lookup activity** reads a control table and returns rows. Its output is reachable as `@activity('LookupTables').output.value` (all rows) or `@activity('LookupTables').output.firstRow.tableName` (first row). *(Verified limits: Lookup returns at most **5,000 rows** and **4 MB**; it fails if the size exceeds 4 MB, and silently returns only the first 5,000 if the row count is exceeded. The longest it runs before timeout is **24 hours**. The Azure Databricks Delta Lake connector is stricter — its Lookup caps at **1,000 rows**.)*
4. **A ForEach** iterates `@activity('LookupTables').output.value`. Inside the loop, the current row is `@item()`, so `@item().tableName` is this iteration's table. *(Verified limits: `batchCount` max **50** for parallelism, default **20**; up to **100,000** items total; you **cannot nest** a ForEach directly inside another ForEach or Until — use a child pipeline. Set/Append Variable inside a parallel ForEach is unsafe.)*
5. **Inside the loop, a Copy activity** uses a parameterized dataset and binds its parameter from the loop item and the pipeline param:
   ```json
   "inputs": [{
     "referenceName": "BlobDataset", "type": "DatasetReference",
     "parameters": { "path": "@concat('raw/', formatDateTime(pipeline().parameters.loadDate,'yyyy-MM-dd'), '/', item().tableName)" }
   }]
   ```
6. **Inside the dataset**, `folderPath` reads `@dataset().path` — the value injected in step 5. If the dataset's linked service is parameterized (e.g. `dbName`), the dataset passes that down too, and the LS reads `@{linkedService().dbName}`.

So the full read-chain by layer:

| Layer | What it reads | Source of the value |
|---|---|---|
| Trigger | `@trigger().scheduledTime` | ADF engine |
| Pipeline | `@pipeline().parameters.loadDate` | mapped from trigger |
| Loop | `@item().tableName` | the ForEach `items` array |
| Upstream output | `@activity('LookupTables').output.firstRow.x` | the Lookup activity |
| Dataset | `@dataset().path` | bound by the Copy activity |
| Linked service | `@{linkedService().dbName}` | passed down by the dataset |

- **Databricks bridge for the whole chain:** In Lakeflow Jobs you'd pass `{{job.trigger.time}}` / a job parameter into a notebook, read it with `dbutils.widgets`, and template your `spark.read.load(path)` directly in code — one hop. ADF's value is the *same idea* but routed through up to four declarative scopes because connection (linked service), shape (dataset), and orchestration (pipeline) are separate first-class objects. More indirection, but it's what enables one dataset/linked-service to be reused across hundreds of pipelines — the metadata-driven pattern ADF is built around.

**Takeaway:** A value enters at the trigger, is frozen into a pipeline parameter, then cascades into dataset/linked-service parameters; each layer reads it with *its own* accessor (`pipeline()`, `item()`, `activity()`, `dataset()`, `linkedService()`), and nothing reaches across scopes automatically — you wire every hop explicitly.


---

## 5. Dynamic / Metadata-Driven Pipelines

A metadata-driven pipeline is ADF's answer to the question: *"I have 200 source tables — am I really going to build 200 Copy activities?"* No. You build **one** parameterized Copy activity, store the list of tables (and their connection details) as **rows in a control table**, and let a `ForEach` loop drive it. This is the single most important production pattern in ADF, and it maps almost 1:1 onto a `dbutils.widgets`-driven Databricks notebook looped by a Lakeflow Job — except in ADF the loop, the parameterization, and the parallelism are all declarative JSON, not Python.

ADF terms used throughout, defined on first use:
- **IR (Integration Runtime)** — the compute that actually moves bytes. **Azure IR** is fully managed (cloud-to-cloud); **SHIR (Self-Hosted Integration Runtime)** is an agent you install on a VM to reach private/on-prem sources. Your Databricks-native equivalent is "which cluster/warehouse runs this" — but for *copy*, ADF's IR is closer to a managed data-movement fleet than a Spark cluster.
- **Linked service** — a connection definition (server, auth). ≈ a Databricks *connection* / Unity Catalog *external location* + credential.
- **Dataset** — a named pointer to a specific table/file *through* a linked service. ≈ a table reference.
- **Expression language** — ADF's `@{...}` interpolation, evaluated at runtime. `@pipeline().parameters.x`, `@item()`, `@activity('X').output...`. ≈ `dbutils.widgets.get("x")` + f-strings, but resolved by the ADF control plane, not by your code.

---

### The core building blocks: Lookup -> ForEach -> one parameterized Copy

The whole framework is three activities chained together.

- **What.** A **Lookup** activity reads the control table into the pipeline as a JSON array. A **ForEach** activity iterates that array. Inside the loop, a **single Copy activity** whose source/sink are *parameterized* handles every row.
- **Mechanism.** `Lookup.output.value` is a JSON array. You hand it to `ForEach.items`. Inside the loop, `@item()` is the current row object; `@item().TABLE_NAME` pulls a field. Those `@item()` values are passed down into a **parameterized dataset**, which substitutes them into the table/connection at runtime.
- **Example — the wiring expressions** (these are the exact strings you type into the UI):

  ```
  ForEach  -> Items:   @activity('LookupControlTable').output.value
  Copy src -> Query:   select * from @{item().TABLE_NAME}
  Sink dataset param:  @{item().TABLE_NAME}
  ```

- **Gotcha — the Lookup is a hard ceiling, and it is silent until it bites.** A Lookup returns **at most 5,000 rows** and **at most 4 MB** of output; beyond 5,000 it returns the *first* 5,000 rows with **no error and no warning** — your tail tables just silently never get copied. The 4 MB limit *does* fail the activity. (Connector caveat: the **Azure Databricks Delta Lake** connector caps Lookup at **1,000 rows**, not 5,000 — relevant to you directly, since your job touches Databricks.) Lookup also requires exactly **one** result set (zero or multiple result sets fail the activity) and times out at **24 hours**. Workaround for >5,000 control rows: a two-level pipeline (outer Lookup pages the control table, inner pipeline does the copy) — which is precisely the shape the built-in Copy Data Tool generates (next section).

> **Takeaway:** One parameterized Copy + a control table replaces N hand-built pipelines; just respect the 5,000-row / 4 MB Lookup cap (1,000 rows for the Databricks Delta Lake connector) or your "all tables" run will quietly become "first 5,000 tables."

---

### The control table

This is your metadata. It lives in Azure SQL DB (any tabular store works as the Lookup source, but SQL DB is canonical because you also write the watermark back to it via a stored procedure).

A minimal hand-rolled control table:

```sql
CREATE TABLE dbo.IngestionControl (
    Id                INT IDENTITY PRIMARY KEY,
    SourceServer      VARCHAR(255),
    SourceDb          VARCHAR(255),
    SourceSchema      VARCHAR(128),
    SourceTable       VARCHAR(128),
    WatermarkColumn   VARCHAR(128),   -- e.g. 'LastModifytime'
    SinkTable         VARCHAR(256),
    LoadType          VARCHAR(20),    -- 'Full' | 'Delta'
    Enabled           BIT DEFAULT 1
);
```

- **What.** Each row = one table to ingest, plus *how* to ingest it. Adding a source = `INSERT` a row. No pipeline redeploy.
- **Mechanism.** The Lookup query is just `SELECT * FROM dbo.IngestionControl WHERE Enabled = 1`. Every column becomes a field on `@item()` inside the loop.
- **Bridge.** This is conceptually the same as a YAML/asset config that a Dagster or Airflow DAG factory reads to generate tasks — except ADF reads it *at runtime each run*, so toggling `Enabled = 0` takes effect on the next trigger with zero deployment. The modern-stack equivalent (Airflow dynamic task mapping, Dagster `@asset` factories) generates tasks at *parse* time and usually needs a code push.

> **Takeaway:** The control table is the contract; the pipeline is generic machinery that reads it. Maintenance is `INSERT`/`UPDATE`, never redeploy.

---

### Real JSON: the parameterized dataset + linked service

This is the part people get wrong. To make ONE Copy serve N sources you must push parameters down through **both** the dataset *and* (optionally) the linked service.

**Parameterized linked service** — connect to different databases on the same logical SQL server without one linked service per DB. The parameter is referenced with `@{linkedService().DBName}` (note: `linkedService()`, not `dataset()`):

```json
{
  "name": "AzureSqlDatabase",
  "properties": {
    "type": "AzureSqlDatabase",
    "typeProperties": {
      "connectionString": "Server=tcp:myserver.database.windows.net,1433;Database=@{linkedService().DBName};User ID=user;Password=fake;Encrypt=True;Connection Timeout=30"
    },
    "parameters": { "DBName": { "type": "String" } }
  }
}
```

**Parameterized dataset** — the table name is a dataset parameter resolved with `@dataset().SinkTableName`:

```json
{
  "name": "SinkDataset",
  "properties": {
    "type": "AzureSqlTable",
    "linkedServiceName": { "referenceName": "AzureSqlDatabaseLinkedService", "type": "LinkedServiceReference" },
    "parameters": { "SinkTableName": { "type": "String" } },
    "typeProperties": { "tableName": { "value": "@dataset().SinkTableName", "type": "Expression" } }
  }
}
```

In the Copy activity's Sink tab you then bind that dataset parameter to the loop variable: `SinkTableName = @{item().TABLE_NAME}`.

- **No invisible operations — three traps the docs call out explicitly:**
  1. **IR, database *type*, and file-format *type* CANNOT be parameterized.** You cannot have one pipeline ingest from Oracle *and* SQL Server by parameterizing "connector type." You need a separate parameterized pipeline per source-type — but they can **share one control table**. This is a real architectural constraint, not a preference.
  2. **Never parameterize passwords/secrets.** Microsoft recommends storing the secret in Azure Key Vault and parameterizing the *Secret Name* instead. (Closest Databricks analog: `dbutils.secrets.get(scope, key)` — you parameterize the *key*, never the value.)
  3. **Parameter names with `-` (hyphen) have an open bug** (per the parameterize-linked-services doc) — use names without hyphens until it's resolved. The same page also flags an active bug with spaces in dataflow names.

> **Takeaway:** Parameterize the *table* and *DB name* freely; you cannot parameterize the connector type or IR, so plan one pipeline per source family sharing one control table.

---

### Incremental loading: the high-watermark pattern

Full reloads don't scale. The watermark pattern copies only rows changed since last run. This is ADF's equivalent of a Databricks `MERGE` driven by a `max(updated_at)` bookmark — but ADF makes the bookmark *explicit state* in a SQL table rather than implicit in Delta.

The pipeline inside the `ForEach` is **Lookup(old) -> Lookup(new) -> Copy -> Stored Procedure**:

| Step | Activity | What it does | Real expression |
|---|---|---|---|
| 1 | Lookup `LookupOldWaterMarkActivity` | Read last-saved watermark from the watermark table | `select * from watermarktable where TableName = '@{item().TABLE_NAME}'` |
| 2 | Lookup `LookupNewWaterMarkActivity` | Read current max watermark from the **source** | `select MAX(@{item().WaterMark_Column}) as NewWatermarkvalue from @{item().TABLE_NAME}` |
| 3 | Copy | Copy only the delta slice between old and new | see dynamic query below |
| 4 | Stored Procedure | Persist the new watermark back to the control/watermark table | calls `usp_write_watermark` |

**The dynamically built Copy source query** (this exact string is the heart of the pattern — it matches the ADF "incrementally load from multiple tables" tutorial verbatim):

```
select * from @{item().TABLE_NAME}
where @{item().WaterMark_Column} > '@{activity('LookupOldWaterMarkActivity').output.firstRow.WatermarkValue}'
  and @{item().WaterMark_Column} <= '@{activity('LookupNewWaterMarkActivity').output.firstRow.NewWatermarkvalue}'
```

Read the chained references literally: `@activity('LookupOldWaterMarkActivity').output.firstRow.WatermarkValue` reaches into the *named* Lookup activity's output and grabs the `WatermarkValue` column of its first row. `firstRow` is how you get a scalar out of a Lookup that returned one row.

**Execution trace** (table `customer_table`, watermark column `LastModifytime`):
1. `LookupOldWaterMarkActivity` -> `firstRow.WatermarkValue = 2017-09-05 08:06:00`
2. `LookupNewWaterMarkActivity` -> `firstRow.NewWatermarkvalue = 2017-09-08 00:00:00` (someone updated a row)
3. Copy runs `... where LastModifytime > '2017-09-05 08:06:00' and LastModifytime <= '2017-09-08 00:00:00'` -> copies exactly the one changed row.
4. Stored proc writes `2017-09-08 00:00:00` back. Next run starts from there.

The stored procedure that closes the loop:

```sql
CREATE PROCEDURE usp_write_watermark @LastModifiedtime datetime, @TableName varchar(50)
AS
BEGIN
  UPDATE watermarktable SET [WatermarkValue] = @LastModifiedtime WHERE [TableName] = @TableName
END
```

You wire its parameters in the Stored Procedure activity (these are the exact bindings from the ADF tutorial):
- `LastModifiedtime (DateTime)` = `@{activity('LookupNewWaterMarkActivity').output.firstRow.NewWatermarkvalue}`
- `TableName (String)` = `@{activity('LookupOldWaterMarkActivity').output.firstRow.TableName}`

- **No invisible operations — the boundary is `>` old and `<=` new, deliberately.** Strictly-greater on the low end avoids re-copying the boundary row already captured last run; less-than-or-equal on the high end is inclusive because you captured `new` from the source *now*. Get this asymmetric and you either duplicate or drop boundary rows. (The official ADF tutorials use exactly this `> old AND <= new` convention — keep the watermark-write consistent with it.)
- **Gotcha — `firstRow` of a Lookup returning zero rows is null**, and string-interpolating null into the query yields `> ''`, which can copy everything or error. Seed the watermark table with an initial low value (`'1/1/2010'`) per table so `LookupOldWaterMarkActivity` always returns a row.
- **Bridge.** In Databricks you'd do this as `MERGE INTO target USING (changed rows) ...` with the bookmark tracked in a Delta table or via Auto Loader / SDP (Spark Declarative Pipelines, formerly DLT) checkpoints. ADF's watermark is the *manual* version of what Auto Loader's checkpoint and `cloudFiles` do for you automatically. The trade: ADF gives you an inspectable SQL bookmark you fully control; Auto Loader gives you an opaque-but-automatic one.

> **Takeaway:** Two Lookups bracket the delta, one Copy moves it, one stored proc advances the bookmark. The bookmark is explicit SQL state — that's the whole reason this is more transparent (and more your-responsibility) than a Delta MERGE.

---

### The built-in shortcut: Metadata-driven Copy Data Tool

You don't have to hand-build any of the above. ADF's **Copy Data Tool** has a **"Metadata-driven copy task"** mode that generates the control tables, the SQL scripts, *and* the parameterized pipelines for you.

- **What.** A wizard: point it at sources, pick full vs. delta per table, pick a destination, set max concurrency. It emits two SQL scripts (one for the control tables, one for the stored procedure) and three pipelines.
- **Mechanism — what gets generated:**
  - **Two control tables:** a **main control table** (one row per object: `SourceObjectSettings`, `CopySourceSettings`, `DataLoadingBehaviorSettings` (Full vs. Delta), `TaskId` for ordering — copied `ORDER BY [TaskId] DESC`, `CopyEnabled` 1/0) and a **connection control table** (connection settings, used when you parameterized the linked service).
  - **Three-level pipeline** — `TopLevel` (a Lookup `GetSumOfObjectsToCopy` + a `ForEach` `CopyBatchesOfObjectsSequentially` that batches), `MiddleLevel` (splits a batch into groups to dodge the 5,000-row Lookup cap, via a `ForEach` `DivideOneBatchIntoMultipleGroups` + Lookup `GetObjectsPerGroupToCopy`), `BottomLevel` (a `ForEach` `ListObjectsFromOneGroup` -> a **Switch** `RouteJobsBasedOnLoadingBehavior` that routes each object to a `FullLoadOneObject` Copy or a `DeltaLoadOneObject` Copy + `GetMaxWatermarkValue` Lookup + `UpdateWatermarkColumnValue` stored proc).
  - A **stored procedure** to update the watermark in the main control table after each delta run.
- **Gotcha — known limitations baked into the generated code:**
  - **IR, database type, and file-format type can't be parameterized** (same constraint as hand-rolled) — so multiple source *types* need multiple generated pipeline sets, but they can share one control table.
  - The generated SQL uses **`OPENJSON`**, so a SQL Server hosting the control table must be **SQL Server 2016 (13.x) or later** (DB compatibility level 130+). Azure SQL Database / Managed Instance / Synapse support `OPENJSON` natively.
  - Editing the control table via the tool (right-click the TopLevel pipeline -> **Edit control table**) **does not redeploy the pipeline** — it only regenerates a SQL script you must rerun (the three-level pipeline structure is fixed; only the data in the control table changes).
  - The wizard's **"Number of concurrent copy tasks"** defaults to **20** — this becomes the `MaxNumberOfConcurrentTasks` pipeline parameter, editable per-run without redeploy.

| | Hand-rolled framework | Metadata-driven Copy Data Tool |
|---|---|---|
| Control table | You design it | Auto-generated (main + connection) |
| Pipeline depth | 1 level (you add levels for >5k rows) | 3 levels, auto-handles the Lookup cap |
| Full + Delta routing | You build the `If`/`Switch` | Built-in `Switch` |
| Flexibility | Total | Fixed structure; edit data only |
| Best when | Custom logic, non-copy steps | "Just copy thousands of tables at scale" |

> **Takeaway:** For pure bulk copy, let the tool generate the three-level framework — it already solves the 5,000-row Lookup cap and Full/Delta routing. Hand-build only when you need transforms or non-Copy steps inside the loop.

---

### ForEach parallelism and batch limits

The loop's parallelism is where throughput — and write-conflict bugs — live.

- **What.** `ForEach` runs iterations in parallel by default; `batchCount` caps the concurrency.
- **Mechanism — the exact numbers (verified against current docs):**
  - `isSequential: false` (default) -> parallel; `true` -> one-at-a-time.
  - `batchCount` = upper concurrency limit. **Default 20, maximum 50.** The docs state it explicitly: this is "the upper concurrency limit, but the for-each activity will not always execute at this number" — so at most `batchCount` items run at once, but the engine may run fewer.
  - **Maximum 100,000 items** per `ForEach`.
- **No invisible operations — three sharp edges:**
  1. **`SetVariable` inside a parallel `ForEach` is unsafe.** Per the docs, pipeline variables are *global to the whole pipeline*, not scoped to a `ForEach` iteration; parallel iterations race on the same variable. Either set `isSequential: true` or push the variable handling into a child pipeline via `Execute Pipeline`.
  2. **`ForEach` cannot be nested inside another `ForEach` (or `Until`).** Workaround: outer pipeline's `ForEach` calls an inner pipeline that holds the second loop.
  3. **Raising `batchCount` does not guarantee more throughput** — it's a *ceiling* to protect your source/sink from concurrent-write contention, not a throttle-up knob. If iterations write to the *same* sink file concurrently you get errors; different files/tables are fine.

  ```json
  {
    "name": "IterateControlTable",
    "type": "ForEach",
    "typeProperties": {
      "isSequential": false,
      "batchCount": 10,
      "items": { "value": "@activity('LookupControlTable').output.value", "type": "Expression" },
      "activities": [ /* the Lookup->Lookup->Copy->SProc chain */ ]
    }
  }
  ```

- **Bridge.** `batchCount` ≈ a Lakeflow Job's *max concurrent runs* / task concurrency, or Airflow's `max_active_tis_per_dag`. The "variables are global, not iteration-scoped" trap has no Spark equivalent — in a notebook each widget read is local; in ADF a pipeline variable is shared mutable state across parallel branches, so treat it like a thread-shared variable without a lock.

> **Takeaway:** `batchCount` defaults to 20, caps at 50, items cap at 100,000; it's a safety ceiling, not a turbo button — and never mutate pipeline variables inside a parallel loop.

---

### Tumbling-window trigger for time-sliced incremental

When "incremental" means "process one fixed time slice per run, reliably, including catching up on history," you want a **tumbling-window trigger** rather than a schedule trigger.

- **What.** A trigger that fires once per fixed, non-overlapping (tumbling) time window — every hour, every day — and exposes the window's start/end to the pipeline so the pipeline filters source data *to that slice*. (Minimum interval is 15 minutes; valid frequencies are Minute, Hour, Month.)
- **Mechanism.** Two system variables: `@trigger().outputs.windowStartTime` and `@trigger().outputs.windowEndTime`. You pass them as pipeline parameters in the trigger definition, then use them in the Copy source query:

  ```
  @formatDateTime(trigger().outputs.windowStartTime, 'yyyy-MM-dd HH:mm:ss.fff')
  @formatDateTime(trigger().outputs.windowEndTime,   'yyyy-MM-dd HH:mm:ss.fff')
  ```
  For a 1-hour trigger, the 1:00–2:00 AM window yields `windowStartTime = 2017-09-01T01:00:00Z`, `windowEndTime = 2017-09-01T02:00:00Z`. The pipeline copies only `WHERE event_time >= @start AND event_time < @end`. The window itself *is* the watermark — no watermark table needed.
- **Tumbling vs. Schedule trigger (verified):**

  | Feature | Tumbling window | Schedule |
  |---|---|---|
  | **Backfill** (run past windows) | Supported — set `startTime` in the past, it generates all historical windows | Not supported |
  | **Reliability** | 100% — every window from start, no gaps | Less reliable |
  | **Retry policy** | Supported (default `retryPolicy.count = 0`; `intervalInSeconds` default 30, min 30) | Not supported |
  | **Concurrency** | Explicit, **1–50** concurrent runs (`maxConcurrency`) | Not supported |
  | **Window vars** | `windowStartTime` / `windowEndTime` (plus `scheduledTime` / `startTime`) | Only `scheduledTime` / `startTime` |
  | **Pipeline relationship** | **One-to-one** (one trigger -> one pipeline) | Many-to-many |

- **No invisible operations — the immutability trap:** after a tumbling-window trigger is **published, you cannot edit `interval` or `frequency`** (the docs note this restriction exists so `triggerRun` reruns and dependency evaluations stay correct). Changing the cadence means a new trigger. Also, backfill is *automatic and deterministic*: if `startTime` is in the past, it computes `M = (CurrentTime - TriggerStartTime) / WindowSize` and fires `M` past runs **oldest-to-newest**, honoring the concurrency limit — great for catch-up, but it *will* hammer your source on first publish if `startTime` is far back. Set concurrency deliberately. (Microsoft's own guidance: for a long backfill period, do an initial historical load instead.)
- **Bridge.** This is ADF's version of an Airflow DAG with `schedule_interval` + `data_interval_start`/`data_interval_end` and `catchup=True` — the same "each run owns a data interval, and missed intervals backfill deterministically" model. Schedule triggers are the `catchup=False`, fire-and-forget cron equivalent. Databricks Lakeflow Jobs cron schedules behave like ADF *schedule* triggers (no backfill of missed windows, no per-window variable); the tumbling-window data-interval semantics are an Airflow/Dagster idea, and ADF is the Azure-native place you get them.

> **Takeaway:** Tumbling-window = per-slice processing + free backfill + the window *as* the watermark. Use it for time-partitioned incremental; just remember `interval`/`frequency` freeze at publish and a far-back `startTime` triggers a deterministic backfill storm.

---

### Where this sits in the bigger picture (and two limits that bite at scale)

- **DIU (Data Integration Unit — a bundled CPU+memory+network unit on Azure IR):** Copy throughput scales with DIUs, allowed range **4–256**, default "Auto" (the service picks an optimal value per source-sink pair and data pattern). DIU applies to Azure IR only, **not SHIR** (SHIR throughput scales by adding nodes instead). For partitioned parallel reads, docs suggest degree-of-parallelism ≈ `(DIUs or SHIR node count) × (2 to 4)` — and note that some sinks (e.g., Synapse, Fabric Warehouse) cap at ~32 concurrent queries, so an over-large value can trigger throttling.
- **SHIR scale:** up to **4 nodes** per self-hosted IR, for high availability and throughput on private/on-prem sources.
- **The 896 KB activity-payload limit** — the quiet killer of metadata-driven designs. Each activity run's payload (its config + referenced datasets + linked services + values passed in) must stay under **896 KB**. If you pass *actual data* (e.g., a fat Lookup result) from activity to activity through the loop, you can blow this limit. Keep `@item()` rows small (metadata, not data), and let Copy move the bulk directly source->sink rather than routing it through pipeline parameters.

> **Takeaway:** Tune throughput with DIUs (4–256, Azure IR) or SHIR nodes (max 4); keep control-table rows lean so you never trip the 896 KB per-activity payload ceiling.


---

## 6. Schema Evolution & Schema Drift

Two completely different mechanisms hide under the word "schema" in ADF, and conflating them is the #1 source of confusion. They live in two different execution engines:

| Mechanism | Where it runs | What it solves | Engine |
|---|---|---|---|
| **Copy activity schema mapping** | Copy activity (`translator` property) | How a *known* source column lands in a *known* sink column, with type conversion | Integration Runtime data-movement engine (.NET-based, **not** Spark) |
| **Mapping Data Flow schema drift** | Mapping Data Flow source/sink transformations | How to survive *unknown / changing* columns at runtime | **Spark** cluster (Azure IR-managed) |

A useful first anchor to your Databricks world: **Copy activity mapping is the static, contract-bound case** (like `df.write` to a table whose schema you declared). **Schema drift is the dynamic case** (like Auto Loader discovering columns it has never seen). We'll build both up, then bridge each to its Databricks-native equivalent.

> **Terms defined once, used throughout:** *IR* = Integration Runtime (the compute that actually moves/transforms data; Azure IR is serverless Microsoft-managed, SHIR = Self-Hosted IR runs on your own VM for private networks). *MDF* = Mapping Data Flow (visually-authored, Spark-backed transformation). *DIU* = Data Integration Unit (a unit of Copy activity power). *Projection* = an MDF source's declared column list + types (its compile-time schema view).

---

### Part 1 — Copy activity schema mapping

The Copy activity reads from one source dataset, writes to one sink dataset, and `translator` (the JSON property) describes the column-to-column mapping. There are two modes.

#### 1a. Default mapping (auto-mapping by name)

- **What:** If you specify no `translator`, Copy activity maps source → sink **by column name, case-sensitive**.
- **Mechanism (no invisible operations):**
  - If the **sink does not yet exist** (e.g. writing files), source field names are **persisted as-is** as the sink column names.
  - If the **sink already exists**, it must contain **all** columns being copied from the source — a source column with no name match in the sink causes failure.
  - Default mapping **natively supports flexible schemas and source-to-sink schema drift from execution to execution**: all data returned by the source flows to the sink (the docs' exact phrasing is "supports flexible schemas and schema drift from source to sink from execution to execution"). This is ADF's *zero-config* schema-drift story (distinct from MDF drift below); the canonical example is file-to-file.
- **Gotcha — headerless text:** If the source is a delimited text file **without a header line**, there are no column names to match on, so **explicit mapping is required** (you map by `ordinal`, see 1b).
- **Gotcha — case sensitivity:** `CustomerId` and `customerid` are *different* columns under default mapping. This bites when a source system changes column casing.

> **Takeaway:** Default mapping = "copy everything, match by exact name" — zero-config and drift-tolerant, but rigid on casing and on pre-existing typed sinks.

#### 1b. Explicit mapping (the `translator`)

Explicit mapping lets you copy a subset, rename, reorder, change types, or reshape tabular↔hierarchical. The activity executes in three steps: **(1)** read source + determine source schema → **(2)** apply your mapping → **(3)** write to sink.

Real JSON — rename three columns from a tabular source to a tabular sink:

```json
"translator": {
  "type": "TabularTranslator",
  "mappings": [
    { "source": { "name": "Id" },               "sink": { "name": "CustomerID" } },
    { "source": { "name": "Name" },             "sink": { "name": "LastName"  } },
    { "source": { "name": "LastModifiedDate" }, "sink": { "name": "ModifiedDate" } }
  ]
}
```

Key properties inside each `mappings` entry (per the docs):

| Property | Purpose | Notes |
|---|---|---|
| `name` | Column/field name | Tabular source/sink |
| `ordinal` | 1-based column index | **Required** for delimited text **without** a header line |
| `path` | JSON path of the field | Hierarchical sources/sinks (Cosmos DB, MongoDB, REST). Root fields start `$`; fields inside the `collectionReference` array start from the array element **without** `$` |
| `type` | Interim data type | Usually leave unset |
| `culture` / `format` | For `Datetime`/`Datetimeoffset` | e.g. `format: "yyyy-MM-dd"`, default culture `en-us` |

Plus `collectionReference` at the `translator` level: for a hierarchical source, point it at the JSON path of an **array** to cross-apply — each array element becomes one output row. (Note from the docs: if the array marked as collection reference is empty, the entire record is skipped.)

> **Takeaway:** Explicit mapping is your contract — partial copy, rename, reshape. It is the ADF analogue of an explicit `SELECT col AS newcol` projection rather than `SELECT *`.

#### 1c. Type conversion (the silent coercion you must know)

Copy activity does **not** convert source-native types straight to sink-native types. It goes through **ADF interim types** in three hops (call this out — it is otherwise invisible):

```
source native type  →  ADF interim type  →  (auto-convert as needed)  →  sink native type
```

Interim types: `Boolean, Byte, Byte array, Datetime, DatetimeOffset, Decimal, Double, GUID, Int16, Int32, Int64, SByte, Single, String, Timespan, UInt16, UInt32, UInt64`. (Example mapping: SQL Server `int` → interim `Int32`; `bit` → interim `Boolean`; `uniqueidentifier` → interim `Guid`.)

The type-conversion experience is controlled under `translator.typeConversionSettings` (enable with `typeConversion: true`):

| Setting (JSON) | What it does | Default |
|---|---|---|
| `allowDataTruncation` | Permit lossy conversion, e.g. **decimal → integer**, **DatetimeOffset → Datetime** | **`true`** |
| `treatBooleanAsNumber` | `true` → `1`, `false` → `0` | false |
| `dateTimeFormat` / `dateTimeOffsetFormat` / `timeSpanFormat` / `dateFormat` | Format strings when converting to/from string | — |
| `culture` | e.g. `en-us`, `fr-fr` | en-us |

```json
"translator": {
  "type": "TabularTranslator",
  "typeConversion": true,
  "typeConversionSettings": {
    "allowDataTruncation": true,
    "treatBooleanAsNumber": false,
    "dateTimeFormat": "yyyy-MM-dd HH:mm:ss.fff"
  }
}
```

**Gotchas (no invisible operations):**
- `allowDataTruncation` defaults to **`true`** — so a `decimal(18,4)` → `int` copy **silently drops the fraction** unless you flip it to `false`. This is the loudest "implicit mutation" in Copy activity.
- `typeConversion` is **on by default** for copy activities created via the UI **since late June 2020**, but **off** for ones created before then (backward compat). For *programmatic* authoring you must set `typeConversion: true` explicitly.
- Type conversion is supported **only for tabular↔tabular**. For **hierarchical** sources/sinks there is **no system-defined type conversion** — types pass through as-is.
- For types mapping to interim `Decimal`, Copy activity supports **precision up to 28**; beyond that, cast to string in your source SQL query.

> **Takeaway:** Every cross-type Copy passes through interim types, and `allowDataTruncation=true` is a default that will lose data quietly — pin it to `false` when correctness matters.

#### 1d. Parameterized / dynamic mapping (templatize a copy)

To build one generic copy pipeline for many objects, parameterize the entire `translator`:

1. Define a pipeline parameter of **type Object**, e.g. `mapping`.
2. On the Mapping tab, add dynamic content binding `translator` to it:

```json
"typeProperties": {
  "source": { ... },
  "sink": { ... },
  "translator": {
    "value": "@pipeline().parameters.mapping",
    "type": "Expression"
  }
}
```

3. At runtime, pass the **full `translator` object** as the parameter value. For a tabular→tabular copy that value is literally:

```json
{"type":"TabularTranslator","mappings":[
  {"source":{"name":"Id"},"sink":{"name":"CustomerID"}},
  {"source":{"name":"Name"},"sink":{"name":"LastName"}}
]}
```

A common pattern: a `Lookup` activity reads a control table of mapping definitions, a `ForEach` iterates objects, and `@item().mapping` (or `@activity('LookupMappings').output.value`) feeds each Copy's `translator`. This is the ADF analogue of config-table-driven dynamic notebooks in Databricks.

> **Takeaway:** Dynamic mapping turns the `translator` into runtime data — the metadata-driven copy framework lives here.

#### 1e. Additional columns (synthesize columns at copy time)

You can append columns the source doesn't have via the source-side `additionalColumns` array:

```json
"source": {
  "type": "DelimitedTextSource",
  "additionalColumns": [
    { "name": "SourceFile",  "value": "$$FILEPATH" },
    { "name": "IdCopy",      "value": "$$COLUMN:CustomerId" },
    { "name": "PipelineRun", "value": { "value": "@pipeline().RunId", "type": "Expression" } },
    { "name": "Env",         "value": "prod" }
  ]
}
```

Allowed `value` forms (call out the reserved tokens):
- **`$$FILEPATH`** — reserved; the source file's path relative to the folder path specified in the dataset (file-based sources). Your lineage column, equivalent to Spark's `_metadata.file_path` / `input_file_name()`.
- **`$$COLUMN:<source_column_name>`** — duplicate an existing source column.
- **Expression** — any ADF expression (system variables like `@pipeline().RunId`, upstream activity output).
- **Static value** — a literal constant.

Remember to **map these in the Mapping tab** so they reach the sink. (Related but separate: `enablePartitionDiscovery` + `partitionRootPath` auto-extract Hive-style `year=2020/month=08` folder values as columns — the ADF equivalent of Spark partition-column inference.)

> **Takeaway:** `additionalColumns` is your audit/lineage stamp (`$$FILEPATH`, run id, env) injected without touching the source.

#### 1f. Hierarchical / complex sources

Three reshape directions are supported via the Mapping tab (Advanced editor exposes raw JSON paths):
- **Tabular → tabular** (rename/subset).
- **Hierarchical → tabular** — flatten using `path` JSON paths + `collectionReference` to cross-apply an array into rows.
- **Tabular/Hierarchical → hierarchical** — note: when copying tabular source to hierarchical sink, writing **to an array inside an object is not supported**, and there is **no system-defined type conversion** on the hierarchical path.

For heavier reshaping the docs explicitly say to use **Data Flow** instead.

---

### Part 2 — Mapping Data Flow SCHEMA DRIFT

Now switch engines. MDF runs on **Spark**. Here "schema drift" is a first-class, architectural choice, defined precisely by the docs:

> Schema drift is the case where your sources often change metadata — fields, columns, and types can be added, removed, or changed on the fly.

**The mechanism that matters most:** when you accept schema drift, ADF treats the flow as **late-binding**. You **lose early-binding** of columns and types — meaning **drifted column names do not appear in the schema views** of downstream transformations at design time. You cannot click them; you must address them by *pattern* or by *name function*. (Contrast: a non-drift flow is early-binding — every column is known and clickable in each transformation's Inspect tab.)

#### 2a. The "projection" and what "drifted" means

- A source transformation's **projection** = the column list + types taken from the dataset (or imported on the Projection tab for inline datasets).
- A **drifted column** = a column that arrives at runtime but is **not in the projection**.

#### 2b. Allow schema drift — in the SOURCE

- **What:** Checkbox **Allow schema drift** on the source transformation.
- **Mechanism:** When on, **all incoming fields are read at execution time and passed through the entire flow to the sink**, even ones absent from the projection.
- **Silent default to call out:** drifted columns **arrive as `string`** by default. Check **Infer drifted column types** to have ADF auto-infer their types instead.
- Related Projection-tab schema options (inline datasets):

| Option | Effect |
|---|---|
| **Allow schema drift** | Let new, undefined columns flow through |
| **Infer drifted column types** | Auto-detect drifted column types (else everything is `string`) |
| **Validate schema** | **Fail the data flow** if any projected column/type does **not** match the discovered source schema (schema-enforcement / contract) |
| **Use projected schema** | Skip per-file schema auto-discovery across many files (perf) — apply the stored projection to every file |

> **Takeaway:** Source drift = "read columns I never declared." The hidden default — drifted columns are `string` unless you infer types — is the single most common surprise.

#### 2c. Allow schema drift — in the SINK (+ auto-map)

- **What:** **Allow schema drift** on the sink lets you **write additional columns on top of the sink's defined schema**.
- **Mechanism / gotcha:** With sink drift on, you **must also turn on the Auto-mapping slider** on the sink's Mapping tab. Auto-map on → all incoming columns (including drifted ones) are written. Auto-map off → you must use **rule-based mapping** to land drifted columns, or they are dropped.
- **Sink Validate schema:** fails the flow if any column in the sink projection isn't found in the sink store, or types mismatch — a contract check on the *write* side.

> **Takeaway:** Sink drift without Auto-mapping (or a rule) silently drops the drifted columns — both switches must agree.

#### 2d. Referencing drifted columns — three tools

Because drifted columns aren't in schema views, you reach them one of three ways (this is the core skill):

**(1) `byName()` / `byPosition()` — late-binding column access.**
- `byName('movieId')` returns the drifted column's value by name; `byPosition(3)` by 1-based ordinal.
- They return an untyped value, so wrap in a cast: `toInteger(byName('movieId'))`, `toString(byName('ProductNumber'))`.
- The **Map Drifted** quick action (Data Preview tab, debug mode on) auto-generates a Derived Column doing exactly this — e.g. it writes `toInteger(byName('movieId'))` and thereby promotes `movieId` into the schema views downstream.
- `byName()` works across streams too: `toString(byName('ProductNumber','source1')) == toString(byName('ProductNumber','source2'))` in an Exists transformation — that's the docs' explicit "late binding without hardcoding" example.

**(2) Column patterns — in Derived Column / Aggregate / Window.**
A boolean match expression over five column attributes:

| Token | Meaning |
|---|---|
| `name` | incoming column name |
| `type` | data type |
| `stream` | the source/transformation name the column belongs to |
| `position` | 1-based ordinal position |
| `origin` | the transformation where the column originated / was last updated |
| `$$` | the value/name of each match (think `this`) |
| `$0` | the matched column name (scalar) / hierarchy path (complex) |

**Column pattern — real example:** match every `double` column and round it, keeping the same name:

```
match condition:  type == 'double'
name as:          $$
value:            round($$, 2)
```

Or the classic "cast everything that looks like a total" — `instr(name, 'total') > 0` → `toDouble($$)`.

**(3) Rule-based mapping — in Select / Sink.**
Each rule = a **match condition** (left expression, boolean over `name/type/stream/position/origin`) + a **name-as** rule (right expression using `$$`).
- Example: match string columns with short names — condition `type=='string' && length(name) < 6`, name-as `$$ + '_short'` → a column `test` becomes `test_short`.
- **Gotcha (call out):** if a rule-based mapping is the *only* mapping, **columns that don't match are dropped**. Patterns match both drifted and defined columns.
- **Regex mapping:** a chevron option matches by regex on the name, e.g. pattern `(r)` matches any name containing lowercase `r`, transformed via `$$`. With multiple regex groups, refer to a specific match with `$n` (e.g. `$2` for the second match).
- **Default behavior to know:** any projection with **more than 50 columns defaults to a rule-based mapping** that matches every column and outputs the input name (so large schemas auto-pass-through); fewer than 50 columns default to fixed mappings, which **cannot** map or rename a drifted column.

**The canonical "auto-map drift into an existing table" Data Flow Script snippet** (place a Select before the Sink, leave Sink mapping on auto-map):

```
select(mapColumn(each(match(true()))),
       skipDuplicateMapInputs: true,
       skipDuplicateMapOutputs: true) ~> automap
```

`match(true())` matches **every** column; `each(...)` applies a rule per match — this is how you load an unknown/dynamic column set into a fixed DB schema.

> **Takeaway:** `byName()` for one known-by-name column; column patterns for "operate on every column where X"; rule-based mapping for bulk select/sink projection. All three exist *because* drift kills the clickable schema view.

#### 2e. Validation / Assert — drift's safety net

Drift accepts anything, so you add **data-quality gates**:
- **Validate schema** (source/sink) — structural contract; fails the run on mismatch.
- **Assert transformation** — row-level rules: `Expect true` (e.g. domain range), `Expect unique`, `Expect exists` (cross-stream, requires a second incoming stream). Optional **Fail data flow** flag fails immediately; otherwise tag rows and test downstream with `isError()` / `hasError()`, and route failures to an error file via the sink's **Errors** tab. (Note: the Assert transformation is **not currently supported in Dataflow Gen2** — the Fabric successor.)

> **Takeaway:** Schema drift + Assert is "let unknown columns through, but enforce the values that matter."

---

### Part 3 — Schema DRIFT vs Schema EVOLUTION (don't conflate)

| | **Schema drift** | **Schema evolution** |
|---|---|---|
| Question | "Can my pipeline *survive* unknown/changing **input** columns at runtime?" | "Does my **sink/target** schema *grow* to absorb new columns?" |
| Scope | Read/transform side (MDF source→sink pass-through) | Write side / table metadata (Delta, Parquet) |
| ADF surface | Allow schema drift, byName(), patterns, rule-based map | Sink **Allow schema drift** + the **target format/connector** accepting new columns (e.g. Delta sink `mergeSchema`) |
| Failure if absent | Columns dropped or flow breaks on name binding | Write **rejected** because incoming columns don't match target |

Drift is about *tolerating* change in flight; evolution is about *persisting* that change into the destination schema. In ADF they meet at the **sink**: allowing sink drift + auto-map sends extra columns to the store, and whether the **store** absorbs them is the store's evolution feature (Delta `mergeSchema`, etc.).

---

### Part 4 — Bridge to what you already know (Databricks)

You handle this daily on Azure Databricks at Apollo Gen2. Here's the precise mapping.

#### 4a. ADF source schema drift ↔ Auto Loader schema evolution

| Concept | ADF Mapping Data Flow | Databricks Auto Loader (`cloudFiles`) |
|---|---|---|
| Tolerate unknown incoming columns | **Allow schema drift** on source | `cloudFiles.schemaEvolutionMode` |
| Where new-column knowledge persists | In-flight only (late binding); nothing persisted by the source | **`cloudFiles.schemaLocation`** tracks the evolving schema across runs |
| Default type of new columns | **`string`** (unless *Infer drifted column types*) | For JSON/CSV/XML, **all columns inferred as `string`** unless `cloudFiles.inferColumnTypes=true` |
| Behavior on a brand-new column | Silently flows through | Default mode **`addNewColumns`**: stream **fails** with `UnknownFieldException`, adds the column to the tracked schema, **resumes on restart** (Lakeflow Jobs auto-restart) |
| "Park the weird data" | Rule-based map / Assert error rows | **`_rescued_data`** column (`rescuedDataColumn`) captures type-mismatched / unexpected / case-mismatched values |
| Strict contract | Source **Validate schema** = fail on mismatch | `cloudFiles.schemaEvolutionMode = failOnNewColumns` |
| Known types, infer the rest | *Infer drifted column types* + projection | `cloudFiles.schemaHints` (e.g. `"id long, amount double"`) |

**The single biggest behavioral difference to internalize:** ADF schema drift **never stops** for a new column — it just passes it through (late-bound). Auto Loader's default (`addNewColumns`) **deliberately fails the stream once**, records the new schema, then resumes on restart — a *fail-then-evolve* design so the schema is durably tracked. ADF MDF has **no persisted schema-location concept** in its drift model; each run rediscovers.

Auto Loader's `cloudFiles.schemaEvolutionMode` values, per the docs:
- **`addNewColumns`** (default when no schema is supplied) — fail-then-evolve as above.
- **`rescue`** — never evolves, never fails on schema change; all new columns land in the rescued-data column.
- **`failOnNewColumns`** — fails and does **not** restart until you fix the schema or remove the offending file.
- **`none`** (default *when you supply an explicit schema*) — ignores new columns, no rescue unless `rescuedDataColumn` is set.
- **`addNewColumnsWithTypeWidening`** — like `addNewColumns` but also widens supported types (`int`→`long`); unsupported changes (e.g. `int`→`string`) go to the rescued-data column. (Public Preview, Databricks Runtime 16.4+.)

#### 4b. ADF sink drift ↔ Delta `mergeSchema` / Spark schema evolution

| Concept | ADF | Azure Databricks / Delta |
|---|---|---|
| Let target absorb new columns | Sink **Allow schema drift** + **Auto-mapping** on | `.option("mergeSchema", "true")` on write, or `MERGE WITH SCHEMA EVOLUTION` / `INSERT WITH SCHEMA EVOLUTION` |
| Session-wide evolution | (no equivalent) | `spark.databricks.delta.schema.autoMerge.enabled=true` — session-wide (applies to every write in the session), so scope it carefully |
| Replace schema entirely | Recreate / overwrite sink dataset | `.option("overwriteSchema", "true")` |
| Default = enforce, not evolve | Default mapping requires sink to contain all columns | **Schema enforcement on write** — Delta **rejects** mismatched writes by default |

Mechanism parallels you can lean on:
- `mergeSchema` is **additive only** — it adds new source columns to the Delta table, does **not** drop existing columns and does **not** change existing column types (type *widening*, e.g. `int`→`long`, needs `delta.enableTypeWidening` / Auto Loader's `addNewColumnsWithTypeWidening`). That additive-only rule is exactly the spirit of ADF sink "write additional columns on top of what's defined."
- Delta's **schema enforcement** (reject by default) is the conceptual twin of ADF's **Validate schema** (fail on mismatch). Both are the "contract" guardrail.

#### 4c. ADF Assert ↔ Lakeflow expectations (and where the modern stack differs)

| | ADF Assert | Lakeflow SDP expectations |
|---|---|---|
| Unit | Per-row rule | Per-row SQL boolean constraint |
| Pass / quarantine / stop | `isError()`/`hasError()` tags + Errors sink; **Fail data flow** flag | `@dp.expect` (**warn**, default) / `expect_or_drop` / `expect_or_fail` |
| Metrics | Data preview / run output | Emitted to the **pipeline event log** automatically (for `warn`/`drop`; `fail` halts on the first bad record, so no metrics are recorded) |

The Assert/`Expect true` ⇄ `@dp.expect(... , "age BETWEEN 0 AND 120")` correspondence is near-exact; the difference is Lakeflow's three named violation policies (warn/drop/fail) vs ADF's fail-or-tag-and-route model. (Lakeflow's current product name is **Lakeflow Spark Declarative Pipelines**, SDP; the Python decorators are `@dp.expect*`.)

**Where Airflow / Dagster (the modern-stack roadmap) differ:** neither has a built-in schema-drift *engine*. They're **orchestrators**, not transformation engines — schema handling lives in the *task's* code (a Spark/dbt/Python step). The closest first-class analogues are **dbt** `on_schema_change` (`append_new_columns` / `sync_all_columns` / `fail` / `ignore`) for incremental models, and **Dagster asset checks** / **Great Expectations** / **Soda** for the Assert role. So the ADF lesson to carry over: in ADF the drift handling is *inside the data-flow engine*; in an Airflow/Dagster world you push that responsibility down into dbt/Spark and let the orchestrator only sequence and alert.

> **Section takeaway:** Copy activity mapping = static, contract-bound, runs on the IR data-movement engine (interim-type conversion, `allowDataTruncation` defaults to *lossy*). MDF schema drift = dynamic, late-binding, runs on Spark (byName/patterns/rule-based mapping because columns leave the schema view). "Drift" = tolerate unknown input columns; "evolution" = grow the target schema. Your Auto Loader `schemaEvolutionMode` + `schemaLocation` and Delta `mergeSchema` are the durable-persistence cousins of ADF's in-flight, non-persisted drift model — with the key contrast that Auto Loader *fails-then-evolves-then-resumes* while ADF MDF *silently passes through*.


---

## 7. Triggers, Monitoring & CI/CD

Triggers decide *when* a pipeline runs, monitoring tells you *what happened*, and CI/CD moves your factory *from dev to prod safely*. In Databricks terms: triggers are the ADF equivalent of a Lakeflow Job schedule/file-arrival trigger, monitoring is the Jobs run UI + system tables, and CI/CD is your Databricks Asset Bundle (DAB) / Terraform promotion flow. The big mental-model difference: ADF's deployment unit is a single **ARM (Azure Resource Manager) template** generated from Git, and that one fact drives almost every CI/CD gotcha below.

---

### Triggers — the four types

A trigger is a separate JSON resource that references a pipeline. You author it, then **Publish** *and* **Start** it (publishing alone does not arm it — it stays in `Stopped` runtime state until started).

| Trigger type | Fires on | Pipeline relationship | Backfill | Retry built in | Concurrency control |
|---|---|---|---|---|---|
| **Schedule** | Wall-clock recurrence (cron-like) | many-to-many (1 trigger → N pipelines, N triggers → 1 pipeline) | No (future only) | No | No |
| **Tumbling window** | Fixed contiguous time slices | **one-to-one** (exactly 1 pipeline) | **Yes** (start time in the past) | **Yes** (`retryPolicy`) | **Yes** (`maxConcurrency` 1–50) |
| **Storage event** | Blob created / deleted on ADLS Gen2 or GPv2 | many-to-many | No | No | No |
| **Custom event** | Any event you publish to an Event Grid custom topic | many-to-many | No | No | No |

> Source: [Trigger type comparison](https://learn.microsoft.com/azure/data-factory/concepts-pipeline-execution-triggers#trigger-type-comparison).

#### Schedule trigger

- **What:** runs on a calendar recurrence — every 15 min, daily at 18:00, Mondays + Thursdays, etc.
- **Mechanism:** a `ScheduleTrigger` with a `recurrence` block. Only two system variables are exposed: `@trigger().scheduledTime` (when it *should* have fired) and `@trigger().startTime` (when it *actually* fired — these can differ slightly under load).
- **Example** (15-minute recurrence):

```json
{
  "name": "trigger1",
  "properties": {
    "type": "ScheduleTrigger",
    "typeProperties": {
      "recurrence": {
        "frequency": "Minute",
        "interval": 15,
        "startTime": "2026-03-03T04:38:00Z",
        "timeZone": "UTC"
      }
    },
    "pipelines": [{
      "pipelineReference": { "referenceName": "demo_pipeline", "type": "PipelineReference" },
      "parameters": { "parameter_1": "@trigger().startTime" }
    }]
  }
}
```

- **Gotcha:** schedule triggers have **no gap-free guarantee** — if the factory was down for a slot, that slot is simply skipped (no catch-up). If you need every slice processed exactly once with no gaps, use a tumbling window trigger instead. Databricks Lakeflow Jobs schedules behave the same way as the schedule trigger.

*Takeaway: use schedule triggers for "run roughly on this clock" work where a missed slot is harmless.*

#### Tumbling window trigger — the workhorse for time-sliced ETL

This is the one that maps to *incremental, partition-by-time* loads — exactly the Synapse Link / CDC-style hourly or daily slice processing you already do.

- **What:** generates a contiguous, **gap-free** series of fixed time windows from `startTime` forward, each window producing exactly one run.
- **Minimum interval is 15 minutes.** `frequency` and `interval` **cannot be edited after the trigger is created** (changing them would break rerun and dependency math) — you must drop and recreate.
- **The killer feature — window start/end:** each window exposes its boundaries via the system variables `@trigger().outputs.windowStartTime` and `@trigger().outputs.windowEndTime` (the trigger-authoring UI labels these `WindowStart` / `WindowEnd`). You pass these into pipeline parameters and filter your source query on them. This is how you process "yesterday's slice" deterministically. (Databricks analog: passing `{{job.start_time}}` / a date widget into a notebook and filtering the source.)

**Backfill — the part that's genuinely different from Databricks.** If you set `startTime` in the past, ADF computes:

> **M = (CurrentTime − TriggerStartTime) / WindowSize**

and immediately generates **M** past runs *in parallel*, executed *oldest-to-newest*, honoring `maxConcurrency`, **before** any future runs. So a daily trigger with a `startTime` 30 days ago spawns 30 backfill runs on start. ([backfill execution order](https://learn.microsoft.com/azure/data-factory/how-to-create-tumbling-window-trigger#tumbling-window-trigger-type-properties)). **No invisible operation here to miss:** this happens the moment you start the trigger — for a long history, MS explicitly recommends doing an initial historical load instead.

- **Retry:** `retryPolicy` with `count` (default **0** = no retries) and `intervalInSeconds` (default **30**, minimum 30). In the case of pipeline failures, the tumbling window trigger automatically retries the referenced pipeline run, reusing the **same input parameters**, with no user intervention.
- **Concurrency:** `maxConcurrency` (1–50) caps how many ready windows run in parallel.
- **Dependency:** a tumbling window trigger can `dependsOn` another tumbling window trigger so it only fires after the upstream window succeeds. Two flavors: `TumblingWindowTriggerDependencyReference` (depend on a *different* trigger) and `SelfDependencyTumblingWindowTriggerReference` (depend on your *own* prior window — serializes runs, e.g. "today can't start until yesterday finished"). A self-dependency `offset` **must be negative**, and you can set a `size` to depend on a different-sized window. **A tumbling window trigger can depend on a maximum of five other triggers.** This is ADF's native answer to Airflow/Dagster cross-task data dependencies and `depends_on_past=True`.

```json
{
  "name": "twTrigger",
  "properties": {
    "type": "TumblingWindowTrigger",
    "typeProperties": {
      "frequency": "Hour",
      "interval": 1,
      "startTime": "2026-01-01T00:00:00Z",
      "maxConcurrency": 10,
      "retryPolicy": { "count": 2, "intervalInSeconds": 60 },
      "dependsOn": [{
        "type": "SelfDependencyTumblingWindowTriggerReference",
        "size": "01:00:00",
        "offset": "-01:00:00"
      }]
    },
    "pipeline": {
      "pipelineReference": { "referenceName": "hourly_load", "type": "PipelineReference" },
      "parameters": {
        "wStart": "@trigger().outputs.windowStartTime",
        "wEnd": "@trigger().outputs.windowEndTime"
      }
    }
  }
}
```

- **Gotcha:** dependencies only support *other tumbling window* triggers (`dependsOn` rejects any non-tumbling-window trigger) — you can't make a tumbling window wait on a *schedule* trigger. And a window stuck in `Waiting on dependency` will sit there until the upstream completes (or you cancel it from Monitoring — you can cancel a window in `Waiting`, `Waiting on dependency`, or `Running` state).

*Takeaway: tumbling window = gap-free, retryable, time-sliced loads with real upstream/self dependencies and built-in backfill. Reach for it for any "process each hour/day exactly once" job.*

#### Storage event trigger

- **What:** fires on **Blob created** (`Microsoft.Storage.BlobCreated`) or **Blob deleted** (`Microsoft.Storage.BlobDeleted`) in an ADLS Gen2 or General-purpose v2 account — ADF's equivalent of Auto Loader / file-arrival triggers, but it kicks off a whole pipeline rather than streaming files into a table.
- **Mechanism:** a `BlobEventsTrigger`. Under the hood ADF asks **Azure Event Grid** to create an event subscription on the storage account; Event Grid *pushes* the event (not Kafka-style pull). ADF itself never makes direct contact with the storage account for the trigger — the subscribe/listen path is relayed entirely through Event Grid.
- **Filtering:** only two patterns — `blobPathBeginsWith` and `blobPathEndsWith`; at least one is required. No general wildcards. When you specify container + folder you must include the `/blobs/` segment, e.g. `/sample-data/blobs/event-testing/` (for *begins-with* the UI inserts `/blobs/` automatically) ending with `.csv`.
- **Limits / gotchas:**
  - Due to an Event Grid limit, **max 500 storage event triggers per storage account**.
  - Only ADLS Gen2 / GPv2 supported (SFTP events on these accounts also need the SFTP Data API specified under filtering).
  - If the storage account is behind a private endpoint, you must grant access to trusted Azure services (Event Grid) or configure Event Grid private endpoints.
  - Setting filters *too broad* matches many files and can spike both run count and cost — the UI's Data Preview screen exists to sanity-check this before you Finish.

*Takeaway: storage event = "a file landed, go process it" — but it's pipeline-level fan-out via Event Grid, not row-level streaming like Auto Loader.*

#### Custom event trigger

- **What:** fires on an arbitrary event you (or another service) publish to an **Event Grid custom topic** — e.g. an upstream app emits `copysucceeded`. This is the escape hatch for true event-driven orchestration across systems.
- **Mechanism:** a `CustomEventsTrigger` scoped to the topic's ARM resource ID. Unlike storage events, **ADF does not create the topic for you** — you create it first. Events must follow the Event Grid event schema (`topic`, `subject`, `id`, `eventType`, `eventTime`, `data`, `dataVersion`, …).
- **Filtering:** `subjectBeginsWith` / `subjectEndsWith` (both optional), plus a list of `eventType` values (OR-matched, case-insensitive), plus **advanced filters** on payload values (`NumberIn`, `StringContains`, `BoolEquals`, etc. — a subset of Event Grid's operators). Event Grid limits apply: **5 advanced filters and 25 filter values across all filters** per trigger, 512 chars per string value, max 5 values for `in`/`not in` operators, and keys can't contain `.`.
- **Gotcha (sharp edge):** if your parameter mapping references a key like `@triggerBody().event.data.callback` and that key is **missing** from the payload, the **trigger run fails and no pipeline run is created** — the expression can't be evaluated (you get a "property doesn't exist" error). Defensive payloads matter.

*Takeaway: custom event = cross-service event-driven runs; you own the Event Grid topic and the payload contract.*

---

### Passing data from trigger → pipeline

This trips people up because of one rule: **system variables live in the *trigger* JSON; pipelines only read *parameters*.** You map the system variable to a pipeline parameter in the trigger definition, then everywhere in the pipeline you reference the *parameter*, never the system variable.

- **Mechanism:** in the trigger's `parameters` block, assign `"myStart": "@trigger().outputs.windowStartTime"`. In the pipeline you then use `@pipeline().parameters.myStart`.
- **No invisible coercion:** the value flows as-is into the parameter. If you reference `@trigger()...` directly inside an *activity*, it won't resolve — only the mapped parameter does.

System variables per trigger scope ([control-flow-system-variables](https://learn.microsoft.com/azure/data-factory/control-flow-system-variables)):

| Trigger | Key system variables |
|---|---|
| Schedule | `@trigger().scheduledTime`, `@trigger().startTime` |
| Tumbling window | `@trigger().outputs.windowStartTime`, `@trigger().outputs.windowEndTime`, plus the two above |
| Storage event | `@triggerBody().fileName`, `@triggerBody().folderPath` (first segment = container name), `@trigger().startTime` |
| Custom event | `@triggerBody().event.eventType`, `@triggerBody().event.subject`, `@triggerBody().event.data.<keyName>`, `@trigger().startTime` |

Worked storage-event trace: blob `MoviesDB.csv` lands at `sample-data/event-testing` → trigger captures `@triggerBody().folderPath = "sample-data/event-testing"` and `@triggerBody().fileName = "MoviesDB.csv"` → mapped to params `sourceFolder` / `sourceFile` → a Copy activity reads `@pipeline().parameters.sourceFile`.

- **Synapse gotcha:** in *Synapse* pipelines (your job's other half) the body path differs — you must use `@trigger().outputs.body.fileName` / `@trigger().outputs.body.folderPath` and `@trigger().outputs.body.event`, **not** `@triggerBody()...`. Same concept, different accessor.

This is the conceptual cousin of `dbutils.widgets.get("file")` receiving a value passed at job-trigger time.

*Takeaway: map system variable → pipeline parameter in the trigger, consume the parameter in the pipeline. Mind the Synapse `.outputs.body` variant.*

---

### Monitoring

#### Pipeline & activity runs

- **What:** the Monitor hub lists triggered runs with columns: Pipeline Name, Run Start/End, Duration, **Triggered By**, Status (`Failed` / `Succeeded` / `In Progress` / `Canceled` / `Queued`), Annotations, Parameters, Error, **Run** (Original / Rerun / Rerun (Latest)), Run ID. Click a run → activity-run list → **Output** to see per-activity JSON (including `billableDuration`). A **Gantt** view groups runs by name/annotation. ([monitor-visually](https://learn.microsoft.com/azure/data-factory/monitor-visually)).
- **No invisible operation:** **auto-refresh is not supported** — you must hit Refresh manually. And **ADF retains run data for only 45 days** ([data-storage](https://learn.microsoft.com/azure/data-factory/monitor-data-factory#data-storage)). Past that, runs vanish from the UI and from `Get-AzDataFactoryV2PipelineRun` (queries for older windows return no error, just no rows) unless you've routed logs to Log Analytics. Databricks Jobs run history retention is far longer and queryable via system tables — ADF forces you to externalize for any real history.

#### Rerun — and the subtle rerun rules

- **Rerun whole run:** hover a run → **Rerun** (restarts from the top).
- **Rerun from failed activity:** if an activity fails/times-out/cancels, select **Rerun from failed activity** — skips already-succeeded activities and resumes at the failure point. Huge for expensive upstream Copy steps. (Lakeflow Jobs "repair run" is the direct analog.)
- **Rerun from a chosen activity:** in the activity-runs view, pick any activity → **Rerun from activity**.
- **Gotchas in the rerun skip logic** ([rerun behavior](https://learn.microsoft.com/azure/data-factory/monitor-visually#rerun-pipelines-and-activities)):
  - `ForEach` **always re-loops** over the items it receives; inner activities may still be skipped per the rerun rules.
  - `If`/`Switch` conditions are **always re-evaluated**, and all inner activities are evaluated; inner activities may still be skipped per the rerun rules, but activities such as `Execute Pipeline` *will* rerun.
  - `Until` re-evaluates its expression and loops; inner activities may still be skipped.
  - `Execute Pipeline` triggers the child pipeline, though activities inside the child may still be skipped per the rerun rules.
  - **Rerun with new parameters counts as a brand-new run** — it won't appear under the original's rerun groupings.

#### Alerts via Azure Monitor

- **What:** in Monitoring → **Alerts**, create metric alert rules. The canonical one: **Failed pipeline runs > 0**. Others: Total entities count, Total factory size (GB). You can alert on any metric / log / activity-log entry in the [monitoring data reference](https://learn.microsoft.com/azure/data-factory/monitor-data-factory-reference).
- **Pipeline-level email** is separate: a common pattern is a **Web activity** on the failure path calling a Logic App, as in the [send-email tutorial](https://learn.microsoft.com/azure/data-factory/how-to-send-email).

#### Diagnostic logs → Log Analytics

- **What / why:** because of the 45-day cap, route diagnostic logs via a **Diagnostic Setting** to a **Log Analytics workspace** (or Storage / Event Hubs). You can fan multiple factories into one workspace for cross-factory dashboards and custom alerts.
- **Mechanism:** with the setting in **Resource-Specific** mode, logs land in dedicated tables you query with **KQL (Kusto Query Language)** — chiefly `ADFPipelineRun`, `ADFActivityRun`, `ADFTriggerRun` (plus SSIS-specific tables). (In **Azure-Diagnostics** mode they instead flow into the single `AzureDiagnostics` table.) Log Analytics inherits the Azure Monitor schema but capitalizes the first letter of each column (`correlationId` → `CorrelationId`) and drops the `Level` column.

```kusto
ADFActivityRun
| where TimeGenerated >= ago(24h)
| where Status != 'InProgress' and Status != 'Queued'
| where FailureType != 'UserError'
| summarize failureCount = countif(Status != 'Succeeded') by bin(TimeGenerated, 1h), ActivityName
| top 5 by failureCount desc nulls last
```

This is your equivalent of querying Databricks `system.lakeflow` job-run tables — ADF just makes it opt-in.

*Takeaway: the ADF Monitor UI is real-time but ephemeral (45 days, manual refresh). For history, SLAs, and cross-factory analytics, ship diagnostics to Log Analytics (Resource-Specific mode) and query `ADFPipelineRun` / `ADFActivityRun` in KQL.*

---

### CI/CD — Git integration and ARM promotion

#### Git integration: collaboration branch vs publish branch

- **What:** connect the factory to Azure Repos or GitHub. You author in **feature branches**, open PRs into the **collaboration branch** (default `main`). You can **publish to the live ADF service only from the collaboration branch**.
- **The publish branch (`adf_publish`):** when you click **Publish**, ADF generates the **ARM template** of the whole factory and commits it to a branch called **`adf_publish`** by default. Override the name by adding `publish_config.json` (`{"publishBranch": "factory/adf_publish"}`) to the collaboration branch root; ADF only reads this file when it loads the factory, so refresh the browser after changing it. ([source-control](https://learn.microsoft.com/azure/data-factory/source-control#configure-publishing-settings)).
- **No invisible operation:** Git mode and "Live/Data Factory" mode are different. Some features (ARM parameter config, *include global parameters in ARM template*) are **only available in Git mode**.

Two flavors of the publish step:

| Flow | Who builds the ARM template | Manual step? |
|---|---|---|
| **Classic** | The ADF UI **Publish** button writes ARM templates to `adf_publish` | Yes — a human clicks Publish |
| **Automated** ([CI/CD improvements](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery-improvements)) | A DevOps build pipeline runs the npm package `@microsoft/azure-data-factory-utilities` (Validate all + Export ARM template) on every merge to the collaboration branch, emitting the ARM template as a build artifact; the release pipeline then points at that artifact instead of `adf_publish` | No |

Both are supported; the automated flow removes the manual UI click and gives true CI. This is the same architectural choice as classic ADF-UI publish vs. Databricks Asset Bundles / Terraform — let the build agent generate the artifact, not a person.

#### The ARM template + parameterization

Publishing produces two files in `<FactoryName>/` of the publish branch:
- **`ARMTemplateForFactory.json`** — the resources.
- **`ARMTemplateParametersForFactory.json`** — the parameters you override per environment.

- **Promotion dev → test → prod:** point an **ARM Template Deployment** task (Azure Pipelines release, or `az deployment group create`) at those two files, set the target subscription/RG, and pass **Override template parameters** per stage. ([automate-azure-pipelines](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery-automate-azure-pipelines)).
- **Deployment mode — critical:** use **Incremental**. In **Complete** mode, *any resource in the resource group not present in the template is **deleted***. That's a foot-gun that can wipe sibling resources.
- **256-parameter ceiling:** the default ARM template parameterizes a lot. If your factory grows past **256 parameters** the template becomes invalid. Fixes: (1) a custom `arm-template-parameters-definition.json` in the branch root to *reduce* which properties get parameterized (this doesn't change the 256 limit itself — it lowers the count); (2) refactor pipeline params to **global parameters**; (3) split into multiple factories. Separately, for very large factories ADF auto-emits **linked templates** in a `linkedTemplates` folder (`ArmTemplate_master.json` + `ArmTemplate_0.json`, `ArmTemplate_1.json` …) to get around the 4-MB total ARM template size limit; these require a storage account + SAS token at deploy time.

#### Per-environment overrides: linked services, global parameters, IR

This is the heart of "the same factory, different connections per stage."

- **Linked services:** parameterize the connection-determining property (server name, account URL). **Best practice with Key Vault:** keep a **separate Key Vault per environment** but use the **same secret names** across stages — then only the *vault name* is a parameter, and you don't have to parameterize each connection string. ([CI/CD best practices](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery#best-practices-for-ci-cd)). This mirrors using Databricks **secret scopes** keyed identically across workspaces.
- **Global parameters** ([author-global-parameters](https://learn.microsoft.com/azure/data-factory/author-global-parameters)): factory-wide constants referenced as `pipeline().globalParameters.<name>`, designed to be **overridden per environment** during CI/CD. Enable **Manage hub → ARM template → "Include global parameters in ARM template"** (the newer mechanism — doesn't clobber factory-level settings, no extra PowerShell). **Gotcha:** parameter names **can't contain `-`** (use `_`) or ARM rejects the template; and "Include global parameters in an ARM template" is **Git-mode only** (disabled in live/Data-Factory mode).
- **Integration Runtime per environment — the rule that bites everyone:** the **IR name, type, and sub-type must be identical across environments**. If dev has a **SHIR (Self-Hosted Integration Runtime — compute you install on your own VM to reach on-prem/private networks)**, then test and prod must *also* define that IR as self-hosted with the same name (ARM deployment fails with `DataFactoryPropertyUpdateNotSupported` if you try to change an existing IR's type). You don't redeploy the SHIR binary per stage. For *sharing* one SHIR across stages, configure it as a **linked self-hosted IR** (IR sharing is supported only for self-hosted IRs, not Azure-SSIS), and a common pattern is a dedicated "ternary" factory that only holds the shared IRs. ([CI/CD best practices](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery#best-practices-for-ci-cd)).
- **Triggers must be stopped before deploy:** a trigger in `started` state can't be updated, so deployment fails if you try to change an active trigger. The standard fix is pre/post-deployment scripts that **stop triggers before** and **restart them after** deployment. The automated-publish npm artifact already contains these scripts (a Ver2 script can stop/start only the *modified* triggers instead of all of them). ([sample pre/post-deployment script](https://learn.microsoft.com/azure/data-factory/continuous-integration-delivery-sample-script)).
- **Hotfix flow:** branch from the last-deployed commit, fix in ADF Studio on that branch, Export ARM template, check into `adf_publish`, deploy to test+prod, then merge the fix back to dev so it isn't lost.

*Takeaway: ADF deploys one Git-generated ARM template per factory; promote dev→test→prod with **Incremental** mode and per-stage parameter overrides; keep IR *name + type* identical across stages, same-named secrets in per-env Key Vaults, and let global parameters carry environment-specific constants.*

---

### Cost model

ADF billing is consumption-based with **three core meters** plus the extras. Crucially, **integration runtime time is prorated per minute and rounded UP** (1 min 1 sec → billed 2 min). ([plan-manage-costs](https://learn.microsoft.com/azure/data-factory/plan-manage-costs); [apply-finops](https://learn.microsoft.com/azure/data-factory/apply-finops)).

| Cost area | Meter | What you pay for | Key mechanics / gotchas |
|---|---|---|---|
| **Orchestration** | **Activity Runs** (priced per 1,000) | Every activity execution **plus each trigger instance counts as one activity run** | A 1-Copy + 1-Databricks pipeline = **3** activity runs per execution (1 trigger + 2 activities). Pricing calculator rounds runs to nearest 1,000. |
| **Copy execution (Azure IR)** | **DIU-hours** (Data Integration Unit) | Copy activity throughput × duration | DIU default auto-set (e.g. 4); DIU-hours = (minutes/60) × DIU × runs |
| **Data flow** | **vCore-hours** | Mapping data flow execution + debug on a managed Spark cluster | Charged by **compute type** (general purpose / memory optimized / compute optimized) × **vCores** × duration |
| **External/pipeline activity** | execution hours | e.g. external compute (Databricks, HDInsight) dispatch time | billed separately as External Pipeline Activity execution |
| **SHIR** | data-movement / activity execution (no DIU meter) | ADF charges for data-movement + pipeline/external activities run on the SHIR **plus** the VM you host it on | There is **no** DIU-hours meter for SHIR (DIU is Azure-IR copy only); data movement on SHIR is still billed by ADF at the self-hosted rate (see the data-pipeline pricing page) on top of the VM cost |
| **SSIS IR** | node uptime | lift-and-shift SSIS packages | by instance type × duration |
| Operations | Read/Write + Monitoring | artifact CRUD + monitoring calls | "typically negligible"; **doesn't file under per-pipeline billing** |

**Data flow TTL — the cost lever to know:**
- A mapping data flow runs on a **just-in-time Spark cluster** that takes minutes to spin up. **Time To Live (TTL)** keeps the cluster warm after a run so the next data flow reuses it (faster, but you pay for the warm window).
- **Debug session default TTL is 60 minutes** — and an open debug session bills the whole time it's alive. MS's worked (hypothetical) example: an engineer leaves debug on for an 8-hour workday on 8 compute-optimized cores at $0.193/core-hour = 8 × 8 × $0.193 = **$12.35/day**. ([apply-finops](https://learn.microsoft.com/azure/data-factory/apply-finops#example-scenarios)). Turn debug off when you walk away.
- **Gotcha:** if you set TTL on an **Azure IR**, data-flow activities running on it **won't itemize under per-pipeline billing** — they fall back to a factory-level line item. ([per-pipeline limitations](https://learn.microsoft.com/azure/data-factory/plan-manage-costs#monitor-costs)).

**Visibility:** the Monitor UI's **Consumption** report (per pipeline run) shows quantities per meter (units, not dollars). For chargeback, opt into **per-pipeline detailed billing** (Manage → Factory setting). That setting is **not** exported in the ARM template, so dev/test/prod can carry different billing behaviors. Three meters file under a factory-level fall-back line item rather than per pipeline: Data Factory Operations (Read/Write + Monitoring), SSIS IR nodes, and data flows on a **TTL-configured Azure IR**.

> **Verification note / flagged item:** Microsoft Learn defines the *meters and worked examples* above, but the **exact per-unit list prices** (e.g. $ per 1,000 activity runs, $ per DIU-hour, $ per vCore-hour) live on the [Azure Data Factory pricing page](https://azure.microsoft.com/pricing/details/data-factory/), **not** in Learn docs, and the per-core figures in the FinOps article are explicitly labeled *hypothetical*. Treat dollar amounts as illustrative and confirm current rates on the pricing page for your region. Mapping-data-flow vCore-hours can be discounted with **ADF Data Flow reserved capacity** (1-year/3-year commitments per compute type).

*Takeaway: three meters — orchestration (per activity run, **+1 per trigger fire**), copy (DIU-hours on Azure IR), data flow (vCore-hours, watch TTL/debug). SHIR has no DIU meter — you pay ADF's self-hosted data-movement rate plus the VM. ADF rounds IR time up to the minute. Learn gives the model; the pricing page gives the rates.*

---

### Quick limits cheat-sheet (verified against current docs)

| Item | Value |
|---|---|
| Tumbling window min interval | 15 min; `frequency`/`interval` immutable after create |
| Tumbling window `maxConcurrency` | 1–50 |
| Tumbling window dependency targets | max 5 (other tumbling-window triggers only) |
| Storage event triggers per storage account | 500 (Event Grid limit) |
| Custom event advanced filters / values | 5 filters, 25 values total; 512 chars per value; 5 values per `in`/`not in` |
| Run history retention (Monitor UI / SDK) | 45 days |
| ForEach `batchCount` | default 20, max 50; max 100,000 items |
| Lookup activity | ≤ 5,000 rows, ≤ 4 MB output, 24-hr timeout |
| SHIR nodes | up to 4 (HA + scale-out) |
| ARM template parameters | max 256 |
| Max activities per pipeline | 120 |


---

## 8. Capstone — End-to-End Metadata-Driven Ingestion Framework

## Capstone — One Metadata-Driven Ingestion Framework, End to End

Everything above converges here. We build **one** pipeline that ingests **N on-prem SQL Server tables** into ADLS Gen2 / Azure SQL, copying only changed rows (high-watermark incremental), surviving column changes (schema drift), driven entirely by a **control table** — add a source by `INSERT`ing a row, never by redeploying. This is the production pattern; the Databricks analog is a `dbutils.widgets`-driven notebook looped by a Lakeflow Job, except every hop here is declarative JSON.

We assemble it in the exact order ADF executes it.

---

### 0. The compute substrate: a SHIR for the on-prem source

Because the source is a private SQL Server, the Copy must run on a **SHIR (Self-Hosted Integration Runtime — ADF software on a Windows VM inside your network, outbound-only over 443)**. The source *linked service* binds to it via `connectVia`; by the IR-precedence rule (**SHIR > managed-VNet Azure IR > global Azure IR**), the whole copy then runs on the SHIR. Credentials live in **Key Vault** (parameterize the *secret name*, never the password). For Parquet output, the SHIR host needs a **Java runtime (JRE 8 / JDK / OpenJDK)** — the classic first-run trap.

```json
{
  "name": "OnPremSqlServer",
  "properties": {
    "type": "SqlServer",
    "typeProperties": {
      "connectionString": "Server=sqlprod01;Database=@{linkedService().DBName};",
      "password": { "type": "AzureKeyVaultSecret",
                    "store": { "referenceName": "KV_LS", "type": "LinkedServiceReference" },
                    "secretName": "sqlprod-password" }
    },
    "parameters": { "DBName": { "type": "String" } },
    "connectVia": { "referenceName": "SHIR_DC1", "type": "IntegrationRuntimeReference" }
  }
}
```

Note `@{linkedService().DBName}` — the **linked service is parameterized**, so one connection object serves every database on that server. (Reminder: you *cannot* parameterize the IR, the database type, or the file-format type — so one parameterized pipeline per source family, sharing one control table.)

---

### 1. The control table — the contract

Each row = one table to ingest, plus *how*. Maintenance is `INSERT`/`UPDATE`; the pipeline is generic machinery that reads it at runtime each run.

```sql
CREATE TABLE dbo.IngestionControl (
    Id              INT IDENTITY PRIMARY KEY,
    SourceDb        VARCHAR(255),
    SourceSchema    VARCHAR(128),
    SourceTable     VARCHAR(128),
    WatermarkColumn VARCHAR(128),   -- e.g. 'LastModifytime'
    SinkTable       VARCHAR(256),
    Enabled         BIT DEFAULT 1
);
-- a companion watermark table, seeded low so the first run isn't NULL
CREATE TABLE dbo.watermarktable (TableName VARCHAR(256) PRIMARY KEY, WatermarkValue DATETIME);
INSERT dbo.watermarktable VALUES ('Orders', '2010-01-01');
```

Bridge: this is a Dagster `@asset` factory / Airflow DAG-factory config — except ADF reads it **at runtime**, so toggling `Enabled = 0` takes effect next trigger with **zero deployment** (the modern stack would need a code push at parse time).

---

### 2. The pipeline: Lookup → ForEach → (Lookup-old → Lookup-new → Copy → SProc)

The outer Lookup reads the control table; the ForEach iterates it; inside the loop the four-step watermark chain runs per table.

```json
{
  "name": "IngestOnPremTables",
  "properties": {
    "parameters": { "DBName": { "type": "String", "defaultValue": "Sales" } },
    "activities": [
      {
        "name": "LookupControlTable", "type": "Lookup",
        "typeProperties": {
          "source": { "type": "AzureSqlSource",
            "sqlReaderQuery": "SELECT * FROM dbo.IngestionControl WHERE Enabled = 1" },
          "firstRowOnly": false
        }
      },
      {
        "name": "ForEachTable", "type": "ForEach",
        "dependsOn": [ { "activity": "LookupControlTable", "dependencyConditions": ["Succeeded"] } ],
        "typeProperties": {
          "items": { "value": "@activity('LookupControlTable').output.value", "type": "Expression" },
          "isSequential": false,
          "batchCount": 10,
          "activities": [ /* the four steps below */ ]
        }
      }
    ]
  }
}
```

**The 5,000-row / 4 MB Lookup cap is the silent killer here:** beyond 5,000 control rows the Lookup returns the *first* 5,000 with no error — your tail tables silently never copy. (The **Azure Databricks Delta Lake** connector caps Lookup at **1,000 rows** — relevant since your job touches Databricks.) For >5,000 sources, page the control table with a two-level pipeline (exactly what the built-in Metadata-Driven Copy Data Tool generates).

---

### 3. Inside the loop — the high-watermark incremental chain

Four activities bracket and move the delta. The boundary is deliberately `> old AND <= new` (strictly-greater low end avoids re-copying last run's boundary row; inclusive high end because `new` was captured from the source *now*).

```json
[
  {
    "name": "LookupOldWatermark", "type": "Lookup",
    "typeProperties": {
      "source": { "type": "AzureSqlSource",
        "sqlReaderQuery": {
          "value": "select WatermarkValue, TableName from dbo.watermarktable where TableName = '@{item().SourceTable}'",
          "type": "Expression" } },
      "firstRowOnly": true
    }
  },
  {
    "name": "LookupNewWatermark", "type": "Lookup",
    "dependsOn": [ { "activity": "LookupOldWatermark", "dependencyConditions": ["Succeeded"] } ],
    "typeProperties": {
      "source": { "type": "SqlServerSource",
        "sqlReaderQuery": {
          "value": "select MAX(@{item().WatermarkColumn}) as NewWatermarkvalue from [@{item().SourceSchema}].[@{item().SourceTable}]",
          "type": "Expression" } },
      "firstRowOnly": true
    }
  },
  {
    "name": "CopyDelta", "type": "Copy",
    "dependsOn": [ { "activity": "LookupNewWatermark", "dependencyConditions": ["Succeeded"] } ],
    "policy": { "timeout": "0.02:00:00", "retry": 2, "retryIntervalInSeconds": 60 },
    "typeProperties": {
      "source": {
        "type": "SqlServerSource",
        "sqlReaderQuery": {
          "value": "select * from [@{item().SourceSchema}].[@{item().SourceTable}] where @{item().WatermarkColumn} > '@{activity('LookupOldWatermark').output.firstRow.WatermarkValue}' and @{item().WatermarkColumn} <= '@{activity('LookupNewWatermark').output.firstRow.NewWatermarkvalue}'",
          "type": "Expression" },
        "additionalColumns": [
          { "name": "SourceFile", "value": "$$FILEPATH" },
          { "name": "LoadedBy",   "value": { "value": "@pipeline().RunId", "type": "Expression" } }
        ]
      },
      "sink": { "type": "ParquetSink" }
    },
    "inputs":  [ { "referenceName": "OnPremTableDS", "type": "DatasetReference",
                   "parameters": { "DBName": "@pipeline().parameters.DBName" } } ],
    "outputs": [ { "referenceName": "AdlsParquetDS", "type": "DatasetReference",
                   "parameters": { "TableName": "@item().SinkTable" } } ]
  },
  {
    "name": "WriteWatermark", "type": "SqlServerStoredProcedure",
    "dependsOn": [ { "activity": "CopyDelta", "dependencyConditions": ["Succeeded"] } ],
    "typeProperties": {
      "storedProcedureName": "usp_write_watermark",
      "storedProcedureParameters": {
        "LastModifiedtime": { "value": "@{activity('LookupNewWatermark').output.firstRow.NewWatermarkvalue}", "type": "DateTime" },
        "TableName":        { "value": "@{activity('LookupOldWatermark').output.firstRow.TableName}", "type": "String" }
      }
    }
  }
]
```

```sql
CREATE PROCEDURE usp_write_watermark @LastModifiedtime datetime, @TableName varchar(256)
AS BEGIN
  UPDATE dbo.watermarktable SET WatermarkValue = @LastModifiedtime WHERE TableName = @TableName
END
```

**Execution trace** (table `Orders`, watermark column `LastModifytime`):
1. `LookupOldWatermark.output.firstRow.WatermarkValue` → `2026-06-29 08:06:00`
2. `LookupNewWatermark.output.firstRow.NewWatermarkvalue` → `2026-06-30 00:00:00`
3. Copy runs `... where LastModifytime > '2026-06-29 08:06:00' and LastModifytime <= '2026-06-30 00:00:00'` → only the changed rows.
4. SProc writes `2026-06-30 00:00:00` back; tomorrow starts there.

**No invisible operations to watch:**
- `firstRow` of a Lookup that returned **zero rows is null** → interpolates to `> ''`, which copies everything or errors. That's why we seeded `watermarktable` low.
- `@{...}` (string interpolation) **stringifies** the value; bare `@...` preserves type. Inside a SQL string we *want* the string form, so `@{...}` is correct here — but never use it where a downstream field needs an Int/Bool.
- `additionalColumns` (`$$FILEPATH`, `@pipeline().RunId`) only reach the sink if mapped in the Mapping tab — the ADF analog of `df.withColumn("source_file", input_file_name())`.

Bridge: this whole chain is the *manual* version of a Databricks `MERGE` driven by `max(updated_at)`, or Auto Loader's checkpoint. The trade: ADF's bookmark is **explicit, inspectable SQL state you own**; Auto Loader's is opaque-but-automatic.

---

### 4. The parameterized dataset (one definition, every table)

```json
{
  "name": "AdlsParquetDS",
  "properties": {
    "type": "Parquet",
    "linkedServiceName": { "referenceName": "AdlsGen2_LS", "type": "LinkedServiceReference" },
    "parameters": { "TableName": { "type": "String" } },
    "typeProperties": {
      "location": { "type": "AzureBlobFSLocation", "fileSystem": "bronze",
        "folderPath": { "value": "@dataset().TableName", "type": "Expression" } }
    }
  }
}
```

The Copy binds `TableName = @item().SinkTable` (step 3); the dataset reads it via `@dataset().TableName`; the source dataset passes `DBName` down to the linked service's `@{linkedService().DBName}`. One value cascades **pipeline → dataset → linked service**, each layer reading with *its own* accessor — nothing crosses scopes automatically.

---

### 5. Schema-drift handling — where Copy isn't enough

The watermark Copy above uses **default mapping** (match by name; it "supports flexible schemas and schema drift from execution to execution" — new columns just flow through, but they arrive as the source's names, case-sensitive). That handles *additive* drift on a file sink fine.

When the sink is a **typed table** that must *evolve*, or you need to operate on unknown columns, route the loop body through a **Mapping Data Flow (MDF — visual, Spark-backed transform)** instead of a raw Copy, and turn on drift:

- **Source:** check **Allow schema drift** + **Infer drifted column types** (else drifted columns silently arrive as `string`).
- **Sink:** **Allow schema drift** *and* the **Auto-mapping** slider must *both* be on — sink drift without auto-map silently **drops** the new columns.
- Reference drifted columns you can't click in the schema view via `byName('NewCol')` (wrap in a cast: `toInteger(byName('NewCol'))`), column patterns (`type == 'double'` → `round($$, 2)`), or the canonical auto-map-into-existing-table Select rule:

```
select(mapColumn(each(match(true()))),
       skipDuplicateMapInputs: true,
       skipDuplicateMapOutputs: true) ~> automap
```

**Drift vs evolution:** drift = *tolerate* unknown **input** columns in flight (MDF source→sink). Evolution = *grow* the **target** schema to persist them — which is the store's job (Delta `mergeSchema`). They meet at the sink. Bridge: ADF MDF drift **silently passes through** and persists nothing per run; Auto Loader's default `addNewColumns` **fails-then-evolves-then-resumes** with a durable `schemaLocation`. If correctness matters, add an **Assert** transformation (the ADF cousin of a Lakeflow `@dp.expect` expectation).

---

### 6. The trigger that owns the slice

A **tumbling-window trigger** makes "yesterday's slice" deterministic and backfillable — the window *is* the watermark for time-partitioned sources (you can even drop the watermark table for those). It's one-to-one with the pipeline, retryable, and gap-free.

```json
{
  "name": "DailyIngest",
  "properties": {
    "type": "TumblingWindowTrigger",
    "typeProperties": {
      "frequency": "Day", "interval": 1,
      "startTime": "2026-06-01T00:00:00Z",
      "maxConcurrency": 5,
      "retryPolicy": { "count": 2, "intervalInSeconds": 60 }
    },
    "pipeline": {
      "pipelineReference": { "referenceName": "IngestOnPremTables", "type": "PipelineReference" },
      "parameters": {
        "DBName": "Sales"
      }
    }
  }
}
```

**The backfill foot-gun:** a `startTime` of `2026-06-01` on a daily trigger fires ~29 historical windows the moment you Start it (`M = (now − startTime) / windowSize`, oldest-to-newest, honoring `maxConcurrency`) — set concurrency deliberately or do an initial historical load instead. And `frequency`/`interval` are **immutable after create**. Bridge: this is Airflow's `data_interval_start/end` + `catchup=True`; a Databricks/Schedule-trigger cron is `catchup=False`.

---

### How it all clicks

```
TumblingWindow trigger ─pours window→ pipeline.parameters
   └─ LookupControlTable  (≤5000 rows!)  → @activity(...).output.value
        └─ ForEach @item()  (batchCount 10, never SetVariable in parallel)
             ├─ LookupOldWatermark   → firstRow.WatermarkValue
             ├─ LookupNewWatermark   → firstRow.NewWatermarkvalue
             ├─ Copy  (runs on SHIR by precedence; > old AND <= new; $$FILEPATH lineage)
             │     source LS  @{linkedService().DBName}  ← KeyVault secret
             │     sink DS     @dataset().TableName       (or MDF if drift→typed sink)
             └─ usp_write_watermark   advances the bookmark
```

Add a table = one `INSERT`. Change cadence = new trigger. Reach a new on-prem box = register another SHIR node (max 4) with the same key. Survive a new source column = the file sink already passes it (default mapping) or the MDF drift switches catch it. Every concept in this guide is a labeled box in that diagram — and the 896 KB per-activity payload ceiling is the reason `@item()` carries *metadata, not data*: Copy moves bulk source→sink directly, never through pipeline parameters.


---

## 9. Master Cheat-Sheet

## Master Quick-Reference

### The seven parameter/variable scopes

| Scope | Mutable? | Set by | Reference syntax | Use |
|---|---|---|---|---|
| **Global parameters** | No (env-overridable via ARM) | Factory admin | `pipeline().globalParameters.x` | env name, shared constants (no `-` in name; Git mode only for CI/CD include) |
| **System variables** | No (engine) | ADF runtime | `@pipeline().RunId`, `@trigger().scheduledTime`, `@item()`, `@activity('X').output...` | run/trigger metadata, loop item, upstream output |
| **Pipeline parameters** | No (per-run, frozen at start) | Trigger / parent / Debug | `@pipeline().parameters.x` | the run's inputs (String/Int/Float/Bool/Array/Object/SecureString; max 50) |
| **Pipeline variables** | **Yes** (Set/Append Variable) | The pipeline itself | `@variables('x')` | counters/accumulators (String/Bool/Array only; **unsafe in parallel ForEach**) |
| **Dataset parameters** | No (per-reference) | The activity using it | `@dataset().x` | folder/file path, table name |
| **Linked service parameters** | No (per-reference) | The dataset referencing it | `@{linkedService().x}` | DB name, server (never the password — parameterize KV secret name) |
| **Data flow parameters** | No (immutable, `$`-prefixed) | Execute Data Flow activity | `$x` | transform thresholds (separate expression dialect: `==`, `&&`, `iif()`, 1-based arrays, no interpolation) |

**Expression rule:** `@expr` preserves native type; `@{expr}` **stringifies** (silent coercion); `@@` escapes a literal `@`. `coalesce` treats empty-but-not-null as a value; `json(null)` returns `{}`.

### Activity groups

| Group | Members | Gets retry/timeout policy? | Runs on |
|---|---|---|---|
| **Data movement** | Copy (1 source → 1 sink) | Yes | Azure IR or SHIR (data plane) |
| **Data transformation** | Mapping Data Flow, Databricks Notebook/Jar/Python, Synapse Notebook, HDInsight, Stored Procedure, Script, Azure Function, Custom | Yes | Dispatched to external compute (or ADF-managed Spark for MDF) |
| **Control flow** | ForEach, Until, If, Switch, Lookup, GetMetadata, SetVariable, AppendVariable, ExecutePipeline, Wait, Web, Webhook, Fail, Filter, Validation | **No** (except Until/Validation/Wait carry their own `timeout`) | Control plane |

**Dependency conditions:** Succeeded / Failed / Completed / Skipped. **Multiple `dependsOn` always AND** — for OR, use Completed arrows + an If Condition reading `@activity('X').Status`.

### Integration Runtime types

| IR | Runs where | Does | On-prem reach | DIU? | Synapse |
|---|---|---|---|---|---|
| **Azure IR** | MS-managed serverless | Cloud↔cloud Copy, MDF Spark, dispatch | Only via managed VNet + private endpoint | **Yes** (4–256) | Yes |
| **SHIR** | Your Windows VM (outbound-only 443) | Cloud↔private Copy, dispatch, custom drivers | **Yes** (its purpose) | No (scale by nodes, max 4) | Yes (not shareable) |
| **Azure-SSIS IR** | MS-managed VM cluster | Run legacy `.dtsx` packages | Via VNet injection | No | **No (ADF only)** |

**IR precedence when several apply:** SHIR > managed-VNet Azure IR > global Azure IR. **MDF Data Flow:** `coreCount` ∈ {8,16,32,48,80,144,272}; TTL keeps Spark warm (helps *sequential* runs only; not on AutoResolve IR).

### Schema-drift toggles

| Toggle | Where | Effect | Silent default to know |
|---|---|---|---|
| **Allow schema drift** (source) | MDF source | Read undeclared columns, pass through | Drifted columns arrive as **`string`** |
| **Infer drifted column types** | MDF source | Auto-detect drifted types | Off → everything `string` |
| **Validate schema** | MDF source/sink | **Fail** the flow on schema/type mismatch | — |
| **Allow schema drift** (sink) | MDF sink | Write extra columns | Must **also** enable Auto-mapping or columns are **dropped** |
| `allowDataTruncation` | Copy `translator.typeConversionSettings` | Permit lossy convert (decimal→int) | **`true`** — silently drops fractions |
| Default mapping (no `translator`) | Copy | Match by name, case-sensitive; tolerant of execution-to-execution drift | New column to a pre-existing sink that lacks it → **fail** |

Drift = tolerate unknown **input** columns in flight; Evolution = grow the **target** schema (Delta `mergeSchema`). Databricks cousins: `cloudFiles.schemaEvolutionMode` (`addNewColumns` fails-then-evolves) + `schemaLocation`; ADF MDF silently passes through, persists nothing.

### Key numeric limits (verified)

| Item | Value |
|---|---|
| Max activities per pipeline | **120** (hard; includes inner container activities) |
| ForEach `batchCount` | default **20**, max **50**; up to **100,000** items; **no nesting**; SetVariable unsafe in parallel |
| Lookup output | ≤ **5,000 rows** / **4 MB** / 24-hr timeout (**Databricks Delta Lake connector: 1,000 rows**) |
| Web / Script / GetMetadata output | **4 MB** |
| Per-activity payload | **896 KB** (keep `@item()` rows = metadata, not data) |
| Databricks notebook `runOutput` | **2 MB** |
| Copy DIU | **4–256** (Azure IR only; REST source floors at 1; PolyBase/COPY effective 2) |
| SHIR nodes | up to **4** (HA + scale-out); shareable to 120 factories, **not** across product boundary |
| Pipeline parameters | max **50** |
| ARM template parameters | max **256** |
| Tumbling window | min interval **15 min**; `freq`/`interval` immutable after create; `maxConcurrency` **1–50**; depends-on max **5** TW triggers; retry default 0 |
| Storage event triggers / account | **500** (Event Grid limit) |
| Run history retention (Monitor UI/SDK) | **45 days** (route to Log Analytics for more) |
| Activity timeout default | **12 h** for Copy/transform (min 10 min); **7 days** for control/looping — don't conflate |
| Retry policy | `retry` default **0**; `retryIntervalInSeconds` default 30, min 30, max 86400 (no exponential backoff) |

**Cost meters:** orchestration (per activity run — **each trigger fire = +1 run**), Copy (DIU-hours, Azure IR only), Data Flow (vCore-hours — watch debug TTL, default 60 min). SHIR has no DIU meter (self-hosted data-movement rate + your VM). IR time rounds **up** to the minute.

**Deploy:** Git collaboration branch → Publish generates one **ARM template** → `adf_publish` branch. Promote dev→test→prod with **Incremental** mode (Complete deletes untracked resources). IR **name + type must match across stages**; stop triggers before deploy; same-named secrets in per-env Key Vaults.


---

## 10. Appendix — Verification Notes

What the adversarial doc-check changed, and what remains uncertain (verify against live docs before relying on it).


### ADF Architecture & Building Blocks — verdict: `minor_corrections`

**Corrections applied:**

- Corrected the 120-activity limit from 'a default soft limit (raisable via support)' to a HARD limit. Microsoft's Azure subscription limits table (learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits#azure-data-factory-limits) lists 'Maximum activities per pipeline, which includes inner activities for containers' with BOTH default limit AND maximum limit = 120. There is no documented path to raise it. The 'includes inner activities inside containers' claim was correct and retained.
- Tightened the Fabric migration section: global parameters are NOT migrated automatically. Per learn.microsoft.com/fabric/data-factory/convert-global-parameters-to-variable-libraries and the ADF-to-Fabric upgrade guide, neither the built-in upgrade experience nor the PowerShell tool migrates global parameters — you recreate them manually as variable libraries. The original 'global parameters become variable libraries' was directionally right but implied automatic conversion.
- Corrected the trigger-migration claim. Per the ADF-to-Fabric upgrade FAQ (learn.microsoft.com/azure/data-factory/how-to-upgrade-your-azure-data-factory-pipelines-to-fabric-data-factory): only SCHEDULE triggers migrate automatically (disabled); all other trigger types must be manually reconfigured, and CUSTOM EVENT triggers can't be migrated at all (storage event = coming soon; tumbling window becomes interval-based scheduling with backfill requiring redesign). The original blanket 'triggers arrive disabled (you re-enable them)' was an oversimplification.
- Added the verified-accurate nuance that a SHIR can be shared with up to 120 data factories but never across the product boundary (Synapse/Fabric), per learn.microsoft.com/azure/data-factory/create-self-hosted-integration-runtime and the Fabric-vs-ADF comparison doc — strengthens the existing (correct) sharing gotcha.
- Clarified the SHIR node count: the section's 'up to 4 nodes' matches the canonical ADF limits page (default and maximum both 4). Retained 4 and labeled it as the documented maximum on the ADF limits page (noting in residual risks that one Fabric comparison doc cites a higher figure).
- Added minor verified-accurate enrichments that preserve style: parameter data types (String/Int/Float/Bool/Array/Object/SecureString), the 8,192-character expression limit, the DIU 'Auto picks optimal' detail, the debug-IR default (8-core, 60-min TTL), TW default 0 retries + oldest-to-newest backfill order, and the exact custom-event missing-key error text — all grounded in the cited docs.
- Added a one-line note that triggers, pipeline runs, parameters, and variables are additional core objects alongside the six building blocks (matches the claim list and Microsoft's object model), without disrupting the six-block table.
- Replaced the imprecise phrase 'degree-of-parallelism increases don't always raise throughput' framing with Microsoft's own documented wording that the for-each activity 'will not always execute at' the batchCount value, keeping the same teaching point.
- Corrected the Databricks-vs-Microsoft attribution for the orchestrator-choice guidance: the 'use Lakeflow Jobs when only on Databricks, use ADF/Airflow when beyond' guidance is Databricks' guidance (learn.microsoft.com/azure/databricks/jobs and /ldp/workflows), not 'Microsoft's own guidance' as a separate ADF source. Verified the ADF-as-outer-orchestrator-calling-Databricks pattern from the same docs.

**Residual risks / verify-before-trusting:**

- SHIR maximum node count: the canonical ADF limits page (azure-subscription-service-limits) states max 4 nodes, and the Gen1->Gen2 best-practices doc says 'up to 4 nodes.' However, the Fabric-vs-ADF comparison doc (learn.microsoft.com/fabric/data-factory/compare-fabric-data-factory-and-azure-data-factory) states SHIR High Availability is 'Up to 8 nodes (4 default).' I kept '4' per the primary limits page; the higher HA ceiling may apply in some configurations. Worth a one-line check before teaching as absolute.
- The 'single copy activity partitions its file set across nodes' for SHIR is verified for file-based copy in the Gen1->Gen2 best-practices doc; whether ALL copy sources partition across SHIR nodes (vs only file stores with name-range partitioning) is not fully general — the doc example is file-based.
- Mapping Data Flow '5-7 min warm-up' is verified verbatim in multiple ADF tutorials; actual warm-up varies with cluster size and region and the docs phrase it as a typical figure, not a hard SLA.
- The ~100 built-in expression functions and '90+ connectors' figures were retained from the original as round approximations; Microsoft does not publish a single canonical count and the true number grows over time. Treated as illustrative, not precise.
- Azure-SSIS IR in Synapse: the IR-types page explicitly says Synapse pipelines support only Azure or self-hosted IRs (so no Azure-SSIS), and the ADF-vs-Synapse comparison table confirms no Azure-SSIS IR for Synapse. However, some Azure-SSIS provisioning articles are tagged 'applies to Azure Synapse Analytics' with a limitations link — there may be narrow Azure-SSIS scenarios in Synapse. The section's claim (no Azure-SSIS in Synapse pipelines) matches the authoritative IR-types statement and is the safe teaching position.
- Azure Data Explorer (Kusto) Lookup caps at 5,000 rows AND 2 MB with a 1-hour timeout (a connector-specific override, like the Databricks Delta Lake 1,000-row cap). The section only calls out the Databricks override; the Kusto override exists too but was out of scope for the claims list, so it was not added.

### Integration Runtimes & On-Prem Connectivity (SHIR) — verdict: `minor_corrections`

**Corrections applied:**

- FACTUAL ERROR (the only substantive one): The section repeatedly stated the SHIR needs 'JRE 11 (e.g. Microsoft OpenJDK 11)' for Parquet/ORC/Avro. Microsoft Learn's current Parquet/ORC connector pages specify 64-bit JRE 8, JDK (currently JDK 23), or OpenJDK / Microsoft Build of OpenJDK — NOT JRE 11. Corrected every occurrence (the prose bullet, the source-driver table, the end-to-end walkthrough, and the final takeaways) to 'JRE 8 / JDK / OpenJDK'. Doc basis: https://learn.microsoft.com/azure/data-factory/format-parquet#using-self-hosted-integration-runtime and https://learn.microsoft.com/azure/data-factory/format-orc#using-self-hosted-integration-runtime.
- SOFTENED an unverifiable specific: the SAP Table/BW/Open Hub claim of 'dispatcher port 32NN / gateway port 33NN (NN = instance number)'. The ADF SAP-Table connector doc only states systemNumber 'affects the PORT number used when communicating with the SAP table' (https://learn.microsoft.com/azure/data-factory/connector-sap-table#linked-service-properties); the explicit 32NN/33NN port convention is standard SAP NetWeaver knowledge but is NOT stated on the ADF Learn pages. Reworded to attribute it to the SAP gateway/dispatcher convention rather than asserting it as an ADF-documented fact.
- VERIFIED and tightened the SAP-driver table: SAP HANA requires the SAP HANA ODBC driver ('SAP HANA CLIENT for Windows') on the SHIR, and the DIAHostService account needs Read & Execute on the driver folder (https://learn.microsoft.com/azure/data-factory/connector-sap-hana#prerequisites and https://learn.microsoft.com/purview/register-scan-sap-hana#prerequisites). SAP Table/BW/Open Hub require SAP Connector for Microsoft .NET 3.0 with 'Install Assemblies to GAC' (https://learn.microsoft.com/azure/data-factory/connector-sap-table#prerequisites, .../connector-sap-business-warehouse-open-hub#prerequisites). SAP ECC supports BOTH Azure IR and SHIR (https://learn.microsoft.com/azure/data-factory/connector-sap-ecc#supported-capabilities). All confirmed accurate; left intact.
- SOFTENED the flat 'managed VNet does not support VNet peering' assertion. The ADF managed-VNet limitations page (https://learn.microsoft.com/azure/data-factory/managed-virtual-network-private-endpoint) documents 'Custom DNS is not supported' and 'All ports are opened for outbound communications [through public endpoint]' explicitly, and confirms the managed VNet/private endpoints live under a Microsoft subscription — but it does not itself enumerate 'no VNet peering.' Kept the practical conclusion (you cannot peer your own VNet into ADF's Microsoft-owned managed VNet; reach on-prem via Private Link Service + load balancer) but phrased the peering point as a consequence of the managed VNet being Microsoft-owned rather than a quoted doc line.
- VERIFIED with no change needed: three IR types + Synapse supports only Azure/Self-hosted not SSIS; resolution precedence SHIR > managed-VNet Azure IR > global Azure IR and 'either side SHIR => whole copy on SHIR'; AutoResolve sink-region best-effort detection with factory-region fallback and Lookup/GetMetadata/Delete/external-dispatch/Data Flow always factory-region; DIU Azure-IR-only, range 4–256 (multiples of 4); Data Flow coreCount {8,16,32,48,80,144,272}, computeType General/ComputeOptimized/MemoryOptimized, default AutoResolve = 4 worker cores General; timeToLive default 0, not on AutoResolve IR, one-job-per-cluster (sequential-only benefit), production minimum General 8+8 (16 vCores) + 10-min TTL; IR selection applies to triggered runs only, debug uses debug-session cluster; SHIR outbound-only 443 to *.servicebus.windows.net, {datafactory}.{region}.datafactory.azure.net, download.microsoft.com, Key Vault URL, AzureCloud/Internet + DataFactoryManagement NSG tags; up to 4 nodes via same auth key; Windows-only 64-bit, .NET 4.7.2+, not on domain controller, 4 cores/8GB/80GB min, hibernation => offline; creds in Key Vault or DPAPI-local with version-stamped multi-node copies; DIAHostService + Log on as a service; one SHIR per machine, share within same Entra tenant via Contributor on the Shared IR resource ID, Synapse cannot share/link; ForEach batchCount max 50 default 20, parallel cap 50; Lookup max 5000 rows / 4 MB; outbound 1433 for SQL sink with staged-copy 443 workaround; managed private endpoint Pending->Approved workflow over Microsoft backbone; Azure-SSIS managed VM cluster + customer SSISDB + VNet injection or SHIR proxy, not in Synapse; all-on-prem source/sink/SHIR keeps data on-prem. Every one of these matched the live docs.

**Residual risks / verify-before-trusting:**

- SAP dispatcher port 32NN / gateway port 33NN: this is the well-known SAP NetWeaver port convention (sapgwNN = 33NN, sapdpNN = 32NN where NN = the two-digit systemNumber) but it is NOT spelled out on the ADF Microsoft Learn connector pages, which only say systemNumber 'affects the PORT number.' I softened the wording but could not cite an ADF doc that states the exact 32NN/33NN formula.
- Managed VNet 'no VNet peering': the practical conclusion is sound (the managed VNet is Microsoft-owned, so customers cannot peer their own VNet into it and must use a Private Link Service + internal load balancer to reach on-prem), but the ADF managed-VNet limitations page I reviewed enumerates 'no custom DNS' and 'all outbound ports open' explicitly without a literal 'VNet peering not supported' line. The claim is reasonable but not verbatim-documented.
- 'Primary-coordinated, not symmetric' SHIR cluster: ADF docs describe multi-node SHIR as 'active-active mode' and confirm work/file-copy is distributed across nodes and credentials sync across nodes, but the docs do not literally state 'one node is primary and distributes work to secondaries.' There is a primary-node concept in the product, and the section already flags that the high-level docs say 'active-active', so this is a fair characterization — but the precise primary/secondary work-distribution mechanic is not verbatim in the current Learn pages.
- Synapse managed-VNet 'can restrict outbound' vs ADF 'all ports open': verified directionally (the concepts-integration-runtime note confirms Synapse workspaces have options to limit managed-VNet outbound while ADF opens all ports), so this product difference is accurate as stated.
- JDK version specifics drift over time: the current Parquet doc names JDK 23 as the JDK option; the section deliberately uses the version-agnostic 'JRE 8 / JDK / OpenJDK' to avoid pinning a fast-moving JDK number. JRE 8 and OpenJDK (Microsoft Build of OpenJDK) are the stable, documented anchors.

### The Activity Catalog — verdict: `minor_corrections`

**Corrections applied:**

- Execute Pipeline `waitOnCompletion` default: the section claimed the default is FALSE (async) and built a 'call this out' gotcha around it. The canonical Microsoft Learn 'Execute Pipeline activity' doc (Type properties table) states the default is TRUE — the parent blocks and child output is available by default. (The ARM/SDK ExecutePipelineActivityTypeProperties says false, a known doc-vs-SDK discrepancy; per the instruction to trust the docs, the ADF article's TRUE is authoritative.) Rewrote the Execute Pipeline section to make true the default, kept the async-vs-sync distinction, and flagged the SDK conflict. Source: https://learn.microsoft.com/azure/data-factory/control-flow-execute-pipeline-activity#type-properties
- Web activity HTTP methods: the section listed only GET/POST/PUT/DELETE and said body is 'forbidden for GET'. Current docs list GET, POST, PUT, PATCH, DELETE (PATCH was missing), and body is 'Required for POST/PUT/PATCH, Optional for DELETE' (not forbidden for DELETE; simply not used for GET). Corrected the methods list and the body rule. Source: https://learn.microsoft.com/azure/data-factory/control-flow-web-activity#type-properties
- Synapse/Fabric 32-concurrent-query cap: confirmed for Azure Synapse Analytics — the ADF connector doc states 'Azure Synapse Analytics can execute a maximum of 32 queries at a moment' as the parallel-copy tuning ceiling. Could NOT confirm the identical 32 figure for Microsoft Fabric Warehouse from the docs, so I narrowed the gotcha to call out Synapse explicitly and softened the Fabric claim. Source: https://learn.microsoft.com/azure/data-factory/connector-azure-sql-data-warehouse#parallel-copy-from-azure-synapse-analytics
- Verified and left unchanged (all confirmed against docs): DIU range 4–256, Auto file-store auto-pick 4–32, REST/HTTP source = 1 DIU, Synapse PolyBase/COPY effective DIU = 2; parallelCopies orthogonal to DIUs, tuning rule (DIU or #SHIR nodes) × (2–4); staged copy enableStaging+stagingSettings, delete permission, two-hop billing, not supported across two different SHIRs, SP/MSI auth unsupported when compression enabled; fault tolerance three scenarios (type conversion, column-count mismatch, PK violation) and exclusions (Upsert, stored-proc SQL sink, Redshift UNLOAD); additionalColumns $$FILEPATH and $$COLUMN:<name>, plus expressions/static, must map in Mapping tab, latest dataset model; upsert writeBehavior=upsert + upsertSettings.keys (defaults to PK); ForEach isSequential default false, batchCount default 20 / max 50, items max 100,000, no nesting in ForEach/Until, Set Variable unsafe in parallel ForEach; Lookup firstRowOnly default true, 5,000 rows / 4 MB / 24 h, Databricks Delta Lake 1,000 rows, ADX/Kusto 5,000 rows / 2 MB / 1 h, exactly one result set; GetMetadata fieldList fields and exists semantics, 4 MB max, no wildcard, childItems immediate-folder-only; Switch max 25 cases + defaultActivities, expression resolves to string; Until default 7 days / max 90 days, does not stop on inner failure; Set Variable no self-reference, pipeline return value 4 MB; Validation timeout 12 h / sleep 10 s / minimumSize 0 / childItems semantics; Fail message+errorCode required; Delete recursive false / maxConcurrentConnections 1 / soft-delete caveat / on-prem SHIR > 3.14; Databricks notebook baseParameters=widgets, runOutput 2 MB; Script Query/NonQuery, recordsAffected, 5000 rows/4 MB, truncation order logs→parameters→rows, outputTruncated; Azure Function methods GET/POST/PUT/DELETE/OPTIONS/HEAD/TRACE, must return JSON (err 3603), functionName/functionKey/functionAppUrl required; Data Flow coreCount {8,16,32,48,80,144,272}, computeType General; dependency conditions Succeeded/Failed/Completed/Skipped, multiple dependsOn ANDed, Skipped cascade; activity policy retry default 0, retryIntervalInSeconds default 30 / min 30 / max 86400, execution timeout 12 h (min 10 min) vs control/ARM 7 days; 120-activity soft limit per pipeline including inner activities.

**Residual risks / verify-before-trusting:**

- Execute Pipeline waitOnCompletion default is genuinely ambiguous in Microsoft's own materials: the ADF 'Execute Pipeline activity' reference page Type-properties table says 'Default is true', while the ARM/SDK ExecutePipelineActivityTypeProperties documents 'Default is false'. I corrected the section to the ADF doc (true) per the trust-the-docs instruction and flagged the split, but the effective runtime default for a hand-authored JSON omitting the property could differ from the UI default — the only safe practice is to set it explicitly.
- The '32 concurrent queries' cap is confirmed for Azure Synapse Analytics (dedicated SQL pool) as stated in the ADF Synapse connector's parallel-copy guidance. I could NOT confirm that Microsoft Fabric Warehouse shares the identical 32 figure, so the original section's lumping of 'Synapse / Fabric Warehouse' under one 32 cap is only verified for Synapse; I softened the Fabric half. Note also the underlying Synapse memory/concurrency doc shows higher max-concurrent-query counts (48/64/128) at DWUs above DW1500c, so 32 is the connector-guidance ceiling, not a hard universal limit.
- Web activity body-for-DELETE: docs state body is 'Optional for DELETE method' (so DELETE *may* carry a body); the original section's 'forbidden for GET' was kept (GET is not listed as taking a body) but I could not find an explicit statement that a GET body is rejected outright — treat 'no body on GET' as the documented allowed-values behavior rather than a hard validation error.
- Azure Function method list (GET/POST/PUT/DELETE/OPTIONS/HEAD/TRACE) comes from the SDK AzureFunctionActivityMethod enum and the troubleshooting doc (error 3602); the prose 'Azure Function activity' reference page itself only enumerates GET/POST/PUT in its property table. The 7-method list is correct per the authoritative enum, but a reader checking only the activity reference page may see a narrower set.
- Switch expression type: the ADF docs/UI require the expression to resolve to a string and cap cases at 25. The original section's parenthetical 'SDK allows string or integer' was dropped because I did not re-verify an integer-accepting SDK path; if that nuance matters, confirm against the current SwitchActivity SDK model.
- Several 'invisible behavior' bridges and Databricks/Airflow analogies (e.g., Mapping Data Flow ~5-min cold start, debug cluster differs from configured IR, useTempDB staging mechanics for upsert) are accurate in spirit and consistent with the docs, but exact current numeric latencies are not pinned to a single doc figure and may drift.

### Parameters, Variables, Expressions & Their Scopes — verdict: `minor_corrections`

**Corrections applied:**

- Tightened '~50 types' to '50 types' for native-UI linked-service parameterization. Verified: the Learn 'Parameterize linked services' page states 'All the linked service types are supported for parameterization' and lists exactly 50 natively-UI-supported types (Amazon Redshift through Vertica). https://learn.microsoft.com/azure/data-factory/parameterize-linked-services#supported-linked-service-types
- Corrected the opening Microsoft Learn quote. The section spliced two sentences as if contiguous ('Parameters are defined at the pipeline level, and can't be modified...'). The actual parameter-concepts quote is: 'Parameters are external and therefore passed into pipelines, datasets, linked services, and data flows, whereas variables are defined and used within a pipeline. Parameters are read-only, whereas variables can be modified within a pipeline by using the Set Variable activity.' Replaced with the verbatim text. https://learn.microsoft.com/azure/data-factory/how-to-expression-language-functions#parameter-concepts
- Strengthened the SecureString gotcha with the docs' own blunt wording ('serialized as JSON within the activity.json file as plain text... not truly secure, and is not intended to be secure'), since the section asserted this without the supporting quote. https://learn.microsoft.com/azure/data-factory/transform-data-using-custom-activity#retrieve-securestring-outputs
- Variable numeric-counter workaround: changed 'store it as a String/Array' to 'store it as a String' (an Array is not how you hold a scalar counter) and added the docs' documented self-reference limitation (Set Variable can't read the variable it is setting; needs a temp var + second Set Variable). https://learn.microsoft.com/azure/data-factory/control-flow-set-variable-activity#incrementing-a-variable
- Set Variable 'pipeline return value' note: added that it is key-value pairs bounded by the 4 MB returned-JSON size limit, per the Set Pipeline Return Value tutorial. https://learn.microsoft.com/azure/data-factory/tutorial-pipeline-return-value
- Global parameters Fabric-syntax flag rewritten for accuracy. The section implied @globalParameters('name') is a current Fabric reference form; the Fabric migration docs actually show @globalParameters('ParamName') as the LEGACY ADF expression that migration tooling rewrites TO @pipeline.libraryVariables.ParamName (variable libraries). Also added that the built-in upgrade tooling does NOT auto-migrate global parameters. https://learn.microsoft.com/fabric/data-factory/convert-global-parameters-to-variable-libraries
- Global parameters CI/CD: added that the older 'Manage hub -> Global parameters -> Include in ARM template' flow still works but is deprecated, and quoted the exact docs phrasing that the new include is 'only available in Git mode... disabled in live mode or Data Factory mode.' https://learn.microsoft.com/azure/data-factory/author-global-parameters#global-parameters-in-ci-cd
- System variables table: clarified RunId description to 'ID (GUID)' matching docs ('ID of the specific pipeline run'), and GroupId to 'ID of the group the run belongs to'. Added a Synapse-specific note that storage/custom event trigger bodies use @trigger().outputs.body.* instead of @triggerBody().* — documented on the System variables page. https://learn.microsoft.com/azure/data-factory/control-flow-system-variables
- Trigger->pipeline handoff: replaced the paraphrased 'utilize parameters, like @pipeline().parameters.parameterName, not system variables' quote (which I could not locate verbatim on the cited page) with the verbatim docs sentence from the schedule-trigger 'Pass the trigger start time to a pipeline' section. https://learn.microsoft.com/azure/data-factory/how-to-create-schedule-trigger#pass-the-trigger-start-time-to-a-pipeline
- UTC flag: replaced near-quote with the exact docs note 'Trigger-related date/time system variables (in both pipeline and trigger scopes) return UTC dates in ISO 8601 format, for example, 2017-06-01T22:20:00.4061448Z.' https://learn.microsoft.com/azure/data-factory/control-flow-system-variables#pipeline-scope
- Expression coercion truth table: replaced the '@@{...}' row example to match the docs' actual row ('Answer is: @@{...}' -> literal 'Answer is: @{...}'), which is the documented example; the prior bare '@@{...}' row was not the docs' example. https://learn.microsoft.com/azure/data-factory/control-flow-expression-language-functions#expressions
- Functions table: dropped the 'array' row (its description conflated array()/createArray and was not load-bearing) and added an 'int' row (int('10') -> 10), which the trace and the variable-coercion gotcha reference. json row reworded to 'JSON value/object' to match docs ('JSON native type value or object'). https://learn.microsoft.com/azure/data-factory/control-flow-expression-language-functions#function-reference
- Data flow dialect gotcha: added two further verified data-flow specifics from the expression-builder docs — one-based array indexing (myArray[1] is the first element) and NO string interpolation in data flow (concatenate instead). Removed the unverifiable claim that data-flow strings use 'single OR double quotes' as a blanket rule by grounding it in the docs' actual statement about single/double quote usage. https://learn.microsoft.com/azure/data-factory/concepts-data-flow-expression-builder ; https://learn.microsoft.com/azure/data-factory/parameters-data-flow#assign-parameter-values-from-a-pipeline
- Fixed a JSON syntax error in the end-to-end trace step 5: the 'path' expression string was missing its closing double-quote (...item().tableName) -> ...item().tableName)"). 
- Lookup limit wording sharpened to distinguish the two failure modes per docs: >4 MB FAILS the activity; >5,000 rows silently returns only the first 5,000. https://learn.microsoft.com/azure/data-factory/control-flow-lookup-activity#supported-capabilities
- Added the verified '50 parameters per pipeline' service cap as a parenthetical in the Pipeline parameters section (it was absent). https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits#azure-data-factory-limits

**Residual risks / verify-before-trusting:**

- The claim that the Databricks Delta Lake connector Lookup 'caps at 1,000 rows' is confirmed for the 'Azure Databricks Delta Lake' connector page ('can return up to 1000 rows'). I did not separately verify whether the newer generic 'Azure Databricks' connector (distinct from 'Azure Databricks Delta Lake') has the same or a different cap; the section's wording specifically names the Delta Lake connector, which is correct.
- The section frames the seven scopes as a fixed, canonical ADF taxonomy. Microsoft Learn documents each scope individually (pipeline params, pipeline vars, dataset params, LS params, data flow params, global params, system variables) but does not itself present a single authoritative 'seven scopes' list — that grouping is the author's pedagogical framing, not a verbatim doc structure. It is accurate but not a doc-sourced enumeration.
- The 'Answer is: @@{...}' escape row is grounded in the docs' example. The simpler '@@' -> single '@' character behavior is also documented separately; both are correct, but I substituted the docs' exact compound example rather than keep the author's standalone '@@{pipeline()...}' row which the docs do not show in that exact form.
- ForEach 'batchCount default 20, max 50' is confirmed for ADF (subscription limits page and ForEach activity page). The Fabric Data Factory limits page shows the same numbers, but Fabric is a different product surface; the section is about classic ADF, where the values are verified.
- Mapping Data Flow operator examples (==, &&, iif(), equalsIgnoreCase) are representative of the Spark-based data-flow expression language and consistent with the docs' general statement, but I did not verify each individual operator token against the data-flow function reference; they are illustrative rather than an exhaustive verified list.
- Databricks/Airflow/Dagster bridge analogies (Lakeflow job.run_id, {{run_id}}, {{ logical_date }}, data_interval_start) are not Microsoft Learn content and were not verified against Databricks/Airflow docs in this pass — they are retained as the author's cross-tool teaching analogies.

### Dynamic / Metadata-Driven Pipelines — verdict: `accurate`

**Corrections applied:**

- All 30 numeric/capability/naming claims verified against current Microsoft Learn docs and confirmed accurate. No factual errors were found; edits are clarifications and source-anchoring only.
- Lookup 'exactly one result set' requirement: added explicit note that zero OR multiple result sets fail the activity, matching the docs' 'one and exact one result set' wording (control-flow-lookup-activity#supported-capabilities).
- Hyphen-in-parameter-names bug: anchored to the parameterize-linked-services doc and added the doc's adjacent warning about an active bug with spaces in dataflow names (parameterize-linked-services).
- Watermark dynamic query: added explicit note it matches the 'incrementally load from multiple tables' tutorial verbatim, and renamed the generic 'LookupOld'/'LookupNew' step labels to the canonical activity names LookupOldWaterMarkActivity / LookupNewWaterMarkActivity used across the ADF tutorials (tutorial-incremental-copy-multiple-tables-portal, tutorial-incremental-copy-portal).
- Boundary-convention note: removed the speculative aside that 'some ADF tutorials use < new' — the official ADF and Fabric tutorials all use '> old AND <= new'; replaced with a statement that the official tutorials use exactly this convention.
- Copy Data Tool 3-level detail: added the exact generated activity names (CopyBatchesOfObjectsSequentially, DivideOneBatchIntoMultipleGroups, GetObjectsPerGroupToCopy, ListObjectsFromOneGroup) and the TaskId 'ORDER BY [TaskId] DESC' ordering, per copy-data-tool-metadata-driven#pipelines.
- OPENJSON requirement: added that it needs DB compatibility level 130+ and that Azure SQL DB / MI / Synapse support it natively (openjson-transact-sql; copy-data-tool-metadata-driven#known-limitations).
- Key Vault secret claim: reworded to 'Microsoft recommends' to match the doc's 'We recommend not to parameterize passwords or secrets' (parameterize-linked-services).
- batchCount mechanism: softened 'the engine builds batchCount sequential queues' (not literal doc wording) to the docs' exact phrasing — 'the upper concurrency limit, but the for-each activity will not always execute at this number' — preserving the teaching point without asserting an internal-queue model the docs don't state.
- Tumbling window: added the verified retryPolicy.intervalInSeconds default of 30 (the section only mentioned the minimum); added minimum interval 15 minutes and valid frequencies (Minute/Hour/Month); added Microsoft's guidance to do an initial historical load for long backfills (how-to-create-tumbling-window-trigger; concepts-pipeline-execution-triggers#trigger-type-comparison).
- DIU default: clarified 'Auto' means the service picks an optimal value per source-sink pair/data pattern (copy-activity-performance-features#data-integration-units).
- Parallelism suggestion: added that some sinks (Synapse, Fabric Warehouse) cap ~32 concurrent queries, so an over-large degree triggers throttling — context the docs attach to the (DIU or SHIR nodes) x (2-4) suggestion (connector-azure-sql-data-warehouse#parallel-copy-from-azure-synapse-analytics).

**Residual risks / verify-before-trusting:**

- The minimum tumbling-window interval differs between sources: the Azure subscription service-limits page lists 'Minimum tumbling window trigger interval: 5 min (default) / 15 min (max)', while the TumblingWindowTrigger SDK/how-to docs state 'minimum interval allowed is 15 Minutes.' I used 15 minutes (the trigger doc's value); the limits-page 5-min figure may reflect a different/legacy constraint. Low impact on the section since it doesn't quote a minimum interval as a load-bearing claim, but flag if precision matters.
- The exact byte composition of the 896 KB per-activity payload ('activity config + datasets + linked services + passed values') is the section's gloss; the limits page states the 896 KB figure as 'Bytes per payload for each activity run' without itemizing the components. The itemization is a reasonable interpretation but not verbatim from a single doc.
- The Databricks Delta Lake connector 1,000-row Lookup cap is confirmed for the ADF connector (connector-azure-databricks-delta-lake). I did not separately verify whether the same cap applies under the Fabric Data Factory 'Azure Databricks' connector, which is a distinct product surface; the section scopes the caveat to ADF, so this is not an error.
- The seed-watermark value ('1/1/2010') and the null-firstRow-yields-\"> ''\" behavior are pedagogically correct and consistent with the tutorials' practice of pre-seeding watermarktable, but the docs do not state the exact failure mode of interpolating a null firstRow into the query; treat that mechanism description as well-reasoned rather than doc-quoted.

### Schema Evolution & Schema Drift — verdict: `minor_corrections`

**Corrections applied:**

- Default mapping drift scope: the original said default mapping is 'ADF's file-to-file schema-drift story.' Per docs (copy-activity-schema-and-type-mapping#schema-mapping), default mapping 'supports flexible schemas and schema drift from source to sink from execution to execution' — it is source-to-sink in general, not only file-to-file. Reworded to 'source-to-sink' while keeping the file example.
- Auto Loader schemaEvolutionMode value list: the Spark API options reference (spark/api-options#datastreamreader-options) lists only addNewColumns, none, rescue, failOnNewColumns as the schemaEvolutionMode valid values. addNewColumnsWithTypeWidening is documented as a mode in the schema-evolution article but is Public Preview, DBR 16.4+. Kept all modes in the list but added the preview/version caveat for addNewColumnsWithTypeWidening so the claim is precise.
- spark.databricks.delta.schema.autoMerge.enabled 'not recommended for production': I could not find a doc statement that Databricks explicitly does NOT recommend this for production. The Delta schema-evolution docs describe it as a session-level conf without a prod-discouragement note. Softened from 'Databricks does not recommend for prod' to 'session-wide (applies to every write in the session) — scope it carefully' to stay doc-grounded.
- MERGE/INSERT WITH SCHEMA EVOLUTION: confirmed these are real Databricks SQL clauses; left as-is. Delta schema enforcement on write (reject by default), mergeSchema additive-only (adds columns, does not drop or change existing types), overwriteSchema to replace — all verified against delta-lake-schema-evolution and data-engineering/schema-evolution.
- Verified verbatim and left unchanged: interim type list (Boolean..UInt64), three-hop interim conversion, allowDataTruncation default true with decimal->integer and DatetimeOffset->Datetime examples, typeConversion default-on for UI copies since late June 2020 / off for older / must set true programmatically, tabular-only type conversion (no system-defined hierarchical conversion), Decimal precision up to 28, translator mapping properties (name/ordinal 1-based required for headerless delimited text/path/type/culture/format), collectionReference cross-apply with root-$ vs in-array-no-$, parameterized Object translator via @pipeline().parameters, additionalColumns $$FILEPATH/$$COLUMN reserved tokens, 'writing to array inside object not supported' for tabular->hierarchical sink.
- Verified verbatim for MDF: schema-drift definition and late-binding (drifted names absent from downstream schema views), drifted = not in source projection, source Allow schema drift reads all incoming fields and passes to sink with drifted columns as string unless Infer drifted column types, source Validate schema fails run on projection mismatch, sink Allow schema drift writes additional columns and needs Auto-mapping on (else rule-based mapping or columns dropped), byName/byPosition return untyped value needing a cast, Map Drifted generates toInteger(byName('movieId')), byName cross-stream Exists example, column pattern attributes name/type/stream/position/origin plus $$ ('this') and $0 (matched name scalar / hierarchy path complex), rule-based-only mapping drops non-matching columns, regex mapping via chevron, >50-column projection defaults to rule-based pass-through, automap snippet select(mapColumn(each(match(true()))), skipDuplicateMapInputs:true, skipDuplicateMapOutputs:true).
- Verified verbatim: Assert transformation Expect true / Expect unique / Expect exists, Fail data flow flag, isError()/hasError() tagging, route error rows via sink Errors tab, and 'not currently supported in Dataflow Gen2' (data-flow-assert).
- Verified verbatim: Auto Loader stores schema in cloudFiles.schemaLocation; JSON/CSV/XML infer all columns as string unless cloudFiles.inferColumnTypes=true; UnknownFieldException + add-to-schema + resume-on-restart for addNewColumns; none is default when explicit schema provided (addNewColumns default when no schema); _rescued_data captures type-mismatch/unexpected/case-difference values; schemaHints example 'id long, amount double'.
- Verified verbatim: Lakeflow SDP expectations are per-row SQL boolean constraints with three violation policies warn(default)/drop/fail mapping to @dp.expect / expect_or_drop / expect_or_fail, metrics emit to the pipeline event log (note: fail does not record metrics since the update fails on first invalid record — added that nuance).

**Residual risks / verify-before-trusting:**

- dbt on_schema_change values (append_new_columns / sync_all_columns / fail / ignore) and Dagster asset checks / Great Expectations / Soda are not Microsoft Learn topics, so they were not verified against MS docs in this pass. They match dbt's public documentation from general knowledge but were out of scope for the doc grounding requested.
- The claim that the >50-column rule-based default outputs 'the input name' and that <50 columns default to fixed mappings is verified for Select/Sink (data-flow-select, concepts-data-flow-column-pattern). I did not separately confirm the exact threshold behavior for every transformation type, but the docs state it generally for projections.
- spark.databricks.delta.schema.autoMerge.enabled was softened from 'Databricks does not recommend for prod' because I found no explicit doc statement to that effect — only that it is a session-level conf. If a stronger prod-discouragement note exists in a Databricks (non-MS-Learn) doc, the softer wording is still safe.
- delta.enableTypeWidening as the table property name for Delta type widening is stated from general knowledge; the MS Learn results I pulled documented Auto Loader's addNewColumnsWithTypeWidening explicitly but did not show the exact Delta table-property spelling, so that one token is lower-confidence.
- MERGE WITH SCHEMA EVOLUTION / INSERT WITH SCHEMA EVOLUTION are real Databricks SQL clauses (general knowledge) but did not appear verbatim in the specific MS Learn chunks retrieved this pass.

### Triggers, Monitoring & CI/CD — verdict: `minor_corrections`

**Corrections applied:**

- SHIR cost row was wrong. The section claimed 'the data-movement DF compute on SHIR is free; you pay only for the VM.' Microsoft docs (self-hosted-integration-runtime-proxy-ssis 'Billing' section, and the data-pipeline pricing page) state data-movement activities that run on a self-hosted IR ARE billed by ADF, separately. Corrected to: ADF charges data-movement + activity execution on the SHIR at the self-hosted rate AND you pay for the VM; the only true nuance is there is no DIU-hours meter for SHIR (DIU applies to Azure-IR copy only).
- Added the tumbling-window dependency cap: 'a tumbling window trigger can depend on a maximum of five other triggers' (tumbling-window-trigger-dependency doc). The section omitted this limit.
- IR CI/CD rule tightened: docs require the integration runtime 'name, type and sub-type' to match across stages (continuous-integration-delivery best practices; ci-cd troubleshoot guide DataFactoryPropertyUpdateNotSupported). Section said only 'type must be identical.' Also added that IR sharing as linked self-hosted is supported only for self-hosted IRs (not Azure-SSIS).
- Clarified the 256-parameter mitigations: the custom arm-template-parameters-definition.json does NOT change the 256 limit (it only reduces the parameter count), and the linked-templates auto-split (ArmTemplate_master.json + ArmTemplate_N.json in a linkedTemplates folder) is the mechanism for the 4-MB total-template-size limit, not strictly the 256-parameter limit. The section had conflated these.
- Diagnostic-logs mechanism made precise: dedicated tables ADFPipelineRun/ADFActivityRun/ADFTriggerRun appear only in Resource-Specific diagnostic mode; in Azure-Diagnostics mode logs go to the single AzureDiagnostics table (monitor-configure-diagnostics). Section implied the dedicated tables always apply.
- Backfill wording: docs say the M past runs are generated 'in parallel, honoring trigger concurrency.' Added 'in parallel' to match. Also changed 'spawns 30 backfill runs on publish' to 'on start' since backfill fires when the trigger is started, consistent with the section's own later note.
- Retry claim corrected: the section asserted tumbling-window 'auto-retries on 400, 429, and 500 status codes.' Microsoft's tumbling-window docs describe automatic retry of failed pipeline runs reusing the same input parameters but do NOT enumerate HTTP 400/429/500 as the trigger-level retry conditions (that status-code list is not in the trigger docs). Removed the unverifiable 400/429/500 claim and kept the documented behavior (auto-retry on pipeline failure, same input parameters).
- Rerun rules expanded to match the doc verbatim: added that If/Switch evaluate all inner activities (Execute Pipeline reruns), Until inner activities may be skipped, and Execute Pipeline triggers the child but child activities may be skipped per rerun rules. The section's version was slightly compressed.
- Removed the specific alert thresholds 'Total entities count > 1.7M, Total factory size (GB) > 6' which are illustrative numbers not grounded in the current docs; kept the verified canonical alert 'Failed pipeline runs > 0' and the metric names generically.
- Storage event types/required-filter detail added (Microsoft.Storage.BlobCreated/BlobDeleted; at least one of blobPathBeginsWith/blobPathEndsWith required; UI auto-inserts /blobs/ for begins-with) and the RBAC/Event-Grid relay note, all from how-to-create-event-trigger.
- Added a compact verified limits cheat-sheet (ForEach batchCount default 20/max 50/max 100,000 items; Lookup 5,000 rows / 4 MB / 24-hr; SHIR 4 nodes; 256 ARM params; 120 activities/pipeline; 45-day retention) — every figure confirmed against current docs (control-flow-for-each-activity, control-flow-lookup-activity, create-self-hosted-integration-runtime, azure-subscription-service-limits).

**Residual risks / verify-before-trusting:**

- Node 20.x recommendation for the @microsoft/azure-data-factory-utilities npm package: I kept the automated-CI/CD description but could not confirm the exact recommended Node version (20.x) in the docs I retrieved, so I removed the specific 'Use Node 20.x' line. The package and its use in an Azure Pipeline are confirmed; the Node version is unverified — check the continuous-integration-delivery-improvements page for the current pinned version.
- Tumbling window minimum interval: the dedicated trigger doc and the ARM/Bicep/Terraform schema all state 'minimum interval is 15 minutes', which is what I kept. However, the Azure subscription-service-limits table lists 'Minimum tumbling window trigger interval | 5 min | 15 min' under Default/Maximum columns, which is ambiguous and could be read as a 5-minute floor. The authoritative trigger docs win, but this is a known doc inconsistency.
- Custom event advanced-filter operator list (NumberIn, StringContains, BoolEquals, etc.) is a documented 'subset' that Microsoft expands over time as Event Grid GA API versions advance; the exact current operator set may differ slightly from what's shown.
- Per-pipeline detailed billing being 'not exported in the ARM template' is stated in the section and is consistent with the per-pipeline-billing limitations doc, but I did not find an explicit single sentence in the retrieved chunks confirming the ARM-export exclusion verbatim — it is inferred from the factory-setting + limitations docs. Low risk but not word-for-word verified.
- Exact dollar list prices ($ per 1,000 activity runs, per DIU-hour, per vCore-hour, the $0.193/core-hour figure) are explicitly hypothetical per Microsoft and live on the pricing page, not Learn — the FinOps $12.35/day example is reproduced verbatim from the doc and is illustrative only.
