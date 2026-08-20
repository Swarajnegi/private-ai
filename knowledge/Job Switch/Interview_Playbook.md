# Interview Playbook — Product-Company Data Engineer Switch

> **What this file is:** the map. It holds the interview *process* — which rounds exist, what each one tests, what gets you rejected — and points at the five roadmaps in this folder that close each gap. Read this first, then pick a roadmap.
>
> **What this file is NOT:** a study roadmap. No topics to learn here. The learning lives in `Roadmap_01` through `Roadmap_05`, all in this folder, all self-contained.
>
> **Calibration:** Data Engineer, ~2 years experience at time of applying. Target tier: Google / Microsoft / Adobe / Cisco India, plus any product company running a comparable loop.

---

## The hard timeline (read this before planning anything)

| Date | Event | Source |
|---|---|---|
| **2027-04-22** | Service Commitment Period ends. Resigning before this = ~₹2.2L liability (₹1.5L + 50% of trainee stipend). | Mutual Service Agreement, signed 2026-04-16 |
| **~2027-07-22** | Earliest actual last working day. Notice is a flat 3 months, mandatory, and runs *only after* the SCP completes — not concurrent. | Same |
| **~2027-04** | You hit ~2 YOE. Coincides almost exactly with SCP end. | — |

**The non-obvious consequence:** you do not have until April 2027 to prepare. Google and Microsoft loops run **6–12+ weeks** from application to offer, and offer-to-join negotiation adds more. Working backwards from wanting a signed offer around **March–April 2027**, applications go out by **December 2026**.

> **Prep window that actually matters: mid-Aug 2026 → end of Nov 2026. ~16 weeks.**

That is why the roadmaps in this folder run in **parallel**, not in sequence. See the schedule at the bottom.

---

## Target companies — and the honest caveat

The shortlist under consideration: **Google India, Microsoft India, Adobe India, Cisco Systems**.

**This list came from a generic listicle, and one of its claims is already known to be wrong.** Real employee-review research (Blind / Glassdoor threads, not official rankings) run on 2026-07-20 found:

| Company | Real-review status |
|---|---|
| Adobe India | **MIXED / team-dependent.** Threads contradict each other; one team reported 7am–11pm hours. The listicle's "best work-life balance in tech" claim is not corroborated. |
| Google India | **Unverified.** Never checked against real threads — only against listicles. |
| Microsoft India | **Unverified.** Same. |
| Cisco Systems | **Unverified.** Same. |
| Salesforce India | Strongest real-review-grounded pick from the earlier research. Not on the current list. |
| Intuit India | Surfaced unprompted in genuine WLB discussion threads. Not on the current list. |
| Atlassian India | **Was** assumed good on async-culture reputation; real threads show it became a PIP shop since 2022. Proof that reputations shift and listicles lag. |

**The meta-lesson, repeated across every independent source:** WLB in Indian tech is **team- and manager-dependent far more than company-dependent**. Brand tells you almost nothing.

**Action items regardless of which company:**
- Re-verify Google / Microsoft / Cisco against *current* Blind and Glassdoor threads before final rounds — not before applying, but before accepting.
- In every onsite, ask directly: on-call rotation, average hours in the last quarter, recent reorgs or layoffs on this specific team.
- Treat any offer as an offer from a *team*, not a company.

---

## The FAANG data-interview blueprint — 5 rounds

The general shape most product companies converge on:

| Round | Focus areas | What they actually test | Success factor |
|---|---|---|---|
| **SQL & Data Manipulation** | Query efficiency, debugging logic | Edge-case handling, logical flow | Narrate reasoning, not just syntax |
| **Data Modeling & Architecture** | Schema design, scalability | Translating business into structure | Explain trade-offs clearly |
| **System Design for Data** | Pipeline design, ingestion, storage | End-to-end architecture thinking | Balance cost, latency, reliability |
| **Scenario / Behavioral** | Collaboration, ownership | Clarity, leadership, accountability | Connect tech to impact stories |
| **Bar Raiser** | Strategic alignment | Big-picture reasoning | Blend depth + context + composure |

Note what's being tested in every single row: **not knowledge — reasoning made visible**. Three of five success factors are about *how you talk*, not what you know. That is the single highest-leverage insight on this page.

