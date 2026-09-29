#!/usr/bin/env python3
"""
mail_watch.py — UserPromptSubmit adapter: the agent-mail channel, checked on every prompt.

LAYER: Tools (thin host adapter over scripts/agent_mail.py)

Run with:
    (as a Claude Code UserPromptSubmit hook: JSON event on stdin)
    python scripts/hooks/mail_watch.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

check_agent_mail.py looks at the mail once, at SessionStart. Codex and
Antigravity answer minutes or hours later, and a session can run all day, so a
reply could sit unread and a question addressed to Claude could block another
agent until the next session. The owner asked (2026-09-29) for the channel to
work by itself: detect Codex's reply, ask when a question is needed, and answer
questions addressed to Claude.

What a hook can and cannot do here. A hook is a script, not the model. The
Claude Code CLI is not installed on this machine (the editor extension is), so
a hook cannot start a second instance of Claude to draft a reply. What it CAN
do is make the reply happen on the very next prompt, without anyone asking: it
puts the full text of each new reply and each open question into the model's
context and orders an answer before the user's request. The model then answers
"to its best" and sends it with agent_mail.py. A reply is never faked by a
script, so a message signed `claude` is always written by Claude.

Sending questions by itself is deterministic, needs no model, and is limited:
  - REMINDER: a question Claude sent that has stood unanswered for REMIND_AFTER_S
    gets one follow-up.
  - BACKLOG STATUS: when Codex's or Antigravity's parse backlog is over
    BACKLOG_LIMIT turns, ask what blocks them, at most once per ASK_EVERY_S.
Neither kind is ever answered with another automatic question (subjects start
with "Reminder:" / "Status:"), so two hooks can never ping-pong.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load agent_mail; read state (which replies were already shown).
        |
STEP 2: open questions to Claude -> quoted in full every prompt until answered.
        New replies to Claude's questions -> quoted in full once.
        |
STEP 3: apply the two auto-ask rules, record each in the state file.
        |
STEP 4: emit one additionalContext; say nothing when there is nothing to say.
        Always exit 0: a broken hook must never disrupt a turn.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REMIND_AFTER_S = 2 * 3600
ASK_EVERY_S = 12 * 3600
BACKLOG_LIMIT = 200
BACKLOG_CHECK_EVERY_S = 30 * 60
FRESH_REPLY_S = 6 * 3600          # first run: replies newer than this still count as new
_ROOT = Path(__file__).resolve().parents[2]
def state_path_for(agent: str) -> Path:
    return _ROOT / "jarvis_data" / f".mail_watch_{agent}.json"


STATE_PATH = state_path_for("claude")
_AUTO = ("Reminder:", "Status:")


def _organ():
    sys.path.insert(0, str(_ROOT / "scripts"))
    import agent_mail
    return agent_mail


def _backlog() -> Dict[str, Dict[str, Any]]:
    sys.path.insert(0, str(_ROOT / "js-development"))
    from jarvis_core.agent.parse_ledger import backlog
    return backlog()


def _load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, state: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def watch(directory: Optional[Path] = None, state_path: Path = STATE_PATH,
          now: Optional[float] = None, backlog_fn=_backlog, organ: Any = None,
          agent: str = "claude", auto_ask: bool = True) -> str:
    """The context to inject this prompt ('' when nothing waits) and any questions sent."""
    now = time.time() if now is None else now
    organ = organ or _organ()
    state = _load(state_path)
    first_run = not state
    seen: List[int] = list(state.get("seen_answers", []))
    auto: Dict[str, float] = dict(state.get("auto_asks", {}))
    parts: List[str] = []

    pending = organ.pending_for(agent, directory)
    if pending:
        parts.append(f"{len(pending)} QUESTION(S) ADDRESSED TO YOU are waiting. Answer each NOW, before "
                     "the user's request, to the best of your ability from the repo and this session, "
                     "and send it (the asker is blocked until you do):")
        for t in pending:
            frm = t.question.sender or "unknown"
            parts.append(f"\n--- q_{t.number:03d} from {frm}: {t.question.subject}\n{t.question.body}\n"
                         f"Send with: python scripts/agent_mail.py --answer {t.number} --from {agent} --body \"...\"")

    new_replies = []
    for t in organ.replies_for(agent, directory):
        if t.number in seen:
            continue
        seen.append(t.number)
        if first_run and now - t.answer.path.stat().st_mtime > FRESH_REPLY_S:
            continue                      # old history, not news
        new_replies.append(t)
    for t in new_replies:
        frm = (t.answer.sender if t.answer else None) or "unknown"
        parts.append(f"\nNEW REPLY from {frm} to your q_{t.number:03d} ({t.question.subject}):\n"
                     f"{t.answer.body}\nRead it, act on it, and reply if it needs one.")

    sent: List[str] = []
    threads = organ.list_threads(directory) if auto_ask else []
    open_by_addressee: Dict[str, int] = {}
    for t in threads:
        if not t.answered and t.question.sender == agent:
            open_by_addressee[t.question.addressee or ""] = open_by_addressee.get(t.question.addressee or "", 0) + 1
    for t in threads:
        q = t.question
        if t.answered or q.sender != agent or q.subject.startswith(_AUTO):
            continue
        key = f"reminder:{t.number}"
        if key in auto or now - q.path.stat().st_mtime < REMIND_AFTER_S or not q.addressee:
            continue
        path = organ.ask(q.addressee, f"Reminder: q_{t.number:03d} is still unanswered",
                         f"My question q_{t.number:03d} ({q.subject}) has been open for "
                         f"{(now - q.path.stat().st_mtime) / 3600:.1f} h. Please answer it with "
                         f"`python scripts/agent_mail.py --answer {t.number} --from {q.addressee} --body \"...\"`, "
                         "or say what blocks you.", agent, directory)
        auto[key] = now
        sent.append(f"reminder to {q.addressee} about q_{t.number:03d} ({path.name})")

    if auto_ask and now - float(state.get("last_backlog_check", 0)) >= BACKLOG_CHECK_EVERY_S:
        state["last_backlog_check"] = now
        try:
            counts = backlog_fn()
        except Exception:                # noqa: BLE001
            counts = {}
        for host in [h for h in ("claude", "codex", "antigravity") if h != agent]:
            info = counts.get(host) or {}
            n, key = int(info.get("pending") or 0), f"backlog:{host}"
            if n <= BACKLOG_LIMIT or now - float(auto.get(key, 0)) < ASK_EVERY_S:
                continue
            if any(not t.answered and t.question.sender == agent and t.question.addressee == host
                   and t.question.subject.startswith("Status:") for t in threads):
                continue                  # the last status question is still open
            path = organ.ask(host, f"Status: {n} unparsed {host} turns",
                             f"The parse ledger shows {n} unparsed {host} turns, oldest "
                             f"{info.get('oldest', '?')}. Are you draining them by READING each turn (10-20 at "
                             "a time, a rationale per verdict), and what blocks you? Reply with the number you "
                             f"cleared and how many remain. See NERVOUS_SYSTEM.md section 3.", agent, directory)
            auto[key] = now
            sent.append(f"status question to {host} ({path.name})")

    state["seen_answers"], state["auto_asks"] = seen, auto
    _save(state_path, state)
    if sent:
        parts.append("\nAUTO-SENT by the mail hook (no model involved): " + "; ".join(sent) + ".")
    if not parts:
        return ""
    return "AGENT MAIL (checked on every prompt by scripts/hooks/mail_watch.py):\n" + "\n".join(parts)


def main() -> int:
    try:
        raw = sys.stdin.read()
        json.loads(raw) if raw.strip() else None
        agent = sys.argv[sys.argv.index("--agent") + 1] if "--agent" in sys.argv else "claude"
        body = watch(state_path=state_path_for(agent), agent=agent,
                     auto_ask="--no-auto-ask" not in sys.argv)
        if body:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                     "additionalContext": body}}))
    except BaseException:                # noqa: BLE001
        pass
    return 0


def _self_test() -> int:
    import tempfile
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    organ = _organ()
    with tempfile.TemporaryDirectory() as td:
        d, st = Path(td) / "converse", Path(td) / "state.json"
        no_backlog = lambda: {}                                        # noqa: E731
        t0 = time.time()
        check("T1 an empty channel says nothing", watch(d, st, t0, no_backlog, organ) == "")
        organ.ask("claude", "How do you run the loop?", "Please explain.", "codex", d)
        body = watch(d, st, t0, no_backlog, organ)
        check("T2 a question to Claude is quoted in full with the answer command",
              "Please explain." in body and "--answer 1" in body and "NOW" in body, body)
        check("T3 it is repeated every prompt until answered", "Please explain." in watch(d, st, t0, no_backlog, organ))
        organ.answer(1, "Like this.", "claude", d)
        check("T4 once answered it stops", watch(d, st, t0, no_backlog, organ) == "")

        organ.ask("codex", "Which corpus?", "Tell me.", "claude", d)
        check("T5 an unanswered question of Claude's is quiet at first", watch(d, st, t0 + 60, no_backlog, organ) == "")
        later = watch(d, st, t0 + REMIND_AFTER_S + 60, no_backlog, organ)
        threads = organ.list_threads(d)
        check("T6 after 2 h one reminder is sent to the addressee, and reported",
              "AUTO-SENT" in later and any(t.question.subject.startswith("Reminder:") for t in threads), later)
        again = watch(d, st, t0 + REMIND_AFTER_S + 120, no_backlog, organ)
        n = sum(t.question.subject.startswith("Reminder:") for t in organ.list_threads(d))
        check("T7 no second reminder, and a reminder is never reminded about", n == 1, f"{n} {again}")

        organ.answer(2, "Engineer.", "codex", d)
        got = watch(d, st, t0 + REMIND_AFTER_S + 180, no_backlog, organ)
        check("T8 a new reply from Codex is shown in full, once",
              "NEW REPLY from codex" in got and "Engineer." in got
              and "NEW REPLY" not in watch(d, st, t0 + REMIND_AFTER_S + 240, no_backlog, organ), got)

        big = lambda: {"codex": {"pending": 900, "oldest": "2026-09-07"}, "antigravity": {"pending": 5, "oldest": "x"}}  # noqa: E731
        s1 = watch(d, st, t0 + 4 * 3600, big, organ)
        subj = [t.question.subject for t in organ.list_threads(d)]
        check("T9 a backlog over the limit triggers one status question to that agent only",
              "AUTO-SENT" in s1 and any(s.startswith("Status: 900 unparsed codex") for s in subj)
              and not any("antigravity" in s for s in subj), str(subj))
        watch(d, st, t0 + 4 * 3600 + BACKLOG_CHECK_EVERY_S + 60, big, organ)
        check("T10 it does not repeat within the ask window",
              sum(s.startswith("Status:") for s in [t.question.subject for t in organ.list_threads(d)]) == 1)
    print(f"  {10 - len(failed)}/10 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(main())
