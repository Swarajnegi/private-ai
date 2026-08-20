"""
specialists/__init__.py

JARVIS Specialists Layer.

This package owns per-specialist QLoRA adapter tooling — corpus assembly,
training scripts, and (once a real adapter exists) RouteTarget integration.
Stage 5 ships The Engineer first (Decision 2026-05-01, Engineer-first MVP);
the rest of the roster templates the same recipe once it's proven out.

Available modules:
    jarvis_core.specialists.engineer_corpus — assembles The Engineer's
        fine-tuning corpus from jarvis_core/, the KB, chat-history, and the
        DE corpus (Stage 5.2.2)

Not to be confused with jarvis_core.engineer — an unrelated, pre-existing
package (async HTTP I/O for the research-paper ingestion pipeline).
"""
