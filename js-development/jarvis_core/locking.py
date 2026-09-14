"""
locking.py — cross-platform advisory locks for JARVIS runtime state.

LAYER: Engineer (runtime persistence)

=============================================================================
THE BIG PICTURE
=============================================================================

JARVIS runs on both POSIX and native Windows. ``fcntl.flock`` is available only
on POSIX, while Windows provides ``msvcrt.locking``. Runtime writers need the
same single-writer guarantee on both systems; silently skipping the lock on
Windows turns concurrent appends into data corruption.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Open a sibling ``.lock`` file rather than locking the payload itself.
        ↓
STEP 2: Acquire its first byte with the native platform primitive.
        ↓
STEP 3: Yield while the caller writes and fsyncs its payload.
        ↓
STEP 4: Release the lock in ``finally``.
=============================================================================
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Serialize local writers for ``path`` with a sibling runtime lock file."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            raise RuntimeError("no supported file-locking primitive on this platform")
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
