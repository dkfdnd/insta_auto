import json
import subprocess
import time
import sys
from pathlib import Path
from types import SimpleNamespace

from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.analyze import score_account, assessment
from hotpost.criteria import defaults
from hotpost.source_queries import product_query_plan, platform_queries
from hotpost.source_urls import video_url
from hotpost.source_finder import Candidate, _dedupe
from hotpost.storage import Storage


def test_source_retry_does_not_prioritize_previously_rejected_downloads(tmp_path):
    from hotpost.source_finder import search_local_cache
    settings = Settings(data_dir=tmp_path)
    folder = settings.source_dir / 'code-100'
    folder.mkdir(parents=True)
    rows = [
        {'url':'https://www.tiktok.com/@u/video/111', 'downloaded_file':'bad.mp4',
         'selected_for_zip':False, 'rejection_reasons':['low_product_or_scene_similarity']},
        {'url':'https://www.tiktok.com/@u/video/222', 'downloaded_file':'reviewed-bad.mp4',
         'selected_for_zip':True, 'editing_eligible':False},
        {'url':'https://www.tiktok.com/@u/video/333', 'downloaded_file':'good.mp4',
         'selected_for_zip':True, 'rejection_reasons':[]},
    ]
    (folder/'manifest.json').write_text(json.dumps({'candidates':rows}))
    # Even a one-item cache budget must reach the verified source at the end.
    assert [c.url for c in search_local_cache(settings, 'code', 1)] == [rows[-1]['url']]


def test_product_identity_overrides_broad_clip_and_distributes_languages():
    plan = product_query_plan('아디다스 나일론 백팩 플랩 조임끈',
                             ['travel organizer bag', '旅行收纳袋'], ['Recognize text'],
                             {'speech': '백팩 소개', 'screen_text': ''}, [])
    queries = [row['query'] for row in plan['query_details']]
    assert plan['products'][0]['en'] == 'backpack'
    assert plan['models'] == []
    assert 'travel organizer bag' not in queries and 'Recognize text' not in queries
    assert 'adidas backpack' in queries and 'backpack' in queries
    zh = platform_queries(queries, 'douyin', 6)
    assert len(zh) == 6 and all(any('\u3400' <= char <= '\u9fff' for char in q) for q in zh)
    assert any('开箱' in q for q in zh) and any('尼龙' in q for q in zh)
    assert next(x for x in plan['query_details'] if x['query'] == 'adidas backpack')['confidence'] == 'medium'
    assert any('백팩' in q for q in platform_queries(queries, 'youtube', 6))


def test_real_subjects_survive_unrelated_visual_search_labels():
    cases = [('여권지갑 옷 안에 숨기는 여행 복대', 'hidden passport money belt'),
             ('어그 신상 뮬 스웨이드', 'backless mule sneakers'),
             ('닭다리살 마늘간장 소스로 허니콤보 만들기', 'honey garlic soy chicken')]
    for caption, subject in cases:
        plan = product_query_plan(caption, ['travel organizer bag', '旅行收纳袋'],
                                  ['adidas backpack', 'bts bangtan', 'брюки классические'], {}, [])
        assert [p['en'] for p in plan['products']] == [subject]
        queries = [d['query'] for d in plan['query_details']]
        assert all('bts' not in q and 'adidas' not in q and 'backpack' not in q for q in queries)
        assert platform_queries(queries, 'douyin', 2)
        assert platform_queries(queries, 'youtube', 2)
        if 'chicken' in subject:
            assert any('recipe' in q for q in queries)
            assert not any('unboxing' in q for q in queries)


def test_model_requires_explicit_label_and_preserves_evidence():
    plan = product_query_plan('백팩 할인 2026 AB1234', [], [], {'screen_text': '품번: IK1234'}, [])
    assert [row['value'] for row in plan['models']] == ['IK1234']
    assert any('IK1234' in q['query'] and 'screen_text' in q['sources'] for q in plan['query_details'])


