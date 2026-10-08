import json
import subprocess
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.transcript import _isolated_speech


def test_isolated_speech_preserves_recognized_segments_and_fallback_notes(tmp_path, monkeypatch):
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'audio')
    recognized = [{'source': 'speech', 'start': 0, 'end': 2, 'text': '실제로 인식한 음성'}]

    def execute(command, **options):
        assert command[1:5] == ['-X', 'utf8', '-m', 'hotpost.speech_worker']
        request = json.loads((tmp_path / next(p.name for p in tmp_path.glob('speech-*')) / 'request.json').read_text('utf-8'))
        assert request['audio'] == str(audio.resolve())
        assert request['model'] == 'small'
        assert options['timeout'] == 180
        result = command[command.index('--result') + 1]
        from pathlib import Path
        Path(result).write_text(json.dumps({'speech': recognized, 'language': 'ko',
            'method': 'faster-whisper-cpu', 'notes': ['GPU 실패 · CPU 전사']}), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr('hotpost.transcript.subprocess.run', execute)
    notes = []
    assert _isolated_speech(Settings(data_dir=tmp_path), audio, notes) == (recognized, 'ko', 'faster-whisper-cpu')
    assert notes == ['GPU 실패 · CPU 전사']
    assert not list(tmp_path.glob('speech-*'))


def test_hung_speech_worker_times_out_without_fabricating_speech(tmp_path, monkeypatch):
    audio = tmp_path / 'audio.wav'
    audio.touch()
    def hang(command, **options):
        raise subprocess.TimeoutExpired(command, options['timeout'])
    monkeypatch.setattr('hotpost.transcript.subprocess.run', hang)
    with pytest.raises(subprocess.TimeoutExpired):
        _isolated_speech(Settings(data_dir=tmp_path), audio, [])
    assert not list(tmp_path.glob('speech-*'))


def test_missing_worker_receipt_is_an_error(tmp_path, monkeypatch):
    audio = tmp_path / 'audio.wav'
    audio.touch()
    monkeypatch.setattr('hotpost.transcript.subprocess.run', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match='결과를 반환하지'):
        _isolated_speech(Settings(data_dir=tmp_path), audio, [])
