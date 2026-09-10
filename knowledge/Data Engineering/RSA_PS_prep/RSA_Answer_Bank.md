# RSA / PS Answer Bank — Databricks Resident Solutions Architect

**Source material (this folder):**
- `RSA interview checklist File 1(Interview Topics).csv` — 43 topics across 7 sections, with the *"What You Are Evaluating"* column stating what each question is really grading.
- `PS_InterviewQuestion 1(Sr.csv` — ~200 questions actually asked in prior rounds, by several interviewers.

**What this file is:** the canonical written answer for each topic, in the form it should be *spoken*. Precedent: `knowledge/Data Engineering/Novartis_SDP_50Q_Bank.md` — a standalone, role-specific bank rather than an append to the cross-company `DE_Interview_Prep.md`.

---

## Format contract

Every answer follows the same six-part shape, and the labels are used verbatim where they fit:

| Label | What goes in it |
|---|---|
| **What** | One-line definition. No jargon. |
| **Mechanism** | Numbered steps, one line each. How it actually works. |
| **Output** | What the artifact / result / number looks like. |
| **Fails-on** | The gotchas, the cases where it doesn't apply, the invisible behaviour. |
| **Inspect** | How to *see* it — `EXPLAIN`, Spark UI, logs, metrics. |
| **Knob** | Config name + default, in a table. |
| **Your answer** | The spoken version. This is the deliverable; everything above is the working. |

**Two hard rules, both learned the hard way in this repo:**

1. **Define before use.** Every abbreviation and technical term gets a plain-English definition the first time it appears. A term used undefined transfers zero information — it looks dense and teaches nothing. Shared vocabulary lives in Part 0 so individual answers can lean on it; *that* is what makes compression legitimate.
2. **Exact knob placement, not just the concept.** In a real round (2026-06-03, DLT/SDP) the correct *pattern* was produced cold but the flag was placed in Auto Loader settings when it is actually flow-level. Concept-right / knob-wrong reads as shallow. Hence the Knob table on every answer.

---

## Why this track exists

KB entry, 2026-05-20 (`framework_fluency_above_engine_fluency`): production DLT/Databricks **API** knowledge is deep — Apollo Gen2, 422 pipelines, named hard incidents. Spark **internals** self-test scored **3.5/10**.

> *"For Databricks-DE specifically, engine fluency is the interview gate. The user worked above the engine — needs deliberate descent."*

The RSA checklist is roughly 60% engine internals. **This folder is that descent.** Sections are ordered by that gap, not by the CSV's order.

---
---

# PART 0 — Shared vocabulary

Eight ideas do most of the work across every Spark-internals answer. Defined once here; every answer below assumes them.

## Machine code
The only language a processor (CPU) actually understands. Raw numbers meaning things like *"add the number in slot 1 to the number in slot 2."* Nothing is faster — there is no translation step left.

## Java, bytecode, and the JVM
Spark is written in Scala and Java, and **Java does not compile to machine code.**

It compiles to **bytecode** — a halfway language no CPU can run directly. Bytecode runs inside a program called the **JVM (Java Virtual Machine)**, which reads bytecode instructions and carries them out.

```
Your Java code → bytecode → [ JVM reads it and acts ] → CPU
                 (halfway)    (this middle step is the cost)
```

## Interpreting, JIT, and what "C2" means
Two ways the JVM can handle bytecode:

- **Interpreting** — read one instruction, do it, read the next. Like re-reading the recipe sheet before every single action. Correct, slow.
- **JIT compilation** — **JIT = Just-In-Time**. The JVM watches which code runs repeatedly ("hot" code) and, *while the program is still running*, translates it into real machine code. Roughly **20–50× faster** than interpreting.

The JVM ships **two** JIT compilers:

| Name | Compile speed | Machine code quality |
|---|---|---|
| **C1** | Fast | Mediocre |
| **C2** | Slow | Excellent |

C1 gets things moving; the hottest code is then re-compiled by C2 for the good version.

> **"The C2 JIT" = the JVM's high-quality translator that turns frequently-run Java bytecode into fast machine code while the program runs.** That's all it is.

## SIMD, and what AVX-512 is
Normally one CPU instruction does one piece of arithmetic. **SIMD = Single Instruction, Multiple Data** — instructions that apply the same operation to many numbers at once, using extra-wide slots inside the CPU.

**AVX-512** is one such family, where those slots are **512 bits** wide:

```
512 bits ÷ 64 bits per decimal number = 8 numbers at a time
512 bits ÷ 32 bits per whole number   = 16 numbers at a time
```

One AVX-512 instruction compares 8 prices against 100 simultaneously. **A free 8× — if you can get the CPU to actually use it.** (Whether you can is the entire reason Photon exists.)

## CPU cache and "L1"
Main memory (RAM) is physically far from the CPU — ~100 nanoseconds per fetch. So CPUs carry tiny fast memories on the chip itself:

| Layer | Size | Speed |
|---|---|---|
| **L1** | ~32–48 KB | ~1 ns |
| L2 | ~1 MB | ~4 ns |
| L3 | ~30 MB | ~15 ns |
| RAM | GBs | ~100 ns |

**Data that fits in L1 is reached ~100× faster.** This is why batch size in Photon is ~1,000 rows and not 100,000.

## Serialize / deserialize (and "pickling")
**Serializing** = flattening something in memory into a plain stream of bytes so it can be sent elsewhere — another program, a network, a disk. **Deserializing** = rebuilding it. Both cost CPU time proportional to data volume. **Pickle** is simply Python's name for its own serializing format.

