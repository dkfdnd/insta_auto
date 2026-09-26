"""Human approval gates and recoverable production stages for the local studio."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .editing_adapter import _atomic_json, selected_source_videos
from .studio_store import Conflict, StudioStore, uid


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def selected(state, collection, key):
    return next((r for r in state[collection] if r["id"] == state.get(key)), None)


class Studio:
    def __init__(self, settings, *, workers=True):
        self.settings = settings
        self.store = StudioStore(settings.data_dir / "studio")
        self.stop = threading.Event()
        self.render_lock = threading.Lock()
        self._lease = None
        if workers:
            self._lease = (self.store.root / "worker.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    self._lease.seek(0)
                    msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._lease.close(); self._lease = None
            if self._lease:
                self.store.recover()
                for i in range(3):
                    threading.Thread(target=self._worker, name=f"studio-{i}", daemon=True).start()

    def create(self, code):
        from .storage import Storage
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code):
            raise ValueError("올바르지 않은 게시물 ID")
        db = Storage(self.settings.db_path)
        try:
            row = db.conn.execute("SELECT * FROM posts WHERE shortcode=?", (code,)).fetchone()
            if not row or row["kind"] not in {"reel", "video"}:
                raise ValueError("수집된 동영상 게시물을 선택하세요.")
            title = re.sub(r"#\S+", "", row["caption"] or "").strip().split("\n")[0][:70] or code
        finally:
            db.close()
        state, _ = self.store.create(code, title)
        return self.public(state)

    def folder(self, task_id):
        if not re.fullmatch(r"work-[a-f0-9]{16}", task_id):
            raise ValueError("올바르지 않은 제작 ID")
        path = self.store.root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _script(self, state, text, origin, restored_from=None):
        text = str(text).strip()
        if not text or len(text) > 3000:
            raise ValueError("대본은 1~3000자로 입력하세요.")
        current = selected(state, "scripts", "script_id")
        if current and current["text"] == text:
            return current
        revision = dict(id=uid("script-"), text=text, origin=origin, created=time.time(), restored_from=restored_from)
        path = self.folder(state["id"]) / (revision["id"] + ".txt")
        path.write_text(text + "\n", encoding="utf-8")
        revision["path"] = str(path)
        state["scripts"].append(revision)
        state.update(script_id=revision["id"], approved_script_id=None, voice_id=None,
                     approved_voice_id=None, edit_id=None, status="script_review", error="", message="대본을 검토해 주세요")
        return revision

    def action(self, task_id, action, data):
        def change(state, db):
            if action == "save-script":
                self._script(state, data.get("text", ""), "manual")
            elif action == "restore-script":
                old = next(s for s in state["scripts"] if s["id"] == data["script_id"])
                self._script(state, old["text"], "restored", old["id"])
            elif action == "propose-script":
                script = selected(state, "scripts", "script_id")
                if not script: raise ValueError("수정할 대본이 없습니다.")
                if any(j["kind"] == "proposal" and j["status"] in {"running", "queued"} for j in self.store.jobs(task_id)):
                    raise Conflict("AI 수정안을 준비하고 있습니다. 완료 후 다시 요청하세요.")
                request = str(data.get("request", "")).strip()[:2000]
                if not request: raise ValueError("수정 요청을 입력하세요.")
                self.store.enqueue(db, task_id, "proposal", {"script_id": script["id"], "request": request}, uid("proposal:"))
            elif action == "apply-proposal":
                proposal = next(p for p in state["proposals"] if p["id"] == data["proposal_id"])
                if proposal["script_id"] != state["script_id"]:
                    raise Conflict("수정안 생성 후 대본이 바뀌었습니다. 현재 대본으로 다시 요청하세요.")
                self._script(state, proposal["text"], "ai_proposal")
            elif action in {"approve-script", "regenerate-voice"}:
                script = selected(state, "scripts", "script_id")
                if not script: raise ValueError("승인할 대본이 없습니다.")
                if data.get("script_id") != script["id"]: raise Conflict("대본 버전이 바뀌었습니다.")
                if action == "regenerate-voice" and state["approved_script_id"] != script["id"]:
                    raise Conflict("현재 대본을 먼저 승인하세요.")
                if action == "approve-script" and state["approved_script_id"] == script["id"]: return
                if state["status"] == "voice_generating": return
                state.update(approved_script_id=script["id"], voice_id=None, approved_voice_id=None, edit_id=None,
                             status="voice_generating", message="음성 생성 대기", error="")
                speed = float(data.get("speed", 1))
                if not .8 <= speed <= 1.25: raise ValueError("음성 속도는 0.8~1.25배입니다.")
                voice_id = uid("voice-")
                self.store.enqueue(db, task_id, "voice", {"script_id": script["id"], "voice_id": voice_id, "speed": speed}, voice_id)
                state["pending_voice_id"] = voice_id
            elif action == "approve-voice":
                voice = selected(state, "voices", "voice_id")
                if not voice or data.get("voice_id") != voice["id"]: raise Conflict("음성 버전을 확인하세요.")
                if state.get("pending_voice_id") != voice["id"]: raise Conflict("새로 생성 중인 음성을 확인한 뒤 승인하세요.")
                if voice["script_id"] != state["approved_script_id"]: raise Conflict("현재 승인 대본과 다른 음성입니다.")
                if state["approved_voice_id"] == voice["id"]: return
                if digest(voice["path"]) != voice["sha256"]: raise Conflict("음성 파일이 변경되었습니다.")
                state.update(approved_voice_id=voice["id"], status="editing", message="장면·자막 편집 대기", error="")
                self.store.enqueue(db, task_id, "edit", {"voice_id": voice["id"], "script_id": voice["script_id"]}, "edit:" + voice["id"])
            elif action == "retry":
                row = db.execute("SELECT * FROM jobs WHERE task_id=? AND status='failed' ORDER BY updated DESC LIMIT 1", (task_id,)).fetchone()
                if not row: return
                payload = json.loads(row["payload"])
                if payload.get("script_id", state["script_id"]) != state["script_id"]:
                    raise Conflict("이전 대본의 작업입니다. 현재 대본을 승인해 주세요.")
                if row["kind"] == "voice" and payload.get("voice_id") != state.get("pending_voice_id"):
                    raise Conflict("이전 음성의 작업입니다. 현재 음성을 확인하세요.")
                if row["kind"] in {"edit", "revision", "edit_request"} and payload.get("voice_id") != state.get("approved_voice_id"):
                    raise Conflict("이전 음성의 편집입니다. 현재 음성을 먼저 승인하세요.")
                db.execute("UPDATE jobs SET status='queued',error='' WHERE id=?", (row["id"],))
                state.update(error="", message="중단 단계부터 재시도 중")
                state["status"] = {"prepare":"preparing", "voice":"voice_generating", "edit":"editing", "revision":"editing"}.get(row["kind"], state["status"])
            elif action in {"revise-edit", "request-edit"}:
                edit = selected(state, "edits", "edit_id")
                if not edit or data.get("edit_id") != edit["id"]: raise Conflict("현재 편집 버전을 확인하세요.")
                if edit["voice_id"] != state["approved_voice_id"]: raise Conflict("현재 승인 음성과 다른 편집입니다.")
                if any(r["status"] in {"queued", "running"} and r["kind"] in {"edit", "revision", "edit_request"} for r in self.store.jobs(task_id)):
                    raise Conflict("진행 중인 편집이 완료된 후 요청하세요.")
                kind = "edit_request" if action == "request-edit" else "revision"
                self.store.enqueue(db, task_id, kind, {"edit_id": edit["id"], "voice_id": edit["voice_id"],
                                   "script_id": edit["script_id"], "changes": data.get("changes", []),
                                   "request": str(data.get("request", ""))[:2000], "start": data.get("start", 0), "end": data.get("end")}, uid("edit:"))
                state.update(status="editing", message="선택 구간 수정 중", error="")
            elif action == "open-capcut":
                edit = next((e for e in state["edits"] if e["id"] == data.get("edit_id")), None)
                if not edit: raise ValueError("초안 생성 후 이용할 수 있습니다.")
                self.store.enqueue(db, task_id, "register", {"edit_id": edit["id"]}, "register:" + edit["id"])
                db.execute("UPDATE jobs SET status='queued' WHERE key=? AND status='done'", ("register:" + edit["id"],))
                state.update(message="CapCut 초안 준비 중", error="")
            else:
                raise ValueError("지원하지 않는 작업입니다.")
            self.store.event(db, task_id, action, {k: v for k, v in data.items() if k not in {"text"}})
        return self.public(self.store.change(task_id, change, data.get("revision")))

    def public(self, state):
        state = copy.deepcopy(state)
        if state.get("manifest_path"):
            state["sources"] = self._source_records([s["path"] for s in state["sources"]], state["manifest_path"], state["sources"])
        for collection in ("scripts", "voices", "edits"):
            for item in state[collection]:
                for field in ("path", "preview_path", "cover_path"):
                    if item.get(field):
                        item[field.replace("_path", "") + "_url"] = self.media_url(state["id"], item[field])
                if collection == "edits" and item.get("plan_path"):
                    plan = json.loads(Path(item["plan_path"]).read_text(encoding="utf-8"))
                    for shot in plan.get("shots", []):
                        shot["thumbnail_url"] = self.media_url(state["id"], shot["frames"][1 if len(shot["frames"]) > 1 else 0])
                        shot["video_url"] = self.media_url(state["id"], shot["path"])
                    item["plan"] = plan
        for source in state["sources"]:
            source["url"] = self.media_url(state["id"], source["path"])
        state["jobs"] = self.store.jobs(state["id"])
        return state

    @staticmethod
    def _source_records(videos, manifest, existing=None):
        from urllib.parse import urlparse
        try:
            data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if existing is not None: return existing
            raise
        records = []
        for i, raw in enumerate(videos):
            path = Path(raw)
            record = dict(existing[i]) if existing else {"id": f"source-{i}", "path": str(path), "sha256": digest(path)}
            candidate = next((c for c in data.get("candidates", []) if c.get("file_sha256") == record["sha256"] or Path(c.get("downloaded_file") or "_").name == path.name), {})
            url = candidate.get("original_url") or candidate.get("url", "")
            record.update(origin_url=url if urlparse(url).scheme in {"http", "https"} else "",
                          rights=candidate.get("rights", "unknown"), manifest_path=str(manifest))
            records.append(record)
        return records

    def media_url(self, task_id, raw):
        from urllib.parse import quote
        relative = Path(raw).resolve().relative_to(self.settings.data_dir.resolve()).as_posix()
        return f"/api/studio/{task_id}/media?file={quote(relative)}"

    def media(self, task_id, relative):
        state = self.store.get(task_id)
        path = (self.settings.data_dir / relative).resolve()
        own = self.folder(task_id).resolve()
        sources = {Path(s["path"]).resolve() for s in state["sources"]}
        if not path.is_file() or not path.is_relative_to(self.settings.data_dir.resolve()):
            raise ValueError("미디어 파일을 찾을 수 없습니다.")
        if not path.is_relative_to(own) and path not in sources:
            raise ValueError("이 작업의 미디어 파일이 아닙니다.")
        if path.suffix.lower() not in {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".wav", ".txt", ".srt"}:
            raise ValueError("지원하지 않는 미디어 형식")
        return path

    def _worker(self):
        while not self.stop.is_set():
            job = self.store.claim()
            if not job:
                self.stop.wait(.6); continue
            try:
                state = self.store.get(job["task_id"])
                payload = job["payload"]
                if "script_id" in payload and payload["script_id"] != state["script_id"]:
                    self.store.finish(job, {}, lambda *_: None); continue
                result = getattr(self, "_" + job["kind"])(state, job)
                self.store.finish(job, result, lambda s, db, r: self._accept(s, job, r))
            except Exception as exc:
                self.store.fail(job, exc)

    def _prepare(self, state, job):
        from .source_finder import find_sources
        from .transcript import extract_transcript
        from .script_rewriter import rewrite
        code = state["shortcode"]
        manifests = sorted(self.settings.source_dir.glob(f"{code}-*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        videos, manifest = [], None
        for candidate in manifests:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                data["candidates"] = [c for c in data.get("candidates", []) if c.get("editing_eligible", True) and c.get("source_quality") in {"clean-source", "light-overlay"}]
                filtered = candidate.parent / "studio-selected.json"
                _atomic_json(filtered, data)
                videos = selected_source_videos(filtered)
                manifest = candidate
                break
            except (ValueError, OSError): continue
        if not videos:
            result = find_sources(self.settings, code, lambda *_: None)
            manifest = Path(result["zip_path"]).parent / "manifest.json"
            videos = selected_source_videos(manifest)
        transcripts = sorted(self.settings.transcript_dir.glob(f"{code}-*/transcript.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        transcript = next((p for p in transcripts if json.loads(p.read_text(encoding="utf-8")).get("speech")), None)
        if transcript is None:
            transcript = Path(extract_transcript(self.settings, code, lambda *_: None)["json_path"])
        original = "\n".join(s.get("text", "") for s in json.loads(transcript.read_text(encoding="utf-8")).get("speech", []))
        existing = sorted((self.settings.data_dir / "productions" / code).glob("scripts-v*/scripts.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        script = json.loads(existing[0].read_text(encoding="utf-8")) if existing else rewrite(
            self.settings, transcript, manifest, self.folder(state["id"]) / "research", lambda *_: None)
        return {"text": script["variants"][0]["text"], "original_text": original,
                "sources": self._source_records(videos, manifest),
                "manifest_path": str(manifest)}

    def _proposal(self, state, job):
        from .studio_ai import propose_script
        script = next(s for s in state["scripts"] if s["id"] == job["payload"]["script_id"])
        return {**propose_script(self.settings, state, script["text"], job["payload"]["request"]),
                "id": job["id"], "script_id": script["id"], "created": time.time()}

    def _voice(self, state, job):
        from .voicebench_adapter import VoiceBenchAdapter, verify_wav
        p = job["payload"]
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        folder = self.folder(state["id"]) / p["voice_id"]
        folder.mkdir(exist_ok=True)
        voice = folder / "original.wav"
        metadata = folder / "tts.json"
        if not (voice.is_file() and metadata.is_file()):
            def checkpoint(request_id):
                job["checkpoint"]["request_id"] = request_id
                self.store.checkpoint(job["id"], job["checkpoint"])
            result = VoiceBenchAdapter(self.settings).synthesize(script["text"], voice,
                request_id=job["checkpoint"].get("request_id"), on_submitted=checkpoint)
            _atomic_json(metadata, result)
        result = json.loads(metadata.read_text(encoding="utf-8"))
        if p["speed"] != 1:
            voice = folder / "approved-listening.wav"
            self._process(state, job, "audio", {"input": str(folder / "original.wav"), "output": str(voice), "speed": p["speed"]})
        info = verify_wav(voice.read_bytes())
        return {"id": p["voice_id"], "script_id": script["id"], "path": str(voice), "sha256": digest(voice),
                "created": time.time(), "speed": p["speed"], "duration": info["duration"],
                "request_id": result["voicebench_request_id"], "quality_control": result.get("quality_control")}

    def _process(self, state, job, action, payload):
        folder = self.folder(state["id"]) / job["id"]
        folder.mkdir(exist_ok=True)
        request, result = folder / f"{action}-request.json", folder / f"{action}-result.json"
        _atomic_json(request, {"action": action, "output_dir": str(folder), **payload})
        with self.render_lock:
            with (folder / f"{action}.log").open("a", encoding="utf-8") as log:
                proc = subprocess.Popen([str(self.settings.auto_capcut_python), "-X", "utf8", "-m", "auto_capcut.studio_runner",
                                   "--request", str(request), "--result", str(result)],
                                  cwd=self.settings.auto_capcut_root, stdout=log, stderr=log)
                # The runner owns an OS lock and a result receipt. A server restart can
                # reconnect without executing the same render concurrently or twice.
                job["checkpoint"][action + "_pid"] = proc.pid
                self.store.checkpoint(job["id"], job["checkpoint"])
                try:
                    proc.wait(timeout=self.settings.auto_capcut_timeout)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("편집 시간이 길어지고 있습니다. 재시도하면 기존 실행 결과를 이어받습니다.")
        if not result.is_file(): raise RuntimeError("편집 실행기가 결과를 반환하지 않았습니다. 작업 로그를 확인하세요.")
        data = json.loads(result.read_text(encoding="utf-8"))
        if data.get("status") != "completed": raise RuntimeError(data.get("error", "편집 실행 실패"))
        return data

    def _edit(self, state, job):
        from .studio_ai import describe_shots
        p = job["payload"]
        voice = next(v for v in state["voices"] if v["id"] == p["voice_id"])
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        if digest(voice["path"]) != voice["sha256"]: raise Conflict("승인한 음성이 변경되었습니다.")
        sources = self._source_records([s["path"] for s in state["sources"]], state["manifest_path"], state["sources"])
        base = self._process(state, job, "analyze", {"sources": sources, "voice": voice, "script": script})
        plan = base["plan"]
        semantic = self.folder(state["id"]) / job["id"] / "semantic-plan.json"
        if semantic.is_file():
            plan = json.loads(semantic.read_text(encoding="utf-8"))
            result = self._process(state, job, "render", {"plan": plan})
            return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}
        try:
            observations, choices = describe_shots(self.settings, plan["shots"], plan["beats"])
            for shot in plan["shots"]:
                observation = observations.get(shot["id"], {})
                if observation.get("observation"):
                    shot["observation"] = str(observation["observation"])[:1200]
                    shot["tags"] = [str(t)[:100] for t in observation.get("tags", [])[:15]]
            for beat in plan["beats"]:
                choice = choices.get(beat["id"], {})
                if choice.get("options"): beat["options"] = choice["options"][:3]
                if type(choice.get("emphasis")) is int and choice["emphasis"] in (0, 1, 2):
                    beat["emphasis"] = choice["emphasis"]
                    beat["emphasis_reason"] = choice["emphasis_reason"]
            plan["semantic_provider"] = self.settings.script_model
        except Exception as exc:
            plan["warnings"].append("장면 의미 분석을 완료하지 못해 대체 후보를 사용했습니다: " + str(exc)[:200])
        _atomic_json(semantic, plan)
        result = self._process(state, job, "render", {"plan": plan})
        return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}

    def _revision(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        result = self._process(state, job, "revise", {"plan": plan, "changes": job["payload"]["changes"]})
        return {"id": job["id"], "script_id": edit["script_id"], "voice_id": edit["voice_id"],
                "parent_id": edit["id"], "created": time.time(), **result}

    def _edit_request(self, state, job):
        from .studio_ai import plan_revision
        p = job["payload"]
        edit = next(e for e in state["edits"] if e["id"] == p["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        start, end = float(p["start"]), float(p["end"] or plan["duration"])
        if not 0 <= start < end <= plan["duration"] + .1: raise ValueError("수정할 구간을 확인하세요.")
        result = job["checkpoint"].get("interpretation")
        if result is None:
            result = plan_revision(self.settings, plan, p["request"], start, end)
            job["checkpoint"]["interpretation"] = result
            self.store.checkpoint(job["id"], job["checkpoint"])
        job["payload"]["changes"] = [{"beat_id": c["beat_id"], "emphasis": c["emphasis"]} for c in result["changes"] if "emphasis" in c]
        candidates = [c["beat_id"] for c in result["changes"] if c.get("choose_candidates")]
        if job["payload"]["changes"]:
            output = self._revision(state, job)
        else:
            output = {"no_render": True}
        return {**output, "candidate_requests": candidates, "request_summary": result["summary"]}

    def _register(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        return self._process(state, job, "register", {"plan_path": edit["plan_path"], "edit_id": edit["id"], "launch": True})

    def _accept(self, state, job, result):
        kind, p = job["kind"], job["payload"]
        if kind == "prepare":
            state.update({k: v for k, v in result.items() if k != "text"})
            if not state["scripts"]: self._script(state, result["text"], "recommended")
        elif kind == "proposal":
            if not any(r["id"] == result["id"] for r in state["proposals"]): state["proposals"].append(result)
        elif kind == "voice":
            if not any(v["id"] == result["id"] for v in state["voices"]): state["voices"].append(result)
            if state["approved_script_id"] == result["script_id"] and state.get("pending_voice_id") == result["id"]:
                state.update(voice_id=result["id"], status="voice_review", message="음성을 듣고 승인해 주세요", error="")
        elif kind in {"edit", "revision", "edit_request"}:
            if not result.get("no_render") and not any(e["id"] == result["id"] for e in state["edits"]): state["edits"].append(result)
            if state["approved_voice_id"] == p["voice_id"]:
                if not result.get("no_render"): state["edit_id"] = result["id"]
                state.update(status="draft_review", message=result.get("request_summary") or "초안을 확인해 주세요", error="",
                             candidate_requests=result.get("candidate_requests", []))
        elif kind == "register":
            edit = next(e for e in state["edits"] if e["id"] == p["edit_id"])
            edit.update(draft_path=result["draft_path"], draft_name=result["draft_name"])
            state.update(message="CapCut에서 초안을 열어 편집할 수 있습니다", error="")
