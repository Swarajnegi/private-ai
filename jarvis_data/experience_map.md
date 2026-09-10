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
> **TRACKED — and that was this file's own stated condition.** It was gitignored at creation because
> a *public* document titled "things this engineer hasn't done" is career-sensitive while a job
> switch is live (see `knowledge/Job Switch/`), with the note: flip it to tracked once the repo is
> private. The repo went private 2026-08-26 and the user directed that everything be tracked, so the
> condition is met and this file is committed. The sensitivity that motivated the original exclusion
> has not evaporated — it is now handled by the repo being private, which means the usual caveat
> applies: private is not secret, and a repo can be forked, granted, or flipped public by accident.

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
| **Platform migration (on-prem → cloud)** | Hadoop / Teradata / Netezza / Informatica → Databricks / Snowflake / BigQuery | NEVER| I just haven't worked on any projects in platform migration yet, I would've simulated it on my own but i can't have access to two platforms let alone do a platform migration for learning and this is why I haven't learnt it too.|
| **Cloud-to-cloud migration** | AWS → Azure, or GCP → AWS. Whole estate, new IAM/network model | NEVER| Same reason as platform migration|
| **Region migration / DR redesign** | Same cloud, different region. Forward-sync → cutover → backward-sync; RPO/RTO redesign | TOUCHED | You built validation *for* one — did you own migration mechanics? -- NO, I was added to the project after the Deepclone framework was already built and I had to work on Test Framework for Deepclone. |
| **Re-platforming** | Same workload, different engine. Synapse → Databricks, Redshift → Snowflake | NEVER| Again, the two BUPA projects are my only projects since I turned full-time on dec 1 2025, so same reason as platform migration.|
| **Greenfield lakehouse build** | Medallion from zero. No legacy, all design decisions open | SHIPPED|The BUPA SDP project is  where I actually designed and often fixed the medallion in SDP, where to append, where to put a temp view where to have an MV, where to enforce shcema and how, how to apply SCD provided by SDP, which one  touse between auto cdc and auto cdc snapshot etc.|
| **Warehouse modernization / dimensional remodel** | Star-schema design, SCD strategy, conformed dimensions, semantic layer | TOUCHED| Touched because I SHIPPED the SCD strategy as mentioned in above point, but I have only STUDIED about data modeling concepts like startschema etc. In BUPA SDP project I was only uplifting the platform they were already on so the data models were already built. Same in region-migration projct. |
| **Batch → streaming enablement** | Introducing Kafka / Event Hubs / Structured Streaming / CDC where only batch existed | STUDIED| Have't gotten any situation where I would try out kafka or event hubs.|
| **Cost optimization / FinOps** | Engagement whose *deliverable is a lower bill*. Cluster policies, right-sizing, spot, storage tiering | STUDIED| You have `Databricks_Costing.md` — was that ever an engagement?  -- NO, although you can see from session_learnings how I did debug and fixed the slow running deepclone test frameowrk and looked up the VM family per region quota on azure to then size the VM and driver-worker nodes so they don't axceed Azure Quota in bupa-region migration but that was just optimization not cost optimization.|
| **Governance & compliance rollout** | Unity Catalog / Purview / Immuta rollout, RBAC redesign, PII classification, data contracts | TOUCHED | You worked *around* Immuta and UC masking — did you ever *roll it out*? -- NO |
| **Regulatory reporting build** | BCBS239, Solvency II, HIPAA, APRA. Lineage and auditability are the product | NEVER| I never built a lineage if that's what you're asking, it's always other people who are handed that task in my current project while i was busy in test frameowrk for deepclone.|
| **Data quality / observability programme** | DQ framework, expectations, freshness SLAs, Monte Carlo / Soda / GE | TOUCHED| Adjacent to your validation work — is it the same skill? -- I worked on test case development in both my projects, first one had different type of tests, it was on whtehr the data ingested via our sdp pipelines between gen1 and gen2, with each layer (stg.brz/silver/gld) haiving differnt sets of tests to test out SCD, uniqueness, Expectations in SDP pipelines etc |
| **MDM / entity resolution** | Golden-record building, fuzzy matching, survivorship rules | NEVER| I don't know what this is.|
| **Self-service / semantic layer enablement** | dbt metrics, Power BI datasets, certified datasets, enabling analysts | NEVER| Never worked with powerbi or dbt etc.|
| **ML platform / feature-store enablement** | Feature stores, training pipelines, MLOps handoff | NAME-ONLY | The repo has `feature_store/` — did you touch it? -- NO |
| **Decommissioning / rationalization** | Sunsetting legacy systems, archival, proving nothing still depends on it | NAME-ONLY| Name only because in the first bupa project i was there till the end (hypercare) so I was part of the cutover before that too, ut it was handled mostly by the seniors and my tech lead but I was aware of the cutover strategy but i can;t remember it properly now.|
| **M&A data integration** | Merging two companies' estates, duplicate domains, conflicting master data | NEVER| never had the chance to work on something like this.|
| **Performance remediation / firefighting** | Inheriting a broken slow estate with no design authority | TOUCHED | The 30-hour livelock and quota incidents are this shape, inside your own project -- I have metnioned about this shape in the "Cost Optimization"'s notes column.|
| **Multi-tenancy / productization** | Turning an internal pipeline into a product other teams or customers consume | NEVER| never had the chance to work on something like this.|
| **POC / vendor bake-off** | Evaluate and recommend. Deliverable is a decision, not a pipeline | TOUCHED| I did work on one POC that i remembrerin the first bupa project, it was whether I can translate and history (SCD 2) table in gen1 into a gen2 table via SDP directly. This was translating the historical part, the incremental part would work using SDP's features like sauto cdc or auto cdc snapshot ingesting data from src systems.|
| **BAU support / staff augmentation** | Running someone else's estate. On-call, ticket queue, no build mandate | NEVER| never did this kind of work|

