import json

import pytest

from hotpost.cli import _sleep_after_account
from hotpost.collectors.base import CollectError
from hotpost.collectors.web_graphql import WebGraphQLCollector
from hotpost.config import Settings


def test_random_account_delay_uses_success_and_failure_ranges(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    settings.sleep_between_accounts = 4
    settings.sleep_between_accounts_max = 9
    settings.sleep_after_error_min = 20
    settings.sleep_after_error_max = 45
    ranges = []
    slept = []

    def choose(low, high):
        ranges.append((low, high))
        return (low + high) / 2

    monkeypatch.setattr("hotpost.cli.random.uniform", choose)
    monkeypatch.setattr("hotpost.cli.time.sleep", slept.append)
    monkeypatch.setattr("hotpost.cli._operational_event", lambda *_args: None)

    assert _sleep_after_account(settings, "web", "ok", "success", True) == 6.5
    assert _sleep_after_account(settings, "web", "failed", "failure", True) == 32.5
    assert ranges == [(4, 9), (20, 45)]
    assert slept == [6.5, 32.5]
    assert _sleep_after_account(settings, "web", "last", "success", False) == 0
    assert _sleep_after_account(settings, "demo", "demo", "failure", True) == 0


def test_graphql_error_diagnostic_excludes_tokens_and_variables(tmp_path):
    class Response:
        status_code = 200
        headers = {"x-fb-request-id": "request-123"}
        text = "for (;;);" + json.dumps({"error": 1357031, "errorSummary": "내용을 볼 수 없음"})
        content = text.encode()

    class Session:
        def post(self, *_args, **_kwargs):
            return Response()

    collector = WebGraphQLCollector.__new__(WebGraphQLCollector)
    collector.settings = Settings(data_dir=tmp_path)
    collector.settings.instagram_diagnostic_log_max_mb = 1
    collector.s = Session()
    collector.lsd = "SECRET_LSD"
    collector.dtsg = "SECRET_DTSG"
    collector._cookie = lambda _name: "SECRET_COOKIE"
    collector._discover = lambda _name: ("doc-456", [])

    with pytest.raises(CollectError, match="1357031"):
        collector._gql("PolarisProfilePostsQuery", {"username": "PRIVATE_VARIABLE"})

    for handler in collector._diagnostics.handlers:
        handler.flush()
    log = (tmp_path / "instagram_diagnostics.log").read_text(encoding="utf-8")
    assert '"error_code":1357031' in log
    assert '"doc_id":"doc-456"' in log
    assert '"http_status":200' in log
    assert '"request_id":"request-123"' in log
    assert "SECRET_LSD" not in log
    assert "SECRET_DTSG" not in log
    assert "SECRET_COOKIE" not in log
    assert "PRIVATE_VARIABLE" not in log
