"""HTTP boundary to the separately deployed VoiceBench TTS subsystem."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

import requests

from .config import Settings


class VoiceBenchAdapter:
    """Submit once, poll by request ID, and materialize the resulting WAV."""

    def __init__(self, settings: Settings, session=None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.session = session or requests.Session()
        self.sleep = sleep

    def _api_key(self) -> str:
        value = os.environ.get("VOICEBENCH_API_KEY", "").strip()
        if not value:
            path = self.settings.voicebench_api_key_file.expanduser()
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(
                "VoiceBench API key was not found in VOICEBENCH_API_KEY or "
                f"{self.settings.voicebench_api_key_file}."
            )
        return value

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key()}"}

    def _url(self, path: str) -> str:
        return self.settings.voicebench_url.rstrip("/") + path

    @staticmethod
    def _response_json(response) -> dict:
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("VoiceBench returned a non-object response.")
        return data

    def synthesize(self, text: str, output_path: Path,
                   progress: Callable[[str, int], None] | None = None,
                   request_id: int | None = None,
                   on_submitted: Callable[[int], None] | None = None) -> dict:
        script = text.strip()
        if not script:
            raise ValueError("VoiceBench cannot synthesize an empty script.")
        target = output_path.expanduser().resolve()
        data_root = self.settings.data_dir.resolve()
        if target.suffix.lower() != ".wav" or not target.is_relative_to(data_root):
            raise ValueError(f"Voice output must be a WAV under {data_root}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        progress = progress or (lambda _message, _percent: None)
        headers = self._headers()
        timeout = min(60.0, float(self.settings.voicebench_timeout))
        progress("VoiceBench 음성 생성을 요청하는 중", 5)
        try:
            if request_id is None:
                submitted = self._response_json(self.session.post(
                    self._url("/v1/tts"), json={"text": script}, headers=headers,
                    timeout=timeout,
                ))
            else:
                if type(request_id) is not int or request_id <= 0:
                    raise ValueError("Invalid persisted VoiceBench request ID.")
                submitted = self._response_json(self.session.get(
                    self._url(f"/v1/tts/{request_id}"), headers=headers, timeout=timeout))
                submitted.setdefault('id', request_id)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"VoiceBench is not reachable at {self.settings.voicebench_url}."
            ) from exc
        request_id = submitted.get("id")
        if not isinstance(request_id, int):
            raise RuntimeError("VoiceBench did not return a request ID.")
        if on_submitted:
            on_submitted(request_id)

        deadline = time.monotonic() + float(self.settings.voicebench_timeout)
        status = submitted
        while status.get("status") not in {"succeeded", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"VoiceBench request {request_id} exceeded "
                    f"{self.settings.voicebench_timeout}s; the request was not resubmitted."
                )
            completed = int(status.get("completed_segments") or 0)
            total = max(1, int(status.get("segment_count") or 1))
            progress(
                f"VoiceBench 음성 생성 중 ({completed}/{total})",
                min(90, 10 + int(80 * completed / total)),
            )
            self.sleep(max(.1, float(self.settings.voicebench_poll_interval)))
            try:
                status = self._response_json(self.session.get(
                    self._url(f"/v1/tts/{request_id}"), headers=headers,
                    timeout=timeout,
                ))
            except requests.RequestException as exc:
                raise RuntimeError(
                    f"VoiceBench status check failed for request {request_id}; "
                    "the request was not resubmitted."
                ) from exc
        if status.get("status") != "succeeded":
            detail = str(status.get("error") or status.get("message") or "unknown error")
            raise RuntimeError(
                f"VoiceBench request {request_id} ended as {status.get('status')}: "
                f"{detail[:500]}"
            )

        try:
            audio = self.session.get(
                self._url(f"/v1/tts/{request_id}/audio"), headers=headers,
                timeout=timeout,
            )
            audio.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"VoiceBench audio download failed for request {request_id}."
            ) from exc
        payload = audio.content
        if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
            raise RuntimeError("VoiceBench returned an invalid WAV payload.")
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        metadata = {
            "voicebench_request_id": request_id,
            "status": "succeeded",
            "output_path": str(target),
            "quality_control": status.get("quality_control"),
            "speech_plan": status.get("speech_plan"),
            "reused": bool(submitted.get("reused")),
        }
        target.with_suffix(".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        progress("VoiceBench 음성 생성 완료", 100)
        return metadata
