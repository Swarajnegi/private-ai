#!/usr/bin/env python3
"""
reconcile_codex_memory.py — promote Codex's own memory into the one authoritative mind.

LAYER: Tools (thin adapter — arbitration lives in scripts/kb_append.py's dedup gate)

Run with:
    python3 scripts/reconcile_codex_memory.py --dry-run   # candidates found, nothing written
    python3 scripts/reconcile_codex_memory.py              # promote into knowledge_base.jsonl

=============================================================================
THE BIG PICTURE
=============================================================================

The user's decision (2026-09-10): keep Codex's native `memories` feature ON —
the Codex models in use have a far smaller context window than Claude Code's,
so a fast per-session cache is a real cost saver — while
`knowledge_base.jsonl` stays the ONE authoritative mind. They
asked for a layer that decides which of the two lines (Codex's or the KB's)
gets kept.

THAT LAYER ALREADY EXISTS AND IS FREE. `scripts/kb_append.py`'s embedding
dedup gate refuses any candidate whose content is >0.85 similar to an existing
entry. That is exactly "decide whether the Codex line or the KB line should be
stored" — mechanically, deterministically, and it was built for a different
reason (preventing the model from re-writing the same insight twice) but does
precisely this job. This script does NOT reimplement arbitration; it converts
Codex's memory files into KB-shaped candidates and lets kb_append.py's
existing gate decide. Per this repo's own rule (KB 528/569 family): add the
instrument before the feature — an LLM judge for the 0.70-0.85 similarity band
is deferred until measurement shows the embedding gate alone is insufficient.

WHY ONE-WAY (Codex -> KB), NEVER THE REVERSE. The reverse direction needs no
code: Codex reads `cognitive_profile.md` via `AGENTS.md`'s SESSION BOOT
section on every session start, the same pattern proven for Antigravity. A
two-way sync would risk exactly the fork this project has spent this week
instrumenting against (KB 548's storage taxonomy: one FACT, everything else a
derived PROJECTION). `knowledge_base.jsonl` is the FACT. Codex's memory is a
fast, session-scoped PROJECTION of it that periodically donates new signal
back in — never a second FACT to reconcile against.

WHY THE FILTER MATTERS: `~/.codex/memories/` IS GLOBAL, NOT PER-PROJECT.
Verified in `~/.codex/config.toml` — `[memories]` has no per-project scoping,
and Codex is used for more than this one repo. Without a JARVIS-relevance
filter, another project's memory would leak into this KB the first time this
script runs on a machine where Codex has done unrelated work. The filter here
is conservative (path/keyword match) rather than an LLM call, on purpose:
a filter that runs before spending a model call is the cheap, first line of
defense, and the KB's own dedup is the second.

WHICH FILES ARE ACTUALLY READ: `raw_memories.md` and `MEMORY.md`, and only
those two. `memory_summary.md` exists in the same directory and is NOT read —
it is Codex's own rolled-up summary OF the other two, so ingesting it as well
would promote the same content twice under two headings, and the KB's dedup
gate would then have to clean up a mess this script never needed to make.
(Named here because an earlier version of this note listed all three as
though all three were parsed.)

HONESTY NOTE, stated because it matters for trusting this file's own tests:
the memory files on THIS machine are all still template placeholders — "No durable user profile
information has been observed yet.", "No raw memories yet." — because the
`memories` feature was only just turned on and Codex has done almost no work
here. **There is no real populated example to build or verify a parser
against.** The parser below is built structurally (split on markdown
headings, treat template placeholder lines as empty) and tested against
SYNTHETIC content shaped like the real template's own headings — it has not
been run against genuine Codex-generated memory prose, because none exists
yet. Re-verify against real content the first time this file actually has
something in it.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read raw_memories.md and MEMORY.md; split each into candidate blocks
        on markdown heading boundaries.
        |
STEP 2: Drop template placeholders ("no ... observed yet", "no ... yet") and
        anything under _MIN_CANDIDATE_CHARS — there is nothing to promote from
        an empty section heading.
        |
STEP 3: Filter to JARVIS-relevant candidates (keyword/path match against this
        repo's own vocabulary) — memories is a GLOBAL store, not per-project.
        |
STEP 4: Promote each survivor via scripts/kb_append.py as a Cognitive_Pattern,
        tagged so its origin is traceable and never mistaken for something the
        user wrote directly. kb_append's own >0.85 dedup gate is the
        arbitration layer between "Codex already knew this" and "the KB
        already knows this" — whichever was appended first wins, silently and
        correctly, because they are the same fact either way.
        |
STEP 5: Report counts. A run over an untouched/empty memory store reporting
        ZERO candidates is the CORRECT result today — never padded.
=============================================================================
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from kb_append import append_entry  # noqa: E402

CODEX_MEMORY_DIR = Path.home() / ".codex" / "memories"
RAW_MEMORIES_PATH = CODEX_MEMORY_DIR / "raw_memories.md"
MEMORY_HANDBOOK_PATH = CODEX_MEMORY_DIR / "MEMORY.md"

_MIN_CANDIDATE_CHARS = 80

# Codex's own template code emits these EXACT sentences (byte for byte, minus
# leading "- " bullets) when a memory section is empty. Verified against the
# real, currently-unpopulated files on this machine.
#
# THIS WAS FIRST A HAND-WRITTEN REGEX APPROXIMATING THE GRAMMAR, AND IT WAS
# WRONG despite having every one of these exact strings already quoted in this
# file's own header — "no X (are|is)? (available|observed|recorded)? yet"
# does not match "has been observed yet" or "have been observed yet", so it
# missed 2 of the 5 known placeholders on its own self-test (caught 2026-09-10).
# That is the SAME mistake as matching an open vocabulary with keywords
# (capture.py's `nse`-in-"response", the SFT reason-gate) applied backwards:
# here the vocabulary is NOT open, it's a small fixed set of literal strings a
# specific piece of template code emits — so the fix is to match those strings
# literally, not to write a cleverer regex for a grammar that doesn't need one.
_KNOWN_PLACEHOLDERS = frozenset({
    "no durable user profile information has been observed yet.",
    "no reusable preferences have been observed yet.",
    "no validated cross-task guidance has been recorded yet.",
    "no consolidated task groups yet.",
    "no raw memories yet.",
    "no consolidated rollout memories are available yet.",
})

# Conservative relevance filter. ~/.codex/memories/ is GLOBAL — Codex is used
# for more than this repo — so a candidate must name something JARVIS-specific
# before it is eligible to enter this project's KB at all.
_JARVIS_MARKERS = re.compile(
    r"\bjarvis\b|knowledge_base\.jsonl|cognitive_profile|observation_queue|"
    r"jarvis_core|jarvis_data|js-development|js-learning|\.agent/rules|"
    r"hearth\.py|the hearth\b", re.IGNORECASE)


@dataclass(frozen=True)
class MemoryCandidate:
    heading: str
    text: str
    source_file: str


def _split_markdown_sections(text: str) -> Iterator[tuple]:
    """(heading, body) for each markdown section, any heading level.

    Deliberately simpler than build_sft_pairs.py's `_split_md_sections`: that
    one needs a fixed heading LEVEL to tell a lesson from its sub-structure.
    This just needs "one block of prose per heading, whatever level it is",
    because a memory file's structure is unverified and a rigid level
    assumption would silently drop real content shaped differently than the
    one empty template on this machine.
    """
    lines = text.splitlines()
    heading: Optional[str] = None
    body: List[str] = []
    for line in lines:
        if line.strip().startswith("#"):
            if heading is not None:
                yield heading, "\n".join(body).strip()
            heading = line.strip().lstrip("#").strip()
            body = []
        elif heading is not None:
            body.append(line)
        # Content before the first heading (e.g. MEMORY.md's lone paragraph
        # with no heading at all) is handled by the caller via a synthetic
        # leading heading — see extract_candidates.
    if heading is not None:
        yield heading, "\n".join(body).strip()


def _is_placeholder(text: str) -> bool:
    """True when a section body is empty or IS EXACTLY one of Codex's own
    template placeholder sentences — never real signal, regardless of length.

    Exact match only, deliberately: MEMORY.md's real handbook sentence is
    "No consolidated rollout memories are available yet. Add task-group
    blocks after..." — the known placeholder PLUS real trailing prose. That
    must NOT be caught here (it is not purely a placeholder), and it isn't —
    it survives to is_jarvis_relevant() instead, which is the second, broader
    layer that filters it out for a different, equally valid reason (it names
    nothing JARVIS-specific). Two independent gates catching the same case for
    different reasons is a feature, not redundancy — see this module's tests.
    """
    stripped = re.sub(r"\s+", " ", text.strip().lstrip("-*").strip()).lower()
    if not stripped:
        return True
    return stripped in _KNOWN_PLACEHOLDERS


def extract_candidates(path: Path) -> List[MemoryCandidate]:
    """Every non-placeholder section in one memory file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return []
    out: List[MemoryCandidate] = []
    # A file with prose before its first heading (MEMORY.md's own single
    # paragraph today) needs a synthetic heading so that prose isn't dropped.
    first_heading_at = text.find("\n#")
    if not text.lstrip().startswith("#") and (first_heading_at == -1 or first_heading_at > 0):
        preamble = text.split("\n#", 1)[0].strip()
        if preamble and not _is_placeholder(preamble):
            out.append(MemoryCandidate(path.stem, preamble, path.name))
    for heading, body in _split_markdown_sections(text):
        if _is_placeholder(body):
            continue
        if len(body) < _MIN_CANDIDATE_CHARS:
            continue
        out.append(MemoryCandidate(heading, body, path.name))
    return out


