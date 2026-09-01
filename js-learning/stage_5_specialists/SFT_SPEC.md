# SFT Dataset Spec — Stage 5.1.2 / 5.2.2

> **What this decides:** the format, the target counts, and where every pair comes from.
> Written 2026-08-26 because "gather until the corpus is rich" had no stopping criterion — a
> condition that cannot be met by observation is not a plan. This replaces it with numbers.
>
> **Status:** spec agreed, pairs not yet built.

---

## 1. The decision: MIXED

Two objectives, two data shapes, one training run.

| | Raw text | SFT pairs |
|---|---|---|
| Record | `{"text": "..."}` | `{"messages": [user, assistant]}` |
| Loss on | every token | **assistant tokens only** |
| Teaches | how the user's material *sounds* | how to *respond* |
| Have today | **3,064 records / ~1.29 M tokens** | **0** |

**Why not raw alone.** Kimi K2.6 is already instruction-tuned — it can answer questions. The risk is
the reverse: ~1.29 M tokens of raw code and prose pushes the weights toward *"continue this
document"* and away from *"answer this person."* The observable failure is asking *"how should I
structure this job?"* and getting a YAML file in your voice instead of an answer. SFT pairs hold
instruction-following in place while the raw half does the voice work.

**Why not SFT alone.** Pairs are expensive and their ceiling is the quality of whoever writes them.
Raw text carries voice, vocabulary and judgment that no pair set reproduces economically.

**The loss-masking difference is the whole mechanical point** and must be implemented, not assumed:
raw records train on all tokens, SFT records train only on the assistant span. Two files, one
training script, two collators.

---

## 2. Format

`messages`, not Alpaca `{instruction, input, output}` — Kimi is a chat model, chat templates render
from `messages`, and both TRL and Unsloth consume it natively. Multi-turn comes free.

```json
{
  "messages": [
    {"role": "user", "content": "Why does the cross-workspace trigger run on a VNet cluster instead of serverless?"},
    {"role": "assistant", "content": "Serverless egress fails the workspace-trust check for a cross-workspace Jobs API call, so those two tasks need VNet compute. Nothing on that cluster reads Unity Catalog — both notebooks get their SP and workspace hosts pre-resolved as DAB variables — so a non-UC profile is all that is needed."}
  ],
  "source_type": "sft_engineer",
  "source_path": "test_cases_orchestrator_job.yml#block16",
  "metadata": {"origin": "transformed", "domain": "databricks_orchestration"}
}
```

Keep `source_type` / `source_path` / `metadata` — same traceability contract as the existing
corpora. Every pair must name where it came from.

---

## 3. Targets

**~600 pairs total.** Below ~200 an adapter memorizes rather than generalizes; LIMA-style results
show careful curation matters far more than volume past roughly a thousand. 600 is deliberately at
the low end of useful, because the *first* run is a measurement, not the product.

| Bucket | Target | Difficulty |
|---|---|---|
| **Engineer** | **400** | Mostly mechanical — see §4 |
| **Personalization** | **200** | The real bottleneck — see §5 |

At ~500 tokens per pair that is ~300 K tokens, roughly **19%** of the blended set against 1.29 M raw.
A meaningful fraction, not a garnish.

---

## 4. Engineer: 400 pairs, and they already exist as prose

The key finding — **these are transformed, not authored.** The source material is already
question-shaped; it just isn't in question format.

| Source | Units available | Pairs to take | Shape of the transform |
|---|---|---|---|
| `SESSION_LEARNINGS.md` bolded lessons | **151** | 120 | Each bolded claim is an answer. The question is what it answers. |
| `Data_Engineering_Lessons.md` `###` lessons | **152** | 120 | Heading → question; body → answer. Nearly 1:1. |
| `jarvis_core` "THE BIG PICTURE" headers | **75** | 60 | Docstring already explains *why this module exists*. |
| Orchestrator YAML comment blocks (>200 ch) | **29** | 29 | Decision records with rejected alternatives attached. |
| Framework `test_cases/*.py` module docstrings | ~20 | 20 | Same shape. |
| Hand-authored to fill gaps | — | 51 | Whatever §4 coverage is thin on. |
| | | **400** | |

