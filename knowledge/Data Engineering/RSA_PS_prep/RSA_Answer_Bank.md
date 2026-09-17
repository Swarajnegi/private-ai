# RSA / PS Answer Bank — Databricks Resident Solutions Architect

**Source material (this folder):**
- `RSA interview checklist File 1(Interview Topics).csv` — 43 topics across 7 sections, with the *"What You Are Evaluating"* column stating what each question is really grading.
- `PS_InterviewQuestion 1(Sr.csv` — ~200 questions actually asked in prior rounds, by several interviewers.

**What this file is:** the canonical written answer for each topic, in the form it should be *spoken*. Precedent: `knowledge/Data Engineering/Novartis_SDP_50Q_Bank.md` — a standalone, role-specific bank rather than an append to the cross-company `DE_Interview_Prep.md`.

**STANDING RULE (added 2026-09-15, binding on every future turn in this thread):** the moment a Q&A exchange in this conversation covers an RSA-checklist or PS-bank topic, append it to this file **before the turn ends** — verbatim original question(s) first, then the full answer in the corrected format below. Do not wait to be told "add it" or "do it." This rule exists because it was skipped once already: five completed answers (Delta `_delta_log` metadata + sample tables, `exceptAll` internals, the driver-bottleneck diagnostic catalogue, join strategies) sat in chat only from 2026-09-02 to 2026-09-15 — thirteen days of finished work that couldn't help under interview pressure because nobody wrote it down. See A4–A7 below for the backfill, and the Format contract's Rule 3.

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

**Three hard rules, all learned the hard way in this repo:**

1. **Define before use — and this is a floor on vocabulary, not on depth.** Every abbreviation and technical term gets a plain-English definition the first time it appears, in the labeled sections themselves, not deferred to a glossary the reader has to hunt for. Correction that produced this rule, verbatim (2026-09-02): *"you are using terminology that briefs out the answer but is difficult for me to understand. use simple words and explain everything properly, like you used C2 JIT, I DONT KNOW WHAT THAT IS!"* The fix is **not** to simplify or shorten — a term used undefined transfers zero information, so defining it makes an answer *deeper*, not shallower. Simple words, full mechanism, every time. Shared vocabulary lives in Part 0 so individual answers can lean on it without re-deriving from scratch; *that* is what makes reuse legitimate — compression that skips a definition is not.
2. **Exact knob placement, not just the concept.** In a real round (2026-06-03, DLT/SDP) the correct *pattern* was produced cold but the flag was placed in Auto Loader settings when it is actually flow-level. Concept-right / knob-wrong reads as shallow. Hence the Knob table on every answer.
3. **Capture the question, not just the answer.** Every answer opens with the user's own verbatim question(s) in a blockquote, above the checklist mapping. A written answer with no record of what was actually asked is unreviewable later — you can't tell if it addressed the real question or a nearby one you assumed.

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
`EXPLAIN FORMATTED` — look for `PhotonScan`, `PhotonProject`, `PhotonGroupingAgg` vs. their plain equivalents. Then **hunt for `ColumnarToRow` / `RowToColumnar` mid-plan** — those are the Photon↔Java conversions, the fallback tax made visible. **Read the node name literally, `XToY` = FROM X TO Y:** `ColumnarToRow` = columnar (Photon's format) → row (Java's) = **Photon → Java**. `RowToColumnar` = row → columnar = **Java → Photon**. Easy to invert from memory — the name states the direction, don't guess it. Spark UI SQL tab colours Photon steps; `photonTotalTime` metric.

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

## A4 · Delta Architecture Limitations — the three stores, three clocks, and how to query each

> **Checklist #12 — Delta Lake & Ingestion / Delta Architecture Limitations.**
> Verbatim: *"What makes Delta different from standard Parquet at a file-system level, and what are the specific architectural limitations of ACID properties in Delta (e.g., concurrent write conflicts)?"*
> Evaluating: *"Delta transaction log mechanism, optimistic concurrency control limits."*
>
> **Original questions (verbatim, two turns):**
> 1. *"'What the log answers on its own — safe for the full 30 days even after VACUUM has removed every data file: column names, types and nullability (metaData.schemaString); ordinal column order; file count and total bytes (replay AddFile minus RemoveFile); SHOW TBLPROPERTIES (reconstructable from metaData.configuration plus protocol); partition columns; table and column comments; column-mapping mode and deletion-vector settings; and every DESCRIBE HISTORY question — clone versions, clone-commit counts, MAX(version).' from session_learnings, please elaborate further, and give sample queries that are used to query these metadata info"*
> 2. *"if you are sure, can you provide sample tables containing 2-3 rows each for these tables when I query them showcasing all the columns that can be found in each of these tables? SHOWTBLPROPERTIES, DESCRIBE DETAIL, DESCRIBE DETAIL EXTENDED, table_changes, DESCRIBE HISTORY"*
>
> **Confidence note carried over from the original answer:** the Databricks MCP connector was down (404, no endpoint) when this was written, so nothing here was executed against a live workspace. Column *names and types* are high-confidence (documented Delta protocol); exact sample values are illustrative, and two fields are flagged version-dependent below.
>
> **Correction folded in:** `DESCRIBE DETAIL EXTENDED` does not exist as a command — there is `DESCRIBE DETAIL` (Delta-specific) and `DESCRIBE TABLE EXTENDED` (Spark SQL). The second question named the first; this answer covers `DESCRIBE TABLE EXTENDED`, which is what the shape of the request implied.

### What
A governed Delta table is not one thing — it is **three separate stores, on three separate clocks**, and knowing which one answers a given question tells you which clock can break it.

**VACUUM** = the command that physically deletes data files no longer part of the table. **It never touches `_delta_log`.** Log cleanup is a separate, automatic process on its own schedule.

