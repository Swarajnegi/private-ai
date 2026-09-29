"""
client_infra.py — mask a client's INFRASTRUCTURE identifiers in text that goes into git.

LAYER: Memory (capture hygiene)

Run with:
    python -m jarvis_core.agent.client_infra            # self-test

=============================================================================
THE BIG PICTURE
=============================================================================

The owner sometimes pastes the client's production pipeline code into chats.
Chat text is tracked in git (observation_queue.jsonl, the episode shards). The
rule in CLAUDE.md is that client source, connection strings, workspace URLs and
table names never enter a tracked file; the owner's own decision (2026-08-26)
also keeps the training corpus, which holds redacted client CODE, in the
private repo. So the line drawn here is narrow and exact:

    MASKED  -> the client's environment identifiers: catalog and schema names
               (bdp4_prod_lh, stg_lrc_g2), source table names (lrc_...),
               workspace hostnames, storage-account hostnames.
    KEPT    -> everything else: the owner's own words, the code's structure,
               and the employer/client NAMES, which run through the KB and the
               profile by the owner's decision and are stripped separately by
               brain/outbound_policy.py before anything reaches a provider.

Each identifier becomes a STABLE pseudonym derived from a hash of itself
("bdp4_prod_lh" -> "cli_a1b2c3d4"), so the same catalog is the same token in
every chat and joins still read correctly for training, while the real name is
not recoverable from the repo. The hash is salted with a fixed public string:
it is a pseudonym, not encryption, and an attacker who already knows a
candidate name can confirm it. That is acceptable for the stated goal, which is
keeping the names out of plain text.

=============================================================================
THE FLOW
=============================================================================

STEP 1: mask(text) applies each pattern in _PATTERNS.
        |
STEP 2: every match is replaced by pseudonym(match); the count is returned so
        callers can record how much was masked.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import List, Tuple

_SALT = "jarvis-client-infra-v1:"

_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("catalog", re.compile(r"\bbdp\d?_[A-Za-z0-9_]+")),
    ("schema", re.compile(r"\bstg_(?:lrc|peoplesoft)[A-Za-z0-9_]*", re.IGNORECASE)),
    ("table", re.compile(r"\blrc_[A-Za-z0-9_]+", re.IGNORECASE)),
    ("workspace", re.compile(r"\badb-\d{6,}\.\d+\.azuredatabricks\.net", re.IGNORECASE)),
    ("storage", re.compile(r"\b[a-z0-9]{3,24}\.(?:dfs|blob)\.core\.windows\.net", re.IGNORECASE)),
)


def pseudonym(identifier: str) -> str:
    digest = hashlib.sha256((_SALT + identifier.lower()).encode("utf-8")).hexdigest()
    return f"cli_{digest[:8]}"


def mask(text: str) -> Tuple[str, int]:
    """(masked text, number of identifiers masked)."""
    total = 0
    for _kind, rx in _PATTERNS:
        text, n = rx.subn(lambda m: pseudonym(m.group(0)), text)
        total += n
    return text, total


def _self_test() -> int:
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    src = 'spark.readStream.table("bdp4_prod_lh.stg_lrc_g2.lrc_actual_balancesheet_total")'
    out, n = mask(src)
    check("T1 catalog, schema and table names are masked", n == 3 and "bdp4" not in out and "lrc_" not in out, out)
    check("T2 the code's structure survives",
          out.startswith('spark.readStream.table("cli_') and out.endswith('")'), out)
    check("T3 the same identifier maps to the same pseudonym everywhere",
          mask("bdp4_prod_lh")[0] == mask("use bdp4_prod_lh;")[0].split()[1].rstrip(";"))
    check("T4 workspace and storage hostnames are masked",
          mask("adb-1234567890123456.7.azuredatabricks.net")[1] == 1
          and mask("acct01.dfs.core.windows.net")[1] == 1)
    plain = "I want the deepclone job kept for Celebal work and my own notes"
    check("T5 the owner's words and employer names are left alone", mask(plain) == (plain, 0))
    check("T6 masking is idempotent", mask(mask(src)[0])[1] == 0)
    print(f"  {6 - len(failed)}/6 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.exit(_self_test())
