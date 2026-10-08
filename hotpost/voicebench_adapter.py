"""HTTP boundary to the separately deployed VoiceBench TTS subsystem."""
from __future__ import annotations

import json
import io
import os
import shutil
import time
import uuid
import wave
from pathlib import Path
from typing import Callable

import requests

from .config import Settings


def verify_wav(payload: bytes) -> dict:
    """Reject header-only, truncated and zero-duration synthesis responses."""
    try:
        with wave.open(io.BytesIO(payload), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if frames <= 0 or rate <= 0 or channels <= 0 or width <= 0:
                raise ValueError('empty audio')
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError('truncated audio')
            return {'duration': frames / rate, 'sample_rate': rate,
                    'channels': channels, 'sample_width': width}
    except (wave.Error, EOFError, ValueError) as exc:
        raise RuntimeError('VoiceBench returned an invalid WAV payload.') from exc


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

    def voices(self) -> dict:
        try:
            return self._response_json(self.session.get(self._url('/v1/voices'),headers=self._headers(),timeout=15))
        except requests.RequestException as exc:
            raise RuntimeError('목소리 목록을 불러오지 못했어요. VoiceBench 연결·업데이트 상태를 확인하고 다시 눌러주세요.') from exc

    def default_voice_status(self) -> dict:
        return self._response_json(self.session.get(self._url('/v1/health'), headers=self._headers(), timeout=15))

    def release_idle(self) -> dict:
        """Ask the server to free idle workers; never supply engine overrides."""
        try:
            headers = self._headers()
        except RuntimeError:
            # Resource cleanup is optional for script-only installations. The
            # synthesis path still requires its normal authentication setup.
            return {'status': 'unconfigured', 'released': False}
        response = self.session.post(self._url('/v1/resources/release-idle'),
            json={}, headers=headers, timeout=60, allow_redirects=False)
        if response.status_code in (404, 405, 501):
            return {'status': 'unsupported', 'released': False}
        if 300 <= response.status_code < 400:
            raise RuntimeError('VoiceBench resource API redirects are not allowed.')
        result = self._response_json(response)
        if result.get('status') not in ('busy', 'released'):
            raise RuntimeError('VoiceBench returned an invalid resource status.')
        return result

    def preview(self, voice_id: str) -> tuple[bytes,str]:
        import re
        if not re.fullmatch(r'[a-z0-9_-]{1,100}',voice_id): raise ValueError('올바르지 않은 목소리입니다.')
        try:
            response=self.session.get(self._url('/v1/voices/'+voice_id+'/preview'),headers=self._headers(),timeout=20)
            response.raise_for_status()
            return response.content,response.headers.get('Content-Type','audio/wav')
        except requests.RequestException as exc:
            raise RuntimeError('이 목소리의 미리듣기를 준비하지 못했어요. 다른 목소리를 듣거나 잠시 후 다시 시도하세요.') from exc

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
                   on_submitted: Callable[[int], None] | None = None,
                   retry_failed: bool = False, generation_key: str | None = None,
                   voice_profile_id: str | None = None, require_personal_clone: bool = False) -> dict:
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
        payload = {"text": script}
        if require_personal_clone:
            if voice_profile_id:
                raise ValueError('자동 제작은 본인 복제 목소리만 사용합니다.')
            health = self.default_voice_status()
            if not health.get('ready') or health.get('default_voice_kind') != 'personal':
                raise RuntimeError('내 목소리 복제 준비가 필요합니다. ' +
                                   ' / '.join(health.get('errors') or ['기본 음성이 개인 복제 음성인지 확인할 수 없습니다.']) +
                                   ' 다른 기본 목소리로 대체하지 않습니다.')
        if voice_profile_id:
            if not any(v.get('id')==voice_profile_id and v.get('available') for v in self.voices().get('voices',[])):
                raise ValueError('선택한 목소리가 준비되지 않았습니다. 다른 목소리를 선택하세요.')
            payload['voice_id'] = voice_profile_id
        if generation_key:
            payload['generation_key'] = generation_key
        try:
            if request_id is None:
                submitted = self._response_json(self.session.post(
                    self._url("/v1/tts"), json=payload, headers=headers,
                    timeout=timeout,
                ))
            else:
                if type(request_id) is not int or request_id <= 0:
                    raise ValueError("Invalid persisted VoiceBench request ID.")
                submitted = self._response_json(self.session.get(
                    self._url(f"/v1/tts/{request_id}"), headers=headers, timeout=timeout))
                submitted.setdefault('id', request_id)
                # Explicit retry may replace a confirmed terminal failure.
                # Unknown/running outcomes always retain the existing ID.
                if retry_failed and submitted.get('status') in {'failed', 'cancelled'}:
                    submitted = self._response_json(self.session.post(
                        self._url('/v1/tts'), json=payload, headers=headers, timeout=timeout))
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

        if require_personal_clone and status.get('voice_id'):
            raise RuntimeError('기존 요청이 다른 목소리로 생성됐습니다. 본인 복제 음성으로 새 작업이 필요합니다.')
        if voice_profile_id and status.get('voice_id') != voice_profile_id:
            raise RuntimeError('요청한 목소리와 생성 결과가 다릅니다. VoiceBench 업데이트 상태를 확인하세요.')
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
        audio_info = verify_wav(payload)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(payload)
            if target.is_file():
                shutil.copy2(target, target.with_name(f'{target.stem}.backup-{uuid.uuid4().hex[:12]}.wav'))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        metadata = {
            "voicebench_request_id": request_id,
            "voice_profile_id": status.get('voice_id') or voice_profile_id,
            "status": "succeeded",
            "output_path": str(target),
            "audio": audio_info,
            "quality_control": status.get("quality_control"),
            "speech_plan": status.get("speech_plan"),
            "reused": bool(submitted.get("reused")),
        }
        target.with_suffix(".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        progress("VoiceBench 음성 생성 완료", 100)
        return metadata
