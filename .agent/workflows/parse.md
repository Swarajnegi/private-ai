# Antigravity Parse Workflow

**Description**: Parses pending turns from the user's conversation history according to the Memory Contract.

**Steps**:
1. Run `python scripts/ingest_antigravity_sessions.py` to queue recent turns.
2. Run `python scripts/parse_turns.py --pending --host antigravity --limit 20` to fetch turns.
3. Format judgements into a JSON file following `PARSE_RULE v1`.
4. Run `python scripts/parse_turns.py --submit <file> --agent antigravity/<model>` to submit verdicts.
