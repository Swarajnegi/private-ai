# Conversation Topics — Dense-Capture Backlog

> **Purpose:** a live queue of domains to have deliberate, high-density conversations on.
> Created 2026-08-20 at the user's request. **Expected to grow** — add rows freely.
>
> **Committed (not gitignored)** on purpose: unlike `personal_life.md`, nothing here names a
> third party or exposes financials, and it needs to travel to any machine JARVIS runs on.

---

## Why this list exists

Measured 2026-08-20: passive capture accrues **6.1 substantive records/week**, so a month of
incidental conversation adds only ~26 records against a ~500-1000 target. Waiting doesn't work.
Deliberate high-density sessions do — one deep hour plausibly out-produces a week of build chatter.

**What these conversations are for — and what they are NOT for.** They capture *how the user
thinks*, not what they know:

- reasoning from first principles vs. from analogy
- how they hold a position they can't fully verify (the calibration axis — the real gap vs. frontier models)
- what they pursue vs. drop, and why
- what counts as an elegant explanation to them
- taste and worldview, which no public corpus contains

They are **not** training data for domain specialists. The user corrected this on 2026-08-20 and was
right: Scientist's competence comes from DeepSeekMath-V2 distilled over millions of papers — a few
thousand tokens of conversation is a rounding error. See KB 482.

**Corollary that makes this easier, not harder:** topics need NOT be ones the user is expert in.
A conversation where they're curious and half-wrong is *better* personalization data than one where
they recite something known cold — the reasoning is visible instead of cached.

**Operational requirement:** these conversations must happen in a Claude Code chat opened in
`/home/swara_unix/work/JARVIS`. Hooks are project-scoped — anywhere else means zero capture.

---

## RE-DERIVED 2026-08-26 against the SFT spec — read this before running a session

The list below was built for one purpose: capture **raw voice**. That purpose stands and every topic
survives. But `SFT_SPEC.md` changed what "more data" means, and the queue now has **two session
types with different rules**, not one.

**The reason:** raw voice is the half already at ~1.29 M tokens. The scarce half is
**(question → the user's own answer)** — SFT pairs whose assistant side is *theirs*. Those need a
different session shape, and the target is 200 of them against ~40 available today.

| Session type | Produces | How it runs |
|---|---|---|
| **Exploratory** — the queue below | Raw voice, worldview, how they reason | As before. Real conversation, disagreement and tangents are the signal. |
| **Decision-explanation** — new, §D | SFT pairs | Named bounded question → they answer at length → **JARVIS stays quiet** until after. |

> **The rule that makes type 2 work, and it is a rule for JARVIS, not for the user:** ask, then shut
> up. A long analytical reply is exactly what makes a turn unusable as a training pair, because the
> assistant side has to be *theirs*. This happened correctly once by accident — the "unreasonable
> men" answer in the 2026-08-26 history session is the right shape. Make it deliberate.

### ⚡ Do this before any session — it beats every conversation on the list

**Retrieve the three Substack essays** from `swarajnegi.substack.com` (circa 2024): *The Detective of
Unseen Graves*, *Chasing Death to Truly Live*, and the third piece. They are long-form prose **in the
user's own voice, already written**, and they are **not in this repository** — only referenced in a
KB entry and in this file. Minutes of work for the highest-quality personalization material that
exists. Nothing on the queue below competes with it.

Second-highest: **fill in `jarvis_data/experience_map.md`.** 38 of ~133 rows carry a marker and most
of those are JARVIS's guesses; all four free-text sections are empty. It is the only record of what
the user has *not* done, and passive capture structurally cannot produce it.

---

## The queue

Status: ⬜ not started · 🔄 partially covered · ✅ has real captured depth

### Sciences & engineering
| Topic | Status | Notes |
|---|---|---|
| Physics (general) | ⬜ | |
| Quantum physics | ⬜ | |
| Space / astronomy | ⬜ | |
| Energy | ⬜ | |
| Mechanics | ⬜ | |
| Biology | ⬜ | |
| Data engineering (as *interest*, not job) | 🔄 | Heavy job-context capture exists; the *why-it-interests-them* angle does not |

### Speculative & conceptual
| Topic | Status | Notes |
|---|---|---|
| Time paradoxes | ⬜ | |
| Alternate realities | ⬜ | |

### Humanities & outlook
| Topic | Status | Notes |
|---|---|---|
| History — the specific flavour they like | ⬜ | **Highest information gain.** Verified 2026-08-20: KB has ZERO record of this; all 77 keyword matches were false positives (`DESCRIBE HISTORY`, vector *space*). User confirmed: "you wouldn't have anything." |
| World views | ⬜ | |

### Introspective
| Topic | Status | Notes |
|---|---|---|
| Philosophy | 🔄 | `insufficiency_as_sin`, `Detective of Unseen Graves` exist as conclusions — origins never captured |
| Purpose / legacy | 🔄 | Stated ("I believe I have a purpose"); content thin |
| Aspirations | 🔄 | Career + exit-corporate captured; broader life aspirations not |
| Relationships | 🔄 | Facts in `personal_life.md`; how they think *about* relationships not captured |

### Surfaced in conversation, never actually discussed
| Topic | Status | Notes |
|---|---|---|
| Fitness / training | ⬜ | Real athletic peak (90kg bench @ 66kg bw, 16-18 pull-ups) now lapsed — the *why* behind starting and stopping is uncaptured |
| Hologram project | ⬜ | Appears throughout the roster as a hypothetical corpus; user has never described wanting it |
| Passive income / exiting corporate | 🔄 | User deferred: "we'll come back to discuss how we can make passive income later" |
| Robotics / aerospace | ⬜ | Named in `Finance/strategy.md` §1 as a long-term frontier target; never discussed directly |

---

### D. Decision-explanation sessions (NEW 2026-08-26 — SFT pair source)

Not topics to explore; **decisions to explain.** The user's answer is the training target, so these
run differently: one bounded question, a long answer from them, no analysis from JARVIS until after.
Target 40 pairs from this section.

| Prompt | Status | Notes |
|---|---|---|
| Walk through a technical call you made that you'd defend against pushback | ⬜ | The DeepClone join semantics, the tier split, the retention gate — pick one and reason it out loud |
| A decision you got wrong, and what you'd do differently | ⬜ | Failure reasoning is scarcer and more diagnostic than success reasoning |
| How you decide something is "done enough" to ship | ⬜ | Directly relevant to their own stopping-criterion blind spot |
| When you disagree with a senior, how do you decide whether to press | ⬜ | Pairs with the Jijabai gap (KB 502) |
| Why you chose DE over the other paths available at graduation | ⬜ | |
| What makes an explanation good, in your own words | ⬜ | The corpus has JARVIS's model of this; not theirs |
| How you'd evaluate a junior engineer | ⬜ | Reveals the standard they hold themselves to |
| Talk through your finance strategy as if teaching it | ⬜ | `strategy.md` is written reasoning; the spoken version differs |

---

## How to run a session

0. **Which type?** Exploratory (sections A–C) or decision-explanation (section D). They have
   different rules — see the re-derivation note at the top.
1. Pick one topic — not several. Depth beats breadth for this purpose.
2. **Named, bounded prompts.** Per KB 470, open-ended "tell me about yourself" produces
   "I don't know where to start"; a named domain produces detail immediately.
3. Real conversation, not an interview script — disagreement and tangents are the signal.
4. Update the row's status here afterward.
5. Capture is automatic (`Stop` hook). Append any durable pattern to the KB during the session,
   not at the end — sessions end unpredictably (KB 473).
