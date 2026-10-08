"""Public shortlists enter the normal verification pipeline before web discovery."""
from types import SimpleNamespace

from hotpost.config import Settings
from hotpost.source_finder import Candidate
from hotpost.source_finder import search_local_cache
from hotpost.source_search.discovery import discover


def test_untried_public_hints_are_prioritized_and_canonical_duplicates_excluded(tmp_path):
    old = Candidate('https://www.youtube.com/watch?v=old123', 'test')
    fresh = Candidate('https://www.youtube.com/watch?v=new123', 'test')
    services = SimpleNamespace(search_local_hints=lambda *_: [old, fresh])
    progress = []
    candidates, queries, browser, audit, _ = discover(
        Settings(), 'post', [], ['tent'], {'products': []}, [], tmp_path,
        [], ['https://youtu.be/old123'], lambda *a: progress.append(a), services)
    assert candidates == [fresh]
    assert queries == ['tent'] and browser['candidates'] == []
    assert audit[0]['candidates'] == 1 and progress
    # Discovery never grants download, visual matching or editing eligibility.
    assert not fresh.downloaded_file and fresh.match_quality == 'unverified'


def test_exhausted_hints_resume_regular_providers(tmp_path):
    settings = Settings(source_browser_search=False)
    old = Candidate('https://www.youtube.com/watch?v=old123', 'test')
    fresh = Candidate('https://www.youtube.com/watch?v=new123', 'test')
    calls = []
    services = SimpleNamespace(
        search_local_hints=lambda *_: [old], _clean_visual_terms=lambda terms: terms,
        search_web=lambda *a: calls.append('web') or [],
        search_bing=lambda *a: calls.append('bing') or [],
        search_local_cache=lambda *a: [], search_youtube=lambda *a: [fresh],
        search_pexels=lambda *a: [], Candidate=Candidate)
    candidates, *_ = discover(settings, 'post', [], ['tent'], {'products': []}, [],
        tmp_path, [], [old.url], lambda *a: None, services)
    assert fresh in candidates and 'web' in calls and 'bing' in calls


def test_available_cache_is_revalidated_before_any_external_search(tmp_path):
    cached = Candidate('https://www.tiktok.com/@seller/video/7492345678901234567', 'cache', match_kind='cached-candidate')
    services = SimpleNamespace(search_local_cache=lambda *_:[cached], search_local_hints=lambda *_:[])
    candidates, _, browser, audit, _ = discover(Settings(data_dir=tmp_path), 'post', [], ['tent'],
        {}, [], tmp_path, [], [], lambda *a:None, services)
    assert candidates == [cached] and browser['candidates'] == []
    assert audit[0]['provider'] == 'local-cache'
    assert not cached.downloaded_file and cached.match_quality == 'unverified'


def test_inspected_cache_does_not_prevent_external_discovery_on_next_round(tmp_path):
    cached = Candidate('https://www.youtube.com/watch?v=cache123', 'cache')
    fresh = Candidate('https://www.youtube.com/watch?v=new123', 'youtube')
    calls = []
    services = SimpleNamespace(search_local_cache=lambda *_:[cached], search_local_hints=lambda *_:[],
        search_web=lambda *a: calls.append('web') or [], search_bing=lambda *a: [],
        search_youtube=lambda *a:[fresh], search_pexels=lambda *a:[], Candidate=Candidate)
    candidates, *_ = discover(Settings(data_dir=tmp_path, source_browser_search=False), 'post', [],
        ['tent'], {}, [], tmp_path, [], [cached.url], lambda *a:None, services)
    assert fresh in candidates and 'web' in calls


def test_cache_requires_existing_file_and_preserves_origin_without_granting_approval(tmp_path):
    import json
    settings = Settings(data_dir=tmp_path)
    folder = settings.source_dir/'post-1'
    (folder/'videos').mkdir(parents=True)
    (folder/'videos/valid.mp4').write_bytes(b'fixture')
    (folder/'manifest.json').write_text(json.dumps({'candidates':[
        {'url':'https://www.tiktok.com/@seller/video/7492345678901234567', 'selected_for_zip':True,
         'downloaded_file':'videos/missing.mp4'},
        {'url':'https://www.youtube.com/watch?v=valid123', 'selected_for_zip':True,
         'downloaded_file':'videos/valid.mp4', 'rights':'unknown-check-before-reuse'},
        {'url':'https://www.youtube.com/watch?v=rejected', 'selected_for_zip':True,
         'downloaded_file':'videos/valid.mp4', 'rejection_reasons':['different_core_function']},
    ]}), encoding='utf-8')
    found = search_local_cache(settings, 'post', 10)
    assert len(found) == 1 and found[0].url.endswith('valid123')
    assert found[0].rights == 'unknown-check-before-reuse'
    assert found[0].match_quality == 'unverified'
