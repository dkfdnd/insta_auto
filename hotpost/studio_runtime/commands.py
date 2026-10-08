"""User commands and atomic edits to Studio state."""
from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path

from ..editing_adapter import _atomic_json
from ..studio_store import Conflict, uid
from ..studio_workflow import enabled, init_run
from .common import digest, selected


class CommandsMixin:
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

    def _command_regenerate_script(self, task_id, data):
        action = 'regenerate-script'
        product = str(data.get('product','')).strip()
        instructions = str(data.get('instructions','')).strip()
        product_url = str(data.get('product_url','')).strip()
        evidence_mode = data.get('evidence_mode','research')
        if evidence_mode not in {'research','reference'}:
            raise ValueError('상품 조사 또는 원본 영상 관찰 모드를 선택하세요.')
        from urllib.parse import urlparse
        if not product or len(product)>300 or len(instructions)>1500:
            raise ValueError('대상 상품은 1~300자, 수정 지침은 1500자 이하로 입력하세요.')
        if product_url and (len(product_url)>2000 or urlparse(product_url).scheme not in {'http','https'} or not urlparse(product_url).hostname):
            raise ValueError('상품 링크는 올바른 http 또는 https 주소로 입력하세요.')
        def regenerate(s, db):
            if not s.get('original_text') or not s.get('reference_video') or not s.get('sources'):
                raise ValueError('원본 영상·발화·사용 소스를 먼저 확보하세요.')
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                raise Conflict('진행 중인 작업이 끝난 뒤 새 대본을 생성하세요.')
            # A completed version remains untouched; this action recovers
            # failed rewrite steps, not an alternate edit-version path.
            if s.get('script_id') or s.get('edit_id'):
                raise Conflict('이미 제작한 대본이 있습니다. 대본 수정 기능으로 새 버전을 만드세요.')
            attempt = uid('rewrite-')
            s.setdefault('rewrite_history', []).append({'studio_job_id':s.get('studio_job_id'),
                'product':s.get('product'), 'product_url':s.get('product_url_override',''),
                'script_candidates':copy.deepcopy(s.get('script_candidates',[])),
                'error':s.get('error'), 'at':time.time()})
            s.update(product=product, product_override=product, rewrite_instructions=instructions,
                     product_url_override=product_url, evidence_mode=evidence_mode, script_candidates=[], top_pick=None, selected_candidate=None,
                     studio_job_id=None, status='rewriting', error='', progress=0,
                     message='바로잡은 상품과 근거로 새 대본 생성 대기')
            s.setdefault('automation', {}).update(protocol=2,active=True,paused_by_user=False,stage='rewrite',needs_top_pick=False)
            init_run(s)
            # Older attempts remain auditable but cannot be revived by
            # retry/resume while the corrected request is being processed.
            db.execute("UPDATE jobs SET status='superseded' WHERE task_id=? AND kind='rewrite' AND status IN ('failed','paused')", (task_id,))
            self.store.enqueue(db, task_id, 'rewrite', {}, attempt)
            db.execute('UPDATE jobs SET checkpoint=? WHERE key=?',
                       (json.dumps({'generation_key':attempt}),attempt))
            self.store.event(db, task_id, action, {'product':product,'attempt':attempt})
        return self.public(self.store.change(task_id,regenerate,data.get('revision')))

    def _command_caption_preview(self, task_id, data):
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

    def _command_check_script(self, task_id, data):
        # A read-only request; never hold the task DB lock across HTTP or
        # save/approve text merely because the user asked to inspect it.
        from ..studio_adapter import StudioAdapter
        text = str(data.get('text', ''))
        if not text.strip() or len(text) > 3000:
            raise ValueError('대본은 1~3000자로 입력하세요.')
        state = self.store.get(task_id)
        try:
            return StudioAdapter(self.settings).review(text, state.get('reviewed_original_text', state['original_text']),
                evidence_mode='self_shot' if state.get('creation_mode') == 'self_shot' else
                    'benchmark' if state.get('benchmark_analysis') else 'research')
        except (RuntimeError, OSError) as exc:
            raise ValueError('내장 대본 검사를 완료하지 못했습니다. 입력 내용은 그대로 유지됩니다.') from exc

    def action(self, task_id, action, data):
        own = self.store.get(task_id)
        if own.get('creation_mode') == 'self_shot':
            if action == 'save-self-shot-brief':
                return self.save_self_shot_brief(task_id, data)
            if action in {'refresh-sources', 'retry-automatic-sources'}:
                raise ValueError('내 촬영 영상 작업은 직접 추가한 영상만 사용합니다.')
            if action in {'start-auto', 'resume-auto'} and own.get('self_shot', {}).get('started') is not True:
                return self.start_self_shot(task_id, data)
        if action == 'add-script-candidate':
            from ..script_candidate_versions import add_candidate
            return self.public(add_candidate(self.store, task_id, data))
        if action == 'regenerate-script':
            return self._command_regenerate_script(task_id, data)
        if action == 'prepare-caption-preview':
            return self._command_caption_preview(task_id, data)
        if action == 'check-script':
            return self._command_check_script(task_id, data)
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
                state['automation']['pause_reason'] = action
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
                self.release_source_hold(state)
                hold = state.pop('editorial_content_hold', None)
                if hold:
                    state.setdefault('editorial_review_history', []).append(hold)
                    self.store.event(db, task_id, 'editorial_hold_released', hold)
                state['error'] = ''
                state['automation']['active'] = True
                state['automation'].pop('consumed_by_daily_policy', None)
                state['automation']['selection_mode'] = 'manual_resume'
                state['automation'].pop('paused_by_user', None)
                state['automation'].pop('pause_reason', None)
                if enabled(state):
                    db.execute("UPDATE jobs SET status='queued' WHERE task_id=? AND status='paused'", (task_id,))
                if not state.get('original_text') or (not state.get('reference_video') and state.get('creation_mode') != 'self_shot'):
                    self.store.enqueue(db, task_id, 'prepare', {}, 'prepare:'+task_id)
                    state.update(status='preparing', message='자료 준비 재개', error='')
                pending_prepare = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='prepare' AND status IN ('queued','running','paused')", (task_id,)).fetchone()
                if pending_prepare:
                    state.update(status='preparing', message='자료 준비 대기', error='')
                else:
                    self._advance_auto(state, db)
                self.store.event(db, task_id, action, {})
                return
            if action == 'refresh-sources':
                if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('prepare','refresh_sources','collect_sources') AND status IN ('queued','running')", (task_id,)).fetchone():
                    raise Conflict('자료 수집이 이미 대기 중이거나 실행 중입니다.')
                request = str(data.get('request', ''))[:1000]
                self.release_source_hold(state)
                if data.get('retry_job_id'):
                    failed = db.execute("SELECT payload FROM jobs WHERE id=? AND task_id=? AND kind='refresh_sources' AND status='failed'",
                                        (data['retry_job_id'], task_id)).fetchone()
                    if not failed:
                        raise Conflict('재시도할 소스 검색이 변경되었습니다. 최신 상태를 확인하세요.')
                    request = json.loads(failed['payload']).get('request', '')
                from ..source_policy import adopt_policy
                policy = adopt_policy(state, self.settings)
                self.store.enqueue(db, task_id, 'refresh_sources', {'request':request, 'source_policy':policy}, uid('sources:'))
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
                row = (db.execute("SELECT * FROM jobs WHERE task_id=? AND id=? AND status='failed'", (task_id,data['job_id'])).fetchone()
                       if data.get('job_id') else db.execute("SELECT * FROM jobs WHERE task_id=? AND status='failed' ORDER BY updated DESC LIMIT 1", (task_id,)).fetchone())
                if not row: return
                if row['kind'] == 'collect_sources':
                    self.release_source_hold(state)
                    checkpoint=json.loads(row['checkpoint'])
                    checkpoint.update(auto_retries=0,not_before=0)
                    db.execute("UPDATE jobs SET status='queued',error='',checkpoint=? WHERE id=?",(json.dumps(checkpoint),row['id']))
                    state['source_search']={'status':'queued','message':'소스 수집 재시도 대기','progress':0}
                    self.store.event(db,task_id,'retry_sources',{'job_id':row['id']})
                    return  # A source retry must not erase an independent TTS failure.
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
                    if row['kind']=='rewrite':
                        previous=checkpoint.pop('studio_job_id',None)
                        if previous:
                            checkpoint.setdefault('previous_studio_job_ids',[]).append(previous)
                        # The remote generation may have completed while all
                        # candidates failed Hotpost's review. Reusing that
                        # completed response can never repair the script.
                        checkpoint['generation_key']=uid('rewrite-retry-')
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
