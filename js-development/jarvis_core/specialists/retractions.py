"""
retractions.py — material that must never reach training, because it is not what it looked like.

LAYER: Specialists (corpus assembly)

=============================================================================
THE BIG PICTURE
=============================================================================
Verdicts in turn_curation.jsonl control only the turns that come from the observation
queue. They do not control the other doors into a corpus: knowledge-base entries and
the raw conversation store. On 2026-09-26 JARVIS answered its own interview question in
the owner's first-person voice; that text entered through THREE doors (a queue row, KB
735, and a conversation-store turn), and retracting the queue verdict alone would have
left two copies in the next rebuild.

This registry is the one place that says "this KB entry / this conversation turn is not
the owner's words (or is otherwise unreliable)". It is append-only, tracked with
merge=union like the other jsonl logs, and read by every corpus builder. Nothing is
deleted from the KB or the conversation store: the source of record stays intact, and
only what is TRAINED ON changes.

Row shapes (one JSON object per line):
    {"kind": "kb",        "id": 735, "reason": "...", "ts": "..."}
    {"kind": "conv_turn", "file": "conv-web-xxx.jsonl", "line": 17, "reason": "...", "ts": "..."}
`line` is the zero-based index of the turn in the file, the same number the builders
put in their `source_path` ("conv-web-xxx.jsonl#L17").

=============================================================================
THE FLOW
=============================================================================
STEP 1: `load_retractions()` reads jarvis_data/retractions.jsonl, cached by (mtime, size).
        |
STEP 2: a builder asks `kb_retracted(r, entry_id)` or `conv_turn_retracted(r, file, line)`.
        |
STEP 3: a True answer means the builder skips the record and counts it as dropped.
=============================================================================
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple

from jarvis_core.config import DATA_ROOT

RETRACTIONS_PATH = Path(DATA_ROOT) / "retractions.jsonl"
RETRACTIONS_PATH_DEFAULT = RETRACTIONS_PATH


@dataclass(frozen=True)
class Retractions:
    kb_ids: FrozenSet[str] = frozenset()
    conv_turns: FrozenSet[Tuple[str, int]] = frozenset()


_cache: Dict[str, Tuple[Tuple[int, int], Retractions]] = {}


def load_retractions(path: Optional[Path] = None) -> Retractions:
    path = path or RETRACTIONS_PATH           # read at CALL time so a test can point it elsewhere
    try:
        stat = path.stat()
    except FileNotFoundError:
        return Retractions()
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    kb: set = set()
    conv: set = set()
    with path.open("r", encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue                       # a torn final line must not disable every other retraction
            kind = row.get("kind")
            if kind == "kb" and row.get("id") is not None:
                kb.add(str(row["id"]))
            elif kind == "conv_turn" and row.get("file") and isinstance(row.get("line"), int):
                conv.add((str(row["file"]), int(row["line"])))
            else:
                raise ValueError(f"{path}:{n}: unrecognised retraction row {row!r}")
    out = Retractions(frozenset(kb), frozenset(conv))
    _cache[str(path)] = (stamp, out)
    return out


def kb_retracted(retractions: Retractions, entry_id: Any) -> bool:
    return entry_id is not None and str(entry_id) in retractions.kb_ids


def conv_turn_retracted(retractions: Retractions, file_name: str, line: int) -> bool:
    return (file_name, line) in retractions.conv_turns


def _self_test() -> int:
    import tempfile
    failures = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "retractions.jsonl"
        check("a missing file retracts nothing", load_retractions(path) == Retractions())
        path.write_text(json.dumps({"kind": "kb", "id": 735, "reason": "x"}) + "\n"
                        + json.dumps({"kind": "conv_turn", "file": "conv-a.jsonl", "line": 17, "reason": "y"}) + "\n", encoding="utf-8")
        r = load_retractions(path)
        check("a KB id is retracted, whether given as int or str", kb_retracted(r, 735) and kb_retracted(r, "735"))
        check("another KB id is not", not kb_retracted(r, 736) and not kb_retracted(r, None))
        check("a conversation turn is retracted by file and index", conv_turn_retracted(r, "conv-a.jsonl", 17))
        check("a different index or file is not", not conv_turn_retracted(r, "conv-a.jsonl", 16) and not conv_turn_retracted(r, "conv-b.jsonl", 17))
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"kind": "kb", "id": 800')            # a killed writer's torn last line
        check("a torn final line does not disable the other retractions", kb_retracted(load_retractions(path), 735))
        path.write_text(json.dumps({"kind": "mystery"}) + "\n", encoding="utf-8")
        try:
            load_retractions(path)
            check("an unrecognised row is refused loudly", False)
        except ValueError:
            check("an unrecognised row is refused loudly", True)

        # the real builders must honour it
        import jarvis_core.specialists.retractions as me
        from jarvis_core.specialists import engineer_corpus as ec
        tmpd = Path(tmp)
        me.RETRACTIONS_PATH = tmpd / "live.jsonl"
        me.RETRACTIONS_PATH.write_text(
            json.dumps({"kind": "kb", "id": 735}) + "\n"
            + json.dumps({"kind": "conv_turn", "file": "conv-x.jsonl", "line": 1}) + "\n", encoding="utf-8")
        kb = tmpd / "kb.jsonl"
        kb.write_text("".join(json.dumps(e) + "\n" for e in (
            {"id": 734, "type": "Episodic", "tags": ["a"], "timestamp": "t", "content": "A genuine entry about spark partition tuning and shuffles " * 4},
            {"id": 735, "type": "Episodic", "tags": ["a"], "timestamp": "t", "content": "A retracted entry with a made-up first person answer to a question " * 4})))
        dropped: Dict[str, int] = {}
        kept = {r.source_path.split("#")[1] for r in ec.iter_kb_records(kb_path=kb, dropped=dropped)}
        check("engineer corpus: a retracted KB entry is skipped, the genuine one kept", kept == {"734"}, str(kept))
        check("engineer corpus: the skip is counted, never silent", dropped.get("kb_entry:retracted") == 1, str(dropped))
        cdir = tmpd / "conv"; cdir.mkdir()
        (cdir / "conv-x.jsonl").write_text("".join(json.dumps(t) + "\n" for t in (
            {"ts": "t", "role": "user", "content": "how do I tune spark partitions please"},
            {"ts": "t", "role": "assistant", "content": "I made this answer up on the owner's behalf entirely"},
            {"ts": "t", "role": "user", "content": "thanks that is useful for the cluster"})))
        old_dir = ec._CONVERSATIONS_DIR
        ec._CONVERSATIONS_DIR = cdir
        try:
            dropped2: Dict[str, int] = {}
            paths = [r.source_path for r in ec._iter_conversation_store_records(dropped=dropped2)]
        finally:
            ec._CONVERSATIONS_DIR = old_dir
        check("engineer corpus: a retracted conversation turn is skipped by file and index",
              "conv-x.jsonl#L1" not in paths and "conv-x.jsonl#L0" in paths and "conv-x.jsonl#L2" in paths, str(paths))
        check("engineer corpus: that skip is counted", dropped2.get("chat_history:retracted") == 1, str(dropped2))
        from jarvis_core.memory import episode_index as ei
        units = [u["turn_ids"][0] for u in ei.kb_raw_units(kb)]
        check("the episode index (retrieval) skips a retracted KB entry too", len(units) == 1 and "735" not in units[0], str(units))
        me.RETRACTIONS_PATH = RETRACTIONS_PATH_DEFAULT
    print("PASS" if not failures else f"{len(failures)} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
