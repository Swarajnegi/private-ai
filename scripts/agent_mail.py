#!/usr/bin/env python3
"""
agent_mail.py — the channel the agents talk to each other through.

LAYER: Tools (organ + CLI; the Claude Code adapter is scripts/hooks/check_agent_mail.py)

Run with:
    python3 scripts/agent_mail.py --check codex        # anything waiting for Codex?
    python3 scripts/agent_mail.py --list               # every thread, answered or not
    python3 scripts/agent_mail.py --ask codex --subject "..." --body "..."
    python3 scripts/agent_mail.py --answer 1 --body "..."   # answer thread 001
    python3 scripts/agent_mail.py --read 1             # print a whole thread
    python3 scripts/agent_mail.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

Three agents now work on JARVIS — Claude Code (work laptop), Codex CLI and
Antigravity (personal laptop) — and until now they could only communicate by
the user manually relaying. That makes the user a message bus, which is both
slow and lossy: the thing Codex wants to ask about a design decision is
usually a thing the user would have to first understand well enough to
re-explain.

This gives them a direct channel, using the transport that already works.
`agents_converse/` is a tracked directory; git is the wire. No server, no
polling daemon, no new dependency — the same "one file plus adapters" shape
as the capture organ.

USER'S DESIGN, ADOPTED: a question is a markdown file; the addressee is named
with a `~ Name` line, exactly as proposed ("beside the question you will put
~ Codex, so for each question it is known who is asking and who must answer").

ONE CHANGE TO THAT DESIGN, AND THE REASON. The original proposal was that the
answerer writes the answer back INTO the same file. That is the one shape
guaranteed to break: two agents on two machines editing one tracked file is
the textbook git conflict, and `.gitattributes` gives `merge=union` to
`*.jsonl` ONLY — a `.md` edited on both sides conflicts and needs manual
resolution, which is precisely the manual step this channel exists to remove.
So: **a question file is written ONCE by the asker and never modified. The
answer is a SEPARATE file.** No file is ever written by two parties, so a
conflict is structurally impossible rather than merely unlikely.

    agents_converse/q_001.md   <- written by the asker, immutable
    agents_converse/a_001.md   <- written by the answerer

"Unanswered" is then not a status field anyone has to maintain honestly; it is
`q_001.md` existing with no `a_001.md` beside it. State you can derive is state
that cannot go stale.

=============================================================================
HOW EACH AGENT NOTICES — and the honest limit
=============================================================================

The user's hope was "as soon as anything lands you will notice". **No agent
here can do that**, and saying otherwise would be the same mistake as thinking
the hearth has senses. None of the three runs continuously; each exists only
inside a session. So notification is at SESSION BOUNDARIES:

    Claude Code   SessionStart hook (scripts/hooks/check_agent_mail.py)
                  -> injected automatically, no one has to remember
    Codex         AGENTS.md SESSION BOOT step -> `--check codex`
    Antigravity   js-workspace-rule.md boot step -> `--check antigravity`

And git still has to move: an answer written here reaches the other machine
only after a push and a pull. The hearth can automate the pull half on a
cadence; the push half is deliberately left to a human, because an agent that
force-pushes unattended is a different risk conversation.

So the real latency is "next session on the other side", not "instant". That
is still vastly better than routing every question through the user's memory.

=============================================================================
THE FLOW
=============================================================================

STEP 1: An agent has a question it cannot answer from the repo. It calls
        --ask, naming the addressee.
        |
STEP 2: q_NNN.md is written with a `~ <Addressee>` line. Commit + push.
        |
STEP 3: The addressee's next session boots, its adapter runs --check <self>,
        and the pending question is put in front of it.
        |
STEP 4: It answers with --answer NNN, writing a_NNN.md. Commit + push.
        |
STEP 5: The asker's next session sees the answer the same way (--check also
        reports answers to questions YOU asked that you have not seen).
=============================================================================
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONVERSE_DIR = _REPO_ROOT / "agents_converse"

_IST = timezone(timedelta(hours=5, minutes=30))

# Canonical agent ids, with the aliases a human or a model might actually type.
# Normalisation matters because the addressee is free text written by another
# agent, and a name that resolves to nothing is never delivered.
#
# THESE NAME HOSTS, NOT MODELS -- deliberately. Each host runs whichever model
# the user picked that day: Codex may be GPT-6 Astra or GPT-5.6 Sol/Terra/Luna,
# and Claude Code swaps between Opus/Sonnet/Fable mid-session (the runtime
# self-state hook exists precisely because that happens). Pinning an alias to a
# model version would rot the moment the user switched, so the generic vendor
# tokens below ("gpt", "claude") carry the routing and the substring fallback in
# normalize_agent() catches any version suffix for free.
_ALIASES: Dict[str, str] = {
    "claude": "claude", "claude code": "claude", "claude-code": "claude",
    "cc": "claude", "opus": "claude", "sonnet": "claude", "fable": "claude",
    "codex": "codex", "codex cli": "codex", "gpt": "codex", "openai": "codex",
    "antigravity": "antigravity", "ag": "antigravity", "anti-gravity": "antigravity",
}
AGENTS = ("claude", "codex", "antigravity")

_ADDRESSEE_RE = re.compile(r"^~\s*(.+?)\s*$", re.M)
_FROM_RE = re.compile(r"^\*\*From:\*\*\s*(.+?)\s*$", re.M)
_SUBJECT_RE = re.compile(r"^#\s*[QA]\s*(\d+)\s*[—\-:]\s*(.+?)\s*$", re.M | re.I)


def normalize_agent(name: str) -> Optional[str]:
    """'Codex CLI' -> 'codex'. None when it matches no known agent."""
    if not name:
        return None
    key = re.sub(r"[^a-z0-9 -]", "", name.strip().lower())
    if key in _ALIASES:
        return _ALIASES[key]
    for alias, canon in _ALIASES.items():          # substring fallback
        if alias in key:
            return canon
    return None


def ist_now() -> str:
    return datetime.now(_IST).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Message:
    number: int
    kind: str            # "q" or "a"
    sender: Optional[str]
    addressee: Optional[str]
    subject: str
    body: str
    path: Path


@dataclass(frozen=True)
class Thread:
    number: int
    question: Message
    answer: Optional[Message]

    @property
    def answered(self) -> bool:
        return self.answer is not None


def parse_message(path: Path) -> Optional[Message]:
    """Read one q_/a_ file. Returns None if it is not a well-formed message."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.match(r"^([qa])_(\d+)\.md$", path.name)
    if not m:
        return None
    kind, number = m.group(1), int(m.group(2))

    subject = ""
    sm = _SUBJECT_RE.search(text)
    if sm:
        subject = sm.group(2)

    sender = None
    fm = _FROM_RE.search(text)
    if fm:
        sender = normalize_agent(fm.group(1))

    # The addressee is the LAST `~ Name` line: the user's own convention, and
    # taking the last one means a quoted `~ Name` inside the body cannot
    # hijack delivery.
    addressee = None
    hits = _ADDRESSEE_RE.findall(text)
    for h in reversed(hits):
        cand = normalize_agent(h)
        if cand:
            addressee = cand
            break

    body = _ADDRESSEE_RE.sub("", text).strip()
    return Message(number, kind, sender, addressee, subject, body, path)


