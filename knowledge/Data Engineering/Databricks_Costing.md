# Databricks Costing — Complete Reference

> Consolidated interview/revision guide. Two parts: **Part 1** = the core costing model (DBU model, pricing matrix, Photon, serverless vs classic, optimization levers, observability, discounts, storage). **Part 2** = the specialized corners (Model Serving / GPU / Mosaic AI, SQL Warehouse sizing, cluster policies, per-instance DBU ratings, cloud-side levers, dashboards/budgets).
>
> **Accuracy note:** all `$/DBU` figures are US-region **list prices, illustrative** — the official pricing pages are JS-rendered; rates vary by cloud/region/tier/discount. **DBU *counts* are the stable, authoritative quantity.** Specialized numbers in Part 2 were web-verified against MS Learn pricing tables (2026-06-11); model rosters and token rates churn — quote mechanisms confidently, rates "as of mid-2026."

---

# PART 1 — Core Costing Model

## 1. The cost model

> **Total cost = Compute (DBUs × $/DBU) + Infrastructure + Storage**

Started as a 2-part equation, expanded to **3 axes**:

- **DBU** = *Databricks Unit* — a unit of **processing throughput-per-hour**. The billing currency, the "Databricks software tax."
- **It is NOT dollars** (multiply DBUs by a $/DBU rate to get dollars) and **NOT compute-hours** (a bigger/faster VM burns more DBUs per hour).
- **DBUs consumed** = Σ over the cluster's life of `(instance DBU-rate/hr × hours running)`.

**Anchor line:** *Databricks bills you twice in classic — DBUs to Databricks, VMs to the cloud. Serverless folds both into one DBU rate. Storage is a third, separate bill.*

---

## 2. Compute / infra decoupling

The architecture that explains everything: **Control Plane vs Data Plane.**

| Plane | What runs there | Who pays |
|---|---|---|
| **Control plane** | Web UI, job scheduler, cluster manager, query history — Databricks' brain | Databricks (their cloud) |
| **Data plane (classic)** | The actual compute clusters (VMs) | **Your cloud account** — VM bill goes straight from AWS/Azure to *you* |
| **Data plane (serverless)** | Ephemeral compute Databricks spins up | Databricks' cloud account → bundled into the DBU rate |

**The two halves:**

| | Compute (the DBU) | Infrastructure |
|---|---|---|
| Is | the Databricks *software* (runtime, Photon, optimizer, UC, scheduler) | the raw *hardware* (VMs, disk, network) |
| Billed by | Databricks, as DBUs | cloud provider (classic) / bundled (serverless) |

**Why classic gives two bills:** in classic the VMs run **in your own cloud subscription**, so AWS/Azure bills you for them directly, separate from the DBU bill.

**Why they were decoupled (3 reasons):**
1. Databricks is a **software vendor running on top of** AWS/Azure/GCP — charging software (DBU) separately from hardware keeps it cloud-agnostic.
2. **You keep your cloud economics** — your reserved instances, spot, enterprise discounts apply to the infra half.
3. **Separation of concerns / data residency** — your data + compute stay in your account (classic).

---

## 3. Pricing matrix — compute types × tiers

*(List $/DBU, illustrative — varies by cloud/region; always confirm on the calculator.)*

**Compute types (SKUs):**

| Compute type | ~$/DBU | Use | Note |
|---|---|---|---|
| **All-Purpose (interactive)** | ~$0.40–0.55 | Notebooks, dev, ad-hoc | **2–3× pricier** than Jobs — never run prod ETL here |
| **Jobs Compute** | ~$0.15–0.30 | Scheduled/automated ETL | Cheapest classic; ephemeral job clusters |
| **DLT / Lakeflow Pipelines** | tiered (Core/Pro/Advanced) | Declarative pipelines | Advanced (CDC/expectations) costs more |
| **SQL Classic** | ~$0.22 | BI on classic warehouse | Lowest SQL rate |
| **SQL Pro** | ~$0.55 | BI + Predictive I/O, IWM | |
| **SQL Serverless** | ~$0.70 US / ~$0.91 EU | Instant/spiky BI | Infra bundled; scales to zero |

**Tiers** (higher tier = higher $/DBU, more governance):

