# Session Learnings — Data Engineering

Captured while building and operating the Databricks Delta deep-clone DR
framework (SE → East region).

- **Aug 12** — validating the framework and diagnosing a slow full-diff
  comparison job. Everything on Delta internals, Spark execution, and the
  testing methodology.
- **Aug 20** — adding the incremental (INC) test cases and taking the framework
  to prod in both regions. Everything on cloud capacity, infrastructure-as-code,
  job orchestration, and infrastructure diagnosis. Three prod failures in one
  day drove most of it: a cluster-policy rejection that blocked a deploy, an
  Azure vCPU quota exhaustion that killed a run, and a VM-generation compliance
  rule that constrained every choice around both.

## Delta Lake internals

- **Two independent retention clocks, not one.** `deletedFileRetentionDuration`
  (default 7d) governs how long VACUUM keeps tombstoned *data files* on disk.
  `logRetentionDuration` (default 30d) governs how long the `_delta_log`
  commits/checkpoints themselves survive. Checks that only read the log
  (schema, metadata, file stats) stay valid for the full 30 days even after
  VACUUM has removed the data — checks that read actual rows don't.
- **The log can answer more than you'd think without touching data.** File
  count and total size can be reconstructed by replaying `_delta_log`
  (checkpoint parquet + JSON commits, cancelling AddFile against RemoveFile by
  path) — no Parquet footer read, so it survives VACUUM. Schema comes from
  `metaData`, not from scanning rows. `SELECT * WHERE 1=0` gets you a real
  schema with zero file reads.
- **There are actually THREE stores behind a governed Delta table, on three
  different clocks — and knowing which one answers your question tells you
  which clock can break it.**
  1. **Physical data files** — governed by VACUUM /
     `deletedFileRetentionDuration` (default **7d**). Only reached when you
     genuinely read rows.
  2. **`_delta_log`** — commit JSONs and checkpoint Parquet, governed by
     `logRetentionDuration` (default **30d**). Answers schema, file counts,
     sizes, properties, partitioning, comments, and all history.
  3. **The Unity Catalog metastore** — governed by *neither*. Registration,
     tags, PK/FK constraints and grants live here, and there is **no time
     travel over any of it**: every read is LIVE, whatever version you pin.
  Most "which retention do I need?" confusion comes from not noticing the third
  store exists.
- **What ONLY the data files can answer** — i.e. the checks that
  `deletedFileRetentionDuration` can actually break: anything that reads row
  *values*. Set comparison (`exceptAll`), row sampling / decode checks,
  checksums, and any aggregate over a column. That is a much shorter list than
  it feels like.
- **What the log answers on its own** — safe for the full 30 days even after
  VACUUM has removed every data file: column names, types and nullability
  (`metaData.schemaString`); ordinal column order; file count and total bytes
  (replay AddFile minus RemoveFile); `SHOW TBLPROPERTIES` (reconstructable from
  `metaData.configuration` plus `protocol`); partition columns; table and column
  comments; column-mapping mode and deletion-vector settings; and every
  `DESCRIBE HISTORY` question — clone versions, clone-commit counts,
  `MAX(version)`.
- **`COUNT(*)` is the interesting edge case.** Delta usually serves it from
  per-file `numRecords` statistics in the log rather than scanning, so it often
  behaves like a log-only read — and empirically pinned row counts kept
  succeeding long after the 7-day window on a real estate. But that is an
  optimisation, not a contract: if stats are absent it falls back to reading
  files. Treat it as "usually log, occasionally data" and don't build a
  guarantee on it.
- **Reconstruction needs a checkpoint at or before the version you want, not
  just the commits.** Replaying the log from scratch is only possible back to
  the newest checkpoint at or before your target version; if log cleanup has
  removed that checkpoint, the AddFiles from the missing range are simply
  absent and a naive replay silently *under-counts*. The correct behaviour is to
  detect the gap and raise — an under-count here looks exactly like a table that
  legitimately shrank.
- **So the question to ask of any new check is just: which of the three stores
  answers it?** Data files → worry about `deletedFileRetentionDuration` (7d),
  and gate the check on it. `_delta_log` → worry about `logRetentionDuration`
  (30d), which is 4× more generous. Unity Catalog → neither clock applies, but
  you have a *different* problem: the read is live, so comparing it against a
  version-pinned counterpart is comparing now against then.
- **Deep clone copies data files, not Unity Catalog metadata.** PK/FK
  constraints, table tags, column tags live in UC's own catalog, not in the
  Delta transaction log — a clone can be byte-perfect on data and still lose
  all of that.
- **`DESCRIBE DETAIL` has no time-travel.** No `VERSION AS OF` variant exists
  for it — comparing it against a version-pinned clone target silently
  compares live-source-now against frozen-target-then. Same failure shape
  shows up anywhere a live/UC-only read is compared against a pinned one.
- **`DESCRIBE HISTORY`'s CLONE rows carry both sides' version**
  (`operationParameters.sourceVersion`), from a single query on the target —
  a good example of getting cross-side information without a second read.
- **Workspace-level Delta defaults are a distinct thing from per-table
  properties.** `spark.databricks.delta.properties.defaults.<prop>` sets what
  new tables inherit; `SHOW TBLPROPERTIES` on an existing table only shows an
  override if one was explicitly set — absence means "inheriting the
  built-in default," not "unset."
- **A CLONE commit is a far richer record than "a clone happened."** Beyond
  `operationParameters.sourceVersion` it carries `operationMetrics` —
  `numCopiedFiles`, `copiedFilesSize`, `sourceNumOfFiles`, `numRemovedFiles` —
  plus the commit `timestamp`. One `DESCRIBE HISTORY` on the target yields both
  sides' versions, the volume actually copied, and when. Worth reading the full
  operationMetrics map for any operation before building a separate audit table
  to record what Delta already recorded.
- **Counting CLONE commits is a truthful incrementality test.** Two or more
  CLONE commits in a table's history means a previous clone exists, so this one
  is genuinely incremental; exactly one is a first load; zero means never
  cloned. That is stronger evidence than a `sync_type` column in your own audit
  log, because it comes from the engine's own record rather than from whatever
  the orchestrator believed it was doing.
- **`operationMetrics` is only populated if the writer bothered to collect
  it.** A clone path running with metrics collection disabled leaves
  `numCopiedFiles` and `copiedFilesSize` structurally zero — measured at zero
  for all 13,574 tables in one environment. That zero means "not measured," not
  "nothing copied," and anything downstream that averages or sums it produces a
  confident wrong answer. Same failure shape as the NOT MEASURED point below.
