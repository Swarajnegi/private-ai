"""
personalization_corpus.py

Stage 5: Personalization Adapter — Training Corpus Assembly.

Run with:
    PYTHONPATH=js-development python3 -m jarvis_core.specialists.personalization_corpus

=============================================================================
THE BIG PICTURE: the adapter that is JARVIS, not a domain specialist
=============================================================================

Every other adapter in the roster answers "what does this system know about
a DOMAIN." This one answers "what does this system know about its OWNER."
It is not the router (`brain/router.py` classifies intent — a different,
narrower job). It is the layer that should make any answer, from any
specialist, sound like it came from something that actually knows the user
rather than something reading a briefing note.

Without a real personalization corpus:
    -> "JARVIS knows me" stays a context-injection story: cognitive_profile.md
       re-read every session, capped at 2500 chars inside a 6000-char boot
       budget (brain/context_injector.py) — a cheat sheet, not internalization
    -> personal_life.md, the richest non-work material that exists, reaches
       nothing at all — verified: zero modules reference it
    -> The user's own 460 captured prompts — how they ACTUALLY write, ask,
       push back — are used for nothing

With this module:
    -> One inspectable JSONL of everything that constitutes "who the owner is"
    -> Two distinct signal types, tagged separately because they teach
       different things:
         FACTS about the user (profile patterns, life notes, philosophy)
         VOICE of the user (their own raw messages — tone, cadence, how they
         phrase a correction, what terseness means coming from them)
    -> A corpus that can be re-assembled in one command as the user's life
       and the KB keep changing

=============================================================================
THE FLOW
=============================================================================

STEP 1: Five source iterators. KB-derived sources query the structured
        cognitive index (memory/cognitive_index.py) rather than re-scanning
        knowledge_base.jsonl by hand — that index exists precisely so
        "personality dimension" is a query, not a substring guess.
        |
STEP 2: KB sources are UNIONED and deduped by entry id: the identity/
        philosophy tag-set overlaps heavily with the personality dimension
        (most identity entries ARE Cognitive_Pattern), so a naive
        concatenation would double-weight the user's core axioms.
        |
STEP 3: Voice sources are capped for near-duplicates (same repeated prompt
        across debugging sessions) using the same prefix-cluster approach
        proven in engineer_corpus.py — verified there against real data,
        where 122 near-dupes were removed.
        |
STEP 4: All records stream through ONE open file handle; stats tally as a
        byproduct of the write loop. Output stays model-agnostic (raw
        source-tagged text, not a rendered chat template) — the template
        depends on the tokenizer chosen at training time.

DELIBERATELY EXCLUDED — cognitive_profile.md. It is SYNTHESIZED FROM the
same KB entries this module already ingests (scripts/profile_synth.py reads
the KB and distills it). Including both would train twice on the same
content and silently over-weight whichever patterns the synthesizer happened
to rank top-8 that day. The KB entries are the source; the profile is a
derived view of them.

KNOWN DUPLICATION — CorpusRecord / cluster-capping logic is mirrored from
engineer_corpus.py rather than shared. Deliberate: two instances is not yet
a pattern (rule of three), and factoring a common module today would mean
destabilizing engineer_corpus.py, which is verified against real data. When
a third specialist corpus appears, extract specialists/corpus_common.py.

LAYER: Specialists (Corpus Assembly)
=============================================================================
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from jarvis_core.agent.capture import redact
from jarvis_core.config import DATA_ROOT, SPECIALIST_CORPUS_ROOT
from jarvis_core.memory.chunking import RecursiveWordChunker
from jarvis_core.memory.cognitive_index import (
    query_all,
    query_by_dimension,
    query_by_tag,
    rebuild_index,
)


# =============================================================================
# Part 1: CONSTANTS
# =============================================================================

_CORPUS_CHUNK_CHAR_LIMIT = 4000
_CORPUS_CHUNK_OVERLAP = 400

_PERSONAL_LIFE_PATH = Path(DATA_ROOT) / "personal_life.md"
_CONVERSATIONS_DIR = Path(DATA_ROOT) / "conversations"
_OBSERVATION_QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"

# Tags marking entries about who the user IS, beyond the behavioural patterns
# already covered by the personality dimension. Heavy overlap is expected and
# handled by id-dedup in _iter_kb_identity_records.
_IDENTITY_TAGS = ("identity", "philosophy", "legacy", "motivation-architecture")

# Entries OUTSIDE the personality dimension that still encode how the user
# decides. Measured 2026-08-20 against the real KB: of 370 non-identity entries,
# 105 carry these markers (~41K tokens), 3 are pure build-log prose, 262 are
# technical facts belonging to the Engineer corpus rather than here. A Decision
# recording that the user rejected an approach and why IS personality data --
# it shows their reasoning, not just a project outcome.
_USER_SIGNAL = re.compile(
    r"user (pushed back|corrected|rejected|chose|said|asked|explicitly|overrode"
    r"|flagged|wants|framed)|user's own|per the user|DIRECTIVE",
    re.IGNORECASE,
)

# Build-log openers: my prose about my own work. Excluded explicitly -- training
# on these teaches the adapter to imitate build summaries, not the user.
_BUILD_LOG = re.compile(
    r"^(Built|Shipped|Added|Wired|Fixed|Created|Implemented|Verified)", re.IGNORECASE
)

# First-person reasoning the user owns, written down outside the KB.
# strategy.md qualifies because Sec1 (profile/constraints/strategic identity),
# Sec5.6 (guardrails they set against their own impulses) and Sec8 (discipline
# notes) are genuinely about them. DELIBERATELY EXCLUDED: knowledge/Job Switch/
# (my teaching roadmaps written FOR them, not their reasoning) and
# Data_Engineering_Lessons.md (already ingested by engineer_corpus as de_corpus --
# including it here would double-count it across the blend).
_WRITTEN_REASONING_PATHS = (
    Path(DATA_ROOT).parent / "knowledge" / "Finance" / "strategy.md",
)

# --- Source 7: PUBLISHED LITERATURE (added 2026-08-26) ----------------------
# The user's own long-form published writing: three Substack essays (2024-2025)
# and two poems posted to X. This is the PUREST voice material in the entire
# corpus and it sat unused for months.
#
# WHY IT WAS MISSED, worth recording so the same class of miss does not repeat:
# the files were image-only PDFs and .webp/.jpg screenshots. A grep for
# "unseen graves" scoped to *.md and *.txt returned nothing, and I concluded
# "nowhere in this repository" — a false negative produced by searching only the
# formats I expected. The material had been sitting in knowledge/literature/
# since May. Text was recovered 2026-08-26 from the live Substack posts (the
# local PDF exports clip the right margin, so transcribing them would have
# meant guessing words in a corpus whose whole purpose is fidelity to the
# user's voice) and from visual reading for the two poems.
#
# WHY THIS RANKS ABOVE CONVERSATION CAPTURE: it is unmediated. No question of
# mine shaped it, no assistant turn is interleaved, nothing was summarized. It
# is also the PRIMARY SOURCE for KB patterns previously recorded only as my
# observations -- "Are you able to give yourself goosebumps via your
# imagination?" (visceral_imagination_test) and "Cowardice, in its truest form
# is to not be what you are. Greatest sin? To be a fraction of what you could
# be." (insufficiency_as_sin) are both verbatim from the Napoleon essay,
# written October 2024.
#
# Purity tag "authored" distinguishes it from written_reasoning's "mixed"
# (strategy.md carries generic tax/platform reference alongside the personal
# reasoning); every line here is the user's.
_LITERATURE_DIR = Path(DATA_ROOT).parent / "knowledge" / "literature"

# --- Source 6: PROFESSIONAL REASONING (added 2026-08-24) --------------------
# WHY THIS EXISTS, and why the previous classification was wrong.
#
# Until now the client work went ONLY to engineer_corpus, on the theory that
# technical content belongs to the technical adapter. The user rejected the
# premise the whole split rested on (KB 495):
#
#   "no one writes code on their own these days when every company is giving
#    out claude codes and codex's. So it isn't about gathering data where I've
#    handwritten code, It's all about how I understand code, how I actually
#    understand better, how I architect stuff ... my experience and what kind
#    of problems i've faced and resolved"
#
# They are right, and it invalidates the metric I had been scoring the corpus
# with. Keystroke authorship is a pre-agentic-coding proxy: it measures who
# operated the tool, not who held the judgment. What makes text personalization
# material is whether the REASONING is the user's -- and a decision recorded
# with its rejected alternatives attached is theirs regardless of what emitted
# the surrounding YAML.
#
# So the reasoning prose is extracted separately, here. Measured:
#   test_cases_orchestrator_job.yml   930 of 1,493 lines are comment (62%)
#   test_cases/*.py (20 files)      2,879 of 9,456 lines (30%)
#   SESSION_LEARNINGS.md              917 lines, ~all of it
# ~4,700 lines of architectural decision-making from two client projects.
#
# DELIBERATE OVERLAP, not an oversight: these comment lines ALSO remain inside
# engineer_corpus's client_work records, because a comment stripped from the
# code it explains loses the thing it refers to. So the model sees this slice
# twice -- once in context as project material, once alone as voice material.
# That is intentional weighting of the highest-value ~28% of the client corpus,
# and it is reported in the stats table so the double-count stays visible
# rather than silently inflating a total.
#
# AUTHORED PATHS ONLY. The surrounding repo has six committers; team-authored
# comments are good engineering but they are not this user's voice, and the
# whole point of this source is voice. Markers mirror
# engineer_corpus._CLIENT_WORK_AUTHORED_MARKERS -- keep them in sync.
_CLIENT_WORK_ROOT = Path(DATA_ROOT).parent / "client_work"
_PROF_REASONING_MARKERS = (
    "gld_deepclone/test_cases/",
    "test_cases_orchestrator_job.yml",
    "SESSION_LEARNINGS.md",
)
_PROF_REASONING_EXTENSIONS = (".py", ".yml", ".yaml", ".md")
_CLIENT_WORK_JUNK_MARKERS = (":Zone.Identifier", ":sec.endpointdlp")

# Comment lines that carry no reasoning. Notebook cell separators, linter
# pragmas, and section banners are structure, not thought.
_PROSE_NOISE = re.compile(
    r"^(COMMAND -+|MAGIC\s*$|DBTITLE|Databricks notebook source|-{3,}|={3,}|#+\s*$)"
    r"|^noqa|^type:\s*ignore|^pylint|^fmt:\s*(on|off)$",
    re.IGNORECASE,
)

# A reasoning block has to be long enough to contain a reason. Tuned against
# the real files: 200 chars keeps the decision records ("AT_LEAST_ONE_SUCCESS
# is the only choice that is both reachable AND halts on failure...") and drops
# one-line labels. Raising it starts losing real content; lowering it lets in
# "# tables-only" and "# see below".
_MIN_PROSE_BLOCK_CHARS = 200

# Same near-duplicate capping proven against real data in engineer_corpus.py:
# the user asks the same question across separate debugging sessions, and none
# of it is exact-duplicate text, so exact dedup misses all of it.
_DEDUP_PREFIX_LEN = 100
_MAX_PER_CLUSTER = 2

_DEFAULT_OUTPUT_PATH = SPECIALIST_CORPUS_ROOT / "personalization_corpus.jsonl"


def _chunker() -> RecursiveWordChunker:
    return RecursiveWordChunker(char_limit=_CORPUS_CHUNK_CHAR_LIMIT, overlap=_CORPUS_CHUNK_OVERLAP)


def _cluster_key(text: str) -> str:
    return " ".join(text.split()).lower()[:_DEDUP_PREFIX_LEN]


# =============================================================================
# Part 2: RECORD SHAPES
# =============================================================================

@dataclass(frozen=True)
class CorpusRecord:
    """One training example, traceable back to its exact origin."""
    source_type: str
    source_path: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorpusStats:
    per_source: Dict[str, Dict[str, int]]
    total_records: int
    output_path: Path
    dropped_near_duplicates: Dict[str, int] = field(default_factory=dict)


# =============================================================================
# Part 3: FACTS — WHO THE OWNER IS
# =============================================================================

def iter_personal_life_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    The private life notes: family, living situation, relationships,
    friendships, health history, professional recognition. Local-only and
    gitignored (never pushed to the public repo) — but note this DOES leave
    the machine if the assembled corpus is uploaded to RunPod for training.
    """
    try:
        text = _PERSONAL_LIFE_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    if not text.strip():
        return
    for i, chunk in enumerate(_chunker().chunk(text)):
        yield CorpusRecord(
            source_type="personal_life",
            source_path=f"personal_life.md#chunk{i}",
            text=chunk,
            metadata={"visibility": "private-local-only"},
        )