**Tombstone** = a log entry saying "this data file is no longer part of the table." The file is not deleted at that moment — it is marked, and VACUUM deletes it later.

| Store | Governed by | Default retention | Answers |
|---|---|---|---|
| **Physical data files** | `delta.deletedFileRetentionDuration` | **7 days** | Anything reading actual row *values* |
| **`_delta_log`** (commit JSONs + checkpoint Parquet) | `delta.logRetentionDuration` | **30 days** | Schema, file counts, sizes, properties, partitioning, comments, all history |
| **Unity Catalog metastore** | *neither clock* | n/a — always live | Registration, tags, PK/FK constraints, grants |

> **The 23-day window is the whole point.** Between day 7 and day 30, the data files may be physically gone while the log entries describing them survive. Every question the log can answer on its own still works in that window. Every question needing row values does not.

### Mechanism — what `_delta_log` physically is

```
/path/to/table/
├── part-00000-abc.snappy.parquet          ← data files
├── part-00001-def.snappy.parquet
└── _delta_log/
    ├── 00000000000000000000.json          ← commit 0
    ├── 00000000000000000001.json          ← commit 1
    ├── ...
    ├── 00000000000000000010.checkpoint.parquet   ← snapshot of state at v10
    ├── 00000000000000000011.json
    └── _last_checkpoint                   ← tiny pointer to the newest checkpoint
```

- **Commit file** — one JSON file per version, zero-padded to 20 digits. Newline-delimited: **one *action* per line.**
- **Checkpoint** — every 10 commits by default, Delta collapses all history so far into one Parquet file. Without it, reading version 5,000 means replaying 5,000 JSON files.
- **Action** — a single recorded fact. Seven types matter: `metaData` (schema as a JSON string, partition columns, table properties), `add` (a data file joining the table — path, size, partition values, stats, deletion vector), `remove` (a tombstone), `protocol` (reader/writer version + feature flags), `commitInfo` (who/what/when — operation, parameters, metrics, timestamp, job, notebook), `txn` (streaming idempotency marker), `domainMetadata` (newer features, e.g. Liquid Clustering state).

### The master map — question → action → SQL surface

| Question | Lives in | SQL surface | Time travel on that surface? |
|---|---|---|---|
| Column names / types / nullability | `metaData.schemaString` | `SELECT * … WHERE 1=0` | ✅ **yes** |
| Ordinal column order | same | same | ✅ yes |
| File count + total bytes | `add` − `remove` replay | `DESCRIBE DETAIL` | ❌ **no** — must replay |
| Table properties | `metaData.configuration` + `protocol` | `SHOW TBLPROPERTIES` | ❌ no |
| Partition columns | `metaData.partitionColumns` | `DESCRIBE DETAIL` | ❌ no |
| Table / column comments | `metaData.description` / field metadata | `DESCRIBE TABLE` | ❌ no |
| Column-mapping mode, deletion vectors | `metaData.configuration` | `SHOW TBLPROPERTIES` | ❌ no |
| Clone version / count / `MAX(version)` | `commitInfo` | `DESCRIBE HISTORY` | n/a — always live, **and that's a feature** |

> **That "no" column is the entire reason to bother replaying the log yourself.** The convenient SQL commands are live-only. Compare a live `DESCRIBE DETAIL` on a source against a version-pinned target and you have silently compared **now against then**.

### Output — sample queries

**1 · Schema at a pinned version — the free read.**
```sql
SELECT * FROM cat.sch.tbl VERSION AS OF 42 WHERE 1=0;
```
The predicate `1=0` can never be true, so Spark prunes every file at planning time and returns an empty result **carrying the real schema**. Zero data files opened.

**2 · File count and total bytes at a pinned version — the replay.**
```python
from pyspark.sql import functions as F

LOG = "abfss://container@account.dfs.core.windows.net/path/tbl/_delta_log"
V, CP = 42, 40          # target version, newest checkpoint at or before it

cp = (spark.read.parquet(f"{LOG}/{CP:020d}.checkpoint.parquet")
        .filter("add IS NOT NULL")
        .select(F.col("add.path").alias("path"), F.col("add.size").alias("size")))

commits = spark.read.json([f"{LOG}/{v:020d}.json" for v in range(CP + 1, V + 1)])
adds = commits.filter("add IS NOT NULL").select(F.col("add.path").alias("path"), F.col("add.size").alias("size"))
rems = commits.filter("remove IS NOT NULL").select(F.col("remove.path").alias("path"))

live = cp.unionByName(adds).join(rems, "path", "left_anti")
live.agg(F.count("*").alias("numFiles"), F.sum("size").alias("sizeInBytes")).show()
```
Newest checkpoint ≤ V, add later `add` entries, subtract `remove` entries **by path**.

**3 · Table properties — and why `configuration` alone is wrong.**
```python
meta  = commits.filter("metaData IS NOT NULL").select("metaData.*").first()
proto = commits.filter("protocol IS NOT NULL").select("protocol.*").first()
props = dict(meta["configuration"])
props.update({"delta.minReaderVersion": proto["minReaderVersion"], "delta.minWriterVersion": proto["minWriterVersion"]})
```
**`SHOW TBLPROPERTIES` is not just `metaData.configuration`** — protocol-derived entries surface there too.

**4 · `DESCRIBE HISTORY` family.**
```sql
SELECT version, timestamp,
       operationParameters.sourceVersion              AS src_version,
       CAST(operationMetrics.numCopiedFiles AS BIGINT) AS copied_files
FROM   (DESCRIBE HISTORY main.sales.customers)
WHERE  operation RLIKE 'CLONE'
ORDER  BY version DESC;

SELECT COUNT(*) FROM (DESCRIBE HISTORY main.sales.customers) WHERE operation RLIKE 'CLONE';
--   0 = never cloned | 1 = first load | >=2 = genuinely incremental
```

