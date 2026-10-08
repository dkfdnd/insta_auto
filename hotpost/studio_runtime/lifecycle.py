"""Worker lanes, completion handling, and legacy automatic advancement."""
from __future__ import annotations

import time
from pathlib import Path

from ..studio_store import Conflict
from ..studio_workflow import enabled, init_run, snapshot, current_run, capcut_running, transient
from .common import digest, selected


class LifecycleMixin:
    def _watch_top(self):
        from ..studio_automation import enqueue_latest
        while not self.stop.is_set():
            try:
                enqueue_latest(self.settings)
            except (OSError, ValueError, KeyError):
                pass  # A report may not exist yet; the collection hook also enqueues.
            self.stop.wait(30)

    def _worker(self, lane=None):
        while not self.stop.is_set():
            job = self.store.claim(lane)
            if not job:
                self.stop.wait(.6); continue
            try:
                state = self.store.get(job["task_id"])
                if enabled(state) and not current_run(state):
                    state = self.store.change(state['id'], lambda s, db: init_run(s))
                if enabled(state) and state.get('pending_reproduction') and job['kind'] not in {'collect_sources','refresh_sources','proposal','suggest_edit'}:
                    self.store.finish(job, {}, lambda s, db, r: self.activate_reproduction(s, db))
                    continue
                if job['kind'] in {'register', 'export'} and not job['payload'].get('launch') and capcut_running():
                    edit = next((e for e in state['edits'] if e['id'] == job['payload'].get('edit_id')), {})
                    portable_ready = Path(edit.get('portable_draft_path') or '__missing__').joinpath('draft_content.json').is_file()
                    if job['kind'] == 'register' and enabled(state) and portable_ready:
                        # A user's open editor must not block an already rendered
                        # automatic MP4. Keep the portable draft without claiming
                        # it was registered in the running native application.
                        self.store.finish(job, {'registration_deferred': True,
                            'registration_note': 'CapCut 사용 중 · 편집 가능한 프로젝트는 보존하고 MP4를 먼저 내보냅니다.'},
                            lambda s, db, r: self._accept(s, job, r, db))
                        continue
                    registered = (job['kind'] == 'export' and any(
                        e['id'] == job['payload'].get('edit_id') and (e.get('draft_path')
                        or (e.get('registration_deferred') and portable_ready)) for e in state['edits']))
                    if registered:
                        # The editable draft is already registered. Exporting
                        # its saved plan on the web path does not touch an open
                        # CapCut session or any user edits in that draft.
                        job['checkpoint'].setdefault('native_export_unavailable',
                            'CapCut 창이 열려 있어 저장된 장면·음성·자막으로 웹 내보내기')
                        self.store.checkpoint(job['id'], job['checkpoint'])
                    else:
                        self.store.defer(job, 'CapCut 종료 대기 · 저장하고 앱을 닫으면 자동으로 이어집니다', 15, waiting=True)
                        continue
                payload = job["payload"]
                if "script_id" in payload and payload["script_id"] != state["script_id"]:
                    self.store.finish(job, {}, lambda *_: None); continue
                result = getattr(self, "_" + job["kind"])(state, job)
                self.store.finish(job, result, lambda s, db, r: self._accept(s, job, r, db))
            except Exception as exc:
                from ..collectors.base import CollectionBlocked
                if isinstance(exc, CollectionBlocked) and exc.reason == 'profile_busy':
                    # Daily collection owns this same saved login profile. Waiting
                    # for its lease is not a failed download or an auth retry.
                    self.store.defer(job, 'Instagram 브라우저 사용 종료 대기 · 비면 자동으로 이어집니다',
                                     30, waiting=True, waiting_status='retry_wait')
                elif job['kind'] == 'collect_sources':
                    self.handle_source_error(job, exc)
                elif enabled(self.store.get(job['task_id'])) and transient(exc) and job['checkpoint'].get('auto_retries', 0) < 2:
                    self.store.defer(job, str(exc), 15 * (job['checkpoint'].get('auto_retries', 0)+1))
                else:
                    self.store.fail(job, exc)
                    state = self.store.get(job['task_id'])
                    if enabled(state) and state.get('pending_reproduction'):
                        self.store.change(state['id'], lambda s, db: self.activate_reproduction(s, db))

    def _accept(self, state, job, result, db=None):
        kind, p = job["kind"], job["payload"]
        if kind == 'collect_sources':
            self.accept_source_round(state, job, result, db)
            if (current_run(state) or {}).get('status') != 'completed':
                snapshot(state)
            return
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
            from ..source_search.strategy import merge_history, restore_history
            record = state.setdefault('source_acquisition', {})
            restore_history(record)
            record['queries'] = merge_history(record.get('queries', []), result.get('searches', []))
            record['urls'] = list(dict.fromkeys([*record.get('urls', []), *result.get('attempted_urls', [])]))
            # Append assets; existing renders and source references stay playable.
            hashes = {s['sha256'] for s in state['sources']}
            urls = {s.get('origin_url') for s in state['sources'] if s.get('origin_url')}
            added = [s for s in result['sources'] if s['sha256'] not in hashes and s.get('origin_url') not in urls]
            state['sources'].extend(added)
            state['source_search_manifest_path'] = result['source_search_manifest_path']
            state.setdefault('source_acquisition', {}).setdefault('rounds', []).append({
                'job_id':job.get('id'), 'manifest_path':result['source_search_manifest_path'],
                'source_policy':result.get('source_policy'), 'platform_outcomes':result.get('platform_outcomes', {})})
            state['source_search'] = {'status': 'done', 'message': f'추가 수집 완료 · 신규 {len(added)}개 / 보유 {len(state["sources"])}개', 'progress': 100}
            goal = result.get('platform_targets', {}).get('tiktok')
            if goal:
                state['source_search']['message'] += f" · TikTok {goal['usable']}/{goal['target']}개"
                if goal['status'] != 'met':
                    state['source_search']['message'] += ' · 목표 미달/검색 미완료 (검색 기록 확인)'
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
            if not state["scripts"] and result.get('text'): self._script(state, result["text"], result.get('script_origin', "recommended"))
        elif kind == 'rewrite':
            state.update({k:v for k,v in result.items() if k != 'text'})
            if not state['scripts'] or enabled(state): self._script(state, result['text'], 'automatic_codex')
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
            if result.get('registration_deferred'):
                edit.update(registration_deferred=True, registration_note=result['registration_note'])
                state.update(message=result['registration_note'], error='')
            else:
                edit.update(draft_path=result["draft_path"], draft_name=result["draft_name"])
                edit.pop('registration_deferred', None)
                edit.pop('registration_note', None)
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
            stage, status, message = 'rewrite', 'rewriting', 'Codex 대본 집필·검사 중'
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
