from __future__ import annotations

from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.voicebench_adapter import VoiceBenchAdapter


class Response:
    def __init__(self, data=None, content=b"", status=200):
        self._data = data
        self.content = content
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, wav: bytes):
        self.wav = wav
        self.posts = 0
        self.gets = 0

    def post(self, url, **kwargs):
        self.posts += 1
        assert kwargs["json"] == {"text": "실제 대본"}
        assert kwargs["headers"]["Authorization"] == "Bearer secret"
        return Response({"id": 17, "status": "queued", "segment_count": 1})

    def get(self, url, **kwargs):
        self.gets += 1
        if url.endswith("/audio"):
            return Response(content=self.wav)
        return Response({"id": 17, "status": "succeeded", "segment_count": 1,
                         "completed_segments": 1})


def _settings(tmp_path: Path) -> Settings:
    key = tmp_path / "key.txt"
    key.write_text("secret\n", encoding="utf-8")
    return Settings(data_dir=tmp_path / "data", voicebench_api_key_file=key,
                    voicebench_poll_interval=.01, voicebench_timeout=10)


def test_voicebench_submits_once_and_downloads_wav(tmp_path):
    settings = _settings(tmp_path)
    wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\0" * 32
    session = Session(wav)
    target = settings.data_dir / "editing_jobs" / "job-1" / "voice.wav"
    result = VoiceBenchAdapter(settings, session=session, sleep=lambda _: None).synthesize(
        "  실제 대본  ", target
    )
    assert session.posts == 1
    assert target.read_bytes() == wav
    assert result["voicebench_request_id"] == 17


def test_voicebench_rejects_output_outside_data(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ValueError, match="under"):
        VoiceBenchAdapter(settings, session=Session(b"")).synthesize(
            "대본", tmp_path / "outside.wav"
        )