| Tier | Adds | 2026 status |
|---|---|---|
| Standard | basic | **Sunset** Oct 2025 (AWS/GCP); Azure by Oct 2026 |
| **Premium** | Unity Catalog, RBAC, audit | **Default now** |
| Enterprise | HIPAA, customer-managed keys (CMK), enforced private link | Regulated only (AWS/GCP; Azure has no Enterprise tier — Azure Premium ≈ AWS Enterprise) |

---

## 4. Photon — the multiplier trap

- **What:** vectorized C++ engine using **SIMD** (*Single Instruction Multiple Data* — one CPU instruction processes a whole batch of column values).
- **Mechanism:** it does **not** change $/DBU; it raises the **DBU consumption rate** (~2× — the node burns DBUs faster).
- **Why it can still be cheaper:** for **vectorizable** work it finishes in ⅓–⅛ the wall-clock, so **net DBUs drop** → cheaper *and* faster.
- **When it wastes money:** non-vectorizable work pays the higher rate with **no speedup**.

**✅ Vectorizable (enable Photon):**

| Class | Example |
|---|---|
| Scans/filters/projections | `SELECT a,b FROM t WHERE dt >= '2026-01-01'` |
| Joins | `orders JOIN customers ON customer_id` |
| Aggregations | `GROUP BY region` with `SUM/COUNT/AVG` |
| Window functions | `ROW_NUMBER() OVER (...)` |
| Delta DML writes | `MERGE`/`UPDATE`/`DELETE` |
| Built-in expressions/casts | `to_timestamp()`, `regexp_extract()` |

**❌ Non-vectorizable (Photon falls back to JVM, you still pay premium):**

| Class | Example | Why |
|---|---|---|
| Python UDF | `@udf("double") def f(x): ...` | row serialized JVM→Python→JVM |
| Scala/Java UDF | `spark.udf.register(...)` | arbitrary JVM closure |
| RDD API | `sc.textFile().map().reduceByKey()` | bypasses Catalyst/Photon |
| Pandas/Arrow UDF | `@pandas_udf(...)` | Arrow-batched (less bad) but runs in Python workers |
| Spark ML training | `LogisticRegression().fit()` | iterative, not query vectorization |

**The win (say this in interviews):** *Most "Photon didn't help" cases are UDFs that didn't need to be UDFs.* Rewrite the UDF as a native SQL expression and Photon accelerates it:

```sql
-- UDF version: falls back to JVM
-- native version: vectorized, Photon-accelerated
SELECT *, CASE WHEN tenure < 12 THEN amount*0.03 ELSE amount*0.01 END AS risk FROM t
```

**Mixed plan:** if 90% is scan/join/agg + one UDF, Photon runs the 90% natively and falls back only for the UDF. A *pure*-UDF/RDD job gets ~zero benefit + full premium = the "pure waste" case.

---

## 5. Serverless vs classic

| | Classic | Serverless |
|---|---|---|
| Infra bill | separate (you pay cloud for VMs) | **bundled** into DBU rate |
| Startup | 4–7 min cold | seconds |
| Idle | pay until auto-terminate | **scales to zero** |
| Spot/discounts | yes (spot on infra) | no knob |
| Tuning | you size it | auto-managed |

**Performance modes (serverless):**
- **Standard** — fewer DBUs, **~70% cheaper**, 4–6 min startup. Jobs + Pipelines only (not notebooks). Best for batch.
- **Performance-optimized** — fast startup, higher burn. Latency-sensitive/interactive.

**Break-even rule:** serverless wins for **short/spiky/infrequent** jobs (< ~30 min); long, predictable jobs may be cheaper on **classic + spot + Photon**.

