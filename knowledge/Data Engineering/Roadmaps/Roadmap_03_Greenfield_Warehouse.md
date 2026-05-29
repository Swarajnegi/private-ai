# Roadmap 03 — Greenfield Data Warehouse Portfolio Project (4 weeks)

> **Goal:** Build the muscle of designing a data warehouse **from a business problem**, not from an existing source model. Ship a public GitHub repo that an interviewer can open in 30 seconds and recognize as senior DE work.
>
> **Why this is the gap-close you can't get at a consultancy:** All your production work (Apollo, LRC, PeopleSoft, BigQuery migration) starts from an *existing* source schema — the ERP / D365 / API hands you the entity model and you build pipelines downstream. You've never sat with a business stakeholder, said "what are you trying to answer," and designed a star schema from first principles. Product companies test for exactly this in their system-design rounds.
>
> **Outcome:** A public GitHub repo named something like `nyc-taxi-lakehouse`. Pinned to your GitHub profile. Mentioned on your resume under Projects. Becomes your default talk-track for "tell me about a project you built."
>
> **Time budget:** ~10 hrs/week × 4 weeks = 40 hrs. Compressible to 3 weeks at 13 hrs/week but don't go faster — the value here is *making real design decisions*, not racing.

---

## Pick your dataset (do this first, in 30 minutes)

Three good options, ranked for this project:

| Dataset | Why it fits | Volume | Difficulty |
|---|---|---|---|
| **NYC TLC Trip Data** ⭐ | Canonical taxi data — recruiters recognize it. Clean. Time-series facts + rich dimensions (zones, vehicles, payment types). Multiple grain options. | ~3B rows total, ~50M rows/month sample is plenty | ⭐⭐ |
| GitHub Archive | Modern event-stream feel. Great if you want to show Kafka-shaped thinking. But less obviously "warehouse-y". | ~1B events/year | ⭐⭐⭐ |
| Stripe BigQuery Public Set | Already business-shaped (orders, customers, refunds, disputes). Less work designing dimensions. | ~50M rows | ⭐⭐ |

**Default recommendation: NYC TLC Yellow Taxi.** Start with **1 month** (~10M rows) for development, scale to **6–12 months** for the polish phase. Data is at https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page (Parquet format since 2022 — perfect).

If you've never touched this data before: ask me "explain the NYC TLC schema" and I'll walk you through what's in it.

---

## Week 1 — Business Problem + Data Exploration

**The goal of this week is to NOT write any pipeline code yet.** This week is what consultancies skip and what product companies hire for.

**What you'll do**
1. **Pretend you're a product manager at a taxi company.** Write down 5 business questions you'd ask the data team:
   - *Example:* "What's our daily revenue trend over the last 12 months, broken down by borough?"
   - *Example:* "Which pickup zones have the highest tip percentage and what time of day?"
   - *Example:* "Driver utilization — what % of time are vehicles on trips vs idle?"
   - Write these as actual stakeholder language, not technical specs.
2. **Download 1 month of Yellow Taxi Parquet** (latest available month).
3. **Explore in DuckDB or pandas.** Don't model yet. Look at:
   - Row count, null distribution per column
   - Min/max ranges (any negative fares? trips longer than 24 hrs? GPS points in the Atlantic?)
   - Unique value cardinalities (how many zones? how many payment types?)
   - Time distribution (gaps? backfills?)
4. **Document the quirks.** Real DE work is 50% "this column has trailing whitespace, this one has impossible values, this date is in US format." Find at least 10 such quirks and write them down.

**Deliverable**
A repo with:
- `README.md` skeleton (just the project intro for now)
- `docs/business_questions.md` — your 5 stakeholder questions
- `docs/data_quirks.md` — your exploration findings
- `notebooks/01_explore.ipynb` — your DuckDB/pandas exploration

**Topics to ask about**
- "Explain the NYC TLC trip data schema column by column"
- "What are the most common data quality issues in NYC TLC?"
- "How do I frame business questions in stakeholder language vs technical language?"
- "What's the right sample size for a portfolio project — 1 month or 12 months?"

---

## Week 2 — Dimensional Modeling: Design the Star Schema

**This is the highest-leverage week.** What you produce here is the interview-defining artifact.

**What you'll do**

### Step 1: Identify your fact table(s)
- Most likely: `FactTrip` (one row per trip)
- Maybe also: `FactPayment` (one row per payment event — same trip can have 2 payments if you allow refunds)
- Maybe also: `FactTripSegment` (if you want to support multi-leg trips — probably overkill here)

### Step 2: Pick a grain — write it down explicitly
> **Grain:** One row per trip, where a trip is defined as `(vehicle_id, pickup_datetime, dropoff_datetime)` tuple.

