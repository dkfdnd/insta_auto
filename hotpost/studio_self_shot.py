"""Independent owned-footage intake; downstream versions use the Studio workflow."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from urllib.parse import urlparse

from .editing_adapter import _atomic_json
from .source_policy import owned_policy
from .studio_store import Conflict
from .studio_workflow import snapshot


def validate_brief(data):
    mode = data.get('script_mode', 'automatic')
    if mode not in {'automatic', 'manual'}:
        raise ValueError('자동 대본 또는 직접 입력을 선택하세요.')
    limits = {'product':300, 'details':3000, 'experience':1500, 'product_url':2000,
              'comment_keyword':40, 'text':3000, 'title':120}
    brief = {'script_mode':mode}
    for key, maximum in limits.items():
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(f'{key} 입력 길이를 확인하세요. 최대 {maximum}자입니다.')
        brief[key] = value.strip()
    if mode == 'manual' and not brief['text']:
        raise ValueError('영상에서 읽을 대본을 입력하세요.')
    if mode == 'automatic' and not brief['product']:
        raise ValueError('주제 또는 제품명을 입력하세요.')
    if brief['product_url']:
        url = urlparse(brief['product_url'])
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
            raise ValueError('제품 링크는 올바른 http 또는 https 주소로 입력하세요.')
    return brief


class SelfShotMixin:
    def save_self_shot_brief(self, task_id, data):
        brief = validate_brief(data)
        def save(s, db):
            if s.get('creation_mode') != 'self_shot' or s['self_shot'].get('started'):
                raise Conflict('제작 시작 후에는 기존 제작실에서 대본과 설정을 수정하세요.')
            s['self_shot'] = {**brief, 'started':False}
            s['title'] = brief['title'] or brief['product'] or brief['text'].splitlines()[0][:70]
            self.store.event(db, task_id, 'self_shot_brief_saved', {})
        return self.public(self.store.change(task_id, save, data.get('revision')))

    def create_self_shot(self, data):
        brief = validate_brief(data)
        key = data.get('creation_key')
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key):
            raise ValueError('새 제작 요청을 다시 열어 주세요.')
        title = brief['title'] or brief['product'] or brief['text'].splitlines()[0][:70]
        state, _ = self.store.create('own-'+key, title,
            {'protocol':2, 'active':False, 'stage':'prepare', 'selection_mode':'self_shot', 'needs_top_pick':False},
            initial={'creation_mode':'self_shot', 'self_shot':{**brief, 'started':False},
                     'source_policy':owned_policy(), 'status':'self_shot_draft',
                     'message':'촬영 영상을 추가하고 제작 시작을 눌러 주세요.'}, prepare=False)
        return self.public(state)

    def start_self_shot(self, task_id, data):
        def start(s, db):
            if s.get('creation_mode') != 'self_shot':
                raise ValueError('내 촬영 영상 제작 작업이 아닙니다.')
            if s['self_shot'].get('started'):
                raise Conflict('이미 제작을 시작했습니다. 현재 결과에서 소스·대본을 수정하세요.')
            available = {v['id']:v for v in s['sources']}
            ids = data.get('source_ids', list(available))
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 20
                    or any(not isinstance(v, str) or v not in available for v in ids)):
                raise ValueError('직접 추가한 촬영 영상을 1~20개 선택하세요.')
            for source_id in ids:
                source = available[source_id]
                path = Path(source['path'])
                if (source.get('rights') != 'user_supplied' or not path.is_file()
                        or not path.resolve().is_relative_to(self.folder(task_id).resolve() / 'uploads')):
                    raise ValueError('이 작업에 직접 업로드한 촬영 영상만 사용할 수 있습니다.')
            s['self_shot']['started'] = True
            s['automation'].update(active=True, paused_by_user=False, stage='prepare')
            run = snapshot(s)
            run['inputs'].update(source_ids=list(dict.fromkeys(ids)), self_shot=copy.deepcopy(s['self_shot']))
            self.store.enqueue(db, task_id, 'prepare', {'source_ids':run['inputs']['source_ids']}, 'prepare:'+task_id)
            s.update(status='preparing', error='', progress=0, message='내 촬영 영상으로 제작 준비 중')
            self.store.event(db, task_id, 'self_shot_started', {'count':len(set(ids))})
        return self.public(self.store.change(task_id, start, data.get('revision')))

    def prepare_self_shot(self, state, job):
        brief = state['self_shot']
        if not brief.get('started'):
            raise ValueError('촬영 영상을 선택한 뒤 제작을 시작하세요.')
        ids = job['payload'].get('source_ids', [])
        sources = [v for v in state['sources'] if v['id'] in ids]
        if not ids or len(sources) != len(set(ids)):
            raise ValueError('선택한 촬영 영상을 찾지 못했습니다.')
        for source in sources:
            if source.get('rights') != 'user_supplied' or not Path(source['path']).is_file():
                raise ValueError('선택한 촬영 영상 파일을 다시 추가해 주세요.')
        evidence = {'subject':brief['product'], 'user_details':brief['details'],
                    'user_experience':brief['experience'], 'product_url':brief['product_url'], 'facts':[], 'warnings':[]}
        if brief['script_mode'] == 'automatic':
            from .studio_adapter import StudioAdapter
            adapter = StudioAdapter(self.settings)
            research_id = job['checkpoint'].get('research_job_id')
            if research_id:
                research = adapter.get(research_id)
                if job['checkpoint'].get('retry_requested') and research['state'] in {'failed','cancelled','interrupted'}:
                    research = adapter.retry(state['id'], research_id)
            else:
                research = adapter.jobs.create('product_research', {'product':brief['product'], 'product_url':brief['product_url']}, state['id'])
            job['checkpoint']['research_job_id'] = research['id']
            self.store.checkpoint(job['id'], job['checkpoint'])
            adapter.jobs.start()
            self.store.change(state['id'], lambda s, db: s.update(message='제품 정보와 출처를 확인하는 중', progress=20))
            try:
                evidence.update(adapter._wait(research)['result'])
            except (RuntimeError, ValueError, OSError) as exc:
                evidence['warnings'].append('제품 조사 미완료 · 입력한 정보만으로 집필합니다: '+str(exc)[:180])
        # Evidence is text, never a fake speech transcript or a benchmark post.
        context = '\n'.join(filter(None, [brief['product'], brief['details'],
            ('사용자가 제공한 실제 경험: '+brief['experience']) if brief['experience'] else '',
            *[fact['text'] for fact in evidence.get('facts', [])]]))
        if brief['script_mode'] == 'manual':
            context = brief['text']
        manifest = self.folder(state['id']) / (job['id']+'-owned.json')
        _atomic_json(manifest, {'caption':state['title'], 'owned_only':True, 'user_supplied':True,
            'downloaded':len(sources), 'candidates':[{'title':v.get('original_name',''),
                'file_sha256':v['sha256'], 'rights':'user_supplied', 'original_url':'', 'selected_for_zip':True} for v in sources]})
        result = {'original_text':context, 'reference_kind':'provided_text', 'research':evidence,
                  'sources':sources, 'manifest_path':str(manifest), 'product':brief['product'] or state['title']}
        if brief['script_mode'] == 'manual':
            result['text'] = brief['text']
            result['script_origin'] = 'manual'
        return result

    def write_self_shot(self, state, job):
        from .studio_adapter import StudioAdapter
        from .local_compute import serialized_compute, release_idle_voice
        from .writing.contract import snapshot as contract_snapshot
        @serialized_compute('script')
        def write(owner):
            release_idle_voice(self.settings, best_effort=True)
            adapter = StudioAdapter(self.settings)
            jid = job['checkpoint'].get('writing_job_id')
            if jid:
                remote = adapter.get(jid)
                if job['checkpoint'].get('retry_requested') and remote['state'] in {'failed','cancelled','interrupted'}:
                    remote = adapter.retry(state['id'], jid)
            else:
                brief = state['self_shot']
                payload = {'reference_script':state['original_text'], 'generation_mode':'self_shot',
                    'product':brief['product'], 'research':state.get('research', {}),
                    'comment_keyword':brief['comment_keyword'] or '나도',
                    'writing_contract':contract_snapshot('self_shot')}
                remote = adapter.jobs.create('script', payload, state['id']+':'+state['run_id'])
            job['checkpoint']['writing_job_id'] = remote['id']
            self.store.checkpoint(job['id'], job['checkpoint'])
            adapter.jobs.start()
            result = adapter._wait(remote)['result']
            candidate = result['scripts'][0]
            return {'text':candidate['text'], 'script_candidates':[candidate], 'selected_candidate':0,
                    'studio_job_id':remote['id'], 'writing_contract':result.get('writing_contract'),
                    'writing_warnings':result.get('warnings', [])}
        return write(self)
