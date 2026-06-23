# Security & Compliance — Practice MCQs (10%)

1. A team must ensure that analysts in the `pii_viewers` account group see plaintext `email` values while everyone else sees a masked value, without maintaining separate copies of the `customers` table. They write this UDF:

   ```sql
   CREATE FUNCTION mask_email(email STRING)
   RETURNS STRING
   RETURN CASE WHEN is_account_group_member('pii_viewers') THEN email
               ELSE '***' END;
   ```

   Which statement correctly applies this as a column mask on the existing table?

   - A. `ALTER TABLE customers ALTER COLUMN email SET MASK mask_email`
   - B. `ALTER TABLE customers SET ROW FILTER mask_email ON (email)`
   - C. `CREATE VIEW customers_masked AS SELECT mask_email(email) FROM customers`
   - D. `GRANT MASK ON COLUMN customers.email TO mask_email`

2. A `transactions` table must be restricted so each analyst sees only rows for the region group they belong to, enforced centrally regardless of how the table is queried. An engineer defines a UDF to use as a Unity Catalog row filter on the `region` column. Which UDF definition is valid for use as a row filter?

   - A. `CREATE FUNCTION region_filter(region STRING) RETURNS BOOLEAN RETURN is_account_group_member('admins') OR is_account_group_member(region)`
   - B. `CREATE FUNCTION region_filter(region STRING) RETURNS STRING RETURN CASE WHEN region = 'APAC' THEN region ELSE NULL END`
   - C. `CREATE FUNCTION region_filter() RETURNS BOOLEAN RETURN true`
   - D. `CREATE FUNCTION region_filter(region STRING) RETURNS TABLE(region STRING) RETURN SELECT region`

3. A compliance officer requires that customer support staff be able to recover the original national-ID value for a flagged fraud case using a securely stored mapping, but the analytics warehouse must never expose the raw value. The data team is choosing a de-identification technique. Which technique satisfies the recoverability requirement?

   - A. Tokenization, where each ID is replaced by a token that maps back to the original value via a secured vault
   - B. SHA-256 hashing of the ID with a per-row random salt that is discarded
   - C. Generalization, replacing the exact ID with only its issuing-state prefix
   - D. Suppression, replacing the ID column entirely with NULL

4. A Delta table `users` has deletion vectors enabled. To satisfy a GDPR erasure request, an engineer runs `DELETE FROM users WHERE user_id = 42` and confirms the row no longer appears in queries. An auditor still finds the raw PII inside the underlying Parquet files in cloud storage. Which sequence permanently removes the data from storage?

   - A. `DELETE` the rows, then `REORG TABLE users APPLY (PURGE)`, then `VACUUM users`
   - B. `DELETE` the rows, then `VACUUM users` with `RETAIN 0 HOURS` only
   - C. `DELETE` the rows, then `OPTIMIZE users ZORDER BY (user_id)` only
   - D. `DELETE` the rows, then `ALTER TABLE users DROP DELETION VECTORS`

5. A Structured Streaming job ingests raw clickstream events containing email and IP into a bronze table, and must publish a silver table where PII is de-identified before any consumer can read it. Bronze raw PII must be retained only for short-term replay by the data-engineering team. Which design is compliant and avoids leaking raw PII to silver consumers?

   - A. Apply deterministic SHA-256 hashing of email/IP inside the streaming transformation that writes silver, and restrict bronze to the data-engineering group via Unity Catalog privileges
   - B. Write raw PII to silver and add a downstream SQL Alert that emails the team if PII appears
   - C. Grant all consumers SELECT on bronze and rely on the BI tool to hide PII columns client-side
   - D. Disable Auto Loader schema inference so the email/IP columns are dropped automatically

6. A new contractor needs to trigger and cancel runs of an existing production job, but must not be able to edit its definition, change the cluster configuration, modify its permissions, or delete it. Following least privilege with job ACLs, which permission should they be granted on the job?

   - A. CAN MANAGE RUN on the job
   - B. CAN MANAGE on the job
   - C. IS OWNER on the job
   - D. CAN VIEW on the job only

7. A health analytics dataset must be released for cohort analysis. Exact birth dates and full 6-digit PIN codes create high re-identification risk, but analysts still need approximate age bands and broad geography. Which anonymization technique best preserves analytical value while reducing re-identification risk?

   - A. Generalization — replace birth date with a 10-year age band and PIN with its first 2 digits
   - B. Suppression — set birth date and PIN to NULL for every record
   - C. Tokenization — replace birth date and PIN with reversible tokens
   - D. Keep the raw columns but apply a column mask that only admins can bypass

