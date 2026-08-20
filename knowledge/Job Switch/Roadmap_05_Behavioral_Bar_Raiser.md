# Job Switch Roadmap 05 — Behavioral, Bar Raiser & Hiring Manager (6 weeks)

> **Goal:** Walk into the behavioral, Bar Raiser, and hiring-manager rounds with **8–10 distinct, metric-backed stories**, and answer any prompt in STAR format without visibly searching for one.
>
> **Why this matters:** This is where strong engineers get rejected. Three of the four red-flag categories are behavioral — communication, problem-solving *approach*, and project understanding — and the single most-cited failure is **reusing the same 2–3 stories across an entire loop**. That failure is entirely preventable and entirely a preparation problem. The Bar Raiser round in particular can veto an otherwise-passing candidate.
>
> **Prerequisites:** Two years of real project work. You have four distinct sources to mine, which is more than enough.
>
> **Outcome:** A story bank of 8–10 written, rehearsed, metric-backed stories, mapped to every standard prompt.
>
> **Time budget:** ~3 hrs/week × 6 weeks (weeks 10–16) — **but story-mining starts in Week 1** and runs passively throughout. See the note below.

---

## Start mining in Week 1, not Week 10

The roadmap *runs* weeks 10–16, but the raw material has to be collected from the start. Reason: you cannot reconstruct real numbers from memory four months later. Runtime before and after a fix, row counts, cost deltas, incident durations — these exist right now in your Jira tickets, PR descriptions, Slack threads, dashboards, and pipeline logs. They will be harder to find every week that passes, and some will be gone.

**From Week 1, keep a running file** (`story_notes.md`, in this folder or anywhere):
- Anything that broke and how it got fixed
- Any number you saw — before/after, volumes, costs, durations
- Any disagreement, escalation, or decision you influenced
- Anything you taught someone or documented

Ten minutes a week. By Week 10 you'll have a mine instead of a memory test.

---

## Your source material

Four distinct project sources, which is enough for 8–10 non-overlapping stories:

| Source | What's in it | Story types it yields |
|---|---|---|
| **BUPA Region Migration** (current, from 2026-07) | Azure/Databricks BDP4 region flip ASE→AE, Deep Clone DR, Immuta bypass. Live, complex, cross-team | Ambiguity, technical depth, risk management, stakeholder coordination |
| **Apollo / LRC production work** | Real incidents and hard-won lessons already documented | Failure/recovery, debugging under pressure, ownership |
| **Novartis SDP client round** | Cleared technically ("good" feedback), lost on a BGV/experience-verification staffing call | Resilience, things outside your control, handling rejection |
| **PeopleSoft / BigQuery migration** | Platform migration work | Scale, migration risk, legacy constraints |
| **JARVIS** (personal, 15 months) | Self-directed multi-stage system build — memory layer, agent framework, multi-model orchestration | Initiative, self-teaching, long-horizon persistence, technical curiosity |

**On JARVIS as interview material:** use it deliberately, not as a default. It's excellent evidence for *initiative*, *self-directed learning*, and *technical ambition* — Googliness and growth-mindset territory. It is weak evidence for *collaboration*, *conflict*, or *delivering under organizational constraint*, since it's a solo project. Keep it to one or two stories, and never let it crowd out the professional ones — a loop where most stories are personal projects reads as thin professional experience.

---

## Phase 1 (Weeks 10–11) — Build the Story Bank

**What you'll learn**

**STAR, done properly:**
- **Situation** (~15%) — enough context to make the stakes legible. Two sentences, not five. Candidates burn half their answer here
- **Task** (~10%) — what *you specifically* were responsible for. Not the team's goal — yours
- **Action** (~50%) — the bulk. What you did, what you considered, what you rejected and why. **First person singular.** "I" not "we"
- **Result** (~25%) — the outcome, **with a number**, plus what you learned or changed afterward

**The "I" vs "we" discipline:** *"Did you propose a solution or implement it?"* is a named red flag. Interviewers listen specifically for candidates hiding behind "we." Say "we" for genuine team context, then immediately narrow: *"the team decided X; my piece was Y, and I made the call to Z."* Being explicit about a *small* scope honestly is far stronger than an implied large scope that collapses under one follow-up.

**The 10 stories to build.** Each must be genuinely distinct — a different project, or the same project from a materially different angle:

