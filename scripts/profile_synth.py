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

The SessionStart hook (inject_profile.py) and the boot inhale
(brain/context_injector.py) need ONE document that says who the owner is.
The KB holds hundreds of scattered entries; profile_synth sorts the
user-model entries into sections and renders every selected entry WHOLE.

"Who you are" is IDENTITY, not recency (corrected 2026-09-28, KB 771). It
used to be the 8 newest directive-bearing Cognitive_Patterns cut to 320
chars, so a week of Stitch colour corrections displaced every durable trait
and JARVIS answered "what do you know about me?" with UI rules. Identity is
now selected by identity-family tags (career, legacy, philosophy, ambition,
motivation, self-model...) and read oldest -> newest, so later entries read
as updates to earlier ones. Last week's project corrections get their own,
explicitly-labelled section.

"People in your life" (added 2026-09-28) holds every entry tagged `person`
or `person-<name>`, which is what parse_rule's person facts are written with,
oldest -> newest, right after "Who you are". Before it, the owner's
girlfriend was nowhere JARVIS could see: a person fact had no section to land
in, and the only personal-life record was a file JARVIS never read.

No entry is ever cut, and no section has a count limit: an entry is either
selected in full or not selected. An entry appears in exactly one section.
Entries a newer entry declares superseded (a `supersedes-YYYY-MM-DD` tag
sharing a topical tag) are left out, which is a selection, not a cut.

The profile leaves the machine (OpenRouter via the boot inhale, Claude via
the hook). People in the owner's life are NOT redacted here: on 2026-09-28
the owner chose to let JARVIS see them when answering ("in context only"),
after JARVIS could not say who their girlfriend was. Training artifacts
still redact them (specialists/third_parties.py at blend/SFT time), and
employer/client identifiers are still stripped downstream by
brain/outbound_policy.redact_outbound.

=============================================================================
THE FLOW
=============================================================================

STEP 1: rebuild_index(kb_path) — always fresh, no assumption a pre-existing
        index is current.
        |
        v
STEP 2: Drop superseded entries, then assign each remaining entry to the
        FIRST section whose selector accepts it, in priority order:
        people -> who -> think -> recent -> how -> building -> prefs -> other.
        |
        v
STEP 3: Render every assigned entry in full; write
        jarvis_data/cognitive_profile.md (or stdout).

=============================================================================
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.config import DATA_ROOT  # noqa: E402
from jarvis_core.memory.cognitive_index import (  # noqa: E402
    IndexedEntry,
    IndexStats,
    query_all,
    rebuild_index,
)

_PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"
_IST = timezone(timedelta(hours=5, minutes=30))
_RECENT_DAYS = 7

# Identity family, surveyed from the KB's real tags on 2026-09-28. Explicit
# rather than a prefix match: "self_hosted" and "self-critique-unreliable"
# share a prefix with "self-model" and are not identity.
_IDENTITY_TAGS = frozenset({
    "identity", "career", "career-strategy", "career-plan", "career-planning",
    "career-switch", "career-timeline", "legacy", "philosophy", "ambition",
    "ambition-passion-distinction", "motivation", "motivation-architecture",
    "meaning-architecture", "life-design", "self-model", "self-knowledge",
    "self-assessment", "self-calibration", "production-vs-self-assessment",
    "intellectual-profile", "exhaustive-learner", "cognitive-signature",
    "identity-measure", "identity_measure_of_value", "personal-artifact",
    "financial-profile", "demographics",
})
# Tags that mean the entry is about JARVIS's own identity, not the owner's.
_SYSTEM_SELF_TAGS = frozenset({
    "JARVIS-identity", "identity-pillar", "identity-assertion",
    "identity-crisis", "runtime-state", "awareness-probe",
})
# A procedural `is`-vs-`==` note is tagged "identity" too; only these types
# can describe a person.
_IDENTITY_TYPES = frozenset({
    "Cognitive_Pattern", "Cognitive_Profile", "Decision", "Episodic", "Semantic",
})
_LEARNING_TAG = re.compile(r"learn|gap|metacognition|meta[-_]cognition|explanation|teaching")
_PATTERN_TYPES = frozenset({"Cognitive_Pattern", "Cognitive_Profile"})
_SUPERSEDES_TAG = re.compile(r"^supersedes-(\d{4}-\d{2}-\d{2})")
# Too broad to show two entries are about the same thing.
_NON_TOPICAL_TAGS = frozenset({"identity", "DIRECTIVE", "directive"})


def _has_directive(e: IndexedEntry) -> bool:
    return any(t.lower() == "directive" for t in e.tags) or "DIRECTIVE:" in e.content