- **`MAX(version)` from `DESCRIBE HISTORY` survives log truncation.** Comparing
  the version recorded at clone time against the source's current maximum tells
  you whether the source has moved since — and unlike a `VERSION AS OF` read it
  needs no specific commit to still exist, so it stays valid past
  `logRetentionDuration`. A check built this way can be deliberately exempted
  from the retention gate that pinned reads require.

## Spark execution & performance

- **`exceptAll` is a full shuffle of every column on both sides, disguised as
  a simple diff.** Spark rewrites it to a `GROUP BY` over all columns with a
  ±1 sentinel — deductive and exact, but the cost is proportional to total
  row bytes moved across the network, not to how different the tables
  actually are.
- **Row counts are usually free; set differences never are.** Delta answers
  `COUNT(*)` from log-level stats in most cases; there's no equivalent
  shortcut for an exact multiset comparison.
- **A checksum/hash comparison is a different kind of claim, not a faster
  version of the same claim.** `exceptAll` is deductive (mathematically
  complete). Summing per-row hashes is probabilistic — overwhelmingly
  reliable, but not the same as "we compared every row." That distinction is
  worth surfacing explicitly before it goes into a DR sign-off.
- **One-sided set difference can still prove full equality**, given the right
  side condition: if `|A| = |B|` and `B \ A = ∅`, then `A = B` — a two-sided
  guarantee from a one-sided (cheaper) computation.
- **Shuffle partition count is a global session setting, and "just set it
  high" has a real cost on the small end.** AQE coalesces partitions only
  *after* the shuffle write — a 10-file table still pays for planning against
  2,048 partitions even though most collapse away.
- **Photon doesn't accelerate every operator.** Enabling it on a cluster
  doesn't guarantee it's engaging on your expensive step — check the query
  plan for the Photon badge on the actual exchange/aggregate nodes.
- **Spot eviction loses shuffle state, not just compute.** An evicted
  executor's shuffle files disappear with it, so every downstream task
  waiting on them fails and the stage re-runs — on more spot capacity that may
  get evicted again. That's a correctness-adjacent infra failure mode, not a
  tuning problem.
- **The Spark UI Executors tab tells you which failure mode you're in.** Low
  GC time rules out memory pressure; `Shuffle Write >> Shuffle Read` is the
  signature of work done and then discarded and redone; executors that appear
  and die with zero tasks means the cloud provider isn't granting capacity at
  all.
- **Node shape affects shuffle locality.** Fewer, larger nodes at the same
  total core count keep more shuffle traffic node-local instead of crossing
  the network — a real lever independent of instance family.
- **`spark.conf.set` is session-global, which breaks naive "tune per
  workload" thinking under concurrency.** You can't safely give different
  threads different shuffle-partition counts in one SparkSession — the fix is
  phased/tiered execution (all giants together under one setting, then all
  small tables under another), not per-thread config.
- **Idle workers can be a symptom of a driver bottleneck, not of
  over-provisioning.** A tier running a thread pool on the driver logged ~70
  autoscaler resizes in 3h17m, oscillating 1→3→2→1 on a 40–90 second cycle, and
  looked massively over-sized. It wasn't: 24 Python threads were running on an
  8-core / 64 GB driver, each holding a Delta-log file list in driver heap, and
  the same log recorded four `DRIVER_NOT_RESPONDING … likely due to GC` stalls.
  The workers idled *because the work never reached them*. Cutting worker count
  would have been the intuitive fix and the wrong one.
- **For a driver-hosted thread pool, the metric is memory per concurrent
  thread.** 64 GB ÷ 24 threads = 2.7 GB/thread stalled; 256 GB ÷ 24 = 10.7 GB
  fixed it with no change to concurrency. Deriving that ratio turns "the driver
  feels small" into a number you can size against — and it tells you which of
  the two levers to pull, since halving the threads and doubling the driver
  reach the same ratio at very different throughput.
- **Diagnose the tier that is slow, not the tier that looks wasteful.** The
  same job had one tier finishing in 39 minutes and another in 3h17m. Effort
  spent trimming the fast one is invisible; the slow one is the only thing that
  moves wall clock. Obvious in hindsight, easy to invert when the fast tier is
  the one with the alarming-looking event log.

## Distributed batch-job design

- **Naive `index % N` chunking creates stragglers.** Splitting a workload into
  N parallel chunks by row position, when the underlying items vary wildly in
  size (a 1.08B-row table next to a 10-row one), makes total wall-clock a
  function of luck. Size-aware bin-packing (sort descending, assign to the
  currently-lightest bucket) is the standard fix.
- **Checkpoint incrementally in long-running jobs, or a 30-hour run can
  produce zero output.** Buffering all results in memory for one final write
  means any failure — including a plain timeout — loses everything. Periodic
  partial writes (with a full-rewrite-not-append pattern, so the file is
  always valid mid-run) is cheap insurance.
- **Skip-lists have to be conservative in one direction only.** A "don't
  re-check this, it already passed" list is safe to under-populate (re-verify
  more than needed) but never safe to over-populate — anything that isn't a
  confirmed pass must re-run, or a real defect disappears silently as "not in
  scope."
- **A shared skip-list is scoped to the widest run that writes it.** If a
  narrow-scope run (say, only tables touched since a timestamp) rebuilds the
  same skip-list file that the full-scope run uses, it silently discards every
  entry the full run earned. Nothing fails; the *next* full run just re-does
  everything — one narrow run over ~500 tables can cost a later run the
  13,320→497 narrowing it had banked. Either scope the file per mode, or make
  the narrow run union into the list rather than replace it.
- **Retries belong on the unit that can independently fail and independently
  redo its work.** On a fan-out, that's the inner task, not the wrapper — a
  retry on the wrapper re-runs every sibling iteration, not the one that died.
  And a retry is only safe if that unit is idempotent: each chunk must
  re-derive its own slice and *rewrite* its own output rather than append, so a
  second attempt recomputes instead of duplicating.
- **Retry count is a bet on the failure being transient.** Two attempts
  survives a one-off eviction or allocation miss without spending triple the
  runtime discovering that a chunk is systematically broken. Worth choosing
  deliberately rather than defaulting, because with no checkpointing inside the
  unit each retry redoes the whole chunk.

- **A checkpoint interval larger than the work unit is identical to no
  checkpointing at all — and raising parallelism can silently create that
  state.** The full diff checkpointed every 250 comparisons. At ~400 tables per
  chunk that fired once per run; when the chunk count was raised for speed, each
  chunk dropped to ~241 tables and the checkpoint **could never fire**. A run
  cancelled at 171 of 400 therefore produced *no result file whatsoever*,
  despite checkpointing being implemented, reviewed and believed to work.
  **Forward rule:** express the interval as a fraction of the expected work unit
  rather than an absolute count, and re-derive it whenever chunk counts or
  parallelism change. Any absolute interval is a hidden coupling to a number
  someone else is free to tune. Cheap test: divide the smallest plausible unit
  by the interval — if the answer is less than about 5, the interval is wrong.