The grain statement is the most important sentence in any warehouse design. **Recruiters look for it.**

### Step 3: Identify dimensions
Likely candidates:
- `DimDate` (the universal Kimball date dim)
- `DimTime` (hour-of-day, AM/PM, peak/off-peak)
- `DimLocation` (taxi zone, borough, lat/long centroid)
- `DimPaymentType` (cash, card, no-charge, dispute, etc.)
- `DimRateCode` (standard, JFK, Newark, etc.)
- `DimVendor` (taxi company)
- Possibly `DimVehicle` if you can join driver/vehicle data

### Step 4: Decide on SCD strategy
- Most dimensions are static here (DimDate, DimRateCode, DimPaymentType). SCD1 = simple overwrite.
- `DimLocation` could change if zones get redrawn (rare but happens). Pick SCD1 vs SCD2 and **justify**.
- Document your SCD choice per dimension.

### Step 5: Surrogate keys vs natural keys
- Use surrogate keys (integer `dim_id`s) for joins — interviewer signal.
- Keep natural keys (like `PULocationID` from source) as a non-key column for traceability.

### Step 6: Draw the schema
- Use draw.io, Lucidchart, or even pen and paper photographed.
- Fact table in the middle, dims around it, arrows showing FK relationships.
- Save as `docs/star_schema.png` in the repo.

**Deliverable**
- `docs/star_schema.png` — the diagram
- `docs/schema_decisions.md` — a 1–2 page write-up with:
  - **Grain statement** (the most important sentence)
  - List of fact and dim tables
  - SCD choice per dim + justification
  - Surrogate key strategy
  - At least 3 tradeoffs you considered and rejected (this is the part recruiters love)

**Topics to ask about**
- "What's a Kimball star schema and why does it dominate analytical warehouses?"
- "Explain dimensional modeling grain — give me 3 examples of choosing a grain wrong"
- "SCD Type 1 vs Type 2 vs Type 3 vs Type 4 — when does each fit?"
- "Why surrogate keys over natural keys?"
- "When should I use One Big Table instead of a star schema?"
- "What's a snowflake schema and why is it usually wrong?"
- "Star schema vs Data Vault — when is each right?"

> **Ask me to red-team your design before you build it.** Paste your schema decisions doc into chat — I'll attack it and you'll learn the holes interviewers would find.

---

## Week 3 — Build the Pipeline: Bronze / Silver / Gold

**You know this pattern from Apollo. Just do it for NYC TLC.**

**Setup options** (pick one):

| Option | Pros | Cons |
|---|---|---|
| **Databricks Community Edition** | Real Databricks env, great signal on resume | Limited compute, expires |
| **Local Spark + Delta Lake** | Free, persistent, full control | Setup overhead |
| **dbt + DuckDB** | Modern stack signal | Less Databricks-specific |
| **dbt + Databricks SQL** ⭐ | Best of both — modern + your stack | Need Databricks workspace |

**My recommendation:** **dbt + Databricks Community Edition or Databricks Free Trial.** Reasons:
- dbt is the lingua franca of product-co data teams in 2026 — having dbt models in your repo is a green flag
- Databricks runtime stays in your skill stack
- Free for portfolio scale

**What you'll build**

### Bronze layer
- Raw ingestion of NYC TLC Parquet files via Auto Loader (Databricks) or `spark.read.parquet()` (local)
- Land in Delta format
- No transformations — preserve the source

### Silver layer
- Type casting (string → timestamp, string → decimal)
- Business cleanup: filter impossible values (negative fares, 50-hour trips, NULL pickup zones)
- Deduplication if needed
- Conformed dimensions: this is where you build out `DimLocation`, `DimDate`, etc.

### Gold layer
- `FactTrip` joined to all surrogate keys from dims
- Aggregate marts for your 5 business questions:
  - `agg_daily_revenue_by_borough`
  - `agg_zone_tip_pct_hourly`
  - etc.

**Deliverable**
- `models/bronze/*.sql` (or `.py` if PySpark)
- `models/silver/*.sql`
- `models/gold/*.sql` (one model per business question + the fact + dims)
- A working pipeline that runs end-to-end: `dbt run` (or your equivalent) executes cleanly
- Commit everything to public GitHub

**Topics to ask about**
- "Walk me through dbt's project structure"
- "How do I structure a Databricks-Asset-Bundle alternative for portfolio scale?"
- "Auto Loader vs `spark.read.parquet` — when does each win for ingestion?"
- "How do I write SCD Type 2 in dbt?"
- "What's an incremental model in dbt?"
- "How do I do data tests in dbt (uniqueness, null checks, custom assertions)?"

---

## Week 4 — Performance + Polish + Talk-Track

