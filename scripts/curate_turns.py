#!/usr/bin/env python3
"""
curate_turns.py — drive the curator over the capture stream.

LAYER: Tools (capture stream adapter)

    python3 scripts/curate_turns.py --status              # how much is uncurated
    python3 scripts/curate_turns.py --backlog 50          # curate the oldest N
    python3 scripts/curate_turns.py --review              # agent vs classifier
    python3 scripts/curate_turns.py --routing             # what routing results
    python3 scripts/curate_turns.py --self-test           # offline, no network

=============================================================================
THE BIG PICTURE
=============================================================================

`jarvis_core/agent/curator.py` holds the judgement and is host-independent.
This is the adapter that feeds it: it finds turns nobody has curated, gives
each one its session neighbours, calls a model, and APPENDS the verdict to
`jarvis_data/turn_curation.jsonl`.

It is the same split that made capture portable — organ in `jarvis_core/`,
thin driver in `scripts/` — so Codex, Antigravity and JARVIS reuse the organ
without reusing this file's OpenRouter assumption.

=============================================================================
WHY A SEPARATE FILE AND NOT A COLUMN IN THE QUEUE
=============================================================================

`observation_queue.jsonl` is a FACT and is never rewritten (KB 548's taxonomy).
Curation is a JUDGEMENT about a fact, it arrives later, and it can be revised
by a reviewer. Writing it back into the queue would mean rewriting history to
record an opinion.

So verdicts live in their own append-only log, joined on (ts, session_id) —
the key every other projection over this queue already uses. Folding keeps the
newest verdict per turn and leaves every superseded one readable underneath,
which is what makes "any agent can review whether JARVIS routed this right"
a real operation rather than a promise.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Load the queue in timestamp order and group by session, so each turn
        can be handed its own preceding turns as context.
        |
STEP 2: Subtract what is already curated. Resumable by construction — this
        runs on a clock against a queue that grows, and a crash mid-batch must
        cost one turn, not the batch.
        |
STEP 3: Curate each remaining turn, attaching the embedding label from
        `domain_labels.jsonl` alongside the agent's verdict so the two can be
        compared later. Both are kept; neither overwrites the other.
        |
STEP 4: Append. Never rewrite. `--review` folds and reports disagreements.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.agent.curator import (  # noqa: E402
    CORPORA, DOMAINS, NOT_TRAINABLE, Curation, TurnContext, curate, fold_events,
)
from jarvis_core.config import DATA_ROOT  # noqa: E402

QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"
CURATION_PATH = Path(DATA_ROOT) / "turn_curation.jsonl"
LABELS_PATH = Path(DATA_ROOT) / "domain_labels.jsonl"

_IST = timezone(timedelta(hours=5, minutes=30))

# Curation is cheap per turn and there are ~1k of them, so the default model is
# chosen for cost rather than depth. Overridable: a turn the cheap model rates
# low-confidence is exactly what a reviewer should re-run with a better one.
_DEFAULT_MODEL = os.environ.get("JARVIS_CURATOR_MODEL", "google/gemini-3.6-flash")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except (OSError, FileNotFoundError):
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_contexts(queue_path: Path = QUEUE_PATH) -> List[TurnContext]:
    """Every turn, in timestamp order, carrying its own session's prior turns."""
    records = _read_jsonl(queue_path)
    records.sort(key=lambda r: str(r.get("ts", "")))
    seen: Dict[str, List[str]] = defaultdict(list)
    contexts: List[TurnContext] = []
    for rec in records:
        session = str(rec.get("session_id", ""))
        user_text = str(rec.get("user_text", ""))
        contexts.append(TurnContext(
            ts=str(rec.get("ts", "")),
            session_id=session,
            user_text=user_text,
            assistant_summary=str(rec.get("assistant_summary", "")),
            neighbours=tuple(seen[session]),
            chat_label=str(rec.get("chat_label", "")),
        ))
        seen[session].append(user_text)
    return contexts