def list_threads(directory: Optional[Path] = None) -> List[Thread]:
    d = Path(directory) if directory is not None else CONVERSE_DIR
    if not d.exists():
        return []
    questions: Dict[int, Message] = {}
    answers: Dict[int, Message] = {}
    for p in sorted(d.glob("[qa]_*.md")):
        msg = parse_message(p)
        if msg is None:
            continue
        (questions if msg.kind == "q" else answers)[msg.number] = msg
    return [Thread(n, questions[n], answers.get(n)) for n in sorted(questions)]


def pending_for(agent: str, directory: Optional[Path] = None) -> List[Thread]:
    """Unanswered questions addressed to `agent`."""
    who = normalize_agent(agent)
    return [t for t in list_threads(directory)
            if not t.answered and t.question.addressee == who]


def replies_for(agent: str, directory: Optional[Path] = None) -> List[Thread]:
    """Answered threads where `agent` was the one who asked."""
    who = normalize_agent(agent)
    return [t for t in list_threads(directory)
            if t.answered and t.question.sender == who]


def next_number(directory: Optional[Path] = None) -> int:
    threads = list_threads(directory)
    return (max((t.number for t in threads), default=0)) + 1


def ask(addressee: str, subject: str, body: str, sender: str,
        directory: Optional[Path] = None) -> Path:
    """Write q_NNN.md. The file is never modified after this."""
    who = normalize_agent(addressee)
    if who is None:
        raise ValueError(f"unknown addressee {addressee!r}; known: {AGENTS}")
    frm = normalize_agent(sender) or sender
    d = Path(directory) if directory is not None else CONVERSE_DIR
    d.mkdir(parents=True, exist_ok=True)
    n = next_number(d)
    path = d / f"q_{n:03d}.md"
    path.write_text(
        f"# Q{n:03d} — {subject}\n\n"
        f"**From:** {frm}\n"
        f"**Date:** {ist_now()}\n\n"
        f"{body.strip()}\n\n"
        f"~ {who}\n",
        encoding="utf-8")
    return path


