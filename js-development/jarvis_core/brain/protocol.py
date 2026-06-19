"""
protocol.py — ProtocolAdapter (Stage 4.1 Wave 2: per-model wire dialects).

LAYER: Brain (Orchestration — the owned model-protocol seam)

Import with:
    from jarvis_core.brain.protocol import ProtocolAdapter, adapt

=============================================================================
THE BIG PICTURE
=============================================================================

Different model endpoints speak slightly different WIRE dialects. The Mind and
the ReActLoop must never learn this — they emit one portable message list and
get text back. ProtocolAdapter is the thin middleware that wraps an `LLMCall`
and applies a model's wire quirks transparently, so the dialect lives in ONE
named place instead of leaking into the agent loop.

HONEST SCOPE (do not inflate this — most "dialects" are already handled at the
correct layer and moving them here would be churn, not value):
  - empty reasoning-channel content  -> already retried in llm_client.
  - mirror / monitor / max_iterations -> already profile-resolved in boot.
  - malformed tool-call JSON          -> already repaired in react (STEAL #13).
  - proprietary tool markup           -> already avoided at pick_free_model.
So the adapter's ONE net-new transform is **system-prompt folding**: some
endpoints reject a `system` role entirely; for those, the system message must
be folded into the first user turn. Everything else here is the documented SEAM
where a FUTURE wire quirk lands (and the SUGGEST-only catalog capability read).

Default is PASSTHROUGH — `fold_system=False` returns the messages byte-identical,
so wrapping a normal model changes nothing.

=============================================================================
THE FLOW
=============================================================================

STEP 1: adapt(inner_llm_call, profile) reads `profile.system_role_ok` -> sets
        fold_system. (Or pass fold_system explicitly; profile is optional so
        protocol.py stays decoupled from model_profiles.py.)
        |
STEP 2: On each call, _transform(messages): if fold_system, merge every system
        message into the first user turn (order-preserving); else passthrough.
        |
STEP 3: Invoke the inner LLMCall (sync OR async — awaited if awaitable), return
        text. The wrapper IS an LLMCall, so the Mind sees no difference.

=============================================================================
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

LLMCall = Callable[[List[Dict[str, str]]], Union[str, Awaitable[str]]]


def _fold_system_into_user(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Merge every `system` message into the first `user` turn (order-preserving).
    For endpoints that reject a system role. If there is no user turn, the folded
    system text becomes a leading user turn."""
    system_parts = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
    if not system_parts:
        return list(messages)
    preamble = "\n\n".join(p for p in system_parts if p.strip())
    out: List[Dict[str, str]] = []
    folded = False
    for m in messages:
        if m.get("role") == "system":
            continue  # dropped — its content moves into the first user turn
        if not folded and m.get("role") == "user":
            content = m.get("content", "")
            merged = f"{preamble}\n\n{content}" if preamble else content
            out.append({"role": "user", "content": merged})
            folded = True
        else:
            out.append(dict(m))
    if not folded:  # no user turn existed — prepend the system text as one
        out.insert(0, {"role": "user", "content": preamble})
    return out


class ProtocolAdapter:
    """Wraps an LLMCall to apply a model's WIRE dialect transparently. IS an
    LLMCall itself (messages -> text, sync inner awaited). Passthrough by default."""

    def __init__(self, inner: LLMCall, *, fold_system: bool = False, label: str = "") -> None:
        self._inner = inner
        self._fold_system = fold_system
        self._label = label

    @property
    def model(self) -> str:
        # Transparently surface the inner client's model id if it has one, so
        # the adapter is a drop-in for code that reads `.model` (orchestrator).
        return str(getattr(self._inner, "model", "") or "")

    def __getattr__(self, name: str) -> Any:
        # Forward unknown attribute access (ledger_summary, pick_free_model, ...)
        # to the wrapped client so the adapter is a faithful stand-in. Guarded so
        # an __init__-bypass path (copy.deepcopy / pickle.loads / __new__) can't
        # recurse forever probing a missing `_inner`, and dunders fall back to
        # Python defaults instead of being forwarded.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    def _transform(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if self._fold_system:
            return _fold_system_into_user(messages)
        # Fresh dicts (not just a new list): a future inner that annotates a
        # message in place must not leak back into the caller's dicts.
        return [dict(m) for m in messages]

    async def __call__(self, messages: List[Dict[str, str]]) -> str:
        out = self._inner(self._transform(messages))
        if inspect.isawaitable(out):
            out = await out
        return str(out)


