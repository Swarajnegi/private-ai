"""
kb_compact.py

JARVIS Memory hygiene tool — compact knowledge_base.jsonl by pruning expired
entries and de-duplicating semantically similar ones (within type), with
provenance preservation, atomic write, and an append-only audit log.

Run with:
    python scripts/kb_compact.py                  # dry-run (default)
    python scripts/kb_compact.py --force          # apply changes
    python scripts/kb_compact.py --threshold 0.93 # custom dedup threshold
    python scripts/kb_compact.py --no-expire      # skip expiry pruning
    python scripts/kb_compact.py --no-dedupe      # skip semantic dedup
    python scripts/kb_compact.py -v               # verbose dedup reasons

This script demonstrates:
    1. Embedder via Dependency Injection — Memory layer never imports an LLM client
    2. Expiry pruning — date-based TTL respecting `expiry: "Permanent"`
    3. Semantic dedup — cosine + tag-Jaccard structural rule, type-isolated
    4. Quality-aware merge — keep the richer entry, union tags, preserve provenance
    5. Atomic write — tmp + fsync + os.replace; .bak preserved
    6. Audit log — every run appends to compaction_log.jsonl

LAYER: Memory

=============================================================================
THE BIG PICTURE
=============================================================================

Without a structured compactor:
    -> KB grows unbounded as build progresses
    -> Duplicates poison RAG (top-k returns 3 paraphrases of the same insight)
    -> Old expired plans (sprint timelines, transient decisions) stay forever
    -> search_memory.py recall degrades with noise
    -> Stage 2.5.8 cannot gate Stage 3 entry

With this compactor:
    -> Expiry pruning enforces TTL on transient entries
    -> Semantic dedup collapses paraphrases (>=0.95 cosine + tag overlap)
    -> Provenance preserved: earliest timestamp wins on equal-quality merge
    -> Audit log records what changed, why, and when (forensic recovery)
    -> Atomic write: a crash mid-compaction never corrupts the KB

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Load KB JSONL into typed KBEntry tuples (one per line, line_no preserved)
        |
        v
STEP 2: Build embedder (default: MiniLM-L6-v2 CPU; DI-overridable)
        |
        v
STEP 3: If --expire: filter entries whose `expiry` ISO date < today
        |
        v
STEP 4: If --dedupe: within each `type`, find pairs with
            cosine >= threshold AND tag_jaccard >= tag_overlap_threshold
        Pick winner by quality (DIRECTIVE > content_len > tag_count > earliest_ts)
        Merge tags into winner; record loser as deduped_into:<winner_line>
        |
        v
STEP 5: Build final entry list (kept + merged winners; losers and expired dropped)
        |
        v
STEP 6: If --dry-run (default): print report, don't write
        If --force: write KB.bak, atomic-write new KB
        |
        v
STEP 7: Append run summary to jarvis_data/compaction_log.jsonl (always)

=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

# Make jarvis_core importable when run as a script from repo root or scripts/
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import KB_PATH, DEFAULT_EMBEDDING_MODEL  # noqa: E402


# =============================================================================
# Part 1: TYPES
# =============================================================================

Embedder = Callable[[Sequence[str]], np.ndarray]
"""Encodes a list of strings to a (n, dim) numpy array. Must be DI-compatible."""


@dataclass(frozen=True)
class KBEntry:
    """One JSONL line, parsed and typed. `raw` carries the full original dict."""
    line_no: int
    timestamp: str
    type: str
    tags: Tuple[str, ...]
    content: str
    expiry: str
    raw: Mapping[str, object]


@dataclass(frozen=True)
class CompactionVerdict:
    """What happened to one entry during compaction."""
    line_no: int
    action: str          # "kept" | "expired" | "deduped_into:<line>"
    reason: str
    similarity: Optional[float] = None


@dataclass(frozen=True)
class CompactionReport:
    """End-to-end summary of one run."""
    total_before: int
    total_after: int
    expired: Tuple[CompactionVerdict, ...]
    deduped: Tuple[CompactionVerdict, ...]
    timestamp: str


# =============================================================================
# Part 2: LOADER
# =============================================================================

def load_kb(path: Path) -> Tuple[KBEntry, ...]:
    """Read JSONL into typed entries; line_no is 1-based. Fails loud on malformed JSON."""
    entries: List[KBEntry] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"line {i}: invalid JSON ({e})") from e
            entries.append(KBEntry(
                line_no=i,
                timestamp=str(obj.get("timestamp", "")),
                type=str(obj.get("type", "")),
                tags=tuple(obj.get("tags", []) or ()),
                content=str(obj.get("content", "")),
                expiry=str(obj.get("expiry", "Permanent")),
                raw=obj,
            ))
    return tuple(entries)


# =============================================================================
# Part 3: EXPIRY FILTER
# =============================================================================

def _is_expired(entry: KBEntry, today: date) -> bool:
    """`Permanent` (or unparseable expiry) -> never expired. ISO date -> expired if today > date."""
    if entry.expiry == "Permanent" or not entry.expiry:
        return False
    iso_part = entry.expiry[:10]
    try:
        expiry_date = date.fromisoformat(iso_part)
    except ValueError:
        return False  # malformed expiry: keep (fail safe, never silently drop)
    return today > expiry_date


def filter_expired(
    entries: Sequence[KBEntry],
    today: Optional[date] = None,
) -> Tuple[Tuple[KBEntry, ...], Tuple[CompactionVerdict, ...]]:
    """Returns (entries-still-valid, verdicts-for-expired)."""
    today = today or date.today()
    kept: List[KBEntry] = []
    expired: List[CompactionVerdict] = []
    for e in entries:
        if _is_expired(e, today):
            expired.append(CompactionVerdict(
                line_no=e.line_no,
                action="expired",
                reason=f"expiry={e.expiry} < today={today.isoformat()}",
            ))
        else:
            kept.append(e)
    return tuple(kept), tuple(expired)


# =============================================================================
# Part 4: SEMANTIC DEDUP
# =============================================================================

def _tag_jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """|intersection| / |union|; 0.0 if both empty (treat as no overlap signal)."""
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _quality_tuple(entry: KBEntry) -> Tuple[int, int, int]:
    """
    Higher tuple wins. Components, in order of priority:
      1. has_DIRECTIVE in content (1/0) — preserve action-bearing entries
      2. content length — longer = more detail
      3. tag count — more tags = more searchable surfaces
    Ties are broken by earliest-timestamp in `_pick_winner`.
    """
    return (int("DIRECTIVE" in entry.content), len(entry.content), len(entry.tags))


def _pick_winner(a: KBEntry, b: KBEntry) -> Tuple[KBEntry, KBEntry]:
    """Return (winner, loser) by quality; earliest-timestamp wins on equal quality."""
    qa, qb = _quality_tuple(a), _quality_tuple(b)
    if qa != qb:
        return (a, b) if qa > qb else (b, a)
    return (a, b) if a.timestamp <= b.timestamp else (b, a)


def _merge_tags_into_winner(winner: KBEntry, loser: KBEntry) -> KBEntry:
    """Return winner with tag-union (loser's novel tags appended in encounter order)."""
    seen = set(winner.tags)
    merged = list(winner.tags)
    for t in loser.tags:
        if t not in seen:
            merged.append(t)
            seen.add(t)
    new_raw = dict(winner.raw)
    new_raw["tags"] = merged
    return KBEntry(
        line_no=winner.line_no,
        timestamp=winner.timestamp,
        type=winner.type,
        tags=tuple(merged),
        content=winner.content,
        expiry=winner.expiry,
        raw=new_raw,
    )


def dedupe(
    entries: Sequence[KBEntry],
    embedder: Embedder,
    *,
    cosine_threshold: float,
    tag_overlap_threshold: float,
    same_type_only: bool = True,
) -> Tuple[Tuple[KBEntry, ...], Tuple[CompactionVerdict, ...]]:
    """
    Identify duplicates by cosine(>= threshold) AND tag_jaccard(>= threshold).
    Same-type only by default — a Decision and a Failure on the same topic
    capture different signals and must both stay.

    EXECUTION FLOW:
    1. Embed contents and L2-normalize
    2. Iterate upper-triangle pairs (i, j>i)
    3. For each pair passing cosine + same-type + tag-jaccard gates:
         resolve i and j to their CURRENT winner (handle prior merges)
         pick winner by quality_tuple; record loser; merge tags into winner
    4. Return (kept_entries_with_merged_tags, verdicts_for_losers)
    """
    n = len(entries)
    if n < 2:
        return tuple(entries), ()

    embeddings = np.asarray(embedder([e.content for e in entries]))
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-12
    embeddings = embeddings / norms
    sim_matrix = embeddings @ embeddings.T

    # state[line_no] -> current entry (winner after merges)
    state: Dict[int, KBEntry] = {e.line_no: e for e in entries}
    # redirects[loser_line] -> winner_line
    redirects: Dict[int, int] = {}
    verdicts: List[CompactionVerdict] = []

    def resolve(line_no: int) -> int:
        """Follow redirect chain to current winner line."""
        seen = set()
        while line_no in redirects:
            if line_no in seen:
                break  # defensive cycle break (shouldn't happen)
            seen.add(line_no)
            line_no = redirects[line_no]
        return line_no

    for i in range(n):
        for j in range(i + 1, n):
            sim = float(sim_matrix[i, j])
            if sim < cosine_threshold:
                continue
            ei, ej = entries[i], entries[j]
            if same_type_only and ei.type != ej.type:
                continue
            tag_overlap = _tag_jaccard(ei.tags, ej.tags)
            if tag_overlap < tag_overlap_threshold:
                continue

            wi_line = resolve(ei.line_no)
            wj_line = resolve(ej.line_no)
            if wi_line == wj_line:
                continue  # already merged transitively
            wi, wj = state[wi_line], state[wj_line]
            winner, loser = _pick_winner(wi, wj)
            merged = _merge_tags_into_winner(winner, loser)
            state[winner.line_no] = merged
            redirects[loser.line_no] = winner.line_no
            verdicts.append(CompactionVerdict(
                line_no=loser.line_no,
                action=f"deduped_into:{winner.line_no}",
                reason=f"cosine={sim:.4f} tag_jaccard={tag_overlap:.2f} type={ei.type}",
                similarity=sim,
            ))

    kept_lines = sorted({e.line_no for e in entries} - set(redirects.keys()))
    kept = tuple(state[ln] for ln in kept_lines)
    return kept, tuple(verdicts)


# =============================================================================
# Part 5: ATOMIC WRITER
# =============================================================================

def write_atomic(entries: Sequence[KBEntry], path: Path) -> None:
    """
    Write entries as JSONL via tmp + fsync + os.replace (POSIX-atomic rename).

    EXECUTION FLOW:
    1. If path exists: copy bytes to path.with_suffix(path.suffix + ".bak")
    2. Open NamedTemporaryFile in path.parent
    3. Write each entry's raw dict as one JSON line + \\n
    4. flush() + fsync() to force kernel buffer to disk
    5. os.replace(tmp, path) — atomic on POSIX, near-atomic on Windows
    6. On any exception, unlink tmp and re-raise (original kb intact)
    """
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_bytes(path.read_bytes())

    fd, tmp_str = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e.raw, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


# =============================================================================
# Part 6: AUDIT LOG (machine-local; gitignored)
# =============================================================================

AUDIT_LOG_PATH = KB_PATH.parent / "compaction_log.jsonl"


def append_audit(report: CompactionReport, args_dict: Mapping[str, object]) -> None:
    """Append one JSON record per run; never read by JARVIS at runtime."""
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": report.timestamp,
        "total_before": report.total_before,
        "total_after": report.total_after,
        "n_expired": len(report.expired),
        "n_deduped": len(report.deduped),
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in args_dict.items()},
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# =============================================================================
# Part 7: REPORT FORMATTING
# =============================================================================