def test_all_providers_reject_nonvideo_urls_before_subprocess(tmp_path, monkeypatch):
    from hotpost import source_finder as sf
    monkeypatch.setattr(sf, '_run', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('must not download')))
    for url in ['https://so.douyin.com/', 'https://mall.douyin.com/?from=anything',
                'https://www.douyin.com/hashtag/1234', 'https://youtube.com.evil.invalid/watch?v=123']:
        assert not video_url(url)
        candidate = Candidate(url, 'bing')
        assert sf.download_candidate(candidate, tmp_path, 1, 200) is None
        assert candidate.rejection_reasons == ['not_video_url']
    assert len(_dedupe([Candidate(u, 'youtube') for u in
                       ['https://youtu.be/abc', 'https://www.youtube.com/shorts/abc',
                        'https://youtube.com/watch?v=abc&feature=share']])) == 1


def test_pinned_old_post_does_not_end_gap_recovery(monkeypatch):
    from hotpost.collectors import web_graphql as web
    now = int(time.time())
    known = Post('known', 'u', now - 1000, 'image', 10, 1)
    pinned = Post('pinned', 'u', now - 9000, 'image', 10, 1)
    new = [Post(f'new{i}', 'u', now - i * 10, 'image', 10, 1) for i in range(15)]
    pages = [[pinned, *new[:11]], [*new[11:], known]]
    collector = web.WebGraphQLCollector.__new__(web.WebGraphQLCollector)
    collector.settings = Settings()
    collector._profile_html = lambda _: ''
    collector._parse_profile = lambda *_: Profile('u', followers=100)
    collector._sleep = lambda *_: None
    monkeypatch.setattr(web, '_node_to_post', lambda node, _: node)
    def gql(*_):
        page = pages.pop(0)
        return {'data': {'xdt_api__v1__feed__user_timeline_graphql_connection': {
            'edges': [{'node': p} for p in page],
            'page_info': {'has_next_page': bool(pages), 'end_cursor': 'next'}}}}
    collector._gql = gql
    collector._parse_profile = lambda *_: Profile('u', user_id='1', followers=100)
    _, posts, _ = collector.fetch('u', 5, {'known': known})
    assert {p.shortcode for p in posts} == {p.shortcode for p in new}
    assert not pages


