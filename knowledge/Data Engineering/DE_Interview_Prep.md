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