def load_curations(path: Path = CURATION_PATH) -> Dict[Tuple[str, str], Dict[str, Any]]:
    return fold_events(_read_jsonl(path))


def load_embedding_labels(path: Path = LABELS_PATH) -> Dict[Tuple[str, str], Dict[str, Any]]:
    return {
        (str(r.get("ts", "")), str(r.get("session_id", ""))): r
        for r in _read_jsonl(path)
    }


def append_curation(curation: Curation, path: Path = CURATION_PATH) -> None:
    """Append one verdict, healing a torn final line first.

    Both halves are the standing rule for every `.jsonl` in this repo: a lock
    stops a concurrent writer and does NOTHING about a writer that was killed
    mid-line, whose partial record would otherwise swallow this one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(curation.to_record(), ensure_ascii=False)
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        handle.seek(0, os.SEEK_END)
        if handle.tell():
            handle.seek(handle.tell() - 1)
            if handle.read(1) != "\n":
                handle.write("\n")
        handle.write(line + "\n")


def _build_complete_fn(model: str):
    """An OpenRouter completion callable, or None when the key is absent."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        return None, "OPENROUTER_API_KEY is not set"
    try:
        import asyncio

        from jarvis_core.brain.llm_client import build_llm_call
        client = build_llm_call(model=model)

        def complete(prompt: str) -> str:
            return asyncio.run(client([{"role": "user", "content": prompt}]))

        return complete, ""
    except Exception as exc:                       # noqa: BLE001
        return None, f"could not build the model client: {exc}"


def run_backlog(limit: int, model: str, dry_run: bool = False) -> int:
    contexts = load_contexts()
    done = load_curations()
    labels = load_embedding_labels()
    pending = [c for c in contexts if (c.ts, c.session_id) not in done]

    print(f"  queue          : {len(contexts)} turns")
    print(f"  already curated: {len(done)}")
    print(f"  pending        : {len(pending)}")
    if not pending:
        print("  nothing to do.")
        return 0
    batch = pending[:limit]
    print(f"  this run       : {len(batch)} (model: {model})")
    if dry_run:
        print("\n  --dry-run: showing the first prompt only, nothing written\n")
        from jarvis_core.agent.curator import build_prompt
        print(build_prompt(batch[0])[:1800])
        return 0

    complete, why = _build_complete_fn(model)
    if complete is None:
        print(f"\n  CANNOT CURATE: {why}")
        print("  Turns stay uncurated, which is recoverable. A guessed verdict is not.")
        return 1

    ok = failed = 0
    for i, ctx in enumerate(batch, 1):
        label = labels.get((ctx.ts, ctx.session_id), {})
        verdict = curate(ctx, complete, curated_by=model,
                         curated_at=datetime.now(_IST).isoformat(timespec="seconds"))
        if verdict is None:
            failed += 1
            print(f"  [{i}/{len(batch)}] {ctx.ts[:16]}  UNPARSEABLE — left uncurated")
            continue
        verdict = Curation(**{**verdict.__dict__,
                              "embedding_label": str(label.get("label", "")),
                              "embedding_score": float(label.get("score") or 0.0)})
        append_curation(verdict)
        ok += 1
        flag = "  <-- disagrees" if verdict.disagrees_with_embedding else ""
        print(f"  [{i}/{len(batch)}] {ctx.ts[:16]}  {'+'.join(verdict.corpora):<26} "
              f"{verdict.domain:<17} conf={verdict.confidence:.2f}{flag}")
    print(f"\n  curated {ok}, unparseable {failed}")
    return 0 if ok else 1


