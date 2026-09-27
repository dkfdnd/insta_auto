import sys
import time

from hotpost.source_browser_worker import run_bounded, isolated_search
from hotpost.config import Settings


SCRIPT = """
import sys,json,time
from pathlib import Path
p=json.load(sys.stdin)
Path(p['checkpoint']).write_text(json.dumps({'message':'saved','candidates':[{'url':'https://youtu.be/test'}],
    'terms':[],'notes':[],'searches':[{'provider':'youtube','status':'results'}]}),encoding='utf-8')
time.sleep(p['sleep'])
"""


def test_hung_worker_is_stopped_and_completed_results_survive(tmp_path):
    checkpoint = tmp_path / 'snapshot.json'
    started = time.monotonic()
    result = run_bounded([sys.executable, '-c', SCRIPT], {'checkpoint': str(checkpoint), 'sleep': 30},
                         checkpoint, 2)
    assert time.monotonic() - started < 15
    assert result['candidates'][0]['url'] == 'https://youtu.be/test'
    assert result['searches'][-1]['status'] == 'timeout'
    assert '보존' in result['notes'][-1]


def test_completed_worker_returns_final_checkpoint(tmp_path):
    checkpoint = tmp_path / 'snapshot.json'
    result = run_bounded([sys.executable, '-c', SCRIPT], {'checkpoint': str(checkpoint), 'sleep': 0},
                         checkpoint, 5)
    assert result['notes'] == [] and len(result['candidates']) == 1


def test_real_worker_bootstrap_without_external_browser(tmp_path):
    # Real module startup, settings/path serialization and private checkpoint IO.
    result = isolated_search(Settings(data_dir=tmp_path, source_browser_search=False), [], ['query'],
                             1, tmp_path/'debug')
    assert result == {'candidates': [], 'terms': [], 'notes': [], 'searches': []}
