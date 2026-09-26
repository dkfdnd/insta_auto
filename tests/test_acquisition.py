import json
import subprocess
import xml.etree.ElementTree as ET

from hotpost.acquisition import acquire, candidates
from hotpost.config import Settings
from hotpost.scheduler import windows_task_xml


def report():
    return {'is_sample': False, 'accounts': [{'username': 'small', 'followers': 1000},
        {'username': 'large', 'followers': 1000000}, {'username': 'unknown', 'followers': 0}],
        'posts': [{'shortcode': user, 'username': user, 'kind': 'reel', 'views': 10000}
                  for user in ('small', 'large', 'unknown')]}


def test_acquisition_uses_followers_and_excludes_unknown_or_stale():
    settings = Settings()
    value = report()
    assert [p['shortcode'] for p in candidates(value, settings)] == ['small']
    value['posts'][0]['metric_status'] = {'views': 'stale'}
    assert candidates(value, settings) == []


def test_acquisition_retries_only_failed_stage_and_preserves_success(tmp_path):
    settings = Settings(data_dir=tmp_path)
    calls = []
    def transcript(settings, code, progress):
        calls.append('transcript')
        path = tmp_path / 'transcript.json'
        path.write_text('{}')
        return {'json_path': str(path), 'speech': [{'text': '원본 발화예요.'}]}
    def source(settings, code, progress):
        calls.append('source')
        if calls.count('source') == 1:
            raise RuntimeError('temporary download failure')
        path = tmp_path / 'sources.zip'
        path.write_bytes(b'zip')
        return {'zip_path': str(path), 'downloaded': 1}
    workers = {'transcript': transcript, 'source': source}
    acquire(settings, report(), lambda _: None, workers)
    acquire(settings, report(), lambda _: None, workers)
    acquire(settings, report(), lambda _: None, workers)
    assert calls == ['transcript', 'source', 'source']


def test_empty_acquisition_is_failure_and_can_be_retried(tmp_path):
    settings = Settings(data_dir=tmp_path)
    path = tmp_path / 'empty.json'
    path.write_text('{}')
    def empty(*args):
        return {'json_path': str(path), 'speech': [], 'downloaded': 0}
    for _ in range(2):
        results = acquire(settings, report(), lambda _: None,
                          {'transcript': empty, 'source': empty})
        assert len(results) == 2
        assert all(row['status'] == 'error' for row in results)


def test_windows_schedule_uses_korean_time_and_acquires_materials():
    root = ET.fromstring(windows_task_xml(7, 0).split('\n', 1)[1])
    assert root.findtext('.//{*}StartBoundary').endswith('T07:00:00+09:00')
    assert '--acquire' in root.findtext('.//{*}Arguments')
    assert root.findtext('.//{*}LogonType') == 'InteractiveToken'
    assert root.findtext('.//{*}MultipleInstancesPolicy') == 'IgnoreNew'


def test_windows_schedule_status_is_read_only(monkeypatch):
    from hotpost import scheduler
    monkeypatch.setattr(scheduler.sys, 'platform', 'win32')
    calls = []
    def run(args, **kwargs):
        import json
        calls.append(json.loads(kwargs['input']))
        return subprocess.CompletedProcess(args, 0, '{"hour":7,"installed":true}', '')
    monkeypatch.setattr(scheduler.subprocess, 'run', run)
    assert scheduler.schedule_status()['hour'] == 7
    assert len(calls) == 1 and calls[0]['action'] == 'status'
