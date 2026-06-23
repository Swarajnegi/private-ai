# Day 2 — Security, Compliance & Governance (S7 10% + S8 7% = 17% of the exam)

> **Doc-grounded deep-dive.** Every fact below is cited inline to *current* Azure Databricks docs (learn.microsoft.com, verified June 2026). On your prior attempt Security scored **50%** — and the Nov-2025 exam *added* anonymization/pseudonymization methods, the compliant PII-masking pipeline, and retention purging that didn't exist when you sat it. S7 (Security & Compliance) and S8 (Governance) together are **17% — roughly 10 of 59 scored questions.** That is more than Data Modelling (6%) and Sharing (5%) *combined*. This is a high-ROI day.
>
> **What this doc deliberately skips:** SDP, AUTO CDC / APPLY CHANGES, SCD2, expectations, Auto Loader basics — you own those from Apollo Gen2 (422 pipelines). Where they intersect security (e.g. `skipChangeCommits` for GDPR-on-streaming-tables, refresh-as-owner semantics for masks in pipelines) I cover *only the security wrinkle*, not the pipeline mechanics.
>
> **Term map (defined once, used throughout):** UC = Unity Catalog. ACL = Access Control List. UDF = User-Defined Function. RLS/CLS = Row-Level / Column-Level Security. PII = Personally Identifiable Information. RTBF = Right To Be Forgotten (GDPR Art. 17). DV = Deletion Vector. ABAC = Attribute-Based Access Control. Securable = an object you can `GRANT` privileges on.

---

## The mental model: three *separate* access-control systems

