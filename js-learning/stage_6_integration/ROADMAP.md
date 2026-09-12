# PHASE 6: Integration & Interface Roadmap

> **Master Plan Position:** Phase 6 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Unify all components into a single JARVIS interface with voice and vision input.  
> **Prerequisites:** Phase 1-5 (Python, Memory, Agents, Orchestration, Specialists)  
> **This is the Final Phase — After this, JARVIS is operational.**

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **6.1** | Voice Input | Speak to JARVIS naturally | Whisper transcribes with <500ms latency |
| **6.2** | Vision Input | JARVIS can "see" images/screens | LLaVA analyzes screenshots and documents |
| **6.3** | Unified API Layer | Single interface to all components | REST/WebSocket API for all JARVIS functions |
| **6.4** | Conversation Memory | Remember context across sessions | Multi-turn conversations with history |
| **6.5** | Context Caching (Cloud) | Optional cloud-assisted code understanding | Full codebase in context via API KV caching |
| **6.6** | JARVIS MVP | The complete system | End-to-end: Voice → Think → Respond |
| **6.7** | Always-Reachable Memory Backend | Replace git-sync with a continuously-reachable memory layer | Any device reads/writes current state without a manual pull |
| **6.8** | Universal Capture Adapter | Awareness capture that isn't tied to one specific host/IDE | A new host gets full capture parity by implementing one adapter contract |
| **6.9** | Client Shells | JARVIS on the surfaces the user actually lives on | Phone, desktop and web clients all reach the same JARVIS with the same state |
| **6.10** | Ambient Presence Tier | Always-on without an always-on GPU bill | Wake word → local intent → cloud escalation, with Tier 0 never sleeping |