8. Requirements: members of `finance` see full `salary`; members of `hr` see salary rounded to the nearest 10,000; everyone else sees NULL. Which SQL UDF body, when attached as a column mask on `salary`, implements this correctly?

   - A. `CASE WHEN is_account_group_member('finance') THEN salary WHEN is_account_group_member('hr') THEN round(salary, -4) ELSE NULL END`
   - B. `CASE WHEN current_user() = 'finance' THEN salary ELSE 0 END`
   - C. `is_account_group_member('finance') AND salary > 0`
   - D. `SELECT salary FROM employees WHERE is_account_group_member('finance')`

9. Auditors require two distinct controls on a `customers` Delta table (deletion vectors enabled): (1) most analysts must never see raw `phone`, and (2) when a customer invokes their right to be forgotten, their record must be physically removed from storage. Which combination correctly addresses both — and why are they not interchangeable?

   - A. A column mask on `phone` for control 1; `DELETE` + `REORG TABLE ... APPLY (PURGE)` + `VACUUM` for control 2, because masking only changes values at query time and never removes stored bytes
   - B. A column mask on `phone` for both, because a mask physically deletes the underlying data when applied
   - C. `DELETE` + `VACUUM` for both, because removing the row also satisfies the access-control requirement for remaining users
   - D. Row filters for control 1 and column masks for control 2, because filters delete rows and masks delete columns

10. An engineer must pseudonymize `email` in a silver table so that (a) the same email always maps to the same pseudonym to allow joins across tables, and (b) an attacker who obtains the table cannot trivially recover common emails via a precomputed rainbow table. Which approach best meets both?

    - A. SHA-256 of the email concatenated with a secret, access-controlled salt that is the same for all rows, in a function marked `DETERMINISTIC`
    - B. SHA-256 of the email with a fresh random salt generated per row and stored in an adjacent column
    - C. Replace email with a per-session random UUID generated at query time
    - D. Base64-encode the email

---

## Answers & Explanations

1. **A** — Column masks are bound to a column with `ALTER TABLE ... ALTER COLUMN <col> SET MASK <func>`. Per the Databricks docs, a column mask is a scalar SQL UDF that "takes the column value as input and returns the original value or a masked version," evaluated at query time and able to inspect the caller's group membership (here via `is_account_group_member`). B is wrong because `SET ROW FILTER` attaches a row filter — a BOOLEAN UDF that drops rows, not a mask. C is a manual dynamic-view workaround that does not use the UC mask mechanism and creates a second object to maintain, contradicting the "no separate copies" requirement. D is invented syntax; there is no `GRANT MASK` statement. *(Objective: S7 — Row filters + column masks — column mask UDF binding and signature)*

2. **A** — A row filter is a scalar SQL UDF returning BOOLEAN; per the docs, "rows where the function returns FALSE are excluded from query results." The UDF receives the filtered column as a parameter and may branch on the caller's identity/group, so A is valid (`admins` see all rows; others see only rows whose region matches a group they belong to). B returns STRING — that is a column-mask signature, not a row filter. C takes no parameter mapped to the filtered column, so it cannot be attached with `ALTER TABLE ... SET ROW FILTER ... ON (region)`. D returns a TABLE; row filters must be scalar BOOLEAN UDFs, not table-valued functions. *(Objective: S7 — Row filters — row filter UDF return type and semantics)*

3. **A** — Tokenization is pseudonymization: the value is replaced by a token, and a separately secured mapping (vault) allows authorized recovery — exactly the requirement. The Databricks GDPR guidance contrasts complete deletion against obfuscation techniques like pseudonymization, where recovery via a retained mapping is what distinguishes pseudonymization from anonymization. B (hashing with a discarded salt) is irreversible anonymization — with the salt thrown away the original cannot be recovered. C (generalization) is irreversible loss of precision. D (suppression to NULL) destroys the value. Only tokenization with a retained mapping is recoverable. *(Objective: S7 — Anonymization vs pseudonymization — reversibility distinction)*

4. **A** — With deletion vectors enabled, `DELETE` is a soft-delete: rows are logically hidden but the bytes remain in the existing Parquet files. The Databricks GDPR doc states that for tables with deletion vectors "after deleting records, you must also run `REORG TABLE ... APPLY (PURGE)` to permanently delete underlying records," then `VACUUM` removes the now-unreferenced rewritten files from cloud storage. B is insufficient: until files are rewritten by PURGE they are still actively referenced, so VACUUM will not delete them. C compacts/clusters files but does not provide the PURGE rewrite semantics and still requires VACUUM. D is not a valid command. *(Objective: S7 — Data purging for retention compliance — deletion vectors + REORG PURGE + VACUUM)*

