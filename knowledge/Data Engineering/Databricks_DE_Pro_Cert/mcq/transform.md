# Data Transformation, Cleansing & Quality — Practice MCQs (10%)

1. An analyst writes the following Spark SQL to compute a daily running revenue total per store on a large fact table:

   ```sql
   SELECT store_id, sale_date, amount,
          SUM(amount) OVER (PARTITION BY store_id ORDER BY sale_date) AS running_total
   FROM sales;
   ```

   Multiple sales can occur on the same sale_date. The analyst expects running_total to accumulate row-by-row, but values for rows sharing the same sale_date all show the same (summed) total. Which explanation is correct?

   - A. Because no explicit frame was specified, Spark applies the default RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW, so all rows tied on sale_date are collapsed into the same cumulative value; switching to ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW gives the row-by-row accumulation.
   - B. Window aggregates ignore the ORDER BY clause entirely, so SUM is computed over the whole partition; an explicit ORDER BY inside the OVER clause is required to make it cumulative.
   - C. Spark SQL does not support cumulative SUM in window functions; the analyst must use a self-join on sale_date <= sale_date to get a running total.
   - D. The PARTITION BY clause forces a global aggregation; removing PARTITION BY and keeping only ORDER BY would produce the per-store running total.

2. A PySpark batch job joins a 4 TB transactions fact DataFrame to a 60 MB country_codes dimension DataFrame on country_id. The query profile shows a large shuffle (SortMergeJoin) and one straggler task. The cluster has ample driver and executor memory. Which single change most directly removes the shuffle for this size of dimension?

   - A. Wrap the small dimension in an explicit broadcast(country_codes) hint so it is sent to every executor and joined map-side, eliminating the shuffle of the 4 TB fact table.
   - B. Repartition both DataFrames by country_id with a high partition count so the SortMergeJoin tasks are evenly sized, which removes the shuffle.
   - C. Cache the 4 TB fact DataFrame before the join so the join reads from memory and skips the shuffle stage.
   - D. Convert the join to a crossJoin and filter on country_id afterward to avoid the shuffle introduced by the join key.

3. A join between two large tables on customer_id runs for hours; the Spark UI shows a handful of reduce tasks processing tens of GB each while most finish in seconds. Investigation reveals a few customer_id values (e.g., a 'GUEST' sentinel) account for most rows. Both tables are large, so broadcast is not viable. Which approach correctly mitigates the skew?

   - A. Rely on Adaptive Query Execution skew-join handling (which splits and, if needed, replicates skewed partitions into roughly evenly sized tasks) and/or salt the hot keys by appending a random suffix on the fact side and replicating those buckets on the dimension side.
   - B. Increase spark.sql.shuffle.partitions to a very large number, which guarantees the skewed key is spread evenly across the new partitions.
   - C. Add a coalesce(1) before the join so all data is processed in a single partition, removing the imbalance between tasks.
   - D. Replace the SortMergeJoin with a broadcast join of the larger table to bypass the shuffle entirely.

4. In a Lakeflow Spark Declarative Pipeline (SDP), a data engineer adds this constraint to a streaming table:

   ```python
   @dp.expect_or_fail("valid_amount", "amount > 0")
   ```

   During an update, a batch arrives containing some rows with amount <= 0. What is the documented behavior, and what should the engineer use instead if the goal is to keep the pipeline running while removing only the offending rows from the target?

   - A. expect_or_fail (ON VIOLATION FAIL UPDATE) fails the pipeline update when any record violates the constraint and atomically rolls back the transaction; to drop only the bad rows and continue, use expect_or_drop (ON VIOLATION DROP ROW).
   - B. expect_or_fail silently drops the violating rows and logs a metric; to instead halt the pipeline, the engineer should switch to expect_or_drop.
   - C. expect_or_fail writes violating rows to a _rescued_data column automatically; to fully reject them the engineer should use expect (the default) which deletes them.
   - D. expect_or_fail retains the bad rows but flags them; expect_or_drop is identical and only differs in the metric name reported in the event log.

