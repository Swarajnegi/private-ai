"""Validate the recorded October 13 baseline without generating new answers.

LAYER: Engineer
THE BIG PICTURE: a baseline documents failures; it does not claim to repair them.
THE FLOW: validate complete reviewed content digests -> reproduce the known error
classification -> report unresolved cases and the unavailable original audio.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "js-development"))
from jarvis_core.specialists.training_review import TrainingReviewGate


def main() -> int:
    baseline = json.loads((ROOT / "jarvis_data/eval/milestone1/baseline.json").read_text(encoding="utf-8"))
    gate = TrainingReviewGate(ROOT)
    for reviewed in baseline["reviewed_sources"]:
        packet = gate.packet(reviewed["identity"])
        if packet["digest"] != reviewed["digest"] or packet["status"] != reviewed["decision"]:
            raise ValueError("baseline source or review changed: " + str(reviewed["identity"]))
    from jarvis_core.agent.errors import classify_error
    from jarvis_core.agent.tool import ToolResult
    case = next(c for c in baseline["cases"] if c["id"] == "B03")
    observed = classify_error(ToolResult(error=case["fixture"]["error"]), attempted_tool_name="file_read")
    print("B03 offline reproduction:", observed.kind.value)
    for case in baseline["cases"]:
        print(f"{case['id']} {case['status']}: {case['failure']}")
    print(f"{len(baseline['reviewed_sources'])} complete source digests verified; six baseline cases retained.")
    print("Unresolved means later repair is required. Original ambiguous audio is unavailable; no transcription score asserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
