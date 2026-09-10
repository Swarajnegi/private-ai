"""
domain_classifier.py — Embedding nearest-centroid domain classifier (Stage 3.5.10 refinement).

LAYER: Agent (Cognitive Synthesis Loop — signal quality)

Import with:
    from jarvis_core.agent.domain_classifier import DomainClassifier, KNOWN_DOMAINS

=============================================================================
THE BIG PICTURE
=============================================================================

KB L314: the first real synthesis run returned 0 links partly because the Stop
hook's `_guess_domain` (a 4-keyword-list matcher) dumped 55/99 turns into the
catch-all "general" bucket — DE/SQL/JARVIS content that missed a keyword became
"general", starving the correlation engine of per-domain signal.

The fix is a better classifier — but it CANNOT live in the Stop hook. The hook
fires on EVERY turn of EVERY chat and must stay stdlib-fast (sub-second, no model
load), or it would block the session. So classification splits by speed:

  - CAPTURE time (hook, stdlib): keep the cheap keyword `domain_guess` as a HINT.
  - SYNTHESIS time (this, off the hot path): the correlation engine re-derives
    each turn's domain from its stored text using MiniLM embeddings + nearest-
    centroid. Embeddings are already in play at synthesis (kb dedup), so the cost
    is amortized and the queue is NEVER mutated — reclassification happens live
    on every run.

Mechanism: nearest-PROTOTYPE. Each of the 4 SPECIFIC domains is a SET of seed-
phrase embeddings; a domain's score for a turn is the MAX cosine over its seeds
(not a blurry averaged centroid — averaging diverse seeds buries the peak match,
which is exactly why an early centroid build mis-filed "LoRA fine-tuning" as
general). A turn embeds once; argmax domain wins UNLESS its best score is below
`threshold`, in which case it returns UNKNOWN -- "no specific domain is confident
enough". UNKNOWN is deliberately NOT "general": conflating the classifier declining
with a real category is what hid 99 days of bad labels (see the UNKNOWN constant).

Brain-swap-proof / testable: the embedder is an injected `embed_fn`
(Callable[[List[str]], List[List[float]]] returning UNIT-normalized vectors).
Default lazily loads `all-MiniLM-L6-v2` exactly as scripts/search_memory.py does;
tests inject a deterministic fake and never touch the model.

=============================================================================
THE FLOW
=============================================================================

STEP 1: (lazy, once) embed the seed phrases of the 4 specific domains; mean +
        re-normalize -> one unit centroid per domain.
        |
STEP 2: classify(text): embed the text (unit vector); cosine = dot vs each
        centroid; pick the best.
        |
STEP 3: if best_score >= threshold -> that domain; else -> UNKNOWN. Blank text
        -> UNKNOWN. The score travels with the label via classify_scored(), so a
        wrong threshold is measurable rather than invisible. Results cached by
        content so repeats (e.g. "continue") embed once.

=============================================================================
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

# Embedder protocol: texts in, UNIT-normalized vectors out (cosine == dot).
EmbedFn = Callable[[List[str]], List[List[float]]]

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_THRESHOLD = 0.30  # tuned against the real queue (see __main__ + KB L314 follow-up)

# ABSTENTION IS A LABEL (2026-09-08). This module used to fall back to "general"
# below threshold, exactly as the keyword matcher it was built to replace did. That
# is the real defect, and it is worse than any accuracy problem:
#
#   "general" meant BOTH "this turn is genuinely general" AND "I have no idea",
#   so a failing classifier was indistinguishable from a working one.
#
# Measured on the live queue before this change: 309 of 583 records (53%) were
# labelled "general", and ALL 309 had ZERO keyword hits. Not one was a positive
# classification. The rot ran for 99 days because an abstention had no way to be
# counted -- the same "unrepresentable fact" family as usage.py, the life_state
# feed and projections.py.
#
# UNKNOWN is now returned instead. It is not a domain; it is the classifier
# declining. Callers may then count it, alert on it, and exclude it -- none of
# which was possible while it wore the name of a real category.
UNKNOWN = "unknown"

# The 4 SPECIFIC domains (must mirror capture_turn.py's keyword domains) + their
# seed phrases. There is no "general" centroid, which is precisely why nothing was
# ever positively classified as general.
_DEFAULT_PROTOTYPES: Dict[str, List[str]] = {
    "data-engineering": [
        "Apache Spark internals, executors and the Catalyst optimizer",
        "Databricks Delta Lake, DLT and Lakeflow declarative pipelines",
        "SQL query optimization, window functions, joins and CTEs",
        "ETL data pipeline, warehouse modeling and the medallion architecture",
        "streaming joins, watermarks and stateful aggregation",
        "shuffle partitions, AQE skew handling and broadcast joins",
        "dbt, Airflow orchestration and incremental models",
        "schema evolution, SCD2 and change data capture",
        # Added 2026-09-08 from gold-set misses: the seeds above described a
        # narrower slice of the work than the user actually does. Each of these
        # scored 0.14-0.25 (below threshold) and abstained on a real DE turn.
        "AWS Glue, the Glue catalog, Athena and Redshift",
        "Delta time travel, VACUUM, retention windows and the transaction log",
        "snapshot CDC, apply_changes, handling deletes and late-arriving data",
        "Azure Data Factory dynamic pipelines and on-premise source ingestion",
        "data engineering interview questions on warehousing and pipelines",
    ],
    "finance": [
        "stock portfolio allocation and investment strategy",
        "SIP, mutual funds and equity rebalancing",
        "NSE market movements, bulk deals and watchlist",
        "risk profile, entry, stop-loss and position sizing",
        "capital allocation plan and trade rationale",
    ],
    "ai-ml": [
        "transformer attention, embeddings and tokenization",
        "LoRA and QLoRA fine-tuning of language models",
        "retrieval augmented generation and vector search",
        "neural network training, gradients and backpropagation",
        "LLM inference, quantization and model evaluation metrics",
        # Same gold-set correction: the training-INFRASTRUCTURE vocabulary was
        # entirely missing, so "the SFT thing / the runpod task" scored 0.210.
        "SFT supervised fine-tuning datasets and instruction response pairs",
        "RunPod GPU pods, training cost per hour and adapter training runs",
        "running models locally on device, agentic AI hardware and NPUs",
    ],
    "jarvis-build": [
        "JARVIS agent framework in jarvis_core and its module design",
        "the ReAct loop, tool registry and permission engine",
        "MemGPT memory manager, heartbeat and the consolidator",
        "Stage 3 roadmap, the cognitive synthesis loop and the Final Boss",
        "MIRROR-lite reflection, CoT loop monitor and trace events",
        # Same correction: JARVIS's own operation and evaluation, as opposed to
        # its code, had no seeds at all.
        "iterating on JARVIS's own answers and how it responds to questions",
        "the observation queue, per-prompt capture and the cognitive profile",
        "JARVIS chats across VS Code and Antigravity, and its identity",
    ],
}

KNOWN_DOMAINS = frozenset(set(_DEFAULT_PROTOTYPES) | {UNKNOWN})


def _unit(vec: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n > 0 else list(vec)


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _build_default_embed_fn(model_name: str) -> EmbedFn:
    """Lazy real embedder — same loader scripts/search_memory.py uses."""
    from sentence_transformers import SentenceTransformer  # local import: heavy
    model = SentenceTransformer(model_name)

    def embed(texts: List[str]) -> List[List[float]]:
        vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    return embed


class DomainClassifier:
    """Re-derives a turn's domain from its text via embedding nearest-centroid.
    Used at SYNTHESIS time only — never in the Stop hook."""

    def __init__(
        self,
        embed_fn: Optional[EmbedFn] = None,
        threshold: float = _DEFAULT_THRESHOLD,
        prototypes: Optional[Dict[str, List[str]]] = None,
        model_name: str = _DEFAULT_MODEL,
        fallback_label: str = UNKNOWN,
    ) -> None:
        self._embed_fn = embed_fn
        self._model_name = model_name
        self._threshold = float(threshold)
        # WHAT "BELOW THRESHOLD" MEANS DEPENDS ON THE CALLER, and conflating the
        # two is what this class was just fixed for. Two live consumers:
        #   - activity domains: there is no "general" prototype, so falling back
        #     to that name asserted a category nobody classified into -> UNKNOWN.
        #   - brain/router.py: "general" IS a real routing destination (the
        #     general model pool). Abstaining there legitimately means "send it
        #     to general", so the router passes fallback_label="general".
        # Hard-coding UNKNOWN broke the router's 50-query gate (Final Boss leg 3,
        # caught 2026-09-09) because "unknown" is not in its ROUTING_LABELS.
        self._fallback = str(fallback_label)
        self._prototypes = prototypes or _DEFAULT_PROTOTYPES
        self._seed_vecs: Optional[Dict[str, List[List[float]]]] = None
        self._cache: Dict[str, str] = {}
        self._score_cache: Dict[str, Tuple[str, float]] = {}

    # ---- lazy embedder + centroids --------------------------------------

    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._embed_fn is None:
            self._embed_fn = _build_default_embed_fn(self._model_name)
        return self._embed_fn(texts)

    def _ensure_seed_vecs(self) -> Dict[str, List[List[float]]]:
        if self._seed_vecs is not None:
            return self._seed_vecs
        # Embed every seed across all domains in ONE batch, then regroup.
        flat: List[str] = []
        spans: List[tuple] = []  # (domain, start, end)
        for domain, seeds in self._prototypes.items():
            start = len(flat)
            flat.extend(seeds)
            spans.append((domain, start, len(flat)))
        vecs = self._embed(flat) if flat else []
        seed_vecs: Dict[str, List[List[float]]] = {}
        for domain, start, end in spans:
            seed_vecs[domain] = [_unit(v) for v in vecs[start:end]]
        self._seed_vecs = seed_vecs
        return seed_vecs

    # ---- classification --------------------------------------------------

    def classify(self, text: str) -> str:
        return self.classify_many([text])[0]

    def classify_scored(self, text: str) -> Tuple[str, float]:
        """Like classify(), but also returns the winning cosine score — the routing
        layer (Stage 4.2) needs a (label, confidence) pair, not just the label. A
        below-threshold result is (UNKNOWN, <the sub-threshold max>) so callers see
        HOW close it came; blank text is (UNKNOWN, 0.0) -- blank text is not a
        "general" turn, it is nothing to classify, and saying so is the point."""
        if not (text or "").strip():
            return self._fallback, 0.0
        key = self._key(text)
        if key in self._score_cache:
            return self._score_cache[key]
        seed_vecs = self._ensure_seed_vecs()
        vec = self._embed([text])[0]
        result = self._nearest_scored(vec, seed_vecs)
        self._score_cache[key] = result
        return result

    def classify_many(self, texts: List[str]) -> List[str]:
        seed_vecs = self._ensure_seed_vecs()

        # Resolve from cache where possible; embed only the misses.
        results: List[Optional[str]] = [None] * len(texts)
        to_embed: List[str] = []
        embed_idx: List[int] = []
        for i, t in enumerate(texts):
            key = self._key(t)
            if not (t or "").strip():
                results[i] = self._fallback
            elif key in self._cache:
                results[i] = self._cache[key]
            else:
                to_embed.append(t)
                embed_idx.append(i)

        if to_embed:
            vecs = self._embed(to_embed)
            for j, vec in enumerate(vecs):
                domain = self._nearest(vec, seed_vecs)
                i = embed_idx[j]
                results[i] = domain
                self._cache[self._key(texts[i])] = domain

        return [r if r is not None else self._fallback for r in results]

    def _nearest(self, vec: List[float], seed_vecs: Dict[str, List[List[float]]]) -> str:
        """Nearest-prototype: a domain scores = MAX cosine over its seeds."""
        return self._nearest_scored(vec, seed_vecs)[0]

    def _nearest_scored(
        self, vec: List[float], seed_vecs: Dict[str, List[List[float]]]
    ) -> Tuple[str, float]:
        """Nearest-prototype with the winning score. Below threshold -> (UNKNOWN,
        best_score): the score is still the closest specific-domain match, so a
        caller can see HOW close it came and tune the threshold against evidence
        instead of guessing. Returning UNKNOWN rather than "general" is what makes
        a wrong threshold detectable at all — see the UNKNOWN constant's note."""
        best_domain, best_score = self._fallback, -1.0
        for domain, seeds in seed_vecs.items():
            score = max((_dot(vec, s) for s in seeds), default=-1.0)
            if score > best_score:
                best_domain, best_score = domain, score
        if best_score >= self._threshold:
            return best_domain, best_score
        return self._fallback, best_score

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS
# =============================================================================