### Performance pass
- **Partition columns**: pick wisely. Usually `pickup_date` (year-month-day) for time-series fact tables.
- **OPTIMIZE + ZORDER** or **Liquid Clustering** on hot query columns. For NYC TLC, the hot columns are usually `pickup_location_id`, `dropoff_location_id`.
- **Benchmark**: pick 3 of your business-question queries. Time them BEFORE optimization. Time them AFTER. Document the speedup. Even a small dataset will show measurable improvement.

### Analytical queries
Write 5 analytical SQL queries answering your Week 1 business questions. These go in `analytics/` folder. Output sample rows or a Plotly chart per query.

### README polish — the most important thing recruiters see
Structure:
1. **What this project is** (1 sentence)
2. **The business problem** (your 5 stakeholder questions, lightly edited)
3. **Architecture diagram** (Bronze/Silver/Gold + your star schema link)
4. **Stack** (Databricks, dbt, Delta Lake, Parquet)
5. **Key decisions** (link to `docs/schema_decisions.md`)
6. **Performance optimization** (your benchmark numbers)
7. **How to run** (3 commands max — recruiters will try to clone and run)
8. **What I'd do differently** (this section is gold — shows you're past "I built it" into "I learned from it")

### Talk-track rehearsal
**Record yourself** giving a 3-minute walkthrough of the project. Watch it back. The first time will be cringe. Do it 3 times until it's smooth.

The structure should match the STAR format from your existing interview-prep work:
- **Situation:** "I wanted to build the muscle of greenfield warehouse design — something my consulting work doesn't expose me to."
- **Task:** "Take NYC TLC raw trip data and answer 5 business questions, end-to-end."
- **Action:** "I designed a star schema with grain = one trip, picked SCD1 for most dims and SCD2 for DimLocation because zones can change. Built Bronze/Silver/Gold in dbt + Databricks. Tuned with Liquid Clustering on pickup_location_id."
- **Result:** "5 analytical queries answering the business questions, each <2 seconds on 6 months of data. Public repo at github.com/swarajnegi/nyc-taxi-lakehouse."

**Deliverable**
- Polished README in repo
- Performance benchmark numbers in repo
- LinkedIn post (optional but recommended) linking to the repo
- Self-recorded talk-track stored locally

**Topics to ask about**
- "How do I structure a really good README for a portfolio DE project?"
- "What does a 3-minute interview talk-track for a project look like?"
- "How do I pick partition columns for a star schema fact table?"
- "Liquid Clustering vs ZORDER vs partition columns — when each?"
- "How should I benchmark before/after Delta optimizations?"

---

## Resources

| Resource | Use for |
|---|---|
| *The Data Warehouse Toolkit* (Kimball, 3rd ed) | Chapters 1–4 only. Read in Week 2 BEFORE you start modeling. |
| dbt Learn (free online course) | Quick onboarding to dbt if you've never used it |
| NYC TLC Data Dictionary | https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page — the official schema |
| Reference repos | Search "nyc taxi dbt" on GitHub for 3–4 inspiration projects. Don't copy. Read for structure ideas. |
| Databricks Free Trial | https://www.databricks.com/try-databricks — 14-day, plenty for this project |

---

## Checkpoints

- **End of Week 1:** Business questions + data quirks docs published. You can articulate the dataset's quirks in 60 seconds.
- **End of Week 2:** Star schema diagram + grain statement reviewed by Claude (paste it in chat). Decisions doc has at least 3 rejected tradeoffs.
- **End of Week 3:** Pipeline runs end-to-end. `dbt run` produces all marts cleanly. Public repo created.
- **End of Week 4:** README polished. Benchmark numbers in place. Talk-track recorded. Repo pinned to your GitHub profile. **Add the project to your resume.**

---

## How to use this file

1. **Don't skip Week 1.** Most failed portfolio projects skip the business-problem framing and jump to building. The framing IS the muscle.
2. **In Week 2, ask me to red-team your schema** before you start building. Better to discover bugs in the design phase than in the build phase.
3. **Commit incrementally to GitHub.** Each weekly deliverable = a commit (or PR if you want to show PR discipline). Recruiters can see the history.
4. **The README is the resume bullet.** Spend disproportionate time on it in Week 4.
5. **Don't extend past 4 weeks.** Scope creep is the failure mode here. Ship a tight 4-week project, not a sprawling 6-month one. You can always add a v2 later.

---

## What's NOT in scope (deliberately)

- Real-time streaming (you have that on your resume from DLT)
- A second source (one source is enough to show modeling muscle)
- A frontend / dashboard (irrelevant to DE positioning)
- ML / forecasting (different roadmap)
- Multi-tenant / multi-region (overkill for portfolio)

Stay focused. The product is: "I designed a warehouse from a business problem." Not: "I built Databricks again from scratch."
