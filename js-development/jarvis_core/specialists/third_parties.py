"""
third_parties.py — keep people who never consented out of the weights.

LAYER: Specialists (Corpus Assembly)

Run with:
    PYTHONPATH=js-development python3 -m jarvis_core.specialists.third_parties   # smoke tests

=============================================================================
THE BIG PICTURE
=============================================================================

The user's own life is theirs to train on — ENDGAME §2 draws the line at
"yours to send / not yours to send", not at personal versus impersonal. The
people IN that life sit on the other side of the line: a partner, friends,
family. They never consented to being baked into model weights, and weights
cannot be un-trained the way a file can be deleted.

Excluding personal_life.md from the corpus (2026-09-23) was necessary and NOT
sufficient. Measured the same day: the same people still reached training
through three other doors — the conversations where the user first described
them (chat_history), the user's own typed prompts (user_voice), and a KB
identity entry. A partner's name was in 6 blend records and 1 SFT pair. The
file had been distilled FROM those conversations, so removing the distillate
left the source untouched.

So the unit of protection is the PERSON, not the file. This module replaces
each listed identifier with a role placeholder — "my [partner] also works
there" — which keeps the user's own story (theirs to train on) and removes the
other person's identity (not theirs to give).

=============================================================================
WHY A LIST, WHEN text_hygiene.py ARGUES AGAINST LISTS
=============================================================================

text_hygiene.py rejects blocklists, correctly: it classifies an OPEN set
(every string a machine might emit), where a list is always one entry short.
This is the opposite case. The set of people is CLOSED and EXPLICIT — the user
knows exactly who their partner is — so a list is the exact tool, and any
classifier would be strictly worse, because it would have to guess.

WHAT THIS DOES NOT COVER, stated so nobody assumes it does: anyone who is not
in jarvis_data/third_parties.json. A newly-mentioned friend reaches training
until someone adds them. check_pipeline enforces the list; nothing enforces
the completeness of the list. Identifiers are word-bounded, so an inflected
form the list does not name (an honorific suffix, say) is also missed.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load() reads jarvis_data/third_parties.json and compiles one
        case-insensitive, word-bounded pattern per identifier. A MISSING file
        RAISES — silently redacting nothing is the dangerous direction.
        |
STEP 2: redact(text, people) replaces every hit with "[<role>]" and returns
        the count, so a caller can report how much it removed.
        |
STEP 3: roles_present(text, people) reports WHICH ROLES were found, never the
        identifiers — so an invariant's own output never reprints a name.
=============================================================================
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

People = Tuple[Tuple["re.Pattern[str]", str], ...]


def _default_path() -> Path:
    from jarvis_core.config import DATA_ROOT
    return Path(DATA_ROOT) / "third_parties.json"


def load(path: Optional[Path] = None) -> People:
    """Compiled (pattern, placeholder) pairs, longest identifier first so an
    identifier containing another is replaced whole rather than in pieces."""
    src = path or _default_path()
    data = json.loads(src.read_text(encoding="utf-8"))
    pairs = []
    for person in data.get("people", []):
        placeholder = f"[{person['role']}]"
        for ident in person.get("identifiers", []):
            if ident.strip():
                pairs.append((ident.strip(), placeholder))
    pairs.sort(key=lambda p: -len(p[0]))
    return tuple(
        (re.compile(r"\b" + re.escape(ident) + r"\b", re.IGNORECASE), placeholder)
        for ident, placeholder in pairs
    )


def redact(text: str, people: People) -> Tuple[str, int]:
    """Text with every listed identifier replaced by its role, and the count."""
    total = 0
    for pattern, placeholder in people:
        text, n = pattern.subn(placeholder, text)
        total += n
    return text, total


def roles_present(text: str, people: People) -> List[str]:
    """Placeholders whose identifiers occur in text. Never the identifiers."""
    return sorted({placeholder for pattern, placeholder in people if pattern.search(text)})


# =============================================================================
# Smoke tests — hermetic except T9, which reads the real list read-only
# =============================================================================

def _smoke() -> int:
    import tempfile

    passed = failed = 0

    def check(label: str, got, want) -> None:
        nonlocal passed, failed
        if got == want:
            passed += 1
            print(f"  PASS  {label}")
        else:
            failed += 1
            print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")

    print("=" * 70)
    print("  third_parties smoke tests")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "tp.json"
        f.write_text(json.dumps({"people": [
            {"role": "partner", "identifiers": ["Alice", "Ali"]},
            {"role": "friend", "identifiers": ["Bob"]},
            {"role": "employer", "identifiers": ["ACME"]},
        ]}), encoding="utf-8")
        people = load(f)

        check("T1 a listed name becomes its role",
              redact("I told Alice about it.", people), ("I told [partner] about it.", 1))
        check("T2 matching is case-insensitive",
              redact("alice and BOB", people)[0], "[partner] and [friend]")
        check("T3 a possessive keeps its suffix",
              redact("Alice's laptop", people)[0], "[partner]'s laptop")
        check("T4 word-bounded: an identifier inside a longer word is untouched",
              redact("ACMEcorp and Bobsleigh", people), ("ACMEcorp and Bobsleigh", 0))
        check("T5 the longer identifier wins over one it contains",
              redact("Alice", people)[0], "[partner]")
        check("T6 the count reflects every replacement",
              redact("Bob, Bob, and Alice", people)[1], 3)
        check("T7 text with no identifier is returned unchanged",
              redact("nothing to see here", people), ("nothing to see here", 0))
        check("T8 roles_present reports roles, never identifiers",
              roles_present("Alice met Bob", people), ["[friend]", "[partner]"])

        try:
            load(Path(tmp) / "absent.json")
            check("T10 a missing list RAISES rather than redacting nothing", "no raise", "raised")
        except FileNotFoundError:
            check("T10 a missing list RAISES rather than redacting nothing", "raised", "raised")

    try:
        real = load()
        check("T9 the tracked list loads and is non-empty", len(real) > 0, True)
    except FileNotFoundError:
        check("T9 the tracked list loads and is non-empty", "missing", "present")

    print("-" * 70)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_smoke())