def _is_correction(e: IndexedEntry) -> bool:
    return any("correction" in t.lower() for t in e.tags)


def _render(e: IndexedEntry) -> str:
    text = " ".join(e.content.split())
    return f"- [{(e.timestamp or '')[:10]} · {e.type}] {text}"


def _superseded_ids(entries: List[IndexedEntry]) -> Set[str]:
    """Ids a NEWER entry declares superseded via `supersedes-<date>`, where the
    two also share a topical tag — a date alone would sweep in every unrelated
    entry written that day (KB 245 supersedes 2026-04-18 *portfolio snapshots*,
    not the Strategic Identity decision from the same date)."""
    out: Set[str] = set()
    for newer in entries:
        topical = {t for t in newer.tags
                   if t not in _NON_TOPICAL_TAGS and not t.startswith("supersedes-")}
        for tag in newer.tags:
            m = _SUPERSEDES_TAG.match(tag)
            if not m:
                continue
            day = m.group(1)
            for older in entries:
                if (older.id != newer.id and (older.timestamp or "")[:10] == day
                        and (older.timestamp or "") < (newer.timestamp or "")
                        and topical & set(older.tags)):
                    out.add(older.id)
    return out


def _is_person(e: IndexedEntry) -> bool:
    """About someone in the owner's life. `person-` exactly, so that
    "personal-artifact" (an identity tag) is not mistaken for one."""
    return (any(t == "person" or t.startswith("person-") for t in e.tags)
            and not set(e.tags) & _SYSTEM_SELF_TAGS)


def _is_identity(e: IndexedEntry) -> bool:
    tags = set(e.tags)
    return (e.type in _IDENTITY_TYPES
            and (e.type == "Cognitive_Profile" or bool(tags & _IDENTITY_TAGS))
            and not tags & _SYSTEM_SELF_TAGS
            and not _is_correction(e))


def _is_learning(e: IndexedEntry) -> bool:
    return e.type == "Cognitive_Pattern" and any(_LEARNING_TAG.search(t) for t in e.tags)


def _is_how(e: IndexedEntry) -> bool:
    return e.type == "System_Protocol" or _has_directive(e)


def _is_building(e: IndexedEntry) -> bool:
    return (e.type in ("Decision", "System_Protocol")
            and any(cue in e.content.lower() for cue in ("stage", "sub-phase", "wave")))


def _is_pref(e: IndexedEntry) -> bool:
    return (e.type == "Failure"
            or bool({"refusal_pattern", "refusal"} & set(e.tags))
            or "anti-pattern" in e.content.lower())


def _oldest_first(entries: List[IndexedEntry]) -> List[IndexedEntry]:
    return sorted(entries, key=lambda e: e.timestamp or "")


def _newest_first(entries: List[IndexedEntry]) -> List[IndexedEntry]:
    return sorted(entries, key=lambda e: e.timestamp or "", reverse=True)


def _directive_first(entries: List[IndexedEntry]) -> List[IndexedEntry]:
    return sorted(entries, key=lambda e: (_has_directive(e), e.timestamp or ""), reverse=True)


def _bucket(kb_path: Path, db_path: Path,
            now: datetime) -> Tuple[Dict[str, List[IndexedEntry]], IndexStats]:
    stats = rebuild_index(kb_path=kb_path, db_path=db_path)
    entries = list(query_all(db_path))
    dropped = _superseded_ids(entries)
    live = [e for e in entries if e.id not in dropped]

    recent_floor = (now - timedelta(days=_RECENT_DAYS)).isoformat()

    def is_recent_correction(e: IndexedEntry) -> bool:
        return (e.type == "Cognitive_Pattern" and (_has_directive(e) or _is_correction(e))
                and _parse_ts(e.timestamp) >= recent_floor)

    selectors: List[Tuple[str, Callable[[IndexedEntry], bool],
                          Callable[[List[IndexedEntry]], List[IndexedEntry]]]] = [
        ("people", _is_person, _oldest_first),
        ("who", _is_identity, _oldest_first),
        ("think", _is_learning, _oldest_first),
        ("recent", is_recent_correction, _newest_first),
        ("how", _is_how, _directive_first),
        ("building", _is_building, _newest_first),
        ("prefs", _is_pref, _directive_first),
        ("other", lambda e: e.type in _PATTERN_TYPES, _oldest_first),
    ]
    buckets: Dict[str, List[IndexedEntry]] = {name: [] for name, _, _ in selectors}
    for e in live:
        for name, accepts, _ in selectors:
            if accepts(e):
                buckets[name].append(e)
                break
    return {name: order(buckets[name]) for name, _, order in selectors}, stats


