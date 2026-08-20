# Job Switch Roadmap 03 — Data Modeling & Architecture (5 weeks)

> **Goal:** Clear the "Data Modeling & Architecture" round — take a vague business requirement, turn it into a schema out loud, and defend every choice under follow-up questioning.
>
> **Why this matters:** The blueprint's stated test for this round is *"translating business into structure"* and its success factor is *"explain trade-offs clearly."* Neither is about knowing what a star schema is. Both are about **defending a design while someone attacks it** — which is a rehearsable skill you have never rehearsed, because consultancy work hands you the source model already built. You've spent two years building *downstream* of someone else's entity model.
>
> **Prerequisites:** SQL fluency ([Roadmap_02](Roadmap_02_Advanced_SQL.md) runs in parallel; no dependency). Production ETL experience — you have it.
>
> **Outcome:** Two designed-from-scratch schemas with written justifications, and rehearsed answers for the standard attack questions.
>
> **Time budget:** ~4 hrs/week × 5 weeks. Runs weeks 1–5, in parallel with Roadmaps 01 and 02.

---

## The gap this closes, stated honestly

Every model you've worked on — Apollo, LRC, PeopleSoft, BUPA — started from an **existing** source schema. The ERP, the D365 instance, or the API handed you entities and you built pipelines downstream. That is real, valuable experience, and it is **not** what this round tests.

This round tests: *"A product manager says users complain that the analytics dashboard is slow and they can't see refunds by region. Design the data model."* No entities handed to you. No source system to mirror. You choose the grain, the dimensions, the SCD strategy, and then you justify each one against an interviewer who will push back on all three.

The named red flags for this round map exactly onto that gap:
- *Are they applying theory in practical projects?* — connect every concept to something you actually built
- *Evaluating all the edge cases* — late-arriving data, deletes, key changes
- *Approach to how they're solving* — the process is graded, not just the destination
- *Not talking about security and scalable considerations* — one sentence, always
- *Not mentioning automation / CI-CD* — one sentence, always

The last two are free points and among the most commonly forgotten.

---

## Phase 1 (Week 1) — Relational Foundations & ER Modeling

**What you'll learn**
- **Entity-Relationship modeling:** entities, attributes, relationships; cardinality (1:1, 1:N, M:N) and optionality; how an M:N resolves into a junction table
- **Keys:** primary, candidate, composite, foreign, natural vs surrogate; why a natural key that "will never change" always eventually changes
- **Normalization, worked concretely:**
  - **1NF** — atomic values, no repeating groups
  - **2NF** — no partial dependency on part of a composite key
  - **3NF** — no transitive dependency (non-key attribute depending on another non-key attribute)
  - **BCNF** — enough to name it and say when it differs from 3NF
  - **Denormalization** — deliberate, for read performance, with the write-side cost stated
- **Anomalies normalization prevents:** insert, update, delete anomalies — with a concrete before/after example for each
- **OLTP vs OLAP:** row-store vs column-store, normalized vs dimensional, many small writes vs few huge reads, index strategy differences, why the same data ends up modeled twice
- **Theory of SQL as the interviewer means it:** relational algebra basics (selection, projection, join, union), set semantics vs bag semantics, ACID properties, isolation levels at a nameable level

**Why it matters**
"Theory of SQL" and "ER concepts" are both explicitly on the interviewer expectations list, separately from "Advanced SQL coding." That's a signal: they want the *conceptual* layer, not just the query layer. And normalization is the most common opening question of the whole round because it's a fast competence filter — a candidate who fumbles 3NF gets a shorter, easier interview, which is not what you want.

**Deliverable**
Take a messy, deliberately-unnormalized table (an orders sheet with customer name, address, product list, and prices all inline) and normalize it to 3NF on paper. Draw the ER diagram. Then write two paragraphs: what anomalies were possible before, and what a query now costs that didn't before. **Then denormalize one part on purpose** and justify it.

