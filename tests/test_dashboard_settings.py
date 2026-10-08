import json
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from hotpost import display_settings
from hotpost.categories import post_categories, category_topics
from hotpost.config import Settings
from hotpost.server import serve
from hotpost.storage import Storage


def test_display_settings_and_notification_http_roundtrip(tmp_path):
    settings = Settings(data_dir=tmp_path, web_dir=tmp_path, influencer_file=tmp_path/'accounts.txt')
    server = serve(settings, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    def request(path, method='GET', data=None):
        body = json.dumps(data).encode() if data is not None else None
        with urlopen(Request(base+path, data=body, method=method,
                             headers={'Content-Type':'application/json'})) as response:
            return json.load(response)
    try:
        values = request('/api/display-settings')['values']
        assert values == display_settings.DEFAULTS
        assert values['detection'] == 'today' and values['period'] == 24
        values.update(detection='all', period=72, kind='video', sort='views', account='creator')
        request('/api/display-settings', 'PUT', {'values': values})
        assert request('/api/display-settings')['values'] == values
        for bad in ({**values, 'period':1}, {**values, 'tier':True}, {**values, 'account':'<script>'}):
            with pytest.raises(HTTPError) as error:
                request('/api/display-settings', 'PUT', {'values':bad})
            assert error.value.code == 400
        with _store(settings) as store:
            assert display_settings.read(store) == values
            for i in range(55): store.notify('test', f'test-{i}', f'알림 {i}')
        notifications = request('/api/notifications')
        assert len(notifications['notifications']) == 50 and notifications['unseen'] == 55
        item = notifications['notifications'][0]
        request(f'/api/notifications/{item["id"]}/seen', 'POST')
        assert request('/api/notifications/seen', 'DELETE')['deleted'] == 1
        assert request('/api/notifications')['unseen'] == 54
    finally:
        server.shutdown(); server.server_close(); thread.join()


@contextmanager
def _store(settings):
    store=Storage(settings.db_path)
    try: yield store
    finally: store.close()


def test_topics_are_broad_categories_not_arbitrary_caption_words():
    def post(text, tags=()):
        return SimpleNamespace(caption=text, hashtags=list(tags), username='creator', shortcode=text)
    assert post_categories(post('부담 곤란 한참')) == ['생활·기타']
    assert post_categories(post('가벼운 수납 가방으로 차박 캠핑 여행')) == ['캠핑·여행']
    assert post_categories(post('이 제품 좋아요', ['주방템', '요리'])) == ['주방·요리']
    items = [SimpleNamespace(post=post('청소 곰팡이 욕실'), tier=2),
             SimpleNamespace(post=post('물때 청소'), tier=1),
             SimpleNamespace(post=post('주방 요리'), tier=0)]
    topics=category_topics(items,10)
    assert len(topics)==1 and topics[0]['label']=='청소·세탁' and topics[0]['posts']==2


def test_report_endpoint_reads_latest_snapshot_without_cache(tmp_path):
    settings=Settings(data_dir=tmp_path, influencer_file=tmp_path/'accounts.txt')
    server=serve(settings,port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        for timestamp in (1,2):
            settings.report_path.write_text(json.dumps({'generated_at':timestamp,'posts':[]}),encoding='utf-8')
            with urlopen(base+'/api/report') as response:
                assert response.headers['Cache-Control']=='no-store'
                assert json.load(response)['generated_at']==timestamp
        settings.report_path.write_text('{incomplete',encoding='utf-8')
        with pytest.raises(HTTPError) as error: urlopen(base+'/api/report')
        assert error.value.code==503
    finally:
        server.shutdown();server.server_close();thread.join()
