# Roadmap 04 — Portable Modern Data Stack (~10–12 weeks)

> **Goal:** Become *platform-independent*. You already own the **lakehouse** side cold (Databricks / Spark / SDP / Delta — Apollo Gen2, LRC, PeopleSoft). This roadmap adds the other half of the industry: the **warehouse + transformation + orchestration + streaming** stack that any non-Databricks shop runs. Master both and you're the rare DE who fits *any* project, not just a Databricks one.
>
> **Why now:** The Novartis SDP client round fell through on a BGV / experience-verification staffing call — *not* on skill (interview feedback was "good"). None of the SDP study is wasted: streaming semantics, CDC, SCD2, watermarks, checkpoints and lakehouse internals are engine-agnostic and transfer directly to everything below. The lesson is strategic, not technical: don't be a single-vendor DE. This roadmap makes you vendor-proof.
>
> **Outcome:** One public GitHub capstone repo that exercises the *entire* portable stack end-to-end, plus fluency talk-tracks for dbt, Snowflake, Airflow/Dagster and Kafka in interviews. You'll be able to walk into a "we use Snowflake + dbt + Airflow" shop and a "we use Databricks" shop with equal credibility.
>
> **Time budget:** ~8–10 hrs/week × 10–12 weeks. dbt + Snowflake alone (Phases 1–2, ~5 weeks) already make you hireable on this stack; the rest is the differentiating edge. You've historically run ~5× pace on self-study, so compress where it feels slow — but do NOT skip the capstone, which is where the hiring signal lives.

---

## Your head start (read this first — it's why you can move fast)

Almost every piece of this stack *rhymes* with something you already mastered on Databricks. The sequencing below is deliberately ordered to exploit that — you are not learning from zero, you're re-mapping known concepts onto new tools.

