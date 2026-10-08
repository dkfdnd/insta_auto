"""Server-persisted dashboard display preferences (separate from scoring)."""
import json
import re

DEFAULTS = dict(detection='today', period=24, kind='all', tier=1, sort='rank', assessment='all', account='')
CHOICES = dict(detection=('all', 'today'), period=(24, 72, 168, 336, 720),
               kind=('all', 'video', 'image'), tier=(0, 1, 2, 3),
               sort=('rank', 'views', 'comments', 'likes', 'recent'),
               assessment=('all', 'confirmed', 'provisional'))


def read(store):
    row = store.conn.execute("SELECT value FROM app_meta WHERE key='display_settings'").fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def save(store, values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError('화면 설정 항목을 확인하세요.')
    for key, choices in CHOICES.items():
        if type(values[key]) is not type(DEFAULTS[key]) or values[key] not in choices:
            raise ValueError(f'올바르지 않은 화면 설정: {key}')
    if not isinstance(values['account'], str) or not re.fullmatch(r'[A-Za-z0-9_.]{0,30}', values['account']):
        raise ValueError('올바르지 않은 계정 필터')
    store.conn.execute("INSERT INTO app_meta(key,value) VALUES('display_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (json.dumps(values),))
    store.conn.commit()
    return values
