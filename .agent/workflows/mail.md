# Antigravity Mail Workflow

**Description**: Checks and processes agent mail on Antigravity (portable hookless host).

**When to Run**:
- At session boot (before first reply).
- At the start of every reply / prompt.
- Every ~10 turns alongside `parse.md`.

**Steps**:
1. Run `python scripts/hooks/mail_watch.py --agent antigravity --no-auto-ask --plain`.
   - If output is empty, there is no pending mail; proceed.
   - If new replies or unanswered questions appear, review them completely.
2. For each question addressed to Antigravity (`q_NNN.md`):
   - Draft a complete, grounded answer addressing all specific queries.
   - Send the reply via:
     `python scripts/agent_mail.py --answer <N> --from antigravity --body "..."`
3. If asking another agent a blocking question:
   `python scripts/agent_mail.py --ask <agent> --subject "..." --body "..." --from antigravity`
4. Stage, commit, and push if running git sync.
