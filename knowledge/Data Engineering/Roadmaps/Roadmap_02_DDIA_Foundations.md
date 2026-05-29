# Roadmap 02 — DDIA Foundations (4 weeks)

> **Source:** *Designing Data-Intensive Applications* by Martin Kleppmann (the orange-with-boar-on-cover book). Chapters 1–11.
>
> **Goal:** **Vocabulary fluency**, not deep memorization. You already know most of these concepts empirically from your DLT/Apollo work — you just don't have the *named formal vocabulary* that interviewers use. When the interviewer says "linearizability" or "leader-based replication" or "two-phase commit," you respond instantly, not after 5 seconds of internal translation.
>
> **Why this is the cheapest highest-leverage 4 weeks you can spend:** DDIA is the single most-cited reference in product-DE interviews at Stripe / Atlassian / Snowflake / Datadog / Confluent. The book *is* the vocabulary they speak. Reading it gives you the shared dictionary.
>
> **Prerequisites:** None. Real-world DE experience makes the book easier (you'll keep recognizing patterns from your work). Read with a notebook open.
>
> **Time budget:** ~8 hrs/week × 4 weeks = 32 hrs. Compresses to 3 weeks at 10 hrs/week.

---

## Week 1 — Foundations of Data Systems (Chapters 1–3)

### Chapter 1: Reliable, Scalable, Maintainable Applications

**What you'll learn**
- **Tail latencies**: P50, P95, P99, P999. Why averages lie.
- **Reliability** — fault vs failure
- **Scalability** — vertical, horizontal, "load parameters"
- **Maintainability** — operability, simplicity, evolvability

**Why it matters**
Interviewers ask "how would you measure your pipeline's SLA?" Knowing P99 latency vs mean latency is the right vocabulary. Most candidates say "average response time" and lose points.

### Chapter 2: Data Models and Query Languages

**What you'll learn**
- **Relational vs Document vs Graph** data models
- SQL vs MapReduce vs Cypher
- **Object-relational impedance mismatch**
- Schema-on-read vs schema-on-write
- Many-to-many relationships across the three models

**Why it matters**
The interviewer asks "why not use Mongo for this?" You need a structured answer about access patterns + impedance mismatch, not "Mongo is bad."

### Chapter 3: Storage and Retrieval

**THE most important chapter for a DE.** Read it twice.

**What you'll learn**
- **B-trees** (Postgres, MySQL) — page-oriented storage, write amplification
- **LSM-trees** (Cassandra, RocksDB, **Delta Lake's log structure is LSM-style**) — sorted string tables, compaction
- **Log-structured storage** in general
- **Column-oriented vs row-oriented** — why Parquet beats CSV for analytics
- **Materialized views**, **data cubes**, **OLAP vs OLTP**

**Why it matters**
Knowing Delta Lake is LSM-style at heart connects everything you do. Compaction = OPTIMIZE. The whole `_delta_log` folder is a literal log-structured store.

**Deliverable for Week 1**
In one sentence each, explain:
1. Why Parquet beats CSV for analytical queries
2. Why Delta Lake's `_delta_log` is an example of LSM-tree thinking
3. The difference between P50 latency and mean latency in one example

**Topics to ask about**
- "What's the difference between P99 and mean latency?"
- "Explain B-trees vs LSM-trees with their write/read tradeoffs"
- "Why is Delta Lake's storage layout LSM-style?"
- "What is column-oriented storage and why is it faster for analytics?"
- "What's the object-relational impedance mismatch?"

---

## Week 2 — Encoding, Replication, Partitioning (Chapters 4–6)

### Chapter 4: Encoding and Evolution

**What you'll learn**
- **Backwards vs forwards compatibility**
- **Avro vs Protobuf vs Thrift vs JSON** — when each wins
- Schema evolution rules (the same rules govern your Delta schema evolution)
- Dataflow through services + databases + message brokers

**Why it matters**
Every time you add a column to a Kafka topic or a Delta table, you're navigating backward/forward compatibility. Knowing the formal rules saves you from "I added a non-nullable column and broke all the consumers" production incidents.

### Chapter 5: Replication

**What you'll learn**
- **Single-leader** (Postgres, MySQL primary) — synchronous vs async replication
- **Multi-leader** — when, why, conflict resolution (CRDTs, version vectors)
- **Leaderless** (Cassandra, DynamoDB) — quorums (W+R > N)
- **Replication lag** consequences: read-your-writes, monotonic reads, consistent prefix
- **Eventual consistency** — what it actually means

**Why it matters**
The interviewer points at any system and asks "single-leader, multi-leader, or leaderless?" You should answer in one sentence. Plus the read-your-writes problem affects every UI-fronted data system.

### Chapter 6: Partitioning

**What you'll learn**
- **Hash partitioning** vs **range partitioning** — and why range is good for ordered queries
- **Hotspots** and how to fix them
- **Secondary indexes** — local vs global
- **Rebalancing**: fixed partitions, dynamic partitions, partitioning by hash of key
- **Request routing**: gossip protocol, ZooKeeper, server-side discovery

**Why it matters**
Spark `partitionBy()` is range-or-hash partitioning. Kafka topics are partitioned. Cassandra is partitioned. Postgres `PARTITION BY` is partitioned. Same concept everywhere.

**Deliverable for Week 2**
Take 3 systems you use (or have heard of):
- **Kafka** — what kind of partitioning + replication?
- **Postgres** — what kind of partitioning + replication?
- **DynamoDB** — what kind of partitioning + replication?
Write 1 paragraph each placing them on the spectrum.

**Topics to ask about**
- "What's the difference between backwards and forwards compatibility?"
- "Avro vs Protobuf — when does each win?"
- "Walk me through single-leader vs multi-leader vs leaderless replication"
- "What's read-your-writes consistency and why is it tricky?"
- "What's a quorum and how does W+R > N work?"
- "Hash partitioning vs range partitioning — tradeoffs"
- "How does Kafka actually partition messages?"

---

## Week 3 — Transactions + Distributed Systems Pain (Chapters 7–8)

### Chapter 7: Transactions

**The most "interview-y" chapter — read it slowly.**

**What you'll learn**
- **ACID** — and why each database disagrees on the I (Isolation)
- **Isolation levels** (memorize these):
  - Read Uncommitted (dirty reads possible)
  - Read Committed (default in Postgres, MySQL)
  - Repeatable Read (default in MySQL InnoDB — but it's actually snapshot isolation)
  - Snapshot Isolation (Postgres calls this "repeatable read")
  - Serializable (the gold standard)
- **Anomalies**: dirty reads, non-repeatable reads, phantoms, lost updates, write skew
- How **2PL (two-phase locking)** and **SSI (serializable snapshot isolation)** achieve serializable

**Why it matters**
Every database brags about ACID. Knowing which I they actually provide is mid-senior signal. Plus: write skew is the anomaly that bit YOUR production system at some point — name it.

### Chapter 8: The Trouble with Distributed Systems

**What you'll learn**
- **Unreliable networks** — packet loss, duplication, reordering, partition (the "P" in CAP)
- **Unreliable clocks** — clock skew, leap seconds, why Google built TrueTime
- **Process pauses** — GC pause, hypervisor preemption, page swapping
- **Knowing the truth** — leader election, fencing tokens
- **Byzantine faults** — usually out of scope, but know the name

**Why it matters**
Every distributed-systems interview question is downstream of this chapter. "What happens if the leader crashes?" "What happens if there's a network partition?" Your answer is informed by Chapter 8.

**Deliverable for Week 3**
Explain in 100 words: **why your DLT pipeline's idempotency guarantees matter**, using vocabulary from Chapter 7 + 8 (transactions, fencing tokens, exactly-once vs at-least-once).

**Topics to ask about**
- "Walk me through ACID isolation levels with examples of each anomaly"
- "What's snapshot isolation and why isn't it serializable?"
- "What's write skew and give me a real example"
- "What's a fencing token and why do I need one?"
- "What is two-phase locking?"
- "What's the difference between exactly-once and at-least-once?"
- "Why is `current_timestamp()` unreliable in distributed systems?"

---

## Week 4 — Consistency + Consensus + Batch/Stream (Chapters 9–11)

### Chapter 9: Consistency and Consensus

**The hardest chapter. Don't skip.**

**What you'll learn**
- **Linearizability** vs **serializability** — *they are different things, both about ordering, but in different dimensions*
- **CAP theorem** — and why Kleppmann argues it's overrated
- **Causality, total order, partial order**
- **Atomic commits** and **two-phase commit (2PC)**
- **Consensus** — Raft, Paxos, Zab (at a high level, not implementation details)
- **Membership and coordination services** — ZooKeeper, etcd

**Why it matters**
CAP is the most-misunderstood concept in DE interviews. After this chapter you can dunk on candidates who think CAP means "pick 2 of 3" without nuance.

### Chapter 10: Batch Processing

**What you'll learn**
- **MapReduce** model — and why Spark beat it
- **Joins in batch**: sort-merge join, hash join, broadcast hash join (sound familiar?)
- **Output of batch workflows** — files, databases, key-value stores, search indexes
- **Beyond MapReduce**: dataflow engines (Spark, Flink, Tez)

**Why it matters**
You already do batch processing daily. This chapter just gives you the names for what you do.

### Chapter 11: Stream Processing

**The most directly relevant chapter to your DE work.**

**What you'll learn**
- **Event streams** vs change streams
- **Event sourcing** — and how it relates to CDC (your DLT SCD2 work)
- **Stream-table duality** — every table is a stream of changes, every stream produces a table
- **Time and windowing**: event-time vs processing-time vs ingestion-time
- **Watermarks** — Kafka, Flink, Spark Structured Streaming all use this concept
- **Joins in streams**: stream-stream, stream-table, table-table (your DLT SCD2 is basically stream-table)
- **Exactly-once** — what it really means at each layer (Kafka offsets, idempotent writes, transactional sinks)
- **Lambda vs Kappa architecture**

**Why it matters**
Confluent, Databricks DSS, Snowflake Streaming, Datadog ingestion — all of them assume Chapter 11 vocabulary. Plus your own DLT streaming work maps DIRECTLY onto this chapter.

**Deliverable for Week 4**
Take your **LRC pipeline** and write 1 page mapping concepts from Chapter 11 onto each layer:
- Bronze: which kind of stream? (event stream / change stream / log-compacted topic?)
- Silver SCD2 step: stream-table join? exactly-once semantics?
- Gold output: materialized view? aggregation over event time?

**Topics to ask about**
- "Linearizability vs serializability — define each and give an example where they differ"
- "Walk me through the CAP theorem and explain why it's overrated"
- "What is total order broadcast and why is it equivalent to consensus?"
- "Explain Raft at a high level"
- "What's the stream-table duality?"
- "Watermarks — explain conceptually + how do you set one?"
- "Event-time vs processing-time — give me a real scenario where the choice matters"
- "Explain exactly-once semantics across Kafka + Spark Streaming"
- "Lambda vs Kappa architecture — when does each fit?"

---

## Resources (single-source-of-truth canon)

| Resource | Use for |
|---|---|
| **DDIA itself** | The book. Read it cover-to-cover for chapters 1–11. The "Summary" sections at the end of each chapter are gold for revision. |
| Martin Kleppmann's [Distributed Systems lecture series](https://www.youtube.com/playlist?list=PLeKd45zvjcDFUEv_ohr_HdUFe97RItdiB) | Free Cambridge course (8 lectures, ~6 hrs total). Supplements DDIA chapters 5, 7, 8, 9. Watch in Week 3. |
| ByteByteGo blog | Visual explainers for CAP, Raft, isolation levels. Use when DDIA's prose isn't clicking. |
| The original Raft paper ("In Search of an Understandable Consensus Algorithm") | Optional, for Week 4. Genuinely readable. |

---

## Checkpoints (self-assess at each)

- **End of Week 1:** Explain B-tree vs LSM-tree in 60 seconds, naming Delta Lake as LSM-style.
- **End of Week 2:** Place Kafka, Postgres, Cassandra, DynamoDB on the partitioning + replication axes correctly.
- **End of Week 3:** Recite the 5 isolation levels and name one anomaly each prevents.
- **End of Week 4:** Define linearizability vs serializability cleanly. Give a real scenario where exactly-once matters.

---

## How to use this file

1. **Read the chapter first.** Then come here and tick off topics.
2. Any topic in the "Topics to ask about" lists — paste into chat, I'll explain at depth.
3. **Don't skim the book.** This roadmap assumes you've read each chapter. The chapter is the primary source; this is the index.
4. **Map every concept back to your DLT work.** That's how it sticks — you've already lived these concepts; you're just learning the names.
5. The Chapter 11 mapping exercise is the single highest-value deliverable — do it carefully. It's also a great interview talk-track ("at my last role I was effectively doing X, where X is named-from-DDIA").