> **Honest note (added 2026-08-01):** this file (6.1-6.6) is the ORIGINAL pre-Stage-3 draft and
> has never been re-scoped the way `stage_4_orchestration/ROADMAP.md` was — it still assumes a
> "local Llama 70B" (6.5's constraint note, line 97) that was never actually built; the real
> stack is OpenRouter + Gemini today, Kimi K2.6 target base from Stage 5. Re-scoping 6.1-6.6
> against the real stack is a separate, larger task, not done here. 6.7 and 6.8 are new additions
> from a live architecture discussion, not part of the original draft, and describe real,
> concrete gaps identified against the CURRENT design (git-sync between two known machines;
> host-specific capture) — not aspirational voice/vision features.
>
> **Extended 2026-08-26:** 6.1-6.6 predates the stated ENDGAME as well as the stated stack. The
> user's actual deliverable — *"deployed on my phone as an app, in my computer as an app and a
> web-app ... connects to my phone camera, laptop camera and mics on both ... can really live with
> me"* — appeared **nowhere in this repo** until it was written into `JARVIS_ENDGAME.md` §1.1 on
> that date. A grep of the whole canon returned zero hits for phone/desktop/web app, android, ios,
> electron, or "ambient". 6.1-6.6 build the *capabilities* (hear, see, serve an API); they never
> built the *delivered form*. **6.9 and 6.10 are that gap**, and they are the two sub-phases
> closest to what "done" means to the user.

---

## Sub-Phase 6.1: Voice Input ⬜

**Goal:** Let JARVIS hear you — the "Iron Man" experience.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.1.1 | Whisper Overview | State-of-the-art speech recognition | `@[/learn] Explain Whisper and speech-to-text.` |
| 6.1.2 | Local Whisper Setup | Run Whisper on your hardware | `/dev Set up local Whisper with faster-whisper.` |
| 6.1.3 | Streaming Transcription | Real-time speech processing | `/dev Implement streaming transcription.` |
| 6.1.4 | Wake Word Detection | "Hey JARVIS" activation | `@[/learn] Explain wake word detection options.` |

**Practical Exercise:** Speak a command and see it transcribed in <1 second.

---

## Sub-Phase 6.2: Vision Input ⬜

**Goal:** Let JARVIS see — analyze images, screenshots, documents.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.2.1 | Vision-Language Models | LLMs that understand images | `@[/learn] Explain VLMs like LLaVA and Qwen-VL.` |
| 6.2.2 | Local LLaVA Setup | Run vision model locally | `/dev Set up LLaVA-Next for JARVIS.` |
| 6.2.3 | Screenshot Analysis | "What's on my screen?" | `/dev Implement screenshot capture and analysis.` |
| 6.2.4 | Document OCR | Extract text from images | `/dev Build OCR pipeline with vision models.` |

**Practical Exercise:** JARVIS correctly describes what's in a screenshot.

---

## Sub-Phase 6.3: Unified API Layer 🔄 **v0 SHIPPED 2026-09-08 ("the hearth")**

**Goal:** One interface to rule them all — REST/WebSocket API.

> **What actually landed, out of order and ahead of Stage 5**, because the omnipresence plan's
> steps 1–7 needed it: `js-development/jarvis_core/serve/` — `hearth.py` (ASGI app, 23/23) and
> `scheduler.py` (the clock, 24/24), plus `scripts/hearth.py` (start/stop/status) and
> `scripts/jarvis_client.py` (the reference client every other surface copies).
>
> **Verified live**, not just tested: `POST /v1/ask` booted the real Mind, ran 4–9 tools, streamed
> narration over SSE, and a second request **continued the same conversation session**. A terminal
> can now opt in with `--ask "…" --via-hearth` instead of booting a second Mind.
>
> Two design notes that changed the plan below:
> - **Raw ASGI, not FastAPI.** `uvicorn` was already installed; `fastapi`/`starlette` were not. A
>   bare ASGI callable adds **zero dependencies** and is testable with a fake `receive`/`send`
>   pair with no socket — every one of the 23 tests runs offline. 6.3.1 is therefore answered
>   differently than written, and better.
> - **The terminal demotion is opt-in, and that is not timidity.** The hearth has no TTY, so it
>   DENIES every permission prompt (and reports the denial). Making `--via-hearth` the default
>   would silently *reduce* capability. It flips once remote approval exists — the Commitment gate.

| Lesson | Topic | JARVIS Use Case | Status |
|--------|-------|-----------------|--------|
| 6.3.1 | HTTP API for JARVIS | Async Python API | ✅ raw ASGI on uvicorn (`serve/hearth.py`) — FastAPI deliberately rejected, see above |
| 6.3.2 | Streaming | Real-time response streaming | ✅ SSE over `POST /v1/ask` with `Accept: text/event-stream`; `printer=` bridged to an `asyncio.Queue`. WebSockets not needed for one-way narration |
| 6.3.3 | Authentication | Secure your JARVIS | ✅ bearer token (`.hearth_token`, 0600, gitignored) + per-request loopback peer check. Two independent gates |
| 6.3.4 | Rate Limiting & Queuing | Handle concurrent requests | 🔄 single-flight only: one ask at a time, 409 otherwise. Rejecting beats queueing (a client blocked 3 min cannot tell that from a hang). Real queuing waits for a reason to exist |
| 6.3.5 | **The clock** (not in the original plan) | JARVIS's pulse stops depending on the user opening a terminal | ✅ `serve/scheduler.py` — consolidation every 6h, guarded projection refresh. See the note under row 0 below |

**Practical Exercise:** ✅ done — `curl -H "Authorization: Bearer $(python3 scripts/hearth.py --token)"
http://127.0.0.1:8756/v1/health` and `python3 scripts/jarvis_client.py "…"`.

**Not done, and named honestly:** no WebSocket, no multi-client fan-out, no reachability beyond
loopback (Tailscale is step 9), no remote approval. `GET /v1/health` is the only other route.

---

## Sub-Phase 6.4: Conversation Memory ⬜

**Goal:** JARVIS remembers what you talked about — across sessions.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.4.1 | Conversation History | Track multi-turn context | `/dev Implement conversation history storage.` |
| 6.4.2 | Context Window Management | Handle long conversations | `@[/learn] Explain context window strategies.` |
| 6.4.3 | Session Persistence | Resume conversations later | `/dev Implement session save/restore.` |
| 6.4.4 | User Preferences | Remember how you like things | `/dev Build user preference system.` |

**Practical Exercise:** Ask JARVIS about something you discussed yesterday.

---

## Sub-Phase 6.5: Context Caching (Optional Cloud) ⬜

**Goal:** Use cloud API context caching for coding tasks that exceed local model limits.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.5.1 | KV Cache Architecture | How context caching works in cloud APIs | `@[/learn] Explain KV caching in Gemini/Claude for persistent code context.` |
| 6.5.2 | Codebase Loading | Feed entire project into cached context | `/dev Implement codebase context loader for cloud API.` |
| 6.5.3 | Hybrid Local+Cloud Routing | Use local for general, cloud for code refactoring | `/dev Route coding tasks to cloud API with cached context.` |
| 6.5.4 | Cost Management | Monitor API costs, fallback to local | `/dev Implement cost tracking and local fallback.` |

**Practical Exercise:** Load your entire JARVIS codebase into a cached Gemini session
and refactor a module with full dependency awareness.

> **Constraint:** Context caching is cloud-only. Your local Llama 70B maxes out at
> 128K tokens (~300 pages). Cloud APIs offer 1-2M tokens. Use for code ONLY
> when local context is insufficient. Privacy trade-off: code leaves your machine.

---

## Sub-Phase 6.6: JARVIS MVP ⬜

**Goal:** The complete system — your intellectual exoskeleton.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.6.1 | End-to-End Integration | Connect all phases | `/dev Integrate all JARVIS components.` |
| 6.6.2 | Error Handling & Resilience | Handle failures gracefully | `/dev Implement global error handling.` |
| 6.6.3 | Performance Optimization | Reduce latency everywhere | `/dev Profile and optimize JARVIS.` |
| 6.6.4 | The First Conversation | "Good morning, JARVIS" | `/dev Run full JARVIS demo.` |

**Practical Exercise:** Complete a multi-step research task using only voice.

---

## Sub-Phase 6.7: Always-Reachable Memory Backend ⬜

> **Implementation state (2026-09-12):** a first, deliberately narrow vertical
> slice is built but not yet deployed: the hearth now exposes authenticated,
> allowlisted JSONL-ledger read/union-write endpoints and
> `scripts/sync_remote_memory.py` batches local facts to the Railway-mounted
> durable volume. It still needs a separate sync bearer token configured in
> Railway, a deployed build, scheduled sync on each host, and the 6.7.3
> cross-device continuity proof before this row can be called complete.

**Goal:** Today, "portable across machines" means git push/pull between exactly two known
laptops, with an explicit single-user-at-a-time constraint. That's a real, working mechanism for
a solo project, but it isn't "always aware on any system" — it requires a manual sync step, and
it doesn't generalize past the two machines it was designed for. This sub-phase replaces the
git-synced files with a continuously-reachable memory/data layer any client (a third laptop, a
phone, a machine you've never used before) can read and write against in real time.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.7.1 | Self-hosted vs. cloud-hosted backend tradeoffs | A small server you run vs. a hosted DB/vector store — cost, control, uptime | `@[/learn] Explain self-hosted vs. managed backend tradeoffs for a personal memory layer.` |
| 6.7.2 | Network-reachable KB + vector store | Replace local ChromaDB with a server-reachable instance (or a thin sync daemon in front of it) | `/dev Design a network-reachable memory backend for jarvis_data/.` |
| 6.7.3 | Multi-client consistency | What changes once "single-user-at-a-time" is no longer guaranteed — two devices reading/writing close together | `@[/learn] Explain consistency models for a low-concurrency personal data store.` |
| 6.7.4 | Security/auth for a now-exposed memory layer | Local git-synced files were never network-exposed; a reachable backend is a new attack surface | `/dev Add auth to the memory backend; threat-model what changed.` |

**Practical Exercise:** From a machine that has never had this repo cloned, ask JARVIS something
that depends on yesterday's conversation — no manual sync step first.

---

## Sub-Phase 6.8: Universal Capture Adapter 🔄 **6.8.1-6.8.4 CLOSED 2026-09-10 — forced by the Codex migration, not scheduled work**

**Goal:** Awareness capture — the mechanism that makes JARVIS actually know what you did — is
host-specific today: automatic via hooks on Claude Code, manual via `/memory` on Antigravity (no
hook system there). The underlying organ (`jarvis_core/agent/capture.py`) is already built to be
host-independent per its own design; what's missing is a defined, minimal adapter contract so a
brand-new host gets full capture parity without bespoke, one-off wiring each time.

> **What actually closed this, and why it wasn't a deliberate roadmap pass:** the user bought
> ChatGPT Plus and decided to shift primary JARVIS development to Codex CLI. Building the second
> reference adapter was the forcing function this sub-phase had been waiting for — the same
> pattern as the hearth (Stage 6.3), which shipped out of order because omnipresence needed it.
> Measured before building: all 599 turns in the live queue came from ONE machine, because
> Antigravity's manual `/memory` capture has produced **zero** records across months of real use.
> Automatic beats manual, empirically, not just in theory.

| Lesson | Topic | Status |
|--------|-------|--------|
| 6.8.1 | Audit the existing capture organ | ✅ confirmed host-agnostic: `build_observation`/`append_observation`/`redact` have zero `~/.claude/` paths. Only `extract_turn`'s transcript parser and the Stop-hook event shape were Claude-specific |
| 6.8.2 | Define the adapter contract | ✅ *(implicit, proven by 6.8.3 rather than written as a standalone spec)*: parse your host's transcript into `{user_text, assistant_summary, model, ts}`, call the same two organ functions. One required organ change: `build_observation` gained an optional `ts` override — live capture stamps "now" correctly, but an adapter ingesting a HISTORICAL transcript must supply the turn's own time or corrupt every timestamp-ordered consumer downstream (`recall.py`, `agent/tension.py`) |
| 6.8.3 | Build a second reference adapter | ✅ `scripts/ingest_codex_sessions.py` (25/25 tests) — reads Codex's own persisted rollouts from `~/.codex/sessions/`, feeds the same organ Claude Code's Stop hook uses. Proves the contract generalizes: this is a **different host, different transcript format, different lifecycle** (no hooks at all — a scheduled reader instead), same queue schema, same downstream consumers unmodified |
| 6.8.4 | Explicit degraded mode | ✅ `AGENTS.md`'s CAPTURE STATUS section: tells Codex to run `--status`/`--dry-run` and say plainly if capture isn't currently running here, rather than assume the pipeline is live. Antigravity's equivalent statement updated in `js-workspace-rule.md` — still degraded, honestly, because it's still unknown whether Antigravity persists a readable transcript at all |

**What this did NOT close:** Antigravity capture is unchanged — still manual `/memory` only. 6.8.3
proved the *contract* generalizes; it did not give Antigravity a transcript to read. That remains a
scoping question (does the host persist anything on disk?), not an architecture one anymore.

**Practical Exercise:** ✅ done — ingested 7 real historical exchanges from 2 real Codex rollouts
(sessions from 2026-07-15 and 2026-09-05, both predating this sub-phase's own start), verified
end to end: correct chronological ordering, correct thread names resolved from Codex's own
session index, harness/wrapper content correctly stripped, a second run correctly ingesting zero
(watermark holds). `592 → 599` turns in `observation_queue.jsonl`; first non-Claude-Code turns
the corpus has ever held.

---

## Sub-Phase 6.9: Client Shells ⬜

**Goal:** Put JARVIS on the surfaces the user actually lives on. Today JARVIS is reachable only
from a terminal inside this repo — `orchestrator.py --ask` on one laptop. The stated endgame is a
phone app, a desktop app, and a web app, all reaching the same JARVIS with the same state
(`JARVIS_ENDGAME.md` §1.1). This sub-phase is the delivered *form*; 6.1–6.3 built the capabilities
it exposes.

**Hard constraint, stated up front:** Kimi K2.6 is 1T params (INT4 ≈ 200–400 GB). **Every client is
a thin client.** Nothing here hosts a model — they capture input, render output, and hold session
state. Inference lives in Tier 2 (§6.10). Depends on 6.3 (unified API) and 6.7 (reachable memory
backend) — without 6.7 the clients cannot share state at all.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.9.1 | Thin-client architecture | What lives on-device vs. server-side, and why the split is forced rather than chosen | `@[/learn] Explain thin-client design for a cloud-hosted personal assistant.` |
| 6.9.2 | Web app first | The cheapest surface to ship and the one that proves the API contract | `/dev Build the JARVIS web client against the 6.3 API.` |
| 6.9.3 | Desktop app | Screen capture and local-filesystem access are desktop-only powers worth having | `/dev Package the JARVIS desktop client.` |
| 6.9.4 | Phone app | Camera, mic, and always-with-you presence — the surface that makes it ambient | `/dev Build the JARVIS mobile client.` |
| 6.9.5 | One identity, many clients | Auth + session continuity so a conversation started on the phone continues on the laptop | `/dev Implement cross-client session continuity.` |

**Practical Exercise:** Start a conversation on the phone, finish it on the laptop, without
repeating yourself once.

---

## Sub-Phase 6.11: General Perception of Absence 🟡 **Tier 1 shipped; Tier 2–3 gated**

**Goal:** the sibling of `agent/tension.py`. That organ surfaces *contradiction* over the user's own
history; this one surfaces *silence* — "you opened this and never closed it." Requested directly by
the user 2026-09-11.

**Spec: [DORMANCY_SPEC.md](DORMANCY_SPEC.md).** Read §0 first — two measurements already killed the
two obvious implementations (domain-level dormancy has literally zero signal; keyword-scraping the
KB for deferral language returns mostly *closed* decisions). Tier 1 is a commitment registry that
records resolution conditions instead of inferring them; Tiers 2–3 are gated on Tier 1 proving
insufficient. Handed to Codex as `agents_converse/q_002.md`.

---

## Sub-Phase 6.10: Ambient Presence Tier ⬜

> **REFRAMED 2026-09-06: ambient is a DELIVERY CHANNEL, not a destination.** `JARVIS_ENDGAME.md`
> §1.2 established that all four §1.1 goals reduce to one organ — unprompted surfacing over the
> user's own history — and that ambient presence is how that organ reaches them, not a fifth goal
> standing alongside it.
>
> The practical consequence is a **hard ordering**: ambient presence is worth exactly as much as the
> surfacing organ has to say. A phone that is always listening and never has anything worth raising
> is a novelty with a battery cost. **Build 6.10 only after the organ demonstrably produces
> insights worth interrupting someone for** — measured, not assumed.
>
> Current state of that organ: `agent/life_state_monitor.py` has surfaced **3 insights, ever**, all
> on 2026-06-18. It was starved for 80 days by the deadlock described in row 0 below, fixed
> 2026-09-06. Whether it produces anything worth hearing at a sustained rate is now measurable and
> **unmeasured** — that measurement is the real gate on this sub-phase, not 6.1–6.9.
>
> **2026-09-08 — the organ now has a pulse, and that is a smaller claim than it sounds.**
> `serve/scheduler.py` (shipped with 6.3's hearth) runs the consolidator every 6 hours from the
> capture stream, so the feed no longer depends on the user opening `--ask`. **Nothing about
> delivery changed:** surfacing still happens only at SessionStart, so the user still has to open
> something to hear it. Step 7 made the *pulse* independent of attention; making the *delivery*
> independent is step 8 (Telegram push). Do not read "the clock ships" as "ambient works".
>
> **⛔ 2026-09-08 — THE GATE MEASUREMENT FAILED.** The clock ran the consolidator three times
> and produced zero new insights. `consolidate.py --dry-run`: `turns=115 domains=5` **`links=0`**,
> down from 1 link at 115 vs 75 turns. Neither the 0.60 floor nor the plumbing was the constraint.
>
> **✅ 2026-09-09 — DIAGNOSED, AND THE DETECTOR IS REPLACED.** The old detector was not
> under-tuned; it was measuring turn counts and could only fire when a domain *declined*
> (`b_recent < 0.6 × b_earlier`). Numerator grows with every captured turn, denominator is a
> frozen slice of history — so its ability to say anything **decayed toward zero the more JARVIS
> was used.** Its three lifetime "insights" were one volume shift restated three times, and its
> `70%` confidence was just the cap on a hand-rolled sum. `agent/tension.py` replaced it (KB 571).
>
> **What is now PROVEN, on real history, with no hand-feeding:**
> ```
> KB 461  →  retrieved KB 429 at rank 1  →  REVERSES  0.95  →  SURFACED
> KB 518  →  retrieved KB 509 at rank 1  →  NONE            →  silent
> ```
> KB 461 genuinely contradicted KB 429; a human did not notice until KB 463, days later. The
> detector produces: *"This reverses KB 429 (2026-07-20): blocks specialists based on the absence
> of evidenced personal data, contradicting Prior 429's explicit retraction of the premise that
> personal corpus absence should delay specialist training."* **That is §1.2's promised sentence,
> generated unprompted.** And KB 518 — near-identical in shape, but reversing on genuinely new
> grounds, which it says outright — correctly stayed silent. That discrimination is the design.
>
> **What is STILL NOT measured, and this is what 6.10 remains gated on.** A 26-candidate replay
> over recent material (KB since 2026-08-14, queue since 09-05) returned **0 findings** — funnel:
> `26 candidates → 26 judged (0 lacked priors) → 26 NONE`. Retrieval is healthy; the judge simply
> found no tension. That is *plausibly correct* — those candidates are build-log entries
> ("STEP 4 SHIPPED") and short approvals ("go ahead"), neither of which contradicts anything. But
> it means the SUSTAINED RATE is unknown: one proven catch is not a cadence.
>
> **So the gate has moved from "structurally impossible" to "demonstrated once, rate unmeasured."**
> Step 8 (Telegram push) stays blocked until a few weeks of scheduled running show whether real
> catches arrive often enough to justify a channel. Watch `.hearth_jobs.json` and the feed; the
> `ScanReport` funnel now makes a zero explain itself rather than being ambiguous (KB 573).

**Goal:** Make JARVIS continuously present without a continuously-running GPU. This sub-phase
exists because *"can really live with me"* and ENDGAME §2's *"cold-wake only"* are in direct
conflict — continuous 4× A5000 hosting is **~₹8.0 lakh/year** against a Year-1 envelope of
₹21.6K–50.3K, i.e. 16–38× over. The resolution is tiering, so that only the free tier never sleeps.

| Tier | Where | Cost | Sleeps? |
|---|---|---|---|
| 0 | Device CPU (phone + laptop) | ₹0 | **Never** |
| 1 | Device | ~₹0 | Never |
| 2 | RunPod cold-wake | ₹91/hr | Aggressively |

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.10.1 | Tier 0 — the always-on ear | Wake word + VAD + small-Whisper on CPU. Must be cheap enough to run forever and private enough to run locally | `/dev Build the always-on Tier 0 listener.` |
| 6.10.2 | Tier 1 — local intent triage | Answer trivia locally, escalate real intent. Reuses the CPU-side ModernBERT router already specified for the Orchestrator | `/dev Implement local intent triage and the escalation boundary.` |
| 6.10.3 | Escalation policy + cost ceiling | What justifies a ₹91/hr wake-up, and a hard monthly ceiling that fails closed | `/dev Implement wake-up policy with a fail-closed budget cap.` |
| 6.10.4 | Camera frame gating | A camera feed that wakes nothing 99.9% of the time — motion//scene-change gating before any model sees a frame | `/dev Build camera frame gating for Tier 0.` |
| 6.10.5 | Privacy boundary | What Tier 0 may retain, what leaves the device, and what is never recorded. Ambient sensing is the largest privacy surface in the project | `@[/learn] Threat-model an always-on camera and mic in a personal assistant.` |

**Practical Exercise:** Leave it running for a full day. Confirm the month's projected spend from
real wake-up counts, and confirm the ceiling actually stops it.

---

## Connectivity decisions (2026-09-08, user-confirmed)

Settled while planning the omnipresence architecture. Recorded here because each one changes a
sub-phase below.

| # | Decision | Effect |
|---|---|---|
| 1 | **Third-party servers may call JARVIS** — wanted as a capability, not a near-term use | New final step: a **scoped outbound token** (`ask:readonly`, no tools, no memory writes, no spend), rate-limited, revocable, logged in the Intent Ledger. Deliberately LAST — exposing a system whose permission layer currently fails open is the one thing that must not happen early |
| 2 | **The restaurant call stays.** My objection was US-centric and I withdrew it: India has no bot-disclosure statute for a personal agent placing a call, and TRAI's UCC framework governs *marketing*, not this | Requirement that replaces the objection: **a call must end in verifiable confirmation** (callback, SMS, or booking reference) or it reports failure. A booking you wrongly believe succeeded is worse than none. The user's own framing of the failure register — *"They hung up on me, sir."* — is now the worked example in `VOICE_SPEC.md` |
| 3 | **Device-key storage gets an interface now**, implemented as a plain file | Free today, expensive later: moving to OS keychain / Android Keystore / iOS Secure Enclave after devices are enrolled means re-enrolling all of them. Broader host-compromise threat model is deliberately deferred until JARVIS is complete |
| 4 | **Telegram now → native Android later. iOS dropped.** | Android: Firebase Cloud Messaging is free, Play Store is a **one-time $25**. iOS is **$99/yr ≈ ₹8,300 — 38% of the conservative annual envelope**, for one user, on an envelope with no hosting line. 6.9 client-shell order is therefore: Telegram bot → browser PWA → native Android. Not iOS |
| 5 | **GraphRAG (4.6) is promoted from deferred to required** | See below — it is the completion of the context design, not an optional retrieval upgrade |

### Storage vs index — the distinction that fixes row 0b's cousin

Settled in the same session, after the question *"context storage is GraphRAG, what about memory
storage — SQLite?"* GraphRAG is **not** storage. It is one of four **indexes**, and conflating the
two is what produced the live drift recorded below.

| Layer | Role | State |
|---|---|---|
| **Storage** — authoritative, the only thing that is *true* | append-only log | `knowledge_base.jsonl` + the new Context Ledger |
| **Index** — derived, disposable, rebuildable | semantic | ChromaDB ✅ |
| | token-level | ColBERT ⏭ (concept learned, skipped on storage cost) |
| | **graph / multi-hop** | **GraphRAG ⏭ NOT BUILT — now required** |
| | keyword | BM25 ✅ |
| | structured | `cognitive_index.sqlite3` ✅ |

**The log must stay JSONL and must not move into SQLite.** Append-only JSONL has a property SQLite
does not: *concatenation is merge*. Two devices append to their own segments, the files concatenate,
and the result is correct with no conflict resolution — that is the entire basis of the coherence
design. A SQLite file is a binary B-tree; two devices writing it produce a conflict git cannot merge.

**LIVE BUG THIS EXPLAINS:** `knowledge_base.jsonl` = 544 entries, `cognitive_index.sqlite3` = 533,
`cognitive_profile.md` header = 533. All five artifacts are git-tracked, **including the derived
ones**. Syncing a projection as if it were authoritative is how a mind forks on a single machine
with nothing noticing. Fix: untrack the projections, rebuild locally, stamp them with the log prefix
they were built from. `cognitive_index.py:198-203` already declares itself "derived and disposable."

**Why 4.6 GraphRAG is now required, not deferred.** Its trigger was *"first KB-logged multi-hop
retrieval failure."* That trigger is met by argument rather than incident: unbounded *recall* is
achievable by the Context Ledger, but retrieval is query-shaped, and the one thing it cannot serve is
**connecting two distant facts when you did not know to look for either**. That is multi-hop, it is
Layer 3's stated job, and it is precisely ENDGAME §1.2's moat sentence — *"it cannot fire when you
did not know to ask."* GraphRAG is the last piece of the context design, not an optional upgrade.

---

## Distance to Goal

> **The scoreboard.** Progress is reported against *this*, not against corpus statistics. Corpus
> depth, blend ratios and record counts are instrumentation for row 2 only — the user's directive,
> 2026-08-26 (KB 504). Update the state column; do not add rows to make it look fuller.

| # | Requirement (ENDGAME §1.1) | State |
|---|---|---|
| **0** | **Used at all — reached for, not just built** | 🔴 **19 `--ask` sessions lifetime; 0 in the last 30 days; last use 2026-08-03** |
| **0b** | **Proactive surfacing alive — the actual differentiator (§1.2)** | 🟡 **Unstarved 2026-09-06 after 80 days dead. 3 insights surfaced ever, all 2026-06-18. Rate now measurable, still unmeasured** |
| 1 | Reasoning core reachable end-to-end | ✅ Stage 4 closed — Final Boss 8/8 **offline scripted twin**, not a live run |
| 2 | Corpus assembled for the trained adapter | ✅ 2,143 engineer + 921 personalization records |
| 3 | **Adapter actually trained** | ⬜ Not started. Gated on row 0 by the user's own condition (corpus richness / value before spend), not blocked |
| 4 | Adapter deployed and serving | ⬜ Stage 5.4 |
| 5 | Voice in / voice out | ⬜ 6.1 |
| 6 | Vision in | ⬜ 6.2 |
| 7 | Unified API | ⬜ 6.3 |
| 8 | Memory reachable from any device | ⬜ 6.7 |
| 9 | Web / desktop / phone clients | ⬜ 6.9 |
| 10 | Ambient — always-on tier, cameras + mics live | ⬜ 6.10 |

**Row 0 added 2026-09-06, and it precedes everything.** An external audit named the failure mode —
*"a platform in search of a repeated job"* — and checking it took one command: `conversations/` holds
19 real sessions, the last on 2026-08-03, against 535 captured turns of *building* JARVIS in the same
period. The system had not been opened in a month and **nothing in this repo noticed**, because every
other instrument here counts construction. `conversations/` was the only usage log and had no reader.

It has one now: `brain/usage.py` reports days-since-last-use into the boot inhale, so JARVIS states
its own disuse in the first block of every session. That number gets worse while you build and
better only when you use — the one metric here that does not reward construction.

**Row 0b added 2026-09-06, and it explains row 0 mechanically.** Chasing "what job does this do
daily?" led to `agent/life_state_monitor.py` — the proactive-surfacing daemon, the one capability
that survives the frontier-subscription counterfactual (ENDGAME §1.2). It was dead:

```
Consolidator runs only inside Mind's heartbeat (mind.py:349)
  -> Mind boots only on `--ask`   -> unused 35 days
    -> life_state_feed.jsonl frozen at 3 entries from 2026-06-18
      -> life_state_monitor fail-closes, surfaces nothing
        -> JARVIS has nothing proactive to say
          -> no reason to open `--ask`
```

**A closed loop: the capability that justifies the system was starved by not using the system.** The
fix was small — `CrossDomainCorrelationEngine` already reads `observation_queue.jsonl`
(`correlation.py:86`), the Claude Code stream, and was never `--ask`-specific. Nothing simply called
it. `scripts/consolidate.py` plus a `Stop` hook now do, once a day, deterministically, at ₹0.
`Mind`'s heartbeat is untouched, so both sources feed one organ.

**Do not read row 0b as solved.** Unstarving it is not the same as it being useful. The 0.60 surface
floor is epistemic control and on the day of the fix the best live link scored 0.592 and correctly
produced nothing. Whether real insights clear that bar at a worthwhile rate is the open measurement
— and it gates 6.10 (see the reframe above) more than any of 6.1–6.9 do.

**Rows 4–10 remain downstream of row 3.** But row 3 is downstream of **row 0**: training an adapter
for a system nobody opens buys a better version of something unused. Two earlier framings on this
line were wrong and are corrected here — row 3 was never "blocked on a signup" (it is a deliberate
user-set gate), and row 1's ✅ means an offline scripted harness passed, not that a live system ran.

---

## Final Boss: JARVIS Operational

The complete system that:
1. [ ] Listens to voice commands (Whisper)
2. [ ] Sees images and screenshots (LLaVA)
3. [ ] Routes to appropriate specialist (Orchestrator)
4. [ ] Uses tools and memory (Agent + RAG)
5. [ ] Responds with synthesized, confident answers
6. [ ] Remembers your preferences and history

**When this works, you have built JARVIS.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 6.1 Voice Input | ⬜ Not Started | 0/4 |
| 6.2 Vision Input | ⬜ Not Started | 0/4 |
| 6.3 Unified API Layer | SHIPPED v0 - hearth | 4/4 core lessons; queueing/client shells remain |
| 6.4 Conversation Memory | ⬜ Not Started | 0/4 |
| 6.5 Context Caching (Cloud) | ⬜ Not Started | 0/4 |
| 6.6 JARVIS MVP | ⬜ Not Started | 0/4 |
| 6.7 Always-Reachable Memory Backend | 🔄 v0 ledger sync built; not deployed or cross-device verified | 1/4 |
| 6.8 Universal Capture Adapter | COMPLETE - 6.8.1-6.8.4 | 4/4 |

---

## After This Phase

**Congratulations. JARVIS is operational.**

> "Good morning, JARVIS."  
> "Good morning, sir. Systems are online. How can I assist you today?"

---

## The Journey Complete

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  "I am Iron Man."                                                           │
│                                                                             │
│  You didn't just learn to code. You built your intellectual exoskeleton.   │
│                                                                             │
│  JARVIS is now:                                                             │
│  • Your research accelerator (2-3× productivity)                            │
│  • Your multi-domain synthesizer                                            │
│  • Your context-aware assistant                                             │
│  • Your tool that removes friction between thought and action               │
│                                                                             │
│  The journey from "I want to build JARVIS" to "JARVIS, run analysis"       │
│  took ~12-15 months of focused work.                                        │
│                                                                             │
│  Now iterate. Improve. Make it yours.                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