def format_report(report: CompactionReport, *, dry_run: bool, verbose: bool) -> str:
    """Human-readable compaction report — printed regardless of --force."""
    lines: List[str] = []
    sep = "=" * 72
    mode = "DRY-RUN (no changes will be written)" if dry_run else "WRITE (changes applied)"
    lines.append(sep)
    lines.append(f"  KB COMPACTION REPORT  -  {mode}")
    lines.append(f"  Generated: {report.timestamp}")
    lines.append(sep)
    lines.append(f"  Total before:  {report.total_before}")
    lines.append(f"  Expired:       {len(report.expired)}")
    lines.append(f"  Deduped:       {len(report.deduped)}")
    lines.append(f"  Total after:   {report.total_after}")
    lines.append("-" * 72)

    if report.expired:
        lines.append("EXPIRED (TTL pruned):")
        for v in report.expired:
            lines.append(f"  L{v.line_no:>4}: {v.reason}")
        lines.append("")

    if report.deduped:
        lines.append("DEDUPED (collapsed into winner; tags merged):")
        for v in report.deduped:
            sim = f"{v.similarity:.4f}" if v.similarity is not None else "n/a"
            lines.append(f"  L{v.line_no:>4} -> {v.action}  (cos={sim})")
            if verbose:
                lines.append(f"        reason: {v.reason}")
        lines.append("")

    if not report.expired and not report.deduped:
        lines.append("No entries flagged. KB already compact at current thresholds.")
        lines.append("")

    lines.append(sep)
    if dry_run:
        lines.append("  Re-run with --force to apply.  Backup will be written to KB.bak.")
        lines.append(sep)
    return "\n".join(lines)


