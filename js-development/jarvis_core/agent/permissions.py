"""
permissions.py

JARVIS Agent Layer: STEAL #9 Hook-Driven Permission Engine.

Import with:
    from jarvis_core.agent.permissions import (
        PermissionDecision, PermissionRule, PermissionContext, PermissionError,
    )

This module provides:
    1. PermissionDecision -- Enum of allow/ask/deny verdicts
    2. PermissionRule     -- Frozen dataclass matching (tool_name, tool_input)
                             against substring or regex patterns
    3. PermissionContext  -- Engine that combines async classifiers + rule list
                             into a single decision per tool call
    4. PermissionError    -- Raised by callers when a denial occurs at an
                             allow-only path

=============================================================================
THE BIG PICTURE
=============================================================================

Without a permission engine:
    -> Every unsafe tool (shell, file write, network) decides for itself
       whether to run. The agent can invoke `bash("rm -rf /")` and the
       tool happily executes because no gate sits in front of it.
    -> Safety policy is scattered across tool code -- impossible to audit
       and impossible to override per-session.
    -> There is no extension point for context-aware policy (e.g. "block
       if cwd is outside /workspace"); the only knob is the global
       requires_permission boolean.

With a permission engine (STEAL #9):
    -> A declarative rule list expresses static policy:
           PermissionRule("bash", ALLOW, input_pattern="ls ")
           PermissionRule("bash", DENY,  input_pattern="rm ")
    -> Async classifiers express dynamic policy: a coroutine inspects the
       tool input and returns a PermissionDecision (or None to defer).
       Classifier verdict wins over rules, so context-aware checks can
       override a generic ALLOW.
    -> A single PermissionContext.check() call returns ALLOW/ASK/DENY for
       any (tool_name, tool_input). The dispatcher gates execution on it.
    -> Default is ASK -- the engine fails closed: if nothing matches and
       no classifier weighs in, a human must approve.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Operator builds a PermissionContext at session start:
            ctx = PermissionContext.from_dict({
                "default": "ask",
                "rules": [
                    {"tool_name": "memory_search", "decision": "allow"},
                    {"tool_name": "bash", "decision": "deny",
                     "input_pattern": "rm |sudo ", "pattern_is_regex": True},
                ],
            })
        ↓
STEP 2: Tool-specific classifiers register on the context:
            ctx.register_classifier("bash", bash_safety_classifier)
        Each classifier is an async callable returning PermissionDecision
        or None. None means "I don't have an opinion; fall through to rules".
        ↓
STEP 3: For each tool invocation the dispatcher calls:
            decision = await ctx.check("bash", {"command": "ls -la"})
        ↓
STEP 4: check() runs the classifier first (highest priority):
            - PermissionDecision returned -> use it
            - None returned                -> fall through to rules
            - Exception raised             -> log to stderr, fall through
        ↓
STEP 5: Walk rules in insertion order. First matching rule wins:
            - rule.tool_name == "*" or matches the tool name
            - input_pattern is None, OR substring/regex matches the
              json.dumps-serialized tool_input
        ↓
STEP 6: No rule matched -> return self._default (ASK).
        ↓
STEP 7: Dispatcher reacts:
            ALLOW -> invoke directly
            ASK   -> prompt human, then invoke or skip
            DENY  -> raise PermissionError, never invoke
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional


# =============================================================================
# Part 1: PERMISSION DECISION ENUM
# =============================================================================

class PermissionDecision(str, Enum):
    """The three verdicts the engine can return for a tool call."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# =============================================================================
# Part 2: PERMISSION RULE (Frozen dataclass; matches tool calls)
# =============================================================================

# Cap the serialized tool_input length before regex matching. A 16KB cap
# prevents catastrophic backtracking on adversarial input from blocking the
# permission engine for tens of seconds. Inputs larger than this are
# truncated for matching purposes only (the original tool_input is unchanged).
_MAX_SERIALIZED_INPUT_LEN = 16 * 1024


