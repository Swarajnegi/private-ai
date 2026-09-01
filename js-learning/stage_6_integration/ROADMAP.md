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

## Sub-Phase 6.3: Unified API Layer ⬜

**Goal:** One interface to rule them all — REST/WebSocket API.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.3.1 | FastAPI for JARVIS | Modern async Python API | `/dev Design JARVIS API with FastAPI.` |
| 6.3.2 | WebSocket Streaming | Real-time response streaming | `/dev Implement WebSocket streaming.` |
| 6.3.3 | Authentication | Secure your JARVIS | `/dev Add API key authentication.` |
| 6.3.4 | Rate Limiting & Queuing | Handle concurrent requests | `/dev Implement request queuing.` |

**Practical Exercise:** Query JARVIS via curl and get streaming response.

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

## Sub-Phase 6.8: Universal Capture Adapter ⬜

**Goal:** Awareness capture — the mechanism that makes JARVIS actually know what you did — is
host-specific today: automatic via hooks on Claude Code, manual via `/memory` on Antigravity (no
hook system there). The underlying organ (`jarvis_core/agent/capture.py`) is already built to be
host-independent per its own design; what's missing is a defined, minimal adapter contract so a
brand-new host gets full capture parity without bespoke, one-off wiring each time.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 6.8.1 | Audit the existing capture organ | Separate what's genuinely host-independent in `capture.py` from what's currently Claude-Code-hook-specific glue | `@[/learn] Trace capture.py's host-independent core vs. its Claude Code hook adapter.` |
| 6.8.2 | Define the adapter contract | The minimal interface any new host must implement to trigger a capture event | `/dev Draft the capture adapter contract (interface, not implementation).` |
| 6.8.3 | Build a second reference adapter | Prove the contract actually generalizes by wiring it into ONE new host type (e.g. a plain terminal wrapper) | `/dev Build a second capture adapter against the contract from 6.8.2.` |
| 6.8.4 | Explicit degraded mode | A host with no adapter yet must fail visibly (no capture, flagged as such) — never silently lose turns pretending capture happened | `/dev Add an explicit "capture unavailable" state instead of silent no-ops.` |

**Practical Exercise:** Use JARVIS from a host that's never been wired up before; confirm it
either captures via the new adapter, or clearly tells you it isn't capturing — never silence.

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

## Sub-Phase 6.10: Ambient Presence Tier ⬜

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

## Distance to Goal

> **The scoreboard.** Progress is reported against *this*, not against corpus statistics. Corpus
> depth, blend ratios and record counts are instrumentation for row 2 only — the user's directive,
> 2026-08-26 (KB 504). Update the state column; do not add rows to make it look fuller.

| # | Requirement (ENDGAME §1.1) | State |
|---|---|---|
| 1 | Reasoning core reachable end-to-end | ✅ Stage 4 closed, Final Boss 8/8 |
| 2 | Corpus assembled for the trained adapter | ✅ 2,143 engineer + 921 personalization records |
| 3 | **Adapter actually trained** | ⛔ **BLOCKED — no RunPod account (zero `RUNPOD_*` env vars)** |
| 4 | Adapter deployed and serving | ⬜ Stage 5.4 |
| 5 | Voice in / voice out | ⬜ 6.1 |
| 6 | Vision in | ⬜ 6.2 |
| 7 | Unified API | ⬜ 6.3 |
| 8 | Memory reachable from any device | ⬜ 6.7 |
| 9 | Web / desktop / phone clients | ⬜ 6.9 |
| 10 | Ambient — always-on tier, cameras + mics live | ⬜ 6.10 |

**Row 3 is the whole critical path.** Rows 4–10 are all downstream of it, and it is not blocked on
engineering — it is blocked on a signup. Every hour spent deepening the corpus improves row 2, which
is already green.

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
| 6.3 Unified API Layer | ⬜ Not Started | 0/4 |
| 6.4 Conversation Memory | ⬜ Not Started | 0/4 |
| 6.5 Context Caching (Cloud) | ⬜ Not Started | 0/4 |
| 6.6 JARVIS MVP | ⬜ Not Started | 0/4 |
| 6.7 Always-Reachable Memory Backend | ⬜ Not Started | 0/4 |
| 6.8 Universal Capture Adapter | ⬜ Not Started | 0/4 |

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
