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
text or None) composed into ONE prompt block that boot.py appends to
JARVIS_PSYCHE_PROMPT. Providers are injected — a test passes a fake clock and
temp paths; a future host passes its own self-state — so the organ is
host-independent by construction (System_Protocol: core organ + thin adapter).

Nothing is cut (owner directive 2026-09-28: no truncation anywhere). Every
provider's text ships whole and no section is ever dropped for size — the old
per-provider caps and 6,000-char total cut the profile to its first 2,500
chars, so the model never saw most of who its owner is. Context-window
overflow is handled by paging elsewhere, not by silently discarding state
here. A provider that crashes still costs one note line, never the boot.

=============================================================================
THE FLOW
=============================================================================

STEP 1: default_providers() builds the standard set: temporal (injected clock),
        self-state (passed line), roadmap (next pending task), profile
        (cognitive_profile.md head), activity (ActivityRecaller digest).
        |
STEP 2: ContextInjector.inhale(): run each provider in order; skip empty,
        redact outbound identifiers, note (never raise) on failure.
        |
STEP 3: return InhaleResult (block + which providers fired/skipped) for the
        BootReport.

=============================================================================
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import (
    DATA_ROOT, JARVIS_ROOT, KB_PATH, AGENT_RULES_DIR, AGENT_WORKFLOWS_DIR,
)
from jarvis_core.brain.outbound_policy import OutboundPolicy, redact_outbound

_IST = timezone(timedelta(hours=5, minutes=30))

# A provider yields one section of live state, or None/"" to skip itself.
Provider = Callable[[], Optional[str]]
Clock = Callable[[], datetime]

_DEFAULT_PROFILE_PATH = Path(DATA_ROOT) / "cognitive_profile.md"
_DEFAULT_PERSONAL_LIFE_PATH = Path(DATA_ROOT) / "personal_life.md"

# pipeline_health builds both inhales to check nothing in them is cut, and the
# inhale includes pipeline health: without this, each would compute the other
# forever. Set only while pipeline_health is building an inhale.
_PIPELINE_HEALTH_SUPPRESSED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "pipeline_health_suppressed", default=False)
_PIPELINE_HEALTH_TTL_S = 60.0


@contextlib.contextmanager
def pipeline_health_suppressed() -> Iterator[None]:
    """Silence the Pipeline health provider for the duration (recursion guard)."""
    token = _PIPELINE_HEALTH_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _PIPELINE_HEALTH_SUPPRESSED.reset(token)


