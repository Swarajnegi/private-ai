#!/usr/bin/env python3
"""
windows_hearth_watchdog.py — persist the native-Windows hearth without Task Scheduler.

LAYER: Tools (Windows host adapter; the hearth itself remains platform-neutral)

Run with:
    python scripts/windows_hearth_watchdog.py --install
    python scripts/windows_hearth_watchdog.py --status
    python scripts/windows_hearth_watchdog.py --uninstall
    python scripts/windows_hearth_watchdog.py --self-test

=============================================================================
THE BIG PICTURE
=============================================================================

Native Windows has no ``os.fork``, so ``hearth.py --background`` cannot detach.
Task Scheduler is the preferred Windows mechanism, but some managed accounts deny
task creation and even task enumeration. This adapter uses the current user's
Run registry key instead: Windows launches this watchdog directly at logon, and
the watchdog owns a foreground hearth child for as long as the user is logged in.

No privileged service, scheduled task, or machine-wide registry key is touched.

=============================================================================
THE FLOW
=============================================================================

``--install`` writes one HKCU Run value -> Windows starts ``--watchdog`` at logon
    -> watchdog starts native ``hearth.py`` in the foreground, without a window
    -> hearth exits unexpectedly -> watchdog waits briefly and starts it again
    -> user logs out -> Windows ends the per-user process tree
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

try:
    import winreg
except ImportError:  # Allows the self-test to describe the platform requirement clearly.
    winreg = None  # type: ignore[assignment]


# =============================================================================
# PART 1: Paths and the narrow per-user persistence contract
# =============================================================================

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HEARTH = _REPO_ROOT / "scripts" / "hearth.py"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "JARVIS Hearth Watchdog"
_HOST = "127.0.0.1"
_PORT = 8756
_RESTART_DELAY_SECONDS = 10


def _pythonw_path(executable: Optional[Path] = None) -> Path:
    """Prefer pythonw for the Run entry so logon never opens a terminal window."""
    current = executable if executable is not None else Path(sys.executable)
    hidden = current.with_name("pythonw.exe")
    return hidden if hidden.exists() else current


def _hearth_python(executable: Optional[Path] = None) -> Path:
    """The child needs python.exe so ordinary stderr is captured in the watchdog log."""
    current = executable if executable is not None else Path(sys.executable)
    visible = current.with_name("python.exe")
    return visible if visible.exists() else current


def _watchdog_command(root: Optional[Path] = None,
                      executable: Optional[Path] = None) -> str:
    """Return a Windows-safe Run value, without relying on the user's PATH."""
    repo = root if root is not None else _REPO_ROOT
    script = repo / "scripts" / "windows_hearth_watchdog.py"
    return subprocess.list2cmdline([str(_pythonw_path(executable)), str(script), "--watchdog"])


def _require_windows() -> None:
    if os.name != "nt" or winreg is None:
        raise RuntimeError("this adapter is for native Windows only")


def install() -> str:
    """Write exactly one current-user Run value; no administrator permission is needed."""
    _require_windows()
    command = _watchdog_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, command)
    return command


def uninstall() -> bool:
    """Remove only this adapter's current-user Run value."""
    _require_windows()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
        return True
    except FileNotFoundError:
        return False


def installed_command() -> Optional[str]:
    """Read the one Run value this adapter owns, never enumerate unrelated startup items."""
    _require_windows()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, _RUN_VALUE)
        return str(value)
    except FileNotFoundError:
        return None


# =============================================================================
# PART 2: Foreground supervision after Windows has launched the Run entry
# =============================================================================

def _is_listening(host: str = _HOST, port: int = _PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _watchdog_log(root: Optional[Path] = None) -> Path:
    repo = root if root is not None else _REPO_ROOT
    return repo / "jarvis_data" / "hearth_watchdog.log"


def _current_environment() -> dict[str, str]:
    """Merge live HKCU environment variables so hearth picks up env changes without re-logon."""
    env = dict(os.environ)
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        if isinstance(val, str):
                            env[name] = val
                        i += 1
                    except OSError:
                        break
        except OSError:
            pass
    return env


def _spawn_hearth(root: Optional[Path] = None) -> subprocess.Popen[bytes]:
    """Start a normal foreground hearth; Windows owns this watchdog, not a shell."""
    repo = root if root is not None else _REPO_ROOT
    hearth = repo / "scripts" / "hearth.py"
    if not hearth.exists():
        raise FileNotFoundError(f"hearth entry point missing: {hearth}")
    log_path = _watchdog_log(repo)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab", buffering=0)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [str(_hearth_python()), str(hearth)], cwd=repo,
            env=_current_environment(),
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags,
        )
        log.close()  # The child inherited its own handle; do not leak one per restart.
        return process
    except Exception:
        log.close()
        raise


def run_watchdog(restart_delay: int = _RESTART_DELAY_SECONDS) -> int:
    """Stay alive under the Run key and restart a crashed hearth after a bounded pause."""
    if _is_listening():
        return 0  # A manually launched or already-supervised hearth owns the loopback port.

    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while not stopping:
        process = _spawn_hearth()
        while process.poll() is None and not stopping:
            time.sleep(1)
        if stopping and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if stopping:
            return 0
        time.sleep(restart_delay)
    return 0


# =============================================================================
# PART 3: CLI and offline smoke tests
# =============================================================================

def _self_test() -> None:
    """Prove command construction without changing the registry or starting a process."""
    import tempfile

    passed = 0
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "JARVIS with spaces"
        (root / "scripts").mkdir(parents=True)
        script = root / "scripts" / "windows_hearth_watchdog.py"
        script.write_text("# test\n", encoding="utf-8")
        fake_python = root / "python.exe"
        fake_python.write_text("", encoding="utf-8")
        fake_pythonw = root / "pythonw.exe"
        fake_pythonw.write_text("", encoding="utf-8")
        command = _watchdog_command(root, fake_python)
        assert "pythonw.exe" in command and "--watchdog" in command
        assert '"' in command  # The path contains spaces, so quoting is not optional.
        passed += 1
        assert _watchdog_log(root) == root / "jarvis_data" / "hearth_watchdog.log"
        passed += 1
    print(f"windows_hearth_watchdog.py: {passed}/2 passed")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Persist the native Windows JARVIS hearth.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="install the current-user logon entry")
    group.add_argument("--uninstall", action="store_true", help="remove the current-user logon entry")
    group.add_argument("--status", action="store_true", help="show this adapter's Run entry")
    group.add_argument("--watchdog", action="store_true", help=argparse.SUPPRESS)
    group.add_argument("--self-test", action="store_true", help="offline command-construction tests")
    args = parser.parse_args(argv)

    if args.self_test:
        _self_test()
        return 0
    try:
        if args.install:
            print("installed HKCU logon watchdog:")
            print(install())
            return 0
        if args.uninstall:
            print("removed" if uninstall() else "not installed")
            return 0
        if args.status:
            command = installed_command()
            print(command if command else "not installed")
            return 0 if command else 1
        return run_watchdog()
    except RuntimeError as error:
        print(f"windows hearth watchdog: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
