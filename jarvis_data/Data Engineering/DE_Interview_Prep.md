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
3. [System Design (Data)](#system-design-data)
4. [Distributed Systems Theory](#distributed-systems-theory)
5. [Coding](#coding)
6. [Behavioral (STAR)](#behavioral-star)

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

## Streaming Semantics

*(No entries yet — Q6–Q10 pending.)*

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
