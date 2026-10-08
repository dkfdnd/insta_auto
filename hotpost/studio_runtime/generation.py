"""Reference preparation, source refresh, script generation, and personal voice jobs."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..editing_adapter import _atomic_json, selected_source_videos
from ..local_compute import release_idle_voice, serialized_compute
from ..source_quality import editing_ready
from ..studio_store import uid
from ..studio_workflow import enabled, snapshot
from .common import digest


class GenerationMixin:
    def _prepare(self, state, job):
        if state.get('creation_mode') == 'self_shot':
            return self.prepare_self_shot(state, job)
        from ..source_finder import find_sources
        from ..transcript import extract_transcript
        from ..script_rewriter import rewrite
        def progress(message, pct):
            self.store.change(state['id'], lambda s, db: s.update(message=str(message)[:300], progress=pct))
        code = state["shortcode"]
        from ..reference_cache import reusable_reference
        # Search must see actual speech/OCR from this reference on the first run.
        transcripts = sorted(self.settings.transcript_dir.glob(f"{code}-*/transcript.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        transcript = None
        for path in transcripts:
            if not (reusable_reference(self.settings, code, path)
                    and reusable_reference(self.settings, code, path.parent/'reference.mp4')):
                continue
            try:
                cached = json.loads(path.read_text(encoding='utf-8'))
                if cached.get('speech') or cached.get('screen_text'):
                    transcript = path; break
            except (OSError, ValueError):
                continue
        if transcript is None:
            transcript = Path(extract_transcript(self.settings, code, progress)["json_path"])
        # Preserve acquired evidence even when the separate visual reading fails.
        self.store.change(state['id'], lambda s, db: s.update(
            transcript_path=str(transcript), reference_video=str(transcript.parent/'reference.mp4'),
            reference_speech_text='\n'.join(str(r.get('text','')) for r in
                json.loads(transcript.read_text('utf-8')).get('speech',[]))))
        from ..reference_narrative import reference_text
        progress('원본의 음성·화면 참고 내용을 구분하는 중', 85)
        narrative = reference_text(self.settings, transcript)
        original = narrative['text']
        def record_transcript(s, db):
            s.update(original_text=original, transcript_path=str(transcript), reference_video=str(transcript.parent / 'reference.mp4'))
            s.update(reference_kind=narrative['kind'], reference_speech_text=narrative['speech_text'],
                     reference_text_evidence=narrative if narrative['kind'] in {'screen_text','mixed'} else None)
            if enabled(s):
                snapshot(s)
        self.store.change(state['id'], record_transcript)
        if not original.strip():
            raise ValueError('집필할 원본 참고 내용이 없습니다.')
        if enabled(state):
            reference = transcript.parent / 'reference.mp4'
            if not reference.is_file():
                raise ValueError('대본 재가공에 필요한 기준 영상이 없습니다.')
            ids = job.get('payload', {}).get('source_ids')
            sources = [v for v in state['sources'] if ids is None or v['id'] in ids]
            manifest = self.folder(state['id'])/(job['id']+'-reference.json')
            _atomic_json(manifest, {'caption':state['title'], 'user_supplied':bool(ids),
                'downloaded':len(sources), 'candidates':[{'title':v.get('original_name',''),
                    'file_sha256':v['sha256'], 'original_url':v.get('origin_url',''),
                    'rights':v.get('rights','unknown'), 'selected_for_zip':True} for v in sources]})
            return {'original_text':original, 'reference_video':str(reference), 'transcript_path':str(transcript),
                    'sources':sources, 'manifest_path':str(manifest)}
        manifests = sorted(self.settings.source_dir.glob(f"{code}-*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        # User uploads are production assets, not another search request. Keep
        # their IDs/provenance so selected sources remain selected downstream.
        chosen_ids = job.get('payload', {}).get('source_ids')
        supplied = [v for v in state['sources'] if (chosen_ids is None or v['id'] in chosen_ids) and Path(v['path']).is_file()]
        if chosen_ids is not None and len(supplied) != len(set(chosen_ids)):
            raise ValueError('선택한 영상 파일이 없습니다. 영상을 다시 업로드하세요.')
        videos, manifest = [Path(v['path']) for v in supplied], None
        for candidate in ([] if supplied else manifests):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                data["candidates"] = [c for c in data.get("candidates", []) if editing_ready(c)]
                filtered = candidate.parent / "studio-selected.json"
                _atomic_json(filtered, data)
                videos = selected_source_videos(filtered)
                manifest = candidate
                break
            except (ValueError, OSError): continue
        if not videos:
            result = find_sources(self.settings, code, progress)
            manifest = Path(result["zip_path"]).parent / "manifest.json"
            data = json.loads(manifest.read_text(encoding='utf-8'))
            data['candidates'] = [c for c in data.get('candidates', []) if editing_ready(c)]
            filtered = manifest.parent / 'studio-selected.json'
            _atomic_json(filtered, data)
            videos = selected_source_videos(filtered)
        if not videos:
            raise ValueError('제작에 사용할 소스 영상이 없습니다. 자료를 확인하고 재시도하세요.')
        original = narrative['text']
        if not original.strip():
            raise ValueError('실제 발화 대본을 확보하지 못했습니다. OCR을 음성 대본으로 대체하지 않습니다.')
        if supplied:
            manifest = self.folder(state['id']) / (job['id']+'-user-sources.json')
            _atomic_json(manifest, {'caption': state['title'], 'user_supplied': True, 'downloaded': len(supplied), 'candidates': [
                {'title': v.get('original_name', ''), 'file_sha256': v['sha256'],
                 'original_url': v.get('origin_url', ''), 'rights': v.get('rights', 'unknown'),
                 'selected_for_zip': True} for v in supplied]})
        if state.get('automation'):
            reference = transcript.parent / 'reference.mp4'
            if not reference.is_file():
                raise ValueError('대본 재가공에 필요한 기준 영상이 없습니다.')
            products = json.loads(manifest.read_text(encoding='utf-8')).get('product_evidence', {}).get('products', []) if manifest else []
            product = next((p.get('ko') or p.get('en') for p in products if isinstance(p, dict)), '')
            return {'original_text':original, 'reference_video':str(reference), 'transcript_path':str(transcript),
                    'product':product or state['title'], 'sources':supplied or self._source_records(videos, manifest),
                    'manifest_path':str(manifest) if manifest else ''}
        existing = sorted((self.settings.data_dir / "productions" / code).glob("scripts-v*/scripts.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        script = json.loads(existing[0].read_text(encoding="utf-8")) if existing else rewrite(
            self.settings, transcript, manifest, self.folder(state["id"]) / "research", lambda *_: None)
        return {"text": script["variants"][0]["text"], "original_text": original,
                "sources": supplied or self._source_records(videos, manifest),
                "manifest_path": str(manifest)}

    def _refresh_sources(self, state, job):
        if state.get('creation_mode') == 'self_shot':
            raise ValueError('내 촬영 영상 작업에는 외부 영상을 수집하지 않습니다.')
        from ..source_finder import find_sources
        def progress(message, pct):
            def update(s, db):
                old = s.get('source_search', {})
                strategy_message = str(message) if str(message).startswith('검색 전략 · ') else old.get('strategy_message', '')
                s['source_search'] = {'status':'running', 'message':str(message)[:300], 'progress':pct,
                                      'strategy_message':strategy_message[:400]}
            self.store.change(state['id'], update)
        from ..source_search.strategy import restore_history
        acquisition = state.setdefault('source_acquisition', {})
        history = restore_history(acquisition)
        result = find_sources(self.settings, state['shortcode'], progress, search_request=job['payload'].get('request', ''),
                              search_round=max(1, acquisition.get('round', 0)), previous_searches=history,
                              exclude_urls=acquisition.get('urls', []),
                              search_context={'completed_rounds':acquisition.get('bounded_rounds',0),
                                              'rounds':acquisition.get('rounds',[])})
        manifest = Path(result['zip_path']).parent / 'manifest.json'
        videos = [manifest.parent / c['downloaded_file'] for c in result['candidates']
                  if c.get('selected_for_zip') and editing_ready(c)]
        records = self._source_records(videos, manifest)
        for record in records:
            record['id'] = uid('source-')
        return {'source_search_manifest_path': str(manifest), 'sources': records,
                'source_policy':result.get('source_policy'), 'platform_outcomes':result.get('platform_outcomes', {}),
                'platform_targets': result.get('platform_targets', {}), 'searches':result.get('search_audit', []),
                'attempted_urls':[c.get('original_url') or c.get('url') for c in result.get('candidates', [])
                                  if c.get('downloaded_file') or c.get('error')]}

    def _rewrite(self, state, job):
        if state.get('creation_mode') == 'self_shot':
            return self.write_self_shot(state, job)
        from ..studio_services import ensure_local
        from ..studio_automation import rewrite
        if state.get('automation', {}).get('needs_top_pick') and state.get('script_candidates'):
            from ..studio_top_pick import choose
            candidates = state['script_candidates']
            index, result = choose(self.settings, state, list(enumerate(candidates)))
            return {'text':candidates[index]['text'], 'top_pick':result, 'selected_candidate':index,
                    'selection_reason':result['reason']}
        ensure_local(self.settings, 'script')
        return rewrite(self, state, job)

    def _proposal(self, state, job):
        from ..studio_ai import propose_script
        script = next(s for s in state["scripts"] if s["id"] == job["payload"]["script_id"])
        text = job['payload'].get('base_text', script['text'])
        evidence = {**state, 'original_text':job['payload'].get('original_text', state.get('reviewed_original_text', state['original_text']))}
        return {**propose_script(self.settings, evidence, text, job["payload"]["request"]),
                'base_text':text, 'original_text':evidence['original_text'],
                'base_hash':hashlib.sha256(text.encode()).hexdigest(),
                "id": job["id"], "script_id": script["id"], "created": time.time()}

    @serialized_compute('voice')
    def _voice(self, state, job):
        from ..voicebench_adapter import VoiceBenchAdapter, verify_wav
        p = job["payload"]
        manual_voice = p.get('voice_mode') == 'manual' and bool(p.get('voice_profile_id'))
        voice_profile = p.get('voice_profile_id') if manual_voice else None
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        folder = self.folder(state["id"]) / p["voice_id"]
        folder.mkdir(exist_ok=True)
        voice = folder / "original.wav"
        metadata = folder / "tts.json"
        if metadata.is_file() and not manual_voice:
            cached = json.loads(metadata.read_text(encoding='utf-8'))
            if cached.get('voice_profile_id'):
                raise ValueError('저장된 음성은 다른 목소리입니다. 본인 복제 음성으로 새 버전을 만들어야 합니다.')
        if not (voice.is_file() and metadata.is_file()):
            if state.get('automation'):
                from ..studio_services import ensure_local
                ensure_local(self.settings, 'voice')
            def checkpoint(request_id):
                job["checkpoint"]["request_id"] = request_id
                job['checkpoint'].pop('retry_requested', None)
                self.store.checkpoint(job["id"], job["checkpoint"])
            result = VoiceBenchAdapter(self.settings).synthesize(p.get('spoken_text', script["text"]), voice,
                progress=lambda message, pct: self.store.change(state['id'], lambda s, db: s.update(message=message, progress=pct)),
                request_id=job["checkpoint"].get("request_id"), on_submitted=checkpoint,
                retry_failed=bool(job['checkpoint'].get('retry_requested')), generation_key=p.get('generation_key'),
                require_personal_clone=not manual_voice,
                **({'voice_profile_id':voice_profile} if voice_profile else {}))
            _atomic_json(metadata, result)
            release_idle_voice(self.settings, best_effort=True)
        result = json.loads(metadata.read_text(encoding="utf-8"))
        if p["speed"] != 1:
            voice = folder / "approved-listening.wav"
            self._process(state, job, "audio", {"input": str(folder / "original.wav"), "output": str(voice), "speed": p["speed"]})
        info = verify_wav(voice.read_bytes())
        return {"id": p["voice_id"], "script_id": script["id"], "path": str(voice), "sha256": digest(voice),
                "created": time.time(), "speed": p["speed"], "duration": info["duration"],
                "spoken_text": p.get('spoken_text', script['text']),
                "voice_profile_id": result.get('voice_profile_id') or '',
                "request_id": result["voicebench_request_id"], "quality_control": result.get("quality_control")}