5. Requirements: every incoming record must be persisted (none dropped or rejected), but downstream consumers should only read records passing all data-quality rules, while a separate review process reads the failing records. Using SDP expectations, which design implements this 'quarantine' pattern as documented by Databricks?

   - A. Materialize a (temporary) streaming table that tags each row with is_quarantined = NOT(all rules combined), then expose two views: a valid view filtering is_quarantined = false and an invalid view filtering is_quarantined = true.
   - B. Apply expect_or_drop for the rules on the target table; the dropped rows are automatically written to a sibling <table>_quarantine table that downstream review jobs can query.
   - C. Apply expect_or_fail and configure ON VIOLATION QUARANTINE so violating rows are routed to a quarantine table while valid rows continue to the target.
   - D. Set pipelines.quarantine = true in the pipeline settings so SDP creates separate good/bad tables automatically without writing any custom rule logic.

6. A classic (non-SDP) Structured Streaming job uses Auto Loader to ingest JSON files whose schema drifts over time. The team needs (1) records with unexpected/extra fields or type mismatches preserved rather than lost, and (2) genuinely malformed/corrupt JSON records isolated for inspection. Which configuration meets both needs?

   - A. Keep the default _rescued_data column to capture fields that don't match the current schema (wrong type, unknown column, case mismatch) as a JSON blob, and set badRecordsPath to capture incomplete/malformed JSON records.
   - B. Set mode = FAILFAST so the stream stops on the first bad record, then manually move the offending file to a quarantine folder for inspection.
   - C. Drop the _rescued_data column and rely solely on badRecordsPath, which captures both schema-mismatched fields and malformed records in one location.
   - D. Enable cloudFiles.inferColumnTypes = false so all columns load as strings, which removes the possibility of bad records entirely.

7. A PySpark transform must produce, for each customer_id, the single most recent event row (all columns) from a multi-billion-row events table that has an event_ts column. Which approach is the most efficient and correct on large data?

   - A. Use a window: ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY event_ts DESC) and filter rn = 1, which returns exactly one full row per customer even when timestamps tie.
   - B. GROUP BY customer_id and SELECT MAX(event_ts) along with the other columns directly, which returns the full latest row per customer in one shuffle.
   - C. Use dropDuplicates(['customer_id']) which is guaranteed to keep the row with the maximum event_ts for each customer_id.
   - D. Use FIRST(*) with a GROUP BY customer_id; FIRST always returns the row with the latest event_ts regardless of ordering.

8. A transform on a 2 TB Delta table currently does df.repartition(2000).filter("status = 'ACTIVE'").select(...). The query profile shows the full table being shuffled before the filter, and the filter eliminates ~95% of rows. The table has stats collected on status. Which change most improves efficiency?

   - A. Apply the filter first so predicate pushdown and Delta data skipping prune files before any shuffle, and drop the explicit repartition unless a later wide operation actually needs it.
   - B. Increase the repartition count to 8000 so the post-shuffle partitions are smaller and the filter runs faster on each.
   - C. Replace repartition with coalesce(2000) before the filter, which avoids the shuffle while keeping the same partition count.
   - D. Cache the DataFrame immediately after repartition so the shuffle only happens once across the whole job.

## Answers & Explanations

1. **A** — Per the Databricks Window reference, when ordering is defined but no frame is given, the default is a growing window frame: RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW. A RANGE frame is value-based — it includes all peer rows sharing the same ORDER BY value — so every tie on sale_date receives one identical cumulative total. Specifying ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW makes the frame positional (row offsets), giving a true row-by-row running total. B is wrong: ORDER BY is present and is exactly what makes the aggregate cumulative. C is wrong: Spark fully supports cumulative window SUM. D is wrong: removing PARTITION BY would accumulate across all stores and is not the cause of the tie behavior. *(Objective: S3 Transform/Quality — efficient Spark SQL/PySpark transforms, window functions)*

2. **A** — A broadcast hash join sends the small dimension to every executor and joins map-side, so the 4 TB fact table is never shuffled. The key correction: 60 MB exceeds both auto-broadcast defaults (static spark.sql.autoBroadcastJoinThreshold = 10 MB; Databricks AQE spark.databricks.adaptive.autoBroadcastJoinThreshold = 30 MB), so Spark will NOT auto-broadcast it — an explicit broadcast() hint is required, and per the Databricks Hints documentation the BROADCAST hint broadcasts the relation regardless of autoBroadcastJoinThreshold. B reduces skew within a SortMergeJoin but still shuffles the 4 TB fact table, which is exactly what we want to avoid. C caching does not change the join strategy; a SortMergeJoin still shuffles. D crossJoin produces a Cartesian explosion and is far worse. *(Objective: S3 Transform/Quality — efficient joins on large data, broadcast vs shuffle)*

