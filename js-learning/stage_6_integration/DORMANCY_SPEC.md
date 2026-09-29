# DORMANCY_SPEC — general perception of absence, Tier 1

> **Status:** Tier 1 shipped 2026-09-11 and was wired to the hearth clock 2026-09-22 via the
> `check_commitments` job. Tier 2–3 remain deliberately gated until this instrument has a measured
> quiet-week run and a gold evaluation set shows that explicit checks miss real stalled commitments.
> **Requested by the user, verbatim:** *"JARVIS doesn't notice you stopped working on the finance
> thing unless something measures that — I want this general perception of absence."*
> **Parent:** `JARVIS_ENDGAME.md` §1.2. This is the sibling of `agent/tension.py`: that organ
> surfaces **contradiction** over your own history, this one surfaces **silence**.

---

## 0. Read this before designing anything

Two measurements were already run, and **both killed the obvious implementation.** Do not
re-derive them; do not build what they rule out.

**Measurement 1 — domain-level dormancy has no signal whatsoever.** Across 100 days and 607
captured turns, all six domains (`general`, `data-engineering`, `finance`, `jarvis-build`, `ai-ml`,
`unknown`) were last active **0–2 days ago**. A "this domain went quiet" detector would fire
**never**. Reproduce it:

```bash
python3 - <<'PY'
import json, collections, datetime as dt
IST = dt.timezone(dt.timedelta(hours=5, minutes=30)); now = dt.datetime.now(IST)
d = collections.defaultdict(list)
for l in open("jarvis_data/observation_queue.jsonl"):
    l = l.strip()
    if not l: continue
    r = json.loads(l); ts = r.get("ts")
    if ts: d[(r.get("heuristic_signals") or {}).get("domain_guess","unknown")].append(dt.datetime.fromisoformat(ts))
for k, v in sorted(d.items(), key=lambda kv: -len(kv[1])):
    print(f"{k:20} {len(v):5} turns   last seen {(now-max(v)).days}d ago")
PY
```

The lesson is about **granularity, not the idea**: you do not stop touching finance, you stop
touching one specific question inside it.

**Measurement 2 — keyword-matched "open loops" are mostly false positives.** Scanning the KB for
deferral language (`deferred`, `revisit`, `pending`, `still need`, `TODO`, `not yet`) matched ~70
entries, ~51 older than 30 days — which *looks* like rich signal until you read the rows. The top
hits include `"Decision: Skip Phase 1.4 … as standalone study"` and `"/next verdict: Sub-phase 2.4
COMPLETE"` — **closed** decisions that merely contain deferral vocabulary.

This is the **fourth** time open-vocabulary keyword matching has failed in this repo (see `nse`
matching inside "response" in `capture.py`, the SFT reason gate, and the Codex placeholder regex).
**Do not build the detector this way.** It will look like it works and quietly generate noise.

**What the measurements imply:** the signal is absence of **resolution**, not absence of
**activity** — and resolution state should be **recorded, not inferred.** That is the same move
that replaced `domain_guess` (a keyword hint) with `domain_labels.jsonl` (an explicit projection).

---

## 1. What Tier 1 is

**A commitment registry.** When a decision defers something, write the deferral *structurally*
instead of burying it in prose. Then detecting a stalled commitment is a boring scan with zero
inference and zero false positives.

The repo already does this informally, and those cases are machine-checkable **today**:

> Historical example: `4.6 GraphRAG ⏭ DEFERRED (trigger-gated: first KB-logged multi-hop retrieval failure)`.
> It was promoted to required on 2026-09-08; this is exactly the kind of recorded reversal the
> commitment registry must preserve rather than silently overwrite.

That is a real open loop with an explicit trigger condition. Tier 1 makes that shape first-class.

### Where it lives

`jarvis_data/commitments.jsonl` — append-only, `flock`ed, torn-line-healed (the two
non-negotiables in the canon), tracked in git.

**It is a thin structured INDEX, not a second mind.** This matters: the repo's storage taxonomy is
*one FACT, everything else derived*, and a second authored store is exactly the fork this project
has spent weeks instrumenting against. So the registry holds **only** the structured fields plus a
`kb_id` pointer; the reasoning stays in the `knowledge_base.jsonl` entry it references. No prose is
ever duplicated.

### Schema

```json
{
  "id": "c001",
  "opened": "2026-09-11T18:30:00+05:30",
  "kb_id": 588,
  "what": "one line: what was deferred",
  "resolves_when": "free text: the condition that closes this",
  "check": "optional shell command; exit 0 means RESOLVED",
  "review_after": "2026-12-01",
  "status": "open",
  "closed": null,
  "closed_by": null
}
```

