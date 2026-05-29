# Roadmap 01 — Spark Internals (6 weeks)

> **Goal:** Close the gap between *using* Spark via the DLT abstraction and *understanding* what happens at the engine layer. After this, you walk into a Databricks-DE interview and don't pause when asked "walk me through what happens when I call `df.groupBy().agg()`."
>
> **Why this is the #1 leverage move:** Test #1 graded you at 3.5/10 on engine internals — the exact bar Databricks DE specifically tests against. Atlassian / Stripe / Snowflake don't grill on this; Databricks does. Closing this is the binary between "Databricks DE is out of reach" and "Databricks DE is reachable."
>
> **Prerequisites:** Comfort with PySpark DataFrame API (you have it). Java/Scala literacy is helpful but not required — Spark source is readable in small doses.
>
> **Time budget:** ~6 hrs/week × 6 weeks = 36 hrs. Compresses to 4 weeks at 9 hrs/week if you're sprinting.

---

## Week 1 — Foundations & Execution Model

**What you'll learn**
- Spark architecture: driver, executor, cluster manager, SparkContext / SparkSession
- Lazy evaluation: why transformations don't execute and actions do
- RDD vs DataFrame vs Dataset (and why DataFrame won)
- The full Catalyst pipeline: Parser → Unresolved → Analyzed → Optimized → Physical
- `df.explain()` modes: `simple`, `extended`, `formatted`, `cost`, `codegen`

**Why it matters**
You already know what `df.show()` does. You don't yet know *what 8 internal stages run between your code and the rows hitting your screen*. Every other week of this roadmap builds on this mental model.

**Deliverable**
Write a "hello world" Spark job locally:
```python
df = spark.read.parquet("some_file")
df.groupBy("col_a").agg(F.sum("col_b")).show()
```
Run `df.groupBy("col_a").agg(F.sum("col_b")).explain('formatted')`. Save the output to a markdown file. Annotate each line — what is `HashAggregate`? What is `Exchange hashpartitioning`? What does `*(2)` mean?

**Topics to ask about** *(paste any into chat and I'll explain)*
- "What does each Catalyst stage actually do?"
- "Why is the DataFrame API faster than the RDD API?"
- "What's the difference between `explain('formatted')` and `explain('cost')`?"
- "What's the lifecycle of a Spark job — from `.show()` to result?"
- "How do driver and executor communicate?"
- "What is `SparkSession` vs `SparkContext`?"

---

## Week 2 — Catalyst Optimizer Deep Dive

**What you'll learn**
- **Rule-based optimizations** (each individually — already started in [`DE_Interview_Prep.md`](../DE_Interview_Prep.md)):
  - Predicate pushdown
  - Column pruning
  - Constant folding
  - Projection pushdown
  - Filter combining
  - Boolean simplification
- Less-famous rules: `NullPropagation`, `FoldablePropagation`, `CollapseProject`, `EliminateOuterJoin`, `ReorderJoin`
- **Cost-based optimizer (CBO)**: when it kicks in, what stats it needs (`ANALYZE TABLE name COMPUTE STATISTICS`), join reordering
- Histograms (`spark.sql.statistics.histogram.enabled`) and why they're disabled by default
- Reading the **optimized logical plan** specifically (the layer right before physical)

**Why it matters**
RBO + CBO is *every* pre-execution optimization Spark does. AQE (Week 4) is everything that happens after. Interview Q: "If a query is slow, where would Spark have already tried to make it fast before you got involved?"

**Deliverable**
Take **5 real DLT-generated queries** from your Apollo/LRC work. For each:
1. Dump `df.explain('formatted')`
2. Identify what Catalyst rewrote — the optimized plan often looks nothing like the SQL you wrote
3. Write 2 sentences per query explaining what changed

Bonus: try `df.explain('cost')` — if stats exist, you'll see CBO's row-count estimates.

**Topics to ask about**
- "Define each rule-based Catalyst optimization individually" *(already in [DE_Interview_Prep.md](../DE_Interview_Prep.md) Q1-deep)*
- "What's the difference between predicate pushdown and projection pushdown?"
- "How does the cost-based optimizer estimate join cardinality?"
- "Why are column histograms disabled by default?"
- "What does `ANALYZE TABLE` actually do and when should I run it?"
- "What does the `EliminateOuterJoin` rule do?"

---

## Week 3 — Tungsten & Whole-Stage Codegen

**What you'll learn**
- **Tungsten's three pillars**:
  1. Whole-stage codegen — fusing operators into one compiled JVM method
  2. Off-heap memory management — bypassing JVM GC
  3. Cache-aware computation — CPU L1/L2 alignment
- `UnsafeRow` representation — why Spark doesn't use Java objects internally
- **Vectorized / columnar execution** — Spark 3.x added native columnar processing
- **Where codegen breaks**: UDFs, certain joins, type-mismatch in WHERE clauses
- **Photon** (Databricks proprietary) — what Tungsten doesn't do that Photon does
- The `*(N)` markers in physical plans — what they mean, why they group operators

**Why it matters**
This is the layer that makes Spark 10× faster than naive JVM. Knowing where codegen fires vs doesn't is the difference between "Spark is slow" and "Spark is slow because my UDF broke the codegen pipeline."

**Deliverable**
Take one of your Apollo/LRC queries that uses a Python UDF. Compare:
1. `df.explain('codegen')` with the UDF
2. `df.explain('codegen')` after replacing the UDF with a built-in expression

Document the difference. The non-UDF version should show generated Java/Scala source code; the UDF version will have a serialization boundary.

**Topics to ask about**
- "What does whole-stage codegen actually compile into?"
- "Why is `UnsafeRow` faster than `Row` objects?"
- "When does codegen NOT fire?"
- "What's the difference between row-based and columnar execution?"
- "What does Photon do that Tungsten doesn't?"
- "Why are Python UDFs slower than Scala UDFs which are slower than built-in expressions?"
- "What does `*(N)` mean in the physical plan output?"

---

## Week 4 — AQE: Adaptive Query Execution

**What you'll learn** *(you've already done Q2-deep — go deeper)*
- All three AQE optimizations with knob names:
  - Dynamic Shuffle Partition Coalescing
  - Dynamic Join Strategy Switching
  - Dynamic Skew Join Handling
