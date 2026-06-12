"""
brain/__init__.py

JARVIS Brain Layer — model-facing strategy (Stage 4: Orchestration).

The layer boundary, settled at Stage 4 entry (Decision L325):

    agent/   = the EXECUTION RUNTIME — how one reasoning loop runs (ReAct,
               tools, planning, memory manager, permissions). Frozen Stage 3.
    brain/   = MODEL-FACING STRATEGY — which brain(s) to use, how to speak
               each one's dialect, what context to inhale at boot, how to
               judge and merge answers. Built Stage 4.
    memory/  = retrieval (ChromaDB, hybrid, rerank). Stage 2.

(Stage 3 note: the planner and agent loop this docstring once reserved were
built in agent/ and STAY there — brain/ composes the Mind from above, it
never re-homes the runtime.)

Stage 4 organs, as they land:
    context_injector  (4.0.1) — boot inhale: clock/profile/digest/self-state
    roadmap_state     (4.0.2) — next-pending-task from ROADMAP checkboxes
    confidence        (4.0.3) — ConfidenceGate: grounding score + verdict
    boot              (4.0.4) — composition root: assemble_mind()
    orchestrator      (4.0.4) — the spine: inhale -> solve -> gate -> distill
    session_writer    (4.0.5) — end-of-session KB distillation
    model_profiles / protocol / targets / model_pool   (4.1)
    router            (4.2)
    aggregator        (4.4)
"""
