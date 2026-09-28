import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hotpost.config import Settings
from hotpost.production_health import check


def test_reachable_voice_server_with_missing_engine_is_not_ready():
    session = Mock()
    session.get.side_effect = [
        Mock(status_code=200),
        Mock(status_code=200, json=lambda: {'ready': False, 'errors': ['기본 엔진 없음']}),
    ]
    with patch('hotpost.production_health.requests.Session') as sessions, \
         patch('hotpost.production_health.StudioAdapter.headers', return_value={}), \
         patch('hotpost.production_health.VoiceBenchAdapter._headers', return_value={}), \
         patch('hotpost.production_health.subprocess.run', return_value=SimpleNamespace(stdout=json.dumps({'ready': True}))):
        sessions.return_value.__enter__.return_value = session
        result = check(Settings())
    assert result['ready'] is False
    assert result['checks']['voicebench'] == {'ready': False, 'message': '기본 엔진 없음'}
