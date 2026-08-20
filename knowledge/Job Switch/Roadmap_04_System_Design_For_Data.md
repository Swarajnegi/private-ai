# Job Switch Roadmap 04 — System Design for Data (8 weeks)

> **Goal:** Given a one-sentence prompt like *"design a near real-time pipeline for global user activity,"* run a structured 45-minute design conversation — requirements, capacity, architecture, deep dive, trade-offs — without freezing and without jumping straight to naming tools.
>
> **Why this matters:** This round appears **twice** in the Google loop (the DE round and the System Design round) and once in every other company's. Its stated test is *"end-to-end architecture thinking"* and its success factor is *"balance cost, latency, reliability."* Note what's absent: correctness. There is no right answer — you are graded on whether you reason about trade-offs like someone who has operated a system at scale.
>
> **Prerequisites:** [Roadmap_03](Roadmap_03_Data_Modeling_Architecture.md) Phases 1–3 (grain, dimensional modeling, SCD) — the storage-layer discussions assume that vocabulary. Production pipeline experience, which you have.
>
> **Outcome:** Three full written designs against real interview prompts, a rehearsed answering framework, and defensible numbers for capacity estimation.
>
> **Time budget:** ~4–5 hrs/week × 8 weeks. Runs weeks 5–13, after Roadmap_03 has laid the modeling foundation.

---

## The three anchor questions

Everything in this roadmap builds toward answering these three. They are **real questions from real loops**, not invented practice prompts. Return to them at the end of every phase and answer them again with the new material folded in.

**Anchor 1 — Global user activity (near real-time)**
> *Design a near real-time data pipeline to track global user activity. Data arrives from multiple regions with different latency and schema versions. How would you design for scalability, consistency, and cost?*

Note what's embedded: multi-region, heterogeneous latency, **schema version skew across producers**, and an explicit demand to address three competing properties. This is the hardest of the three.

**Anchor 2 — Real-time clickstream**
> *Design a real-time clickstream pipeline.* Follow-ups: fault tolerance, deduplication, efficient storage. Tools flagged: Pub/Sub, Kafka, Dataflow, BigQuery, Z-ordering.

**Anchor 3 — External API → BigQuery ETL**
> *Design an ETL from an external API into BigQuery.* Follow-ups: schema evolution, Airflow scheduling, query optimization. Tips flagged: failure handling, retry, partitioning.

Anchor 3 is the most likely to appear and the easiest to under-prepare for, because it looks mundane. It isn't — the follow-ups are where it's scored.

---

## Phase 1 (Weeks 1–2) — The Answering Framework

**This phase is worth more than the next six combined.** Most candidates fail this round on process, not knowledge — they hear "design a clickstream pipeline" and immediately say "Kafka into Spark into a lakehouse," which reads as pattern-matching rather than engineering. *Jumping to solutions* is a named red flag, and it's the most common one in this round.

**What you'll learn**

**The five-stage structure. Say the stage names out loud as you move through them** — it makes your process legible, which is the thing being graded:

1. **Requirements (5–8 min).** Never skip, never rush.
   - *Functional:* what questions must this answer? Who consumes it, and how? Dashboard, ML features, alerting, ad-hoc?
   - *Non-functional:* what does "near real-time" mean here — 1 second, 1 minute, 15 minutes? Each implies a completely different architecture, and the interviewer usually hasn't decided. Ask.
   - *Scale:* events/sec, peak vs average, event size, retention period, number of regions/producers.
   - *Consistency:* is approximate-but-fast acceptable, or must counts be exact? Can we tolerate duplicates? Late data — how late, and does it need to be reflected?
   - *Constraints:* existing stack, cloud provider, team size, budget.
   - **Write the answers on the board.** They become the criteria you justify against later, and they protect you when the interviewer changes a requirement mid-round.