def pipeline_health_line() -> Optional[str]:
    """Every breach, one per line, or None when the pipeline is healthy.

    Quiet-when-healthy like projections.stale_line: a working pipeline costs
    zero prompt tokens, and a broken one is something JARVIS says out loud.
    """
    if _PIPELINE_HEALTH_SUPPRESSED.get():
        return None
    scripts = str(Path(JARVIS_ROOT) / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import pipeline_health  # scripts/pipeline_health.py — the one implementation
    report = pipeline_health.cached_report(max_age_s=_PIPELINE_HEALTH_TTL_S)
    lines = pipeline_health.brief_lines(report)
    if not lines:
        return None
    return (f"PIPELINE BREACHED — {len(lines)} problem(s) in your own memory and "
            f"training pipeline. Tell your owner plainly the next time they speak "
            f"to you; do not wait to be asked. Full detail: python "
            f"scripts/pipeline_health.py\n" + "\n".join(lines))


# =============================================================================
# Part 1: CONTRACTS (frozen)
# =============================================================================

@dataclass(frozen=True)
class ProviderSpec:
    """One named source of live state."""
    name: str
    provider: Provider


@dataclass(frozen=True)
class InhaleResult:
    """One breath: the composed block + which organs actually supplied air."""
    block: str
    fired: Tuple[str, ...]
    skipped: Tuple[str, ...]
    redacted: Tuple[str, ...] = ()


# =============================================================================
# Part 2: THE INJECTOR
# =============================================================================

class ContextInjector:
    """Composes provider output into one boot-inhale prompt block."""

    HEADER = (
        "LIVE SYSTEM STATE (boot inhale — current, machine-derived; trust it "
        "over training-data priors):"
    )

    def __init__(self, providers: List[ProviderSpec],
                 policy: Optional[OutboundPolicy] = None) -> None:
        self._providers = list(providers)
        self._policy = policy or OutboundPolicy()

    def inhale(self) -> InhaleResult:
        sections: List[str] = []
        fired: List[str] = []
        skipped: List[str] = []
        redacted: List[str] = []
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
            # THE AIRLOCK. Every provider passes through here, including any
            # added later — that is the point of doing it in the loop rather
            # than inside individual providers.
            verdict = redact_outbound(text, policy=self._policy)
            redacted.extend(verdict.removed)
            sections.append(f"## {spec.name}\n{verdict.text}")
            fired.append(spec.name)
        if not fired:
            # Notes alone are not a breath — boot proceeds bare rather than
            # carrying a block that says only "everything was unavailable".
            return InhaleResult(block="", fired=(), skipped=tuple(skipped),
                                redacted=tuple(sorted(set(redacted))))
        block = self.HEADER + "\n\n" + "\n\n".join(sections)
        return InhaleResult(block=block, fired=tuple(fired),
                            skipped=tuple(skipped),
                            redacted=tuple(sorted(set(redacted))))


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
    # Portable across ANY host (not just the IDE that happens to auto-load
    # .agent/rules/CLAUDE.md) -- the roadmap docs are plain project files, read
    # identically regardless of which coding tool, if any, is running JARVIS.
    from jarvis_core.brain.roadmap_state import default_roadmap_paths
    roadmaps = [p for p in default_roadmap_paths(root=root) if p.exists()]
    if roadmaps:
        names = ", ".join(str(p.relative_to(root)) for p in roadmaps)
        lines.append(f"- Your own build-status roadmap (canonical, portable): {names}")
    try:
        if Path(kb_path).exists():
            lines.append(f"- Your long-term knowledge: {Path(kb_path).relative_to(root)}")
    except Exception:
        pass
    lines.append("- Your production code: js-development/jarvis_core/")
    if not rules and not workflows and not roadmaps:
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
    collections: Optional[List[str]] = None,
    personal_life_path: Optional[Path] = None,
) -> List[ProviderSpec]:
    """The standard inhale: tool guidance, temporal, self-state, next task,
    profile, activity.

    Every source is injectable; every default points at the real artifacts.
    Heavy reads happen inside the provider closures, at inhale time, never here.
    """
    now = clock or (lambda: datetime.now(_IST))
    profile_file = Path(profile_path) if profile_path else _DEFAULT_PROFILE_PATH

    def tool_guidance() -> str:
        # The L324 lesson: wiring the autobiography tool is not enough; the
        # Mind must know WHICH organ holds its history, or it reaches for
        # document search and finds nothing (observed live, Gate A 2026-06-12).
        text = (
            "Tool guidance: prior_self_consult is your AUTOBIOGRAPHY — the "
            "project's own knowledge base (what was built, decisions, failures, "
            "history). list_dir inspects repository folder hierarchy and code directories. "
            "file_read inspects actual source code (.py) and specs (.md). corpus_stats "
            "inspects observation queues and fine-tuning datasets. For code/project architecture "
            "questions, always inspect real source files directly."
        )
        if collections:
            text += (
                f" memory_semantic_search searches document collections "
                f"{collections} — pass one of these collection names explicitly; "
                f"it holds documents, NOT the project history."
            )
        return text

    def temporal() -> str:
        t = now()
        return (f"Current date/time: {t.isoformat(timespec='seconds')} (IST). "
                f"Today is {t.strftime('%A')}.")

    def runtime_self_state() -> str:
        return self_state or f"Machine: {_machine_name()}."

    def projection_state() -> Optional[str]:
        # Announces a stale index rather than waiting to be audited. The
        # 544-vs-533 drift was found by accident, and accident is not a
        # detection strategy — same reasoning as the usage provider below.
        # Returns None when everything matches, so a healthy system stays
        # silent and only a real problem costs prompt space.
        from jarvis_core.brain.projections import stale_line
        return stale_line()

    def pipeline_state() -> Optional[str]:
        return pipeline_health_line()

    def usage_state() -> str:
        # The one provider that can report badly on the project. It exists
        # because conversations/ was the only usage log in the repo and had no
        # consumer — see brain/usage.py's header for the audit that found it.
        from jarvis_core.brain.usage import usage_line
        return usage_line()

    def next_task() -> Optional[str]:
        from jarvis_core.brain.roadmap_state import next_pending, default_roadmap_paths
        task = next_pending(roadmap_paths or default_roadmap_paths())
        if task is None:
            return None
        return (f"Next pending roadmap task: {task.label} "
                f"[{Path(task.file).name}:{task.line_no}]")

    def profile_text() -> Optional[str]:
        if not profile_file.exists():
            return None
        return profile_file.read_text(encoding="utf-8", errors="replace").strip()

    def personal_life() -> Optional[str]:
        # The owner chose on 2026-09-28 to let JARVIS see the people in their
        # life when answering (it could not say who their girlfriend was).
        # Context only: training artifacts still redact these names. The file
        # opens with a blockquote about its own storage policy; the people and
        # circumstances start at the first heading.
        f = Path(personal_life_path) if personal_life_path else _DEFAULT_PERSONAL_LIFE_PATH
        if not f.exists():
            return None
        text = f.read_text(encoding="utf-8", errors="replace")
        start = text.find("\n## ")
        return (text[start:] if start >= 0 else text).strip() or None

    def recent_activity() -> Optional[str]:
        from jarvis_core.agent.recall import ActivityRecaller
        recaller = (ActivityRecaller(queue_path=queue_path) if queue_path
                    else ActivityRecaller())
        text = recaller.digest(days=activity_days, now=now())
        return None if "no captured turns" in text else text

    return [
        ProviderSpec("Tool routing guidance", tool_guidance),
        ProviderSpec("Temporal", temporal),
        ProviderSpec("Runtime self-state", runtime_self_state),
        ProviderSpec("Projection integrity", projection_state),
        ProviderSpec("Pipeline health", pipeline_state),
        ProviderSpec("Usage reality (built vs actually used)", usage_state),
        ProviderSpec("Next pending task", next_task),
        ProviderSpec("Repo self-map (your own anatomy)", repo_anatomy),
        ProviderSpec("Cognitive profile (standing model of your owner)", profile_text),
        ProviderSpec("People and circumstances in your owner's life", personal_life),
        ProviderSpec("Recent cross-chat activity", recent_activity),
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

    # T6: a large provider ships whole — no cut, no marker
    r6 = ContextInjector([ProviderSpec("Big", lambda: "z" * 50_000)]).inhale()
    check("T6 a 50,000-char section ships whole",
          "z" * 50_000 in r6.block and "truncated" not in r6.block)

    # T7: no section is ever dropped for size, however large the total
    r7 = ContextInjector(
        [ProviderSpec("S1", lambda: "a" * 30_000),
         ProviderSpec("S2", lambda: "b" * 30_000),
         ProviderSpec("S3", lambda: "c" * 30_000)],
    ).inhale()
    check("T7 every section fires regardless of total size",
          r7.fired == ("S1", "S2", "S3") and not r7.skipped
          and all(ch * 30_000 in r7.block for ch in "abc"), str(r7.fired))

    # T8: nothing fired -> empty block (boot proceeds bare)
    r8 = ContextInjector([ProviderSpec("N", lambda: None)]).inhale()
    check("T8 no air -> empty block", r8.block == "" and r8.fired == ())

    # T9-T13: the standard provider set against temp artifacts
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        profile = tdp / "cognitive_profile.md"
        long_profile = "# Profile\nPROFILE-MARKER-XYZ likes depth. " + "trait " * 2000 + "PROFILE-TAIL-END"
        profile.write_text(long_profile, encoding="utf-8")
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
        check("T11b a 12,000-char profile is inhaled whole, to its last word",
              long_profile.strip() in rr.block)
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

        # T17: the people in the owner's life reach the inhale, named, without
        # the file's storage-policy blockquote (context-only consent, 2026-09-28).
        life = tdp / "personal_life.md"
        life.write_text("# Personal Life\n\n> storage policy note\n\n## Relationships\n"
                        "- Girlfriend: Alicia, called \"Ali\".\n", encoding="utf-8")
        spec = next(s for s in default_providers(personal_life_path=life, profile_path=tdp / "none.md")
                    if s.name.startswith("People and circumstances"))
        body = spec.provider()
        check("T17 personal life ships named, policy blockquote left out",
              bool(body) and "Alicia" in body and "Ali" in body and "storage policy" not in body, str(body))

    # T18-T20: the Pipeline health provider — silent when healthy, every
    # breach when not, and never recursing into itself.
    import types
    fake_reports = {"r": {"healthy": True, "breaches": []}}
    fake = types.ModuleType("pipeline_health")
    fake.cached_report = lambda max_age_s=60.0: fake_reports["r"]          # type: ignore[attr-defined]
    fake.brief_lines = lambda r: [f"[{b['check']}] {b['detail']}" for b in r["breaches"]]  # type: ignore[attr-defined]
    real_mod = sys.modules.get("pipeline_health")
    sys.modules["pipeline_health"] = fake
    try:
        check("T18 a healthy pipeline costs zero prompt tokens", pipeline_health_line() is None)
        fake_reports["r"] = {"healthy": False, "breaches": [
            {"check": "job:reindex_memory", "detail": "16 consecutive failures"},
            {"check": "backlog:codex", "detail": "1153 turns unparsed"}]}
        line = pipeline_health_line() or ""
        check("T19 every breach reaches the inhale, one per line",
              "PIPELINE BREACHED — 2 problem(s)" in line
              and "\n[job:reindex_memory] 16 consecutive failures" in line
              and "\n[backlog:codex] 1153 turns unparsed" in line, line)
        with pipeline_health_suppressed():
            check("T20 suppressed while pipeline_health builds an inhale (no recursion)",
                  pipeline_health_line() is None)
        check("T20b the standard set includes the Pipeline health provider",
              any(sp.name == "Pipeline health" for sp in default_providers()))
    finally:
        if real_mod is not None:
            sys.modules["pipeline_health"] = real_mod
        else:
            sys.modules.pop("pipeline_health", None)

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