### Output — sample tables for the five metadata commands

**`SHOW TBLPROPERTIES`** — 2 columns (`key`, `value`), one row per property, no time travel:
```
key                                 value
-----------------------------------  --------------------------
delta.minReaderVersion               3
delta.minWriterVersion               7
delta.feature.deletionVectors        supported
delta.columnMapping.mode             name
delta.enableChangeDataFeed           true
delta.logRetentionDuration           interval 30 days
delta.deletedFileRetentionDuration   interval 7 days
```
`minReaderVersion 3` / `minWriterVersion 7` means **table features mode** — capabilities listed individually as `delta.feature.<name> = supported` rather than implied by a bare version number. **Absence is not "off"** — a missing property means *inheriting the built-in default*, not unset.

**`DESCRIBE DETAIL`** — 14–16 columns, **exactly 1 row, always.** No `VERSION AS OF`:
```
format            delta
id                8f3c1a2e-...-9d4b
name              main.sales.customers
location          abfss://.../customers
partitionColumns  ["region"]
clusteringColumns  []
numFiles          1284
sizeInBytes       9663676416
minReaderVersion  3
minWriterVersion  7
tableFeatures     ["columnMapping","deletionVectors"]   ⚠️ DBR-version-dependent field
```
`partitionColumns` and `clusteringColumns` are **mutually exclusive** — the clean way to answer *"does Liquid Clustering create physical partitions?"*: it does not, which is why `partitionColumns` stays empty while `clusteringColumns` populates.

**`DESCRIBE TABLE EXTENDED`** — always **3 columns** (`col_name`, `data_type`, `comment`), column rows first, then labelled metadata rows in the *same* 3 columns:
```
col_name          data_type       comment
customer_id       bigint          Surrogate key
region            string          Sales region

# Detailed Table Information
Catalog           main
Location          abfss://.../customers
Provider          delta
Table Properties  [delta.columnMapping.mode=name, delta.enableDeletionVectors=true]
```
Note the shape shift: in the metadata section, `col_name` holds the *label* and `data_type` holds the *value*. One 3-column result, not two tables — unpleasant to parse programmatically, which is why `DESCRIBE DETAIL` is the machine-readable choice.

**`table_changes(...)`** (Change Data Feed) — requires `delta.enableChangeDataFeed = true`, and only from the version it was enabled onward. All the table's own columns **plus three appended**:
```
customer_id  region  _change_type       _commit_version  _commit_timestamp
101          EMEA    insert             6                2026-08-30 09:12:04
102          APAC    update_preimage    7                2026-08-30 10:03:44
102          EMEA    update_postimage   7                2026-08-30 10:03:44
103          AMER    delete             8                2026-08-31 14:20:11
```
**One UPDATE emits TWO rows** — `update_preimage` (before) and `update_postimage` (after), sharing a `_commit_version`. A naive `COUNT(*)` double-counts updates; a naive downstream MERGE applies the old value if you don't filter to `update_postimage`.

**`DESCRIBE HISTORY`** — 15 columns, one row per version, newest first, **always live**:
```
version  timestamp            operation  readVersion  isBlindAppend
412      2026-09-01 22:14:07  CLONE              411          false
411      2026-09-01 21:40:12  MERGE              410          false
410      2026-09-01 03:00:55  OPTIMIZE           409          false

operationParameters
412: {source: main_dr.sales.customers, sourceVersion: 388, isShallow: false}
411: {predicate: (t.customer_id = s.customer_id)}
operationMetrics
412: {sourceNumOfFiles: 1284, numCopiedFiles: 96, copiedFilesSize: 402653184}
411: {numSourceRows: 48211, numTargetRowsInserted: 3140, numTargetRowsUpdated: 9022}
```

### Fails-on

| Failure | Mechanism |
|---|---|
| **Missing checkpoint → silent under-count** | Replay only works back to the newest checkpoint ≤ your target. If cleanup removed it, the `add` entries from the gap are simply absent and the count comes back **low** — indistinguishable from a table that legitimately shrank. **Detect the gap and raise.** |
| **Live vs pinned comparison** | `DESCRIBE DETAIL`, `SHOW TBLPROPERTIES`, `DESCRIBE TABLE` have no `VERSION AS OF`. Pairing one against a pinned counterpart compares now against then. |
| **`operationMetrics` zeros mean "not measured"** | If the writer ran with metrics collection off, `numCopiedFiles` is structurally `0` — measured at zero for all 13,574 tables in one environment. Anything that sums or averages it emits a confident wrong answer. |
| **Absent property ≠ unset** | `spark.databricks.delta.properties.defaults.<prop>` sets what *new* tables inherit; `SHOW TBLPROPERTIES` shows an entry only if explicitly overridden. |
| **`operation` naming varies for clones** | Current DBR emits `CLONE` with `isShallow` in the parameters; older/other engines emit `SHALLOW CLONE` / `DEEP CLONE` as the operation string. Match with `rlike('CLONE')`, not equality. |
| **`add.stats` is a JSON string, not a struct** | Reading `numRecords` needs `get_json_object` / `from_json`, not dot access. |

### Inspect
`EXPLAIN FORMATTED` won't show this — these are catalog/log reads, not query plans. Instead: `df.schema.fields` (ordered — answers ordinal position + comments in one call); the checkpoint interval via `delta.checkpointInterval`; whether Photon-badge tooling even applies (it doesn't — these are metadata reads, not vectorizable compute).