- **A population statistic cannot be computed inside a fan-out.** The size
  threshold that routes tables into large/small tiers was originally stamped by
  the per-chunk extractor — but that task is a 5-way `for_each`, so the
  "population mean" was computed five times over five disjoint slices, giving
  five different thresholds and a tiering that depended on which chunk a table
  landed in. The fix was to move the decision into the merge step, the only
  place that sees every row. **Forward rule:** any statistic over the whole
  population — mean, median, percentile, total, rank — belongs in a reduce
  stage, never in the map stage. If a fanned-out task computes a number that
  other tasks compare against, that number is wrong by construction.
- **Verify that your tiering key actually correlates with cost before you tier
  on it.** Tables were split into tiers by *bytes*, on the assumption bigger
  tables cost more to validate. The real numbers said otherwise: an 18:1 split
  by table count produced only a 5:1 split in runtime, which means the
  extractor's cost was **per-table** (Delta log reads, metadata calls) and
  almost independent of table size. The estate was being routed on a variable
  that barely predicted the thing being optimised. **Forward rule:** before
  tiering, plot or at least ratio your candidate key against observed runtime.
  If the ratios don't track, you are load-balancing on the wrong axis — and the
  right lever changes too: for per-item cost, add more workers (more chunks);
  for per-byte cost, add bigger ones.

### Scope handles: passing "which objects" between jobs

- **"Give me a run_id and I'll tell you every table that run touched" is NOT a
  built-in Databricks capability.** It worked here only because the clone
  framework writes its **own** audit table — one row per table per run, carrying
  `run_id`, catalog/schema/table, `run_ts`, `status`, `error_message`,
  `copied_file_size` and `stream_name`. That table is application code someone
  chose to write. Do not assume the capability exists on a platform where nobody
  built it.
- **A run_id used this way is a *scope handle*: one opaque token that
  reconstitutes an exact working set anywhere.** Instead of passing 22,000 table
  names between jobs, regions and notebooks, you pass one string and let each
  consumer re-derive the same list from the audit table. Cheap to pass, precise,
  and it survives the set being large. Recognising when a token can replace a
  payload is the reusable idea here.
- **Match the scope handle to the question being asked.** A `run_id` answers
  "which tables did *this run* touch". It cannot answer "which tables have been
  incrementally cloned *since some point in time*", because that spans many runs
  — that question needs a timestamp as the handle, filtering the same audit
  table on `run_ts > T`. Same table, different handle, because the questions
  have different shapes. Reaching for run_id when the question is temporal is
  how you end up with an unanswerable scope.
- **The platform *does* record provenance, just table-first rather than
  run-first.** Delta's `DESCRIBE HISTORY` identifies the job and notebook behind
  each commit, so per table you can ask "which run wrote this". The limitation is
  the direction: you must already have candidate tables to inspect. Going the
  other way — run to tables — is what needs either an audit table or Unity
  Catalog's lineage/system tables (`system.access.*`), and the latter is subject
  to enablement and retention. Verify what your workspace actually exposes
  before designing on it.
- **The audit table earns its keep by carrying what lineage cannot.** Per-table
  `status` and `error_message` distinguish "the clone never produced this table"
  from "it produced a bad copy" — a distinction lineage has no concept of, and
  the one that makes a downstream comparison report meaningful rather than just
  a list of mismatches.
- **If you will ever need to ask "what did run X touch", design that table
  before the first run.** Retrofitting it from history or lineage is possible,
  lossy, and slow — and the data you most want (why a given object failed) was
  never captured by anything but the writer at the time.
- **Carry a size or cost signal in the audit row.** `copied_file_size` recorded
  at clone time became the input for size-tiering the downstream validation
  clusters — the only size signal available early enough to route work, because
  the obvious alternative is computed by the very task the routing decides. Audit
  rows are a good place to stash cheap facts that a later stage will need before
  it can afford to measure them itself.

## How each check actually reads, and which clock governs it

Worked example of the three-store split above, from the DR validation suite.
The pattern generalises: for any check, find the mechanism, and the mechanism
tells you the clock.

### Data-file reads — governed by `deletedFileRetentionDuration` (7d)

- **Full set comparison (`exceptAll`)** — `target.exceptAll(source)` with both
  sides pinned via `VERSION AS OF`, plus a row count on each. Reads every row of
  both tables. This is the only check in the suite that is unambiguously
  data-bound, and it is also by far the most expensive — those two facts travel
  together, because reading rows is what costs.
- **Read/decode probe** — `SELECT * FROM <ref> LIMIT n`. Deliberately a *sample*,
  not a scan: it proves the files exist and decode without paying for the table.
  A cheap way to get a data-file liveness signal without a data-file-sized bill.
- **Row count** — `SELECT COUNT(1)`. Filed here because it *can* fall through to
  the files, but in practice Delta answered it from log statistics throughout,
  which is why it was deliberately exempted from the retention gate.

### `_delta_log` reads — governed by `logRetentionDuration` (30d)

- **Schema / structure and column order** — `SELECT * FROM <ref> WHERE 1=0`, then
  read `df.schema`. The predicate is unsatisfiable so Spark plans a scan of
  nothing and returns the real schema from `metaData`. **Zero file reads for a
  full column/type/nullability signature** — the neatest trick in the suite, and
  reusable anywhere you want a schema without a read.
- **File count and total size** — replay the log: take the newest checkpoint at
  or before the target version, add the AddFile entries from later commits,
  subtract the RemoveFile entries by path, then count and sum. Reads Parquet
  *checkpoint* files and JSON *commits*, never a data file's footer. This exists
  because `DESCRIBE DETAIL` has no `VERSION AS OF`, so the obvious call would
  have compared a live source against a frozen target.
- **Table properties** — reconstructed from an already-fetched `metaData`
  configuration plus `protocol`, rather than `SHOW TBLPROPERTIES` (which is also
  live-only). Note that `SHOW TBLPROPERTIES` is not merely
  `metaData.configuration`: protocol-derived entries surface there too, so a
  faithful reconstruction has to merge both.
- **Partitioning, table comment, column comments, column-mapping mode,
  deletion vectors** — all fields of the same `metaData`/`protocol` pair, so one
  log fetch answers five checks. Fetching that pair *once* and passing it to
  every dependent check, rather than letting each re-trigger its own log walk,
  is the difference between one scan and five.
- **Clone version, clone-commit count, latest version** — all `DESCRIBE
  HISTORY`, which reads commit records only. Note `DESCRIBE HISTORY` takes no
  time-travel modifier, so it always reflects live history — which is a feature
  here: `MAX(version)` stays answerable however far back the log has been
  trimmed, so a check built on it can be exempted from retention gating that the
  pinned reads need.