def _parse_ts(ts: str) -> str:
    """ISO timestamp normalised to IST so string comparison is chronological."""
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    return dt.astimezone(_IST).isoformat()


def synthesize(kb_path: Optional[Path] = None, db_path: Optional[Path] = None,
               now: Optional[datetime] = None) -> str:
    from jarvis_core.config import KB_PATH

    kb = kb_path or KB_PATH
    if db_path is not None:
        db = db_path
    else:
        from jarvis_core.config import COGNITIVE_INDEX_PATH

        db = COGNITIVE_INDEX_PATH

    moment = (now or datetime.now(_IST)).astimezone(_IST)
    buckets, stats = _bucket(Path(kb), Path(db), moment)

    lines: List[str] = []
    lines.append("# Cognitive Profile — Model of the User")
    lines.append("")
    lines.append(
        "> Auto-synthesized by `scripts/profile_synth.py` from "
        f"`knowledge_base.jsonl` ({stats.total_entries} entries). "
        "Injected into every chat via the SessionStart hook. "
        "Regenerate after KB updates. Every entry is shown in full, "
        "dated, and appears in one section only."
    )
    lines.append("")

    def section(title: str, key: str, empty: str, preface: str = "") -> None:
        lines.append(f"## {title}")
        if preface:
            lines.append(preface)
        if buckets[key]:
            lines.extend(_render(e) for e in buckets[key])
        else:
            lines.append(f"- ({empty})")
        lines.append("")

    section("Who you are", "who", "no identity entries captured yet",
            "_Durable identity — career, ambitions, philosophy, how you see "
            "yourself. Oldest first; later entries update earlier ones._")
    section("People in your life", "people", "no people captured yet",
            "_Who the people around you are, and what they are to you. Oldest "
            "first; later entries update earlier ones._")
    section("How you think and learn", "think", "no learning-pattern entries captured yet")
    section("How you work — active directives", "how", "no directives captured yet")

    lines.append("## What you're building")
    building = buckets["building"]
    if building:
        lines.append(f"**Current focus:** {_render(building[0])[2:]}")
        lines.append("")
        lines.extend(_render(e) for e in building[1:])
    else:
        lines.append("- (no build-state decisions captured yet)")
    lines.append("")

    section("Preferences & anti-patterns", "prefs", "no preference/refusal patterns captured yet")
    section("Other observed patterns", "other", "no other patterns captured yet")
    section(f"Recent corrections (last {_RECENT_DAYS} days)", "recent",
            "no corrections in the last week",
            "_Project-specific corrections from the past week. These are NOT "
            "identity — never answer \"who am I?\" from this section._")

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

    now = datetime(2026, 9, 28, 12, 0, tzinfo=_IST)
    long_identity = "Strategic Identity: legacy-driven, not career-driven. " + ("ambition " * 600)

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
             "content": "Preamble that must survive. DIRECTIVE: /next must skip concept-only lessons when build lessons exist.",
             "expiry": "Permanent"},
            {"timestamp": "2026-04-18T00:00:00+05:30", "type": "Decision",
             "tags": ["identity", "legacy"], "content": long_identity, "expiry": "Permanent"},
            {"timestamp": "2026-04-17T00:00:00+05:30", "type": "Episodic",
             "tags": ["career", "identity"],
             "content": "User Identity Update: Data Engineer, lives with Alicia.", "expiry": "Permanent"},
            {"timestamp": "2026-01-15T00:00:00+05:30", "type": "Procedural",
             "tags": ["identity", "python"],
             "content": "Use `is None` for singleton identity checks.", "expiry": "Permanent"},
            {"timestamp": "2026-09-27T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["identity", "correction", "directive"],
             "content": "CORRECTION: Stitch gold is 0.8% dark green. DIRECTIVE: use it.",
             "expiry": "Permanent"},
            {"timestamp": "2026-05-13T00:00:00+05:30", "type": "Episodic",
             "tags": ["finance", "identity"],
             "content": "OLD-SNAPSHOT holdings list.", "expiry": "Permanent"},
            {"timestamp": "2026-05-16T00:00:00+05:30", "type": "Episodic",
             "tags": ["finance", "identity", "supersedes-2026-05-13-snapshot"],
             "content": "NEW-SNAPSHOT holdings list.", "expiry": "Permanent"},
            {"timestamp": "2026-06-11T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["identity-pillar", "self-model", "DIRECTIVE"],
             "content": "JARVIS-SELF: the runtime did not register its own model swap. DIRECTIVE: announce it.",
             "expiry": "Permanent"},
            {"timestamp": "2026-09-14T00:00:00+05:30", "type": "Semantic",
             "tags": ["distilled", "person", "source-claude", "person-shubha"],
             "content": "The owner's girlfriend is Shubha, called Tobu. " + ("detail " * 400),
             "expiry": "Permanent"},
            {"timestamp": "2026-08-01T00:00:00+05:30", "type": "Semantic",
             "tags": ["person-father"],
             "content": "PERSON-OLDER the owner's father is a teacher.", "expiry": "Permanent"},
            {"timestamp": "2026-02-01T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["personal-artifact", "identity"],
             "content": "PERSONAL-ARTIFACT-IDENTITY a notebook the owner keeps.", "expiry": "Permanent"},
            {"timestamp": "2026-03-01T00:00:00+05:30", "type": "Cognitive_Pattern",
             "tags": ["curiosity-shape"],
             "content": "UNTAGGED-PATTERN user asks for execution traces.", "expiry": "Permanent"},
        ]
        with open(kb, "w", encoding="utf-8") as f:
            for e in fake:
                f.write(json.dumps(e) + "\n")

        out = synthesize(kb, db, now=now)

        def section_of(marker: str) -> str:
            head = out[:out.index(marker)]
            return head[head.rindex("\n## ") + 4:].split("\n", 1)[0]

        check("T1 non-empty", len(out) > 100)
        check("T2 has every section", all(s in out for s in (
            "## Who you are", "## People in your life", "## How you think and learn", "## How you work",
            "## What you're building", "## Preferences", "## Other observed patterns",
            "## Recent corrections")))
        check("T3 a 5,000-char identity entry appears whole", long_identity.strip() in out)
        check("T4 no excerpt ellipsis anywhere", " ..." not in out)
        check("T5 identity entries land in 'Who you are'",
              section_of("Strategic Identity") == "Who you are"
              and section_of("User Identity Update") == "Who you are", out[:600])
        check("T6 identity reads oldest -> newest",
              out.index("User Identity Update") < out.index("Strategic Identity"))
        check("T7 a Procedural tagged identity is not identity",
              "Use `is None`" not in out[:out.index("## How you think")])
        check("T8 a recent correction is labelled recent, not identity",
              section_of("Stitch gold") == "Recent corrections (last 7 days)")
        check("T9 the text before DIRECTIVE: survives",
              "Preamble that must survive. DIRECTIVE:" in out)
        check("T10 learning pattern lands in 'How you think'",
              section_of("ML math foundation") == "How you think and learn")
        check("T11 superseded snapshot excluded, superseding one kept",
              "OLD-SNAPSHOT" not in out and "NEW-SNAPSHOT" in out)
        check("T12 JARVIS's own self-model is not the owner's identity",
              section_of("JARVIS-SELF") != "Who you are")
        check("T13 people in the owner's life stay named (context-only consent, 2026-09-28)", "Alicia" in out)
        check("T14 current stage surfaced", "Sub-Phase 3.5" in out)
        check("T15 refusal/anti-pattern surfaced", section_of("bundling") == "Preferences & anti-patterns")
        check("T16 unplaced pattern kept, not dropped",
              section_of("UNTAGGED-PATTERN") == "Other observed patterns")
        check("T17 every entry appears once",
              all(out.count(marker) == 1 for marker in (
                  "Strategic Identity", "ML math foundation", "Stitch gold",
                  "MemoryManager", "bundling", "JARVIS-SELF")))
        check("T18 header keeps the (N entries) count the stale check parses",
              "(15 entries)" in out)
        check("T20 person-tagged entries land in 'People in your life', whole",
              section_of("girlfriend is Shubha") == "People in your life"
              and section_of("PERSON-OLDER") == "People in your life"
              and ("The owner's girlfriend is Shubha, called Tobu. " + "detail " * 400).strip() in out)
        check("T21 people read oldest -> newest, right after 'Who you are'",
              out.index("PERSON-OLDER") < out.index("girlfriend is Shubha")
              and out.index("## Who you are") < out.index("## People in your life")
              < out.index("## How you think and learn"))
        check("T22 'personal-artifact' is identity, not a person",
              section_of("PERSONAL-ARTIFACT-IDENTITY") == "Who you are")

        empty = Path(td) / "empty.jsonl"
        empty_db = Path(td) / "empty.sqlite3"
        empty.write_text("", encoding="utf-8")
        out2 = synthesize(empty, empty_db, now=now)
        check("T19 empty KB still has every section with placeholders",
              all(s in out2 for s in ("## Who you are", "## People in your life", "## How you work",
                                       "## What you're building", "## Preferences",
                                       "(no identity entries captured yet)")))

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