3. **A** — Skew comes from too many rows hashing to one key, so they all land in one partition. Per the Databricks AQE documentation, skew-join handling dynamically splits oversized skewed partitions (replicating the matching side as needed) into roughly evenly sized tasks for sort merge join and shuffle hash join. Salting — appending a random bucket suffix to the hot key on the fact side and replicating those buckets on the dimension side — manually spreads one hot key across many partitions; the Databricks best-practices guidance explicitly recommends salting highly-skewed keys. B fails because all rows with the same key still hash to the same partition regardless of partition count. C coalesce(1) makes it strictly worse (single task). D broadcasting a large table will OOM the executors and is not viable here. *(Objective: S3 Transform/Quality — efficient transforms on skewed joins, salting / AQE skew handling)*

4. **A** — Per the Databricks expectations documentation, expect_or_fail maps to ON VIOLATION FAIL UPDATE: it stops execution immediately when a record fails validation and, for a table update, atomically rolls back the transaction; because the update fails, per-record metrics are not recorded. To keep the pipeline running while removing only the violating rows from the target, use expect_or_drop (ON VIOLATION DROP ROW), which drops the bad rows and continues, logging the dropped count. B inverts the two operators. C is wrong: _rescued_data is an Auto Loader feature, not an expectation action, and the plain expect operator retains (does not delete) bad rows. D is wrong: expect (warn, the default) keeps violating rows while expect_or_drop removes them — a material difference, not just a metric name. *(Objective: S3 Transform/Quality — quarantine bad data in SDP, expectations + ON VIOLATION)*

5. **A** — The documented SDP quarantine pattern ingests ALL rows into a single (temporary) streaming table partitioned by is_quarantined, adds an is_quarantined column computed as NOT(all rules combined) — i.e., the inverse of the AND of the expectation constraints — then defines two filtered views: valid (is_quarantined = false) and invalid (is_quarantined = true). This keeps every record while separating the consumption paths. B is wrong: expect_or_drop discards rows; it does not auto-write them to a quarantine table. C is wrong: there is no ON VIOLATION QUARANTINE action — the only actions are warn (EXPECT), drop (DROP ROW), and fail (FAIL UPDATE). D is wrong: there is no pipelines.quarantine setting that auto-splits tables. *(Objective: S3 Transform/Quality — quarantine bad data in SDP, inverted-rule quarantine pattern)*

6. **A** — Per the Auto Loader schema documentation, the _rescued_data column (added automatically when the schema is inferred) captures any field that doesn't match the current schema — wrong type, unknown/missing column, or case mismatch — as a JSON blob with the source file path, satisfying need (1). The badRecordsPath option captures incomplete/malformed JSON or CSV records that cannot be parsed at all, satisfying need (2). The docs state the two are complementary: when rescuedDataColumn is in use, data type mismatches are NOT treated as bad records, so only genuinely corrupt records go to badRecordsPath. B FAILFAST halts the entire stream rather than quarantining. C is wrong: badRecordsPath does not capture mere type/schema mismatches when rescuedDataColumn is used; those go to _rescued_data. D loading as strings does not eliminate corrupt/unparseable records and discards type information. *(Objective: S3 Transform/Quality — quarantine bad data in Auto Loader classic jobs)*

7. **A** — ROW_NUMBER() partitioned by customer_id and ordered by event_ts DESC assigns rank 1 to the latest row; filtering rn = 1 returns exactly one complete row per customer, with ties broken deterministically by ROW_NUMBER. B is invalid SQL semantics: you cannot select arbitrary non-aggregated columns alongside MAX(event_ts) and get the matching row's values without a join or window. C dropDuplicates keeps an arbitrary row per key, not the latest. D FIRST without an explicit ordered window returns a non-deterministic row, not necessarily the latest. *(Objective: S3 Transform/Quality — efficient aggregations on large data, deduplication semantics)*

8. **A** — repartition() is a wide transformation that shuffles the entire 2 TB before the filter even runs, materializing data the filter then discards. Filtering first lets Spark push the predicate down and lets Delta data skipping prune files using the min/max statistics collected on status (Delta collects stats on the first 32 columns by default), so ~95% of data is eliminated before any expensive shuffle. The explicit repartition should be removed unless a downstream wide operation actually needs that layout. B shuffles even more data. C coalesce on 2 TB into 2000 partitions still forces data movement and still happens before the filter. D caching a needless shuffle just pays the cost once instead of removing it. *(Objective: S3 Transform/Quality — efficient Spark transforms, avoiding wide vs narrow misuse)*