- The **temporal argument**: why AQE can't do predicate pushdown
- **Dynamic Partition Pruning (DPP)** — the one runtime predicate-pushdown-shaped feature
- What AQE *can't* do: aggregate skew, broadcast-side estimation errors, etc.
- Reading AQE behavior in Spark UI — the SQL tab shows plan changes in real time

**Why it matters**
AQE is the Databricks-favorite question. Knowing the three optimizations + their knobs + their conditions is the binary pass/fail of a Databricks-DE phone screen.

**Deliverable**
Write three intentionally-bad queries that AQE will *each* save:
1. Query that produces tiny post-shuffle partitions → AQE coalesces
2. Query whose build side filters down enough to broadcast → AQE switches strategy
3. Query with a skewed key → AQE splits skewed partition

Verify each by checking the Spark UI SQL tab. Take screenshots. Document what AQE did.

**Topics to ask about**
- "Walk me through all 3 AQE optimizations with knob names" *(in [DE_Interview_Prep.md](../DE_Interview_Prep.md) Q2)*
- "Why can't AQE do predicate pushdown?" *(in Q2-deep)*
- "What is Dynamic Partition Pruning and how does it differ from AQE?"
- "When does AQE not help?"
- "How do I confirm AQE actually fired on my query?"
- "What happens if I have AQE on but no shuffles in my plan?"

---

## Week 5 — Shuffles, Joins, Skew, and Tuning

**What you'll learn**
- **Shuffle internals**: Map output writer, External Shuffle Service, sort-based shuffle, push-based shuffle
- All **5 join algorithms** revisited with execution detail:
  - BroadcastHashJoin
  - SortMergeJoin
  - ShuffleHashJoin
  - BroadcastNestedLoopJoin
  - CartesianProduct