## Garbage collection (GC)
Java manages memory for you. Periodically it **stops your program**, finds objects nobody is using, and frees them. That freeze is a *stop-the-world pause*. You don't control when it happens.

## DBU
**Databricks Unit** — the unit Databricks bills in. Not a machine and not an hour: a synthetic unit of processing. Different compute types burn DBUs at different rates, which is why "faster" and "cheaper" are separate questions.

## The unifying thesis — use this to structure any optimization answer
Derived independently on 2026-06-01 and recorded as a positive KB pattern (`cross_system_unifying_inference`):

> **Every major Databricks optimization is closing one of three JVM tax points at a specific boundary.**

| # | Tax point | The boundary | Optimizations that close it |
|---|---|---|---|
| 1 | **Memory representation** | Java objects vs. native bytes | Tungsten `UnsafeRow`, Delta Cache (decoded columnar, off-heap), vectorized Parquet reader |
| 2 | **CPU execution** | JVM bytecode vs. native SIMD | Whole-stage code generation (partial), **Photon** (full) |
| 3 | **Boundary serialization** | JVM↔Python, executor↔disk, executor↔executor | Arrow / Pandas UDFs, RocksDB state store, COPY INTO |

Mapping a question onto one of the three, out loud, beats reciting a memorized list. **A1 is tax point 3. A2 is tax point 2. A3 is not a JVM question at all** — it's a tenancy question, and saying so is itself the answer's structure.

---
---

# PART 1 — ANSWERS

---

## A1 · Reading a Parquet file: PySpark vs. SQL

> **Checklist:** partially serves #1 *Spark Core & Architecture / Spark Internals* (plan stages). Primary source is the PS bank — *"When do you use Parquet vs Delta files in Spark?"*, *"Logical Plan vs. Physical Plan?"*, *"How many partitions do you have when you read data from table in spark?"*
>
> **The trap:** the expected-but-wrong answers are *"SQL is faster because Photon"* or *"PySpark is faster because it's closer to the engine."* Both wrong. The senior answer is **"the same — and here's how I'd prove it, and here's what actually differs."**

### What
Two ways of *writing down* the same request. Spark converts both into the identical internal plan before running anything. Ordering by pointing at the menu photo, or by saying the dish's name — same kitchen, same dish.

