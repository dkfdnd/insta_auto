"""Persistent, resumable per-post source → transcript → two Shorts workflow."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from .config import Settings
from .editing_adapter import AutoCapcutAdapter, _atomic_json, selected_source_videos
from .storage import Storage

_CODE = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")


class ProductionManager:
    def __init__(self, settings: Settings, queue):
        self.settings, self.queue = settings, queue
        self.root = settings.data_dir / "productions"
        self.lock = threading.RLock()
        self.stop = threading.Event()
        queue.register("production", self._work)

    def folder(self, code):
        if not _CODE.fullmatch(code):
            raise ValueError("올바르지 않은 게시물 ID")
        return self.root / code

    def read(self, code):
        path = self.folder(code) / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {
            "shortcode": code, "status": "idle", "stages": {}, "variants": []}

    def save(self, state):
        state["updated_at"] = int(time.time())
        _atomic_json(self.folder(state["shortcode"]) / "state.json", state)

    def start(self, code, retry=False):
        with self.lock:
            state = self.read(code)
            if state["status"] in ("done", "error") and not retry:
                return self.public(state)
            if state["status"] in ("queued", "running"):
                previous = self.queue.get(state.get("job_id", ""))
                if previous and previous["status"] in ("queued", "running"):
                    return self.public(state)
            # A failed retry resumes verified artifacts under this same production ID.
            state.update(status="queued", error="", message="자동 제작 대기", progress=0,
                         run_id=state.get("run_id") or uuid.uuid4().hex[:10])
            self.save(state)
            job = self.queue.start("production", code)
            state["job_id"] = job["id"]
            self.save(state)
            return self.public(state)

    def watch(self):
        def loop():
            while not self.stop.is_set():
                try:
                    report = json.loads(self.settings.report_path.read_text(encoding="utf-8"))
                    if not report.get("is_sample"):
                        for post in report.get("posts", []):
                            if post.get("tier", 0) >= 1 and post.get("kind") in ("reel", "video"):
                                self.start(post["shortcode"])
                except (OSError, ValueError):
                    pass
                self.stop.wait(15)
        if self.settings.production_enabled:
            threading.Thread(target=loop, daemon=True, name="hotpost-production").start()

    def _file(self, raw):
        if not raw:
            return None
        path = Path(raw).resolve()
        if path.is_relative_to(self.settings.data_dir.resolve()) and path.is_file() and path.stat().st_size:
            return path
        return None

    def artifact(self, code, asset):
        state = self.read(code)
        fields = {"source": state.get("stages", {}).get("source", {}).get("zip_path"),
                  "transcript": state.get("stages", {}).get("transcript", {}).get("text_path")}
        for variant in state.get("variants", []):
            number = variant["version"]
            fields[f"script{number}"] = variant.get("script_path")
            if variant.get("status") == "done":
                fields[f"video{number}"] = variant.get("video_path")
        return self._file(fields.get(asset))

    def public(self, state):
        code = state["shortcode"]
        def url(asset):
            return f"/api/legacy-productions/{code}/download?asset={asset}"
        source = state.get("stages", {}).get("source", {})
        transcript = state.get("stages", {}).get("transcript", {})
        source_ready = source.get("status") == "done" and self._file(source.get("zip_path"))
        transcript_ready = transcript.get("status") == "done" and self._file(transcript.get("text_path"))
        def visible_status(stage, ready):
            status = stage.get("status", "queued")
            if status == "done" and not ready:
                return "missing"
            if state["status"] == "queued" and status in ("running", "voice", "building", "exporting", "error"):
                return "queued"
            if state["status"] == "error" and status in ("running", "voice", "building", "exporting"):
                return "error"
            return status
        variants = [{"version": v["version"], "status": visible_status(v, self._file(v.get("video_path"))),
                     "angle": v.get("angle", ""), "draft_name": v.get("draft_name", ""),
                     "download_url": url(f"video{v['version']}") if v.get("status") == "done" and self._file(v.get("video_path")) else None,
                     "script_url": url(f"script{v['version']}") if self._file(v.get("script_path")) else None}
                    for v in state.get("variants", [])]
        missing = (source.get("status") == "done" and not source_ready or
                   transcript.get("status") == "done" and not transcript_ready or
                   any(v["status"] == "missing" for v in variants))
        return {"shortcode": code, "status": "error" if missing else state["status"],
                "message": "결과 파일 확인 필요" if missing else state.get("message", "자동 제작 대기"),
                "error": "저장된 결과 파일을 찾을 수 없습니다. 다시 시도해 주세요." if missing else state.get("error", ""),
                "progress": state.get("progress", 0),
                "source": {"status": visible_status(source, source_ready),
                           "count": source.get("count", 0) if source_ready else 0,
                           "download_url": url("source") if source_ready else None},
                "transcript": {"status": visible_status(transcript, transcript_ready),
                               "download_url": url("transcript") if transcript_ready else None}, "variants": variants}

    def list(self):
        return [self.public(json.loads(path.read_text(encoding="utf-8"))) for path in self.root.glob("*/state.json")]

    def _existing(self, root, code, name):
        return sorted(root.glob(f"{code}-*/{name}"), key=lambda p: p.stat().st_mtime, reverse=True)

    def _work(self, code, progress):
        from .source_finder import find_sources
        from .transcript import extract_transcript
        from .script_rewriter import rewrite, SCRIPT_POLICY_VERSION
        from .voicebench_adapter import VoiceBenchAdapter
        with self.lock:
            state = self.read(code)
            state.update(status="running", error="")
            self.save(state)
        def update(message, percent):
            state.update(message=message, progress=percent)
            self.save(state)
            progress(message, percent)
        def stage(name, value):
            state["stages"][name] = value
            self.save(state)
        try:
            update("소스 영상 확인·다운로드 중", 5)
            stage("source", {"status": "running"})
            manifests = self._existing(self.settings.source_dir, code, "manifest.json")
            manifest = next((p for p in manifests if self._usable_sources(p)), None)
            if manifest is None:
                result = find_sources(self.settings, code, lambda m, p: update(m, 5 + p // 4))
                manifest = Path(result["zip_path"]).parent / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            selected = [c for c in data.get("candidates", []) if c.get("selected_for_zip") and
                        self._file(manifest.parent / c.get("downloaded_file", ""))]
            if not selected:
                raise RuntimeError("다운로드된 유효 소스가 없습니다. 검색 결과·플랫폼 로그인을 확인하세요.")
            stage("source", {"status": "done", "count": len(selected), "manifest_path": str(manifest),
                             "zip_path": str(manifest.parent / f"sources_{code}.zip")})
            update("대본 추출 중", 32)
            stage("transcript", {"status": "running"})
            paths = self._existing(self.settings.transcript_dir, code, "transcript.json")
            transcript = next((p for p in paths if json.loads(p.read_text(encoding="utf-8")).get("speech") and
                               p.with_suffix(".txt").is_file()), None)
            if transcript is None:
                result = extract_transcript(self.settings, code, lambda m, p: update(m, 32 + p // 6))
                transcript = Path(result["json_path"])
            stage("transcript", {"status": "done", "json_path": str(transcript), "text_path": str(transcript.with_suffix(".txt"))})
            update("다른 구성의 대본 두 개를 재작성하는 중", 50)
            # Retain scripts referenced by older drafts when writing a new policy revision.
            scripts_path = self.folder(code) / f"scripts-v{SCRIPT_POLICY_VERSION}" / "scripts.json"
            scripts = json.loads(scripts_path.read_text(encoding="utf-8")) if scripts_path.is_file() else {}
            if scripts.get("policy_version") != SCRIPT_POLICY_VERSION:
                scripts = rewrite(self.settings, transcript, manifest, scripts_path.parent,
                                  lambda m, p: update(m, 50 + p // 10))
            # Only include usable sources in the editing handoff; keep the full download manifest intact.
            filtered = {**data, "candidates": [{**c, "selected_for_zip": bool(c.get("selected_for_zip") and
                         c.get("editing_eligible", True) and
                         c.get("source_quality") in ("clean-source", "light-overlay"))} for c in data["candidates"]]}
            editing_manifest = manifest.parent / "production-selected.json"
            _atomic_json(editing_manifest, filtered)
            videos = selected_source_videos(editing_manifest)
            previous = {v["version"]: v for v in state["variants"]}
            if any(previous.get(item["version"], {}).get("text", item["text"]) != item["text"] or
                   previous.get(item["version"], {}).get("draft_path") and
                   (previous[item["version"]].get("export_profile") != "free" or
                    not self._same_source_inputs(code, state['run_id'], item['version'],
                                                 videos if item['version'] == 1 else list(reversed(videos))))
                   for item in scripts["variants"]):
                state["run_id"] = uuid.uuid4().hex[:10]
                previous = {}  # A changed script must never reuse an old voice, project or export.
            state["variants"] = [{**item, **previous.get(item["version"], {})} for item in scripts["variants"]]
            adapter = AutoCapcutAdapter(self.settings)
            for variant in state["variants"]:
                version = variant["version"]
                job_id = f"{code}-{state['run_id']}-v{version}"
                folder = self.settings.editing_dir / job_id
                voice = folder / "voice.wav"
                if not self._file(voice):
                    variant["status"] = "voice"
                    update(f"버전 {version} 음성 생성 중", 60 + version * 4)
                    VoiceBenchAdapter(self.settings).synthesize(variant["text"], voice,
                        lambda m, p: update(f"버전 {version} · {m}", 60 + version * 4))
                if not variant.get("draft_path") or not Path(variant["draft_path"]).is_dir():
                    variant["status"] = "building"
                    variant["draft_name"] = f"hotpost_{job_id}"
                    update(f"CapCut 버전 {version} 프로젝트 생성 중", 74 + version * 4)
                    ordered = videos if version == 1 else list(reversed(videos))
                    result = adapter.build(job_id=job_id, video_paths=ordered, voice_path=voice,
                        script_path=variant["script_path"], draft_name=variant["draft_name"], audio_profile="clean_tts",
                        export_profile="free", narration_speed=1.12)
                    if result.get("status") != "completed":
                        raise RuntimeError(result.get("message") or "CapCut 프로젝트 생성 실패")
                    variant["draft_path"] = result["draft_path"]
                    # auto_capcut preserves existing drafts by choosing a new
                    # name on collision. Export that returned project identity.
                    variant["draft_name"] = result.get("draft_name") or Path(result["draft_path"]).name
                    variant["export_profile"] = "free"
                    variant["status"] = "draft_ready"
                    self.save(state)
            # Both drafts must be built before starting the editor, which owns its registry while open.
            for variant in state["variants"]:
                if variant.get("status") == "done" and self._file(variant.get("video_path")):
                    continue
                variant["status"] = "exporting"
                update(f"CapCut 버전 {variant['version']} 내보내기 중", 88 + variant["version"] * 3)
                result = adapter.export(job_id=f"{code}-{state['run_id']}-v{variant['version']}",
                                        draft_name=variant["draft_name"], draft_path=Path(variant["draft_path"]))
                variant.update(status="done", video_path=result["video_path"])
                self.save(state)
            state["status"] = "done"
            update("쇼츠 두 버전 내보내기 완료", 100)
            return {"json_path": str(self.folder(code) / "state.json"), "variants": state["variants"]}
        except Exception as exc:
            state.update(status="error", error=str(exc)[:600], message="자동 제작 중 확인 필요")
            self.save(state)
            raise

    def _same_source_inputs(self, code, run_id, version, videos):
        request = self.settings.editing_dir / f'{code}-{run_id}-v{version}' / 'request.json'
        try:
            data = json.loads(request.read_text(encoding='utf-8'))
            return [str(Path(p).resolve()) for p in data['video_paths']] == [str(p.resolve()) for p in videos]
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _usable_sources(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return (path.parent / f"sources_{data['shortcode']}.zip").is_file() and any(
                c.get("selected_for_zip") and c.get("source_quality") in ("clean-source", "light-overlay") and
                c.get("editing_eligible", True) and
                self._file(path.parent / c.get("downloaded_file", "")) for c in data.get("candidates", []))
        except (OSError, ValueError, KeyError):
            return False
