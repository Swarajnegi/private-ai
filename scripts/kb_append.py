"""
kb_append.py — the ONE safe write path into knowledge_base.jsonl.

LAYER: Tools (Memory hygiene)

Run with:
    # As a library (preferred — the consolidator, /memory, future tools call this):
    from scripts.kb_append import append_entry
    append_entry("Cognitive_Pattern", ["learning-pattern","DIRECTIVE","spark"], "...")

    # CLI:
    python3 scripts/kb_append.py --type Cognitive_Pattern --tags a,b,c --content "..."
    python3 scripts/kb_append.py --audit           # report dup ids + near-dup patterns
    python3 scripts/kb_append.py --self-test        # run smoke tests

=============================================================================
THE BIG PICTURE
=============================================================================

Without a single safe write path:
    -> Every chat hand-rolls its own append (python -c 'open(...).write(...)').
       Two chats computing "next id = 303" with no lock both write L303 — the
       exact collision that hit this repo on 2026-06-01 (work-laptop Wave 1
       Decision vs personal-laptop zero_gap_signal). merge=union unions both
       lines without conflict, so the dup id slips through silently.
    -> No dedup: the same insight gets appended five times across five chats.

With kb_append (this module):
    -> fcntl.flock(LOCK_EX) serializes all same-machine writers. Two concurrent
       appends get distinct ids, guaranteed.
    -> Content-hash dedup (reuses jsonl_merge.entry_key) drops byte-identical
       re-appends. Semantic dedup (reuses the MiniLM embedding) drops
       >0.85-similar same-type entries per the CLAUDE.md memory-hygiene rule.
    -> Each entry is stamped with source_machine so a post-merge --audit can
       detect cross-machine integer-id collisions that flock can't prevent
       offline.
    -> heartbeat=True adds the `heartbeat-emitted` tag so kb_compact.py never
       displaces auto-captured consolidation writes (see kb_compact.py:450).

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller invokes append_entry(type, tags, content, ...).
        |
        v
STEP 2: Open KB file, acquire fcntl.flock(LOCK_EX). All other same-machine
        writers block here until we release.
        |
        v
STEP 3: Re-read the file UNDER THE LOCK (so the id + dedup see the freshest
        state, including anything a writer that just released wrote).
        |
        v
STEP 4: Content-hash dedup. If an identical entry exists -> return
        {status: "deduped"} without writing.
        |
        v
STEP 5: Semantic dedup (optional). Embed the new content + existing same-type
        entries; if max cosine > 0.85 -> return {status: "deduped", similar_to}.
        |
        v
STEP 6: Assign next integer id = max(existing ids, 300) + 1. Build the entry
        with ISO+05:30 timestamp + source_machine stamp.
        |
        v
STEP 7: Append the single JSON line, flush+fsync, release the lock. Return
        {status: "appended", id}.

=============================================================================

NOTE: fcntl is POSIX-only. This script runs on the Linux work laptop (where
Claude Code hooks run). The Windows personal laptop (Antigravity) does not
call this — it consumes the committed KB read-side. Cross-machine writes are
reconciled by git merge=union + the --audit pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl  # POSIX file locking
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows fallback (not used in prod)
    _HAS_FCNTL = False

# Resolve KB_PATH from jarvis_core.config (honors JARVIS_ROOT env, machine-agnostic).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.config import KB_PATH  # noqa: E402


# =============================================================================
# PART 1: Constants
# =============================================================================

_IST = timezone(timedelta(hours=5, minutes=30))
HEARTBEAT_EXEMPT_TAG = "heartbeat-emitted"  # mirrors kb_compact.py:450
SEMANTIC_DEDUP_THRESHOLD = 0.85             # CLAUDE.md hygiene: >0.85 -> update, don't dup
_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_ID_FLOOR = 300  # historical: ids 1-300 are implicit by line order; explicit ids start at 301


def _ist_now_iso() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


def _machine_tag() -> str:
    return os.environ.get("JARVIS_MACHINE", socket.gethostname() or "unknown")


# =============================================================================
# PART 2: Content-hash dedup key (reuses jsonl_merge.entry_key semantics)
# =============================================================================

def _content_key(entry: Dict[str, Any]) -> str:
    """Stable dedup key — collisions only on truly identical entries.
    Identical to scripts/jsonl_merge.py:entry_key so the two agree."""
    parts = [
        entry.get("timestamp", ""),
        entry.get("type", ""),
        str(sorted(entry.get("tags", []))),
        entry.get("content", "")[:300],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _content_key_ignoring_ts(entry: Dict[str, Any]) -> str:
    """Dedup key WITHOUT timestamp — catches the same insight re-appended at a
    different time (the real duplicate case across chats)."""
    parts = [
        entry.get("type", ""),
        str(sorted(entry.get("tags", []))),
        entry.get("content", "")[:300],
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# =============================================================================
# PART 3: KB read helpers
# =============================================================================

def _read_entries(kb_path: Path) -> List[Dict[str, Any]]:
    """Parse all JSONL entries; skip blank/garbage lines."""
    entries: List[Dict[str, Any]] = []
    if not kb_path.exists():
        return entries
    with open(kb_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[kb_append] skip {kb_path}:{lineno} unparseable: {e}", file=sys.stderr)
    return entries


def _next_id(entries: List[Dict[str, Any]]) -> int:
    """Next integer id = max(existing explicit ids, _ID_FLOOR) + 1."""
    explicit = [e["id"] for e in entries if isinstance(e.get("id"), int)]
    return max(explicit + [_ID_FLOOR]) + 1


# =============================================================================
# PART 4: Semantic dedup (lazy — only loads the model when actually used)
# =============================================================================

_MODEL_CACHE: Dict[str, Any] = {}


def _get_model() -> Optional[Any]:
    """Lazy-load MiniLM. Returns None if sentence-transformers is unavailable
    (offline/CI) — semantic dedup then degrades to content-hash only."""
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(_EMBED_MODEL)
        _MODEL_CACHE["model"] = model
        return model
    except Exception as e:  # noqa: BLE001
        print(f"[kb_append] semantic dedup disabled (model load failed: {e})", file=sys.stderr)
        _MODEL_CACHE["model"] = None
        return None


def _semantic_duplicate(
    content: str,
    entry_type: str,
    entries: List[Dict[str, Any]],
    threshold: float = SEMANTIC_DEDUP_THRESHOLD,
) -> Optional[Tuple[int, float]]:
    """Return (line_index, similarity) of the most-similar SAME-TYPE entry if
    cosine > threshold, else None. Same-type-only matches kb_compact policy."""
    model = _get_model()
    if model is None:
        return None
    same_type = [(i, e) for i, e in enumerate(entries) if e.get("type") == entry_type and e.get("content")]
    if not same_type:
        return None
    import numpy as np
    texts = [content] + [e["content"] for _, e in same_type]
    vecs = model.encode(texts, normalize_embeddings=True)
    query = vecs[0]
    sims = vecs[1:] @ query  # cosine (normalized)
    best_local = int(np.argmax(sims))
    best_sim = float(sims[best_local])
    if best_sim > threshold:
        return same_type[best_local][0], best_sim
    return None


# =============================================================================
# PART 5: The safe append
# =============================================================================

def append_entry(
    entry_type: str,
    tags: List[str],
    content: str,
    expiry: str = "Permanent",
    heartbeat: bool = False,
    semantic_dedup: bool = True,
    kb_path: Path = KB_PATH,
) -> Dict[str, Any]:
    """Safely append one entry to the KB. Returns a status dict.

    status is one of:
        "appended"  -> {status, id, content_key}
        "deduped"   -> {status, reason: "content_hash"|"semantic", similar_to}
        "rejected"  -> {status, reason} (validation failure)
    """
    content = (content or "").strip()
    if not content:
        return {"status": "rejected", "reason": "empty content"}
    if not entry_type:
        return {"status": "rejected", "reason": "empty type"}

    tags = list(dict.fromkeys(t for t in (tags or []) if t))  # dedup tags, keep order
    if heartbeat and HEARTBEAT_EXEMPT_TAG not in tags:
        tags.append(HEARTBEAT_EXEMPT_TAG)
    if not (1 <= len(tags) <= 8):
        return {"status": "rejected", "reason": f"need 1-8 tags, got {len(tags)}"}

    kb_path = Path(kb_path)
    kb_path.parent.mkdir(parents=True, exist_ok=True)

    # Open for read+append; create if missing. Lock the FD for the whole op.
    with open(kb_path, "a+", encoding="utf-8") as fh:
        if _HAS_FCNTL:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            entries = _read_entries(kb_path)  # fresh read UNDER the lock

            new_entry = {
                "id": _next_id(entries),
                "timestamp": _ist_now_iso(),
                "type": entry_type,
                "tags": tags,
                "expiry": expiry,
                "content": content,
                "source_machine": _machine_tag(),
            }

            # Content-hash dedup (ignoring timestamp — same insight re-appended).
            new_key = _content_key_ignoring_ts(new_entry)
            for e in entries:
                if _content_key_ignoring_ts(e) == new_key:
                    return {"status": "deduped", "reason": "content_hash",
                            "similar_to": e.get("id"), "id": None}

            # Semantic dedup (optional, lazy model load).
            if semantic_dedup:
                hit = _semantic_duplicate(content, entry_type, entries)
                if hit is not None:
                    idx, sim = hit
                    return {"status": "deduped", "reason": "semantic",
                            "similar_to": entries[idx].get("id"),
                            "similarity": round(sim, 4), "id": None}

            line = json.dumps(new_entry, ensure_ascii=False)
            # Ensure we start on a fresh line even if the file lacked a trailing \n.
            fh.seek(0, os.SEEK_END)
            if fh.tell() > 0:
                fh.seek(fh.tell() - 1)
                last = fh.read(1)
                if last != "\n":
                    fh.write("\n")
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
            return {"status": "appended", "id": new_entry["id"],
                    "content_key": new_key}
        finally:
            if _HAS_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# =============================================================================
# PART 6: Audit (the lightweight kb_doctor)
# =============================================================================

def audit(kb_path: Path = KB_PATH) -> Dict[str, Any]:
    """Report duplicate integer ids (cross-machine collisions flock can't stop
    offline) + byte-identical content dups. Read-only."""
    entries = _read_entries(Path(kb_path))
    id_seen: Dict[int, List[int]] = {}
    for lineno, e in enumerate(entries, 1):
        if isinstance(e.get("id"), int):
            id_seen.setdefault(e["id"], []).append(lineno)
    dup_ids = {i: lines for i, lines in id_seen.items() if len(lines) > 1}

    key_seen: Dict[str, List[int]] = {}
    for lineno, e in enumerate(entries, 1):
        key_seen.setdefault(_content_key_ignoring_ts(e), []).append(lineno)
    dup_content = {k: lines for k, lines in key_seen.items() if len(lines) > 1}

    return {
        "total_entries": len(entries),
        "explicit_ids": len(id_seen),
        "duplicate_ids": dup_ids,
        "duplicate_content_groups": len(dup_content),
        "duplicate_content_lines": [lines for lines in dup_content.values()],
    }


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    import tempfile
    import concurrent.futures as cf

    print("=" * 70)
    print("  kb_append.py -- Smoke Tests")
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

        # T1: first append gets id 301 (floor 300 + 1)
        r1 = append_entry("Semantic", ["t1", "smoke"], "first fact about ducks",
                          semantic_dedup=False, kb_path=kb)
        check("T1 first append succeeds", r1["status"] == "appended", str(r1))
        check("T1b id == 301", r1["id"] == 301, str(r1))

        # T2: distinct second append -> id 302
        r2 = append_entry("Semantic", ["t2", "smoke"], "second fact about geese",
                          semantic_dedup=False, kb_path=kb)
        check("T2 second append -> 302", r2.get("id") == 302, str(r2))

        # T3: content-hash dedup (same type+tags+content, different time)
        r3 = append_entry("Semantic", ["t1", "smoke"], "first fact about ducks",
                          semantic_dedup=False, kb_path=kb)
        check("T3 content-hash dedup", r3["status"] == "deduped"
              and r3["reason"] == "content_hash", str(r3))

        # T4: empty content rejected
        r4 = append_entry("Semantic", ["x"], "   ", semantic_dedup=False, kb_path=kb)
        check("T4 empty content rejected", r4["status"] == "rejected", str(r4))

        # T5: bad tag count rejected
        r5 = append_entry("Semantic", [], "no tags here", semantic_dedup=False, kb_path=kb)
        check("T5 zero tags rejected", r5["status"] == "rejected", str(r5))

        # T6: heartbeat flag adds the exempt tag
        r6 = append_entry("Cognitive_Pattern", ["hb"], "a heartbeat observation",
                          heartbeat=True, semantic_dedup=False, kb_path=kb)
        entries = _read_entries(kb)
        hb_entry = next(e for e in entries if e["id"] == r6["id"])
        check("T6 heartbeat tag added", HEARTBEAT_EXEMPT_TAG in hb_entry["tags"], str(hb_entry["tags"]))

        # T7: source_machine stamped
        check("T7 source_machine stamped", "source_machine" in hb_entry, str(hb_entry.keys()))

        # T8: flock serialization — 8 concurrent appends -> 8 DISTINCT ids
        kb2 = Path(td) / "kb2.jsonl"
        def _worker(n: int) -> Optional[int]:
            r = append_entry("Episodic", ["conc", f"n{n}"], f"concurrent entry number {n}",
                             semantic_dedup=False, kb_path=kb2)
            return r.get("id")
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            ids = [f.result() for f in [ex.submit(_worker, n) for n in range(8)]]
        ids_clean = [i for i in ids if i is not None]
        check("T8 all 8 concurrent appends got ids", len(ids_clean) == 8, str(ids))
        check("T8b all 8 ids DISTINCT (flock works)", len(set(ids_clean)) == 8, str(sorted(ids_clean)))

        # T9: audit detects a planted dup id
        kb3 = Path(td) / "kb3.jsonl"
        with open(kb3, "w") as f:
            f.write(json.dumps({"id": 305, "timestamp": "t", "type": "X", "tags": ["a"],
                                "content": "one", "expiry": "Permanent"}) + "\n")
            f.write(json.dumps({"id": 305, "timestamp": "t2", "type": "Y", "tags": ["b"],
                                "content": "two", "expiry": "Permanent"}) + "\n")
        rep = audit(kb3)
        check("T9 audit detects dup id 305", 305 in rep["duplicate_ids"], str(rep["duplicate_ids"]))

        # T10: real KB audit reports zero dup ids (we fixed L303/L304 earlier)
        real = audit(KB_PATH)
        check("T10 real KB has no duplicate ids", real["duplicate_ids"] == {},
              str(real["duplicate_ids"]))

        # T11: semantic dedup (only if model loads; else skip gracefully)
        kb4 = Path(td) / "kb4.jsonl"
        append_entry("Idea", ["sem"], "We should cache embeddings on disk to speed retrieval.",
                     semantic_dedup=False, kb_path=kb4)
        r11 = append_entry("Idea", ["sem"],
                           "Caching the embeddings to disk would make retrieval faster.",
                           semantic_dedup=True, kb_path=kb4)
        if _get_model() is not None:
            check("T11 semantic dedup catches paraphrase",
                  r11["status"] == "deduped" and r11["reason"] == "semantic", str(r11))
        else:
            check("T11 semantic dedup skipped (no model) — degrades gracefully",
                  r11["status"] in ("appended", "deduped"), str(r11))

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} kb_append smoke tests passed.")
    print("=" * 70)


def main() -> int:
    p = argparse.ArgumentParser(description="Safe append into knowledge_base.jsonl")
    p.add_argument("--type", dest="entry_type", help="Entry type (Cognitive_Pattern, Decision, ...)")
    p.add_argument("--tags", help="Comma-separated tags (1-8)")
    p.add_argument("--content", help="Entry content")
    p.add_argument("--expiry", default="Permanent")
    p.add_argument("--heartbeat", action="store_true", help="Add heartbeat-emitted tag")
    p.add_argument("--no-semantic", action="store_true", help="Skip semantic dedup")
    p.add_argument("--audit", action="store_true", help="Report dup ids + dup content")
    p.add_argument("--self-test", action="store_true", help="Run smoke tests")
    args = p.parse_args()

    if args.self_test:
        _run_self_test()
        return 0

    if args.audit:
        rep = audit()
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 1 if rep["duplicate_ids"] else 0

    if not (args.entry_type and args.tags and args.content):
        p.error("--type, --tags, and --content are required (unless --audit/--self-test)")

    result = append_entry(
        entry_type=args.entry_type,
        tags=[t.strip() for t in args.tags.split(",")],
        content=args.content,
        expiry=args.expiry,
        heartbeat=args.heartbeat,
        semantic_dedup=not args.no_semantic,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in ("appended", "deduped") else 2


if __name__ == "__main__":
    raise SystemExit(main())
