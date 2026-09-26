"""Local, ephemeral voice workers. LAYER: Body (speech adapter).

Each subprocess exits after a request, returning its memory to the OS. The shared
lock prevents STT and TTS competing with each other on the 8 GB personal laptop.
"""
from __future__ import annotations
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import wave
from jarvis_core.config import JARVIS_ROOT

RUNTIME = JARVIS_ROOT / '.runtime' / 'voice'
LOCK = threading.Lock()


def _check_memory() -> None:
    """Reject new workers only when Windows is close to exhausting commit memory."""
    if os.name != 'nt':
        return
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                'total_physical', 'available_physical', 'total_page', 'available_page',
                'total_virtual', 'available_virtual', 'extended_virtual')]

    state = MemoryStatus()
    state.length = ctypes.sizeof(state)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)) and state.available_page < 512 * 1024 * 1024:
        raise RuntimeError('Windows has insufficient free memory for local voice. Close an application and retry.')


def capabilities() -> dict:
    config = RUNTIME / 'config.json'
    try:
        cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        cfg = {}
    stt = all(Path(cfg.get(k, '')).is_file() for k in ('whisper', 'stt_model'))
    tts = all(Path(cfg.get(k, '')).is_file() for k in ('python', 'tts_model'))
    return {'local': True, 'transcription': stt, 'synthesis': tts,
            'busy': LOCK.locked(), 'setup': 'Run scripts/setup_voice.ps1', 'config': cfg}


def process(kind: str, payload: dict) -> dict:
    if kind not in ('transcribe', 'synthesize'):
        raise ValueError('Unknown voice operation.')
    status = capabilities()
    key = 'transcription' if kind == 'transcribe' else 'synthesis'
    if not status[key]:
        raise ValueError('Local voice is not installed. Run scripts/setup_voice.ps1; text chat remains available.')
    if not LOCK.acquire(blocking=False):
        raise RuntimeError('Voice is already processing. Wait for the current operation to finish.')
    try:
        _check_memory()
        cfg = status['config']
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='request-', dir=RUNTIME) as folder:
            location = Path(folder)
            if kind == 'transcribe':
                try:
                    audio = base64.b64decode(payload.get('audio', ''), validate=True)
                    with wave.open(io.BytesIO(audio)) as wav:
                        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
                            raise ValueError('Expected mono 16-bit PCM at 16 kHz.')
                        if not 0 < wav.getnframes() <= 16000 * 120:
                            raise ValueError('Record between a fraction of a second and two minutes.')
                except (wave.Error, EOFError, TypeError) as exc:
                    raise ValueError('Invalid WAV recording.') from exc
                source = location / 'input.wav'; source.write_bytes(audio)
                output = location / 'transcript'
                cmd = [cfg['whisper'], '-m', cfg['stt_model'], '-f', str(source),
                       '-otxt', '-of', str(output), '-l', 'auto', '-t', '4', '-nt']
                result = subprocess.run(cmd, capture_output=True, timeout=180,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode or not output.with_suffix('.txt').exists():
                    raise RuntimeError('Local transcription worker failed. Your recording was not sent online.')
                text = output.with_suffix('.txt').read_text(encoding='utf-8').strip()
                return {'text': text, 'local': True}
            text = payload.get('text', '')
            if not isinstance(text, str) or not text.strip() or len(text) > 6000:
                raise ValueError('Speech requires a nonempty text chunk of at most 6000 characters.')
            output = location / 'reply.wav'
            cmd = [cfg['python'], '-m', 'piper', '-m', cfg['tts_model'], '-f', str(output)]
            result = subprocess.run(cmd, input=text.encode('utf-8'), capture_output=True,
                                    timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or not output.exists():
                raise RuntimeError('Local speech worker failed. The complete text reply remains available.')
            return {'audio': base64.b64encode(output.read_bytes()).decode('ascii'), 'local': True}
    finally:
        LOCK.release()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect local voice or run an offline worker smoke test.')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        from unittest.mock import patch
        with patch(__name__ + '.capabilities', return_value={'transcription': True, 'synthesis': True, 'config': {}}):
            for kind, payload in [('transcribe', {'audio': 'invalid'}), ('synthesize', {'text': ''})]:
                try:
                    process(kind, payload)
                    raise AssertionError('Invalid input accepted')
                except ValueError:
                    pass
                assert not LOCK.locked()
            LOCK.acquire()
            try:
                try:
                    process('synthesize', {'text': 'test'})
                    raise AssertionError('Concurrent worker accepted')
                except RuntimeError:
                    pass
            finally:
                LOCK.release()
        print('PASS: invalid audio/text rejected; worker lock released; concurrent voice rejected.')
    else:
        state = capabilities()
        state.pop('config', None)
        print(json.dumps(state, indent=2))