- When each fires; how to force each with hints
- **Salting** patterns for skew (you know this — drill it deeper)
- **Two-stage isolation** of hot keys
- **Bucketing**: when both sides bucketed on join key → no shuffle
- **Partitioning strategies**: hash, range, partition pruning
- The **`spark.sql.shuffle.partitions` rule of thumb**: 100–200 MB per partition (you missed this in Q3 of Test #1)

**Why it matters**
Most "Spark is slow" interview questions are really "do you know how shuffles work and how to reshape them." Plus the explicit Q3 gap from your Test #1 grading.

**Deliverable**
Take a deliberately-skewed dataset (1B rows, 99% in one key) and fix the slow join **three different ways**:
1. AQE skew join (zero code)
2. Salting (medium code change)
3. Two-stage hot-key isolation (heavy code change)
Measure: wall time, max task duration, # of stages. Write a 1-page comparison.

**Topics to ask about**
- "Explain all 5 Spark join algorithms in detail" *(in Q3-deep)*
- "When does Spark pick BroadcastHashJoin vs SortMergeJoin?"
- "What's the External Shuffle Service and why does it exist?"
- "Why was ShuffleHashJoin disabled by default in Spark 2.4?"
- "How does sort-based shuffle work step by step?"
- "What's bucketing and when does it actually help?"
- "What's the right value for `spark.sql.shuffle.partitions`?"
- "Walk me through a salting fix for skew."

---

## Week 6 — Production Tuning + Spark UI

**What you'll learn**
- **Spark UI** — every tab: Stages, Tasks, Storage, SQL, Executors, Environment
- Identifying **spills** (disk spill from memory)
- Identifying **fetch failures**, **OOMs**, **GC pauses**
- **Memory tuning**: executor memory, off-heap, broadcast threshold, shuffle.partitions
- Photon: when it accelerates (joins, aggregations), when it doesn't (UDFs, certain string ops)
- **Liquid Clustering vs ZORDER vs partition columns** — when each wins
- Common production pitfalls (you have war stories from Apollo — name them in DDIA vocabulary)

**Why it matters**
Production debugging is half of senior DE work. Reading Spark UI fluently is the differentiator between "I built pipelines" and "I own the platform."

**Deliverable**
Pick a real slow query from Apollo/LRC. Profile it via Spark UI. Write a **1-page postmortem**:
- Symptom (wall time, what failed)
- Diagnosis (which UI tab showed it, what specific metric)
- Fix (named, not vague)
- Result (before/after numbers)

This postmortem becomes interview gold — a 4-minute STAR story.

**Topics to ask about**
- "How do I read the Spark UI Stages tab?"
- "What does it mean when a task spills to disk?"
- "What's the difference between Liquid Clustering and ZORDER?"
- "When does Photon NOT speed things up?"
- "How do I tune `spark.executor.memory`?"
- "What's the difference between storage memory and execution memory?"
- "How do I debug an OOM in Spark?"

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| *Spark: The Definitive Guide* (Chambers & Zaharia) | Chapters 4, 19, 21, 22, 24 — the foundation reading |
| *High Performance Spark* (Karau & Warren) | Chapters 3, 4, 5, 7 — the tuning reading |
| Databricks Engineering Blog | Photon, AQE, Liquid Clustering deep-dives — search by topic |
| Spark UI docs | https://spark.apache.org/docs/latest/web-ui.html — read top to bottom once |
| Spark source code | `CatalystOptimizer.scala`, `AdaptiveSparkPlanExec.scala` — open these when you want depth on ONE specific rule |

---

## Checkpoints (self-assess at each)

- **End of Week 2:** Answer Q1 and Q2 of [`DE_Interview_Prep.md`](../DE_Interview_Prep.md) cold, in under 90 seconds each. If you can't, repeat Week 2.
- **End of Week 4:** Name all 3 AQE optimizations + exact knob names + firing conditions, out loud, in under 60 seconds. Record yourself.
- **End of Week 6:** Take a fresh self-test on Spark internals (ask me to generate one) — target 8/10. Have 2 polished Apollo STAR stories ready.

---

## How to use this file

1. Pick a week (default: start at Week 1).
2. Read the **What you'll learn** list.
3. Pick any **Topic to ask about** that's unfamiliar — paste it into chat, I'll explain it at the depth your cognitive pattern wants (hand-computed examples, named-step traces, no hand-waving).
4. Do the **Deliverable** to lock it in.
5. Self-test at the **Checkpoint** before moving on.
6. Don't move forward until the checkpoint passes — internalization > coverage.
