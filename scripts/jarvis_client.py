#!/usr/bin/env python3
"""
jarvis_client.py — talk to the hearth from anywhere. Stdlib only.

LAYER: Tools (thin adapter — the reference client every other surface copies)

Run with:
    python3 scripts/jarvis_client.py "what did I decide about the roster?"
    python3 scripts/jarvis_client.py --no-stream "..."     # one JSON blob
    python3 scripts/jarvis_client.py --health

This is the shape a phone app, a browser PWA, an IDE extension and a shell
alias all take: mint nothing, remember nothing, decide nothing. Send a
question, render the stream. ~150 lines of stdlib, and the ONLY reason it is
Python here is that Python is what this repo already has — the protocol is
plain HTTP + Server-Sent Events, so the Kotlin and JS versions are the same
file in another language.

WHY IT USES urllib AND NOT requests/httpx: neither is guaranteed present, and
a client that cannot run because of a missing dependency is not a client. SSE
over urllib works because urlopen returns a file-like object that yields lines
as they arrive.

WHAT THIS DELIBERATELY CANNOT DO: approve a permission prompt. The hearth
denies them (no human is reachable over a socket) and says so in the output.
Remote approval is the Commitment gate — step 10 — not a client feature.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.config import DATA_ROOT                    # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8756"
TOKEN_PATH = Path(DATA_ROOT) / ".hearth_token"


def read_token(path: Path = TOKEN_PATH) -> str:
    """The bearer token from disk, or "" — the caller decides how to complain."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def is_up(base_url: str = DEFAULT_URL, token: Optional[str] = None,
          timeout: float = 1.5) -> bool:
    """True when a hearth answers /v1/health. Used to decide, never to trust."""
    try:
        req = urllib.request.Request(
            f"{base_url}/v1/health",
            headers={"Authorization": f"Bearer {token or read_token()}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def health(base_url: str, token: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(f"{base_url}/v1/health",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ask_streaming(question: str, base_url: str, token: str,
                  session: Optional[str] = None, new_session: bool = False,
                  timeout: float = 900.0,
                  printer: Any = print) -> Dict[str, Any]:
    """POST /v1/ask as SSE; print each log frame; return the answer payload.

    EXECUTION FLOW:
    1. Send the question with Accept: text/event-stream.
    2. Read the response line by line. `event:` names the frame, `data:` is its
       JSON body; a blank line ends the frame.
    3. Log frames print immediately (this is the progress bar). The `answer`
       frame is returned.

    Returns:
        The final payload dict, or {"ok": False, "error": ...} if the stream
        ended without one — a truncated stream must not look like success.
    """
    body = json.dumps({"question": question, "session": session,
                       "new_session": new_session}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/v1/ask", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Accept": "text/event-stream"})
    final: Dict[str, Any] = {}
    event = ""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not line:
                event = ""
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if event == "log":
                    printer(data.get("line", ""))
                elif event == "answer":
                    final = data
    if not final:
        return {"ok": False, "error": "the stream ended without an answer frame"}
    return final


def ask_buffered(question: str, base_url: str, token: str,
                 session: Optional[str] = None, new_session: bool = False,
                 timeout: float = 900.0) -> Dict[str, Any]:
    """POST /v1/ask and wait for one JSON body. For scripts, not for humans."""
    body = json.dumps({"question": question, "session": session,
                       "new_session": new_session}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/v1/ask", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}


def main() -> int:
    p = argparse.ArgumentParser(description="Ask the running JARVIS hearth.")
    p.add_argument("question", nargs="*", help="the question (quote it)")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--health", action="store_true", help="print hearth status as JSON")
    p.add_argument("--no-stream", action="store_true",
                   help="wait for one JSON body instead of streaming progress")
    p.add_argument("--session", default=None, help="continue a specific session id")
    p.add_argument("--new", action="store_true", help="start a fresh session")
    p.add_argument("--json", action="store_true", help="print the raw payload")
    args = p.parse_args()

    token = read_token()
    if not token:
        print(f"no hearth token at {TOKEN_PATH} — start the hearth first "
              f"(python3 scripts/hearth.py)", file=sys.stderr)
        return 2

    try:
        if args.health:
            print(json.dumps(health(args.url, token), indent=2))
            return 0

        question = " ".join(args.question).strip()
        if not question:
            p.error("a question is required (or --health)")

        payload = (ask_buffered if args.no_stream else ask_streaming)(
            question, args.url, token, session=args.session, new_session=args.new)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        print(f"hearth refused the request: HTTP {e.code} {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"no hearth at {args.url} ({type(e).__name__}: {e})\n"
              f"  start one:  python3 scripts/hearth.py --background",
              file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload.get("ok") else 1

    if not payload.get("ok"):
        print(f"\n  ERROR: {payload.get('error', 'unknown')}", file=sys.stderr)
        return 1
    print(f"\n  JARVIS  : {payload.get('answer', '')}")
    print(f"  confidence: {payload.get('verdict')} "
          f"({payload.get('confidence', 0.0):.2f})")
    for denial in payload.get("denials") or []:
        print(f"  DENIED  : {denial['tool']} — needs a human; re-run it "
              f"through --ask to approve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
