"""Versioned automatic production. Feedback is staged, never a live input mutation."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from .studio_store import Conflict, uid
from .source_quality import sha256_file

STEPS = [('sources', '소스 확보'), ('transcript', '원본 대본 추출'),
         ('script', 'Top Pick 대본'), ('voice', 'TTS'), ('project', 'CapCut 프로젝트'), ('export', 'MP4 내보내기')]


def enabled(state):
    return state.get('automation', {}).get('protocol') == 2


def current_run(state):
    return next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), None)


def init_run(state):
    if current_run(state):
        return current_run(state)
    run = dict(id=uid('run-'), number=len(state.setdefault('runs', []))+1,
               created=time.time(), status='running', inputs={}, artifacts={})
    state['runs'].append(run)
    state['run_id'] = run['id']
    return run


def snapshot(state):
    run = init_run(state)
    run['artifacts'].update({k: copy.deepcopy(state.get(k)) for k in
        ('script_id', 'voice_id', 'edit_id', 'transcript_path', 'original_text', 'manifest_path')})
    ids = run['inputs'].get('source_ids')
    run['artifacts']['sources'] = copy.deepcopy([s for s in state['sources'] if ids is None or s['id'] in ids])
    script = next((s for s in state['scripts'] if s['id']==state.get('script_id')), {})
    pick = state.get('selected_candidate')
    candidates = state.get('script_candidates', [])
    if isinstance(pick,int) and 0<=pick<len(candidates) and candidates[pick].get('text')==script.get('text'):
        run['artifacts']['top_pick'] = copy.deepcopy(state.get('top_pick'))
    return run


def transient(exc):
    if isinstance(exc, (TimeoutError, ConnectionError, subprocess.TimeoutExpired)):
        return True
    text = str(exc).lower()
    if any(s in text for s in ('login', '로그인', 'captcha', '검증', '해시', '자료', 'api_key', '401', '403')):
        return False
    return any(s in text for s in ('timeout', 'timed out', '시간 초과', '연결하지 못', 'connection', 'http 429', 'http 502', 'http 503', 'http 504'))


def validate_edit_feedback(edit, changes):
    """Reject invalid editor input before it replaces a usable production run."""
    plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
    beats = {b['id']: b for b in plan['beats']}
    cues = {c['id']: dict(c) for c in plan['cues']}
    for change in changes:
        beat = beats.get(change['beat_id'])
        if beat is None:
            raise ValueError('존재하지 않는 구간입니다.')
        if 'shot_id' in change and change['shot_id'] not in {o['shot_id'] for o in beat['options']}:
            raise ValueError('제안된 장면 후보에서 선택하세요.')
        if 'emphasis' in change and (type(change['emphasis']) is not int or change['emphasis'] not in (0, 1, 2)):
            raise ValueError('잘못된 강조 강도')
        if 'text' in change:
            text = change['text']
            if not isinstance(text, str) or not text.strip() or '\n' in text.strip() or len(text.strip()) > 100:
                raise ValueError('자막은 비어 있지 않은 한 줄로 입력하세요.')
        cue = cues[beat['cue_id']]
        for key in ('start', 'end'):
            if key in change:
                value = float(change[key])
                if not math.isfinite(value):
                    raise ValueError('자막 시간은 숫자로 입력하세요.')
                cue[key] = value
    previous = 0
    for cue in cues.values():
        if not previous <= cue['start'] < cue['end'] <= plan['duration'] + .001:
            raise ValueError('자막 시간이 겹치거나 음성 범위를 벗어났습니다.')
        previous = cue['end']


def capcut_running():
    if os.name == 'nt':
        p = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq CapCut.exe', '/FO', 'CSV', '/NH'],
                           capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return b'capcut.exe' in p.stdout.lower()
    p = subprocess.run(['pgrep', '-ix', 'CapCut'], capture_output=True, timeout=15)
    return p.returncode == 0


class WorkflowMixin:
    def upload_source(self, task_id, stream, length, name):
        from .source_finder import probe_video
        self.store.get(task_id)
        suffix = Path(name).suffix.lower()
        if suffix not in {'.mp4','.mov','.webm'}: raise ValueError('MP4, MOV, WEBM 영상을 선택하세요.')
        path = self.folder(task_id)/'uploads'/(uid('source-')+suffix)
        path.parent.mkdir(exist_ok=True)
        try:
            with path.open('wb') as out:
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024*1024,remaining))
                    if not chunk: raise ValueError('업로드가 중단되었습니다.')
                    out.write(chunk)
                    remaining -= len(chunk)
            info = probe_video(path)
            if not info or float(info.get('duration') or 0) <= 0 or not info.get('width'): raise ValueError('재생 가능한 영상이 아닙니다.')
            sha = sha256_file(path)
            def add(s, db):
                if not any(v['sha256']==sha for v in s['sources']):
                    s['sources'].append(dict(id=path.stem,path=str(path),sha256=sha,origin_url='',rights='user_supplied',original_name=Path(name).name))
                self.store.event(db, task_id, 'source_uploaded', {'name':Path(name).name})
            saved = self.store.change(task_id,add)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        if not any(v['path']==str(path) for v in saved['sources']): path.unlink(missing_ok=True)
        return self.public(saved)

    def workflow_action(self, task_id, action, data):
        state = self.store.get(task_id)
        if action == 'use-sources':
            def continue_with_sources(s, db):
                ids = data.get('source_ids')
                available = {v['id']: v for v in s['sources']}
                if not isinstance(ids, list) or not ids or any(not isinstance(v, str) or v not in available for v in ids):
                    raise ValueError('제작에 사용할 영상을 한 개 이상 선택하세요.')
                if any(not Path(available[v]['path']).is_file() for v in ids):
                    raise ValueError('선택한 영상 파일이 없습니다. 영상을 다시 업로드하세요.')
                if s.get('automation', {}).get('stage', 'prepare') != 'prepare':
                    raise Conflict('이미 다음 제작 단계입니다. 소스 선택을 저장한 뒤 변경사항을 반영해 주세요.')
                if not s.get('automation') and s['status'] != 'preparing' and not (
                    s['status'] == 'attention' and db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='prepare' AND status='failed'", (task_id,)).fetchone()
                ):
                    raise Conflict('이미 대본 검토를 시작한 영상입니다. 현재 제작 단계를 먼저 마무리하세요.')
                if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status='running' AND kind NOT IN ('proposal','suggest_edit')", (task_id,)).fetchone():
                    raise Conflict('자료 작업이 실행 중입니다. 업로드한 영상은 보관되며, 현재 작업이 끝난 뒤 이어갈 수 있습니다.')
                db.execute("UPDATE jobs SET status='done' WHERE task_id=? AND kind='prepare' AND status IN ('queued','paused','failed')", (task_id,))
                if s.get('automation'):
                    s['automation'].update(active=True, paused_by_user=False, stage='prepare')
                if enabled(s):
                    run = snapshot(s)
                    run['status'] = 'running'
                    run['inputs']['source_ids'] = list(dict.fromkeys(ids))
                self.store.enqueue(db, task_id, 'prepare', {'source_ids': list(dict.fromkeys(ids))}, uid('manual-sources:'))
                s.update(status='preparing', error='', progress=0, message='선택한 영상으로 자료 준비를 이어갑니다')
                self.store.event(db, task_id, action, {'count': len(set(ids))})
            return self.public(self.store.change(task_id, continue_with_sources, data.get('revision')))
        if action == 'start-auto':
            def start(s, db):
                if s.get('automation') and not s.get('top_pick') and s.get('script_candidates'):
                    s['automation']['needs_top_pick'] = True
                s.setdefault('automation', {}).update(protocol=2, active=True, paused_by_user=False)
                init_run(s)
                # Existing manual work and its assets become the first version.
                if s.get('sources') and s.get('original_text'):
                    self._advance_auto(s, db)
                else:
                    self.store.enqueue(db, task_id, 'prepare', {}, 'prepare:'+task_id)
                self.store.event(db, task_id, 'start-auto', {})
            return self.public(self.store.change(task_id, start, data.get('revision')))
        if not enabled(state):
            return None
        actions = {'save-feedback', 'save-script', 'restore-script', 'apply-proposal', 'regenerate-voice',
                   'revise-edit', 'request-edit', 'reproduce', 'discard-feedback', 'select-candidate', 'discard-edit-feedback',
                   'save-captions', 'export-edit', 'make-video'}
        if action not in actions:
            return None
        def change(s, db):
            if data.get('feedback_revision') is not None and data['feedback_revision'] != s.get('feedback_revision',0):
                raise Conflict('다른 화면에서 피드백이 변경되었습니다. 최신 내용을 확인한 뒤 다시 저장하세요.')
            feedback = s.setdefault('feedback', {})
            if action == 'make-video':
                if 'text' in data:
                    text = str(data['text']).strip()
                    if not text or len(text) > 3000: raise ValueError('대본은 1~3000자로 입력하세요.')
                    feedback['script_text'] = text
            if action in {'save-captions','export-edit'}:
                edit = next((e for e in s['edits'] if e['id']==data.get('edit_id')), None)
                if not edit or edit['id'] != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 이전 영상의 수정 내용을 보관한 뒤 새 영상을 확인하세요.')
                if set(feedback)-{'changes','base_edit_id','caption_only'}:
                    raise Conflict('소스·대본·음성의 저장된 변경사항을 먼저 반영하거나 초기화한 뒤 자막을 편집하세요.')
                if feedback.get('base_edit_id',edit['id']) != edit['id']:
                    raise Conflict('이전 버전에 저장한 자막 수정이 있습니다. 보관 내용을 확인하고 구간 수정을 초기화한 뒤 새 영상을 편집하세요.')
                if any(set(c)-{'beat_id','text','start','end'} for c in feedback.get('changes',[])):
                    raise Conflict('저장된 장면·강조 수정이 있습니다. 먼저 반영하거나 구간 수정을 초기화하세요.')
                changes = data.get('changes')
                if not isinstance(changes,list) or any(not isinstance(c,dict) or not isinstance(c.get('beat_id'),str) or set(c)-{'beat_id','text','start','end'} for c in changes):
                    raise ValueError('자막 문구와 시간만 수정할 수 있습니다.')
                if len({c['beat_id'] for c in changes}) != len(changes): raise ValueError('중복된 자막 구간입니다.')
                validate_edit_feedback(edit,changes)
                plan=json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
                cues={c['id']:c for c in plan['cues']}; beats={b['id']:b for b in plan['beats']}
                changes=[c for c in changes if any(c[k]!=cues[beats[c['beat_id']]['cue_id']][k] for k in ('text','start','end') if k in c)]
                if action=='export-edit':
                    if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running') AND kind NOT IN ('refresh_sources','proposal','suggest_edit')",(task_id,)).fetchone():
                        raise Conflict('현재 제작 또는 내보내기가 끝나면 다시 내보낼 수 있습니다.')
                    if not changes and not edit.get('export_path'):
                        changes=[{'beat_id':b['id'],**{k:cues[b['cue_id']][k] for k in ('text','start','end')}} for b in plan['beats']]
                for k in ('changes','base_edit_id','caption_only'): feedback.pop(k,None)
                if changes: feedback.update(changes=copy.deepcopy(changes),base_edit_id=edit['id'],caption_only=True)
                if action=='save-captions' or not changes:
                    s['feedback_revision']=s.get('feedback_revision',0)+1
                    self.store.event(db,task_id,action,{})
                    return
            if action == 'discard-feedback':
                s['feedback'] = {}
            elif action == 'discard-edit-feedback':
                feedback.pop('changes', None)
                feedback.pop('base_edit_id', None)
                feedback.pop('caption_only', None)
            elif action in {'save-script', 'restore-script', 'apply-proposal', 'select-candidate'}:
                if action == 'save-script': text = str(data.get('text', '')).strip()
                elif action == 'restore-script': text = next(v['text'] for v in s['scripts'] if v['id'] == data['script_id'])
                elif action == 'select-candidate': text = s['script_candidates'][int(data['index'])]['text']
                else:
                    proposal = next(p for p in s['proposals'] if p['id'] == data['proposal_id'])
                    base = str(data.get('base_text', feedback.get('script_text') or next(v['text'] for v in s['scripts'] if v['id'] == s['script_id']))).strip()
                    if proposal.get('base_hash') and proposal['base_hash'] != hashlib.sha256(base.encode()).hexdigest():
                        raise Conflict('수정안 생성 후 대본이 바뀌었습니다. 다시 요청하세요.')
                    if proposal.get('original_text', s.get('reviewed_original_text', s['original_text'])) != s.get('reviewed_original_text', s['original_text']):
                        raise Conflict('원본 발화가 교정되었습니다. 교정한 발화를 기준으로 수정안을 다시 요청하세요.')
                    text = proposal['text']
                if not text or len(text) > 3000: raise ValueError('대본은 1~3000자로 입력하세요.')
                feedback['script_text'] = text
            elif action in {'save-feedback', 'regenerate-voice', 'make-video'}:
                if 'speed' in data:
                    speed = float(data['speed'])
                    if not math.isfinite(speed) or not .8 <= speed <= 1.25: raise ValueError('속도는 0.8~1.25배입니다.')
                    feedback['speed'] = speed
                if 'pronunciations' in data:
                    pairs = data['pronunciations']
                    if not isinstance(pairs, list) or len(pairs) > 50: raise ValueError('발음 교정 목록을 확인하세요.')
                    for pair in pairs:
                        if not isinstance(pair, dict) or not all(isinstance(pair.get(k), str) and 0 < len(pair[k]) <= 100 for k in ('from', 'to')):
                            raise ValueError('발음 교정은 원문과 읽을 발음을 입력하세요.')
                    feedback['pronunciations'] = pairs
                if 'source_ids' in data:
                    ids = data['source_ids']
                    if not isinstance(ids, list) or not set(ids) <= {v['id'] for v in s['sources']}:
                        raise ValueError('보유한 소스에서 선택하세요.')
                    feedback['source_ids'] = list(dict.fromkeys(ids))
                if action == 'regenerate-voice': feedback['regenerate_voice'] = True
            elif action == 'revise-edit':
                feedback.pop('caption_only', None)
                edit = next(e for e in s['edits'] if e['id'] == data['edit_id'])
                if s.get('edit_id') and edit['id'] != s['edit_id']:
                    raise Conflict('새 편집 영상이 준비되었습니다. 입력 내용을 보관한 뒤 새로고침하여 새 영상의 구간을 확인하세요.')
                changes = data.get('changes', [])
                if not isinstance(changes, list) or not changes: raise ValueError('수정할 구간을 선택하세요.')
                if feedback.get('base_edit_id', edit['id']) != edit['id']: raise Conflict('다른 편집 버전의 수정이 저장되어 있습니다.')
                feedback['base_edit_id'] = edit['id']
                by_id = {c['beat_id']: c for c in feedback.get('changes', [])}
                for c in changes:
                    if not isinstance(c, dict) or not isinstance(c.get('beat_id'), str): raise ValueError('올바르지 않은 구간')
                    by_id.setdefault(c['beat_id'], {}).update(c)
                validate_edit_feedback(edit, list(by_id.values()))
                feedback['changes'] = list(by_id.values())
            elif action == 'request-edit':
                if data.get('edit_id') != s.get('edit_id'):
                    raise Conflict('새 편집 영상이 준비되었습니다. 새로고침하여 수정할 구간을 확인하세요.')
                request = str(data.get('request', '')).strip()
                if not request: raise ValueError('수정 요청을 입력하세요.')
                self.store.enqueue(db, task_id, 'suggest_edit', {**data, 'feedback_hash': self.feedback_hash(feedback)}, uid('suggest:'))
            if action in {'reproduce','export-edit','make-video'}:
                if s.get('pending_reproduction'): raise Conflict('이미 재제작이 대기 중입니다.')
                if not feedback: raise ValueError('반영할 변경사항을 먼저 저장하세요.')
                if feedback.get('changes') and any(k in feedback for k in ('script_text', 'speed', 'pronunciations', 'regenerate_voice', 'source_ids')):
                    raise Conflict('대본·음성·소스를 바꾸면 장면 구성이 달라집니다. 구간 수정만 초기화한 뒤 재제작하고, 새 영상에서 장면·자막을 조정하세요. 기존 완성본은 보존됩니다.')
                ids = feedback.get('source_ids', [v['id'] for v in s['sources']])
                if not ids: raise ValueError('사용할 소스를 한 개 이상 선택하세요.')
                snapshot(s)
                # Reproduce is an explicit start request. A later pause must
                # remain authoritative when the running step eventually ends.
                s['automation'].update(active=True, paused_by_user=False)
                s['pending_reproduction'] = copy.deepcopy(feedback)
                s['feedback'] = {}
                db.execute("UPDATE jobs SET status='superseded' WHERE task_id=? AND status IN ('queued','paused') AND kind NOT IN ('refresh_sources','proposal','suggest_edit')", (task_id,))
                if not db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status='running' AND kind NOT IN ('refresh_sources','proposal','suggest_edit')", (task_id,)).fetchone():
                    self.activate_reproduction(s, db)
                else:
                    s['message'] = '현재 단계 결과 저장 후 수정본 제작으로 전환합니다'
            self.store.event(db, task_id, action, {})
            s['feedback_revision'] = s.get('feedback_revision',0)+1
        return self.public(self.store.change(task_id, change, None if 'feedback_revision' in data else data.get('revision')))

    @staticmethod
    def feedback_hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def activate_reproduction(self, s, db):
        if s.get('automation', {}).get('paused_by_user'):
            return
        feedback = s.pop('pending_reproduction')
        old = snapshot(s)
        if old['status'] != 'completed': old['status'] = 'superseded'
        old_inputs = copy.deepcopy(old['inputs'])
        old_inputs.pop('changes', None)
        old_inputs.pop('regenerate_voice', None)
        old_inputs.update(feedback)
        s.pop('run_id', None)
        run = init_run(s)
        run.update(inputs=old_inputs, parent_id=old['id'])
        if 'script_text' in feedback:
            self._script(s, feedback['script_text'], 'manual')
            s['automation']['needs_top_pick'] = False
        if any(k in feedback for k in ('script_text', 'pronunciations', 'speed', 'regenerate_voice')):
            s.update(voice_id=None, approved_voice_id=None, edit_id=None)
        elif 'source_ids' in feedback:
            s['edit_id'] = None
        s['automation'].update(active=True, paused_by_user=False)
        s.update(error='', progress=0)
        if feedback.get('changes') and not any(k in feedback for k in ('script_text','pronunciations','speed','regenerate_voice','source_ids')):
            edit = next(e for e in s['edits'] if e['id'] == feedback['base_edit_id'])
            self.store.enqueue(db, s['id'], 'revision', {'edit_id':edit['id'], 'script_id':edit['script_id'],
                'voice_id':edit['voice_id'], 'changes':feedback['changes'], 'caption_only':bool(feedback.get('caption_only'))}, 'revision:'+run['id'])
            s.update(status='editing', message='수정한 자막으로 MP4 내보내기 중' if feedback.get('caption_only') else '저장한 장면·자막 수정으로 새 버전 제작 중')
        else:
            self._advance_auto(s, db)

    def advance_workflow(self, s, db):
        from .studio import selected, digest
        run = snapshot(s)
        if s.get('pending_reproduction'):
            self.activate_reproduction(s, db)
            return
        if not s['automation'].get('active') or not s.get('sources'): return
        script, voice, edit = (selected(s, c, k) for c, k in [('scripts','script_id'), ('voices','voice_id'), ('edits','edit_id')])
        key = run['id']
        if not script or s['automation'].get('needs_top_pick'):
            stage, status, message, payload = 'rewrite', 'rewriting', '후보 대본 비교 · Top Pick 선정 중', {}
        elif not voice or voice['script_id'] != script['id']:
            stage, status, message = 'voice', 'voice_generating', '선정 대본으로 TTS 생성 중'
            voice_id = 'voice-'+key
            s.update(approved_script_id=script['id'], pending_voice_id=voice_id)
            text = script['text']
            for pair in run['inputs'].get('pronunciations', []): text = text.replace(pair['from'], pair['to'])
            payload = dict(script_id=script['id'], voice_id=voice_id, speed=run['inputs'].get('speed',1), spoken_text=text)
            if run['inputs'].get('regenerate_voice'):
                payload['generation_key'] = key
            s['automation']['script_selection'] = {'mode':'automatic','script_id':script['id']}
        elif not edit or edit['voice_id'] != voice['id']:
            if digest(voice['path']) != voice['sha256']: raise Conflict('음성 파일이 변경되었습니다.')
            stage, status, message = 'edit', 'editing', '장면·자막 구성 및 프로젝트 생성 중'
            s['approved_voice_id'] = voice['id']
            s['automation']['voice_selection'] = {'mode':'automatic','voice_id':voice['id']}
            payload = dict(script_id=script['id'], voice_id=voice['id'], source_ids=run['inputs'].get('source_ids'),
                           changes=run['inputs'].get('changes',[]), base_edit_id=run['inputs'].get('base_edit_id'))
        elif not edit.get('draft_path') and not edit.get('export_verified'):
            stage, status, message, payload = 'register', 'registering', 'CapCut 프로젝트 등록 중', {'edit_id':edit['id'], 'launch':False}
        elif not edit.get('export_path'):
            stage, status, message, payload = 'export', 'exporting', 'CapCut 최종 MP4 내보내기 중', {'edit_id':edit['id']}
        else:
            run.update(status='completed', completed=time.time())
            s['latest_completed_run_id'] = run['id']
            s['automation'].update(stage='completed', completed_at=time.time())
            s.update(status='completed', message='수정한 자막으로 MP4 내보내기 완료' if edit.get('export_kind')=='web_captions' else 'CapCut 최종 영상 내보내기 완료', progress=100, error='')
            return
        self.store.enqueue(db, s['id'], stage, payload, stage+':'+key)
        if s['automation'].get('stage') != stage:
            self.store.event(db, s['id'], 'automatic_stage', {'stage':stage, 'message':message})
        s['automation']['stage'] = stage
        s.update(status=status, message=message, progress=0, error='')

    def _export(self, state, job):
        from .editing_adapter import AutoCapcutAdapter
        edit = next(e for e in state['edits'] if e['id'] == job['payload']['edit_id'])
        result = AutoCapcutAdapter(self.settings).export(job_id=job['id'], draft_name=edit['draft_name'], draft_path=Path(edit['draft_path']))
        if result.get('width')!=1080 or result.get('height')!=1920 or abs(result.get('fps',0)-30)>.01:
            raise ValueError('최종 영상이 1080×1920 · 30fps 규격과 다릅니다. CapCut 내보내기 설정을 확인하세요.')
        target = self.folder(state['id']) / job['id'] / 'final.mp4'
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(result['video_path'], target)
        return {'export_path':str(target), 'export_verified':result['verified'], 'exported_at':time.time()}

    def render_feedback(self, state, job, plan):
        """Rebind scene IDs by source identity and narration, never by list position."""
        import difflib
        changes = copy.deepcopy(job['payload'].get('changes', []))
        if not changes: return self._process(state, job, 'render', {'plan':plan})
        base = next(e for e in state['edits'] if e['id']==job['payload']['base_edit_id'])
        old = json.loads(Path(base['plan_path']).read_text(encoding='utf-8'))
        used = set()
        for change in changes:
            beat = next(b for b in old['beats'] if b['id']==change['beat_id'])
            matches = sorted([(difflib.SequenceMatcher(None,beat['text'],b['text']).ratio(),b) for b in plan['beats'] if b['id'] not in used],key=lambda v:v[0],reverse=True)
            if not matches or matches[0][0]<.65 or len(matches)>1 and matches[0][0]==matches[1][0]:
                raise ValueError('대본 변경으로 수정 구간을 확실히 연결하지 못했습니다. 구간 피드백을 조정해 주세요.')
            target = matches[0][1]; used.add(target['id']); change['beat_id']=target['id']
            if 'shot_id' in change:
                shot = next(v for v in old['shots'] if v['id']==change['shot_id'])
                replacement = next((v for v in plan['shots'] if v['sha256']==shot['sha256'] and abs(v['start']-shot['start'])<.01),None)
                if not replacement: raise ValueError('선택했던 장면이 새 소스 구성에 없습니다. 장면 피드백을 조정해 주세요.')
                change['shot_id']=replacement['id']
                if not any(o['shot_id']==replacement['id'] for o in target['options']):
                    target['options'].append({'shot_id':replacement['id'],'relation':'illustration','reason':'사용자가 선택한 장면'})
        return self._process(state, job, 'revise', {'plan':plan,'changes':changes})

    def _suggest_edit(self, state, job):
        from .studio_ai import plan_revision
        p = job['payload']
        edit = next(e for e in state['edits'] if e['id'] == p['edit_id'])
        plan = json.loads(Path(edit['plan_path']).read_text(encoding='utf-8'))
        start, end = float(p.get('start',0)), float(p.get('end') or plan['duration'])
        if not 0 <= start < end <= plan['duration']+.001: raise ValueError('수정 구간을 확인하세요.')
        return {**plan_revision(self.settings, plan, p['request'], start, end), 'base_edit_id':edit['id'], 'feedback_hash':p['feedback_hash']}

    def pipeline(self, state):
        runs = copy.deepcopy(state.get('runs', []))
        if not runs:
            runs = [dict(id='legacy', number=1, status='legacy', artifacts={
                **{k:state.get(k) for k in ('script_id','voice_id','edit_id','original_text','transcript_path')}, 'sources':state['sources']})]
        for run in runs:
            if run['id']==state.get('run_id') and run['status'] not in {'completed','superseded'}:
                if state.get('error'): run['status']='failed'
                elif state['status'] in {'waiting_capcut','retry_wait','paused'}: run['status']='waiting'
            a = run['artifacts']
            script = next((v for v in state['scripts'] if v['id']==a.get('script_id')), {})
            voice = next((v for v in state['voices'] if v['id']==a.get('voice_id')), {})
            edit = next((v for v in state['edits'] if v['id']==a.get('edit_id')), {})
            available = {'sources':any(Path(v['path']).is_file() for v in a.get('sources', [])),
                'transcript':bool(a.get('original_text')), 'script':bool(script.get('path') and Path(script['path']).is_file()),
                'voice':bool(voice.get('path') and Path(voice['path']).is_file()),
                'project':bool(edit.get('portable_draft_path') and Path(edit['portable_draft_path']).is_dir()),
                'export':bool(edit.get('export_verified') and edit.get('export_path') and Path(edit['export_path']).is_file())}
            stage = state.get('automation', {}).get('stage', 'prepare')
            active_key = {'prepare':'sources','rewrite':'script','voice':'voice','edit':'project','register':'project','export':'export'}.get(stage)
            run['steps'] = []
            for key, label in STEPS:
                status = 'completed' if available[key] else 'pending'
                if run['id'] == state.get('run_id') and key == active_key and not available[key]:
                    status = 'failed' if state.get('error') else 'waiting' if state['status'] in ('waiting_capcut','retry_wait','paused') else 'running'
                if run['status']=='superseded' and status=='pending': status='superseded'
                run['steps'].append(dict(key=key,label=label,status=status,
                    download_url=f"/api/studio/{state['id']}/download?run={run['id']}&asset={key}" if available[key] else None))
            if not a.get('top_pick'):
                run['steps'][2]['label'] = '제작 대본 · 기존 선택'
            run['preview_url'] = self.media_url(state['id'], edit['preview_path']) if edit.get('preview_path') and Path(edit['preview_path']).is_file() else None
            run['video_url'] = self.media_url(state['id'], edit['export_path']) if available['export'] else None
        return runs

    def download(self, task_id, run_id, asset):
        state = self.store.get(task_id)
        run = next((r for r in self.pipeline(state) if r['id']==run_id), None)
        if not run or not any(s['key']==asset and s['download_url'] for s in run['steps']): raise ValueError('완료된 결과물이 없습니다.')
        a = run['artifacts']
        target_dir = self.folder(task_id) / 'downloads' / run_id
        target_dir.mkdir(parents=True, exist_ok=True)
        if asset == 'transcript':
            target = target_dir/'original.txt'
            target.write_text(a['original_text'], encoding='utf-8')
            return target
        collection, key, field = {'script':('scripts','script_id','path'), 'voice':('voices','voice_id','path'),
                                  'export':('edits','edit_id','export_path'), 'project':('edits','edit_id','portable_draft_path')}.get(asset, ('','',''))
        if collection:
            item = next(v for v in state[collection] if v['id']==a[key])
            if asset != 'project': return Path(item[field])
        target = target_dir / (asset+'.zip')
        # Atomic replacement supports simultaneous downloads without partial ZIPs.
        temp = target.with_name(uid('bundle-')+'.zip')
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_STORED) as archive:
            if asset == 'sources':
                for i, source in enumerate(a.get('sources', [])):
                    path = Path(source['path'])
                    if path.is_file(): archive.write(path, f"{i+1:02}-{path.name}")
                archive.writestr('provenance.json', json.dumps(a['sources'], ensure_ascii=False, indent=2))
            else:
                root = Path(item[field])
                for path in root.rglob('*'):
                    if path.is_file(): archive.write(path, (Path(root.name)/path.relative_to(root)).as_posix())
                archive.writestr('README.txt', 'CapCut 프로젝트와 studio-assets 미디어입니다. 다른 PC에서는 미디어 위치를 다시 연결해야 할 수 있습니다.')
        os.replace(temp, target)
        return target
