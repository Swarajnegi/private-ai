# Experience Coverage Map — Data Engineering

> **Purpose.** Records what the user HAS and HAS NOT worked on. Created 2026-08-24 after the user
> identified the gap: *"what kind of projects, issues, problems and scenarios I **haven't** faced."*
>
> **Why the gaps matter more than the fills.** A model that knows what you know but not what you
> don't cannot calibrate register — it can't tell when to explain from first principles versus skip
> to the interesting part. Verified 2026-08-24: across 494 KB entries there were **zero** records of
> any experience boundary (3 grep hits, all false positives). See KB 496.
>
> **Why this can't be captured passively.** Build work generates records of what was *done*. No
> event fires when something is *not* done, so the `Stop` hook, the observation queue, and every
> corpus iterator are structurally blind to it. Absence has no trigger — it has to be elicited once,
> by hand. Same class of failure as KB 474.
>
> **GITIGNORED, deliberately.** A public document titled "things this engineer hasn't done" is
> career-sensitive while a job switch is live (see `knowledge/Job Switch/`). Flip it to tracked once
> the repo is private — it's high-value migration material, just not public-safe today.

---

## How to fill this in

Mark each row with a depth, and add a note where the note is the interesting part.

| Depth | Means |
|---|---|
| **SHIPPED** | Built it in production, owned it, debugged it under pressure |
| **TOUCHED** | Used it on a real task, but didn't own the design |
| **STUDIED** | Read/learned/certified it, no production contact |
| **NAME-ONLY** | Know it exists, couldn't operate it |
| **NEVER** | No contact at all |

Two rules that make this useful rather than a CV:

1. **Be unkind to yourself on SHIPPED.** "I wrote some of it" is TOUCHED. SHIPPED means it broke and you fixed it.
2. **A NEVER with a reason is worth more than a NEVER alone.** *"NEVER — service company, never staffed on it"* and *"NEVER — actively avoided, don't rate the tech"* mean completely different things for calibration.

---

## Part 1 — Project archetypes (enterprise DE)

The user's own two, for anchoring:

| # | Project | Archetype | Depth |
|---|---|---|---|
| 1 | BUPA / Apollo Gen2 | **Upliftment / modernization** — legacy notebook ETL → SDP/DLT declarative pipelines | SHIPPED |
| 2 | BUPA Region Migration | **Validation / assurance framework** — built the suite proving a DeepClone cross-region DR framework was correct. Sat *inside* a region-migration + DR-redesign programme, and touched the serverless-conversion workstream separately | SHIPPED |

### The wider set that matters at enterprise level

| Archetype | What it actually is | Depth | Notes |
|---|---|---|---|
| **Upliftment / modernization** | Legacy ETL → modern framework, same business logic. Notebook/stored-proc/SSIS → DLT, dbt, SDP | SHIPPED | Apollo Gen2 |
| **Validation / assurance framework** | Build the thing that proves another thing is correct. Reconciliation, DR validation, parallel-run comparison | SHIPPED | Region Migration |
| **Platform migration (on-prem → cloud)** | Hadoop / Teradata / Netezza / Informatica → Databricks / Snowflake / BigQuery | | |
| **Cloud-to-cloud migration** | AWS → Azure, or GCP → AWS. Whole estate, new IAM/network model | | |
| **Region migration / DR redesign** | Same cloud, different region. Forward-sync → cutover → backward-sync; RPO/RTO redesign | TOUCHED? | You built validation *for* one — did you own migration mechanics? |
| **Re-platforming** | Same workload, different engine. Synapse → Databricks, Redshift → Snowflake | | |
| **Greenfield lakehouse build** | Medallion from zero. No legacy, all design decisions open | | |
| **Warehouse modernization / dimensional remodel** | Star-schema design, SCD strategy, conformed dimensions, semantic layer | | |
| **Batch → streaming enablement** | Introducing Kafka / Event Hubs / Structured Streaming / CDC where only batch existed | | |
| **Cost optimization / FinOps** | Engagement whose *deliverable is a lower bill*. Cluster policies, right-sizing, spot, storage tiering | | You have `Databricks_Costing.md` — was that ever an engagement? |
| **Governance & compliance rollout** | Unity Catalog / Purview / Immuta rollout, RBAC redesign, PII classification, data contracts | TOUCHED? | You worked *around* Immuta and UC masking — did you ever *roll it out*? |
| **Regulatory reporting build** | BCBS239, Solvency II, HIPAA, APRA. Lineage and auditability are the product | | |
| **Data quality / observability programme** | DQ framework, expectations, freshness SLAs, Monte Carlo / Soda / GE | TOUCHED? | Adjacent to your validation work — is it the same skill? |
| **MDM / entity resolution** | Golden-record building, fuzzy matching, survivorship rules | | |
| **Self-service / semantic layer enablement** | dbt metrics, Power BI datasets, certified datasets, enabling analysts | | |
| **ML platform / feature-store enablement** | Feature stores, training pipelines, MLOps handoff | NAME-ONLY? | The repo has `feature_store/` — did you touch it? |
| **Decommissioning / rationalization** | Sunsetting legacy systems, archival, proving nothing still depends on it | | |
| **M&A data integration** | Merging two companies' estates, duplicate domains, conflicting master data | | |
| **Performance remediation / firefighting** | Inheriting a broken slow estate with no design authority | TOUCHED? | The 30-hour livelock and quota incidents are this shape, inside your own project |
| **Multi-tenancy / productization** | Turning an internal pipeline into a product other teams or customers consume | | |
| **POC / vendor bake-off** | Evaluate and recommend. Deliverable is a decision, not a pipeline | | |
| **BAU support / staff augmentation** | Running someone else's estate. On-call, ticket queue, no build mandate | | |