**Why serverless $/DBU looks HIGHER (it's apples-to-oranges):** the serverless rate **bundles** (1) the infra/VM cost Databricks pays for you, and (2) the **elasticity premium** (scale-to-zero, instant start, no idle). The honest comparison:

| | Classic Jobs | Serverless Jobs (Standard) |
|---|---|---|
| Databricks $/DBU | $0.15 | $0.45 (bundled) |
| Separate VM bill | + $0.10/DBU-equiv | $0 |
| Idle/startup waste | + cold-start + idle | $0 |
| **True all-in** | $0.25 **+ idle** | **$0.45 flat** |

> So compare `serverless $/DBU` **vs** `classic $/DBU + infra + idle waste` — not the headline numbers.

---

## 6. Optimization levers

| Lever | Saves on | Magnitude | Gotcha |
|---|---|---|---|
| **Move ETL: All-Purpose → Jobs** | DBU | **2–3×** | highest-impact, zero code change |
| **Auto-terminate** (idle timeout) | DBU + infra | huge | idle = silent burn |
| **Autoscaling** | DBU + infra | 20–40% | thrash on bursty loads can cost more |
| **Spot / Fleet** | **infra only** | up to 90% off VMs | **DBU unchanged**; eviction risk → fault-tolerant batch only |
| **Photon** (vectorizable only) | net DBU | ⅓–⅔ | useless on UDF/RDD |
| **Serverless Standard mode** | DBU | ~70% | 4–6 min startup |
| **Instance pools** | startup time | indirect | warm VMs cut cold-start waste |
| **Right-size cluster** | DBU + infra | varies | over-provisioning is the default sin |
| **Liquid Clustering / OPTIMIZE / Z-Order** | DBU (less scan) | varies | better layout → fewer scan DBUs |
| **Predictive Optimization** | storage + DBU | auto | UC-managed OPTIMIZE/VACUUM |
| **Committed Use Discounts** | $/DBU | **18–48%** | annual commit |

**Spot, precisely:** spot is a **cloud-infra discount** (up to ~90% off VM on-demand). It discounts **only the VM line item**. The **DBU rate is set by Databricks and is indifferent to the VM lifecycle** — a spot VM and an on-demand VM of the same type burn the same DBUs. On **serverless you have no spot knob → no spot savings.**

```
Classic node, 2 hrs:   DBU (Databricks)  +  VM (cloud)
  on-demand:           [unchanged]       +  $X
  spot:                [unchanged]       +  $0.1X   ← only this half moves
Serverless:            [bundled rate]              ← no separate VM line, no spot
```

---

## 7. Observability & attribution

**What "attribute spend" means:** mapping every DBU/dollar to the **responsible entity** — team, project, cost-center, env, job — for chargeback/showback and answering *"who/what caused this cost?"*

**System tables (source of truth):**

| Table | What |
|---|---|
| `system.billing.usage` | one row per usage record: `sku_name`, `usage_quantity` (DBUs), `usage_date`, `usage_metadata` (job/cluster/warehouse IDs), `identity_metadata` (who), `custom_tags` |
| `system.billing.list_prices` | $/DBU per SKU over time → join to convert DBUs → $ |

**The canonical cost query:**
```sql
SELECT u.sku_name, u.usage_date,
       SUM(u.usage_quantity)                     AS dbus,
       SUM(u.usage_quantity * p.pricing.default) AS est_cost_usd
FROM system.billing.usage u
JOIN system.billing.list_prices p
  ON u.sku_name = p.sku_name
 AND u.usage_end_time BETWEEN p.price_start_time AND COALESCE(p.price_end_time, now())
GROUP BY u.sku_name, u.usage_date
ORDER BY est_cost_usd DESC;
```

**Serverless vs non-serverless attribution:**

| | Non-serverless | Serverless |
|---|---|---|
| Taggable unit | the cluster/job/warehouse (you tag it) | **none** — ephemeral compute |
| How tags get applied | tag the resource → flows to `custom_tags` | **serverless budget/usage policy** stamps tags onto the *user's* serverless activity |
| Failure if skipped | untagged = "misc" bucket | **all serverless spend unattributable** |

> Classic: you attribute by tagging the cluster. Serverless has no cluster → **serverless usage policies** (admin defines a tag-bundle, assigns to users/groups; tags land in `custom_tags`).

**Plus:** **budgets + budget alerts** (account-wide or filtered by team/project/workspace, with email alerts).

---

## 8. Commercial — committed-use discounts

- **DBCU / DCU:** commit annual consumption → tiered discount, usable across AWS/Azure/GCP.
- Rough bands: **$1M commit → 18–28% off; $3M → 25–38%; $10M → 35–48%.**
- Pay-as-you-go (no commit) = list price.

---

## 9. Storage costs (the third axis)

| Component | What | Grows because |
|---|---|---|
| Active Delta data | current Parquet in S3/ADLS/GCS | data volume; $/GB/month |
| Old versions / history | every MERGE/UPDATE/DELETE writes **new** files; old ones kept for time-travel | retained until **VACUUM** — unbounded if never run |
| Small-file bloat | many tiny files (streaming/frequent writes) | bad layout |
| Logs/checkpoints | `_delta_log`, streaming checkpoints | accumulate |

**The storage→compute coupling (the non-obvious bit):** bad layout (small files, no clustering) → more files to open → **more DBUs to scan** → higher *compute* bill. So storage hygiene cuts **both** axes.

**Levers:** `VACUUM` (drop files past retention), `OPTIMIZE` (+ Z-Order) to compact, **Liquid Clustering**, **Predictive Optimization** (UC auto-runs them), retention tuning (`delta.deletedFileRetentionDuration`, `logRetentionDuration`), bucket lifecycle policies.

```sql
OPTIMIZE sales ZORDER BY (customer_id);   -- compact + co-locate → fewer scan DBUs
VACUUM sales RETAIN 168 HOURS;            -- drop files >7 days old
```

---

## 10. Interview drills + gotchas (Part 1)

**Rapid-fire:**
1. *DBU?* → unit of processing/hr; the billing currency; not $ or hours.
2. *All-Purpose vs Jobs for nightly ETL?* → Jobs, 2–3× cheaper.
3. *Photon always cheaper?* → No; vectorizable only; loses on UDF/RDD.
4. *Does spot cut my Databricks bill?* → infra half only; DBU unchanged; nothing on serverless.
5. *Serverless or classic for a 10-min spiky job?* → serverless (zero idle).
6. *…for a 4-hr predictable batch?* → likely classic + spot + Photon (compare).
7. *Attribute serverless spend with no cluster?* → serverless usage policies → `custom_tags`.
8. *Bill spiked 3×?* → query `system.billing.usage` by `sku_name`+`custom_tags`+`usage_metadata.job_id`, join `list_prices`, diff vs last week.
9. *Biggest single win on a messy account?* → move stable work off All-Purpose to Jobs + enforce auto-terminate.
10. *Why is serverless $/DBU higher?* → infra bundled; no separate VM bill + no idle.

**Gotchas:** DBU ≠ $; DBU ≠ hours · Enterprise tier costs more per DBU — don't default to it · idle interactive clusters are the #1 hidden cost · autoscaling thrash · DLT Advanced tier bills higher · storage (old versions, no VACUUM) grows silently.

**One-liner:** *Databricks cost = compute (DBUs) + infra (VMs or bundled) + storage; cut it by burning fewer DBUs and scanning less data, buy it cheaper with commits/spot/serverless-Standard, control it by attributing every DBU via tags + `system.billing.usage`.*

---

# PART 2 — The Specialized Corners

*(Web-verified against MS Learn pricing tables, 2026-06-11. `~$0.07/DBU` = Serverless Real-Time Inference, US list.)*

## 11. Model Serving / GPU / Mosaic AI / per-token pricing

**Unifying mechanism:** everything AI bills in **DBUs on serverless SKUs**, converted at ~**$0.07/DBU** (US list; $0.088 AP Sydney — region multiplies the $, never the DBU count). Sanity check: Claude Haiku 4.5 input = 14.286 DBU/1M × $0.07 = **$1.00/1M**, exactly Anthropic's list price in DBU clothing.

**Four distinct billing units:**

| Product | Billing unit | Rate (verified) |
|---|---|---|
| **Custom CPU serving** | per provisioned **concurrency slot** | **1 DBU/hr per concurrent request** (Small = 4 slots = 4 DBU/hr ≈ $202/mo always-on); slots in multiples of 4 |
| **Custom GPU serving** | flat DBU/hr per **instance size** | T4 Small **10.48** → 1×A10G **20** → 1×A100-80GB **78.6** → 8×A100-80GB **628 DBU/hr** (≈$44/hr) |
| **Foundation Model APIs** | per **token** (PPT) or per **throughput band** (PT) | see below |
| **Vector Search** | per **vector-search-unit-hour** | Standard **4.0 DBU/hr**/unit (2M vectors @768-dim); storage-optimized **18.29** (64M vectors) |

**Pay-per-token (PPT) vs provisioned throughput (PT):**
- **PPT** (shared, rate-limited, **zero idle cost**): Llama 3.3 70B = 7.143 in / 21.429 out DBU per 1M (≈ $0.50/$1.50); Llama 3.1 8B ≈ $0.15/$0.45; Claude Sonnet ≈ $3/$15; Claude Opus ≈ $5/$25. Extra meters people forget: **cache-write** (~1.25× input), **cache-read** (~0.1×), long-context (>200k) surcharge, **In-geo ~10% premium** over Global.
- **PT** (reserved tokens/sec band, flat DBU/hr, per-minute billing): Llama 3.3 70B = **85.714 DBU/hr ≈ $6/hr ≈ $4.3k/month** per band. Autoscales in chunks (e.g. 980 tok/s).
- **Crossover:** steady monthly token spend at PPT rates < PT monthly flat → stay PPT. **PT is mandatory for serving fine-tuned models** — PPT doesn't support them.

**Fine-tuning (Foundation Model Training SKU — verified):** bills DBUs as **training tokens × epochs × model size** at ~**$0.65/DBU** — *not* cluster-hours. Llama 3.1 8B on 10M words = 100 DBUs = **$65**; 70B on 500M words = 11,000 DBUs = **$7,150**. Hidden cost: the result needs a PT endpoint, and *serving usually out-costs training within weeks.*

**The three idle traps:**
1. A serving endpoint **without scale-to-zero bills full rate 24/7 at zero traffic** — idle 1×A10G ≈ $1k+/month. Scale-to-zero (30-min idle) zeroes it but adds cold starts, no SLA, and a separate **LAUNCH SKU** charge per wake.
2. **Vector Search has NO scale-to-zero**: billing starts at first index creation, 1-unit minimum, runs 24/7 regardless of queries, stops only 24h after the last index is deleted. Consolidate indexes onto one endpoint; prefer **triggered** over continuous sync.
3. **AI Gateway inference tables bill 7.143 DBU/GB of logged payload** — observability itself becomes a line item.

**Attribution:** `system.billing.usage` with `sku_name LIKE '%SERVERLESS_REAL_TIME_INFERENCE%'` and `usage_metadata.endpoint_name`.

---

## 12. SQL Warehouse sizing mechanics

**Mechanism:** a T-shirt size fixes ONE cluster's shape and a **fixed DBU/hr burn independent of query load** — idle-but-running bills the same as busy. Concurrency scales separately via **min/max cluster count**: each added cluster is a full copy, so **cost multiplies linearly with active clusters**.

**DBU/hr table (verified exact, MS Learn 2026-06-01):**

| Size | Workers | DBU/hr |
|---|---|---|
| 2X-Small | 1 | **4** |
| X-Small | 2 | **6** |
| Small | 4 | **12** |
| Medium | 8 | **24** |
| Large | 16 | **40** |
| X-Large | 32 | **80** |
| 2X-Large | 64 | **144** |
| 3X-Large | 128 | **272** |
| 4X-Large | 256 | **528** |

Workers double per step; DBU/hr steps 1.5–2× (driver doesn't double every step). 5X-Large (512) is Public Preview, no published rate.

**Worked math:** Medium × 3 clusters fully scaled × 4 hr = 24 × 3 × 4 = **288 DBUs** → serverless ≈ $201.60 all-in at $0.70/DBU; pro = $158.40 *plus* the cloud VM bill.

**Mechanics that get asked:**
- **Scale-UP vs scale-OUT (classic trap):** more clusters **never** speed up one query — they add concurrency slots (~10 concurrent queries/cluster on pro/classic). *Disk spill in the query profile → bigger size. Queued queries → more clusters.*
- **Pro/classic autoscale schedule (verified):** estimated time-to-clear 2–6 min → +1 cluster; 6–12 → +2; 12–22 → +3; >22 → +3 plus 1 per extra 15 min; any query queued 5 min forces upscale; 15 min low load scales down. **Serverless replaces this with IWM** (Intelligent Workload Management).
- **Auto-stop defaults (verified):** serverless **10 min** (UI min 5, API min 1); pro/classic **45 min** (min 10); API default 120, `0` = never. Why: serverless cold-starts in **2–6 s**, classic **~4 min**.
- **Why serverless often nets cheaper despite $0.70 vs $0.22:** all-in rate (no VM/disk bill — Azure classic adds a 256 GB Premium SSD per node, hourly), fine-grained metering, 10-min stop, IWM. Classic wins on saturated near-24/7 load with **spot** (Cost Optimized = workers on spot, driver always on-demand; classic only, now API-only — hedge).
- **Gotcha:** 24h cluster recycling can transiently exceed configured max — don't panic-debug it. Auto-stop=0 on a Medium = 17,280 DBUs/month (~$12k serverless) for nothing.

---

## 13. Cluster policies as cost control

**Mechanism:** a workspace JSON rule-set enforced **at compute-creation time**. Each Clusters-API attribute path gets one rule from seven types: `fixed` (pin + optionally hide), `forbidden`, `allowlist`, `blocklist`, `regex`, `range`, `unlimited`. Users without "unrestricted cluster creation" can only create compute through granted policies — zero policies = no compute creation.

**The cost-guardrail policy (snippet to know):**

```json
{
  "cluster_type":              {"type": "fixed", "value": "job"},
  "dbus_per_hour":             {"type": "range", "maxValue": 100},
  "node_type_id":              {"type": "allowlist", "values": ["i3.xlarge","i3.2xlarge"], "defaultValue": "i3.xlarge"},
  "autoscale.max_workers":     {"type": "range", "maxValue": 10, "defaultValue": 4},
  "autotermination_minutes":   {"type": "range", "minValue": 10, "maxValue": 60, "defaultValue": 30},
  "aws_attributes.availability":   {"type": "fixed", "value": "SPOT_WITH_FALLBACK", "hidden": true},
  "aws_attributes.first_on_demand":{"type": "fixed", "value": 1, "hidden": true},
  "custom_tags.COST_CENTER":   {"type": "allowlist", "values": ["9999","9921","9531"]}
}
```

**Key attributes:**
- **`dbus_per_hour`** — synthetic, Databricks-calculated: the only direct **cost-rate cap** per cluster (driver included; `range` with `maxValue` only). Caps *rate*, not duration — pair with autotermination + "max compute resources per user."
- **`cluster_type` fixed to `"job"`** — policy then doesn't appear in the all-purpose create UI → users can't create $0.55/DBU interactive clusters when $0.15–0.30 jobs compute would do. Inverse: `workload_type.clients.jobs: false` on all-purpose policies stops scheduling jobs onto interactive clusters.
- **Mandatory `custom_tags.*`** — launch impossible without a valid tag → chargeback flows to `system.billing.usage.custom_tags`.
- **Spot enforcement** — fix availability to spot-with-fallback, `first_on_demand: 1` keeps driver on-demand (driver eviction kills the cluster).
- **`runtime_engine`** — fix STANDARD to block Photon's DBU uplift, or PHOTON where it wins.

**Three traps:**
1. **Policy edits don't retro-apply** to existing clusters — run compliance enforcement ("Fix all").
2. **`defaultValue` only fills the UI** — API/Terraform-created clusters ignore it unless the spec sets `apply_policy_default_values: true`. Classic "works in UI, jobs never terminate via IaC" bug.
3. **Personal Compute is enabled account-wide by default** — single-node all-purpose, **72-hour** auto-termination, no per-user cap. Most common surprise-spend hole; disable or delegate it.

**Governance one-liner:** *Cluster policies **prevent** (ex-ante config control, classic only); tags/usage-policies **attribute**; budgets **detect** (alert-only). Nothing hard-stops general compute spend mid-month.* Serverless compute is **not** governed by cluster policies — only usage policies.

---

## 14. Per-instance DBU/hr ratings + the calculator

**Mapping rule:** every classic instance type carries a fixed published **DBU count/hr**; cluster burn = **sum over all nodes (driver + workers)**, metered per-second. The DBU count never varies by tier/region — only the $/DBU does.

| Instance | vCPU / RAM | DBU/hr | Confidence |
|---|---|---|---|
| Azure DS3_v2 | 4 / 14 GiB | **0.75** | verified |
| Azure DS4_v2 | 8 / 28 | **1.5** | verified |
| Azure DS5_v2 | 16 / 56 | **3.0** | verified |
| Azure D4ads_v5 | 4 / 16 | **1.0** | verified |
| Azure D8ads_v5 | 8 / 32 | **2.0** | verified |
| Azure E8ds_v4 | 8 / **64** | **2.0** | verified |
| AWS m5.xlarge | 4 / 16 | 0.69 | *2020 source; re-check live calculator* |
| AWS m5.2xlarge / **r5.2xlarge** | 8 / 32 vs **64** | both **1.37** | *same caveat* |
| AWS i3.xlarge | 4 / 30.5 | 1.0 | *same caveat* |

**Patterns to memorize:**
- DBU scales ~**linearly with vCPU within a family** (0.75 → 1.5 → 3.0). ~0.17–0.25 DBU per vCPU-hr; newer v5 rate 0.25/core.
- **RAM is mostly free in DBU terms**: r5.2xlarge (64 GB) = m5.2xlarge (32 GB) = 1.37 DBU/hr; E8ds_v4 (64 GiB) = D8ads_v5 (32 GiB) = 2.0. **Spilling to disk? Memory-optimized is often a free upgrade on the Databricks bill** — pay only the small VM delta.
- But families differ: i3.xlarge = 1.0 vs m5.xlarge = 0.69 for same 4 vCPU — table lookup, not a formula.
- **Photon on classic** ≈ doubles the instance's DBU rating (measured: E8ds_v5 $6.27/hr → $10.80/hr; docs only say "a different rate" — hedge the 2×). **Default-ON in the UI** for new classic compute → silent uplift on UDF-heavy work. On SQL warehouses/serverless Photon is always-on and already in the price.
- **Worked example:** 1 driver + 4 workers, all DS3_v2, Azure Premium all-purpose, 2 hrs = 5 × 0.75 × 2 = **7.5 DBUs** ≈ $4.13 to Databricks + 10 VM-hours to Azure.

**The calculator:** `databricks.com/product/pricing` — inputs cloud + tier + compute type + instance + count + hours; computes `count × hours × DBU-rating × $/DBU`. **Azure shows VM+DBU combined per row; AWS shows DBU-only** (EC2 on the AWS bill) — naive Azure-vs-AWS comparisons mislead. Azure Jobs lists ~$0.30/DBU, not AWS's $0.15.

---

## 15. Cloud-side levers (the half Databricks doesn't bill)

**The stacking insight:** the two meters take **disjoint discount instruments that stack**:

| Meter | Instrument | Magnitude |
|---|---|---|
| **DBU** (Databricks) | Azure **DBCU pre-purchase** (1/3-yr prepaid pool) — *verified: drawdown at list ratio (All-Purpose Premium 0.55 units/DBU, Jobs 0.30), no cancel/exchange, "applies only to DBU usage"* | up to **37%** (3-yr, verified); ~33% 1-yr (*illustrative*). AWS: private negotiated commits only |
| **VM** (cloud) | Azure RIs / savings plans, AWS Savings Plans/RIs — ordinary VMs in *your* subscription | vendor-best-case 65–72%; realistic far lower |

Photon burns the DBCU pool faster. **Neither instrument touches serverless.** Spot stacks on the VM meter instead of RIs. ⚠️ Azure retires RI purchases/renewals for legacy VM series (Dv2/Dsv2/Dv3/Esv3 — common Databricks families) on **July 1, 2026**.

**Networking — silent leaks:**
- **#1 on AWS: NAT gateway at $0.045/GB processed** for private-subnet clusters reading S3. Fix: **free S3 gateway VPC endpoint** ($0/GB) or interface endpoint ($0.01/GB ≈ 4.5× cheaper than NAT).
- **Colocate compute and storage region** — cross-region reads bill $0.02–$0.09/GB *on every read, forever* (500 GB/day ≈ $300–400/mo).
- AWS cross-AZ = $0.01/GB each direction (Databricks places a cluster in one AZ); **Azure cross-AZ is now free** (2024 — older sources are stale).
- Databricks rolling out **serverless networking charges** (private-connectivity per-GB) — rates not yet public.

**Delta Sharing egress:** data read **in place** — the **provider pays egress** when the recipient is cross-region/cross-cloud/internet (≈$0.09/GB internet). Same-region Databricks-to-Databricks = **free**. Mitigations: deep-clone replicate to recipient region (egress once, incrementally), CDF-based sync, or back shares with **Cloudflare R2** (zero egress — but no view sharing, no liquid clustering).

**Storage tiering traps:** never lifecycle-archive anything under **`_delta_log/`** (bricks the table); archived data files need **archival support** (`delta.timeUntilArchived`, DBR 13.3+, preview) or queries fail; lifecycle deletes must be ≥ VACUUM retention; cool/cold tiers add retrieval fees (a frequently-read table in cool tier often costs *more*); ADLS bills ops per 4 MB block, so small-file bloat multiplies transaction cost.

---

## 16. Dashboards, budgets, and alerts

**Prebuilt usage dashboard** (account console → Usage → import to any UC workspace; **GA on Azure 2026-03-18**, still preview on AWS): v2.0 ships four views — spend trend + run rate + **AI_FORECAST forecasting**; Top-N spend drivers with owners; **Tag Matching** (tagged/untagged/mismatched — untagged-spend finder); Top Objects with days-since-last-use (abandoned-resource finder). Viewers need SELECT on the two billing tables.

**Budgets (account console, Public Preview):**
- Monthly USD monitor = usage × **list price** (**discounts ignored** — budget "spend" overstates a discounted invoice).
- Scope by workspace / resource type / custom tags; up to **4 thresholds**, email lists; alerts lag up to **24h**.
- **Alert-only — never stops compute.** Exception: Genie / Unity AI Gateway budgets added per-user thresholds and a **"Block usage"** option (June 2026) — the platform's first hard-stop.
- Tag-scoped budgets only see usage that *carries* the tags → useless for serverless unless users have **serverless usage policies**.

**No native cost-anomaly detection (June 2026)** — the feature named "Anomaly detection" is *data-quality* monitoring (freshness/completeness), an interview trick. Cost anomalies = DIY SQL alert over `system.billing.usage` (docs ship a 7d-vs-14d trend query) or third-party (CloudZero, Revefi), plus Azure Cost Management anomaly alerts.

**Per-job cost (no cost column in Jobs UI):** join `system.billing.usage` (`usage_metadata.job_id IS NOT NULL`) × `list_prices` × `system.lakeflow.jobs` / `job_run_timeline`. **Gotcha:** only jobs-compute + serverless usage attributes to the job — a job run on an all-purpose cluster or SQL warehouse bills as the *cluster/warehouse* → "why does my job show zero cost."

**Utilization forensics:** `system.compute.node_timeline` — minute-level CPU/mem per instance, classic only, 90-day retention → proves paid-but-idle. `system.query.history` — 365 days, per-statement bytes/task-duration, **no dollar column** → allocate warehouse cost proportional to `total_task_duration_ms`. The non-billing system schemas (`compute`, `lakeflow`, `query`) must be explicitly enabled by an admin.

---

## The completed mental model

> **Three meters** (DBU / cloud infra / storage) **× three motions** (burn less / buy cheaper / see everything). AI workloads add four billing units (concurrency-hr, GPU-instance-hr, tokens, vector-unit-hr) with **idle traps as the dominant failure mode**; warehouses burn by **size × active clusters**, never by query load; **policies prevent, tags attribute, budgets only alert**; instance DBU ratings make memory upgrades nearly free and Photon a 2×-bet; cloud commits stack with DBCU because the meters are disjoint; NAT gateways + cross-region reads + Delta Sharing egress are the three silent cloud-side leaks.

**Caveats:** all `$/DBU` figures are US-list *illustrative* (official pages JS-rendered; corroborated by 2026 FinOps guides); DBU *counts* are the stable authoritative quantity; model rosters/token rates churn — quote mechanisms confidently, rates "as of mid-2026."