This is the single most-tested governance distinction, and it trips up experienced engineers because all three feel like "permissions." Databricks runs **three different access-control systems for three different object classes** ([Authentication and access control](https://learn.microsoft.com/azure/databricks/security/auth/)):

| Object class | Examples | Access-control system | Granted by |
|---|---|---|---|
| **Workspace-level** | notebooks, jobs, pipelines, folders, queries, dashboards, SQL warehouses, pools | **ACLs** (`CAN VIEW` / `CAN RUN` / `CAN EDIT` / `CAN MANAGE`) | workspace admins + object creators |
| **Account-level** | service principals, groups | **Account RBAC** (account roles) | account admins, group/SP managers |
| **Data** | catalogs, schemas, tables, views, volumes, functions, models | **Unity Catalog** (`SELECT`, `MODIFY`, `USE CATALOG`, …) | object owners + `MANAGE` holders |

The exam trap: a question gives you "a user can run the *notebook* but gets PERMISSION_DENIED on the *table* it reads." That is **two systems** — `CAN RUN` on the notebook (ACL) is satisfied, but `SELECT` + `USE CATALOG` + `USE SCHEMA` (UC) is not. They never substitute for each other.

**Recap:** ACLs guard workspace objects, UC guards data, account RBAC guards account objects — three systems, never interchangeable.

---

## S7.1 — ACLs on workspace objects + least privilege

### What ACLs actually are

In Databricks, ACLs configure permission to access **workspace-level objects** — notebooks, jobs, pipelines, queries, dashboards, SQL warehouses, pools, folders ([Access control lists](https://learn.microsoft.com/azure/databricks/security/auth/access-control/)). Two invariants worth memorizing:

1. **Workspace admins have `CAN MANAGE` on every object** in their workspace.
2. **Users automatically get `CAN MANAGE` on objects they create.**

### The permission levels are *not* uniform across object types

This is the detail most people get wrong. The ladder differs per object. From the doc's ACL tables ([Access control lists](https://learn.microsoft.com/azure/databricks/security/auth/access-control/)):

**Notebook ACLs** — `NO PERMISSIONS → CAN VIEW → CAN RUN → CAN EDIT → CAN MANAGE`. Note the order: `CAN RUN` (attach + run commands) sits *below* `CAN EDIT` (edit cells). `CAN VIEW` lets you read cells and comment but **not** attach to a cluster.

**Job ACLs** — a *different* ladder: `NO PERMISSIONS → CAN VIEW → CAN MANAGE RUN → IS OWNER → CAN MANAGE`. There is an `IS OWNER` level here that notebooks don't have.

**Folder ACLs** — `NO PERMISSIONS → CAN VIEW → CAN EDIT → CAN RUN → CAN MANAGE` (note `CAN RUN` is *above* `CAN EDIT` here, the reverse of notebooks).

> **Silent/invisible behavior — the UI vs API naming mismatch.** The workspace UI calls view-only access **`CAN VIEW`**, but the Permissions REST API calls the *exact same level* **`CAN READ`** ([Access control lists](https://learn.microsoft.com/azure/databricks/security/auth/access-control/)). If you write a DAB or Terraform that sets `CAN VIEW` you will get an error — the API only knows `CAN_READ`. The exam can phrase a question in API terms; "CAN READ on a notebook" = "CAN VIEW in the UI."

### Job ownership has hard, exam-favorite rules

From the Job ACL notes ([Access control lists — Job ACLs](https://learn.microsoft.com/azure/databricks/security/auth/access-control/#job-acls)):

- The job **creator is `IS OWNER` by default**.
- A job **cannot have more than one owner**.
- A **group cannot be the owner** (`IS OWNER` cannot be assigned to a group).
- **Jobs triggered via "Run Now" run with the *owner's* permissions, not the triggerer's.** This is a frequent trap: a low-privilege analyst clicks Run Now on a job owned by a high-privilege service principal — the run executes with the SP's data access, not the analyst's.

### Folder inheritance — the least-privilege power tool

Objects in a folder **inherit all permission settings of that folder** ([Access control lists — Manage ACLs with folders](https://learn.microsoft.com/azure/databricks/security/auth/access-control/)). Grant `CAN RUN` on a folder → every alert/notebook/query inside inherits `CAN RUN`. This is how you implement least privilege at scale instead of per-object grants.

> **Silent metadata leak.** If you grant a user access to *one object inside* a folder but nothing on the folder, they **can still see the parent folder's name** (though not its other contents). Doc's worked example: grant `CAN VIEW` on `test1.py` inside folder `Workflows`, no folder permission → the user sees that the parent is named `Workflows`, but cannot list or open anything else in it ([Access control lists](https://learn.microsoft.com/azure/databricks/security/auth/access-control/)). Folder *names* are not secret once you can reach a child.

### Least-privilege enforcement at the platform layer

Beyond per-object ACLs, the doc's least-privilege guidance ([Database objects in Azure Databricks](https://learn.microsoft.com/azure/databricks/database-objects/)) is: **restrict cluster-creation privileges and use compute policies.** Access to compute is itself governed by ACLs, and a compute policy caps what a user can spin up — so you don't hand out unbounded cluster creation as a side door around data governance.

```python
# Worked example: set notebook ACL via the Permissions REST API (DAB/CI-CD style).
# Note the API verb CAN_READ — NOT "CAN VIEW" (UI label). This is the silent mismatch.
import requests

payload = {
    "access_control_list": [
        {"group_name": "analysts",     "permission_level": "CAN_READ"},   # UI shows "CAN VIEW"
        {"group_name": "data_eng",     "permission_level": "CAN_MANAGE"},
        {"user_name":  "svc-prod@co",  "permission_level": "CAN_RUN"},
    ]
}
requests.put(
    f"{host}/api/2.0/permissions/notebooks/{notebook_id}",
    headers={"Authorization": f"Bearer {token}"},
    json=payload,
)
```

**Recap:** ACL permission ladders differ per object type, `CAN VIEW`(UI)==`CAN READ`(API), jobs Run-Now executes as the owner, and folder inheritance is your least-privilege lever — but folder names leak to anyone with a grant on a child.

---

## S8 — Unity Catalog permission inheritance model (metastore → catalog → schema → table)

(Covering S8 before the rest of S7 because row filters, masks, tags, and purging *all* assume you understand the UC hierarchy.)

### The hierarchy and what "container" means

UC data lives in a **three-level namespace `catalog.schema.table`** under a top-level **metastore** ([UC permissions model concepts](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts)). Only **catalogs and schemas are *container objects*** — they have children and they propagate privileges downward. Tables, views, volumes, functions are **non-container** (no children, nothing inherits from them).

### Inheritance direction and the metastore exception

> **The single highest-yield fact in S8:** Privileges inherit **downward** from a container to all *current and future* children. **BUT metastore-level privileges do NOT inherit to child objects.** ([UC permissions concepts — Privilege inheritance](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts))

So:
- `GRANT SELECT ON CATALOG sales TO finance_team` → readable on every table/view in every schema in `sales`, present and future. ✅ inherits.
- `GRANT SELECT ON SCHEMA sales.emea TO finance_team` → every table/view in `sales.emea`. ✅ inherits.
- Metastore grants (`CREATE CATALOG`, `CREATE EXTERNAL LOCATION`, etc.) are metastore-scoped operations and **do not flow down** to data inside the metastore. ❌ does not inherit.

### Usage privileges are a *prerequisite*, not inherited access

`USE CATALOG` and `USE SCHEMA` are **usage privileges** — gates you must pass to *interact with* anything inside, regardless of child grants ([UC permissions concepts — Usage privileges](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts)). To read one table you need **all three**:

```sql
USE CATALOG on parent catalog
+ USE SCHEMA on parent schema
+ SELECT     on the table
```

> **The classic trap, verbatim from the doc:** "Having only the `SELECT` privilege on a table is not sufficient to read it if you lack `USE CATALOG` or `USE SCHEMA` on its parent objects." A table owner can `GRANT SELECT` to whomever they like, but that grantee **still cannot read the table** without `USE CATALOG` on the parent — and only the *catalog* owner / `MANAGE` holder can grant `USE CATALOG`. This is the deliberate access-control boundary that stops table owners from exfiltrating data outside approved catalog boundaries.

### Ownership vs the `MANAGE` privilege (a Nov-2025 favorite)

These look identical but differ in ways the exam probes ([UC permissions concepts — Ownership / MANAGE](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts)):

| | **Owner** | **`MANAGE` privilege** |
|---|---|---|
| All capabilities on the object | Yes — *implied*, but UC does **not** explicitly grant `ALL PRIVILEGES` (so `SHOW GRANTS` won't list it) | No — must grant privileges separately (but can self-grant) |
| Grant/revoke, transfer ownership, drop | Yes | Yes |
| Manage child objects | Yes — implied on all children | Yes — but `MANAGE` *is* explicitly granted on children |
| Requires `USE CATALOG`/`USE SCHEMA` | No | **Yes** |
| Number of principals | Exactly one (user, SP, or group) | Many |

> **Two silent behaviors here.** (1) **Ownership does NOT inherit downward** — owning catalog `sales` does *not* make you owner of schema `sales.emea`; you only get the *ability to manage* children, not ownership of them. (2) `ALL PRIVILEGES` **does not include `MANAGE`** (anti-privilege-escalation), and **owners' privileges never appear in `SHOW GRANTS`** because they're implied, not granted. A question that says "the owner ran `SHOW GRANTS` and saw nothing for themselves" is describing *correct* behavior.

### Two privileges built for discoverability without data access

- **`BROWSE`** — discover objects, view name/description/tags, request access — **without** `USE CATALOG`/`USE SCHEMA` and without reading data. **Catalog-level only.** Databricks recommends granting `BROWSE` to `All account users` ([UC privileges reference — Catalog](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/securable-objects)).
- **`APPLY TAG`** — add/edit tags; on a table/view it also enables *column-level* tagging ([UC privileges reference](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/privileges-reference)).

```sql
-- Inheritance in action: one grant, whole catalog readable now + future
GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG sales TO finance_team;

-- Discoverability without data access, account-wide
GRANT BROWSE ON CATALOG sales TO `All account users`;

-- Workspace-catalog binding SUPERSEDES grants:
-- even an explicit SELECT can't reach a catalog not bound to the user's workspace
```

> **Workspace binding overrides everything.** A catalog is reachable from all workspaces on the metastore *by default*, but you can bind it to specific workspaces (optionally read-only). "Workspace binding supersedes individual privilege grants. Even a user with an explicit `SELECT` grant cannot access an object in a catalog that is not bound to their workspace." ([UC securable objects — Catalog](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/securable-objects))

**Recap:** privileges inherit catalog→schema→table (metastore grants do *not* flow down); `USE CATALOG`+`USE SCHEMA`+`SELECT` are all three required to read; ownership ≠ `MANAGE` (owner is implied/single/no-usage-needed, MANAGE is explicit/many/needs-usage); `BROWSE` enables discovery without data; workspace binding beats any grant.

---

## S7.2 — Row filters + column masks (table-level)

### Definitions and the one-line mechanics

- **Row filter** = a SQL UDF applied to a table; it evaluates **per row at query time** and rows where it returns `FALSE` are **excluded** ([Row filters and column masks](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/)). **One row filter per table.**
- **Column mask** = a SQL UDF bound to a column; it takes the column value and returns the original or a masked version. Return type must match/cast to the column type. **One mask per column.**

### Row filter — worked example with execution trace

```sql
-- A non-admin sees only US rows; admins see everything.
CREATE FUNCTION us_filter(region STRING)
RETURN IF(IS_ACCOUNT_GROUP_MEMBER('admin'), TRUE, region = 'US');

CREATE TABLE sales (region STRING, id INT);
ALTER TABLE sales SET ROW FILTER us_filter ON (region);

-- remove later:  ALTER TABLE sales DROP ROW FILTER;
```
([Manually apply row filters and column masks — Row filter examples](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply))

Trace, table holds `('US',1),('UK',2),('US',3)`:
- Query by `alice@` (member of `admin`) → `us_filter` returns `TRUE` for every row → sees all 3 rows.
- Query by `bob@` (not admin) → filter evaluates `region='US'` → rows 1 and 3 returned, row 2 silently dropped.

### Column mask — worked example with execution trace

```sql
CREATE FUNCTION ssn_mask(ssn STRING)
  RETURN CASE WHEN IS_ACCOUNT_GROUP_MEMBER('HumanResourceDept')
              THEN ssn ELSE '***-**-****' END;

CREATE TABLE users (name STRING, ssn STRING MASK ssn_mask);
-- or on an existing table:
ALTER TABLE users ALTER COLUMN ssn SET MASK ssn_mask;
```
Query by a non-HR user → `SELECT * FROM users;` returns `James  ***-**-****` ([Manually apply — Column mask examples](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).

### `USING COLUMNS` — conditional masking on *other* columns

A mask's first parameter is always the masked column; extra parameters come via `USING COLUMNS` (other columns *or* constant literals):

```sql
-- redact address unless the viewer's group matches the row's country
ALTER TABLE customers
  ALTER COLUMN address
  SET MASK mask_address_by_country USING COLUMNS (country, '_address_viewers');
```
Result for a `US_address_viewers` member: US rows show the address, UK/FR rows show `REDACTED` ([Manually apply — Column mask with additional columns](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).

### Python logic? You must wrap it in a SQL UDF

You **cannot** apply a Python UDF directly as a mask — you get `[ROUTINE_NOT_FOUND]`. Create the Python UDF, then a SQL UDF that calls it, and apply the *SQL wrapper* ([Manually apply — Column mask with Python UDF](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)):

```sql
CREATE OR REPLACE FUNCTION email_mask_python(email STRING) RETURNS STRING
LANGUAGE PYTHON AS $$
import re
return re.sub(r'^[^@]+', lambda m: '*' * len(m.group()), email)
$$;

CREATE OR REPLACE FUNCTION email_mask_sql(email STRING)
  RETURN email_mask_python(email);          -- this SQL wrapper is what you apply

CREATE TABLE contacts (name STRING, email STRING MASK email_mask_sql);
```

### Privileges, compute, and the dangerous silent gotchas

**To apply** a mask/filter: `EXECUTE` on the function + `USE SCHEMA` + `USE CATALOG`; plus `CREATE TABLE` (new table) or **owner / `MANAGE`** (existing table) ([Column mask clause](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-column-mask)).

**To read** a table with filters/masks, compute must be: a SQL warehouse, **standard access mode on DBR 12.2 LTS+**, or **dedicated access mode on DBR 15.4 LTS+**. You **cannot** read them on dedicated compute ≤ DBR 15.3 ([Manually apply — Before you begin](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).

> **Silent behaviors that change query *results*, not just errors:**
> 1. **Type-mismatch → silent NULL.** UDF parameter types must match the column types. If a `STRING` column hits an `INT` parameter, the value is implicitly cast; **with ANSI mode disabled, uncastable values silently become `NULL`**, which can make a filter/mask produce *wrong results with no error* ([Manually apply — type mismatch](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).
> 2. **Mask is applied at fetch, before everything else.** "The mask is applied as soon as each row is fetched… Any expressions, predicates, or ordering are applied *after* the masking." So a **JOIN on a masked column compares the *masked* values**, not the originals ([Column mask clause](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-column-mask)). This silently breaks joins/aggregations people expect to work on real values.
> 3. **Drop order matters or the table bricks.** You must `ALTER TABLE … DROP MASK` / `DROP ROW FILTER` *before* `DROP FUNCTION`. Drop the function first and the table becomes *inaccessible* until you drop the orphaned reference ([Manually apply](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).
> 4. **Serverless billing leak.** On dedicated compute (DBR 15.4+), the filtering/masking runs on **serverless** behind the scenes — so you can be **charged for serverless** even when reading from a dedicated cluster ([Manually apply — Before you begin](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).
> 5. **Filters/masks survive `REPLACE TABLE`** — they are retained when a table is replaced ([Manually apply](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply)).

### In pipelines (the security wrinkle on top of SDP you already know)

You can attach filters/masks to streaming tables / materialized views via `CREATE OR REFRESH`. The security-relevant detail: **on *refresh*, `CURRENT_USER`/`IS_MEMBER` evaluate as the *pipeline owner* (definer's rights); on *query*, they evaluate as the *invoker*.** Also, a materialized view over a source that has filters/masks **always full-refreshes** (never incremental) so the latest policy is applied ([Use Unity Catalog with pipelines — row filters and column masks](https://learn.microsoft.com/azure/databricks/ldp/unity-catalog)).

**Recap:** row filters drop `FALSE` rows (one/table), column masks rewrite values (one/column), Python needs a SQL wrapper, `USING COLUMNS` enables cross-column logic — and watch the five silent behaviors: NULL-on-bad-cast, mask-before-join, drop-order bricking, serverless billing, survives REPLACE.

---

## S7.2b — Dynamic views (the `is_account_group_member` route)

A **dynamic view** is an ordinary SQL view whose definition embeds identity functions to filter rows / mask columns / reshape data. Use it when you want to expose a **curated, joined, or redacted slice spanning multiple base tables** to users who **don't** have access to the underlying tables ([Create a dynamic view](https://learn.microsoft.com/azure/databricks/views/dynamic)).

The three identity functions (define-before-use):
- **`is_account_group_member('grp')`** → `TRUE` if the connected user is a direct/indirect member of an **account-level** group. **This is the recommended one for UC data.** ([is_account_group_member](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/is_account_group_member))
- **`is_member('grp')`** → checks **workspace-level** group membership. **Avoid against UC data** — it doesn't evaluate account-level membership; it exists for Hive-metastore compatibility ([is_member](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/is_member)).
- **`session_user()` / `current_user()`** → the connected user's email.

> **Exam trap, exact:** a dynamic view uses `is_member('auditors')` and a user who is in the *account* group `auditors` still sees redacted data. Why? `is_member` only checks *workspace* groups. The fix is `is_account_group_member`. The doc explicitly recommends `is_account_group_member` for UC and warns against `is_member`.

```sql
-- Column-level: only auditors see full email; everyone else gets the domain.
-- Alias 'email' AS 'email' so the CASE logic doesn't leak into the column name.
CREATE VIEW sales_redacted AS
SELECT
  user_id,
  CASE WHEN is_account_group_member('auditors') THEN email
       ELSE regexp_extract(email, '^.*@(.*)$', 1) END AS email,
  country, product, total
FROM sales_raw;

-- Row-level: non-managers can't see transactions over $1M
CREATE VIEW big_deals AS
SELECT user_id, country, product, total
FROM sales_raw
WHERE CASE WHEN is_account_group_member('managers') THEN TRUE
           ELSE total <= 1000000 END;
```
([Create a dynamic view](https://learn.microsoft.com/azure/databricks/views/dynamic))

### Dynamic view vs row-filter/mask vs ABAC — when to use which

| Approach | Applies to | Managed using | Best for |
|---|---|---|---|
| Table-level row filter / column mask | individual tables & columns | `ALTER TABLE` by owner/`MANAGE` | table-specific logic, no new objects |
| **ABAC policies** | tables/columns matched by **governed tags** | `CREATE POLICY` on catalog/schema | consistent rules across **many** tables, auto-applies as tables get tagged |
| **Dynamic views** | a view over one+ base tables | SQL in the view definition | curated/joined/reshaped slices for users without base-table access |

([Row filters and column masks — when to use ABAC or dynamic views](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/), [ABAC vs table-level](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/abac-vs-rls-cm))

> **Two documented drawbacks of dynamic views vs filters/masks:** (1) **Limited auditing** — views lack semantic metadata (tags/policy definitions) in system tables, so they're hard to audit at scale. (2) **Vulnerable to probing** — they have no `SecureView` barrier, so a user can craft a predicate with side effects to *infer* filtered rows. Upside: dynamic views **fully support predicate pushdown**, so they can outperform row filters/masks ([ABAC vs table-level — dynamic views](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/abac-vs-rls-cm)).

**Recap:** dynamic views = SQL-defined RLS/CLS across multiple tables for users without base access; use `is_account_group_member` (account), never `is_member` (workspace-only) for UC; they pushdown well but audit poorly and are probe-able.

---

## S7.3 — Anonymization / pseudonymization: the four methods

The exam expects you to know **four de-identification techniques and when each applies.** Databricks docs frame the strategic choice first ([Prepare your data for GDPR compliance](https://learn.microsoft.com/azure/databricks/ldp/gdpr)):

> "You have to choose between deleting data and obfuscating it. Obfuscation can be implemented using pseudonymization, data masking, etc. **However, the safest option is complete erasure** because, in practice, eliminating the risk of re-identification often requires a complete deletion of PII data."

So: **obfuscation reduces but does not eliminate re-identification risk; deletion does.** Memorize that ordering.

### The four methods, mechanism, and when to use

| Method | Mechanism | Reversible? | When to use | Databricks primitive |
|---|---|---|---|---|
| **Hashing** (deterministic pseudonymization) | replace value with a one-way digest; same input → same hash, so you can still **join/group** on it | No (one-way) | you need referential integrity / joins across tables but not the raw value (e.g. customer key) | `SHA2(val, 256)` ([sha2](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/sha2)) |
| **Tokenization** | replace value with a random surrogate token; the **value↔token map lives in a separate secured store** | Yes (via the vault) | you must restore the original later for authorized parties (e.g. payments) | mapping table in a locked-down schema |
| **Suppression** | drop / null / fully redact the field | No | the value has no analytic use and high sensitivity (e.g. full SSN) | `mask()`, `'***'`, set to NULL |
| **Generalization** | reduce precision so individuals blend into groups | No | you need *coarse* analytics, not identity (DOB → birth year, ZIP → region) | `regexp_extract`, `date_trunc`, binning |

### Hashing — the consistent-hashing pattern with key rotation

The doc's recommended pseudonymization UDF. `DETERMINISTIC` tells the optimizer the function is stable (enables caching/pushdown); the `version` parameter supports **key rotation** without breaking historical hashes:

```sql
CREATE FUNCTION pseudonymize(val STRING, version INT) RETURNS STRING
DETERMINISTIC
  RETURN SHA2(CONCAT(val, CAST(version AS STRING)), 256);
```
Bump `version` to generate new hashes going forward; old data keeps its old-version hashes ([Common patterns — consistent hashing](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/common-patterns)).

> **Why salt/version matters (the security subtlety):** raw `SHA2(ssn)` is vulnerable to a rainbow/dictionary attack — the input space of SSNs is small and an attacker can pre-hash all of them. Concatenating a secret/version before hashing defeats the precomputed table. The exam may ask "why is plain SHA2 of a phone number weak pseudonymization?" — answer: small input domain → brute-forceable.

### Suppression / generalization — the built-in `mask()` function

`mask(str [, upperChar [, lowerChar [, digitChar [, otherChar]]]])` substitutes character classes — defaults `X` for upper, `x` for lower, `n` for digits, and `NULL` (leave as-is) for "other" ([mask function](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/mask)):

```sql
SELECT mask('SSN-123-4567');           -- XXX-nnn-nnnn  (digits→n, letters→X, '-' untouched)
SELECT mask('abc123', 'Q', NULL);      -- abcnnn  (lower kept via NULL, digits→n)

-- Generalization: collapse a full email to its domain (coarse analytics, no identity)
SELECT regexp_extract(email, '^.*@(.*)$', 1) AS domain FROM users;
```

There is also **`ai_mask(content, ...)`** — an AI built-in that masks named entities in free text for de-identification ([ai_mask](https://learn.microsoft.com/azure/databricks/sql/language-manual/functions/ai_mask)) — useful when PII is embedded in unstructured strings rather than typed columns.

**Recap:** hashing = irreversible-but-joinable (salt/version it, or it's brute-forceable), tokenization = reversible via a separate vault, suppression = drop/redact, generalization = reduce precision; and per the docs, *deletion beats all obfuscation* when re-identification risk must be eliminated.

---

## S7.4 — A compliant batch + streaming PII-masking pipeline

This synthesizes everything above into the pattern the exam tests as "compliant pipeline." Two halves: **masking at rest/in-flight** and **purging on request (RTBF)**.

### Architecture (medallion-aligned, doc-grounded)

```
Bronze (raw, restricted)          Silver (pseudonymized)            Gold (analytics)
  raw PII landed                    SHA2(email) as email_pk           aggregates only
  ACL: data_eng only      ──▶       suppression: ssn  → '***'  ──▶    no raw PII present
  (or volume, no SELECT)            generalization: dob → year        masks/filters for
                                    + column masks for live access    fine-grained access
```

### Batch + streaming masking in one pipeline (SDP — you know the mechanics; here's the security layer)

```sql
-- BRONZE: streaming ingest, raw PII isolated, no broad SELECT granted
CREATE OR REFRESH STREAMING TABLE bronze_events
AS SELECT * FROM STREAM read_files('abfss://.../raw', format => 'json');

-- SILVER: pseudonymize + generalize during the streaming transform.
-- The MASK clause anonymizes sensitive data right in the table definition.
CREATE OR REFRESH STREAMING TABLE silver_customers (
  customer_pk STRING,
  email       STRING MASK email_mask_sql,          -- column mask: live fine-grained access
  ssn         STRING MASK ssn_mask,
  birth_year  INT                                   -- generalized from full DOB upstream
)
AS SELECT
     SHA2(CONCAT(customer_id, '_v1'), 256) AS customer_pk,   -- deterministic pseudonym
     email,
     ssn,
     YEAR(date_of_birth)                   AS birth_year      -- generalization
   FROM STREAM(bronze_events);

-- GOLD: materialized view, aggregates only — no raw PII flows here
CREATE OR REFRESH MATERIALIZED VIEW gold_cohorts
AS SELECT birth_year, country, COUNT(*) AS n
   FROM silver_customers GROUP BY birth_year, country;
```
The `MASK` clause is valid in `CREATE STREAMING TABLE` and adds "a column mask function to anonymize sensitive data" ([CREATE STREAMING TABLE — parameters](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-create-streaming-table)).

> **The pipeline-specific security wrinkle (re-stated because it's heavily tested):** during a pipeline **refresh**, mask/filter functions run as the **pipeline owner** (definer's rights); during a **query** they run as the **invoker**. So the pipeline owner needs `SELECT` on the base tables, and a materialized view over a masked source **always full-refreshes** ([Use Unity Catalog with pipelines](https://learn.microsoft.com/azure/databricks/ldp/unity-catalog)).

### RTBF (right-to-be-forgotten) propagation — bronze first, then down

Doc's prescribed order ([GDPR compliance](https://learn.microsoft.com/azure/databricks/ldp/gdpr)): a scheduled job reads a **deletion-requests table**, **deletes from Bronze first**, then propagates:

- **Materialized views** *automatically* handle source deletions (incremental if cheaper, else full recompute) — but you must **refresh + run maintenance** to fully process them. No special handling.
- **Streaming tables** are **append-only**; an update/delete on a streaming *source* **breaks the stream.** The compliant 3-step fix:
  1. `DELETE` from the source Delta table (DML),
  2. `DELETE` from the streaming table (DML),
  3. set the streaming read to **`skipChangeCommits`** so it ignores non-append changes ([GDPR — propagate changes](https://learn.microsoft.com/azure/databricks/ldp/gdpr)).

> **Exam trap:** "after deleting a row from a streaming-table source, the pipeline fails." Cause: streaming tables process append-only; deletes/updates aren't supported on the source. Fix: `skipChangeCommits`. This is *the* PII-on-streaming gotcha.

**Recap:** compliant pipeline = isolate raw PII in bronze (tight ACLs), pseudonymize/generalize/suppress into silver via `MASK` clauses + `SHA2`, aggregate-only gold; for RTBF delete bronze-first, MVs self-heal, streaming tables need DELETE+DELETE+`skipChangeCommits` — then *purge* (next section).

---

## S7.5 — Data purging for retention compliance (VACUUM, DELETE, retention)

`DELETE` is a **logical** delete. The bytes stay in cloud storage and remain time-travel-accessible until a retention-bounded physical cleanup runs. Compliance (GDPR/CCPA) requires *physical* removal. Three commands, three jobs.

### The command trio (memorize what each one physically does)

| Command | What it does physically | Compliance role |
|---|---|---|
| **`DELETE`** | logical removal from the *latest* table version; bytes + history remain | step 1 — locate & remove PII (fast point-delete via Delta ACID) |
| **`REORG TABLE … APPLY (PURGE)`** | rewrites files to physically drop **deletion-vector** soft-deletes (idempotent; only rewrites affected files) | required *only* when **deletion vectors** are enabled |
| **`VACUUM`** | deletes data files no longer referenced by the log AND older than the retention threshold; removes them from cloud storage | step 2/final — actually frees the bytes; **destroys time travel** past the window |

([VACUUM](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-vacuum), [REORG TABLE](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-reorg-table), [Deletion vectors](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors))

### VACUUM retention numbers — get these exactly right

- **Default retention threshold = 7 days**, controlled by table property **`delta.deletedFileRetentionDuration`** ([VACUUM](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-vacuum)).
- Databricks **strongly recommends ≥ 7 days.** Below that, a long-running concurrent job may write files not-yet-committed, and a too-short VACUUM could delete them before commit → corruption.
- There's a **safety check** that *blocks* VACUUM below the configured floor. You can disable it with `spark.databricks.delta.retentionDurationCheck.enabled = false` — but only do so if you're certain no operation longer than your interval is running.
- VACUUM **skips directories starting with `_`** (including `_delta_log`).
- Running VACUUM **costs you time travel** to any version older than the retention window.

> **The 30-vs-7 trap.** Delta retains *table history* for **30 days by default** (for time travel/rollback), but **VACUUM**'s file-retention default is **7 days** ([GDPR compliance](https://learn.microsoft.com/azure/databricks/ldp/gdpr)). Two different defaults, two different purposes. A question may quote one to test whether you conflate them.

```sql
-- Retention purge sequence for a table WITHOUT deletion vectors:
DELETE FROM sales.customers WHERE customer_id = 'c-123';   -- logical
VACUUM sales.customers;                                    -- physical (>= 7-day-old files)

-- Extend retention to 30 days (more time travel, slower compliance):
ALTER TABLE sales.customers
  SET TBLPROPERTIES ('delta.deletedFileRetentionDuration' = '30 days');
```

### When deletion vectors are ON, you MUST add a PURGE step

Deletion vectors mark rows deleted **without rewriting Parquet** — the bytes survive until a rewrite. For compliance you must force the rewrite ([GDPR — deletion vectors](https://learn.microsoft.com/azure/databricks/ldp/gdpr), [REORG TABLE](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-reorg-table)):

```sql
DELETE FROM sales.orders WHERE customer_id = 'c-123';      -- soft delete via DV
REORG TABLE sales.orders APPLY (PURGE);                    -- rewrite files, drop soft-deletes
-- wait for delta.deletedFileRetentionDuration to elapse, then:
VACUUM sales.orders;                                       -- remove the now-unreferenced old files

-- target a partition only:
REORG TABLE sales.orders WHERE order_date = DATE '2026-05-01' APPLY (PURGE);
```

> **Nuance the exam loves:** `OPTIMIZE` *automatically* purges files where **>5%** of records are referenced by deletion vectors, so routine maintenance usually does NOT need a separate `REORG … PURGE`. You run explicit `REORG … APPLY (PURGE)` only for **compliance** or to force-purge *below* the 5% threshold ([Deletion vectors — compare REORG/OPTIMIZE/VACUUM](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors)). And `REORG` is **idempotent** — a second run does nothing.

### Streaming tables / materialized views: the extra REORG ceremony

These are still Delta under the hood. To physically purge from a streaming table or MV with deletion vectors ([Use standalone streaming tables — permanently delete](https://learn.microsoft.com/azure/databricks/ldp/dbsql/streaming)):
1. `DELETE`/update the records,
2. `REORG TABLE <st_or_mv> APPLY (PURGE);`,
3. wait out `delta.deletedFileRetentionDuration` (default 7 days),
4. `REFRESH` — within 24h, pipeline maintenance auto-runs the required `VACUUM`.

### Let the platform do it: predictive optimization + auto time-to-live

- **Predictive optimization** for UC managed tables auto-runs `OPTIMIZE`/`VACUUM` (and `PURGE` when DVs are on) based on usage — you "don't need to run `VACUUM` manually in most cases" ([VACUUM](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-vacuum)).
- **Auto time-to-live (auto-TTL)** automates row-level retention: set an expiration period, and predictive optimization asynchronously runs `DELETE` → (`PURGE` if DVs) → `VACUUM`. Note the **timing is not exact** — up to ~3 days buffer per command (≤6 days total) plus your configured retention duration ([Auto time-to-live](https://learn.microsoft.com/azure/databricks/tables/operations/auto-ttl)).

> **Don't forget upstream + don't conflate with managed tables.** GDPR/CCPA cover *all* copies — you must also delete from **upstream sources** (Kafka, files, databases), not just Delta ([GDPR compliance](https://learn.microsoft.com/azure/databricks/ldp/gdpr)). And **UC *managed* tables reduce this ops overhead** (S6 overlap) because predictive optimization handles maintenance for you; *external* tables you maintain yourself.

**Recap:** `DELETE` is logical; `VACUUM` (default 7-day floor, configurable via `delta.deletedFileRetentionDuration`, blocked below 7 by a safety check) physically frees bytes and kills time travel; deletion-vector tables additionally need `REORG … APPLY (PURGE)` for compliance (OPTIMIZE auto-purges >5%); table *history* default is 30 days but VACUUM file-retention default is 7 — don't conflate.

---

## S8 (continued) — Metadata, comments & tags for discoverability

S8 isn't only inheritance; ~half of it is **making data discoverable**. Two primitives ([Best practices for data and AI governance](https://learn.microsoft.com/azure/databricks/lakehouse-architecture/data-governance/best-practices)): **comments** (free-text descriptions) and **tags** (key + optional value).

### Comments

`COMMENT ON { CATALOG | SCHEMA | TABLE | COLUMN | VOLUME | SHARE | … } name IS '…'` ([COMMENT ON](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-comment)). Search reviews **table names, column names, table comments, and column comments** — so good comments directly improve search hits ([Discover data](https://learn.microsoft.com/azure/databricks/discover/)).

```sql
COMMENT ON TABLE sales.customers IS 'Cleansed customer dim; PII pseudonymized (SHA2 v1)';
COMMENT ON COLUMN sales.customers.email IS 'Masked via email_mask_sql; raw only for auditors';
```

> **Two silent behaviors:** (1) Editing a comment in Catalog Explorer **triggers an `ALTER` SQL command**, which "can disrupt Databricks pipelines and jobs" ([Add comments](https://learn.microsoft.com/azure/databricks/comments/)) — and on a Delta/UC table it records a `SET TBLPROPERTIES` entry in table history. (2) **AI-generated comments** exist (Catalog Explorer "AI generate"), but Databricks "**should not be relied on for data classification tasks such as detecting columns with PII**" and require human review ([AI-generated comments](https://learn.microsoft.com/azure/databricks/comments/ai-comments)). To *view* comments you only need **`BROWSE`**; to *edit* table comments you need owner or `MODIFY`+`SELECT`+`USE CATALOG`+`USE SCHEMA` (views/MVs require ownership — `MANAGE` is insufficient).

### Tags and governed tags

**Tags** = key + optional value on securables (catalogs, schemas, tables, **columns**, views, volumes, functions, models). Need **`APPLY TAG`** + `USE SCHEMA` + `USE CATALOG`, or ownership ([Apply tags](https://learn.microsoft.com/azure/databricks/database-objects/tags)).

**Governed tags** = account-level tags with a **policy**: controlled key, allowed-value set, and `ASSIGN`-permission control — so tagging stays consistent and only authorized users set them. They power **ABAC policies** via `has_tag()` / `has_tag_value()` ([Governed tags](https://learn.microsoft.com/azure/databricks/admin/governed-tags/), [ABAC core concepts](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/core-concepts)). **System tags** are predefined governed tags (e.g. certified/deprecated) you can't edit but can control who assigns.

> **Tag-inheritance trap — the exact rule:** for **ABAC evaluation**, a tag on a parent applies to all objects beneath it — **except tags do NOT inherit to the column level** (column tags must be applied directly) ([ABAC core concepts — governed tags](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/core-concepts)). And this implicit inheritance "occurs when evaluating ABAC policies only. Tag inheritance doesn't apply generally" ([Apply tags — implicit inheritance](https://learn.microsoft.com/azure/databricks/database-objects/tags)).

> **Constraints to recall:** tag keys are **case-sensitive** (`Sales`≠`sales`); max **50 tags per object**, **1000 column tags per table**; key ≤255 / value ≤1000 chars; characters `. , - = / :` are **not allowed in keys**; **you cannot tag multiple columns in one `ALTER TABLE`** (one column at a time — unlike `COMMENT`, which does allow multiple columns) ([Apply tags — constraints](https://learn.microsoft.com/azure/databricks/database-objects/tags)). **Security warning:** tag data is stored as plain text and may replicate globally — never put PII/secrets in tag names or values.

```sql
ALTER TABLE sales.customers SET TAGS ('domain' = 'crm', 'sensitivity' = 'high');
ALTER TABLE sales.customers ALTER COLUMN ssn SET TAGS ('pii' = 'true');  -- one column per statement
```

### Certified / deprecated (trust signals)

System tags flag assets **certified** (trusted, meets quality bar) or **deprecated** (outdated) — they surface inline and **influence search ranking** ([Data discovery in Unity Catalog](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/data-discovery)).

**Recap:** comments + tags drive discoverability and search; governed tags add account-level consistency and feed ABAC; tags inherit downward *only for ABAC* and *never to columns*; keys are case-sensitive and PII-free; editing a comment fires an `ALTER` that can disrupt jobs.

---

## Common exam traps (memorize this box)

> 1. **`CAN VIEW` (UI) == `CAN READ` (API).** Same level, two names. DABs/Terraform use `CAN_READ`.
> 2. **`SELECT` alone can't read a table** — you also need `USE CATALOG` + `USE SCHEMA`. A table owner granting SELECT can't bypass the catalog owner's `USE CATALOG` gate.
> 3. **Metastore privileges do NOT inherit downward.** Catalog/schema grants do.
> 4. **Owner ≠ MANAGE:** owner is single, implied (invisible in `SHOW GRANTS`), needs no usage privs; MANAGE is multi-principal, explicit on children, requires usage privs. `ALL PRIVILEGES` excludes `MANAGE`.
> 5. **Ownership does not inherit downward** — owning a catalog gives you *manage* over children, not *ownership* of them.
> 6. **Workspace binding beats any grant.**
> 7. **`is_member` = workspace groups; `is_account_group_member` = account groups.** Use the latter for UC data; the former is the trap answer.
> 8. **Mask applies before joins/predicates/ordering** → joins compare *masked* values.
> 9. **Type mismatch in a filter/mask UDF silently NULLs** (ANSI off) → wrong results, no error.
> 10. **Drop the MASK/ROW FILTER before the function** or the table becomes inaccessible.
> 11. **Python UDF can't be a mask directly** — wrap in a SQL UDF (else `[ROUTINE_NOT_FOUND]`).
> 12. **Deletion ≠ obfuscation:** docs say full erasure is the only way to eliminate re-identification risk.
> 13. **Plain `SHA2(pii)` is brute-forceable** (small input domain) — salt/version it.
> 14. **VACUUM default = 7 days; table history default = 30 days.** Different defaults, different jobs.
> 15. **Deletion vectors require `REORG … APPLY (PURGE)` for compliance** (then VACUUM); `OPTIMIZE` auto-purges only >5% DV files.
> 16. **Deleting from a streaming-table source breaks the stream** → DELETE source + DELETE ST + `skipChangeCommits`.
> 17. **Tags inherit downward only during ABAC evaluation, and never to columns.** Tag keys are case-sensitive; one column per `ALTER TABLE … SET TAGS`.
> 18. **`BROWSE` = discover metadata without data access** (catalog-level only); grant to `All account users`.
> 19. **Reading masked/filtered tables on dedicated compute silently bills serverless** (DBR 15.4+).
> 20. **Run-Now executes a job as its owner**, not the user who clicked it.

---

## Hands-on lab (run in your own workspace — Day 2)

Use a scratch catalog so nothing collides with Apollo. Run on a **SQL warehouse** or standard-access-mode cluster (filters/masks won't read on dedicated ≤ DBR 15.3).

**Setup**
```sql
CREATE CATALOG IF NOT EXISTS dq_lab;
CREATE SCHEMA  IF NOT EXISTS dq_lab.sec;
USE CATALOG dq_lab; USE SCHEMA sec;

CREATE TABLE customers (id INT, name STRING, email STRING, ssn STRING, region STRING, dob DATE)
  TBLPROPERTIES ('delta.enableDeletionVectors' = 'true');
INSERT INTO customers VALUES
  (1,'Alice','alice@corp.com','111-22-3333','US', DATE'1990-04-01'),
  (2,'Bob','bob@corp.com','444-55-6666','UK', DATE'1985-11-12'),
  (3,'Cara','cara@corp.com','777-88-9999','US', DATE'1995-07-30');
```

**1. Column mask** — mask `ssn` unless caller is in `HumanResourceDept`; verify with `SELECT *`. Then add an email-domain generalization mask. Confirm `DROP MASK` before `DROP FUNCTION` and observe the inaccessible-table error if you do it backwards (then recover).

**2. Row filter** — `us_filter(region)` returning all rows for `admin`, else `region='US'`; `SET ROW FILTER`; query and confirm Bob's UK row disappears.

**3. Dynamic view** — build `customers_redacted` using `is_account_group_member('auditors')` to reveal full email vs domain-only. Deliberately rewrite it with `is_member` and note the behavioral difference (workspace vs account group). Don't grant the view's readers `SELECT` on `customers`.

**4. Pseudonymization** — add a `customer_pk` column = `SHA2(CONCAT(CAST(id AS STRING),'_v1'),256)`; confirm two rows with the same id hash identically (join-safe), and that bumping `_v1`→`_v2` changes the hash.

**5. Inheritance + least privilege** — `GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG dq_lab TO <a group>`; then *revoke* `USE CATALOG` and confirm SELECT alone now fails. `GRANT BROWSE` and confirm the group can discover but not read.

**6. Retention purge (the full compliance ceremony)**
```sql
DELETE FROM customers WHERE id = 2;          -- logical (soft-delete via DV)
DESCRIBE HISTORY customers;                  -- see the DELETE version
REORG TABLE customers APPLY (PURGE);         -- DV tables need this for compliance
-- shrink window to demo (DO NOT do this in prod without the safety analysis):
SET spark.databricks.delta.retentionDurationCheck.enabled = false;
VACUUM customers RETAIN 0 HOURS;             -- physically removes unreferenced files
DESCRIBE DETAIL customers;                   -- inspect protocol / DV metadata
```

**7. Discoverability** — `COMMENT ON TABLE` + `COMMENT ON COLUMN`; `ALTER TABLE … SET TAGS ('sensitivity'='high')` and a column tag `('pii'='true')` (one column per statement); then search the table in the workspace search bar and confirm the comment is searchable.

**Cleanup:** `DROP CATALOG dq_lab CASCADE;`

---

## One-page recap table

| Topic | The fact you'll be tested on | Doc |
|---|---|---|
| 3 access systems | ACL=workspace objects · UC=data · Account RBAC=account objects (never substitute) | [auth](https://learn.microsoft.com/azure/databricks/security/auth/) |
| ACL levels | per-object ladders differ; `CAN VIEW`(UI)=`CAN READ`(API); folder inheritance; Run-Now runs as owner | [ACLs](https://learn.microsoft.com/azure/databricks/security/auth/access-control/) |
| UC inheritance | catalog→schema→table inherits; **metastore grants don't**; need `USE CATALOG`+`USE SCHEMA`+`SELECT` | [permissions concepts](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts) |
| Owner vs MANAGE | owner single/implied/no-usage; MANAGE multi/explicit/needs-usage; `ALL PRIVILEGES` ⊅ MANAGE | [permissions concepts](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/access-control/permissions-concepts) |
| BROWSE / binding | BROWSE = discover w/o data (catalog only); workspace binding overrides grants | [securable objects](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/securable-objects) |
| Row filter | SQL UDF→BOOLEAN, drops FALSE rows, one/table, `SET ROW FILTER` | [filters & masks](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/filters-and-masks/manually-apply) |
| Column mask | SQL UDF→value, one/column, `SET MASK`, `USING COLUMNS`; applies *before* joins; Python needs SQL wrapper | [column mask](https://learn.microsoft.com/azure/databricks/sql/language-manual/sql-ref-syntax-ddl-column-mask) |
| Dynamic view | `is_account_group_member` (acct) not `is_member` (wksp); multi-table RLS/CLS; poor audit/probe-able | [dynamic views](https://learn.microsoft.com/azure/databricks/views/dynamic) |
| Anonymization | hashing(join-safe, salt it) · tokenization(reversible/vault) · suppression(drop) · generalization(coarsen) | [common patterns](https://learn.microsoft.com/azure/databricks/data-governance/unity-catalog/abac/common-patterns) |
| PII pipeline | bronze isolated → silver SHA2+MASK+generalize → gold aggregates; refresh=owner, query=invoker | [GDPR](https://learn.microsoft.com/azure/databricks/ldp/gdpr) |
| RTBF on streaming | delete source + delete ST + `skipChangeCommits`; MVs self-heal on refresh | [GDPR](https://learn.microsoft.com/azure/databricks/ldp/gdpr) |
| VACUUM | default 7-day floor (`delta.deletedFileRetentionDuration`), safety check, kills time travel; history default 30d | [VACUUM](https://learn.microsoft.com/azure/databricks/sql/language-manual/delta-vacuum) |
| Deletion vectors | `DELETE`→`REORG … APPLY (PURGE)`→`VACUUM` for compliance; OPTIMIZE auto-purges >5% | [deletion vectors](https://learn.microsoft.com/azure/databricks/tables/features/deletion-vectors) |
| Comments | searchable; editing fires `ALTER` (can disrupt jobs); AI-comments ≠ PII classifier | [comments](https://learn.microsoft.com/azure/databricks/comments/) |
| Tags | `APPLY TAG`; governed tags→ABAC; inherit only for ABAC, never to columns; case-sensitive; one col/statement | [tags](https://learn.microsoft.com/azure/databricks/database-objects/tags) |

*Grounded in current Azure Databricks docs (learn.microsoft.com), verified June 2026. Pair with the Day-2 lab above, then do the Security/Governance set in `MCQ_Bank.md`.*