def test_initial_collection_requests_baseline_and_keeps_history(tmp_path, monkeypatch):
    from hotpost import cli, collectors
    settings = Settings(data_dir=tmp_path)
    store = Storage(settings.db_path)
    now = int(time.time())
    limits = []
    def fetch(name, limit, existing):
        limits.append(limit)
        return Profile(name), [Post(str(i), name, now - i * 86400, 'image', 10, 1) for i in range(limit)], []
    monkeypatch.setattr(collectors, 'get_collector', lambda *_: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(cli, '_operational_event', lambda *_: None)
    assert cli.collect(settings, store, 'web', ['u'])[:2] == (1, 0)
    cli.collect(settings, store, 'web', ['u'])
    assert limits == [31, 5]
    assert len(store.posts_for('u')) == 31
    store.close()


def test_old_baseline_views_are_backfilled_with_request_limit(monkeypatch):
    from hotpost.collectors.web_graphql import WebGraphQLCollector
    now = int(time.time())
    collector = WebGraphQLCollector.__new__(WebGraphQLCollector)
    collector.settings = Settings(baseline_views_lookup_limit=2)
    collector._api_headers = lambda *_: {}
    collector._sleep = lambda *_: None
    calls = []
    def get(url, **_):
        calls.append(url)
        return SimpleNamespace(status_code=200, ok=True, json=lambda: {'items': [{'play_count': 1000}]})
    collector.s = SimpleNamespace(get=get)
    posts = [Post(str(i), 'u', now - (i + 20) * 86400, 'reel', 10, 1, media_id=str(i)) for i in range(5)]
    observations = collector._fill_video_views({p.shortcode: p for p in posts}, {})
    assert len(calls) == len(observations) == 2
    assert all(o.success for o in observations)


def test_confirmation_requires_unadjusted_performance_and_fresh_repeat_observation():
    now = int(time.time()); settings = Settings(); criteria = defaults(settings)
    peers = [Post(f'old{i}', 'u', now - (i + 5) * 86400, 'reel', 100, 10, 1000) for i in range(10)]
    young = Post('young', 'u', now - 8 * 3600, 'reel', 100, 10, 1000)
    good = [{'success': True, 'observed_at': now - 4 * 3600, 'views': 1000},
            {'success': True, 'observed_at': now, 'views': 3000}]
    scored = score_account([young, *peers], settings, now=now)[0]
    assert scored.tier > 0
    result = assessment(scored, good, now, settings, criteria)
    assert result['status'] == 'provisional'
    assert '신규 게시물 보정으로 기준 통과' in result['reasons']
    strong = Post('strong', 'u', now - 4 * 86400, 'reel', 300, 30, 3000)
    scored = score_account([strong, *peers], settings, now=now)[0]
    assert assessment(scored, good, now, settings, criteria)['status'] == 'confirmed'
    assert assessment(scored, good[:1], now, settings, criteria)['status'] == 'provisional'
    assert assessment(scored, good, now + 40 * 3600, settings, criteria)['status'] == 'provisional'


def test_rotation_includes_nonhot_reels_and_skips_recent_attempts(tmp_path):
    store = Storage(tmp_path / 'db.sqlite'); now = int(time.time())
    posts = [Post(str(i), 'u', now - (i + 1) * 86400, 'reel', 10, 1, media_id=str(i)) for i in range(5)]
    store.upsert_posts(posts)
    out = store.recent_view_candidates('u', 14, {'0'}, 2, now)
    assert [p.shortcode for p in out] == ['1', '2']
    store.close()


def test_windows_schedule_uses_data_arguments_not_interpolated_code(monkeypatch):
    from hotpost import scheduler
    def run(command, **kwargs):
        assert command[0] == 'powershell.exe'
        assert '-EncodedCommand' in command
        config = json.loads(kwargs['input'])
        assert config['action'] == 'status' and config['name'] == scheduler.WINDOWS_TASK
        return subprocess.CompletedProcess(command, 0, '{"installed":false,"supported":true}', '')
    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    assert scheduler._windows_schedule('status')['supported']


def test_ocr_reads_unicode_paths_as_bytes(tmp_path):
    from hotpost.text_overlay import TextOverlayDetector
    from PIL import Image
    frame = tmp_path / '한글프레임.jpg'
    Image.new('RGB', (400, 800), 'white').save(frame)
    detector = TextOverlayDetector.__new__(TextOverlayDetector)
    def readtext(value, **_):
        assert isinstance(value, bytes) and value == frame.read_bytes()
        return [([[10, 500], [250, 500], [250, 540], [10, 540]], 'visible caption', .9)]
    detector.reader = SimpleNamespace(readtext=readtext)
    detector.tesseract = None
    detector.languages = ['ko', 'en']
    result = detector.analyze([frame])
    assert result['source_quality'] == 'edited-with-text'
    assert detector.reference_text([frame]) == 'visible caption'


def test_verified_candidate_title_can_refine_model_queries():
    plan = product_query_plan('백팩', [], [], {}, [], ['adidas backpack model IK1234'])
    model_queries = [q for q in plan['query_details'] if 'IK1234' in q['query']]
    assert model_queries
    assert all('verified_candidate_title' in q['sources'] for q in model_queries)


def test_external_process_output_with_mixed_encoding_does_not_abort_job():
    from hotpost.source_finder import _run
    result = _run([sys.executable, '-c', "import sys; sys.stderr.buffer.write(bytes([0xc0,0xaf]))"])
    assert result.returncode == 0
    assert isinstance(result.stderr, str) and result.stderr


def test_unreadable_foreign_text_is_not_a_clean_source(tmp_path):
    from hotpost.text_overlay import TextOverlayDetector
    from PIL import Image
    frame = tmp_path / 'foreign.jpg'; Image.new('RGB', (400, 800), 'white').save(frame)
    detector = TextOverlayDetector.__new__(TextOverlayDetector)
    detector.reader = SimpleNamespace(readtext=lambda *_a, **_k: [
        ([[10, 500], [250, 500], [250, 540], [10, 540]], 'unreadable', .1)])
    detector.tesseract = None; detector.languages = ['ko', 'en']
    assert detector.analyze([frame])['source_quality'] == 'unknown'
    detector.reader = SimpleNamespace(readtext=lambda *_a, **_k: [
        ([[10, 500], [250, 500], [250, 540], [10, 540]], '@creator_name', .9)])
    assert detector.analyze([frame])['source_quality'] == 'light-overlay'


def test_download_failures_do_not_consume_successful_probe_budget(tmp_path, monkeypatch):
    from hotpost import source_finder as sf, text_overlay
    from PIL import Image
    settings = Settings(data_dir=tmp_path, source_browser_search=False, source_use_openclip=False,
                        source_max_downloads=1, source_max_probe_downloads=2, source_max_attempts=4)
    post = Post('ref', 'u', int(time.time()), 'reel', caption='백팩')
    frame = tmp_path / 'frame.jpg'; Image.new('RGB', (20, 30), 'white').save(frame)
    monkeypatch.setattr(sf, '_post', lambda *_: post)
    monkeypatch.setattr(sf, '_download_reference', lambda *args: args[-1])
    def extract(_video, directory, *_a, **_k):
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'candidate_001.jpg'
        target.write_bytes(frame.read_bytes())
        return [target]
    monkeypatch.setattr(sf, 'extract_frames', extract)
    monkeypatch.setattr(sf, 'OpenClipVerifier', lambda *_: SimpleNamespace(error='', product_evidence=[], last_embedding=None,
                        subject_reference_indices=[], focus_subject=lambda _: None,
                        discover_product_queries=lambda: [], score=lambda _: .9))
    monkeypatch.setattr(sf, 'search_google_vision', lambda *_: ([], []))
    monkeypatch.setattr(sf, 'search_local_cache', lambda *_: [])
    monkeypatch.setattr(sf, 'search_web', lambda *_: [])
    monkeypatch.setattr(sf, 'search_bing', lambda *_: [])
    monkeypatch.setattr(sf, 'search_pexels', lambda *_: [])
    monkeypatch.setattr(sf, 'search_youtube', lambda *_: [Candidate(f'https://youtube.com/watch?v={i}', 'youtube') for i in range(6)])
    monkeypatch.setattr(text_overlay, 'TextOverlayDetector', lambda *_: SimpleNamespace(note='', reference_text=lambda _: '',
                        analyze=lambda _: {'source_quality': 'clean-source'}))
    attempts = []
    def download(candidate, directory, index, *_a, **_k):
        attempts.append(index)
        if len(attempts) <= 2:
            return None
        path = directory / f'{index}.mp4'; path.write_bytes(str(index).encode()); return path
    monkeypatch.setattr(sf, 'download_candidate', download)
    monkeypatch.setattr(sf, 'probe_video', lambda _: {'duration': 10, 'width': 720, 'height': 1280})
    def compare(_frames, video, directory):
        extract(video, directory)
        return .85
    monkeypatch.setattr(sf, 'compare_videos', compare)
    result = sf.find_sources(settings, 'ref')
    assert result['probe_attempts'] == 4 and result['probed_downloads'] == 2
    assert result['downloaded'] == 1
    assert Path(result['zip_path']).is_file()
def test_product_reference_omits_matching_intro_people():
    from hotpost.source_quality import subject_frame_indices
    assert set(subject_frame_indices([.17,.18,.30,.31,.29,.28], [.30,.29,.22,.23,.23,.24])) == {2,3,4,5}
    assert subject_frame_indices([.31,.18], [.20,.30]) == []