def iter_kb_identity_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Union of the personality dimension and the identity/philosophy tag-set,
    deduped by entry id. Queried through the structured cognitive index, not
    a hand-rolled scan of knowledge_base.jsonl.
    """
    seen_ids = set()
    chunker = _chunker()

    def emit(entry, origin: str) -> Generator[CorpusRecord, None, None]:
        if entry.id in seen_ids or not entry.content.strip():
            return
        seen_ids.add(entry.id)
        for i, chunk in enumerate(chunker.chunk(entry.content)):
            yield CorpusRecord(
                source_type="kb_identity",
                source_path=f"kb#{entry.id}#chunk{i}",
                text=chunk,
                metadata={
                    "kb_type": entry.type,
                    "dimension": entry.cognitive_dimension,
                    "tags": list(entry.tags),
                    "matched_via": origin,
                    "timestamp": entry.timestamp,
                },
            )

    for entry in query_by_dimension("personality"):
        yield from emit(entry, "dimension:personality")
    for tag in _IDENTITY_TAGS:
        for entry in query_by_tag(tag):
            yield from emit(entry, f"tag:{tag}")


def iter_kb_judgment_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Entries outside the personality dimension that still record the user's
    OWN choices, pushbacks and corrections. Tagged as its own source_type
    (not folded into kb_identity) so a training run can weight or ablate
    "how they reason" separately from "who they are" -- the two teach
    different things and shouldn't be silently averaged.

    Skips anything kb_identity already takes, and skips build-log prose.
    """
    chunker = _chunker()
    for entry in query_all():
        if entry.cognitive_dimension == "personality":
            continue
        if any(t in entry.tags for t in _IDENTITY_TAGS):
            continue
        content = entry.content
        if not content.strip() or not _USER_SIGNAL.search(content):
            continue
        if _BUILD_LOG.match(content.strip()):
            continue
        for i, chunk in enumerate(chunker.chunk(content)):
            yield CorpusRecord(
                source_type="kb_judgment",
                source_path=f"kb#{entry.id}#chunk{i}",
                text=chunk,
                metadata={
                    "kb_type": entry.type,
                    "dimension": entry.cognitive_dimension,
                    "tags": list(entry.tags),
                    "timestamp": entry.timestamp,
                },
            )


