"""A changed keyword cannot repair an unresolved search-page parser."""
import json
import time
from pathlib import Path


def parser_revision(provider):
    # Version changes authorize one check of the repaired parser, not an auth
    # bypass. Existing authentication gates remain independent and authoritative.
    return 'tiktok-search-response-v1' if provider == 'tiktok' else 'platform-links-v1'


def readiness_record(data_dir, provider):
    try:
        value = json.loads((Path(data_dir)/'search_readiness'/f'{provider}.json').read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):
        return {}


def readiness_blocked(data_dir, provider):
    record = readiness_record(data_dir,provider)
    return (record.get('reason') == 'page_unresolved'
            and record.get('parser_revision') == parser_revision(provider)
            and not record.get('recheck_requested'))


def record_unresolved(data_dir, provider, query):
    from ..editing_adapter import _atomic_json
    _atomic_json(Path(data_dir)/'search_readiness'/f'{provider}.json',
                 {'reason':'page_unresolved','parser_revision':parser_revision(provider),
                  'at':time.time(),'query':query,'recheck_requested':False})


def request_readiness_recheck(data_dir, provider):
    """Called only by the existing explicit session-save/recheck action."""
    from ..editing_adapter import _atomic_json
    record = readiness_record(data_dir,provider)
    if not record:
        return False
    record.update(recheck_requested=True,recheck_at=time.time())
    _atomic_json(Path(data_dir)/'search_readiness'/f'{provider}.json',record)
    return True
