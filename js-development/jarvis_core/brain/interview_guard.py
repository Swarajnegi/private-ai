"""
interview_guard.py — keeps JARVIS from answering its own interview question.

LAYER: Brain (conduct guard around the ask path)

=============================================================================
THE BIG PICTURE
=============================================================================
The owner's personalization interview is a numbered bank of questions that JARVIS
asks one at a time ("**Question 6:** ..."). On 2026-09-26, after eleven idle days,
the owner asked an off-script question ("how long have i been away for?"). The
answering model (a free Nemotron) ignored it and wrote BOTH sides of the interview:
a "**Question 6:**" header, a 5,363-character first-person "answer" in its own
voice, and "That covers Question 6. Ready for the next." That text then reached the
KB, three training corpora and the parser, which filed it as the owner's voice
(KB 1201 records the incident).

Nothing stopped it because the interviewer protocol lived only in the owner's first
chat message, with no system-level rule and no check on what the interviewer says.
This module is that check. It is pure functions, so it is testable without a model.

A legitimate interviewer reply is short ("Noted. Question 7: ...") and may even say
"ready for the next". So a reply is a violation only when it is LONG and carries a
question header, a "that covers question N" closer, or heavy first-person narration.

=============================================================================
THE FLOW
=============================================================================
STEP 1: open_question(history) finds the last short "**Question N:**" turn JARVIS
        asked. None means this is not an interview session and nothing changes.
        |
STEP 2: ask() appends TASK_SUFFIX to the task (never to the stored question).
        |
STEP 3: violates(reply) is checked; on a violation the task is retried once with
        STRICT_SUFFIX, and if it still violates the reply is replaced by
        fallback_reply(open): the open question restated.
=============================================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_REPLY_CHARS = 700
_HEADER = re.compile(r"\*\*Question\s+(\d+)\s*[:.]?\*\*\s*(.+)")
_CLOSER = re.compile(r"that covers question\s+\d+|ready for the next", re.I)
_FIRST_PERSON = re.compile(r"\bI\b")

TASK_SUFFIX = (
    "\n\n[Interview-mode rule, not part of the owner's message] You are the interviewer in the owner's "
    "personalization interview. If the owner's message is not an answer to the open question, answer it "
    "briefly and plainly (the clock and your tools can tell you elapsed time), then restate the open question. "
    "Keep the reply to a few sentences. NEVER write the owner's answer yourself, never write a 'Question N' "
    "header followed by an answer, and never say 'That covers Question N'."
)
STRICT_SUFFIX = (
    "\n\n[Interview-mode rule, restated] Your previous reply wrote the owner's side of the interview. That is "
    "forbidden. Reply in at most three sentences: answer the owner's message directly, then restate the open "
    "question. Do not write any answer on the owner's behalf."
)

Turn = Dict[str, Any]


def open_question(history: Sequence[Turn]) -> Optional[Tuple[int, str]]:
    """(number, text) of the question JARVIS last asked, or None when this is not an interview.

    A long assistant turn that merely contains a header is a confabulation, not a question: it is skipped,
    so the persisted bad turn of 2026-09-26 cannot become the "open question"."""
    for turn in reversed(list(history)):
        if turn.get("role") != "assistant":
            continue
        content = str(turn.get("content", ""))
        if len(content) > MAX_REPLY_CHARS:
            continue
        match = _HEADER.search(content)
        if match:
            return int(match.group(1)), match.group(2).strip()
    return None


def violates(reply: str) -> bool:
    """True when a LONG reply carries the signature of the interviewer writing the owner's turn."""
    text = (reply or "").strip()
    if len(text) <= MAX_REPLY_CHARS:
        return False
    return bool(_HEADER.search(text) or _CLOSER.search(text) or len(_FIRST_PERSON.findall(text)) >= 8)


def fallback_reply(open_q: Tuple[int, str]) -> str:
    number, text = open_q
    return f"I'll keep to the interview. Back to question {number}: {text}"


def _self_test() -> int:
    failures: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failures.append(name)

    q6 = "**Question 6:** What experiences have shaped your worldview most deeply?"
    bad = ("**Question 6:** What experiences have shaped your worldview most deeply?\n\n---\n\n"
           + "The most formative experience in my development has been the tension between ambition and grounding. " * 8
           + "\n\n---\n\nThat covers Question 6. Ready for the next.")
    history = [{"role": "user", "content": "Alright Jarvis, ask me these questions one by one"},
               {"role": "assistant", "content": "**Question 1:** Who are you trying to become?"},
               {"role": "user", "content": "x " * 200},
               {"role": "assistant", "content": q6},
               {"role": "user", "content": "Hi, been a while?"},
               {"role": "assistant", "content": "Hey. Back to question 6: What experiences have shaped your worldview most deeply?"}]
    check("an interview session is detected and the open question found", open_question(history) == (
        6, "What experiences have shaped your worldview most deeply?"), str(open_question(history)))
    check("a normal chat is not an interview", open_question([{"role": "user", "content": "hi"},
                                                              {"role": "assistant", "content": "hello"}]) is None)
    check("an empty history is not an interview", open_question([]) is None)
    check("a long headered turn (the 2026-09-26 reply) is never the open question",
          open_question(history + [{"role": "user", "content": "how long have i been away?"},
                                   {"role": "assistant", "content": bad}]) == (6, "What experiences have shaped your worldview most deeply?"))
    check("the 2026-09-26 reply is a violation", violates(bad))
    check("a short interviewer reply with a header is fine", not violates("Noted.\n\n**Question 7:** Why are you building JARVIS?"))
    check("a short reply that says 'ready for the next' is fine", not violates("Thanks, that is clear. Ready for the next."))
    check("a long reply with a header is a violation", violates("**Question 7:** x\n\n" + "y " * 500))
    check("a long first-person monologue with no header is a violation", violates(("I think I was always like this. " * 40)))
    check("a long reply with no header, closer or first person is allowed (a real explanation)",
          not violates("Elapsed time is computed from the conversation timestamps. " * 20))
    check("an empty reply is not a violation", not violates("") and not violates(None))   # type: ignore[arg-type]
    check("the fallback restates the open question", fallback_reply((6, "What shaped you?")) == "I'll keep to the interview. Back to question 6: What shaped you?")
    check("the suffixes forbid writing the owner's answer", "NEVER write the owner's answer" in TASK_SUFFIX and "forbidden" in STRICT_SUFFIX)
    print("PASS" if not failures else f"{len(failures)} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