---

## The Google DE loop — 6 rounds, concrete

A real teardown of the Google Data Engineer loop, with the actual questions asked:

### Round 1 — Online Assessment (DSA + SQL + Python)
- **DSA:** a sliding-window question.
- **SQL:** join + aggregate + window function.
- **Python:** detect schema anomalies in logs.
- **Calibration tip given:** LeetCode Medium + HackerRank SQL is the right practice bar.
- → **Roadmap_01** (DSA/Python) + **Roadmap_02** (SQL)

### Round 2 — Data Engineering Round
- Design an ETL from an external API into BigQuery.
- Follow-ups: schema evolution, Airflow scheduling, query optimization.
- Tips flagged: failure handling, retry, partitioning.
- → **Roadmap_04** (System Design), **Roadmap_03** (Modeling)

### Round 3 — Coding Round
- Process GBs of a log file to get the top 10 users — as a **stream**, not loaded into memory.
- Follow-up: handle a schema change midway through the file.
- Tips flagged: generators, external sorting.
- → **Roadmap_01 Phase 5** (this is exactly the DE-flavored coding phase)

### Round 4 — System Design
- Design a real-time clickstream pipeline.
- Follow-ups: fault tolerance, deduplication, efficient storage.
- Tips flagged: Pub/Sub, Kafka, Dataflow, BigQuery, Z-ordering.
- → **Roadmap_04**

### Round 5 — Behavioral + Googliness
- Ownership of a failing project. Conflict with a PM.
- Framing expected: STAR format, humility, growth mindset.
- → **Roadmap_05**

### Round 6 — Hiring Manager
- Project deep dive. How you'd onboard a junior. Metrics.
- → **Roadmap_05**

---

## What interviewers expect you to have

The full expectations checklist, grouped. Use as a coverage audit — every line should map to a roadmap you've actually finished.

**1. Fundamental technical skills**
- Python coding → R01
- Advanced SQL coding → R02
- Code optimization → R01, R02
- Cloud services → R04
- AI concepts → *(see note below)*

**2. Data engineering basic concepts**
- Theory of SQL → R02
- ETL / ELT processing → R03
- Data modeling → R03
- ER concepts → R03
- Data quality → R03
- Alerting and monitoring mechanisms → R03
- Slowly changing dimension (SCD) tables → R03

**3. Data infrastructure**
- Scalability → R04
- Real-time processing → R04
- Data storage optimization → R04
- Infrastructure efficiency → R04
- Handling differently-structured data → R04
- Trade-off discussions → R04, and every round

**4. Mock interview with a professional**
- Behavioral questions in STAR format → R05

> **Note on "AI concepts":** appearing on DE expectation lists as of 2026 — expect light questions on embeddings, vector stores, RAG pipelines, and how a data platform feeds ML/LLM workloads. Not a deep-learning interview. You already have unusually strong coverage here from JARVIS work (embeddings, ChromaDB, hybrid search, reranking, agent orchestration) — this is a *strength to deploy*, not a gap to close, and it doubles as a differentiating talk-track. No roadmap needed; just be ready to describe it in 90 seconds.

---

## Red flags — the pre-interview self-audit

These get you rejected even when your technical answer is right. Run this list before every round.

### Communication
- [ ] **Unclear explanations.** Can a non-expert follow your answer's shape?
- [ ] **Not asking clarifying questions.** Silence before diving in reads as "doesn't gather requirements."
- [ ] **Sharing the same 2–3 stories across the entire loop.** The single most-cited behavioral failure. → R05 builds 8–10 distinct stories specifically to kill this.

### Problem-solving approach
- [ ] **Jumping to solutions.** Say the requirements back before you design anything.
- [ ] **Missing metric / outcome.** Every story and every design ends with a number.
- [ ] **Missing edge cases.** Enumerate them out loud, unprompted.
- [ ] **"Did you propose it or implement it?"** Be explicit about your own scope vs the team's.

### Project understanding
- [ ] **Unable to give specific information.** Vague = didn't really do it.
- [ ] **Fails to give the project's overall impact.** Why did the business care?
- [ ] **Talking about fake numbers.** Interviewers probe. Dig up real figures from your actual projects; never invent one. A real "we cut runtime 90 min → 12 min" beats an invented "improved performance by 10x" that collapses under one follow-up.

