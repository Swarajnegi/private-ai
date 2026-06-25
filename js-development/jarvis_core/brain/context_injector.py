"""
context_injector.py — Boot Inhale (Stage 4.0.1: the Temporal + Identity pillars).

LAYER: Brain (Cognitive Control Loop — the lungs)

Import with:
    from jarvis_core.brain.context_injector import ContextInjector, default_providers

=============================================================================
THE BIG PICTURE
=============================================================================

The consciousness is portable in the repo (KB, cognitive_profile.md,
activity_digest); the runtime entry point lacked the lungs to inhale it
(KB L324, live repro: the Mind could not answer "what have we built?").
Claude Code sessions get this state injected by hooks; the runtime Mind got
nothing — same mind, different limb, no breath.

This organ is the inhale: a small set of PROVIDERS (plain callables returning
text or None) composed into ONE bounded prompt block that boot.py appends to
JARVIS_PSYCHE_PROMPT. Providers are injected — a test passes a fake clock and
temp paths; a future host passes its own self-state — so the organ is
host-independent by construction (System_Protocol: core organ + thin adapter).

Bounded by design: per-provider char caps + a total cap. A boot inhale that
blows a free-tier model's context window would be a self-inflicted lobotomy;
a provider that crashes must cost one note line, never the boot.

=============================================================================
THE FLOW
=============================================================================

STEP 1: default_providers() builds the standard set: temporal (injected clock),
        self-state (passed line), roadmap (next pending task), profile
        (cognitive_profile.md head), activity (ActivityRecaller digest).
        |
STEP 2: ContextInjector.inhale(): run each provider in order; skip empty,
        truncate to its cap, note (never raise) on failure.
        |
STEP 3: stop appending when the total cap is reached; return InhaleResult
        (block + which providers fired/skipped) for the BootReport.

=============================================================================
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import (
    DATA_ROOT, JARVIS_ROOT, KB_PATH, AGENT_RULES_DIR, AGENT_WORKFLOWS_DIR,
)

_IST = timezone(timedelta(hours=5, minutes=30))

# A provider yields one section of live state, or None/"" to skip itself.
Provider = Callable[[], Optional[str]]
Clock = Callable[[], datetime]

_DEFAULT_TOTAL_CAP = 6000
_TRUNCATION_MARK = " …(truncated)"

_DEFAULT_PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"


# =============================================================================
# Part 1: CONTRACTS (frozen)
# =============================================================================

@dataclass(frozen=True)
class ProviderSpec:
    """One named source of live state with its own size budget."""
    name: str
    provider: Provider
    max_chars: int = 1200


@dataclass(frozen=True)
class InhaleResult:
    """One breath: the composed block + which organs actually supplied air."""
    block: str
    fired: Tuple[str, ...]
    skipped: Tuple[str, ...]


# =============================================================================
# Part 2: THE INJECTOR
# =============================================================================

class ContextInjector:
    """Composes provider output into one bounded boot-inhale prompt block."""

    HEADER = (
        "LIVE SYSTEM STATE (boot inhale — current, machine-derived; trust it "
        "over training-data priors):"
    )

    def __init__(self, providers: List[ProviderSpec],
                 total_cap: int = _DEFAULT_TOTAL_CAP) -> None:
        self._providers = list(providers)
        self._total_cap = max(0, int(total_cap))

    def inhale(self) -> InhaleResult:
        sections: List[str] = []
        fired: List[str] = []
        skipped: List[str] = []
        used = len(self.HEADER)
        for spec in self._providers:
            try:
                value = spec.provider()
            except Exception as e:
                sections.append(f"## {spec.name}\n(unavailable: {type(e).__name__})")
                skipped.append(spec.name)
                continue
            text = (value or "").strip()
            if not text:
                skipped.append(spec.name)
                continue
            if len(text) > spec.max_chars:
                text = text[: spec.max_chars] + _TRUNCATION_MARK
            section = f"## {spec.name}\n{text}"
            if used + len(section) > self._total_cap:
                skipped.append(spec.name)
                continue
            sections.append(section)
            used += len(section)
            fired.append(spec.name)
        if not fired:
            # Notes alone are not a breath — boot proceeds bare rather than
            # carrying a block that says only "everything was unavailable".
            return InhaleResult(block="", fired=(), skipped=tuple(skipped))
        block = self.HEADER + "\n\n" + "\n\n".join(sections)
        return InhaleResult(block=block, fired=tuple(fired), skipped=tuple(skipped))


# =============================================================================
# Part 3: THE STANDARD PROVIDER SET
# =============================================================================

def _machine_name() -> str:
    return os.environ.get(
        "JARVIS_MACHINE", os.uname().nodename if hasattr(os, "uname") else "unknown")


# A one-line role hint for the canonical rule files; every other .md is listed by
# name only (the Mind reads it to learn, the hint just speeds the obvious two).
_RULE_HINTS = {
    "JARVIS_ENDGAME.md": "the architecture blueprint",
    "CLAUDE.md": "operating context / current build state",
    "js-workspace-rule.md": "workspace protocol",
}


def repo_anatomy(
    rules_dir: Path = AGENT_RULES_DIR,
    workflows_dir: Path = AGENT_WORKFLOWS_DIR,
    kb_path: Path = KB_PATH,
    root: Path = JARVIS_ROOT,
) -> Optional[str]:
    """A DYNAMIC self-map of where JARVIS's own docs live (never stale — lists the
    real dirs at inhale time). Closes the orientation gap: the Mind knows its rules
    are .md under .agent/, so it searches there instead of guessing a filename."""
    lines: List[str] = []

    def _list_md(d: Path) -> List[str]:
        try:
            return sorted(p.name for p in d.glob("*.md"))
        except Exception:
            return []

    rules = _list_md(rules_dir)
    if rules:
        named = ", ".join(
            f"{n} ({_RULE_HINTS[n]})" if n in _RULE_HINTS else n for n in rules)
        lines.append(f"- Your rules + blueprint: .agent/rules/ -> {named}")
    workflows = _list_md(workflows_dir)
    if workflows:
        lines.append(f"- Your workflow protocols (slash-commands): .agent/workflows/ -> "
                     f"{', '.join(workflows)}")
    try:
        if Path(kb_path).exists():
            lines.append(f"- Your long-term knowledge: {Path(kb_path).relative_to(root)}")
    except Exception:
        pass
    lines.append("- Your production code: js-development/jarvis_core/")
    if not rules and not workflows:
        return None  # nothing to map — skip the section
    return ("YOUR ANATOMY (where your own docs live — to answer questions about "
            "yourself/the system, file_search these and read the .md files; never "
            "guess a filename):\n" + "\n".join(lines))


def default_providers(
    clock: Optional[Clock] = None,
    self_state: Optional[str] = None,
    profile_path: Optional[Path] = None,
    queue_path: Optional[Path] = None,
    roadmap_paths: Optional[List[Path]] = None,
    activity_days: int = 7,
) -> List[ProviderSpec]:
    """The standard inhale: temporal, self-state, next task, profile, activity.

    Every source is injectable; every default points at the real artifacts.
    Heavy reads happen inside the provider closures, at inhale time, never here.
    """
    now = clock or (lambda: datetime.now(_IST))
    profile = Path(profile_path) if profile_path else _DEFAULT_PROFILE_PATH

    def temporal() -> str:
        t = now()
        return (f"Current date/time: {t.isoformat(timespec='seconds')} (IST). "
                f"Today is {t.strftime('%A')}.")

    def runtime_self_state() -> str:
        return self_state or f"Machine: {_machine_name()}."

    def next_task() -> Optional[str]:
        from jarvis_core.brain.roadmap_state import next_pending, default_roadmap_paths
        task = next_pending(roadmap_paths or default_roadmap_paths())
        if task is None:
            return None
        return (f"Next pending roadmap task: {task.label} "
                f"[{Path(task.file).name}:{task.line_no}]")

    def profile_head() -> Optional[str]:
        if not profile.exists():
            return None
        return profile.read_text(encoding="utf-8", errors="replace").strip()

    def recent_activity() -> Optional[str]:
        from jarvis_core.agent.recall import ActivityRecaller
        recaller = (ActivityRecaller(queue_path=queue_path) if queue_path
                    else ActivityRecaller())
        text = recaller.digest(days=activity_days, now=now())
        return None if "no captured turns" in text else text

    return [
        ProviderSpec("Temporal", temporal, max_chars=200),
        ProviderSpec("Runtime self-state", runtime_self_state, max_chars=300),
        ProviderSpec("Next pending task", next_task, max_chars=300),
        ProviderSpec("Repo self-map (your own anatomy)", repo_anatomy, max_chars=800),
        ProviderSpec("Cognitive profile (standing model of your owner)",
                     profile_head, max_chars=2500),
        ProviderSpec("Recent cross-chat activity", recent_activity, max_chars=2400),
    ]


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS (offline — fake clock, temp paths)
# =============================================================================

def _run_self_test() -> None:
    import json
    import tempfile

    print("=" * 70)
    print("  context_injector.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    FIXED = datetime(2026, 6, 12, 12, 0, tzinfo=_IST)

    # T1-T3: basic composition, ordering, header
    inj = ContextInjector([
        ProviderSpec("A", lambda: "alpha state"),
        ProviderSpec("B", lambda: "beta state"),
    ])
    r = inj.inhale()
    check("T1 both providers fire", r.fired == ("A", "B"), str(r.fired))
    check("T2 sections titled and ordered",
          r.block.index("## A\nalpha state") < r.block.index("## B\nbeta state"))
    check("T3 header present", r.block.startswith(ContextInjector.HEADER))

    # T4: empty/None providers are skipped, not rendered
    r4 = ContextInjector([
        ProviderSpec("E1", lambda: None), ProviderSpec("E2", lambda: "  "),
        ProviderSpec("OK", lambda: "x"),
    ]).inhale()
    check("T4 empty providers skipped", r4.fired == ("OK",)
          and set(r4.skipped) == {"E1", "E2"}, str(r4))

    # T5: a raising provider costs a note line, never the boot
    def boom() -> str:
        raise OSError("disk gone")
    r5 = ContextInjector([ProviderSpec("Bad", boom),
                          ProviderSpec("Good", lambda: "fine")]).inhale()
    check("T5 provider failure noted, inhale survives",
          "(unavailable: OSError)" in r5.block and "Good" in r5.fired
          and "Bad" in r5.skipped, r5.block)

    # T6: per-provider cap enforced with marker
    r6 = ContextInjector([ProviderSpec("Big", lambda: "z" * 500, max_chars=100)]).inhale()
    check("T6 per-provider cap", "z" * 100 + _TRUNCATION_MARK in r6.block
          and "z" * 101 not in r6.block)

    # T7: total cap stops later sections (earlier ones intact)
    r7 = ContextInjector(
        [ProviderSpec("S1", lambda: "a" * 300, max_chars=400),
         ProviderSpec("S2", lambda: "b" * 300, max_chars=400)],
        total_cap=420,
    ).inhale()
    check("T7 total cap drops the overflow section",
          r7.fired == ("S1",) and "S2" in r7.skipped, str(r7.fired))

    # T8: nothing fired -> empty block (boot proceeds bare)
    r8 = ContextInjector([ProviderSpec("N", lambda: None)]).inhale()
    check("T8 no air -> empty block", r8.block == "" and r8.fired == ())

    # T9-T13: the standard provider set against temp artifacts
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        profile = tdp / "cognitive_profile.md"
        profile.write_text("# Profile\nPROFILE-MARKER-XYZ likes depth.", encoding="utf-8")
        queue = tdp / "queue.jsonl"
        queue.write_text(json.dumps({
            "ts": FIXED.isoformat(), "session_id": "s1", "machine": "test-box",
            "model": "test-brain", "cwd": td, "chat_label": "t",
            "user_text": "build the stage four context injector organ today",
            "assistant_summary": "built it",
            "heuristic_signals": {"prompt_len": 40, "has_correction_markers": False,
                                  "domain_guess": "jarvis-build"},
        }) + "\n", encoding="utf-8")
        roadmap = tdp / "ROADMAP.md"
        roadmap.write_text("# R\n- [x] done thing\n- [ ] pending thing\n", encoding="utf-8")

        specs = default_providers(
            clock=lambda: FIXED, self_state="Runtime brain: test-brain | machine: test-box",
            profile_path=profile, queue_path=queue, roadmap_paths=[roadmap],
        )
        rr = ContextInjector(specs).inhale()
        check("T9 temporal uses the injected clock",
              "2026-06-12T12:00:00" in rr.block and "Friday" in rr.block)
        check("T10 self-state line present", "Runtime brain: test-brain" in rr.block)
        check("T11 profile content inhaled", "PROFILE-MARKER-XYZ" in rr.block)
        check("T12 roadmap next-pending surfaced", "pending thing" in rr.block)
        check("T13 activity digest inhaled (from temp queue)",
              "context injector organ" in rr.block, rr.block[-300:])

        # T14: missing profile -> section skipped silently
        specs14 = default_providers(clock=lambda: FIXED, profile_path=tdp / "nope.md",
                                    queue_path=queue, roadmap_paths=[roadmap])
        r14 = ContextInjector(specs14).inhale()
        check("T14 missing profile skipped",
              "Cognitive profile" not in r14.block and "Temporal" in r14.fired)

        # T15: empty queue -> activity provider skips (no 'no captured turns' noise)
        empty_q = tdp / "empty.jsonl"
        empty_q.write_text("", encoding="utf-8")
        specs15 = default_providers(clock=lambda: FIXED, profile_path=profile,
                                    queue_path=empty_q, roadmap_paths=[roadmap])
        r15 = ContextInjector(specs15).inhale()
        check("T15 empty queue -> activity section absent",
              "Recent cross-chat activity" in r15.skipped)

        # T16: repo_anatomy lists real .md dirs (the orientation fix) — dynamic,
        # role-hints the canonical files, fails-soft when dirs are absent.
        rules_d = tdp / "rules"; rules_d.mkdir()
        (rules_d / "JARVIS_ENDGAME.md").write_text("x", encoding="utf-8")
        (rules_d / "CLAUDE.md").write_text("y", encoding="utf-8")
        wf_d = tdp / "workflows"; wf_d.mkdir()
        (wf_d / "learn.md").write_text("z", encoding="utf-8")
        anat = repo_anatomy(rules_dir=rules_d, workflows_dir=wf_d,
                            kb_path=tdp / "kb.jsonl", root=tdp)
        check("T16 anatomy lists rules + workflows with canonical hint",
              anat and "JARVIS_ENDGAME.md (the architecture blueprint)" in anat
              and "learn.md" in anat and ".agent/workflows/" in anat, str(anat))
        check("T16b anatomy steers to file_search the .md (no guessing)",
              "file_search" in anat and "never guess" in anat, str(anat)[:120])
        # T16c: absent dirs -> None (section skipped, no crash)
        check("T16c missing .agent dirs -> None",
              repo_anatomy(rules_dir=tdp / "nope", workflows_dir=tdp / "nada",
                           kb_path=tdp / "kb.jsonl", root=tdp) is None)

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}")
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} context_injector smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
