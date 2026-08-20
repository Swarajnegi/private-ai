# Job Switch Roadmap 02 — Advanced SQL & Data Manipulation (6 weeks)

> **Goal:** Clear the "SQL & Data Manipulation" round — write a correct, efficient query under time pressure, *narrating your reasoning as you build it*, and debug a broken query someone hands you.
>
> **Why this matters:** SQL is the one round every single target company runs, at every level, without exception. It's also the round where you are closest to competent already — you write production SQL daily — which makes it the highest-return track per hour invested. The gap isn't capability; it's six specific, *measured* weak spots and the habit of explaining while you type.
>
> **Prerequisites:** Production SQL fluency. You have it. This roadmap assumes you can already write joins and aggregates without thinking.
>
> **Outcome:** All six known gaps closed to cold-solve-twice standard, plus a rehearsed narration habit and query-debugging reflexes.
>
> **Time budget:** ~4 hrs/week × 6 weeks. Runs in parallel with [Roadmap_01](Roadmap_01_DSA_Python_Coding.md) during weeks 1–6.

---

## The six known gaps — this roadmap's actual reason for existing

Two graded SQL self-tests on 2026-05-28 scored **~5/10 and ~5.5/10**. Not from missing knowledge — from six specific, repeatable failure modes. **These are not hypothetical weak spots; they are your measured ones**, and every phase below targets them directly.