def adapt(
    inner: LLMCall,
    profile: Optional[Any] = None,
    *,
    fold_system: Optional[bool] = None,
    label: str = "",
) -> ProtocolAdapter:
    """Wrap `inner` per a ModelProfile (read via getattr to stay decoupled).
    Explicit `fold_system` overrides the profile. Default = passthrough."""
    if fold_system is None:
        fold_system = profile is not None and not getattr(profile, "system_role_ok", True)
    return ProtocolAdapter(inner, fold_system=bool(fold_system), label=label)


def suggest_from_catalog(catalog_entry: Optional[Dict[str, Any]]) -> List[str]:
    """SUGGEST-ONLY capability notes from a catalog entry — NEVER auto-applied to
    a profile (the override-only invariant: a human flips conduct flags on live
    evidence). Returns human-readable suggestions for review."""
    if not isinstance(catalog_entry, dict):
        return []
    notes: List[str] = []
    ctx = catalog_entry.get("context_length")
    if isinstance(ctx, int) and ctx and ctx < 16000:
        notes.append(f"SUGGEST: small context ({ctx}) — consider a lower observation_max_chars.")
    if catalog_entry.get("is_multimodal"):
        notes.append("SUGGEST: multimodal — vision inputs supported (not used by the text loop).")
    return notes


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — scripted inner)
# =============================================================================

