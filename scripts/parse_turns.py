#!/usr/bin/env python3
"""
parse_turns.py — the one tool every agent uses to parse the owner's turns.

LAYER: Memory (curation + knowledge — host adapter)

    python3 scripts/parse_turns.py --status                           # backlog per host
    python3 scripts/parse_turns.py --pending --host claude --limit 10 # a packet to parse
    python3 scripts/parse_turns.py --submit verdicts.json --agent claude/claude-opus-5-5
    python3 scripts/parse_turns.py --host jarvis --auto --limit 10    # JARVIS parses its own
    python3 scripts/parse_turns.py --routing | --review               # what the verdicts say
    python3 scripts/parse_turns.py --self-test                        # offline, temp files

=============================================================================
THE BIG PICTURE
=============================================================================

By the owner's decision (2026-09-28) the agent the owner was talking to
parses those turns: Claude parses Claude chats, Codex Codex, Antigravity
Antigravity, JARVIS its own. No background job makes a paid call; the Gemini
curator this replaces failed 185 of 195 runs on an empty balance and said
nothing.

Four agents parsing by four private notions of "important" would produce four
incompatible corpora, so there is ONE rule (agent/parse_rule.PARSE_RULE) and
ONE tool, this one. It hands an agent its pending turns, each WHOLE, with the
whole earlier session and the tension priors, and then validates what comes
back strictly before anything is written. A verdict that fails validation
writes nothing; the turn stays pending, which is recoverable. A guessed one
is not.

What an accepted verdict writes, and where:
  * the routing half -> turn_curation.jsonl (append-only, folded newest-wins,
    now carrying rule_version and host so parse_ledger can count it);
  * each fact -> the KB through kb_append.append_entry (exact + semantic
    dedup), which is how the owner's girlfriend finally reaches the profile;
  * a tension -> Consolidator.record_finding, the same KB + life_state_feed
    path the surfacing organ has always read.

Re-submitting the same verdicts changes nothing: facts dedup in kb_append,
tension dedups on the feed id, and a curation identical to the folded one on
corpora/domain/trainable/rule_version is not appended again.

=============================================================================
THE FLOW
=============================================================================

STEP 1: --pending picks the oldest pending turns for a host (parse_ledger),
        grouped by session, and builds a packet: PARSE_RULE + each turn in
        full + every earlier owner turn of its session + priors.
        |
STEP 2: the agent answers {"verdicts": [...]} (or --auto: JARVIS's own free
        model chain answers it, paged to fit the model's window).
        |
STEP 3: --submit finds each verdict's turn by (ts, session_id), recomputes the
        priors it was offered, and runs parse_rule.validate_verdict.
        |
STEP 4: accepted -> facts, tension, then curation are written; every rejection
        is printed with every reason.
=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from jarvis_core.agent.curator import (  # noqa: E402
    Curation, TurnContext, _CONTEXT_WINDOW_CHARS, _extract_json, _notes_over, fold_events)
from jarvis_core.agent.parse_ledger import (  # noqa: E402
    CURATION_PATH, HOSTS, QUEUE_PATH, _TEST_SESSION, backlog, host_of, pending)
from jarvis_core.agent.parse_rule import PARSE_RULE, PARSE_RULE_VERSION, Verdict, validate_verdict  # noqa: E402
from jarvis_core.config import DATA_ROOT, KB_PATH  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))
FEED_PATH = Path(DATA_ROOT) / "life_state_feed.jsonl"
LABELS_PATH = Path(DATA_ROOT) / "domain_labels.jsonl"

# Tension priors are retrieved only for turns that can carry a claim; the
# threshold is tension.py's own, so both paths agree on what a candidate is.
_MIN_PRIOR_CHARS = 40
# Turns per model call. Measured 2026-09-28 on the free chain: ten turns in
# one call came back as prose from nemotron and as ONE verdict from
# openrouter/free; three came back whole from both.
_AUTO_PAGE = int(os.environ.get("JARVIS_PARSE_PAGE", "3"))
# A verdict batch with facts is a few thousand tokens; a reasoning model spends
# more before it answers. The client continues a length-cut reply on its own,
# so this is a per-call ceiling, never a cut.
_AUTO_MAX_TOKENS = 16000


@dataclass(frozen=True)
class Paths:
    queue: Path = QUEUE_PATH
    curation: Path = CURATION_PATH
    kb: Path = Path(KB_PATH)
    feed: Path = FEED_PATH
    labels: Path = LABELS_PATH


PriorsFn = Callable[[str, str], List[Dict[str, Any]]]     # (ts, owner text) -> priors


# =============================================================================
# Part 1: reading
# =============================================================================

def _jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    try:
        handle = Path(path).open("r", encoding="utf-8")
    except (OSError, FileNotFoundError):
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def _kb_index(kb_path: Path) -> Dict[str, Dict[str, Any]]:
    return {str(e.get("id")): e for e in _jsonl(kb_path) if e.get("id") is not None}


def _sessions(queue_path: Path, session_ids: set) -> Dict[str, List[Dict[str, Any]]]:
    """Every row of the given sessions, in timestamp order, first copy of each ts."""
    rows: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for row in _jsonl(queue_path):
        sid = str(row.get("session_id") or "")
        if sid in session_ids:
            rows[sid].setdefault(str(row.get("ts") or ""), row)
    return {sid: [by_ts[t] for t in sorted(by_ts)] for sid, by_ts in rows.items()}


def _context_of(session_rows: Sequence[Dict[str, Any]], ts: str) -> List[Dict[str, str]]:
    return [{"ts": str(r.get("ts")), "user_text": str(r.get("user_text") or "")}
            for r in session_rows
            if str(r.get("ts")) < ts and str(r.get("user_text") or "").strip()]


def _select(host: str, limit: int, paths: Paths) -> List[Tuple[str, str]]:
    """The oldest pending keys for `host`, whole sessions at a time, up to `limit`."""
    keys = sorted((t.ts, t.session_id) for t in pending(host, paths.queue, paths.curation))
    by_session: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    order: List[str] = []
    for key in keys:
        if key[1] not in by_session:
            order.append(key[1])
        by_session[key[1]].append(key)
    chosen: List[Tuple[str, str]] = []
    for sid in order:
        for key in by_session[sid]:
            if len(chosen) >= limit:
                return chosen
            chosen.append(key)
    return chosen


# =============================================================================
# Part 2: tension priors (agent/tension.py's retrieval, unchanged)
# =============================================================================

def build_priors_fn(kb_path: Path) -> Tuple[Optional[PriorsFn], str]:
    """A priors function over the chromadb KB index, or (None, why).

    The store prints its warm-up to stdout; that is sent to stderr so the
    packet on stdout stays pure JSON an agent can parse."""
    import contextlib
    try:
        from jarvis_core.agent.memory_manager import MemoryManager
        from jarvis_core.agent.tension import TensionCandidate, TensionDetector
        from jarvis_core.brain.boot import MEMORY_COLLECTION
        from jarvis_core.memory.store import JarvisMemoryStore
        with contextlib.redirect_stdout(sys.stderr):
            store = JarvisMemoryStore()
            store.__enter__()
            detector = TensionDetector(retriever=MemoryManager(store=store,
                                                               collection_name=MEMORY_COLLECTION))
    except Exception as exc:                                  # noqa: BLE001
        return None, f"ChromaDB unavailable ({type(exc).__name__}: {exc})"
    kb = _kb_index(kb_path)

    def priors(ts: str, text: str) -> List[Dict[str, Any]]:
        cand = TensionCandidate(source="queue", ref=f"turn:{ts}", ts=ts, text=text)
        with contextlib.redirect_stdout(sys.stderr):
            found = asyncio.run(detector.retrieve_priors(cand))
        # The index holds chunks; the agent is shown the WHOLE entry.
        return [{"id": p.entry_id, "type": p.entry_type, "ts": p.ts,
                 "content": str(kb.get(p.entry_id, {}).get("content") or p.text)}
                for p in found]
    return priors, ""


def _priors_for(priors_fn: Optional[PriorsFn], ts: str, text: str) -> List[Dict[str, Any]]:
    if priors_fn is None or len(text.strip()) < _MIN_PRIOR_CHARS:
        return []
    try:
        return priors_fn(ts, text)
    except Exception:                                         # noqa: BLE001
        return []


# =============================================================================
# Part 3: the packet
# =============================================================================

def build_packet(host: str, limit: int = 10, paths: Paths = Paths(),
                 priors_fn: Optional[PriorsFn] = None, priors_note: str = "") -> Dict[str, Any]:
    keys = _select(host, limit, paths)
    sessions = _sessions(paths.queue, {sid for _, sid in keys})
    turns = []
    for ts, sid in keys:
        rows = sessions.get(sid, [])
        row = next((r for r in rows if str(r.get("ts")) == ts), {})
        user_text = str(row.get("user_text") or "")
        turns.append({
            "ts": ts, "session_id": sid,
            "user_text": user_text,
            "assistant_summary": str(row.get("assistant_summary") or ""),
            "context": _context_of(rows, ts),
            "priors": _priors_for(priors_fn, ts, user_text),
        })
    return {
        "rule_version": PARSE_RULE_VERSION,
        "rule": PARSE_RULE,
        "host": host,
        "backlog": backlog(paths.queue, paths.curation).get(host, {}),
        "priors_note": priors_note or ("priors retrieved from the KB index for turns of "
                                       f">= {_MIN_PRIOR_CHARS} chars"),
        "turns": turns,
        "submit_hint": ("Write {\"verdicts\": [...]} (one per turn, keyed by ts and session_id) "
                        "to a file, then run: python scripts/parse_turns.py --submit <file> "
                        f"--agent {host}/<your-model-id>"),
    }


# =============================================================================
# Part 4: validation + writes
# =============================================================================

def append_curation(record: Dict[str, Any], path: Path) -> None:
    """Append one verdict: lock where the OS has one, and heal a torn last line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
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
        handle.flush()