@dataclass(frozen=True)
class PermissionRule:
    """
    LAYER: Agent -- Declarative rule mapping a (tool_name, tool_input) pattern
    to a PermissionDecision.

    Match logic:
        - tool_name: exact equality OR "*" wildcard.
        - input_pattern: None means "any input"; otherwise the tool_input dict
          is serialized via json.dumps(..., sort_keys=True, default=str) and
          checked against the pattern (substring or regex).

    Regex validation: when pattern_is_regex=True, the pattern is compiled
    at construction time via __post_init__. A bad regex fails immediately
    with ValueError instead of crashing on first check() call.
    """
    tool_name: str
    decision: PermissionDecision
    input_pattern: Optional[str] = None
    pattern_is_regex: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.input_pattern is not None and self.pattern_is_regex:
            try:
                re.compile(self.input_pattern)
            except re.error as exc:
                raise ValueError(
                    f"PermissionRule input_pattern is not a valid regex: "
                    f"{self.input_pattern!r} ({exc})"
                ) from exc

    def matches(self, tool_name: str, tool_input: Dict[str, Any]) -> bool:
        """True iff this rule fires for the given tool call.

        Safety: exceptions during json.dumps or re.search are swallowed and
        treated as 'no match'. A buggy rule must never break the gate.
        """
        if self.tool_name != "*" and self.tool_name != tool_name:
            return False

        if self.input_pattern is None:
            return True

        try:
            serialized = json.dumps(tool_input, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False

        if len(serialized) > _MAX_SERIALIZED_INPUT_LEN:
            serialized = serialized[:_MAX_SERIALIZED_INPUT_LEN]

        try:
            if self.pattern_is_regex:
                return re.search(self.input_pattern, serialized) is not None
            return self.input_pattern in serialized
        except re.error:
            return False


# =============================================================================
# Part 3: ASYNC CLASSIFIER TYPE ALIAS
# =============================================================================

# A classifier is an async function that inspects tool_input and returns
# either a verdict (ALLOW/ASK/DENY) or None to defer to the rule list.
AsyncClassifier = Callable[[Dict[str, Any]], Awaitable[Optional[PermissionDecision]]]


# =============================================================================
# Part 4: PERMISSION CONTEXT (Engine combining classifiers + rules)
# =============================================================================

class PermissionContext:
    """
    LAYER: Agent -- The engine resolving (tool_name, tool_input) into a
    PermissionDecision.

    Priority order (highest first):
        1. Async classifier registered for the tool (if any).
           - Returns PermissionDecision -> final verdict.
           - Returns None              -> fall through to rules.
           - Raises exception          -> logged to stderr, falls through.
        2. First matching PermissionRule in insertion order.
        3. The default (constructor argument; ASK if unset).
    """

    def __init__(
        self,
        rules: Optional[List[PermissionRule]] = None,
        default: PermissionDecision = PermissionDecision.ASK,
    ) -> None:
        self._rules: List[PermissionRule] = list(rules) if rules else []
        self._default: PermissionDecision = default
        self._classifiers: Dict[str, AsyncClassifier] = {}

    def add_rule(self, rule: PermissionRule) -> None:
        """Append a rule. Insertion order determines match precedence."""
        self._rules.append(rule)

    def register_classifier(self, tool_name: str, classifier: AsyncClassifier) -> None:
        """Bind an async classifier to a tool. Replaces any prior one."""
        self._classifiers[tool_name] = classifier

    async def check(self, tool_name: str, tool_input: Dict[str, Any]) -> PermissionDecision:
        """Resolve a verdict for one (tool_name, tool_input) call.

        Safety: classifier exceptions are caught + logged. Non-PermissionDecision
        return values (e.g. a buggy classifier returning a raw string) are
        treated as None and the engine falls through to rules.
        """
        classifier = self._classifiers.get(tool_name)
        if classifier is not None:
            try:
                verdict = await classifier(tool_input)
                if isinstance(verdict, PermissionDecision):
                    return verdict
                if verdict is not None:
                    print(
                        f"[permissions] classifier for '{tool_name}' returned "
                        f"non-PermissionDecision value {verdict!r}; "
                        f"falling back to rules",
                        file=sys.stderr,
                    )
            except Exception as exc:
                # Classifier must never crash the gate; log and fall through.
                print(
                    f"[permissions] classifier for '{tool_name}' raised "
                    f"{type(exc).__name__}: {exc}; falling back to rules",
                    file=sys.stderr,
                )

        for rule in self._rules:
            try:
                if rule.matches(tool_name, tool_input):
                    return rule.decision
            except Exception as exc:
                print(
                    f"[permissions] rule {rule!r} raised {type(exc).__name__}: "
                    f"{exc}; skipping",
                    file=sys.stderr,
                )

        return self._default

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "PermissionContext":
        """
        Build a PermissionContext from a plain-dict config (e.g. parsed JSON).

        Schema:
            {
              "default": "ask" | "allow" | "deny",
              "rules": [
                {"tool_name": str, "decision": str,
                 "input_pattern": str | None, "pattern_is_regex": bool,
                 "description": str}, ...
              ]
            }
        """
        default_raw = config.get("default", PermissionDecision.ASK.value)
        default = PermissionDecision(default_raw)

        rules: List[PermissionRule] = []
        for raw in config.get("rules", []):
            rules.append(
                PermissionRule(
                    tool_name=raw["tool_name"],
                    decision=PermissionDecision(raw["decision"]),
                    input_pattern=raw.get("input_pattern"),
                    pattern_is_regex=bool(raw.get("pattern_is_regex", False)),
                    description=raw.get("description", ""),
                )
            )

        return cls(rules=rules, default=default)


# =============================================================================
# Part 5: PERMISSION ERROR
# =============================================================================

class PermissionError(Exception):
    """Raised when an ALLOW path was expected but the engine returned DENY."""


# =============================================================================
# MAIN ENTRY POINT (Smoke tests)
# =============================================================================

if __name__ == "__main__":
    import asyncio

    async def smoke_test() -> None:
        print("=" * 60)
        print("  permissions.py -- Smoke Test")
        print("=" * 60)

        passed = 0
        failed: List[str] = []

        def check(name: str, cond: bool, hint: str = "") -> None:
            nonlocal passed
            if cond:
                passed += 1
            else:
                failed.append("FAIL: " + name + ((" (" + hint + ")") if hint else ""))

        # ---- T1: exact tool_name, no input pattern --------------------------
        r1 = PermissionRule("bash", PermissionDecision.ALLOW)
        check("T1 exact tool_name match", r1.matches("bash", {"command": "ls"}))
        check("T1 different tool no match", not r1.matches("python", {"command": "ls"}))

        # ---- T2: wildcard ---------------------------------------------------
        r2 = PermissionRule("*", PermissionDecision.DENY)
        check("T2 wildcard matches any tool", r2.matches("anything", {"x": 1}))
        check("T2 wildcard matches another", r2.matches("bash", {"command": "rm"}))

        # ---- T3: substring input pattern ------------------------------------
        r3 = PermissionRule("bash", PermissionDecision.DENY, input_pattern="rm ")
        check("T3 substring matches rm",
              r3.matches("bash", {"command": "rm -rf /tmp/x"}))
        check("T3 substring misses ls",
              not r3.matches("bash", {"command": "ls -la"}))

        # ---- T4: regex input pattern ----------------------------------------
        r4 = PermissionRule(
            "bash", PermissionDecision.DENY,
            input_pattern=r"(rm\s|sudo\s)", pattern_is_regex=True,
        )
        check("T4 regex matches sudo",
              r4.matches("bash", {"command": "sudo apt update"}))
        check("T4 regex matches rm",
              r4.matches("bash", {"command": "rm file.txt"}))
        check("T4 regex misses plain command",
              not r4.matches("bash", {"command": "echo hi"}))

        # ---- T5: mismatched tool_name returns False -------------------------
        r5 = PermissionRule("bash", PermissionDecision.ALLOW, input_pattern="anything")
        check("T5 mismatched tool returns False",
              not r5.matches("python", {"command": "anything"}))

        # ---- T6: no rules -> default ASK ------------------------------------
        ctx_empty = PermissionContext()
        d6 = await ctx_empty.check("bash", {"command": "ls"})
        check("T6 empty context defaults to ASK", d6 is PermissionDecision.ASK,
              hint=f"got {d6}")

        # ---- T7: first-match-wins ------------------------------------------
        ctx7 = PermissionContext(
            rules=[
                PermissionRule("bash", PermissionDecision.ALLOW, input_pattern="ls "),
                PermissionRule("bash", PermissionDecision.DENY),
            ],
        )
        d7a = await ctx7.check("bash", {"command": "ls -la"})
        d7b = await ctx7.check("bash", {"command": "rm -rf /"})
        check("T7a first ALLOW wins for ls", d7a is PermissionDecision.ALLOW,
              hint=f"got {d7a}")
        check("T7b fallthrough DENY for rm", d7b is PermissionDecision.DENY,
              hint=f"got {d7b}")

        # ---- T8: classifier ALLOW overrides DENY rule ----------------------
        ctx8 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.DENY)],
            default=PermissionDecision.ASK,
        )

        async def always_allow(_inp: Dict[str, Any]) -> Optional[PermissionDecision]:
            return PermissionDecision.ALLOW

        ctx8.register_classifier("bash", always_allow)
        d8 = await ctx8.check("bash", {"command": "rm -rf /"})
        check("T8 classifier ALLOW overrides DENY rule",
              d8 is PermissionDecision.ALLOW, hint=f"got {d8}")

        # ---- T9: classifier None falls through to rules --------------------
        ctx9 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.DENY)],
            default=PermissionDecision.ALLOW,
        )

        async def abstain(_inp: Dict[str, Any]) -> Optional[PermissionDecision]:
            return None

        ctx9.register_classifier("bash", abstain)
        d9 = await ctx9.check("bash", {"command": "anything"})
        check("T9 classifier None falls through to DENY rule",
              d9 is PermissionDecision.DENY, hint=f"got {d9}")

        # ---- T10: classifier exception falls through to rules --------------
        ctx10 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.ALLOW)],
            default=PermissionDecision.DENY,
        )

        async def boom(_inp: Dict[str, Any]) -> Optional[PermissionDecision]:
            raise RuntimeError("classifier is on fire")

        ctx10.register_classifier("bash", boom)
        d10 = await ctx10.check("bash", {"command": "anything"})
        check("T10 classifier exception falls through to ALLOW rule",
              d10 is PermissionDecision.ALLOW, hint=f"got {d10}")

        # ---- T11: from_dict roundtrip --------------------------------------
        ctx11 = PermissionContext.from_dict({
            "default": "deny",
            "rules": [
                {"tool_name": "memory_search", "decision": "allow"},
                {"tool_name": "bash", "decision": "deny",
                 "input_pattern": r"rm\s|sudo\s", "pattern_is_regex": True,
                 "description": "block destructive shell ops"},
                {"tool_name": "*", "decision": "ask"},
            ],
        })
        d11a = await ctx11.check("memory_search", {"q": "anything"})
        d11b = await ctx11.check("bash", {"command": "rm file"})
        d11c = await ctx11.check("bash", {"command": "echo hi"})
        d11d = await ctx11.check("unknown_tool", {"x": 1})
        check("T11a memory_search -> ALLOW", d11a is PermissionDecision.ALLOW,
              hint=f"got {d11a}")
        check("T11b bash rm -> DENY", d11b is PermissionDecision.DENY,
              hint=f"got {d11b}")
        check("T11c bash echo -> ASK (via wildcard)",
              d11c is PermissionDecision.ASK, hint=f"got {d11c}")
        check("T11d unknown -> ASK (via wildcard)",
              d11d is PermissionDecision.ASK, hint=f"got {d11d}")

        # ---- T12: ALLOW for safe + DENY for dangerous ----------------------
        ctx12 = PermissionContext(
            rules=[
                PermissionRule("memory_search", PermissionDecision.ALLOW),
                PermissionRule("bash", PermissionDecision.DENY,
                               input_pattern="rm "),
            ],
            default=PermissionDecision.ASK,
        )
        d12a = await ctx12.check("memory_search", {"q": "anything"})
        d12b = await ctx12.check("bash", {"command": "rm -rf /"})
        d12c = await ctx12.check("bash", {"command": "ls"})
        check("T12a memory_search ALLOW", d12a is PermissionDecision.ALLOW,
              hint=f"got {d12a}")
        check("T12b dangerous bash DENY", d12b is PermissionDecision.DENY,
              hint=f"got {d12b}")
        check("T12c safe bash falls to ASK default",
              d12c is PermissionDecision.ASK, hint=f"got {d12c}")

        # ---- T13: add_rule preserves insertion order -----------------------
        ctx13 = PermissionContext(default=PermissionDecision.ASK)
        ctx13.add_rule(PermissionRule("bash", PermissionDecision.ALLOW))
        ctx13.add_rule(PermissionRule("bash", PermissionDecision.DENY))
        d13 = await ctx13.check("bash", {"command": "anything"})
        check("T13 add_rule preserves order: first ALLOW wins",
              d13 is PermissionDecision.ALLOW, hint=f"got {d13}")

        # ---- T14: ASK default applies on no match + no classifier ----------
        ctx14 = PermissionContext(
            rules=[PermissionRule("memory_search", PermissionDecision.ALLOW)],
        )
        d14 = await ctx14.check("bash", {"command": "ls"})
        check("T14 ASK default on no match + no classifier",
              d14 is PermissionDecision.ASK, hint=f"got {d14}")

        # ---- T15: bad regex fails at construction --------------------------
        try:
            PermissionRule("bash", PermissionDecision.DENY,
                           input_pattern="(unclosed", pattern_is_regex=True)
            check("T15 bad regex fails at construction", False, hint="no error")
        except ValueError:
            check("T15 bad regex fails at construction", True)

        # ---- T16: json.dumps failure does not crash check -------------------
        # tool_input with circular reference cannot serialize -> rule skipped
        # (returns False from matches, falls to default).
        circular: Dict[str, Any] = {}
        circular["self"] = circular
        ctx16 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.DENY,
                                  input_pattern="anything")],
            default=PermissionDecision.ASK,
        )
        d16 = await ctx16.check("bash", circular)
        check("T16 circular input -> rule skipped -> ASK default",
              d16 is PermissionDecision.ASK, hint=f"got {d16}")

        # ---- T17: serialized input length cap (no ReDoS) -------------------
        # Massive input + greedy regex would hang without the 16KB cap.
        # We just verify it returns and doesn't take forever.
        huge_input = {"data": "x" * (100 * 1024)}
        ctx17 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.DENY,
                                  input_pattern="x+", pattern_is_regex=True)],
            default=PermissionDecision.ASK,
        )
        import time as _time
        _t0 = _time.time()
        d17 = await ctx17.check("bash", huge_input)
        _elapsed = _time.time() - _t0
        check("T17 huge input bounded under cap",
              d17 is PermissionDecision.DENY and _elapsed < 1.0,
              hint=f"got {d17} in {_elapsed:.3f}s")

        # ---- T18: classifier returns non-PermissionDecision (buggy) --------
        async def bad_clf(ti: Dict[str, Any]) -> Any:
            return "allow"  # raw string, NOT PermissionDecision
        ctx18 = PermissionContext(
            rules=[PermissionRule("bash", PermissionDecision.DENY)],
            default=PermissionDecision.ASK,
        )
        ctx18.register_classifier("bash", bad_clf)
        d18 = await ctx18.check("bash", {"command": "rm"})
        check("T18 non-PermissionDecision verdict -> fall through to rules",
              d18 is PermissionDecision.DENY, hint=f"got {d18}")

        # ---- T19: rule with bad regex caught at construction -> safe ------
        # (T15 covered this; T19 verifies that a valid regex still works
        # after the __post_init__ check.)
        good_rule = PermissionRule("bash", PermissionDecision.ALLOW,
                                   input_pattern=r"^safe.*",
                                   pattern_is_regex=True)
        check("T19 valid regex constructs ok",
              good_rule.input_pattern == r"^safe.*")

        # ---- Report ---------------------------------------------------------
        total = passed + len(failed)
        print("\n  Passed:", passed, "/", total)
        if failed:
            for f_ in failed:
                print("  " + f_)
            raise SystemExit(1)
        print("  All", total, "smoke tests passed.")

    asyncio.run(smoke_test())
