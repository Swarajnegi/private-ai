"""
coercion.py

JARVIS Agent Layer: tolerant tool-argument coercion (STEAL #13).

Import with:
    from jarvis_core.agent.coercion import coerce_arguments

LAYER: Agent (Tools — the owned function-calling harness)

=============================================================================
THE BIG PICTURE
=============================================================================

We own the tool-calling harness; we do NOT depend on a provider's native
function-calling endpoint. Over a remote TEXT API we cannot bias a model's
logits, so true constrained decoding is impossible — the owned equivalent of
function-calling reliability is a robust parse -> COERCE -> validate -> repair
pipeline. This module is the COERCE step.

The failure it fixes (live, gpt-4o-mini, 2026-06-18): a weak model emits VALID
JSON tool calls with WRONG field NAMES — {"file_name": ...} when file_read
wants `path`; {"file_path": ...}; {"query": ...} for a search tool whose fields
are name_glob/content_regex. The JSON parses; Pydantic (extra="forbid") then
rejects it. Without coercion the model just gets a raw validation error back
and guesses another wrong key, burning iterations.

coerce_arguments() maps an LLM's near-miss argument keys onto a schema's
canonical field names, CONSERVATIVELY, before validation. Anything it cannot
resolve UNAMBIGUOUSLY is left untouched so validation still fails cleanly and
the repair layer (errors.classify_error) hands the model the real schema. Every
remap is recorded in `notes` — no invisible operations.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Introspect the schema: canonical field names and per-field declared
        aliases (Field(json_schema_extra={"aliases": [...]})).
        |
STEP 2: Build a normalized accepted-key -> canonical map. A field's OWN name
        always wins over an alias; a normalized alias that maps to TWO different
        fields is AMBIGUOUS and dropped (never bound by declaration order).
        |
STEP 3: Pass 1 — assign every exact-canonical key (the model got it right).
        Pass 2 — for the rest, remap ONLY via normalized-name / declared-alias
        match (never clobbering an already-filled canonical field).
        |
STEP 4: Return (coerced_dict, notes). Any key NOT matched by name/alias is kept
        VERBATIM — there is deliberately no bind-by-elimination guess (binding a
        semantically unknown key onto a lone required field is a wrong-bind-that-
        succeeds, worse than a clean failure). Unresolved keys make Pydantic fail
        cleanly so the repair layer hands the model the real schema.

=============================================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, Type


def _norm(s: Any) -> str:
    """Case- and separator-insensitive key: 'fileName'/'file_name'/'file-name' -> 'filename'."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def coerce_arguments(
    raw_args: Any, input_schema: Type[Any]
) -> Tuple[Any, List[str]]:
    """
    Map an LLM's near-miss argument keys onto `input_schema`'s canonical fields.

    CONSERVATIVE by construction: a canonical key the model got right is never
    overwritten; an ambiguous or unrecognized key is left verbatim (so Pydantic
    still rejects it and the repair layer shows the real schema). Every remap is
    recorded in the returned notes.

    Args:
        raw_args:     The model's `arguments` dict (passed through unchanged if
                      not a dict — defensive).
        input_schema: A Pydantic model class exposing model_json_schema().

    Returns:
        (coerced_args, notes) — notes is a human-readable list of every remap.
    """
    if not isinstance(raw_args, dict):
        return raw_args, []

    try:
        schema = input_schema.model_json_schema()
    except Exception:
        return dict(raw_args), []

    props: Dict[str, Any] = schema.get("properties", {}) or {}
    if not props:
        return dict(raw_args), []

    # Normalized accepted-key -> canonical field.
    #   Pass A: every field's OWN name (always wins).
    #   Pass B: declared aliases, but ONLY when unambiguous — a normalized alias
    #   that maps to TWO different fields is dropped (ambiguous -> falls through to
    #   repair, never bound by declaration order). A field name always beats an
    #   alias on collision.
    accept: Dict[str, str] = {}
    for field in props:
        accept.setdefault(_norm(field), field)
    alias_to_fields: Dict[str, set] = {}
    for field, spec in props.items():
        if not isinstance(spec, dict):
            continue
        for alias in (spec.get("aliases") or []):
            na = _norm(alias)
            if na in accept:           # already a field name -> field name wins
                continue
            alias_to_fields.setdefault(na, set()).add(field)
    for na, fields_set in alias_to_fields.items():
        if len(fields_set) == 1:       # unambiguous alias only
            accept[na] = next(iter(fields_set))

    coerced: Dict[str, Any] = {}
    notes: List[str] = []

    # Pass 1: exact-canonical keys (the model got these right) — they take priority.
    for k, v in raw_args.items():
        if k in props:
            coerced[k] = v

    # Pass 2: remap the rest via normalized-name / declared-alias match ONLY. There
    # is deliberately NO bind-by-elimination heuristic: binding a semantically
    # unknown key onto the lone required field (e.g. {"url": ...} -> file_read.path)
    # is a wrong-bind-that-succeeds — worse than a clean failure. Anything not
    # resolved by an explicit name/alias match is left verbatim so Pydantic rejects
    # it and the repair layer hands the model the real schema (conservatism > recall).
    for k, v in raw_args.items():
        if k in props:
            continue
        target = accept.get(_norm(k))
        if target is None:
            coerced.setdefault(k, v)   # unresolved -> kept verbatim (clean fail)
            continue
        if target in coerced:
            notes.append(f"ignored duplicate argument '{k}' (already have '{target}')")
            continue
        coerced[target] = v
        notes.append(f"coerced argument '{k}' -> '{target}'")

    return coerced, notes


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — inline Pydantic schemas)
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from typing import Optional
    from pydantic import Field
    from jarvis_core.agent.tool import ToolInput

    print("=" * 66)
    print("  coercion.py — Smoke Tests")
    print("=" * 66)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    class ReadIn(ToolInput):
        path: str = Field(json_schema_extra={
            "aliases": ["file_path", "filepath", "file_name", "filename", "file"]})
        max_bytes: int = Field(default=1000)

    class SearchIn(ToolInput):
        name_glob: Optional[str] = Field(
            default=None, json_schema_extra={"aliases": ["glob", "name_pattern"]})
        content_regex: Optional[str] = Field(
            default=None, json_schema_extra={"aliases": ["regex", "grep"]})
        max_results: int = Field(default=20)

    class OneReq(ToolInput):
        path: str  # required, NO declared aliases

    # T1: exact keys pass through, no notes
    c, n = coerce_arguments({"path": "x", "max_bytes": 50}, ReadIn)
    check("T1 exact passthrough", c == {"path": "x", "max_bytes": 50} and n == [], f"{c} {n}")

    # T2: declared semantic alias (file_name -> path) — the live repro
    c, n = coerce_arguments({"file_name": "workflow_rules.txt"}, ReadIn)
    check("T2 file_name -> path", c == {"path": "workflow_rules.txt"}, str(c))
    check("T2b remap noted", any("file_name" in x and "path" in x for x in n), str(n))

    # T2c: the other observed miss (file_path -> path)
    c, _ = coerce_arguments({"file_path": "/a/b"}, ReadIn)
    check("T2c file_path -> path", c == {"path": "/a/b"}, str(c))

    # T3: case/separator normalization (maxResults -> max_results)
    c, n = coerce_arguments({"path": "x", "maxResults": 5}, SearchIn)  # maxResults vs max_results
    # SearchIn has no `path`; maxResults normalizes to max_results
    c2, _ = coerce_arguments({"maxResults": 5}, SearchIn)
    check("T3 maxResults -> max_results", c2 == {"max_results": 5}, str(c2))

    # T4: AMBIGUOUS 'query' on a no-required-field search -> NOT coerced (left for repair)
    c, n = coerce_arguments({"query": "spark"}, SearchIn)
    check("T4 ambiguous 'query' left verbatim", c == {"query": "spark"} and n == [], f"{c} {n}")

    # T5 (SAFETY — the HIGH fix): a lone SEMANTICALLY-UNKNOWN key is NOT bound onto
    # the single required field. No bind-by-elimination: {"url": ...} must NOT become
    # file_read's path (a wrong-bind-that-succeeds). Left verbatim -> clean fail -> repair.
    c, n = coerce_arguments({"location": "/etc/hosts"}, OneReq)
    check("T5 lone unknown key NOT bound to required field", c == {"location": "/etc/hosts"} and n == [],
          f"{c} {n}")
    c2, _ = coerce_arguments({"url": "/etc/passwd"}, OneReq)
    check("T5b no bind-by-elimination ({'url'} !-> path)", c2 == {"url": "/etc/passwd"}, str(c2))

    # T6: collision — model sent BOTH canonical and an alias -> canonical wins, no clobber
    c, n = coerce_arguments({"path": "RIGHT", "file_name": "WRONG"}, ReadIn)
    check("T6 canonical wins over alias", c["path"] == "RIGHT", str(c))
    check("T6b duplicate noted, not clobbered",
          any("duplicate" in x for x in n) and "WRONG" not in str(c.get("path")), f"{c} {n}")

    # T7: non-dict input returned as-is
    c, n = coerce_arguments("not a dict", ReadIn)
    check("T7 non-dict passthrough", c == "not a dict" and n == [])

    # T8: a known alias for one required field still works (the legit single-field case)
    class OneAliased(ToolInput):
        path: str = Field(json_schema_extra={"aliases": ["file", "location"]})
    c, _ = coerce_arguments({"location": "/real/file"}, OneAliased)
    check("T8 declared alias for a required field DOES bind", c == {"path": "/real/file"}, str(c))

    # T9: a field's OWN name beats another field's alias on a normalized collision
    class Collide(ToolInput):
        path: str = Field(default="")                                  # field named 'path'
        target: str = Field(default="", json_schema_extra={"aliases": ["path"]})  # alias 'path'
    c, _ = coerce_arguments({"path": "v"}, Collide)
    check("T9 field-name beats alias", c == {"path": "v"}, str(c))

    # T10: multiple unresolved keys -> all kept verbatim, no guessing
    c, n = coerce_arguments({"a": 1, "b": 2}, OneReq)
    check("T10 multiple unresolved -> no guess", c == {"a": 1, "b": 2}, str(c))

    # T11 (collision fix): the SAME alias declared on TWO fields is AMBIGUOUS -> dropped,
    # so the key is NOT bound by declaration order; it falls through to repair.
    class AmbAlias(ToolInput):
        src: str = Field(default="", json_schema_extra={"aliases": ["source"]})
        dst: str = Field(default="", json_schema_extra={"aliases": ["source"]})
    c, n = coerce_arguments({"source": "X"}, AmbAlias)
    check("T11 ambiguous cross-field alias NOT bound (left verbatim)",
          c == {"source": "X"} and n == [], f"{c} {n}")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 66)
        raise SystemExit(1)
    print(f"  All {total} coercion smoke tests passed.")
    print("=" * 66)
