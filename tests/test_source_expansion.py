import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_queries import product_query_plan, platform_queries, language
from hotpost.source_planning import enrich_plan
from hotpost.source_finder import Candidate, build_queries, download_candidate
from hotpost.studio import Studio


def test_recipe_and_repair_queries_do_not_use_product_unboxing():
    for caption in ['생선을 구워요. 생선구이', '타일 보수 작업']:
        plan = product_query_plan(caption, [], [], {}, [])
        queries = [r['query'] for r in plan['query_details']]
        assert {r['language'] for r in plan['query_details']} == {'ko', 'en', 'zh'}
        assert not any('unboxing' in q or '언박싱' in q or '开箱' in q for q in queries)
    assert build_queries('보내드릴게요 그대로예요 궁금하시면') == []


def test_model_requires_literal_evidence_and_real_language():
    plan = product_query_plan('', [], [], {}, ['궁금한 제품'])
    response = {'subject_kind': 'recipe', 'queries': [
        dict(query='fry fish without breaking', language='en', source='speech', quote='살이 안 부서져요'),
        dict(query='煎鱼不破皮', language='zh', source='speech', quote='살이 안 부서져요'),
        dict(query='생선 튀기기', language='en', source='speech', quote='살이 안 부서져요'),
        dict(query='add lemon', language='en', source='speech', quote='레몬을 넣어요'),
    ]}
    actual = enrich_plan(Settings(), plan, '', {'speech': '생선 살이 안 부서져요'}, lambda *_: response)
    assert [r['query'] for r in actual['query_details']] == ['fry fish without breaking', '煎鱼不破皮']
    assert '일부 언어' in actual['planning_notes'][0]


def test_queries_distribute_all_languages_in_six_global_searches():
    queries = ['fish ' + str(i) for i in range(6)] + ['생선 ' + str(i) for i in range(6)] + ['煎鱼 ' + str(i) for i in range(6)]
    assert {language(q) for q in platform_queries(queries, 'youtube', 6)} == {'ko', 'en', 'zh'}
    assert all(language(q) == 'zh' for q in platform_queries(queries, 'bilibili', 6))


def test_youtube_result_budget_does_not_starve_later_languages(monkeypatch):
    from hotpost import source_finder as sf
    monkeypatch.setattr(sf, '_executable', lambda _: 'tool')
    commands = []
    def run(command, **_):
        commands.append(command)
        count = int(command[-1].split(':', 1)[0].replace('ytsearch', ''))
        entries = [{'url': f'https://youtube.com/watch?v={len(commands)}_{i}'} for i in range(count)]
        return SimpleNamespace(returncode=0, stdout=json.dumps({'entries': entries}))
    monkeypatch.setattr(sf, '_run', run)
    queries = ['fish ' + str(i) for i in range(4)] + ['생선', '煎鱼']
    audit = []
    found = sf.search_youtube(queries, 8, audit=audit)
    assert len(found) == 8 and len(audit) == 6
    assert {r['language'] for r in audit} == {'en', 'ko', 'zh'}


def test_bilibili_deadline_prevents_long_retry(tmp_path, monkeypatch):
    from hotpost import source_finder as sf
    monkeypatch.setattr(sf, '_executable', lambda _: 'tool')
    monkeypatch.setattr(sf.time, 'monotonic', lambda: 100)
    seen = []
    def run(command, timeout):
        seen.append(timeout)
        assert '--js-runtimes' in command and 'node:C:/node.exe' in command
        raise subprocess.TimeoutExpired(command, timeout)
    monkeypatch.setattr(sf, '_run', run)
    c = Candidate('https://www.bilibili.com/video/BV1234567890', 'bilibili')
    assert download_candidate(c, tmp_path, 1, 50, deadline=110, js_runtime='node:C:/node.exe') is None
    assert seen == [10]


def test_browser_failed_navigation_cannot_reuse_previous_results(tmp_path, monkeypatch):
    from hotpost import browser_search as bs
    monkeypatch.setattr(bs, 'probe_platform_auth', lambda *_: 'unverified')
    monkeypatch.setattr(bs.time, 'sleep', lambda _: None)
    def fail(*_a, **_k): raise TimeoutError()
    page = SimpleNamespace(route=lambda *_: None, goto=fail, close=lambda: None)
    monkeypatch.setattr(bs, '_anchors', lambda *_: pytest.fail('stale page must not be scraped'))
    searcher = bs.BrowserSearcher(Settings(source_queries_per_platform=1), tmp_path)
    searcher._platforms(SimpleNamespace(new_page=lambda: page), ['fry fish'], 4)
    assert len(searcher.searches) == 4
    assert all(r['status'] == 'error' and r['candidates'] == 0 for r in searcher.searches)


def test_refresh_appends_sources_without_overwriting_review_versions(tmp_path):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('ref', 'test')
    state.update(sources=[{'id': 'old', 'sha256': 'oldhash', 'origin_url': 'https://x/old'}],
                 scripts=[{'id': 'script'}], edit_id='edited', edits=[{'id': 'edited'}])
    result = {'source_search_manifest_path': 'new/manifest.json', 'sources': [
        {'id': 'dup', 'sha256': 'newhash', 'origin_url': 'https://x/old'},
        {'id': 'new', 'sha256': 'added', 'origin_url': 'https://x/new'}]}
    studio._accept(state, {'kind': 'refresh_sources', 'payload': {}}, result)
    assert [s['id'] for s in state['sources']] == ['old', 'new']
    assert state['edit_id'] == 'edited' and state['scripts'] == [{'id': 'script'}]
    assert state['source_search']['status'] == 'done'


