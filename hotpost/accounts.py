"""웹과 CLI가 함께 사용하는 Instagram 모니터링 계정 레지스트리."""
from __future__ import annotations

import threading
from pathlib import Path

from .config import Settings
from .sources import extract_username
from .storage import Storage

_INIT_LOCK = threading.Lock()


def _legacy_entries(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    seen = set()
    entries = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        username = extract_username(raw)
        if not username or username in seen:
            continue
        note = raw.split("|", 1)[1].strip()[:200] if "|" in raw else ""
        seen.add(username); entries.append((username, note))
    return entries


class AccountRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        with _INIT_LOCK:
            store = Storage(settings.db_path)
            try:
                store.initialize_managed_accounts(_legacy_entries(settings.influencer_file))
            finally:
                store.close()

    def list(self) -> list[dict]:
        store = Storage(self.settings.db_path)
        try:
            return store.managed_accounts()
        finally:
            store.close()

    def usernames(self) -> list[str]:
        return [item["username"] for item in self.list()]

    def add(self, value: str, note: str = "") -> tuple[dict, bool]:
        username = extract_username(value)
        if not username:
            raise ValueError("올바른 Instagram 아이디 또는 프로필 URL을 입력하세요.")
        note = str(note).strip()
        if len(note) > 200:
            raise ValueError("메모는 200자 이내로 입력하세요.")
        store = Storage(self.settings.db_path)
        try:
            created = store.upsert_managed_account(username, note)
            item = next(row for row in store.managed_accounts() if row["username"] == username)
            return item, created
        finally:
            store.close()

    def delete(self, value: str) -> bool:
        username = extract_username(value)
        if not username:
            raise ValueError("올바르지 않은 Instagram 아이디입니다.")
        store = Storage(self.settings.db_path)
        try:
            return store.delete_managed_account(username)
        finally:
            store.close()
