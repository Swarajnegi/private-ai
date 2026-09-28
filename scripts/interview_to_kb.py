"""
interview_to_kb.py — the owner's interview answers, in their own words, into the KB.

LAYER: Tools (Memory hygiene)

Run with:
    python scripts/interview_to_kb.py              # append every accepted answer not yet in the KB
    python scripts/interview_to_kb.py --dry-run    # show what would be appended
    python scripts/interview_to_kb.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

JARVIS runs a personalization interview: it asks "**Question N:** ..." and
the owner answers at length, in their own words. Those answers are the
richest self-description JARVIS has, and until 2026-09-28 they reached
nothing that describes the owner: the profile is built only from the KB, and
nothing ever moved an answer there. Asked "tell me about myself", JARVIS knew
nothing of Uttarakhand, the farm, the quiet life in the north, or the doubt
cycle every few months, all of which the owner had told it directly.

This copies each ACCEPTED answer into the KB verbatim, tagged as identity, so
the profile's "Who you are" and retrieval both carry it. An answer counts as
accepted once JARVIS moves on to a different question; until then it may be
half-said. If JARVIS re-asks the same question, what came in between was not
an answer ("Hi, been a while?") and is dropped. Re-running is safe:
kb_append drops exact duplicates.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Read every conversation in jarvis_data/conversations/, in order.
        |
STEP 2: Track the open question; collect the owner's messages after it.
        A re-ask of the same number resets the collection; a new number
        closes the previous answer.
        |
STEP 3: kb_append each closed answer (Cognitive_Pattern, identity tags).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from jarvis_core.config import DATA_ROOT  # noqa: E402

CONVERSATIONS = Path(DATA_ROOT) / "conversations"
TAGS = ["identity", "interview", "self-model", "in-own-words"]
_QUESTION = re.compile(r"\*\*Question\s+(\d+):\*\*\s*(.+)")


@dataclass(frozen=True)
class Answer:
    number: int
    question: str
    asked_ts: str
    text: str

    def content(self) -> str:
        return (f"Interview answer, question {self.number} (asked {self.asked_ts[:10]}): "
                f"\"{self.question}\" In the owner's own words:\n\n{self.text}")


def _turns(path: Path) -> Iterator[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                yield json.loads(line)
            except ValueError:
                continue


def accepted_answers(turns: Iterable[dict]) -> Iterator[Answer]:
    number: Optional[int] = None
    question = asked_ts = ""
    said: List[str] = []
    for turn in turns:
        role, content = turn.get("role"), str(turn.get("content") or "")
        if role == "assistant":
            m = _QUESTION.search(content)
            if not m:
                continue
            n = int(m.group(1))
            if n != number and number is not None and said:
                yield Answer(number, question, asked_ts, "\n\n".join(said))
            if n != number:
                number, question, asked_ts = n, m.group(2).strip(), str(turn.get("ts") or "")
            said = []
        elif role == "user" and number is not None and content.strip():
            said.append(content.strip())


def all_answers(directory: Path = CONVERSATIONS) -> Iterator[Answer]:
    for path in sorted(directory.glob("*.jsonl")):
        yield from accepted_answers(_turns(path))


def run(directory: Path = CONVERSATIONS, dry_run: bool = False,
        kb_path: Optional[Path] = None) -> dict:
    from kb_append import append_entry
    counts = {"appended": 0, "already_in_kb": 0, "other": 0}
    for answer in all_answers(directory):
        if dry_run:
            print(f"--- Q{answer.number}: {answer.question}\n{answer.text}\n")
            counts["appended"] += 1
            continue
        kwargs = {"kb_path": kb_path} if kb_path else {}
        status = append_entry("Cognitive_Pattern", TAGS, answer.content(),
                              semantic_dedup=False, **kwargs).get("status")
        key = {"appended": "appended", "duplicate": "already_in_kb"}.get(str(status), "other")
        counts[key] += 1
    return counts


def _self_test() -> int:
    import tempfile
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    turns = [
        {"ts": "2026-09-14T12:51:00+05:30", "role": "user", "content": "Ask me the questions."},
        {"ts": "2026-09-14T12:51:00+05:30", "role": "assistant", "content": "Rules set.\n\n**Question 1:** Who are you?"},
        {"ts": "2026-09-14T13:07:00+05:30", "role": "user", "content": "A builder from the hills."},
        {"ts": "2026-09-14T13:07:00+05:30", "role": "assistant", "content": "Noted.\n\n**Question 2:** What life?"},
        {"ts": "2026-09-14T13:20:00+05:30", "role": "user", "content": "A quiet farm, eventually. And I"},
        {"ts": "2026-09-14T13:20:00+05:30", "role": "assistant", "content": "You trailed off?"},
        {"ts": "2026-09-14T13:21:00+05:30", "role": "user", "content": "And I want to be free."},
        {"ts": "2026-09-14T13:21:00+05:30", "role": "assistant", "content": "Got it.\n\n**Question 3:** Traits?"},
        {"ts": "2026-09-26T03:54:00+05:30", "role": "user", "content": "Hi, been a while?"},
        {"ts": "2026-09-26T03:54:00+05:30", "role": "assistant", "content": "Back to it. **Question 3:** Traits?"},
        {"ts": "2026-09-26T03:56:00+05:30", "role": "user", "content": "Calm under pressure."},
    ]
    got = list(accepted_answers(turns))
    check("T1 an answer is accepted once the next question is asked",
          [a.number for a in got] == [1, 2], str([a.number for a in got]))
    check("T2 a follow-up before the next question belongs to the same answer",
          got[1].text == "A quiet farm, eventually. And I\n\nAnd I want to be free.", repr(got[1].text))
    check("T3 the still-open question is not recorded", all(a.number != 3 for a in got))
    check("T4 the owner's words are kept verbatim, whole",
          got[0].text == "A builder from the hills." and "Who are you?" in got[0].content())

    with tempfile.TemporaryDirectory() as td:
        conv = Path(td) / "conversations"
        conv.mkdir()
        (conv / "conv-web-x.jsonl").write_text(
            "\n".join(json.dumps(t) for t in turns) + "\n", encoding="utf-8")
        kb = Path(td) / "kb.jsonl"
        kb.write_text("", encoding="utf-8")
        first = run(conv, kb_path=kb)
        second = run(conv, kb_path=kb)
        rows = [json.loads(l) for l in kb.read_text(encoding="utf-8").splitlines() if l.strip()]
        check("T5 accepted answers land in the KB as identity entries",
              first["appended"] == 2 and all("identity" in r["tags"] for r in rows), str(first))
        check("T6 re-running appends nothing (exact dedup)",
              second["appended"] == 0 and len(rows) == 2, f"{second} rows={len(rows)}")

    print(f"  {6 - len(failed)}/6 passed")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    print(json.dumps(run(dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