def test_equal_segment_filenames_keep_distinct_original_urls(tmp_path):
    from hotpost.studio import digest
    paths = []
    candidates = []
    for i in range(2):
        p = tmp_path / str(i) / 'segment.mp4'; p.parent.mkdir(); p.write_bytes(str(i).encode())
        paths.append(p)
        candidates.append({'downloaded_file': f'{i}/segment.mp4', 'file_sha256': digest(p),
                           'original_url': f'https://youtube.com/watch?v=source{i}'})
    manifest = tmp_path/'manifest.json'; manifest.write_text(json.dumps({'candidates': candidates}))
    records = Studio._source_records(paths, manifest)
    assert [r['origin_url'] for r in records] == [c['original_url'] for c in candidates]


def test_prepare_transcribes_before_source_search(tmp_path, monkeypatch):
    from hotpost import source_finder, transcript
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('ref', 'test')
    calls = []
    def transcribe(*_):
        calls.append('transcript')
        (tmp_path / 'transcript.json').write_text(json.dumps({'speech': [{'text': '실제 원본 발화'}]}), encoding='utf-8')
        return {'json_path': str(tmp_path / 'transcript.json')}
    def find(*_):
        calls.append('sources')
        raise RuntimeError('stop before external services')
    monkeypatch.setattr(transcript, 'extract_transcript', transcribe)
    monkeypatch.setattr(source_finder, 'find_sources', find)
    with pytest.raises(RuntimeError): studio._prepare(state, {})
    assert calls == ['transcript', 'sources']


def test_long_video_scans_and_saves_original_interval(tmp_path, monkeypatch):
    from hotpost import source_finder as sf
    from hotpost.source_segments import extract_relevant_segment
    monkeypatch.setattr(sf, '_executable', lambda _: 'ffmpeg')
    def run(command, timeout):
        Path(command[-1]).write_bytes(b'fixture')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(sf, '_run', run)
    scores = iter([.1, .2, .3, .9, .3, .4, .5, .4])
    verifier = SimpleNamespace(score=lambda _: next(scores))
    result = extract_relevant_segment(Settings(), tmp_path/'original.mp4', {'duration': 630}, verifier,
                                      tmp_path/'segments', float('inf'))
    assert result and result[0].is_file()
    assert result[1]['start'] == pytest.approx(600 * 3/7, abs=.001)
    assert result[1]['original_duration'] == 630


@pytest.mark.parametrize('height, expected', [(1280, 1), (400, 0)])
@pytest.mark.parametrize('initial_count', [1, 25])
def test_low_yield_expands_search_and_verifies_new_download(tmp_path, monkeypatch, height, expected, initial_count):
    from hotpost import source_finder as sf, text_overlay
    from hotpost.models import Post
    from PIL import Image
    settings = Settings(data_dir=tmp_path, source_browser_search=False, source_query_model_enabled=False,
                        source_transcribe_reference=False, source_max_downloads=2, source_max_attempts=22)
    monkeypatch.setattr(sf, '_post', lambda *_: Post('ref', 'u', 1, 'reel', caption='생선구이'))
    monkeypatch.setattr(sf, '_download_reference', lambda *a: a[-1])
    def frames(_video, directory, *_a, **_k):
        directory.mkdir(parents=True, exist_ok=True)
        p = directory/'candidate_001.jpg'; Image.new('RGB', (20, 30), 'white').save(p); return [p]
    monkeypatch.setattr(sf, 'extract_frames', frames)
    monkeypatch.setattr(sf, 'OpenClipVerifier', lambda *_: SimpleNamespace(error='', product_evidence=[], last_embedding=None,
                        subject_reference_indices=[], focus_subject=lambda _: None,
                        discover_product_queries=lambda: [], score=lambda _: .9))
    monkeypatch.setattr(text_overlay, 'TextOverlayDetector', lambda *_: SimpleNamespace(note='', reference_text=lambda _: '',
                        analyze=lambda _: {'source_quality': 'clean-source'}))
    for name in ('search_local_cache', 'search_web', 'search_bing', 'search_pexels'):
        monkeypatch.setattr(sf, name, lambda *_: [])
    monkeypatch.setattr(sf, 'search_google_vision', lambda *_: ([], []))
    searches = []
    def search(queries, limit, cookie, audit, runtime):
        searches.append(queries)
        audit.append({'provider': 'youtube', 'query': queries[0], 'status': 'results'})
        if len(searches) == 1:
            return [Candidate(f'https://youtube.com/watch?v=initial{i}', 'youtube') for i in range(initial_count)]
        return [Candidate('https://youtube.com/watch?v=refined', 'youtube')]
    monkeypatch.setattr(sf, 'search_youtube', search)
    def download(candidate, directory, index, *_a, **_k):
        if 'initial' in candidate.url: return None
        p=directory/'new.mp4'; p.write_bytes(b'video'); return p
    monkeypatch.setattr(sf, 'download_candidate', download)
    monkeypatch.setattr(sf, 'probe_video', lambda _: {'duration': 10, 'width': 720, 'height': height})
    def compare(ref, video, directory):
        assert height >= 640, 'Invalid format must be rejected before heavy analysis'
        frames(video, directory); return .85
    monkeypatch.setattr(sf, 'compare_videos', compare)
    result = sf.find_sources(settings, 'ref')
    assert len(searches) == 2 and searches[0][0] not in searches[1]
    assert result['downloaded'] == expected and result['probe_attempts'] == (2 if initial_count == 1 else 22)
    assert result['refinement_query_details'] and len(result['search_audit']) == 2