1. **A project you owned end to end** — scope, decisions, outcome
2. **A failure or a project going badly, and how you took ownership** *(Google asks this by name)*
3. **A conflict with a PM or stakeholder** *(Google asks this by name)*
4. **A technical disagreement with a senior engineer** — and how it resolved, including if you were wrong
5. **Working under ambiguity** — unclear requirements, no precedent
6. **A hard debugging session** — a production incident, the diagnosis path
7. **Missing a deadline or making a mistake** — what it cost, what changed after
8. **Teaching, mentoring, or onboarding someone** *(the hiring-manager round asks this)*
9. **Influencing a decision without authority** — convincing others when you couldn't just decide
10. **Learning something hard, fast** — the growth-mindset story

**Why it matters**
Eight to ten distinct stories is the direct, mechanical fix for the most-cited red flag. In a 6-round loop with 3–4 behavioral questions per round, you'll be asked for 12–20 stories. With three in the bank, you repeat — visibly, and interviewers compare notes.

**Deliverable**
`story_bank.md` in this folder: all 10 stories written in STAR format, 200–300 words each. Then a **coverage matrix** — stories as rows, the prompt list from Phase 2 as columns, marking which stories can answer which prompts. Any prompt with zero coverage is a gap to fill; any story covering everything is probably too vague.

