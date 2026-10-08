"""Cross-responsibility contracts of the public Studio facade."""
import copy
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

from hotpost.config import Settings
from hotpost.studio import Studio, digest
from hotpost.studio_adapter import StudioAdapter


def test_script_review_does_not_lock_out_worker_progress(tmp_path, monkeypatch):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('review-concurrent', '대본 검사 중 작업 진행')
    studio.store.change(state['id'], lambda s, db: s.update(original_text='원본 발화'))

    def review(self, text, reference, *, evidence_mode):
        # An HTTP read may overlap another worker's database write. It must
        # not inherit the command transaction or silently save edited text.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(studio.store.change, state['id'],
                                 lambda s, db: s.update(progress=42))
            future.result(timeout=2)
        return {'text': text, 'naturalness_review': {'issues': []}}

    monkeypatch.setattr(StudioAdapter, 'review', review)
    studio.action(state['id'], 'check-script', {'text': '아직 저장하지 않은 대본이에요.'})
    after = studio.store.get(state['id'])
    assert after['progress'] == 42
    assert after['scripts'] == []
    assert after['script_id'] is None
    assert after['approved_script_id'] is None


def test_public_projection_is_detached_and_media_urls_still_resolve(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('projection', '영상 비교')
    studio.store.change(state['id'], lambda s, db: studio._script(s, '비교할 대본이에요.', 'manual'))
    source = tmp_path / 'sources' / 'source.mp4'
    source.parent.mkdir()
    source.write_bytes(b'owned source')
    studio.store.change(state['id'], lambda s, db: s['sources'].append({
        'id': 'source-1', 'path': str(source), 'sha256': digest(source),
        'source_quality': 'clean-source', 'editing_eligible': True,
    }))
    saved = studio.store.get(state['id'])
    before = copy.deepcopy(saved)
    public = studio.public(saved)
    for item in (public['sources'][0], public['scripts'][0]):
        url = item.get('url') or item['path_url']
        relative = parse_qs(urlparse(url).query)['file'][0]
        assert studio.media(state['id'], relative).is_file()
    public['sources'][0]['source_quality'] = 'edited-with-text'
    public['scripts'][0]['text'] = '화면에서만 편집 중'
    assert saved == before
    assert studio.store.get(state['id']) == before


def test_worker_calls_instance_step_and_completion_overrides(tmp_path):
    seen = []

    class FixtureStudio(Studio):
        def _prepare(self, state, job):
            seen.append(('prepare', job['id']))
            self.stop.set()
            return {'text': '작업 결과 대본이에요.', 'original_text': '원본', 'sources': []}

        def _accept(self, state, job, result, db=None):
            seen.append(('accept', job['id']))
            return super()._accept(state, job, result, db)

    studio = FixtureStudio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('worker-dispatch', '단계 실행')
    studio._worker('production')
    job = studio.store.jobs(state['id'])[0]
    assert job['status'] == 'done'
    assert seen == [('prepare', job['id']), ('accept', job['id'])]
    assert studio.store.get(state['id'])['scripts'][0]['text'] == '작업 결과 대본이에요.'


def test_scoped_claim_leaves_other_task_queue_untouched(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    first, _ = studio.store.create('first', 'First')
    second, _ = studio.store.create('second', 'Second')
    claimed = studio.store.claim('production', task_id=second['id'])
    assert claimed['task_id'] == second['id']
    assert studio.store.claim('production', task_id=second['id']) is None
    assert studio.store.claim('production', task_id="missing' OR 1=1 --") is None
    assert studio.store.claim('production')['task_id'] == first['id']