### Mechanism
Neither PySpark nor SQL executes anything. Both are descriptions. **Catalyst** (Spark's query planner) turns a description into a runnable plan in five steps:

```
STEP 1 — You write it (PySpark or SQL). The ONLY step where they differ.

STEP 2 — Parse into a LOGICAL PLAN
         A tree: "read this file → keep rows where amt > 100 → take
         columns id, amt". Says WHAT, not HOW.
         ⚠️ Your language is already gone. Both inputs make the same tree.

STEP 3 — ANALYZE
         Check names and types are real. Does column `amt` exist? Is it
         comparable to 100? A typo'd column fails here.

STEP 4 — OPTIMIZE the logical plan (rewrite it cheaper)
         • Predicate pushdown — "predicate" just means a filter condition.
           Move the filter as early as possible, ideally INTO the file
           reader, so discarded rows are never loaded at all.
         • Column pruning — asked for 2 of 50 columns, so read only those
           2 off disk. Possible because Parquet stores column-by-column;
           a CSV would force reading everything.
         • Constant folding — "WHERE x > 2 + 3" becomes "WHERE x > 5",
           computed once at planning time, not a billion times at runtime.

STEP 5 — PICK THE PHYSICAL PLAN (HOW)
         Which join algorithm, how many parallel pieces. Becomes tasks.
```

Both converge at step 2. **Identical plan from step 2 onward = identical performance.**

### Output
```python
df.explain(True)                  # prints all four plan stages
spark.sql("...").explain(True)
```
Compare the `== Optimized Logical Plan ==` section. Character-for-character identical. *Saying you would check this* is worth as much as knowing the answer.

### Fails-on — the four real divergences

**(a) Python UDFs — the only large one.** *UDF = User Defined Function*, your own function applied per row.

Spark runs in the JVM. **Your Python code cannot run inside the JVM.** So Spark launches a **separate Python process** beside each worker, and per row:

```
1. Take the row out of Java's memory
2. Serialize (pickle) it into bytes
3. Push through a pipe to the Python process
4. Python rebuilds it, runs YOUR function on that ONE row
5. Python serializes the answer
6. Push back through the pipe
7. Java rebuilds it
   ... × 100,000,000
```

`amt > 100` costs about **one nanosecond**. That round trip costs **microseconds** — a thousandfold overhead for a nanosecond of work.

*Analogy:* a translator between you and a worker. **Native** — same language: one shouted instruction, a thousand items processed. **Python UDF** — every single item described, translated, acted on, translated back.

**Pandas UDF** is the middle path: the translator receives **a whole crate (~10,000 rows) at a time**. Same translation cost spread across 10,000 items, and it uses **Arrow** — a memory format Java and Python both already understand, so far less repackaging.

| Approach | Cost vs. native | Why |
|---|---|---|
| SQL / DataFrame native operation | **1×** | Never leaves the JVM |
| Pandas UDF | ~3–10× | Process hop, but batched + Arrow |
| Plain Python UDF | **~30–100×** | One serialize + one interpreter call **per row** |

**Invisible:** nothing warns you, and your code isn't longer. The tell is a plan node named `BatchEvalPython`. SQL has no syntax for a Python UDF — a *safety* property, not a speed one.

**(b) Raw path vs. registered table** — real, and usually misattributed to the language:

| | `spark.read.parquet("/mnt/x/")` | `SELECT * FROM catalog.schema.tbl` |
|---|---|---|
| Finding the schema | **List every file**, open ≥1 and read its *footer* (the small index at the end of a Parquet file describing its columns) | Read it from the Delta transaction log — already recorded |
| Skipping data | Only within a file, via per-chunk min/max in the footer | Log holds **min/max per file** → whole files skipped unopened |
| At 50,000 files | Listing is slow on cloud storage — minutes | One small read |

**But `spark.table("catalog.schema.tbl")` in PySpark gets exactly the same benefit.** The axis that matters is **raw path vs. registered table**, not **Python vs. SQL**. Most candidates merge these two; separating them is the differentiator.

**(c) Silent schema trap.** `spark.read.parquet()` reads the schema from **one** file's footer by default. If file #40,000 gained a column, or a column changed from whole-number to decimal, it is **silently dropped or mis-read**. No error.

**(d) Which compute you land on.** "SQL in Databricks" usually means the SQL editor → a **SQL Warehouse** (Photon always on; a **result cache** returns an identical query against unchanged data instantly, using no compute). "PySpark" usually means a notebook → an **all-purpose cluster** (Photon often off, no result cache). Same query, SQL "wins" — but you measured **two products**, not two languages.

### Inspect
`df.explain(True)` / `EXPLAIN FORMATTED`. Look for `BatchEvalPython` (Python UDF present), `PhotonScan` vs plain `Scan`, and `ColumnarToRow` (Photon→Java handoff).

### Knob
| Knob | Default | Effect |
|---|---|---|
| `mergeSchema` (reader option) | `false` | `true` = read every file's footer, catches schema drift |
| `spark.sql.execution.arrow.pyspark.enabled` | `true` on DBR | Arrow path for Pandas UDFs and `toPandas()` |
| `spark.sql.sources.parallelPartitionDiscovery.threshold` | `32` | Above this many paths, file listing goes distributed |

### Your answer
> Same. Both compile to the same plan, and I'd show that by diffing `.explain(True)` output. What actually differs is: Python UDFs, which force a per-row hop out of the JVM into a separate Python process; raw path reads versus registered table reads, which changes how much metadata work happens before any data is touched; and which compute the query lands on.
>
> I default to SQL for transformation logic — declarative, readable by the client's analysts, and you can't accidentally write a Python UDF into it. I reach for PySpark when I need to **build** the query programmatically: a column list not known until runtime, a loop over 200 tables driven by config. **PySpark's real advantage is writing code that writes queries, not speed.**

---

## A2 · Photon & Vectorization

> **Checklist #8 — Spark Core & Architecture / Photon & Vectorization.**
> Verbatim: *"Explain the exact low-level mechanics of the Photon Engine. How does its vectorized execution model differ from traditional JVM-based Volcano iteration, and what workloads derive zero benefit from it?"*
> Evaluating: *"Vectorized query execution internals, C++ engine execution layers, runtime engine constraints."*
>
> **The trap:** *"it's a faster C++ engine"* is a non-answer. They want the execution model **and** the workloads it doesn't help — the second half is the consulting value.

### What
A **replacement query engine written in C++ instead of Java**, loaded into the same worker process Spark already runs in. It escapes the JVM entirely and processes **1,000 rows at a time instead of one**. (Paper: *"Photon: A Fast Query Engine for Lakehouse Systems,"* SIGMOD 2022 — naming it plays well.)

### Mechanism — why it exists

**The original problem: one row at a time.** Databases classically use the **iterator model** (academic name: the *Volcano model*, from a 1990s research system — the name carries no meaning beyond that).

A bucket brigade. Your query is `read → filter → select → sum`. The last person asks the one before: *"give me a row."* Down the chain. **One row** comes back up. Repeat a billion times: 4 hand-offs × 1e9 rows = **4 billion function calls**, each unpredictable, each stalling the CPU. **Passing the rows costs more than the work done to them.**

**Spark already fixed that in 2016 — whole-stage code generation.** Instead of a chain of operators, Spark **writes a brand-new Java program while your query runs** that does all four steps in one single loop, and hands it to the JVM to JIT-compile. One person doing four jobs in one pass. A genuine 5–10× win.

> **So the real question is: if that exists, why build Photon?** Three walls it cannot get past.

**Wall 1 — You cannot force the JVM to use SIMD.**
The C2 compiler *sometimes* notices a loop could go 8-at-a-time and does it unprompted. But **it gives up whenever the loop contains an `if`, a null check, or a call it can't merge inline.** Every real query operator has null checks — any SQL column can be NULL, and NULL breaks ordinary comparison rules. So real Spark loops always contain exactly the thing that makes C2 abandon SIMD.

> You can write Java and *hope* you got SIMD. You can never write Java and *know*. In C++ you write the 8-at-a-time instruction yourself. **That guarantee is the whole reason for a new engine.**

**Wall 2 — A size limit where the JVM silently gives up.**
The JVM refuses to JIT-compile any single method larger than **8,000 bytecode instructions**. Too big → **it goes back to interpreting**, 20–50× slower. Whole-stage codegen emits **one enormous method per stage**; a wide query (200 columns, several fused operators) blows past 8,000.

**Nothing tells you.** No error, no warning, no change in the plan. The query just gets dramatically slower as it gets *wider*, with no visible reason. Naming this cliff is a strong signal — you only learn it by hitting it.

**Wall 3 — Garbage collection pauses**, plus no control over memory layout for cache friendliness.

### Mechanism — how vectorized execution works
1. Each step passes a **batch of ~1,000 rows stored column by column** — all 1,000 `amt` values in one flat array, all 1,000 `region` values in another.
2. `WHERE amt > 100` becomes **one loop over a flat array**: one function call for 1,000 rows instead of 1,000 calls.
3. **It fits in L1 cache**: 1,000 × 8 bytes = **8 KB**, inside L1's ~32 KB. The CPU never waits on RAM.
4. **SIMD now works** — flat array, no branching, exactly what C2 couldn't guarantee. 1,000 comparisons → **125 instructions**.
5. **Nothing is copied.** Photon writes a **selection vector** — literally a list of surviving positions, `[0, 3, 7, 11, …]` — and passes the *same* batch onward. No filtered array is ever built.

### The design choice worth quoting
Databricks **already owned the best code-generation engine in the industry** and deliberately went the **opposite** way for Photon — hand-written C++ rather than generated code. Two reasons:
1. **You can profile and debug a real, named C++ function.** You cannot meaningfully debug a string of Java your system invented thirty seconds ago.
2. **Hand-written code can inspect the batch first and pick a specialized version** — *"no NULLs in this batch → use the variant with the null check removed"*, *"all ASCII → skip Unicode decoding."* Generated-and-compiled code is fixed **before** it sees a single row.

### Output — rough arithmetic
`SELECT sum(amt) WHERE amt > 100`, 1 billion rows, one CPU core, compute only:

| Approach | The work | Time |
|---|---|---|
| One row at a time | 4 billion unpredictable function calls | **~10–20 s** in hand-offs alone |
| Whole-stage codegen | 1 billion comparisons, one at a time | **~0.3–0.6 s** |
| Photon | 125 million SIMD instructions | **~0.04 s** |

**~8× over whole-stage codegen on pure computation; 2–4× realistically end-to-end** — cloud-storage reads and network shuffling are untouched. If CPU was 30% of runtime, an 8× CPU win can't return more than that 30%.

### Fails-on — the actual rule
**Photon is a library of hand-written C++ functions, one per (operation, data type) combination.** Filter-on-integer: written. Sum-on-decimal: written. *Run this arbitrary Python function the user just wrote*: **impossible to have written in advance.**

When Photon meets a step it has no function for, **that step falls back to the Java engine — and the hand-off itself costs real work**, because column-batches must be rebuilt into Java row objects and back.

| Little or no benefit | Why |
|---|---|
| **Python or Scala UDFs** | Arbitrary code, no pre-written function possible. Falls back **and** pays conversion. The #1 reason Photon "didn't help." |
| **RDD API** (Spark's old low-level interface) | You hand Spark a raw function, not a describable operation — Photon can't see inside it |
| **Deeply nested data** (structures inside structures inside arrays) | Coverage lagged, still incomplete |
| **Streaming with memory** (running counts, session tracking) | Far fewer functions written than for batch |
| **Under ~1M rows** | Setup cost outweighs a win that only pays across many batches |
| **Storage- or shuffle-bound jobs** | 8× on CPU moves ~5% of the clock |
| **Many-tiny-files writes** | Bottleneck is thousands of storage write requests, not computation |

### The cost trap — volunteer this
**Photon bills at roughly 2× the DBU rate** (verify against current pricing for the tier).

> **Photon is a net loss below about 2× speedup.** A UDF-heavy pipeline can pay double the rate for identical speed.

Saying this unprompted shows you'll tell a client *not* to buy something — precisely what a customer-facing architect role selects for.

### Inspect
`EXPLAIN FORMATTED` — look for `PhotonScan`, `PhotonProject`, `PhotonGroupingAgg` vs. their plain equivalents. Then **hunt for `ColumnarToRow` / `RowToColumnar` mid-plan** — those are the Photon↔Java conversions, the fallback tax made visible. Spark UI SQL tab colours Photon steps; `photonTotalTime` metric.

**Lead with your own finding**, not the textbook — [Data_Engineering_Lessons.md:714](../Data_Engineering_Lessons.md#L714):
> *"Photon doesn't accelerate every operator. Enabling it on a cluster doesn't guarantee it's engaging on your expensive step. Check the query plan for the Photon badge on the actual exchange/aggregate nodes."*

### Knob
| Knob | Default | Effect |
|---|---|---|
| `spark.databricks.photon.enabled` | on for Photon SKUs | Master switch |
| Cluster UI "Use Photon Acceleration" | on for SQL Warehouses | Same, via UI |
| `spark.databricks.photon.window.enabled` | on | Photon for window functions specifically |
| — (billing) | ~2× DBU | The economic gate |

### Your answer
> One-row-at-a-time execution was already solved by whole-stage code generation. Photon exists for three things that can't fix: you can never guarantee the JVM emits the 8-at-a-time SIMD instructions, because it abandons them whenever there's a null check; generated methods above 8,000 bytecodes silently drop back to interpreted mode with nothing in the plan to show it; and you're still paying for garbage collection.
>
> Photon is C++ processing 1,000-row column batches, so the batch fits in L1 cache, SIMD is explicit, and filtering writes a list of surviving positions instead of copying data. Roughly 8× on raw compute, 2–4× realistically once storage and shuffle are counted.
>
> But it only works where a C++ function exists for that operation and type — a Python UDF has none, so it falls back to Java **and** pays the conversion. And it bills at about 2× DBU, so under 2× speedup it costs you money. I check the plan for Photon badges on the *expensive* step before claiming a win.

---

## A3 · Serverless Architecture

> **Checklist #10 — Spark Core & Architecture / Serverless Architecture.**
> Verbatim: *"What are the architectural, scheduling, and startup latency differences between classic Databricks compute and Serverless Compute? How do you handle custom library installations or networking limitations in Serverless?"*
> Evaluating: *"Modern compute paradigms, container security, network isolation constraints (Private Link vs. Serverless)."*
>
> **The trap:** "faster startup" is the answer everyone gives, and it's the *symptom*. Give the root cause instead — then re-derive the startup point at the end, where it lands much harder.

### What — first, two terms
Databricks is split in two:
- **Control plane** — the website, the buttons, the job scheduler, where notebook text is stored. **Always in Databricks' own cloud account**, for every compute type.
- **Data plane** — the actual machines running Spark and touching your data.

### The single difference everything follows from
**Whose cloud account are those working machines created in?**

| | **Classic** | **Serverless** |
|---|---|---|
| Control plane | Databricks' account | Databricks' account |
| **Working machines** | **YOUR Azure/AWS account, inside YOUR private network** | **Databricks' machines, Databricks' network** |
| Who owns them | You, for their lifetime | Databricks, always |
| Your cloud bill | Shows the machines | Shows nothing |
| You pay | Cloud provider for machines **+** Databricks for DBUs | One blended DBU rate covering both |

**That is the whole answer.** Everything below is a consequence — and presenting a chain of consequences rather than a feature list is what makes it an architect's answer.

### Mechanism — Consequence 1: Networking. The real blocker.

Three terms:
- **VNet (Virtual Network)** — a private network inside your cloud account. Things inside can talk; nothing outside gets in unless permitted. AWS calls it a VPC.
- **Private Endpoint** — makes a cloud service (database, storage) reachable **only** from inside your VNet, with no public address at all. Enterprises love these.
- **ExpressRoute** — a dedicated private cable from your company's own datacentre into Azure, bypassing the internet.

The logic is almost trivial:
```
Your database is reachable only from inside your VNet.
Serverless machines are not inside your VNet.
→ Serverless cannot reach your database. At all.
```
Same for firewalled storage and anything on-premises behind ExpressRoute.

**The fix, and name it: NCC — Network Connectivity Configuration.** An **account-level** object (above individual workspaces), two modes:
1. **Stable outbound addresses** — Databricks guarantees serverless traffic always leaves from a fixed set of internet addresses, which you add to the target's firewall allow-list.
2. **Managed private endpoint** — Databricks builds a private tunnel from its network into your resource, and **you approve it** from your side.

**What has no fix:**
- No injecting serverless into your VNet.
- **No custom routing rules** — normally you can force all traffic down a specific path.
- **No security appliance in the path** — many enterprises route every outbound connection through a central firewall box for inspection.
- **No custom DNS** — DNS translates names like `mydb.database.windows.net` into addresses; enterprises often run a private version.

> If the client's security standard says *"all outbound traffic must pass through the central firewall,"* **serverless breaks that rule structurally.** That's a conversation with their security team, not a setting. Recognizing it as an architecture problem rather than a config problem is the senior move.

### Mechanism — Consequence 2: A deliberately narrower Spark
**Multi-tenancy** = many customers' work on the same shared pool of machines.

On a classic cluster the machines are yours alone, so Databricks can safely let you install software as root, mount drives, run any code. On serverless **your code runs on machines that also serve other customers**, and the only way to guarantee you can't break out is to **take capabilities away**.

| Removed | What it is | Migration impact |
|---|---|---|
| **Init scripts** | A shell script Databricks runs on each machine before Spark starts — the standard way to install OS packages, database drivers, monitoring agents | Gone. Libraries only via `%pip` or an environment spec. Any pipeline needing a driver installed this way won't run. |
| **Most `spark.conf` settings** | Spark's tuning dials — memory per worker, shuffle piece count, GC flags | Locked or platform-managed. **An entire category of "how would you tune this" answers stops applying.** |
| **`SparkContext` / RDD API** | Spark's original low-level interface; `sc` is the handle, `sc.parallelize` and `rdd.mapPartitions` the common operations | Blocked. Legacy code using them **will not run.** |
| **DBFS FUSE** | Makes cloud storage appear as an ordinary folder like `/dbfs/mnt/data` | Gone. Code assuming ordinary file paths breaks. |
| **Hive metastore** | The *old* catalog — the registry of which tables exist and where. **Unity Catalog** is the modern replacement, adding permissions and lineage | **Unity Catalog mandatory.** No non-UC route. |

> **Headline: moving a legacy job to serverless is a code-compatibility exercise, not a configuration change.** That single reframe answers the checklist's *"how do you handle custom library installations or networking limitations."*

### Mechanism — Consequence 3: Cost control inverts (most-missed)
**Classic:** you choose machine type and count. That choice is a **physical ceiling on spend** — a badly written job on a small cluster is **cheap and slow**. It cannot cost more than the cluster costs.

**Serverless:** you choose nothing. The platform decides how much to throw at the query. The same bad job becomes **expensive instead of slow.**

| | Classic | Serverless |
|---|---|---|
| Main control | **Cluster policies** — rules capping what can be started | **Budget policies, tagging, dashboards** |
| Control type | **Preventive** — physically stops overspend before it happens | **Detective** — tells you afterwards |

> **For a client whose entire cost discipline is built on cluster policies, serverless invalidates their cost-control model.** Raising that unprompted is exactly what a consulting-facing role hires for.

### Mechanism — Consequence 4: No version freezing
**DBR (Databricks Runtime)** = the versioned bundle of Spark, libraries and OS a cluster runs. Classic pins `14.3 LTS` and it stays frozen until *you* move — you can validate a pipeline against it and keep it validated.

Serverless has only broad "environment versions," and **Databricks upgrades the underlying runtime on their schedule.** For a regulated client needing a validated frozen runtime, that's a hard blocker — and the kind that surfaces in month four if nobody raised it in month one.

### The unifying close — now startup lands
It's fast because **Databricks keeps a pool of machines already switched on, software already loaded, shared across all customers.** "Starting" isn't creating and booting a machine — it's **handing you a slot in a pool that was already warm**, plus attaching your identity and permissions.

> **That pool is only affordable because it's shared between customers.** So the fast startup and the restrictions are **the same fact seen from two sides.** You get near-instant starts *because* the machines are shared, pre-warmed and not yours — and you lose init scripts, VNet injection, `spark.conf` and version pinning *for exactly the same reason.* **There is no version of this where you get one without the other.**

### Fails-on — precision point most candidates fumble
"Serverless" is **four products** with different maturity and restrictions:

| Product | Notes |
|---|---|
| **Serverless SQL Warehouse** | Oldest, most mature. Photon always on, result caching |
| **Serverless Jobs / Workflows** | Newer — code-compatibility restrictions bite hardest here |
| **Serverless Notebooks** | Python and SQL first-class; Scala later and restricted |
| **Serverless DLT / Lakeflow Pipelines** | Where the "starts small and grows" behaviour lives |

**Asking "which serverless?" before answering is itself a good signal.**

### Inspect / your own ammunition
Four findings from BUPA that beat any textbook answer:

| Finding | Source |
|---|---|
| *"Serverless blocks reading certain Spark confs outright — distinct from 'the value isn't set.' Looks like a runtime failure; it's a compute-tier restriction."* | [L510](../Data_Engineering_Lessons.md#L510) |
| *"Serverless egress fails the cross-workspace trust check, so the triggering and waiting tasks must run on classic VNet compute — a constraint that only appears at **runtime**."* | [L1077](../Data_Engineering_Lessons.md#L1077) |
| *"A dashboard task that sleeps and waits sat on serverless **22h46m** doing zero Spark work. Classic single-node cost ~5 min startup."* | [L728](../Data_Engineering_Lessons.md#L728) |
| *"Serverless DLT starts small and autoscales — it doesn't hand you 200 slots on demand. Sequential often finishes faster than parallel."* | [L659](../Data_Engineering_Lessons.md#L659) |

The second is the strongest thing you own here: a networking constraint that **only appeared at runtime** and forced a classic cluster into a job that wanted none. No candidate gets that from documentation.

The third yields a reusable rule worth stating as a principle: **classify every task as compute-bound or wall-clock-bound before choosing its compute.** Serverless is right for short bursty compute and actively wrong for anything that mostly waits.

### Knob
| Knob | Where | Note |
|---|---|---|
| **NCC** (Network Connectivity Configuration) | **Account** console, then attached to workspaces | Not a workspace setting — the level matters, and it's the kind of placement detail that gets probed |
| Environment version | Serverless notebook/job env spec | Replaces DBR pinning; far narrower |
| `%pip install` | Notebook-scoped only | No cluster-scoped libraries, no init scripts |
| Budget policies + tags | Account console | The replacement for cluster policies as cost control |

### Your answer
> The one real difference is whose cloud account the working machines live in. Classic creates them inside your own subscription and your own private network; serverless runs them on Databricks' machines in Databricks' network. Everything else follows from that.
>
> Because they're not in your network, they can't reach anything private by default — Private Endpoint databases, firewalled storage, on-prem over ExpressRoute — and the fix is a Network Connectivity Configuration, either stable outbound addresses you allow-list or a managed private endpoint you approve. There's no VNet injection, no custom routing, no security appliance in the path, so it structurally breaks a central-firewall egress model.
>
> Because the machines are shared between customers, capabilities get removed: no init scripts, most Spark settings locked, no SparkContext or RDD API, Unity Catalog mandatory. So migrating a legacy job is a code-compatibility exercise, not a config change.
>
> And the cost model inverts. On classic the cluster is a physical spending ceiling, so a bad job is cheap and slow. On serverless the platform sizes it, so a bad job becomes expensive instead. Cost control moves from preventive cluster policies to detective budget alerts.
>
> The startup speed and all of those restrictions are the same fact from two sides — you get instant starts because the pool is pre-warmed and shared, and you lose control for exactly that reason.

---
---

# PART 2 — Coverage across all 43 checklist topics

**Status:** ✅ written · 🟡 partial · ⬜ not started · 🔵 ammunition exists in `Data_Engineering_Lessons.md` but no answer written yet

## Spark Core & Architecture (10)
| # | Topic | Status | Note |
|---|---|---|---|
| 1 | Spark Internals (stages from filter+groupBy) | 🟡 | Plan pipeline covered in A1; **shuffle-boundary stage counting not yet written** — this is the #1 measured gap |
| 2 | Advanced Optimization (AQE) | ⬜ | Appears 6× in the PS bank. Highest-frequency unanswered topic |
| 3 | Speculative Execution | ⬜ | |
| 4 | Join Strategies (BHJ / SMJ / SHJ / BNLJ) | ⬜ | Appears 4× in the PS bank |
| 5 | Memory Spill Management | ⬜ | |
| 6 | Cluster Sizing & Selection | 🔵 | Four BUPA findings ready — see ammunition index |
| 7 | Resource Utilization | 🔵 | Driver-bottleneck finding ready |
| 8 | **Photon & Vectorization** | ✅ | **A2** |
| 9 | Heap Memory & GC (on/off-heap, G1GC) | ⬜ | Part 0 defines GC; the tuning answer is unwritten |
| 10 | **Serverless Architecture** | ✅ | **A3** |

## Delta Lake & Ingestion (5)
| # | Topic | Status | Note |
|---|---|---|---|
| 11 | Delta Layout Optimization (Liquid vs Z-Order vs Predictive) | ⬜ | Appears 7× in the PS bank — **highest frequency of any topic** |
| 12 | Delta Architecture Limitations (ACID limits, write conflicts) | 🔵 | `_delta_log` direct-access finding ready ([L1145](../Data_Engineering_Lessons.md#L1145)) |
| 13 | SCD Strategies (MERGE vs CDF) | 🔵 | SCD2-on-SCD2 incident is a named war story |
| 14 | UniForm & Iceberg Compatibility | ⬜ | |
| 15 | Deletion Vectors | ⬜ | |

## Streaming & DLT (7)
| # | Topic | Status | Note |
|---|---|---|---|
| 16 | LDP / DLT Multi-source patterns | 🔵 | Apollo Gen2, 422 pipelines — strongest existing ground |
| 17 | LDP / DLT Materialized Views (why not Bronze/Silver) | ⬜ | |
| 18 | Ingestion Strategy (Auto Loader vs CDC; notification mode) | 🔵 | Parquet `_metadata.file_path` finding ([L165](../Data_Engineering_Lessons.md#L165)) |
| 19 | Stream-Stream Joins + watermarking | ⬜ | |
| 20 | Stateful vs Stateless (RocksDB) | ⬜ | |
| 21 | Time-based Windows (tumble/slide/session) | ⬜ | |
| 22 | State Clearing | ⬜ | |

## Databricks Migration Strategy (5)
| # | Topic | Status | Note |
|---|---|---|---|
| 23 | Migration Architecture (Snowflake/Teradata/Synapse → Lakehouse) | ⬜ | |
| 24 | In-flight Migrations (taking over a stalled project) | 🔵 | BUPA region migration is exactly this shape |
| 25 | Migration Tooling (Lakebridge / BladeBridge / remorph) | ⬜ | Honest "haven't used" + evaluation framework is a valid answer |
| 26 | Data Reconciliation | 🔵 | **The BUPA validation framework is precisely this.** Strongest single answer available |
| 27 | Migration TCO | 🔵 | 22h46m serverless finding is a TCO story |

## Platform Architecture & Admin (6)
| # | Topic | Status | Note |
|---|---|---|---|
| 28 | UC Access Control (RBAC limits, nested groups) | ⬜ | |
| 29 | Attribute Governance (ABAC, tag-based policies) | ⬜ | |
| 30 | Unity Catalog Governance (setup, SCIM) | ⬜ | |
| 31 | RBAC & Administration (account/workspace/metastore admin) | ⬜ | |
| 32 | Infrastructure as Code (DAB vs Terraform) | 🔵 | DAB used in production on BUPA |
| 33 | Console Administration | ⬜ | Overlaps #31 |

## Advanced Troubleshooting & Riddles (5)
| # | Topic | Status | Note |
|---|---|---|---|
| 34 | Performance Degradation (10 min → 2 hrs, no code change) | 🔵 | Spark UI triage finding ready |
| 35 | Auto Loader Scaling (perf drops as file count grows) | ⬜ | |
| 36 | **Logic Riddle: API UDF** (190 countries, 500+ calls) | ⬜ | **A1's UDF section is the foundation** — answer is lineage re-execution + caching |
| 37 | Logic Riddle: Partition Repair | ⬜ | |
| 38 | Logic Riddle: PySpark odd/even split | ⬜ | |

## Next-Gen Suite & AI (5)
| # | Topic | Status | Note |
|---|---|---|---|
| 39 | Lakeflow Suite & Automation | ⬜ | |
| 40 | Databricks Genie & AI BI | ⬜ | |
| 41 | Unity Metric Views & Semantic Layer | ⬜ | |
| 42 | Agentic AI & AgentBricks | ⬜ | JARVIS build is directly relevant experience here |
| 43 | Lakebase & Lakehouse Federation | ⬜ | |

**Written 3 / 43. Ammunition already exists for 12 more.**

---

# PART 3 — Ammunition index

Production findings indexed by which interview question they answer. **In an RSA round, a lived finding outranks a textbook answer every time** — these are the differentiator, and they're otherwise buried in files too long to search under pressure.

### Two sources, and why the citation style differs

| Source | What it holds | Cite by | Status |
|---|---|---|---|
| **`SL`** — [`client_work/<project>/SESSION_LEARNINGS.md`](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md) | **Primary.** Written live during the work, per project. Grows as the project runs. | **Section anchor** | Live — BUPA runs to Dec 2026 |
| **`DEL`** — [`Data_Engineering_Lessons.md`](../Data_Engineering_Lessons.md) | Generalized lessons distilled out of BUPA's `SL` up to 2026-08-22 | **Line number** | Frozen for BUPA |

**Convention, and the reason for it:** as of 2026-09-02 per-project learnings are tracked in place and are **no longer distilled into `Data_Engineering_Lessons.md`** — that file was growing without bound as projects accumulate. So:

- **New findings cite `SL` by section anchor.** Line numbers into a file still being appended to would rot; section headings survive appends.
- **Existing `DEL` citations stay as line numbers.** That file is now a frozen snapshot for BUPA content, so its line numbers are stable. No point churning 18 working links.
- Everything added to `SESSION_LEARNINGS.md` between now and December lands in this table as `SL`.

| Finding | Src | Ref | Answers topic # |
|---|---|---|---|
| Photon doesn't engage on every operator — check the badge on the *expensive* node | DEL | [714](../Data_Engineering_Lessons.md#L714) | 8 |
| Serverless blocks *reading* certain Spark confs — a tier restriction disguised as a runtime error | DEL | [510](../Data_Engineering_Lessons.md#L510) | 10 |
| Serverless egress fails cross-workspace trust — surfaces only at **runtime** | DEL | [1077](../Data_Engineering_Lessons.md#L1077) | 10, 24 |
| Serverless is UC-only, so going non-UC forces classic compute | DEL | [1142](../Data_Engineering_Lessons.md#L1142) | 10, 30 |
| Wall-clock-bound task on serverless: 22h46m, zero Spark work | DEL | [728](../Data_Engineering_Lessons.md#L728) | 10, 27 |
| Serverless DLT is elastic, not infinite — sequential often beats parallel | DEL | [659](../Data_Engineering_Lessons.md#L659) | 10, 16 |
| vCPU quota is per **VM family**, per region, per subscription — 1,344 cores needed vs 350 limit | DEL | [688](../Data_Engineering_Lessons.md#L688) | 6 |
| Spot draws from a *separate*, far larger quota — 350 vs 10,000 cores, same VM | DEL | [694](../Data_Engineering_Lessons.md#L694) | 6 |
| Quota ≠ capacity; insufficient quota can hang **pending** instead of failing loudly | DEL | [695](../Data_Engineering_Lessons.md#L695) | 6, 34 |
| VM *generation* can be a compliance gate (VNet encryption → v5 only), orthogonal to size and price | DEL | [701](../Data_Engineering_Lessons.md#L701) | 6 |
| Spot eviction loses **shuffle state**, not just compute — keep the driver on-demand | DEL | [709](../Data_Engineering_Lessons.md#L709) | 3, 5, 6 |
| Fewer, larger nodes at equal core count keep shuffle traffic node-local | DEL | [713](../Data_Engineering_Lessons.md#L713) | 4, 6 |
| Idle workers can mean a **driver** bottleneck — 24 threads on an 8-core driver, 4 GC stalls | DEL | [718](../Data_Engineering_Lessons.md#L718) | 7, 9, 34 |
| Memory-per-concurrent-thread is the sizing metric: 64 GB ÷ 24 = 2.7 GB stalled, 256 GB ÷ 24 = 10.7 GB fixed it | DEL | [721](../Data_Engineering_Lessons.md#L721) | 6, 7 |
| Diagnose the tier that is **slow**, not the one that looks wasteful | DEL | [723](../Data_Engineering_Lessons.md#L723) | 34 |
| Direct `_delta_log` access on non-UC sessions is what makes log-replay checks possible at all | DEL | [1145](../Data_Engineering_Lessons.md#L1145) | 12, 26 |
| Gen1→Gen2 SCD2 migration: matching row counts, **100% wrong active rows** | DEL | [223](../Data_Engineering_Lessons.md#L223) | 13, 26 |
| Suspect a **type/format** issue whenever a comparison fails 100% rather than partially | DEL | [506](../Data_Engineering_Lessons.md#L506) | 26, 34 |
| You can wait on a single **task inside** a remote run, not the whole run — turns a full-run barrier into a precise sync point. The source calls this the most useful thing in its section | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#cross-region-orchestration-one-job-triggering-and-awaiting-another) | 23, 24 |
| A policy that **requires** a property does not **impose** it — a single-node policy rejected a cluster that never declared `num_workers: 0` | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#infrastructure-as-code-deploy-time-vs-run-time) | 6, 32 |
| `life_cycle_state` and `result_state` are different fields; `SKIPPED`/`INTERNAL_ERROR` arrive with **no** `result_state`, so treating absence as "still running" builds a poll loop that never exits | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#cross-region-orchestration-one-job-triggering-and-awaiting-another) | 23, 34 |
| A cluster policy's allowlist can be **fundamentally incompatible** with your standards — spot-only policy plus an on-demand-only rule means no compliant config exists at all | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#infrastructure-as-code-deploy-time-vs-run-time) | 6, 32 |

---

# Appendix — Known weak patterns to drill against

From KB, so drilling targets the measured gaps rather than what's comfortable:

**Spark internals — 3.5/10 self-test (2026-05-20).** Specific misses: didn't separate Unresolved vs Analyzed logical plan; conflated predicate pushdown with column pruning; named predicate pushdown as an **AQE** optimization (wrong — AQE is runtime-only by definition); missed `shuffle.partitions` tuning as the first fix for big joins; knew salting but missed AQE skew-join handling; couldn't read a physical plan. *A1's Step-4 breakdown addresses the pushdown/pruning conflation directly.*

**Concept-right / knob-wrong (2026-06-03, live round).** Chose the correct backfill pattern cold, then placed the `ONCE` flag in Auto Loader settings when it is flow-level. **This is why every answer here carries a Knob table.**

**Framework fluency above engine fluency (2026-05-20).** DLT/Delta API knowledge is deep; engine internals are the gate for this specific role. Order study accordingly — Spark Core first, Next-Gen Suite last.

---

*Format contract derived from KB `explanation_format_interview_prep` (2026-08-21) and `jargon_gap` (2026-09-02). Append answers, don't rewrite prior ones. Update the Part 2 coverage table with every addition.*