**Topics to ask about** *(paste any into chat and I'll explain)*
- "Here's my story draft — grade it as a Bar Raiser would" *(paste it)*
- "How much Situation is too much?"
- "Help me find a conflict story — I don't think I have one" *(you do; this is a framing problem)*
- "Is this story too small to use?"
- "How do I tell a failure story without looking incompetent?"

---

## Phase 2 (Weeks 11–13) — Metrics, Scope Honesty, and the Prompt Map

**What you'll learn**

**Metrics discipline — the highest-stakes item in this roadmap.**

Two separate named red flags converge here: *missing metric/outcome* and *talking about fake numbers*. The second is the dangerous one. Interviewers probe numbers — "how did you measure that?", "what was it before?", "how did you attribute the improvement?" — and an invented figure collapses in two questions. It doesn't read as exaggeration; it reads as dishonesty, and it ends the loop.

**Every story needs at least one real, defensible number.** Go find them:
- Pipeline runtime before and after — job history, cluster logs
- Data volume — row counts, GB processed, table sizes
- Cost — cluster spend, query cost, storage cost before and after
- Incident duration — first alert to resolution, from ticket timestamps
- Frequency — "this failed twice a week before, zero since"
- Scope — number of tables, pipelines, downstream consumers, users affected

**If a number genuinely doesn't exist, say so and give a bounded qualitative statement instead:** *"I didn't have a formal baseline, but the job had been failing roughly weekly and hasn't failed since — I can walk you through the fix."* That is a strong answer. An invented "improved performance by 40%" is a fatal one.

**Impact framing:** *"fails to provide the overall impact of the project"* is a named red flag. Every story needs one sentence on **why the business cared**. Not "I optimized a pipeline" — "the finance team's month-end close depended on this table landing by 6am; it was landing at 11am."

**Specificity:** *"unable to give specific information"* is another. Vague answers read as not-really-having-done-it. Name the technologies, the volumes, the exact failure. You have the detail — the risk is over-summarizing out of a sense that detail is boring. It isn't; it's the evidence.

**The prompt map.** Rehearse against the standard set:

*Ownership & impact* — biggest achievement; a project you owned end to end; going beyond your role
*Failure & recovery* — a failure; a mistake and what you learned; a missed deadline; something you'd do differently
*Conflict & influence* — disagreement with a manager or PM; convincing someone without authority; receiving hard feedback
*Ambiguity & judgment* — unclear requirements; a decision with incomplete information; competing priorities
*Collaboration & mentoring* — helping a struggling teammate; onboarding someone; cross-team work
*Growth* — learning something hard fast; a skill you deliberately built; feedback that changed you

**Why it matters**
This phase is where an existing story bank becomes *credible*. Stories without numbers are anecdotes; stories with real numbers are evidence.

**Deliverable**
Go through each of the 10 stories and attach at least one real, sourced number — **sourced meaning you can name where you found it**. Mark any story where you couldn't find one and rewrite its Result as a bounded qualitative statement. Add the one-sentence business-impact line to every story. Then fill any zero-coverage cells in the prompt matrix.

**Topics to ask about**
- "I can't find a number for this story — help me find a defensible alternative"
- "Is this metric strong enough or does it sound made up?"
- "How do I attribute an improvement when several things changed at once?"
- "Rewrite this Result section to lead with impact"
- "Give me a prompt from the map and grade my answer"

---

## Phase 3 (Weeks 13–15) — Googliness, Growth Mindset, and Culture Fit

**What you'll learn**

**What "Googliness" actually means** (Google names it; the others test the same things differently):
- **Comfort with ambiguity** — you act without complete information and adjust
- **Bias to action** — you did something, not just identified the problem
- **Intellectual humility** — you can say "I was wrong," and describe changing your mind on evidence
- **Collaboration** — you make others better and give credit accurately
- **User focus** — you connect technical work back to who it serves
- **Doing the right thing** — you raised the uncomfortable issue

**Humility, specifically.** The Google framing names humility alongside STAR and growth mindset. This is where strong engineers over-correct into either false modesty ("it was really a team effort" — which erases your contribution and triggers the propose-or-implement flag) or defensiveness about mistakes. The calibrated version: state your contribution precisely, credit others precisely, and describe mistakes without either minimizing or flagellating.

**Growth mindset** (weighted heavily at Microsoft, and present in every loop): frame ability as developed rather than fixed. The story to have ready: something you were bad at, what you deliberately did, and where you are now. **Your DSA track is a live example** — starting from zero, structured practice, measurable progress. So is teaching yourself the JARVIS stack across 15 months. Both are genuine, current, and verifiable, which beats a polished story from three years ago.

**"Why are you leaving?"** — you will be asked, at least twice.

The honest driver is work-life balance at a services company. That's a legitimate reason and a common one. But delivered flatly it can read as "will leave again when things get hard." **Reframe toward what you're moving *toward*, without lying about what you're moving from:**

> *"I've had good technical growth at Celebal — real production ownership across several clients. What I want next is depth: owning one platform over years instead of rotating between client engagements, and seeing the long-term consequences of my own design decisions. That's structurally what a product company offers and a services company can't."*

True, positive, and specific. **Never criticize Celebal, clients, or managers** — it's the fastest way to be read as a future problem.

**Questions you ask them.** Graded, and also genuinely useful to you given the team-dependent WLB finding:
- "What does on-call look like for this team?"
- "How many hours does the team typically work in a normal week? During a crunch?"
- "Has this team been through a reorg or layoffs recently?"
- "What does the first 90 days look like?"
- "How are technical decisions made — who owns architecture?"
- "What's the biggest challenge this team is facing?"

The first three are the ones that matter for the reason this switch exists. Ask them of your *future teammates* — the engineers on your loop — not the recruiter. Company brand tells you almost nothing; the team tells you everything.

**Why it matters**
Culture rounds are pass/fail, and the Bar Raiser has veto power. A technically excellent candidate who reads as arrogant, blame-shifting, or fixed-mindset gets rejected, and never finds out why.

**Deliverable**
Write and rehearse: the "why are you leaving" answer (under 60 seconds), a genuine intellectual-humility story where you were wrong, a growth-mindset story using the DSA track or JARVIS, and your question list per round type. Record all four and play them back.

**Topics to ask about**
- "Grade my 'why are you leaving' answer" *(paste it)*
- "How do I show humility without underselling my contribution?"
- "What's a good intellectual-humility story that doesn't make me look weak?"
- "What questions should I ask to detect a bad-WLB team before I accept?"
- "How do I answer 'what's your biggest weakness' without a cliché?"

---

## Phase 4 (Weeks 15–16) — Bar Raiser, Hiring Manager, and Mock Rounds

**What you'll learn**

**The Bar Raiser round.** An interviewer outside the hiring team whose job is to protect the company-wide bar — often with veto power regardless of how other rounds went. Tested: **strategic alignment and big-picture reasoning**; success factor: **depth plus context plus composure**.

What that means concretely:
- **Zoom out unprompted.** Don't just answer "how did you build it" — answer "why did this matter to the business, and what would you do differently at 10× the scale?"
- **Composure under pushback.** They will challenge a correct answer to see whether you fold or hold. The right response is neither capitulation nor defensiveness: *"That's a fair concern — here's why I still think X, but you're right that Y would change it."*
- **Consistency.** They've read the other interviewers' notes. Your stories must not contradict each other. A story that grew between rounds is a flag.
- **Depth on demand.** They'll pick one thing and go three levels deeper than the other rounds did. Know your own projects to the bottom.

**The hiring-manager round** — project deep dive, onboarding a junior, metrics:
- **Project deep dive:** your most substantial project, at whatever depth they want. Architecture, your specific decisions, what went wrong, what you'd change. They're assessing whether you can operate at the level they need on *day one*
- **"How would you onboard a junior?"** — asked by name. Tests whether you think about the team, not just your tickets. Have a real answer: what you'd have them do in week one, how you'd pair, what documentation you'd point them at, how you'd calibrate their first independent task. If you've actually done this, tell that story; if not, describe what you wished someone had done for you
- **Metrics:** how you measure your own work's success. Ties back to Phase 2's discipline

**Mock protocol for the final two weeks:**
- Full behavioral round: 4 prompts back to back, 45 minutes, recorded, no notes
- Play back and grade against the red-flag list — repeated stories, "we" instead of "I", missing metrics, missing impact, vagueness
- Bar Raiser simulation: pick one story and have someone (or me) push back three levels deep
- The consistency check: read all 10 stories in one sitting and confirm no two contradict

**Why it matters**
These two rounds are where preparation either holds or visibly cracks. They're also the rounds most candidates don't prepare for at all, because they're less concrete than "learn SQL windows."

**Deliverable**
Two recorded full mock rounds on separate days, graded against the red-flag list. Plus a written project-deep-dive outline for your strongest project (probably BUPA — most recent, most complex) that survives three levels of "why did you do it that way?"

**Topics to ask about**
- "Run a Bar Raiser round on me — push back hard" *(then paste your answers)*
- "Give me 4 behavioral prompts and grade my answers against the red flags"
- "Push three levels deep on my BUPA project"
- "How do I answer 'how would you onboard a junior' if I haven't done it?"
- "Grade my story bank for consistency and overlap" *(paste the bank)*

---

## Resources (canonical only — no list bloat)

| Resource | Use for |
|---|---|
| Your Jira, PRs, Slack, dashboards, pipeline logs | **The most important resource here.** This is where the real numbers are. Mine it early — it decays |
| `Data_Engineering_Lessons.md` (your existing production-incident archive) | Already-written incidents — raw material for failure, debugging, and ownership stories |
| Google's official "how we hire" pages | The public framing of Googliness and the hiring-committee process |
| Amazon's leadership principles | Not a target company, but the most explicit public articulation of behavioral criteria; useful as a rehearsal checklist |
| A recording device | Non-negotiable. You cannot self-assess delivery without playback |

**Deliberately excluded:** behavioral-answer template libraries and scripted "best answers." Rehearsed-sounding answers are worse than rough ones, and interviewers at this tier recognize canned material immediately.

---

## Checkpoints (self-assess at each)

- **Week 1 (parallel):** `story_notes.md` created. Ten minutes a week logging incidents, numbers, and decisions.
- **End of Week 11:** All 10 stories written in STAR. Coverage matrix built. No prompt category has zero coverage.
- **End of Week 13:** Every story carries a **real, sourced** number or an explicit bounded qualitative statement. Every story has a business-impact sentence. Zero invented figures — verify this deliberately, story by story.
- **End of Week 15:** "Why are you leaving" delivered in under 60 seconds, positive and specific, recorded and played back. Humility and growth-mindset stories rehearsed.
- **End of Week 16:** Two full mock rounds recorded. Answer any prompt from the map with a distinct story, no repeats across 12 consecutive questions. Survive a three-level Bar Raiser pushback without folding or getting defensive.

---

## How to use this file

1. **Start `story_notes.md` this week**, even though the roadmap runs in Week 10. The numbers are the hard part and they decay fastest.
2. **Ten stories, not three.** This is the mechanical fix for the most-cited behavioral red flag, and it only works if you actually build all ten.
3. **Never invent a number.** Interviewers probe. A real small number beats an invented large one every time, and getting caught ends the loop.
4. **Record yourself.** Reading a story and delivering it are different skills, and only playback shows the gap.
5. Paste any story into chat and ask me to grade it as a Bar Raiser would — that's cheaper than finding the weakness live.
6. Say "I" when it was you and "we" when it was the team, then immediately narrow to your piece. Vagueness about scope is a named red flag and interviewers listen for it specifically.
