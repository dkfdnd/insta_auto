import json
from types import SimpleNamespace

import pytest

from hotpost.source_collection_access import collection_disabled
from hotpost.browser_search import BrowserSearcher
from hotpost.source_finder import Candidate, download_candidate
from hotpost.source_outcomes import platform_outcomes


def write_policy(root, platforms):
    (root/'source_collection_policy.json').write_text(json.dumps({
        'disabled_platforms':{platform:'사용자 요청' for platform in platforms}}), encoding='utf-8')


def test_switches_are_reversible_without_changing_auth(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)
    assert not collection_disabled('douyin', settings)
    write_policy(tmp_path, ['douyin','xiaohongshu'])
    assert collection_disabled('douyin', settings)
    assert collection_disabled('xiaohongshu', settings)
    assert not collection_disabled('tiktok', settings)
    write_policy(tmp_path, [])
    assert not collection_disabled('douyin', settings)


@pytest.mark.parametrize('platform', ['douyin','xiaohongshu'])
def test_disabled_browser_route_never_navigates(tmp_path, platform):
    write_policy(tmp_path, [platform])
    searcher = BrowserSearcher(SimpleNamespace(data_dir=tmp_path), tmp_path/'debug')
    # A context without new_page demonstrates the disabled branch never opens a page.
    searcher._platforms(object(), ['蒜末保存'], 5, providers={platform})
    assert searcher.searches[-1]['status'] == 'platform_disabled'
    outcome = platform_outcomes([], searcher.searches)[platform]
    assert outcome['search_attempts'] == 0
    assert outcome['skipped_reasons']['platform_disabled'] == 1


@pytest.mark.parametrize('url', [
    'https://www.douyin.com/video/123456789',
    'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'])
def test_indexed_or_deferred_disabled_url_never_downloads(tmp_path, monkeypatch, url):
    write_policy(tmp_path, ['douyin','xiaohongshu'])
    monkeypatch.setattr('hotpost.config.load_settings', lambda:SimpleNamespace(data_dir=tmp_path))
    candidate = Candidate(url=url, provider='google-lens')
    assert download_candidate(candidate, tmp_path/'videos', 1, 200) is None
    assert candidate.download_attempted is False
    assert candidate.rejection_reasons == ['platform_disabled']
    assert not (tmp_path/'videos').exists()
