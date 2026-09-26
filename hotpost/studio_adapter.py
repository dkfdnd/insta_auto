"""PersonalProject1 HTTP contract. No cross-project Python imports."""
from __future__ import annotations

import os
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
            headers=headers, timeout=180, allow_redirects=False, **kwargs)
        if response.status_code >= 300:
            raise RuntimeError(f'PersonalProject1 요청 실패: HTTP {response.status_code}')
        return response.json()

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