### Unity Catalog reads — governed by neither clock

- **Table present, table registered, schema present, PK/FK constraints, table
  tags, column tags.** These live in the metastore, not in Delta at all — which
  is exactly why a deep clone can be byte-perfect on data and still lose every
  one of them.
- **The trap is not retention, it's liveness.** No `VERSION AS OF` exists for any
  of them, so pairing one against a version-pinned counterpart silently compares
  *now* on one side against *then* on the other. Either compare live-to-live, or
  accept the check answers a different question than the pinned ones do.

### The design consequences that fell out of this

- **Gate each check on the clock that actually governs it.** Applying the
  7-day data-file gate to all twelve checks, when only two touch data files,
  discarded roughly 20,000 valid log-sourced measurements per run. The gate's
  blast radius should match its cause — and working out the mechanism per check
  is what tells you the radius.
- **Reach for the log before reaching for the data.** Several checks were moved
  off convenient SQL (`DESCRIBE DETAIL`, `SHOW TBLPROPERTIES`) onto direct log
  reads specifically to gain time-travel and 30-day durability. The SQL surface
  is friendlier; the log is more capable.
- **Splitting checks by store also splits them by cost, which is what makes
  tiering possible.** Log-only checks are latency-bound — thousands of small
  reads, wanting concurrency. Data-file checks are shuffle-bound, wanting cores
  per table. Those want opposite cluster shapes, and separating them let each
  get one.

## Reading past Unity Catalog: masked tables, path reads, and the non-UC split

- **Row filters and column masks block validation in two independent ways, and
  both surprise you separately.** On a UC-governed session, a masked or
  row-filtered table refuses a **path-based** read
  (`PERMISSION_DENIED: Path-based access … row filter or column mask not
  supported`) *and* refuses **time travel by name**
  (`COLUMN_MASKS_FEATURE_NOT_SUPPORTED.TIME_TRAVEL`). Fixing one does nothing
  for the other, so it reads like two unrelated defects.
- **The common cause is the session, not the syntax — and that is the whole
  insight.** Both refusals come from **UC's own session-level analyzer**, which
  fires while resolving the read through UC's catalog metadata. So the fix is
  not a different query shape; it is a session that never consults UC in the
  first place.
- **Therefore: switching to a `delta.\`<path>\`` read is necessary but NOT
  sufficient.** A path read from a UC-governed cluster is exactly what the first
  error blocks — UC maps the path back to the table it governs and refuses.
- **It is ONE decision with two consequences, not three ingredients.** The
  decision is to make the session **non-UC**; the rest follows:
  - **The decision** — `data_security_mode: NONE`. Note this *is* what "non-UC
    cluster" means; it is not something you switch on top of a UC-enabled
    cluster. `SINGLE_USER` and `USER_ISOLATION` are the UC-enabled values, and
    on either of them UC's analyzer is in the session and both blocks fire.
    **There is no configuration that keeps UC enabled and skips its masking
    checks** — that would be a governance hole, not a feature.
  - **Consequence 1** — UC no longer brokers storage access, so the cluster must
    carry its own credential (direct SP OAuth on the storage account).
  - **Consequence 2** — there is no catalog to resolve a name against, so the
    read *must* be expressed by path. Path syntax is the result of going
    non-UC, not the thing that defeats the mask.
  Confirmed empirically against a real masked table with a live `VERSION AS OF`
  read on a `data_security_mode: NONE` cluster.
- **Corollary worth remembering when someone proposes a middle ground:** setting
  `fs.azure.account.*` credentials on a UC-enabled cluster and reading by path
  does not work, and in shared/`USER_ISOLATION` mode those confs are generally
  refused outright. The governance mode is binary for this purpose.
- **The payoff is correctness, not just access.** Because the non-UC session can
  time-travel a masked table, *every* table gets compared at its real pinned
  version — no live-version fallback for the masked subset. That removes an
  entire class of "we compared now against then" error precisely where the
  temptation to fall back would have been strongest.
- **Bringing your own credential means SP OAuth per storage account.** Without
  UC brokering access you set `fs.azure.account.auth.type`,
  `…oauth.provider.type`, `…oauth2.client.id`, `…client.secret` and
  `…client.endpoint` for each account host. Practical consequences: the secret
  is read from a scope at run time and lives in Spark conf on that cluster, and
  the set of accounts has to be known up front.
- **You lose everything UC knows, which forces an architectural split.** Tags,
  PK/FK constraints, `information_schema`, registration — none of it is
  reachable from a non-UC session. So the suite could not simply move to non-UC
  wholesale; it had to **split the checks across two clusters** by which store
  answers them. That split is the real design consequence of the workaround.
- **The reusable shape: a UC "prep" task that resolves everything, then a non-UC
  executor that consumes plain values.** The prep task runs on UC compute,
  resolves external-location names and config lookups, and publishes plain
  strings as task values; the non-UC task receives them pre-resolved and never
  needs a catalog. Anything the executor would have had to *look up* becomes
  something it is *handed*.
- **Cross-region reads need the path approach regardless of masking.** The other
  region's tables are not registered in this workspace's metastore, so there is
  no name to read them by — path is the only option. Masking and cross-region
  are two independent reasons that happen to want the same mechanism.

### Performance and other implications of path reads

- **Speed is not the reason to do this, and expecting a speedup is the wrong
  model.** The dominant costs are unchanged: shuffle for a full comparison,
  per-table latency for metadata. The access path is not where the time goes.
  Choose it for *capability*.
- **Two genuine secondary savings, though.** Mask and row-filter evaluation is
  real per-query CPU that raw file reads skip entirely — meaningful on a
  full-table scan. And there is no UC credential vending or permission
  resolution per query, which is small individually but non-trivial across
  thousands of tiny metadata reads.
- **Direct `_delta_log` access is the underrated one.** On a non-UC session the
  log is just files: list the directory, read the checkpoint Parquet and commit
  JSONs. That is what makes log-replay checks (file counts, sizes, properties at
  a pinned version) possible at all.
- **Serverless is off the table.** Serverless is UC-only, so going non-UC forces
  classic compute — cluster startup on every run, and nodes held for the task's
  duration. That is a real, recurring cost of the workaround.
- **The reads become invisible to governance tooling.** Path reads from a non-UC
  cluster do not appear in UC audit or lineage. Worth stating out loud when the
  job doing them is itself compliance-adjacent.
- **You are reading unmasked data, and that must be a deliberate, authorised
  decision.** The mask exists for a reason and this bypasses it. What made it
  defensible here: it runs as a service principal with storage-level RBAC, and
  the checks emit *structure and counts*, never row values. A check that sampled
  and reported rows would be exfiltrating exactly what the mask protects — so
  when adding checks to a non-UC path, audit what they *output*, not just what
  they read.

