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
`threshold`, in which case it falls back to "general" ("no specific domain is
confident enough", not its own prototype).

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
STEP 3: if best_score >= threshold -> that domain; else -> "general". Blank text
        -> "general". Results cached by content so repeats (e.g. "continue")
        embed once.

=============================================================================
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

# Embedder protocol: texts in, UNIT-normalized vectors out (cosine == dot).
EmbedFn = Callable[[List[str]], List[List[float]]]

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_THRESHOLD = 0.30  # tuned against the real queue (see __main__ + KB L314 follow-up)

# The 4 SPECIFIC domains (must mirror capture_turn.py's keyword domains) + their
# seed phrases. "general" is the fallback, NOT a centroid.
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
    ],
    "jarvis-build": [
        "JARVIS agent framework in jarvis_core and its module design",
        "the ReAct loop, tool registry and permission engine",
        "MemGPT memory manager, heartbeat and the consolidator",
        "Stage 3 roadmap, the cognitive synthesis loop and the Final Boss",
        "MIRROR-lite reflection, CoT loop monitor and trace events",
    ],
}

KNOWN_DOMAINS = frozenset(set(_DEFAULT_PROTOTYPES) | {"general"})


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
    ) -> None:
        self._embed_fn = embed_fn
        self._model_name = model_name
        self._threshold = float(threshold)
        self._prototypes = prototypes or _DEFAULT_PROTOTYPES
        self._seed_vecs: Optional[Dict[str, List[List[float]]]] = None
        self._cache: Dict[str, str] = {}

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

    def classify_many(self, texts: List[str]) -> List[str]:
        seed_vecs = self._ensure_seed_vecs()

        # Resolve from cache where possible; embed only the misses.
        results: List[Optional[str]] = [None] * len(texts)
        to_embed: List[str] = []
        embed_idx: List[int] = []
        for i, t in enumerate(texts):
            key = self._key(t)
            if not (t or "").strip():
                results[i] = "general"
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

        return [r if r is not None else "general" for r in results]

    def _nearest(self, vec: List[float], seed_vecs: Dict[str, List[List[float]]]) -> str:
        """Nearest-prototype: a domain scores = MAX cosine over its seeds."""
        best_domain, best_score = "general", -1.0
        for domain, seeds in seed_vecs.items():
            score = max((_dot(vec, s) for s in seeds), default=-1.0)
            if score > best_score:
                best_domain, best_score = domain, score
        return best_domain if best_score >= self._threshold else "general"

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
    check("T5 unrelated -> general (below threshold)", clf.classify("how do I cook pasta") == "general")
    check("T6 blank -> general", clf.classify("   ") == "general")
    check("T7 empty -> general", clf.classify("") == "general")

    # batch + cache
    batch = clf.classify_many(["spark job", "sip plan", "cook pasta", "spark job"])
    check("T8 batch classifies correctly",
          batch == ["data-engineering", "finance", "general", "data-engineering"], str(batch))
    check("T9 repeated text cached (same result)", batch[0] == batch[3])
    check("T10 cache populated", len(clf._cache) >= 3, str(len(clf._cache)))

    # output is always a KNOWN domain
    check("T11 outputs are known domains", all(d in KNOWN_DOMAINS for d in batch))

    # threshold tightening pushes ambiguous -> general
    strict = DomainClassifier(embed_fn=fake_embed, threshold=0.99, prototypes=fake_protos)
    # "spark stock" -> unit [.707,.707,0,0]; best single-seed dot = .707 < 0.99 -> general.
    check("T12 high threshold pushes ambiguous -> general",
          strict.classify("spark stock") == "general", str(strict.classify("spark stock")))

    # mixed-keyword text picks the stronger domain
    check("T13 mixed picks argmax", clf.classify("spark spark sql stock") == "data-engineering")

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
            "what time should we meet for lunch tomorrow": "general",
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
