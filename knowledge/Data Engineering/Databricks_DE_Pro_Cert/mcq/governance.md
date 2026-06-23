# Data Governance — Practice MCQs (7%)

1. A data engineer runs the following to set up access for the analytics team on a new catalog that will accumulate dozens of schemas and hundreds of tables over the next year:

   ```sql
   GRANT USE CATALOG ON CATALOG sales_prod TO `analysts`;
   GRANT USE SCHEMA, SELECT ON CATALOG sales_prod TO `analysts`;
   ```

   A teammate argues these grants will only cover the tables that exist today and that new tables created next month will be invisible to the analysts. Which statement is correct about how Unity Catalog will behave?

   - A. The grants apply to all current AND future schemas and tables in `sales_prod`, because a privilege granted on a container object is inherited by all current and future child objects.
   - B. The teammate is right; `SELECT` granted at the catalog level only resolves against tables that existed at grant time, so a nightly re-`GRANT` job is required for new tables.
   - C. `USE SCHEMA` and `SELECT` cannot be granted on a catalog; they must be granted on each schema individually, so only explicitly granted schemas will be accessible.
   - D. The grants apply to future tables only if AUTO INHERIT is first enabled on the catalog with `ALTER CATALOG sales_prod SET INHERIT = true`.

2. An analyst is granted `SELECT` directly on the table `prod.finance.gl_entries`, but no other privileges. When they run `SELECT * FROM prod.finance.gl_entries` they get a permission error. The analyst insists `SELECT` on the table should be sufficient. Which explanation correctly diagnoses the failure?

   - A. Reading a table also requires `USE CATALOG` on its parent catalog (`prod`) and `USE SCHEMA` on its parent schema (`finance`); `SELECT` alone on the table is insufficient.
   - B. `SELECT` must be granted on the schema, not the table; table-level `SELECT` grants are silently ignored by Unity Catalog.
   - C. The analyst additionally needs the `BROWSE` privilege on the table, because `BROWSE` is the prerequisite for any data read.
   - D. The catalog owner must first run `ALTER TABLE ... OWNER TO \`analyst\``, because only owners can issue `SELECT` against a managed table.

3. A platform admin wants every member of the `data_platform` group to be able to read all data in every catalog across the metastore with a single grant. They consider running `GRANT SELECT ON METASTORE TO \`data_platform\``. A reviewer pushes back. Which statement about metastore-level grants is correct?

   - A. Privileges granted at the metastore level do not inherit to catalogs, schemas, or tables; metastore grants govern only metastore-scoped operations such as `CREATE CATALOG` and `CREATE EXTERNAL LOCATION`, so a metastore grant could never confer `SELECT` on data.
   - B. It works as intended: a metastore-level `SELECT` grant cascades down through all catalogs and schemas to every table in the metastore.
   - C. Metastore-level grants are syntactically invalid in Unity Catalog; all privileges must originate at the catalog level or below.
   - D. It works, but only for catalogs created before the grant; catalogs created afterward would each need their own metastore-level re-grant.

4. A team lead owns the catalog `ml_features`. A new schema `ml_features.embeddings` is created inside it by another engineer. The team lead assumes that because they own the parent catalog, they automatically own the new schema and every table created within it. Which statement most accurately describes the relationship between catalog ownership and child objects in Unity Catalog?

   - A. Ownership does not inherit downward; the catalog owner does not become the owner of each child schema or table, but does automatically get the ability to manage all child objects (the equivalent of `MANAGE` on them).
   - B. Owning a catalog makes you the explicit owner of every current and future schema and table inside it, with full OWNER rights on each.
   - C. Catalog ownership grants no rights over child objects at all; the team lead would need a separate explicit grant to even see the new schema.
   - D. Child schemas inherit ownership only if they were created by the catalog owner; schemas created by other engineers are owned by no one until reassigned.

5. A governance team wants to bulk-document hundreds of legacy tables to improve discoverability and is evaluating Unity Catalog's AI-generated comments feature. A stakeholder proposes wiring it into a pipeline that auto-generates comments and saves them directly, and also wants to rely on it to flag which columns contain PII. Which recommendation is most consistent with Databricks guidance?

   - A. AI-generated comments must be reviewed by a human before saving and should not be relied upon for sensitive tasks like PII detection; they are a discoverability aid driven by object metadata such as the table schema and column names.
   - B. Auto-saving is the intended workflow because the underlying LLM reads the actual row-level data, making the generated comments authoritative enough to drive PII tagging.
   - C. The feature should be avoided entirely because AI-generated comments cannot be edited after generation and permanently overwrite any human-written comments.
   - D. It is safe to auto-save for tables, but PII detection requires first enabling a separate AI-PII-classifier privilege at the metastore level.