## Cloud capacity: quota, VM generations, and spot

- **Azure vCPU quota is per VM *family*, per region, per subscription — not per
  pool, per cluster, or per workload.** Names like `standardESv5Family`,
  `standardDDSv5Family`, `standardDSv5Family` are the actual buckets, and an
  `AZURE_QUOTA_EXCEEDED_EXCEPTION` names the one you exhausted. The practical
  consequence is unintuitive: **changing node size can change which quota you
  draw from**, so a "smaller, cheaper" node may succeed where a larger one
  failed purely because it lands in a different, emptier bucket. Spreading a
  fleet across families is a legitimate capacity strategy.
- **Compute peak concurrent vCPU before shipping a fan-out, and do it as a
  sum.** Every chunk of a parallel fan-out is its own cluster, and independent
  tiers run *at the same time*, so peak = Σ over all chunks of
  (workers + 1 driver) × cores-per-node. One job at concurrency 3 and 12 needed
  1,344 cores of one family against a limit of 350 — a 4× overrun that was
  entirely predictable from the YAML, and wasn't predicted because nobody did
  the arithmetic.
- **Spot draws from a *separate* quota, and it can be far larger.** In the same
  region and subscription: 350 cores for the on-demand family, **10,000** for
  `Total Regional Spot vCPUs`. The spot pool was the *same VM* as the on-demand
  one. So when a per-family limit blocks you, moving to spot is not a downgrade
  in hardware at all — it's a change of accounting bucket, and it may be the
  only way to keep your intended concurrency while a quota increase is pending.
- **Quota is not capacity.** Having headroom in the limit says nothing about
  whether the provider has spare VMs of that SKU in that region right now,
  which matters most for spot. Treat "quota available" and "allocation will
  succeed" as two separate questions.
- **A pool with no `max_capacity` cannot be a contention point.** If pools are
  uncapped, two clusters sharing one pool draw exactly the same VMs from
  exactly the same quota as two clusters on two pools — splitting them to
  "avoid contention" buys nothing. Scarcity lives at the quota layer, not the
  pool layer. Worth checking `max_capacity` and `min_idle_instances` before
  designing around imagined pool contention.
- **VM *generation* can be a compliance gate, independent of everything else.**
  One region enforced a standard requiring Azure VNet encryption, which only
  v4/v5 SKUs support: `INVALID_PARAMETER_VALUE … must use instances that
  support Azure Virtual Network encryption`. That is a property of the VM
  generation alone — orthogonal to spot vs on-demand, to size, and to price. A
  region can therefore have pools that *exist* and are *quota-available* and
  still cannot start a single cluster.
- **Compliance rules shrink the usable inventory dramatically, and asymmetrically
  between regions.** Of 12 pools in the constrained region, 8 were v5 and
  startable; of those, 4 were on-demand. An "on-demand only, no spot" policy
  plus a v5-only compliance rule left exactly **four** usable pools, and only
  **two** of them memory-optimised — both drawing on the same 350-core family.
  Enumerate the intersection of all constraints early; the answer is often much
  smaller than the pool list suggests.
- **The same pool name can be different hardware in different regions.** One
  region's `ondemand_memory_optimised_32core_256gb` was E32s_v5, the other's
  E32s_v3; the 4-core standard pool was D4s_v5 in one and DS3_v2 in the other.
  Name-based resolution is what lets one config serve two regions, and it is
  also what hides the fact that the two regions are running different silicon.
- **Insufficient quota does not always fail loudly.** Sometimes you get a clean
  `AZURE_QUOTA_EXCEEDED_EXCEPTION`; sometimes the cluster simply sits pending
  and the fan-out waits on it indefinitely. The second is how a run silently
  becomes a two-day run. Loud failure is the good case.

## Infrastructure-as-code: deploy time vs run time

- **The single most expensive confusion: a bundle deploys the whole job
  definition to *every* target, so every cluster spec is validated in every
  region — including clusters for tasks that can never run there.** A comment
  reading "this task is SE-only, so the East constraint doesn't apply" was
  correct about runtime and wrong about deployment, and it blocked a prod
  deploy. **Runtime reachability and deploy-time validation are different
  properties.** Ask separately: will this task ever *execute* here, and will
  this spec ever be *validated* here.
- **Know exactly which checks happen at each stage.** Deploy time: does the
  resource name resolve, and does the spec satisfy any attached policy. Cluster
  start time: quota, compliance rules, actual capacity. A v3 pool that no
  region-local task uses will deploy perfectly and only fail if something
  eventually tries to start it — which makes it a latent trap rather than a
  visible one.
- **A cluster *policy* validates at deploy, and its allowlist can be
  fundamentally incompatible with your standards.** The single-node policy in
  one region allowed only **spot** pools. Combined with an "on-demand only"
  rule, no compliant configuration existed at all — the two requirements were
  mutually exclusive and no amount of pool-swapping would have satisfied both.
  When a policy blocks you, check whether the policy's allowlist and your own
  policy can *ever* both hold before searching for the pool that squares them.
- **A policy that requires a property does not impose it.** A single-node
  policy rejected a cluster that hadn't declared itself single-node — the spec
  had the policy attached and none of `num_workers: 0`, the `ResourceClass`
  tag, or the `cluster.profile` conf. "Single node via the policy" was the
  assumption; "single node *or rejected* by the policy" was the reality.
- **Dropping a policy is a legitimate fix when nothing mandates one.** Twelve of
  fourteen cluster profiles in the repo carried no policy and deployed fine, in
  the very apply that the one policed cluster failed — direct evidence the
  workspace didn't require policies. Matching the configuration that
  demonstrably works beats inferring what a policy wants from its error text.
- **Referencing anything that exists in only one workspace breaks the other's
  deploy.** A pool present in one region and absent in the other fails the
  lookup, and the error names the missing resource rather than the reasoning
  that introduced it.
- **A resource referenced only by a never-running task is a standing
  fragility.** Nobody in that region has any reason to keep it, and if it's
  cleaned up the deploy starts failing with an error unrelated to whatever
  change exposed it.
- **Deploying the same bundle twice with different config between runs is
  possible but leaves the repo correct for only one target at a time.** Any
  redeploy of the other region — a rollback, a hotfix, an automated pipeline
  run — then fails, and nothing in the repo records which region the committed
  state is currently aimed at. Prefer configuration that is valid everywhere;
  where you can't, make the asymmetry loud in the file itself.

## Validation / testing methodology

- **A binary pass/fail hides the difference between "wrong" and "couldn't
  tell."** A third verdict — NOT MEASURED — for permission errors, extractor
  bugs, and unsafe time-travel windows keeps "the clone lost data" distinct
  from "we weren't able to check," which otherwise collapse into the same
  alarming-looking failure count.
