"""Read original post text without confusing it with a speech transcript."""
import sqlite3
import json
from pathlib import Path


def reference_kind(state):
    """Only label speech/screen text when the stored source establishes it."""
    explicit = state.get('reference_kind')
    if explicit in {'speech', 'screen_text', 'mixed', 'provided_text'}:
        return explicit
    text = state.get('reviewed_original_text', state.get('original_text', ''))
    path = Path(state.get('transcript_path') or '')
    if text and path.is_file():
        try:
            source = json.loads(path.read_text(encoding='utf-8'))
            for kind, key in [('speech', 'speech'), ('screen_text', 'screen_text')]:
                value = '\n'.join(str(r.get('text', '')) for r in source.get(key, []))
                if ''.join(value.split()) == ''.join(text.split()):
                    return kind
        except (OSError, ValueError, TypeError):
            pass
    return 'provided_text'


def post_caption(settings, state):
    if state.get('original_caption'):
        return str(state['original_caption'])[:12000]
    path = settings.db_path
    if not path.is_file() or not state.get('shortcode'):
        return ''
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=10)
    try:
        row = db.execute('SELECT caption FROM posts WHERE shortcode=?', (state['shortcode'],)).fetchone()
        return str(row[0] or '')[:12000] if row else ''
    finally:
        db.close()
