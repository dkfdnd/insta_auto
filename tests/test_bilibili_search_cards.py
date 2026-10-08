from types import SimpleNamespace

from hotpost.browser_search import _anchors
from hotpost.source_search.models import Candidate
from hotpost.source_search.triage import discovery_duration_reasons


def test_thumbnail_stats_do_not_replace_title_and_known_duration_prevents_long_download():
    url = 'https://www.bilibili.com/video/BV1W94y1i7q4/'
    rows = [
        {'href':url, 'text':'22.7万 91 09:35'},
        {'href':url, 'text':'竹制展示柜收纳玩具', 'title':'竹制展示柜收纳玩具'},
    ]
    page = SimpleNamespace(url='https://search.bilibili.com',
                           locator=lambda _:SimpleNamespace(evaluate_all=lambda _:rows))
    found = _anchors(page, 'playwright-bilibili', '竹制展示柜', 'platform-search')
    assert len(found) == 1
    assert found[0]['title'] == '竹制展示柜收纳玩具'
    assert found[0]['discovery_meta']['duration'] == 575
    assert discovery_duration_reasons(Candidate(**found[0]), 300) == ['invalid_duration']


def test_card_duration_is_metadata_and_does_not_grant_visual_approval():
    page = SimpleNamespace(url='https://search.bilibili.com',
        locator=lambda _:SimpleNamespace(evaluate_all=lambda _:[
            {'href':'https://www.bilibili.com/video/BV1NGTQ6rEfv', 'text':'展示柜', 'duration':'01:31'}]))
    candidate = Candidate(**_anchors(page, 'playwright-bilibili', '展示柜', 'platform-search')[0])
    assert candidate.discovery_meta['duration'] == 91
    assert not discovery_duration_reasons(candidate, 300)
    assert candidate.match_quality == 'unverified'