@dataclass
class TurnReport:
    ts: str
    session_id: str
    accepted: bool
    reasons: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)       # one status line per fact
    tension: str = ""
    curation: str = ""

    def lines(self) -> List[str]:
        head = f"  {'ACCEPTED' if self.accepted else 'REJECTED'}  {self.ts}  {self.session_id}"
        out = [head] + [f"      reason : {r}" for r in self.reasons]
        out += [f"      fact   : {f}" for f in self.facts]
        if self.tension:
            out.append(f"      tension: {self.tension}")
        if self.curation:
            out.append(f"      curation: {self.curation}")
        return out


def _eligible_prior_ids(kb: Dict[str, Dict[str, Any]], ts: str) -> List[str]:
    from jarvis_core.agent.tension import CONTRADICTABLE_TYPES
    return [i for i, e in kb.items()
            if e.get("type") in CONTRADICTABLE_TYPES and str(e.get("timestamp") or "") < ts]


def _default_append(kb_path: Path, semantic: bool) -> Callable[..., Dict[str, Any]]:
    from kb_append import append_entry

    def append(**kwargs: Any) -> Dict[str, Any]:
        return append_entry(**kwargs, semantic_dedup=semantic, kb_path=kb_path)
    return append


def submit(verdicts: Any, agent: str, paths: Paths = Paths(),
           priors_fn: Optional[PriorsFn] = None, priors_ready: bool = False,
           append_fn: Optional[Callable[..., Dict[str, Any]]] = None,
           semantic: bool = True) -> List[TurnReport]:
    """Validate and write each verdict. Never coerces; a rejection writes nothing.

    `priors_ready` says `priors_fn` is the live retriever: a tension may then
    cite only a prior it would offer. Without one, a cited prior must at least
    be a real, contradictable KB entry older than the turn.
    """
    if not isinstance(verdicts, dict) or not isinstance(verdicts.get("verdicts"), list):
        return [TurnReport("", "", False, ['input must be {"verdicts": [...]}'])]
    items = verdicts["verdicts"]
    wanted = {(str(v.get("ts")), str(v.get("session_id"))) for v in items if isinstance(v, dict)}
    sessions = _sessions(paths.queue, {sid for _, sid in wanted})
    kb = _kb_index(paths.kb)
    folded = fold_events(list(_jsonl(paths.curation)))
    labels = {(str(r.get("ts")), str(r.get("session_id"))): r for r in _jsonl(paths.labels)}
    append = append_fn or _default_append(paths.kb, semantic)
    consolidator = None
    now = datetime.now(_IST).isoformat(timespec="seconds")
    agent_host = agent.split("/", 1)[0].lower()

    reports: List[TurnReport] = []
    seen_keys: set = set()
    for raw in items:
        if not isinstance(raw, dict):
            reports.append(TurnReport("", "", False, ["a verdict is not an object"]))
            continue
        ts, sid = str(raw.get("ts")), str(raw.get("session_id"))
        rep = TurnReport(ts, sid, False)
        reports.append(rep)
        if (ts, sid) in seen_keys:
            rep.reasons.append("duplicate verdict for this turn in the same submission")
            continue
        seen_keys.add((ts, sid))
        rows = sessions.get(sid, [])
        row = next((r for r in rows if str(r.get("ts")) == ts), None)
        if row is None:
            rep.reasons.append("unknown turn: no (ts, session_id) like this in the queue")
            continue
        if _TEST_SESSION.match(sid):
            rep.reasons.append("test session: ephemeral voicegate turns are never parsed")
            continue
        host = host_of(row)
        user_text = str(row.get("user_text") or "")
        ctx = TurnContext(ts=ts, session_id=sid, user_text=user_text,
                          assistant_summary=str(row.get("assistant_summary") or ""),
                          neighbours=tuple(c["user_text"] for c in _context_of(rows, ts)),
                          chat_label=str(row.get("chat_label") or ""))
        prior_ids: List[str] = []
        if raw.get("tension") not in (None, {}, ""):
            if priors_ready:
                prior_ids = [str(p["id"]) for p in _priors_for(priors_fn, ts, user_text)]
            else:
                prior_ids = _eligible_prior_ids(kb, ts)
        verdict = validate_verdict(raw, ctx, curated_by=agent, curated_at=now, prior_ids=prior_ids)
        if not isinstance(verdict, Verdict):
            rep.reasons.extend(verdict)
            continue
        rep.accepted = True
        if agent_host in HOSTS and agent_host != host:
            rep.reasons.append(f"note: a {host} turn parsed by {agent} (the owner's rule is "
                               "that the agent in the chat parses it)")

        new_facts = 0
        for fact in verdict.knowledge:
            res = append(entry_type=fact.kb_type, tags=fact.kb_tags(host),
                         content=fact.kb_content(ts, host))
            status = res.get("status", "?")
            new_facts += status == "appended"
            where = res.get("id") if status == "appended" else res.get("similar_to")
            rep.facts.append(f"{status} ({fact.type}, KB {where}) {fact.fact}")

        if verdict.tension is not None:
            from jarvis_core.agent.consolidator import Consolidator
            from jarvis_core.agent.tension import TensionFinding
            if consolidator is None:
                consolidator = Consolidator(append_fn=append, feed_path=paths.feed,
                                            kb_path=paths.kb)
            t = verdict.tension
            finding = TensionFinding(
                relation=t.kind, candidate_ref=f"turn:{ts}", candidate_ts=ts,
                prior_ref=t.prior_id, prior_ts=str(kb.get(t.prior_id, {}).get("timestamp") or ""),
                which=t.why, grounds_already_rejected=False,
                confidence=verdict.curation.confidence)
            out = consolidator.record_finding(finding, now)
            rep.tension = f"{out['status']} ({t.kind} KB {t.prior_id}) {t.why}"

        label = labels.get((ts, sid), {})
        cur = Curation(**{**verdict.curation.__dict__,
                          "embedding_label": str(label.get("label", "")),
                          "embedding_score": float(label.get("score") or 0.0)})
        record = {**cur.to_record(), "rule_version": PARSE_RULE_VERSION, "host": host,
                  "knowledge_count": len(verdict.knowledge)}
        prev = folded.get((ts, sid))
        same = prev is not None and all(
            prev.get(k) == record[k] for k in ("corpora", "domain", "trainable", "rule_version"))
        if same and new_facts == 0:
            rep.curation = "unchanged (identical verdict already recorded)"
        else:
            append_curation(record, paths.curation)
            folded[(ts, sid)] = record
            rep.curation = (f"written: {'+'.join(cur.corpora)} / {cur.domain} / "
                            f"trainable={cur.trainable}")
    return reports


