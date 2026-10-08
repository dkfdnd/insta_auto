"""Local collection switches, independent of login and CAPTCHA state."""
import json


def disabled_platforms(settings=None):
    if settings is None:
        from .config import load_settings
        settings = load_settings()
    path = settings.data_dir / 'source_collection_policy.json'
    try:
        policy = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    disabled = policy.get('disabled_platforms', {})
    if not isinstance(disabled, dict):
        raise ValueError('소스 수집 플랫폼 설정 형식이 올바르지 않습니다.')
    return {key: str(reason) for key, reason in disabled.items() if reason}


def collection_disabled(platform, settings=None):
    return platform in disabled_platforms(settings)