### Engagement shape (orthogonal to archetype — worth its own row)

| Dimension | Which end have you lived? | Notes |
|---|---|---|
| Greenfield vs brownfield | I don't know what these two are| |
| Build vs run (project vs BAU/on-call) |Build | Have you ever carried a pager? -- what do you mean pager? I haven't |
| Hands-on vs advisory/design-authority |more of hands-on, some of designing | |
| Client-facing vs internal | I had a lot of clinet facing with weekly demos showcasing my gen2 pipelines and addressing their issue son call and addressing issues i found in their data, but I have no client interation in the current bupa projcet since i joined in much later. | You're service-side — how much direct client contact? |
| Solo vs squad vs multi-squad programme |I was working Solo and squad in both projects, with 2-4 people and 2 people on second bupa (deepclone test frameowrk). | Region Migration had 6+ committers |
| Time-boxed vs open-ended | Extremely time-boxed in both projects, I had to work around 16-18 hours in the first bupa consistently because of messed up timelines set up by whoever did the presales for bupa SDP project, and the same person did the presales for the current bupa too, and I had to deliver the proper deepclone test frmework in extreme deadlines due to stakeholder pressure, which is what I reciverd the appreciation mail form the AVP for which you already know about.| |

---

## Part 2 — Technology surface

> **Drafted 2026-09-03 by JARVIS. Read this before trusting any row.**
>
> A depth ending in **`?`** with a `GUESS:` note is **mine, not yours** — inferred from evidence in
> the repo, and quite possibly wrong. Overturning one is the point; you overturned 2 of my 5 Part 1
> guesses. A depth with **no `?`** is either yours already or quoted from your own Part 1 answers,
> and those quote you directly so you can check them.
>
> **The evidence rule I applied, after getting burned by it.** A term's presence in a file proves
> nothing until you read the match. Four technologies looked like real production exposure and were
> pure noise: `Hadoop` was `spark.hadoop.fs.azure.*` (a config namespace), `Hive` was a substring of
> `arc`**`hive`**`d`, `Java` was `Py4JJavaError`, and `Scala` was `15.4.x-scala2.12`, the runtime
> version string. Same failure as KB 496 and KB 521. Where a marker rests on a false positive, the
> note says so.
>
> I also **retracted two of my own earlier guesses** rather than resolve them — Control-M and
> Qlik/Attunity claimed "named in the BUPA stack" and that claim has zero support. They are blank
> again, which is the honest state.