- **Comparing an evolving source against a frozen target is not a fair
  test**, no matter how good the comparator is — the fix has to happen at the
  measurement layer (pin both sides to the same version), not in how
  differences get reported afterward.
- **A retention/safety gate should be scoped to what it actually protects,
  not applied blanket.** Gating *all* checks on the data-file retention window
  when only two of twelve checks touch data files threw away ~20,000 valid
  measurements per run — the gate's blast radius should match its actual
  cause.
- **Guard against "confident wrong answer" more than against "crash."** A
  function that returns `0` or `{}` on an edge case it can't actually handle
  is worse than one that raises — the caller can route an exception to NOT
  MEASURED, but a silently-wrong zero looks exactly like a real, passing
  measurement.
- **A mode switch beats a parallel implementation.** Adding a second family of
  checks as an `inc=true/false` mode on the existing notebooks — rather than
  duplicating them — avoided copying ~1,800 lines of renderer and comparator
  logic that would then have drifted. The condition for this being safe is that
  the two modes are genuinely mutually exclusive; if both could run at once
  you'd be building a flag, not a mode.
- **Put the mode gate at the single point every path already passes through.**
  One four-line guard inside the function every check card is rendered by beat
  wrapping twenty-odd call sites, and it cannot be forgotten when a new card is
  added later. Finding that convergence point is usually the whole design.
- **Derive the output shape from one named set, never from a second list.**
  Column ordering, the extractor loop, and the written schema all deriving from
  a single `ACTIVE_CHECKS` list means a mode switch changes one line. An earlier
  version iterated a different dict for the column headers and would have
  emitted nine all-NaN columns that look exactly like measurements nobody took.
- **Prove the old path is unchanged; don't assert it.** After adding a mode
  switch, executing the registry cells from the *pre-change commit* and from
  HEAD and diffing the resulting check lists element-by-element turned "I only
  added an else branch" into evidence. Cheap to write, and it catches the
  reordering that a set comprehension or a dict-iteration change silently
  introduces.
- **Choose deliberately what a new mode does *not* fold in.** Excluding the
  long-running full diff from the incremental report was a design decision, not
  an omission: including it would have forced a dependency edge onto a task
  that runs for 22 hours and serialised a four-hour report behind it. Worth
  recording the reasoning next to the exclusion, or someone "fixes" it later.
- **Classify failures by side and by cause before drawing any conclusion from
  the count.** A recovered run showed 465 passes and **88 failures**, which read
  as a serious clone defect. Breaking them down changed the story completely:
  all 88 were **source-side** (three storage accounts, all in the source
  region), **zero** were row-count mismatches, and the causes were 52
  `FAILED_READ_FILE.DBR_FILE_NOT_EXIST` plus 35 `FileNotFoundException` 404s —
  i.e. source files vacuumed away between clone time and validation time. Not
  one of them said anything about the clone. **Forward rule:** a failure count
  is not a finding. Group by side, by error class, and by object before
  reporting — the grouping usually *is* the diagnosis, and an ungrouped count
  will send people to debug the wrong component.
- **An absolute threshold is an absolute answer to a relative question — and
  the obvious statistical fix has its own degenerate case.** A fixed 50 GB tier
  boundary was applied to an estate whose largest table was under 50 GB, so
  every table classified "small": the large-tier cluster started, found zero
  tables, and exited eight minutes later while the small tier ran past twelve
  hours. Switching to a population statistic is the right instinct, but the
  *median* was also degenerate here, because most tables reported zero size —
  the median of a zero-heavy population is zero, which routes the entire estate
  the other way. The mean over non-zero values was the workable choice.
  **Forward rule:** derive split points from the data, but inspect the
  distribution first — count the zeros and nulls before choosing a statistic,
  and keep a sanity check that raises when a computed threshold would put every
  item on one side.

## Job orchestration (Databricks Jobs)

- **A `for_each` repair must resolve to the same iteration count as the
  original run.** Change the `inputs:` array from 8 entries to 12 and every
  in-flight or historical run becomes **permanently unrepairable** — the
  scheduler can't map old iterations onto the new array. So: deploys that
  change pools, parameters or notebook code leave old runs repairable; deploys
  that change an `inputs:` array do not. Worth knowing before you promise
  someone a repair.
- **In a fan-out, the chunk divisor and the scheduled iteration count are two
  different numbers and both directions of mismatch matter.** Iterations >
  divisor is wasteful but safe — surplus iterations exit on the guard. Divisor
  > iterations is **silent data loss**: whole modulo groups get no runner at
  all, nothing fails, and the only trace is an absent output file. Reconcile
  row-level coverage before overwriting the scope file, not after.
- **The UI task-edit is a real escape hatch when redeploys are expensive.** You
  can repoint a task's cluster in the Jobs UI and repair the run immediately,
  without another deploy; the next IaC deploy reverts it. That converts "we get
  one deploy attempt" into "we get one deploy attempt plus a manual override,"
  which materially changes how much risk a change can carry.
- **Job parameters silently override task base parameters of the same name.**
  A job-level `max_parallel` beat every per-tier `base_parameter` of that name
  on every task, so per-tier tuning had no effect at all and looked like a
  stale deploy. Namespacing the job-level parameters (`default_max_parallel`,
  `scope_chunks`) fixed it. Check for name collisions between the two layers
  before concluding a value "isn't taking effect."
- **A default nobody runs with is a bug waiting to surface.** A concurrency
  default of 1 was survivable only because operators overrode it by hand every
  time; the first run that used the default would have been ~8× slower with no
  error. Defaults should be the value you actually want.
- **Serverless bills for the wall-clock you hold it, so the worst possible fit
  is a long-lived task that does no compute.** A live progress dashboard — sleep
  60s, list a few small files, one API call, render text — sat on serverless for
  **22h46m** on a single run, because it exits only once every sibling task is
  terminal. It performed no Spark work in that entire window and was billed at a
  rate meant for real query compute. Moving it to the cheapest classic
  single-node cluster cost about five minutes of startup, which is irrelevant
  against a 22-hour run. **Forward rule:** classify every task as
  compute-bound or wall-clock-bound before choosing its compute. Serverless is
  excellent for short bursty work and actively wrong for anything that mostly
  waits.
- **A cosmetic task must be structurally incapable of failing or delaying the
  run.** Two properties made that true for the dashboard, and both are
  counter-intuitive: **nothing depends on it** (so it can never block a
  successor), and it carries **no `timeout_seconds`** — because a Databricks
  task timeout marks the task Failed, and a failed task fails the whole run. A
  timeout on a monitoring task would mean a cosmetic component could kill a
  22-hour validation. It self-exits on its own internal limit instead, with
  success. **Forward rule:** for any observability or reporting sidecar, check
  both edges — can it block anything, and can it fail anything — and prefer an
  in-notebook self-exit over a platform timeout.