def _run_self_test() -> None:
    import asyncio

    print("=" * 66)
    print("  protocol.py — Smoke Tests")
    print("=" * 66)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    def run(coro):
        return asyncio.run(coro)

    # An inner that ECHOES the messages it received, so we can assert the wire shape.
    seen: Dict[str, Any] = {}
    def echo_inner(messages):
        seen["messages"] = messages
        return "OK"
    async def aecho_inner(messages):
        seen["messages"] = messages
        return "OK-async"

    sys_user = [
        {"role": "system", "content": "SYS-RULES"},
        {"role": "user", "content": "the question"},
    ]

    # T1: passthrough (fold_system=False) — messages byte-identical
    a1 = ProtocolAdapter(echo_inner, fold_system=False)
    run(a1(sys_user))
    check("T1 passthrough keeps system role", seen["messages"] == sys_user, str(seen["messages"]))

    # T2: fold_system=True — system merged into first user, system role gone
    a2 = ProtocolAdapter(echo_inner, fold_system=True)
    run(a2(sys_user))
    folded = seen["messages"]
    check("T2 system role removed", all(m["role"] != "system" for m in folded), str(folded))
    check("T2b system text folded into user",
          folded[0]["role"] == "user" and "SYS-RULES" in folded[0]["content"]
          and "the question" in folded[0]["content"], str(folded))

    # T3: fold with NO user turn -> system becomes a leading user turn
    a3 = ProtocolAdapter(echo_inner, fold_system=True)
    run(a3([{"role": "system", "content": "ONLY-SYS"}]))
    check("T3 system-only folds to a user turn",
          seen["messages"] == [{"role": "user", "content": "ONLY-SYS"}], str(seen["messages"]))

    # T4: multiple system messages concatenated in order, history preserved
    a4 = ProtocolAdapter(echo_inner, fold_system=True)
    run(a4([{"role": "system", "content": "S1"}, {"role": "system", "content": "S2"},
            {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"}]))
    m = seen["messages"]
    check("T4 multi-system folded into FIRST user, order kept",
          m[0]["content"].startswith("S1\n\nS2") and "u1" in m[0]["content"]
          and m[1] == {"role": "assistant", "content": "a1"}
          and m[2] == {"role": "user", "content": "u2"}, str(m))

    # T5: async inner awaited; sync inner works
    check("T5 sync inner returns text", run(a1(sys_user)) == "OK")
    check("T5b async inner awaited",
          run(ProtocolAdapter(aecho_inner, fold_system=False)(sys_user)) == "OK-async")

    # T6: adapt() reads profile.system_role_ok (decoupled via getattr)
    class _P:
        def __init__(self, ok): self.system_role_ok = ok
    fold_p = adapt(echo_inner, _P(False)); run(fold_p(sys_user))
    check("T6 profile system_role_ok=False -> folds",
          all(x["role"] != "system" for x in seen["messages"]), str(seen["messages"]))
    pass_p = adapt(echo_inner, _P(True)); run(pass_p(sys_user))
    check("T6b profile system_role_ok=True -> passthrough", seen["messages"] == sys_user)
    none_p = adapt(echo_inner, None); run(none_p(sys_user))
    check("T6c no profile -> passthrough (default)", seen["messages"] == sys_user)
    expl = adapt(echo_inner, _P(True), fold_system=True); run(expl(sys_user))
    check("T6d explicit fold_system overrides profile",
          all(x["role"] != "system" for x in seen["messages"]))

    # T7: messages with NO system -> unchanged regardless of fold_system
    nosys = [{"role": "user", "content": "hi"}]
    run(ProtocolAdapter(echo_inner, fold_system=True)(nosys))
    check("T7 no-system passthrough under fold", seen["messages"] == nosys, str(seen["messages"]))

    # T8: .model + attribute forwarding (drop-in for the client)
    class _Client:
        model = "vendor/x"
        def ledger_summary(self): return {"model": "vendor/x", "calls": 3}
        def __call__(self, messages): return "C"
    wrapped = ProtocolAdapter(_Client(), fold_system=False)
    check("T8 .model forwarded", wrapped.model == "vendor/x")
    check("T8b unknown attr forwarded (ledger_summary)",
          wrapped.ledger_summary()["calls"] == 3)

    # T9: suggest_from_catalog is SUGGEST-only (returns notes, mutates nothing)
    entry = {"context_length": 8000, "is_multimodal": True}
    sugg = suggest_from_catalog(entry)
    check("T9 catalog suggestions returned, entry untouched",
          any("small context" in s for s in sugg) and any("multimodal" in s for s in sugg)
          and entry == {"context_length": 8000, "is_multimodal": True}, str(sugg))
    check("T9b non-dict -> no suggestions", suggest_from_catalog(None) == [])

    # T10 (verify-fix #5): passthrough returns FRESH dicts — a future inner that
    # mutates a received message must not leak back into the caller's dicts.
    caller = [{"role": "user", "content": "orig"}]
    def mutating_inner(messages):
        messages[0]["content"] = "MUTATED"   # hostile inner
        return "x"
    run(ProtocolAdapter(mutating_inner, fold_system=False)(caller))
    check("T10 passthrough isolates caller dicts", caller[0]["content"] == "orig",
          str(caller))

    # T11 (verify-fix #4): __getattr__ must NOT infinite-recurse on an __init__-
    # bypass (deepcopy / pickle / __new__) — it returns/raises cleanly instead.
    import copy
    bare = ProtocolAdapter.__new__(ProtocolAdapter)   # no _inner set
    try:
        _ = bare.anything                              # would RecursionError pre-fix
        check("T11 __getattr__ no recursion on missing _inner", False, "expected AttributeError")
    except AttributeError:
        check("T11 __getattr__ no recursion on missing _inner", True)
    except RecursionError:
        check("T11 __getattr__ no recursion on missing _inner", False, "RecursionError")
    try:
        copy.deepcopy(ProtocolAdapter(echo_inner, fold_system=False))
        check("T11b deepcopy survives (no recursion)", True)
    except RecursionError:
        check("T11b deepcopy survives (no recursion)", False, "RecursionError")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 66)
        raise SystemExit(1)
    print(f"  All {total} protocol smoke tests passed.")
    print("=" * 66)


if __name__ == "__main__":
    _run_self_test()
