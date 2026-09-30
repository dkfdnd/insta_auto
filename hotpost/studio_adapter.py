"""PersonalProject1 HTTP contract. No cross-project Python imports."""
from __future__ import annotations

import os
import hashlib
import json
import time
from pathlib import Path

import requests


class StudioAdapter:
    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.trust_env = False

    def headers(self):
        key = os.environ.get('STUDIO_API_KEY', '').strip()
        path = self.settings.studio_api_key_file.expanduser()
        if not key and path.is_file():
            key = path.read_text('utf-8').strip()
        if not key:
            raise RuntimeError('PersonalProject1 연결 키를 찾지 못했습니다.')
        return {'Authorization': 'Bearer ' + key}

    def request(self, method, path, **kwargs):
        headers = {**self.headers(), **kwargs.pop('headers', {})}
        response = self.session.request(
            method, self.settings.studio_url.rstrip('/') + path,
            headers=headers, timeout=kwargs.pop('timeout', 180), allow_redirects=False, **kwargs)
        if response.status_code >= 300:
            raise RuntimeError(f'PersonalProject1 요청 실패: HTTP {response.status_code}')
        return response.json()

    def review(self, text, reference):
        return self.request('POST', '/api/scripts/review',
                            json={'text':text, 'reference_script':reference[:10000]}, timeout=10)

    def editorial(self, instruction, evidence, media=None):
        payload={'instruction':instruction,'evidence':evidence,'media':media or []}
        key='editorial-'+hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        remote=self.request('POST','/api/editorial/jobs',json=payload,headers={'Idempotency-Key':key})
        # A previous retry may itself have failed. Follow its idempotent chain
        # until an existing active/result job or one new queued attempt is found.
        for _ in range(32):
            if remote['state'] not in ('failed','cancelled','interrupted'):
                break
            remote=self.retry(key,remote['id'])
        else:
            raise RuntimeError('로컬 AI 검토 재시도가 반복 실패했습니다. script_auto 작업 오류를 확인하세요.')
        deadline=time.monotonic()+self.settings.studio_timeout
        while time.monotonic()<deadline:
            if remote['state']=='completed':return remote['result']['value']
            if remote['state'] in ('failed','cancelled','interrupted'):
                raise RuntimeError('로컬 AI 검토 실패: '+str(remote.get('error') or remote.get('message'))[:500])
            time.sleep(2)
            remote=self.get(remote['id'])
        raise RuntimeError('로컬 AI 검토 대기 시간 초과. 재시도하면 기존 요청을 확인합니다.')

    def submit(self, production_id: str, video: Path, reference: str, payload: dict):
        with video.open('rb') as stream:
            upload = self.request('POST', '/api/uploads',
                files={'file': (video.name, stream, 'video/mp4')},
                headers={'Idempotency-Key': production_id + '-reference'})
        job = self.request('POST', '/api/jobs', json={
            'kind': 'script', 'upload_id': upload['id'],
            'reference_script': reference, 'product': payload['product'],
            'product_url': payload.get('product_url', ''),
            'notes': payload.get('notes', ''), 'relation': 'same',
            'target': 'local', 'release_model': True,
        }, headers={'Idempotency-Key': production_id + '-rewrite'})
        return job

    def get(self, job_id):
        if not isinstance(job_id, str) or not job_id.isalnum():
            raise ValueError('잘못된 대본 작업 ID')
        return self.request('GET', '/api/jobs/' + job_id)

    def retry(self, production_id, job_id):
        if not isinstance(job_id, str) or not job_id.isalnum():
            raise ValueError('잘못된 대본 작업 ID')
        return self.request('POST', '/api/jobs/' + job_id + '/retry', json={},
                            headers={'Idempotency-Key': production_id + '-retry-' + job_id})
