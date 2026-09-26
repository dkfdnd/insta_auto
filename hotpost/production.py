"""Durable orchestration: acquired assets -> selected rewrite -> WAV -> draft.

Each service owns its domain. This module only stores handoffs and dispatches
their public interfaces. Interrupted work is resumed explicitly, never blindly
replayed on server startup.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .editing_adapter import AutoCapcutAdapter, _atomic_json
from .storage import Storage
from .studio_adapter import StudioAdapter
from .voicebench_adapter import VoiceBenchAdapter


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


@contextmanager
def file_lock(path):
    """OS lock survives threads/processes correctly and releases after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('진행 중인 제작 작업이 있습니다. 완료 후 다시 시도하세요.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ProductionManager:
    def __init__(self, settings, studio=None, voice=None, editor=None):
        self.settings = settings
        self.root = settings.production_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.studio = studio or StudioAdapter(settings)
        self.voice = voice or VoiceBenchAdapter(settings)
        self.editor = editor or AutoCapcutAdapter(settings)

    def folder(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('잘못된 제작 ID')
        return self.root / job_id

    def get(self, job_id):
        path = self.folder(job_id) / 'production.json'
        if not path.is_file():
            raise ValueError('제작 작업을 찾지 못했습니다.')
        return json.loads(path.read_text('utf-8'))

    def save(self, job, **changes):
        job.update(changes, updated_at=time.time())
        _atomic_json(self.folder(job['id']) / 'production.json', job)

    def listing(self):
        rows = [self.get(path.parent.name) for path in self.root.glob('*/production.json')]
        return sorted(rows, key=lambda row: row['created_at'], reverse=True)[:100]

    def public(self, job):
        try:
            with file_lock(self.folder(job['id']) / 'job.lock'):
                running = False
        except ValueError:
            running = True
        return {**job, 'running': running}

    def asset_path(self, value):
        path = Path(value).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(self.settings.data_dir.resolve()):
            raise ValueError('자료 경로가 insta_auto 데이터 폴더 밖입니다.')
        return path

    def create(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('제작 정보가 필요합니다.')
        product = str(payload.get('product', '')).strip()
        if not product or len(product) > 300:
            raise ValueError('정확한 상품명(1~300자)이 필요합니다.')
        store = Storage(self.settings.db_path)
        try:
            source = store.job_for(str(payload.get('source_job_id', '')))
            transcript = store.job_for(str(payload.get('transcript_job_id', '')))
        finally:
            store.close()
        for row, kind in ((source, 'source'), (transcript, 'transcript')):
            if not row or row['kind'] != kind or row['status'] != 'done':
                raise ValueError('같은 릴스의 소스 확보·대본 추출을 먼저 완료하세요.')
        if source['shortcode'] != transcript['shortcode']:
            raise ValueError('소스와 대본의 기준 릴스가 다릅니다.')
        transcript_path = self.asset_path(transcript['result']['json_path'])
        original = json.loads(transcript_path.read_text('utf-8'))
        reference = '\n'.join(str(row.get('text', '')).strip()
                              for row in original.get('speech', []) if row.get('text'))
        if not reference.strip():
            raise ValueError('음성 전사문이 없습니다. 화면 OCR을 음성 대본으로 대체하지 않습니다.')
        reference_video = self.asset_path(transcript_path.parent / 'reference.mp4')
        source_result = source['result']
        manifest_path = self.asset_path(Path(source_result['zip_path']).parent / 'manifest.json')
        manifest = json.loads(manifest_path.read_text('utf-8'))
        assets = []
        for item in manifest.get('candidates', []):
            if not item.get('selected_for_zip') or not item.get('downloaded_file'):
                continue
            path = self.asset_path(manifest_path.parent / item['downloaded_file'])
            if not path.is_relative_to(manifest_path.parent):
                raise ValueError('소스 manifest의 파일 경로가 잘못되었습니다.')
            assets.append({'id': str(len(assets)), 'path': str(path),
                           'sha256': file_digest(path), 'source': item})
        if not assets:
            raise ValueError('사용 가능한 로컬 소스 영상이 없습니다.')
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'contract_version': '1.0', 'created_at': time.time(),
               'shortcode': source['shortcode'], 'status': 'acquired',
               'product': product, 'product_url': str(payload.get('product_url', ''))[:2000],
               'notes': str(payload.get('notes', ''))[:2000],
               'reference_script': reference, 'reference_video': str(reference_video),
               'reference_sha256': file_digest(reference_video),
               'transcript_path': str(transcript_path), 'manifest_path': str(manifest_path),
               'source_job_id': source['id'], 'transcript_job_id': transcript['id'],
               'assets': assets, 'revision': 0, 'error': ''}
        self.save(job)
        return job

    def refresh_scripts(self, job):
        remote = self.studio.get(job['studio_job_id'])
        if remote['state'] == 'completed':
            self.save(job, scripts_result=remote['result'], status='awaiting_selection', error='')
        elif remote['state'] in ('failed', 'cancelled', 'interrupted'):
            raise ValueError('대본 작업이 중단되었습니다. PersonalProject1에서 결과를 확인하세요: '
                             + str(remote.get('error') or remote['state']))
        return remote

    def select(self, job_id, payload):
        with file_lock(self.folder(job_id) / 'job.lock'):
            job = self.get(job_id)
            if not job.get('studio_job_id'):
                raise ValueError('먼저 대본 재가공을 실행하세요.')
            remote = self.refresh_scripts(job)
            if remote['state'] != 'completed':
                raise ValueError('대본 재가공이 아직 완료되지 않았습니다.')
            index = payload.get('script_index')
            scripts = remote['result']['scripts']
            if type(index) is not int or not 0 <= index < len(scripts):
                raise ValueError('선택할 대본 번호가 잘못되었습니다.')
            selected = scripts[index]
            review = selected.get('rewrite_review', {})
            text = selected['text']
            if (review.get('script_sha256') != digest(text)
                    or review.get('reference_sha256') != digest(job['reference_script'])
                    or review.get('status') != 'needs_editorial_review'):
                raise ValueError('재가공 검사 결과가 없거나 통과하지 못했습니다. PersonalProject1에서 수정하세요.')
            plan = payload.get('transformation', {})
            if not isinstance(plan, dict) or any(
                    not isinstance(plan.get(key), str) or not 5 <= len(plan[key].strip()) <= 1500
                    for key in ('new_angle', 'structure_change', 'visual_change')):
                raise ValueError('새 관점·전개 변경·화면 변경 계획을 각각 5~1500자로 입력하세요.')
            if payload.get('reviewed') is not True:
                raise ValueError('원본과 재가공 대본·변환 계획을 검토한 뒤 선택하세요.')
            scenes = payload.get('scenes')
            edit_style = payload.get('edit_style')
            if edit_style not in ('house', 'brisk', 'calm'):
                raise ValueError('편집 스타일을 선택하세요.')
            if not isinstance(scenes, list) or not scenes:
                raise ValueError('편집에 사용할 장면과 설명을 지정하세요.')
            by_id = {item['id']: item for item in job['assets']}
            normalized = []
            for scene in scenes:
                if not isinstance(scene, dict) or scene.get('asset_id') not in by_id:
                    raise ValueError('잘못된 소스 영상 ID')
                item = by_id[scene['asset_id']]
                quality = item['source'].get('source_quality', 'unknown')
                if quality == 'edited-with-text':
                    raise ValueError('자막이 포함된 편집 영상은 소스로 사용할 수 없습니다.')
                if quality == 'unknown' and scene.get('reviewed') is not True:
                    raise ValueError('화면 품질 미분류 소스는 직접 검토해야 합니다.')
                label = str(scene.get('label', '')).strip()
                if not 2 <= len(label) <= 80 or re.search(r'[\\/:*?"<>|]', label):
                    raise ValueError('장면 설명은 파일명에 쓸 수 있는 2~80자여야 합니다.')
                span = scene.get('range')
                if span is not None and (not isinstance(span, list) or len(span) != 2
                        or any(type(t) not in (int, float) or not math.isfinite(t) for t in span)
                        or not 0 <= span[0] < span[1]):
                    raise ValueError('장면 구간은 [시작 초, 종료 초]로 입력하세요.')
                normalized.append({'asset_id': item['id'], 'label': label, 'range': span})
            revision = job['revision'] + 1
            script_path = self.folder(job_id) / f'words-v{revision}.txt'
            script_path.write_text(text, encoding='utf-8', newline='\n')
            self.save(job, revision=revision, selected_script=index,
                      script_path=str(script_path), script_sha256=digest(text),
                      rewrite_review=review, transformation=plan, scenes=normalized,
                      edit_style=edit_style,
                      selection_time=time.time(), status='script_selected', error='',
                      voicebench_request_id=None, voice=None, editing=None)
            return job

    def dispatch(self, job_id, action):
        if action not in ('rewrite', 'build'):
            raise ValueError('알 수 없는 제작 명령')
        self.get(job_id)
        # Work is persistent. Reads remain available while a worker owns the lock.
        thread = threading.Thread(target=self._background, args=(job_id, action), daemon=True)
        thread.start()
        return {'id': job_id, 'message': '작업을 요청했습니다. 상태를 조회하세요.'}

    def _background(self, job_id, action):
        try:
            self.run(job_id, action)
        except ValueError:
            # A second click must not overwrite the active worker's state.
            return

    def run(self, job_id, action):
        with file_lock(self.folder(job_id) / 'job.lock'):
            job = self.get(job_id)
            try:
                with file_lock(self.root / 'execution.lock'):
                    if action == 'rewrite':
                        self._rewrite(job)
                    elif action == 'build':
                        self._build(job)
                    else:
                        raise ValueError('알 수 없는 제작 명령')
            except Exception as exc:
                self.save(job, status='blocked', error=str(exc)[:1500])
            return job

    def _rewrite(self, job):
        if job.get('script_path'):
            raise ValueError('이미 확정한 대본이 있습니다. 대본을 다시 선택하거나 새 제작을 시작하세요.')
        self.save(job, status='rewriting', error='')
        if not job.get('studio_job_id'):
            remote = self.studio.submit(job['id'], self.asset_path(job['reference_video']),
                                        job['reference_script'], job)
            self.save(job, studio_job_id=remote['id'])
        else:
            remote = self.studio.get(job['studio_job_id'])
            if remote['state'] in ('failed', 'cancelled', 'interrupted'):
                retried = self.studio.retry(job['id'], job['studio_job_id'])
                self.save(job, studio_job_id=retried['id'])
        deadline = time.monotonic() + self.settings.studio_timeout
        while time.monotonic() < deadline:
            if self.refresh_scripts(job)['state'] == 'completed':
                return
            time.sleep(2)
        raise ValueError('대본 작업 대기 시간이 초과됐습니다. 같은 작업 ID로 재개할 수 있습니다.')

    def _build(self, job):
        if (job.get('editing') or {}).get('status') == 'completed':
            self.save(job, status='draft_ready', error='')
            return
        if not job.get('script_path') or not job.get('transformation'):
            raise ValueError('재가공 대본과 변환 계획을 먼저 선택하세요.')
        script_path = self.asset_path(job['script_path'])
        text = script_path.read_text('utf-8')
        if digest(text) != job['script_sha256']:
            raise ValueError('선택한 대본 파일이 변경됐습니다. 대본을 다시 선택하세요.')
        assets = {item['id']: item for item in job['assets']}
        videos = [self.asset_path(assets[scene['asset_id']]['path']) for scene in job['scenes']]
        for scene, path in zip(job['scenes'], videos):
            if file_digest(path) != assets[scene['asset_id']]['sha256']:
                raise ValueError('선택한 소스 영상이 변경됐습니다. 새 제작을 등록하세요.')
        voice_path = self.folder(job['id']) / f'voice-v{job["revision"]}.wav'
        if not job.get('voice'):
            self.save(job, status='synthesizing', error='')
            voice = self.voice.synthesize(text, voice_path,
                request_id=job.get('voicebench_request_id'),
                on_submitted=lambda request_id: self.save(job, voicebench_request_id=request_id))
            self.save(job, voice={**voice, 'sha256': file_digest(voice_path),
                                 'script_sha256': job['script_sha256']})
        if (file_digest(voice_path) != job['voice']['sha256']
                or job['voice']['script_sha256'] != job['script_sha256']):
            raise ValueError('음성 파일 또는 대본 버전이 변경됐습니다.')
        self.save(job, status='editing', error='')
        edit_id = job['id'] + '-v' + str(job['revision'])
        result_path = self.settings.editing_dir / edit_id / 'result.json'
        if result_path.is_file():
            previous = json.loads(result_path.read_text('utf-8'))
            if (previous.get('status') == 'completed' and previous.get('job_id') == edit_id
                    and previous.get('script_sha256') == job['script_sha256']):
                self.save(job, editing=previous, status='draft_ready')
                return
        result = self.editor.build(job_id=edit_id, video_paths=videos,
            draft_name='reel-' + edit_id, voice_path=voice_path, script_path=script_path,
            video_labels=[scene['label'] for scene in job['scenes']],
            audio_profile='clean_tts', narration_speed=1.0,
            edit_style=job['edit_style'], source_ranges=[scene['range'] for scene in job['scenes']])
        self.save(job, editing=result,
                  status='draft_ready' if result['status'] == 'completed' else 'blocked',
                  error='' if result['status'] == 'completed' else result.get('message', '편집 중단'))
