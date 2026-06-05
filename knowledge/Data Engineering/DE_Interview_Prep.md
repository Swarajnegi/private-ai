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
4. [System Design (Data)](#system-design-data)
5. [Distributed Systems Theory](#distributed-systems-theory)
6. [Coding](#coding)
7. [Behavioral (STAR)](#behavioral-star)

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