### Knob
| Knob | Default | Effect |
|---|---|---|
| `delta.deletedFileRetentionDuration` | `interval 7 days` | How long tombstoned data files survive VACUUM |
| `delta.logRetentionDuration` | `interval 30 days` | How long commits/checkpoints survive |
| `delta.checkpointInterval` | `10` | Commits between checkpoints |
| `delta.columnMapping.mode` | `none` | `name`/`id` → rename without rewrite |
| `delta.enableDeletionVectors` | varies by DBR | merge-on-read deletes |

### Your answer
> A governed Delta table has three stores on three clocks — data files on 7 days, the log on 30, and Unity Catalog on neither. So the first question about any check is which store answers it, because that tells you which clock can break it. Schema, file counts, properties, partitioning, comments, and all of `DESCRIBE HISTORY` come from the log and stay valid four times longer than the data files themselves. The catch is that the convenient SQL — `DESCRIBE DETAIL`, `SHOW TBLPROPERTIES` — is live-only, so for a pinned comparison I replay the log myself: newest checkpoint at or before my version, add the later `AddFile`s, subtract the `RemoveFile`s by path — and I gate on the missing-checkpoint case, because a naive replay under-counts silently and that looks exactly like a table that shrank.

**Ammunition:** [Direct `_delta_log` access on non-UC sessions is what makes log-replay checks possible at all](../Data_Engineering_Lessons.md#L1145).

---

## A5 · `exceptAll` and Data Reconciliation

> **Checklist #26 — Databricks Migration Strategy / Data Reconciliation.**
> Verbatim: *"How do you architect a foolproof row-by-row and aggregate data reconciliation framework during enterprise scale migrations to guarantee zero data loss without blowing up migration costs?"*
> Evaluating: *"Data auditing, validation automation, hash-based verification at scale."*
>
> **Original question (verbatim):** *"what exactly happens in exceptAll? just A-B?"*

### What
No — and "just A−B?" is exactly the right instinct to check, because `exceptAll` is **not** a set operation. `A.exceptAll(B)` is **multiset difference** (also called *bag* difference). A multiset is a collection where duplicates count. For every distinct row value `r`:

```
output count of r  =  max( count_A(r) − count_B(r) , 0 )
```

One-sided like `A − B`, but it's **arithmetic on multiplicities**, not membership. A row appearing 5× in A and 2× in B yields **3 copies** — not 0, and not 1.

`except` (`EXCEPT DISTINCT`) is the set version: deduplicate both sides first, emit `r` once if it's in A and not in B. **The two can disagree wildly.**

### Mechanism
Spark does not compute a difference. The optimizer rule `RewriteExceptAll` turns it into a **`GROUP BY` over every column** with a ±1 sentinel column (a temporary tag column, conventionally `vcol`):

```
1. Project A  →  add vcol = +1
2. Project B  →  add vcol = -1
3. UNION ALL the two
4. GROUP BY (every output column), SUM(vcol) AS sum_vcol
5. FILTER sum_vcol > 0
6. Generate ReplicateRows(sum_vcol) — emit each surviving row sum_vcol times
7. Project away vcol
```

Step 4 is where the cost goes. Grouping requires a **shuffle** — redistributing rows across the cluster so identical rows land on the same worker — and the shuffle key is **the entire row**. Every column of every row on both sides crosses the network.

### Output — hand-traced

**A:** `(1,EMEA)×3, (2,APAC)×1, (3,NULL)×1`. **B:** `(1,EMEA)×1, (2,APAC)×2, (3,NULL)×1, (4,AMER)×1`.

| Group | vcol values | `sum_vcol` | Survives `> 0`? |
|---|---|---|---|
| `(1, EMEA)` | +1,+1,+1,−1 | **+2** | ✅ emit **2 copies** |
| `(2, APAC)` | +1,−1,−1 | **−1** | ❌ |
| `(3, NULL)` | +1,−1 | **0** | ❌ |
| `(4, AMER)` | −1 | **−1** | ❌ |

**`A.exceptAll(B)` = 2× `(1, EMEA)`.** Verify: `3−1=2`. ✅

**Now the same data through `except`:** `distinct A = distinct B` on every key except the counts don't matter for set membership → **`A except B = {}`, EMPTY.**

> **`except` says the tables match. `exceptAll` says two rows are missing.** Same inputs. If you're reconciling a migration, `except` would have signed off on a table with a genuine duplicate-count defect.

### Fails-on

- **Cost is proportional to total row bytes, not to how different the tables are.** Two byte-identical billion-row tables cost exactly as much as two completely different ones — there is no early exit. Per the source lesson: *"`exceptAll` is a full shuffle of every column on both sides, disguised as a simple diff... the cost is proportional to total row bytes moved across the network, not to how different the tables actually are."* — [SESSION_LEARNINGS.md § Spark execution & performance](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance)
- **`NULL` groups with `NULL`.** In `GROUP BY`, NULL is a valid group key, so `exceptAll` correctly treats NULL-bearing rows on both sides as the same row. A hand-rolled `LEFT ANTI JOIN` on all columns does **not** — `NULL = NULL` is NULL, not true, so those rows never match and appear as false differences. **This is the main reason `exceptAll` is the right tool for reconciliation despite the cost.**
- **Ungroupable column types break it.** `MapType` cannot be a group key in Spark, so `exceptAll` on a DataFrame containing a map column fails outright.
- **Column order and types must match** on both sides — positional, not by name.
- **Both sides must be fully materialised** at a pinned version, so this is the one check in a validation suite that is unambiguously data-bound — governed by the 7-day `deletedFileRetentionDuration` clock (see A4).

### The cheaper exact alternative
> **If `|A| = |B|` and `B − A = ∅`, then `A = B`.** — [SESSION_LEARNINGS.md § Spark execution & performance](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance)

Why it holds: `B − A = ∅` as multisets means `count_B(r) ≤ count_A(r)` for every row, forcing `|B| ≤ |A|`. Given `|A| = |B|`, every inequality is tight — a **two-sided** guarantee from a **one-sided** (half-cost) computation, since row counts are usually near-free from Delta log statistics (A4).

| Approach | Kind of claim | Shuffle cost |
|---|---|---|
| `exceptAll` both directions | Deductive, complete | **2×** full row bytes |
| One direction + both counts | Deductive, complete | **1×** full row bytes |
| Per-row hash, then `SUM()` | **Probabilistic** — can cancel on offsetting errors | ~8 bytes/row |
| Row count alone | Necessary, not sufficient | ~free (log stats) |

A checksum sum is a *different kind of claim*, not a faster version of the same claim — two offsetting errors produce an identical sum, so it's fine for detecting accidental corruption but not something to put in a DR sign-off as "we compared every row."

### Inspect
```python
A.exceptAll(B).explain()
```
Look for, top to bottom: `Generate ReplicateRows` → `Filter (sum_vcol > 0)` → `HashAggregate(keys=[all columns], functions=[sum(vcol)])` → **`Exchange hashpartitioning(<every column>, 200)`** → `Union`. That `Exchange` line listing every column **is** the cost.

### Knob
| Knob | Default | Effect |
|---|---|---|
| `spark.sql.shuffle.partitions` | `200` | Post-shuffle partition count for the `GROUP BY` |
| `spark.sql.adaptive.coalescePartitions.enabled` | `true` | Merges small post-shuffle partitions — after the shuffle write, so tiny tables still plan against the full count |

### Your answer
> It's multiset difference, not set difference — each row survives `max(count_A − count_B, 0)` times, so duplicates are counted, not collapsed. Spark doesn't compute a difference at all: it tags A with +1 and B with −1, unions them, groups by *every column* summing the tag, keeps positive sums and replicates each row that many times. The shuffle key is the whole row, so cost tracks total bytes on both sides regardless of how different the tables are. Its real advantage over a hand-rolled anti-join is that `GROUP BY` matches NULL to NULL, where three-valued SQL logic would silently drop those rows as false differences. And when I need to cut cost, I use the one-sided-plus-row-count trick — `|A|=|B|` and `B−A=∅` together prove full equality for half the shuffle.

**Ammunition:** [`exceptAll` full-shuffle finding](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance) · [Gen1→Gen2 SCD2 migration, matching row counts but 100% wrong active rows](../Data_Engineering_Lessons.md#L223) · [Suspect a type/format issue whenever a comparison fails 100%](../Data_Engineering_Lessons.md#L506).

---

## A6 · Resource Utilization — driver bottlenecks and the full diagnostic catalogue

> **Checklist #7 — Spark Core & Architecture / Resource Utilization.**
> Verbatim: *"How do you diagnose an over-utilized vs. under-utilized cluster using Ganglia, cluster metrics, or the Spark UI? What action items do you execute if a cluster exhibits high driver CPU but near-zero executor load?"*
> Also serves **#9** (Heap Memory & GC) and **#34** (Performance Degradation).
>
> **Original question (verbatim, quoting the ammunition finding back for elaboration):** *"'Idle workers can be a symptom of a driver bottleneck, not of over-provisioning. A tier running a thread pool on the driver logged ~70 autoscaler resizes in 3h17m... The workers idled because the work never reached them. Cutting worker count would have been the intuitive fix and the wrong one.' explain this further, explaining this scenario, and similar ones that i might face and their deductions and suggested solutions."*

### What
**Driver** = the single process running your main program — builds the plan, decides what work exists, hands out tasks, collects results. One per application. **Executor** = worker processes that run tasks. **Task** = the unit of work shipped to an executor, one per data partition. **Autoscaler** = Databricks adding/removing worker nodes based on demand.

### Mechanism — the case that motivated this, worked in full

**Two separate failures stacked on top of each other.**

**Failure A — the work never became Spark tasks.** The autoscaler scales on pending *tasks*, not CPU load — empty scheduler queue → it concludes the cluster is oversized → removes workers. A Python thread doing non-Spark work (listing Delta log files, parsing JSON) creates zero tasks. So: Python-heavy phase → task queue empty → autoscaler removes workers (3→2→1) → Spark burst arrives → tasks queue → autoscaler adds workers (1→3) → repeat. **~70 resizes in 3h17m is one every ~2.8 minutes**, matching the observed 40–90s cycle. Each resize costs 1–3 minutes for a new worker to boot and join — by the time capacity arrives, the burst is often over.

**Failure B — the driver couldn't schedule even when tasks existed.** 24 Python threads, one Delta log file list each, all in driver heap: `64 GB ÷ 24 threads = 2.7 GB/thread`. **GC (garbage collection)** = Java periodically stopping the whole program to reclaim memory nobody's using — a **stop-the-world pause**. As heap fills, GC fires more; a frozen JVM sends no heartbeats (→ `DRIVER_NOT_RESPONDING`, recorded 4×); a frozen scheduler dispatches to nobody. **Executors idle even when real tasks are waiting, because the dispatcher is intermittently dead.**

**Why cutting workers was the wrong fix:** it removes the idle workers, so the *symptom* disappears — nothing gets faster, because the driver was the constraint. Wall clock stays the same, and Spark bursts get *slower* from less capacity.

**The actual fix:** `256 GB ÷ 24 threads = 10.7 GB/thread` — resolved, **with concurrency unchanged.** The reusable metric: **for driver-hosted concurrency, size on memory per concurrent thread, not on cores.** Two routes reach the same 10.7 GB ratio with very different outcomes — growing the driver keeps throughput; cutting threads to 6 quarters it. The ratio says how much you need; it doesn't say which side to move.

Also worth naming: **Python's GIL** (Global Interpreter Lock — permits one thread executing Python bytecode at a time) means 24 threads never bought CPU parallelism; they bought I/O overlap at 24× the memory cost.

### The diagnostic order
```
STEP 1 — Are tasks even being created?       Jobs tab, gaps in the timeline = driver-side work
STEP 2 — Is the driver healthy?              Executors tab, DRIVER row GC Time; event log DRIVER_NOT_RESPONDING
STEP 3 — Are tasks distributed evenly?       Stage Summary Metrics (min/25th/median/75th/max)
STEP 4 — Are there enough tasks at all?      Task count vs. total cluster cores
STEP 5 — Are executors staying alive?        Appear-and-die with zero tasks = cloud isn't granting capacity
STEP 6 — Is work being redone?               Shuffle Write >> Shuffle Read
```

### Output — the scenario catalogue

| # | Symptom | Signature | Deduction | Fix |
|---|---|---|---|---|
| **S1** | Executors idle, driver CPU high, autoscaler oscillating | Jobs timeline gaps; driver GC Time high; `DRIVER_NOT_RESPONDING` | Driver-hosted work never becomes tasks | Size driver by memory ÷ concurrent threads; disable autoscaling for that tier |
| **S2** | Driver OOM / `resultSize exceeded` | Fails at `collect()`/`toPandas()`/broadcast | Distributed data pulled into one process | Don't collect — write to a table and read back. Raising `maxResultSize` moves the cliff, doesn't remove it |
| **S3** | Executors idle, no GC issue | e.g. 8 tasks on 40 cores | Not enough partitions | `repartition(n)`; raise shuffle partitions; **stop using gzip** — it's not splittable, so one `.csv.gz` file = one task regardless of size |
| **S4** | 97/100 tasks finish in seconds, 3 run for hours | `max` Duration/Shuffle ≫ `median` | Data skew — one key dominates | AQE skew-join handling (sort-merge only — see A7); salting; isolate hot keys |
| **S5** | Cluster stays *pending*; or executors appear and die instantly | `AZURE_QUOTA_EXCEEDED_EXCEPTION`; zero-task executors | vCPU quota exhausted, or no spot capacity right now | Different VM **family** = different quota bucket; spot draws from a separate, often larger quota |
| **S6** | Stages restart repeatedly, runtime balloons | **`Shuffle Write ≫ Shuffle Read`** | Spot eviction takes shuffle files with it — downstream tasks fail, stage re-runs | **Driver on-demand, workers spot** — one driver eviction kills the whole job |
| **S7** | Executors at 100% CPU, throughput still bad | `BatchEvalPython` in the plan, no Photon badge | Python UDF per-row serialize/pipe cost (see A1) | Native function or Pandas UDF |
| **S8** | Long dead time before any task starts, even on tiny tables | Driver busy, no stages running | Cost is per-table/per-file, not per-byte — thousands of small log reads | Add concurrency not cores; compact small files; Auto Loader notification mode |
| **S9** | Large shuffle both sides though one side is small | `SortMergeJoin` where `BroadcastHashJoin` was expected | Size estimate for the small side missing/stale | `ANALYZE TABLE ... COMPUTE STATISTICS`; explicit `broadcast()` hint |
| **S10** | Many autoscaler resizes, worse than a fixed cluster | Event log full of `RESIZING`, sawtooth worker count | Bursty demand; new node takes 1–3 min to join, arrives after the burst | Fixed worker count for bursty/driver-heavy tiers |

### Fails-on
The trap in S1 specifically: **idle workers reads as over-provisioning, and the intuitive fix (cut workers) removes the symptom without touching the cause.** More generally: diagnose the *slow* tier, not the one that *looks* wasteful — a job with one tier at 39 minutes and another at 3h17m wastes effort if trimmed on the fast one; only the slow tier moves wall clock.

### Inspect
Ganglia (older workspaces) or the built-in cluster metrics tab — either way, the thing needed is **driver metrics separated from worker metrics**, because an aggregate CPU number averages the busy driver with the idle workers and hides exactly this failure. Spark UI Executors tab: low GC time rules out memory pressure; `Shuffle Write ≫ Shuffle Read` is the signature of work computed, lost, and redone.

### Knob
| Knob | Default | Use |
|---|---|---|
| `spark.driver.maxResultSize` | `4g` | Cap on data returned to the driver — raising it treats a symptom |
| `spark.sql.shuffle.partitions` | `200` | Post-shuffle partition count; **session-global**, so two concurrent tiers can't have different values — the fix is phased execution |
| `spark.sql.adaptive.skewJoin.enabled` | `true` | Splits skewed partitions — sort-merge joins only (A7) |
| `spark.sql.files.maxPartitionBytes` | `128MB` | Bytes per read task, splittable formats only |
| `spark.sql.autoBroadcastJoinThreshold` | `10MB` | Below this, broadcast; `-1` disables |

### Your answer
> Idle executors mean work isn't reaching them, and I check it in order: are tasks being created at all, is the driver healthy, are tasks distributed evenly, are there enough of them, are executors staying alive, is work being redone. In that specific case, the autoscaler scales on pending tasks, and driver-side Python threads create none — so it read an empty queue as an oversized cluster and thrashed 70 times in three hours. Meanwhile 24 threads on a 64 GB driver left 2.7 GB each, GC was stopping the world, and a frozen driver can't dispatch to anyone — the workers idled because the scheduler was intermittently dead, not because there were too many of them. Cutting workers would have removed the symptom, not the cause. For driver-hosted concurrency the metric is memory per concurrent thread; 256 GB over the same 24 threads fixed it with no loss of parallelism.

**Ammunition:** [Idle workers = driver bottleneck, 24 threads / 64GB / 4 GC stalls](../Data_Engineering_Lessons.md#L718) · [Memory-per-thread sizing metric](../Data_Engineering_Lessons.md#L721) · [Diagnose the slow tier, not the wasteful-looking one](../Data_Engineering_Lessons.md#L723) · [Spot eviction loses shuffle state](../Data_Engineering_Lessons.md#L709) · [Quota ≠ capacity, pending is silent failure](../Data_Engineering_Lessons.md#L695).

---

## A7 · Join Strategies — BHJ, SHJ, SMJ, BNLJ, and why AQE skew-splitting is SMJ-only

> **Checklist #4 — Spark Core & Architecture / Join Strategies.**
> Verbatim: *"Compare all Spark join strategies (BHJ, SMJ, SHJ, Broadcast Nested Loop Join). Which is the worst possible strategy, why, and how do you force or avoid it via hints or configuration?"*
> Evaluating: *"Distributed join internals, memory footprints, cartesian product mitigation."*
>
> **Original question (verbatim):** *"why only sort-merge join? what happens exactly in each of the joins? SHJ, BJ and SMJ?"*

### What
**Equi-join** = a join whose condition is equality (`ON a.id = b.id`); anything else (`<`, `<>`, `BETWEEN`) is non-equi. **Hash table** = a lookup structure where a key finds its matching rows in ~one step. **Build side / probe side** = in a hash join, the side loaded *into* the hash table vs. the side streamed *against* it — always build from the smaller one. **Hash partitioning** = `partition = hash(key) % numPartitions`, used so equal keys land in the same partition and can be joined in isolation.

### Mechanism — one dataset, three strategies

`orders` (big, 6 rows: `1,1,2,3,1,2`) joined to `customers` (small, 3 rows: `1→Anita, 2→Bhaskar, 3→Chen`).

**Broadcast Hash Join (BHJ).** Read the small side in full, send a complete copy to **every** executor, build a hash table locally, then each executor streams its **own existing** big-side partitions through it. The big side **never moves** — zero shuffle. Cost: network = `size(small) × executors`; memory = one copy per executor; time = O(big).

**Shuffle Hash Join (SHJ).** Shuffle **both** sides by `hash(key)`, then per partition build a hash table from the smaller side's partition and stream the larger through it. No sorting. Cost: network = full size of both sides; memory = the build **partition** must fit — no graceful degradation if it doesn't.

**Sort Merge Join (SMJ) — the default.** Shuffle both sides (same as SHJ), then **sort** each partition by key, then walk the two sorted streams with two advancing pointers, like merging two sorted lists. No hash table. Memory is bounded — the sort **spills to disk** when it doesn't fit, just slower, never failing outright. `spark.sql.join.preferSortMergeJoin` defaults `true`, which is why SHJ is rare in practice.

### Output — comparison

| | **BHJ** | **SHJ** | **SMJ** | **BNLJ** |
|---|---|---|---|---|
| Shuffle | **None** | Both sides | Both sides | None (broadcast) |
| Sort | No | No | **Yes** | No |
| Hash table | Per executor | Per partition | No | No |
| Memory risk | Small side × executors | Build partition must fit | **Bounded — spills** | Broadcast side |
| Equi-join required | Yes | Yes | Yes | **No** |
| Complexity | O(n) | O(n+m) | O(n log n) | **O(n×m)** |
| Skew-vulnerable | **No** | Yes | Yes | n/a |
| AQE skew-split applies | **No — no shuffle** | Narrow, version-dependent | **Yes** | No |

### Fails-on — why AQE skew handling is SMJ-only

**AQE** (Adaptive Query Execution) re-plans mid-flight using real post-shuffle partition sizes. Its skew rule: a partition is skewed if `size > 5× median AND size > 256MB`; it then **splits** the skewed side's partition into N pieces and **replicates** the other side's matching partition N times, running N independent smaller joins.

**Splitting one side forces duplicating the other** — natural for SMJ because a merge join is a re-readable streaming scan over sorted shuffle blocks; splitting by byte range and re-scanning the whole matching side for each piece is just three ordinary merges, memory bounded throughout. **Awkward for SHJ** because the first act of a hash join is building a hash table — split the probe side into 3 and you either rebuild that table 3× (paying 3× the build cost and 3× the memory that already made hash joins fragile) or share one table between tasks, which Spark's task model doesn't do. **Structurally exempt for BHJ**, for two reasons: no shuffle means no shuffle statistics to measure and nothing to split; and skew is a *concentration* event from a shuffle gathering one key into one partition — BHJ never redistributes the big side, so no concentration ever happens.

> **Honest version boundary:** originally AQE's skew rule matched only `SortMergeJoinExec`; SHJ coverage was added later and is narrower. Check `EXPLAIN` on the actual runtime before claiming SHJ coverage.

**The connection people miss:** AQE's *other* trick — converting SMJ → BHJ at runtime once real stats reveal a side is smaller than estimated — is often the better skew fix, because it removes the shuffle entirely rather than subdividing it.

**The worst strategy — BNLJ / Cartesian.** For every row of one side, scan every row of the other, evaluating the condition — cost is **multiplicative** (`n × m`), not additive. Chosen **silently** whenever the join condition isn't an equality (`<>`, a range, or none at all) — nobody writes this on purpose, the planner just has no other option. `CartesianProductExec` is the worse cousin: no equi-condition and neither side broadcastable.

**Avoiding it:** manufacture an equality — bucket a range join to a coarse grain (e.g. day), join on that, then filter the exact range; or use Databricks' `/*+ RANGE_JOIN(t, 3600) */` hint.

### Inspect
Check the plan for `BroadcastNestedLoopJoin` or `CartesianProduct` before shipping any join whose condition isn't a plain `=`. For skew, check `EXPLAIN` for whether the runtime's skew rule actually covers the join type in use.

### Knob
| Knob | Default | Effect |
|---|---|---|
| `spark.sql.autoBroadcastJoinThreshold` | `10MB` | Below this → BHJ. `-1` disables. |
| `spark.sql.join.preferSortMergeJoin` | `true` | Why SHJ is rare |
| `spark.sql.adaptive.skewJoin.skewedPartitionFactor` | `5` | × median to qualify as skewed |
| `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` | `256MB` | Absolute floor — a skewed partition under this is never split |
| `spark.sql.crossJoin.enabled` | `true` | When `false`, an accidental cartesian join **errors instead of running** |
| Hints | — | `/*+ BROADCAST(t) */`, `/*+ MERGE(t) */`, `/*+ SHUFFLE_HASH(t) */`, `/*+ RANGE_JOIN(t, binSize) */` |

### Your answer
> Broadcast sends the small side to every executor and never shuffles the big one — fastest, and structurally immune to skew because no redistribution ever happens. Shuffle hash and sort-merge both shuffle everything; hash join builds an in-memory table per partition and degrades badly if it doesn't fit, sort-merge sorts and spills to disk, which is why it's the default.
>
> AQE's skew rule splits a hot partition and replicates the matching partition from the other side — natural for sort-merge, because a merge is a re-readable streaming scan; awkward for hash join because you'd rebuild the hash table per split; meaningless for broadcast, which has no shuffle statistics to measure and no concentration to fix in the first place. The better skew fix is often converting sort-merge to broadcast at runtime once real stats arrive — that removes the shuffle instead of subdividing it.
>
> The worst strategy is the broadcast nested loop or a full cartesian product, chosen silently whenever the condition isn't an equality, at multiplicative cost. Fix: manufacture an equality, or use the `RANGE_JOIN` hint — and I'd set `crossJoin.enabled` to false in production so an accidental one fails loudly instead of running for a day.

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
| 4 | **Join Strategies (BHJ / SMJ / SHJ / BNLJ)** | ✅ | **A7.** Appears 4× in the PS bank |
| 5 | Memory Spill Management | 🔵 | Spot-eviction / shuffle-state finding touches this via A6 |
| 6 | Cluster Sizing & Selection | 🔵 | Four BUPA findings ready — see ammunition index |
| 7 | **Resource Utilization** | ✅ | **A6** — driver bottleneck + 10-scenario catalogue |
| 8 | **Photon & Vectorization** | ✅ | **A2** |
| 9 | **Heap Memory & GC** | 🟡 | S1 in A6 covers driver-heap GC in depth; on-heap/off-heap split and G1GC tuning knobs still unwritten |
| 10 | **Serverless Architecture** | ✅ | **A3** |

## Delta Lake & Ingestion (5)
| # | Topic | Status | Note |
|---|---|---|---|
| 11 | Delta Layout Optimization (Liquid vs Z-Order vs Predictive) | ⬜ | Appears 7× in the PS bank — **highest frequency of any topic** |
| 12 | **Delta Architecture Limitations (ACID limits, write conflicts)** | ✅ | **A4** — three stores/three clocks, full query set, sample output tables |
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
| 26 | **Data Reconciliation** | ✅ | **A5** — `exceptAll` internals + the one-sided-plus-count cost halving trick |
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
| 34 | **Performance Degradation (10 min → 2 hrs, no code change)** | ✅ | **A6** — full diagnostic order + 10-scenario catalogue covers this directly |
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

**Written 7 / 43** (A1–A7). **Ammunition already exists for 10 more** — see Part 3.

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
| `exceptAll` is a full shuffle of every column on both sides, disguised as a simple diff — cost tracks total row bytes moved, not how different the tables are | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance) | 26 |
| One-sided set difference (`B − A = ∅`) plus equal counts (same row totals) proves full two-sided equality at half the shuffle cost of running `exceptAll` both directions | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance) | 26 |
| Shuffle partition count is session-global, and AQE coalesces small partitions only *after* the shuffle write — a 10-file table still pays for planning against 2,048 partitions | **SL** | [§](../../../client_work/bupa_region_migration/SESSION_LEARNINGS.md#spark-execution-performance) | 2, 5 |

---

# Appendix — Known weak patterns to drill against

From KB, so drilling targets the measured gaps rather than what's comfortable:

**Spark internals — 3.5/10 self-test (2026-05-20).** Specific misses: didn't separate Unresolved vs Analyzed logical plan; conflated predicate pushdown with column pruning; named predicate pushdown as an **AQE** optimization (wrong — AQE is runtime-only by definition); missed `shuffle.partitions` tuning as the first fix for big joins; knew salting but missed AQE skew-join handling; couldn't read a physical plan. *A1's Step-4 breakdown addresses the pushdown/pruning conflation directly.*

**Concept-right / knob-wrong (2026-06-03, live round).** Chose the correct backfill pattern cold, then placed the `ONCE` flag in Auto Loader settings when it is flow-level. **This is why every answer here carries a Knob table.**

**Framework fluency above engine fluency (2026-05-20).** DLT/Delta API knowledge is deep; engine internals are the gate for this specific role. Order study accordingly — Spark Core first, Next-Gen Suite last.

---

*Format contract derived from KB `explanation_format_interview_prep` (2026-08-21) and `jargon_gap` (2026-09-02). Append answers, don't rewrite prior ones. Update the Part 2 coverage table with every addition.*
