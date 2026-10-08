from types import SimpleNamespace
import json
from hotpost.login_exchange import publish_session, apply_sessions, read_session, downloader_cookies
from hotpost.browser_profile import save_platform_cookies


def cookie(value):
    return dict(domain='.tiktok.com', path='/', name='sessionid', value=value, expires=-1)


def test_collector_cannot_overwrite_new_login_and_refresh_survives(tmp_path):
    publish_session([cookie('new-login')], tmp_path, 'tiktok')
    save_platform_cookies([cookie('old-search')], tmp_path, 'tiktok')
    assert read_session(tmp_path, 'tiktok')['cookies'][0]['value'] == 'new-login'
    received = []
    context = SimpleNamespace(add_cookies=received.extend)
    profile = tmp_path/'search-profile'
    apply_sessions(context, tmp_path, profile, ['tiktok'])
    assert received == [cookie('new-login')]
    received.clear()
    apply_sessions(context, tmp_path, profile, ['tiktok'])
    assert received == [], 'Do not replace cookies refreshed by the live profile'
    publish_session([cookie('next-login')], tmp_path, 'tiktok')
    apply_sessions(context, tmp_path, profile, ['tiktok'])
    assert received == [cookie('next-login')]


def test_empty_login_and_other_platform_do_not_erase_session(tmp_path):
    publish_session([cookie('saved')], tmp_path, 'tiktok')
    publish_session([], tmp_path, 'tiktok')
    publish_session([cookie('different')], tmp_path, 'douyin')
    assert read_session(tmp_path, 'tiktok')['cookies'] == [cookie('saved')]
    assert not read_session(tmp_path, 'douyin')


def test_downloader_uses_private_copy_of_latest_manual_session(tmp_path):
    fallback = tmp_path/'source_browser_cookies.txt'
    fallback.write_text('old-search')
    publish_session([cookie('latest')], tmp_path, 'tiktok')
    private_copy = downloader_cookies(fallback, 'tiktok', tmp_path/'job')
    assert 'latest' in private_copy.read_text()
    private_copy.write_text('downloader changed its own cookie jar')
    assert read_session(tmp_path, 'tiktok')['cookies'] == [cookie('latest')]
    assert fallback.read_text() == 'old-search'
