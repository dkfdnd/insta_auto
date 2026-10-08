"""CapCut process boundary and editable video generation jobs."""
from __future__ import annotations

import json
import hashlib
import subprocess
import time
from pathlib import Path

from ..editing_adapter import _atomic_json
from ..studio_store import Conflict
from .common import digest


class EditingMixin:
    def _process(self, state, job, action, payload):
        if 'plan' in payload:
            from ..source_review_withdrawals import validate_plan
            validate_plan(self.settings, payload['plan'], payload.get('changes', ()))
        folder = self.folder(state["id"]) / job["id"]
        folder.mkdir(exist_ok=True)
        request, result = folder / f"{action}-request.json", folder / f"{action}-result.json"
        _atomic_json(request, {"action": action, "output_dir": str(folder), **payload})
        with self.render_lock:
            with (folder / f"{action}.log").open("a", encoding="utf-8") as log:
                proc = subprocess.Popen([str(self.settings.auto_capcut_python), "-X", "utf8", "-m", "auto_capcut.studio_runner",
                                   "--request", str(request), "--result", str(result)],
                                  cwd=self.settings.auto_capcut_root, stdout=log, stderr=log,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                # The runner owns an OS lock and a result receipt. A server restart can
                # reconnect without executing the same render concurrently or twice.
                job["checkpoint"][action + "_pid"] = proc.pid
                self.store.checkpoint(job["id"], job["checkpoint"])
                try:
                    proc.wait(timeout=self.settings.auto_capcut_timeout)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("편집 시간이 길어지고 있습니다. 재시도하면 기존 실행 결과를 이어받습니다.")
        if not result.is_file(): raise RuntimeError("편집 실행기가 결과를 반환하지 않았습니다. 작업 로그를 확인하세요.")
        data = json.loads(result.read_text(encoding="utf-8"))
        if data.get("status") != "completed": raise RuntimeError(data.get("error", "편집 실행 실패"))
        return data

    def _edit(self, state, job):
        from ..studio_ai import describe_shots, restrict_context_shots
        p = job["payload"]
        voice = next(v for v in state["voices"] if v["id"] == p["voice_id"])
        script = next(s for s in state["scripts"] if s["id"] == p["script_id"])
        if digest(voice["path"]) != voice["sha256"]: raise Conflict("승인한 음성이 변경되었습니다.")
        records = [s for s in state['sources'] if p.get('source_ids') is None or s['id'] in p['source_ids']]
        if not records: raise ValueError('사용 가능한 소스가 없습니다.')
        sources = self._source_records([s["path"] for s in records], state.get("manifest_path", ''), records)
        from ..source_review_withdrawals import apply_withdrawals
        from ..source_quality import editing_ready
        sources = [apply_withdrawals(self.settings, source) for source in sources]
        sources = [source for source in sources if not source.get('source_interval_withdrawal') or editing_ready(source)]
        if not sources:
            raise ValueError('출력 검토 후 사용할 수 있는 소스 장면이 없습니다.')
        if state.get('creation_mode') == 'self_shot' and any(s.get('rights') != 'user_supplied' for s in sources):
            raise ValueError('내 촬영 영상 제작에는 직접 업로드한 영상만 사용할 수 있습니다.')
        base = self._process(state, job, "analyze", {"sources": sources, "voice": voice, "script": script})
        plan = base["plan"]
        plan['narration_priority'] = {'policy':'script-first-20261006-v2', 'script_id':script['id'],
                                    'script_sha256':hashlib.sha256(script['text'].encode()).hexdigest(),
                                    'footage_role':'adapt_to_selected_narration'}
        restrict_context_shots(plan, sources)
        if state.get('reviewed_scene_rules'):
            from ..studio_reviewed_scenes import apply_reviewed_scenes
            plan=apply_reviewed_scenes(plan,state['reviewed_scene_rules'])
            result=self.render_feedback(state,job,plan)
            return {"id":job["id"],"script_id":script["id"],"voice_id":voice["id"],"created":time.time(),**result}
        semantic = self.folder(state["id"]) / job["id"] / "semantic-plan.json"
        if semantic.is_file():
            plan = json.loads(semantic.read_text(encoding="utf-8"))
            restrict_context_shots(plan, sources)
            result = self.render_feedback(state, job, plan)
            return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}
        try:
            observations, choices = describe_shots(self.settings, plan["shots"], plan["beats"])
            for shot in plan["shots"]:
                observation = observations.get(shot["id"], {})
                if observation.get("observation"):
                    shot["observation"] = str(observation["observation"])[:1200]
                    shot["tags"] = [str(t)[:100] for t in observation.get("tags", [])[:15]]
                for field in ('visual_type', 'selection_exclusion', 'evidence_status'):
                    if field in observation:
                        shot[field] = observation[field]
            for beat in plan["beats"]:
                choice = choices.get(beat["id"], {})
                if choice.get("options"): beat["options"] = choice["options"][:3]
                if type(choice.get("emphasis")) is int and choice["emphasis"] in (0, 1, 2):
                    beat["emphasis"] = choice["emphasis"]
                    beat["emphasis_reason"] = choice["emphasis_reason"]
            plan["semantic_provider"] = "codex_internal"
        except Exception as exc:
            plan["warnings"].append("장면 의미 분석을 완료하지 못해 대체 후보를 사용했습니다: " + str(exc)[:200])
        restrict_context_shots(plan, sources)
        _atomic_json(semantic, plan)
        result = self.render_feedback(state, job, plan)
        return {"id": job["id"], "script_id": script["id"], "voice_id": voice["id"], "created": time.time(), **result}

    def _revision(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        action = 'caption-export' if job['payload'].get('caption_only') else 'revise'
        result = self._process(state, job, action, {"plan": plan, "changes": job["payload"]["changes"]})
        return {"id": job["id"], "script_id": edit["script_id"], "voice_id": edit["voice_id"],
                "parent_id": edit["id"], "created": time.time(), **result}

    def _edit_request(self, state, job):
        from ..studio_ai import plan_revision
        p = job["payload"]
        edit = next(e for e in state["edits"] if e["id"] == p["edit_id"])
        plan = json.loads(Path(edit["plan_path"]).read_text(encoding="utf-8"))
        start, end = float(p["start"]), float(p["end"] or plan["duration"])
        if not 0 <= start < end <= plan["duration"] + .1: raise ValueError("수정할 구간을 확인하세요.")
        result = job["checkpoint"].get("interpretation")
        if result is None:
            result = plan_revision(self.settings, plan, p["request"], start, end)
            job["checkpoint"]["interpretation"] = result
            self.store.checkpoint(job["id"], job["checkpoint"])
        job["payload"]["changes"] = [{"beat_id": c["beat_id"], "emphasis": c["emphasis"]} for c in result["changes"] if "emphasis" in c]
        candidates = [c["beat_id"] for c in result["changes"] if c.get("choose_candidates")]
        if job["payload"]["changes"]:
            output = self._revision(state, job)
        else:
            output = {"no_render": True}
        return {**output, "candidate_requests": candidates, "request_summary": result["summary"]}

    def _register(self, state, job):
        edit = next(e for e in state["edits"] if e["id"] == job["payload"]["edit_id"])
        return self._process(state, job, "register", {"plan_path": edit["plan_path"], "edit_id": edit["id"], "launch": job['payload'].get('launch', True)})
