# Databricks Certified Data Engineer Professional — 7-Day Retake Plan

> **Exam (official guide, Nov 30 2025):** 59 scored MCQs · 120 min · $200 · ~70% to pass · Python + SQL · **no API docs allowed** · valid 2 years · online or test-center proctored.
> **Your retake target:** ~2026-06-25. Budget: ~4–5 hrs/day. Workspace: available (hands-on labs included).

---

## Why this plan looks the way it does

### Your prior attempt (30 Sep 2025, as a 3-month trainee — OLD 6-domain exam) — FAILED
| Old domain | Score |
|---|---|
| Testing & Deployment | 100% ✅ |
| Data Modeling | 83% ✅ |
| Data Processing | 61% ⚠️ |
| Tooling | 50% ⚠️ |
| Security | 50% ⚠️ |
| **Monitoring** | **33%** ❌ |

That was a trainee on the *old* exam. You now have ~1 YOE + Apollo Gen2 (422 SDP pipelines) + deep study behind you. The fail is a **targeting map**, not a verdict.

### Two traps when mapping old scores to the NEW (Nov-2025) exam
1. **Data Modeling — your 83% — is now worth only 6%.** It can't carry you. Don't over-study it.
2. **Testing & Deployment — your 100% — is *not* safe.** The new exam added **Databricks Asset Bundles (DABs)** + **Git CI/CD** to deploy and **System Tables** to monitoring — none existed when you sat it.

### New exam = 10 domains (weights)
| # | Domain | Weight | Focus this week |
|---|---|---|---|
| 1 | Developing Code (Python/SQL) | **22%** | DABs, testing frameworks, UDFs, control flow (new bits) |
| 6 | Cost & Performance Optimisation | **13%** | deletion vectors, liquid clustering, data skipping, Query Profile, Spark perf |
| 3 | Data Transformation & Quality | 10% | window functions, joins, quarantine |
| 5 | Monitoring & Alerting | 10% | **System Tables**, Query Profiler, REST/CLI, SQL Alerts, event logs |
| 7 | Security & Compliance | 10% | row filters/column masks, anonymization, PII, purging |
| 9 | Debugging & Deploying | 10% | Spark UI/logs, job repairs, **DABs**, Git CI/CD |
| 2 | Data Ingestion & Acquisition | 7% | Auto Loader, formats, append-only Delta |
| 8 | Data Governance | 7% | UC permission inheritance, metadata/tags |
| 10 | Data Modelling | 6% | Delta models, liquid clustering vs partition/ZORDER, dimensional |
| 4 | Data Sharing & Federation | 5% | **Delta Sharing (D2D/D2O)**, Lakehouse Federation |

**~50% of the exam (Sections 1-new, 4, 5, 6, 7, 9) is in topics your existing notes cover only partially or not at all.** That's where this week lives.

---

## The 7-day schedule (~4–5 hr/day)

Each gap day = **doc-verified deep-dive → hands-on lab in your workspace → 12 graded MCQs**.

| Day | Focus | Deep-dive file | Lab |
|---|---|---|---|
| **1** | **Monitoring & Alerting** (your 33% — #1) | `01_Monitoring.md` | Query 4 system tables; build a SQL Alert; open a Query Profile |
| **2** | **Security & Compliance + Governance** (your 50%) | `02_Security_Governance.md` | Row filter + column mask + dynamic view; apply tags/comments |
| **3** | **Developing Code** (22% — biggest) | `03_Code_DABs_Testing.md` | Build + deploy a minimal DAB; write a unit test (`assertDataFrameEqual`) |
| **4** | **Cost & Performance** + Spark depth (your 61%) | `04_Cost_Performance.md` | Query-profile a slow query; OPTIMIZE + liquid clustering |
| **5** | **Debugging/Deploying + Sharing/Federation** + strength review | `05_Debug_Deploy_Sharing.md` | Delta Share (D2D); trigger a job repair |
| **6** | **MOCK #1** (59 Q, 120 min, timed, domain-weighted) | `Mock_Exam_1.md` | Grade by domain → re-study anything < 70% |
| **7** | **MOCK #2** (fresh) + final review + cheat-sheet | `Mock_Exam_2.md`, `Cheat_Sheet.md` | Logistics: proctor setup, ~2 min/Q pacing |

---

## How to use this pack

- **Deep-dives (`01`–`05`)** — read first each day; they only cover your *gaps* (System Tables, DABs, Delta Sharing, anonymization/PII, Query Profiler, testing frameworks). For your strengths (SDP, AUTO CDC, SCD2, expectations, Auto Loader) lean on your existing notes: `SDP_Syntax.md`, `Novartis_SDP_50Q_Bank.md`, `Roadmaps/Roadmap_01_Spark_Internals.md`.
- **`MCQ_Bank.md`** — domain-tagged practice questions, graded with explanations. Do the day's domain set after the deep-dive + lab.
- **`Mock_Exam_1.md` / `Mock_Exam_2.md`** — full 59-Q timed mocks in real exam proportions. Don't peek; grade by domain afterward.
- **`Cheat_Sheet.md`** — one-page last-day recall (system tables list, anonymization methods, DABs commands, liquid-clustering rule, AQE knobs, APPLY CHANGES signature, Delta Sharing D2D/D2O).

**Success bar:** both mocks ≥ 75% overall AND every domain ≥ 70%, with Monitoring, Security, and Code provably lifted above 70%.

*All MCQs and deep-dives are generated grounded in the official Nov-30-2025 objectives and fact-checked against current Databricks documentation.*
