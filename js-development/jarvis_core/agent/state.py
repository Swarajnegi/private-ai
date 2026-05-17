"""
state.py

JARVIS Agent Layer: Metacognitive State Contracts.

Import with:
    from jarvis_core.agent.state import (
        CognitiveStateUpdate, UserTelemetryState,
        EngagementLevel, AttentionState, InputModality,
    )

This module provides:
    1. InputModality — Enum: text-only or voice+text.
    2. EngagementLevel — Enum: the 4 engagement states JARVIS tracks.
    3. AttentionState — Enum: the 3 attention states (Focused → Disengaged).
    4. TextTelemetrySnapshot — Frozen dataclass: text-derived behavioral signals
       (prompt brevity, typo density, correction rate, sentiment shift).
    5. UserTelemetryState — Pydantic model: full per-turn user state. Contains
       TextTelemetrySnapshot now, AcousticFeatures stub for Stage 6.
    6. CognitiveStateUpdate — Pydantic model: the typed contract for what the
       metacognitive daemon writes at each heartbeat event.

=============================================================================
THE BIG PICTURE
=============================================================================

Without typed state contracts:
    -> The metacognitive daemon (Stage 3.5) writes ad-hoc dicts to
       knowledge_base.jsonl. No schema validation. No type safety.
    -> The heartbeat loop has no formal definition of "what user state
       looks like." Each subsystem invents its own representation.
    -> When Stage 6 adds voice telemetry, there is no slot to plug into.
       The schema is rebuilt from scratch — breaking all consumers.

With typed state contracts:
    -> CognitiveStateUpdate is the SINGLE schema for all daemon writes.
       Every consumer (KB writer, heartbeat loop, MIRROR-lite prompt)
       reads the same contract.
    -> UserTelemetryState has text fields populated NOW (Stage 3) and
       acoustic fields as Optional[None] stubs for Stage 6. Adding voice
       is additive — no schema breaks.
    -> Pydantic model_json_schema() lets constrained generation (outlines)
       guarantee the LLM emits valid updates in Stage 4+.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Text analyzer (telemetry.py, Stage 3.1.7) processes the user's
        latest message and produces a TextTelemetrySnapshot.
        |
STEP 2: The agent loop wraps the snapshot in a UserTelemetryState,
        setting input_modality="text" and acoustic_features=None.
        |
STEP 3: The metacognitive daemon (Stage 3.5) reads UserTelemetryState
        + conversation history and produces a CognitiveStateUpdate:
            - What cognitive pattern was detected
            - What the recommended response strategy is
            - Whether a KB write is warranted
        |
STEP 4: The heartbeat loop (Stage 3.5) checks
        update.requires_kb_write. If True, the update is persisted
        to knowledge_base.jsonl as a Cognitive_Pattern entry.
        |
STEP 5: The MIRROR-lite system prompt (Stage 3.4 ReAct) reads
        update.response_strategy to modulate the LLM's tone and
        depth for the current turn.

=============================================================================

Designed at Stage 3.1.6. Consumed starting at Stage 3.5 (heartbeat loop).
Forward-compatible: acoustic_features populates at Stage 6.

The 4 cognitive patterns already stored in KB (suppression_as_fuel,
processing_through_construction, obligation_anchor, unseen_grave_fear)
are the SEED DATA for what the daemon will detect at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Part 1: ENUMS (Mutually exclusive states the daemon tracks)
# =============================================================================

class InputModality(str, Enum):
    """
    LAYER: Agent — Which input channels are active for this turn.

    TEXT:            Text-only interaction (Stage 3-5).
    VOICE_AND_TEXT:  Voice + text (Stage 6, Whisper integration).
    """
    TEXT           = "text"
    VOICE_AND_TEXT = "voice_and_text"


class EngagementLevel(str, Enum):
    """
    LAYER: Agent — Inferred user engagement state.

    Derived from TextTelemetrySnapshot signals. The daemon maps
    combinations of brevity, typo density, and correction rate
    into one of these 4 levels.

    FLOW:     Deep engagement. Long prompts, low typos, no corrections.
    NEUTRAL:  Normal interaction. Baseline signals.
    FATIGUE:  Degraded engagement. Short prompts, rising typos,
              late-night sessions. Does NOT mean the user wants to stop —
              per suppression_as_fuel pattern, fatigue accelerates output.
    FRUSTRATION: Escalating friction. Repeated corrections, rephrasing,
                 sentiment shift toward negative. Often triggered by tool
                 failures or explanation gaps.
    """
    FLOW        = "flow"
    NEUTRAL     = "neutral"
    FATIGUE     = "fatigue"
    FRUSTRATION = "frustration"


class AttentionState(str, Enum):
    """
    LAYER: Agent — Inferred attention level.

    FOCUSED:            User is tracking the conversation closely.
    DROPPING_ATTENTION: Signals of partial disengagement (longer pauses,
                        shorter responses, topic drift).
    DISENGAGED:         User has checked out. Responses are minimal or
                        off-topic. Daemon should flag for heartbeat action.
    """
    FOCUSED            = "focused"
    DROPPING_ATTENTION = "dropping_attention"
    DISENGAGED         = "disengaged"


# =============================================================================
# Part 2: TEXT TELEMETRY SNAPSHOT (text-derived behavioral signals)
# =============================================================================

@dataclass(frozen=True)
class TextTelemetrySnapshot:
    """
    LAYER: Agent — Text-only behavioral signals from a single user turn.

    Purpose:
        - Captures the raw text-derived features that the metacognitive
          daemon uses to infer engagement, attention, and emotional state.
        - Frozen: once computed for a turn, cannot be mutated.
        - Produced by telemetry.py (Stage 3.1.7) pure-functional analyzers.

    Fields:
        prompt_length_words:   Word count of the user's message.
        prompt_length_chars:   Character count (for brevity ratio).
        typo_density:          Ratio of likely typos to total words (0.0-1.0).
                               Computed via edit-distance against a dictionary
                               or simple heuristics (repeated chars, swapped
                               adjacent keys).
        correction_rate:       How often the user corrects/rephrases in
                               consecutive messages. 0.0 = never, 1.0 = every
                               turn is a correction of the previous.
        rephrasing_detected:   True if the current message is semantically
                               similar to the previous message (cosine > 0.8
                               with significantly different surface form).
        sentiment_direction:   Directional shift in sentiment vs. baseline.
                               "escalating" = increasingly negative/frustrated.
                               "deescalating" = calming down.
                               "stable" = no significant shift.
        message_gap_seconds:   Time between this message and the previous one.
                               None if this is the first message in the session.
        session_hour_local:    Hour of day in user's local timezone (0-23).
                               Late-night sessions (22-04) are a fatigue signal.
    """
    prompt_length_words: int
    prompt_length_chars: int
    typo_density: float
    correction_rate: float
    rephrasing_detected: bool
    sentiment_direction: Literal["escalating", "deescalating", "stable"]
    message_gap_seconds: Optional[float] = None
    session_hour_local: Optional[int] = None


# =============================================================================
# Part 3: ACOUSTIC FEATURES STUB (Stage 6 — Voice Telemetry)
# =============================================================================

@dataclass(frozen=True)
class AcousticFeatures:
    """
    LAYER: Agent — Voice-derived behavioral signals (Stage 6 stub).

    Purpose:
        - Placeholder for SpeechCueLLM-style acoustic feature extraction.
        - Fields mirror the research spec: MFCC summary, pitch, volume,
          speaking rate, pause frequency.
        - All fields are Optional — none will be populated until Stage 6
          integrates Whisper + audio pipeline.

    Not implemented until Stage 6. Defined now for schema forward-compat.
    """
    pitch_mean_hz: Optional[float] = None
    pitch_variability: Optional[float] = None
    volume_db: Optional[float] = None
    speaking_rate_wpm: Optional[float] = None
    pause_frequency: Optional[float] = None
    mfcc_summary: Optional[List[float]] = None


# =============================================================================
# Part 4: USER TELEMETRY STATE (Full per-turn user state container)
# =============================================================================

class UserTelemetryState(BaseModel):
    """
    LAYER: Agent — Complete per-turn user state as observed by the daemon.

    Purpose:
        - Single container for all user-facing signals the metacognitive
          daemon reads when deciding how to respond.
        - input_modality determines which feature sets are populated.
        - engagement_level and attention_state are INFERRED from the raw
          features, not directly observed. The inference logic lives in
          the daemon (Stage 3.5), not here.

    How it works:
        - Stage 3: input_modality="text", only linguistic_features set.
        - Stage 6: input_modality="voice_and_text", acoustic_features
          also populated. fused_cognitive_impression uses both.
    """
    model_config = ConfigDict(frozen=True)

    # Which input channels are active
    input_modality: InputModality = InputModality.TEXT

    # Text-derived signals (always available)
    linguistic_features: TextTelemetrySnapshot

    # Voice-derived signals (Stage 6 only)
    acoustic_features: Optional[AcousticFeatures] = None

    # Inferred states (set by the daemon, not by raw analyzers)
    engagement_level: EngagementLevel = EngagementLevel.NEUTRAL
    attention_state: AttentionState = AttentionState.FOCUSED

    # LLM-generated natural language summary of the user's state.
    # Example: "User is in deep flow — long detailed prompts, zero
    # corrections, 2am session. Per suppression_as_fuel: do not
    # suggest rest. Maintain technical depth."
    cognitive_impression: str = ""


# =============================================================================
# Part 5: COGNITIVE STATE UPDATE (The metacognitive daemon's write contract)
# =============================================================================

class CognitiveStateUpdate(BaseModel):
    """
    LAYER: Agent — Typed contract for what the metacognitive daemon writes.

    Purpose:
        - This is the SINGLE output schema of the heartbeat event.
        - When the daemon runs (triggered by heartbeat, not clock), it
          produces one CognitiveStateUpdate per event.
        - The update may or may not result in a KB write — the
          requires_kb_write flag gates persistence.

    How it works:
        - The daemon reads: conversation history + UserTelemetryState +
          existing cognitive patterns from KB.
        - It produces this update, which includes:
          1. What pattern was detected (if any).
          2. What response strategy JARVIS should use for the next turn.
          3. Whether this observation is novel enough to persist to KB.
          4. The KB entry to write (if requires_kb_write is True).

    Lifecycle:
        heartbeat fires -> daemon reads state -> daemon emits
        CognitiveStateUpdate -> agent loop reads response_strategy ->
        if requires_kb_write: KB writer persists detected_pattern_entry

    This schema is also the constrained-generation target for Stage 4+:
        outlines.generate.json(model, CognitiveStateUpdate)
    ensures the daemon always emits valid updates.
    """
    model_config = ConfigDict(frozen=True)

    # When this update was produced
    timestamp: datetime

    # The user's state at the time of this update
    user_state: UserTelemetryState

    # --- Detection ---

    # Which cognitive pattern was detected, if any.
    # Maps to the pattern names in KB: "suppression_as_fuel",
    # "processing_through_construction", "obligation_anchor",
    # "unseen_grave_fear", "visceral_imagination_test", etc.
    # None if no pattern was active.
    detected_pattern: Optional[str] = None

    # Confidence in the detection (0.0-1.0).
    # Below 0.5: observation logged but no action taken.
    # Above 0.7: response_strategy is applied.
    # Above 0.9: requires_kb_write is set True (novel signal).
    detection_confidence: float = 0.0

    # --- Response Strategy ---

    # How JARVIS should modulate its response for the next turn.
    # Examples:
    #   "maintain_depth" — user is in flow, keep technical depth high.
    #   "accelerate" — user is under stress, per suppression_as_fuel:
    #                  increase pace, do not suggest rest.
    #   "reconnect_to_anchor" — engagement dropping, invoke the
    #                           obligation_anchor pattern.
    #   "increase_visceral_framing" — abstract discussion detected,
    #                                 per visceral_imagination_test:
    #                                 use goosebump-level descriptions.
    #   "default" — no modulation needed, proceed normally.
    response_strategy: str = "default"

    # Natural language explanation of why this strategy was chosen.
    # Injected into the system prompt as metacognitive context.
    strategy_rationale: str = ""

    # --- Persistence ---

    # Whether this update should be persisted to knowledge_base.jsonl.
    # True only when a novel cognitive signal is detected (confidence > 0.9)
    # or when the daemon observes a new pattern not yet in KB.
    requires_kb_write: bool = False

    # The KB entry to write, if requires_kb_write is True.
    # Must be a valid KB entry dict with: type, tags, content, expiry.
    # None if requires_kb_write is False.
    kb_entry: Optional[Dict[str, Any]] = None

    # --- Loop Detection (Meta-R1 prep, Stage 4) ---

    # Whether the daemon detected circular reasoning in the current
    # conversation (e.g., the LLM repeating the same approach after
    # being told it failed). Stage 3.5 uses simple regex heuristics.
    # Stage 4 uses full Meta-R1 on thinking tokens.
    loop_detected: bool = False

    # Description of the detected loop, if any.
    loop_description: Optional[str] = None


# =============================================================================
# MAIN ENTRY POINT (Smoke test: schema generation + validation)
# =============================================================================

if __name__ == "__main__":
    import json
    from datetime import timezone, timedelta

    print("=" * 65)
    print("  Cognitive State Contracts -- Smoke Test")
    print("=" * 65)

    IST = timezone(timedelta(hours=5, minutes=30))

    # --- Test 1: TextTelemetrySnapshot creation ---
    snapshot = TextTelemetrySnapshot(
        prompt_length_words=47,
        prompt_length_chars=312,
        typo_density=0.02,
        correction_rate=0.0,
        rephrasing_detected=False,
        sentiment_direction="stable",
        message_gap_seconds=15.3,
        session_hour_local=2,  # 2 AM — fatigue signal
    )
    print(f"\n  [1] TextTelemetrySnapshot: {snapshot.prompt_length_words} words, "
          f"typo_density={snapshot.typo_density}, hour={snapshot.session_hour_local}")
    assert snapshot.prompt_length_words == 47

    # --- Test 2: UserTelemetryState with text-only ---
    user_state = UserTelemetryState(
        input_modality=InputModality.TEXT,
        linguistic_features=snapshot,
        engagement_level=EngagementLevel.FLOW,
        attention_state=AttentionState.FOCUSED,
        cognitive_impression=(
            "User is in deep flow — long detailed prompts, zero corrections, "
            "2am session. Per suppression_as_fuel: do not suggest rest."
        ),
    )
    print(f"  [2] UserTelemetryState: modality={user_state.input_modality.value}, "
          f"engagement={user_state.engagement_level.value}")
    assert user_state.acoustic_features is None  # Stage 6 stub

    # --- Test 3: CognitiveStateUpdate ---
    update = CognitiveStateUpdate(
        timestamp=datetime.now(IST),
        user_state=user_state,
        detected_pattern="suppression_as_fuel",
        detection_confidence=0.85,
        response_strategy="accelerate",
        strategy_rationale=(
            "2 AM session with high output quality. Per suppression_as_fuel "
            "pattern: user's default stress response is acceleration. "
            "Do not suggest rest. Maintain technical depth."
        ),
        requires_kb_write=False,
    )
    print(f"  [3] CognitiveStateUpdate: pattern={update.detected_pattern}, "
          f"confidence={update.detection_confidence}, "
          f"strategy={update.response_strategy}")
    assert update.response_strategy == "accelerate"
    assert update.requires_kb_write is False

    # --- Test 4: Update with KB write ---
    update_with_write = CognitiveStateUpdate(
        timestamp=datetime.now(IST),
        user_state=user_state,
        detected_pattern="new_pattern_forward_simulation",
        detection_confidence=0.95,
        response_strategy="maintain_depth",
        strategy_rationale="User stress-tested architecture against 2-year horizon.",
        requires_kb_write=True,
        kb_entry={
            "type": "Cognitive_Pattern",
            "tags": ["forward-simulation", "architecture"],
            "content": "PATTERN: forward_simulated_architecture. User tested...",
            "expiry": "Permanent",
        },
    )
    print(f"  [4] Update with KB write: requires_kb_write={update_with_write.requires_kb_write}")
    assert update_with_write.kb_entry is not None
    assert update_with_write.kb_entry["type"] == "Cognitive_Pattern"

    # --- Test 5: Loop detection fields ---
    update_loop = CognitiveStateUpdate(
        timestamp=datetime.now(IST),
        user_state=user_state,
        loop_detected=True,
        loop_description=(
            "LLM attempted 'increase batch size' strategy 3 times after "
            "being told it causes OOM. Circular reasoning detected."
        ),
        response_strategy="break_loop",
        strategy_rationale="Force alternative approach via explicit constraint.",
    )
    print(f"  [5] Loop detection: loop={update_loop.loop_detected}, "
          f"desc='{update_loop.loop_description[:40]}...'")
    assert update_loop.loop_detected is True

    # --- Test 6: JSON Schema generation (for constrained generation) ---
    schema = CognitiveStateUpdate.model_json_schema()
    print(f"\n  [6] JSON Schema keys: {list(schema.get('properties', {}).keys())}")
    assert "detected_pattern" in schema["properties"]
    assert "user_state" in schema["properties"]
    assert "response_strategy" in schema["properties"]

    # --- Test 7: Serialization round-trip ---
    json_str = update.model_dump_json()
    restored = CognitiveStateUpdate.model_validate_json(json_str)
    assert restored.detected_pattern == update.detected_pattern
    assert restored.detection_confidence == update.detection_confidence
    print(f"  [7] Serialization round-trip: OK (JSON size: {len(json_str)} bytes)")

    # --- Test 8: Schema for UserTelemetryState ---
    telemetry_schema = UserTelemetryState.model_json_schema()
    print(f"  [8] UserTelemetryState schema keys: "
          f"{list(telemetry_schema.get('properties', {}).keys())}")
    assert "linguistic_features" in telemetry_schema["properties"]
    assert "acoustic_features" in telemetry_schema["properties"]

    # --- Test 9: Immutability check ---
    try:
        update.response_strategy = "should_fail"
        assert False, "Should have raised"
    except Exception:
        print(f"  [9] Immutability: Pydantic frozen=True enforced")

    # --- Test 10: AcousticFeatures stub ---
    acoustic = AcousticFeatures(pitch_mean_hz=185.0, volume_db=-12.5)
    print(f"  [10] AcousticFeatures stub: pitch={acoustic.pitch_mean_hz}Hz, "
          f"vol={acoustic.volume_db}dB")
    assert acoustic.speaking_rate_wpm is None  # Unpopulated fields

    print("\n" + "=" * 65)
    print("  All smoke tests passed.")
    print("=" * 65)