### Compute & processing
| Item | Depth | Notes |
|---|---|---|
| Spark (batch, DataFrame API) | SHIPPED | |
| Spark Structured Streaming | TOUCHED? | GUESS: SDP/DLT streaming tables and auto-CDC **are** Structured Streaming underneath, and you shipped 422 pipelines on it. But SDP writes the `readStream` for you. **Your call, and it's a real one:** if you've never hand-written a stream, trigger or checkpoint, drop this to STUDIED |
| Delta Lake internals (`_delta_log`, time travel, VACUUM) | SHIPPED | Deep — see the three-stores model |
| DLT / Lakeflow SDP | SHIPPED | Apollo Gen2, 422 pipelines |
| Databricks Asset Bundles / IaC | SHIPPED | |
| Serverless vs classic compute tradeoffs | SHIPPED | |
| Photon | TOUCHED | Confirmed by evidence, `?` dropped: `runtime_engine: PHOTON` in the cluster configs, plus real reasoning in your comments — DBU multiplier, vectorised execution, a deliberate Photon-OFF choice, and "Photon cannot project an all-NULL VO". That last one is a caveat you only learn by hitting it |
| Apache Iceberg | NEVER? | GUESS: 6 hits, all in study material I wrote. Zero production contact |
| Apache Hudi | NEVER? | GUESS: 1 hit, study material |
| dbt | STUDIED? | GUESS, **and my earlier citation was wrong** — I claimed "`portable_mds` setup exists"; `find` returns nothing in this repo. The real basis is a dbt-on-Databricks wiring exercise recorded only in machine-local memory (which doesn't migrate). Your Part 1 words: "Never worked with powerbi or dbt etc." Drop to NEVER if you don't count that exercise |
| Snowflake | STUDIED? | GUESS: 15 knowledge files, 0 production hits |
| BigQuery | NEVER? | GUESS: no evidence anywhere |
| Redshift | NEVER? | GUESS: no evidence anywhere |
| Trino / Presto / Athena | NEVER? | GUESS: 1 hit, study material |
| Flink | NEVER? | GUESS: no evidence anywhere |
| Hadoop / Hive / MapReduce | NEVER? | GUESS, **and this is the false-positive row**: 11 files matched "Hadoop" and 5 matched "Hive" in the client repo. Every one was `spark.hadoop.fs.azure.*` (an Azure connector config namespace) or the substring inside `skipped_arc`**`hive`**`d`. Neither is Hadoop or Hive |
| Polars / DuckDB | NEVER? | GUESS: DuckDB appears only in JARVIS's own endgame doc as a *future* choice for the Analyst. Polars: zero hits |

### Orchestration & movement
| Item | Depth | Notes |
|---|---|---|
| Databricks Workflows / Jobs | SHIPPED | for_each, condition_task, cross-workspace |
| Azure Data Factory | STUDIED | `?` dropped: `ADF_Deep_Dive.md` is study material and there are zero production hits. Raise it if you used ADF somewhere I can't see |
| Airflow | STUDIED? | GUESS: 8 knowledge files, 0 production hits |
| Control-M | | **RETRACTED — this was my error.** I had marked it `TOUCHED?` claiming "named in the BUPA stack." Zero hits in the client repo, in `knowledge/`, or in the KB. I appear to have invented it. Blank is the honest state — over to you |
| Dagster / Prefect | NEVER? | GUESS: no evidence anywhere |
| Qlik / Attunity CDC | | **RETRACTED — same error as Control-M.** "In the stack" was unsupported: zero hits for Attunity, one for Qlik and it's in study material |
| Debezium | NEVER? | GUESS: 2 hits, study material |
| Kafka / Event Hubs | STUDIED | **Yours, not a guess** — Part 1: "Have't gotten any situation where I would try out kafka or event hubs" |
| Fivetran / Airbyte | NEVER? | GUESS: 1 hit each, study material |

### Storage, governance, platform
| Item | Depth | Notes |
|---|---|---|
| ADLS Gen2 / abfss, SP OAuth, RBAC | SHIPPED | |
| Unity Catalog (as a user) | SHIPPED | |
| Unity Catalog (rollout / design) | NEVER | **Yours, not a guess** — Part 1, governance rollout: "did you ever roll it out? -- NO" |
| Immuta | TOUCHED | Worked around its masking; didn't own it |
| Purview / Collibra / Alation | NEVER? | GUESS: 1 hit for Purview, study material. Zero for the others |
| S3 / GCS | NEVER? | GUESS: the estate is entirely Azure across both projects |
| Azure vCPU quota, pools, spot economics | SHIPPED | Learned the hard way, Aug 2026 |
| Terraform | NAME-ONLY? | GUESS: one comment in the client repo notes that `terraform apply` validates every `job_cluster`. That's awareness of a constraint someone else's IaC imposes on you, not using it |
| Kubernetes | NEVER? | GUESS: 1 hit, study material |
| CI/CD (Azure DevOps pipelines) | TOUCHED | `azure-pipelines.yml` present in the repo |

### Modelling & warehousing
| Item | Depth | Notes |
|---|---|---|
| Medallion architecture | SHIPPED | |
| SCD Type 2 / CDC merge patterns | SHIPPED | |
| Kimball dimensional modelling | STUDIED | **Yours, not a guess** — Part 1: "I have only STUDIED about data modeling concepts like startschema etc… the data models were already built" |
| Data Vault | NEVER? | GUESS: 2 hits, study material |
| One Big Table / wide denormalized | NEVER? | GUESS: no evidence. Though you may have *encountered* wide gold tables without designing one — that'd be NAME-ONLY |
| Data mesh / domain ownership | NEVER? | GUESS: zero hits anywhere, including study material |

### Languages & tooling
| Item | Depth | Notes |
|---|---|---|
| Python | SHIPPED | |
| SQL (analytical, window functions) | SHIPPED | |
| PySpark | SHIPPED | |
| Scala | NAME-ONLY? | GUESS, **false-positive row**: all 5 client-repo matches are `15.4.x-scala2.12` (the DBR runtime version string) or a stack-trace example. You know Scala UDFs exist and cost differently — you've never written one |
| PowerShell | TOUCHED | Enough to hit the `` `v `` escape bug |
| Bash / Linux | TOUCHED? | GUESS: WSL Ubuntu daily, `scripts/`, Claude Code, git from the shell. TOUCHED not SHIPPED because I've no evidence you've written anything substantial *in* bash as a deliverable |
| Git (rebase, conflict resolution, history rewriting) | TOUCHED? | GUESS, **and the row bundles three different things**: daily commit/branch use is clearly TOUCHED+; conflict resolution likely TOUCHED; **history rewriting is probably NEVER** — nothing in this repo shows a rebase or filter-branch. Consider splitting the row |
| Java | NEVER? | GUESS, **false-positive row**: both client-repo matches are `Py4JJavaError`, a Python-side Databricks exception, and a mention of "legacy Java exception class names". Neither is Java |

### Reliability & operations
| Item | Depth | Notes |
|---|---|---|
| Reading Spark UI / event logs for diagnosis | SHIPPED | GC stalls, shuffle signatures, executor death |
| Production incident under time pressure | SHIPPED | Three prod failures in one day, 2026-08-20 |
| On-call rotation / pager | NEVER | **Yours, not a guess** — Part 1: "what do you mean pager? I haven't". Worth naming the generalization: **no on-call culture exposure at all**, which is probably the single cause behind most of this block rather than several separate gaps |
| SLA/SLO definition and defence | NEVER? | GUESS: follows from the row above — defining and defending an SLO is an on-call-culture activity |
| Backfill / replay strategy at scale | TOUCHED? | GUESS: the gen1→gen2 SCD2 historical-load POC is exactly this shape — loading history separately from the incremental path. Raise it if you owned the replay design |
| Disaster recovery (designing, not validating) | NEVER | **Yours, not a guess** — Part 1: "I was added to the project after the Deepclone framework was already built". You validated a DR design; you didn't author one |
| Cost governance at org scale | NEVER | **Yours, not a guess** — Part 1: "that was just optimization not cost optimization" |
| Post-incident review / blameless postmortem | TOUCHED? | GUESS: `SESSION_LEARNINGS.md` **is** a postmortem practice and an unusually disciplined one — but self-run, on your own work. TOUCHED not SHIPPED because I've no evidence of a team process you ran or were reviewed by |

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