5. **A** — A compliant streaming PII pipeline de-identifies in-band: the silver write applies a one-way transform (deterministic SHA-256 hashing preserves joinability while removing the plaintext value), and bronze raw PII is locked down with least-privilege Unity Catalog grants to only the engineering group — the same separation-of-tables pattern Databricks documents for raw-vs-redacted PII tables. B writes raw PII to silver (the exact leak being prevented); an alert is detective, not preventive. C exposes raw PII to all consumers and relies on client-side hiding, which is trivially bypassed. D is false — Auto Loader schema inference does not selectively drop sensitive columns. (Note: hashing low-entropy fields is only strong when combined with a secret salt and access controls, as in Q10; here it is the in-band placement plus locked-down bronze that makes A the only compliant option.) *(Objective: S7 — Compliant streaming PII-masking pipeline — where masking must occur)*

6. **A** — Per the Databricks job ACL table, CAN MANAGE RUN lets a principal run, run-with-different-parameters, and cancel runs of an existing job (and view its results/logs and Spark UI), but does NOT grant "Edit job settings," "Delete job," or "Modify permissions" — those require IS OWNER or CAN MANAGE. CAN MANAGE RUN is therefore the minimal grant satisfying the requirement. B (CAN MANAGE) grants full edit/delete and cluster-config rights, exceeding least privilege. C (IS OWNER) is broader still (adds permission management). D (CAN VIEW) cannot trigger runs, failing the functional need. *(Objective: S7 — ACLs on workspace objects — least privilege / policy enforcement)*

7. **A** — Generalization lowers precision (birth date to a 10-year age band, full PIN to a 2-digit prefix) so individuals are no longer uniquely identifiable while age bands and broad geography stay usable — the stated need. B (suppression to NULL) destroys analytical value. C (tokenization) is reversible pseudonymization, so it does not actually reduce re-identification risk for a holder of the mapping and yields no usable age bands. D keeps the raw high-risk values in the table and merely controls who can see them, which does not anonymize the released dataset itself. *(Objective: S7 — Anonymization techniques — generalization vs suppression for re-identification risk)*

8. **A** — A column mask UDF takes the column value as input and returns a value castable to the column's type. A branches on group membership via `is_account_group_member` to return the full value, a generalized (rounded) value, or NULL, matching all three tiers. B compares `current_user()` (an identity/email string) to the literal group name `'finance'`, which never matches, so finance would never see the full salary. C returns BOOLEAN — a row-filter signature, not a column mask. D is a query, not a scalar masking expression, and cannot be a mask body. *(Objective: S7 — Row filters + column masks — conditional dynamic masking by group)*

9. **A** — The two controls are orthogonal. A column mask is query-time access control: it changes what a principal sees, but the raw bytes remain in storage, so it cannot satisfy erasure. Physical erasure of a deletion-vector table requires `DELETE`, then `REORG TABLE ... APPLY (PURGE)` to rewrite the affected Parquet files, then `VACUUM` to drop the now-unreferenced files. B is wrong — masks never delete stored data. C conflates the controls: deleting one customer's row does nothing to restrict other analysts from seeing the remaining customers' raw phone numbers. D misstates the mechanisms — row filters hide rows at query time (they do not delete) and column masks transform values (they do not delete columns). *(Objective: S7 — Compliant batch PII-masking + retention — combining mask for access and purge for erasure)*

10. **A** — A keyed/salted hash with a single secret salt shared across all rows is deterministic (the same email yields the same pseudonym, preserving cross-table joins), and the secret, access-controlled salt defeats generic rainbow tables — satisfying both requirements. This matches the Databricks "Common patterns for row filtering and column masking" recipe, which uses a `DETERMINISTIC`-marked SHA2 function for consistent pseudonymization (`SHA2(CONCAT(val, ...), 256)`); marking it `DETERMINISTIC` also lets the engine optimize. B uses a fresh per-row salt, so the same email hashes to different values — breaking joins — and storing the salt adjacent weakens protection. C produces a different value every session, so it is unstable and unjoinable. D Base64 is reversible encoding, not hashing, and offers no protection. *(Objective: S7 — Pseudonymization with hashing — deterministic, salted, join-preserving design)*