**`check` is the important field.** Where a commitment has a machine-checkable predicate,
resolution is automatic and involves no judgment at all — run the command, exit 0 means done. For
the GraphRAG example that is a grep over the KB for a logged multi-hop retrieval failure. Where no
`check` exists, the commitment falls back to `review_after` plus human or LLM judgment, which is
Tier 2's job. **Prefer a `check` whenever one is expressible**; every commitment that has one is a
commitment that never needs an LLM.

`status` is `open` | `resolved` | `abandoned`. **`abandoned` is a first-class outcome**, not a
failure state — "we decided not to" is a real resolution and must be recordable, or the registry
slowly fills with things nobody will ever do and becomes the noise it was built to prevent.

---

## 2. Deliverables

1. **`scripts/commitments.py`** — organ + CLI, matching the shape of `scripts/agent_mail.py`:
   - `--open --what "…" --resolves-when "…" [--check "…"] [--review-after DATE] [--kb-id N]`
   - `--list [--status open|resolved|abandoned]`
   - `--due` — open commitments past `review_after`, **or** whose `check` now exits 0
   - `--close <id> [--abandoned] [--note "…"]`
   - `--self-test` — offline, temp dirs, never touches the real file
2. **A seed set, hand-picked, NOT keyword-scraped.** Measurement 2 is exactly why. Real open loops
   in the canon today, to be verified before entering:
   - `4.6 GraphRAG` — required after the always-reachable Context Ledger is verified; its prior
     trigger-gated form remains historical evidence of the reversal
   - The **Antigravity capture adapter** — blocked on `agents_converse/q_001.md`
     (`check`: does `a_001.md` exist?)
   - **Tier 2 / Tier 3 of this spec** — gated on Tier 1 proving insufficient
   - The **12-specialist roster** — demand-gated per `JARVIS_ENDGAME.md` §3, ten of twelve deferred
   - **The two exposed PATs** — user-only action, still outstanding
   - **Stage 5 itself** — not started; the open question is whether a trained adapter beats the
     retrieval path already built
3. **A `--due` report an agent can read at session start.** The hearth now runs the same command
   every six hours. Boot surfacing remains gated until the clock has demonstrated a quiet week
   without producing nonsense.

The scheduled command uses `--due --record-run --run-source scheduled` to append each scan's timestamp,
duration, return code, and due IDs to `jarvis_data/commitment_runs.jsonl`. Manual scans are marked
separately and cannot satisfy the quiet-week gate. `scripts/eval_dormancy.py` compares
the labelled Tier 1 snapshot with these run records. Aggregate hearth counters cannot reconstruct
past due IDs, so the quiet-week measurement starts with this log; earlier runs do not count as
auditable coverage. One positive case in the current gold set is not sufficient to claim broad
recall or unlock Tier 2.

**Definition of done:** `--due` returns **zero or a small number of genuinely stalled items** on a
registry seeded with real commitments. If it returns a long list, the seed set is wrong, not the
threshold.

---

## 3. Explicitly NOT in Tier 1

- **No detector, no LLM judge, no scanning of prose.** Tier 1 only reads what was deliberately
  written into the registry.
- **No auto-population from the KB.** That is Measurement 2's trap wearing a different hat.

## 4. Tier 2, when Tier 1 proves insufficient

Do not build this yet. First collect a quiet-week run from the scheduled Tier 1 organ and build the
gold set below. If explicit checks resolve or surface the real commitments, Tier 2 is unnecessary.
If it misses confirmed stalled items, mirror `agent/tension.py`'s architecture exactly — it is proven and it is in this repo:
candidates → LLM judge **with an abstention option** → confidence floor → append-only watermark so
nothing nags twice.

**Build the gold eval set FIRST**, as `scripts/eval_tension.py` did: labelled cases where a
positive *must* surface and a negative *must stay silent*. Without it you cannot distinguish a
working detector from a broken one — which is precisely how the previous volume-based detector
died, producing zero insights for months with nobody noticing.

## 5. Tier 3 — statistical dormancy over topic clusters

Only if 1–2 fall short. Measurement 1 says the data is bursty and coarse-grained, so this is
speculative. It would need finer clustering than `domain_guess` provides, and must clear the
anti-inductive test: a threshold whose satisfiability does **not** decay as the corpus grows.

---

## 6. The failure mode to design against

**Do not ship something that reports "you have 51 stale items."** Most of them are finished work.
A false-positive firehose trains the user to ignore the channel — and an ignored channel is
indistinguishable from a broken one, which is the exact failure this whole organ exists to prevent.

Silence is a valid and common output. Build for that.
