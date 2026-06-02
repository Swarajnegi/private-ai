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
inject into every chat. The KB has ~300 scattered entries; the model
shouldn't have to search them every session. profile_synth distills the
high-signal user-model entries into a single ranked markdown profile.

Heuristic NOW (no LLM): selects Cognitive_Pattern / System_Protocol /
Decision / Failure entries, ranks by recency + whether they carry a
DIRECTIVE, and assembles four sections:
    - Who you are
    - How you work (active directives)
    - What you're building (current stage)
    - Preferences & anti-patterns

The Stage 3.5.7 consolidator can later replace the heuristic with an LLM
synthesis; the output contract (cognitive_profile.md) stays the same.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read all KB entries (jarvis_core.config.KB_PATH).
        |
        v
STEP 2: Bucket entries into the four sections by type + tags + content cues.
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
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.config import KB_PATH, DATA_ROOT  # noqa: E402

_PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"

_MAX_PER_SECTION = 8
_EXCERPT_CHARS = 320


def _read_kb(kb_path: Path) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not kb_path.exists():
        return entries
    with open(kb_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _has_directive(e: Dict[str, Any]) -> bool:
    tags = [t.lower() for t in e.get("tags", [])]
    return "directive" in tags or "DIRECTIVE:" in e.get("content", "")


def _rank_key(e: Dict[str, Any]):
    # DIRECTIVE-carrying first, then most-recent timestamp.
    return (_has_directive(e), e.get("timestamp", ""))


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text if len(text) <= limit else text[:limit] + " ..."


def _directive_sentence(content: str) -> str:
    """Pull the DIRECTIVE clause if present, else the opening sentence."""
    if "DIRECTIVE:" in content:
        frag = content.split("DIRECTIVE:", 1)[1]
        return _excerpt("DIRECTIVE:" + frag)
    return _excerpt(content)


def _bucket(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    who: List[Dict[str, Any]] = []
    how: List[Dict[str, Any]] = []
    building: List[Dict[str, Any]] = []
    prefs: List[Dict[str, Any]] = []

    for e in entries:
        etype = e.get("type", "")
        tags = [t.lower() for t in e.get("tags", [])]
        content_l = e.get("content", "").lower()

        # How you work — anything carrying an explicit directive or a protocol.
        if _has_directive(e) or etype == "System_Protocol":
            how.append(e)

        # Who you are — patterns describing the user's background/expertise.
        if etype == "Cognitive_Pattern" and any(
            cue in content_l for cue in ("user has", "user's", "background", "expertise", "mental model")
        ):
            who.append(e)

        # What you're building — Decisions / protocols mentioning a stage.
        if etype in ("Decision", "System_Protocol") and (
            "stage" in content_l or "sub-phase" in content_l or "wave" in content_l
        ):
            building.append(e)

        # Preferences & anti-patterns — refusals + failures + feedback.
        if (
            "refusal_pattern" in tags
            or "refusal" in tags
            or etype == "Failure"
            or "anti-pattern" in content_l
        ):
            prefs.append(e)

    def top(bucket: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(bucket, key=_rank_key, reverse=True)[:_MAX_PER_SECTION]

    def top_recent(bucket: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Build-state must reflect the LATEST stage, so rank by recency only —
        # DIRECTIVE-weighting would bury a recent non-directive stage Decision.
        return sorted(bucket, key=lambda e: e.get("timestamp", ""), reverse=True)[:_MAX_PER_SECTION]

    return {
        "who": top(who),
        "how": top(how),
        "building": top_recent(building),
        "prefs": top(prefs),
    }


def synthesize(kb_path: Path = KB_PATH) -> str:
    entries = _read_kb(Path(kb_path))
    buckets = _bucket(entries)

    # Best-effort "current stage" line from the most recent stage Decision.
    current = ""
    for e in sorted(buckets["building"], key=lambda x: x.get("timestamp", ""), reverse=True):
        current = _excerpt(e.get("content", ""), 200)
        if current:
            break

    lines: List[str] = []
    lines.append("# Cognitive Profile — Model of the User")
    lines.append("")
    lines.append(
        "> Auto-synthesized by `scripts/profile_synth.py` from "
        f"`knowledge_base.jsonl` ({len(entries)} entries). "
        "Injected into every chat via the SessionStart hook. "
        "Regenerate after KB updates."
    )
    lines.append("")

    lines.append("## Who you are")
    if buckets["who"]:
        for e in buckets["who"]:
            lines.append(f"- {_excerpt(e.get('content', ''))}")
    else:
        lines.append("- (no user-background patterns captured yet)")
    lines.append("")

    lines.append("## How you work — active directives")
    if buckets["how"]:
        for e in buckets["how"]:
            tag = e.get("type", "")
            lines.append(f"- [{tag}] {_directive_sentence(e.get('content', ''))}")
    else:
        lines.append("- (no directives captured yet)")
    lines.append("")

    lines.append("## What you're building")
    if current:
        lines.append(f"**Current focus:** {current}")
        lines.append("")
    if buckets["building"]:
        for e in buckets["building"][:5]:
            lines.append(f"- {_excerpt(e.get('content', ''), 200)}")
    else:
        lines.append("- (no build-state decisions captured yet)")
    lines.append("")

    lines.append("## Preferences & anti-patterns")
    if buckets["prefs"]:
        for e in buckets["prefs"]:
            lines.append(f"- {_excerpt(e.get('content', ''))}")
    else:
        lines.append("- (no preference/refusal patterns captured yet)")
    lines.append("")

    return "\n".join(lines)


def _run_self_test() -> None:
    import tempfile

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
        kb = Path(td) / "kb.jsonl"
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

        out = synthesize(kb)
        check("T1 non-empty", len(out) > 100)
        check("T2 has 'Who you are'", "## Who you are" in out)
        check("T3 has 'How you work'", "## How you work" in out)
        check("T4 has 'What you're building'", "## What you're building" in out)
        check("T5 has 'Preferences'", "## Preferences & anti-patterns" in out)
        check("T6 surfaces a DIRECTIVE", "DIRECTIVE:" in out, out[:400])
        check("T7 surfaces current stage", "3.5" in out or "Stage 3" in out)
        check("T8 surfaces refusal/anti-pattern", "bundling" in out.lower() or "anti-pattern" in out.lower())

        # Empty KB -> still well-formed with placeholders
        empty = Path(td) / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        out2 = synthesize(empty)
        check("T9 empty KB still has all 4 sections",
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