**Quality bar.** The answer must contain the *reason*, not just the fact — that is the target voice
(KB 492: `comment_as_decision_record`). A pair whose answer states a conclusion without its
mechanism is training the exact thing the user rejects in others.

**Do not source Engineer pairs from `chat_history`.** Verified 2026-08-26: 371 of 434 Claude Code
turns have their assistant side truncated at the old 400-char cap. They are summaries, not answers.
Only 63 are intact — not a corpus. (Cap raised to 2,000 on 2026-08-21, so turns captured *from now
on* are viable; this constraint is historical only.)

---

## 5. Personalization: 200 pairs, and this is the actual bottleneck

Engineer wants *good* answers. Personalization wants **the user's** answers — their voice, their
judgment, their reasoning — as the assistant side. That material is far scarcer.

| Source | State | Pairs |
|---|---|---|
| **Substack essays** (3, circa 2024) | **NOT IN THE CORPUS AT ALL** — see below | 40 |
| Long explanatory conversation turns | ~a handful today; grows per session | 60 |
| `experience_map.md` | Created, **largely unfilled** | 40 |
| `personal_life.md` | 1 record | 20 |
| Decision-explanation sessions (new format, §6) | Not started | 40 |
| | | **200** |

### The single highest-value action, and it is not a conversation

`swarajnegi.substack.com` holds **three published essays** — *The Detective of Unseen Graves*,
*Chasing Death to Truly Live*, and one further piece (KB entry, `substack, literature, identity`).

They are **long-form prose, in the user's own voice, already written**, and they are **nowhere in
this repository** — only *referenced* in a KB entry and in `conversation_topics.md`. Retrieving them
costs minutes and yields the highest-quality personalization material available, without a single
new conversation. **Do this before any gathering session.**

### The trap

Do **not** build personalization pairs where the assistant side is *my* writing. KB
`Cognitive_Pattern` entries are observations *about* the user, authored by me. Training on them
teaches the adapter to describe the user in the third person, not to be them. Same reason assistant
turns are excluded from `user_voice` in `personalization_corpus.py`.

---

## 6. What this changes about the conversation queue

`conversation_topics.md` was built to capture **raw voice** — how the user reasons, their taste and
worldview. That purpose stands and those topics stay.

But raw voice is the half we already have 1.29 M tokens of. The scarce half is **(question → the
user's own answer)**, which needs a different session shape:

| Session type | Produces | Run how |
|---|---|---|
| **Exploratory** (existing queue: history, physics, philosophy) | Raw voice | As today — real conversation, tangents welcome |
| **Decision-explanation** (new) | SFT pairs | Ask a bounded question whose answer *is* the training target; let them answer at length; do not interrupt with my own analysis until after |

The second type did occur once by accident — the "unreasonable men" turn in the history session is
exactly the right shape. It happened because the question was named and bounded and the answer was
theirs. That should be deliberate, not lucky.

**Practical rule for me:** in a decision-explanation session, my job is to ask and shut up. Long
analytical replies are what make a turn *un*-usable as a pair — the assistant side has to be theirs.

---

## 7. Open, deliberately

- **Pair-level dedup.** 400 Engineer pairs drawn from overlapping sources will collide. Reuse the
  `_cluster_key` prefix-capping already proven in `engineer_corpus.py`.
- **Held-out eval set.** Carve ~10% before training, or Stage 5.3 has nothing honest to measure against.
- **`_PERSONALIZATION_REPEATS`** stays at 1 until the first run reports. Adding SFT pairs changes the
  char-share arithmetic; re-measure rather than re-guess.

---

## 8. Definition of done

1. `jarvis_data/training_corpus/sft_pairs.jsonl` exists, ~600 records, every one carrying `source_path`.
2. Engineer/personalization split is 400/200 ±10%.
3. A held-out slice is separated before any training run.
4. `blend_corpus.py` reports raw vs SFT share **by character**, not by record count — the mistake
   already made once and fixed on 2026-08-22.
