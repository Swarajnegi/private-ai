"""Bounded Codex transcript discovery, independent of optional plugin caches.

Only pass sessions/ or archived_sessions/ here. A disappearing subtree must
not discard its readable siblings; never traverse symlinks or Windows junctions.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Callable, Iterator, Optional


def rollout_paths(root: Path, on_error: Optional[Callable[[OSError], None]] = None) -> Iterator[Path]:
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    try:
                        path = Path(entry.path)
                        if entry.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(path)
                        elif entry.is_file(follow_symlinks=False) and entry.name.startswith('rollout-') and entry.name.endswith('.jsonl'):
                            yield path
                    except OSError as err:
                        if on_error:
                            on_error(err)
                        else:
                            warnings.warn(f'Codex transcript entry unavailable: {err}', RuntimeWarning)
        except OSError as err:
            # Fresh machines legitimately have no transcript roots. A missing
            # nested directory is a race, not a reason to lose the other files.
            if directory == Path(root) and isinstance(err, FileNotFoundError):
                continue
            if on_error:
                on_error(err)
            else:
                warnings.warn(f'Codex transcript directory unavailable: {err}', RuntimeWarning)


def _self_test() -> int:
    import tempfile
    from unittest.mock import patch
    failures = []
    def check(name, ok):
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
        if not ok: failures.append(name)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sessions = root/'sessions'
        readable = sessions/'good'
        readable.mkdir(parents=True)
        expected = readable/'rollout-fixture.jsonl'
        expected.write_text('{}\n',encoding='utf-8')
        (root/'plugins'/'chrome').mkdir(parents=True)
        bad = sessions/'vanishing'
        bad.mkdir()
        real_scan = os.scandir
        seen, errors = [], []
        def scan(path):
            seen.append(Path(path))
            if Path(path) == bad:
                raise FileNotFoundError('directory vanished during scan')
            return real_scan(path)
        with patch('os.scandir',side_effect=scan):
            found=list(rollout_paths(sessions,errors.append))
        check('missing nested directory preserves sibling transcripts',found == [expected] and len(errors)==1)
        check('plugin cache never visited',all('plugins' not in p.parts for p in seen))
        check('absent transcript root is normal',list(rollout_paths(root/'absent')) == [])
        with patch('os.scandir',side_effect=PermissionError('denied')):
            errors=[]
            check('permission failure is surfaced without crash',list(rollout_paths(sessions,errors.append))==[] and len(errors)==1)
    print(f'{4-len(failures)}/4 passed')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(_self_test())
