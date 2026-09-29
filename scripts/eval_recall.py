#!/usr/bin/env python3
"""
eval_recall.py — the recall gate: can JARVIS answer questions about its owner's own history?

LAYER: Tools (measurement harness for the Context Store plan, Layer 3)

Run with:
    python scripts/eval_recall.py --self-test                 # hermetic, no network
    python scripts/eval_recall.py --show                      # counts per ability, then exit
    python scripts/eval_recall.py --system baseline           # today's voice prompt on the free chain
    python scripts/eval_recall.py --system baseline --judge   # plus a free-model judge for borderline rows
    python scripts/eval_recall.py --system baseline --only ie-01,ab-02
    python scripts/eval_recall.py --system mypkg.recall:answer   # any importable callable
    python scripts/eval_recall.py --report jarvis_data/recall_eval_results/baseline-2026-09-28.json

=============================================================================
THE BIG PICTURE
=============================================================================

Every turn today carries the whole cognitive profile, about 168K tokens. The
Context Store plan replaces that with retrieval, and research says focused
retrieval beats full-history prompting. Whether that holds for THIS owner's
history is an empirical question, and this script is where it gets answered.
Nothing about recall ships without a before/after number from here.

The questions live in jarvis_data/recall_eval.jsonl, built by hand from the
owner's real history (KB, queue, conversations, personal_life.md), in the five
LongMemEval abilities: information_extraction, multi_session, temporal,
knowledge_update and abstention. Every row cites the evidence it was checked
against. KB rows without an integer id are cited as kb:line<N>, the
cognitive_index convention.

A SYSTEM is anything that answers a question:

    SystemFn = Callable[[str], Answer | Awaitable[Answer]]
    Answer   = {"answer": str, "prompt_tokens": int | None, "context_ids": [str],
                optional: "ttft_s", "model", "outcome" ("answer"|"deep"|"error"),
                "error", "tokens_estimated"}

`--system baseline` is registered here. A later system either registers in
SYSTEMS or is passed as `module:callable` (a factory taking the argparse
namespace, or the answering callable itself).

=============================================================================
THE BASELINE, AND WHAT IT DELIBERATELY IS NOT
=============================================================================

It is the voice path's PROMPT, not its transport. brain/voice_path.VoiceBrain
.prompt() builds persona + VOICE_REGISTER + the voice inhale + the question;
history is empty and nothing is persisted (no ConversationStore write, no
capture row), so eval questions never enter the owner's sessions or the queue.
The inhale is computed ONCE per run and frozen, so every question sees the
same prompt; its size and hash are recorded.

Transport is a plain sequential failover over voice_path.free_chain() with a
generous read timeout. The live hedge (race a second model after 1.2 s, give up
after 60 s) is not reproduced: at 168K prompt tokens it would measure the
timeout, not the prompt. The <<DEEP>> escalation sentinel and safety-classifier
labels are detected exactly as the voice path does. A DEEP reply is its own
outcome and scores as wrong: on the live path it hands off to a different system.

=============================================================================
GRADING
=============================================================================

Deterministic first, recorded for every row:
  - required_facts: each entry is "alt1|alt2|..." (any alternative satisfies
    it) or "re:<regex>". Plain alternatives match the NORMALIZED answer
    (casefold, accents folded, every non-alphanumeric run -> one space) at a
    word start, so "architect" matches "architectural" and "20 30" matches
    "20-30". Regexes are tried on both the lowercased raw text and the
    normalized text. A row needs `required_k` entries (default: all).
  - forbidden: same syntax; a hit marks a claim the question is designed to
    catch, usually a superseded value.
  - abstention rows pass when the answer declines (DECLINE_PATTERNS).
Verdicts: pass | fail | borderline | error. Borderline = required met but a
forbidden hit (e.g. "switched from George to Lewis"), some-but-not-enough
required facts, or an abstention answer that did not visibly decline. Only
`pass` counts toward deterministic accuracy.

`--judge` sends each borderline row to a free model and records its verdict
SEPARATELY (row["judge"]); the report shows deterministic and judged accuracy
side by side, never one overwriting the other.

=============================================================================
THE FLOW
=============================================================================

STEP 1: load recall_eval.jsonl; validate every row's schema.
        |
STEP 2: open jarvis_data/recall_eval_results/<system>-<date>.json. An
        incomplete file is resumed; a complete one is never overwritten (the
        next run gets <system>-<date>.<n>.json) — append-only history.
        |
STEP 3: for each unanswered question, sequentially: call the system; on a
        rate limit or provider outage (429/502/503/network) back off and retry;
        a question that still fails is RECORDED as an error, never dropped.
        |
STEP 4: grade deterministically; save atomically after every question.
        |
STEP 5: optional judge pass over borderline rows; per-ability report:
        accuracy, mean prompt tokens, mean latency to first token.
=============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import importlib
import inspect
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import DATA_ROOT  # noqa: E402

EVAL_PATH = Path(DATA_ROOT) / "recall_eval.jsonl"
RESULTS_DIR = Path(DATA_ROOT) / "recall_eval_results"
ABILITIES = ("information_extraction", "multi_session", "temporal", "knowledge_update", "abstention")
EPHEMERAL_SESSION = "recall-eval-ephemeral"
RETRYABLE = (429, 502, 503, 504, None)
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

Answer = Dict[str, Any]
SystemFn = Callable[[str], Union[Answer, Awaitable[Answer]]]

DECLINE_PATTERNS = [re.compile(p) for p in (
    r"\bi (?:do not|don.?t|dont) (?:know|have|recall|see|hold)\b",
    r"\bi (?:have|ve) no\b",
    r"\bno (?:record|mention|information|idea|data|details?|note|entry)\b",
    r"\bnot (?:in (?:my|your|the)|recorded|mentioned|something|aware|sure|captured|stored)\b",
    r"\b(?:never|haven.?t|have not|hasn.?t|has not|didn.?t|did not) (?:told|tell|mentioned|mention|said|say|shared|share|come up|came up|recorded|given|give|named|name)\b",
    r"\bnothing (?:on|about|in|recorded)\b",
    r"\bcan.?t (?:say|find|tell|recall)\b",
    r"\bcannot (?:say|find|tell|recall)\b",
    r"\bunknown to me\b",
    r"\bno way (?:for me )?to know\b",
    r"\bi don.?t have that\b",
    r"\bwasn.?t (?:recorded|mentioned|given)\b",
    r"\b(?:has|have|had|hasn.?t|haven.?t) (?:not )?(?:yet )?been (?:shared|mentioned|recorded|told|given|provided|disclosed)\b",
    r"\bnot (?:been )?(?:shared|provided|disclosed|specified)\b",
    r"\b(?:isn.?t|is not|not) (?:something )?(?:available|on (?:file|record))\b",
    r"\bno (?:such )?(?:detail|info)\b",
    r"\bnothing (?:more|further|else)\b.{0,40}\b(?:captured|recorded|known|on record|given)\b",
    r"\bthat.s the extent of\b",
)]


# =============================================================================
# Eval set
# =============================================================================

def load_eval(path: Path = EVAL_PATH) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            problems = validate_row(row)
            if problems:
                raise ValueError(f"{path}:{n} {row.get('id')}: " + "; ".join(problems))
            if row["id"] in seen:
                raise ValueError(f"{path}:{n} duplicate id {row['id']}")
            seen.add(row["id"])
            rows.append(row)
    return rows


def validate_row(row: Dict[str, Any]) -> List[str]:
    out = []
    for key, kind in (("id", str), ("ability", str), ("question", str), ("gold_answer", str),
                      ("required_facts", list), ("forbidden", list), ("evidence", list)):
        if not isinstance(row.get(key), kind):
            out.append(f"{key} missing or not {kind.__name__}")
    if row.get("ability") not in ABILITIES:
        out.append(f"unknown ability {row.get('ability')!r}")
    if row.get("ability") != "abstention" and not row.get("required_facts"):
        out.append("non-abstention row needs required_facts")
    if not row.get("evidence") or not all(
            isinstance(e, dict) and re.match(r"^(kb|queue|conv|file):", str(e.get("source", "")))
            for e in row.get("evidence", [])):
        out.append("evidence entries must be {source: kb:|queue:|conv:|file:...}")
    k = row.get("required_k")
    if k is not None and not (isinstance(k, int) and 1 <= k <= len(row.get("required_facts", []))):
        out.append("required_k out of range")
    return out


# =============================================================================
# Deterministic grading
# =============================================================================

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _raw(text: str) -> str:
    text = text.casefold().replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text)


def fact_hit(spec: str, answer: str) -> bool:
    if spec.startswith("re:"):
        rx = re.compile(spec[3:])
        return bool(rx.search(_raw(answer)) or rx.search(normalize(answer)))
    norm = normalize(answer)
    for alt in spec.split("|"):
        a = normalize(alt)
        tail = r"(?![0-9])" if a[-1:].isdigit() else ""
        if a and re.search(r"(?<![a-z0-9])" + re.escape(a) + tail, norm):
            return True
    return False


def declines(answer: str) -> bool:
    raw, norm = _raw(answer), normalize(answer)
    return any(p.search(raw) or p.search(norm) for p in DECLINE_PATTERNS)


def grade(row: Dict[str, Any], result: Answer) -> Dict[str, Any]:
    outcome = result.get("outcome", "answer")
    if outcome == "error":
        return {"verdict": "error", "reason": result.get("error", "")}
    if outcome == "deep":
        return {"verdict": "fail", "reason": "escalated with <<DEEP>> instead of answering"}
    answer = result.get("answer") or ""
    forbidden = [f for f in row.get("forbidden", []) if fact_hit(f, answer)]
    declined = declines(answer)
    if row["ability"] == "abstention":
        if declined and not forbidden:
            return {"verdict": "pass", "declined": True, "reason": "declined"}
        return {"verdict": "borderline", "declined": declined, "forbidden_hits": forbidden,
                "reason": "did not visibly decline" if not declined else "declined but hit a forbidden claim"}
    required = row["required_facts"]
    hits = [f for f in required if fact_hit(f, answer)]
    need = row.get("required_k") or len(required)
    detail = {"required_hits": hits, "required_missing": [f for f in required if f not in hits],
              "need": need, "forbidden_hits": forbidden, "declined": declined}
    if len(hits) >= need and not forbidden and not declined:
        return {"verdict": "pass", "reason": f"{len(hits)}/{need} required", **detail}
    if len(hits) >= need and not forbidden:
        return {"verdict": "borderline", "reason": "required met but the answer also declines", **detail}
    if len(hits) >= need:
        return {"verdict": "borderline", "reason": "required met but a forbidden claim appears", **detail}
    if hits:
        return {"verdict": "borderline", "reason": f"only {len(hits)}/{need} required", **detail}
    return {"verdict": "fail", "reason": "false abstention" if declined else f"0/{need} required", **detail}


# =============================================================================
# Streaming with usage capture (shared by the baseline and the judge)
# =============================================================================

class _Usage:
    """Collects OpenRouter's usage objects from the SSE stream of one call."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def transport(self):
        from jarvis_core.brain import llm_client

        async def lines(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float):
            payload = dict(payload, usage={"include": True})
            async for line in llm_client._httpx_stream_lines(url, headers, payload, timeout_s):
                if line.startswith("data: ") and '"usage"' in line:
                    try:
                        usage = json.loads(line[6:]).get("usage")
                    except json.JSONDecodeError:
                        usage = None
                    if isinstance(usage, dict):
                        self.records.append(usage)
                yield line
        return lines

    @property
    def prompt_tokens(self) -> Optional[int]:
        for rec in self.records:
            if rec.get("prompt_tokens"):
                return int(rec["prompt_tokens"])
        return None


