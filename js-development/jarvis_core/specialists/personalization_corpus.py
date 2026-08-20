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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from jarvis_core.config import DATA_ROOT, SPECIALIST_CORPUS_ROOT
from jarvis_core.memory.chunking import RecursiveWordChunker
from jarvis_core.memory.cognitive_index import (
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

    print(f"\n  {'Source':<16} {'Records':>10} {'Chars':>12} {'Dropped (dup)':>14}")
    print("  " + "-" * 56)
    for name, counts in stats.per_source.items():
        dropped = stats.dropped_near_duplicates.get(name, 0)
        note = "  (source missing)" if counts["records"] == 0 else ""
        print(f"  {name:<16} {counts['records']:>10,} {counts['chars']:>12,} {dropped:>14,}{note}")
    print("  " + "-" * 56)
    print(f"  {'TOTAL':<16} {stats.total_records:>10,}")

    size = stats.output_path.stat().st_size
    print(f"\n  Output: {stats.output_path} ({size:,} bytes)")
    print("=" * 70)


if __name__ == "__main__":
    main()