def run_status() -> int:
    contexts = load_contexts()
    done = load_curations()
    labels = load_embedding_labels()
    pending = sum(1 for c in contexts if (c.ts, c.session_id) not in done)
    print("=" * 70)
    print("  TURN CURATION STATUS")
    print("=" * 70)
    print(f"  capture queue        : {len(contexts)} turns")
    print(f"  curated by an agent  : {len(done)}")
    print(f"  uncurated            : {pending}")
    print(f"  embedding labels     : {len(labels)} (context-free second opinion)")
    if done:
        print()
        corp = Counter()
        for rec in done.values():
            corp["+".join(rec.get("corpora", [])) or "?"] += 1
        print("  routing so far:")
        for k, v in corp.most_common():
            print(f"     {v:>5}  {k}")
        dom = Counter(rec.get("domain", "?") for rec in done.values())
        print("  domains:")
        for k, v in dom.most_common():
            print(f"     {v:>5}  {k}")
        trainable = sum(1 for r in done.values() if r.get("trainable"))
        print(f"  trainable            : {trainable} of {len(done)}")
    print("=" * 70)
    return 0


def run_review(min_confidence: float) -> int:
    """Everything a reviewing agent should look at, and why it is on the list."""
    done = load_curations()
    contexts = {(c.ts, c.session_id): c for c in load_contexts()}
    if not done:
        print("  nothing curated yet — run --backlog first")
        return 1

    disagree, lowconf = [], []
    for key, rec in done.items():
        emb = str(rec.get("embedding_label", ""))
        if emb and emb != "unknown" and emb != rec.get("domain"):
            disagree.append((key, rec))
        if float(rec.get("confidence") or 0.0) < min_confidence:
            lowconf.append((key, rec))

    print("=" * 70)
    print("  CURATION REVIEW")
    print("=" * 70)
    print(f"  curated turns                       : {len(done)}")
    print(f"  agent disagrees with the classifier : {len(disagree)}")
    print(f"  agent confidence below {min_confidence:.2f}          : {len(lowconf)}")
    print()
    print("  Both lists are for a REVIEWING AGENT, not for a human to grind through.")
    print("  To overturn one, append a corrected verdict — the original stays readable:")
    print("     python3 scripts/curate_turns.py --backlog 1   (after deleting nothing)")
    print()
    for title, rows in (("DISAGREEMENTS", disagree), ("LOW CONFIDENCE", lowconf)):
        if not rows:
            continue
        print(f"  --- {title} ---")
        for key, rec in rows[:12]:
            ctx = contexts.get(key)
            print(f"   {key[0][:16]}  agent={rec.get('domain')} "
                  f"emb={rec.get('embedding_label')}({rec.get('embedding_score', 0):.2f}) "
                  f"conf={rec.get('confidence', 0):.2f}")
            print(f"      corpora   : {'+'.join(rec.get('corpora', []))}")
            print(f"      responds  : {str(rec.get('responds_to', ''))[:100]}")
            if ctx:
                print(f"      turn      : {ctx.user_text[:100]!r}")
        print()
    print("=" * 70)
    return 0


def run_routing() -> int:
    """What the curation actually routes, versus what happens without it."""
    done = load_curations()
    if not done:
        print("  nothing curated yet — run --backlog first")
        return 1
    eng = sum(1 for r in done.values() if "engineer" in r.get("corpora", []))
    per = sum(1 for r in done.values() if "personalization" in r.get("corpora", []))
    non = sum(1 for r in done.values() if NOT_TRAINABLE in r.get("corpora", []))
    both = sum(1 for r in done.values()
               if {"engineer", "personalization"} <= set(r.get("corpora", [])))
    print("=" * 70)
    print("  ROUTING (curated turns only)")
    print("=" * 70)
    print(f"  -> engineer only      : {eng - both}")
    print(f"  -> personalization    : {per - both}")
    print(f"  -> BOTH               : {both}")
    print(f"  -> neither (dropped)  : {non}")
    print()
    print(f"  Without curation every one of these {len(done)} turns went to BOTH")
    print(f"  corpora. Curation sends {both} there deliberately and drops {non}.")
    print("=" * 70)
    return 0