def answer(number: int, body: str, sender: str,
           directory: Optional[Path] = None) -> Path:
    """Write a_NNN.md beside the question. Refuses to overwrite an answer."""
    d = Path(directory) if directory is not None else CONVERSE_DIR
    q = d / f"q_{number:03d}.md"
    if not q.exists():
        raise FileNotFoundError(f"no question {q.name} to answer")
    a = d / f"a_{number:03d}.md"
    if a.exists():
        raise FileExistsError(
            f"{a.name} already exists — a thread is answered once. "
            f"Ask a follow-up with --ask instead of editing history.")
    qmsg = parse_message(q)
    subject = qmsg.subject if qmsg else ""
    back_to = (qmsg.sender if qmsg and qmsg.sender else "claude")
    frm = normalize_agent(sender) or sender
    a.write_text(
        f"# A{number:03d} — {subject}\n\n"
        f"**From:** {frm}\n"
        f"**Date:** {ist_now()}\n"
        f"**Answering:** {q.name}\n\n"
        f"{body.strip()}\n\n"
        f"~ {back_to}\n",
        encoding="utf-8")
    return a


def render_check(agent: str, directory: Optional[Path] = None) -> str:
    """The text an adapter injects at session start. Empty when nothing waits."""
    who = normalize_agent(agent)
    if who is None:
        return ""
    pend = pending_for(who, directory)
    mine = [t for t in replies_for(who, directory)]
    if not pend and not mine:
        return ""
    lines = ["AGENT MAIL — messages in agents_converse/ (git is the transport)."]
    if pend:
        lines.append(f"\n{len(pend)} QUESTION(S) ADDRESSED TO YOU, unanswered:")
        for t in pend:
            frm = t.question.sender or "unknown"
            lines.append(f"  [{t.question.path.name}] from {frm}: {t.question.subject}")
        lines.append("  Read one with:  python3 scripts/agent_mail.py --read <N>")
        lines.append("  Answer it with: python3 scripts/agent_mail.py --answer <N> --body \"...\"")
        lines.append("  Then commit and push so the asker can pull it.")
    if mine:
        lines.append(f"\n{len(mine)} answer(s) to questions you asked:")
        for t in mine:
            frm = (t.answer.sender if t.answer else None) or "unknown"
            lines.append(f"  [{t.answer.path.name}] from {frm}: {t.question.subject}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Agent-to-agent mail over git.")
    p.add_argument("--check", metavar="AGENT", help="what is waiting for this agent")
    p.add_argument("--list", action="store_true", help="every thread")
    p.add_argument("--read", type=int, metavar="N", help="print thread N")
    p.add_argument("--ask", metavar="ADDRESSEE")
    p.add_argument("--answer", type=int, metavar="N")
    p.add_argument("--subject", default="")
    p.add_argument("--body", default="")
    p.add_argument("--from", dest="sender", default="claude")
    args = p.parse_args()

    if args.check:
        out = render_check(args.check)
        print(out if out else f"no mail for {args.check}")
        return 0

    if args.list:
        threads = list_threads()
        if not threads:
            print("agents_converse/ is empty — no threads yet.")
            return 0
        for t in threads:
            mark = "ANSWERED" if t.answered else "OPEN    "
            frm = t.question.sender or "?"
            to = t.question.addressee or "?"
            print(f"  {mark} {t.number:03d}  {frm} -> {to}  {t.question.subject}")
        return 0

    if args.read is not None:
        d = CONVERSE_DIR
        for name in (f"q_{args.read:03d}.md", f"a_{args.read:03d}.md"):
            fp = d / name
            if fp.exists():
                print(f"===== {name} =====")
                print(fp.read_text(encoding="utf-8"))
        return 0

    if args.ask:
        if not args.subject or not args.body:
            p.error("--ask needs --subject and --body")
        path = ask(args.ask, args.subject, args.body, args.sender)
        print(f"wrote {path.relative_to(_REPO_ROOT)} — commit and push it")
        return 0

    if args.answer is not None:
        if not args.body:
            p.error("--answer needs --body")
        path = answer(args.answer, args.body, args.sender)
        print(f"wrote {path.relative_to(_REPO_ROOT)} — commit and push it")
        return 0

    p.print_help()
    return 0


# =============================================================================
# SMOKE TESTS (offline, temp dirs — never touches the real agents_converse/)
# =============================================================================

