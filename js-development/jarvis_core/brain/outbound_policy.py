"""
outbound_policy.py — the enforcement point for what may leave this machine.

LAYER: Brain (Cognitive Control Loop — the airlock)

Import with:
    from jarvis_core.brain.outbound_policy import redact_outbound, OutboundPolicy

=============================================================================
THE BIG PICTURE
=============================================================================

JARVIS_ENDGAME.md promised, for months, that "only the final prompt (query +
5 retrieved chunks) leaves the local machine." The code did something else:
boot.py composes a ~5,100-char inhale block — 2,500 chars of cognitive profile
plus 2,400 chars of cross-chat activity — into the system prompt of every real
`--ask` call, which then goes to OpenRouter.

Neither half was wrong on its own. The doc stated a guarantee; the code
implemented a feature; nothing sat between them, so both stayed true-looking
for months. context_injector.py even carries a PASSING test asserting the
profile reaches the system prompt. The defect was never the injection — it was
that a guarantee existed in prose with no place in the code that could enforce
or violate it. Same failure class as KB 521/527: a claim nothing re-checks.

WHAT THIS MODULE IS NOT: a switch that strips personal context. Sending the
user's own cognitive profile is the entire product — a JARVIS that does not
know its owner is a worse ChatGPT, and the owner already stopped opening that.
Measured 2026-09-06, the shipped slice contains ZERO third-party names
(personal_life.md is not a provider; the profile is synthesised from the KB).

The line this draws is therefore NOT personal/impersonal. It is:

    YOURS TO SEND          -> self-assessments, cognitive patterns, working
                              style, preferences, project history. Ships.
    NOT YOURS TO SEND      -> employer and client identifiers. Withheld,
                              because that is an employment and contract
                              question the user already settled once for
                              client_work/ — not a privacy preference.

=============================================================================
THE FLOW
=============================================================================

STEP 1: client_identifiers() derives terms from the client_work/ directory
        names (so a new client project is covered without editing this file)
        and unions them with _EXPLICIT_TERMS for names that never appear as a
        folder (the employer itself).
        |
STEP 2: redact_outbound(text) replaces each term, case-insensitively and on
        word boundaries, with a labelled placeholder. It reports WHAT it
        removed so the caller can log it rather than silently mutating.
        |
STEP 3: ContextInjector.inhale() calls it on every provider's output before
        the per-provider cap is applied — one choke point, all providers,
        including any added later.
=============================================================================
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import CLIENT_WORK_ROOT

# Identifiers that never appear as a client_work/ folder name. The employer is
# the obvious one: it is in the user's own KB prose, not in a project path.
_EXPLICIT_TERMS: FrozenSet[str] = frozenset({"celebal", "bupa", "immuta"})

# Folder-name tokens that carry no identifying weight on their own.
_GENERIC_TOKENS: FrozenSet[str] = frozenset({
    "region", "migration", "project", "client", "work", "prod", "dev", "test",
    "data", "platform", "pipeline", "framework", "gen1", "gen2",
})

_PLACEHOLDER = "[client]"
_MIN_TERM_LEN = 3


@dataclass(frozen=True)
class OutboundPolicy:
    """What the airlock is allowed to let through."""
    redact_client_identifiers: bool = True
    placeholder: str = _PLACEHOLDER


@dataclass(frozen=True)
class RedactionResult:
    """Redacted text plus what was removed — never mutate silently."""
    text: str
    removed: Tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.removed


def client_identifiers(root: Optional[Path] = None) -> FrozenSet[str]:
    """Redaction terms: client_work/ folder tokens ∪ the explicit list.

    Deriving from folder names means onboarding a new client project extends
    coverage automatically. Missing directory is normal — client_work/ is
    gitignored, so it is absent on any freshly cloned machine.
    """
    terms = set(_EXPLICIT_TERMS)
    base = Path(root) if root else Path(CLIENT_WORK_ROOT)
    try:
        entries = [p for p in base.iterdir() if p.is_dir()]
    except (OSError, FileNotFoundError):
        entries = []
    for project in entries:
        for token in re.split(r"[^A-Za-z0-9]+", project.name.lower()):
            if len(token) >= _MIN_TERM_LEN and token not in _GENERIC_TOKENS:
                terms.add(token)
    return frozenset(terms)


def redact_outbound(
    text: str,
    policy: Optional[OutboundPolicy] = None,
    terms: Optional[FrozenSet[str]] = None,
) -> RedactionResult:
    """Strip client identifiers from text bound for a model provider."""
    active = policy or OutboundPolicy()
    if not text or not active.redact_client_identifiers:
        return RedactionResult(text=text, removed=())

    vocabulary = terms if terms is not None else client_identifiers()
    if not vocabulary:
        return RedactionResult(text=text, removed=())

    removed: List[str] = []
    result = text
    # Longest-first so a compound term is not half-consumed by a shorter one.
    for term in sorted(vocabulary, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        result, hits = pattern.subn(active.placeholder, result)
        if hits:
            removed.append(term)
    return RedactionResult(text=result, removed=tuple(sorted(removed)))


# =============================================================================
# SMOKE TESTS (offline — temp dirs, no network, no persistent writes)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  outbound_policy.py -- Smoke Tests")
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

    fixed = frozenset({"bupa", "celebal", "acmecorp"})

    # T1 -- THE CANARY. This is the inverted form of context_injector's T3:
    # that test asserts the profile REACHES the prompt; this one asserts a
    # client identifier does NOT. Together they encode the actual policy.
    canary = "Worked 16-18 hours on the BUPA region migration for Celebal."
    r = redact_outbound(canary, terms=fixed)
    check("T1 canary: client identifiers do not survive",
          "bupa" not in r.text.lower() and "celebal" not in r.text.lower(),
          f"got: {r.text}")

    check("T2 removal is reported, never silent",
          set(r.removed) == {"bupa", "celebal"}, f"got: {r.removed}")

    # T3 -- the whole point of the narrow cut: the user's own voice survives.
    check("T3 the user's own content is preserved",
          "16-18 hours" in r.text and "region migration" in r.text, r.text)

    personal = ("PATTERN: jargon_gap. VERBATIM: 'use simple words and explain "
                "everything properly'. I'm not as intelligent as tony.")
    p = redact_outbound(personal, terms=fixed)
    check("T4 a profile entry with no client name passes through untouched",
          p.text == personal and p.clean, f"removed={p.removed}")

    # T5 -- substring safety: 'bupa' inside a longer word is not an identifier.
    r5 = redact_outbound("The bupashire dataset", terms=fixed)
    check("T5 word-boundary only (no substring mangling)",
          r5.text == "The bupashire dataset", r5.text)

    r6 = redact_outbound("BuPa and bupa and BUPA", terms=fixed)
    check("T6 case-insensitive, all occurrences",
          r6.text.count("[client]") == 3, r6.text)

    off = redact_outbound(canary, policy=OutboundPolicy(
        redact_client_identifiers=False), terms=fixed)
    check("T7 policy is a dial, not a hardcode",
          off.text == canary and off.clean, off.text)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "acme_region_migration").mkdir()
        derived = client_identifiers(root=root)
        check("T8 terms derive from client_work/ folder names",
              "acme" in derived, f"got: {sorted(derived)}")
        check("T9 generic folder tokens are not treated as identifiers",
              "region" not in derived and "migration" not in derived,
              f"got: {sorted(derived)}")

    missing = client_identifiers(root=Path("/nonexistent-client-root"))
    check("T10 absent client_work/ degrades to the explicit list",
          "celebal" in missing, f"got: {sorted(missing)}")

    check("T11 empty input is safe", redact_outbound("").text == "")

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()
