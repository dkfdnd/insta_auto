from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.search_access import access_record, indexed_gate, request_manual_recheck
from hotpost import source_finder
from hotpost.source_outcomes import platform_outcomes
from hotpost.source_search.strategy import merge_history


@pytest.mark.parametrize('provider,search', [('duckduckgo', source_finder.search_web), ('bing', source_finder.search_bing)])
def test_challenge_stops_remaining_queries_and_subsequent_calls(tmp_path, monkeypatch, provider, search):
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr('hotpost.config.load_settings', lambda: settings)
    monkeypatch.setattr(source_finder, 'request_pause', lambda: None)
    calls = []
    def get(*a, **k):
        calls.append(a)
        return SimpleNamespace(status_code=202, url='https://example.test/search',
                               text='<form id="challenge-form">Unfortunately, bots use DuckDuckGo too.</form>')
    monkeypatch.setattr(source_finder.requests, 'get', get)
    audit = []
    assert search(['cabinet', 'cabinet closeup', 'cabinet demo'], 6, audit) == []
    assert len(calls) == 1 and audit[0]['status'] == 'captcha'
    assert audit[0]['http_status'] == 202 and audit[0]['requests']
    assert search(['other cabinet'], 6, audit) == []
    assert len(calls) == 1 and audit[-1]['status'] == 'verification_required'
    assert not audit[-1].get('requests')
    assert access_record(tmp_path, provider)['requires_verification']
    assert request_manual_recheck(tmp_path, provider)
    assert search(['other cabinet'], 6, audit) == []
    assert len(calls) == 2 and access_record(tmp_path, provider)['requires_verification']


def test_unused_script_and_accepted_status_do_not_claim_challenge(tmp_path):
    response = SimpleNamespace(status_code=202, url='https://example.test/search',
        text='<script>const warning="verify you are human"</script><main>Search results</main>')
    assert indexed_gate('duckduckgo', response, Settings(data_dir=tmp_path)) == {}
    assert not access_record(tmp_path, 'duckduckgo')


def test_rate_limit_stops_without_permanent_authentication_gate(tmp_path):
    settings = Settings(data_dir=tmp_path)
    response = SimpleNamespace(status_code=429, url='https://example.test/search', text='Too many requests')
    assert indexed_gate('bing', response, settings)['status'] == 'rate_limited'
    assert indexed_gate('bing', settings=settings)['status'] == 'cooldown'
    assert not access_record(tmp_path, 'bing')['requires_verification']


def test_indexed_auth_gate_preserves_platform_failure_without_counting_skips_as_requests():
    query = 'cabinet site:tiktok.com/@ inurl:video'
    attempted = {'provider':'duckduckgo', 'query':query, 'status':'captcha', 'http_status':202,
                 'reason':'captcha', 'requests':[{'operation':'indexed_search','at':1}]}
    skipped = {'provider':'duckduckgo', 'query':query, 'status':'verification_required', 'reason':'captcha'}
    outcome = platform_outcomes([], [attempted, skipped], {'tiktok':5})['tiktok']
    assert outcome['search_attempts'] == 1
    assert outcome['reasons']['captcha'] == 1
    assert outcome['skipped_reasons']['verification_required'] == 1
    assert merge_history([attempted])[0]['http_status'] == 202