| # | Gap | How it showed up | Status |
|---|---|---|---|
| 1 | **Gaps-and-islands** | Failed *twice* (Test#1 Q5, Test#2 NQ3). The "subtract `row_number` from date" / cumulative-sum-of-gap-starts trick is not internalized. | **Open** |
| 2 | **`WHERE` vs `HAVING` vs `GROUP BY`** | Wrote `GROUP BY dept HAVING salary_tier <= 2` for a *row-level* filter. Three-way vocabulary confusion. | **Open** |
| 3 | **Window `ORDER BY` tiebreakers** | Missed adding `order_id` as a tiebreaker inside a `LAG` window when the ordering column had ties → non-deterministic output. | **Open** |
| 4 | **Filter-reading discipline** | Missed a "completed orders only" filter in the prompt. Recurring across both tests. | **Open** |
| 5 | **Aggregate vs window function** | Used `AVG() OVER (PARTITION BY ...)` + `DISTINCT` where a plain `AVG() ... GROUP BY` was correct. | **Open** |
| 6 | **`COUNT(CASE ... ELSE 0)` trap** | `COUNT(CASE WHEN x THEN 1 ELSE 0 END)` counts *every* row, because `0` is not `NULL`. | **Open** |

**Closure standard: solved cold, correctly, twice, on different days.** Not "I understand it now" — that was already true after the first test, and gap #1 still failed on the second.

There's a documented pattern behind several of these: you reach for the correct *design pattern* cold but misplace the exact *knob or keyword* under pressure. That's a precision problem, not a comprehension problem, and it responds to drilling, not to reading.

---

## Phase 1 (Weeks 1–2) — Execution Semantics & the Filter Family

**What you'll learn**
- **Logical query processing order:** `FROM` → `JOIN` → `WHERE` → `GROUP BY` → `HAVING` → `SELECT` → `DISTINCT` → `ORDER BY` → `LIMIT`. Memorize this; it explains gaps #2 and #5 completely.
- **Why you can't reference a `SELECT` alias in `WHERE`** but can in `ORDER BY` — a direct consequence of the order above
- **`WHERE` vs `HAVING`:** row-level filter (before grouping) vs group-level filter (after aggregation). The rule: *if the condition doesn't involve an aggregate, it belongs in `WHERE`.* → **gap #2**
- **`GROUP BY` semantics:** what one output row represents, which columns are legal in `SELECT`, why the "bare column" rule exists
- **Aggregate vs window function:** `AVG() ... GROUP BY` collapses rows; `AVG() OVER (PARTITION BY ...)` preserves them and attaches the aggregate to each. Choosing the window form then killing duplicates with `DISTINCT` is a smell, not a solution. → **gap #5**
- **`COUNT` semantics:** `COUNT(*)` vs `COUNT(col)` vs `COUNT(DISTINCT col)`, and why `COUNT` ignores `NULL` but not `0`. The correct conditional-count idiom is `SUM(CASE WHEN x THEN 1 ELSE 0 END)` or `COUNT(CASE WHEN x THEN 1 END)` — **never** `COUNT(... ELSE 0)`. → **gap #6**
- **NULL semantics:** three-valued logic, `NULL = NULL` is unknown, `IS NULL`, `COALESCE`, `NULLIF`, how NULLs behave in aggregates, joins, `GROUP BY`, and `NOT IN` (the classic silent-empty-result bug)

**Why it matters**
Three of your six gaps (#2, #5, #6) collapse into a single root cause: not having the logical processing order internalized as the *first* thing you reason from. Fix the order, and the three fix themselves. This is also the highest-frequency interview material on the entire page — "what's the difference between WHERE and HAVING" is asked in probably a third of all SQL screens.

**Deliverable**
`SQL_01_Semantics_Filters.ipynb` — 12 questions concentrated on gaps #2, #5, #6: row-filter vs group-filter discrimination, conditional counting done three ways (one right, two wrong — identify which), aggregate-vs-window selection, and a set of NULL-behavior traps. Include at least three questions where the *naive* answer is wrong in a way that still returns rows.

**Topics to ask about** *(paste any into chat and I'll explain)*
- "Walk me through logical query processing order and what each step can and can't see"
- "`WHERE` vs `HAVING` — give me the one-line rule and three examples where it's ambiguous"
- "Why does `COUNT(CASE WHEN x THEN 1 ELSE 0 END)` count everything?"
- "When should I use a window function instead of `GROUP BY` — and when is it a mistake?"
- "Show me three ways `NULL` silently breaks a query"
- "Why does `NOT IN` with a NULL in the subquery return nothing?"

---

## Phase 2 (Weeks 2–4) — Window Functions, Properly

**What you'll learn**
- **Anatomy:** `func() OVER (PARTITION BY ... ORDER BY ... frame)` — each clause independently
- **Ranking family:** `ROW_NUMBER` vs `RANK` vs `DENSE_RANK` vs `NTILE` — behavior on ties is the whole question
- **Offset family:** `LAG`, `LEAD`, with `offset` and `default` arguments; `FIRST_VALUE`, `LAST_VALUE` (and why `LAST_VALUE` usually returns the wrong thing without an explicit frame)
- **Aggregate windows:** running totals, moving averages, `SUM() OVER (ORDER BY ...)` as a cumulative sum
- **Frame clauses:** `ROWS` vs `RANGE`, `UNBOUNDED PRECEDING`, `CURRENT ROW`, `N FOLLOWING`. The **default frame** when you specify `ORDER BY` but no frame is `RANGE UNBOUNDED PRECEDING TO CURRENT ROW` — this surprises people and silently changes results with ties
- **Tiebreakers — your gap #3:** any `ORDER BY` inside a window whose column has ties produces **non-deterministic output**. Always add a unique tiebreaker (`ORDER BY event_date, order_id`). This is a correctness bug that passes tests intermittently, which is the worst kind
- **Top-N-per-group:** the canonical `ROW_NUMBER()` + outer-filter pattern
- **Deduplication via `ROW_NUMBER`:** the standard DE idiom, directly transferable to your production work
- **Windows can't go in `WHERE`** — they're evaluated after it, hence the subquery/CTE wrap

**Why it matters**
The Google OA's SQL question was explicitly **join + aggregate + window function**. Windows are the dividing line between a SQL-competent candidate and a SQL-fluent one, and they carry two of your six gaps (#3, and #5's other half).

**Deliverable**
`SQL_02_Windows.ipynb` — 12 questions: rank-with-ties discrimination, top-N per group, running total, moving average with an explicit frame, `LAG` for period-over-period change, `LAG` where the ordering column has ties (**forced tiebreaker — gap #3**), first/last value with correct framing, dedup via `ROW_NUMBER`, cumulative distinct count, and two questions where the default frame silently gives a wrong answer.

**Topics to ask about**
- "`ROW_NUMBER` vs `RANK` vs `DENSE_RANK` on ties — show me the same data through all three"
- "What is the default window frame and when does it bite me?"
- "Why does `LAST_VALUE` usually return the current row?"
- "Hand-trace a `LAG` where the ORDER BY column has duplicate values"
- "Give me the top-N-per-group pattern and explain why the window can't go in `WHERE`"
- "How do I dedup a table with `ROW_NUMBER`?"

---

## Phase 3 (Weeks 4–5) — Gaps-and-Islands, CTEs, and Joins

**What you'll learn**

**Gaps-and-islands — gap #1, failed twice, gets its own dedicated block:**
- The **problem shape:** find consecutive runs (islands) or missing stretches (gaps) in a sequence — consecutive login days, uninterrupted sensor readings, unbroken streaks
- **Technique A — the row-number difference trick:** for consecutive integers or dates, `value - ROW_NUMBER() OVER (ORDER BY value)` is **constant within an island**. Group by that constant. Hand-trace this on 10 rows until it's obvious rather than magic
- **Technique B — the gap-flag cumulative sum:** mark each row where `value != LAG(value) + 1` as a new-island start, then `SUM()` those flags cumulatively to produce a group id
- **When each applies:** A is cleaner for dense integer/date sequences; B generalizes to arbitrary "is this a new group?" conditions (session boundaries with a 30-min timeout, status changes)
- The DE framing: **sessionization** is gaps-and-islands. So is streak calculation, downtime detection, and SCD2 validity-range building

**CTEs and subqueries:**
- `WITH` clauses, chaining multiple CTEs, readability as an interview signal in itself
- Correlated vs uncorrelated subqueries and the performance difference
- `EXISTS` vs `IN` vs `JOIN` for semi-join logic; when `NOT EXISTS` beats `NOT IN` (the NULL trap from Phase 1)
- **Recursive CTEs:** hierarchies (manager chains, category trees), date-series generation, the anchor + recursive-term structure

**Joins, past the basics:**
- `INNER` / `LEFT` / `RIGHT` / `FULL OUTER` / `CROSS`, and `SELF` joins for row-to-row comparison
- **Anti-join** (`LEFT JOIN ... WHERE right.key IS NULL`) — the "find records with no match" idiom
- **Fan-out:** joining to a table with duplicate keys silently multiplies rows and corrupts every downstream aggregate. Recognize it by row-count sanity checks
- Join order, filter placement (`ON` vs `WHERE` for outer joins — a real semantic difference, not style)
- Set operations: `UNION` vs `UNION ALL` (dedup cost), `INTERSECT`, `EXCEPT`

**Why it matters**
Gap #1 has now failed twice, which makes it the single most likely thing to sink a real SQL round. The join-fan-out material is the other high-stakes item — it produces *plausible wrong answers*, which are worse than errors because nothing tells you.

**Deliverable**
`SQL_03_Islands_CTEs_Joins.ipynb` — 14 questions, with **5 dedicated to gaps-and-islands** (consecutive login streaks, longest streak per user, sessionize events with a 30-minute timeout, find missing date ranges, detect uninterrupted status periods — solve at least two with *both* techniques). Plus: recursive CTE for a manager hierarchy, anti-join, a deliberate fan-out scenario to detect and fix, `EXISTS` vs `IN` with NULLs, and `UNION` vs `UNION ALL` cost.

**Topics to ask about**
- "Hand-trace the row-number-difference trick on 10 rows of dates with a gap"
- "Show me gaps-and-islands both ways on the same data"
- "How is sessionization the same problem as gaps-and-islands?"
- "Explain join fan-out and how I'd catch it in a query I didn't write"
- "`ON` vs `WHERE` for a LEFT JOIN filter — what's the semantic difference?"
- "Write a recursive CTE for a manager hierarchy and explain the anchor term"
- "`EXISTS` vs `IN` vs `JOIN` — when is each right?"

---

## Phase 4 (Weeks 5–6) — Query Efficiency, Debugging, and Narration

**What you'll learn**

**Efficiency (what the round actually grades):**
- Reading an execution plan at a conceptual level: scan vs seek, join algorithm, sort/aggregate steps, estimated vs actual rows
- **Predicate pushdown and partition pruning** — filter as early and as close to the source as possible
- **Column pruning** — `SELECT *` is a real cost on columnar storage, not a style preference
- Index basics: what a query needs to use one, why a function wrapped around a column (`WHERE YEAR(dt) = 2026`) kills index usage, and the sargable rewrite
- Why `DISTINCT` is often a symptom of a join bug rather than a requirement
- Common table scan → seek fixes, and when a rewrite beats an index

**Debugging a query you didn't write** (this is an explicitly-named focus area — *"query efficiency, debugging logic"*):
- A repeatable method: check the grain first (what does one row mean?) → check join keys for fan-out → check filter placement → check NULL handling → check aggregate/window choice
- Row-count sanity checks at each CTE boundary
- Narrowing by bisection: comment out CTEs and compare counts

**Narration — the graded success factor:**
The blueprint's stated success factor for this round is *"narrate reasoning, not just syntax."* The interviewer is scoring **how you decompose**, not whether you can type `JOIN`.
- Restate the requirement in your own words first — this catches gap #4 (filter-reading) before you write anything
- Announce the grain of your result set *before* writing the query: "one row per user per day"
- Build in CTE layers and say what each layer produces
- State assumptions out loud ("assuming order_id is unique; if not, I'd need to dedup first")
- Sanity-check aloud at the end: "let me verify the row count didn't multiply"

**Filter-reading discipline — gap #4:** before writing a single character, read the prompt twice and write the filters down as a list. Your misses (*"completed orders only"*) were never comprehension failures — they were reading-speed failures under pressure. The fix is mechanical: enumerate filters explicitly before starting.

**Why it matters**
This phase converts SQL correctness into SQL *performance in an interview*, which are different skills. It also closes gap #4, which is the cheapest of the six to fix and the one most likely to cost you an otherwise-perfect answer.

**Deliverable**
`SQL_04_Debugging_Narration.ipynb` — 10 broken queries to diagnose and fix (each seeded with one specific bug: fan-out, wrong filter placement, missing tiebreaker, `COUNT ... ELSE 0`, `NOT IN` with NULLs, wrong grain, `HAVING` used for a row filter, missing `DISTINCT` where genuinely needed, non-sargable predicate, silently wrong default frame). Plus: for 3 questions from earlier notebooks, **record yourself narrating** the full build and play it back.

**Topics to ask about**
- "Give me a repeatable method for debugging a query I didn't write"
- "What makes a predicate sargable and why does `WHERE YEAR(dt) = 2026` hurt?"
- "How do I detect fan-out without knowing the data?"
- "What does 'grain' mean and how do I state it before writing a query?"
- "Walk me through reading an execution plan at a conceptual level"
- "Give me an unseen SQL question and grade my narration, not just my answer"

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| HackerRank SQL track (Advanced) | Explicitly named as the OA calibration bar. Do the Advanced Select + Aggregation + Join sections |
| LeetCode SQL 50 | Tighter, interview-shaped; heavy on windows and top-N-per-group |
| DuckDB (local, zero setup) | Run every notebook here — no cluster, no cloud, no cost. `pip install duckdb` |
| PostgreSQL docs — Window Functions | The clearest official treatment of frames and ordering. Read it once, fully |
| *SQL for Data Analysis* (Tanimura), Ch. 3–4, 6 | Windows and time-series patterns, including sessionization |

**Deliberately excluded:** vendor-specific tuning guides, stored-procedure/PL-SQL material, and NoSQL query languages. None appear in a DE SQL round at this tier.

---

## Checkpoints (self-assess at each)

- **End of Week 2:** State the logical query processing order from memory. Explain `WHERE` vs `HAVING` in one sentence with an example. **Gaps #2, #5, #6 solved cold, twice, on different days.**
- **End of Week 4:** Write the top-N-per-group pattern from memory, first try. Explain the default window frame and when it's wrong. **Gap #3 closed** — every window `ORDER BY` you write includes a tiebreaker automatically, without thinking about it.
- **End of Week 5:** **Gap #1 closed** — solve two unseen gaps-and-islands problems cold, using both techniques, on two different days. This is the checkpoint that has failed twice before; treat it as the roadmap's real gate.
- **End of Week 6:** Take a fresh 10-question mixed SQL test (ask me to generate one) — **target 8.5/10**, versus the 5/10 and 5.5/10 baselines. Narrate one full solve on tape and play it back. **Gap #4 closed** — you write the filter list before the query, every time.

---

## How to use this file

1. Work the phases in order. Phase 1's processing order is what makes Phases 2–4 make sense.
2. **The six gaps are the point of this roadmap.** A phase isn't done because you read it — it's done when its gaps are solved cold, twice, on different days. Gap #1 already survived one round of "I understand it now."
3. Run everything in **DuckDB locally** — zero setup, zero cost, and it supports the full window-function and recursive-CTE surface.
4. Pick any **Topic to ask about** and paste it into chat.
5. Ask me to generate fresh test notebooks whenever you want a cold assessment — new questions each time, calibrated against these six gaps first.
6. Narrate out loud on at least one problem per session, from Week 1. The round grades reasoning, not syntax, and narration is a rehearsed skill.
