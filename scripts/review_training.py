"""Read complete training-review packets or explicitly submit independent verdicts.

LAYER: Engineer
THE BIG PICTURE: quality review is separate from capture, retrieval and PARSE_RULE.
THE FLOW: list/packet reads -> human/independent agent judgment -> locked submission.
No model calls, maintenance execution or conversational tool registration.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "js-development"))
from jarvis_core.specialists.training_review import ReviewError, TrainingReviewGate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--list", action="store_true")
    modes.add_argument("--packet", type=Path, help="JSON identity file; prints complete packet")
    modes.add_argument("--submit", type=Path, help='JSON {"verdicts": [...]} file')
    parser.add_argument("--reviewer", help="actual independent host/model identity")
    parser.add_argument("--status", choices=("approved", "pending", "rejected"))
    parser.add_argument("--session", help="exact session id filter")
    parser.add_argument("--packets", action="store_true", help="list complete packets rather than identities")
    args = parser.parse_args()
    try:
        gate = TrainingReviewGate(args.root)
        if args.submit:
            payload = json.loads(args.submit.read_text(encoding="utf-8"))
            if set(payload) != {"verdicts"}:
                raise ReviewError("submission must contain only verdicts")
            print(json.dumps({"appended": gate.submit(payload["verdicts"], args.reviewer), "counts": gate.counts()}))
        elif args.packet:
            print(json.dumps(gate.packet(json.loads(args.packet.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2))
        else:
            for packet in gate.packets():
                if args.status and packet["status"] != args.status:
                    continue
                if args.session and packet["identity"].get("session_id") != args.session:
                    continue
                print(json.dumps(packet if args.packets else {k: packet[k] for k in ("identity", "digest", "status")}, ensure_ascii=False))
        return 0
    except (ReviewError, OSError, ValueError) as exc:
        print(f"training review refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