# =============================================================================
# Part 8: DEFAULT EMBEDDER (sentence-transformers, CPU)
# =============================================================================

def build_default_embedder() -> Embedder:
    """Lazy-load MiniLM-L6-v2 on first call. CPU-only, ~90MB RAM, ~1-2s for 200 entries."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)

    def encode(texts: Sequence[str]) -> np.ndarray:
        return np.asarray(model.encode(list(texts), show_progress_bar=False))

    return encode


# =============================================================================
# Part 9: ORCHESTRATION
# =============================================================================

HEARTBEAT_EXEMPT_TAG = "heartbeat-emitted"
"""
Stage 3.5 sleep-time consolidation writes transient state observations carrying this tag
(e.g., 5 consecutive heartbeats observing 'user in Flow state'). They LOOK like
near-duplicates by design and would be displaced by structural-rule dedup; a separate
stream-compactor (Stage 3.5 work) handles them per session. See KB Decision 2026-05-13
metacognitive-integration.
"""


def compact(
    entries: Sequence[KBEntry],
    embedder: Optional[Embedder],
    *,
    do_expire: bool,
    do_dedupe: bool,
    cosine_threshold: float,
    tag_overlap_threshold: float,
) -> Tuple[CompactionReport, Tuple[KBEntry, ...]]:
    """Apply (optional) expiry + (optional) dedup; return (report, surviving_entries).

    Policy: entries tagged `HEARTBEAT_EXEMPT_TAG` bypass dedup entirely and pass through
    unchanged. dedup() itself stays a pure algorithm; the exemption lives one level up.
    """
    total_before = len(entries)
    expired: Tuple[CompactionVerdict, ...] = ()
    if do_expire:
        entries, expired = filter_expired(entries)

    deduped: Tuple[CompactionVerdict, ...] = ()
    if do_dedupe:
        if embedder is None:
            raise ValueError("dedupe=True requires an embedder")
        excluded = tuple(e for e in entries if HEARTBEAT_EXEMPT_TAG in e.tags)
        candidates = tuple(e for e in entries if HEARTBEAT_EXEMPT_TAG not in e.tags)
        candidates, deduped = dedupe(
            candidates, embedder,
            cosine_threshold=cosine_threshold,
            tag_overlap_threshold=tag_overlap_threshold,
        )
        entries = tuple(sorted(excluded + candidates, key=lambda e: e.line_no))

    report = CompactionReport(
        total_before=total_before,
        total_after=len(entries),
        expired=expired,
        deduped=deduped,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return report, tuple(entries)


# =============================================================================
# Part 10: CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="kb_compact",
        description="Compact knowledge_base.jsonl: prune expired + dedup similar entries.",
    )
    p.add_argument("--force", action="store_true",
                   help="Apply changes (default: dry-run only)")
    p.add_argument("--no-expire", action="store_true",
                   help="Skip expiry-based pruning")
    p.add_argument("--no-dedupe", action="store_true",
                   help="Skip semantic deduplication")
    p.add_argument("--threshold", type=float, default=0.95,
                   help="Cosine similarity threshold for dedup (default: 0.95)")
    p.add_argument("--tag-overlap", type=float, default=0.5,
                   help="Min tag-Jaccard to confirm dedup (default: 0.5)")
    p.add_argument("--kb", type=Path, default=KB_PATH,
                   help=f"Path to KB JSONL (default: {KB_PATH})")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print full reasons in dedup report")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.kb.exists():
        print(f"[FATAL] KB not found: {args.kb}", file=sys.stderr)
        return 1

    do_expire = not args.no_expire
    do_dedupe = not args.no_dedupe
    if not do_expire and not do_dedupe:
        print("[FATAL] both --no-expire and --no-dedupe set; nothing to do.", file=sys.stderr)
        return 1

    print(f"Loading KB: {args.kb}")
    entries = load_kb(args.kb)
    print(f"  Loaded {len(entries)} entries")

    embedder: Optional[Embedder] = None
    if do_dedupe:
        print(f"Loading embedder: {DEFAULT_EMBEDDING_MODEL}")
        embedder = build_default_embedder()

    report, new_entries = compact(
        entries, embedder,
        do_expire=do_expire,
        do_dedupe=do_dedupe,
        cosine_threshold=args.threshold,
        tag_overlap_threshold=args.tag_overlap,
    )

    print(format_report(report, dry_run=not args.force, verbose=args.verbose))

    if args.force:
        print(f"Writing {len(new_entries)} entries to {args.kb} (atomic + .bak backup)...")
        write_atomic(new_entries, args.kb)
        print(f"  Done. Backup: {args.kb}.bak")

    append_audit(report, vars(args))
    print(f"Audit appended to {AUDIT_LOG_PATH}")
    return 0


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

if __name__ == "__main__":
    # Smoke test mode: when invoked with --self-test, run pure-functional checks
    # (no embedder, no real KB) that verify the dedup + expiry algorithms.
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        print("=" * 60)
        print("  SMOKE TESTS  (pure-functional, no network/embedding)")
        print("=" * 60)

        # Smoke 1: expiry parsing
        e_perm = KBEntry(1, "2026-01-01", "Decision", ("a",), "x", "Permanent", {})
        e_past = KBEntry(2, "2026-01-01", "Decision", ("a",), "x", "2025-12-31", {})
        e_future = KBEntry(3, "2026-01-01", "Decision", ("a",), "x", "2099-12-31", {})
        e_bad = KBEntry(4, "2026-01-01", "Decision", ("a",), "x", "not-a-date", {})
        kept, verdicts = filter_expired([e_perm, e_past, e_future, e_bad], today=date(2026, 5, 3))
        assert {x.line_no for x in kept} == {1, 3, 4}, f"expiry kept wrong set: {kept}"
        assert len(verdicts) == 1 and verdicts[0].line_no == 2
        print("  [OK] Smoke 1: expiry parsing (Permanent / past / future / malformed)")

        # Smoke 2: tag jaccard
        assert _tag_jaccard(["a", "b"], ["b", "c"]) == 1 / 3
        assert _tag_jaccard(["a"], ["a"]) == 1.0
        assert _tag_jaccard([], []) == 0.0
        print("  [OK] Smoke 2: tag_jaccard math")

        # Smoke 3: quality tuple ordering
        e_long_directive = KBEntry(1, "2026-01-01", "X", ("a",), "DIRECTIVE: long content here", "P", {})
        e_short_plain = KBEntry(2, "2026-01-01", "X", ("a",), "short", "P", {})
        winner, loser = _pick_winner(e_long_directive, e_short_plain)
        assert winner.line_no == 1, "DIRECTIVE+longer should beat short+plain"
        print("  [OK] Smoke 3: _pick_winner prefers DIRECTIVE + longer content")

        # Smoke 4: provenance tiebreak (equal quality -> earliest timestamp wins)
        a = KBEntry(1, "2026-03-01", "X", ("t",), "same content", "P", {})
        b = KBEntry(2, "2026-04-01", "X", ("t",), "same content", "P", {})
        winner, loser = _pick_winner(a, b)
        assert winner.line_no == 1, "earliest timestamp should win on equal quality"
        print("  [OK] Smoke 4: provenance tiebreak (earliest timestamp on equal quality)")

        # Smoke 5: tag merge
        winner = KBEntry(1, "t", "X", ("a", "b"), "c", "P", {"timestamp": "t", "type": "X", "tags": ["a", "b"], "content": "c", "expiry": "P"})
        loser = KBEntry(2, "t", "X", ("b", "c", "d"), "c", "P", {})
        merged = _merge_tags_into_winner(winner, loser)
        assert merged.tags == ("a", "b", "c", "d"), f"tag merge wrong: {merged.tags}"
        print("  [OK] Smoke 5: tag merge preserves order, no dupes")

        # Smoke 6: stub embedder + dedup integration
        def stub_embedder(texts: Sequence[str]) -> np.ndarray:
            # near-identical for the first two, different for the third
            return np.array([
                [1.0, 0.0, 0.0],
                [0.99, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ], dtype=np.float32)[: len(texts)]

        e1 = KBEntry(1, "2026-01-01", "Decision", ("brain", "stage4"), "Brain = Kimi K2.6 default.", "P", {"timestamp": "2026-01-01", "type": "Decision", "tags": ["brain", "stage4"], "content": "Brain = Kimi K2.6 default.", "expiry": "P"})
        e2 = KBEntry(2, "2026-02-01", "Decision", ("brain", "kimi"),   "Brain default = Kimi K2.6 (paraphrased).", "P", {"timestamp": "2026-02-01", "type": "Decision", "tags": ["brain", "kimi"], "content": "Brain default = Kimi K2.6 (paraphrased).", "expiry": "P"})
        e3 = KBEntry(3, "2026-03-01", "Decision", ("memory",),         "Use ChromaDB.", "P", {"timestamp": "2026-03-01", "type": "Decision", "tags": ["memory"], "content": "Use ChromaDB.", "expiry": "P"})
        kept, verdicts = dedupe([e1, e2, e3], stub_embedder, cosine_threshold=0.95, tag_overlap_threshold=0.3)
        kept_lines = {k.line_no for k in kept}
        # Winner picked by quality_tuple: e2's content (45 chars) > e1's (30 chars).
        # So e2 wins; e1 redirects into e2; e3 is unrelated and stays.
        assert kept_lines == {2, 3}, f"dedup kept wrong set: {kept_lines}"
        assert len(verdicts) == 1 and verdicts[0].line_no == 1
        # Verify tag union landed on the winner
        winner = next(k for k in kept if k.line_no == 2)
        assert set(winner.tags) == {"brain", "stage4", "kimi"}, f"tag merge wrong: {winner.tags}"
        print(f"  [OK] Smoke 6: dedup kept {kept_lines}, dropped L1, merged tags into winner")

        # Smoke 7: heartbeat-emitted entries bypass dedup (Stage 3.5 prerequisite)
        def stub_embedder_hb(texts: Sequence[str]) -> np.ndarray:
            # All three entries are near-identical in embedding space
            return np.array([
                [1.0, 0.0, 0.0],
                [0.999, 0.0, 0.0],
                [0.998, 0.0, 0.0],
            ], dtype=np.float32)[: len(texts)]

        h1 = KBEntry(1, "2026-01-01", "Cognitive_Pattern", ("user-state",),
                     "User in Flow state.", "Permanent",
                     {"timestamp": "2026-01-01", "type": "Cognitive_Pattern",
                      "tags": ["user-state"], "content": "User in Flow state.", "expiry": "Permanent"})
        h2 = KBEntry(2, "2026-01-02", "Cognitive_Pattern", ("user-state",),
                     "User in Flow state again.", "Permanent",
                     {"timestamp": "2026-01-02", "type": "Cognitive_Pattern",
                      "tags": ["user-state"], "content": "User in Flow state again.", "expiry": "Permanent"})
        h3 = KBEntry(3, "2026-01-03", "Cognitive_Pattern", ("user-state", "heartbeat-emitted"),
                     "User in Flow state, heartbeat tick.", "Permanent",
                     {"timestamp": "2026-01-03", "type": "Cognitive_Pattern",
                      "tags": ["user-state", "heartbeat-emitted"],
                      "content": "User in Flow state, heartbeat tick.", "expiry": "Permanent"})
        report, kept = compact(
            [h1, h2, h3], stub_embedder_hb,
            do_expire=False, do_dedupe=True,
            cosine_threshold=0.95, tag_overlap_threshold=0.3,
        )
        kept_lines = {e.line_no for e in kept}
        assert 3 in kept_lines, f"heartbeat-emitted entry L3 must survive dedup; got {kept_lines}"
        assert len(kept_lines) == 2, (
            f"expected 2 kept (one of L1/L2 deduped + L3 exempt); got {len(kept_lines)}: {kept_lines}"
        )
        assert len(report.deduped) == 1, (
            f"expected 1 dedup verdict for L1/L2 collision; got {len(report.deduped)}"
        )
        # Verify the deduped verdict came from a candidate, not the exempt entry
        assert report.deduped[0].line_no in {1, 2}, (
            f"dedup verdict should target L1 or L2, not L3 (exempt); got L{report.deduped[0].line_no}"
        )
        print(f"  [OK] Smoke 7: heartbeat-emitted bypass — kept {kept_lines}, L3 survived dedup")

        print("=" * 60)
        print("  All smoke tests passed.")
        print("=" * 60)
        sys.exit(0)

    sys.exit(main())