def _run_self_test() -> None:
    print("=" * 70)
    print("  domain_classifier.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # --- Deterministic FAKE embedder: a 4-d keyword-presence space. Centroids and
    # queries built so nearest-centroid + threshold are fully predictable. ---
    fake_keys = {
        "data-engineering": ["spark", "sql"],
        "finance": ["stock", "sip"],
        "ai-ml": ["lora", "transformer"],
        "jarvis-build": ["jarvis", "react"],
    }
    order = list(fake_keys.keys())

    def fake_embed(texts: List[str]) -> List[List[float]]:
        out = []
        for t in texts:
            tl = (t or "").lower()
            v = [float(sum(1 for k in fake_keys[d] if k in tl)) for d in order]
            out.append(_unit(v))
        return out

    fake_protos = {
        "data-engineering": ["spark sql"],
        "finance": ["stock sip"],
        "ai-ml": ["lora transformer"],
        "jarvis-build": ["jarvis react"],
    }
    clf = DomainClassifier(embed_fn=fake_embed, threshold=0.30, prototypes=fake_protos)

    check("T1 spark -> data-engineering", clf.classify("explain spark AQE skew") == "data-engineering")
    check("T2 stock -> finance", clf.classify("rebalance my stock portfolio") == "finance")
    check("T3 lora -> ai-ml", clf.classify("LoRA fine-tuning details") == "ai-ml")
    check("T4 jarvis -> jarvis-build", clf.classify("the jarvis consolidator module") == "jarvis-build")
    check("T5 unrelated -> UNKNOWN, not 'general' (the classifier declines, and says so)",
          clf.classify("how do I cook pasta") == UNKNOWN)
    check("T6 blank -> UNKNOWN (whitespace is nothing to classify, not a general turn)",
          clf.classify("   ") == UNKNOWN)
    check("T7 empty -> UNKNOWN", clf.classify("") == UNKNOWN)

    # batch + cache
    batch = clf.classify_many(["spark job", "sip plan", "cook pasta", "spark job"])
    check("T8 batch classifies correctly",
          batch == ["data-engineering", "finance", UNKNOWN, "data-engineering"], str(batch))
    check("T9 repeated text cached (same result)", batch[0] == batch[3])
    check("T10 cache populated", len(clf._cache) >= 3, str(len(clf._cache)))

    # output is always a KNOWN domain
    check("T11 outputs are known domains", all(d in KNOWN_DOMAINS for d in batch))

    # threshold tightening pushes ambiguous -> UNKNOWN
    strict = DomainClassifier(embed_fn=fake_embed, threshold=0.99, prototypes=fake_protos)
    # "spark stock" -> unit [.707,.707,0,0]; best single-seed dot = .707 < 0.99 -> UNKNOWN.
    check("T12 an over-tight threshold abstains rather than guessing",
          strict.classify("spark stock") == UNKNOWN, str(strict.classify("spark stock")))

    # mixed-keyword text picks the stronger domain
    check("T13 mixed picks argmax", clf.classify("spark spark sql stock") == "data-engineering")

    # classify_scored: (label, confidence) for the routing layer (Stage 4.2)
    lbl, sc = clf.classify_scored("explain spark AQE skew")
    check("T14 classify_scored returns matching label", lbl == "data-engineering", lbl)
    check("T14b classify_scored returns a float score in [-1,1]",
          isinstance(sc, float) and -1.0 <= sc <= 1.0001, str(sc))
    check("T14c classify_scored agrees with classify",
          clf.classify_scored("rebalance my stock portfolio")[0] == clf.classify("rebalance my stock portfolio"))
    blbl, bsc = clf.classify_scored("   ")
    check("T14d blank -> (UNKNOWN, 0.0)", blbl == UNKNOWN and bsc == 0.0, f"{blbl},{bsc}")

    # --- OPTIONAL: real MiniLM model with the REAL prototypes (tunes the default
    # threshold). Skips gracefully if sentence-transformers can't load. ---
    real_ok = True
    try:
        real = DomainClassifier()  # default embed_fn (lazy real model) + default prototypes
        cases = {
            "explain spark AQE skew handling in databricks": "data-engineering",
            "rebalance my SIP portfolio allocation on NSE": "finance",
            "LoRA fine-tuning a transformer with QLoRA adapters": "ai-ml",
            "the jarvis_core ReAct agent loop and consolidator": "jarvis-build",
            # Not "general" — there is no general prototype to match, so the honest
            # answer is that no domain is confident enough. That distinction is the
            # entire point of UNKNOWN.
            "what time should we meet for lunch tomorrow": UNKNOWN,
        }
        for text, expect in cases.items():
            got = real.classify(text)
            check(f"R: '{text[:32]}...' -> {expect}", got == expect, f"got {got}")
    except Exception as e:
        real_ok = False
        print(f"  [real-model checks skipped: {type(e).__name__}: {e}]")

    total = passed + len(failed)
    print(f"\n  Passed: {passed}/{total}" + ("" if real_ok else "  (real-model checks skipped)"))
    if failed:
        for f_ in failed:
            print(f"  {f_}")
        print("=" * 70)
        raise SystemExit(1)
    print(f"  All {total} domain_classifier smoke tests passed.")
    print("=" * 70)


if __name__ == "__main__":
    _run_self_test()
