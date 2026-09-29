"""Git tracks membership; each PC keeps notes, sessions and observations."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from .config import Settings
from .sources import extract_username
from .storage import Storage

_INIT_LOCK = threading.RLock()
_EMPTY = '# hotpost: empty-list'


def _read_entries(path):
    if not path.exists():
        return None, []
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('계정 목록은 UTF-8 텍스트여야 합니다. 기존 계정은 유지됩니다.') from exc
    entries, seen = [], set()
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name = extract_username(line)
        if not name:
            raise ValueError(f'계정 목록 {number}행을 확인하세요. Git 충돌 표시나 잘못된 계정이 있으면 반영하지 않습니다.')
        if name not in seen:
            note = line.split('|', 1)[1].strip()[:200] if '|' in line else ''
            entries.append((name, note)); seen.add(name)
    if not entries and _EMPTY not in text.splitlines():
        raise ValueError('빈 계정 파일은 자동 반영하지 않습니다. 전체 삭제는 계정 관리 화면에서 진행하세요.')
    return raw, entries


def _legacy_entries(path: Path) -> list[tuple[str, str]]:
    return _read_entries(path)[1]


class AccountRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        # A conflicted file is reported by the API, not a server startup crash.
        with _INIT_LOCK:
            store = Storage(settings.db_path)
            store.close()

    @contextmanager
    def _store(self):
        with _INIT_LOCK:
            store = Storage(self.settings.db_path)
            try:
                # Serialize file imports and UI edits across local processes.
                store.conn.execute('BEGIN IMMEDIATE')
                yield store
                store.conn.commit()
            except Exception:
                store.conn.rollback()
                raise
            finally:
                store.close()

    def _apply(self, store, raw, entries):
        if raw is None:
            return  # A missing file is not a request to delete accounts.
        digest = hashlib.sha256(raw).hexdigest()
        prior = store.conn.execute("SELECT value FROM app_meta WHERE key='accounts_file_sha256'").fetchone()
        if prior and prior[0] == digest:
            return
        rows = store.conn.execute('SELECT username,note,created_at,updated_at FROM managed_accounts ORDER BY created_at,username').fetchall()
        wanted = {name for name, _ in entries}
        removed = [dict(row) for row in rows if row['username'] not in wanted]
        if removed:
            backup = self.settings.data_dir / 'account-imports'
            backup.mkdir(parents=True, exist_ok=True)
            (backup / f'before-sync-{time.time_ns()}.json').write_text(
                json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2), encoding='utf-8')
        now = int(time.time())
        for order, (name, note) in enumerate(entries, 1):
            # Existing notes are local. Import legacy notes only for new rows.
            store.conn.execute('''INSERT OR IGNORE INTO managed_accounts(username,note,created_at,updated_at)
                VALUES (?,?,?,?)''', (name, note, now + order, now))
        store.conn.executemany('DELETE FROM managed_accounts WHERE username=?',
                              [(row['username'],) for row in removed])
        store.conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES ('accounts_file_sha256',?)", (digest,))
        store.conn.execute("INSERT OR IGNORE INTO app_meta(key,value) VALUES ('managed_accounts_initialized',?)", (str(now),))

    def _load(self, store):
        raw, entries = _read_entries(self.settings.influencer_file)
        self._apply(store, raw, entries)
        return raw

    def _write(self, expected, names):
        path = self.settings.influencer_file
        text = '# Shared monitoring accounts. Web changes update this file; commit/push to share.\n'
        text += '# Login sessions, collected data and local notes are not included.\n\n'
        text += ''.join(f'https://www.instagram.com/{name}/\n' for name in names) if names else _EMPTY + '\n'
        raw = text.encode('utf-8')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            current = path.read_bytes() if path.exists() else None
            if current != expected:
                raise ValueError('계정 파일이 다른 작업에서 변경됐습니다. 목록을 새로고침한 뒤 다시 저장하세요.')
            os.replace(temp, path)
        finally:
            Path(temp).unlink(missing_ok=True)
        # If DB commit fails, the next read recovers from the published file.
        return raw

    def list(self) -> list[dict]:
        with self._store() as store:
            raw = self._load(store)
            return self._ordered(store, raw)

    def _ordered(self, store, raw):
        rows = store.managed_accounts()
        if raw is not None:
            names = [extract_username(line) for line in raw.decode('utf-8-sig').splitlines()]
            order = {name: i for i, name in enumerate(names) if name}
            rows.sort(key=lambda row: order.get(row['username'], len(order)))
        return rows

    def usernames(self) -> list[str]:
        return [item['username'] for item in self.list()]

    def add(self, value: str, note: str = '') -> tuple[dict, bool]:
        username = extract_username(value)
        if not username:
            raise ValueError('올바른 Instagram 아이디 또는 프로필 URL을 입력하세요.')
        note = str(note).strip()
        if len(note) > 200:
            raise ValueError('메모는 200자 이내로 입력하세요.')
        with self._store() as store:
            raw = self._load(store)
            rows = self._ordered(store, raw)
            names = [row['username'] for row in rows]
            created = username not in names
            if created:
                names.append(username)
            if created or raw is None:
                written = self._write(raw, names)
                self._apply(store, written, [(name, '') for name in names])
            store.conn.execute('UPDATE managed_accounts SET note=?,updated_at=? WHERE username=?',
                               (note, int(time.time()), username))
            return next(row for row in store.managed_accounts() if row['username'] == username), created

    def delete(self, value: str) -> bool:
        username = extract_username(value)
        if not username:
            raise ValueError('올바르지 않은 Instagram 아이디입니다.')
        with self._store() as store:
            raw = self._load(store)
            names = [row['username'] for row in self._ordered(store, raw)]
            if username not in names:
                return False
            names.remove(username)
            written = self._write(raw, names)
            self._apply(store, written, [(name, '') for name in names])
            return True
