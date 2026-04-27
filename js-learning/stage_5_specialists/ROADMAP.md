# PHASE 5: Domain Specialists Roadmap

> **Master Plan Position:** Phase 5 of 6 → [JARVIS_MASTER_ROADMAP.md](../JARVIS_MASTER_ROADMAP.md)  
> **Goal:** Integrate and fine-tune specialized models for coding, science, and medical domains.  
> **Prerequisites:** Phase 1-4 (Python, Memory, Agents, Orchestration)  
> **Hardware:** Cloud GPU for fine-tuning (RunPod A100 80GB / Vast.ai). See `JARVIS_ENDGAME.md` Section 2.

---

## Overview

| Sub-Phase | Name | Core Concept | Definition of Done |
|-----------|------|--------------|-------------------|
| **5.1** | Fine-Tuning Basics | Adapt models to your domain | Can run LoRA fine-tuning on a 7B model |
| **5.2** | Code Specialist | DeepSeek for software engineering | Code specialist outperforms generalist on coding tasks |
| **5.3** | Science Specialist | Physics, math, astronomy reasoning | Science specialist handles LaTeX and equations |
| **5.4** | Medical Specialist | BioMistral for medical literature | Medical specialist understands clinical terminology |
| **5.5** | Evaluation & Benchmarks | Measure specialist quality | Benchmarks prove specialists > generalist |

---

## Sub-Phase 5.1: Fine-Tuning Basics ⬜

**Goal:** Learn to adapt base models to specific domains.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.1.1 | LoRA/QLoRA Overview | Efficient fine-tuning | `@[/learn] Explain LoRA and QLoRA for fine-tuning.` |
| 5.1.2 | Dataset Preparation | Format data for training | `@[/learn] Explain dataset formats for fine-tuning.` |
| 5.1.3 | Training with Unsloth | Fast local fine-tuning | `/dev Set up Unsloth for local fine-tuning.` |
| 5.1.4 | Merging & Exporting | Merge LoRA weights into base | `/dev Implement LoRA merge and export pipeline.` |

**Practical Exercise:** Fine-tune a 7B model on 1000 examples.

---

## Sub-Phase 5.2: Code Specialist ⬜

**Goal:** Integrate a high-quality code generation specialist.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.2.1 | DeepSeek Coder Overview | State-of-the-art code model | `@[/learn] Explain DeepSeek Coder capabilities.` |
| 5.2.2 | Code Completion Setup | IDE-style suggestions | `/dev Integrate DeepSeek for code completion.` |
| 5.2.3 | Code Understanding | Explain existing code | `/dev Build code explanation pipeline.` |
| 5.2.4 | Code Review & Debug | Find bugs and suggest fixes | `/dev Implement code review specialist.` |

**Practical Exercise:** Code specialist correctly implements a complex algorithm.

---

## Sub-Phase 5.3: Science Specialist ⬜

**Goal:** Build a specialist for physics, math, and astronomy.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.3.1 | Science Domain Challenges | LaTeX, equations, reasoning | `@[/learn] Explain challenges in science LLMs.` |
| 5.3.2 | ArXiv Dataset Curation | Collect physics/math papers | `/dev Build ArXiv paper collection pipeline.` |
| 5.3.3 | Fine-Tuning for Math | Improve equation handling | `/dev Fine-tune for mathematical reasoning.` |
| 5.3.4 | Physics Reasoning Tests | Evaluate on physics problems | `/dev Create physics reasoning benchmark.` |

**Practical Exercise:** Science specialist solves a physics problem with correct equations.

---

## Sub-Phase 5.4: Medical Specialist ⬜

**Goal:** Integrate a specialist for medical literature and protocols.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.4.1 | BioMistral Overview | Medical domain specialist | `@[/learn] Explain BioMistral and medical LLMs.` |
| 5.4.2 | Medical Terminology | Handle clinical language | `@[/learn] Explain medical NLP challenges.` |
| 5.4.3 | PubMed Integration | Retrieve medical literature | `/dev Build PubMed retrieval pipeline.` |
| 5.4.4 | Safety & Disclaimers | Handle medical queries safely | `@[/learn] Explain safety in medical AI.` |

**Practical Exercise:** Medical specialist correctly interprets a drug interaction query.

---

## Sub-Phase 5.5: Evaluation & Benchmarks ⬜

**Goal:** Prove specialists outperform generalists.

| Lesson | Topic | JARVIS Use Case | Command |
|--------|-------|-----------------|---------|
| 5.5.1 | Evaluation Metrics | Accuracy, F1, domain-specific | `@[/learn] Explain LLM evaluation metrics.` |
| 5.5.2 | Benchmark Suites | HumanEval, MATH, MedQA | `@[/learn] Explain standard LLM benchmarks.` |
| 5.5.3 | A/B Testing | Compare specialist vs generalist | `/dev Implement A/B testing for specialists.` |
| 5.5.4 | Continuous Evaluation | Monitor specialist drift | `/dev Build evaluation monitoring pipeline.` |

**Practical Exercise:** Benchmark shows code specialist beats generalist by 20%+ on HumanEval.

---

## Final Boss: The Experts

Have at least 3 working specialists that:
1. [ ] Code specialist: DeepSeek integrated, outperforms generalist
2. [ ] Science specialist: Handles physics/math better than base model
3. [ ] Medical specialist: Understands clinical terminology
4. [ ] Benchmarks prove measurable improvement
5. [ ] Specialists integrate with Phase 4 orchestrator

**When this works, JARVIS has its Experts.**

---

## Progress Tracker

| Sub-Phase | Status | Lessons Complete |
|-----------|--------|------------------|
| 5.1 Fine-Tuning Basics | ⬜ Not Started | 0/4 |
| 5.2 Code Specialist | ⬜ Not Started | 0/4 |
| 5.3 Science Specialist | ⬜ Not Started | 0/4 |
| 5.4 Medical Specialist | ⬜ Not Started | 0/4 |
| 5.5 Evaluation & Benchmarks | ⬜ Not Started | 0/4 |

---

## After This Phase

→ Proceed to **Phase 6: Integration & Interface** → [PHASE_06_ROADMAP.md](../integration-learning/PHASE_06_ROADMAP.md)