**Topics to ask about** *(paste any into chat and I'll explain)*
- "Walk me through 1NF → 2NF → 3NF on one concrete table, showing what moves at each step"
- "Give me a concrete insert/update/delete anomaly and how normalization kills it"
- "Natural vs surrogate keys — when has a natural key burned someone?"
- "OLTP vs OLAP — why do we model the same data twice?"
- "What is BCNF and when does it differ from 3NF?"
- "Explain ACID and isolation levels at the level an interviewer expects"

---

## Phase 2 (Weeks 1–2) — Dimensional Modeling

**What you'll learn**
- **Facts and dimensions:** what belongs in each; measures vs attributes; the "verbs vs nouns" heuristic and where it breaks
- **Grain — the single most important decision:** what exactly one fact row represents, stated as one sentence before anything else is designed. *"One row per order line item per shipment event."* Every downstream mistake traces back to a fuzzy grain
- **Fact table types:** transaction (one row per event), periodic snapshot (one row per entity per period), accumulating snapshot (one row per process instance, updated as it progresses); factless fact tables
- **Measure additivity:** fully additive, semi-additive (balances — sum across products but not across time), non-additive (ratios, percentages — store the numerator and denominator instead)
- **Dimension design:** attributes, hierarchies, conformed dimensions shared across facts, degenerate dimensions (an order number living on the fact), junk dimensions, role-playing dimensions (one date dimension referenced as order_date, ship_date, return_date)
- **Star vs snowflake:** star denormalizes dimensions for fewer joins; snowflake normalizes them. Star is the default for analytics; snowflake is defensible for very large, genuinely hierarchical dimensions or where storage dominates
- **One Big Table (OBT):** when a flat wide table beats a star — columnar storage, small dimension counts, BI tools that can't join well. Know when to reach for it and when it's laziness
- **Surrogate keys in a warehouse:** why the fact table shouldn't carry business keys, and how SCD2 makes surrogates mandatory rather than optional

**Why it matters**
This is the vocabulary of the round. Being able to say "the grain is one row per trip" before you draw anything signals seniority faster than any other single sentence. Interviewers listen for grain specifically, because candidates who skip it produce designs that fall apart three questions later.

**Deliverable**
**Design #1, from a business problem, not a source schema.** Pick one: an e-commerce refunds-and-returns dashboard, or a ride-hailing trips analysis. Write:
1. Three business questions the model must answer
2. The grain statement — one sentence, explicit
3. Fact table(s) with measures and their additivity classified
4. Dimensions with attributes and hierarchies
5. A drawn star schema
6. **Three trade-offs you rejected and why** — this section is what the round actually grades

**Topics to ask about**
- "How do I pick a grain? Give me three examples of picking it wrong and what broke"
- "Transaction vs periodic vs accumulating snapshot facts — one example of each"
- "What's a semi-additive measure and how do I handle it in a query?"
- "Star vs snowflake — when is snowflake actually right?"
- "When is One Big Table the correct answer over a star schema?"
- "What are role-playing and junk dimensions?"

---

## Phase 3 (Weeks 2–3) — Slowly Changing Dimensions

**What you'll learn**
- **The problem SCDs solve:** a customer moves from Delhi to Bengaluru. Do last year's sales now report under Bengaluru? The answer is a *business* decision, and picking without asking is the mistake
- **Type 0** — retain original, never update (immutable attributes like date-of-birth, original signup source)
- **Type 1** — overwrite. No history. Simple, cheap, and destroys the ability to report historically. Correct for corrections (fixing a typo in a name)
- **Type 2** — new row per change, with `valid_from` / `valid_to` / `is_current` and a new surrogate key. The workhorse. Preserves full history; grows the dimension; requires every fact to join on the surrogate valid at event time
- **Type 3** — add a column (`previous_region`). Tracks exactly one prior value. Niche: use when the business cares about "before and after one specific reorg"
- **Type 4** — mini-dimension / history table split: rapidly-changing attributes moved to their own dimension
- **Type 6** — the hybrid (1+2+3): a Type 2 row that also carries a current-value column, so you can report both "as-was" and "as-is" without a second join
- **Implementation mechanics:** change detection (hash the tracked columns and compare), the merge/upsert pattern, handling multiple changes arriving in one batch, and **sequencing** — what happens when two updates to the same key land in the same load
- **Edge cases that get asked:** late-arriving dimension rows (fact arrives before its dimension), late-arriving facts (event timestamp predates the current dimension version), hard deletes in the source, and key reuse in the source system

**Why it matters**
"Slowly changing dimension (SCD) tables" is called out by name on the interviewer expectations list — the only modeling topic specific enough to be named individually. You've implemented SCD2 in production (AUTO CDC / `sequence_by` / `__START_AT`-`__END_AT` patterns), which means you can answer this from lived experience rather than theory. That is a strong position — provided you can also explain *why you chose Type 2 there*, which is the follow-up.

**Deliverable**
For your Design #1 dimensions, assign an SCD type to **each** dimension with a one-line business justification. At least one must be Type 2 and at least one Type 1, and you must be able to argue why the reverse would be wrong. Then write the Type 2 merge logic in SQL — the full upsert: close the old row, insert the new one, handle the no-change case.

**Topics to ask about**
- "SCD Types 0 through 6 — one concrete business example each"
- "Write the SCD Type 2 merge and explain the close-then-insert ordering"
- "How do I detect changes efficiently across 200 columns?"
- "Two updates to the same key in one batch — what breaks and how do I fix it?"
- "What's a late-arriving dimension and what are my options?"
- "How do I handle a hard delete in the source system?"

---

## Phase 4 (Weeks 3–4) — Data Quality, Lineage, Monitoring

**What you'll learn**
- **The quality dimensions**, named and measurable: completeness, uniqueness, validity, accuracy, consistency, timeliness. Being able to *name* them is what separates "we had some tests" from a real answer
- **Where checks live:** at ingestion (schema/type/nullability), post-transform (business rules, referential integrity), pre-publish (reconciliation against source counts and control totals)
- **Enforcement policy — the actual design decision:** warn (log and continue) vs quarantine (route bad rows to a side table) vs fail (abort the load). Each is correct in different situations, and knowing *when* is the signal. A dashboard feed warns; a financial reconciliation fails
- **Data contracts:** an explicit producer-consumer agreement on schema, semantics, and SLA; why contracts move quality left instead of catching it downstream
- **Reconciliation:** row counts, control totals, hash comparisons against source; the "did we lose rows?" check that catches most real incidents
- **Lineage:** column-level vs table-level; why it matters for impact analysis ("if I change this column, what breaks?") and for root-cause during an incident
- **Monitoring and alerting mechanisms:** freshness SLAs, volume anomaly detection (today's row count vs the trailing average), null-rate drift, distribution drift, schema drift alerts, job success/failure and duration trends
- **Alert design:** thresholds vs anomaly detection, alert routing, and — critically — **avoiding alert fatigue**. An interviewer will respect "we tuned it down after the team started ignoring it" more than a list of every metric you monitor
- **Runbooks and on-call:** what happens *after* the alert fires. This is the part most candidates omit entirely

**Why it matters**
"Data Quality" and "Alert and Monitoring mechanism" are both named on the expectations list, and they're where consultancy experience genuinely shines — you have production incidents to draw on. The trap is describing tooling ("we used Great Expectations") instead of *decisions* ("we quarantined rather than failed because the downstream dashboard tolerated gaps but not outages"). Interviewers grade the decision.

**Deliverable**
For Design #1, write a one-page quality and monitoring plan: the checks at each stage, the enforcement policy per check with justification, the freshness SLA, the alerts and their thresholds, and what the runbook says when each alert fires. Then map each item to a **real incident** you've handled — that mapping is your talk-track for this round.

**Topics to ask about**
- "Name the data quality dimensions and give me a check for each"
- "Warn vs quarantine vs fail — how do I decide?"
- "What is a data contract and how is it different from a schema?"
- "How do I detect volume anomalies without alerting every Monday?"
- "Column-level vs table-level lineage — when do I need column-level?"
- "What goes in a runbook for a freshness alert?"

---

## Phase 5 (Weeks 4–5) — ETL/ELT Patterns & Defending the Design

**What you'll learn**

**ETL vs ELT:**
- The actual difference (where transformation compute happens) and why ELT won for cloud warehouses — separation of storage and compute, and the warehouse being the cheapest place to transform
- When ETL is still correct: PII that must be masked before it lands, heavy transformation the warehouse handles poorly, source-side aggregation to cut transfer volume
- Layered architecture: raw/landing → cleaned/conformed → curated/serving. The naming varies by shop; the *reasons for the layers* don't
- Idempotent loads and re-runnability: why every pipeline must survive being run twice
- Load patterns: full refresh, incremental append, merge/upsert, CDC — and how to choose

**Defending the design — the rehearsal that this whole roadmap builds to:**
The round is a conversation, not a diagram. Practice answering these while someone pushes back:
- "Why this grain and not one level finer?"
- "What happens when this dimension gets 50 million rows?"
- "The business now wants to report by a hierarchy you didn't model. What changes?"
- "How do you handle a late-arriving fact from three months ago?"
- "This query is slow now. What did you get wrong at design time?"
- "Why Type 2 here and Type 1 there?"
- "How would you migrate this model without downtime?"

**The two free-point sentences, never skipped:**
- **Security:** PII columns identified, masking or tokenization strategy, row-level access by region or role, encryption at rest and in transit, audit access to sensitive dimensions. One or two sentences, unprompted.
- **Automation / CI-CD:** version-controlled model definitions, tested transformations, automated deployment across environments, schema-change review in a pull request. One or two sentences, unprompted.

Both are on the red-flag list as commonly-forgotten omissions. Neither takes more than 20 seconds to mention.

**Why it matters**
This phase turns knowledge into a *performance*. You will know the material by now; the round grades whether you can hold a design under pressure, change it gracefully when a requirement shifts, and volunteer the considerations nobody asked about.

**Deliverable**
**Design #2, timed — 45 minutes, from a cold prompt, out loud, recorded.** Pick a domain you haven't modeled (subscription billing, content streaming, logistics tracking). Produce: business questions → grain → star schema → SCD assignments → quality plan → security and CI-CD note. Then play the recording back and mark every place you went silent, hedged, or skipped a justification.

Then ask me to red-team both designs. Paste them into chat and I'll attack them the way an interviewer would.

**Topics to ask about**
- "ETL vs ELT — when is ETL still the right call in 2026?"
- "Why does every pipeline need to be idempotent, and how do I make a merge idempotent?"
- "Red-team my star schema" *(paste the design)*
- "The business changed the requirement mid-interview — how do I adapt without restarting?"
- "What security considerations belong in a modeling answer?"
- "How do I migrate a live dimensional model without downtime?"

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| *The Data Warehouse Toolkit* (Kimball, 3rd ed) — Ch. 1–5 | The canonical dimensional-modeling text. **Only these chapters** — the rest is industry case studies you don't need |
| *Designing Data-Intensive Applications* (Kleppmann) — Ch. 2, 3 | Data models and storage engines; the OLTP-vs-OLAP contrast done properly |
| dbt docs — "How we structure our dbt projects" | The modern layering convention (staging → intermediate → marts) in one readable page |
| Your own production work | Apollo, LRC, PeopleSoft, BUPA — the source of every concrete example you'll give. Worth more than any book here |

**Deliberately excluded:** Data Vault and Anchor Modeling (rarely asked at this level; know only that they exist and are for auditability-heavy enterprise environments), and vendor-specific modeling guides.

---

## Checkpoints (self-assess at each)

- **End of Week 1:** Normalize an unnormalized table to 3NF on paper, and explain each step's anomaly-prevention out loud in under 3 minutes.
- **End of Week 2:** State a grain in one sentence for three different business problems, cold, in under 60 seconds each. Design #1's star schema is drawn with the rejected-trade-offs section written.
- **End of Week 3:** Explain all SCD types with a business example each, in under 3 minutes. Write the Type 2 merge from memory.
- **End of Week 4:** Present Design #1's quality and monitoring plan, mapping each check to a real incident from your production experience.
- **End of Week 5:** **Design #2 completed cold in 45 minutes, recorded.** Survive a red-team pass with fewer than three "I hadn't considered that" moments. Both free-point sentences (security, CI-CD) delivered unprompted.

---

## How to use this file

1. Phases 1–2 are knowledge; Phases 3–5 are rehearsal. Don't skip the rehearsal half — it's the part the round actually grades, and it's the part you've never practiced.
2. **Say the grain out loud before drawing anything.** Build this reflex from Week 2; it is the single strongest seniority signal in this round.
3. Every concept you learn, immediately attach it to something you actually built. *Applying theory only in the abstract* is a named red flag, and you have four real projects to draw from.
4. Pick any **Topic to ask about** and paste it into chat.
5. Ask me to red-team any design before you consider it done. Finding the holes here costs nothing; finding them in the round costs the offer.
6. End every design answer with the security sentence and the CI-CD sentence. They are free points and they are commonly forgotten.