def iter_written_reasoning_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    Long-form documents holding the user's own reasoning about their life
    and constraints (see _WRITTEN_REASONING_PATHS for what's included and,
    more importantly, what's excluded and why). Mixed-purity by nature --
    strategy.md also contains generic tax/platform reference material --
    so it gets its own source_type rather than being blended in silently.
    """
    chunker = _chunker()
    for path in _WRITTEN_REASONING_PATHS:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        for i, chunk in enumerate(chunker.chunk(text)):
            yield CorpusRecord(
                source_type="written_reasoning",
                source_path=f"{path.name}#chunk{i}",
                text=chunk,
                metadata={"file": path.name, "purity": "mixed"},
            )


def iter_literature_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    The user's published essays and poems — see _LITERATURE_DIR for why this is
    the highest-purity voice source available and why it went unnoticed.

    Reads only the .md transcriptions, not the source PDFs/images they were
    recovered from; those stay in place as provenance.
    """
    if not _LITERATURE_DIR.is_dir():
        return
    chunker = _chunker()
    for path in sorted(_LITERATURE_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        for i, chunk in enumerate(chunker.chunk(text)):
            yield CorpusRecord(
                source_type="literature",
                source_path=f"{path.name}#chunk{i}",
                text=chunk,
                metadata={
                    "file": path.name,
                    "purity": "authored",
                    "form": "poetry" if "poem" in path.name.lower() else "essay",
                },
            )


def _extract_prose_blocks(text: str, suffix: str) -> Generator[str, None, None]:
    """
    Consecutive comment lines, grouped into blocks and stripped of markers.

    Groups rather than yielding per line because a reasoning block is the unit
    that carries an argument — a single line out of the middle of one ("# only
    reached on the TGT leg now") is unintelligible alone. Blank lines and any
    line of actual code end the current block.

    .md files are already prose and pass through whole.
    """
    if suffix == ".md":
        if text.strip():
            yield text
        return

    block: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            # Databricks notebooks prefix markdown cells with "MAGIC %md" and
            # "MAGIC" per line; strip both so the prose reads as prose.
            if body.startswith("MAGIC"):
                body = body[len("MAGIC"):].strip()
                if body.startswith("%md"):
                    body = body[len("%md"):].strip()
            if body and not _PROSE_NOISE.match(body):
                block.append(body)
            continue
        # A blank line inside a comment run is a paragraph break, not an end.
        if not line and block:
            block.append("")
            continue
        if block:
            joined = "\n".join(block).strip()
            if len(joined) >= _MIN_PROSE_BLOCK_CHARS:
                yield joined
            block = []
    if block:
        joined = "\n".join(block).strip()
        if len(joined) >= _MIN_PROSE_BLOCK_CHARS:
            yield joined


def iter_professional_reasoning_records() -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    The user's architectural reasoning, extracted from the client work they
    authored — comment blocks out of code and YAML, plus their hand-written
    learnings file whole.

    This is the source that answers "how do I architect, and what problems
    have I faced and resolved" (KB 495). It is deliberately NOT the code
    itself: engineer_corpus already carries that, and the code is the artifact
    while the comment is the judgment.

    Every record is redacted before it is yielded — same reason as
    engineer_corpus.iter_client_work_records: this corpus is uploaded for
    training, and the client_work quarantine is trusted not to be committed,
    not trusted to be secret-free.
    """
    base = _CLIENT_WORK_ROOT
    if not base.is_dir():
        return
    chunker = _chunker()
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _PROF_REASONING_EXTENSIONS:
            continue
        if any(m in path.name for m in _CLIENT_WORK_JUNK_MARKERS):
            continue
        rel = path.relative_to(base).as_posix()
        if not any(m in rel for m in _PROF_REASONING_MARKERS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for b, block in enumerate(_extract_prose_blocks(text, path.suffix.lower())):
            for i, chunk in enumerate(chunker.chunk(redact(block))):
                yield CorpusRecord(
                    source_type="professional_reasoning",
                    source_path=f"{rel}#block{b}.chunk{i}",
                    text=chunk,
                    metadata={
                        "file": rel,
                        "kind": "prose" if path.suffix.lower() == ".md" else "comment_block",
                    },
                )


# =============================================================================
# Part 4: VOICE — HOW THE OWNER ACTUALLY WRITES
# =============================================================================

def iter_user_voice_records(
    dropped: Optional[Dict[str, int]] = None,
) -> Generator[CorpusRecord, None, None]:
    """
    LAYER: Specialists (Corpus Assembly)

    The user's OWN messages only — never the assistant's. Facts teach what
    the user is; this teaches how they sound: cadence, terseness, how a
    correction gets phrased, what they bother to explain vs. assume.

    Assistant turns are excluded on purpose. Training on them would teach the
    adapter to imitate whichever model happened to answer (gpt-4o-mini,
    gemini-flash, Claude — the brain has swapped repeatedly), which is
    imitating a moving target, not learning the user.
    """
    cluster_counts: Dict[str, int] = {}

    def take(text: str) -> bool:
        key = _cluster_key(text)
        cluster_counts[key] = cluster_counts.get(key, 0) + 1
        if cluster_counts[key] > _MAX_PER_CLUSTER:
            if dropped is not None:
                dropped["user_voice"] = dropped.get("user_voice", 0) + 1
            return False
        return True

    if _CONVERSATIONS_DIR.is_dir():
        for path in sorted(_CONVERSATIONS_DIR.glob("*.jsonl")):
            try:
                handle = path.open("r", encoding="utf-8")
            except OSError:
                continue
            with handle:
                for line_no, raw in enumerate(handle):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        turn = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if turn.get("role") != "user":
                        continue
                    content = turn.get("content", "")
                    if not content.strip() or not take(content):
                        continue
                    yield CorpusRecord(
                        source_type="user_voice",
                        source_path=f"{path.name}#L{line_no}",
                        text=content,
                        metadata={"sub_source": "conversation_store", "ts": turn.get("ts")},
                    )

    if _OBSERVATION_QUEUE_PATH.is_file():
        try:
            handle = _OBSERVATION_QUEUE_PATH.open("r", encoding="utf-8")
        except OSError:
            return
        with handle:
            for line_no, raw in enumerate(handle):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obs = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                content = obs.get("user_text", "")
                if not content.strip() or not take(content):
                    continue
                yield CorpusRecord(
                    source_type="user_voice",
                    source_path=f"observation_queue.jsonl#L{line_no}",
                    text=content,
                    metadata={
                        "sub_source": "observation_queue",
                        "chat_label": obs.get("chat_label"),
                        "ts": obs.get("ts"),
                    },
                )


# =============================================================================
# Part 5: ASSEMBLY
# =============================================================================

_SOURCE_ITERATORS = (
    ("personal_life", lambda dropped: iter_personal_life_records()),
    ("kb_identity", lambda dropped: iter_kb_identity_records()),
    ("kb_judgment", lambda dropped: iter_kb_judgment_records()),
    ("written_reasoning", lambda dropped: iter_written_reasoning_records()),
    ("literature", lambda dropped: iter_literature_records()),
    ("professional_reasoning", lambda dropped: iter_professional_reasoning_records()),
    ("user_voice", lambda dropped: iter_user_voice_records(dropped=dropped)),
)


def assemble_corpus(output_path: Optional[Path] = None) -> CorpusStats:
    """
    LAYER: Specialists (Corpus Assembly)

    Rebuilds the cognitive index first so KB-derived sources reflect the
    current knowledge_base.jsonl rather than a stale snapshot, then streams
    every source through ONE open file handle.
    """
    rebuild_index()

    path = output_path or _DEFAULT_OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    per_source: Dict[str, Dict[str, int]] = {
        name: {"records": 0, "chars": 0} for name, _ in _SOURCE_ITERATORS
    }
    dropped: Dict[str, int] = {}
    total = 0

    with path.open("w", encoding="utf-8") as handle:
        for source_name, iterator_fn in _SOURCE_ITERATORS:
            for record in iterator_fn(dropped):
                handle.write(json.dumps({
                    "source_type": record.source_type,
                    "source_path": record.source_path,
                    "text": record.text,
                    "metadata": record.metadata,
                }, ensure_ascii=False) + "\n")
                per_source[source_name]["records"] += 1
                per_source[source_name]["chars"] += len(record.text)
                total += 1

    return CorpusStats(
        per_source=per_source,
        total_records=total,
        output_path=path,
        dropped_near_duplicates=dropped,
    )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> None:
    print("=" * 70)
    print("  JARVIS: Personalization Adapter — Corpus Assembly")
    print("=" * 70)

    stats = assemble_corpus()

    print(f"\n  {'Source':<24} {'Records':>9} {'Chars':>12} {'~Tokens':>10} {'Dropped':>9}")
    print("  " + "-" * 67)
    for name, counts in stats.per_source.items():
        dropped = stats.dropped_near_duplicates.get(name, 0)
        note = "  (source missing)" if counts["records"] == 0 else ""
        print(f"  {name:<24} {counts['records']:>9,} {counts['chars']:>12,} "
              f"{counts['chars'] // 4:>10,} {dropped:>9,}{note}")
    print("  " + "-" * 67)
    total_chars = sum(c["chars"] for c in stats.per_source.values())
    print(f"  {'TOTAL':<24} {stats.total_records:>9,} {total_chars:>12,} {total_chars // 4:>10,}")

    # professional_reasoning is deliberately ALSO present inside
    # engineer_corpus's client_work records (the comment lives with the code it
    # explains). Say so here rather than let a reader treat these totals as
    # disjoint from the Engineer corpus — see _PROF_REASONING_MARKERS.
    pr = stats.per_source.get("professional_reasoning", {}).get("chars", 0)
    if pr:
        print(f"\n  NOTE: professional_reasoning ({pr:,} chars) is intentionally "
              f"double-counted —\n  the same comment blocks also remain in "
              f"engineer_corpus's client_work records.")

    size = stats.output_path.stat().st_size
    print(f"\n  Output: {stats.output_path} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