### Data modeling & architecture
- [ ] **Applying theory only in the abstract** — tie every concept to something you actually built.
- [ ] **Not evaluating edge cases** in the design.
- [ ] **Not showing your thinking approach** — the process is graded, not just the answer.
- [ ] **Not mentioning security and scalability considerations.**
- [ ] **Not mentioning automation / CI-CD.**

The last two are pure free points. They cost one sentence each and are among the most commonly forgotten.

---

## Round → roadmap coverage map

| Interview round | Primary | Supporting |
|---|---|---|
| Online Assessment | **R01** DSA & Python | **R02** SQL |
| SQL & Data Manipulation | **R02** SQL | — |
| Coding (DE-flavored) | **R01** Phase 5 | — |
| Data Modeling & Architecture | **R03** Modeling | **R04** |
| Data Engineering Round | **R04** System Design | **R03** |
| System Design for Data | **R04** System Design | — |
| Scenario / Behavioral | **R05** Behavioral | — |
| Bar Raiser | **R05** Behavioral | all technical roadmaps |
| Hiring Manager | **R05** Behavioral | **R03**, **R04** |

Every round is covered by a roadmap in this folder. Nothing here depends on files outside it.

---

## The 16-week parallel schedule

Mid-Aug 2026 → end of Nov 2026. Start applying December 2026.

| Weeks | R01 DSA | R02 SQL | R03 Modeling | R04 Sys Design | R05 Behavioral |
|---|---|---|---|---|---|
| **1–4** | Phase 0–1 | Phases 1–2 | Full run | — | mine stories in background |
| **5–8** | Phase 2–3 | Phase 3 | — | Phases 1–3 | — |
| **9–13** | Phase 4 | — | — | Phases 4–7 | draft + metric hunt |
| **14–16** | Phase 5 | — | — | mocks | rehearsal + mocks |

**Total load: ~12–15 hrs/week.** Realistic alongside a full-time Celebal workload, but only if DSA is treated as a **daily** habit (45–60 min) rather than a weekend block. The other tracks rotate.

**Non-negotiables:**
- DSA runs every single week for all 16. It is the longest-lead skill and the one you're starting from zero on.
- Behavioral story-mining starts in Week 1 even though the roadmap runs W10–16 — you need months of noticing which projects produced real numbers, not a weekend of trying to remember.
- If you fall behind, cut R03 depth before cutting R01 or R04. Modeling is the most recoverable from first principles under interview pressure; DSA and system design are not.

---

## The roadmaps in this folder

| File | Covers | Weeks |
|---|---|---|
| [Roadmap_01_DSA_Python_Coding.md](Roadmap_01_DSA_Python_Coding.md) | Python fluency, arrays/strings, hashmaps, stacks/queues, sliding window, DE-flavored coding | 16 |
| [Roadmap_02_Advanced_SQL.md](Roadmap_02_Advanced_SQL.md) | Window functions, joins, CTEs, query debugging + your 6 known gaps | 6 |
| [Roadmap_03_Data_Modeling_Architecture.md](Roadmap_03_Data_Modeling_Architecture.md) | ER/normalization, dimensional modeling, SCD, data quality, monitoring | 5 |
| [Roadmap_04_System_Design_For_Data.md](Roadmap_04_System_Design_For_Data.md) | Ingestion, processing, storage, schema evolution, reliability, trade-offs | 8 |
| [Roadmap_05_Behavioral_Bar_Raiser.md](Roadmap_05_Behavioral_Bar_Raiser.md) | STAR story bank, metrics discipline, Googliness, Bar Raiser, HM round | 6 |

Practice notebooks live alongside them: `DSA_NN_*.ipynb`, `SQL_NN_*.ipynb`.

---

## How to use this file

1. **Re-read the red-flags audit before every single round.** It is the highest ratio of outcome-change to time-spent on this page.
2. **Check the coverage map** when you get a real interview scheduled — it tells you which roadmap to cram.
3. **Update the company table** as you verify WLB claims. Treat every unverified row as unverified until you've read current threads yourself.
4. **Don't let this file grow into a roadmap.** Process and maps here; learning content stays in the numbered files.