6. A central data team adds rich `COMMENT` descriptions and key-value tags (e.g., `domain='finance'`, `sensitivity='internal'`) to securables so analysts can find the right datasets via Catalog search. They want analysts to be able to read these comments and tags and locate the objects WITHOUT being able to query the underlying data, and without first granting `USE CATALOG` / `USE SCHEMA` on every container. Which approach satisfies this?

   - A. Grant the `BROWSE` privilege on the catalog, which lets users discover objects and view their metadata (including comments and tags) without `USE CATALOG` / `USE SCHEMA` and without granting access to the underlying data.
   - B. Grant `SELECT` on the catalog, since `SELECT` is the only privilege that exposes comments and tags, then rely on row filters to block the actual rows.
   - C. Grant `USE CATALOG` and `USE SCHEMA` everywhere, because metadata such as comments and tags is only visible to principals who already hold usage on the parent containers.
   - D. Tags and comments are visible to all workspace users by default regardless of privileges, so no grant is required; only data reads need privileges.

---

## Answers & Explanations

1. **A** — Catalogs and schemas are container objects. Per the Unity Catalog permissions model, "when you grant a privilege on a container object, that privilege automatically applies to all current and future child objects"; the docs use the exact pattern `GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG ... TO <group>` to grant read on all current and future tables. So no re-`GRANT` job is needed (B is the teammate's misconception); `USE SCHEMA` and `SELECT` are both valid catalog-scoped privileges (C is wrong); and there is no AUTO INHERIT / `INHERIT` flag — inheritance is the built-in default (D is fabricated). *(Objective: S8 — Governance: Unity Catalog permission inheritance model)*

2. **A** — The privileges reference states verbatim: "to read from a table, a user needs `SELECT` on the table, `USE CATALOG` on the parent catalog, and `USE SCHEMA` on the parent schema." All three are required (Option A). Table-level `SELECT` is fully valid and not ignored (B). `BROWSE` only enables metadata discovery and explicitly does NOT grant data access (C). Ownership is not required to read; `SELECT` plus the parent USE privileges suffices (D). *(Objective: S8 — Governance: table access prerequisites / usage privileges)*

3. **A** — The permissions-concepts doc flags this explicitly: "Privileges granted on a metastore do not inherit to child objects. Metastore-level grants control metastore-scoped operations like `CREATE CATALOG` and `CREATE EXTERNAL LOCATION`, not access to data within the metastore." The metastore privilege set is `CREATE CATALOG`, `CREATE EXTERNAL LOCATION`, `CREATE CONNECTION`, etc.; `SELECT` is not among them, so a metastore-level `SELECT` could never confer table read either way (Option A). B is the core misconception (no cascade). Metastore grants are valid syntax for metastore-scoped privileges, so C overstates it. D is irrelevant since no inheritance happens at all. *(Objective: S8 — Governance: metastore-level grants do not inherit)*

4. **A** — Per the docs: "Ownership doesn't inherit downward in Unity Catalog. However, object owners do automatically have the ability to manage all child objects. For example, if you own a catalog, you don't automatically own the child schemas within the catalog, but you can manage all child schemas" — functionally equivalent to `MANAGE` on each child, though Databricks does not explicitly assign `MANAGE` (Option A). B is the misconception that ownership flows downward like privileges. C understates the owner's reach (they do get manage capability over children, not nothing). D invents a "creator-based ownership inheritance" rule — the schema's owner is by default its creating principal, not nobody. *(Objective: S8 — Governance: ownership vs. inheritance)*

5. **A** — The AI-generated comments doc states comments "must be reviewed prior to saving," that Databricks "strongly recommends human review," and that "the model should not be relied on for data classification tasks such as detecting columns with PII." It also notes comments are "powered by a large language model (LLM) that takes into account object metadata, such as the table schema and column names" — not row-level data (Option A). B is wrong on both counts (no auto-save guidance; it does not read row data). C is fabricated — comments are editable via the UI or `ALTER`/`COMMENT ON`, and the human-review step exists precisely so nothing is blindly overwritten. D invents a non-existent "AI-PII-classifier privilege"; for actual sensitive-data tagging Databricks points to Data Classification, not AI comments. *(Objective: S8 — Governance: AI-generated comments for discoverability)*

6. **A** — `BROWSE` is purpose-built for this: per the docs it "allows users to discover objects and view their metadata without granting access to the underlying data. Users with `BROWSE` can see that an object exists, view its name, description, and tags, and request access to it without needing `USE CATALOG` or `USE SCHEMA`." For data objects, `BROWSE` is granted at the catalog level (Option A). `SELECT` would expose data and is not the metadata-visibility mechanism (B). C describes the pre-`BROWSE` limitation that `BROWSE` was designed to remove. D is wrong — metadata visibility is governed by privileges (`BROWSE`/`SELECT`/`USE`), not open to everyone by default. *(Objective: S8 — Governance: BROWSE, tags, comments for discoverability)*
