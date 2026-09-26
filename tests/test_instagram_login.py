from types import SimpleNamespace

import pytest
import requests

from hotpost import instagram_login
from hotpost.collectors.base import CollectError
from hotpost.collectors import instaloader_collector
from hotpost.config import Settings


@pytest.mark.parametrize("detected", [None, "other_account"])
def test_failed_verification_preserves_existing_session(tmp_path, monkeypatch, detected):
    settings = Settings(data_dir=tmp_path)
    target = instagram_login.session_file(settings, "expected")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing-session")
    loader = SimpleNamespace(context=SimpleNamespace(_session=requests.Session()), test_login=lambda: detected)
    monkeypatch.setattr(instagram_login, "make_loader", lambda: loader)
    with pytest.raises(CollectError):
        instagram_login.save_verified_session(settings, "expected", [
            {"domain": ".instagram.com", "name": "sessionid", "value": "test-only"}])
    assert target.read_bytes() == b"existing-session"


def test_verified_session_ignores_unrelated_domains(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    session = requests.Session()
    def save(path):
        from pathlib import Path
        assert set(session.cookies.keys()) == {"sessionid"}
        Path(path).write_bytes(b"verified-session")
    loader = SimpleNamespace(context=SimpleNamespace(_session=session),
                             test_login=lambda: "expected", save_session_to_file=save)
    monkeypatch.setattr(instagram_login, "make_loader", lambda: loader)
    target = instagram_login.save_verified_session(settings, "expected", [
        {"domain": ".instagram.com", "name": "sessionid", "value": "test-only"},
        {"domain": "evilinstagram.com", "name": "unrelated", "value": "test-only"}])
    assert target.read_bytes() == b"verified-session"


def test_browser_decryption_failure_has_actionable_safe_error(tmp_path, monkeypatch):
    import browser_cookie3
    def fail(**kwargs):
        raise RuntimeError("sensitive-internal-value")
    monkeypatch.setattr(browser_cookie3, "chrome", fail)
    with pytest.raises(CollectError, match="dedicated") as error:
        instaloader_collector.login_from_browser(Settings(data_dir=tmp_path), "expected", "chrome")
    assert "sensitive-internal-value" not in str(error.value)