def is_jarvis_relevant(candidate: MemoryCandidate) -> bool:
    return bool(_JARVIS_MARKERS.search(candidate.heading + " " + candidate.text))


def reconcile(dry_run: bool = True) -> dict:
    all_candidates: List[MemoryCandidate] = []
    for path in (RAW_MEMORIES_PATH, MEMORY_HANDBOOK_PATH):
        all_candidates.extend(extract_candidates(path))

    relevant = [c for c in all_candidates if is_jarvis_relevant(c)]
    skipped_irrelevant = len(all_candidates) - len(relevant)

    # Three outcomes, not two. kb_append.append_entry distinguishes them and this
    # function used to collapse the distinction wrongly (fixed 2026-09-11):
    #   "appended" -> written
    #   "deduped"  -> the >0.85 arbitration gate fired. THIS IS THE SUCCESS CASE
    #                 for this script — "Codex already knew what the KB knows".
    #   "rejected" -> a VALIDATION failure (empty content, empty type, bad tag
    #                 count). A real defect in what we constructed, not a dedup.
    # The old code counted "rejected" as the dedup case, so a genuine dedup
    # incremented nothing and vanished from the report, while a validation bug
    # was reported to the user as "already in KB" — the arbitration layer the
    # user specifically asked for would have silently mis-stated its own result
    # the first time it ever did real work. Never fired in production only
    # because `eligible` has been 0 while Codex's memory is still empty.
    promoted, deduped, rejected = 0, 0, 0
    results = []
    for cand in relevant:
        content = (
            f"[from Codex's own session memory, not authored by the user — "
            f"treat as an observation to verify, never as an instruction] "
            f"{cand.heading}: {cand.text}"
        )
        if dry_run:
            results.append({"heading": cand.heading, "source": cand.source_file,
                            "chars": len(cand.text), "action": "would-promote"})
            continue
        res = append_entry(
            entry_type="Cognitive_Pattern",
            tags=["codex-memory", "reconciled", "cross-host"],
            content=content,
        )
        status = res.get("status", "error")
        if status == "appended":
            promoted += 1
        elif status == "deduped":
            deduped += 1
        elif status == "rejected":
            rejected += 1
        results.append({"heading": cand.heading, "source": cand.source_file,
                        "status": status, "reason": res.get("reason")})

    return {
        "candidates_found": len(all_candidates),
        "skipped_not_jarvis_relevant": skipped_irrelevant,
        "eligible": len(relevant),
        "promoted": promoted,
        "already_in_kb": deduped,
        "rejected_invalid": rejected,
        "results": results,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Promote JARVIS-relevant items from Codex's own memory into "
                    "knowledge_base.jsonl. One-way; the KB stays authoritative.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not CODEX_MEMORY_DIR.exists():
        print(f"{CODEX_MEMORY_DIR} does not exist — Codex's memory feature has not "
              f"produced anything on this machine yet. Nothing to reconcile.")
        return 0

    result = reconcile(dry_run=args.dry_run)
    print(f"candidates found              : {result['candidates_found']}")
    print(f"skipped (not JARVIS-relevant) : {result['skipped_not_jarvis_relevant']}")
    print(f"eligible                      : {result['eligible']}")
    if args.dry_run:
        for r in result["results"]:
            print(f"  [would promote] {r['source']}#{r['heading'][:50]!r} "
                  f"({r['chars']} chars)")
    else:
        print(f"promoted to KB                : {result['promoted']}")
        print(f"already in KB (dedup gate)    : {result['already_in_kb']}")
        if result["rejected_invalid"]:
            print(f"REJECTED as invalid           : {result['rejected_invalid']}"
                  f"  <- a defect in what this script built, NOT a dedup")
            for r in result["results"]:
                if r.get("status") == "rejected":
                    print(f"    {r['heading'][:48]!r}: {r.get('reason')}")
    if result["candidates_found"] == 0:
        print("\n0 candidates is the CORRECT result while Codex's memory is still "
              "template-empty on this machine — not padded, not an error.")
    return 0


# =============================================================================
# SMOKE TESTS (offline — synthetic content; see the header's HONESTY NOTE:
# no genuinely Codex-populated memory file exists yet to test against for real)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  reconcile_codex_memory.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    # --- _is_placeholder, against the REAL template sentences on this machine ---
    check("T1 recognises the real 'no user profile' placeholder",
          _is_placeholder("No durable user profile information has been observed yet."))
    check("T2 recognises the real 'no preferences' placeholder (bulleted)",
          _is_placeholder("- No reusable preferences have been observed yet."))
    check("T3 recognises the real 'no raw memories' placeholder",
          _is_placeholder("No raw memories yet."))
    check("T4 empty/whitespace-only body is a placeholder",
          _is_placeholder("   \n  "))
    check("T5 real prose is NOT a placeholder",
          not _is_placeholder("The user prefers short, direct answers with no hedging."))

    # --- _split_markdown_sections, against the REAL template structure ---
    real_shape = (
        "v1\n\n## User Profile\n\nNo durable user profile information has been "
        "observed yet.\n\n## User preferences\n\n- No reusable preferences have "
        "been observed yet.\n"
    )
    sections = list(_split_markdown_sections(real_shape))
    check("T6 splits the real memory_summary.md template into its own sections",
          [h for h, _ in sections] == ["User Profile", "User preferences"],
          str([h for h, _ in sections]))

    # --- is_jarvis_relevant ---
    jarvis_cand = MemoryCandidate("Build notes", "The tension detector in jarvis_core "
                                  "needed windowed retrieval.", "raw_memories.md")
    other_cand = MemoryCandidate("Cooking", "The user prefers medium-rare steak.",
                                 "raw_memories.md")
    check("T7 a JARVIS-specific candidate is relevant", is_jarvis_relevant(jarvis_cand))
    check("T8 an unrelated-project candidate is NOT relevant "
          "(memories is GLOBAL, not per-project)", not is_jarvis_relevant(other_cand))

    with tempfile.TemporaryDirectory() as td:
        # --- T9-T13: extract_candidates end to end, SYNTHETIC content shaped
        # like the real template but with real sections filled in — there is
        # no genuine filled example on this machine to test against instead.
        raw = Path(td) / "raw_memories.md"
        raw.write_text(
            "# Raw Memories\n\n"
            "## 2026-09-10 jarvis-build session\n\n"
            "The user is migrating JARVIS development to Codex and wants the "
            "cognitive_profile.md read at every session start, per AGENTS.md.\n\n"
            "## unrelated finance chat\n\n"
            "The user asked several detailed questions about mutual fund SIP "
            "timing and portfolio rebalancing strategy for a completely "
            "different, unrelated personal finance project with no connection "
            "to any of this codebase whatsoever.\n",
            encoding="utf-8")
        handbook = Path(td) / "MEMORY.md"
        handbook.write_text(
            "# Agent Memory Handbook\n\n"
            "No consolidated rollout memories are available yet. Add task-group "
            "blocks after raw memories or rollout summaries provide reusable, "
            "evidence-backed signal.\n",
            encoding="utf-8")

        raw_candidates = extract_candidates(raw)
        check("T9 both real sections are extracted (both clear the length "
              "floor), the top-level '# Raw Memories' heading is not itself "
              "treated as a candidate",
              len(raw_candidates) == 2, str([c.heading for c in raw_candidates]))
        check("T10 JARVIS-relevant filter keeps the jarvis-build section",
              any("AGENTS.md" in c.text for c in raw_candidates
                  if is_jarvis_relevant(c)))
        check("T11 the unrelated finance section is extracted but filtered OUT "
              "by relevance, not silently promoted",
              any("mutual fund" in c.text for c in raw_candidates)
              and not any("mutual fund" in c.text for c in raw_candidates
                         if is_jarvis_relevant(c)))

        handbook_candidates = extract_candidates(handbook)
        check("T12 the handbook's own standing-instruction sentence is extracted "
              "(not a pure placeholder — fails the placeholder gate) but caught "
              "by the SECOND layer (relevance) instead — verified against the "
              "REAL template text on this machine",
              len(handbook_candidates) == 1
              and not is_jarvis_relevant(handbook_candidates[0]),
              str(handbook_candidates))

        check("T13 a missing file yields no candidates, not an error",
              extract_candidates(Path(td) / "nope.md") == [])

        # --- T14-T16: reconcile() dry-run vs real, against the synthetic pair ---
        import reconcile_codex_memory as mod
        orig_raw, orig_hb = mod.RAW_MEMORIES_PATH, mod.MEMORY_HANDBOOK_PATH
        mod.RAW_MEMORIES_PATH, mod.MEMORY_HANDBOOK_PATH = raw, handbook
        try:
            dry = mod.reconcile(dry_run=True)
            check("T14 dry-run finds 3 candidates total (2 from raw_memories, "
                  "1 the handbook's own sentence), exactly 1 eligible after "
                  "relevance filtering",
                  dry["candidates_found"] == 3 and dry["eligible"] == 1,
                  str(dry))

            captured_calls: List[dict] = []
            import kb_append as kb_mod
            orig_append = kb_mod.append_entry

            def fake_append(**kwargs):
                captured_calls.append(kwargs)
                return {"status": "appended", "id": 999}

            mod.append_entry = fake_append
            try:
                real = mod.reconcile(dry_run=False)
                check("T15 a real (non-dry) run promotes exactly the eligible "
                      "candidate, via kb_append's own entry point",
                      real["promoted"] == 1 and len(captured_calls) == 1,
                      str(real))
                check("T16 the promoted entry is tagged as Codex-sourced and "
                      "carries the untrusted/non-user-authored framing, never "
                      "presented as if the user wrote it directly",
                      captured_calls[0]["entry_type"] == "Cognitive_Pattern"
                      and "codex-memory" in captured_calls[0]["tags"]
                      and "not authored by the user" in captured_calls[0]["content"],
                      str(captured_calls[0])[:200])

                # T16b/T16c -- the three outcomes must be counted SEPARATELY.
                # The original suite only ever faked "appended", which is why a
                # real miswiring (dedup counted as `status == "rejected"`) sat
                # here undetected: the arbitration layer's own success case was
                # never once exercised by its own tests.
                mod.append_entry = lambda **kw: {"status": "deduped",
                                                 "reason": "semantic"}
                dd = mod.reconcile(dry_run=False)
                check("T16b a DEDUP is counted as already_in_kb (the arbitration "
                      "gate firing is this script's success case, not a loss)",
                      dd["already_in_kb"] == 1 and dd["promoted"] == 0
                      and dd["rejected_invalid"] == 0, str(dd))

                mod.append_entry = lambda **kw: {"status": "rejected",
                                                 "reason": "empty content"}
                rj = mod.reconcile(dry_run=False)
                check("T16c a VALIDATION rejection is NOT reported as a dedup — "
                      "it is a defect in what we built and must be visible",
                      rj["rejected_invalid"] == 1 and rj["already_in_kb"] == 0
                      and rj["promoted"] == 0, str(rj))
            finally:
                mod.append_entry = orig_append
        finally:
            mod.RAW_MEMORIES_PATH, mod.MEMORY_HANDBOOK_PATH = orig_raw, orig_hb

        # --- T17: the real files on THIS machine really are empty right now ---
        real_result = reconcile(dry_run=True)
        check("T17 the REAL Codex memory store on this machine yields 0 "
              "eligible candidates today (template-empty, as documented) — "
              "confirms this test suite is not masking a live-data dependency",
              real_result["eligible"] == 0, str(real_result))

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _run_self_test()
    else:
        raise SystemExit(main())
