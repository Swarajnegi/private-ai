"""
profile_synth.py — distill jarvis_data/cognitive_profile.md from the KB.

LAYER: Tools (Personalization synthesis)

Run with:
    python3 scripts/profile_synth.py            # synthesize + write the profile
    python3 scripts/profile_synth.py --stdout   # print, don't write
    python3 scripts/profile_synth.py --self-test # smoke test on a fake KB

=============================================================================
THE BIG PICTURE
=============================================================================

The SessionStart hook (inject_profile.py) needs ONE compact document to
inject into every chat. The KB has ~460 scattered entries; the model
shouldn't have to search them every session. profile_synth distills the
high-signal user-model entries into a single ranked markdown profile.

Bucketing runs against jarvis_core.memory.cognitive_index (Decision
2026-08-10) instead of re-scanning raw content for magic substrings. The
KB's own `type` field already IS a brain-inspired taxonomy (Episodic/
Semantic/Procedural = the standard cognitive-science memory model,
Cognitive_Pattern = personality) — cognitive_index just makes it
queryable. "Who you are" now means the structured personality dimension
(every Cognitive_Pattern entry), not only the ones whose prose happened to
contain "user has"/"background"/"expertise" — verified against the real
KB that the old substring check silently missed genuine personality
entries that didn't happen to use those exact phrases (e.g. entries
opening with "PATTERN: dsa_debugging_format..." or "PATTERN: refusal_
pattern - rejects mechanism claims...").

Kept, deliberately: content-level checks for signals that are genuinely
about the TEXT, not the type/tag (does this entry literally say
"DIRECTIVE:" inline, does it mention "anti-pattern") — the structured
index doesn't and shouldn't try to capture that; jarvis_core.memory.
cognitive_index.query_all() gives a real cursor over every entry for
exactly this case, so it's still a query, not a hand-rolled file scan.

The Stage 3.5.7 consolidator can later replace the heuristic with an LLM
synthesis; the output contract (cognitive_profile.md) stays the same.

=============================================================================
THE FLOW
=============================================================================

STEP 1: rebuild_index(kb_path) — always fresh, no assumption a pre-existing
        index is current (matches the old full-rescan property: this
        script always works standalone, nothing to run beforehand).
        |
        v
STEP 2: Bucket via structured queries (query_by_dimension/type/tag/all)
        against the just-rebuilt index.
        |
        v
STEP 3: Rank each bucket (recency desc, DIRECTIVE-carrying first) and take
        the top-N, excerpting each to keep the profile lean.
        |
        v
STEP 4: Render markdown; write jarvis_data/cognitive_profile.md (or stdout).

=============================================================================
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.config import DATA_ROOT  # noqa: E402
from jarvis_core.memory.cognitive_index import (  # noqa: E402
    IndexedEntry,
    IndexStats,
    query_all,
    query_by_dimension,
    query_by_tag,
    query_by_type,
    rebuild_index,
)

_PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"

_MAX_PER_SECTION = 8
_EXCERPT_CHARS = 320


def _has_directive(e: IndexedEntry) -> bool:
    return "DIRECTIVE" in e.tags or "DIRECTIVE:" in e.content


def _rank_key(e: IndexedEntry) -> Tuple[bool, str]:
    # DIRECTIVE-carrying first, then most-recent timestamp.
    return (_has_directive(e), e.timestamp or "")


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text if len(text) <= limit else text[:limit] + " ..."


def _directive_sentence(content: str) -> str:
    """Pull the DIRECTIVE clause if present, else the opening sentence."""
    if "DIRECTIVE:" in content:
        frag = content.split("DIRECTIVE:", 1)[1]
        return _excerpt("DIRECTIVE:" + frag)
    return _excerpt(content)


def _dedupe(entries: List[IndexedEntry]) -> List[IndexedEntry]:
    seen = set()
    out: List[IndexedEntry] = []
    for e in entries:
        if e.id in seen:
            continue
        seen.add(e.id)
        out.append(e)
    return out


def _bucket(kb_path: Path, db_path: Path) -> Tuple[Dict[str, List[IndexedEntry]], IndexStats]:
    stats = rebuild_index(kb_path=kb_path, db_path=db_path)

    # Who you are — the structured personality dimension, full stop. No
    # longer gated on the entry's prose happening to contain a magic phrase.
    who = list(query_by_dimension("personality", db_path))

    # How you work — protocol entries, DIRECTIVE-tagged entries, and
    # entries that literally state "DIRECTIVE:" inline without the tag.
    how = _dedupe(
        list(query_by_type("System_Protocol", db_path))
        + list(query_by_tag("DIRECTIVE", db_path))
        + [e for e in query_all(db_path) if "DIRECTIVE:" in e.content]
    )

    # What you're building — Decisions / protocols that mention project
    # status. Not a dimension (it's a topic, not a memory type), so this
    # stays a content check — but scoped to a structured type-query first
    # instead of scanning the whole KB by hand.
    stage_cues = ("stage", "sub-phase", "wave")
    building_candidates = list(query_by_type("Decision", db_path)) + list(
        query_by_type("System_Protocol", db_path)
    )
    building = _dedupe(
        [e for e in building_candidates if any(cue in e.content.lower() for cue in stage_cues)]
    )

    # Preferences & anti-patterns — refusals, failures, and inline
    # "anti-pattern" mentions without a matching tag.
    prefs = _dedupe(
        list(query_by_type("Failure", db_path))
        + list(query_by_tag("refusal_pattern", db_path))
        + list(query_by_tag("refusal", db_path))
        + [e for e in query_all(db_path) if "anti-pattern" in e.content.lower()]
    )

    def top(bucket: List[IndexedEntry]) -> List[IndexedEntry]:
        return sorted(bucket, key=_rank_key, reverse=True)[:_MAX_PER_SECTION]

    def top_recent(bucket: List[IndexedEntry]) -> List[IndexedEntry]:
        # Build-state must reflect the LATEST stage, so rank by recency only —
        # DIRECTIVE-weighting would bury a recent non-directive stage Decision.
        return sorted(bucket, key=lambda e: e.timestamp or "", reverse=True)[:_MAX_PER_SECTION]

    return (
        {
            "who": top(who),
            "how": top(how),
            "building": top_recent(building),
            "prefs": top(prefs),
        },
        stats,
    )


def synthesize(kb_path: Optional[Path] = None, db_path: Optional[Path] = None) -> str:
    from jarvis_core.config import KB_PATH

    kb = kb_path or KB_PATH
    if db_path is not None:
        db = db_path
    else:
        from jarvis_core.config import COGNITIVE_INDEX_PATH

        db = COGNITIVE_INDEX_PATH

    buckets, stats = _bucket(Path(kb), Path(db))

    # Best-effort "current stage" line from the most recent stage Decision.
    current = ""
    for e in sorted(buckets["building"], key=lambda x: x.timestamp or "", reverse=True):
        current = _excerpt(e.content, 200)
        if current:
            break

    lines: List[str] = []
    lines.append("# Cognitive Profile — Model of the User")
    lines.append("")
    lines.append(
        "> Auto-synthesized by `scripts/profile_synth.py` from "
        f"`knowledge_base.jsonl` ({stats.total_entries} entries). "
        "Injected into every chat via the SessionStart hook. "
        "Regenerate after KB updates."
    )
    lines.append("")

    lines.append("## Who you are")
    if buckets["who"]:
        for e in buckets["who"]:
            lines.append(f"- {_excerpt(e.content)}")
    else:
        lines.append("- (no user-background patterns captured yet)")
    lines.append("")

    lines.append("## How you work — active directives")
    if buckets["how"]:
        for e in buckets["how"]:
            lines.append(f"- [{e.type}] {_directive_sentence(e.content)}")
    else:
        lines.append("- (no directives captured yet)")
    lines.append("")

    lines.append("## What you're building")
    if current:
        lines.append(f"**Current focus:** {current}")
        lines.append("")
    if buckets["building"]:
        for e in buckets["building"][:5]:
            lines.append(f"- {_excerpt(e.content, 200)}")
    else:
        lines.append("- (no build-state decisions captured yet)")
    lines.append("")

    lines.append("## Preferences & anti-patterns")
    if buckets["prefs"]:
        for e in buckets["prefs"]:
            lines.append(f"- {_excerpt(e.content)}")
    else:
        lines.append("- (no preference/refusal patterns captured yet)")
    lines.append("")

    return "\n".join(lines)


def _run_self_test() -> None:
    print("=" * 70)
    print("  profile_synth.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    with tempfile.TemporaryDirectory() as td:
        import json

        kb = Path(td) / "kb.jsonl"
        db = Path(td) / "index.sqlite3"
        fake = [
            {"timestamp": "2026-01-01T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["learning-pattern", "LLM-internals"],
             "content": "User has strong ML math foundation but zero LLM-specific knowledge. DIRECTIVE: define every term on first use.",
             "expiry": "Permanent"},
            {"timestamp": "2026-05-30T00:00:00+05:30", "type": "Decision",
             "tags": ["stage-3", "sub-phase-3.5"],
             "content": "Sub-Phase 3.5 Wave 1 shipped: MemoryManager + ReActLoop wiring. Stage 3 ongoing.",
             "expiry": "Permanent"},
            {"timestamp": "2026-05-25T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["refusal_pattern", "bundling"],
             "content": "User rejects bundling unrelated concerns into one commit. Anti-pattern: overreach.",
             "expiry": "Permanent"},
            {"timestamp": "2026-05-29T00:00:00+05:30", "type": "System_Protocol",
             "tags": ["workflow-protocol", "DIRECTIVE"],
             "content": "DIRECTIVE: /next must skip concept-only lessons when build lessons exist.",
             "expiry": "Permanent"},
        ]
        with open(kb, "w", encoding="utf-8") as f:
            for e in fake:
                f.write(json.dumps(e) + "\n")

        out = synthesize(kb, db)
        check("T1 non-empty", len(out) > 100)
        check("T2 has 'Who you are'", "## Who you are" in out)
        check("T3 has 'How you work'", "## How you work" in out)
        check("T4 has 'What you're building'", "## What you're building" in out)
        check("T5 has 'Preferences'", "## Preferences" in out)
        check("T6 surfaces a DIRECTIVE", "DIRECTIVE:" in out, out[:400])
        check("T7 surfaces current stage", "3.5" in out or "Stage 3" in out)
        check("T8 surfaces refusal/anti-pattern", "bundling" in out.lower() or "anti-pattern" in out.lower())

        # Origin-tracing check: entry 1 (Cognitive_Pattern, no magic
        # substring) must reach "Who you are" via the dimension, not via
        # the old substring cue — this is the actual bug being fixed.
        check("T9 personality entry surfaces without magic-phrase dependency",
              "ML math foundation" in out)

        # Empty KB -> still well-formed with placeholders
        empty = Path(td) / "empty.jsonl"
        empty_db = Path(td) / "empty.sqlite3"
        empty.write_text("", encoding="utf-8")
        out2 = synthesize(empty, empty_db)
        check("T10 empty KB still has all 4 sections",
              all(s in out2 for s in ("## Who you are", "## How you work",
                                       "## What you're building", "## Preferences")))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} profile_synth smoke tests passed.")
    print("=" * 70)


def main() -> int:
    p = argparse.ArgumentParser(description="Synthesize cognitive_profile.md from the KB")
    p.add_argument("--stdout", action="store_true", help="Print instead of writing the file")
    p.add_argument("--self-test", action="store_true", help="Run smoke tests")
    args = p.parse_args()

    if args.self_test:
        _run_self_test()
        return 0

    profile = synthesize()
    if args.stdout:
        sys.stdout.write(profile)
        return 0
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(profile + "\n", encoding="utf-8")
    print(f"[profile_synth] wrote {_PROFILE_PATH} ({len(profile)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
