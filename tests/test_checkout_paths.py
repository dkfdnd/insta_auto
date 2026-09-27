from hotpost import config


def test_existing_checkout_aliases_resolve_services_and_keys(tmp_path, monkeypatch):
    root = tmp_path / 'insta_auto'
    root.mkdir()
    for folder, marker in [('Voice', 'voicebench/api.py'), ('PersonalProject1', 'studio/app.py')]:
        path = tmp_path / folder / marker
        path.parent.mkdir(parents=True)
        path.touch()
    monkeypatch.setattr(config, 'ROOT', root)
    settings = config.Settings()
    assert settings.voicebench_root == tmp_path / 'Voice'
    assert settings.voicebench_api_key_file == settings.voicebench_root / '.runtime/external-api-key.txt'
    assert settings.studio_root == tmp_path / 'PersonalProject1'
    assert settings.studio_api_key_file == settings.studio_root / 'data/access-token.txt'
    assert settings.voicebench_url.endswith(':8765')


def test_canonical_checkout_wins_only_when_it_contains_service(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path / 'insta_auto')
    (tmp_path / 'VoiceBench').mkdir()
    marker = tmp_path / 'Voice/voicebench/api.py'
    marker.parent.mkdir(parents=True)
    marker.touch()
    assert config.Settings().voicebench_root == tmp_path / 'Voice'
    canonical = tmp_path / 'VoiceBench/voicebench/api.py'
    canonical.parent.mkdir()
    canonical.touch()
    assert config.Settings().voicebench_root == tmp_path / 'VoiceBench'