def _print_reports(reports: Sequence[TurnReport]) -> int:
    for rep in reports:
        for line in rep.lines():
            print(line)
    ok = sum(r.accepted for r in reports)
    print(f"\n  {ok} accepted, {len(reports) - ok} rejected")
    return 0 if ok == len(reports) else 2


# =============================================================================
# Part 5: --auto — JARVIS parses its own turns with its own free chain
# =============================================================================

def _render_batch(turns: Sequence[Dict[str, Any]]) -> str:
    """PARSE_RULE + each session once: earlier owner turns, then the turns to parse."""
    parts = [PARSE_RULE, "", "THE TURNS TO PARSE, grouped by session. Earlier owner turns of "
             "each session come first as context; parse only the turns marked PARSE."]
    by_session: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in turns:
        by_session[t["session_id"]].append(t)
    for sid, group in by_session.items():
        offered = {t["ts"] for t in group}
        parts.append(f"\n=== session {sid} ===")
        context = {c["ts"]: c["user_text"] for t in group for c in t["context"]
                   if c["ts"] not in offered}
        timeline = sorted([(ts, "ctx", txt) for ts, txt in context.items()]
                          + [(t["ts"], "turn", t) for t in group], key=lambda x: x[0])
        for ts, kind, item in timeline:
            if kind == "ctx":
                parts.append(f"[earlier {ts}] owner: {item}")
                continue
            parts.append(f"--- PARSE ts={ts} session_id={sid} ---")
            parts.append(f"owner: {item['user_text']}")
            parts.append(f"assistant: {item['assistant_summary']}")
            if item["priors"]:
                parts.append("priors (for tension only):")
                parts.extend(f"  [id={p['id']}] {p['type']} {str(p.get('ts', ''))[:10]}: "
                             f"{p['content']}" for p in item["priors"])
    return "\n".join(parts)


