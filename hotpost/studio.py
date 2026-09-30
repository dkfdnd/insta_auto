"""Manual review and automatic top-two production in one recoverable studio."""
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
from .source_quality import sha256_file
from .studio_workflow import WorkflowMixin, enabled, init_run, snapshot, current_run, capcut_running, transient


def digest(path):
    return sha256_file(Path(path))


def selected(state, collection, key):
    return next((r for r in state[collection] if r["id"] == state.get(key)), None)


class Studio(WorkflowMixin):
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
                # Script models, voice models and rendering share this PC.
                for i in range(1):
                    threading.Thread(target=self._worker, name=f"studio-{i}", daemon=True).start()
                if settings.studio_auto_top_enabled:
                    threading.Thread(target=self._watch_top, name='studio-top-two', daemon=True).start()

    def _watch_top(self):
        from .studio_automation import enqueue_latest
        while not self.stop.is_set():
            try:
                enqueue_latest(self.settings)
            except (OSError, ValueError, KeyError):
                pass  # A report may not exist yet; the collection hook also enqueues.
            self.stop.wait(30)

    def create(self, code, automation=None):
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
        state, _ = self.store.create(code, title, automation)
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
        if action == 'prepare-caption-preview':
            state = self.store.get(task_id)
            edit = next((e for e in state['edits'] if e['id']==data.get('edit_id')), None)
            if not edit or edit['id'] != state.get('edit_id'):
                raise Conflict('새 편집 영상이 준비되었습니다. 새로고침해 주세요.')
            if edit.get('clean_preview_path') and Path(edit['clean_preview_path']).is_file():
                return self.public(state)
            folder = self.folder(task_id)/('caption-preview-'+edit['id']); folder.mkdir(exist_ok=True)
            request, result = folder/'request.json', folder/'result.json'
            _atomic_json(request, {'action':'caption-preview','output_dir':str(folder),
                                  'plan':json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))})
            process = subprocess.run([str(self.settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner',
                                      '--request',str(request),'--result',str(result)],cwd=self.settings.auto_capcut_root,
                                     capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            output = json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {}
            if process.returncode or output.get('status') != 'completed':
                raise ValueError(output.get('error','편집 미리보기를 준비하지 못했습니다. 다시 시도하거나 CapCut에서 편집하세요.'))
            def accept(s, db):
                next(e for e in s['edits'] if e['id']==edit['id'])['clean_preview_path']=output['clean_preview_path']
            return self.public(self.store.change(task_id,accept))
        if action == 'check-script':
            # A read-only request; never hold the task DB lock across HTTP or
            # save/approve text merely because the user asked to inspect it.
            from .studio_adapter import StudioAdapter
            text = str(data.get('text', ''))
            if not text.strip() or len(text) > 3000:
                raise ValueError('대본은 1~3000자로 입력하세요.')
            state = self.store.get(task_id)
            try:
                return StudioAdapter(self.settings).review(text, state.get('reviewed_original_text', state['original_text']))
            except (RuntimeError, OSError) as exc:
                raise ValueError('대본 검사 서비스에 연결하지 못했습니다. script_auto 실행 상태를 확인하세요. 입력 내용은 그대로 유지됩니다.') from exc
        handled = self.workflow_action(task_id, action, data)
        if handled is not None:
            return handled
        def change(state, db):
            if action == 'save-original':
                if data.get('base_text', state.get('reviewed_original_text', state['original_text'])) != state.get('reviewed_original_text', state['original_text']):
                    raise Conflict('다른 화면에서 원본 발화가 바뀌었습니다. 최신 교정본을 확인하세요.')
                text = str(data.get('text', '')).strip()
                if not text or len(text) > 12000:
                    raise ValueError('원본 발화는 1~12000자로 입력하세요.')
                state.setdefault('original_reviews', []).append({'text': text, 'created': time.time()})
                state['reviewed_original_text'] = text
                self.store.event(db, task_id, action, {})
                return
            if action == 'review-result':
                run = next(r for r in self.pipeline(state) if r['id'] == data.get('run_id'))
                if not run.get('video_url') or run['status'] != 'completed':
                    raise ValueError('최종 영상이 완성된 뒤 확인할 수 있습니다.')
                checks = data.get('checks', [])
                if not isinstance(checks, list) or set(checks) != {'speech', 'captions', 'scenes'}:
                    raise ValueError('발음·자막·장면을 모두 확인해 주세요.')
                state.setdefault('result_reviews', {})[run['id']] = {'created': time.time(), 'checks': checks}
                self.store.event(db, task_id, action, {'run_id': run['id']})
                return
            if action in {'save-script', 'restore-script', 'apply-proposal', 'pause-auto'} and state.get('automation'):
                state['automation']['active'] = False
                state['automation']['paused_at'] = time.time()
                if action != 'pause-auto':
                    state['automation']['stage'] = 'manual_review'
                    state['automation'].pop('completed_at', None)
            if action == 'pause-auto':
                if not state.get('automation'): raise ValueError('자동 제작 대상이 아닙니다.')
                state['automation']['paused_by_user'] = True
                if enabled(state):
                    db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND status='queued' AND kind NOT IN ('proposal','refresh_sources','suggest_edit') AND COALESCE(json_extract(payload,'$.launch'),0)<>1", (task_id,))
                state.update(message='자동 진행 중지 · 진행 중인 단계의 결과를 보존합니다')
                self.store.event(db, task_id, action, {})
                return
            if action == 'resume-auto':
                if not state.get('automation'): raise ValueError('자동 제작 대상이 아닙니다.')
                state['automation']['active'] = True
                state['automation'].pop('paused_by_user', None)
                if enabled(state):
                    db.execute("UPDATE jobs SET status='queued' WHERE task_id=? AND status='paused'", (task_id,))
                if not state.get('sources'):
                    self.store.enqueue(db, task_id, 'prepare', {}, 'prepare:'+task_id)
                    state.update(status='preparing', message='자료 준비 재개', error='')
                self._advance_auto(state, db)
                self.store.event(db, task_id, action, {})
                return
            if action == 'refresh-sources':
                if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('prepare','refresh_sources') AND status IN ('queued','running')", (task_id,)).fetchone():
                    raise Conflict('자료 수집이 이미 대기 중이거나 실행 중입니다.')
                request = str(data.get('request', ''))[:1000]
                if data.get('retry_job_id'):
                    failed = db.execute("SELECT payload FROM jobs WHERE id=? AND task_id=? AND kind='refresh_sources' AND status='failed'",
                                        (data['retry_job_id'], task_id)).fetchone()
                    if not failed:
                        raise Conflict('재시도할 소스 검색이 변경되었습니다. 최신 상태를 확인하세요.')
                    request = json.loads(failed['payload']).get('request', '')
                self.store.enqueue(db, task_id, 'refresh_sources', {'request':request}, uid('sources:'))
                state['source_search'] = {'status': 'queued', 'message': '다국어 추가 수집 대기', 'progress': 0}
            elif action == "save-script":
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
                base_text = str(data.get('base_text', state.get('feedback', {}).get('script_text', script['text']))).strip()
                if not base_text or len(base_text) > 3000:
                    raise ValueError('대본은 1~3000자로 입력하세요.')
                self.store.enqueue(db, task_id, "proposal", {"script_id": script["id"], "request": request,
                    'base_text':base_text, 'original_text':state.get('reviewed_original_text', state['original_text'])}, uid("proposal:"))
            elif action == "apply-proposal":
                proposal = next(p for p in state["proposals"] if p["id"] == data["proposal_id"])
                if proposal["script_id"] != state["script_id"]:
                    raise Conflict("수정안 생성 후 대본이 바뀌었습니다. 현재 대본으로 다시 요청하세요.")
                if proposal.get('original_text', state.get('reviewed_original_text', state['original_text'])) != state.get('reviewed_original_text', state['original_text']):
                    raise Conflict('원본 발화가 교정되었습니다. 수정안을 다시 요청하세요.')
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
                if enabled(state):
                    checkpoint = json.loads(row['checkpoint'])
                    checkpoint.pop('not_before',None)
                    checkpoint['auto_retries'] = 0
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),row['id']))
                payload = json.loads(row["payload"])
                if payload.get("script_id", state["script_id"]) != state["script_id"]:
                    raise Conflict("이전 대본의 작업입니다. 현재 대본을 승인해 주세요.")
                if row["kind"] == "voice" and payload.get("voice_id") != state.get("pending_voice_id"):
                    raise Conflict("이전 음성의 작업입니다. 현재 음성을 확인하세요.")
                if row["kind"] in {"edit", "revision", "edit_request"} and payload.get("voice_id") != state.get("approved_voice_id"):
                    raise Conflict("이전 음성의 편집입니다. 현재 음성을 먼저 승인하세요.")
                if row['kind'] in {'rewrite', 'voice'}:
                    checkpoint = json.loads(row['checkpoint'])
                    checkpoint['retry_requested'] = True
                    db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps(checkpoint), row['id']))
                db.execute("UPDATE jobs SET status='queued',error='' WHERE id=?", (row["id"],))
                state.update(error="", message="중단 단계부터 재시도 중")
                state["status"] = {"prepare":"preparing", "rewrite":"rewriting", "voice":"voice_generating", "edit":"editing", "revision":"editing", "register":"registering"}.get(row["kind"], state["status"])
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
                db.execute("UPDATE jobs SET status='queued',payload=? WHERE key=? AND status IN ('done','queued','failed')",
                           (json.dumps({'edit_id':edit['id'], 'launch':True}), "register:" + edit["id"]))
                state.update(message="CapCut 초안 준비 중", error="")
            else:
                raise ValueError("지원하지 않는 작업입니다.")
            self.store.event(db, task_id, action, {k: v for k, v in data.items() if k not in {"text"}})
        return self.public(self.store.change(task_id, change, data.get("revision")))

    def public(self, state):
        state = copy.deepcopy(state)
        state['source_search_retry_supported'] = True
        state['caption_editor_supported'] = True
        if state.get("manifest_path"):
            state["sources"] = self._source_records([s["path"] for s in state["sources"]], state["manifest_path"], state["sources"])
            from .source_audit import summarize
            state['source_audit'] = summarize(state.get('source_search_manifest_path') or state['manifest_path'])
        for collection in ("scripts", "voices", "edits"):
            for item in state[collection]:
                for field in ("path", "preview_path", "cover_path", "clean_preview_path", "export_path"):
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
        state['original_evidence'] = {'speech': [], 'screen_text': []}
        if state.get('transcript_path'):
            try:
                transcript = json.loads(Path(state['transcript_path']).read_text(encoding='utf-8'))
                state['original_evidence'] = {key: transcript.get(key, []) for key in ('speech', 'screen_text')}
                state['original_evidence']['speech_unavailable'] = transcript.get('methods', {}).get('speech') == 'unavailable'
            except (OSError, ValueError):
                pass
        reference = Path(state.get('reference_video') or '')
        if reference.is_file() and reference.is_relative_to(self.settings.data_dir.resolve()):
            state['reference_url'] = self.media_url(state['id'], reference)
        state["jobs"] = self.store.jobs(state["id"])
        state['events'] = self.store.events(state['id'])
        state['pipeline'] = self.pipeline(state)
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
            candidates = data.get('candidates', [])
            candidate = next((c for c in candidates if c.get('file_sha256') == record['sha256']), None)
            if candidate is None:
                candidate = next((c for c in candidates if c.get('downloaded_file')
                                  and (Path(manifest).parent / c['downloaded_file']).resolve() == path.resolve()), {})
            if not candidate and existing:
                records.append(record)
                continue
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
        if state.get('reference_video'):
            sources.add(Path(state['reference_video']).resolve())
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
                if enabled(state) and not current_run(state):
                    state = self.store.change(state['id'], lambda s, db: init_run(s))
                if enabled(state) and state.get('pending_reproduction') and job['kind'] not in {'refresh_sources','proposal','suggest_edit'}:
                    self.store.finish(job, {}, lambda s, db, r: self.activate_reproduction(s, db))
                    continue
                if job['kind'] in {'register', 'export'} and not job['payload'].get('launch') and capcut_running():
                    self.store.defer(job, 'CapCut 종료 대기 · 저장하고 앱을 닫으면 자동으로 이어집니다', 15, waiting=True)
                    continue
                payload = job["payload"]
                if "script_id" in payload and payload["script_id"] != state["script_id"]:
                    self.store.finish(job, {}, lambda *_: None); continue
                result = getattr(self, "_" + job["kind"])(state, job)
                self.store.finish(job, result, lambda s, db, r: self._accept(s, job, r, db))
            except Exception as exc:
                if enabled(self.store.get(job['task_id'])) and transient(exc) and job['checkpoint'].get('auto_retries', 0) < 2:
                    self.store.defer(job, str(exc), 15 * (job['checkpoint'].get('auto_retries', 0)+1))
                else:
                    self.store.fail(job, exc)
                    state = self.store.get(job['task_id'])
                    if enabled(state) and state.get('pending_reproduction'):
                        self.store.change(state['id'], lambda s, db: self.activate_reproduction(s, db))

    def _prepare(self, state, job):
        from .source_finder import find_sources
        from .transcript import extract_transcript
        from .script_rewriter import rewrite
        def progress(message, pct):
            self.store.change(state['id'], lambda s, db: s.update(message=str(message)[:300], progress=pct))
        code = state["shortcode"]
        # Search must see actual speech/OCR from this reference on the first run.
        transcripts = sorted(self.settings.transcript_dir.glob(f"{code}-*/transcript.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        transcript = None
        for path in transcripts:
            try:
                if json.loads(path.read_text(encoding='utf-8')).get('speech'):
                    transcript = path; break
            except (OSError, ValueError):
                continue
        if transcript is None:
            transcript = Path(extract_transcript(self.settings, code, progress)["json_path"])
        original = '\n'.join(v.get('text', '') for v in json.loads(transcript.read_text(encoding='utf-8')).get('speech', []))
        def record_transcript(s, db):
            s.update(original_text=original, transcript_path=str(transcript), reference_video=str(transcript.parent / 'reference.mp4'))
            if enabled(s):
                snapshot(s)
        self.store.change(state['id'], record_transcript)
        if not original.strip():
            raise ValueError('원본 발화를 추출하지 못했습니다. 원본 영상의 음성과 전사 도구 설치 상태를 확인한 뒤 중단 단계를 재시도하세요. 화면 글자는 음성 대본으로 사용하지 않습니다.')
        manifests = sorted(self.settings.source_dir.glob(f"{code}-*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        # User uploads are production assets, not another search request. Keep
        # their IDs/provenance so selected sources remain selected downstream.
        chosen_ids = job.get('payload', {}).get('source_ids')
        supplied = [v for v in state['sources'] if (chosen_ids is None or v['id'] in chosen_ids) and Path(v['path']).is_file()]
        if chosen_ids is not None and len(supplied) != len(set(chosen_ids)):
            raise ValueError('선택한 영상 파일이 없습니다. 영상을 다시 업로드하세요.')
        videos, manifest = [Path(v['path']) for v in supplied], None
        for candidate in ([] if supplied else manifests):
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
            result = find_sources(self.settings, code, progress)
            manifest = Path(result["zip_path"]).parent / "manifest.json"
            data = json.loads(manifest.read_text(encoding='utf-8'))
            data['candidates'] = [c for c in data.get('candidates', []) if c.get('editing_eligible', True)
                                  and c.get('source_quality') in {'clean-source', 'light-overlay'}]
            filtered = manifest.parent / 'studio-selected.json'
            _atomic_json(filtered, data)
            videos = selected_source_videos(filtered)
        if not videos:
            raise ValueError('제작에 사용할 소스 영상이 없습니다. 자료를 확인하고 재시도하세요.')
        original = "\n".join(s.get("text", "") for s in json.loads(transcript.read_text(encoding="utf-8")).get("speech", []))
        if not original.strip():
            raise ValueError('실제 발화 대본을 확보하지 못했습니다. OCR을 음성 대본으로 대체하지 않습니다.')
        if supplied:
            manifest = self.folder(state['id']) / (job['id']+'-user-sources.json')
            _atomic_json(manifest, {'caption': state['title'], 'user_supplied': True, 'downloaded': len(supplied), 'candidates': [
                {'title': v.get('original_name', ''), 'file_sha256': v['sha256'],
                 'original_url': v.get('origin_url', ''), 'rights': v.get('rights', 'unknown'),
                 'selected_for_zip': True} for v in supplied]})
        if state.get('automation'):
            reference = transcript.parent / 'reference.mp4'
            if not reference.is_file():
                raise ValueError('대본 재가공에 필요한 기준 영상이 없습니다.')
            products = json.loads(manifest.read_text(encoding='utf-8')).get('product_evidence', {}).get('products', []) if manifest else []
            product = next((p.get('ko') or p.get('en') for p in products if isinstance(p, dict)), '')
            return {'original_text':original, 'reference_video':str(reference), 'transcript_path':str(transcript),
                    'product':product or state['title'], 'sources':supplied or self._source_records(videos, manifest),
                    'manifest_path':str(manifest) if manifest else ''}
        existing = sorted((self.settings.data_dir / "productions" / code).glob("scripts-v*/scripts.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        script = json.loads(existing[0].read_text(encoding="utf-8")) if existing else rewrite(
            self.settings, transcript, manifest, self.folder(state["id"]) / "research", lambda *_: None)
        return {"text": script["variants"][0]["text"], "original_text": original,
                "sources": supplied or self._source_records(videos, manifest),
                "manifest_path": str(manifest)}

    def _refresh_sources(self, state, job):
        from .source_finder import find_sources
        def progress(message, pct):
            self.store.change(state['id'], lambda s, db: s.update(source_search={
                'status': 'running', 'message': str(message)[:300], 'progress': pct}))
        result = find_sources(self.settings, state['shortcode'], progress, search_request=job['payload'].get('request', ''))
        manifest = Path(result['zip_path']).parent / 'manifest.json'
        videos = [manifest.parent / c['downloaded_file'] for c in result['candidates']
                  if c.get('selected_for_zip') and c.get('editing_eligible', True)
                  and c.get('source_quality') in {'clean-source', 'light-overlay'}]
        records = self._source_records(videos, manifest)
        for record in records:
            record['id'] = uid('source-')
        return {'source_search_manifest_path': str(manifest), 'sources': records}

    def _rewrite(self, state, job):
        from .studio_services import ensure_local
        from .studio_automation import rewrite
        if state.get('automation', {}).get('needs_top_pick') and state.get('script_candidates'):
            from .studio_top_pick import choose
            candidates = state['script_candidates']
            index, result = choose(self.settings, state, list(enumerate(candidates)))
            return {'text':candidates[index]['text'], 'top_pick':result, 'selected_candidate':index,
                    'selection_reason':result['reason']}
        ensure_local(self.settings, 'script')
        return rewrite(self, state, job)

    def _proposal(self, state, job):
        from .studio_ai import propose_script
        script = next(s for s in state["scripts"] if s["id"] == job["payload"]["script_id"])
        text = job['payload'].get('base_text', script['text'])
        evidence = {**state, 'original_text':job['payload'].get('original_text', state.get('reviewed_original_text', state['original_text']))}
        return {**propose_script(self.settings, evidence, text, job["payload"]["request"]),
                'base_text':text, 'original_text':evidence['original_text'],
                'base_hash':hashlib.sha256(text.encode()).hexdigest(),
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
            if state.get('automation'):
                from .studio_services import ensure_local
                ensure_local(self.settings, 'voice')
            def checkpoint(request_id):
                job["checkpoint"]["request_id"] = request_id
                job['checkpoint'].pop('retry_requested', None)
                self.store.checkpoint(job["id"], job["checkpoint"])
            result = VoiceBenchAdapter(self.settings).synthesize(p.get('spoken_text', script["text"]), voice,
                progress=lambda message, pct: self.store.change(state['id'], lambda s, db: s.update(message=message, progress=pct)),
                request_id=job["checkpoint"].get("request_id"), on_submitted=checkpoint,
                retry_failed=bool(job['checkpoint'].get('retry_requested')), generation_key=p.get('generation_key'))
            _atomic_json(metadata, result)
        result = json.loads(metadata.read_text(encoding="utf-8"))
        if p["speed"] != 1:
            voice = folder / "approved-listening.wav"
            self._process(state, job, "audio", {"input": str(folder / "original.wav"), "output": str(voice), "speed": p["speed"]})
        info = verify_wav(voice.read_bytes())
        return {"id": p["voice_id"], "script_id": script["id"], "path": str(voice), "sha256": digest(voice),
                "created": time.time(), "speed": p["speed"], "duration": info["duration"],
                "spoken_text": p.get('spoken_text', script['text']),
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
                                  cwd=self.settings.auto_capcut_root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
        records = [s for s in state['sources'] if p.get('source_ids') is None or s['id'] in p['source_ids']]
        if not records: raise ValueError('사용 가능한 소스가 없습니다.')
        sources = self._source_records([s["path"] for s in records], state.get("manifest_path", ''), records)
        base = self._process(state, job, "analyze", {"sources": sources, "voice": voice, "script": script})
        plan = base["plan"]
        semantic = self.folder(state["id"]) / job["id"] / "semantic-plan.json"
        if semantic.is_file():
            plan = json.loads(semantic.read_text(encoding="utf-8"))
            result = self.render_feedback(state, job, plan)
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
        result = self.render_feedback(state, job, plan)
        return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}

    def _revision(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        action = 'caption-export' if job['payload'].get('caption_only') else 'revise'
        result = self._process(state, job, action, {"plan": plan, "changes": job["payload"]["changes"]})
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
        return self._process(state, job, "register", {"plan_path": edit["plan_path"], "edit_id": edit["id"], "launch": job['payload'].get('launch', True)})

    def _accept(self, state, job, result, db=None):
        kind, p = job["kind"], job["payload"]
        if kind == 'suggest_edit':
            if result['base_edit_id'] != state.get('edit_id'):
                raise Conflict('수정안 준비 중 새 편집본이 만들어졌습니다. 새 영상에서 다시 요청하세요.')
            if self.feedback_hash(state.get('feedback', {})) != result['feedback_hash']:
                raise Conflict('요청 후 피드백이 변경되었습니다. 수정 요청을 다시 보내세요.')
            feedback = state.setdefault('feedback', {})
            feedback['base_edit_id'] = result['base_edit_id']
            changes = [{k:v for k,v in c.items() if k in {'beat_id','emphasis'}} for c in result['changes'] if 'emphasis' in c]
            if changes: feedback.pop('caption_only', None)
            by_id = {c['beat_id']:c for c in feedback.get('changes', [])}
            for c in changes: by_id.setdefault(c['beat_id'], {}).update(c)
            if by_id: feedback['changes'] = list(by_id.values())
            state['candidate_requests'] = [c['beat_id'] for c in result['changes'] if c.get('choose_candidates')]
            state['feedback_message'] = result['summary']
            state['feedback_revision'] = state.get('feedback_revision',0)+1
            return
        if kind == 'refresh_sources':
            # Append assets; existing renders and source references stay playable.
            hashes = {s['sha256'] for s in state['sources']}
            urls = {s.get('origin_url') for s in state['sources'] if s.get('origin_url')}
            added = [s for s in result['sources'] if s['sha256'] not in hashes and s.get('origin_url') not in urls]
            state['sources'].extend(added)
            state['source_search_manifest_path'] = result['source_search_manifest_path']
            state['source_search'] = {'status': 'done', 'message': f'추가 수집 완료 · 신규 {len(added)}개 / 보유 {len(state["sources"])}개', 'progress': 100}
            return
        if kind == "prepare":
            # Uploads may arrive while preparation is running. Never discard
            # them when the worker commits its earlier snapshot.
            incoming = list(result.get('sources', []))
            identity = lambda v: ('sha256', v['sha256']) if v.get('sha256') else ('path', v['path'])
            known = {identity(v) for v in incoming}
            incoming.extend(v for v in state['sources'] if identity(v) not in known)
            result = {**result, 'sources': incoming}
            state.update({k: v for k, v in result.items() if k != "text"})
            if not state["scripts"] and result.get('text'): self._script(state, result["text"], "recommended")
        elif kind == 'rewrite':
            state.update({k:v for k,v in result.items() if k != 'text'})
            if not state['scripts'] or enabled(state): self._script(state, result['text'], 'automatic_script_auto')
            if enabled(state): state['automation']['needs_top_pick'] = False
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
        elif kind == 'export':
            edit = next(e for e in state['edits'] if e['id'] == p['edit_id'])
            edit.update(result)
        if enabled(state) and db is not None:
            snapshot(state)
            if state.get('pending_reproduction'):
                self.activate_reproduction(state, db)
                return
        if state.get('automation', {}).get('active') and db is not None:
            self._advance_auto(state, db)
        elif state.get('automation', {}).get('paused_by_user'):
            state.update(status='paused', message='단계 결과 저장 완료 · 자동 진행 중지')

    def _advance_auto(self, state, db):
        if enabled(state):
            return self.advance_workflow(state, db)
        auto = state['automation']
        if not auto.get('active') or not state.get('sources'): return
        script = selected(state, 'scripts', 'script_id')
        voice = selected(state, 'voices', 'voice_id')
        edit = selected(state, 'edits', 'edit_id')
        if not script:
            stage, status, message = 'rewrite', 'rewriting', 'script_auto 대본 재가공 · 자동 선택 대기'
            self.store.enqueue(db, state['id'], stage, {}, 'rewrite:'+state['id'])
        elif not voice or voice['script_id'] != script['id']:
            stage, status, message = 'voice', 'voice_generating', '자동 선택 대본으로 VoiceBench 음성 생성'
            voice_id = 'voice-auto-' + script['id']
            state.update(approved_script_id=script['id'], pending_voice_id=voice_id)
            auto['script_selection'] = {'mode':'automatic', 'script_id':script['id']}
            self.store.enqueue(db, state['id'], stage,
                               {'voice_id':voice_id, 'script_id':script['id'], 'speed':1.0}, voice_id)
        elif not edit or edit['voice_id'] != voice['id']:
            if digest(voice['path']) != voice['sha256']: raise Conflict('자동 선택 음성의 파일이 변경됐습니다.')
            stage, status, message = 'edit', 'editing', '장면·자막 편집 및 리뷰 영상 생성'
            state.update(approved_voice_id=voice['id'])
            auto['voice_selection'] = {'mode':'automatic', 'voice_id':voice['id']}
            self.store.enqueue(db, state['id'], stage,
                               {'voice_id':voice['id'], 'script_id':script['id']}, 'edit:'+voice['id'])
        elif not edit.get('draft_path'):
            stage, status, message = 'register', 'registering', '리뷰 영상 완료 · CapCut 프로젝트 등록 중'
            self.store.enqueue(db, state['id'], stage, {'edit_id':edit['id'], 'launch':False}, 'register:'+edit['id'])
        else:
            stage, status, message = 'completed', 'draft_review', '자동 제작 완료 · 영상과 CapCut 프로젝트를 검토해 주세요'
            auto['completed_at'] = time.time()
        if auto.get('stage') != stage:
            self.store.event(db, state['id'], 'automatic_stage', {'stage':stage, 'message':message})
        auto['stage'] = stage
        state.update(status=status, message=message, error='', progress=0)
