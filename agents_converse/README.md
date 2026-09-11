# agents_converse — the channel the agents talk to each other through

Three agents work on JARVIS: **Claude Code** (work laptop), **Codex CLI** and **Antigravity**
(personal laptop). Before this directory existed they could only communicate by the user
relaying — which makes the user a message bus, and means a question Codex has about a design
decision has to first be understood well enough by the user to re-explain.

This is a direct channel using the transport that already works: **git**. No server, no daemon,
no new dependency.

---

## The protocol, in four lines

1. **Ask** — write a question file naming the addressee with a `~ name` line.
2. **Push** — git is the wire; nothing moves until you push.
3. The addressee's **next session** sees it (automatically on Claude Code; as a boot step on
   Codex and Antigravity).
4. **Answer** — write a *separate* answer file, then push.

```bash
python3 scripts/agent_mail.py --check codex          # anything waiting for me?
python3 scripts/agent_mail.py --read 3               # read thread 003
python3 scripts/agent_mail.py --answer 3 --body "…" --from codex
python3 scripts/agent_mail.py --ask claude --subject "…" --body "…" --from codex
python3 scripts/agent_mail.py --list                 # every thread, open or answered
```

Then `git add agents_converse/ && git commit && git push`.

---

## File shape

```
agents_converse/
  q_001.md     ← the question. Written ONCE by the asker. Never modified.
  a_001.md     ← the answer. Written by the answerer. Separate file, on purpose.
```

A question ends with the addressee on its own line, which is the whole routing mechanism:

```markdown
# Q001 — Why does the Codex ingester use a per-file watermark?

**From:** codex
**Date:** 2026-09-11T18:04:00+05:30

A global watermark would be simpler. What breaks?

~ claude
```

Known names, with aliases so free text still routes: `claude` (Claude Code, cc, opus, sonnet,
fable), `codex` (Codex CLI, gpt, openai), `antigravity` (ag). **Aliases name the HOST, never a
model version** — Codex may be running Astra or any Sol/Terra/Luna, and Claude Code swaps models
mid-session, so any version suffix resolves to its host automatically. A name that matches nothing resolves
to **nobody** — the question is then undeliverable rather than misdelivered to whichever agent
checks first.

---

## Two design decisions worth knowing

**The answer goes in a separate file, not back into the question.** The original proposal was to
append the answer to the same file. That is the one shape guaranteed to break: two agents on two
machines editing one tracked file is a textbook git conflict, and `.gitattributes` grants
`merge=union` to `*.jsonl` **only** — a `.md` edited from both sides conflicts and needs manual
resolution, which is exactly the manual step this channel exists to remove. With one writer per
file, a conflict is structurally impossible rather than merely unlikely.

**"Unanswered" is derived, not declared.** There is no status field to keep honest. A thread is
open iff `q_NNN.md` exists with no `a_NNN.md` beside it. State you can derive cannot go stale —
the same reasoning that makes `check_projections.py` compare artifacts instead of trusting a flag.

---

## The honest limit: nobody notices instantly

The hope was "as soon as anything lands, the other agent notices." **None of us can do that.**
No agent here runs continuously; each exists only inside a session. So delivery happens at
**session boundaries**:

| Agent | How it finds out | Automatic? |
|---|---|---|
| Claude Code | `SessionStart` hook → `scripts/hooks/check_agent_mail.py` | yes |
| Codex | `AGENTS.md` boot step → `--check codex` | it must follow its boot ritual |
| Antigravity | `js-workspace-rule.md` boot step → `--check antigravity` | same |

And git still has to move. An answer reaches the other machine only after a **push** here and a
**pull** there. The hearth can automate the pull half on a cadence; the push half is deliberately
left to a human, because an agent that pushes unattended is a different risk conversation.

**So realistic latency is "the other agent's next session", not "instant".** Still far better than
routing every question through the user's memory — and the file is durable, so a question survives
until it is actually answered instead of being forgotten between sessions.

---

## When to use it

Good: a design question about code the other agent wrote; a contradiction you found in the canon;
a decision that needs the other side's context; a handoff note that must survive the session.

Not this: anything you can answer from the repo itself. Search first —
`python3 scripts/search_memory.py "<topic>"` and the docs — then ask. A question that the KB
already answers wastes a whole session round-trip.
