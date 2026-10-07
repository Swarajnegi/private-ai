#!/usr/bin/env python3
"""
check_pipeline.py — invariants BETWEEN the corpus artifacts, which nothing owned.

LAYER: Tools (verification)

    python3 scripts/check_pipeline.py             # all invariants
    python3 scripts/check_pipeline.py --verbose   # plus example offenders
    python3 scripts/check_pipeline.py --self-test # hermetic, no repo data

=============================================================================
THE BIG PICTURE
=============================================================================

Every bug found on 2026-09-15 lived in a RELATIONSHIP between artifacts, and
not one lived inside a module's own logic:

    11% of blended_corpus.jsonl duplicated   — a queue-to-corpus relationship
    UI answers paired with a fake prompt     — conversations-to-pairs
    machine text reaching assistant targets  — queue-to-pairs

All 94 smoke suites passed throughout, and correctly: no module owns a
relationship, so no module's tests can see one break. `check_projections.py`
covers KB-to-projection freshness and stops there. The corpus pipeline is six
artifacts —

    observation_queue -> turn_curation -> engineer/personalization -> blend
                                                                  -> sft_pairs

— and before this file, NOTHING compared any of them against any other. Each
count was produced independently and reconciled with nothing.

=============================================================================
WHY THESE INVARIANTS AND NOT OTHERS
=============================================================================

Each one below is derived from a defect that actually occurred, not from
imagining what might. An invariant nobody has seen fail is a guess about the
future; these are all descriptions of the past.

Where an invariant cannot be checked honestly it is reported as UNKNOWN rather
than quietly passing — a green line that means "not measured" is how
`domain_labels.jsonl` sat six days stale while calling itself authoritative.

=============================================================================
WHAT THIS DOES NOT COVER
=============================================================================

  * Semantic quality. It cannot tell a good training pair from a bad one; that
    is what Antigravity's a_005 audit did by reading rows, and it took a human-
    shaped judgement.
  * Anything upstream of the queue. If a capture adapter drops turns at the
    source, every downstream count is consistently wrong and this stays green.
  * Module-internal logic — that is `scripts/run_all_tests.py`.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load each artifact once, tolerating a torn final line rather than
        dying on it (the queue is append-only and a killed writer happens).
        |
STEP 2: run each invariant; each returns OK / FAIL / UNKNOWN plus a count and
        up to three example offenders.
        |
STEP 3: print one line per invariant and exit non-zero if any FAILed, so the
        hearth records a real failure rather than a quiet log line.
=============================================================================
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

OK, FAIL, UNKNOWN = "OK", "FAIL", "UNKNOWN"

# A handful of prompts are reused by design — the rotation in build_sft_pairs
# deliberately shares templates. Past this many pairs on ONE prompt, the model
# sees one input mapped to many different targets, which teaches nothing.
_MAX_PAIRS_PER_PROMPT = 10


@dataclass
class Finding:
    name: str
    status: str
    detail: str = ""
    examples: List[str] = field(default_factory=list)


def _load(path: Path) -> List[Dict[str, Any]]:
    """Every parseable record. A torn final line is skipped, not fatal."""
    out: List[Dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


@dataclass
class Artifacts:
    root: Path

    def __post_init__(self) -> None:
        d = self.root / "jarvis_data"
        c = d / "training_corpus"
        self.queue = _load(d / "observation_queue.jsonl")
        self.curation = _load(d / "turn_curation.jsonl")
        self.engineer = _load(c / "engineer_corpus.jsonl")
        self.personalization = _load(c / "personalization_corpus.jsonl")
        self.blend = _load(c / "blended_corpus.jsonl")
        self.pairs = _load(c / "sft_pairs.jsonl")
        self.heldout = _load(c / "sft_pairs_heldout.jsonl")
        self.conversations = d / "conversations"


# =============================================================================
# The invariants. Each is named for the defect it would have caught.
# =============================================================================

def inv_no_exact_duplicates(a: Artifacts) -> List[Finding]:
    """357 of 3,291 blend records were byte-identical copies (2026-09-15).

    `_MAX_PER_CLUSTER = 2` caps NEAR-duplicates at two, which is right for
    near-duplicates and wrong for exact ones: a byte-identical record carries
    no new information and simply over-weights that sample in training.
    """
    findings: List[Finding] = []
    for label, rows in (("engineer_corpus", a.engineer),
                        ("personalization_corpus", a.personalization)):
        if not rows:
            findings.append(Finding(f"no exact dupes: {label}", UNKNOWN, "artifact absent"))
            continue
        counts = collections.Counter(str(r.get("text", "")) for r in rows)
        dupes = {t: n for t, n in counts.items() if n > 1 and t}
        extra = sum(n - 1 for n in dupes.values())
        findings.append(Finding(
            f"no exact dupes: {label}",
            OK if not dupes else FAIL,
            f"{extra} redundant of {len(rows)} ({extra / len(rows):.1%})" if dupes
            else f"{len(rows)} records, all distinct",
            [t[:90] for t in list(dupes)[:3]]))
    findings.extend(inv_blend_duplication_is_explained(a))
    return findings


def inv_blend_duplication_is_explained(a: Artifacts) -> List[Finding]:
    """The blend must contain NO text twice. Tightened 2026-09-18.

    THIS INVARIANT HAS NOW BEEN WRONG IN TWO DIFFERENT DIRECTIONS, and the
    sequence is the lesson. V1 flagged every duplicate as a defect and failed
    on intended behaviour. V2 (2026-09-08) relaxed to "no duplication I cannot
    ACCOUNT for" — every repeat had to be explained by a text present in both
    source corpora — and passed ever after.

    V2 PASSED WHILE THE DEFECT IT DESCRIBED WAS REAL. Its own docstring said
    312 of the 338 repeats "has never been written down as deliberate", and it
    printed that line on every run for ten days while reporting OK. ACCOUNTED
    FOR IS NOT THE SAME AS CORRECT: reconciling a number explains where it came
    from, not whether it should exist. The 338 were being trained twice per
    epoch — upsampling the thin personalization set behind the back of
    _PERSONALIZATION_REPEATS=1, which exists precisely to prevent that.

    blend_corpus.py now assigns shared text to personalization and drops the
    engineer copy, so the honest assertion is again the strict one: zero
    repeats. The overlap is still REPORTED, because it is the quantity that
    ownership decides and a future reader should see it move.
    """
    if not a.blend:
        return [Finding("blend duplication is explained", UNKNOWN, "artifact absent")]
    if not a.engineer or not a.personalization:
        return [Finding("blend duplication is explained", UNKNOWN, "source corpora absent")]
    counts = collections.Counter(str(r.get("text", "")) for r in a.blend)
    redundant = sum(n - 1 for n in counts.values() if n > 1)
    overlap = {str(r.get("text", "")) for r in a.engineer} & {
        str(r.get("text", "")) for r in a.personalization}
    return [Finding(
        "blend trains no text twice",
        OK if redundant == 0 else FAIL,
        f"{redundant} repeats in the blend; {len(overlap)} shared text(s) "
        f"owned by personalization, engineer copy dropped"
        + ("" if redundant == 0 else " — SOMETHING IS CONCATENATING AGAIN"))]


def inv_pair_targets_are_owner_prose(a: Artifacts) -> List[Finding]:
    """27 SFT assistant targets were pasted shell transcripts (q_003, 2026-09-11).

    With loss masking on assistant tokens this teaches the adapter to emit a
    shell prompt when asked to reason.
    """
    try:
        from jarvis_core.specialists.text_hygiene import MACHINE_TEXT, classify
    except ImportError:
        return [Finding("pair targets are not machine text", UNKNOWN, "text_hygiene unavailable")]
    findings = []
    for label, rows in (("sft_pairs", a.pairs), ("sft_pairs_heldout", a.heldout)):
        if not rows:
            findings.append(Finding(f"targets not machine text: {label}", UNKNOWN, "absent"))
            continue
        bad = []
        for r in rows:
            msgs = r.get("messages") or []
            if len(msgs) < 2:
                continue
            target = str(msgs[1].get("content", ""))
            if classify(target)[0] == MACHINE_TEXT:
                bad.append(target[:90])
        findings.append(Finding(
            f"targets not machine text: {label}",
            OK if not bad else FAIL,
            f"{len(bad)} of {len(rows)} are machine text" if bad else f"{len(rows)} clean",
            bad[:3]))
    return findings


def inv_heldout_is_isolated(a: Artifacts) -> List[Finding]:
    """A held-out slice that overlaps train measures nothing (spec §7/§8.3)."""
    if not a.pairs or not a.heldout:
        return [Finding("held-out is isolated", UNKNOWN, "artifact absent")]
    def sig(r): return json.dumps(r.get("messages"), sort_keys=True)
    train = {sig(r) for r in a.pairs}
    overlap = [r for r in a.heldout if sig(r) in train]
    return [Finding(
        "held-out is isolated", OK if not overlap else FAIL,
        f"{len(overlap)} of {len(a.heldout)} held-out pairs also in train" if overlap
        else f"{len(a.heldout)} held-out, zero overlap")]


def inv_curation_traces_to_queue(a: Artifacts) -> List[Finding]:
    """A verdict about a turn that does not exist is a verdict about nothing."""
    if not a.curation:
        return [Finding("curation traces to the queue", UNKNOWN, "no curation yet")]
    keys = {(str(r.get("ts", "")), str(r.get("session_id", ""))) for r in a.queue}
    orphans = [r for r in a.curation
               if (str(r.get("ts", "")), str(r.get("session_id", ""))) not in keys]
    folded = {(str(r.get("ts", "")), str(r.get("session_id", ""))) for r in a.curation}
    return [Finding(
        "curation traces to the queue", OK if not orphans else FAIL,
        f"{len(orphans)} verdicts reference a turn not in the queue" if orphans
        else f"{len(folded)} curated of {len(a.queue)} turns ({len(folded)/max(len(a.queue),1):.0%})",
        [str(r.get("ts", ""))[:19] for r in orphans[:3]])]


def inv_no_prompt_monoculture(a: Artifacts) -> List[Finding]:
    """One prompt on 14 different answers teaches the model nothing (2026-09-15).

    Found while adding the interview extractor: the synthetic-prompt rotation
    in `extract_user_explanations` has 5 templates across ~59 pairs, so
    collisions are structural rather than accidental.
    """
    if not a.pairs:
        return [Finding("no prompt monoculture", UNKNOWN, "no pairs")]
    counts = collections.Counter(
        str((r.get("messages") or [{}])[0].get("content", "")) for r in a.pairs)
    worst = counts.most_common(1)[0]
    over = {p: n for p, n in counts.items() if n > _MAX_PAIRS_PER_PROMPT}
    return [Finding(
        "no prompt monoculture", OK if not over else FAIL,
        f"{len(over)} prompt(s) used by >{_MAX_PAIRS_PER_PROMPT} pairs; worst {worst[1]}x"
        if over else f"worst prompt reuse is {worst[1]}x, under the {_MAX_PAIRS_PER_PROMPT} bar",
        [p[:80] for p in list(over)[:3]])]


def inv_no_mechanical_verdicts(a: Artifacts) -> List[Finding]:
    """Every parse verdict is a reading, never a label (2026-09-29).

    An agent's inline loop wrote 1,994 verdicts with empty rationales in a few
    minutes, one batch stamped with a model that had never run here; the
    backlog read 0 while nothing had been read. A current-rule verdict with no
    rationale or no responds_to cannot have come through a judgment.
    """
    from jarvis_core.agent.parse_rule import PARSE_RULE_VERSION
    bad = [r for r in a.curation
           if int(r.get("rule_version") or 0) >= PARSE_RULE_VERSION
           and (not str(r.get("rationale") or "").strip() or not str(r.get("responds_to") or "").strip())]
    return [Finding(
        "no mechanical verdicts", OK if not bad else FAIL,
        f"{len(bad)} current-rule verdicts have no rationale or responds_to (curated_by: "
        f"{sorted({str(r.get('curated_by')) for r in bad})[:4]}); revoke them and parse the turns"
        if bad else "every current-rule verdict carries a rationale and responds_to")]


def inv_client_records_survive(a: Artifacts) -> List[Finding]:
    """A build must never drop the client-work training records (2026-09-28).

    A rebuild on a machine without client_work/ shrank engineer `client_work`
    669 -> 17 and personalization `professional_reasoning` 265 -> 17, and the
    shrunken corpus was committed. Each corpus must hold at least every record
    in training_corpus/client_work_snapshot.jsonl (specialists/client_snapshot.py).
    """
    snap = a.root / "jarvis_data" / "training_corpus" / "client_work_snapshot.jsonl"
    if not snap.exists():
        return [Finding("client records survive", UNKNOWN, "no client_work_snapshot.jsonl")]
    # Survival is CONTENT, not path: the corpus drops exact-text duplicates at the
    # write chokepoint, so two identical notebook cells keep one source_path. On
    # 2026-10-05 a work-laptop rebuild refreshed the snapshot with 13 such paths
    # and this check reported them "lost" while every one's text was present.
    want: Dict[str, List[Tuple[str, str]]] = {"engineer": [], "personalization": []}
    for row in _load(snap):
        if row.get("corpus") in want:
            want[row["corpus"]].append((str(row.get("source_path")), (row.get("text") or "").strip()))
    kept = {
        "engineer": [r for r in a.engineer if r.get("source_type") == "client_work"],
        "personalization": [r for r in a.personalization if r.get("source_type") == "professional_reasoning"],
    }
    lost = {}
    for c in want:
        paths = {str(r.get("source_path")) for r in kept[c]}
        texts = {(r.get("text") or "").strip() for r in kept[c]}
        missing = sum(1 for p, t in want[c] if p not in paths and t not in texts)
        if missing:
            lost[c] = missing
    return [Finding(
        "client records survive", OK if not lost else FAIL,
        f"{sum(len(v) for v in want.values())} snapshot records all present in the corpora"
        if not lost else f"corpus is missing snapshot records: {lost} (a rebuild dropped client work)")]


def inv_ui_answers_keep_their_question(a: Artifacts) -> List[Finding]:
    """UI answers were paired with a synthetic prompt, discarding the real one.

    The interview extractor must win the global dedup against
    `extract_user_explanations`; if the registration order is ever flipped,
    every interview pair silently reverts to a generic prompt.
    """
    if not a.pairs or not a.conversations.is_dir():
        return [Finding("UI answers keep their question", UNKNOWN, "no conversations/")]
    ui_answers = set()
    for path in a.conversations.glob("*.jsonl"):
        for rec in _load(path):
            if rec.get("role") == "user":
                text = str(rec.get("content", "")).strip()
                if len(text) >= 60:
                    ui_answers.add(text)
    if not ui_answers:
        return [Finding("UI answers keep their question", UNKNOWN, "no UI answers on disk")]
    synthetic = []
    for r in a.pairs:
        msgs = r.get("messages") or []
        if len(msgs) < 2:
            continue
        target = str(msgs[1].get("content", "")).strip()
        if target in ui_answers and r.get("metadata", {}).get("form") != "interview":
            synthetic.append(str(msgs[0].get("content", ""))[:80])
    return [Finding(
        "UI answers keep their question", OK if not synthetic else FAIL,
        f"{len(synthetic)} UI answer(s) paired with a synthetic prompt" if synthetic
        else f"{len(ui_answers)} UI answers on disk, none flattened",
        synthetic[:3])]


def inv_records_are_well_formed(a: Artifacts) -> List[Finding]:
    """A record missing its identity cannot be joined, deduped or audited."""
    findings = []
    for label, rows, required in (
        ("observation_queue", a.queue, ("ts", "session_id", "user_text")),
        ("turn_curation", a.curation, ("ts", "session_id", "corpora", "domain")),
        ("sft_pairs", a.pairs, ("messages", "source_type")),
    ):
        if not rows:
            findings.append(Finding(f"well-formed: {label}", UNKNOWN, "absent"))
            continue
        bad = [r for r in rows if any(k not in r for k in required)]
        findings.append(Finding(
            f"well-formed: {label}", OK if not bad else FAIL,
            f"{len(bad)} of {len(rows)} missing a required field" if bad
            else f"{len(rows)} records, all carry {', '.join(required)}"))
    return findings


def inv_no_third_party_identity(a: Artifacts) -> List[Finding]:
    """No named third party reaches an artifact training consumes (2026-09-23).

    Excluding personal_life.md from the corpus was not enough: a partner's name
    was still in 6 blend records and 1 SFT pair, arriving through the very
    conversations that file had been distilled from. Redaction lives in
    blend_corpus.py and build_sft_pairs.write_jsonl; this catches any future
    writer that bypasses them. Reports ROLES, never names, so the check's own
    output cannot leak what it guards. It cannot see a person who is not
    listed in jarvis_data/third_parties.json — nothing here can.
    """
    name = "no third-party identity in training"
    try:
        from jarvis_core.specialists import third_parties
    except ImportError:
        return [Finding(name, UNKNOWN, "third_parties unavailable")]
    try:
        people = third_parties.load(a.root / "jarvis_data" / "third_parties.json")
    except FileNotFoundError:
        return [Finding(name, UNKNOWN, "third_parties.json absent")]
    if not (a.blend or a.pairs or a.heldout):
        return [Finding(name, UNKNOWN, "training artifacts absent")]
    leaks: List[str] = []
    for label, rows in (("blend", a.blend), ("sft_pairs", a.pairs), ("sft_pairs_heldout", a.heldout)):
        for r in rows:
            text = str(r.get("text") or "") + json.dumps(r.get("messages", ""), ensure_ascii=False)
            leaks.extend(f"{label}:{role}" for role in third_parties.roles_present(text, people))
    if not leaks:
        return [Finding(name, OK, f"{len(people)} identifiers checked across blend + SFT pairs, none present")]
    counts = collections.Counter(leaks)
    return [Finding(name, FAIL, ", ".join(f"{k} x{v}" for k, v in counts.most_common()))]



# =============================================================================
# NO TRUNCATION (owner directive 2026-09-28). Three places cut text silently:
# the profile's per-entry caps, the inhale's per-provider caps and 6,000-char
# total, and session_writer's 160/220-char heads. Each was removed; these make
# sure none comes back. They take a repo root rather than Artifacts so
# pipeline_health can run them without loading 25 MB of corpora.
# =============================================================================

_CUT_MARKER = "…"
_MIN_PREFIX_MATCH = 100
# Status providers carry no owner state and one of them (Projection integrity)
# loads an embedding model, ~100 s cold. They are left out of the boot inhale
# rebuilt here; everything that can carry the profile or personal life stays.
_STATUS_ONLY_PROVIDERS = frozenset({"Projection integrity", "Pipeline health"})


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


def _kb_rows(root: Path) -> List[Dict[str, Any]]:
    return [r for r in _load(root / "jarvis_data" / "knowledge_base.jsonl") if isinstance(r, dict)]


def trunc_profile_entries_whole(root: Path) -> List[Finding]:
    """Every KB entry profile_synth selects appears WHOLE in the profile.

    Checked by content presence, not by section names, so a new section (the
    People one being added 2026-09-28) needs no change here. Only the KB
    entries the profile was synthesised FROM are compared — its header records
    that count — so an entry appended after the last synth is a stale
    projection (check_projections' job), not a truncation.
    """
    import re
    import tempfile
    from datetime import datetime, timedelta, timezone
    name = "profile carries every selected entry whole"
    profile = root / "jarvis_data" / "cognitive_profile.md"
    kb = root / "jarvis_data" / "knowledge_base.jsonl"
    if not profile.exists() or not kb.exists():
        return [Finding(name, UNKNOWN, "profile or KB absent")]
    text = profile.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\((\d+) entries\)", text)
    lines = [ln for ln in kb.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    synthesised_from = int(m.group(1)) if m else len(lines)
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import profile_synth  # type: ignore
    ist = timezone(timedelta(hours=5, minutes=30))
    when = datetime.fromtimestamp(profile.stat().st_mtime, ist)
    with tempfile.TemporaryDirectory() as td:
        snapshot = Path(td) / "kb.jsonl"
        snapshot.write_text("\n".join(lines[:synthesised_from]) + "\n", encoding="utf-8")
        buckets, _stats = profile_synth._bucket(snapshot, Path(td) / "index.sqlite3", when)
    selected = [e for bucket in buckets.values() for e in bucket]
    body = _norm(text)
    missing = [e for e in selected if _norm(e.content) not in body]
    if not missing:
        return [Finding(name, OK, f"{len(selected)} selected entries, every one present whole")]
    cut = [e for e in missing if _norm(e.content)[:120] in body]
    return [Finding(
        name, FAIL,
        f"{len(missing)} of {len(selected)} selected entries are not in the profile whole "
        f"({len(cut)} present but CUT, {len(missing) - len(cut)} absent): ids "
        + ", ".join(str(e.id) for e in missing)
        + ". Fix: python scripts/profile_synth.py, then find the cap that returned",
        [f"{e.id}: {_norm(e.content)[:90]}" for e in missing[:3]])]


def default_inhales(root: Path) -> Dict[str, str]:
    """The voice inhale (voice_path._default_inhale) and the boot inhale
    (context_injector default providers), built from `root`'s files."""
    from jarvis_core.brain import context_injector as ci
    from jarvis_core.brain.voice_path import _default_inhale
    data = root / "jarvis_data"
    saved = (ci._DEFAULT_PROFILE_PATH, ci._DEFAULT_PERSONAL_LIFE_PATH)
    patch = Path(saved[0]).resolve() != (data / "cognitive_profile.md").resolve()
    if patch:
        ci._DEFAULT_PROFILE_PATH = data / "cognitive_profile.md"
        ci._DEFAULT_PERSONAL_LIFE_PATH = data / "personal_life.md"
    try:
        with ci.pipeline_health_suppressed():
            voice = _default_inhale()
            boot = ci.ContextInjector([s for s in ci.default_providers(core=ci.core_mode_active())
                                       if s.name not in _STATUS_ONLY_PROVIDERS]).inhale().block
    finally:
        if patch:
            ci._DEFAULT_PROFILE_PATH, ci._DEFAULT_PERSONAL_LIFE_PATH = saved
    return {"voice inhale": voice, "boot inhale": boot}


def _personal_life_body(text: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[i:]).strip()
    return text.strip()


def trunc_inhales_carry_whole_state(root: Path,
                                    inhales: Optional[Dict[str, str]] = None) -> List[Finding]:
    """Both inhales carry the WHOLE profile and the whole personal-life body.

    With the standing core on (the Context Store's recall mode) the profile is
    carried as whole SECTIONS (identity, people, recent corrections) and every
    other section is reached through the episode index instead; the invariant
    is then that each carried section is whole, never that the file is.

    Compared after the outbound airlock, because redact_outbound removing a
    client identifier is policy, not truncation: the expected text is the file
    passed through the same redaction the inhale applies.
    """
    from jarvis_core.brain.context_injector import (CORE_PROFILE_SECTIONS, core_mode_active,
                                                    profile_sections)
    from jarvis_core.brain.outbound_policy import redact_outbound
    data = root / "jarvis_data"
    sources: Dict[str, str] = {}
    profile, life = data / "cognitive_profile.md", data / "personal_life.md"
    if profile.exists():
        profile_text = profile.read_text(encoding="utf-8", errors="replace").strip()
        if core_mode_active():
            for heading, body in profile_sections(profile_text, CORE_PROFILE_SECTIONS):
                if body:
                    sources[f"cognitive_profile.md section '{heading}'"] = body
        else:
            sources["cognitive_profile.md"] = profile_text
    if life.exists():
        sources["personal_life.md body"] = _personal_life_body(life.read_text(encoding="utf-8", errors="replace"))
    if not sources:
        return [Finding("inhales carry whole profile + personal life", UNKNOWN, "neither file exists")]
    blocks = inhales if inhales is not None else default_inhales(root)
    findings: List[Finding] = []
    for block_name, block in blocks.items():
        for source_name, raw in sources.items():
            expected = redact_outbound(raw).text.strip()
            name = f"{block_name} carries whole {source_name}"
            if not expected:
                findings.append(Finding(name, UNKNOWN, "source is empty"))
            elif expected in block:
                findings.append(Finding(name, OK, f"{len(expected):,} chars, whole"))
            else:
                how = "present but CUT" if expected[:200] in block else "ABSENT"
                findings.append(Finding(
                    name, FAIL,
                    f"{how}: the {len(expected):,}-char {source_name} is not in the "
                    f"{len(block):,}-char {block_name}. Something is cutting or dropping "
                    f"it — see brain/context_injector.py and brain/voice_path.py VOICE_SECTIONS"))
    return findings


def _split_distill(content: str) -> Optional[Tuple[str, str]]:
    head, sep, _tail = content.rpartition(" | tools: ")
    if not sep or "Q: " not in head or " | A: " not in head:
        return None
    q, _, a = head.split("Q: ", 1)[1].partition(" | A: ")
    return q, a


def _conversation_turns(root: Path) -> List[Tuple[str, str, str]]:
    """(file name, user text, following assistant text) for every UI/terminal turn."""
    out: List[Tuple[str, str, str]] = []
    conv = root / "jarvis_data" / "conversations"
    if not conv.is_dir():
        return out
    for path in sorted(conv.glob("*.jsonl")):
        rows = _load(path)
        for i, rec in enumerate(rows):
            if rec.get("role") != "user":
                continue
            answer = next((str(r.get("content", "")) for r in rows[i + 1:]
                           if r.get("role") == "assistant"), "")
            out.append((path.name, str(rec.get("content", "")), answer))
    return out


def trunc_session_distills_whole(root: Path) -> List[Finding]:
    """Every session-distill KB entry holds its FULL question and answer.

    A distill is cut when its Q or A ends in the "…" marker the old 160/220-char
    heads added, or when a conversation file on disk holds a longer text the KB
    copy is a strict prefix of. An entry is repaired by a later KB entry tagged
    `repairs-kb-<id>` — the KB is append-only, so a repair is an addition,
    never an edit.
    """
    name = "session distills hold the full Q and A"
    rows = _kb_rows(root)
    distills = [r for r in rows if "session-distill" in (r.get("tags") or [])]
    if not distills:
        return [Finding(name, UNKNOWN, "no session-distill entries")]
    repaired = {str(t)[len("repairs-kb-"):] for r in rows for t in (r.get("tags") or [])
                if str(t).startswith("repairs-kb-")}
    turns = _conversation_turns(root)
    cut: List[Tuple[Any, str]] = []
    unparseable: List[Any] = []
    for r in distills:
        rid = r.get("id")
        parts = _split_distill(str(r.get("content", "")))
        if parts is None:
            unparseable.append(rid)
            continue
        q, a = parts
        q_norm, a_norm = _norm(q.rstrip().rstrip(_CUT_MARKER)), _norm(a.rstrip().rstrip(_CUT_MARKER))
        marked = q.rstrip().endswith(_CUT_MARKER) or a.rstrip().endswith(_CUT_MARKER)
        # A short question is a prefix of too many others to identify its
        # conversation by prefix alone; below that length only an exact match counts.
        source = next(((f, u, ans) for f, u, ans in turns
                       if _norm(u) == q_norm or (len(q_norm) >= _MIN_PREFIX_MATCH
                                                 and _norm(u).startswith(q_norm))), None)
        longer_on_disk = bool(source) and (
            len(_norm(source[1])) > len(q_norm)
            or (_norm(source[2]).startswith(a_norm) and len(_norm(source[2])) > len(a_norm)))
        if not (marked or longer_on_disk) or str(rid) in repaired:
            continue
        where = f"full text in conversations/{source[0]}" if source else "no conversation file on disk"
        cut.append((rid, where))
    findings = []
    if cut:
        recoverable = sum(1 for _, w in cut if w.startswith("full text"))
        findings.append(Finding(
            name, FAIL,
            f"{len(cut)} of {len(distills)} session distills are CUT (ids "
            + ", ".join(str(rid) for rid, _ in cut)
            + f"); {recoverable} recoverable from a conversation file. Repair by "
              "appending the whole Q/A tagged repairs-kb-<id>",
            [f"KB {rid}: {w}" for rid, w in cut[:3]]))
    else:
        findings.append(Finding(name, OK, f"{len(distills)} session distills, all whole"))
    if unparseable:
        findings.append(Finding("session distills are parseable", UNKNOWN,
                                "no 'Q: … | A: … | tools:' shape in ids "
                                + ", ".join(str(i) for i in unparseable)))
    return findings


TRUNCATION_CHECKS: Tuple[Callable[[Path], List[Finding]], ...] = (
    trunc_profile_entries_whole,
    trunc_inhales_carry_whole_state,
    trunc_session_distills_whole,
)


def truncation_findings(root: Optional[Path] = None,
                        inhales: Optional[Dict[str, str]] = None) -> List[Finding]:
    """The no-truncation invariants alone. An exception is a FAIL naming the
    check, never a silent pass — a check that cannot run proves nothing."""
    base = Path(root or _REPO_ROOT)
    findings: List[Finding] = []
    for fn in TRUNCATION_CHECKS:
        try:
            if fn is trunc_inhales_carry_whole_state:
                findings.extend(fn(base, inhales))
            else:
                findings.extend(fn(base))
        except Exception as exc:                        # noqa: BLE001
            findings.append(Finding(fn.__name__, FAIL, f"check raised {type(exc).__name__}: {exc}"))
    return findings


def inv_no_truncation(a: Artifacts) -> List[Finding]:
    """Owner directive 2026-09-28: no text is cut anywhere on its way to JARVIS."""
    return truncation_findings(a.root)


def inv_shards_are_safe_to_push(a: Artifacts) -> List[Finding]:
    """Context-store shards (git-tracked): size limit, no credential, no client source.

    Checks the files, not the writer's intent: every shard under 50,000,000
    bytes, no unmasked credential-shaped token, and no tool call/result that
    touches a client_work/<project>/ file left unstubbed.
    """
    from jarvis_core.memory import episode_store as es
    shards = a.root / "jarvis_data" / "context_store" / "shards"
    files = es.shard_files(shards)
    if not files:
        return [Finding("shards are safe to push", UNKNOWN, "no shard files")]
    big, secret, client = [], [], []
    records = 0
    for f in files:
        if f.stat().st_size >= es.SHARD_LIMIT_BYTES:
            big.append(f"{f.relative_to(shards).as_posix()} ({f.stat().st_size} bytes)")
        for rec in es.iter_shard(f):
            records += 1
            text = str(rec.get("content") or "") + json.dumps(rec.get("tool") or {}, ensure_ascii=False)
            if any(rx.search(text) for rx in es._SECRET_PATTERNS):
                secret.append(str(rec.get("id")))
            if (rec.get("role") in ("tool_call", "tool_result") and not rec.get("stub")
                    and es._CLIENT_PATH.search(text)):
                client.append(str(rec.get("id")))
    out = [Finding("shards: every file < 50,000,000 bytes", FAIL if big else OK,
                   ", ".join(big[:5]) if big else f"{len(files)} files"),
           Finding("shards: no unmasked credential", FAIL if secret else OK,
                   f"{len(secret)} records" if secret else f"{records} records scanned",
                   examples=secret[:5]),
           Finding("shards: no client_work tool content", FAIL if client else OK,
                   f"{len(client)} records" if client else f"{records} records scanned",
                   examples=client[:5])]
    return out


def inv_no_eval_canary_in_training(a: Artifacts) -> List[Finding]:
    """The c002 evaluation must never reach a training artifact or the KB.

    Every c002 file carries a canary from jarvis_data/eval/c002/exclusions.json.
    A canary inside a corpus, an SFT pair or a knowledge-base entry means the
    answer key has leaked into what an adapter would learn from.
    """
    from jarvis_core.specialists.eval_exclusions import has_canary, load_registry
    registry = load_registry(a.root / "jarvis_data" / "eval" / "c002" / "exclusions.json")
    if not registry.canaries:
        return [Finding("c002 canary absent from training", UNKNOWN, "no canary registered")]
    kb = _load(a.root / "jarvis_data" / "knowledge_base.jsonl")
    leaked = []
    for label, rows in (("engineer", a.engineer), ("personalization", a.personalization),
                        ("blend", a.blend), ("sft_pairs", a.pairs), ("heldout", a.heldout),
                        ("knowledge_base", kb)):
        for n, row in enumerate(rows):
            if has_canary(registry, json.dumps(row, ensure_ascii=False)):
                leaked.append(f"{label}#{n}")
    return [Finding(
        "c002 canary absent from training", OK if not leaked else FAIL,
        f"{len(leaked)} records carry a canary" if leaked
        else f"{len(registry.canaries)} canary scanned across corpora, pairs and KB",
        leaked[:3])]


def inv_no_retracted_material_in_training(a: Artifacts) -> List[Finding]:
    """Retracted KB entries and conversation turns (jarvis_data/retractions.jsonl) must not be in a corpus.

    Until the next corpus rebuild this FAILS for anything retracted after the last build, which is the
    truth: those artifacts still hold material known not to be the owner's words."""
    from jarvis_core.specialists.retractions import load_retractions
    ret = load_retractions(a.root / "jarvis_data" / "retractions.jsonl")
    if not ret.kb_ids and not ret.conv_turns:
        return [Finding("retracted material absent from training", OK, "nothing retracted")]
    leaked = []
    for label, rows in (("engineer", a.engineer), ("personalization", a.personalization), ("blend", a.blend), ("sft_pairs", a.pairs)):
        for n, row in enumerate(rows):
            sp = str(row.get("source_path", ""))
            head, _, tail = sp.partition("#")
            if head.startswith("kb") and tail.split("#")[0] in ret.kb_ids:
                leaked.append(f"{label}#{n} {sp}")
            elif tail.startswith("L") and tail[1:].isdigit() and (head, int(tail[1:])) in ret.conv_turns:
                leaked.append(f"{label}#{n} {sp}")
            elif sp.startswith("kb#") and sp.split("#")[1] in ret.kb_ids:
                leaked.append(f"{label}#{n} {sp}")
    return [Finding(
        "retracted material absent from training", OK if not leaked else FAIL,
        f"{len(leaked)} retracted record(s) are still in a built artifact (rebuild the corpora)" if leaked
        else f"{len(ret.kb_ids)} KB entries and {len(ret.conv_turns)} turns retracted, none present",
        leaked[:3])]


INVARIANTS: Tuple[Callable[[Artifacts], List[Finding]], ...] = (
    inv_no_retracted_material_in_training,
    inv_no_eval_canary_in_training,
    inv_no_exact_duplicates,   # includes inv_blend_duplication_is_explained
    inv_pair_targets_are_owner_prose,
    inv_heldout_is_isolated,
    inv_curation_traces_to_queue,
    inv_no_prompt_monoculture,
    inv_client_records_survive,
    inv_no_mechanical_verdicts,
    inv_ui_answers_keep_their_question,
    inv_records_are_well_formed,
    inv_no_third_party_identity,
    inv_no_truncation,
    inv_shards_are_safe_to_push,
)


def run(root: Optional[Path] = None) -> List[Finding]:
    artifacts = Artifacts(root or _REPO_ROOT)
    findings: List[Finding] = []
    for fn in INVARIANTS:
        try:
            findings.extend(fn(artifacts))
        except Exception as exc:                        # noqa: BLE001
            findings.append(Finding(fn.__name__, UNKNOWN, f"check raised: {type(exc).__name__}: {exc}"))
    return findings


def report(findings: Sequence[Finding], verbose: bool = False) -> int:
    print("=" * 78)
    print("  PIPELINE INVARIANTS — relationships no single module owns")
    print("=" * 78)
    for f in findings:
        mark = {OK: "  OK  ", FAIL: " FAIL ", UNKNOWN: " ???? "}[f.status]
        print(f"  [{mark}] {f.name:<42} {f.detail}")
        if verbose and f.examples:
            for ex in f.examples:
                print(f"            e.g. {ex!r}")
    failed = [f for f in findings if f.status == FAIL]
    unknown = [f for f in findings if f.status == UNKNOWN]
    print("-" * 78)
    print(f"  {len(findings) - len(failed) - len(unknown)} ok · {len(failed)} failed · "
          f"{len(unknown)} unmeasurable")
    if unknown:
        print("  UNMEASURABLE is not PASS — it means the artifact was missing or the")
        print("  check could not run, and it is reported rather than hidden.")
    print("=" * 78)
    return 1 if failed else 0


def _self_test() -> int:
    """Hermetic: builds artifacts in a temp dir, never reads the real ones."""
    import tempfile
    passed, failed = [], []

    def check(name, got, want):
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    def write(root, rel, rows):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def status_of(findings, needle):
        return next(f.status for f in findings if needle in f.name)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "same"}, {"text": "same"}, {"text": "other"}])
        f = run(root)
        check("T1 within-corpus exact duplicates are caught",
              status_of(f, "no exact dupes: engineer_corpus"), FAIL)

        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "a"}, {"text": "b"}])
        check("T2 distinct records pass",
              status_of(run(root), "no exact dupes: engineer_corpus"), OK)

        write(root, "jarvis_data/observation_queue.jsonl",
              [{"ts": "t1", "session_id": "s", "user_text": "hi"}])
        write(root, "jarvis_data/turn_curation.jsonl",
              [{"ts": "GHOST", "session_id": "s", "corpora": ["none"], "domain": "unknown"}])
        check("T3 a verdict about a nonexistent turn is caught",
              status_of(run(root), "curation traces"), FAIL)

        write(root, "jarvis_data/turn_curation.jsonl",
              [{"ts": "t1", "session_id": "s", "corpora": ["none"], "domain": "unknown"}])
        check("T4 a traceable verdict passes", status_of(run(root), "curation traces"), OK)

        pair = {"messages": [{"role": "user", "content": "Q?"},
                             {"role": "assistant", "content": "my own considered answer here"}],
                "source_type": "sft_personalization", "metadata": {}}
        write(root, "jarvis_data/training_corpus/sft_pairs.jsonl", [pair])
        write(root, "jarvis_data/training_corpus/sft_pairs_heldout.jsonl", [pair])
        check("T5 held-out overlapping train is caught",
              status_of(run(root), "held-out"), FAIL)

        write(root, "jarvis_data/training_corpus/sft_pairs_heldout.jsonl",
              [{"messages": [{"role": "user", "content": "Z?"},
                             {"role": "assistant", "content": "different answer entirely"}],
                "source_type": "sft_personalization", "metadata": {}}])
        check("T6 an isolated held-out slice passes", status_of(run(root), "held-out"), OK)

        write(root, "jarvis_data/training_corpus/sft_pairs.jsonl",
              [{"messages": [{"role": "user", "content": "same prompt"},
                             {"role": "assistant", "content": f"answer {i}"}],
                "source_type": "x", "metadata": {}} for i in range(_MAX_PAIRS_PER_PROMPT + 2)])
        check("T7 prompt monoculture is caught", status_of(run(root), "monoculture"), FAIL)

        write(root, "jarvis_data/observation_queue.jsonl", [{"ts": "t", "session_id": "s"}])
        check("T8 a record missing a required field is caught",
              status_of(run(root), "well-formed: observation_queue"), FAIL)

        empty = Path(tmp) / "nothing"
        empty.mkdir()
        f = run(empty)
        check("T9 a missing artifact is UNKNOWN, never a silent pass",
              all(x.status == UNKNOWN for x in f if x.name != 'no mechanical verdicts')
              and status_of(f, 'no mechanical verdicts') == OK, True)
        check("T10 UNKNOWN does not make the run fail", report(f), 0)

        # T12/T13: the blend must train no text twice. This assertion has been
        # wrong in BOTH directions historically - v1 failed on intended
        # behaviour and taught people to ignore it; v2 relaxed to "explained by
        # the source overlap" and then PASSED for ten days while 312 records
        # were genuinely trained twice. It is strict again, which is only
        # honest now that blend_corpus.py assigns shared text to
        # personalization and drops the engineer copy.
        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl", [{"text": "shared"}])
        write(root, "jarvis_data/training_corpus/personalization_corpus.jsonl",
              [{"text": "shared"}])
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl",
              [{"text": "shared"}])
        check("T12 shared text kept ONCE passes",
              status_of(run(root), "blend trains no text twice"), OK)
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl",
              [{"text": "shared"}, {"text": "shared"}])
        check("T13 shared text concatenated TWICE fails",
              status_of(run(root), "blend trains no text twice"), FAIL)

        # T14/T15: a listed third party anywhere training reads is a FAIL.
        (root / "jarvis_data" / "third_parties.json").write_text(json.dumps(
            {"people": [{"role": "partner", "identifiers": ["Alice"]}]}), encoding="utf-8")
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl", [{"text": "met Alice today"}])
        check("T14 a listed third party in the blend fails",
              status_of(run(root), "no third-party identity"), FAIL)
        write(root, "jarvis_data/training_corpus/blended_corpus.jsonl", [{"text": "met [partner] today"}])
        check("T15 the same record, redacted, passes",
              status_of(run(root), "no third-party identity"), OK)

        write(root, "jarvis_data/training_corpus/engineer_corpus.jsonl",
              [{"text": "dup"}, {"text": "dup"}])
        check("T11 report() exits non-zero on a real failure", report(run(root)), 1)

    # T16-T25: the no-truncation invariants, each against its own temp root.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "jarvis_data"
        data.mkdir(parents=True)
        long_identity = "Identity: I grew up in the hills and want to build JARVIS. " + "detail " * 400 + "IDENTITY-END"
        kb_rows = [
            {"id": 1, "timestamp": "2026-09-01T10:00:00+05:30", "type": "Cognitive_Profile",
             "tags": ["identity"], "content": long_identity},
            {"id": 2, "timestamp": "2026-09-02T10:00:00+05:30", "type": "System_Protocol",
             "tags": ["DIRECTIVE"], "content": "DIRECTIVE: never truncate anything. PROTOCOL-END"},
        ]
        write(root, "jarvis_data/knowledge_base.jsonl", kb_rows)
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import profile_synth  # type: ignore
        profile_text = profile_synth.synthesize(kb_path=data / "knowledge_base.jsonl",
                                                db_path=Path(tmp) / "idx.sqlite3")
        (data / "cognitive_profile.md").write_text(profile_text, encoding="utf-8")
        check("T16 a profile holding every selected entry whole passes",
              trunc_profile_entries_whole(root)[0].status, OK)
        (data / "cognitive_profile.md").write_text(profile_text.replace("IDENTITY-END", ""), encoding="utf-8")
        f16 = trunc_profile_entries_whole(root)[0]
        check("T17 a profile entry cut short is caught, and named as CUT",
              (f16.status, "present but CUT" in f16.detail), (FAIL, True))
        (data / "cognitive_profile.md").write_text(profile_text, encoding="utf-8")
        write(root, "jarvis_data/knowledge_base.jsonl", kb_rows + [
            {"id": 3, "timestamp": "2026-09-03T10:00:00+05:30", "type": "System_Protocol",
             "tags": ["DIRECTIVE"], "content": "DIRECTIVE: added after the last synth."}])
        check("T18 an entry appended after the last synth is staleness, not truncation",
              trunc_profile_entries_whole(root)[0].status, OK)

        (data / "personal_life.md").write_text(
            "# Personal Life\n\n> storage policy\n\n## Relationships\n- Partner: Alicia. LIFE-END\n",
            encoding="utf-8")
        whole = {"voice inhale": "## x\n" + profile_text + "\n## Relationships\n- Partner: Alicia. LIFE-END",
                 "boot inhale": profile_text + "\n## Relationships\n- Partner: Alicia. LIFE-END"}
        check("T19 inhales carrying the whole profile and personal life pass",
              {f.status for f in trunc_inhales_carry_whole_state(root, whole)}, {OK})
        cut = dict(whole, **{"voice inhale": profile_text[:2500]})
        from unittest.mock import patch
        from jarvis_core.brain import context_injector as ci
        for full_profile in ('0', '1'):
            with patch.dict('os.environ', {'JARVIS_FULL_PROFILE': full_profile}):
                findings = trunc_inhales_carry_whole_state(root, cut)
                bad = [f for f in findings if f.status == FAIL]
                profile_failures = [f for f in bad if f.name.startswith('voice inhale carries whole cognitive_profile.md')]
                expected_profiles = len(ci.profile_sections(profile_text, ci.CORE_PROFILE_SECTIONS)) if ci.core_mode_active() else 1
                check(f"T20 mode={full_profile}: cut profile and missing life are caught",
                      (len(profile_failures), any(f.name == 'voice inhale carries whole personal_life.md body' for f in bad),
                       all(f.status == OK for f in findings if f.name.startswith('boot inhale'))),
                      (expected_profiles, True, True))
        real_inhales = default_inhales(root)
        check("T21 the REAL voice and boot inhales, built from these files, carry both whole",
              {f.status for f in trunc_inhales_carry_whole_state(root, real_inhales)}, {OK})

        q_long = "How should the parse rule treat corrections? " + "context " * 30
        a_long = "It should keep them whole. " + "because " * 60
        write(root, "jarvis_data/conversations/conv-20260901T100000-1.jsonl", [
            {"ts": "2026-09-01T10:00:00+05:30", "role": "user", "content": q_long},
            {"ts": "2026-09-01T10:00:00+05:30", "role": "assistant", "content": a_long}])

        def distill(i: int, q: str, a: str, tags: Sequence[str] = ("session-distill", "terminal")) -> Dict[str, Any]:
            return {"id": i, "timestamp": "2026-09-01T10:00:00+05:30", "type": "Episodic", "tags": list(tags),
                    "content": f"Terminal session distill (m): Q: {q} | A: {a} | tools: none | "
                               f"confidence: OK 0.9 | spend: $0.0000"}
        write(root, "jarvis_data/knowledge_base.jsonl", [distill(10, q_long.strip(), a_long.strip())])
        check("T22 a distill equal to its conversation passes",
              trunc_session_distills_whole(root)[0].status, OK)
        flat_q = " ".join(q_long.split())
        write(root, "jarvis_data/knowledge_base.jsonl", [distill(11, flat_q[:160] + "…", a_long[:220] + "…")])
        f23 = trunc_session_distills_whole(root)[0]
        check("T23 the old 160/220-char heads are caught, with the id and where the full text is",
              (f23.status, "ids 11" in f23.detail, "1 recoverable" in f23.detail), (FAIL, True, True))
        write(root, "jarvis_data/knowledge_base.jsonl", [distill(12, flat_q, " ".join(a_long.split())[:150])])
        check("T24 an answer cut WITHOUT a marker is caught against the conversation file",
              trunc_session_distills_whole(root)[0].status, FAIL)
        write(root, "jarvis_data/knowledge_base.jsonl", [
            distill(11, flat_q[:160] + "…", a_long[:220] + "…"),
            distill(13, flat_q, " ".join(a_long.split()), tags=("session-distill", "repairs-kb-11"))])
        check("T25 a cut distill repaired by an entry tagged repairs-kb-<id> passes",
              trunc_session_distills_whole(root)[0].status, OK)
        check("T25b truncation_findings turns a crashing check into a FAIL, never a pass",
              any(f.status == FAIL and "raised" in f.detail
                  for f in truncation_findings(root, inhales={"voice inhale": None})),  # type: ignore[dict-item]
              True)

    # T26-T28: shard safety, on a hand-built shard in a temp root.
    import gzip as _gz
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sd = root / "jarvis_data" / "context_store" / "shards" / "m" / "codex" / "2026-09"
        sd.mkdir(parents=True)
        good = {"id": "turn:codex:s:0", "role": "tool_result", "content": "ok", "tool": None}
        (sd / "a.jsonl.gz").write_bytes(_gz.compress((json.dumps(good) + chr(10)).encode()))
        check("T26 a clean shard passes all three shard checks",
              {f.status for f in inv_shards_are_safe_to_push(Artifacts(root))}, {OK})
        leak = {"id": "turn:codex:s:1", "role": "assistant", "content": "ghp_" + "a" * 36}
        cw = {"id": "turn:codex:s:2", "role": "tool_call", "content": "cat client_work/acme/x.py"}
        (sd / "b.jsonl.gz").write_bytes(_gz.compress("".join(json.dumps(r) + chr(10) for r in (leak, cw)).encode()))
        found = {f.name: f.status for f in inv_shards_are_safe_to_push(Artifacts(root))}
        check("T27 an unmasked token is caught", found["shards: no unmasked credential"], FAIL)
        check("T28 unstubbed client_work tool content is caught",
              found["shards: no client_work tool content"], FAIL)

    # T29-T31: client-record survival is judged by content, not by path.
    def _client_root(tmp: str, snapshot: List[Dict[str, Any]], corpus: List[Dict[str, Any]]) -> Path:
        tc = Path(tmp) / "jarvis_data" / "training_corpus"
        tc.mkdir(parents=True)
        (tc / "client_work_snapshot.jsonl").write_text(
            "".join(json.dumps(r) + chr(10) for r in snapshot), encoding="utf-8")
        (tc / "personalization_corpus.jsonl").write_text(
            "".join(json.dumps(r) + chr(10) for r in corpus), encoding="utf-8")
        (tc / "engineer_corpus.jsonl").write_text("", encoding="utf-8")
        return Path(tmp)

    cell = "import pyspark.sql.functions as F" + " " * 80
    pr = {"source_type": "professional_reasoning"}
    with tempfile.TemporaryDirectory() as tmp:
        root = _client_root(tmp,
                            [{"corpus": "personalization", "source_path": "a.py#block0", "text": cell},
                             {"corpus": "personalization", "source_path": "b.py#block0", "text": cell}],
                            [{**pr, "source_path": "a.py#block0", "text": cell}])
        check("T29 a path the corpus deduplicated, its text kept, is NOT reported lost",
              inv_client_records_survive(Artifacts(root))[0].status, OK)
    with tempfile.TemporaryDirectory() as tmp:
        root = _client_root(tmp,
                            [{"corpus": "personalization", "source_path": "a.py#block0", "text": cell},
                             {"corpus": "personalization", "source_path": "c.py#block0", "text": "unique cell " * 20}],
                            [{**pr, "source_path": "a.py#block0", "text": cell}])
        check("T30 a snapshot record whose text is gone from the corpus IS reported lost",
              inv_client_records_survive(Artifacts(root))[0].status, FAIL)
    with tempfile.TemporaryDirectory() as tmp:
        root = _client_root(tmp,
                            [{"corpus": "personalization", "source_path": f"x{i}.py#b", "text": f"cell {i} " * 30}
                             for i in range(5)],
                            [])
        check("T31 the 2026-09-28 shape (a rebuild that drops every client record) still fails",
              inv_client_records_survive(Artifacts(root))[0].status, FAIL)

    print("=" * 78)
    print("  check_pipeline self-test")
    print("=" * 78)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 78)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 78)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Check invariants between corpus artifacts.")
    p.add_argument("--verbose", action="store_true", help="show example offenders")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return _self_test()
    return report(run(), verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