| You already know (Databricks/SDP) | Maps to (portable stack) | What's genuinely new |
|---|---|---|
| Strong Spark SQL | **dbt** models (it's just SQL + Jinja) | the build-graph / ref() dependency model |
| SDP AUTO CDC / SCD2 (`sequence_by`, `__START_AT`/`__END_AT`) | **dbt snapshots** (SCD2) & **Snowflake Streams** (CDC) | snapshots are batch-diff, not streaming |
| Incremental streaming tables | **dbt incremental models** (`is_incremental()`, merge/insert strategies) | you choose the merge strategy explicitly |
| Delta time travel | **Snowflake Time Travel** + zero-copy clone | clone is metadata-only, instant |
| SDP pipeline DAG (flows → tables) | **Airflow** DAG / **Dagster** asset graph | external orchestration vs in-engine |
| Spark Structured Streaming + watermarks | **Kafka** + **Flink** | Kafka is the *transport*; Flink/Streams is the compute |
| Unity Catalog governance | **Snowflake RBAC** + dbt exposures/contracts | role hierarchy + warehouse grants |

---

## Phase 1 (Weeks 1–3) — dbt · *the centerpiece, start here*

Highest marketability-per-hour in the whole stack and pure leverage off your SQL. dbt is the de-facto transformation/testing/lineage standard; nearly every modern-data-stack job posting lists it.

**What to learn**
1. Core model mechanics: `source()`, `ref()`, the **staging → intermediate → marts** layering convention.
2. **Materializations**: `view`, `table`, `incremental`, `ephemeral` — when each is correct (maps to your MV-vs-ST instincts).
3. **Incremental models**: `is_incremental()`, `unique_key`, incremental strategies (`merge` / `delete+insert` / `append`), late-arriving handling. This is your streaming-incremental brain in batch form.
4. **Snapshots** (SCD2): `dbt snapshot`, `strategy='timestamp'` vs `'check'`, `dbts_valid_from`/`valid_to`. You'll grasp this in an hour given AUTO CDC.
5. **Tests**: generic (`unique`, `not_null`, `accepted_values`, `relationships`) + singular SQL tests; `dbt build` (run + test in DAG order); source **freshness**.
6. **Docs & lineage**: `dbt docs generate/serve`, the lineage graph, `exposures`.
7. **Jinja & macros**, packages (`dbt-utils`, `dbt_expectations`), `seeds`, `vars`, environments/targets.
8. **dbt Core vs dbt Cloud** (and be aware of the newer **Fusion** engine) — learn Core; it's what you run locally and in CI.

**Do:** point your dbt project at a real warehouse (Phase 2). Build a 3-layer project (staging/intermediate/marts) with at least one incremental model, one snapshot, and a full test suite.

**Resources:** dbt Learn → "dbt Fundamentals" (free, official) → "Advanced Materializations" + "Jinja, Macros, Packages".

---

## Phase 2 (Weeks 3–5) — Snowflake · *the warehouse half*

The market-leading portable warehouse and the perfect *contrast* to Databricks — learning it cements the warehouse-vs-lakehouse mental model that senior interviewers probe.

**What to learn**
1. **Architecture**: the three layers (storage / **virtual warehouses** (compute) / cloud services), separation of storage & compute, **micro-partitions**, clustering keys, pruning.
2. **Streams & Tasks**: Snowflake-native **CDC** (streams = change tracking on a table) + **Tasks** (scheduling/DAG) — directly maps to your CDC work; build an SCD2 with a stream + task and compare to AUTO CDC.
3. **Time Travel** (query/restore past states) + **zero-copy cloning** (instant metadata clones) — you already know the Delta analog.
4. **Snowpark** (Python/DataFrame in Snowflake) — bridges your PySpark muscle.
5. **Loading**: `COPY INTO`, stages (internal/external), **Snowpipe** (continuous ingest), and how external tables / Iceberg tables work.
6. **Cost model**: credits, warehouse sizing, auto-suspend/resume, resource monitors — cost-consciousness is a hiring signal.
7. **Governance**: RBAC role hierarchy, grants, masking policies, row access policies.

**Do:** run your Phase-1 dbt project *against Snowflake*. Keep a running journal: "how is this different from Databricks?" (warehouse vs lakehouse, credits vs DBUs, streams vs CDF, time-travel parity). That comparison table is interview gold.

**Resources:** Snowflake "Hands-On Essentials: Data Warehousing Workshop" (free, earns a badge); Snowflake docs on Streams & Tasks.

---

## Phase 3 (Weeks 5–8) — Orchestration · *Airflow → Dagster*

External orchestration is what stitches ingest + dbt + warehouse into a scheduled, observable pipeline. Every shop has *some* orchestrator; Airflow is table-stakes, Dagster is the differentiator.

**Airflow (incumbent — learn first)**
1. DAGs, operators, the **TaskFlow API** (`@task`/`@dag`), XComs, connections & hooks.
2. Scheduling: schedules, backfills, catchup, **deferrable operators**, sensors.
3. **Datasets / data-aware scheduling** (Airflow 3.x) — DAGs triggered by data updates, not just cron.
4. Executors (Local/Celery/Kubernetes) at a conceptual level; `cosmos` for running dbt in Airflow.

**Dagster (the modern differentiator — learn second)**
1. **Software-defined assets** (SDAs) — model your *data assets* and let Dagster derive the graph (vs Airflow's task-centric view).
2. The asset graph, declarative/auto-materialize scheduling, partitions, IO managers, the dbt integration (`dagster-dbt`).
3. Why "assets, not tasks" is where orchestration is heading.

**Do:** orchestrate your dbt + Snowflake pipeline end-to-end in Airflow, then port the same pipeline to Dagster and write up the contrast (task-centric vs asset-centric).

**Resources:** Astronomer Airflow guides (free, excellent); Dagster University (free, official).

---

## Phase 4 (Weeks 8–11) — Streaming · *Kafka (KRaft) + a Flink taste*

Real-time is a strong edge and you already have the streaming *concepts* from Spark Structured Streaming — here you learn the transport (Kafka) and a second compute engine (Flink).

**Kafka (learn the 4.x / KRaft era — skip ZooKeeper tutorials)**
1. Fundamentals: topics, partitions, offsets, producers/consumers, **consumer groups** & rebalancing, replication, ISR.
2. **KRaft** — Kafka 4.0 (Mar 2025) removed ZooKeeper entirely; KRaft (Kafka's own Raft metadata) is now the only mode. (Don't follow tutorials that start with `zookeeper-server-start`; that's pre-4.0.)
3. Delivery semantics: at-least-once / at-most-once / **exactly-once** (idempotent producer + transactions).
4. **Schema Registry** (Avro/Protobuf/JSON-Schema) + schema evolution/compatibility.
5. **Kafka Connect** (source/sink connectors — e.g. Debezium CDC → Kafka → warehouse).

**Flink / Kafka Streams (taste only)**
1. Stateful stream processing, event-time, **watermarks** (you already understand these from SDP), windowing.
2. Contrast Flink (true streaming) vs Spark Structured Streaming (micro-batch) vs Kafka Streams (library).

**Do:** stand up Kafka locally (KRaft, single broker via Docker), produce/consume a stream, register a schema, and wire a Connect sink into Snowflake (or land to files for dbt).

**Resources:** Confluent Developer (free courses, KRaft-era); *Kafka: The Definitive Guide*, 2nd ed.

---

## Cross-cutting (run throughout, not as a separate phase)

- **Git + CI/CD** — GitHub Actions running `dbt build` + tests on every PR. This single thing impresses interviewers more than any cert; it shows you ship like an engineer, not a notebook-runner.
- **Data quality / contracts** — dbt tests → **Great Expectations** → the data-contract concept (schema + SLA enforced at the boundary).
- **Docker / docker-compose** — containerize the local stack (Kafka + Airflow/Dagster + a Postgres) for reproducible dev.
- **Ingestion/EL tooling** — at least conceptual familiarity with **dlt** (Python EL), Airbyte/Fivetran (managed connectors). Know where they sit vs custom code.
- **SQL gap-close** — knock out your flagged weak spots: **gaps-and-islands** (the `row_number` − date trick), window-function edge cases. ~3 LeetCode-SQL/StrataScratch sessions.

---

## Capstone (start ~Week 4, build in parallel) — the portfolio proof

One public GitHub repo that exercises the **entire** stack end-to-end:

> **Kafka/dlt ingest → Snowflake landing → dbt (staging / intermediate / marts + a snapshot for SCD2 + a full test suite) → orchestrated by Airflow (then ported to Dagster) → CI on GitHub Actions → a simple dashboard (Streamlit/Metabase/Preset).**

- **Reuse the design discipline from [Roadmap 03 — Greenfield Data Warehouse](Roadmap_03_Greenfield_Warehouse.md):** that roadmap teaches *modeling from a business problem* (star schema, grain, dimensions). This capstone teaches the *tooling stack* on top. Do 03's modeling thinking inside 04's tooling — they compose into one strong repo.
- **Use a pharma/healthcare-flavored dataset** to lean on your domain (or NYC TLC from Roadmap 03 if you want a recruiter-recognized set).
- Pin it to your GitHub profile; it becomes your default "tell me about a project you built" talk-track and *proves portability* in a way no certificate can.

---

## The edge this buys you

Most DEs are either "Databricks people" **or** "Snowflake/dbt people." After this you're **both** — lakehouse *and* modern-data-stack fluent, with a public repo proving the second half. That's a genuinely rare profile at ~1 YOE, and it's exactly what makes you immune to a single client/project falling through.

---

## Sequencing rationale (why this order)

1. **dbt first** — pure leverage off your strongest existing skill (SQL); immediately marketable; needed by everything downstream.
2. **Snowflake second** — dbt needs a warehouse to run against; Snowflake's streams/time-travel rhyme with your CDC/Delta knowledge so the ramp is short.
3. **Orchestration third** — only meaningful once you have a dbt+warehouse pipeline worth scheduling.
4. **Streaming last** — highest new-concept load, but you already own the *semantics*; it's the transport/engine that's new. Also the least universally required of the four, so it's the right thing to defer.

*Optional next step:* ask for a `/deep-research` scan on current (2026) India-market demand & salary for dbt + Snowflake + Airflow + Kafka if you want hard signal before committing time.