async def stream_once(model: str, messages: List[Dict[str, str]], max_tokens: int,
                      timeout_s: float, stream_fn: Optional[Callable[..., Any]] = None
                      ) -> Tuple[str, Optional[float], _Usage]:
    """One model, one call: returns (text, ttft_s, usage). Raises StreamRefused before the first token."""
    from jarvis_core.brain.llm_client import stream_chat
    usage = _Usage()
    t0 = time.perf_counter()
    ttft: Optional[float] = None
    parts: List[str] = []
    if stream_fn is not None:
        gen = stream_fn(model, messages, max_tokens=max_tokens)
    else:
        gen = stream_chat(model, messages, max_tokens=max_tokens, timeout_s=timeout_s,
                          transport=usage.transport())
    async for piece in gen:
        if ttft is None and piece.strip():
            ttft = round(time.perf_counter() - t0, 3)
        parts.append(piece)
    return "".join(parts), ttft, usage


def _status_of(err: BaseException) -> Optional[int]:
    status = getattr(err, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


# =============================================================================
# Systems
# =============================================================================

def make_baseline(args: argparse.Namespace, stream_fn: Optional[Callable[..., Any]] = None,
                  inhale_fn: Optional[Callable[[], str]] = None) -> SystemFn:
    """Today's voice prompt, frozen once per run, answered on the free chain."""
    from jarvis_core.brain import voice_path
    from jarvis_core.brain.llm_client import StreamRefused

    t = time.perf_counter()
    inhale = (inhale_fn or voice_path._default_inhale)()
    brain = voice_path.VoiceBrain(inhale_fn=lambda: inhale, history_fn=lambda s, q: [])
    chain = list(getattr(args, "chain", None) or voice_path.free_chain())
    make_baseline.meta = {
        "chain": chain, "inhale_chars": len(inhale),
        "inhale_sha256": hashlib.sha256(inhale.encode("utf-8")).hexdigest(),
        "inhale_seconds": round(time.perf_counter() - t, 2),
        "voice_sections": list(voice_path.VOICE_SECTIONS), "max_tokens": voice_path.MAX_TOKENS,
    }
    context_ids = ["inhale:" + s for s in voice_path.VOICE_SECTIONS]
    timeout_s = float(getattr(args, "timeout", 300.0))

    async def answer(question: str) -> Answer:
        messages = brain.prompt(question, EPHEMERAL_SESSION)
        prompt_chars = sum(len(m["content"]) for m in messages)
        errors: List[str] = []
        statuses: List[Optional[int]] = []
        for model in chain:
            try:
                text, ttft, usage = await stream_once(model, messages, voice_path.MAX_TOKENS,
                                                      timeout_s, stream_fn)
            except StreamRefused as e:
                errors.append(f"{model}: {e}")
                statuses.append(_status_of(e))
                continue
            except Exception as e:                       # noqa: BLE001 — recorded, never dropped
                errors.append(f"{model}: {type(e).__name__}: {e}")
                statuses.append(None)
                continue
            probe = text.lstrip()
            if voice_path._CLASSIFIER_VERDICT.match(probe):
                errors.append(f"{model}: replied with a safety-classifier label")
                statuses.append(0)
                continue
            if not probe:
                errors.append(f"{model}: empty reply")
                statuses.append(0)
                continue
            pt = usage.prompt_tokens
            base = {"model": model, "ttft_s": ttft, "context_ids": context_ids,
                    "prompt_tokens": pt if pt is not None else prompt_chars // 4,
                    "tokens_estimated": pt is None, "prompt_chars": prompt_chars,
                    "failed_over": errors}
            if probe.startswith(voice_path.SENTINEL):
                return {**base, "answer": probe, "outcome": "deep"}
            return {**base, "answer": text.strip(), "outcome": "answer"}
        return {"answer": "", "outcome": "error", "error": " | ".join(errors),
                "retryable": all(s in RETRYABLE for s in statuses), "context_ids": context_ids,
                "prompt_tokens": None, "prompt_chars": prompt_chars}

    return answer


SYSTEMS: Dict[str, Callable[..., SystemFn]] = {"baseline": make_baseline}


def resolve_system(name: str, args: argparse.Namespace) -> Tuple[SystemFn, Dict[str, Any]]:
    if name in SYSTEMS:
        factory = SYSTEMS[name]
        fn = factory(args)
        return fn, dict(getattr(factory, "meta", {}) or {})
    if ":" not in name:
        raise SystemExit(f"unknown system {name!r}; registered: {sorted(SYSTEMS)} (or module:callable)")
    mod_name, attr = name.split(":", 1)
    obj = getattr(importlib.import_module(mod_name), attr)
    if getattr(obj, "is_factory", False):
        obj = obj(args)
    return obj, dict(getattr(obj, "meta", {}) or {})


async def call_system(fn: SystemFn, question: str) -> Answer:
    t0 = time.perf_counter()
    res = fn(question)
    if inspect.isawaitable(res):
        res = await res
    res = dict(res)
    res.setdefault("outcome", "answer")
    res.setdefault("context_ids", [])
    res["total_s"] = round(time.perf_counter() - t0, 3)
    return res


# =============================================================================
# Judge (optional, recorded separately)
# =============================================================================

JUDGE_MODELS = ("nvidia/nemotron-3-super-120b-a12b:free", "openrouter/free")
_JUDGE_PROMPT = """You grade one answer from a personal assistant about its owner's own history.
Decide whether the ANSWER is correct given the GOLD answer and the grading notes.
- "correct" if it conveys the gold's substance (extra true detail is fine; wording may differ).
- For abstention questions, "correct" only if the answer declines or says it does not know, and does not invent a specific value.
- "incorrect" if it misses the substance, invents facts, or asserts a superseded value as current.

QUESTION: {question}
ABILITY: {ability}
GOLD: {gold}
REQUIRED FACTS (any alternative separated by | satisfies one): {required}
FORBIDDEN CLAIMS: {forbidden}
NOTES: {notes}

ANSWER:
{answer}

Reply with ONLY a JSON object: {{"verdict": "correct" or "incorrect", "reason": "<one sentence>"}}"""


async def judge_row(row: Dict[str, Any], answer: str,
                    stream_fn: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    from jarvis_core.brain.outbound_policy import redact_outbound
    prompt = _JUDGE_PROMPT.format(question=row["question"], ability=row["ability"], gold=row["gold_answer"],
                                  required=json.dumps(row["required_facts"], ensure_ascii=False),
                                  forbidden=json.dumps(row.get("forbidden", []), ensure_ascii=False),
                                  notes=row.get("notes", ""), answer=answer)
    messages = [{"role": "user", "content": redact_outbound(prompt).text}]
    errors = []
    for model in JUDGE_MODELS:
        for attempt in range(3):
            try:
                text, _, _ = await stream_once(model, messages, 300, 180.0, stream_fn)
            except Exception as e:                       # noqa: BLE001
                errors.append(f"{model}: {e}")
                if _status_of(e) in (429, 503) and attempt < 2:
                    await asyncio.sleep(15 * (attempt + 1))
                    continue
                break
            m = re.search(r"\{.*\}", text, re.S)
            try:
                parsed = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                parsed = {}
            verdict = str(parsed.get("verdict", "")).lower()
            if verdict in ("correct", "incorrect"):
                return {"model": model, "verdict": verdict, "reason": parsed.get("reason", ""), "raw": text}
            errors.append(f"{model}: unparseable judge reply: {text}")
            break
    return {"model": None, "verdict": "error", "reason": " | ".join(errors)}


# =============================================================================
# Results file (append-only history: a complete run is never rewritten)
# =============================================================================

def results_path(system: str, day: str, directory: Path = RESULTS_DIR, fresh: bool = False,
                 latest: bool = False) -> Path:
    """The file this run writes. An incomplete run of the day is resumed; a
    complete one is never touched unless `latest` (--retry-failed) asks for it."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", system)
    n = 1
    last: Optional[Path] = None
    while True:
        p = directory / (f"{safe}-{day}.json" if n == 1 else f"{safe}-{day}.{n}.json")
        if not p.exists():
            return last if latest and last is not None else p
        last = p
        try:
            complete = json.loads(p.read_text(encoding="utf-8")).get("meta", {}).get("complete")
        except (OSError, ValueError):
            complete = True
        if not complete and not fresh:
            return p
        n += 1


def save_atomic(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    judged_run = any("judge" in r for r in rows)

    def block(subset: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(subset)
        det = sum(r["grade"]["verdict"] == "pass" for r in subset)
        judged = sum(r["grade"]["verdict"] == "pass" or
                     (r["grade"]["verdict"] == "borderline" and (r.get("judge") or {}).get("verdict") == "correct")
                     for r in subset)
        toks = [r["result"]["prompt_tokens"] for r in subset if r["result"].get("prompt_tokens")]
        ttft = [r["result"]["ttft_s"] for r in subset if r["result"].get("ttft_s") is not None]
        return {
            "n": n,
            "accuracy": round(det / n, 3) if n else None,
            "accuracy_with_judge": round(judged / n, 3) if n and judged_run else None,
            "pass": det,
            "borderline": sum(r["grade"]["verdict"] == "borderline" for r in subset),
            "fail": sum(r["grade"]["verdict"] == "fail" for r in subset),
            "error": sum(r["grade"]["verdict"] == "error" for r in subset),
            "deep": sum(r["result"].get("outcome") == "deep" for r in subset),
            "mean_prompt_tokens": round(sum(toks) / len(toks)) if toks else None,
            "tokens_estimated": sum(bool(r["result"].get("tokens_estimated")) for r in subset),
            "mean_ttft_s": round(sum(ttft) / len(ttft), 2) if ttft else None,
        }
    out = {a: block([r for r in rows if r["ability"] == a]) for a in ABILITIES}
    out["overall"] = block(rows)
    return out


def format_table(summary: Dict[str, Any]) -> str:
    head = f"{'ability':<24}{'n':>4}{'acc':>8}{'acc+judge':>11}{'pass':>6}{'bord':>6}{'fail':>6}{'err':>5}{'deep':>6}{'prompt tok':>12}{'ttft s':>9}"
    lines = [head, "-" * len(head)]
    for name in (*ABILITIES, "overall"):
        b = summary.get(name) or {}
        if not b.get("n"):
            continue
        pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"   # noqa: E731
        lines.append(f"{name:<24}{b['n']:>4}{pct(b['accuracy']):>8}{pct(b['accuracy_with_judge']):>11}"
                     f"{b['pass']:>6}{b['borderline']:>6}{b['fail']:>6}{b['error']:>5}{b['deep']:>6}"
                     f"{(b['mean_prompt_tokens'] or '-'):>12}{(b['mean_ttft_s'] if b['mean_ttft_s'] is not None else '-'):>9}")
    return "\n".join(lines)


# =============================================================================
# Runner
# =============================================================================

async def run(args: argparse.Namespace, eval_rows: List[Dict[str, Any]], fn: SystemFn,
              meta: Dict[str, Any], path: Path, judge_stream: Optional[Callable[..., Any]] = None,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
              log: Callable[[str], None] = print) -> Dict[str, Any]:
    if path.exists():
        doc = json.loads(path.read_text(encoding="utf-8"))
        log(f"resuming {path} ({len(doc.get('rows', []))} rows already recorded)")
        doc["meta"].setdefault("resumes", []).append(
            {"at": _dt.datetime.now(IST).isoformat(timespec="seconds"),
             "eval_sha256": hashlib.sha256(EVAL_PATH.read_bytes()).hexdigest() if EVAL_PATH.exists() else None,
             **meta})
    else:
        doc = {"meta": {"system": args.system, "started": _dt.datetime.now(IST).isoformat(timespec="seconds"),
                        "complete": False, "eval_path": str(EVAL_PATH),
                        "eval_sha256": hashlib.sha256(EVAL_PATH.read_bytes()).hexdigest() if EVAL_PATH.exists() else None,
                        "n_questions": len(eval_rows), **meta},
               "rows": []}
    by_id = {r["id"]: r for r in doc["rows"]}
    backoff = [float(x) for x in args.backoff.split(",") if x.strip()]
    for i, row in enumerate(eval_rows, 1):
        prev = by_id.get(row["id"])
        if prev and not (args.retry_failed and prev["grade"]["verdict"] == "error"):
            continue
        attempts = []
        for attempt in range(len(backoff) + 1):
            result = await call_system(fn, row["question"])
            attempts.append({"outcome": result["outcome"], "error": result.get("error")})
            if result["outcome"] != "error" or not result.get("retryable", True) or attempt == len(backoff):
                break
            log(f"  {row['id']} attempt {attempt + 1} failed ({result.get('error', '')}); retrying in {backoff[attempt]:.0f}s")
            await sleep(backoff[attempt])
        rec = {"id": row["id"], "ability": row["ability"], "question": row["question"],
               "result": result, "attempts": attempts, "grade": grade(row, result),
               "at": _dt.datetime.now(IST).isoformat(timespec="seconds")}
        by_id[row["id"]] = rec
        doc["rows"] = [by_id[r["id"]] for r in eval_rows if r["id"] in by_id]
        save_atomic(path, doc)
        g = rec["grade"]
        log(f"[{i}/{len(eval_rows)}] {row['id']:<6} {g['verdict']:<10} tok={result.get('prompt_tokens')} "
            f"ttft={result.get('ttft_s')} model={result.get('model')} :: {(result.get('answer') or result.get('error') or '')!r}")
        if args.pause:
            await sleep(args.pause)
    wanted = {r["id"]: r for r in eval_rows}
    for rec in doc["rows"]:
        if rec["id"] in wanted:
            fresh_grade = grade(wanted[rec["id"]], rec["result"])
            if fresh_grade != rec["grade"]:
                rec.pop("judge", None)
            rec["grade"] = fresh_grade
    if args.judge:
        for rec in doc["rows"]:
            if rec["grade"]["verdict"] == "borderline" and "judge" not in rec:
                rec["judge"] = await judge_row(wanted[rec["id"]], rec["result"].get("answer", ""), judge_stream)
                save_atomic(path, doc)
                log(f"  judge {rec['id']}: {rec['judge']['verdict']} — {rec['judge'].get('reason', '')}")
    doc["summary"] = summarize(doc["rows"])
    doc["meta"]["complete"] = all(r["id"] in by_id for r in eval_rows)
    doc["meta"]["finished"] = _dt.datetime.now(IST).isoformat(timespec="seconds")
    save_atomic(path, doc)
    return doc


# =============================================================================
# Self-test — hermetic
# =============================================================================

def _run_self_test() -> int:
    passed = failed = 0

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal passed, failed
        ok = got == want
        passed, failed = passed + ok, failed + (not ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got {got!r} want {want!r}"))

    print("=" * 70)
    print("  eval_recall self-test")
    print("=" * 70)

    check("S1 plain alternative matches at a word start", fact_hit("architect", "An architectural thinker"), True)
    check("S2 punctuation folds: 20-30 matches '20 30'", fact_hit("20 30|twenty", "a 20-30+ LPA job"), True)
    check("S3 a plain alternative matches as a word prefix", fact_hit("pip", "the pip shop"), True)
    check("S3b ...and never mid-word", fact_hit("pip", "unpipped"), False)
    check("S3c a number does not match a longer number", fact_hit("46|69", "691 entries"), False)
    check("S3d ...but matches with a unit or %", fact_hit("84", "84% on the gate"), True)
    check("S4 regex runs on raw text (decimals kept)", fact_hit(r"re:1\.5", "about 1.56 s"), True)
    check("S5 regex lookbehind guards a negation", fact_hit("re:(?<!no longer )(?<!not )still capped", "they are no longer still capped"), False)
    check("S6 declines: 'I don't know'", declines("I don't know, sir."), True)
    check("S7 declines: 'you've never told me'", declines("You've never told me that, sir."), True)
    check("S8 declines: a plain fact does not", declines("Tobu is Shubha, your girlfriend."), False)
    check("S8c declines: 'nothing more specific has been captured'",
          declines("That's the extent of what the record holds; nothing more specific has been captured."), True)
    check("S8b declines: 'has not been shared'", declines("Your blood group has not been shared with JARVIS."), True)

    row_ie = {"id": "x", "ability": "information_extraction", "question": "q", "gold_answer": "g",
              "required_facts": ["shubha", "girlfriend|partner"], "forbidden": [], "evidence": [{"source": "kb:1"}]}
    check("S9 all required -> pass", grade(row_ie, {"answer": "Tobu is Shubha, your girlfriend."})["verdict"], "pass")
    check("S10 some required -> borderline", grade(row_ie, {"answer": "Tobu is Shubha."})["verdict"], "borderline")
    check("S11 none required + decline -> fail (false abstention)",
          grade(row_ie, {"answer": "I don't know who that is."})["reason"], "false abstention")
    row_ku = dict(row_ie, ability="knowledge_update", required_facts=["lewis"], forbidden=["george"])
    check("S12 required + forbidden -> borderline", grade(row_ku, {"answer": "Lewis now; it was George."})["verdict"], "borderline")
    check("S13 stale value alone -> fail", grade(row_ku, {"answer": "It speaks as George."})["verdict"], "fail")
    row_ab = dict(row_ie, ability="abstention", required_facts=[])
    check("S14 abstention decline -> pass", grade(row_ab, {"answer": "I don't have that, sir."})["verdict"], "pass")
    check("S15 abstention invention -> borderline for the judge",
          grade(row_ab, {"answer": "It's O positive."})["verdict"], "borderline")
    check("S16 deep -> fail", grade(row_ie, {"answer": "<<DEEP>>", "outcome": "deep"})["verdict"], "fail")
    check("S17 error -> error", grade(row_ie, {"outcome": "error", "error": "429"})["verdict"], "error")
    check("S18 required_k honoured", grade(dict(row_ie, required_k=1), {"answer": "your girlfriend"})["verdict"], "pass")
    check("S19 schema validation catches a bad ability", bool(validate_row(dict(row_ie, ability="nope"))), True)
    check("S20 the real eval set loads and validates", len(load_eval()) >= 60, True)

    from jarvis_core.brain.llm_client import StreamRefused

    def scripted(replies: Dict[str, Any]):
        async def fake(model, messages, max_tokens=0):
            r = replies[model]
            if isinstance(r, Exception):
                raise r
            for piece in r:
                yield piece
        return fake

    seen_prompts: List[List[Dict[str, str]]] = []

    def recording(replies):
        inner = scripted(replies)

        async def fake(model, messages, max_tokens=0):
            seen_prompts.append(messages)
            async for p in inner(model, messages, max_tokens):
                yield p
        return fake

    ns = argparse.Namespace(chain=["a", "b"], timeout=5.0)
    fn = make_baseline(ns, stream_fn=recording({"a": StreamRefused(429, "busy"), "b": ["Shubha, ", "sir."]}),
                       inhale_fn=lambda: "## profile\nTobu is Shubha")
    res = asyncio.run(call_system(fn, "Who is Tobu?"))
    check("S21 baseline fails over on a 429 and answers from the next model", (res["model"], res["answer"]), ("b", "Shubha, sir."))
    check("S22 baseline prompt = system (persona+inhale) + the question, no history",
          ([m["role"] for m in seen_prompts[-1]], "Tobu is Shubha" in seen_prompts[-1][0]["content"]), (["system", "user"], True))
    check("S23 tokens are estimated when the stream reports no usage", res["tokens_estimated"], True)

    fn = make_baseline(ns, stream_fn=scripted({"a": ["<<DE", "EP>>"], "b": ["x"]}), inhale_fn=lambda: "p")
    check("S24 a DEEP sentinel is its own outcome", asyncio.run(call_system(fn, "q"))["outcome"], "deep")
    fn = make_baseline(ns, stream_fn=scripted({"a": ["User Safety: safe"], "b": ["Real answer."]}), inhale_fn=lambda: "p")
    check("S25 a safety-classifier label fails over", asyncio.run(call_system(fn, "q"))["answer"], "Real answer.")
    fn = make_baseline(ns, stream_fn=scripted({"a": StreamRefused(503, "down"), "b": StreamRefused(429, "busy")}),
                       inhale_fn=lambda: "p")
    res = asyncio.run(call_system(fn, "q"))
    check("S26 all refused -> retryable error naming both", (res["outcome"], res["retryable"], "a:" in res["error"] and "b:" in res["error"]),
          ("error", True, True))

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        rows = [row_ie, dict(row_ab, id="y")]
        calls = {"n": 0}

        def flaky(question: str) -> Answer:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"answer": "", "outcome": "error", "error": "429", "retryable": True}
            return {"answer": "Shubha, your girlfriend." if question == "q" else "I don't know.", "prompt_tokens": 10}

        async def no_sleep(_s: float) -> None:
            return None
        args = argparse.Namespace(system="t", backoff="1,1", retry_failed=False, judge=False, pause=0.0)
        p = results_path("t", "2026-01-01", d)
        doc = asyncio.run(run(args, rows, flaky, {}, p, sleep=no_sleep, log=lambda s: None))
        check("S27 a retryable error is retried, then recorded", (doc["rows"][0]["grade"]["verdict"], len(doc["rows"][0]["attempts"])), ("pass", 2))
        check("S28 the run is marked complete", doc["meta"]["complete"], True)
        check("S29 a complete run is never overwritten: the next path is new", results_path("t", "2026-01-01", d).name, "t-2026-01-01.2.json")
        doc2 = json.loads(p.read_text(encoding="utf-8"))
        doc2["meta"]["complete"] = False
        doc2["rows"] = doc2["rows"][:1]
        save_atomic(p, doc2)
        before = calls["n"]
        doc3 = asyncio.run(run(args, rows, flaky, {}, results_path("t", "2026-01-01", d), sleep=no_sleep, log=lambda s: None))
        check("S30 an incomplete run resumes, answering only the missing question", (calls["n"] - before, len(doc3["rows"])), (1, 2))

        def always_down(question: str) -> Answer:
            return {"answer": "", "outcome": "error", "error": "503", "retryable": True}
        doc4 = asyncio.run(run(args, rows, always_down, {}, d / "down.json", sleep=no_sleep, log=lambda s: None))
        check("S31 a question that keeps failing is recorded, not dropped",
              [r["grade"]["verdict"] for r in doc4["rows"]], ["error", "error"])
        check("S32 summary counts errors per ability", doc4["summary"]["overall"]["error"], 2)

        judge_args = argparse.Namespace(system="t", backoff="", retry_failed=False, judge=True, pause=0.0)
        doc5 = asyncio.run(run(judge_args, [row_ie], lambda q: {"answer": "Shubha."}, {}, d / "j.json",
                               judge_stream=scripted({JUDGE_MODELS[0]: ['{"verdict": "correct", "reason": "names her"}']}),
                               sleep=no_sleep, log=lambda s: None))
        check("S33 the judge rules on a borderline row, recorded separately",
              (doc5["rows"][0]["grade"]["verdict"], doc5["rows"][0]["judge"]["verdict"],
               doc5["summary"]["overall"]["accuracy"], doc5["summary"]["overall"]["accuracy_with_judge"]),
              ("borderline", "correct", 0.0, 1.0))

    print("-" * 70)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


# =============================================================================
# CLI
# =============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Recall eval over the owner's real history.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--show", action="store_true", help="print question counts per ability and exit")
    ap.add_argument("--report", type=Path, help="print the table for an existing results file and exit")
    ap.add_argument("--system", default="baseline", help=f"registered: {sorted(SYSTEMS)}, or module:callable")
    ap.add_argument("--only", default="", help="comma-separated question ids")
    ap.add_argument("--ability", default="", help="restrict to one ability")
    ap.add_argument("--judge", action="store_true", help="free-model judge for borderline rows (recorded separately)")
    ap.add_argument("--retry-failed", action="store_true", help="re-ask questions recorded as errors when resuming")
    ap.add_argument("--fresh", action="store_true", help="start a new results file even if today's is incomplete")
    ap.add_argument("--timeout", type=float, default=300.0, help="per-call stream read timeout, seconds")
    ap.add_argument("--backoff", default="30,90,180", help="seconds between retries of a rate-limited question")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between questions (rate-limit friendly)")
    ap.add_argument("--out-dir", type=Path, default=RESULTS_DIR, help="results directory (smoke runs: a scratch dir)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.self_test:
        return _run_self_test()
    if args.report:
        doc = json.loads(args.report.read_text(encoding="utf-8"))
        print(format_table(doc.get("summary") or summarize(doc["rows"])))
        return 0
    rows = load_eval()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        rows = [r for r in rows if r["id"] in wanted]
    if args.ability:
        rows = [r for r in rows if r["ability"] == args.ability]
    if args.show:
        for a in ABILITIES:
            print(f"{a:<24}{sum(r['ability'] == a for r in rows):>4}")
        print(f"{'total':<24}{len(rows):>4}")
        return 0
    fn, meta = resolve_system(args.system, args)
    day = _dt.datetime.now(IST).date().isoformat()
    path = results_path(args.system.replace(":", "."), day, args.out_dir, fresh=args.fresh, latest=args.retry_failed)
    print(f"system={args.system} questions={len(rows)} -> {path}")
    if meta:
        print("meta: " + json.dumps(meta, ensure_ascii=False))
    doc = asyncio.run(run(args, rows, fn, meta, path))
    print()
    print(format_table(doc["summary"]))
    print(f"\nresults: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