- **A task that watches the run it is part of must exclude itself.** The
  dashboard's exit condition was "all tasks terminal", which it can never
  observe — it is itself running whenever it asks. Without passing the task its
  own key so it can filter itself out, the condition is unsatisfiable and every
  run sits until the backstop limit. **Forward rule:** any self-referential
  monitoring loop needs an identity and a self-exclusion; if you find yourself
  wondering why a watcher always runs to its maximum duration, this is the first
  thing to check.

## Cross-region orchestration: one job triggering and awaiting another

- **A job in region A can fire and then await a job in region B, and the whole
  mechanism is just the REST API plus an Entra service principal.** There is no
  special "cross-workspace" feature to enable. Region A obtains an OAuth token
  for a service principal, then calls region B's ordinary Jobs API with it. Once
  you have the token, the remote workspace is just a hostname.
- **The auth flow is Azure AD machine-to-machine client credentials.** POST to
  `https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token` with
  `grant_type=client_credentials`, the SP's `client_id` and `client_secret`, and
  `scope={DATABRICKS_RESOURCE}/.default`. The response's `access_token` goes
  straight into `Authorization: Bearer …` against the target workspace.
- **`DATABRICKS_RESOURCE` is a fixed, well-known Azure constant** —
  `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d`, the AzureDatabricks first-party
  application ID. It is the same for every tenant and every workspace on earth,
  so it belongs in code as a constant, not in config. Worth committing to memory;
  it is the piece that looks like it must be environment-specific and isn't.
- **The full checklist to make the connection work**, in the order things fail:
  the **tenant ID**; a **service principal** (client ID + secret) that exists in
  the tenant *and* has been granted access **in the target workspace** — being
  registered in the tenant is not enough; the secret stored in a **secret scope
  in the calling workspace**; the **target workspace host**
  (`https://adb-<workspace-id>.<n>.azuredatabricks.net`); and the **target
  `job_id`**. Everything else is a normal API call.
- **`job_id` is workspace-scoped and is the fragile link.** It is a number that
  means nothing in the calling region, and it changes if the target job is ever
  recreated rather than updated — which in IaC terms means changing the resource
  key destroys and re-issues it. That single integer is the tightest coupling
  between the two regions; treat it as an interface.
- **Preflight with `GET /api/2.1/jobs/get` before `run-now`.** One extra call
  proves the job exists *and* the SP can see it, so a wrong ID or a missing
  grant surfaces as a clear error rather than an opaque failure buried in a
  `run-now` response. Two failure modes separated for the cost of one request.
- **`run-now` rejects any `job_parameters` key the target job does not
  declare.** That silently couples the two jobs' parameter lists: adding a
  parameter on the calling side and forwarding it breaks *every* run until the
  target is redeployed too. Deploy the callee first, always.
- **Serverless compute cannot make the call.** Serverless egress fails the
  cross-workspace trust check, so the triggering and waiting tasks must run on
  classic VNet compute. This is the kind of constraint that only appears at
  runtime and forces a cluster into a job that otherwise wanted none.
- **Derive which region you are in at runtime; do not configure it.** One IaC
  target deployed byte-identically to two physical workspaces, so a deploy-time
  "my region" value would be correct in one and wrong in the other. Detecting
  the executing workspace and firing the *opposite* one makes direction a
  derived property. Configured direction is a bug waiting for the second
  deployment.
- **Per-workspace names you assume are symmetric often aren't.** The two
  workspaces' Key Vault-backed secret scopes were named differently
  (`secret-kv101` vs `secret-kv01`) despite one bundle serving both — so the
  code carries *both* candidate scope names and selects once the region is
  known. Expect at least one such asymmetry per region pair.
- **Fire-and-exit, then wait in a separate task.** `run-now` returns as soon as
  the remote run is queued; the returned `run_id` is published as a task value
  and consumed downstream as `{{tasks.<trigger>.values.tgt_run_id}}`. Splitting
  trigger from wait is what lets other local work proceed in parallel with the
  remote run instead of blocking behind it.
- **You can wait on a single *task inside* the remote run, not just the whole
  run.** `GET /api/2.1/jobs/runs/get` returns a `tasks[]` array with per-task
  state, so you can release local work the moment the one upstream task you
  actually depend on finishes. That turned a full-run barrier into a precise
  synchronisation point and unlocked real parallelism — probably the single most
  useful thing in this section.
- **`life_cycle_state` and `result_state` are two different fields and you need
  both.** `TERMINATED` covers success and failure alike; `result_state` says
  which. And some terminal states (`SKIPPED`, `INTERNAL_ERROR`) arrive with no
  `result_state` at all, so treating its absence as "still running" produces a
  poll loop that never exits.
- **Be generous with a wait task's timeout, or make it unbounded.** A wait that
  times out marks the task failed and fails the whole run — so the timeout is
  not a safety net, it is an additional way to lose a good run. Sizing it at 48
  hours against a 22-hour job is the right shape of margin.
- **A cross-region trigger should fail loud, unlike a best-effort one.** If
  everything downstream is meaningless without the remote run, swallowing the
  error just moves the failure somewhere less diagnosable.

## Diagnosing infrastructure failures

- **Read the error's own numbers before theorising.** The quota failure stated
  Current Limit 350, Current Usage 320, Additional Required 160, Minimum New
  Limit 480 — enough to compute both the immediate fix and the real ask (~1,400
  for the full fan-out) without a single assumption. Cloud errors are often
  more quantitative than they look.
- **Ask for the number you actually need, not the minimum the error suggests.**
  480 would have unblocked one cluster and failed on the next. The error tells
  you what the *current* request needed, not what your workload needs.
- **Terminated-cluster history is free evidence.** A 30-day cluster list showed
  three successful spot clusters and two successful runs on the exact SKU that
  later hit quota — proving "spot works in this region" and "this SKU works in
  this region" as separate facts, without creating anything. When you can't run
  an experiment, look for one that already ran.
- **Decompose an unknown into the parts that are already proven.** "Will spot
  E32s_v5 work here" split into three: does the pool exist (yes), is the SKU
  compliant (yes, v5), does spot allocate in this region (yes, evidenced on
  another SKU). What remained unproven was only the *combination* — a far
  smaller risk than the original question, and small enough to accept with a
  retry as cover.
- **Identical round numbers across unrelated metrics are a smell.** Three
  different quota families all reading exactly "0 of 350" was the tell that the
  region filter was wrong — those were untouched defaults for a region nobody
  deploys to. Real usage is lumpy.