2. **Capacity estimation (3–5 min).** Turn requirements into numbers.
   - Events/sec → bytes/sec → GB/day → TB/year, raw and after compression
   - Peak-to-average ratio (assume 3–5× unless told otherwise) and what that means for provisioning
   - Storage cost at rest, per-tier; compute cost per query pattern
   - Whether state fits in memory (this decides your dedup and aggregation strategy, so it's not academic)
   - *Say your assumptions out loud.* "Assuming 100-byte events at 50k/sec average, that's 5 MB/sec, ~430 GB/day raw, maybe 90 GB compressed." Nobody checks your arithmetic; they check that you did it.

3. **High-level architecture (5–8 min).** Boxes and arrows, source to consumer. Name the *role* of each box before naming the product: "a durable ordered log for ingest" then "so, Kafka or Pub/Sub." Role-first shows you understand the requirement; product-first shows you memorized a stack.

4. **Deep dive (15–20 min).** The interviewer picks one or two components, or you offer the interesting one. This is where Phases 2–6 pay off.

5. **Trade-offs and wrap (5 min).** State what you optimized for and what you gave up. Name the alternative you rejected and why. Then the two free-point sentences: **security** and **automation/CI-CD**.

**Additional habits:**
- **Drive the conversation.** Silence is scored badly. Narrate even when thinking: "I'm weighing whether to dedup at ingest or at query time — let me think about the cardinality."
- **Offer alternatives unprompted.** "We could also do X; I'm choosing Y because of the cost constraint we agreed on."
- **Handle mid-round requirement changes gracefully.** They *will* change a requirement to see if you adapt or collapse. Return to your written requirements list and change one thing at a time.

**Why it matters**
The framework is what converts your genuine production experience into a legible interview performance. You have operated real pipelines; the risk is that it comes out as disorganized detail instead of structured reasoning.

**Deliverable**
Write out the five-stage framework on one index card from memory. Then run **Anchor 3** (API → BigQuery) end to end in 45 minutes, out loud, recorded, using only what you already know. Don't study first — this is your baseline. Play it back and mark: did you ask about latency requirements? Did you estimate anything numerically? Did you state a trade-off?

**Topics to ask about** *(paste any into chat and I'll explain)*
- "Give me the requirements checklist I should run through every time"
- "How do I do capacity estimation out loud without stalling?"
- "What does 'near real-time' actually mean and how do I pin the interviewer down?"
- "The interviewer changed a requirement halfway — how do I adapt without restarting?"
- "Give me a system design prompt and grade my process, not my answer"

---

## Phase 2 (Weeks 2–3) — Ingestion & Transport

**What you'll learn**
- **The log abstraction:** append-only, partitioned, ordered-within-partition, replayable by offset. Understand this and Kafka/Pub/Sub/Kinesis are all variations on one idea
- **Kafka:** topics, partitions, consumer groups, offsets, retention; **ordering is per-partition only** — which is the fact that decides your partition-key choice; replication and ISR at a nameable level
- **Pub/Sub:** managed, auto-scaling, at-least-once by default, **no global ordering** (ordering keys give per-key ordering); push vs pull subscriptions; dead-letter topics
- **Choosing between them:** operational burden vs control; Pub/Sub for GCP-native with variable load, Kafka for ordering control, replay depth, and ecosystem
- **Delivery semantics, precisely:** at-most-once, at-least-once, effectively-once. **True end-to-end exactly-once requires a replayable source, deterministic processing, and an idempotent or transactional sink** — all three. Most "exactly-once" claims are at-least-once plus an idempotent sink, and saying so out loud is a strong signal
- **Partition key selection:** ordering guarantees vs hot partitions. Keying by `user_id` gives per-user ordering but skews if one user is 40% of traffic. This is the same skew problem you handle in Spark, framed differently
- **Backpressure:** what happens when consumers fall behind — buffer, drop, or slow the producer. Consumer lag as the metric that matters
- **Batch ingestion:** file-based landing, watermark/high-water-mark tracking, `_SUCCESS` markers, why "list the directory" doesn't scale
- **API ingestion (Anchor 3):** pagination, rate limits and backoff, incremental cursors, auth token refresh, and what to do when the API has no reliable "modified since" field

**Why it matters**
This is the layer where the multi-region and schema-version parts of Anchor 1 land, and where "fault tolerance" from Anchor 2 begins. It's also the layer candidates describe most vaguely — "we put it in Kafka" — while the actual grading is on partition keys, ordering guarantees, and lag handling.

**Deliverable**
For **Anchor 2** (clickstream), write the ingestion layer in detail: transport choice with justification, partition key with the skew risk stated, delivery semantics end to end, retention, and the backpressure plan. For **Anchor 3**, write the API-polling design: pagination, rate-limit backoff, cursor management, and what happens when the API returns a 500 mid-page.

**Topics to ask about**
- "Kafka vs Pub/Sub — the honest decision criteria"
- "Explain exactly-once end to end and why most claims of it are wrong"
- "How do I pick a partition key, and what breaks when I get it wrong?"
- "What is backpressure and what are my three options when consumers fall behind?"
- "The external API has no reliable modified-since field. Now what?"
- "How do I handle rate limits and retries without hammering the source?"

---

## Phase 3 (Weeks 3–5) — Processing

**What you'll learn**
- **Batch vs stream vs micro-batch:** the real decision axis is *latency requirement vs operational complexity*, not "streaming is modern." Micro-batch (Structured Streaming) sits between and is usually the right answer at 1-minute latency
- **Event time vs processing time:** the distinction the entire streaming field is built on. Event time is when it happened; processing time is when you saw it. Global multi-region traffic makes them diverge badly
- **Watermarks:** a threshold on event time — `max(event_time seen) − threshold`. Data older than the watermark is dropped from stateful operations. Watermarks are what let you *bound state*, which is what lets a stream run forever without OOM
- **Late-arriving data:** the three policies — drop (watermark default), side-output to a late lane, or allow-lateness with restatement. Choosing among these is a business decision, and saying that is the senior answer
- **Windowing:** tumbling, sliding, session windows; which each is for
- **Stateful processing:** what state is, where it's checkpointed, how it's restored, and what makes it grow unboundedly (unbounded key cardinality without expiry — the classic production failure)
- **Checkpointing:** what it protects (crash recovery of offsets + state) and what it does not (corrupt state from a logic bug, schema-incompatible query changes, data already dropped by a watermark)
- **The engines:** Dataflow/Beam (unified batch-stream, GCP-native, autoscaling), Flink (lowest latency, richest state), Spark Structured Streaming (micro-batch, unified with your batch stack). Know one deeply and be able to compare
- **Joins in streaming:** stream-stream (both sides buffered in state, bounded by watermark), stream-table (lookup/enrichment), and why the buffering is the expensive part

**Why it matters**
Anchor 1 and Anchor 2 are both stream designs, and the follow-ups (fault tolerance, dedup) live here. Your production streaming background is a genuine advantage in this phase — the material overlaps heavily with the watermark and exactly-once work you've already done. The gap is framing it as design choices rather than as configuration.

**Deliverable**
For **Anchor 1**, write the processing layer: batch/stream/micro-batch choice justified against the latency requirement you pinned down, watermark strategy given multi-region latency skew, late-data policy with a business justification, windowing choice, and the state-growth bound. Explicitly answer: *what's the largest state this can hold and what happens when it exceeds memory?*

**Topics to ask about**
- "Event time vs processing time — what breaks when I confuse them?"
- "What exactly is a watermark and how does it bound state?"
- "Late data — walk me through the three policies and when each is right"
- "How does streaming state grow unboundedly, and how do I prevent it?"
- "Dataflow vs Flink vs Spark Structured Streaming — the honest comparison"
- "Regions have wildly different latency. How does that affect my watermark?"

---

## Phase 4 (Weeks 5–6) — Storage, Serving, Cost

**What you'll learn**
- **Storage layer choice:** object storage + open table format (lakehouse) vs a cloud warehouse (BigQuery, Snowflake) vs both. The real criteria: query patterns, concurrency, cost model, and who's consuming
- **BigQuery specifics** (named in two of three anchors): partitioning (by ingestion time, date, or integer range), clustering (up to 4 columns, order matters), the slot-based compute model, and why `SELECT *` is expensive on a columnar store
- **Partitioning strategy generally:** choosing the partition column (usually time), partition granularity, and the small-file problem when partitions are too fine
- **Clustering / Z-ordering / liquid clustering:** co-locating related rows so scans skip more data. Z-ordering (flagged in the Anchor 2 tips) multi-dimensionally sorts so filters on several columns all benefit
- **File sizing:** the small-file problem — thousands of tiny files destroy scan performance and inflate metadata cost. Compaction as a maintenance job, not an afterthought
- **Hot / warm / cold tiering:** recent data in the fast store, historical in cheap object storage, with the query layer spanning both
- **Serving patterns:** pre-aggregated marts vs raw-with-views vs a materialized-view layer; the latency-vs-flexibility trade-off
- **Cost modeling, concretely:** storage per TB-month by tier, query cost per TB scanned, streaming-ingest premium over batch load, egress across regions (the one that surprises people in multi-region designs). Be able to say "streaming inserts cost roughly N× batch load here, so we batch anything that tolerates 5-minute latency"

**Why it matters**
"Efficient storage" is an explicit Anchor 2 follow-up, "cost" is explicit in Anchor 1, and "query optimization" is explicit in Anchor 3. Cost is also the dimension most candidates ignore entirely — mentioning it unprompted, with actual numbers, is a strong differentiator at the 2-YOE level where it's not expected.

**Deliverable**
For all three anchors, write the storage and serving layer: format, partitioning, clustering, file-sizing and compaction plan, tiering, and a **cost estimate with stated assumptions**. Then, for **Anchor 1**, add the cross-region egress cost — it's the hidden line item that changes the architecture.

**Topics to ask about**
- "Lakehouse vs cloud warehouse — the honest decision criteria in 2026"
- "Partitioning vs clustering vs Z-ordering — what does each actually do to a scan?"
- "Explain the small-file problem and the compaction strategy"
- "How do I estimate query cost on BigQuery before running anything?"
- "What's the cost difference between streaming inserts and batch loads?"
- "Cross-region egress in a multi-region design — how bad is it and how do I avoid it?"

---

## Phase 5 (Weeks 6–7) — Schema Evolution & Multi-Region

**This phase covers the hardest part of Anchor 1, and the part most candidates have never thought about.**

**What you'll learn**
- **Why schema versions skew across producers:** you cannot deploy to all regions simultaneously. Mobile clients update on their own schedule. **Multiple schema versions coexist in the stream permanently, not transiently** — that's the design constraint, and stating it explicitly is the insight the question is fishing for
- **Schema registry:** centralized schema storage with compatibility enforcement at produce time; the shift from "detect breakage downstream" to "prevent it at the producer"
- **Compatibility modes, precisely:**
  - *Backward* — new schema reads old data (safe: add optional field, delete field). Consumers upgrade first
  - *Forward* — old schema reads new data (safe: add field that old readers ignore). Producers upgrade first
  - *Full* — both. The safe default for a heterogeneous multi-region fleet
  - *None* — you're on your own
  - Know which direction each protects and **who upgrades first** under each. That last part is the follow-up
- **Serialization formats:** Avro (schema-embedded or registry-referenced, strong evolution semantics), Protobuf (field numbers make evolution explicit), JSON (flexible, no enforcement, most common in practice and most painful)
- **Evolution policies at the sink:** union schema (add columns, backfill nulls), versioned tables with a merged view, and the quarantine lane for genuinely incompatible records
- **The mid-stream schema change** (Anchor 3's follow-up, and the Google coding round's too): a file or stream where the format changes partway. Detect per-record rather than assuming the header, route by version, and never let one malformed batch kill the pipeline
- **Breaking vs non-breaking changes:** adding an optional field is safe; renaming, retyping, or changing semantics under the same name are not. **A semantic change under an unchanged name and type is the dangerous one** — no schema system catches it, which is why data contracts exist
- **Multi-region architecture:** regional ingestion with central aggregation vs full multi-region processing; data residency and sovereignty constraints (GDPR, India's DPDP Act) that may *forbid* centralizing raw data; region-level failover; and consistency across regions — you almost always accept eventual consistency here, and should say so and justify it

**Why it matters**
Anchor 1 names both multi-region *and* schema versions in a single sentence. That's deliberate: it's testing whether you've operated a real distributed system or only read about pipelines. **Your BUPA region-migration work is directly relevant lived experience** — a live Azure/Databricks region flip with DR via Deep Clone. That's a genuine story for this exact question, and it's the kind of specific, real detail that separates you from a candidate reciting a blog post.

**Deliverable**
Complete the **Anchor 1** design in full, with the schema-version and multi-region sections as the centerpiece. Explicitly answer: *what happens when region A is on schema v3 and region B is still on v1, and a consumer needs both?* Then write the BUPA migration as a system-design talk-track — the constraint, the options, what you chose, what it cost.

**Topics to ask about**
- "Backward vs forward vs full compatibility — who upgrades first in each?"
- "Three regions on three different schema versions. Walk me through the design."
- "Avro vs Protobuf vs JSON for an evolving event stream"
- "How do I detect a schema change mid-file and handle it without dropping data?"
- "What's a semantically-breaking change that a schema registry won't catch?"
- "Data residency constraints forbid centralizing raw data. How does the architecture change?"

---

## Phase 6 (Weeks 7–8) — Reliability, Dedup, Operations

**What you'll learn**
- **Idempotency:** the property that makes retries safe. Achieved via natural idempotency keys, upserts on a deterministic key, or transactional commits with a batch identifier. Without it, at-least-once delivery means duplicated data on every retry
- **Deduplication strategies** (an explicit Anchor 2 follow-up), with the trade-off stated for each:
  - *At ingest, windowed* — keep seen event IDs for N minutes in state. Bounded memory; misses duplicates outside the window
  - *At write, via upsert* — merge on a unique key. Exact; costs write amplification
  - *At query time* — `ROW_NUMBER()` over the key and filter. Zero ingest cost; every reader pays forever
  - *Probabilistic* — a Bloom filter for "probably seen." Tiny memory, false positives, occasionally acceptable
  - The real question is always **how long a duplicate window you must cover**, since that determines whether state fits in memory
- **Retries:** exponential backoff with jitter, retry budgets, distinguishing retriable (timeout, 503) from non-retriable (400, schema violation) failures. Retrying a non-retriable error forever is a real outage pattern
- **Dead-letter queues:** where poison messages go, and — the part people forget — **who looks at the DLQ and when**. A DLQ nobody monitors is a data-loss mechanism with extra steps
- **Checkpointing and recovery:** what's restored on restart, and the failure modes checkpoints *don't* cover (corrupt state, incompatible query changes, watermark-dropped data)
- **Failure domains:** what happens when one region, one broker, or the sink goes down. Graceful degradation over hard failure
- **Backfill and reprocessing:** replaying history without double-counting; running a backfill alongside live ingest (versioned outputs or a separate one-time flow); why idempotency is what makes backfill survivable
- **SLOs and monitoring:** freshness (end-to-end lag), completeness (did we lose events?), correctness (reconciliation against source counts), consumer lag, DLQ depth, cost-per-day trend
- **On-call reality:** runbooks, alert routing, avoiding alert fatigue
- **Security, briefly but always:** encryption in transit and at rest, PII handling and tokenization, IAM/least privilege, network isolation, audit logging, and region-specific residency
- **CI/CD, briefly but always:** infrastructure as code, tested transformations, staged deployment, schema-change review in PRs, and pipeline rollback

**Why it matters**
"Fault tolerance, deduplication, efficient storage" are the three named follow-ups to Anchor 2 — this phase is two of the three. And the security and CI-CD sentences are named red flags when omitted. They cost 20 seconds and they're free points.

**Deliverable**
Complete **Anchor 2** in full with a reliability section: dedup strategy with the window justified, retry and DLQ policy, failure-domain analysis, SLOs with thresholds, and the backfill plan. Then do a final timed pass: **all three anchors, 45 minutes each, out loud, recorded, on three separate days.**

**Topics to ask about**
- "Give me all four dedup strategies with the trade-off for each"
- "How do I decide the dedup window length?"
- "Retriable vs non-retriable failures — how do I classify them in code?"
- "What actually goes wrong when a backfill runs alongside live ingest?"
- "What SLOs should a data pipeline have, and what thresholds?"
- "Red-team my design" *(paste any anchor design)*

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| *Designing Data-Intensive Applications* (Kleppmann) — Ch. 5, 7, 8, 11 | Replication, transactions, distributed-system failures, stream processing. **These four chapters**, not the whole book |
| *Streaming Systems* (Akidau) — Ch. 1–4 | Event time, watermarks, windowing. The clearest treatment that exists |
| Google Cloud Architecture Center — data analytics reference patterns | Free, and directly matches the GCP-flavored anchors (Pub/Sub → Dataflow → BigQuery) |
| Confluent's schema-evolution docs | Compatibility modes explained precisely, with who-upgrades-first spelled out |
| Your own BUPA / Apollo / LRC work | Real multi-region, real DR, real incidents. The concrete detail that makes an answer credible |

**Deliberately excluded:** generic "system design interview" courses aimed at backend SWE roles (URL shorteners, chat apps — wrong problem class), and vendor certification material.

---

## Checkpoints (self-assess at each)

- **End of Week 2:** Recite the five-stage framework from memory. Run Anchor 3 in 45 minutes recorded — this is your **baseline**, and it should feel bad. Keep it for comparison.
- **End of Week 3:** Explain end-to-end exactly-once and why most claims of it are wrong, in under 90 seconds.
- **End of Week 5:** Explain watermarks and state bounding without notes. Anchor 1's processing layer written.
- **End of Week 6:** Produce a cost estimate for any of the three anchors with assumptions stated out loud, in under 5 minutes.
- **End of Week 7:** Answer "three regions, three schema versions" cold, in under 3 minutes, including who upgrades first.
- **End of Week 8:** **All three anchors, 45 minutes each, recorded, on separate days.** Compare Anchor 3 against your Week-2 baseline — the delta is the roadmap's actual output. Survive a red-team pass on each with fewer than three unanswered objections. Security and CI-CD sentences delivered unprompted every time.

---

## How to use this file

1. **Phase 1 before anything else.** The framework is the round. Knowledge without structure reads as rambling, and rambling loses this round even when every fact is right.
2. **Record the Week-2 baseline on Anchor 3 before studying.** You need the before-picture; it's the only honest measure of whether the eight weeks worked.
3. Return to the three anchors at the end of every phase and re-answer them with the new material folded in. They're the spine of this roadmap, not a final exam.
4. Pick any **Topic to ask about** and paste it into chat.
5. **Ask me to red-team every design.** Paste it in and I'll attack it as an interviewer would — that's cheaper than discovering the holes live.
6. Say the stage names out loud during practice ("okay, requirements first"). It feels artificial and it is exactly what makes your process legible to the interviewer.
7. Draw on BUPA, Apollo, and LRC constantly. *Applying theory only in the abstract* is a named red flag, and specific real detail is the fastest credibility you have.
