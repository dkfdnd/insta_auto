"""Read-only API projections and task-scoped media access."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..studio_sources import source_goal
from .common import digest


class MediaMixin:
    def public(self, state):
        state = copy.deepcopy(state)
        state['source_search_retry_supported'] = True
        state['caption_editor_supported'] = True
        if state.get("manifest_path"):
            state["sources"] = self._source_records([s["path"] for s in state["sources"]], state["manifest_path"], state["sources"])
            from ..source_audit import summarize
            state['source_audit'] = summarize(state.get('source_search_manifest_path') or state['manifest_path'],
                                               reviewed_sources=state['sources'])
        for collection in ("scripts", "voices", "edits"):
            for item in state[collection]:
                for field in ("path", "preview_path", "cover_path", "clean_preview_path", "export_path"):
                    if item.get(field):
                        item[field.replace("_path", "") + "_url"] = self.media_url(state["id"], item[field])
                if collection == "edits" and item.get("plan_path"):
                    plan = json.loads(Path(item["plan_path"]).read_text(encoding="utf-8"))
                    for shot in plan.get("shots", []):
                        shot["thumbnail_url"] = self.media_url(state["id"], shot["frames"][1 if len(shot["frames"]) > 1 else 0])
                        shot["video_url"] = self.media_url(state["id"], shot["path"])
                    item["plan"] = plan
        for source in state["sources"]:
            source["url"] = self.media_url(state["id"], source["path"])
        state['original_evidence'] = {'speech': [], 'screen_text': []}
        if state.get('transcript_path'):
            try:
                transcript = json.loads(Path(state['transcript_path']).read_text(encoding='utf-8'))
                state['original_evidence'] = {key: transcript.get(key, []) for key in ('speech', 'screen_text')}
                state['original_evidence']['speech_unavailable'] = transcript.get('methods', {}).get('speech') == 'unavailable'
            except (OSError, ValueError):
                pass
        reference = Path(state.get('reference_video') or '')
        if reference.is_file() and reference.is_relative_to(self.settings.data_dir.resolve()):
            state['reference_url'] = self.media_url(state['id'], reference)
        state["jobs"] = self.store.jobs(state["id"])
        state['source_goal'] = source_goal(state, self.settings.source_min_usable)
        state['events'] = self.store.events(state['id'])
        state['pipeline'] = self.pipeline(state)
        return state

    @staticmethod
    def _source_records(videos, manifest, existing=None):
        from urllib.parse import urlparse
        try:
            data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if existing is not None: return existing
            raise
        records = []
        for i, raw in enumerate(videos):
            path = Path(raw)
            record = dict(existing[i]) if existing else {"id": f"source-{i}", "path": str(path), "sha256": digest(path)}
            candidates = data.get('candidates', [])
            candidate = next((c for c in candidates if c.get('file_sha256') == record['sha256']), None)
            if candidate is None:
                candidate = next((c for c in candidates if c.get('downloaded_file')
                                  and (Path(manifest).parent / c['downloaded_file']).resolve() == path.resolve()), {})
            if not candidate and existing:
                records.append(record)
                continue
            url = candidate.get("original_url") or candidate.get("url", "")
            record.update(origin_url=url if urlparse(url).scheme in {"http", "https"} else "",
                          rights=candidate.get("rights", "unknown"), manifest_path=str(manifest))
            for key in ('source_quality', 'functional_review', 'blur_required', 'watermark_masks', 'frame_hashes', 'editing_eligible'):
                if key in candidate and key not in record:
                    record[key] = candidate[key]
            records.append(record)
        return records

    def media_url(self, task_id, raw):
        from urllib.parse import quote
        relative = Path(raw).resolve().relative_to(self.settings.data_dir.resolve()).as_posix()
        return f"/api/studio/{task_id}/media?file={quote(relative)}"

    def media(self, task_id, relative):
        state = self.store.get(task_id)
        path = (self.settings.data_dir / relative).resolve()
        own = self.folder(task_id).resolve()
        sources = {Path(s["path"]).resolve() for s in state["sources"]}
        if state.get('reference_video'):
            sources.add(Path(state['reference_video']).resolve())
        if not path.is_file() or not path.is_relative_to(self.settings.data_dir.resolve()):
            raise ValueError("미디어 파일을 찾을 수 없습니다.")
        if not path.is_relative_to(own) and path not in sources:
            raise ValueError("이 작업의 미디어 파일이 아닙니다.")
        if path.suffix.lower() not in {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".wav", ".txt", ".srt"}:
            raise ValueError("지원하지 않는 미디어 형식")
        return path
