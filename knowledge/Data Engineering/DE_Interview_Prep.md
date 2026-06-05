# Data Engineering Interview Prep — Q&A Bank

> **Purpose:** Self-test questions + graded "canonical answer" material from JARVIS career-switch prep sessions. Use this for spaced repetition before product-company DE interviews (Atlassian / Stripe / Snowflake / Databricks tier).
>
> **Format:** Each entry = the question, then the full graded answer (the correct material — what the user *should* be able to articulate in an interview). The user's attempt lives in chat history, not here.
>
> **Append-only.** New entries go under the matching domain section. Companion to [Data_Engineering_Lessons.md](Data_Engineering_Lessons.md) — that file is hard-won production lessons; this file is interview-shaped articulation drills.
>
> **Maintenance protocol:** Auto-updated by Claude Code at the end of any session where self-test questions get graded. See `feedback_de_interview_qna_capture.md` in auto-memory.

---

## Domain Sections

1. [Spark Internals](#spark-internals)
2. [Streaming Semantics](#streaming-semantics)
3. [Lakeflow / Spark Declarative Pipelines (SDP)](#lakeflow--spark-declarative-pipelines-sdp)
4. [Novartis Client Round — SDP 50-Question Bank](#novartis-client-round--spark-declarative-pipelines-sdp--lakeflow-50-question-bank)
5. [System Design (Data)](#system-design-data)
6. [Distributed Systems Theory](#distributed-systems-theory)
7. [Coding](#coding)
8. [Behavioral (STAR)](#behavioral-star)

---

## Spark Internals

### Q1 — Execution stages + Catalyst/Tungsten

**Question:** Walk through what happens between `df.groupBy("k").agg(sum("v"))` being called and the result returning. Name every stage: logical plan → analyzed → optimized → physical → tasks. Where does Catalyst run? Where does Tungsten run?

**Canonical answer:**

Two logical plans, not one:

1. **Unresolved Logical Plan** — parser output. Just an AST. No validation. Column names are strings.
2. **Analyzed Logical Plan** — the Analyzer walks the unresolved tree and resolves every column/table against the catalog. **This is the step that throws `AnalysisException`** when a column doesn't exist.

Then:

3. **Optimized Logical Plan** — Catalyst's rule-based optimizer applies predicate pushdown, column pruning (projection pushdown), constant folding, projection pushdown, filter combining, boolean simplification.
4. **Physical Plan** — SparkPlanner + cost-based optimizer (CBO) picks: which join algorithm (SortMergeJoin vs BroadcastHashJoin vs ShuffleHashJoin), which aggregation strategy (HashAggregate vs SortAggregate), which exchange (HashPartitioning vs RangePartitioning). If stats exist (`ANALYZE TABLE`), CBO uses them to pick the cheapest.
5. **Whole-Stage Codegen (Tungsten)** — fuses operators in a stage into one compiled JVM method to eliminate virtual-call overhead.
6. **DAGScheduler → Stages** — split at shuffle boundaries.
7. **TaskScheduler → Tasks** — one per partition per stage.
8. **Executors run tasks.**

Full chain (memorize this exactly — interviewers ask in this order):

```
SQL/DataFrame API
   ↓
Parser → Unresolved Logical Plan          ← AST only, no validation
   ↓
Analyzer → Analyzed Logical Plan          ← resolves columns/tables; AnalysisException here
   ↓
Catalyst Optimizer → Optimized Logical Plan
   ↓ (rule-based: predicate pushdown, column pruning, constant folding,
       projection pushdown, filter combining, boolean simplification)
SparkPlanner + CBO → Physical Plan         ← picks join/agg algorithm, exchanges
   ↓
Whole-Stage Codegen (Tungsten) → bytecode
   ↓
DAGScheduler → Stages (split at shuffle boundaries)
   ↓
TaskScheduler → Tasks (one per partition per stage)
   ↓
Executors run tasks
```

**Catalyst** = the optimizer framework. Spans Parser → Analyzer → Logical Optimizer → Physical Planner. So it's the *whole front end*, not just "the start."

**Tungsten** = the execution engine. Three pillars:
1. **Whole-stage codegen** — fuses operators in a stage into one compiled JVM method to eliminate virtual-call overhead.
2. **Off-heap memory management** — bypasses JVM GC.
3. **Cache-aware computation** — uses CPU L1/L2 layout.

Runs at task execution time, not "after the physical plan is laid out."

**Common confusions to avoid:**
- `AnalysisException` is thrown at *Analyzed Logical Plan* (catalog resolution), NOT at the unresolved plan or the optimized plan.
- "Predicate pushdown" pushes *filters* (`WHERE`) to the source. "Column pruning / projection pushdown" pushes *which columns to read*. `groupBy("k").agg(sum("v"))` triggers column pruning, NOT predicate pushdown.

---

### Q2 — AQE optimizations

**Question:** AQE has 3 main optimizations. Name them, give the exact knob for each, and the conditions under which each fires.

**Canonical answer:**

**Critical:** AQE does NOT do predicate pushdown. Predicate pushdown is a *static* Catalyst rule that fires at plan-optimization time, before execution starts. AQE is by definition *runtime* — it can only use information that doesn't exist until stages have actually run.

The actual three:

| AQE optimization | What it does | Knob | Fires when |
|---|---|---|---|
| **Dynamic Shuffle Partition Coalescing** | After a shuffle completes, AQE looks at actual post-shuffle partition sizes. If many are tiny, it coalesces them into fewer, larger partitions before the next stage. | `spark.sql.adaptive.coalescePartitions.enabled` + `spark.sql.adaptive.advisoryPartitionSizeInBytes` (default 64MB) | Default `spark.sql.shuffle.partitions=200` left lots of tiny partitions; AQE shrinks them. |
| **Dynamic Join Strategy Switching** | After scanning the build side, if its real size is smaller than the broadcast threshold, AQE switches a planned `SortMergeJoin` → `BroadcastHashJoin` at runtime. | `spark.sql.adaptive.autoBroadcastJoinThreshold` (defaults to `spark.sql.autoBroadcastJoinThreshold`, usually 10MB) | Filter on the build side at runtime made it smaller than the static planner could predict. |
| **Dynamic Skew Join Handling** | After a shuffle, AQE detects skewed partitions and splits them into sub-partitions, replicating the matching side. | `spark.sql.adaptive.skewJoin.enabled` + `spark.sql.adaptive.skewJoin.skewedPartitionFactor` (default 5) + `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` (default 256MB) | A partition is both `> median × factor` AND `> threshold`. |

Master switch: `spark.sql.adaptive.enabled = true` (default true since Spark 3.2).

**The senior-bar insight to articulate:** AQE works because it has *runtime statistics* (post-shuffle partition sizes, actual row counts), which the static planner doesn't. Static plan uses table stats (potentially stale, potentially absent). AQE uses what just happened. That's why it catches cases static optimization misses — and why it *can't* do predicate pushdown (predicates have to be pushed *before* the scan, by definition before there are any runtime stats).

---

### Q3 — 500GB fact joining 2GB dim, 90 min runtime

**Question:** You have a 500GB fact joining a 2GB dimension. Default joins ran 90 minutes. Walk through what you'd inspect in the physical plan and the 4 things you'd try in priority order.

**Canonical answer:**

**Things to inspect in the physical plan:**
```
== Physical Plan ==
*(5) Project [...]
+- *(5) BroadcastHashJoin [k#1], [k#10], Inner, BuildRight    ← join algorithm
   :- *(5) ColumnarToRow                                        ← vectorized read
   :  +- FileScan parquet [k#1,v#2]                            
   :        Batched: true, 
   :        DataFilters: [isnotnull(k#1)],                     ← any pushed predicates
   :        PartitionFilters: [],                              ← partition pruning
   :        PushedFilters: [IsNotNull(k)],                     ← pushed to file reader
   :        ReadSchema: struct<k:string,v:bigint>              ← column pruning shows here
   +- BroadcastExchange HashedRelationBroadcastMode(...)        ← broadcast happening
      +- FileScan parquet ...
```

Scan for:
- `BroadcastHashJoin` vs `SortMergeJoin` — your join algorithm.
- `Exchange hashpartitioning(k#1, 3000)` — how many shuffle partitions.
- `PartitionFilters: [...]` — is partition pruning happening.
- `*(N)` prefix — whole-stage codegen boundary (operators in the same `*(N)` are fused into one compiled method).

**Four fixes in priority order:**

**1. Shuffle partition count — almost always the #1 fix.**
Default `spark.sql.shuffle.partitions = 200`. With 500GB joined, each partition is ~2.5GB. That's way too big — each task chokes on memory pressure and spill. Target: **100–200 MB per partition**. So for 500GB you want **2500–5000 shuffle partitions**, not 200.
```python
spark.conf.set("spark.sql.shuffle.partitions", 3000)
```
Or let AQE coalesce — but AQE can only *shrink*, not grow. Must start with enough.

**2. Force broadcast — 2GB is borderline but possible.**
Default `spark.sql.autoBroadcastJoinThreshold = 10MB`. A 2GB dim won't broadcast automatically. Options:
- Raise threshold: `spark.sql.autoBroadcastJoinThreshold = 2GB`. Risky — every executor and the driver must hold a 2GB copy.
- Use a hint: `df_fact.join(broadcast(df_dim), "k")`. Explicit. Safer.
- **Check driver memory** before doing this — broadcast goes through the driver. If driver has 4GB, 2GB broadcast is suicidal.

**3. Partition pruning on the fact.**
If the 500GB fact is partitioned (by date, region, etc.) and the join predicate or upstream filter touches the partition column, only the matching partitions get read. Reading 50GB instead of 500GB is a 10× speedup before you touch anything else. Check `PartitionFilters: [...]` in the physical plan.

**4. Bucketing on the join key.**
If both tables are bucketed on `k` with the same number of buckets, Spark skips the shuffle entirely — `SortMergeJoin` becomes a *co-located* join. Highest-leverage fix when applicable, but requires upstream pipeline changes (you can't bucket after the fact cheaply).

**Secondary diagnostic instincts:**
- Look for **data explosion** (cardinality blowup post-join) if the dim has duplicates.
- Look for **skew** via `df.groupBy("k").count().orderBy(desc("count")).show()`.

---

### Q4 — Skew on a single key (99% in one key)

**Question:** Skew on a single key (1B rows, 99% in one key). DLT and Spark both. Three different fixes — list them by side-effect impact.

**Canonical answer:**

Three fixes, lowest to highest side-effect:

**1. AQE skew join — zero code, lowest impact.**
```python
spark.conf.set("spark.sql.adaptive.enabled", True)
spark.conf.set("spark.sql.adaptive.skewJoin.enabled", True)
```
At runtime, AQE detects partitions where `size > median × 5 AND size > 256MB`, splits each into sub-partitions, and replicates the matching side of the join.
**Caveat:** only works for *joins*, not aggregations. For `groupBy("k").agg(...)` on a skewed `k`, AQE skew join doesn't help.

**2. Salting — medium impact, code change but no data-model change.**
```python
from pyspark.sql.functions import rand, expr, explode, array, lit
N = 100
df_skewed_salted    = df_skewed.withColumn("salt", (rand() * N).cast("int"))
df_other_replicated = df_other.withColumn("salt", explode(array([lit(i) for i in range(N)])))
joined = df_skewed_salted.join(df_other_replicated, ["k", "salt"])
```
The hot key gets spread across N partitions; the other side gets replicated N× (so a 2GB dim becomes 200GB if N=100 — choose N carefully).

For `groupBy + agg`, salt-then-double-aggregate:
```python
df.withColumn("salt", (rand()*N).cast("int")) \
  .groupBy("k", "salt").agg(sum("v").alias("partial")) \
  .groupBy("k").agg(sum("partial").alias("v"))
```

**3. Two-stage isolation / hot-key separation — highest impact, ugly, last resort.**
Split into `df_hot = df.filter(col("k") == hot_key)` and `df_cold = df.filter(col("k") != hot_key)`. Process the hot side differently (often: broadcast the hot key's other-side rows, do a small in-memory join). Union the results.
**Side effect:** explicit knowledge of which key is hot — breaks when hot key shifts.

**DLT vs raw Spark difference:**
- DLT: Spark configs set at pipeline level (`pipelines.spark_conf` in bundle YAML, or via cluster definition).
- DLT doesn't have a declarative skew hint, but the underlying Spark accepts `/*+ SKEW('a', 'k') */` SQL hints inside `spark.sql(...)` blocks.
- AQE is **on by default in DLT** (always). In raw Spark, verify.

---

### Q5 — `df.cache()` vs `df.persist(StorageLevel.MEMORY_AND_DISK_SER)`

**Question:** `df.cache()` vs `df.persist(StorageLevel.MEMORY_AND_DISK_SER)` — when does the choice change behavior, not just performance?

**Canonical answer:**

**Baseline:** For DataFrames, `df.cache()` is *identical* to `df.persist(StorageLevel.MEMORY_AND_DISK)` (not `MEMORY_ONLY`). It's only `MEMORY_ONLY` for legacy RDDs. So the comparison reduces to: `MEMORY_AND_DISK` vs `MEMORY_AND_DISK_SER`. The `_SER` variant serializes to bytes (Kryo by default) — smaller in memory but costs CPU to decode on read.

**Where this stops being just a performance choice:**

The cached DataFrame contains **non-deterministic operators**, e.g.:
```python
df_with_id = df.withColumn("rid", monotonically_increasing_id())
df_with_ts = df.withColumn("ingest_ts", current_timestamp())
df_sampled = df.sample(0.1)            # random
df_udf     = df.withColumn("x", my_random_udf(...))
```

Under memory pressure, partitions can be **evicted and recomputed**.
- `MEMORY_AND_DISK` (deserialized): prefers keeping deserialized partitions in memory until pressure forces a *spill to disk* (still cached, just on disk).
- `MEMORY_AND_DISK_SER`: more partitions fit in memory (smaller), so less spill. But under enough pressure, *either* can evict and recompute.

**On recompute, non-deterministic operators produce different values.** `monotonically_increasing_id()` regenerates with different IDs. `current_timestamp()` returns a different timestamp. `rand()` without a seed produces different samples. **Downstream operations now see different values from a "cached" DataFrame.** This is a real correctness bug.

**Mitigations:**
- Avoid non-determinism in the cached DataFrame (compute deterministically *before* caching, e.g., use `row_number()` over a stable ordering instead of `monotonically_increasing_id()`).
- Persist with replication (`MEMORY_AND_DISK_2`) so eviction is rarer.
- Write to a Delta table and read back — durable, deterministic.

**Why this is the senior-bar answer:** the "performance vs serialization tradeoff" is the expected first-order answer. The non-determinism gotcha is what interviewers want to hear. Secondary: with `_SER`, executor OOMs are rarer because partitions are smaller, so jobs *complete* that otherwise fail. "Did it run vs not" is also a behavior change in some sense.

---

### Q1-deep — Catalyst rule-based optimizations, individually

**Question:** Explain each of the rule-based optimizations Catalyst applies — predicate pushdown, column pruning, constant folding, projection pushdown, filter combining, boolean simplification.

**Canonical answer:**

These are **rule-based optimizations (RBO)** — always fire if the pattern matches, no cost calculation. Distinct from CBO (uses table stats) and AQE (uses runtime stats). Three different layers.

**Predicate pushdown**
- Push `WHERE` filter conditions ("predicates") as close to the data source as possible.
- Two flavors: (a) *pushdown to scan operator* — filter happens inside the scan; fewer rows materialized into the next operator; (b) *pushdown to data source* — Parquet/Delta file readers use min/max statistics in column chunk metadata to **skip entire row groups** that can't match.
- Example: `SELECT * FROM sales WHERE year = 2025`. Parquet stores min/max per column per row group. A row group whose `year` range is [2023, 2023] never gets read.
- Doesn't fire for: UDFs (Spark can't evaluate them at the data-source level), non-deterministic functions (`rand()`, `current_timestamp()`), most string functions on Parquet.
- Inspect via `df.explain('formatted')` → look for `PushedFilters: [...]`.

**Column pruning**
- Only read the columns the query actually needs.
- Possible because Parquet/Delta are *columnar* — each column is physically stored separately. Reading 3 columns out of 50 = ~6% of bytes off disk.
- Example: `df.select("a", "b").filter(...)` reads only `a` and `b`.
- In `explain`: `ReadSchema: struct<a:string,b:bigint>` lists only surviving columns.

**Constant folding**
- Evaluate constant expressions at *plan time*, not per-row at execution time.
- `WHERE x + 1 = 5` → rewritten to `WHERE x = 4` (arithmetic happens once instead of per-row).
- `SELECT 1 + 1 AS two` → `SELECT 2 AS two`.
- `WHERE col = CAST('2025-01-01' AS DATE)` → CAST evaluated at plan time.
- Often enables subsequent rules (boolean simplification fires after constant folding produces TRUE/FALSE).

**Projection pushdown**
- Push the *projection list* (SELECT columns/expressions) through joins, unions, and aggregations so columns are pruned as early as possible across the *whole plan*.
- Difference from column pruning: column pruning is *at the source* (file reader); projection pushdown is *across operators* (the plan).
- Example: `SELECT a FROM (t1 JOIN t2 ON t1.k = t2.k)`. Projection pushdown realizes the final output needs only `a` (from t1), then rewrites the join to read `{a, k}` from t1 and `{k}` from t2. Without it, every column flows through the shuffle.
- Column pruning is the *terminal* step of projection pushdown — after the projection is pushed to the scan, the scan tells the file format which columns to read.

**Filter combining (combine filters)**
- Merge adjacent Filter operators into one Filter with `AND`.
- `.filter(...).filter(...)` initially produces two Filter operators; merged to one means a single pass over the data.
- Also covers: pushing filters above projections — `.select(a, b).filter(a > 5)` → `.filter(a > 5).select(a, b)` because filtering before projecting reduces row count first.
- In `explain`: exactly one `Filter` node for chained filters in the optimized plan.

**Boolean simplification**
- Apply Boolean algebra to clean up logical expressions.
- `WHERE TRUE` → drop the filter entirely. `WHERE FALSE` → return empty without scanning.
- `WHERE a AND TRUE` → `WHERE a`. `WHERE a OR FALSE` → `WHERE a`.
- `NOT (a AND b)` → `(NOT a) OR (NOT b)` (De Morgan's).
- Tautology elimination: `WHERE x > 0 OR x <= 0` (assuming non-null) → `WHERE TRUE` → drop.
- Usually fires after constant folding resolves subexpressions to TRUE/FALSE.

**Interview frame:** there are ~80+ Catalyst rules in `org.apache.spark.sql.catalyst.optimizer.Optimizer`. The six above are the most-asked. Other names worth knowing: `NullPropagation`, `FoldablePropagation`, `CollapseProject`, `ReorderJoin` (CBO-driven), `EliminateOuterJoin`.

---

### Q1-deep — Does the Parser → Unresolved chain repeat per stage?

**Question:** After `DAGScheduler → Stages (split at shuffle boundaries)`, does the Parser → Unresolved Logical Plan chain repeat for each stage?

**Canonical answer:**

**No.** The pipeline `Parser → Unresolved → Analyzed → Optimized Logical → Physical` runs **once per action**, not per stage.

What DOES happen per stage at runtime:
- **Whole-stage codegen (Tungsten)** runs *per stage* — operators within a stage get fused into one compiled JVM method.
- **AQE** can re-plan the *remaining* Physical Plan after each shuffle stage completes, using observed runtime stats. This is "amend the existing Physical Plan," NOT "rerun Parser→Unresolved."

The full picture:

```
ACTION TRIGGERS (.show(), .collect(), .write(), .count())
   ↓
Parser → Unresolved → Analyzed → Optimized Logical → Physical Plan
   ↓                       (ONCE per action)
DAGScheduler splits Physical Plan into Stages at shuffle boundaries
   ↓
For each stage:
   - Tungsten codegen compiles operators in this stage to bytecode
   - TaskScheduler creates one Task per partition
   - Tasks run on executors
   - (If AQE enabled) After stage completes, AQE inspects shuffle output stats
       and may RE-OPTIMIZE the remaining stages' Physical Plan
   ↓
Next stage runs with possibly amended Physical Plan
```

Related clarifications:
- **Transformations are lazy.** `df.groupBy("k").agg(sum("v"))` builds the plan but doesn't execute.
- **Actions trigger.** `.show()`, `.collect()`, `.write...()`, `.count()` run the full pipeline.
- **Multiple actions on the same DataFrame re-run the plan** unless cached/persisted.
- **AQE's re-optimization is incremental.** It doesn't re-derive a Physical Plan from scratch — it applies targeted rewrites: "this SortMergeJoin → BroadcastHashJoin," "these 200 tiny partitions → 20 coalesced," "this skewed partition → 8 sub-partitions."

In `df.explain('formatted')` with AQE on, you'll see `AdaptiveSparkPlan` wrapping the physical plan — and at runtime in the Spark UI the plan literally morphs between stages.

---

### Q1-deep — Full execution lifecycle, chronologically (the "movie")

**Question:** Walk through, in chronological order, exactly what runs and how many times when a real query with narrow + wide transformations and an action executes — including DAGScheduler, per-stage Tungsten codegen, TaskScheduler, executors, and AQE.

**Canonical answer:**

Good catch — that block is the *runtime* half, and I stopped the movie right at the shuffle without showing the machinery that actually dispatches and runs the work. Let me re-run the same movie with those gears installed. Same tiny `sales` file (2 partitions, answer is NYC 300 / LA 600), same script. I'll keep T+0 through T+2 short since you've got them, and expand the moment `.show()` fires.

---

## Recap of the lazy part (T+0 → T+2)

```python
df  = spark.read.parquet("sales")        # T+0  → sticky note, nothing runs
us  = df.filter("country = 'US'")        # T+1  → sticky note (narrow)
agg = us.groupBy("city").sum("amount")   # T+2  → sticky note (WIDE = needs a shuffle)
```

Three sticky notes on the wall. No file touched yet. Now the trigger.

The `sales` file, split into **2 partitions** (each partition = "a piece of the data that one worker handles"):

```
PARTITION A (handled by Worker 1)      PARTITION B (handled by Worker 2)
  NYC,    US, 100                        LA,     US, 300
  LA,     US, 200                        NYC,    US, 50
  London, UK, 50                         Berlin, DE, 90
  NYC,    US, 150                        LA,     US, 100
  Paris,  FR, 80                         London, UK, 70
```

---

## ⏱ T+3 — `agg.show()` fires

### Step A — Plan, **once**, on the driver

The **driver** (the boss machine / your `SparkSession`) reads the sticky notes and produces one optimized physical plan: *read → filter US → partial-sum → shuffle → final-sum*. This is the Catalyst pipeline. **One time per action.** Done. Now it hands off to runtime.

### Step B — Cut the plan into Stages at the shuffle (the **DAGScheduler**)

The **DAGScheduler** is the part of the driver that slices the plan wherever a shuffle happens. One shuffle (the `groupBy`) → **2 stages**:

```
STAGE 1: read → filter US → partial sum     ──shuffle──▶   STAGE 2: final sum → show
```

Here's the key thing the last answer skipped: **Spark does not run both stages at once.** Stage 2 *cannot* start until Stage 1's shuffle output physically exists. So Spark walks the stages **in order**, and before any stage's data is touched, it does two prep jobs. Watch Stage 1 fully, then the AQE checkpoint, then Stage 2.

---

### STAGE 1 — start to finish

**B1 — Tungsten codegen (compile this stage, once)**

Naively, Spark would walk every row asking "filter? yes. now sum? yes." — millions of tiny function calls, slow. Instead, **Tungsten codegen** writes *one custom Java function* for the whole fused stage (read + filter + partial-sum together) and compiles it to **bytecode** (the low-level instructions the JVM actually runs).

- Happens **once per stage**, on the driver.
- The compiled function is then *shipped to every executor* and **reused for all that stage's partitions** — it is NOT recompiled per partition or per row.

So: Stage 1 → 1 compiled function.

**B2 — TaskScheduler hands out the work**

The DAGScheduler gives Stage 1 to the **TaskScheduler** (the dispatcher). It creates **one task per partition** — a **task** = "run this stage's compiled function on one partition." 2 partitions → **2 tasks**. It then places each task on an **executor**.

> **Executor** (define): a worker process (a JVM) running on a worker machine, with some CPU cores and memory. It's the thing that actually *executes* tasks. The driver coordinates; executors do the labor.

So: Task-1 → Executor on Worker 1 (Partition A), Task-2 → Executor on Worker 2 (Partition B).

**B3 — Tasks run on the executors (in parallel)**

Each executor runs the compiled Stage-1 function on its partition:

- **Worker 1 / Partition A:** read 5 rows → keep US → `NYC 100, LA 200, NYC 150` → partial sum: **NYC 250, LA 200**
- **Worker 2 / Partition B:** read 5 rows → keep US → `LA 300, NYC 50, LA 100` → partial sum: **NYC 50, LA 400**

**B4 — Shuffle write**

Each executor writes its partial results to local shuffle files, bucketed by city, ready to be picked up by Stage 2. Stage 1 is now *done*.

---

### ⏱ AQE checkpoint — *after* Stage 1, *before* Stage 2

Now that real data exists on disk, **AQE (Adaptive Query Execution)** wakes up and reads the actual shuffle stats: *"How big is the data? How many groups?"*

In our case it sees: **only 2 cities, a few bytes.** But the original plan said "use 200 reduce partitions for Stage 2" (Spark's default). That would spawn 200 tasks to process 2 rows — absurd. So AQE **amends Stage 2's plan**: coalesce 200 → **1 partition**.

Two things to nail here:
- AQE **amends the not-yet-run stages' physical plan** — it does *not* re-run Step A (the Catalyst pipeline). The plan is edited in place, not rebuilt.
- It fires **once per shuffle boundary**. We have 1 shuffle → 1 AQE checkpoint. (A query with 3 shuffles gets 3 such checkpoints, each between two stages.)

---

### STAGE 2 — start to finish

Same prep loop, now on the amended plan:

- **Codegen:** compile Stage 2's operator (final-sum) → 1 compiled function (Stage 2's own).
- **TaskScheduler:** create tasks = **1 task** now (thanks to AQE's coalesce; would've been 200), placed on one executor.
- **Run:** that executor reads the shuffle files and finishes the sums:
  - NYC = 250 + 50 = **300**
  - LA = 200 + 400 = **600**

### Step F — result to the driver → your screen

```
+----+-----------+
|city|sum(amount)|
+----+-----------+
| NYC|        300|
|  LA|        600|
+----+-----------+
```

---

## The full chronological skeleton

```
agg.show()  ── ACTION fires
  │
  ├─ Step A: PLAN (Catalyst pipeline)         ── driver, ONCE per action
  │
  ├─ Step B: DAGScheduler cuts at shuffle     ── 1 shuffle → 2 stages
  │
  ├─ STAGE 1  (runs first)
  │     ├─ Tungsten codegen     → 1 compiled function for this stage
  │     ├─ TaskScheduler        → 1 task per partition (2 tasks)
  │     ├─ tasks run on executors → partial sums
  │     └─ shuffle write
  │
  ├─ ✦ AQE checkpoint  ── after Stage 1's shuffle; amends Stage 2 (200→1 partition).
  │                       Does NOT re-run Step A.
  │
  ├─ STAGE 2  (runs after Stage 1 + AQE)
  │     ├─ Tungsten codegen     → 1 compiled function for this stage
  │     ├─ TaskScheduler        → 1 task (after AQE coalesce)
  │     └─ tasks run on executors → final sums
  │
  └─ Step F: result → driver → screen
```

---

## Updated counting table

| Thing | How many times | Tied to |
|---|---|---|
| **Catalyst plan** (Step A) | Once | the **action** |
| **DAGScheduler split** | Once per job | the action |
| **Stages** | (number of shuffles) + 1 | each **wide** transformation |
| **Tungsten codegen** | Once **per stage** (compiled on driver, reused by all that stage's tasks) | each stage |
| **Tasks** | One **per partition, per stage** | partitions |
| **Executors** | The worker processes that *run* the tasks | cluster size |
| **AQE re-optimization** | Once **per shuffle boundary** (amends, never rebuilds) | each shuffle |
| **Whole job re-run** | Once **per action**, unless `cache()` | each action |

---

## Textbook-name map (everything you just watched)

- **Driver** — coordinator; runs Step A, the DAGScheduler, and the TaskScheduler.
- **Catalyst pipeline** — Step A planning (*Parser → Analyzed → Optimized → Physical*). Once per action.
- **DAGScheduler** — cuts the plan into stages at shuffles (Step B).
- **Tungsten / whole-stage codegen** — compiles each stage's fused operators into one bytecode function (B1). Once per stage.
- **TaskScheduler** — creates one task per partition and assigns it to an executor (B2).
- **Executor** — the worker JVM that actually runs tasks (B3).
- **Shuffle** — the data movement at a wide transformation; the boundary between two stages (B4).
- **AQE** — re-optimizes the *remaining* stages after a shuffle, using real stats (the checkpoint). Amends, doesn't rebuild.

---

**One-liner, now complete:** *The action triggers one plan (driver/Catalyst); the DAGScheduler cuts it into stages at each shuffle; for each stage in turn, Tungsten compiles it once, the TaskScheduler launches one task per partition onto executors, and after each shuffle AQE amends the remaining stages — then the next action does it all again unless you `cache()`.*

---

### Q3-deep — Every Spark join algorithm, properly

**Question:** Give a proper explanation of each Spark join algorithm — SortMergeJoin, BroadcastHashJoin, ShuffleHashJoin, BroadcastNestedLoopJoin, CartesianProduct.

**Canonical answer:**

Five algorithms. Spark picks one based on join type, predicate shape, and size estimates.

**BroadcastHashJoin (BHJ) — fastest when feasible**
- Mechanism: smaller side collected to driver → broadcast to every executor → each executor builds an in-memory hash table from the broadcast side → big side iterated locally, each row probes the hash table.
- Cost: zero shuffle. One broadcast (driver → executors).
- Constraints: build side fits in driver AND executor memory. Auto-picked when one side's estimated size < `spark.sql.autoBroadcastJoinThreshold` (default 10MB). Force via `broadcast(df2)` or `/*+ BROADCAST(t2) */`.
- Supports: inner, left outer (only big side as probe), right outer (only small side as probe), left semi, left anti, cross. **NOT full outer.**
- Failure mode: OOM on driver or executor if broadcast side too big.

**SortMergeJoin (SMJ) — the workhorse**
- Mechanism: both sides hash-partitioned by join key (shuffle) so matching keys land on same partition → within each partition, both sides sorted by join key → merge-style scan: two pointers walk through both sorted streams, emitting matched pairs.
- Cost: 2 shuffles + 2 sorts. Expensive but **predictable**.
- Constraints: none on size — handles arbitrarily large joins. Spills to disk if sort doesn't fit in memory.
- Default since Spark 2.3 (`spark.sql.join.preferSortMergeJoin = true`).
- Supports every join type including full outer.

**ShuffleHashJoin (SHJ) — rare in practice**
- Mechanism: both sides shuffled by join key (like SMJ step 1) → after shuffle, build a hash table from the smaller side **per partition** (not broadcast) → probe with larger side per partition.
- Cost: 2 shuffles, no sort. Hash table per partition (memory cost).
- Constraints: per-partition build side must fit in executor memory. Skew → OOM.
- Disabled by default since Spark 2.4 — SMJ preferred because it degrades gracefully (sort spills to disk) while SHJ explodes.
- Force via `df.hint("shuffle_hash")` or `/*+ SHUFFLE_HASH(t) */`.
- Niche win: small-but-not-broadcastable build side, low cardinality, no skew.

**BroadcastNestedLoopJoin (BNLJ) — for non-equi joins**
- Mechanism: smaller side broadcast → for each row on the big side, iterate over the entire broadcast side looking for matches.
- Cost: O(N×M) per partition. Catastrophic unless one side tiny.
- When it fires: any join WITHOUT an equi-join condition. `t1.a < t2.b`, `t1.a BETWEEN t2.lo AND t2.hi`, `t1.a LIKE t2.pattern`, cross joins with WHERE.
- The only choice for non-equi joins — Spark has no efficient non-equi algorithm.

**CartesianProduct (Cross Join)**
- Every row × every row. No condition.
- O(N×M). Almost always a bug.
- Knob: `spark.sql.crossJoin.enabled = true` (default true since 3.0). Set false in prod to force explicit `CROSS JOIN` syntax and catch accidents.

**Decision flow (the interview answer):**

```
1. No equi-join condition?
     → BroadcastNestedLoopJoin (if one side broadcastable)
       OR CartesianProduct (if no condition at all)

2. Equi-join exists. Smaller side < autoBroadcastJoinThreshold?
     → BroadcastHashJoin              ← fastest, preferred

3. Neither side broadcastable, build side per partition fits in memory,
   AND SHJ hint provided?
     → ShuffleHashJoin                ← rare, requires explicit hint

4. Else
     → SortMergeJoin                  ← default for large joins
```

**Hints reference:**

| Goal | DataFrame | SQL |
|---|---|---|
| Force broadcast | `broadcast(df2)` or `df2.hint("broadcast")` | `/*+ BROADCAST(t2) */` |
| Force sort-merge | `df2.hint("merge")` | `/*+ MERGE(t2) */` |
| Force shuffle-hash | `df2.hint("shuffle_hash")` | `/*+ SHUFFLE_HASH(t2) */` |
| Force shuffle-replicate-NL | `df2.hint("shuffle_replicate_nl")` | `/*+ SHUFFLE_REPLICATE_NL(t2) */` |

Inspect which join Spark picked: `df.explain('formatted')` → look for join operator name; Spark UI → SQL tab → click query → visual DAG.

---

### Q2-deep — Why AQE can't do predicate pushdown (the temporal argument)

**Question:** Go deeper on "AQE works because it has runtime statistics… that's why it can't do predicate pushdown."

**Canonical answer:**

The deep reason is **temporal**: scanning is the *first* thing that happens, so anything that wants to influence the scan must happen *before* it.

**The temporal argument:**
- Predicate pushdown's value is reducing **bytes read off disk**.
- Bytes read off disk happen at the scan operator.
- The scan is the *first* operator in the plan.
- Therefore, anything influencing the scan must be decided **before any execution starts**.
- AQE's earliest possible action is *after a stage completes*. The first stage that produces stats is, by definition, after the scan.
- By that point, the data is already read. You can't un-read 500GB and re-read it with a tighter filter.

**The narrow exception — Dynamic Partition Pruning (DPP):**

DPP is real runtime predicate-pushdown-like behavior, but it's a separate feature (not part of AQE's three optimizations). Knob: `spark.sql.optimizer.dynamicPartitionPruning.enabled = true` (default).

Scenario:
```sql
SELECT *
FROM sales s                           -- 500GB, partitioned by date
JOIN dim_dates d ON s.date_key = d.date_key
WHERE d.is_holiday = TRUE             -- selects 12 dates out of 3 years
```

Static problem: Spark doesn't know at plan time which 12 dates `is_holiday = TRUE` will match. A static partition filter on `s` can't be created.

DPP flow:
1. Execute the dim_dates filter first (small table, fast).
2. Collect the resulting `date_key` values.
3. **Use those values as a runtime partition filter on the sales scan.**
4. Sales scan reads only those 12 partitions instead of all ~1000.

This is the **only** form of runtime predicate pushdown in modern Spark. Narrow: only for partition columns, only when the dim side is broadcastable, only for joins.

**Why static stats are unreliable (the deeper reason AQE matters):**

1. **Stats are populated by `ANALYZE TABLE name COMPUTE STATISTICS`.** Most teams don't run this religiously. Stale or missing stats are the norm.
2. **Stats are table-level summaries.** Don't capture per-key distributions accurately. Column histograms exist (`spark.sql.statistics.histogram.enabled`) but disabled by default.
3. **Stats can't predict intermediate-result cardinality.** `(t1 JOIN t2)` cardinality depends on key-correlation in actual data; static optimizers use rough heuristics (often `n_left × n_right / max(distinct_left, distinct_right)`) that are wrong by orders of magnitude.
4. **Stats are point-in-time.** Stale after every load until re-ANALYZE.

That's the blind spot AQE fills: **observed cardinality of actual data is ground truth, no estimation error**.

**The clean two-bucket frame for interviews:**

| | Pre-scan optimization | Post-scan optimization |
|---|---|---|
| **Time** | Plan time (before execution) | Runtime (after stage completes) |
| **Input** | Query text + table stats | Actual row counts / partition sizes |
| **Examples** | Predicate pushdown, column pruning, projection pushdown, constant folding | Shuffle partition coalescing, join strategy switching, skew handling |
| **Owner** | Catalyst (rule-based) + CBO (cost-based, if stats exist) | AQE |
| **Limit** | Wrong if stats are wrong | Can only fix what hasn't executed yet |

DPP threads the needle — runtime, but does a small read first (the dim filter) to inform the big read (the fact scan).

**Senior-bar one-liner:** "AQE is fundamentally post-scan; predicate pushdown is fundamentally pre-scan. DPP is the narrow exception, only for partition columns on broadcastable-dim joins."

---

## Streaming Semantics

### Q6 — Watermarks

**Question:** What is a watermark in Structured Streaming? What does setting `withWatermark("event_time", "10 minutes")` actually mean, and what happens to late data that arrives after the watermark threshold?

**Canonical answer:**

A watermark is a **dropping threshold on event time** — not a wait window. It tells Spark: "I don't expect data older than X relative to the latest data I've seen."

**Exact definition:**
```
watermark = max(event_time seen so far) − threshold
```
`withWatermark("event_time", "10 minutes")` means: at any point in the stream, the watermark = the highest `event_time` Spark has observed minus 10 minutes. Any row with `event_time < watermark` is considered too late and is **silently dropped** from stateful operations.

**Primary use case — windowed aggregations:**
```python
df.withWatermark("event_time", "10 minutes") \
  .groupBy(window("event_time", "1 hour")).count()
```
Without a watermark, Spark can never safely evict state for old windows (a record could theoretically arrive from any past timestamp) → unbounded state accumulation → OOM. The watermark tells Spark when a window is finalized: once `watermark > window_end`, no late record can change that window → state is safe to evict.

**Secondary use case — stream-stream joins:**
Both sides buffer rows in state waiting for a match from the other side. The watermark on each side bounds how long rows are kept waiting. Rows older than the watermark are dropped from both sides' state buffers.

**What a watermark does NOT do:**
- It does not delay processing waiting for late data to arrive.
- It does not guarantee all late data is captured — data arriving after the watermark threshold is dropped silently.
- It does not affect sources or reading — only what happens to late rows once they're read.

**In `explain` / Spark UI:** look for `EventTimeWatermark` in the physical plan. In Spark UI → Structured Streaming tab → watermark timestamp advances as max event time advances.

---

### Q7 — Exactly-once semantics

**Question:** What does "exactly-once" mean in Spark Structured Streaming? What are the three components that must all be in place to achieve it end-to-end?

**Canonical answer:**

**Definition:** Each input record produces exactly one output effect — no duplicates written to the sink, no records silently dropped. Distinct from:
- **At-most-once**: records may be dropped on failure. Simpler but lossy.
- **At-least-once**: records are never dropped but may be duplicated on restart. Most common default.

Exactly-once is hard because crashes cause restarts, restarts cause source re-reads from the last checkpoint, and re-reads cause duplicate writes unless the sink is idempotent.

**The three required components:**

**1. Replayable source**
The source must support re-reading from a specific offset after a failure. Kafka: replay from committed offset. File sources (ADLS, S3): files are immutable, re-read by path. The source must expose a monotonically advancing offset that Spark can checkpoint.

**2. Idempotent sink (or transactional sink)**
Writing the same data twice must produce the same result as writing once. Delta Lake achieves this via the **transaction log**: each streaming micro-batch is assigned a unique `batchId`. Before writing, Spark checks if `batchId` already exists in the Delta log. If yes → skip (already committed). If no → write atomically. This makes Delta Lake an exactly-once sink regardless of retries.

**3. Write-ahead checkpointing**
Before processing a batch, Spark commits the **source offset** to the checkpoint directory (DBFS/ADLS). On restart, it reads the checkpoint to know exactly which offsets to process next — avoiding both gaps (at-most-once) and uncontrolled re-reads (unchecked at-least-once).

**Common confusion:** `trigger(once=True)` / `trigger(availableNow=True)` in Auto Loader is a **trigger mode** (process available data and stop), not delivery semantics. You can run with `availableNow=True` and still have at-least-once semantics if your sink isn't idempotent.

**Senior-bar add:** Exactly-once is end-to-end: source → processing → sink. Even if Spark achieves exactly-once processing internally, if the sink is a REST API without idempotency keys, you still have at-least-once at the system level.

---

### Q8 — Stateful vs stateless streaming

**Question:** Give a concrete example of a stateful and a stateless streaming operation. For stateful operations, what does checkpointing protect against — and what does it NOT protect against?

**Canonical answer:**

**Stateless** — each micro-batch processed independently, no memory of prior batches:
- `filter`, `select`, `withColumn`, `map` — each batch self-contained.
- Even simple aggregations within a single batch (`count()` on the current batch) are stateless.
- Schema enforcement, type casting, deduplication within a batch.

**Stateful** — requires memory across micro-batches:
- **Windowed aggregation:** `groupBy(window("event_ts", "1 hour")).agg(count())` — partial counts must persist across batches until the window closes.
- **Stream-stream join:** both sides buffer rows in state, waiting for a match from the other side. Rows held until the watermark says they're too old.
- **`mapGroupsWithState` / `flatMapGroupsWithState`:** arbitrary user-defined state per group (e.g., sessionization, fraud pattern detection).
- **Deduplication across batches:** `dropDuplicates("event_id")` — Spark stores all seen `event_id` values in state.

**What checkpointing protects against:**
- **Driver/executor crash and restart.** State (partial window counts, buffered join rows, dedup seen-IDs) is saved to durable storage (DBFS/ADLS) after each batch. On restart, Spark restores both the source offset AND the state, resuming as if nothing happened.

**What checkpointing does NOT protect:**
- **Corrupt state from logic bugs** — if your stateful function has a bug, restoring from checkpoint restores the corrupt state.
- **Schema-incompatible query changes** — changing the schema of state (e.g., adding a field to `mapGroupsWithState`) makes the checkpoint unreadable. Requires deleting checkpoint and full restart (state loss).
- **Data already dropped by watermark** — late data dropped before reaching state cannot be recovered from checkpoint.
- **Sink failures** — checkpoint protects the Spark offset; if the sink (e.g., a REST API) fails after Spark committed the offset but before the sink confirmed, that record is lost at the sink layer.

---

### Q9 — Trigger modes

**Question:** Name all trigger modes in Structured Streaming. When would you use each in production?

**Canonical answer:**

| Trigger | Syntax | Behavior | When to use |
|---|---|---|---|
| **Default (unspecified)** | `.trigger()` omitted | Micro-batch: next batch starts immediately when previous completes. As fast as possible. | Maximum throughput, latency-tolerant pipelines. Kafka→Delta ingest where you want highest event/sec. |
| **ProcessingTime** | `.trigger(processingTime="30 seconds")` | Wait at least N between batch starts. If a batch takes longer than N, next starts immediately after. | Dashboards or downstream consumers that only need updates on a fixed cadence. Reduces small-file problem. |
| **Once** | `.trigger(once=True)` | Process ALL available data in one or more micro-batches, then stop. Deprecated in DBR 10.4+. | Replaced by AvailableNow. |
| **AvailableNow** | `.trigger(availableNow=True)` | Process all data available at trigger time across multiple micro-batches, then stop. Uses checkpoint to track what's been processed. | Scheduled batch-style runs on streaming infrastructure. Best of both: structured streaming semantics + batch economics. Cron-triggered. |
| **Continuous** | `.trigger(continuous="1 second")` | Fundamentally different execution model. NOT micro-batch. Records processed row-by-row with ~1ms end-to-end latency. Experimental. Limited operator support (no aggregations). | Ultra-low latency requirements where micro-batch latency (~500ms min) is too high. Rarely used in practice. |

**Common mistake:** default trigger is NOT `ProcessingTime("500ms")`. It's "as fast as possible" — no interval at all.

**Production decision tree:**
- Need < 1s latency → Continuous (if your ops support experimental mode)
- Need lowest latency micro-batch → Default (unspecified)
- Downstream only needs updates every 5–30 min → ProcessingTime
- Want to run streaming job as a scheduled batch → AvailableNow
- Legacy codebase pre-DBR 10.4 → Once (still works, just deprecated)

---

### Q10 — Streaming + Delta Lake exactly-once

**Question:** How does Delta Lake enable exactly-once writes from a streaming job? What is the role of the transaction log in preventing duplicate writes on driver restart?

**Canonical answer:**

Delta Lake enables exactly-once via **transactional idempotency at the sink**, implemented through the transaction log (`_delta_log/`).

**The mechanism — per-batch commit tracking:**

Every Structured Streaming micro-batch that writes to Delta is assigned a monotonically increasing `batchId` (0, 1, 2, ...). Before writing data, Spark checks the Delta transaction log:
- If `batchId` already exists in the log → **skip, already committed.** No data written.
- If `batchId` not in the log → **write atomically.** Data files written to temp paths, then a single JSON commit entry added to `_delta_log/` — atomic on ADLS/S3 via rename semantics.

This is idempotent by construction: replaying batch 42 ten times produces the same result as playing it once.

**What the transaction log contains per commit:**
- The `batchId` (stored as a `StreamingUpdate` action in the log)
- Paths of new Parquet files added
- Any files removed (compaction)
- Commit timestamp

**Restart scenario:**
1. Driver crashes mid-batch 42 (data files written but commit not yet added to log).
2. On restart, Spark reads checkpoint: last committed source offset = end of batch 41.
3. Spark re-reads source from batch 41's end offset → rebuilds batch 42.
4. Attempts to write batch 42 → checks Delta log → `batchId=42` not present → writes and commits.
5. Result: no duplicate, no data loss.

**If crash happened after commit:**
Spark's source checkpoint also advances after a successful batch. On restart, checkpoint says "batch 42 done" → Spark reads from batch 43's offset. No re-processing of batch 42.

**What this requires from the source:**
The source must be replayable (Kafka: replay from offset; file sources: files are immutable). If the source isn't replayable (e.g., a socket or a queue that deletes on read), exactly-once is impossible regardless of the sink.

**Senior-bar nuance:** Delta's exactly-once guarantee is for the **write path**. If your streaming query also reads from Delta (e.g., a lookup join), and that Delta table changes between micro-batches, the read is snapshot-isolated per batch — consistent, but not "exactly-once reads." Exactly-once is a write-side property.

---

## Lakeflow / Spark Declarative Pipelines (SDP)

> SDP is the current name for the engine formerly called DLT. Python module: `from pyspark import pipelines as dp` (the `dlt` module is superseded). Full decorator/flow syntax reference (PySpark + SQL) lives in the workspace cheat-sheet `SDP_Syntax.py`.

### SDP-Q1 — Pipeline write atomicity: partial successes, no-write failures, and where expectations fit

**Question:** Are there partial successes in an SDP pipeline? When a pipeline *fails*, in which cases is there NO partial write (no tables/MVs materialized), and in which cases are partial writes left behind? Where do expectations sit in this?

**Canonical answer:**

**The one mental model — the atomic unit is the *flow* (one table's update), not the pipeline.** Every dataset update is backed by a Delta transaction, so atomicity has two scopes:
- **Within one table/MV** → strictly all-or-nothing. A table is *never* half-written. (Streaming table = atomic per micro-batch; MV = commits the whole recomputed version or keeps the previous one.)
- **Across the pipeline DAG** → **partial success is normal.** Each node commits independently; some succeed while others fail.

So yes — partial successes exist, but at the *pipeline* level, never inside one table.

**Case A — NOTHING is written (no datasets materialized at all): the planning / graph-validation failure class.** SDP evaluates every dataset definition and builds the full dataflow graph *before* running any query; if validation fails the whole update aborts before execution.
- Unresolved column, syntax error, type mismatch, schema-validation failure
- Missing source table, **circular dependency** in the DAG
- Illegal API inside a dataset function — `collect()`, `count()`, `save()`, `saveAsTable()`, `toPandas()`, `start()` (SDP re-evaluates definitions during planning, so eager actions break it)
- A dataset function that doesn't return a DataFrame

**Case B — PARTIAL writes land (some datasets updated, others not): the runtime failure class.** The graph was valid, execution started, and a *specific flow* failed. Already-committed datasets stay; the failed flow + its downstream dependents don't run.
- **DAG ordering** — bronze + silver commit, then gold throws → bronze/silver keep new data, gold keeps its prior version.
- **Independent branches** — flow B fails; flows A and C (not dependent on B) still commit.
- **`expect_or_fail` violation** — fails *only that flow* (see table); sibling flows commit.
- **Streaming checkpoint** — already-committed micro-batches persist; only the failing batch is dropped and replayed on restart.
- **Infra failure mid-run** (OOM, node loss) — whatever committed before the crash persists.

**Where expectations sit:**

| Decorator / SQL | What gets written | Update outcome |
|---|---|---|
| `@dp.expect` / `CONSTRAINT … EXPECT (…)` | ALL rows incl. violating (just logged) | **Succeeds** |
| `@dp.expect_or_drop` / `… ON VIOLATION DROP ROW` | Valid rows only; bad rows dropped | **Succeeds** (filtered subset — "partial" by row count, *not* a failure) |
| `@dp.expect_or_fail` / `… ON VIOLATION FAIL UPDATE` | Nothing from the failing batch — that flow's txn never commits | **Fails — that single flow only** |

Key documented fact: **`expect_or_fail` fails a single flow and does NOT cause other flows in the pipeline to fail.** Consequence:
- The **guarded table has no partial write** — the bad batch/version never commits; it keeps its prior good state.
- The **pipeline is partially written** — the *other* independent flows already committed.

**Senior-bar nuance (corrects the common framing):** "Pipeline failure ⇒ no partial write" is only true for **validation/planning** failures (they abort before execution, so nothing materializes). **Runtime** failures usually *do* leave partial pipeline writes — committed datasets persist. And `expect_or_fail` does **not** half-write the table it guards; it produces *pipeline-level* partial writes by failing just its own flow while siblings commit. `expect_or_drop` is not a failure at all — it commits the valid subset.

**One-liner:** *A single table is always atomic (Delta all-or-nothing). Validation failures abort the whole graph before any write, so nothing materializes; runtime failures — including `expect_or_fail` — fail only their own flow, so committed/independent datasets persist and the pipeline ends partially written; `expect_or_drop` just commits the valid subset.*

---

### SDP-Q2 — Backfilling historical data into an existing streaming table

**Question:** A streaming table already holds 2026 data (fed incrementally). You need to backfill 2024–2025 (two years of history) into the *same* streaming table — without re-running the backfill on every pipeline update. How?

**Canonical answer:**

Use **multiple flows into one streaming table** — SDP lets many flows target the same table. Split into two:
- **Continuous incremental flow** — the live 2026+ feed (Auto Loader stream).
- **One-time backfill flow** — a **batch** read of the complete 2024–2025 history, marked **`ONCE`** so it loads exactly once and never re-runs on later updates (unless the table is fully refreshed).

**The critical detail: `ONCE` is a *flow-level* flag, not an Auto Loader option.** The backfill source is a **batch read** (the history is static/complete); Auto Loader is only for the ongoing stream.

**SQL**
```sql
CREATE OR REFRESH STREAMING TABLE orders;

-- continuous incremental (Auto Loader stream)
CREATE FLOW incremental AS INSERT INTO orders BY NAME
SELECT * FROM STREAM read_files('/landing/2026/', format => 'csv');

-- one-time backfill (BATCH read, runs once)
CREATE FLOW backfill_history AS INSERT INTO orders BY NAME ONCE
SELECT * FROM read_files('/archive/2024_2025/', format => 'parquet');
```

**Python**
```python
dp.create_streaming_table("orders")

@dp.append_flow(target="orders")                 # continuous incremental
def incremental():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv").load("/landing/2026/"))

@dp.append_flow(target="orders", once=True)      # one-time backfill, BATCH read
def backfill_history():
    return spark.read.format("parquet").load("/archive/2024_2025/")
```

**Senior-bar nuance:** `ONCE` runs the backfill flow a single time; later updates skip it (its checkpoint marks it done) — *unless* the table is fully refreshed, which re-runs all flows. Backfill and incremental flows are independent (own checkpoints, keyed by flow name), so you can add the backfill later without touching the live stream and without a full refresh. Common interview slip (mine, 2026-06-03): saying `ONCE` lives "in the Auto Loader settings" — it's a property of the **flow** (`INSERT INTO … ONCE` / `@dp.append_flow(once=True)`), and the backfill is a **batch** read, not Auto Loader.

**One-liner:** *"Many flows can write one streaming table: a continuous Auto Loader incremental flow plus a one-time batch backfill flow flagged `ONCE` (flow-level, not an Auto Loader option). `ONCE` loads history exactly once and won't re-run unless the table is fully refreshed."*

---

## Novartis Client Round — Spark Declarative Pipelines (SDP / Lakeflow) 50-Question Bank

> Prep 2026-06-04 for the Novartis client round (interviewer: Nitesh); 2nd internal round may fall on Monday. **Naming:** the interviewer's questions say 'DLT'; answered here entirely in current **SDP (Spark Declarative Pipelines / Lakeflow)** terms — the Python module is now `from pyspark import pipelines as dp`. A legacy name is mapped only where a question literally uses it (Q7 'Live Tables', Q18 'deprecated auto-CDC'). All factual claims doc-verified via a multi-agent generate + adversarial-verify pass (2026-06-04).

---

### Category 1.1 — Pipeline Structure, Capabilities & Design Thinking (Q1–Q4)

#### Q1 — Complete structure & full capability surface of an SDP pipeline
**Question:** Explain the complete structure of a DLT pipeline and describe all the features and capabilities that can be implemented within a single DLT pipeline.

*("DLT pipeline" = SDP / Lakeflow Declarative Pipeline; I answer in current SDP terms.)*

**What an SDP pipeline IS**
- **Pipeline** = the unit of development + execution. You declare *datasets* and *flows*; SDP parses ALL source files first, builds a **dataflow (dependency) graph**, then orchestrates execution order + parallelism automatically. You never write the orchestration.
- An **update** = one run: starts compute, validates the graph (bad column names, missing deps, syntax) BEFORE running anything, then creates/refreshes datasets.

**The 3 dataset types (the nouns)**

| Object | SDP API | Read semantics | Use for |
|---|---|---|---|
| Streaming table (ST) | `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` | `spark.readStream` — incremental, append-only source, each row processed once | Bronze ingest, row-level silver, CDC targets |
| Materialized view (MV) | `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` | `spark.read` — batch; refreshed incrementally **only on serverless** (else full recompute) | Joins, aggregations, gold marts |
| Temporary view | `@dp.temporary_view` / `CREATE TEMPORARY VIEW` | in-pipeline only, not published | intermediate reuse |

*ST vs MV in one line: only difference in the basic body is `spark.readStream` (ST) vs `spark.read` (MV). (`@dp.table` is the ST decorator; `@dp.materialized_view` is the MV decorator — the legacy `@dlt.table` made both, so I always name the MV explicitly.)*

**The flow types (the verbs that write into a target)**
- **Append flow** (`@dp.append_flow`) — default flow of an ST; adds new rows per trigger. Multiple append flows can fan-in to ONE streaming table (union of sources).
- **AUTO CDC flow** (`dp.create_auto_cdc_flow` / `CREATE FLOW ... AS AUTO CDC INTO`) — upsert/delete with out-of-order handling; SCD Type 1 or 2.
- **AUTO CDC FROM SNAPSHOT** (`dp.create_auto_cdc_from_snapshot_flow`) — diffs full snapshots into CDC.
- **Update flow** (`@dp.update_flow`) and **Sinks** (`dp.create_sink` → Delta / Kafka / Event Hubs / custom Python sink) for streaming egress.

**Everything you can put in ONE pipeline**
- **Quality:** expectations — `@dp.expect` / `expect_or_drop` / `expect_or_fail` / `expect_all` / `expect_all_or_drop` / `expect_all_or_fail` (SQL: `CONSTRAINT name EXPECT (expr) [ON VIOLATION DROP ROW | FAIL UPDATE]`).
- **CDC / SCD2** via AUTO CDC, `__START_AT`/`__END_AT` history columns auto-maintained (same data type as `sequence_by`).
- **Schema controls:** column masks, PK/FK informational constraints, `CLUSTER BY` (liquid clustering — Databricks recommends it for all new STs/MVs, replacing `PARTITIONED BY` + `ZORDER`; `CLUSTER BY AUTO` lets the engine pick keys).
- **Mixed languages** (Python + SQL files in the same pipeline), multiple bronze→silver→gold layers, fan-in append flows, sinks, and a built-in **event log** (Delta table) for lineage, expectation metrics, and `flow_progress` events.

```python
from pyspark import pipelines as dp

@dp.table
@dp.expect_or_drop("valid_id", "id IS NOT NULL")
def bronze_orders():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", "/chk/orders")
            .load("/Volumes/cat/sch/incoming/orders"))

@dp.materialized_view
def gold_orders_by_state():
    return (spark.read.table("bronze_orders")
            .groupBy("state").count())
```
```sql
CREATE OR REFRESH STREAMING TABLE bronze_orders(
  CONSTRAINT valid_id EXPECT (id IS NOT NULL) ON VIOLATION DROP ROW
) AS SELECT * FROM STREAM read_files('/Volumes/cat/sch/incoming/orders', format => 'csv');

CREATE OR REFRESH MATERIALIZED VIEW gold_orders_by_state
AS SELECT state, count(*) AS n FROM bronze_orders GROUP BY state;
```

**One-liner:** An SDP pipeline is a declared dependency graph of streaming tables, materialized views, and views — wired together by append / AUTO CDC / update flows and sinks, with expectations, SCD2, and an event log all managed by the engine, not hand-orchestrated.

#### Q2 — Key concepts you must master to work with SDP
**Question:** What are the key concepts that must be well understood when working with DLT?

**Declarative, not imperative**
- You declare WHAT each dataset is; SDP decides execution ORDER and parallelism from the graph. **Order of code ≠ order of execution.**
- Source is evaluated MULTIPLE times during planning — so **no side effects** in dataset functions. The docs explicitly ban these inside dataset code: `collect()`, `count()`, `toPandas()`, `save()`, `saveAsTable()`, `start()`, `toTable()` — i.e. anything that writes or forces execution. (This is exactly why my Apollo Gen2 preprocessing lives in a separate notebook job — arbitrary Python / `dbutils.fs` doesn't belong in a dataset function.)

**ST vs MV (the most-tested distinction)**

| | Streaming table | Materialized view |
|---|---|---|
| Read | `spark.readStream` | `spark.read` |
| Source must be | append-only | any (batch) |
| Recompute | incremental, processes each new row once | incremental refresh **only on serverless**; classic compute (or an unsupported query) → full recompute |
| Mutable source | **breaks** (needs append-only) | fine |

**Flows** — a flow reads a source, transforms, writes a target. Append / AUTO CDC / Update. Multiple flows can target one ST (fan-in); a dataset can otherwise be the target of only one operation across all pipelines.

**AUTO CDC mechanics** (`create_auto_cdc_flow`):
- `keys` (business key), `sequence_by` (logical ordering, sortable type, handles out-of-order; a `struct(...)` breaks ties), `apply_as_deletes`, `stored_as_scd_type` (**default = 1**), `track_history_except_column_list` / `track_history_column_list`.
- **Gotcha I hit:** if you don't EXCEPT every operational-metadata column (`_processing_timestamp`, `_source_file_path`) from history tracking, each re-run flips those values and forges a false SCD2 version.
- Deletes are kept as **tombstones** for **2 days** by default (`pipelines.cdc.tombstoneGCThresholdInSeconds`, table property on the target ST) to absorb late/out-of-order deletes.

**Expectations** — warn (default, row kept), drop, fail; a `fail` only fails THAT flow, not sibling flows.

**Schema evolution (Auto Loader)** — `cloudFiles.schemaEvolutionMode` default `addNewColumns` (when no schema supplied; `none` if you supply one — `addNewColumns` isn't allowed with a provided schema unless given as a schema hint). On a new column the stream throws `UnknownFieldException` and stops; restart resumes with the evolved schema. It only ADDS columns — never removes/renames/retypes. A **dropped source column lands silently as NULL** (soft delete). Type mismatch → `_rescued_data` (which Auto Loader auto-adds as `_rescued_data` whenever it infers the schema). (`addNewColumnsWithTypeWidening`, Public Preview in DBR 16.4+, also widens e.g. `int`→`long`.)

**The event log** — Delta table; query via the `event_log('<pipeline-id>')` TVF (callable only by the ST/MV owner, on a shared cluster or SQL warehouse) for lineage, `flow_progress`, and expectation pass/fail counts (in the `details` JSON).

**One-liner:** Master five things — declarative graph (no side effects), ST-vs-MV read semantics (and that MV incremental refresh needs serverless), the flow types, AUTO CDC's keys/sequence_by/SCD-type/track-history defaults, and the event log — and SDP becomes predictable.

#### Q3 — How to structure your thinking when designing an SDP pipeline
**Question:** How should the thought process be structured and clarified when designing a DLT pipeline?

This is an approach question, so here is the decision sequence I actually run.

**Approach (the design interrogation, in order)**
1. **Source contract:** Is the source append-only or mutable? Append-only → streaming table. Mutable → batch MV, or first stabilize via a CDC feed. (I learned this the hard way: streaming-on-mutable-source breaks the ST.)
2. **Is it already CDC / already SCD?** If the source is *already* SCD2, do NOT run AUTO CDC on top of it — you double-version. Collapse to current-only or map columns directly. Only run AUTO CDC on a raw change feed.
3. **Grain & key:** What uniquely identifies a row (`keys`)? What column gives a real, logical event order (`sequence_by`, sortable type — use a `struct(...)` if one column isn't enough to break ties)? `file_modification_time` is too coarse — if many rows share one file, ties resolve arbitrarily. Need true per-row granularity.
4. **History need:** Current-state only → SCD1 (the default). Full audit trail → SCD2, and decide which columns are *meaningful* history vs noise → `track_history_except_column_list` for every operational-metadata column.
5. **Where does schema get enforced?** Enforce ONCE, at one layer (bronze). Don't re-validate the same contract three times.
6. **Quality policy per constraint:** integrity (PK, SCD2, CDC) → `expect_or_fail` (hard gate); observability (freshness, schema drift) → `expect` (warn). In Apollo Gen2 SIT I warn-in-dev then fail-in-prod across 17 cases.
7. **What does NOT belong in SDP?** Arbitrary Python, `dbutils.fs`, file ops, anything that calls `save`/`start`/`collect`/`count` → split into a preprocessing **notebook job** chained via `depends_on`. Different compute + independent failure domains is a feature, not a workaround.
8. **Layer mapping:** bronze = ST (raw, minimal transform, replayable); silver = ST for row-level cleaning / MV for enrichment joins; gold = MV aggregations.

**Design principles I hold**
- Silent failures beat loud failures — but a *removed* column landing NULL is a silent failure, so add a freshness/schema-drift WARN to surface it.
- Generated code is an artifact, not source of truth — I batch-generate 422 SDP pipelines (211 STG + 211 BRZ SCD2) from one script; edit config + regenerate, never hand-edit output.
- Design around framework limits, don't fight them.

**One-liner:** Start from the source contract (append-only vs mutable, raw-CDC vs already-SCD), pin down key + true sequence column, decide SCD1 vs SCD2 with explicit history-column exclusions, enforce schema once, set per-constraint fail/warn policy, and push anything non-declarative into a chained notebook job.

#### Q4 — Architecture for Bronze/Silver/Gold when S3 gets a new file daily
**Question:** How would you design the architecture for Bronze, Silver, and Gold layers if S3 receives a new file daily?

**Approach (end-to-end design)**
- **Ingest = Auto Loader, not a directory read.** A daily file is incremental file arrival — `cloudFiles` tracks processed files via `schemaLocation`, so I never reprocess yesterday's file and never need manual high-watermark bookkeeping. (In SDP, Auto Loader auto-manages the schema + checkpoint dirs.)
- **Trigger:** daily file → triggered (scheduled) pipeline update, not continuous. Cheaper, matches the cadence.
- **Bronze (streaming table):** raw landing, minimal transform, every row carries operational metadata (`_source_file_path`, `_processing_timestamp`). Replayable — silver/gold can rebuild from bronze if logic changes. Schema enforced HERE, once.
- **Silver (streaming table for row-level clean, or AUTO CDC if the daily file is a change feed):** dedupe, cast, validate. If the daily file is a full/changed snapshot of a dimension, use AUTO CDC → SCD1/SCD2 here.
- **Gold (materialized view):** aggregations/metrics for dashboards; incremental refresh recomputes only what changed — **but only on a serverless pipeline**; on classic compute (or an unsupported query) each refresh is a full recompute.

**Schema-evolution call:** Auto Loader `schemaEvolutionMode = addNewColumns` (default, no schema supplied) — new vendor column → stream throws `UnknownFieldException` and stops, schema evolves, restart picks it up (run under a Lakeflow Job so it auto-restarts). It will NOT catch a *removed* source column — that lands as NULL silently — so I add a WARN expectation on freshness/null-rate to surface it.

```python
from pyspark import pipelines as dp

@dp.table  # BRONZE
def bronze_sales():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", "/Volumes/cat/sch/_schema/sales")
            .load("s3://bucket/incoming/sales/")
            .selectExpr("*", "_metadata.file_path AS _source_file_path",
                        "current_timestamp() AS _processing_timestamp"))

dp.create_streaming_table("silver_customers")  # SILVER as SCD2 if daily file is CDC
dp.create_auto_cdc_flow(
    target="silver_customers", source="bronze_sales",
    keys=["customer_id"], sequence_by="event_ts",
    apply_as_deletes="op = 'DELETE'", stored_as_scd_type=2,
    track_history_except_column_list=["op", "_source_file_path", "_processing_timestamp"])

@dp.materialized_view  # GOLD
def gold_daily_revenue():
    return (spark.read.table("silver_customers")
            .where("__END_AT IS NULL")
            .groupBy("region").sum("amount"))
```
```sql
CREATE OR REFRESH STREAMING TABLE bronze_sales
AS SELECT *, _metadata.file_path AS _source_file_path, current_timestamp() AS _processing_timestamp
FROM STREAM read_files('s3://bucket/incoming/sales/', format => 'csv');

CREATE OR REFRESH STREAMING TABLE silver_customers;
CREATE FLOW silver_cdc AS AUTO CDC INTO silver_customers
FROM STREAM(bronze_sales) KEYS (customer_id)
APPLY AS DELETE WHEN op = 'DELETE' SEQUENCE BY event_ts
COLUMNS * EXCEPT (op, _source_file_path, _processing_timestamp) STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW gold_daily_revenue
AS SELECT region, sum(amount) FROM silver_customers WHERE __END_AT IS NULL GROUP BY region;
```

**Best-practice note:** Databricks recommends separating ingestion (bronze) from transformation (silver/gold) into distinct pipelines so a transform failure doesn't block new data from landing — this mirrors my Apollo Gen2 two-job split (preprocessing notebook → SDP pipeline via `depends_on`).

**One-liner:** Auto Loader streaming-table bronze (incremental, replayable, metadata-tagged), a streaming/AUTO-CDC SCD silver, and a materialized-view gold, run as a daily triggered update — with `addNewColumns` evolution plus a freshness WARN to catch the silent dropped-column NULL.

### Category 1.2–1.3 — Object Model, Pipeline Modes & Full Refresh (Q5–Q9)

#### Q5 — Object types in a Spark Declarative Pipeline
**Question:** What types of objects can be created in Delta Live Tables (DLT)? (DLT = SDP / Lakeflow Declarative Pipelines — answered in SDP terms.)

**The object model (verified, current SDP docs).** A pipeline declares three **dataset** types plus two **plumbing** primitives:

| Object | SDP decorator / SQL | Backed by | Persisted? | Use |
|---|---|---|---|---|
| **Streaming table (ST)** | `@dp.table` / `CREATE OR REFRESH STREAMING TABLE` | UC-managed Delta | Yes (published to UC) | Incremental ingest; each row processed **exactly once**; assumes an append-only source |
| **Materialized view (MV)** | `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` | UC-managed Delta | Yes (published to UC) | Transforms/joins/aggregations; **results pre-computed and cached**, incrementally refreshed |
| **Temporary view** | `@dp.temporary_view` / `CREATE TEMPORARY VIEW` | nothing (logic only) | No (pipeline-scoped) | Intermediate steps, no downstream readers |
| **Flow** | `@dp.append_flow`, `dp.create_auto_cdc_flow`, `dp.create_auto_cdc_from_snapshot_flow`, `@dp.update_flow` | — | — | A query→target unit; multiple flows can feed one ST |
| **Sink** | `dp.create_sink` | Delta or Kafka (`format="delta"` / `"kafka"`) | external | Append/update records to an external target |

**Flow types under the hood (per the SDP flows doc):** **Append** (the default flow created with any ST or MV — append flows back materialized views too), **Auto CDC** (previously *apply changes*; SCD1/SCD2; ST-only target), and **Update** (Public Preview, Python-only, emits changed aggregate records to a sink). A streaming table can have many flows written into it; an MV's default append flow is defined implicitly.

**Sink note:** `create_sink` (Public Preview) takes `format="delta"` or `format="kafka"` only — the `kafka` format also covers Azure Event Hubs via its Kafka-compatible interface; arbitrary targets need a Python custom data source or a `@dp.foreach_batch_sink`. Sinks accept only **append** and **update** flows — not `create_auto_cdc_flow`. A full refresh does **not** clear data already written to a sink.

**PySpark — one of each:**
```python
from pyspark import pipelines as dp

@dp.table  # streaming table
def bronze_accounts():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "csv").load("/incoming/accounts")

@dp.temporary_view  # not persisted
def accounts_clean():
    return spark.read.table("bronze_accounts").dropDuplicates(["accountid"])

@dp.materialized_view  # persisted, incrementally refreshed
def accounts_by_country():
    return spark.read.table("accounts_clean").groupBy("country").count()
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE bronze_accounts
AS SELECT * FROM STREAM read_files('/incoming/accounts', format => 'csv');

CREATE TEMPORARY VIEW accounts_clean AS SELECT DISTINCT * FROM bronze_accounts;

CREATE OR REFRESH MATERIALIZED VIEW accounts_by_country
AS SELECT country, count(*) AS n FROM accounts_clean GROUP BY country;
```

**Apollo Gen2 note (first person):** In my JOB2 SDP pipeline I only use STs and MVs — STG layer is `@dp.table` streaming tables fed by Auto Loader, BRZ layer is SCD2 streaming tables fed by `dp.create_auto_cdc_flow`. Temporary views I use sparingly for intermediate dedup before the CDC flow.

**One-liner:** SDP gives you three dataset objects — streaming tables, materialized views, temporary views — plus flows and sinks as the plumbing that writes into them.

#### Q6 — DLT view vs materialized view
**Question:** What is the difference between a DLT view and a materialized view? When should each be used?

**Core distinction = materialization.** A **view (temporary view, `@dp.temporary_view`)** stores **no data** — its query is recomputed every time it is read, and it exists only inside the pipeline. A **materialized view (MV, `@dp.materialized_view`)** stores its results in a UC-managed Delta table and keeps them up to date via incremental refresh; it is queryable from outside the pipeline.

| Dimension | Temporary view | Materialized view (MV) |
|---|---|---|
| Data stored | No (logic only) | Yes (Delta table in UC) |
| When computed | Every read (on demand) | At pipeline update; cached between updates |
| Visible outside pipeline | No (pipeline-scoped) | Yes (published to catalog.schema) |
| Storage/compute cost | None | Storage + refresh compute |
| Incremental refresh | N/A | Yes on **serverless**; classic compute = full recompute every update |

**Use a temporary view when:**
- Breaking a large query into readable steps with no downstream persistence.
- You want zero storage cost and no external consumers.

**Use an MV when:**
- Multiple downstream queries/pipelines/jobs consume the result (a view is re-run on every read; an MV is computed once).
- You need fast dashboard/analytic reads (gold layer).
- You want to inspect results during development (MVs are queryable; views are not).

**PySpark:**
```python
from pyspark import pipelines as dp

@dp.temporary_view
def filtered():                       # recomputed each reference, not stored
    return spark.read.table("bronze_orders").where("amount > 0")

@dp.materialized_view
def daily_revenue():                  # stored + incrementally refreshed
    return spark.read.table("filtered").groupBy("order_date").sum("amount")
```

**SQL equivalent:**
```sql
CREATE TEMPORARY VIEW filtered AS SELECT * FROM bronze_orders WHERE amount > 0;

CREATE OR REFRESH MATERIALIZED VIEW daily_revenue AS
SELECT order_date, SUM(amount) AS revenue FROM filtered GROUP BY order_date;
```

**Gotcha (call out the invisible cost):** incremental MV refresh only happens when the backing pipeline runs on **serverless** compute and only for supported query shapes; on classic compute, or with an unsupported expression, the MV is **fully recomputed** every update — silently more expensive than expected. (Note: an MV expressing an expectation needs the older `CREATE LIVE VIEW` form if you want the constraint on a non-materialized view; a plain `CREATE TEMPORARY VIEW` does not carry expectations.)

**One-liner:** A view recomputes its query on every read and never leaves the pipeline; a materialized view stores its results as a Delta table and refreshes them incrementally, so use views for cheap intermediate logic and MVs for reused, persisted transforms.

#### Q7 — Live Tables vs Live Streaming Tables
**Question:** What is the difference between Live Tables and Live Streaming Tables in DLT? When would you use each type?

**Legacy→SDP mapping (one clause):** legacy "Live Table" = **materialized view (MV)** and legacy "Live Streaming Table" = **streaming table (ST)**; answering in SDP terms below.

**The difference is the processing model:**

| | Streaming table (ST) | Materialized view (MV) |
|---|---|---|
| Processing | Each input row processed **exactly once** (incremental, append) | Results computed to be **correct for current state**; incrementally refreshed |
| Source requirement | **Append-only** stream (`spark.readStream` / `STREAM(...)`) | Any batch query (`spark.read`) |
| Reacts to source updates/deletes | No (append-only assumption; throws on a change/delete commit) | Yes — recomputes to reflect deletes/updates |
| State/checkpoint | Maintains streaming checkpoint per flow | No streaming checkpoint |
| Typical layer | Bronze ingest, silver row-level transforms, CDC targets | Silver enrichment joins, gold aggregations/dashboards |

**Use a streaming table when:**
- Source grows continuously/incrementally (cloud files, Kafka, CDC feed).
- You want high throughput, low latency, and want to read each record only once.
- It is the target of `dp.create_auto_cdc_flow` (AUTO CDC).

**Use a materialized view when:**
- The query is a transform/join/aggregation that must always reflect the **current** state of mutable sources.
- Downstream consumers need fast pre-computed reads.

**PySpark:**
```python
from pyspark import pipelines as dp

@dp.table  # streaming table: read each event once
def events_bronze():
    return spark.readStream.format("cloudFiles") \
        .option("cloudFiles.format", "json").load("/incoming/events")

@dp.materialized_view  # recomputes to current correct state
def events_per_user():
    return spark.read.table("events_bronze").groupBy("user_id").count()
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE events_bronze
AS SELECT * FROM STREAM read_files('/incoming/events', format => 'json');

CREATE OR REFRESH MATERIALIZED VIEW events_per_user
AS SELECT user_id, count(*) AS n FROM events_bronze GROUP BY user_id;
```

**Apollo Gen2 hard incident (first person):** My signature failure here is **streaming-on-mutable-source** — a `@dp.table` streaming table assumes an append-only source. When I pointed one at an upstream that was being updated/deleted in place, the stream threw on the change commit; the fix is either make the source append-only, switch to a materialized view (no append-only restriction), or set `skipChangeCommits` when reading the source ST (an `spark.readStream.option(...)` flag — note it cannot be used when that source ST is itself the target of a `create_auto_cdc_flow`).

**One-liner:** A streaming table reads an append-only source exactly once for incremental ingest, while a materialized view recomputes a batch query to stay correct against mutable sources — STs for ingest/CDC, MVs for transforms and aggregations.

#### Q8 — Development vs production mode
**Question:** What are the differences between development and production modes in a DLT pipeline?

**What the toggle is.** `development` is a boolean pipeline setting (default **`false`**, surfaced as a Development/Production UI toggle). It does **not** change the target catalog/schema or where tables are published — only cluster lifecycle and how runtime upgrades are handled.

**Important current-docs nuance.** In current SDP docs the cluster-reuse-vs-teardown and retry behavior is described as **"update run behavior" determined by how you trigger the update**, not strictly by the dev/prod flag:
- **Fast-start / debugging behavior** — used by **UI "Run now"** and ad-hoc updates: **reuses the cluster** (clusters run **2 h** by default, tunable via `pipelines.clusterShutdown.delay`) and **disables retries** so errors surface immediately.
- **Automatic retry and restart behavior** — used by **Jobs, the Pipelines API, and continuous pipelines**: restarts the cluster on recoverable errors (memory leaks, stale credentials), retries on errors like cluster-launch failure, and **shuts the cluster down immediately after the run**.

Development mode aligns you with the fast-start behavior (warm cluster, fail-loud) during iteration; production mode aligns with the reliable, cost-efficient teardown-and-retry path for scheduled runs.

| Behavior | Development | Production |
|---|---|---|
| Cluster lifecycle | Reuses the cluster across updates (default **2 h** idle, `pipelines.clusterShutdown.delay`) | Cluster **shuts down immediately** after each run |
| Retries | Effectively off for ad-hoc/UI runs — errors surface immediately | Automatic retry/restart on recoverable errors |
| Update retry count | n/a for ad-hoc/Validate runs | `pipelines.numUpdateRetryAttempts` default **5** (triggered) / **unlimited** (continuous) |
| Flow retry count | n/a | `pipelines.maxFlowRetryAttempts` default **2** (3 total attempts incl. the original) |
| Runtime auto-revert on a bad upgrade | No | Yes — SDP reverts to the last known-good runtime **only for pipelines running in production mode with `channel` = `current`** |
| Goal | Rapid debug loop | Reliability + cost efficiency |

**Note (avoid a common confusion):** dev/prod is distinct from **triggered vs continuous** pipeline mode (the `continuous` flag, default `false`), which controls whether the pipeline stops after processing all data vs runs always-on. Dev/prod is about cluster reuse + upgrade handling; triggered/continuous is about scheduling/latency.

**Approach (how I'd answer "how do you promote dev→prod"):**
- Develop with the pipeline in **development** mode so the cluster stays warm and failures stop loudly for debugging.
- Use **Declarative Automation Bundles**: a target with `mode: development` deployed via `databricks bundle deploy -t dev` marks pipelines `development: true`, prefixes resource names with `[dev ${workspace.current_user.short_name}]`, and pauses schedules/triggers; a `mode: production` target deployed via `databricks bundle deploy -t prod` validates all pipelines are `development: false`, validates the configured Git branch, and recommends a service-principal `run_as`.
- Flip to **production** mode for the scheduled/Jobs run so the cluster tears down per-run and transient failures auto-retry.

**One-liner:** The `development` flag (default false) plus the update trigger source decide cluster lifecycle and retries — development/Run-now keeps the cluster warm and fails loud for a fast debug loop; production/Jobs tears the cluster down per run and auto-retries for reliable, cost-efficient scheduled execution — neither changes where data is published.

#### Q9 — Full refresh
**Question:** Explain the concept of a full refresh in DLT and when it should be used.

**What it is.** A **full refresh reprocesses every record from the source under the table's latest definition.** Contrast with the default refresh, which is **incremental** (STs process only new rows once; MVs incrementally update where possible). The two refresh types behave very differently on the two dataset types:

| Target | Default (incremental) refresh | **Full** refresh (`FULL`) |
|---|---|---|
| Materialized view | Incremental on serverless; else full recompute | Recomputes all source data; **returns the same results as a default refresh** (it clears the MV's stored results + checkpoints, but the output is identical) |
| Streaming table | Reads only new rows once | **Truncates** the table, **clears the flows' checkpoints/state**, and reprocesses all available source data |

**SQL:**
```sql
-- Streaming table: truncate + reprocess from scratch
REFRESH STREAMING TABLE cat.schema.bronze_accounts FULL;

-- Materialized view: recompute all source data (same result as default)
REFRESH MATERIALIZED VIEW cat.schema.daily_revenue FULL;
```
In a pipeline, you trigger it via the UI ("Full refresh all" / select tables), the Pipelines API `start-update` with full-refresh selection, or `databricks pipelines start-update`.

**When to use it:**
- Schema or logic change in a stateful/streaming query (e.g., changed watermark, aggregation columns) — old checkpoint state is incompatible and must be rebuilt.
- Corrupted/inconsistent target, or a backfill where you must reprocess the full history.
- Recovering from a streaming checkpoint failure or corruption (full refresh is one of the documented recovery paths; the others are backup-then-backfill, or a selective checkpoint reset that preserves the data).

**When NOT to use it (the dangerous part — call out the silent data loss):**
- Sources with **short retention** (Kafka) or **lifecycle-expired** object-storage files: a full refresh on a streaming table **truncates first**, then can only reload what the source still has — records no longer in the source are **dropped** from the target. (The same applies to an MV: removed source records are not reflected in the recomputed results.)
- An SCD2 history table: a full refresh wipes the accumulated history.
- Protect critical tables with the table property **`pipelines.reset.allowed = false`** to block full refresh entirely.

**Approach (scenario "you changed a silver aggregation, downstream numbers are wrong"):**
1. Confirm the source still holds the full history needed to rebuild (else you lose data).
2. For a single table, run a **selective** full refresh on just that table to limit blast radius and compute.
3. For an append-only need where you only want new data without truncation, prefer an **`@dp.append_flow`** instead of a full refresh.

**Apollo Gen2 note (first person):** On my BRZ SCD2 tables I keep a `pipelines.reset.allowed=false` mindset, because a full refresh would truncate the streaming table and destroy SCD2 history; if I genuinely need to rebuild, I confirm the ADLS `incoming/` files still cover the full window first, since Synapse Link replicate output is not infinite-retention.

**One-liner:** A full refresh reprocesses all source records under the latest definition — for a streaming table it truncates the table and resets the flows' checkpoints/state, for an MV it recomputes to the same result — use it for schema/logic changes or backfills, but never on short-retention sources, because anything no longer in the source is dropped.

### Category 2 — Materialized Views Deep Dive (Q10–Q13)

#### Q10 — Challenges and limitations of materialized views (MV) in SDP
**Question:** What are the challenges or limitations of using materialized views (MV) in DLT (SDP)?

**Term:** MV (materialized view) = a `@dp.materialized_view` / `CREATE OR REFRESH MATERIALIZED VIEW` dataset in SDP (Spark Declarative Pipelines / Lakeflow). It is a Unity Catalog managed table with a **batch flow**: the query result is precomputed and stored, then kept in sync with sources on each pipeline trigger — incrementally when possible, else by full recompute.

**Hard limitations (verified, current docs):**
- **Incremental refresh is serverless-only.** For an MV defined in SDP, the pipeline must be configured to use serverless; on classic compute the MV is **always fully recomputed** — no incremental path exists. (Note: refresh operations themselves always run on serverless pipelines; the serverless-vs-classic distinction is about the *pipeline's* configured compute.) This is the single biggest gotcha.
- **`PIVOT` is not supported at all in pipelines** — not "falls back to full recompute," it's an unsupported clause. `pivot` requires eager loading of input data to compute the output schema, which pipelines don't support.
- **Not all queries can be incrementalized** (these still run, but force `FULL_RECOMPUTE`): recursive CTEs (`WITH RECURSIVE`); non-deterministic functions other than the time functions `current_date()`/`current_timestamp()`/`now()`, which are supported only in `WHERE`; volumes / external locations / foreign catalogs as sources; foreign Iceberg tables (Unity Catalog managed Iceberg v2/v3 *are* supported).
- **Source must survive full-refresh semantics.** Even an incrementalizable MV may fall back to full recompute, which **rescans the whole source**. If the source deletes/archives old rows (retention threshold), a full refresh silently drops those rows from the result and may even change the schema. So MVs are wrong for sources that retain no history (Kafka) or process-once ingest (Auto Loader).
- **Not low-latency.** Update latency is seconds-to-minutes, not milliseconds. Not for real-time.
- **Read-only output.** You cannot `INSERT`/`UPDATE`/`DELETE` an MV directly — the query definition is the only control. To delete data you must delete from the source and refresh.
- **Single-pipeline ownership.** An MV is defined and updated by exactly one pipeline; no other pipeline can write it.
- **No `CLONE`** — you cannot use an MV as the source or target of a deep or shallow clone.
- **No `OPTIMIZE` / `VACUUM`** — maintenance is automatic; those commands are disallowed.
- **UDF drift risk.** SDP attempts to detect when a UDF changes behavior and full-refresh, but a UDF that calls other functions/libraries may change behavior undetected; then it's your responsibility to trigger a full refresh or the MV silently serves stale logic.
- **Incremental refresh needs Delta features on sources.** Many techniques require **row tracking** (a Delta-only feature); row filters / column masks on a source force a **full refresh** every time (they disable incremental refresh).
- **Identity columns may be recomputed** on MV updates — Databricks recommends identity columns only on streaming tables. (The pipelines `CREATE MATERIALIZED VIEW` reference goes further and lists generated/identity/default columns as unsupported.)

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import count, sum as _sum

@dp.materialized_view  # batch flow; on a serverless pipeline => can incrementally refresh
def transaction_summary():
    return (spark.read.table("transactions_table")
            .groupBy("account_id")
            .agg(count("*").alias("txn_count"),
                 _sum("txn_amount").alias("account_revenue")))
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW transaction_summary AS
SELECT account_id, COUNT(txn_id) AS txn_count, SUM(txn_amount) AS account_revenue
FROM transactions_table
GROUP BY account_id;
```

**Inspect which path ran** (catches the silent full-recompute trap): query the event log for `planning_information` — technique is `ROW_BASED` / `GROUP_AGGREGATE` / `GENERIC_AGGREGATE` / `APPEND_ONLY` / `PARTITION_OVERWRITE` / `WINDOW_FUNCTION` (all incremental) vs `FULL_RECOMPUTE` (`NO_OP` = nothing changed).
```sql
SELECT timestamp, message
FROM event_log(TABLE(my_catalog.my_schema.transaction_summary))
WHERE event_type = 'planning_information'
ORDER BY timestamp DESC;
```
(To check incrementalizability *before* shipping, prepend `EXPLAIN` to the create statement: `EXPLAIN CREATE MATERIALIZED VIEW ...` — but it confirms only structural eligibility, not that the `AUTO` cost model will actually pick incremental at runtime.)

**Apollo Gen2 grounding:** In my pipeline the bronze SCD2 layer is built with `create_auto_cdc_flow` on **streaming tables**, not MVs, precisely because the Synapse-Link source is process-once / append-style and an MV's full-recompute fallback would rescan everything and lose deleted-record history. I reserve MVs for gold-layer aggregations where full recompute is tolerable and the source is a stable Delta table.

**One-liner:** An MV is a precomputed batch result that's only incrementally refreshed on a serverless pipeline, falls back to full recompute on unsupported queries or classic compute (and rejects `PIVOT` outright), is read-only, isn't low-latency, and must never sit on a process-once source.

#### Q11 — When to prefer a materialized view over a streaming table
**Question:** When should I prefer a materialized view over a streaming table in my pipeline architecture?

**Core distinction:** **Streaming table** (`@dp.table`) = **streaming flow**, append-only semantics, each input row read **exactly once**. **MV** (`@dp.materialized_view`) = **batch flow**, result equals re-running the full batch query, kept fresh by incremental refresh when possible.

**Decision table:**
| Need | Pick | Why |
|---|---|---|
| Ingest from cloud storage / Kafka / message bus | Streaming table | Each record processed once; high volume, append-only |
| CDC inserts/updates/deletes | Streaming table (target of `create_auto_cdc_flow` / `AUTO CDC ... INTO`) | Ordered, deduplicated SCD1/SCD2 |
| Source is continuously/incrementally **growing** & must be processed once | Streaming table | Exactly-once; checkpointed |
| Source mutates (rows updated/deleted in place) | **MV** | Streaming needs append-only source; MV reflects updates correctly |
| Complex aggregations / multi-table joins (gold) | **MV** | Result always correct even for late/out-of-order data; incrementally refreshed |
| Dashboard / BI query acceleration | **MV** | Precomputed result; fast reads |
| Full recompute would be cost-prohibitive (huge table) | Streaming table | Avoids rescan; guarantees exactly-once |
| Dimension enrichment in silver (join recomputes when dimension changes) | MV | Streaming-table joins do **not** recompute when a dimension changes; an MV recomputes the join, so it stays correct |

**Approach (the mental test I apply):**
1. **Is the source append-only and must each row be seen once?** Yes -> streaming table. (Process-once ingest, Kafka, Auto Loader.)
2. **Does the source mutate in place, or do I need the *current correct aggregate/join* regardless of arrival order?** -> MV. An MV guarantees batch-equivalent correctness even with late/out-of-order data; a streaming aggregate would need watermarks and still drop late data, and a streaming-table join won't recompute when its dimension changes.
3. **Would a worst-case full recompute be affordable?** MV may fall back to full recompute. If the source is enormous and recompute is prohibitive, use a streaming table instead.
4. **Medallion mapping:** bronze/silver row-level = streaming tables; silver enrichment joins + gold aggregates = MVs.

```python
from pyspark import pipelines as dp

@dp.table  # streaming table: append-only ingest, exactly-once
def orders_bronze():
    return spark.readStream.table("raw_orders")

@dp.materialized_view  # batch flow: correct aggregate, incrementally refreshed on a serverless pipeline
def daily_orders_by_state():
    return (spark.read.table("orders_silver")
            .groupBy("state", "order_date").count())
```

```sql
CREATE OR REFRESH STREAMING TABLE orders_bronze
  AS SELECT * FROM STREAM read_files('/mnt/raw/orders', format => 'json');

CREATE OR REFRESH MATERIALIZED VIEW daily_orders_by_state AS
SELECT state, order_date, COUNT(*) AS n
FROM orders_silver GROUP BY state, order_date;
```

**Apollo Gen2 grounding:** All 422 of my pipelines use **streaming tables** at STG and BRZ because the source is a process-once Synapse-Link replicate feed and BRZ is SCD2 via `create_auto_cdc_flow` (AUTO CDC) — exactly the streaming case. I hit the "streaming-on-mutable-source" incident first-hand: a streaming table needs an append-only source, and a mutable upstream breaks it. If I were building a gold sales summary on top of stable BRZ Delta tables, that layer would be an MV.

**One-liner:** Use a streaming table when the source is append-only and each row must be processed exactly once; use an MV when you need a batch-correct aggregate or join over a possibly-mutating source and can tolerate an occasional full recompute.

#### Q12 — MV behavior on serverless vs standard clusters, and the 10MB-of-1M-rows case
**Question:** How do materialized views behave differently on serverless clusters vs. standard clusters? For example, if only 10MB of data changes in a 1-million-row dataset, how will MV performance differ?

**The hard rule:** Incremental refresh is available **only when the SDP pipeline runs on serverless**. On a **classic/standard** pipeline the MV is **always fully recomputed**. (Refresh operations always execute on serverless pipelines internally; the distinction here is the *configured pipeline compute* — an MV defined in a classic-compute SDP pipeline gets full recompute.)

| | Serverless pipeline | Standard (classic) pipeline |
|---|---|---|
| Incremental refresh | Yes (best-effort, cost-model chosen) | **No — always FULL_RECOMPUTE** |
| 10MB changed of 1M rows | Detects changed rows/groups, recomputes only those | Re-reads & re-aggregates all 1M rows |
| Cost driver | Proportional to **change size** | Proportional to **full dataset size** |
| Decision logic | Cost analysis picks cheaper of incremental vs full | Full recompute only |

**The 10MB / 1M-row example (the answer they want):**
- **Serverless:** SDP detects that only ~10MB changed since the last refresh. For an aggregate (`GROUP BY`), it recomputes **only the affected groups** (technique `GROUP_AGGREGATE`, or `ROW_BASED` for row-level changes), then merges. Work scales with the **delta**, not the table. Cheap and fast. If nothing changed, technique is `NO_OP` — zero work.
- **Standard:** It rescans and recomputes **all 1,000,000 rows** every trigger, regardless that only 10MB moved. Same correct result, but far more compute than the serverless incremental path in this example.

**Approach — to actually get the cheap path on serverless:**
1. Run the pipeline on **serverless**.
2. Enable the optimization features on **source** tables (Databricks recommends all three on every MV source table):
```sql
ALTER TABLE source_tbl SET TBLPROPERTIES (
  delta.enableDeletionVectors = true,
  delta.enableRowTracking = true,
  delta.enableChangeDataFeed = true);
```
Row tracking is required by many incremental techniques; without it those operations fall back to full recompute. (Row filters / column masks on the source force a full refresh entirely.)
3. Keep the query incrementalizable (deterministic, supported constructs; no `PIVOT`, no recursive CTE).
4. **Verify** the technique actually used — don't assume:
```sql
SELECT timestamp, message FROM event_log(TABLE(cat.sch.my_mv))
WHERE event_type = 'planning_information' ORDER BY timestamp DESC;
-- look for GROUP_AGGREGATE / ROW_BASED (incremental) vs FULL_RECOMPUTE
```
5. To **force** behavior, set a refresh policy:
```python
@dp.materialized_view(refresh_policy='incremental_strict')  # fail rather than silently full-recompute
def my_mv():
    return spark.read.table("source_tbl")
```
```sql
CREATE MATERIALIZED VIEW my_mv REFRESH POLICY INCREMENTAL STRICT
AS SELECT a, SUM(b) AS sum_b FROM source_tbl GROUP BY a;
```
Policies: `AUTO` (default, cost-based), `INCREMENTAL` (prefer; fall back to full if the plan no longer supports incremental), `INCREMENTAL STRICT` (fail the update if not incrementalizable), `FULL` (always full).

**One-liner:** On a serverless pipeline an MV with 10MB changed in 1M rows recomputes only the affected groups (work scales with the delta); on a classic pipeline there is no incremental path so it re-aggregates all 1M rows every refresh.

#### Q13 — How an MV refreshes incrementally yet still aggregates the whole dataset
**Question:** How does a materialized view process data incrementally while still performing aggregations on the entire dataset?

**The apparent paradox:** A `GROUP BY` is a whole-table operation, yet SDP claims to refresh "only the changed data." Resolution: the **result** is always batch-correct (equals re-running the full query), but the **work** to reach that result is incremental. SDP maintains internal state so it never re-scans unchanged data.

**Mechanism (concrete trace):**
- MV: `SELECT country, SUM(amount) FROM txns GROUP BY country`. Suppose stored result is USA=100, UK=80, NL=50.
- A trigger adds 5,000 new `txns` rows touching only **USA** and **NL**.
- SDP uses **Change Data Feed + row tracking** on the source to read **only the changed rows** (the delta), not all of `txns`.
- It computes a **partial aggregate** over just those rows: +30 USA, +10 NL.
- It **merges** the partial into the stored groups: USA 100->130, NL 50->60. **UK is untouched** — its group is never recomputed.
- Final MV is identical to a full `GROUP BY` over all rows, but only 2 of 3 groups did any work.

**Why it's still "entire dataset" correct:**
- For incrementalizable aggregates SDP keeps **internal tables that support incremental refresh** — Databricks creates these to back the MV; they appear in `system.information_schema.tables` but are **not visible in Catalog Explorer or other workspace UI surfaces**. They hold per-group running state, so adding the delta to that state == aggregating everything.
- It's **additive aggregate maintenance**: `SUM`, `COUNT`, `GROUP BY` compose from partial results. The technique shows as `GROUP_AGGREGATE` (or `GENERIC_AGGREGATE`) in the event log.
- Late/out-of-order rows still land in the correct group on the next refresh — that's why MVs are "always correct" without watermarks (unlike a streaming aggregate).
- If a change can't be expressed as a partial merge (e.g., upstream deletes that need group recomputation without row tracking, or a non-incrementalizable construct), SDP falls back to `FULL_RECOMPUTE` — same answer, higher cost.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum as _sum

@dp.materialized_view  # GROUP_AGGREGATE incremental maintenance on a serverless pipeline
def revenue_by_country():
    return (spark.read.table("txns")
            .groupBy("country")
            .agg(_sum("amount").alias("revenue")))
```

```sql
CREATE OR REFRESH MATERIALIZED VIEW revenue_by_country AS
SELECT country, SUM(amount) AS revenue
FROM txns GROUP BY country;
```

**Requirements to keep it incremental:** serverless pipeline; deterministic query; row tracking (and ideally deletion vectors + CDF) enabled on the source; supported constructs only (`GROUP BY`, `SUM`/`COUNT`, inner/left/right/full joins, `WHERE`/`HAVING`, `UNION ALL`, window functions with `PARTITION BY` specified). Verify with the `planning_information` event-log query.

**One-liner:** The MV's output always equals a full batch aggregate, but SDP reaches it by reading only the changed rows via change-data-feed plus row tracking, computing a partial aggregate, and merging it into per-group state held in hidden internal tables — so untouched groups are never recomputed.

### Category 3 — Data Ingestion & Source Integration (Q14–Q16)

#### Q14 — Ingesting Oracle into an SDP pipeline + optimizations
**Question:** How do you ingest data from Oracle into your DLT pipeline? What optimizations can be applied? (DLT = SDP — Spark Declarative Pipelines / Lakeflow Declarative Pipelines.)

**Key fact (verified):** There is **no CDC (gateway/binlog) connector for Oracle**. Lakeflow Connect's managed *database CDC* connectors cover only MySQL, PostgreSQL, and SQL Server. Oracle is still a **first-class managed source** — it is supported by Lakeflow Connect's **query-based connector** (foreign-connection ingestion; the other listed query-based sources are Teradata, SQL Server, MySQL, MariaDB, PostgreSQL). So Oracle reaches SDP through one of two supported paths — pick based on whether the source has a usable cursor column.

**The two real options (most-managed first):**

| Path | What it is | When to use | Writes to |
|---|---|---|---|
| **Query-based connector** (Lakeflow Connect) | Managed connector that queries Oracle directly each run via a Unity Catalog (UC) connection (foreign-connection ingestion) or a Lakehouse Federation foreign catalog; tracks a **cursor column** (single monotonic timestamp/int) as a high-water mark; no gateway, no staging volume; runs on **serverless** on a schedule (not continuous); created via UI or Declarative Automation Bundles | Oracle table has an `updated_at` / monotonic id; you want minimal code | a **streaming table** (`@dp.table`) |
| **Generic JDBC read inside a flow** | `spark.read.format("jdbc")` (or SQL `remote_query()`) over a UC **JDBC connection**, wrapped in an SDP dataset | No clean cursor column, custom SQL, or you need full control | `@dp.materialized_view` (batch snapshot) or `@dp.table` |

- **MV (materialized view) vs streaming table:** a full JDBC read sees a **mutable, non-append-only** source — a re-read sees changed/deleted rows. A streaming table (`@dp.table`) needs an **append-only** source, so pointing one straight at a mutable Oracle table errors out. So a raw full JDBC read lands in an **MV** (recomputed on refresh). Note: MVs on a **serverless** pipeline attempt *incremental* refresh, but a mutable external JDBC source generally can't be incrementalized, so it falls back to a **full recompute**. True incrementality comes from the cursor-column query-based connector, not from a full JDBC read.

**PySpark — generic JDBC read as an SDP materialized view (`from pyspark import pipelines as dp`):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import current_timestamp

@dp.materialized_view(name="brz_oracle_customers")
def brz_oracle_customers():
    return (
        spark.read.format("jdbc")
        .option("databricks.connection", "oracle_uc_conn")  # UC JDBC connection hides URL + creds
        .option("dbtable", "SALES.CUSTOMERS")               # allow-listed user option (or 'query')
        .option("partitionColumn", "CUSTOMER_ID")           # parallel read — must be numeric/indexed
        .option("lowerBound", "1")
        .option("upperBound", "10000000")
        .option("numPartitions", "16")                      # all four params required together
        .option("fetchsize", "100000")                      # rows per round trip; raise to cut latency
        .load()
        .withColumn("_ingest_ts", current_timestamp())
    )
```

**SQL equivalent (`remote_query` via Lakehouse Federation):**
```sql
CREATE OR REFRESH MATERIALIZED VIEW brz_oracle_customers AS
SELECT *, current_timestamp() AS _ingest_ts
FROM remote_query(
  'oracle_uc_conn',
  service_name => 'ORCL',          -- Oracle uses service_name, not database
  dbtable      => 'SALES.CUSTOMERS',
  partitionColumn => 'CUSTOMER_ID',
  lowerBound   => '1',
  upperBound   => '10000000',
  numPartitions => '16',
  fetchsize    => '100000'
);
```

**Optimizations (verified defaults):**
- **Parallel reads** — `partitionColumn` + `lowerBound` + `upperBound` + `numPartitions` (all four mandatory together; must use `dbtable`, not `query`). Bounds set the *stride only* — they do **not** filter rows; every row in the table is still partitioned and returned. Partition column must be numeric (or date/timestamp/string for the managed connector), evenly distributed, and ideally indexed.
- **`fetchSize`** — default is `0` (use driver default; often tiny, and most JDBC connectors fetch atomically, which can OOM). Set ~`100,000` so worker nodes read in batches. This batches per worker but is **not** parallel — that's what `numPartitions` is for.
- **Pushdown** — Lakehouse Federation pushes down filters, column projection, `LIMIT`, and many aggregates to Oracle by default. Push filters and projection down so Oracle does the work, not Spark.
- **Cursor-column incremental** — for the query-based connector, only rows with `cursor > stored_high_water_mark` are pulled each run; NULL-cursor rows are skipped, and the cursor must be a single monotonic column. Avoids full-table scans on a hot Oracle instance.
- **Don't over-partition** — too many parallel JDBC connections can crash the source DB; keep `numPartitions` in the low tens, not hundreds.

**Approach (how I'd answer the client):**
1. Check Oracle for a reliable single cursor column (`LAST_MODIFIED`/sequence). If present → **query-based connector**, write to a streaming table, schedule it. If not → **generic JDBC read** into an MV.
2. Stand up the **UC connection** once (URL + creds hidden in the connection, never inlined; allow-listed options exposed via `externalOptionsAllowList`) — reusable across compute.
3. Land raw in **bronze** with operational metadata (`_ingest_ts`, source name); enforce schema once here.
4. Tune parallel reads + `fetchSize`; push filters down; add `@dp.expect` quality gates on bronze.

> *Apollo Gen2 note:* my project ingests **Dynamics 365 → Synapse Link → ADLS CSV → SDP**, so my bronze source is files (Auto Loader), not JDBC. For an Oracle source I'd reuse the same medallion + SCD2 bronze pattern, but swap the file reader for a UC JDBC connection / query-based connector as the bronze flow's source.

**One-liner:** Oracle has no CDC/gateway connector, so I ingest it either via the Lakeflow **query-based connector** (single-cursor-column high-water mark into a streaming table) or a **generic UC JDBC read** into a materialized view, then tune it with parallel reads (`partitionColumn`/bounds/`numPartitions`), a large `fetchSize` (~100k), and filter pushdown.

#### Q15 — Handling soft deletes (active flags vs other methods)
**Question:** How do you handle soft deletes in the data source — through active flags or another method?

**Definition first:** A **soft delete** = the source never physically removes the row; it flags it (`IsActive=0`, `IsDeleted=1`, or sets `DeletedDate`). A **hard delete** = the row physically disappears from the source. The handling differs because a soft delete still arrives as a normal change row, a hard delete arrives as nothing (the row is just absent).

**The decision: turn the soft-delete flag into a real CDC DELETE.** In SDP, `dp.create_auto_cdc_flow` (AUTO CDC) treats every event as an upsert *unless* `apply_as_deletes` matches — so I map the source's active/deleted flag into that predicate. The row is then removed from the *current* view, and under SCD2 it's closed off with `__END_AT`.

| Source pattern | SDP handling |
|---|---|
| `IsActive` boolean flag | `apply_as_deletes = "IsActive = false"` |
| `IsDeleted` / `RecordStatus` | `apply_as_deletes = expr("IsDeleted = 1")` |
| `DeletedDate` populated | `apply_as_deletes = "DeletedDate IS NOT NULL"` |
| Lakeflow query-based connector (no AUTO CDC) | API-only param `deletion_condition` (e.g. `"deleted_at IS NOT NULL"`) marks soft-deleted rows |

**Verified mechanics that matter in the interview:**
- **SCD2 + delete → tombstone:** when `apply_as_deletes` fires on an SCD2 target, the deleted row is **temporarily retained as a tombstone** in the underlying Delta table; a metastore **view filters tombstones out** so consumers don't see them. This exists to handle **out-of-order** events.
- **Tombstone retention default = two days**, configurable via the target table property `pipelines.cdc.tombstoneGCThresholdInSeconds`. If late/out-of-order deletes can arrive after two days, **raise this** so a late re-insert can't resurrect a row (set it above your worst-case event-arrival-to-pipeline-run delay).
- `apply_as_deletes` does **not** drop the row from history under SCD2 — it ends the current version (sets `__END_AT`). Under SCD1 it removes the row from current state.

**PySpark — soft-delete flag → SCD2 close-out (AUTO CDC):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("brz_customers")

dp.create_auto_cdc_flow(
    target              = "brz_customers",
    source              = "stg_customers",         # append-only streaming source
    keys                = ["CustomerId"],
    sequence_by         = "_change_ts",            # real per-row ordering, not file mod time
    apply_as_deletes    = expr("IsDeleted = 1"),   # soft-delete flag -> CDC DELETE
    except_column_list  = ["IsDeleted", "_change_ts", "_source_file_path"],
    stored_as_scd_type  = 2,
)
```

**SQL equivalent (SDP AUTO CDC):**
```sql
CREATE OR REFRESH STREAMING TABLE brz_customers;

CREATE FLOW customers_cdc AS AUTO CDC INTO brz_customers
FROM stream(stg_customers)
KEYS (CustomerId)
APPLY AS DELETE WHEN IsDeleted = 1
SEQUENCE BY _change_ts
COLUMNS * EXCEPT (IsDeleted, _change_ts, _source_file_path)
STORED AS SCD TYPE 2;
```

**Approach (scenario walk-through):**
1. **Identify the flag** — confirm with the source team which column carries the soft delete (`IsActive`/`IsDeleted`/`DeletedDate`) and its exact "deleted" value.
2. **Decide the semantic** — do downstream consumers need *history of when it was deactivated* (→ SCD2, close with `__END_AT`) or only *current active rows* (→ SCD1, drop from current)?
3. **Map flag → `apply_as_deletes`** in AUTO CDC so the framework handles ordering/dedup — never hand-roll a `MERGE`.
4. **Set tombstone retention** (`pipelines.cdc.tombstoneGCThresholdInSeconds`) to exceed worst-case late-delete latency.
5. **Don't blindly filter `WHERE IsActive=1` in bronze** — that loses the deactivation event silently. Keep the flag, let CDC act on it, and surface "active only" as a downstream view.

**One-liner:** Soft deletes are just flagged rows, so I map the source's active/deleted flag into `apply_as_deletes` (SQL `APPLY AS DELETE WHEN`) in AUTO CDC — which on SCD2 closes the row's `__END_AT` and parks it as a tombstone (retention default two days, tunable via `pipelines.cdc.tombstoneGCThresholdInSeconds`) rather than letting me silently filter the event away.

#### Q16 — Propagating CDC from a CSV source into Delta, and which layer
**Question:** How do you propagate CDC changes from a CSV source into Delta tables? In which layer is CDC handled?

**Which layer — short answer:** CDC is applied at the **bronze layer** (the first persisted Delta layer). Auto Loader incrementally ingests the raw CSVs into an append-only staging streaming table, and `dp.create_auto_cdc_flow` materializes the de-duplicated, ordered current/historical state into the bronze SCD table. Silver/gold then read clean Delta — they never re-solve CDC.

**The flow (verified path):**
```
CSV in ADLS ──Auto Loader──▶ stg streaming table (@dp.table, append-only)
                                   │
                          dp.create_auto_cdc_flow  (AUTO CDC — handles order/dedup/deletes)
                                   ▼
                          brz SCD2 Delta table (current + __START_AT/__END_AT history)
```

**Why a staging table sits in between:** AUTO CDC's source **must be a streaming, append-only source** — if a streaming read encounters a change or deletion to an existing record, it throws an error (it is safest to read from static or append-only sources). New CSV files are append-only on arrival, so Auto Loader → `@dp.table` gives a clean append-only stream; AUTO CDC then resolves the actual upserts/deletes into bronze.

**PySpark — CSV → bronze SCD2 via AUTO CDC:**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr, current_timestamp, col

@dp.table(name="stg_customers")            # append-only landing of raw CSV
def stg_customers():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("cloudFiles.schemaLocation", "/Volumes/.../_schema/customers")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")  # default when no schema given
        .option("header", "true")
        .load("/Volumes/.../incoming/customers/")
        .withColumn("_source_file_path", col("_metadata.file_path"))
        .withColumn("_processing_ts", current_timestamp())
    )

dp.create_streaming_table("brz_customers")

dp.create_auto_cdc_flow(
    target             = "brz_customers",
    source             = "stg_customers",
    keys               = ["CustomerId"],
    sequence_by        = "_change_ts",          # real per-row ordering column
    apply_as_deletes   = expr("Operation = 'DELETE'"),
    except_column_list = ["Operation", "_change_ts", "_source_file_path", "_processing_ts"],
    stored_as_scd_type = 2,
)
```

**SQL equivalent:**
```sql
CREATE OR REFRESH STREAMING TABLE stg_customers
AS SELECT *, _metadata.file_path AS _source_file_path, current_timestamp() AS _processing_ts
FROM STREAM read_files('/Volumes/.../incoming/customers/', format => 'csv', header => true);

CREATE OR REFRESH STREAMING TABLE brz_customers;

CREATE FLOW customers_cdc AS AUTO CDC INTO brz_customers
FROM stream(stg_customers)
KEYS (CustomerId)
APPLY AS DELETE WHEN Operation = 'DELETE'
SEQUENCE BY _change_ts
COLUMNS * EXCEPT (Operation, _change_ts, _source_file_path, _processing_ts)
STORED AS SCD TYPE 2;
```

**Two flavours of CSV CDC (know both):**
- **Change-feed CSVs** (each file is a row of inserts/updates/deletes with an `Operation` column) → `dp.create_auto_cdc_flow`.
- **Full-snapshot CSVs** (each file is the whole table state, no op column) → `dp.create_auto_cdc_from_snapshot_flow`, which diffs successive snapshots to derive the changes (Python interface only; snapshots must be processed in ascending version order, and you can't target the same streaming table with both flow types).

**Pitfalls I'd flag (from real CSV/Synapse work):**
- **`sequence_by` granularity** — `file_modification_time` is **too coarse** when many rows share one file; on ties CDC picks arbitrarily, and NULL sequence values aren't supported. Use a real per-row timestamp/sequence number.
- **Exclude operational-metadata columns the right way.** Two distinct levers: `except_column_list` *removes a column from the target table entirely*; `track_history_except_column_list` *keeps the column but doesn't open a new SCD2 version when only it changes*. If you leave `_processing_ts` / `_source_file_path` **in** the target and history-tracked, every re-run sees a "changed" metadata value and writes a **false SCD2 version** — so either drop them via `except_column_list` (as above) or, if you need to keep them, exclude them from history via `track_history_except_column_list`.
- **`schemaEvolutionMode` behavior (default `addNewColumns`)** — `addNewColumns` does **not** silently absorb a new column: the stream **fails with `UnknownFieldException`**, adds the new column to the schema location, and resumes on restart (run under a Lakeflow Job so it auto-restarts). It never removes/renames/retypes existing columns; a **dropped** source column is a soft delete — new rows land NULL. (Default is `addNewColumns` only when no schema is provided; if you supply a schema the default is `none`, and `addNewColumns` isn't allowed unless given as a schema hint.)
- **Headerless / trailing-comma CSVs** (Synapse Link) — fix in a preprocessing step before SDP, since SDP transformations can't run arbitrary file ops.

**Approach (Apollo Gen2, first person):**
On Apollo Gen2 (Dynamics 365 → Synapse Link → ADLS CSV → SDP, 211 entities) I do exactly this: a **JOB1 preprocessing notebook** adds headers from `model.json`, drops the phantom trailing-comma column, validates, and splits per entity into `incoming/` — because **SDP transformations can't run arbitrary Python** (`dbutils.fs`, file ops). **JOB2** is the SDP pipeline: Auto Loader → 211 STG streaming tables → `create_auto_cdc_flow` → 211 **bronze SCD2** tables, chained via `depends_on`. The 5 full-load entities use `create_auto_cdc_from_snapshot_flow` instead. CDC lives entirely in **bronze**; I never re-run CDC on an already-SCD2 source (that was a real incident — you collapse to current-only or map columns directly instead).

**One-liner:** I land raw CSV append-only via Auto Loader into a staging streaming table, then resolve CDC at the **bronze layer** with `dp.create_auto_cdc_flow` (snapshot CSVs use `create_auto_cdc_from_snapshot_flow`) into an SCD2 Delta table — sequenced by a real per-row column and excluding operational-metadata columns (via `except_column_list`, or from history via `track_history_except_column_list`) so re-runs don't create phantom versions.

### Category 4 — Change Data Capture (CDC) & Apply Changes (Q17–Q21)

#### Q17 — When to apply CDC; streaming table vs materialized view for CDC
**Question:** When using Change Data Capture (CDC), in which scenarios would you apply it? How do you decide between using Live Tables and Live Streaming Tables for CDC operations?

*(Legacy mapping, one clause: "Live Table" = **MV (materialized view)**, "Live Streaming Table" = **streaming table**; SDP (Spark Declarative Pipelines) renamed these. Answer below is in SDP terms.)*

**When to apply CDC (AUTO CDC):** use `dp.create_auto_cdc_flow` (Python) / `AUTO CDC ... INTO` (SQL) when any of these is true:
- Source emits a **CDF (Change Data Feed)** — insert/update/delete rows with an operation column.
- You read a **Delta table with Change Data Feed enabled**.
- A relational DB feed arrives via **Debezium / Oracle GoldenGate** (the patterns Databricks docs name explicitly) and you need ordered, deduplicated upserts.
- You need SCD (Slowly Changing Dimension) Type 1 (overwrite) or Type 2 (history) **without hand-writing MERGE + out-of-order handling**.

> Edition gate (docs): AUTO CDC requires **serverless** SDP or the **`PRO`** / **`ADVANCED`** edition. The default `CORE` edition cannot run CDC.

**Where the CDC target must live — this is the real decision:**

| Question | Answer |
|---|---|
| Can AUTO CDC write into an MV? | **No.** An AUTO CDC flow targets a **streaming table only** (`@dp.table` / `CREATE OR REFRESH STREAMING TABLE`). Per docs, a streaming table that is the target of an AUTO CDC flow can only be targeted by other AUTO CDC flows. |
| Why not an MV? | An MV is a **batch flow** that recomputes from sources; it has no incremental upsert/delete keyed by `sequence_by`. |
| What about reading the CDC result downstream? | The AUTO CDC target produces **updates/deletes**, so a **downstream streaming table cannot read it as an append-only source** (the stream errors on a non-append change). Two valid options: consume it with an **MV** in gold, or stream from the AUTO CDC target's **own Change Data Feed** (the target table can emit a CDF for downstream consumers). |

**Decision rule (medallion):**
- **Bronze / silver CDC apply target → streaming table** (it is the only legal AUTO CDC target).
- **Gold / aggregations over the CDC table → materialized view** (incremental refresh on serverless, fast dashboard reads).

**Apollo Gen2 (first person):** In my Novartis CRM pipeline I run **211 STG streaming tables + 211 BRZ SCD2 streaming tables = 422 SDP pipelines**. Bronze is a streaming table because that is the only thing an AUTO CDC flow can write SCD2 into. Anything that aggregates across the SCD2 history I expose as an MV so it incrementally refreshes instead of re-scanning all versions.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_account")          # AUTO CDC target MUST be a streaming table

dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",                          # streaming source
    keys=["accountid"],
    sequence_by="_processing_timestamp",
    stored_as_scd_type=2,
)

@dp.materialized_view                              # gold rollup over the SCD2 table -> MV
def account_active_count():
    return spark.sql("SELECT COUNT(*) AS n FROM brz_account WHERE __END_AT IS NULL")
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account;

CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account)
KEYS (accountid)
SEQUENCE BY _processing_timestamp
STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW account_active_count
AS SELECT COUNT(*) AS n FROM brz_account WHERE __END_AT IS NULL;
```

**One-liner:** Apply AUTO CDC whenever the source is a change/snapshot feed — the apply target is always a streaming table (the only legal AUTO CDC target), while gold aggregations over it are materialized views.

#### Q18 — Effectively applying changes (vs the deprecated auto-CDC feature)
**Question:** How to effectively apply changes (with reference to the deprecated auto-CDC feature)?

*(One-clause legacy mapping: the legacy `apply_changes()` / `APPLY CHANGES INTO` was **renamed** — same signature — to `dp.create_auto_cdc_flow()` / `AUTO CDC ... INTO`; `apply_changes_from_snapshot()` → `create_auto_cdc_from_snapshot_flow()`. Use the new names.)*

**The current API surface (SDP):**

| Capability | Python (SDP) | SQL (SDP) |
|---|---|---|
| Apply a change feed | `dp.create_auto_cdc_flow(...)` | `CREATE FLOW ... AS AUTO CDC INTO` |
| Apply from snapshots | `dp.create_auto_cdc_from_snapshot_flow(...)` | (Python only — no SQL surface) |
| Create the target | `dp.create_streaming_table("t")` | `CREATE OR REFRESH STREAMING TABLE t` |

**Effective-use checklist (what makes AUTO CDC correct, not just runnable):**
- **`keys`** — full natural/composite key that uniquely identifies a row. Wrong key = wrong upsert grain.
- **`sequence_by`** — a **monotonically increasing**, non-NULL column giving event order; AUTO CDC reorders out-of-sequence events for you. NULL sequencing values are not supported, and the column must hold **one distinct update per key per sequencing value** (use a `struct()` if a single column can't guarantee that — see Q21).
- **`apply_as_deletes`** — expr marking delete events (e.g. `"Operation = 'DELETE'"`); without it, deletes are treated as upserts.
- **`stored_as_scd_type`** — `1` (overwrite, **default**) or `2` (history with `__START_AT`/`__END_AT`).
- **`track_history_except_column_list` / `track_history_column_list`** — control which columns trigger a new SCD2 version. By default SCD2 versions on **any** changed column, so exclude operational metadata to avoid false history. (`except_column_list` / `COLUMNS * EXCEPT` instead controls which columns are *included in the target at all*.)
- **`ignore_null_updates`** (default **False**) — set **True** when the source sends only changed columns, so NULLs don't wipe unchanged columns. Default behavior is to overwrite existing columns with the incoming NULL.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_contact")

dp.create_auto_cdc_flow(
    target="brz_contact",
    source="stg_contact",
    keys=["contactid"],
    sequence_by="_processing_timestamp",
    apply_as_deletes="IsDelete = true",
    stored_as_scd_type=2,
    track_history_except_column_list=[          # critical in Apollo Gen2 (see one-liner)
        "_processing_timestamp", "_source_file_path", "SinkModifiedOn",
    ],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_contact;

CREATE FLOW contact_cdc AS AUTO CDC INTO brz_contact
FROM stream(stg_contact)
KEYS (contactid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY _processing_timestamp
COLUMNS * EXCEPT (_processing_timestamp, _source_file_path, SinkModifiedOn)
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (_processing_timestamp, _source_file_path, SinkModifiedOn);
```

> Note on the SQL surface: `COLUMNS * EXCEPT (...)` drops those columns from the *target*; `TRACK HISTORY ON * EXCEPT (...)` keeps them in the target but stops them from *triggering a new SCD2 version*. The Python equivalents are `except_column_list` and `track_history_except_column_list` respectively. The incident below is specifically about the **history-tracking** list.

**Apollo Gen2 incident (first person):** My biggest "effective apply" lesson was `track_history_except_column_list`. If I don't exclude every operational-metadata column (`_processing_timestamp`, `_source_file_path`, etc.) from *history tracking*, each re-run sees a "changed" value and closes the current SCD2 row + opens a new one — a **false history version on every pipeline run**. Listing those columns in the track-history-except list is what keeps SCD2 honest.

**One-liner:** `apply_changes` was renamed to `create_auto_cdc_flow` (same signature) — and applying changes *effectively* means correct `keys` + a monotonic, non-NULL `sequence_by` + explicit `apply_as_deletes` + excluding operational metadata from **history tracking** so re-runs don't fabricate SCD2 versions.

#### Q19 — SCD Type 2 in SDP vs hand-written PySpark
**Question:** How do you apply SCD Type 2 logic in both DLT and standard PySpark pipelines?

*(DLT here = SDP; answered in SDP terms.)*

**SCD2 in one line of intent:** preserve full history — every change closes the prior row (`__END_AT` set) and opens a new current row (`__END_AT = NULL`).

**A. SDP way (declarative — what I use in production):**
- Set `stored_as_scd_type=2`. SDP auto-adds **`__START_AT`** and **`__END_AT`** populated from your `sequence_by` value (same data type as `sequence_by`) and handles dedup + out-of-order + delete tombstoning for you.

```python
from pyspark import pipelines as dp

dp.create_streaming_table("brz_account")
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account",
    keys=["accountid"], sequence_by="_processing_timestamp",
    apply_as_deletes="IsDelete = true", stored_as_scd_type=2,
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account;
CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account) KEYS (accountid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY _processing_timestamp
COLUMNS * EXCEPT (_processing_timestamp, _source_file_path)
STORED AS SCD TYPE 2;
```

**B. Standard PySpark way (the manual MERGE you avoid):**

```python
from delta.tables import DeltaTable
from pyspark.sql import functions as F

tgt = DeltaTable.forName(spark, "brz_account")
incoming = spark.read.table("stg_account")

# 1) rows whose key already exists AND value changed -> need a new version
changed = (incoming.alias("s")
    .join(tgt.toDF().alias("t"),
          (F.col("s.accountid") == F.col("t.accountid")) & (F.col("t.__END_AT").isNull()))
    .where(F.col("s.hashdiff") != F.col("t.hashdiff"))
    .select("s.*"))

# 2) staged union: NULL-key rows force the "close current row" branch; real rows insert
staged = (changed.withColumn("mergeKey", F.lit(None))
          .unionByName(incoming.withColumn("mergeKey", F.col("accountid"))))

(tgt.alias("t").merge(
    staged.alias("s"),
    "t.accountid = s.mergeKey AND t.__END_AT IS NULL")
 .whenMatchedUpdate(condition="t.hashdiff <> s.hashdiff",
                    set={"__END_AT": "s._processing_timestamp"})          # close old
 .whenNotMatchedInsert(values={                                            # open new
     "accountid": "s.accountid", "hashdiff": "s.hashdiff",
     "__START_AT": "s._processing_timestamp", "__END_AT": "null"})
 .execute())
```

| Aspect | SDP AUTO CDC | Hand-written PySpark MERGE |
|---|---|---|
| Out-of-order events | Auto (via `sequence_by`) | You must order + watermark yourself |
| Dedup per key per seq | Auto | Manual window/dedup |
| `__START_AT`/`__END_AT` | Auto-generated | You manage the two-branch NULL-key MERGE |
| Deletes | `apply_as_deletes` + tombstone | Custom delete branch |
| LOC for 211 entities | ~6 lines × config | hundreds of lines, brittle |

**Apollo Gen2 incident (first person):** The trap is **SCD2-on-SCD2** — if the source is *already* SCD2, do **not** run AUTO CDC SCD2 on top of it (you'd version the versions). I either collapse to current-only or preserve the existing history via direct column mapping.

**One-liner:** In SDP I set `stored_as_scd_type=2` and let `sequence_by` populate `__START_AT`/`__END_AT`; the equivalent raw-PySpark is a two-branch NULL-merge-key Delta MERGE that closes the old version and inserts the new one.

#### Q20 — APPLY CHANGES set in silver but not reflected in gold
**Question:** If APPLY CHANGES is enabled in a silver layer but not reflected in the gold layer, what could be the issue?

*(APPLY CHANGES = SDP AUTO CDC; answered in SDP terms.)*

**Approach (diagnose top-down):** the AUTO CDC target in silver is a **streaming table that emits updates and deletes**. Gold's failure to reflect it almost always comes from *how gold consumes that mutable table*.

| # | Likely cause | Why gold goes stale / errors | Fix |
|---|---|---|---|
| 1 | **Gold is a streaming table reading the silver CDC table directly** | A streaming table needs an **append-only** source; an AUTO CDC target produces updates/deletes → the stream throws on the first non-append change (it does not silently "stall") | Make **gold an MV** (it recomputes incrementally over the mutable table); or stream from the silver target's **own Change Data Feed** instead of the table |
| 2 | **Gold reads only current rows but query forgets the SCD2 filter** | All historical versions counted, or stale versions shown | Filter `WHERE __END_AT IS NULL` for current-state gold |
| 3 | **Gold not refreshed / triggered** | Silver updated, gold update never ran | Trigger the gold pipeline / verify schedule; check decoupled bronze-silver vs gold pipelines. (Incremental MV refresh runs only on **serverless** — a non-serverless MV falls back to full recompute, which can look like lag) |
| 4 | **Deletes invisible at gold via the wrong object** | On **Hive metastore**, AUTO CDC creates a *view* over an internal `__apply_changes_storage_<name>` backing table that filters out delete tombstones; querying the backing table directly shows tombstoned rows | Read the **published view/table** by its declared name, never the `__apply_changes_storage_` backing table |
| 5 | **Expectation `expect_or_drop` upstream** | Rows dropped in silver never reach gold | Check data-quality metrics; relax/quarantine instead of drop |
| 6 | **`skipChangeCommits` misunderstanding** | `skipChangeCommits` lets a downstream streaming table *ignore* updates/deletes on a source — so deletes/updates would never propagate **by design**. But note: it **cannot be set when the source IS an AUTO CDC target** (docs explicitly disallow it there), so this only applies to ordinary mutable streaming sources, not the CDC target | Don't reach for `skipChangeCommits` to "fix" gold over a CDC target — switch gold to an MV |

```sql
-- WRONG: streaming table over a mutable AUTO CDC target -> errors on the first update/delete
CREATE OR REFRESH STREAMING TABLE gold_bad
AS SELECT * FROM STREAM(silver_cdc);

-- RIGHT: MV recomputes incrementally over the mutable silver table
CREATE OR REFRESH MATERIALIZED VIEW gold_good
AS SELECT region, COUNT(*) AS active
   FROM silver_cdc WHERE __END_AT IS NULL
   GROUP BY region;
```
```python
@dp.materialized_view
def gold_good():
    return spark.sql("""
        SELECT region, COUNT(*) AS active
        FROM silver_cdc WHERE __END_AT IS NULL GROUP BY region""")
```

**Apollo Gen2 (first person):** I hit exactly cause #1 — **streaming-on-mutable-source**. A gold streaming table off an SCD2 silver target errors on the first update/delete; the moment I switched gold to an MV with a `__END_AT IS NULL` filter it reflected correctly.

**One-liner:** 90% of the time it's that gold is a streaming table reading a mutable AUTO CDC target — switch gold to a materialized view (and filter `__END_AT IS NULL` for current state).

#### Q21 — Preventing invalid records during APPLY CHANGES; sequenceBy and friends
**Question:** During APPLY CHANGES, how can we prevent invalid records from reaching the target table? What configurations can we set (e.g., sequenceBy)?

*(APPLY CHANGES = SDP AUTO CDC; answered in SDP terms.)*

**Approach — two distinct defenses, don't conflate them:**

**1. Correctness configs on `create_auto_cdc_flow` (prevent *wrong* upserts):**

| Config | Role | Default | Gotcha |
|---|---|---|---|
| `sequence_by` | Orders CDC events; AUTO CDC keeps the **latest per key**, reorders out-of-order events | required | Must be **monotonic + non-NULL**, with **one distinct update per key per sequencing value**; if a single column can tie, docs say to combine columns in a `struct()` |
| `keys` | Upsert grain | required | Wrong/partial key = merged or duplicated rows |
| `apply_as_deletes` | Marks delete events | none (treated as upsert) | Omit and deletes resurrect as rows |
| `ignore_null_updates` | Keep existing value when update column is NULL | **False** | Leave False and partial updates blank out columns (default overwrites with NULL) |
| `stored_as_scd_type` | 1 overwrite / 2 history | **1** | SCD2 needs `__START_AT`/`__END_AT` |
| `except_column_list` | Drop columns from the target | all included | exclude `operation`, metadata |
| `pipelines.cdc.tombstoneGCThresholdInSeconds` | How long SCD2 delete tombstones are retained for out-of-order deletes | **2 days (172800s)** | Raise it above max event-arrival lag |

**2. Data-quality expectations (block *invalid* rows before they apply):** expectations attach to the **target streaming table definition** and run on every row.

| Action | Python | SQL | Effect |
|---|---|---|---|
| warn (default) | `@dp.expect` | `EXPECT (...)` | row written, metric logged |
| drop | `@dp.expect_or_drop` | `... ON VIOLATION DROP ROW` | invalid row dropped pre-write |
| fail | `@dp.expect_or_fail` | `... ON VIOLATION FAIL UPDATE` | update fails (the failing run aborts) |
| many at once | `@dp.expect_all` / `_all_or_drop` / `_all_or_fail` | one CONSTRAINT each | granular metrics (collective action is Python-only) |

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import struct

dp.create_streaming_table(
    name="brz_account",
    expect_all_or_drop={                       # gate invalid rows BEFORE AUTO CDC applies
        "valid_key": "accountid IS NOT NULL",
        "valid_seq": "_processing_timestamp IS NOT NULL",
    },
)
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account", keys=["accountid"],
    sequence_by=struct("_processing_timestamp", "accountid"),   # break ties (see incident)
    apply_as_deletes="IsDelete = true", stored_as_scd_type=2,
)
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_account (
  CONSTRAINT valid_key EXPECT (accountid IS NOT NULL)            ON VIOLATION DROP ROW,
  CONSTRAINT valid_seq EXPECT (_processing_timestamp IS NOT NULL) ON VIOLATION FAIL UPDATE
);

CREATE FLOW account_cdc AS AUTO CDC INTO brz_account
FROM stream(stg_account) KEYS (accountid)
APPLY AS DELETE WHEN IsDelete = true
SEQUENCE BY STRUCT(_processing_timestamp, accountid)
STORED AS SCD TYPE 2;
```

**Apollo Gen2 incident (first person):** My `sequence_by` was `file_modification_time`, but **many rows share one file**, so the sequencing column had multiple updates at the same value for a key — which AUTO CDC does not support, and the per-key winner was undefined. Fix: a **`struct()` sequence** (`struct(file_modification_time, real_per_row_key)`) to restore one distinct update per key per sequence value. Pattern I hold: **warn-in-dev, fail-in-prod** — FAIL = integrity gates (PK, SCD2, CDC), WARN = observability (freshness, schema drift), so I catch silent failures, not just hard ones.

**One-liner:** Two layers — `expect_or_drop`/`expect_or_fail` constraints gate invalid rows before they apply, while `sequence_by` (monotonic, non-NULL, one distinct update per key per value, tie-broken with a `struct()`), correct `keys`, and `apply_as_deletes` keep AUTO CDC from producing *wrong* upserts.

### Category 5.1 — Basic Streaming Operations (Q22–Q24)

#### Q22 — Unioning streaming tables in SDP
**Question:** How do you perform union operations between streaming tables in DLT (SDP)?

**Short answer:** In SDP (Spark Declarative Pipelines — the question's "DLT" is the same engine) the idiomatic union is **not** a `UNION` in the query — it is **multiple append flows targeting one streaming table**. `@dp.append_flow` (Python) / `CREATE FLOW ... INSERT INTO` (SQL) lets several streaming sources fan-in to a single target.

**Two ways, and why one wins:**

| Approach | Mechanism | Cost of adding a new source |
|---|---|---|
| `UNION` inside one streaming query | one flow, one checkpoint over the unioned plan | Changes the query plan → forces a **full refresh** (re-reads all sources from scratch) |
| Multiple append flows → one ST (streaming table) | one **independent checkpoint per flow** | Add a new `@dp.append_flow`; existing flows keep their offsets, **no full refresh** |

- **Append flow** = the default flow type for a streaming table; new source rows are appended on each update (Structured Streaming append mode). Any number of append flows can write to one target.
- Each flow is keyed by its **flow name** → that name identifies its checkpoint. Rename a flow and the checkpoint does not carry over (it becomes a brand-new flow); you cannot reuse a flow name in a pipeline because the existing checkpoint won't match the new flow definition.
- **Constraint:** expectations (`@dp.expect`) must be defined on the **target** streaming table (in `create_streaming_table(...)` or the table definition), **not** inside `@dp.append_flow`.
- All source schemas must align with the target (use `BY NAME` in SQL to match by column name).

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

dp.create_streaming_table("customers_us")          # single target ST

@dp.append_flow(target="customers_us")
def from_west():
    return spark.readStream.table("customers_us_west")

@dp.append_flow(target="customers_us")
def from_east():
    return spark.readStream.table("customers_us_east")
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE customers_us;

CREATE FLOW from_west
AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_west);

CREATE FLOW from_east
AS INSERT INTO customers_us BY NAME
SELECT * FROM STREAM(customers_us_east);
```

**Approach (what I'd say in the room):** "If the union set is fixed and rebuilds are cheap, a `UNION` in one `@dp.table` is fine. But in production — where new regions/sources arrive over time — I use one append flow per source into a shared streaming table. Each source then has its own checkpoint, so onboarding a new source is purely additive and never triggers a full refresh of the others. For a one-time historical merge I'd use `INSERT INTO ONCE` / `once=True` so the backfill runs once and isn't replayed unless the table is fully refreshed."

**Apollo Gen2 grounding:** Our 211 entities each land in their own STG streaming table, so we didn't union sibling sources there — but the append-flow-over-UNION rule is exactly what I'd reach for if Synapse Link ever split one entity across multiple `replicate/` drop paths: one append flow per path into one STG table, independent checkpoints, zero full-refresh risk.

**One-liner:** In SDP you union by attaching multiple `@dp.append_flow`s to one streaming table rather than using `UNION`, because each flow carries its own checkpoint and adding a source stays incremental instead of forcing a full refresh.

#### Q23 — What enables SDP to join two streaming sources, and what happens behind the scenes
**Question:** What enables DLT (SDP) to join two streaming sources — what happens behind the scenes?

**The enabler:** a **watermark on BOTH sides** plus a **time-bounded join condition**. Those two together let the engine bound and evict state; without them a stream-stream join's state grows unbounded → OOM (out-of-memory).

**Behind the scenes (the machinery):**
- The operator is a **symmetric-hash join** (operator name `symmetricHashJoin` in the streaming state-operator metrics). Each incoming row from stream A is buffered in a state store and probed against buffered rows of stream B, and vice-versa — symmetric because either side can arrive first.
- **State stores:** a stream-stream join initializes **four state-store instances per shuffle partition** (vs. one per partition for most stateful operators) — exposed as `numStateStoreInstances` in `StreamingQueryProgress`. This is the concrete "what happens" detail interviewers want.
- **Watermark eviction:** the engine tracks max event-time per input, computes a watermark per stream, then keeps **one global watermark = the *minimum* across streams** (default policy `min`, so the slowest stream gates eviction and you don't drop matchable rows). The **time-interval condition** tells the engine when no further match is possible, so rows past that bound are evicted from state.
- Streams can use **different** watermark thresholds; setting `spark.sql.streaming.multipleWatermarkPolicy=max` follows the fastest stream but **drops** slow-stream data — Databricks recommends using it with caution.
- Supported stream-stream join types: inner, left outer, right outer, full outer, left semi. For outer joins watermarking is mandatory; stream-stream joins only support append output mode.

**Stream-static is different (and cheaper):** joining a stream to a static Delta table is a **stateless** join — no watermark needed. The **latest valid version of the static table is re-read at the start of each micro-batch**, so late-arriving dimension rows are NOT retroactively applied to facts already processed, and the result is non-deterministic if the static side changes between runs.

**PySpark (SDP, stream-stream):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

@dp.table
def impressions_with_clicks():
    impressions = (spark.readStream.table("impressions")
                   .withWatermark("impression_time", "10 seconds"))
    clicks = (spark.readStream.table("clicks")
              .withWatermark("click_time", "3 minutes"))
    return impressions.join(
        clicks,
        expr("""
          impressions.ad_id = clicks.ad_id AND
          click_time BETWEEN impression_time AND impression_time + INTERVAL 3 MINUTES
        """),
        "inner")
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE impressions_with_clicks AS
SELECT i.*, c.click_time
FROM STREAM(impressions) i
  WATERMARK impression_time DELAY OF INTERVAL 10 SECONDS
JOIN STREAM(clicks) c
  WATERMARK click_time DELAY OF INTERVAL 3 MINUTES
ON i.ad_id = c.ad_id
AND c.click_time BETWEEN i.impression_time AND i.impression_time + INTERVAL 3 MINUTES;
```

**Approach:** "First I decide stream-stream vs stream-static. If the right side is a slowly-changing dimension Delta table, I make it a stream-static stateless join — no watermark, low latency, snapshot refreshed per micro-batch. If both sides are genuinely unbounded streams, I add a watermark on each side and a time-bound (`BETWEEN ... + INTERVAL`) so state stays finite. I also enable the RocksDB state store for large joins so state spills to disk instead of heap — and on serverless SDP the state store is managed automatically (RocksDB is the default state provider from Databricks Runtime 17.2)."

**Apollo Gen2 grounding:** Most of my joins are silver enrichments against reference data, which are stream-static — and I lean on the per-micro-batch snapshot semantics: a Dynamics 365 lookup that updates mid-run won't retroactively rewrite already-processed CRM rows, which is the behavior we want for auditability.

**One-liner:** SDP joins two streams via a symmetric-hash join backed by four state-store instances per partition, and what *makes it bounded* is a watermark on both sides plus a time-interval condition that lets the engine evict state once no further match is possible — whereas a stream-static join is stateless and just re-reads the latest Delta snapshot each micro-batch.

#### Q24 — How SDP determines where to start in a stream (offsets, checkpointing)
**Question:** How does DLT (SDP) determine where to start processing data in a stream (offset, checkpointing, etc.)?

**The mechanism:** SDP is built on Spark Structured Streaming and **manages the checkpoint for you, one checkpoint per flow**, in an internal location you cannot access. The checkpoint persists three things:

| Checkpoint contents | What it does |
|---|---|
| **Progress / offsets** | which source offsets have already been processed (the "where to start" answer) |
| **Intermediate state** | state across micro-batches for stateful ops (aggregations, joins, dedupe) |
| **Metadata** | streaming-query execution info |

**The decision rule (precise):**
1. **First-ever run of a flow** → start position comes from the **source's starting-offset option**.
   - **Kafka / `read_kafka`:** `startingOffsets` default = **`latest`** for streaming (only new data after start; default is `earliest` for batch). Set `earliest` to read existing data, or a JSON offset map (`-2`=earliest, `-1`=latest) per topic-partition.
   - **Auto Loader / `read_files`:** `cloudFiles.includeExistingFiles` (default **`true`** → ingests files already in the path on first run, then continues incrementally; set `false` to ingest only files created after stream start). Note: Auto Loader always performs a full directory listing on the first run even when `includeExistingFiles=false` — the flag controls only whether pre-existing files are *ingested*, not whether listing happens.
   - **Delta source:** optional `startingVersion` / `startingTimestamp`; otherwise from the current table version.
2. **Every subsequent run** → SDP **ignores the starting-offset option and resumes from the checkpoint**. This is the gotcha interviewers test: changing `startingOffsets` after the first run does nothing. Newly discovered Kafka partitions mid-stream start at **earliest**.
3. **Exactly-once:** checkpointed offsets + idempotent Delta sink = each record processed once across failures/restarts.

**When the checkpoint is the problem — recovery (SDP-specific):** Some changes make a streaming query unable to safely resume from its checkpoint — e.g., changing aggregation grouping keys or aggregate functions, adding/removing an aggregation, changing join keys or join types, adding/removing a join, or changing deduplication columns. The flow then hard-fails and cannot progress. Three recovery options:

| Option | Data loss | Note |
|---|---|---|
| **Full refresh** | possible (if source no longer retains history) | resets the table + wipes existing data, then rebuilds; lets you change logic |
| **Full refresh + backup/backfill** | none | expensive; last resort |
| **Selective checkpoint reset** | none if reset carefully | `reset_checkpoint_selection` in the pipelines REST API `updates` request; pass fully-qualified `catalog.schema.flow_name` |

- Flow name = checkpoint identity. Default flow name = fully-qualified target table (`catalog.schema.table`); a custom `flow_name` (or `name`) overrides it, in which case the fully-qualified flow name is `catalog.schema.flow_name`. Passing a simple (non-qualified) name to `reset_checkpoint_selection` fails the update with an `IllegalArgumentException`. For a stream-stream join/union recovery you must reset **all** participating source flows.

**PySpark (SDP) — first-run start position is set on the source, not a checkpoint path:**
```python
from pyspark import pipelines as dp

@dp.table  # SDP owns the checkpoint internally — no .option("checkpointLocation", ...)
def kafka_bronze():
    return (spark.readStream.format("kafka")
            .option("kafka.bootstrap.servers", "...:9092")
            .option("subscribe", "orders")
            .option("startingOffsets", "earliest")   # honored ONLY on first run
            .load())
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE kafka_bronze AS
SELECT * FROM STREAM read_kafka(
  bootstrapServers => '...:9092',
  subscribe        => 'orders',
  startingOffsets  => 'earliest'   -- first run only; restarts use the checkpoint
);
```

**Approach:** "I never hand-manage `checkpointLocation` in SDP — the engine keeps one checkpoint per flow internally. So 'where does it start?' has two cases: first run = the source's `startingOffsets` / `includeExistingFiles` setting; every run after = the checkpoint, which is why flipping `startingOffsets` later is a no-op. If I genuinely need to rewind, I do a selective `reset_checkpoint_selection` on the specific fully-qualified flow name to preserve existing table data, and reserve full refresh for when I'm also changing stateful logic."

**Apollo Gen2 grounding:** Our STG streaming tables read Synapse Link CSV drops via Auto Loader, so first-run start was governed by `includeExistingFiles=true` to pull the existing `incoming/` backlog, then incremental from the per-flow checkpoint. Because each of the 211 STG tables is its own flow with its own checkpoint, when one entity's logic changed we could reset just that flow rather than full-refreshing all 211 — exactly the selective-checkpoint-reset path.

**One-liner:** SDP keeps one Structured-Streaming checkpoint per flow that records processed offsets, state, and metadata; the first run starts from the source's `startingOffsets`/`includeExistingFiles` setting and every run after resumes from that checkpoint — so to rewind you do a selective `reset_checkpoint_selection` on the fully-qualified flow name, not a change to the offset option.

### Category 5.2 — Advanced Streaming Joins & Watermarks (Q25–Q27)

#### Q25 — Bounding stream-stream left-join state under large arrival gaps
**Question:** When joining two streaming tables using left joins, how do you handle scenarios where data arrives at different times with large gaps (e.g., a 12-hour delay) without causing out-of-memory issues due to large watermark settings?

**The core mechanism (verified against current SDP docs):**
- A stream-stream join keeps **both** sides buffered in state until the engine can prove no future row can match. Two things let it evict that state:
  1. A **watermark on BOTH sides** (`WATERMARK ... DELAY OF INTERVAL` in SQL / `.withWatermark()` in PySpark). For an **outer/left join, a watermark is MANDATORY**, not optional.
  2. A **time-bounded join condition** — a range predicate on the two event-time columns, using the same fields the watermarks are defined on. This interval is what tells the engine "after this point, no further match is possible," so it can drop state. Omit either the watermarks OR the time bound and **state grows without bound → OOM**.
- The trap in the question: people try to absorb a 12-hour gap by setting a **12-hour watermark**. That is the wrong knob. A 12-hour watermark forces the engine to retain ~12 hours of BOTH streams' join keys in the state store — that is exactly what blows memory. Stream-stream joins also allocate **four state-store instances per partition** (confirmed in the `numStateStoreInstances` metric docs), so the blow-up is multiplied.

**Approach (how I'd actually solve a 12-hour skew):**
- **Don't widen the watermark to swallow the gap.** Keep the watermark at a realistic lateness tolerance (minutes/low hours) and set the **time-bound join window** to the real business horizon. The two are separate dials: watermark = "how late a row may arrive," join interval = "how far apart two matching rows may be."
- **If the late side is a slowly-changing dimension, don't stream-stream join it at all** — that is the wrong tool. Make it a **stream-static / stream-snapshot join** (stateless, no watermark, low memory) or a `dp.create_auto_cdc_flow` SCD target you join against. A 12-hour-delayed dimension does not belong in a symmetric-hash stream-stream join.
- **Watch the global watermark.** With two watermarks the engine takes the **minimum** of the two as the global watermark (default `spark.sql.streaming.multipleWatermarkPolicy = min`). If one stream stalls for 12 hours, the **min policy holds the whole join's watermark back**, state piles up, and output is delayed. That is correct (safe) but memory-heavy. Setting the policy to `max` advances with the fast stream but then **drops the slow stream's data** — only acceptable if losing the laggard is tolerable.
- **Monitor the state, don't guess:** check `stateOperators.numRowsTotal`, `memoryUsedBytes`, and `numStateStoreInstances` in the streaming progress / pipeline event log to confirm state is actually being evicted.

**PySpark (SDP — left/outer join with watermark on both sides + time bound):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

dp.create_streaming_table("impression_clicks")

@dp.append_flow(target="impression_clicks")
def join_impressions_and_clicks():
    impressions = (spark.readStream.table("ad_impressions")
                   .withWatermark("impression_time", "30 minutes"))   # lateness tolerance, NOT the gap
    clicks = (spark.readStream.table("user_clicks")
              .withWatermark("click_time", "30 minutes"))
    return impressions.alias("imp").join(
        clicks.alias("clk"),
        expr("""
            imp.ad_id = clk.ad_id
            AND clk.click_time BETWEEN imp.impression_time
                                   AND imp.impression_time + INTERVAL 3 MINUTES
        """),                                                          # time-bound = match horizon
        "leftOuter"
    )
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE impression_clicks AS
SELECT imp.ad_id, imp.impression_time, clk.click_time
FROM STREAM(ad_impressions)
       WATERMARK impression_time DELAY OF INTERVAL 30 MINUTES imp
LEFT JOIN STREAM(user_clicks)
       WATERMARK click_time DELAY OF INTERVAL 30 MINUTES clk
  ON imp.ad_id = clk.ad_id
 AND clk.click_time BETWEEN imp.impression_time
                        AND imp.impression_time + INTERVAL 3 MINUTES;
```

**Apollo Gen2 grounding (first person):** In our Synapse-Link feeds the join-key skew came from entities landing in different files at different times. We deliberately did **not** stream-stream-join the slow side; the dimension-like entities were materialized as SCD2 bronze via `create_auto_cdc_flow` and joined as static/snapshot downstream, so the only true stream-stream joins kept a tight watermark and never had to buffer a half-day of state.

**One-liner:** I bound state with a watermark on both sides plus a time-bounded join condition, and I size the watermark to real lateness — not to the gap — because absorbing a 12-hour skew belongs in the join interval (or a stateless stream-static join), not in an oversized watermark that OOMs the state store.

#### Q26 — Late-arriving matches and the null rows from a left outer join
**Question:** In streaming pipelines, when left outer joins produce null records due to late-arriving data, how do you ensure these null records get corrected when matching data eventually arrives?

**The hard truth first (verified):**
- Stream-stream joins support **append output mode only**. In append mode a row, once written, is **final — it cannot be retracted or updated**.
- For an outer join, an **unmatched left row is NOT emitted immediately**. The engine holds it in state and only writes the null-filled row **after the lateness threshold passes** and it has proven no match can still arrive (per the "Watermarks and output modes for stream-stream joins" docs).
- Consequence: **a null is only ever written when the engine already gave up waiting.** So there is no "null now, correct it later" in a single append-mode join — by construction, if the match arrives **within** the watermark window you get a matched row and **no null is ever written**; if it arrives **after** the window, the null was already emitted and the late match is dropped. **You cannot retroactively patch the null in the same join.**

**Approach — so how do you "correct" it? You design so the correction never needs to happen, or you push it to a layer that allows updates:**

| Strategy | Mechanism | When to use |
|---|---|---|
| **Right-size the watermark/join interval** | Make the lateness threshold ≥ the realistic max delay of the right side, so the match lands *before* the null is emitted. The null then never occurs. | Default fix. Bounded, known lateness. |
| **Push correction into a CDC/MV layer** | Land the join result, then resolve nulls downstream with `create_auto_cdc_flow` (SCD1 upsert) or a `@dp.materialized_view` that re-joins against the now-complete dimension. MVs/CDC targets **can update rows**; the append-only join cannot. | Unbounded or very long delays (the 12-hour case). |
| **Stream-static / snapshot join instead** | If the "late" side is a dimension, join the stream against the static Delta snapshot — no nulls-from-lateness semantics at all. | Right side is slowly-changing reference data. |
| **Backfill / full refresh** | Reprocess from bronze (full history retained) once late data lands, rebuilding the gold join. | Correctness-critical, batch-tolerant. |

**Key reasoning to say out loud:** the null is not a bug you fix in place — it is the engine's *final answer* under append semantics. Either you widen the time the engine waits (watermark) so the match arrives in time, or you move the join to a layer (MV / `create_auto_cdc_flow` SCD1) whose update semantics let a later row overwrite the earlier null.

**PySpark (correction layer: append-only join → CDC upsert that overwrites nulls):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import expr

# Layer 1: append-only left join (may emit null-filled rows after the lateness threshold)
dp.create_streaming_table("orders_enriched_raw")

@dp.append_flow(target="orders_enriched_raw")
def join_orders_customers():
    orders = spark.readStream.table("orders").withWatermark("order_ts", "2 hours")
    cust   = spark.readStream.table("customers").withWatermark("cust_ts", "2 hours")
    return orders.alias("o").join(cust.alias("c"),
        expr("o.cust_id = c.cust_id AND c.cust_ts BETWEEN o.order_ts - INTERVAL 2 HOURS AND o.order_ts + INTERVAL 2 HOURS"),
        "leftOuter")

# Layer 2: SCD1 upsert keyed by order_id — a later, fully-matched row OVERWRITES the earlier null row
dp.create_streaming_table("orders_enriched")
dp.create_auto_cdc_flow(
    target="orders_enriched",
    source="orders_enriched_raw",
    keys=["order_id"],
    sequence_by="order_ts",          # latest version wins
    stored_as_scd_type=1,
)
```

**SQL equivalent (correction layer = AUTO CDC SCD1):**
```sql
CREATE OR REFRESH STREAMING TABLE orders_enriched;

CREATE FLOW fix_nulls AS AUTO CDC INTO orders_enriched
FROM STREAM(orders_enriched_raw)
KEYS (order_id)
SEQUENCE BY order_ts
STORED AS SCD TYPE 1;
```

**Apollo Gen2 grounding (first person):** I hit the mutable-source version of this — a streaming table needs an append-only source, and when an upstream row mutated, the append-only flow couldn't "correct" it in place. The fix was the same shape as above: keep the streaming/join layer append-only, then resolve corrections in a `create_auto_cdc_flow` SCD layer keyed by the entity PK with `sequence_by`, so the latest complete version overwrites the earlier partial/null one. We never tried to mutate an append-mode output.

**One-liner:** An append-mode left join writes the null only after it has stopped waiting, so it can't be patched in place — I either size the watermark so the match arrives before the null is emitted, or I land the join append-only and resolve nulls in a downstream SCD1 `create_auto_cdc_flow` / materialized view whose update semantics let the complete row overwrite the earlier null.

#### Q27 — Effect of window length, and data arriving outside the watermark
**Question:** What is the effect of using different window lengths in streaming aggregations? What happens if data arrives outside the defined watermark window?

**Window length — two separate dials (window vs watermark):**
- **Window length** = the size of the time bucket you aggregate over (`window(event_time, '1 minute')`). **Watermark** = how long the engine waits for late rows before finalizing/evicting that window. They are independent; people conflate them.
- Effect of window length:

| Window length | Effect on result | Effect on state/memory | Effect on latency |
|---|---|---|---|
| **Short** (e.g. 1 min) | Fine-grained, more output rows | Many concurrent windows, each small; high row count | Results finalize sooner (window end reached quickly) |
| **Long** (e.g. 1 hour) | Coarse, fewer rows | Fewer windows but each holds more accumulated state | Results delayed until the long window closes + watermark passes |

- **Window types** (all need a watermark to bound state):
  - **Tumbling** — fixed, non-overlapping; each row in exactly one window.
  - **Sliding** — fixed size, overlapping by `slideDuration` (≤ window length); **one row lands in multiple windows → multiplies state**, so memory cost is higher than tumbling for the same window length.
  - **Session** — variable size; opens on a row, closes after a `gapDuration` of silence.

**A window finalizes when:** the latest observed event time reaches `window_end + watermark`. At that point no new data is accepted for the window, the aggregate is emitted (in append mode) and **the window's state is dropped**. So: longer window OR longer watermark = state held longer = more memory + higher latency; that is the throughput/lateness tradeoff.

**What happens to data outside the watermark window (verified):**
- A row whose event time is **older than `(max_event_time_seen − watermark)`** is **too late**: its window's state has already been dropped, so the row is **dropped from the aggregation** — it does **not** update the already-emitted result.
- Important nuance from the docs: the guarantee is one-directional. Rows **within** the threshold are **always** processed. Rows **outside** the threshold **might still** be processed, but it is **not guaranteed** — so you must treat anything past the watermark as "may silently vanish."
- It is **silent** — no error, no failure. The only signal is the metric **`stateOperators.numRowsDroppedByWatermark`** in the streaming progress / pipeline event log. Per the metric docs this counts **post-aggregation** rows for streaming aggregations and is **not precise** — it is an indication that late data is being dropped, not an exact input-row count.
- **Output mode interaction:** `append` drops old window state after the threshold (bounded memory, late data lost); `complete` keeps **all** window state and rewrites the target each trigger (no drop, no memory bound — only viable for small key spaces). In SDP, append + watermark is the norm precisely to bound memory.

**Approach (operationalizing it — mirrors how I'd test it):** because the drop is silent, late-data loss is an **observability concern, not a hard gate**. I'd surface `numRowsDroppedByWatermark` as a **WARN** signal (freshness/drift class) rather than fail the pipeline, and only fail on integrity violations — the same warn-in-dev/fail-in-prod split we used for SIT.

**PySpark (SDP — tumbling window + watermark):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import window, sum as _sum

@dp.table
def revenue_per_minute():
    return (spark.readStream.table("orders")
            .withWatermark("event_time", "3 minutes")              # late tolerance
            .groupBy(window("event_time", "1 minute"), "region")   # window length
            .agg(_sum("amount").alias("revenue")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE revenue_per_minute AS
SELECT window(event_time, '1 minute') AS time_window, region, SUM(amount) AS revenue
FROM STREAM(orders)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY window(event_time, '1 minute'), region;
```

**Apollo Gen2 grounding (first person):** This is the "silent failures beat loud failures" principle in practice — a row past the watermark just disappears with no exception, so I never relied on the absence of errors to mean correctness; I watched `numRowsDroppedByWatermark` and treated late-drop as an observability WARN, the same way we classified freshness and schema-drift as warn-class rather than the PK/SCD2/CDC integrity gates we set to FAIL.

**One-liner:** Window length sets the aggregation granularity (and longer windows or sliding overlap cost more state and latency), while the watermark sets how long each window waits before finalizing — and any row arriving past `max_event_time − watermark` is silently dropped from the aggregate, observable only via the (imprecise, post-aggregation) `numRowsDroppedByWatermark` metric.

### Category 6 — SQL Implementation & Aggregations (Q28–Q31)

#### Q28 — Where complex SQL logic lives in SDP
**Question:** How do you implement complex SQL logic in DLT? Where exactly do you write the SQL logic in the DLT framework syntax? (DLT = SDP, Spark Declarative Pipelines / Lakeflow Declarative Pipelines)

**Core idea — the SQL goes in the `AS SELECT` body of a dataset definition.** SDP (Spark Declarative Pipelines) is declarative: you do **not** write imperative `INSERT`/`MERGE`. You declare a dataset (MV / streaming table / view) and put your logic in the query that defines it. The engine evaluates every definition across all source files, builds a dataflow graph, then orchestrates execution order itself.

**The places SQL logic can live (pick by purpose):**

| Object | SDP keyword / decorator | When to put logic here |
|---|---|---|
| MV (materialized view) | `CREATE OR REFRESH MATERIALIZED VIEW` / `@dp.materialized_view` | Complex transforms, joins, aggregations; results cached + (best-effort) incrementally refreshed on serverless; **batch-correct** |
| Streaming table | `CREATE OR REFRESH STREAMING TABLE` / `@dp.table` | Append-only / low-latency ingestion + row-level transforms; each row processed once |
| Temporary view | `CREATE TEMPORARY VIEW` / `@dp.temporary_view` | Pipeline-scoped intermediate step; **no storage cost**, not in catalog — ideal for breaking up big logic |
| Persisted view | `CREATE VIEW` (pipelines) | Standard view recomputed on read; usable only inside the defining pipeline (for cross-pipeline reuse, materialize as an MV) |

- The `STREAM` keyword in the `FROM` clause (`FROM STREAM(src)` or `FROM STREAM src`) marks a source as read with streaming semantics; omit it for batch (MV) semantics. **Do not** use `STREAM` when defining a materialized view.
- Data-quality logic is also "SQL logic" here — declared inline as a `CONSTRAINT <name> EXPECT (<expr>) ON VIOLATION DROP ROW | FAIL UPDATE`. (Note: an MV that carries an expectation can still be incrementally refreshed, with the exceptions documented for `DROP` expectations over `NOT NULL` columns.)
- Reference other pipeline datasets by name via `spark.read.table("name")` / `spark.readStream.table("name")`. The legacy `LIVE.` schema prefix and `dlt.read*` helpers still parse but are superseded — just reference by name.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

@dp.temporary_view()                          # intermediate logic, no storage
def orders_clean():
    return spark.read.table("orders_bronze").where("amount > 0")

@dp.materialized_view()                        # complex join/agg lands in an MV (batch read)
def orders_enriched():
    o = spark.read.table("orders_clean")
    c = spark.read.table("customers")
    return o.join(c, "customer_id").selectExpr(
        "customer_id", "state", "amount", "cast(order_ts as date) as order_date")
```

**SQL equivalent (SDP):**
```sql
CREATE TEMPORARY VIEW orders_clean AS
SELECT * FROM orders_bronze WHERE amount > 0;     -- batch read; this view feeds a batch MV

CREATE OR REFRESH MATERIALIZED VIEW orders_enriched (
  CONSTRAINT valid_amt EXPECT (amount > 0) ON VIOLATION DROP ROW
) AS
SELECT o.customer_id, c.state, o.amount, CAST(o.order_ts AS DATE) AS order_date
FROM orders_clean o JOIN customers c ON o.customer_id = c.customer_id;
```

**One-liner:** In SDP you never write procedural SQL — the logic goes in the `AS SELECT` body of a `CREATE OR REFRESH MATERIALIZED VIEW` (or streaming table / temporary view), and the engine wires up execution order from the dataflow graph.

#### Q29 — Running a 1000+ line SQL query inside SDP
**Question:** If you have a very large SQL query (1000+ lines) that needs to be applied to source data in DLT, how do you implement and execute this within the Spark context?

**Approach — decompose the monolith into a DAG of small datasets; do not paste one 1000-line query.** SDP is built to fan one huge query out into many named datasets and re-assemble them via the dataflow graph. This is faster (each node is independently optimized + parallelized), debuggable (you can inspect each node in the pipeline graph), and re-runnable (a transient failure retries at the most granular level — Spark task, then flow, then the whole pipeline — not the whole monolith).

**Decomposition recipe:**
- **Break CTEs / sub-queries into `CREATE TEMPORARY VIEW`s** — each former CTE becomes a named, pipeline-scoped view. Zero storage cost, not added to the catalog, and references resolve to the temp view inside the pipeline.
- **Promote heavy/reused stages to MVs** so they materialize once and are (best-effort) incrementally refreshed on serverless instead of recomputed.
- **Final result = one MV** that selects from the chain. SDP topologically sorts and parallelizes the whole graph automatically.
- **Multiple source files allowed:** SDP evaluates dataset definitions across *all* source files in the pipeline before running anything — so a 1000-line query can be split across several `.sql`/`.py` files for readability.
- **`SELECT`-order ≠ execution-order:** the order statements appear defines code-evaluation order only; the engine decides actual run order from dependencies.

**Two SDP-specific escape hatches when "SQL" alone can't express it:**
- **Python UDFs callable from SDP SQL** — define the UDF in a Python source file first, then call it in the SQL `SELECT`.
- **REPLACE WHERE flows (Beta, PREVIEW channel)** — declared via the inline `FLOW REPLACE WHERE <predicate> BY NAME` clause on a `CREATE STREAMING TABLE` (or `replace_where=` in Python). They recompute/overwrite only the predicate-matched slice of a streaming-table target — built for incremental *batch* processing of late-arriving data, selective reprocessing, and backfills without streaming semantics, not as a generic large-join helper.

```sql
-- file 1: stage the heavy sub-queries as temp views
CREATE TEMPORARY VIEW stg_a AS SELECT ... FROM STREAM(src_a) WHERE ...;   -- ~200 lines
CREATE TEMPORARY VIEW stg_b AS SELECT ... FROM src_b GROUP BY ...;        -- ~300 lines

-- file 2: assemble; engine parallelizes stg_a/stg_b, then builds the MV
CREATE OR REFRESH MATERIALIZED VIEW final_report AS
SELECT a.*, b.metric FROM stg_a a JOIN stg_b b USING (key);
```

```python
from pyspark import pipelines as dp

@dp.temporary_view()
def stg_a(): return spark.read.table("src_a").where("...")   # chunk 1

@dp.temporary_view()
def stg_b(): return spark.read.table("src_b").groupBy("key").sum("amount")  # chunk 2

@dp.materialized_view()
def final_report():
    return spark.read.table("stg_a").join(spark.read.table("stg_b"), "key")
```

**Apollo Gen2 first-person note:** I batch-generate ~200 entities' pipeline code from one Python script (generated code is an artifact, not the source of truth — I edit the config and regenerate). For wide entity logic I split definitions across files and lean on temporary views so the pipeline graph stays inspectable rather than one opaque query.

**One-liner:** I never run a 1000-line monolith in SDP — I decompose it into a DAG of named temporary views and MVs (optionally across multiple source files, with Python UDFs for the parts SQL can't express), and let the engine optimize, parallelize, and retry each node independently.

#### Q30 — Aggregations in SDP: which object type
**Question:** How can aggregations be performed in a DLT pipeline? When performing SQL-based aggregations in DLT, which object type should be used — a view, table (streaming table), or materialized view?

**Answer: use a materialized view (MV) for aggregations.** This is the Databricks-recommended default and the only object that returns a *batch-correct* result over the whole dataset.

**Object comparison for aggregation:**

| Object | Correct over whole dataset? | Cost behavior | Verdict |
|---|---|---|---|
| MV (materialized view) | **Yes — equivalent to a batch query** | Pre-computed; on serverless, best-effort incremental refresh reprocessing only changed data | ✅ **Recommended default** |
| Streaming table | Only with watermark + windowing; stateful, sees each row once | Incremental but **not** a full-dataset aggregate | ⚠️ Only for windowed/append-only streaming aggregates |
| `CREATE VIEW` | Correct but recomputes **from scratch on every query** | No caching → slow & expensive at scale | ❌ Not for heavy aggregation |

**Why MV is correct:** Databricks states a stateful streaming aggregate "should not be used to calculate statistics over an entire dataset" — use an MV. An MV guarantees a result *equivalent to recomputing the aggregate with a batch query*, even for late/out-of-order data. On serverless the engine makes a best-effort incremental refresh (reprocessing only changed data rather than the full result); whether a given aggregate query incrementalizes depends on the query — the engine reports the technique chosen (`GROUP_AGGREGATE`, `GENERIC_AGGREGATE`, `FULL_RECOMPUTE`, etc.) in the `planning_information` event log. On classic (non-serverless) compute an MV is always fully recomputed.

**MV aggregation gotchas (verified):**
- Non-column-reference expressions **require an alias**: `SUM(col2) AS sum_col2` is required; bare `SUM(col2)` is rejected. A plain column reference does not need an alias.
- `SUM` over a nullable column returns **0, not NULL**, when the last non-null value for a group is removed.
- MVs don't support `OPTIMIZE`/`VACUUM` (maintenance is automatic), identity/generated/default columns, or rename. `NOT NULL` must be specified explicitly alongside `PRIMARY KEY`.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import count, sum as _sum, max as _max

@dp.materialized_view()
def daily_orders_by_state():
    return (spark.read.table("orders_enriched")
              .groupBy("state", "order_date")
              .agg(count("*").alias("order_count"),
                   _sum("amount").alias("total_amt"),
                   _max("amount").alias("max_amt")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH MATERIALIZED VIEW daily_orders_by_state AS
SELECT state, order_date,
       COUNT(*)   AS order_count,
       SUM(amount) AS total_amt,
       MAX(amount) AS max_amt
FROM orders_enriched
GROUP BY state, order_date;
```

**One-liner:** Aggregations belong in a materialized view — it's the only SDP object that returns a batch-correct, full-dataset result while still refreshing incrementally on serverless; streaming tables only do windowed/watermarked aggregates and plain views recompute on every read.

#### Q31 — Full-dataset aggregation when the source feeds via auto-CDC
**Question:** When using streaming tables with auto-CDC for aggregation operations (MAX, MIN, COUNT, SUM), how do you ensure aggregation operations work on the complete dataset rather than just incremental records?

**Approach — separate the two layers: AUTO CDC builds the *current full state*, then aggregate that with a materialized view.** The trap is trying to aggregate inside the streaming/CDC layer, where a stateful streaming aggregate only ever sees the *incremental* batch and (without a watermark) builds unbounded state. The fix is architectural, not a flag.

**Why a streaming aggregate sees only increments:**
- A streaming table processes **each input row exactly once**; a stateful aggregate on it tracks state across micro-batches and emits per-batch deltas, not a full-dataset answer.
- Databricks is explicit: *"You should not use a stateful aggregate to calculate statistics over an entire dataset — use materialized views for incremental aggregate calculation on an entire dataset."*
- Without a `WATERMARK`, state grows unbounded → OOM; *with* a watermark you get correct **windowed** results but still not a single whole-dataset total.

**The correct two-layer pattern (this is what I run in Apollo Gen2):**

| Layer | SDP object | Role |
|---|---|---|
| Silver | streaming table + `dp.create_auto_cdc_flow` | AUTO CDC folds inserts/updates/deletes into the **current** SCD1/SCD2 state |
| Gold | **materialized view** | Aggregates over that full current state → `MAX/MIN/COUNT/SUM` are batch-correct and refresh incrementally on serverless |

- **SCD1 target:** the table holds one current row per key (no `__START_AT`/`__END_AT` columns) — the MV aggregates it directly.
- **SCD2 target:** filter to current rows first — `WHERE __END_AT IS NULL` — then aggregate, so you don't double-count historical versions. (SCD2 propagates the `sequence_by` values into the `__START_AT` / `__END_AT` columns.)
- An MV over the CDC target gives a result equivalent to a full batch recompute — that is the "complete dataset" guarantee — while best-effort incrementally refreshing on serverless.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp
from pyspark.sql.functions import sum as _sum, max as _max, count

# Silver: AUTO CDC -> current SCD2 state (NOT where you aggregate)
dp.create_streaming_table("orders_scd2")
dp.create_auto_cdc_flow(
    target="orders_scd2", source="orders_cdc",
    keys=["order_id"], sequence_by="op_ts",
    apply_as_deletes="op = 'DELETE'", stored_as_scd_type="2")

# Gold: MV aggregates the COMPLETE current dataset
@dp.materialized_view()
def orders_rollup():
    return (spark.read.table("orders_scd2")
              .where("__END_AT IS NULL")               # current rows only (SCD2)
              .groupBy("state")
              .agg(count("*").alias("cnt"),
                   _sum("amount").alias("total_amt"),
                   _max("amount").alias("max_amt")))
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE orders_scd2;

CREATE FLOW orders_cdc_flow AS AUTO CDC INTO orders_scd2
FROM STREAM(orders_cdc)
KEYS (order_id)
APPLY AS DELETE WHEN op = 'DELETE'
SEQUENCE BY op_ts
STORED AS SCD TYPE 2;

CREATE OR REFRESH MATERIALIZED VIEW orders_rollup AS
SELECT state, COUNT(*) AS cnt, SUM(amount) AS total_amt, MAX(amount) AS max_amt
FROM orders_scd2
WHERE __END_AT IS NULL          -- aggregate the complete CURRENT state, not CDC deltas
GROUP BY state;
```

**If you truly must aggregate in the streaming layer** (low-latency windowed roll-ups), it has to be a **windowed** aggregate with a watermark, and even then it answers per-window, not whole-dataset:
```sql
CREATE OR REFRESH STREAMING TABLE per_min_counts AS
SELECT window(event_time, '1 minute') AS w, state, COUNT(*) AS cnt
FROM STREAM(events) WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY w, state;   -- incremental only because of the watermark
```

**One-liner:** Let `create_auto_cdc_flow` build the current full state in a streaming table, then put `MAX/MIN/COUNT/SUM` in a materialized view over that table (filtering `__END_AT IS NULL` for SCD2) — the MV gives a batch-correct whole-dataset answer, whereas aggregating inside the CDC/streaming layer only ever sees the incremental batch.

### Category 7 — Data Quality & Constraints (Q32–Q35)

#### Q32 — Applying data quality expectations (types + where DQ errors surface)
**Question:** How do you apply data quality expectations? Explain in detail with types and where DQ errors can be checked.

**What an expectation is**
- An **expectation** is an optional clause on a SDP (Spark Declarative Pipelines / Lakeflow) dataset — `@dp.table` (streaming table), `@dp.materialized_view` (MV — a pre-computed query result), or `@dp.temporary_view` — that runs a **boolean SQL expression on every row** and reacts per a chosen violation policy.
- Unlike a Delta `CHECK` constraint (which hard-rejects writes), expectations are **flexible**: you choose warn / drop / fail.

**The three types (verified — current SDP API)**

| Action | Python | SQL | Behavior on a bad row |
|---|---|---|---|
| **warn** (default) | `@dp.expect` | `EXPECT (...)` | Bad row is still **written** to the target; only counted in metrics |
| **drop** | `@dp.expect_or_drop` | `EXPECT (...) ON VIOLATION DROP ROW` | Bad row dropped before write; drop count logged alongside other dataset metrics |
| **fail** | `@dp.expect_or_fail` | `EXPECT (...) ON VIOLATION FAIL UPDATE` | Update stops on the first bad row; if it's a table update the transaction is **atomically rolled back**; manual intervention required before reprocessing |

> Note: a fail affects only the offending flow — if a pipeline has multiple parallel flows, one flow failing does NOT fail the others (verified).

**Grouping (Python only):** `@dp.expect_all`, `@dp.expect_all_or_drop`, `@dp.expect_all_or_fail` take a dict `{name: constraint}` and apply one collective action — reusable across datasets. SQL allows multiple `CONSTRAINT` clauses but no collective grouping (verified).

**Constraint rules:** must be a valid SQL boolean expression evaluated per row.

**PySpark example**
```python
from pyspark import pipelines as dp

@dp.table
@dp.expect("valid_customer_age", "age BETWEEN 0 AND 120")            # warn
@dp.expect_or_drop("non_null_pk", "customer_id IS NOT NULL")        # drop
@dp.expect_or_fail("non_negative_price", "price >= 0")             # fail
def customers():
    return spark.readStream.table("catalog.raw.customers")
```

**SQL equivalent**
```sql
CREATE OR REFRESH STREAMING TABLE customers(
  CONSTRAINT valid_customer_age  EXPECT (age BETWEEN 0 AND 120),
  CONSTRAINT non_null_pk         EXPECT (customer_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT non_negative_price  EXPECT (price >= 0)              ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM(catalog.raw.customers);
```

**Where DQ errors / metrics can be checked**
- **Pipeline UI:** Jobs & Pipelines -> click the pipeline -> click the dataset -> **Data quality** tab (right sidebar). Shows tracking metrics for **warn** and **drop** only.
- **Event log (Delta table):** query `event_type = 'flow_progress'`; expectation metrics live under `details:flow_progress.data_quality.expectations` (per-expectation `name`, `dataset`, `passed_records`, `failed_records`), and the dropped-row count lives under `details:flow_progress.data_quality.dropped_records`. By default the event log is a hidden Delta table named `event_log_{pipeline_id}` in the pipeline's default catalog and schema, queried via the `event_log(<pipeline-id>)` table-valued function; only the pipeline's run-as user can query it by default.
- **Caveat:** **fail** does NOT record tracking metrics (the update fails on detection before metrics are recorded) — its evidence is the error message instead (see Q34).

**Apollo Gen2 (my experience):** Across 422 SDP pipelines (211 STG streaming tables + 211 BRZ SCD2), I split expectations by intent in my 17-case SIT suite — **FAIL = integrity gates** (PK present, SCD2 sequence valid, CDC keys), **WARN = observability** (freshness, schema drift). I warn-in-dev, then flip to fail-in-prod once the rule is trusted.

**One-liner:** Expectations are row-level boolean SQL checks on `@dp.table`/`@dp.materialized_view`/`@dp.temporary_view` with three policies — warn (default, keeps the row), drop (`expect_or_drop`), fail (`expect_or_fail`, atomic rollback of the failing flow) — and their pass/fail/drop metrics surface in the pipeline UI Data Quality tab (warn + drop only) and the `flow_progress` event-log `data_quality.expectations` object.

#### Q33 — Default handling of bad records in the source
**Question:** If bad records are present in the source, how does DLT handle them by default?

**Key clarification first**
- "DLT" = SDP (Spark Declarative Pipelines / Lakeflow); same engine, current name.
- "Default" splits into two distinct questions — **(a)** default with NO expectation, **(b)** default action of an expectation you declared.

**(a) No expectation declared**
- SDP does **no row-level validation**. A "bad" record (wrong value, malformed field) is treated as ordinary data and **written through** to the target. Garbage in -> garbage stored.
- Malformed-at-parse rows are a separate, ingestion-layer concern (e.g., Auto Loader's `_rescued_data` column / `rescuedDataColumn` mode), not an expectations concern.

**(b) Expectation declared but action unspecified -> warn (default)**

| | Default = warn |
|---|---|
| Row written to target? | **Yes** |
| Counted in metrics? | Yes — `failed_records` in event log + Data Quality tab |
| Pipeline fails? | No |

**Why warn is the default (DE principle):** silent-failure avoidance — SDP keeps the row and *makes the failure visible* rather than dropping data you might need. You opt **up** to drop/fail only where the rule is critical.

**PySpark — bad rows kept and counted**
```python
@dp.table
@dp.expect("valid_timestamp", "event_ts > '2012-01-01'")   # default warn: row stays, just flagged
def events():
    return spark.readStream.table("catalog.raw.events")
```

**SQL equivalent**
```sql
CREATE OR REFRESH STREAMING TABLE events(
  CONSTRAINT valid_timestamp EXPECT (event_ts > '2012-01-01')   -- no ON VIOLATION => warn
) AS SELECT * FROM STREAM(catalog.raw.events);
```

**Approach (how I'd answer the client's scenario framing):**
1. Confirm whether an expectation exists — if not, bad rows land unfiltered; the fix is to add an expectation, not to assume SDP filters.
2. If one exists with no `ON VIOLATION`, it is **warn** — rows are retained, so downstream tables inherit the bad data; check the Data Quality tab to size the problem.
3. Escalate the policy: `expect_or_drop` to keep the clean set flowing, or `expect_or_fail` for integrity-critical columns, or **quarantine** (two flows: drop from main, write rejects to a side streaming table) when I must preserve bad rows for investigation.

**One-liner:** With no expectation SDP writes bad source records straight through, and even a declared expectation defaults to **warn** — the bad row is still written and merely counted — so retention is the default and you must explicitly choose `expect_or_drop` or `expect_or_fail` to filter or fail.

#### Q34 — Tracing records when a fail-expectation isn't in the event log
**Question:** If an expectation is defined to fail on bad records but they don't appear in the event log, how can we trace or debug those records?

**Why they're not in the event log (the trap)**
- For `@dp.expect_or_fail` / `ON VIOLATION FAIL UPDATE`, the update **fails on the first violating row and (for a table update) atomically rolls back**. Because `fail` causes the update to fail when an invalid record is detected, SDP **does not record tracking metrics** for that action — verified. So querying `data_quality.expectations` in the event log returns nothing for that constraint. This is expected, not a bug.

**Where the evidence actually lives: the dedicated error message**
- Expectations configured to fail modify the **Spark query plan** of the transformation to track the information needed to detect and report violations, and SDP emits a dedicated structured error condition `EXPECTATION_VIOLATION` (`SQLSTATE 22000`). At full verbosity the message template is:
```console
[EXPECTATION_VIOLATION.VERBOSITY_ALL] Flow '<flowName>' failed to meet the expectation.
Violated expectations: '<expectationsViolated>'.
Input data: '<inputData>'.
Output record: '<outputRecord>'.
Missing input data: <missingInputData>
```
With a concrete row that resolves to, for example: `Violated expectations: 'temperature_in_valid_range'. Input data: '{"id":"TEMP_001","temperature":-500}'. Output record: '{"sensor_id":"TEMP_001","temperature":-500}'. Missing input data: false`. (Other verbosity levels exist: `VERBOSITY_NONE` and `VERBOSITY_OUTPUT`, which omits the input data.)
- Found in: the **failed update's error / event details** in the pipeline UI, and the corresponding `flow_progress` event with `status = FAILED` (one of the documented flow-progress statuses) — not in the `data_quality` metrics object.

**How to trace the full set (not just the first row)**
Convert the hard gate into a **counting/quarantine query** so every bad row is captured before any fail decision:

**PySpark — diagnostic MV that lists violators**
```python
@dp.materialized_view(name="bad_temperature_audit", comment="All rows that violate the temp rule")
def bad_temperature_audit():
    return (spark.read.table("sensor_raw")
            .where("NOT (temperature BETWEEN -50 AND 150)"))   # inverse of the failing predicate
```

**SQL — same audit, plus a quarantine split**
```sql
-- 1) Enumerate every violator (no fail, so it always completes and is queryable)
CREATE OR REFRESH MATERIALIZED VIEW bad_temperature_audit AS
SELECT * FROM sensor_raw WHERE NOT (temperature BETWEEN -50 AND 150);

-- 2) Quarantine pattern: drop bad from main, route bad rows to a side table
CREATE OR REFRESH STREAMING TABLE sensor_clean(
  CONSTRAINT temp_ok EXPECT (temperature BETWEEN -50 AND 150) ON VIOLATION DROP ROW
) AS SELECT * FROM STREAM(sensor_raw);

CREATE OR REFRESH STREAMING TABLE sensor_quarantine
AS SELECT * FROM STREAM(sensor_raw) WHERE NOT (temperature BETWEEN -50 AND 150);
```

**Approach (debug runbook I use):**
1. Read the failed update's `EXPECTATION_VIOLATION.VERBOSITY_ALL` message — it names the violated expectation and dumps the input + output record (the first offender SDP could attribute).
2. Don't expect `data_quality` metrics for a fail — query the event log only for `event_type='flow_progress' AND details:flow_progress.status='FAILED'` to find the flow, and read its `error` field.
3. Build the inverse-predicate audit MV / quarantine table to enumerate **all** violators, fix root cause, then re-run (fail requires manual intervention before reprocessing).

**Apollo Gen2 tie-in:** my hard FAIL gates (PK present, valid SCD2 sequence) are exactly the ones that produce no metrics on trip — so my SIT design always pairs a fail gate with a parallel warn/quarantine query, otherwise the failing row is invisible in the `data_quality` metrics.

**One-liner:** A fail expectation fails the update before tracking metrics are recorded, so the bad row never appears in the event-log `data_quality` object — you trace it via the `EXPECTATION_VIOLATION.VERBOSITY_ALL` error message (it dumps the offending input/output record) and enumerate the full set with an inverse-predicate audit MV or an `expect_or_drop` quarantine table.

#### Q35 — Ensuring column uniqueness in a Delta table (no enforced PK)
**Question:** How can you ensure uniqueness of a column in a Delta table? If Delta doesn't enforce primary keys by default, how can uniqueness be guaranteed?

**The core fact (verified)**
- On Databricks, table constraints are either **enforced** or **informational**. **Primary key and foreign key constraints are informational only and NOT enforced** — they aid the optimizer and document intent, but do **not** block duplicate inserts.
- The enforced constraints cover other things: **`NOT NULL`** (can only be enabled on an existing table if no current rows are null; blocks future null inserts) and **`CHECK`** (validated against existing and new rows). Neither enforces uniqueness.
- So uniqueness must be **guaranteed by your pipeline logic**, not by the table.

**Ways to guarantee uniqueness**

| Mechanism | Enforced? | Use |
|---|---|---|
| Informational `PRIMARY KEY` | No | Documents intent + optimizer hints only |
| SDP `expect_or_fail` on a dedup-count query | Yes (in pipeline) | Hard gate: fail update if any dup exists |
| `create_auto_cdc_flow` (AUTO CDC) `keys=[...]` | Yes (upsert) | De-dup by merging on key -> one row per key |
| Pre-write dedup (`dropDuplicates` / `ROW_NUMBER` window) | Yes (logic) | Collapse dups before write |
| `GENERATED ALWAYS AS IDENTITY` | Surrogate uniqueness | Unique `BIGINT` surrogate key (unique and incrementing, but **not guaranteed contiguous**; declaring it **disables concurrent transactions** on the table) |

**1. SDP expectation as a uniqueness gate (the canonical SDP answer)**

The official SDP PK-uniqueness pattern declares this on a temporary view (`@dp.view`) with `@dp.expect_or_fail`; an MV works too. Both are shown:
```python
@dp.view(name="report_pk_tests", comment="Validates primary key uniqueness")
@dp.expect_or_fail("unique_pk", "num_entries = 1")
def validate_pk_uniqueness():
    return (spark.read.table("report")
            .groupBy("pk").count()
            .withColumnRenamed("count", "num_entries"))
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW report_pk_tests(
  CONSTRAINT unique_pk EXPECT (num_entries = 1) ON VIOLATION FAIL UPDATE
) AS SELECT pk, count(*) AS num_entries FROM report GROUP BY pk;
```
Any `pk` with `num_entries > 1` trips the fail and rolls back the update.

**2. Guarantee one-row-per-key at write time via AUTO CDC (how I actually do it in BRZ)**
```python
dp.create_streaming_table("account_bronze")
dp.create_auto_cdc_flow(
    target="account_bronze",
    source="account_stg",
    keys=["accountid"],                      # uniqueness key — upsert collapses dups
    sequence_by="_processing_timestamp",     # latest wins on the key
    stored_as_scd_type=2,
    apply_as_deletes="_change_type = 'delete'",
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"]
)
```
```sql
CREATE OR REFRESH STREAMING TABLE account_bronze;
CREATE FLOW account_cdc AS AUTO CDC INTO account_bronze
FROM STREAM(account_stg)
KEYS (accountid)
SEQUENCE BY _processing_timestamp
STORED AS SCD TYPE 2;
```

**3. Pre-write dedup (when source itself has dups)**
```python
from pyspark.sql.window import Window
from pyspark.sql.functions import row_number, col

w = Window.partitionBy("accountid").orderBy(col("_processing_timestamp").desc())
deduped = src.withColumn("_rn", row_number().over(w)).where("_rn = 1").drop("_rn")
```

**Approach (what I'd tell the client):**
1. State plainly: Delta PKs are informational/not enforced — never rely on the declared `PRIMARY KEY` to stop duplicates.
2. For a streaming table fed by CDC, the **AUTO CDC `keys`** upsert already guarantees one row per key — that's my primary mechanism in Apollo Gen2 bronze.
3. Add an **`expect_or_fail` uniqueness gate** (`num_entries = 1` per key) as a SIT integrity check to *prove* uniqueness in tests.
4. Use `GENERATED ALWAYS AS IDENTITY` only for a synthetic surrogate, knowing it disables concurrent transactions and isn't guaranteed contiguous.

**Apollo Gen2 tie-in:** my hard incident here is **`sequence_by` on `file_modification_time` being too coarse** — when many rows share one CSV file, the CDC upsert can pick an arbitrary row on ties, silently violating per-key uniqueness intent. Fix: a real per-row sequence column, plus a `unique_pk` fail-gate in SIT to catch it.

**One-liner:** Delta PRIMARY KEY constraints are informational and not enforced, so uniqueness is guaranteed by the pipeline — `create_auto_cdc_flow` with `keys=[...]` upserts to one row per key, an `@dp.expect_or_fail("unique_pk", "num_entries = 1")` count check fails the update if any duplicate exists, and `GENERATED ALWAYS AS IDENTITY` supplies a unique (non-contiguous) surrogate when needed.

### Category 8 — Performance Optimization & Tuning (Q36–Q39)

#### Q36 — SDP-specific performance tuning techniques implemented
**Question:** What performance tuning techniques specific to DLT (SDP) have you implemented, excluding general techniques like broadcast joins and caching?

**Framing:** SDP (Spark Declarative Pipelines / Lakeflow Declarative Pipelines) is declarative — you do not hand-tune executors or shuffle stages the way you would in a raw Spark job. The pipeline-specific levers are about *how the dataflow graph is shaped, refreshed, and laid out*, not low-level Spark knobs.

**SDP-native techniques (the framework owns these):**
- **Right dataset type per layer.** `@dp.materialized_view` (MV — cached result, incrementally refreshed on serverless when possible, otherwise fully recomputed) vs `@dp.table` (streaming table — each record processed exactly once, assuming an append-only source). Picking streaming for incremental ingest avoids recomputing the whole table every run.
- **Incremental refresh for MVs.** On serverless, MVs attempt an incremental refresh (processing only upstream changes since the last update) and fall back to a full recompute when the query isn't incrementally supported or the compute is classic. Databricks runs a cost analysis and picks the cheaper of incremental vs full each update. Keeping aggregation queries simple and deterministic (no non-deterministic functions like `current_timestamp()`, no non-deterministic UDFs) is the single biggest cost lever — it keeps the refresh on the delta-only path instead of forcing `FULL_RECOMPUTE`.
- **Liquid clustering via `CLUSTER BY` / `CLUSTER BY AUTO`** instead of `PARTITIONED BY` — self-tuning, skew-resistant data layout (see Q39).
- **Enhanced autoscaling + vertical autoscaling (serverless).** Horizontal (worker count) + vertical (cost-efficient instance type chosen to avoid OOM). Standard performance mode for cost-tolerant triggered batch (fewer DBUs, typically 4–6 min startup) vs performance-optimized (faster startup) for latency-sensitive work.
- **Avoid small files.** Match trigger interval to data volume; over-frequent triggers on low-volume sources spray tiny files and degrade reads (each file is a separate metadata lookup + I/O round trip).
- **`track_history_except_column_list` in `create_auto_cdc_flow`.** Not "performance" in the shuffle sense, but it prevents *false SCD2 versions* — if an operational-metadata column changes every run and isn't excluded from history tracking, it generates a new history row each run, exploding table size and slowing reads.
- **Predictive optimization** automatically runs `OPTIMIZE`, `VACUUM`, and `ANALYZE` on Unity Catalog managed tables (including SDP streaming tables and MVs) — I rely on it rather than scheduling manual maintenance.

**From Apollo Gen2 (first person):** Across 211 entities / 422 pipelines (211 STG streaming tables + 211 BRZ SCD2), my biggest SDP-specific wins were: (1) STG as streaming tables (`@dp.table`) so each source file is ingested incrementally rather than reprocessing the full entity each run; (2) BRZ SCD2 via `create_auto_cdc_flow` with a correct `track_history_except_column_list` listing every operational column (`_processing_timestamp`, `_source_file_path`, etc.) so re-runs did not generate phantom SCD2 versions and bloat the history; (3) full-load entities via `create_auto_cdc_from_snapshot_flow` to avoid re-streaming static snapshots.

```python
from pyspark import pipelines as dp

# Streaming table for incremental STG ingest (process each file once)
@dp.table(name="stg_account", cluster_by=["accountid"])
def stg_account():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .load("/Volumes/apollo/incoming/account/"))

dp.create_streaming_table(name="brz_account")
dp.create_auto_cdc_flow(
    target="brz_account",
    source="stg_account",
    keys=["accountid"],
    sequence_by="SinkModifiedOn",
    stored_as_scd_type=2,
    apply_as_deletes="_is_delete = true",
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
CREATE OR REFRESH STREAMING TABLE stg_account CLUSTER BY (accountid)
AS SELECT * FROM STREAM read_files('/Volumes/apollo/incoming/account/', format => 'csv');

CREATE OR REFRESH STREAMING TABLE brz_account;
CREATE FLOW brz_account_cdc AS AUTO CDC INTO brz_account
FROM STREAM(stg_account)
KEYS (accountid)
APPLY AS DELETE WHEN _is_delete = true
SEQUENCE BY SinkModifiedOn
STORED AS SCD TYPE 2
TRACK HISTORY ON * EXCEPT (_processing_timestamp, _source_file_path);
```

**One-liner:** "In SDP my tuning is declarative — pick streaming-table vs materialized-view per layer, keep MV queries simple and deterministic so they stay on the incremental-refresh path, lay out with `CLUSTER BY AUTO`, and set `track_history_except_column_list` correctly so SCD2 doesn't explode — then let predictive optimization handle OPTIMIZE/VACUUM/ANALYZE."

#### Q37 — Are deletion vectors enabled by default in SDP?
**Question:** Do you need to manually enable deletion vectors in DLT (SDP), or are they enabled by default?

**Definition:** Deletion vectors (DV) are a Delta storage optimization. Instead of rewriting a whole Parquet file when a few rows change, `DELETE`/`UPDATE`/`MERGE` mark rows as soft-deleted in a side file; reads skip them. Faster writes, slightly slower reads (extra metadata check on scan).

**The honest answer — it depends on the workspace setting, not on SDP itself:**
- DV is a **Delta table property** (`delta.enableDeletionVectors`). SDP tables are Delta tables, so they inherit whatever the workspace default produces at create time. As of the 2025-06-26 release, new SDP streaming tables and materialized views follow the workspace deletion-vectors setting.
- The relevant control is the workspace admin setting **Auto-Enable Deletion Vectors** (applies to SQL warehouses + DBR 14.0+). Options: **Default** (varies by region), **New UC managed and Databricks SQL tables** (explicitly includes new MVs and streaming tables), **All new tables**, **Disabled**.
- Databricks is rolling this out so that, once complete, **Default** flips from **Disabled** → **All new tables**. Workspaces still in the introductory period have **Default** behaving as **Disabled**.

| Question | Answer |
|---|---|
| Is DV always on for SDP tables? | No — depends on the workspace **Auto-Enable Deletion Vectors** setting |
| Can SDP/UC managed tables get it automatically? | Yes, if admin picks "New UC managed and Databricks SQL tables" or "All new tables" |
| Can I force it per table? | At create time via `TBLPROPERTIES ('delta.enableDeletionVectors' = true)`. Note: you **cannot** `ALTER` a streaming table or MV to add/remove DV — set it at creation. |
| Delta protocol needed | Reader v3 / Writer v7 (older external readers break) |

**Important interview nuance (don't overstate):** Don't claim "DV is on by default in DLT/SDP." The correct statement is **DV is controlled by a workspace-level Delta default, not by the pipeline engine** — so you verify the workspace setting, and if you need it guaranteed (e.g., GDPR deletes on bronze), you set the table property explicitly at creation.

```python
from pyspark import pipelines as dp

@dp.table(
    name="brz_patient",
    table_properties={"delta.enableDeletionVectors": "true"},
)
def brz_patient():
    return spark.readStream.table("stg_patient")
```
```sql
CREATE OR REFRESH STREAMING TABLE brz_patient
TBLPROPERTIES ('delta.enableDeletionVectors' = true)
AS SELECT * FROM STREAM(stg_patient);
```

**Cleanup behavior to mention:** With DV on, `OPTIMIZE` automatically purges files where more than 5% of records are referenced by deletion vectors — so routine maintenance (predictive optimization on SDP) handles most cleanup. For hard physical removal below that 5% threshold (e.g., GDPR), run `REORG TABLE ... APPLY (PURGE)` then `VACUUM`.

**One-liner:** "Deletion vectors aren't an SDP feature — they're a Delta property governed by the workspace 'Auto-Enable Deletion Vectors' admin setting, and as of mid-2025 new SDP streaming tables and MVs follow it, so I verify that setting and, where I need them guaranteed, set `delta.enableDeletionVectors=true` in the table's `table_properties` at creation (you can't ALTER it on afterward)."

#### Q38 — Configuring tuning parameters for a slow/failing join in SDP
**Question:** If a join in DLT (SDP) is taking too long or failing, how can you configure performance tuning parameters within the pipeline?

**Approach (diagnose → choose the right scope → apply):**

**1. Diagnose first.** A join that is slow/failing is almost always (a) a shuffle of a large side that should be broadcast, (b) **data skew** — a few hot keys land on a few tasks (heavy tail in the Spark UI; big gap between median and max task time), or (c) OOM from too-coarse partitioning.

**2. SDP gives you THREE scopes to set Spark properties — pick the narrowest that fixes it:**

| Scope | Where | Use when |
|---|---|---|
| Per dataset/flow | `spark_conf={...}` in the decorator (`@dp.table`, `@dp.materialized_view`) | Only this join needs the tweak — preferred, least blast radius |
| Per compute resource | pipeline JSON `clusters[].spark_conf` | Classic compute, applies to that cluster |
| Whole pipeline | pipeline settings → Advanced → Spark config (`configuration` map in pipeline JSON) | Pipeline-wide default |

**3. Concrete levers (Databricks AQE current defaults — verified):**
- **AQE is ON by default** (`spark.databricks.optimizer.adaptive.enabled=true`) — it already coalesces partitions, flips sort-merge → broadcast at runtime, and does skew-join handling. So first confirm it wasn't disabled.
- **Broadcast a small dimension** with a hint — this is the documented SDP join fix for the dimension-join case (not a "general technique" exclusion).
- **Skew:** AQE skew handling is automatic (split + replicate skewed tasks when a partition exceeds the median × `spark.sql.adaptive.skewJoin.skewedPartitionFactor`, default 5); for severe in-flight skew, **salt** the hot key (append a random bucket suffix, aggregate in two stages). Use **liquid clustering** for skew in the *stored* table.
- **Shuffle partitions:** `spark.sql.shuffle.partitions` defaults to `auto` on serverless (auto-optimized shuffle) and `200` on classic — raise for large joins, lower to avoid tiny-file/overhead on small ones. (Note: for stateful streaming this cannot change across restarts from the same checkpoint.)
- **`spark.databricks.adaptive.autoBroadcastJoinThreshold`** (the Databricks AQE runtime threshold) default `30MB` — raise it so AQE auto-broadcasts a slightly larger dimension at runtime. (Distinct from the static planner threshold `spark.sql.autoBroadcastJoinThreshold`, default `10MB`.)
- **Serverless caveat:** serverless pipelines/notebooks only allow a *restricted* set of Spark properties; cluster-shape properties like `spark.master`, `spark.driver.host`, `spark.jars` aren't settable. Vertical autoscaling already picks bigger instances to dodge OOM.

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import broadcast

@dp.materialized_view(
    name="enriched_orders",
    spark_conf={
        "spark.sql.shuffle.partitions": "auto",
        "spark.databricks.adaptive.autoBroadcastJoinThreshold": "100MB",
    },
)
def enriched_orders():
    orders = spark.read.table("orders")
    products = spark.read.table("products")          # small dimension
    return orders.join(broadcast(products), "product_id")
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW enriched_orders AS
SELECT /*+ BROADCAST(p) */ o.*, p.product_name, p.category
FROM orders o JOIN products p ON o.product_id = p.product_id;
```
Pipeline-wide JSON equivalent (under `configuration`):
```json
{ "configuration": { "spark.sql.shuffle.partitions": "auto" } }
```

**One-liner:** "Set Spark properties at the narrowest scope — `spark_conf` in the dataset decorator for just that join — broadcast the small side, lean on AQE's on-by-default skew-join + auto-shuffle, salt or cluster a genuinely skewed key, and remember serverless only allows a restricted Spark-conf set."

#### Q39 — Why choose liquid clustering at specific medallion layers
**Question:** Why would you choose optimization techniques such as liquid clustering at certain layers of the medallion architecture?

**Definition:** Liquid clustering (LC) replaces static `PARTITIONED BY` and `ZORDER`. It's self-tuning, skew-resistant, and incremental — it only rewrites the data that needs reorganizing, and you can change clustering keys anytime *without rewriting the whole table*. `CLUSTER BY (cols)` picks keys yourself; `CLUSTER BY AUTO` lets Databricks pick/adapt keys from the observed query workload (requires predictive optimization; intelligent key selection relies on metadata from DBR 15.4 LTS+; supported for MVs and streaming tables in SDP — GA for SDP since 2025-08-25). LC and `PARTITIONED BY` are mutually exclusive.

**Why layer choice matters (the real answer: cluster where reads happen on predictable keys, skip where they don't):**

| Layer | Access pattern | LC decision |
|---|---|---|
| **Bronze (raw/SCD2)** | Append-heavy, ingest-ordered, rarely point-queried by business keys | Often skip explicit LC, or `CLUSTER BY` the CDC/business key if downstream merges filter on it. Don't over-invest. |
| **Silver (cleaned/conformed)** | Joins + merges on business keys; this is where data skew bites | **Strong LC candidate** — cluster by the high-cardinality join/merge key(s) to kill shuffle skew and speed CDC merges |
| **Gold (aggregates/serving)** | Filtered/grouped by a few well-known BI dimensions (date, region, customer) | **Best LC payoff** — cluster by the columns analysts filter on for maximum data-skipping |

**Approach / reasoning:**
- LC's value is **data skipping** — files are organized so a filtered query reads fewer files. That only pays off where queries *filter or join on predictable keys*, i.e. silver/gold, not raw bronze landing.
- LC is **skew-resistant** where static partitioning isn't: partitioning by an uneven column (e.g. country) creates giant/tiny partitions; LC self-balances. So at silver, where a CDC merge keys on an uneven business key, LC beats partitioning. (Databricks docs explicitly recommend LC to handle skew in stored tables.)
- LC is **incremental + re-keyable**: as gold query patterns evolve, change keys without a full rewrite — critical for long-lived serving tables.
- **`CLUSTER BY AUTO`** is Databricks' recommended default: let predictive optimization observe the workload and pick keys, especially at gold where query patterns shift. (Note: AUTO may decline to select keys for tables that are too small, already well-ordered, or infrequently queried — it's cost-aware.)

**From Apollo Gen2 (first person):** My STG and BRZ SCD2 tables are bronze-tier and ingest-ordered, so I cluster only on the CDC business key where a downstream layer merges on it. The bigger LC payoff would be at the silver/serving layer Novartis builds on top (CRM entities filtered by account/territory) — there I'd use `CLUSTER BY AUTO` so data skipping tracks how analysts actually slice the data, rather than guessing partition columns up front.

```python
from pyspark import pipelines as dp

# Silver: cluster by the merge/join key to fight skew
@dp.table(name="slv_account", cluster_by=["accountid", "modifiedon"])
def slv_account():
    return spark.readStream.table("brz_account")

# Gold: let Databricks adapt keys to BI query patterns
@dp.materialized_view(name="gold_account_summary", cluster_by_auto=True)
def gold_account_summary():
    return spark.read.table("slv_account").groupBy("territoryid").count()
```
```sql
CREATE OR REFRESH STREAMING TABLE slv_account CLUSTER BY (accountid, modifiedon)
AS SELECT * FROM STREAM(brz_account);

CREATE OR REFRESH MATERIALIZED VIEW gold_account_summary CLUSTER BY AUTO
AS SELECT territoryid, COUNT(*) FROM slv_account GROUP BY territoryid;
```

**One-liner:** "I apply liquid clustering where reads filter or join on predictable keys — `CLUSTER BY` the merge key at silver to beat CDC skew and `CLUSTER BY AUTO` at gold so data-skipping adapts to BI query patterns — and skip it at append-ordered bronze where there's no read pattern to optimize."

### Category 9 — Unity Catalog & Security (Q40–Q42)

#### Q40 — Unity Catalog and its role in SDP pipelines
**Question:** What is Unity Catalog and how is it used in DLT (SDP / Lakeflow Declarative Pipelines) pipelines?

**What UC (Unity Catalog) is:**
- UC = Databricks' central **governance layer** for data + AI across all workspaces in a metastore. One place for access control, lineage, audit, and discovery.
- **Three-level namespace:** `catalog.schema.table` (replaces the old two-level Hive `database.table`).
- Governs more than tables: schemas, **views, materialized views, streaming tables**, volumes (files), functions/UDFs, models, external locations, storage credentials, connections.
- Securables form a hierarchy; privileges **inherit** downward (grant `SELECT` on a schema → applies to all current + future tables in it).

**How SDP uses UC (current default):**
- For pipelines created on/after **2025-02-05**, UC is the **default** publishing target (and the new pipeline default is also **serverless compute + Unity Catalog + Current channel**). Pick a **default catalog** + **default schema** at pipeline config time.
- The pipeline **publishes every `@dp.table` (streaming table) and `@dp.materialized_view` (MV)** into the configured catalog.schema. They become real UC-governed objects, queryable from SQL warehouses, notebooks, other pipelines.
- **Legacy contrast (one clause):** the old `LIVE` virtual schema (legacy publishing mode, pre-2025-02-05 pipelines) is no longer used in the default publishing mode — the `LIVE` keyword is now **silently ignored**; unqualified identifiers resolve to the current schema and you publish to a concrete `catalog.schema`.
- **Three-tier identifier resolution:** unqualified names resolve to the pipeline's default catalog/schema; fully-qualify (`main.stores.regional_sales`) to write/read across catalogs. `USE CATALOG` / `USE SCHEMA` set the scope inside a source file.

**Required privileges for the identity that runs a UC SDP pipeline (verified — these are the pipeline owner / run-as identity's UC grants):**

| Privilege | On | Why |
|---|---|---|
| `USE CATALOG` | target catalog | enter the catalog |
| `USE SCHEMA` | target schema | enter the schema |
| `CREATE TABLE` | target schema | create streaming tables (`@dp.table`) |
| `CREATE MATERIALIZED VIEW` | target schema | create MVs (`@dp.materialized_view`) |
| `MODIFY` | existing tables the pipeline updates | write into tables it doesn't create |
| `CREATE SCHEMA` | catalog | only if the pipeline creates new schemas |

`CREATE TABLE` and `CREATE MATERIALIZED VIEW` are distinct UC privileges — both are grantable at schema or catalog level, and the combined grant syntax is `GRANT CREATE { MATERIALIZED VIEW | TABLE } ON SCHEMA …`.

**Compute requirement:** UC-enabled pipelines run on either **serverless** (the recommended default for new pipelines — serverless pipelines always use UC) or **classic** compute. On classic compute, UC requires **standard** or **dedicated** access mode (the legacy "shared"/"single-user" names) — pipelines manage their own cluster lifecycle, so you don't set the access mode the way you would for a notebook cluster. The standard-vs-dedicated distinction matters mainly when *querying* pipeline-created ST/MV from outside the pipeline: a non-owner on dedicated compute needs DBR 15.4+ and a serverless-enabled workspace.

**Cross-catalog write (PySpark):**
```python
from pyspark import pipelines as dp

@dp.materialized_view(name="main.stores.regional_sales")
def regional_sales():
    return spark.read.table("apollo.silver.partners")
```
```sql
CREATE OR REFRESH MATERIALIZED VIEW main.stores.regional_sales
  AS SELECT * FROM apollo.silver.partners;
```

**Apollo Gen2 (first person):** All 422 of my SDP pipelines publish into UC. Each entity lands as a `<catalog>.<schema>.STG_<entity>` streaming table plus a `BRZ_<entity>` SCD2 (Slowly Changing Dimension type 2) bronze table. UC gives me one governed lineage graph from `incoming/` Auto Loader ingest → STG → BRZ, plus consistent GRANTs so analysts query bronze without touching my raw ADLS landing zone.

**One-liner:** Unity Catalog is Databricks' central catalog.schema.table governance layer, and in SDP it's the default publish target — every streaming table and materialized view becomes a UC-governed object with inherited privileges, lineage, and audit, replacing the legacy `LIVE` schema.

#### Q41 — Handling and resolving access issues in SDP pipelines
**Question:** How do you handle and resolve access-related issues in DLT (SDP)?

**First, the two identities involved (verified):**
- **Pipeline run identity** = the **pipeline owner / run-as user**. The update reads sources, creates tables, and writes data **as that identity**, not as whoever clicked Run. Databricks recommends setting a **service principal** as owner/run-as so prod doesn't break when a person leaves. (Owner ≠ run-as can diverge: changing **Run as** to a service principal reassigns the executing identity.)
- **Caller identity** = whoever runs/edits the pipeline. Needs a pipeline **ACL**: `CAN VIEW`, `CAN RUN`, `CAN MANAGE`, or `IS OWNER`. Running an update requires `CAN RUN`, `CAN MANAGE`, or `IS OWNER`. Managing permissions requires `CAN MANAGE` or `IS OWNER`.

**The common access failures and fixes:**

| Symptom | Root cause | Fix |
|---|---|---|
| Pipeline update fails creating ST/MV | run-as identity lacks `CREATE TABLE` / `CREATE MATERIALIZED VIEW` + `USE SCHEMA`/`USE CATALOG` on target | GRANT the create + use privileges to the owner/SP |
| Update fails writing an existing table | run-as identity lacks `MODIFY` on a table it updates but didn't create | `GRANT MODIFY` on that table to the owner/SP |
| "dataset does not exist" on a source read | run-as identity lacks `SELECT` (or `USE CATALOG`/`USE SCHEMA`) on the upstream — UC reports "not found" instead of "denied" | grant read chain: `USE CATALOG` + `USE SCHEMA` + `SELECT` |
| Analyst can't query the published table | by default **only the pipeline owner** can query pipeline-created ST/MV | `GRANT SELECT` to the consumer group |
| Auto Loader can't read landing zone | run-as identity lacks `READ FILES` on the UC **external location** / volume | grant `READ FILES` on the external location |
| `UNITY_CATALOG_INITIALIZATION_FAILED` | UC misconfig — required catalog/schema missing or not accessible, or the cluster lacks UC access; often a storage-credential / RBAC gap behind it | verify catalog + schema exist and are reachable; fix the storage credential's RBAC (e.g. **Storage Blob Data Contributor** on the ADLS account) |
| Non-admin can't see driver logs to debug | by default only the owner + workspace admins see driver logs | set pipeline config `spark.databricks.acl.needAdminPermissionToViewLogs=false` to let any `CAN VIEW` / `CAN RUN` / `CAN MANAGE` user view the driver logs |
| `PIPELINE_PERMISSION_DENIED_NOT_OWNER` mid-operation | an operation (e.g. refresh of a pipeline-managed table) requires ownership | run as / own the pipeline with a stable SP; don't depend on a personal account |

**The full read chain to remember:** to read one table a principal needs **`USE CATALOG` (parent catalog) + `USE SCHEMA` (parent schema) + `SELECT` (table)** — all three. Missing any one surfaces as "does not exist," which is the #1 misdiagnosed access bug.

**Resolution code:**
```sql
-- let owner/SP create + write bronze
GRANT USE CATALOG ON CATALOG apollo TO `apollo_sp`;
GRANT USE SCHEMA ON SCHEMA apollo.bronze TO `apollo_sp`;
GRANT CREATE { MATERIALIZED VIEW | TABLE } ON SCHEMA apollo.bronze TO `apollo_sp`;
-- write tables it updates but didn't create
GRANT MODIFY ON TABLE apollo.bronze.BRZ_account TO `apollo_sp`;

-- expose published bronze to analysts (default = owner-only)
GRANT SELECT ON TABLE apollo.bronze.BRZ_account TO `analysts`;
REVOKE SELECT ON TABLE apollo.bronze.BRZ_account FROM `intern@novartis.com`;

-- read the ADLS landing zone via external location
GRANT READ FILES ON EXTERNAL LOCATION incoming_zone TO `apollo_sp`;
```
```python
# diagnostic: confirm the read chain from a notebook before blaming the pipeline
spark.sql("SHOW GRANTS `apollo_sp` ON TABLE apollo.silver.partners").show()
```

**Approach (how I triage in production):**
1. **Identify which identity failed** — pipeline run-as identity (write/create) or caller (run/edit). Read the error class: `*_PERMISSION_DENIED` / "does not exist" → run-as read/write grant; `PIPELINE_PERMISSION_DENIED_NOT_OWNER` → ownership; greyed-out ACL dialog → caller `CAN MANAGE`.
2. **Walk the read chain top-down** — `USE CATALOG` → `USE SCHEMA` → `SELECT`/`CREATE`/`MODIFY`. Verify with `SHOW GRANTS`.
3. **Check the storage layer** — for ingest failures it's almost always the external location `READ FILES` grant or the storage-credential managed-identity RBAC role, not the table grant.
4. **Prefer least-privilege group grants over user grants**, and run/own the pipeline with a **service principal** so access doesn't depend on a person.

**Apollo Gen2 (first person):** My pipelines run as a service principal, so a UC SDP run never depends on my personal account. The recurring access ticket was analysts not seeing bronze — expected, since pipeline tables default to owner-only; I fixed it once with a schema-level `GRANT SELECT ... TO analysts` so inheritance covered all BRZ tables in that schema going forward instead of granting table-by-table.

**One-liner:** Access issues in SDP are almost always a missing link in the `USE CATALOG` → `USE SCHEMA` → `SELECT`/`CREATE`/`MODIFY` chain or a storage-credential RBAC gap — I run the pipeline as a service principal, diagnose with `SHOW GRANTS`, and fix at the schema level so privilege inheritance covers all tables.

#### Q42 — What to restrict vs. expose in an SDP implementation
**Question:** What information should be restricted or hidden vs. what information should be exposed or revealed in a DLT (SDP) implementation?

**Principle:** publish the **governed, curated layer**; restrict **raw landing data, credentials, and PII**. Lean on UC privilege inheritance, **row filters / column masks / dynamic views / ABAC policies**, and Databricks **secret scopes** — never hardcode.

**Restrict / hide:**

| Restrict | Mechanism |
|---|---|
| Storage credentials, SAS tokens, connection strings | **Databricks secret scopes** + `dbutils.secrets.get(...)`; never in source/notebook params |
| Raw ADLS landing zone (`replicate/`, `incoming/`) | don't grant `READ FILES` to consumers; only the pipeline SP gets it |
| Bronze/raw + operational metadata internals | publish to a **restricted schema**; don't `GRANT SELECT` to broad groups |
| PII columns (patient/HCP identifiers in pharma) | **column masks** or **dynamic views** gated on `is_account_group_member()` |
| Sensitive rows (per-region, per-cohort) | **row filters** (table-level `SET ROW FILTER`) or **ABAC row-filter policies** for cross-table scale |
| Pipeline ACLs to non-operators | keep `CAN MANAGE` / `IS OWNER` to the platform team |

**Expose / reveal:**

| Expose | How |
|---|---|
| Curated silver/gold ST + MV | `GRANT SELECT` to consumer groups (schema-level for inheritance) |
| **Data lineage** | automatic in Catalog Explorer — column-level (DBR 13.3 LTS+ for SDP column lineage), links back to the pipeline; viewers need `BROWSE` on the catalog plus `CAN VIEW` on the pipeline to see the pipeline link. Reveal it (aids trust + impact analysis) |
| Data-quality expectation results | `@dp.expect` metrics in the pipeline event log / quality dashboards — expose to data stewards |
| Schema + table metadata, tags, descriptions | UC discovery / `BROWSE` privilege so consumers find data without reading it |

**Column mask via dynamic view (verified — `is_account_group_member` is account-level and Databricks-recommended over the workspace-level `is_member`):**
```sql
CREATE VIEW apollo.gold.contact_redacted AS
SELECT
  contact_id,
  CASE WHEN is_account_group_member('hcp_auditors') THEN email
       ELSE regexp_extract(email, '^.*@(.*)$', 1) END AS email,
  country, segment
FROM apollo.silver.contact;
```
```python
# credentials NEVER hardcoded — pulled from a secret scope
sas = dbutils.secrets.get(scope="apollo", key="adls_sas")
```

**Approach (governance design I'd defend):**
1. **Tiered schemas:** `bronze` (SP-only) → `silver`/`gold` (analysts). Restriction is the **default** (pipeline tables are owner-only until granted), so exposure is a deliberate `GRANT`.
2. **PII via FGAC, not separate tables:** row filters / column masks / dynamic views keep one table but mask per-group — avoids duplicate "redacted" copies drifting out of sync. Reach for **ABAC tag-based policies** when the rule must apply consistently across many tables (they attach at catalog/schema level on governed tags). Note: serverless or DBR 16.4+ is required for ABAC-secured tables, and dynamic views require a SQL warehouse / standard / dedicated (DBR 15.4+) compute.
3. **Secret scopes for every credential**; the storage-credential managed identity is the only thing that touches ADLS.
4. **Expose lineage + DQ openly** — transparency about *quality and provenance* builds trust; secrecy is reserved for *credentials and PII*.

**Apollo Gen2 (first person):** Bronze SCD2 tables carry operational metadata (`_processing_timestamp`, `_source_file_path`) that's internal plumbing — I never expose those to analysts; consumers get curated downstream views. Synapse Link credentials live in a secret scope, never in the preprocessing notebook. For Novartis pharma data, HCP/patient identifiers would be masked with dynamic views or column masks gated on an auditors group, so the same governed table serves both privileged and non-privileged readers.

**One-liner:** Restrict credentials (secret scopes), raw landing data, and PII (row filters / column masks / dynamic views / ABAC), but openly expose curated silver/gold tables, lineage, and data-quality metrics — in SDP the default is owner-only, so every exposure is a deliberate least-privilege `GRANT`.

### Category 10–11 — Schema Evolution, Monitoring & Troubleshooting (Q43–Q45)

#### Q43 — Schema evolution when a column is added; evolution modes
**Question:** How do you handle schema evolution when an additional column is added? What types of schema evolution modes are available?

**Where this lives in SDP:** Schema evolution is owned by the **connector** (Auto Loader / `read_files`) at the bronze ingest, *not* by the SDP table. The streaming table (`@dp.table`) just persists whatever the connector hands it. Auto Loader keeps a **schema location** (a `_schemas` directory). Inside SDP you don't set it — SDP manages both the schema location and the streaming checkpoint automatically; these are internal pipeline-managed directories, *separate* from the event log. On each micro-batch Auto Loader merges newly seen columns to the **end** of the inferred schema (initial inference samples the first 50 GB or 1000 files, whichever comes first).

**Mechanism on a new column (default `addNewColumns`):**
- Auto Loader detects the new field and throws `UnknownFieldException` → the **stream stops** (a controlled hard-stop, not data loss).
- Before throwing, it has already written the widened schema to the schema location.
- In an SDP **job/continuous** pipeline this triggers **automatic retry/restart**; the next attempt resumes with the new column populated. Rows read *before* the evolution carry `NULL` for the new column. Existing column **data types never change** under `addNewColumns`.

**`cloudFiles.schemaEvolutionMode` values (verified, current docs):**

| Mode | Behavior on a new column |
|---|---|
| `addNewColumns` **(default when NO schema is provided)** | Stream fails with `UnknownFieldException`, column appended to schema, restart resumes. Existing types unchanged. |
| `addNewColumnsWithTypeWidening` | Same as above **plus** widens supported types (`int`→`long`, `float`→`double`). Unsupported changes (`int`→`string`) go to rescued data. Public Preview, DBR 16.4+. |
| `rescue` | Schema **never** evolves, stream **never** fails; all unmatched columns land in `_rescued_data`. |
| `failOnNewColumns` | Stream fails and **will not restart** until you update the provided schema / schema hint or remove the offending file. |
| `none` | Schema not evolved, new columns **silently ignored** (lost unless `rescuedDataColumn` is set). No failure. |

**Critical non-obvious default (call it out — this is a silent trap):** `addNewColumns` is the default **only when you do NOT provide a schema**. The moment you pass an explicit schema, the default flips to **`none`** — meaning new source columns are silently dropped. In fact `addNewColumns` is *not allowed* with an explicit fixed schema; to still evolve you must pass your schema as a **schema hint** (`cloudFiles.schemaHints`), not a fixed `.schema(...)`. This is exactly the kind of "silent failure" I design against.

**PySpark (SDP):**
```python
from pyspark import pipelines as dp

@dp.table(name="stg_account", comment="Bronze ingest with addNewColumns evolution")
def stg_account():
    return (
        spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")  # explicit, even though default
            .option("rescuedDataColumn", "_rescued_data")               # catch type-mismatched values
            .load("/mnt/incoming/account/")
    )
```

**SQL equivalent (SDP):**
```sql
CREATE OR REFRESH STREAMING TABLE stg_account AS
SELECT * FROM STREAM read_files(
  '/mnt/incoming/account/',
  format        => 'csv',
  schemaEvolutionMode => 'addNewColumns',
  rescuedDataColumn   => '_rescued_data'
);
```

**Apollo Gen2 grounding (first person):** On my Novartis project the upstream is **Dynamics 365 → Synapse Link → ADLS**, and `schemaEvolutionMode = addNewColumns` is exactly the behavior I rely on: it only **adds** columns — it never removes, renames, or retypes. The trap I document for my team is the asymmetry: when D365 *adds* a CRM attribute, Auto Loader picks it up and old rows get `NULL`; but when a source column is *removed* upstream, the column does **not** disappear from the streaming table — new rows just land `NULL` for it (the docs call this a "soft delete"). I also keep `_rescued_data` on so a type drift (e.g. a US-format `SinkModifiedOn` that fails `to_timestamp()`) is captured rather than dropped. For the bronze SCD2 layer, when a new column appears mid-stream I must remember to add it to `track_history_except_column_list` if it is operational metadata, otherwise every backfill row spawns a false SCD2 version.

**One-liner:** Auto Loader's `addNewColumns` (the default only when no schema is supplied — it flips to `none`, and is disallowed outright, the instant you give a fixed schema) appends new columns and hard-stops the stream so the SDP job auto-restarts with the widened schema, never altering existing column types.

#### Q44 — Event logs, checkpoints, and retry mechanisms in SDP
**Question:** Explain event logs, checkpoints, and retry mechanisms in DLT.

*(DLT = SDP / Lakeflow Declarative Pipelines; answered in SDP terms.)*

**1. Event log — the observability backbone**
- Every SDP pipeline auto-writes a structured **Delta table** capturing: audit logs, **data-quality (expectation) results**, pipeline progress, **data lineage**, and resource/error detail. Always on; you don't enable it.
- **Default location (current default publishing mode):** a *hidden* Delta table in the pipeline's default catalog/schema named `event_log_{pipeline_id}` (the system UUID with dashes → underscores). It appears in `system.information_schema.tables` but is **not** visible in Catalog Explorer; by default only the pipeline's **run-as user** can query it. You can optionally *publish* it to a named catalog/schema/table via the pipeline's `event_log` advanced setting.
- **Query it** via the `event_log()` TVF (table-valued function) by pipeline ID, then wrap in a view. The TVF must run on a **shared cluster or SQL warehouse**, can be called only by the pipeline/table owner, and the resulting view can't be shared with other users:
```sql
CREATE VIEW event_log_raw AS SELECT * FROM event_log('<pipeline-id>');
```
- Key `event_type` values to know: `flow_progress` (rows in/out, backlog, **data_quality.expectations** pass/fail/dropped), `flow_definition` (lineage: `input_datasets` → `output_dataset`), `update_progress` (run state), `operation_progress` (snapshot %/listing progress), `autoscale` / `cluster_resources` (classic compute only). `level` ∈ INFO / WARN / ERROR / METRICS.

```sql
-- Expectation (data-quality) metrics for the latest update
SELECT e.dataset, e.name,
       SUM(e.passed_records) AS passed,
       SUM(e.failed_records) AS failed
FROM (
  SELECT explode(from_json(
    details:flow_progress:data_quality:expectations,
    'array<struct<name:string,dataset:string,passed_records:int,failed_records:int>>')) e
  FROM event_log_raw WHERE event_type = 'flow_progress'
) GROUP BY e.dataset, e.name;
```
- **Do not delete** the event log or its parent catalog/schema — future updates fail (`EVENT_LOG_TABLE_DELTA_MISSING_DATA_FILES` class).

**2. Checkpoints — fault tolerance for streaming tables**
- A checkpoint persists **(a) source offsets processed, (b) intermediate state** for stateful ops (aggregations, dedupe, `flatMapGroupsWithState`), and **(c) query metadata**. For Auto Loader the file-discovery state lives in a RocksDB key-value store inside that checkpoint. This is what gives **exactly-once** processing (offsets + idempotent Delta sink) and lets a failed run **resume from the last committed batch** instead of reprocessing from zero.
- In SDP, checkpoints are **fully managed and internal** — one checkpoint per **flow** writing to a streaming table; you don't set a `checkpointLocation`. The `flow_id` in the event log is your handle: as long as `flow_id` is stable, the flow is refreshing **incrementally**; it changes on a full refresh / checkpoint reset.
- **When checkpoints break:** changing a **stateful operator** (adding/removing `dropDuplicates()`, changing aggregation keys, adding/removing a union source) causes a hard failure like `Streaming stateful operator name does not match ... in state metadata` (SQLSTATE 42K03). Recovery options:

| Recovery | Data loss | Cost | When |
|---|---|---|---|
| **Full refresh** | Possible (if source files gone) | Medium | Simplest; also lets you change code |
| **Full refresh + backup/backfill** | None | High | Last resort, must preserve data |
| **Reset table checkpoint** + resume incrementally (`startingVersion` / `startingTimestamp`) | None (if done carefully) | Low | Must keep existing data, continue incrementally |

**3. Retry / restart — how SDP self-heals**
SDP retries transient failures from the most granular unit outward: **Spark task → flow → entire pipeline update**. Whether automatic restart kicks in depends on **how the update is triggered**, not on table type:

| Trigger | Behavior |
|---|---|
| **UI "Run now" / ad-hoc / Validate** | Fast-start, debug mode: **retries DISABLED** (fail fast), cluster reused (default 2 h via `pipelines.clusterShutdown.delay`) |
| **Jobs / Pipelines API / continuous** | **Automatic retry + restart**: restarts cluster on recoverable errors (memory leak, stale creds), retries on cluster-start failures, cluster shuts down right after run |

Verified retry defaults (pipeline properties):
- `pipelines.maxFlowRetryAttempts` — **default 2 retries** → a retryable flow runs **3 times total** (original + 2) before the update fails.
- `pipelines.numUpdateRetryAttempts` — retries the **whole update** as a full update; default **5 for triggered**, **unlimited for continuous**; applies only to automatic-retry pipelines (never for ad-hoc/Validate).
- Continuous serverless pipelines additionally **recover automatically from failures** and keep running until manually stopped.

**Apollo Gen2 grounding (first person):** My 422 SDP pipelines run as **jobs chained via `depends_on`** (preprocessing notebook JOB1 → SDP JOB2), so they're squarely in the automatic-retry path — a transient cluster-start blip self-heals without me touching it, while a genuine integrity failure surfaces after the bounded retries instead of looping forever. I lean on the event log heavily for SIT: my 17 SIT cases read `flow_progress.data_quality.expectations` to assert PK/SCD2/CDC integrity gates (FAIL) and freshness/schema-drift observability (WARN). The one checkpoint scar I carry is **streaming-on-mutable-source**: a streaming table needs an append-only source; when an upstream was mutable the flow failed on the change commit, and the fix was either making the source append-only, setting `skipChangeCommits` on the read, or switching to a snapshot/MV pattern — not fighting the checkpoint.

**One-liner:** The event log is an always-on hidden Delta table (`event_log_{pipeline_id}`) queried via `event_log('<id>')` on a warehouse/shared cluster for lineage, quality and progress; checkpoints are SDP-managed per-flow offset+state stores giving exactly-once resume; and retries escalate task→flow→update, automatic only for job/API/continuous runs (2 flow retries → 3 attempts; 5 update retries triggered, unlimited continuous), while UI "Run now" disables them so you fail fast.

#### Q45 — Production issues faced during SDP pipeline execution and resolution
**Question:** What production issues have you faced during pipeline execution using DLT, and how did you resolve them?

*(DLT = SDP; answered in SDP terms, first person from Apollo Gen2 — Dynamics 365 → Synapse Link → ADLS → SDP, 211 entities, 422 pipelines.)*

**Approach (how I triage any SDP failure):**
1. Read the **event log** `flow_progress` / `update_progress` for the failing `flow_name` and error class.
2. Classify: **integrity gate** (PK/SCD2/CDC) vs **observability** (freshness/schema drift) vs **framework limit**.
3. Apply the smallest fix that preserves data (prefer checkpoint reset / config + regenerate over full refresh).

**The incidents I can name, with resolution:**

| # | Incident | Root cause | Resolution |
|---|---|---|---|
| 1 | **SCD2-on-SCD2** | Source was *already* SCD2; I ran `create_auto_cdc_flow` on top → double-historized garbage | Stopped running CDC on an already-SCD2 source. Either **collapse to current-only** or **preserve history via direct column mapping** (map the source's history columns straight through) instead of re-deriving SCD2. |
| 2 | **Streaming-on-mutable-source** | A `@dp.table` (streaming table) needs an **append-only** source; the upstream was mutable (in-place updates) → the stream failed on the change commit | Set `skipChangeCommits` on the read to ignore non-append commits, switched the feed to an append-only landing, or moved that entity to a **snapshot** pattern (`create_auto_cdc_from_snapshot_flow`) / MV. A streaming table can't propagate updates/deletes from a mutable source. |
| 3 | **Coarse `sequence_by`** | `sequence_by = file_modification_time` — multiple rows shared one file, so on ties CDC picked an **arbitrary** winner | Replaced with a **real per-row** ordering key (true event/sequence timestamp); for tie-breaks I use a `struct(...)` of (event_time, id) so `create_auto_cdc_flow` orders deterministically. |
| 4 | **False SCD2 versions on every re-run** | Operational-metadata columns (`_processing_timestamp`, `_source_file_path`) changed every run, so SCD2 saw a "new version" each time | Added every operational-metadata column to **`track_history_except_column_list`** so they're ignored for change detection. |
| 5 | **Phantom empty column (full-load CSVs)** | Synapse full-load CSVs carry **trailing commas** → an extra empty column; headerless CSVs got mis-aligned headers | In JOB1 preprocessing: if `col_count == expected + 1`, **drop the trailing phantom column**; add headers from `model.json`/`schemas.json`. |
| 6 | **US-format timestamps** | `SinkCreatedOn`/`SinkModifiedOn` are Synapse metadata in **US date format**; naive cast misread day/month | Explicit `to_timestamp(col, 'M/d/yyyy h:mm:ss a')` in preprocessing before the SDP layer; kept `_rescued_data` on to catch stragglers. |
| 7 | **Path/folder quirks** | Case-sensitive ADLS paths + folder names with **stray spaces** caused "path not found" | Normalized paths and `.strip()` on folder names in JOB1. |
| 8 | **"SDP can't run dbutils.fs"** | SDP pipeline code forbids arbitrary file ops / `dbutils.fs` inside the declarative graph | This is *why* I run the **two-job pattern**: preprocessing is a separate single-node notebook JOB1 chained via `depends_on` to the SDP JOB2 — different compute, independent failure domains, and SDP only ever sees clean per-entity files. |

**Cross-cutting principle I applied:** *design around the framework's limits, don't fight them.* The two-job split, the snapshot-vs-CDC choice, and `track_history_except_column_list` are all "work with SDP's contract" decisions. And the generated SDP code is an **artifact, not source-of-truth** — I edit the config and **regenerate** all 211 entities from one script rather than hand-patching 422 pipelines.

**One-liner:** My worst production failures were all "wrong source shape for the chosen flow" — SCD2-on-SCD2, streaming-on-a-mutable-source, and tie-breaking on a coarse `sequence_by` — and I resolved each by matching the flow type to the source contract (collapse/preserve, append-only/`skipChangeCommits` or snapshot CDC, real per-row ordering) plus the two-job pattern that keeps arbitrary file ops out of SDP entirely.

### Category 12–13 — Strategic Decisions & Practical Experience (Q46–Q50)

#### Q46 — Benefits of migrating an existing PySpark pipeline to SDP
**Question:** What are the benefits of migrating an existing PySpark pipeline to Delta Live Tables (now Spark Declarative Pipelines / Lakeflow)?

**Naming note:** "DLT" was renamed to **Lakeflow Spark Declarative Pipelines (SDP)** (2025). The Python module is `from pyspark import pipelines as dp` (it was previously `dlt`). I answer in SDP terms.

**What you give up writing by hand (the core win)**
SDP replaces hundreds of lines of imperative PySpark + Structured Streaming + `MERGE` orchestration with a few declarative decorators. You declare *what* each dataset is; the engine figures out *how* and *in what order* to build it.

| Hand-rolled PySpark you delete | SDP replacement |
|---|---|
| `foreachBatch` + `MERGE INTO` for CDC, manual out-of-order/dedup logic | `dp.create_auto_cdc_flow(...)` (AUTO CDC) — SCD1/SCD2 declaratively |
| Manual checkpoint dirs, `writeStream` plumbing per table | `@dp.table` (streaming table) manages checkpoints/state |
| Custom DAG / `depends_on` between transforms | Auto dataflow-graph + parallelization from `spark.readStream.table(...)` references |
| `if df.filter(bad).count() > 0: raise` data-quality guards | `@dp.expect_or_drop` / `@dp.expect_or_fail` |
| Bespoke retry/backoff wrappers | Built-in retry: Spark task → flow → pipeline |

**Concrete benefits (verified against current Lakeflow docs)**
- **Automatic orchestration:** SDP evaluates all dataset definitions, builds the dependency graph, runs flows in correct order with automatic parallelization, and retries transient failures granularly (task → flow → pipeline) — no manual `depends_on`.
- **Declarative CDC:** AUTO CDC handles out-of-order events, dedup, and SCD2 history without you knowing watermark internals.
- **Incremental processing for free:** Write a materialized view (MV) with batch semantics; on a serverless pipeline the engine attempts to incrementally refresh only changed upstream rows instead of full recompute. (On classic compute, MVs are always fully recomputed — see Q49.)
- **Built-in data quality + lineage:** Expectations emit pass/fail/drop metrics to the event log (for `warn` and `drop`; `fail` aborts and records no metrics); lineage and the dataflow graph come automatically.
- **Unity Catalog managed tables + auto maintenance:** streaming tables and MVs are UC-managed Delta tables; pipelines run `OPTIMIZE`/`VACUUM` on a predictive-optimization cadence.

**PySpark before → SDP after**
```python
# BEFORE: imperative structured streaming + manual merge
def upsert(batch_df, _):
    batch_df.createOrReplaceTempView("u")
    spark.sql("MERGE INTO bronze t USING u s ON t.id=s.id WHEN MATCHED ...")
(spark.readStream.format("cloudFiles").load(path)
   .writeStream.foreachBatch(upsert).option("checkpointLocation", ckpt).start())
```
```python
# AFTER: SDP
from pyspark import pipelines as dp

dp.create_streaming_table("bronze")

dp.create_auto_cdc_flow(
    target="bronze", source="stg_account",
    keys=["accountid"], sequence_by="_seq",
    stored_as_scd_type=2,
    track_history_except_column_list=["_processing_timestamp", "_source_file_path"],
)
```
```sql
-- SQL equivalent
CREATE OR REFRESH STREAMING TABLE bronze;
CREATE FLOW apply_cdc AS AUTO CDC INTO bronze
  FROM STREAM(stg_account)
  KEYS (accountid) SEQUENCE BY _seq STORED AS SCD TYPE 2;
```

**From my Apollo Gen2 experience:** Migrating to SDP is exactly why I could batch-generate **422 pipelines (211 STG streaming tables + 211 BRZ SCD2 tables)** from one config-driven script. Each entity is `@dp.table` + `create_auto_cdc_flow`; I never wrote a single `MERGE` or checkpoint path. Edit config, regenerate — generated code is an artifact, not source-of-truth.

**One-liner:** Migrating to SDP collapses hand-written streaming, MERGE-based CDC, DAG wiring, and quality checks into declarative decorators with automatic orchestration, incremental MV refresh on serverless, granular retries, and built-in lineage and data-quality metrics.

#### Q47 — When to prefer SDP over hand-written Structured Streaming
**Question:** When would you prefer using DLT (SDP) over a traditional Structured Streaming solution?

**Decision rule:** Prefer **SDP** when you want a *managed, declarative, multi-table medallion pipeline*; keep **raw Structured Streaming** when you need a *single low-level stream with custom operators SDP doesn't expose*.

**Prefer SDP when**
- You have **many interdependent tables** (bronze → silver → gold) and want auto-orchestration + lineage instead of wiring `depends_on` yourself.
- You need **SCD1/SCD2 CDC** — AUTO CDC (`create_auto_cdc_flow`) handles ordering/dedup/deletes; doing this in raw streaming means `foreachBatch` + `MERGE` + manual out-of-order handling.
- You want **declarative data quality** via `@dp.expect*` with event-log metrics.
- You want **incremental MVs** for aggregations/joins (batch semantics, engine incrementalizes on serverless).
- You want **managed checkpoints, enhanced autoscaling, and granular retries** without ops code.

**Prefer raw Structured Streaming when**
- You need operators **not supported** in SDP real-time mode: `flatMapGroupsWithState`, `mapPartitions`, arbitrary `foreachBatch`/`foreach`, stream-stream joins in real-time mode, or custom sinks beyond the `dp.create_sink` set.
- You need a **single stream** with bespoke trigger control (`Trigger.AvailableNow`, custom processing-time) and full control of the `writeStream` lifecycle.
- You need to do **arbitrary Python / file ops** (`dbutils.fs`, REST calls) with side effects in the same job — SDP forbids side-effecting Python in dataset-definition functions.

| Need | Choose |
|---|---|
| Medallion ETL, multiple tables, lineage | SDP |
| SCD2 CDC from a change feed | SDP (AUTO CDC) |
| Incremental aggregations/joins for BI | SDP (MV) |
| Custom stateful op (`flatMapGroupsWithState`) | Structured Streaming |
| Arbitrary file/Python orchestration | Plain notebook/job |

**Approach (how I'd frame it in Apollo Gen2):** My pipeline is fundamentally medallion CDC at scale — 211 entities, SCD2 history, quality gates. That's the SDP sweet spot. But preprocessing (reading headerless CSVs, attaching headers from `model.json`, splitting per-entity, `dbutils.fs` operations) is **arbitrary side-effecting Python that SDP won't run in a dataset definition**, so I keep it as a separate notebook JOB1 chained via `depends_on` to the SDP JOB2. So my real answer is *both*: a Structured-Streaming-style notebook for the messy I/O prep, SDP for the declarative medallion core.

**One-liner:** I reach for SDP whenever the workload is a multi-table medallion pipeline with CDC and quality gates; I drop to raw Structured Streaming only for custom stateful operators or arbitrary-Python I/O that SDP won't run.

#### Q48 — Main challenges of implementing SDP instead of building with PySpark
**Question:** What are the main challenges you face when implementing DLT (SDP) instead of building solutions with PySpark?

**The trade:** SDP buys you orchestration and incremental engines, but charges you in **flexibility and debuggability**. You design *around* the framework's guardrails.

**Challenges (each grounded in something I hit)**
- **No arbitrary side-effecting Python in dataset definitions.** SDP dataset functions can't run `dbutils.fs`, arbitrary file moves, or REST calls with side effects. In Apollo Gen2 this forced the **two-job pattern**: a preprocessing notebook (JOB1) chained by `depends_on` to the SDP pipeline (JOB2). Reasons: (1) SDP forbids side-effecting Python in dataset definitions; (2) different compute — single-node notebook vs autoscaling SDP; (3) independent failure domains.
- **Declarative graph, not procedural control.** SDP evaluates *all* dataset definitions and builds the dataflow graph before running. Source order = code-evaluation order, **not** execution order. You can't `print`/step through a `writeStream` lifecycle; you reason about the graph.
- **Full refresh is the blunt tool for logic changes.** A streaming table sees each row once; if you change query logic (e.g., add `UPPER()`), only new rows reflect it. Reprocessing history needs a **full refresh**, which on a short-retention source can lose data.
- **CDC config footguns.** `create_auto_cdc_flow` needs `track_history_except_column_list` to list **every** operational-metadata column (`_processing_timestamp`, `_source_file_path`, etc.), or every re-run creates a false SCD2 version. `sequence_by` must have true per-row granularity — `file_modification_time` is too coarse and CDC picks arbitrarily on ties. (Note: `stored_as_scd_type` defaults to **1**, so SCD2 must be set explicitly.)
- **Source-shape assumptions break streaming tables.** A streaming table needs an **append-only / naturally-bounded** source; a mutable upstream (records changed or deleted) throws an error under streaming read. And running CDC on an **already-SCD2** source (SCD2-on-SCD2) doubles history — you must collapse to current-only or map columns directly.
- **Incremental MV is serverless-only and fragile to query shape.** Incremental refresh only runs on serverless pipelines; on classic compute the MV is **always fully recomputed**. Non-deterministic functions (except temporal functions in `WHERE`), unsupported sources (volumes, external locations, foreign catalogs, foreign Iceberg), recursive CTEs, etc., fall back to full recompute (cost spike).
- **Generated-code volume + governance.** 422 pipelines is a lot of artifact; you must treat generated code as artifact, not source-of-truth (edit config + regenerate).

**Approach to mitigate (what I actually do):**
```python
# Guardrail: every operational column listed so SCD2 doesn't false-version
dp.create_auto_cdc_flow(
    target="brz_account", source="stg_account",
    keys=["accountid"], sequence_by="SinkModifiedOn",   # real per-row timestamp, not file mtime
    apply_as_deletes=expr("_change_type = 'delete'"),
    stored_as_scd_type=2,                                # explicit; default is SCD type 1
    track_history_except_column_list=[
        "_processing_timestamp", "_source_file_path", "_ingest_date",
    ],
)
```

**One-liner:** The main challenges are that SDP forbids side-effecting Python in dataset definitions (forcing my two-job pattern), replaces step-through debugging with declarative-graph reasoning, makes logic changes require full refreshes, and has CDC/streaming footguns I design around — listing every metadata column, setting SCD type explicitly, using real per-row sequence keys, and never running CDC on a mutable or already-SCD2 source.

#### Q49 — Limitations of SDP, streaming tables, materialized views, and expectations
**Question:** What are the limitations of DLT (SDP), streaming tables, materialized views, and expectations?

**Naming note:** "Live Tables vs Live Streaming Tables" in legacy DLT maps to **materialized view (MV)** vs **streaming table** in SDP. (`CREATE OR REFRESH LIVE TABLE` is deprecated in favor of `CREATE OR REFRESH MATERIALIZED VIEW`.) I answer in SDP terms. All limits below verified against current Lakeflow docs.

**Pipeline-level (SDP) limits**
- Workspace cap of **1000 concurrent pipeline updates**.
- Source-file limits: if the config references *only* individual files/notebooks, the limit is **100 source files** per pipeline; if it includes folders, you can have up to **50 source entries** (files or folders) indirectly referencing up to **1000 files**.
- A dataset can be **defined only once** (target of a single owning operation across all pipelines) — *exception:* a streaming table can take multiple append flows (`@dp.append_flow`).
- MVs/streaming tables published from a pipeline are accessible only to Azure Databricks clients/applications; to expose externally, use the sink API (`dp.create_sink`).
- `PIVOT` / the `pivot()` function is **not supported** (it requires eager schema inference).
- Delta time-travel works on streaming tables but **not** on MVs; Iceberg reads (UniForm) can't be enabled on either.

**Streaming table limits**
- **Append-only / naturally-bounded source required** — state is bounded by watermarks; an unbounded/mutable source grows state without bound (OOM risk), and reading a source whose existing records change/delete throws an error (use `SkipChangeCommits` to tolerate).
- **Limited evolution:** each row is seen once; changing the query only affects rows processed *after* the change — reprocessing history needs a **full refresh**.
- **Joins don't recompute:** when a dimension changes, an already-emitted joined row is *not* recomputed ("fast-but-wrong"). For always-correct joins use an MV.
- **Stream-stream join** needs watermarks on **both** sides + a time-bound condition; omit either and state grows unbounded. Late/out-of-order data beyond the watermark is dropped, not auto-corrected.
- Identity columns are **not supported** on tables that are AUTO CDC targets.

**Materialized view limits**
- **Not low-latency** — refresh is seconds-to-minutes, not milliseconds.
- **Incremental refresh runs only on serverless pipelines**; MVs not on serverless are **always fully recomputed**. Even on serverless, the engine cost-compares and may still choose full recompute.
- Not all queries incrementalize: recursive CTEs (`WITH RECURSIVE`), most non-deterministic functions (temporal ones like `current_timestamp()` allowed in `WHERE`), and unsupported sources (volumes, external locations, foreign catalogs, foreign Iceberg) → **full recompute fallback**.
- Some operators (joins, filters, window functions, `UNION ALL`, etc.) require **row tracking** enabled on source tables to incrementalize.
- UDF behavior changes may not be detected → you must full-refresh manually.

**Expectations limits**
- Three actions: **warn (default, `expect` / `EXPECT`)** writes the bad row to the target and logs metrics, **drop** (`expect_or_drop` / `ON VIOLATION DROP ROW`), **fail** (`expect_or_fail` / `ON VIOLATION FAIL UPDATE`).
- `fail` records **no quality metrics** (it aborts the flow and rolls back the transaction); a single flow failure does **not** fail sibling parallel flows.
- Expectations are **row-level boolean checks only** — no native cross-row/quarantine routing; quarantine needs a manual two-flow pattern.
- Supported only on streaming tables, MVs, and (temporary) views; **not** on sinks, and **not** with `AUTO CDC FROM SNAPSHOT`. (Constraints `WHERE`-checks can't reference subqueries on other tables, custom Python functions, or external service calls.)
- Only **Python** can group expectations (`expect_all` / `expect_all_or_drop` / `expect_all_or_fail`); SQL can't specify collective actions.

```python
# warn vs drop vs fail
@dp.table
@dp.expect("recent_ts", "ts > '2012-01-01'")                 # warn (default): row kept, metric logged
@dp.expect_or_drop("has_pk", "accountid IS NOT NULL")        # drop: bad row removed, drop count logged
@dp.expect_or_fail("positive_amt", "amount > 0")             # fail: aborts flow + rollback, no metric
def silver(): return spark.readStream.table("bronze")
```
```sql
CREATE OR REFRESH STREAMING TABLE silver(
  CONSTRAINT recent_ts    EXPECT (ts > '2012-01-01'),
  CONSTRAINT has_pk       EXPECT (accountid IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_amt EXPECT (amount > 0)            ON VIOLATION FAIL UPDATE
) AS SELECT * FROM STREAM(bronze);
```

**From Apollo Gen2:** My **17-case SIT** is built precisely around these limits — FAIL on integrity gates (PK, SCD2, CDC correctness), WARN on observability (freshness, schema drift), warn-in-dev then fail-in-prod, and explicit tests for *silent* failures. The clearest silent case: a column **removed** upstream lands NULL in subsequent rows with no error (mode-independent). By contrast, a brand-**new** source column under the Auto Loader default `cloudFiles.schemaEvolutionMode=addNewColumns` does the opposite — it halts the stream with `UnknownFieldException` until the pipeline restarts with the merged schema. My SIT tests both: the loud new-column halt and the silent removed-column NULL.

**One-liner:** SDP caps concurrency and source files; streaming tables need append-only sources and don't recompute joins; MVs aren't low-latency and only incrementally refresh on serverless with supported query shapes; and expectations are row-level warn/drop/fail checks that lose metrics on fail, can't group in SQL, and don't work with `AUTO CDC FROM SNAPSHOT` or on sinks.

#### Q50 — Rating my practical SDP experience; can I handle these challenges independently?
**Question:** Based on real-time challenges (stream joins with high watermark ranges, aggregation challenges with streaming tables), how would you rate your practical DLT (SDP) experience? Can you handle these challenges independently in a production environment?

**Self-rating:** Solid production-level on declarative CDC and medallion design; competent and improving on heavy stateful streaming (wide-watermark stream-stream joins, large-window aggregations). **Yes — I handle these independently in prod**, with the discipline of verifying against current docs before committing a state-changing design.

**Stream-stream joins with high watermark ranges**
- **Mechanism:** A stream-stream join needs a watermark on **both** sides plus a **time-bound** join condition; the interval tells the engine when no further match is possible so it can evict state. Wide watermark ranges = larger retained state = OOM/latency risk. (Stream-stream joins emit in append mode only; outer joins require watermarks.)
- **How I handle it:** Set the watermark to the *minimum* lateness the business tolerates (state cost scales with the range); enforce a time-bound predicate; and where late dimensions must retroactively apply, switch the join to an **MV** (which recomputes joins when dimensions change) instead of a streaming table (which doesn't).
```python
@dp.table
def impressions_with_clicks():
    imp = spark.readStream.table("impressions").withWatermark("imp_time", "3 minutes")
    clk = spark.readStream.table("clicks").withWatermark("click_time", "3 minutes")
    return imp.join(clk,
        expr("""imp_id = click_imp_id AND
                click_time BETWEEN imp_time AND imp_time + INTERVAL 3 MINUTES"""))
```
```sql
-- WATERMARK is a clause on each relation (WATERMARK <col> DELAY OF INTERVAL ...),
-- placed after the relation and before the table alias.
CREATE OR REFRESH STREAMING TABLE impressions_with_clicks AS
SELECT i.*, c.click_time
FROM STREAM(impressions) WATERMARK imp_time DELAY OF INTERVAL 3 MINUTES AS i
JOIN STREAM(clicks)      WATERMARK click_time DELAY OF INTERVAL 3 MINUTES AS c
  ON i.imp_id = c.click_imp_id
 AND c.click_time BETWEEN i.imp_time AND i.imp_time + INTERVAL 3 MINUTES;
```

**Aggregation challenges with streaming tables**
- **Mechanism:** Streaming aggregations *must* have a watermark or state grows unbounded; the docs are explicit that without a watermark the aggregation is **fully recomputed on each update** rather than incrementally maintained. Changing aggregation columns or the watermark invalidates state → requires **full refresh**.
- **How I handle it:** Use a windowed aggregation + watermark for incremental, bounded state; keep group cardinality limited; for complex/late-correct aggregations move to an **MV** (incremental refresh on serverless), or use a `REPLACE WHERE` flow for targeted incremental-batch recompute of joins/aggregations — noting `FLOW REPLACE WHERE ... BY NAME` is currently **Beta** and requires the Pipelines Preview channel.
```python
@dp.table
def event_counts():
    return (spark.readStream.table("events_raw")
            .withWatermark("event_time", "3 minutes")
            .groupBy(window("event_time", "1 minute"), "region").count())
```
```sql
-- WATERMARK clause sits after the relation, before GROUP BY.
CREATE OR REFRESH STREAMING TABLE event_counts AS
SELECT window(event_time, '1 minute') AS time_window, region, COUNT(*) AS cnt
FROM STREAM(events_raw)
  WATERMARK event_time DELAY OF INTERVAL 3 MINUTES
GROUP BY time_window, region;
```

**Evidence I can do this independently (Apollo Gen2, first person):**
- I built and operate **422 SDP pipelines** (211 STG streaming tables + 211 BRZ SCD2 tables) for 211 Dynamics 365 entities, batch-generated from one config script.
- I diagnosed and fixed real incidents: **SCD2-on-SCD2** (collapsed to current-only instead of CDC-on-CDC), **streaming-on-mutable-source** (rebuilt the source as append-only), and **`sequence_by` on `file_modification_time` ties** (moved to a real per-row timestamp).
- I own a **17-case SIT** that separates integrity FAIL gates from observability WARN gates and explicitly tests silent failures.
- I work around framework limits structurally (the **two-job pattern** for arbitrary-Python prep) and treat generated code as artifact.

**Honest gap:** My highest-volume work is CDC/SCD2 ingestion, not multi-day-watermark analytics joins. For those I lean on the documented contract (watermark on both sides + time-bound condition, MV when correctness on late dimensions matters) and **verify defaults against current Databricks docs** before shipping — I don't trust memory on state-changing behavior.

**One-liner:** I rate myself production-ready — I run 422 SDP pipelines and have debugged real SCD2, mutable-source, and sequencing incidents; I handle wide-watermark stream-stream joins and streaming aggregations independently by bounding state with watermarks plus time-bound conditions and escalating to materialized views when late-arriving correctness matters.

## System Design (Data)

*(No entries yet — Q11–Q13 pending.)*

---

## Distributed Systems Theory

*(No entries yet — Q14–Q16 pending.)*

---

## Coding

*(No entries yet — Q17–Q18 pending.)*

---

## Behavioral (STAR)

*(No entries yet — Q19–Q20 pending.)*
