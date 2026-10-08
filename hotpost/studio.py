"""Public Studio facade: resource ownership and composition of production services.

Implementation map: docs/studio_runtime_architecture.md. Keep this import stable
for the HTTP server, workflow integrations, tests, and operator scripts.
"""
from __future__ import annotations

import os
import re
import threading

from .studio_store import StudioStore
from .studio_workflow import WorkflowMixin
from .studio_sources import SourceAcquisitionMixin
from .studio_self_shot import SelfShotMixin
from .studio_runtime.commands import CommandsMixin
from .studio_runtime.media import MediaMixin
from .studio_runtime.lifecycle import LifecycleMixin
from .studio_runtime.generation import GenerationMixin
from .studio_runtime.editing import EditingMixin
from .studio_runtime.common import digest, selected

__all__ = ["Studio", "digest", "selected"]


class Studio(SelfShotMixin, CommandsMixin, MediaMixin, LifecycleMixin, GenerationMixin,
             EditingMixin, SourceAcquisitionMixin, WorkflowMixin):
    def __init__(self, settings, *, workers=True):
        self.settings = settings
        self.store = StudioStore(settings.data_dir / "studio")
        self.stop = threading.Event()
        self.render_lock = threading.Lock()
        self._lease = None
        if workers:
            self._lease = (self.store.root / "worker.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    self._lease.seek(0)
                    msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._lease.close(); self._lease = None
            if self._lease:
                self.store.recover()
                # Codex writing uses the CLI, while local media/model work
                # remains serial. A task has at most one production job at
                # once, enforced transactionally by StudioStore.claim. Saved
                # proposals remain non-mutating and can overlap media work.
                threading.Thread(target=self._worker, args=('media',), name='studio-production', daemon=True).start()
                threading.Thread(target=self._worker, args=('scripts',), name='studio-scripts', daemon=True).start()
                threading.Thread(target=self._worker, args=('sources',), name='studio-sources', daemon=True).start()
                if settings.studio_auto_top_enabled:
                    threading.Thread(target=self._watch_top, name='studio-top-two', daemon=True).start()

    def create(self, code, automation=None, *, with_created=False):
        from .storage import Storage
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", code):
            raise ValueError("올바르지 않은 게시물 ID")
        db = Storage(self.settings.db_path)
        try:
            row = db.conn.execute("SELECT * FROM posts WHERE shortcode=?", (code,)).fetchone()
            if not row or row["kind"] not in {"reel", "video"}:
                raise ValueError("수집된 동영상 게시물을 선택하세요.")
            title = re.sub(r"#\S+", "", row["caption"] or "").strip().split("\n")[0][:70] or code
        finally:
            db.close()
        state, created = self.store.create(code, title, automation)
        task = self.public(state)
        return (task, created) if with_created else task

    def folder(self, task_id):
        if not re.fullmatch(r"work-[a-f0-9]{16}", task_id):
            raise ValueError("올바르지 않은 제작 ID")
        path = self.store.root / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path