### Engagement shape (orthogonal to archetype — worth its own row)

| Dimension | Which end have you lived? | Notes |
|---|---|---|
| Greenfield vs brownfield | | |
| Build vs run (project vs BAU/on-call) | | Have you ever carried a pager? |
| Hands-on vs advisory/design-authority | | |
| Client-facing vs internal | | You're service-side — how much direct client contact? |
| Solo vs squad vs multi-squad programme | | Region Migration had 6+ committers |
| Time-boxed vs open-ended | | |

---

## Part 2 — Technology surface

### Compute & processing
| Item | Depth | Notes |
|---|---|---|
| Spark (batch, DataFrame API) | SHIPPED | |
| Spark Structured Streaming | | |
| Delta Lake internals (`_delta_log`, time travel, VACUUM) | SHIPPED | Deep — see the three-stores model |
| DLT / Lakeflow SDP | SHIPPED | Apollo Gen2, 422 pipelines |
| Databricks Asset Bundles / IaC | SHIPPED | |
| Serverless vs classic compute tradeoffs | SHIPPED | |
| Photon | TOUCHED? | Know the caveat; ever tuned for it? |
| Apache Iceberg | | |
| Apache Hudi | | |
| dbt | STUDIED? | `portable_mds` setup exists — did it go anywhere? |
| Snowflake | | |
| BigQuery | | |
| Redshift | | |
| Trino / Presto / Athena | | |
| Flink | | |
| Hadoop / Hive / MapReduce | | |
| Polars / DuckDB | | |

### Orchestration & movement
| Item | Depth | Notes |
|---|---|---|
| Databricks Workflows / Jobs | SHIPPED | for_each, condition_task, cross-workspace |
| Azure Data Factory | STUDIED? | `ADF_Deep_Dive.md` exists — production contact? |
| Airflow | | |
| Control-M | TOUCHED? | Named in the BUPA stack — did you operate it? |
| Dagster / Prefect | | |
| Qlik / Attunity CDC | TOUCHED? | In the stack; how close? |
| Debezium | | |
| Kafka / Event Hubs | | |
| Fivetran / Airbyte | | |

### Storage, governance, platform
| Item | Depth | Notes |
|---|---|---|
| ADLS Gen2 / abfss, SP OAuth, RBAC | SHIPPED | |
| Unity Catalog (as a user) | SHIPPED | |
| Unity Catalog (rollout / design) | | |
| Immuta | TOUCHED | Worked around its masking; didn't own it |
| Purview / Collibra / Alation | | |
| S3 / GCS | | |
| Azure vCPU quota, pools, spot economics | SHIPPED | Learned the hard way, Aug 2026 |
| Terraform | | |
| Kubernetes | | |
| CI/CD (Azure DevOps pipelines) | TOUCHED | `azure-pipelines.yml` present in the repo |

### Modelling & warehousing
| Item | Depth | Notes |
|---|---|---|
| Medallion architecture | SHIPPED | |
| SCD Type 2 / CDC merge patterns | SHIPPED | |
| Kimball dimensional modelling | | |
| Data Vault | | |
| One Big Table / wide denormalized | | |
| Data mesh / domain ownership | | |

### Languages & tooling
| Item | Depth | Notes |
|---|---|---|
| Python | SHIPPED | |
| SQL (analytical, window functions) | SHIPPED | |
| PySpark | SHIPPED | |
| Scala | | |
| PowerShell | TOUCHED | Enough to hit the `` `v `` escape bug |
| Bash / Linux | | |
| Git (rebase, conflict resolution, history rewriting) | | |
| Java | | |

### Reliability & operations
| Item | Depth | Notes |
|---|---|---|
| Reading Spark UI / event logs for diagnosis | SHIPPED | GC stalls, shuffle signatures, executor death |
| Production incident under time pressure | SHIPPED | Three prod failures in one day, 2026-08-20 |
| On-call rotation / pager | | |
| SLA/SLO definition and defence | | |
| Backfill / replay strategy at scale | | |
| Disaster recovery (designing, not validating) | | |
| Cost governance at org scale | | |
| Post-incident review / blameless postmortem | | |

---

## Part 3 — Scenarios & failure modes

Not tech, but *situations*. These are often what separates senior from mid, and they're invisible on a CV.

| Scenario | Faced? | Notes |
|---|---|---|
| A migration you had to roll back | | |
| Data loss you caused, or nearly | | The silent 2,490-table mis-split is close |
| Discovering a defect *after* sign-off | | |
| Being wrong in front of a client | | |
| Inheriting undocumented code with the author gone | | |
| Telling a client their requirement is wrong | | |
| A deadline you knew was impossible and said so | | |
| Being blocked by another team for weeks | | |
| A vendor/platform bug with no workaround | | |
| Cost overrun someone had to explain upward | | |
| Compliance/audit finding against your work | | |
| Handing over a system you built and watching it drift | | |
| Being the only person who understands something | | |
| Mentoring / onboarding someone junior | | |
| Interviewing / evaluating other engineers | | |
| Pushing back on a bad architectural mandate from above | | |
| A project cancelled mid-build | | |
| Working through an outage you didn't cause and couldn't fix | | |

---

## Part 4 — Self-assessed edges

Free text, and the most valuable section here. No structure imposed.

**What I'm genuinely strong at, beyond what a CV would say:**

**What I can do but don't enjoy:**

**What I'd be exposed on in a senior interview:**

**What I want to learn next, and why:**

**What I've deliberately chosen not to learn, and why:**

---

*Update whenever a project ends or a gap closes. A row moving NEVER → SHIPPED is a real event and worth a KB entry.*
