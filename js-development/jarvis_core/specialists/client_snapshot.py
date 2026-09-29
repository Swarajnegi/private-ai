"""
client_snapshot.py — client-work training records that a build must never lose.

LAYER: Specialists (Corpus Assembly)

Run with:
    python -m jarvis_core.specialists.client_snapshot            # self-test
    python -m jarvis_core.specialists.client_snapshot --status

=============================================================================
THE BIG PICTURE
=============================================================================

The BUPA deepclone framework, its test_cases_orchestrator job, the
test_cases/ notebooks and their tests reach training as CHUNKS of redacted text:
engineer_corpus.py (`client_work`) and personalization_corpus.py
(`professional_reasoning`) read them from client_work/, which is gitignored and
lives on the WORK laptop only (the owner's decision, recorded in .gitignore:
"don't push the deepclone code, but remove nothing from the corpus data").

On 2026-09-28 a rebuild on the Windows laptop, where client_work/ holds only
SESSION_LEARNINGS.md, silently shrank the engineer corpus's client records from
669 to 17 and personalization's from 265 to 17, and that shrunken corpus was
committed. A builder that reads a source that is absent must not treat absence
as deletion.

The snapshot is the fix: every client record ever produced is kept in one
tracked file, `training_corpus/client_work_snapshot.jsonl`. A build takes the
LIVE records where the source exists, and CARRIES FORWARD the snapshot's record
for every source_path it could not regenerate. After a build the snapshot is
refreshed from the live records, so the work laptop's builds keep it current.
The set only grows or is replaced by fresher live text; it never shrinks.

Records are already redacted (agent.capture.redact) when they enter the snapshot.
Third-party names are replaced later, at blend time, exactly as for every other
record.

=============================================================================
THE FLOW
=============================================================================

STEP 1: the builder streams its live client records and remembers their keys.
        |
STEP 2: carry_forward() yields every snapshot record for this corpus whose
        (source_path) was not produced live.
        |
STEP 3: refresh() rewrites the snapshot: live records replace their older
        versions; carried records stay.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core.config import DATA_ROOT  # noqa: E402

SNAPSHOT_PATH = Path(DATA_ROOT) / "training_corpus" / "client_work_snapshot.jsonl"
CORPORA = {"engineer": "client_work", "personalization": "professional_reasoning"}


def load(path: Optional[Path] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{corpus: {source_path: record}} from the snapshot file."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {c: {} for c in CORPORA}
    src = path or SNAPSHOT_PATH
    if not src.exists():
        return out
    for line in src.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        corpus = row.pop("corpus", "")
        if corpus in out and row.get("source_path"):
            out[corpus][row["source_path"]] = row
    return out


def carry_forward(corpus: str, live_paths: Set[str], path: Optional[Path] = None) -> Iterator[Dict[str, Any]]:
    """Snapshot records for `corpus` that the live build did not regenerate."""
    for source_path, record in load(path)[corpus].items():
        if source_path not in live_paths:
            yield record


def refresh(corpus: str, live_records: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """Fold live records into the snapshot (live wins); return the snapshot size for `corpus`."""
    dest = path or SNAPSHOT_PATH
    state = load(dest)
    for record in live_records:
        state[corpus][record["source_path"]] = dict(record)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for c in CORPORA:
            for source_path in sorted(state[c]):
                fh.write(json.dumps({"corpus": c, **state[c][source_path]}, ensure_ascii=False) + "\n")
    tmp.replace(dest)
    return len(state[corpus])


def counts(path: Optional[Path] = None) -> Dict[str, int]:
    return {c: len(v) for c, v in load(path).items()}


def _self_test() -> int:
    import tempfile
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    def rec(p: str, t: str) -> Dict[str, Any]:
        return {"source_type": "client_work", "source_path": p, "text": t, "metadata": {}}

    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.jsonl"
        refresh("engineer", [rec("a#chunk0", "old a"), rec("b#chunk0", "old b")], snap)
        carried = list(carry_forward("engineer", {"a#chunk0"}, snap))
        check("T1 a source that was not regenerated is carried forward",
              [r["source_path"] for r in carried] == ["b#chunk0"], str(carried))
        n = refresh("engineer", [rec("a#chunk0", "new a")], snap)
        state = load(snap)["engineer"]
        check("T2 a build with fewer live records never shrinks the snapshot", n == 2 and "b#chunk0" in state)
        check("T3 live text replaces the older version", state["a#chunk0"]["text"] == "new a")
        check("T4 corpora are kept apart", load(snap)["personalization"] == {})
        check("T5 an empty live build changes nothing", refresh("engineer", [], snap) == 2)
    print(f"  {5 - len(failed)}/5 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--status" in sys.argv:
        print(json.dumps(counts()))
        sys.exit(0)
    sys.exit(_self_test())