- **Check the filter before trusting the reading.** The above happened because
  an autocomplete matched **Austria** East instead of **Australia** East. Any
  console with a region, subscription, or environment selector will eventually
  hand you correct-looking numbers for the wrong scope.
- **Verify you can perform the diagnostic action before you need it.** Cluster
  creation was denied, so the intended five-minute capacity smoke test was
  impossible — discovered mid-incident. Jobs create their own clusters as the
  run-as identity, so a human can lack a permission the pipeline has, and it
  only surfaces when you try to debug interactively.
- **A comment that encodes a *reason* is load-bearing, and a wrong one is worse
  than none.** "SE-only, so the East VNet constraint does not apply" was
  plausible, survived review, and blocked a prod deploy — because it forecloses
  the check it appears to have already done. When correcting one, record what
  was wrong and why, not just the new value.
- **Stale comments cause real regressions.** A note reading "parallelism is cut
  to 8 because East cannot offer a driver larger than 32 GB" was true for about
  a week. Anyone acting on it afterwards would have undone the fix that
  replaced it. Update the prose in the same commit as the value.
- **Know your recovery-source hierarchy before you need it — the friendliest
  artifact is often the lossy one.** When a 12-hour run was cancelled before
  writing any output, the results still existed in two places, and they were not
  equally good. **Notebook HTML exports were silently truncated**: 452 of 547
  results recovered, with a `*** WARNING` marker and visible gaps in the
  per-table counter — findable only because the output happened to be numbered.
  **Driver stdout was complete**: 171 + 169 + 213 = 553 results across three
  chunks, zero gaps. The polished, shareable artifact lost 17% of the data; the
  raw log lost none. **Forward rule:** when reconstructing from logs, prefer the
  rawest source available and *verify completeness independently* — a sequence
  counter or expected total in the output is what turns "looks complete" into
  "is complete". Design that counter in deliberately; it costs one integer and
  it is the only reason the truncation here was detectable at all.

## Command-line and scripting gotchas (Windows / Databricks CLI)

- **PowerShell's `` `v `` is a vertical-tab escape, not a literal "v".** So
  `"standard$tag`v$ver`Family"` silently produced `standardES3Family` instead of
  `standardESv3Family`. Use `${}` around every variable in an interpolated
  string: `"standard${tag}v${ver}Family"`.
- **Passing multi-line or quote-containing arguments to native executables from
  PowerShell is genuinely hostile.** Here-strings (`@'…'@`) need the terminator
  at column 0 and break inside `;`-chained commands; double quotes embedded in a
  single-quoted string still break argument boundaries when the call is
  reconstructed. For anything non-trivial, write the text to a file and pass the
  file (`git commit -F`), or use repeated single-line flags.
- **`Format-Table` truncates at console width and drops the right-hand columns
  with no indication.** Pipe through `Out-String -Width 4096` when the output
  matters.
- **The Databricks CLI emits a UTF-8 BOM when redirected to a file**, which
  makes `json.load` fail with "Unexpected UTF-8 BOM". Read with `utf-8-sig`.
- **Prefer one API call that already returns what you need.** `instance-pools
  list` includes each pool's `stats` block, so per-pool `get` calls to fetch
  instance counts are wasted round-trips. Check the list response's shape before
  fanning out.

## PySpark / pandas gotchas worth remembering on sight

- **`dict(a_spark_row)` doesn't do what it looks like.** `Row` supports
  iteration over its *values*, not `(key, value)` pairs, so `dict()`
  misreads it — use `.asDict()`.
- **`spark.read.json()` infers any nested JSON object as a STRUCT, never a
  true `MapType`**, even for a field that's logically `map<string,string>` —
  code that expects a dict has to normalize this explicitly regardless of
  source.
- **CSV round-trips between pandas and Spark need explicit escape
  handling.** `pandas.to_csv()` doubles embedded quotes (RFC 4180); Spark's
  reader defaults to backslash-escaping. Without `.option("escape", '"')`, a
  quoted value with an internal comma silently shifts every later column — no
  error, just corrupted rows.
- **`groupBy().agg(F.max(col))` doesn't guarantee other columns come from
  that same max row.** If you need several columns tied to "the latest row,"
  use a window function (`row_number() over partitionBy(...).orderBy(...
  desc())`) — an aggregate can silently mix values from different rows when
  there's more than one candidate.
- **Multi-statement `%sql` notebook cells only display the last statement's
  result.** Earlier statements still ran; their output is just not rendered —
  an easy thing to misread as "didn't execute."
- **Serverless/Spark Connect compute blocks reading certain Spark confs
  outright**, distinct from "the value isn't set." The error looks like a
  runtime failure but is really a compute-tier restriction.
- **Databricks notebooks compile each cell independently, so control flow
  cannot span cells.** An `if` opened in one cell does not indent the next —
  attempting it produces `unexpected indent` on every following cell, which
  reads as a dozen unrelated syntax errors rather than one structural mistake.
  This is what forced a mode switch to be implemented as a guard *inside* the
  single function every code path already passes through, rather than as an `if`
  wrapped around twenty-odd cells. **Forward rule:** in a notebook, conditional
  behaviour has to live inside a function or be repeated per cell — so when you
  need to gate a lot of code, first go looking for the one function everything
  funnels through. A related consequence: `from __future__ import annotations`
  in any cell but the first makes the whole file fail `py_compile` while
  remaining perfectly valid at runtime, so validate notebooks cell-by-cell
  (`ast.parse` per cell) rather than as one file.
- **A pandas CSV round-trip silently converts an integer column containing any
  blank into float.** A version column written as `836` comes back as `836.0`,
  and `"836.0" != "836"` fails every downstream string comparison — on every
  row, so it looks like a total mismatch rather than a formatting artifact. The
  blank is enough to do it: pandas has no integer dtype with missing values by
  default, so one NA promotes the whole column. **Forward rule:** normalise
  through `int(float(x))` at every read boundary, or use the nullable `Int64`
  dtype explicitly. Treat any CSV hop as lossy for numeric types, and be
  suspicious of a comparison that fails 100% rather than partially — that
  pattern is nearly always a type or format issue, not a data issue.
- **`~col.isin([...])` silently drops NULLs, because SQL's `NOT IN` is
  three-valued.** `NULL != 'X'` is NULL, not true, so rows with a null in the
  filtered column fail the predicate and vanish from scope — no error, no
  warning, just a smaller working set than intended. In a scope-building filter
  that is silent data loss at the very first step. **Forward rule:** whenever
  you write an exclusion filter, decide explicitly what NULL should mean, and
  count the nulls you are dropping. The implementation here counts them and
  prints a loud warning if any exist, so the rule can be made explicit the
  moment it actually matters rather than being inherited by accident from
  three-valued logic.