def _self_test() -> int:
    """Offline. Exercises the adapter's own logic with an injected model."""
    import tempfile
    passed, failed = [], []

    def check(name, got, want):
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    with tempfile.TemporaryDirectory() as tmp:
        qpath = Path(tmp) / "observation_queue.jsonl"
        cpath = Path(tmp) / "turn_curation.jsonl"
        rows = [
            {"ts": "2026-09-14T09:00:00+05:30", "session_id": "A", "user_text": "first A",
             "assistant_summary": "ra"},
            {"ts": "2026-09-14T09:01:00+05:30", "session_id": "B", "user_text": "first B",
             "assistant_summary": "rb"},
            {"ts": "2026-09-14T09:02:00+05:30", "session_id": "A", "user_text": "second A",
             "assistant_summary": "ra2"},
        ]
        qpath.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        ctxs = load_contexts(qpath)
        check("T1 every turn loaded", len(ctxs), 3)
        check("T2 turns are timestamp ordered",
              [c.user_text for c in ctxs], ["first A", "first B", "second A"])
        check("T3 neighbours are SESSION-scoped, not global",
              ctxs[2].neighbours, ("first A",))
        check("T4 a session's first turn has no neighbours", ctxs[0].neighbours, ())
        check("T5 another session's turn does not leak in", ctxs[1].neighbours, ())

        good = ('{"corpora":["engineer"],"domain":"jarvis-build","responds_to":"x",'
                '"trainable":true,"confidence":0.9,"rationale":"y"}')
        v = curate(ctxs[0], lambda _p: good, curated_by="test")
        append_curation(v, cpath)
        folded = load_curations(cpath)
        check("T6 verdict round-trips through the log", len(folded), 1)
        check("T7 ...with its corpora intact",
              folded[("2026-09-14T09:00:00+05:30", "A")]["corpora"], ["engineer"])

        revised = Curation(**{**v.__dict__, "domain": "ai-ml", "curated_by": "reviewer"})
        append_curation(revised, cpath)
        folded = load_curations(cpath)
        check("T8 a review supersedes without deleting", len(folded), 1)
        check("T9 the newest verdict wins",
              folded[("2026-09-14T09:00:00+05:30", "A")]["domain"], "ai-ml")
        check("T10 both verdicts remain in the log",
              len(_read_jsonl(cpath)), 2)

        # A torn final line is the failure `append_observation` was fixed for.
        with open(cpath, "a", encoding="utf-8") as fh:
            fh.write('{"ts": "torn", "session')
        append_curation(v, cpath)
        lines = [l for l in cpath.read_text(encoding="utf-8").splitlines() if l.strip()]
        check("T11 a torn line does not swallow the next append",
              json.loads(lines[-1])["ts"], "2026-09-14T09:00:00+05:30")

        check("T12 pending excludes what is curated",
              len([c for c in load_contexts(qpath)
                   if (c.ts, c.session_id) not in load_curations(cpath)]), 2)

    print("=" * 70)
    print("  curate_turns adapter self-test")
    print("=" * 70)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 70)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Curate captured turns with the agent in the loop.")
    p.add_argument("--backlog", type=int, metavar="N", help="curate the oldest N uncurated turns")
    p.add_argument("--status", action="store_true", help="how much is curated")
    p.add_argument("--review", action="store_true", help="disagreements and low confidence")
    p.add_argument("--routing", action="store_true", help="what the curation routes")
    p.add_argument("--model", default=_DEFAULT_MODEL, help="model to curate with")
    p.add_argument("--min-confidence", type=float, default=0.5)
    p.add_argument("--dry-run", action="store_true", help="show the prompt, write nothing")
    p.add_argument("--self-test", action="store_true", help="offline adapter tests")
    args = p.parse_args()

    if args.self_test:
        return _self_test()
    if args.status:
        return run_status()
    if args.review:
        return run_review(args.min_confidence)
    if args.routing:
        return run_routing()
    if args.backlog is not None:
        return run_backlog(args.backlog, args.model, dry_run=args.dry_run)
    return run_status()


if __name__ == "__main__":
    raise SystemExit(main())