def _run_self_test() -> None:
    import tempfile
    print("=" * 70)
    print("  agent_mail.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    # --- normalize_agent ---
    check("T1 canonical names resolve",
          normalize_agent("codex") == "codex" and normalize_agent("claude") == "claude")
    check("T2 aliases resolve (the addressee is free text another model wrote)",
          normalize_agent("Claude Code") == "claude"
          and normalize_agent("Antigravity") == "antigravity")
    # Routing must survive the user switching models on either host -- Codex can
    # be Astra or any Sol/Terra/Luna, Claude Code swaps Opus/Sonnet/Fable.
    check("T2b ANY model version routes to its HOST, so no alias goes stale "
          "when the user switches models",
          all(normalize_agent(n) == "codex" for n in
              ("GPT-6 Astra", "gpt-5.6 Sol", "GPT-5.6 Terra", "gpt-5.6-luna", "codex"))
          and all(normalize_agent(n) == "claude" for n in
                  ("Opus 5", "claude-sonnet-5", "Fable 5.1")),
          str([normalize_agent(n) for n in ("gpt-5.6 Sol", "Fable 5.1")]))
    check("T3 an unknown name resolves to None, not a wrong agent",
          normalize_agent("Gemini") is None and normalize_agent("") is None)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # --- ask / parse ---
        qp = ask("codex", "Why does capture use a watermark?", "Explain the design.",
                 sender="claude", directory=d)
        check("T4 ask() writes q_001.md", qp.name == "q_001.md" and qp.exists())
        m = parse_message(qp)
        check("T5 the `~ Name` convention is parsed as the addressee",
              m.addressee == "codex", str(m))
        check("T6 sender and subject round-trip",
              m.sender == "claude" and "watermark" in m.subject, str(m))

        # --- pending detection ---
        check("T7 it is pending for codex, and NOT for claude",
              len(pending_for("codex", d)) == 1 and len(pending_for("claude", d)) == 0)

        # --- answering ---
        ap = answer(1, "Because a global watermark re-scans forever.", sender="codex",
                    directory=d)
        check("T8 answer() writes a SEPARATE file, leaving the question untouched",
              ap.name == "a_001.md" and qp.read_text(encoding="utf-8").count("~ codex") == 1)
        check("T9 answering clears the pending state (derived, not a status field)",
              len(pending_for("codex", d)) == 0)
        check("T10 the thread is now answered and addressed back to the asker",
              list_threads(d)[0].answered
              and parse_message(ap).addressee == "claude")

        # --- the conflict-avoidance invariant ---
        try:
            answer(1, "second answer", sender="codex", directory=d)
            check("T11 answering twice is REFUSED (a file is written by one party once)",
                  False, "no exception raised")
        except FileExistsError:
            check("T11 answering twice is REFUSED (a file is written by one party once)", True)

        try:
            answer(99, "x", sender="codex", directory=d)
            check("T12 answering a nonexistent question is refused", False)
        except FileNotFoundError:
            check("T12 answering a nonexistent question is refused", True)

        # --- numbering ---
        ask("antigravity", "second question", "body", sender="codex", directory=d)
        check("T13 numbering increments across threads",
              (d / "q_002.md").exists() and next_number(d) == 3)
        check("T14 routing is per-agent: q_002 is pending for antigravity only",
              len(pending_for("antigravity", d)) == 1
              and len(pending_for("codex", d)) == 0)

        # --- render_check ---
        txt = render_check("antigravity", d)
        check("T15 render_check names the file and tells the agent how to answer",
              "q_002.md" in txt and "--answer" in txt, txt[:120])
        check("T16 render_check is EMPTY when nothing waits (hooks must stay silent)",
              render_check("claude", d).count("QUESTION(S) ADDRESSED TO YOU") == 0)
        check("T17 an unknown agent gets empty output, never a crash",
              render_check("gemini", d) == "")

        # --- robustness ---
        (d / "q_003.md").write_text("# Q003 — no addressee\n\nbody only\n", encoding="utf-8")
        # An addressee-less question must be UNDELIVERABLE, never misdelivered to
        # whichever agent happens to check first. (This assertion was originally
        # written as `... is False or True`, which is tautologically green --
        # caught on first read, and the exact always-passing shape this repo has
        # found before. Now it actually asserts.)
        m3 = parse_message(d / "q_003.md")
        check("T18 a question with no ~ line is pending for NOBODY "
              "(undeliverable, not misdelivered to whoever checks first)",
              m3 is not None and m3.addressee is None
              and not any(any(t.number == 3 for t in pending_for(a, d))
                          for a in AGENTS),
              str(m3.addressee if m3 else "unparsed"))
        (d / "notes.md").write_text("not a message", encoding="utf-8")
        check("T19 unrelated files in the directory are ignored",
              len(list_threads(d)) == 3)
        check("T20 a missing directory yields no threads, not an error",
              list_threads(d / "nope") == [])

        # --- the body-hijack guard ---
        (d / "q_004.md").write_text(
            "# Q004 — quoting\n\n**From:** codex\n\n"
            "Someone earlier wrote:\n> ~ antigravity\n\nBut this is really for:\n\n~ claude\n",
            encoding="utf-8")
        check("T21 the LAST ~ line wins, so a quoted one cannot hijack delivery",
              parse_message(d / "q_004.md").addressee == "claude",
              str(parse_message(d / "q_004.md").addressee))

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    for n in failed:
        print(f"    - {n}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _run_self_test()
    raise SystemExit(main())
