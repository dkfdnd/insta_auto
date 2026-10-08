"""Honor explicit collection resets without touching login or voice files."""
import json
from pathlib import Path


def reusable_reference(settings, shortcode, path):
    path = Path(path)
    if not path.is_file():
        return False
    reset_path = settings.data_dir/'collection_reset.json'
    if not reset_path.is_file():
        return True
    reset = json.loads(reset_path.read_text(encoding='utf-8'))
    return (shortcode not in reset.get('shortcodes', [])
            or path.stat().st_mtime >= float(reset.get('cache_after', 0)))
