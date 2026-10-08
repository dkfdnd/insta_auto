"""Small shared value helpers, also re-exported by hotpost.studio."""
from pathlib import Path

from ..source_quality import sha256_file


def digest(path):
    return sha256_file(Path(path))


def selected(state, collection, key):
    return next((r for r in state[collection] if r["id"] == state.get(key)), None)