def _fit(turns: List[Dict[str, Any]], window: int,
         notes_fn: Callable[[str], str]) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Page the turns into prompts that fit `window`. Nothing is cut: a single
    turn whose session context alone overflows has that context turned into
    notes over consecutive chunks (curator's chunk-and-combine); the turn
    itself always goes whole, and a turn too big even alone is left pending."""
    prompts: List[Tuple[str, List[Dict[str, Any]]]] = []
    batch: List[Dict[str, Any]] = []
    for t in turns:
        trial = batch + [t]
        if len(_render_batch(trial)) <= window:
            batch = trial
            continue
        if batch:
            prompts.append((_render_batch(batch), batch))
        batch = [t]
        if len(_render_batch(batch)) > window:
            bare = dict(t, context=[])
            budget = window - len(_render_batch([bare])) - 200
            if budget <= 0:
                print(f"  {t['ts']}  too large for the model window even alone — left pending")
                batch = []
                continue
            history = "\n".join(f"[{c['ts']}] owner: {c['user_text']}" for c in t["context"])
            notes = _notes_over(history, notes_fn, budget)
            batch = [dict(t, context=[{"ts": "", "user_text": "(notes covering every earlier "
                                       "owner turn of this session)\n" + notes}])]
    if batch:
        prompts.append((_render_batch(batch), batch))
    return prompts


def _openrouter_call(model: str, prompt: str) -> str:
    from jarvis_core.brain.llm_client import build_llm_call
    # budget_usd=0.0: a paid id can never be billed from here, even by mistake.
    client = build_llm_call(model=model, budget_usd=0.0, max_tokens=_AUTO_MAX_TOKENS,
                            timeout_s=300.0)
    return asyncio.run(client([{"role": "user", "content": prompt}]))


def auto(host: str, limit: int, paths: Paths = Paths(),
         models: Optional[List[str]] = None,
         call_fn: Callable[[str, str], str] = _openrouter_call,
         priors_fn: Optional[PriorsFn] = None, priors_note: str = "",
         priors_ready: bool = False, append_fn: Optional[Callable[..., Dict[str, Any]]] = None,
         semantic: bool = True, window: int = _CONTEXT_WINDOW_CHARS) -> int:
    """Parse up to `limit` of `host`'s oldest pending turns, a few per call.

    Each page goes down the chain on its own: a model that answers garbage,
    or whose verdicts for some turns are rejected, hands just those turns to
    the next model. A turn no model parses validly stays pending, and a page
    no model could answer at all makes the run exit non-zero.
    """
    if models is None:
        from jarvis_core.brain.voice_path import free_chain
        models = free_chain()
    turns = build_packet(host, limit, paths, priors_fn, priors_note)["turns"]
    if not turns:
        print(f"  nothing pending for {host}.")
        return 0
    unanswerable = 0
    accepted = 0
    for start in range(0, len(turns), _AUTO_PAGE):
        todo = turns[start:start + _AUTO_PAGE]
        answered_once = False
        for model in models:
            if not todo:
                break
            try:
                prompts = _fit(todo, window, lambda q, m=model: call_fn(m, q))
                answers = [_extract_json(call_fn(model, prompt) or "") for prompt, _ in prompts]
            except Exception as exc:                          # noqa: BLE001
                print(f"  {model}: {type(exc).__name__}: {exc}")
                continue
            if any(not isinstance(a, dict) or not isinstance(a.get("verdicts"), list)
                   for a in answers):
                print(f"  {model}: answer was not {{\"verdicts\": [...]}} — trying the next model")
                continue
            answered_once = True
            offered = {(t["ts"], t["session_id"]) for t in todo}
            # Models repeat a verdict; the first one per turn is the answer.
            first: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for v in (v for a in answers for v in a["verdicts"] if isinstance(v, dict)):
                key = (str(v.get("ts")), str(v.get("session_id")))
                if key in offered:
                    first.setdefault(key, v)
            verdicts = list(first.values())
            reports = submit({"verdicts": verdicts}, f"jarvis/{model}", paths, priors_fn,
                             priors_ready, append_fn, semantic) if verdicts else []
            if reports:
                _print_reports(reports)
            done = {(r.ts, r.session_id) for r in reports if r.accepted}
            accepted += len(done)
            todo = [t for t in todo if (t["ts"], t["session_id"]) not in done]
            if todo:
                print(f"  {model}: {len(todo)} turn(s) without an accepted verdict — "
                      "offering them to the next model")
        for t in todo:
            print(f"  {t['ts']}  {t['session_id']}  no model produced a valid verdict — left pending")
        unanswerable += not answered_once
    print(f"\n  parsed {accepted} of {len(turns)} offered turn(s) for {host}")
    if unanswerable:
        print(f"  CANNOT PARSE: every model in the chain failed on {unanswerable} page(s) "
              f"({', '.join(models)}). Nothing was guessed; those turns stay pending.")
        return 1
    return 0


# =============================================================================
# Part 6: reports
# =============================================================================

def run_status(paths: Paths = Paths()) -> int:
    b = backlog(paths.queue, paths.curation)
    print("=" * 62)
    print(f"  PARSE BACKLOG (rule v{PARSE_RULE_VERSION})")
    print("=" * 62)
    print(f"  {'host':<14}{'pending':>9}   oldest pending")
    for host, slot in b.items():
        print(f"  {host:<14}{slot['pending']:>9}   {slot['oldest'] or '-'}")
    print(f"  {'total':<14}{sum(s['pending'] for s in b.values()):>9}")
    print("=" * 62)
    return 0


def run_routing(paths: Paths = Paths()) -> int:
    done = fold_events(list(_jsonl(paths.curation)))
    corp = Counter("+".join(r.get("corpora", [])) or "?" for r in done.values())
    by = Counter(str(r.get("curated_by", "?")).split("/")[0] for r in done.values()
                 if int(r.get("rule_version") or 0) >= PARSE_RULE_VERSION)
    print(f"  {len(done)} turns routed (newest verdict per turn)")
    for k, v in corp.most_common():
        print(f"     {v:>5}  {k}")
    print(f"  trainable: {sum(1 for r in done.values() if r.get('trainable'))}")
    print(f"  parsed under rule v{PARSE_RULE_VERSION}, by agent: {dict(by) or 'none yet'}")
    return 0


def run_review(min_confidence: float, paths: Paths = Paths()) -> int:
    """Where a reviewing agent should look: agent vs classifier, and low confidence."""
    done = fold_events(list(_jsonl(paths.curation)))
    flagged = [(k, r) for k, r in done.items()
               if (r.get("embedding_label") not in ("", None, "unknown")
                   and r.get("embedding_label") != r.get("domain"))
               or float(r.get("confidence") or 0.0) < min_confidence]
    print(f"  {len(flagged)} of {len(done)} verdicts to review "
          f"(disagrees with the classifier, or confidence < {min_confidence:.2f})")
    for (ts, sid), r in flagged:
        print(f"   {ts}  {sid}  agent={r.get('domain')} emb={r.get('embedding_label')} "
              f"conf={float(r.get('confidence') or 0):.2f} by={r.get('curated_by')}")
        print(f"      responds_to: {r.get('responds_to', '')}")
    print("  To overturn one, --submit a corrected verdict; the original stays in the log.")
    return 0


# =============================================================================
# Part 7: self-test (offline: temp files, injected priors and model)
# =============================================================================

def _self_test() -> int:
    import tempfile
    failed: List[str] = []
    passed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        (passed if ok else failed).append(name)

    long_answer = "".join(f"step{i} " for i in range(3000))
    rows = [
        {"ts": "2026-09-28T10:00:00+05:30", "session_id": "conv-a", "host": "jarvis",
         "user_text": "I want JARVIS to remember the people in my life, not just my code.",
         "assistant_summary": "Understood."},
        {"ts": "2026-09-28T10:01:00+05:30", "session_id": "conv-a", "host": "jarvis",
         "user_text": "My girlfriend Shubha, I call her Tobu. I'm from Uttarakhand, the pahadi gene.",
         "assistant_summary": long_answer},
        {"ts": "2026-09-28T10:02:00+05:30", "session_id": "conv-a", "host": "jarvis",
         "user_text": "do it", "assistant_summary": "Done."},
        {"ts": "2026-09-28T10:03:00+05:30", "session_id": "conv-web-voicegate-z",
         "host": "jarvis", "user_text": "Hi, JARVIS.", "assistant_summary": "Hello."},
        {"ts": "2026-09-28T09:00:00+05:30", "session_id": "u-claude", "host": "claude",
         "user_text": "fix the hook", "assistant_summary": "Fixed."},
    ]
    kb_rows = [{"id": 429, "timestamp": "2026-07-18T10:00:00+05:30", "type": "Decision",
                "tags": ["x"], "content": "Specialist priority is gated by demand, not data."}]

    def fake_priors(ts: str, text: str) -> List[Dict[str, Any]]:
        return [{"id": "429", "type": "Decision", "ts": kb_rows[0]["timestamp"],
                 "content": kb_rows[0]["content"]}]

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        paths = Paths(queue=d / "q.jsonl", curation=d / "c.jsonl", kb=d / "kb.jsonl",
                      feed=d / "feed.jsonl", labels=d / "labels.jsonl")
        paths.queue.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        paths.kb.write_text("".join(json.dumps(r) + "\n" for r in kb_rows), encoding="utf-8")
        kb_before = paths.kb.read_text(encoding="utf-8")

        pk = build_packet("jarvis", 10, paths, fake_priors)
        keys = [(t["ts"], t["session_id"]) for t in pk["turns"]]
        check("T1 the packet carries the rule and its version",
              pk["rule"] == PARSE_RULE and pk["rule_version"] == PARSE_RULE_VERSION)
        check("T2 only this host's turns, oldest first, voicegate never offered",
              keys == [(r["ts"], "conv-a") for r in rows[:3]], str(keys))
        t2 = pk["turns"][1]
        check("T3 turns are whole: a 20k-char answer arrives intact",
              t2["assistant_summary"] == long_answer and t2["user_text"] == rows[1]["user_text"])
        check("T4 context is every earlier owner turn of the session, whole, oldest first",
              [c["user_text"] for c in pk["turns"][2]["context"]]
              == [rows[0]["user_text"], rows[1]["user_text"]], str(pk["turns"][2]["context"]))
        check("T5 priors only for turns with >= 40 chars of owner text",
              pk["turns"][1]["priors"] and not pk["turns"][2]["priors"])

        good = {"ts": rows[1]["ts"], "session_id": "conv-a", "corpora": ["personalization"],
                "domain": "unknown", "responds_to": "the owner's wish to be known",
                "trainable": True, "confidence": 0.9, "rationale": "self-description",
                "knowledge": [
                    {"type": "person", "fact": "The owner's girlfriend is Shubha, called Tobu.",
                     "evidence": "My girlfriend Shubha, I call her Tobu.", "person": "Shubha"},
                    {"type": "identity", "fact": "The owner is from Uttarakhand.",
                     "evidence": "I'm from Uttarakhand"}],
                "tension": None}
        trivial = {"ts": rows[2]["ts"], "session_id": "conv-a", "corpora": ["none"],
                   "domain": "unknown", "responds_to": "a plan", "trainable": False,
                   "confidence": 0.95, "rationale": "ack", "knowledge": [], "tension": None}
        bad_corpora = dict(good, corpora=["backend"])
        bad_evidence = dict(good, ts=rows[0]["ts"], knowledge=[{"type": "identity", "fact": "The owner lives in Oslo.",
                                              "evidence": "I live in Oslo"}])
        unknown = dict(trivial, ts="2026-01-01T00:00:00+05:30")
        voice = dict(trivial, ts=rows[3]["ts"], session_id="conv-web-voicegate-z")
        reps = submit({"verdicts": [bad_corpora, bad_evidence, unknown, voice]}, "claude/test",
                      paths, append_fn=None, semantic=False)
        check("T6 bad corpora, invented evidence, unknown key and a voicegate turn: all rejected",
              [r.accepted for r in reps] == [False] * 4
              and "routing half invalid" in reps[0].reasons[0]
              and "verbatim" in reps[1].reasons[0] and "unknown turn" in reps[2].reasons[0]
              and "test session" in reps[3].reasons[0], str([r.reasons for r in reps]))
        check("T7 rejections write nothing",
              not paths.curation.exists() and paths.kb.read_text(encoding="utf-8") == kb_before)
        check("T7b input that is not {verdicts: [...]} is rejected",
              not submit([good], "x", paths, semantic=False)[0].accepted)

        reps = submit({"verdicts": [good, trivial]}, "jarvis/test-model", paths, semantic=False)
        cur = [json.loads(l) for l in paths.curation.read_text(encoding="utf-8").splitlines()]
        kb_now = [json.loads(l) for l in paths.kb.read_text(encoding="utf-8").splitlines()]
        check("T8 accepted verdicts write curation with rule_version, host and knowledge_count",
              all(r.accepted for r in reps) and len(cur) == 2
              and all(c["rule_version"] == PARSE_RULE_VERSION and c["host"] == "jarvis" for c in cur)
              and cur[0]["knowledge_count"] == 2 and cur[0]["curated_by"] == "jarvis/test-model",
              str(cur))
        person = [e for e in kb_now if "person-shubha" in e.get("tags", [])]
        check("T9 facts reach the KB, typed and tagged, with the owner's words",
              len(kb_now) == 3 and person and person[0]["type"] == "Semantic"
              and "My girlfriend Shubha" in person[0]["content"]
              and "source-jarvis" in person[0]["tags"], str(kb_now[1:]))
        check("T10 the turns are no longer pending",
              [t["ts"] for t in build_packet("jarvis", 10, paths)["turns"]] == [rows[0]["ts"]])

        size = (paths.curation.stat().st_size, paths.kb.stat().st_size)
        again = submit({"verdicts": [good, trivial]}, "jarvis/test-model", paths, semantic=False)
        check("T11 re-submitting identical verdicts changes nothing",
              all(r.accepted for r in again)
              and (paths.curation.stat().st_size, paths.kb.stat().st_size) == size
              and all("unchanged" in r.curation for r in again)
              and all(f.startswith("deduped") for r in again for f in r.facts),
              str([r.lines() for r in again]))

        tens = dict(good, knowledge=[], tension={"kind": "REVERSES", "prior_id": "429",
                                                 "why": "gates priority on data again"})
        reps = submit({"verdicts": [dict(tens, ts=rows[0]["ts"], trainable=True,
                                         responds_to="opening")]}, "jarvis/test-model", paths,
                      priors_fn=fake_priors, priors_ready=True, semantic=False)
        feed = paths.feed.read_text(encoding="utf-8").splitlines() if paths.feed.exists() else []
        check("T12 a tension against an offered prior lands in the KB and the feed",
              reps[0].accepted and len(feed) == 1 and "surfaced" in reps[0].tension
              and any("clashes-with-kb-429" in e.get("tags", []) for e in
                      map(json.loads, paths.kb.read_text(encoding="utf-8").splitlines())),
              str(reps[0].lines()))
        stray = dict(tens, tension={"kind": "REVERSES", "prior_id": "9999", "why": "x"})
        reps = submit({"verdicts": [stray]}, "jarvis/test-model", paths,
                      priors_fn=fake_priors, priors_ready=True, semantic=False)
        check("T13 a tension citing a prior that was not offered is rejected",
              not reps[0].accepted and "not among the priors" in reps[0].reasons[0])

        # --auto, with an injected model. The first model answers garbage, the
        # second answers correctly: the chain moves on and the verdict carries
        # the model that produced it.
        paths2 = Paths(queue=paths.queue, curation=d / "c2.jsonl", kb=d / "kb2.jsonl",
                       feed=d / "feed2.jsonl", labels=paths.labels)
        paths2.kb.write_text(kb_before, encoding="utf-8")
        prompts_seen: List[Tuple[str, str]] = []

        def fake_model(model: str, prompt: str) -> str:
            prompts_seen.append((model, prompt))
            if model == "broken:free":
                return "I cannot help with that."
            out = []
            for r in rows[:3]:
                if f"PARSE ts={r['ts']}" in prompt:
                    v = good if r is rows[1] else dict(trivial, ts=r["ts"])
                    out.append(dict(v, ts=r["ts"]))
            return "```json\n" + json.dumps({"verdicts": out}) + "\n```"

        rc = auto("jarvis", 10, paths2, models=["broken:free", "good:free"], call_fn=fake_model,
                  semantic=False)
        cur2 = [json.loads(l) for l in paths2.curation.read_text(encoding="utf-8").splitlines()]
        check("T14 --auto writes verdicts curated_by jarvis/<model>, after a failed model",
              rc == 0 and len(cur2) == 3 and all(c["curated_by"] == "jarvis/good:free" for c in cur2),
              str(cur2))
        check("T15 the --auto prompt is the rule plus whole turns",
              prompts_seen[-1][1].startswith(PARSE_RULE) and long_answer in prompts_seen[-1][1])
        paths3 = Paths(queue=paths.queue, curation=d / "c3.jsonl", kb=d / "kb3.jsonl",
                       feed=d / "feed3.jsonl", labels=paths.labels)
        rc = auto("jarvis", 10, paths3, models=["broken:free"], call_fn=fake_model, semantic=False)
        check("T16 when every model fails: non-zero, nothing written",
              rc == 1 and not paths3.curation.exists() and not paths3.kb.exists())

        one = dict(build_packet("jarvis", 1, Paths(queue=paths.queue,
                                                   curation=d / "none.jsonl"))["turns"][0],
                   context=[])
        small = len(_render_batch([one])) + 50
        paged = _fit([one] * 3, small, lambda p: "n")
        check("T17 a batch too big for the window is paged, never cut",
              len(paged) == 3 and all(len(q) <= small for q, _ in paged), str(len(paged)))
        history = [{"ts": f"2026-09-27T0{i}:00:00+05:30", "user_text": f"h{i}-" + "h" * 2500}
                   for i in range(4)]
        window = len(_render_batch([one])) + 1500
        fitted = _fit([dict(one, context=history)], window, lambda q: "note")
        check("T18 an over-window session context becomes notes over all of it; the turn stays whole",
              len(fitted) == 1 and len(fitted[0][0]) <= window
              and one["user_text"] in fitted[0][0] and "note" in fitted[0][0]
              and "h" * 2500 not in fitted[0][0], str([len(q) for q, _ in fitted]))

    print(f"  {len(passed)}/{len(passed) + len(failed)} passed")
    return 1 if failed else 0


# =============================================================================
# CLI
# =============================================================================

def main() -> int:
    p = argparse.ArgumentParser(description="Parse the owner's turns by the one parsing rule.")
    p.add_argument("--pending", action="store_true", help="print a packet of pending turns")
    p.add_argument("--submit", metavar="FILE", help='a {"verdicts": [...]} file, or - for stdin')
    p.add_argument("--agent", help="who parsed, as host/model, e.g. claude/claude-opus-5-5")
    p.add_argument("--auto", action="store_true", help="JARVIS parses with its own free chain")
    p.add_argument("--host", choices=HOSTS)
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--status", action="store_true", help="backlog per host")
    p.add_argument("--routing", action="store_true", help="what the verdicts route")
    p.add_argument("--review", action="store_true", help="verdicts worth a second look")
    p.add_argument("--min-confidence", type=float, default=0.5)
    p.add_argument("--no-semantic", action="store_true", help="exact dedup only (faster)")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.self_test:
        return _self_test()
    if args.routing:
        return run_routing()
    if args.review:
        return run_review(args.min_confidence)
    if args.submit:
        if not args.agent or "/" not in args.agent:
            p.error("--submit needs --agent host/model")
        raw = sys.stdin.read() if args.submit == "-" else Path(args.submit).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            print(f"  not JSON: {exc}")
            return 2
        priors_fn, why = None, ""
        if any(isinstance(v, dict) and v.get("tension") not in (None, {}, "")
               for v in (data.get("verdicts") or [] if isinstance(data, dict) else [])):
            priors_fn, why = build_priors_fn(Path(KB_PATH))
            if why:
                print(f"  {why}: a cited prior must be a contradictable KB entry older than the turn")
        return _print_reports(submit(data, args.agent, priors_fn=priors_fn,
                                     priors_ready=priors_fn is not None,
                                     semantic=not args.no_semantic))
    if args.pending or args.auto:
        if not args.host:
            p.error("--pending/--auto need --host")
        priors_fn, why = build_priors_fn(Path(KB_PATH))
        note = f"{why}: priors=[] for every turn, so no tension can be judged this packet" if why else ""
        if args.auto:
            if args.host != "jarvis":
                p.error("--auto parses JARVIS's own turns; other hosts parse theirs themselves")
            return auto(args.host, args.limit, priors_fn=priors_fn, priors_note=note,
                        priors_ready=priors_fn is not None, semantic=not args.no_semantic)
        packet = build_packet(args.host, args.limit, priors_fn=priors_fn, priors_note=note)
        print(json.dumps(packet, ensure_ascii=False, indent=1))
        return 0
    return run_status()


if __name__ == "__main__":
    raise SystemExit(main())
