import json

import pytest

from hotpost.collectors.base import CollectionBlocked
from hotpost.config import Settings
from hotpost.studio import Studio


@pytest.mark.parametrize('reason, expected', [('profile_busy', 'retry_wait'), ('login_required', 'attention'), ('verification_required', 'attention')])
def test_worker_waits_only_for_shared_profile_lease(tmp_path, monkeypatch, reason, expected):
    studio = Studio(Settings(data_dir=tmp_path), workers=False)
    state, _ = studio.store.create('lease-test', '브라우저 공유', {'protocol': 2, 'active': True, 'stage': 'prepare'})
    def blocked(*args):
        studio.stop.set()
        raise CollectionBlocked(reason, 'shared profile')
    monkeypatch.setattr(studio, '_prepare', blocked)
    studio._worker()
    saved = studio.store.get(state['id'])
    assert saved['status'] == expected
    with studio.store.connect() as db:
        job = dict(db.execute('SELECT * FROM jobs WHERE task_id=?', (state['id'],)).fetchone())
    checkpoint = json.loads(job['checkpoint'])
    if reason == 'profile_busy':
        assert job['status'] == 'queued'
        assert saved['error'] == ''
        assert checkpoint['not_before'] > 0
        assert checkpoint.get('auto_retries', 0) == 0
        assert not checkpoint.get('retry_requested')
        assert studio.store.claim() is None
        studio.store.recover()
        assert studio.store.claim() is None
    else:
        assert job['status'] == 'failed'
