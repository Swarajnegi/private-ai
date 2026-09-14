"""Synchronize JARVIS authoritative JSONL facts with its hosted hearth.

Required machine-local configuration:
    JARVIS_REMOTE_URL=https://jarvis-hearth-production.up.railway.app
    JARVIS_REMOTE_TOKEN=<the hosted hearth bearer token>

Both sides keep append-only local copies. The hosted copy is continuously
reachable; exact-record union makes retries and low-concurrency multi-device
writes safe without turning a JSONL fact log into a binary database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))

from jarvis_core.config import DATA_ROOT
from jarvis_core.locking import exclusive_lock

_LOGS = ("knowledge_base.jsonl", "observation_queue.jsonl", "commitments.jsonl")
_MAX_BATCH_BYTES = 180_000


def _environment_value(name: str) -> str:
    """Read a process setting, with a Windows user-environment fallback.

    The native-Windows hearth is supervised by a long-running watchdog.  A
    value written to HKCU after that watchdog started is not automatically in
    its inherited environment, so relying only on ``os.environ`` silently
    disables sync until the next logon.  This is deliberately limited to the
    two machine-local settings this client owns.
    """
    value = os.environ.get(name, "").strip()
    if value or os.name != "nt":
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            stored, _kind = winreg.QueryValueEx(key, name)
        return str(stored).strip()
    except (ImportError, OSError):
        return ""


def _endpoint() -> tuple[str, str]:
    url = _environment_value("JARVIS_REMOTE_URL").rstrip("/")
    token = _environment_value("JARVIS_REMOTE_TOKEN")
    if not url or not token:
        raise RuntimeError("Set JARVIS_REMOTE_URL and JARVIS_REMOTE_TOKEN; never commit either value.")
    return url, token


def _local_lines(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]
    except FileNotFoundError:
        return []


def _batches(lines: Iterable[str]) -> Iterable[list[str]]:
    batch: list[str] = []
    size = 0
    for line in lines:
        encoded = len(line.encode("utf-8"))
        if batch and size + encoded > _MAX_BATCH_BYTES:
            yield batch
            batch, size = [], 0
        batch.append(line)
        size += encoded
    if batch:
        yield batch


def _request(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _merge_local(path: Path, incoming: list[str]) -> int:
    existing = set(_local_lines(path))
    fresh = [line for line in incoming if line not in existing]
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path):
        existing = set(_local_lines(path))
        fresh = [line for line in incoming if line not in existing]
        if fresh:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("".join(f"{line}\n" for line in fresh))
    return len(fresh)


def sync(dry_run: bool) -> None:
    base, token = _endpoint()
    for name in _LOGS:
        path = Path(DATA_ROOT) / name
        local = _local_lines(path)
        pushed = 0
        if not dry_run:
            for batch in _batches(local):
                pushed += int(_request("POST", f"{base}/v1/memory/{name}", token, {"lines": batch}).get("added", 0))
        remote = _request("GET", f"{base}/v1/memory/{name}", token).get("lines", [])
        pulled = 0 if dry_run else _merge_local(path, remote if isinstance(remote, list) else [])
        print(f"{name}: local={len(local)} pushed={pushed} pulled={pulled} remote={len(remote)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Union-sync JARVIS fact logs with the hosted hearth.")
    parser.add_argument("--dry-run", action="store_true", help="read remote state but write neither side")
    args = parser.parse_args()
    sync(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
