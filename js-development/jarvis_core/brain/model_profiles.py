"""
model_profiles.py — Per-Model Conduct Registry (Stage 4.1 Wave 1).

LAYER: Brain (model-facing strategy — per-model conduct as DATA)

Import with:
    from jarvis_core.brain.model_profiles import ModelProfile, ProfileRegistry

=============================================================================
THE BIG PICTURE
=============================================================================

Different brains need different handling. nemotron buries its output inside the
MIRROR-lite reflection protocol (so mirror must be OFF for it — observed live,
KB L322/L355); another model might be fine with mirror on. Until now that fact
lived as a HARD-CODE: boot.assemble_mind pinned enable_mirror=False at the call
layer, a single model's quirk frozen into the assembler.

This organ makes per-model conduct DATA: a ModelProfile per model (or model
family), resolved by id, applied at boot. The hard-code becomes a row in
model_profiles.json. When Stage 4.2's Router can choose among several models,
nothing here changes — the profile is keyed on a model-id STRING, so the Router
just hands a different id to resolve.

Discipline (so it ages well):
  - OVERRIDES ONLY. A profile stores conduct (mirror_ok, max_iterations, …),
    NEVER catalog fields (context_length, cost, description). The catalog stays
    the single source for those; profiles never desync on a catalog refresh.
  - SAFE DEFAULT. An unknown model resolves to DEFAULT_PROFILE — mirror OFF,
    monitor ON — the live-proven-safe floor. A miss always safe-degrades; it
    never asserts a capability a model lacks.
  - exact → family → DEFAULT. No freetext capability-parsing (Wave 1): the
    catalog's "reasoning"/"function calling" strings are marketing prose and
    would mint wrong-confident profiles. Capability inference is Wave 2, and
    only as a human-reviewed SUGGESTION, never auto-applied.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load model_profiles.json once ({"exact": {...}, "family": {...}}),
        tolerating a missing/malformed file (-> empty registry, DEFAULT only).
        |
STEP 2: get(model_id): exact-id override -> longest family-substring override
        -> DEFAULT_PROFILE. Returns (ModelProfile, source_label) so the host
        can prove WHICH rule fired.
        |
STEP 3: boot applies the profile (enable_mirror / enable_monitor /
        max_iterations); the BootReport records the source_label.

=============================================================================
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import MODEL_PROFILES_PATH

# Only these keys are conduct overrides a profiles file may set. Anything else
# (e.g. a stray "context_length") is IGNORED — the override-only invariant that
# keeps profiles from duplicating, and desyncing from, the catalog.
_OVERRIDE_KEYS = frozenset({
    "mirror_ok", "enable_monitor", "max_iterations", "reasoning_channel",
    "notes", "observation_max_chars", "system_role_ok",
})


# =============================================================================
# Part 1: CONTRACT (frozen)
# =============================================================================

@dataclass(frozen=True)
class ModelProfile:
    """How JARVIS should CONDUCT a given brain. Conduct only — never catalog facts."""
    mirror_ok: bool = False          # MIRROR-lite safe? (False = the proven floor)
    enable_monitor: bool = True      # CoT instability monitor on?
    max_iterations: int = 8          # ReAct iteration ceiling for this brain
    reasoning_channel: bool = False  # Wave-1 DOC ONLY: empty-content retry already
                                     # handles this unconditionally; not yet enforced.
    notes: str = ""                  # why this conduct (cite the live observation)
    observation_max_chars: Optional[int] = None  # forward-compat; NOT threaded in Wave 1
    system_role_ok: bool = True      # 4.1 W2: does this model accept a `system` role?
                                     # False -> ProtocolAdapter folds system into the
                                     # first user turn. Default True (the OpenRouter norm).


DEFAULT_PROFILE = ModelProfile(
    mirror_ok=False, enable_monitor=True, max_iterations=8,
    notes="conservative default (mirror off, monitor on) — the live-proven-safe floor",
)


# =============================================================================
# Part 2: THE REGISTRY
# =============================================================================

def _coerce_profile(overrides: Dict[str, Any]) -> ModelProfile:
    """Build a ModelProfile from DEFAULT + only the recognized override keys."""
    clean = {k: v for k, v in (overrides or {}).items() if k in _OVERRIDE_KEYS}
    return replace(DEFAULT_PROFILE, **clean)


class ProfileRegistry:
    """Resolves a model id to its conduct profile: exact -> family -> DEFAULT."""

    def __init__(
        self,
        profiles_path: Path = MODEL_PROFILES_PATH,
        profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        raw = profiles if profiles is not None else self._load(profiles_path)
        self._exact: Dict[str, ModelProfile] = {
            k: _coerce_profile(v) for k, v in (raw.get("exact") or {}).items()
        }
        # Longest substring wins (most specific family rule), so order by length desc.
        fam = raw.get("family") or {}
        self._family: Tuple[Tuple[str, ModelProfile], ...] = tuple(
            (sub, _coerce_profile(ov))
            for sub, ov in sorted(fam.items(), key=lambda kv: len(kv[0]), reverse=True)
        )

    @staticmethod
    def _load(path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}  # missing/malformed -> empty registry, DEFAULT for everything

    def get(self, model_id: str) -> Tuple[ModelProfile, str]:
        """(profile, source_label). source_label = the id, the family substring,
        or 'default' — so the host can prove which rule fired."""
        mid = (model_id or "").strip()
        if mid in self._exact:
            return self._exact[mid], mid
        low = mid.lower()
        for sub, profile in self._family:
            if sub.lower() in low:
                return profile, f"family:{sub}"
        return DEFAULT_PROFILE, "default"


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — injected profiles dict)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  model_profiles.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    SEED = {
        "exact": {
            "nvidia/nemotron-3-super-120b-a12b:free": {
                "mirror_ok": False, "max_iterations": 8,
                "notes": "buries output under MIRROR-lite (L322)",
                "context_length": 999999,  # MUST be ignored (override-only invariant)
            },
            "some/reasoner:free": {"mirror_ok": True, "reasoning_channel": True},
        },
        "family": {
            "nemotron": {"mirror_ok": False, "notes": "nemotron family: mirror off"},
            "nemotron-3-super": {"max_iterations": 10},  # longer substring, more specific
        },
    }
    reg = ProfileRegistry(profiles=SEED)

    # T1: exact id wins over family
    p, src = reg.get("nvidia/nemotron-3-super-120b-a12b:free")
    check("T1 exact id resolves", src == "nvidia/nemotron-3-super-120b-a12b:free")
    check("T1b exact profile fields", p.mirror_ok is False and p.max_iterations == 8)

    # T2: override-only invariant — bogus catalog field never reaches the profile
    check("T2 catalog field ignored (override-only)",
          not hasattr(p, "context_length") and p.max_iterations == 8)

    # T3: family substring match when no exact id
    p3, src3 = reg.get("nvidia/nemotron-4-mini:free")
    check("T3 family match", src3.startswith("family:") and p3.mirror_ok is False, src3)

    # T4: longest substring wins (most specific family rule)
    p4, src4 = reg.get("nvidia/nemotron-3-super-999b:free")
    check("T4 longest family substring wins",
          src4 == "family:nemotron-3-super" and p4.max_iterations == 10, src4)

    # T5: unknown model -> DEFAULT, safe floor
    p5, src5 = reg.get("acme/totally-unknown-model")
    check("T5 unknown -> default", src5 == "default"
          and p5.mirror_ok is False and p5.enable_monitor is True)

    # T6: empty / None id -> default, no crash
    check("T6 empty id -> default", reg.get("")[1] == "default" and reg.get(None)[1] == "default")

    # T7: exact profile that enables mirror is honored (data, not hardcode)
    p7, _ = reg.get("some/reasoner:free")
    check("T7 mirror_ok=True honored from data", p7.mirror_ok is True and p7.reasoning_channel is True)

    # T8: DEFAULT_PROFILE is the safe floor
    check("T8 DEFAULT is safe floor",
          DEFAULT_PROFILE.mirror_ok is False and DEFAULT_PROFILE.enable_monitor is True)

    # T9: profile is frozen (immutable conduct)
    try:
        p.mirror_ok = True  # type: ignore[misc]
        check("T9 profile frozen", False)
    except Exception:
        check("T9 profile frozen", True)

    # T10-T12: file loading paths
    with tempfile.TemporaryDirectory() as td:
        good = Path(td) / "profiles.json"
        good.write_text(json.dumps(SEED), encoding="utf-8")
        rg = ProfileRegistry(profiles_path=good)
        check("T10 loads from file", rg.get("nvidia/nemotron-3-super-120b-a12b:free")[1]
              == "nvidia/nemotron-3-super-120b-a12b:free")

        bad = Path(td) / "bad.json"
        bad.write_text("}{ not json", encoding="utf-8")
        rb = ProfileRegistry(profiles_path=bad)
        check("T11 malformed file -> empty registry, DEFAULT", rb.get("anything")[1] == "default")

        missing = ProfileRegistry(profiles_path=Path(td) / "nope.json")
        check("T12 missing file -> DEFAULT", missing.get("x")[1] == "default")

    # T13: real seed file resolves nemotron to mirror-off (the shipped data)
    real = ProfileRegistry()
    pr, srcr = real.get("nvidia/nemotron-3-super-120b-a12b:free")
    check("T13 shipped seed: nemotron resolves mirror-off (not default)",
          pr.mirror_ok is False and srcr != "default",
          f"{srcr} mirror_ok={pr.mirror_ok}")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} model_profiles smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
