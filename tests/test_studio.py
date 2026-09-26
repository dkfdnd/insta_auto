import copy
import hashlib
import json
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.studio_store import Conflict, StudioStore


@pytest.fixture
def studio(tmp_path):
    return Studio(Settings(data_dir=tmp_path), workers=False)


def prepared(studio):
    state, _ = studio.store.create("fixture", "승인 경계 검증")
    studio.store.change(state["id"], lambda s, db: studio._script(s, "같은 제품을 새로운 이야기로 소개해요.\n댓글 남겨주세요?", "recommended"))
    return studio.store.get(state["id"])


def test_create_is_idempotent_and_prepare_only(studio):
    first, created = studio.store.create("one", "첫 작업")
    second, again = studio.store.create("one", "다시 클릭")
    assert created and not again and first["id"] == second["id"]
    assert [j["kind"] for j in studio.store.jobs(first["id"])] == ["prepare"]


def test_approval_gates_and_duplicate_click(studio):
    state=prepared(studio)
    with pytest.raises(Conflict):
        studio.action(state["id"], "approve-voice", {"voice_id":"missing"})
    first=studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    second=studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    assert first["approved_script_id"]==state["script_id"]
    assert len([j for j in second["jobs"] if j["kind"]=="voice"])==1
    assert not any(j["kind"]=="edit" for j in second["jobs"])


def test_user_edit_invalidates_downstream_and_keeps_history(studio):
    state=prepared(studio)
    old=state["script_id"]
    studio.action(state["id"],"approve-script",{"script_id":old})
    updated=studio.action(state["id"],"save-script",{"text":"직접 수정한 새로운 대본이에요."})
    assert updated["script_id"]!=old
    assert updated["approved_script_id"] is None and updated["approved_voice_id"] is None
    assert len(updated["scripts"])==2
    assert any(s["id"]==old for s in updated["scripts"])


def test_late_voice_success_is_history_not_current(studio):
    state=prepared(studio)
    approved=studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    voiceid=approved["pending_voice_id"]
    studio.action(state["id"],"save-script",{"text":"새로 작성한 대본이에요."})
    job={"kind":"voice","payload":{"script_id":state["script_id"],"voice_id":voiceid}}
    result={"id":voiceid,"script_id":state["script_id"]}
    studio.store.change(state["id"],lambda s, db: studio._accept(s,job,result))
    final=studio.store.get(state["id"])
    assert final["voice_id"] is None and len(final["voices"])==1
    assert final["status"]=="script_review"


def test_stale_proposal_does_not_replace_manual_text(studio):
    state=prepared(studio)
    studio.store.change(state["id"],lambda s,db:s["proposals"].append({"id":"p","script_id":state["script_id"],"text":"AI 제안"}))
    studio.action(state["id"],"save-script",{"text":"내가 직접 쓴 문장"})
    with pytest.raises(Conflict): studio.action(state["id"],"apply-proposal",{"proposal_id":"p"})
    assert studio.store.get(state["id"])["scripts"][-1]["text"]=="내가 직접 쓴 문장"


def test_optimistic_save_conflict(studio):
    state=prepared(studio)
    studio.action(state["id"],"save-script",{"text":"다른 창에서 바꾼 내용"})
    with pytest.raises(Conflict): studio.action(state["id"],"save-script",{"text":"오래된 화면", "revision":state["revision"]})


def test_reopen_restores_approvals_and_request_checkpoint(studio):
    state=prepared(studio)
    studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    job=studio.store.claim()
    studio.store.checkpoint(job["id"],{"request_id":718})
    reopened=StudioStore(studio.store.root)
    reopened.recover()
    recovered=reopened.claim()
    assert recovered["id"]==job["id"] and recovered["checkpoint"]["request_id"]==718
    assert reopened.get(state["id"])["approved_script_id"]==state["script_id"]


def test_late_failure_does_not_mark_new_script_failed(studio):
    state=prepared(studio)
    old=studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    studio.store.claim() # prepare
    voice=studio.store.claim()
    studio.action(state["id"],"save-script",{"text":"다음 버전으로 수정했어요."})
    studio.store.fail(voice,"old failure")
    new=studio.store.get(state["id"])
    assert new["status"]=="script_review" and not new["error"]


def test_voice_approval_verifies_hash_and_enqueues_edit(studio):
    state=prepared(studio)
    studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    voice=studio.folder(state["id"])/"voice.wav";voice.write_bytes(b"immutable audio")
    record={"id":"voice-1","script_id":state["script_id"],"path":str(voice),"sha256":hashlib.sha256(voice.read_bytes()).hexdigest()}
    studio.store.change(state["id"],lambda s,db:(s["voices"].append(record),s.update(voice_id="voice-1",pending_voice_id="voice-1",status="voice_review")))
    result=studio.action(state["id"],"approve-voice",{"voice_id":"voice-1"})
    assert result["approved_voice_id"]=="voice-1" and sum(j["kind"]=="edit" for j in result["jobs"])==1
    studio.action(state["id"],"approve-voice",{"voice_id":"voice-1"})
    assert sum(j["kind"]=="edit" for j in studio.store.jobs(state["id"]))==1


def test_media_traversal_and_other_tasks_are_rejected(studio,tmp_path):
    state=prepared(studio)
    private=tmp_path/"private.wav";private.write_bytes(b"private")
    with pytest.raises(ValueError):studio.media(state["id"],"private.wav")
    outside=tmp_path.parent/"outside.wav";outside.write_bytes(b"outside")
    with pytest.raises(ValueError):studio.media(state["id"],"../outside.wav")


def test_approval_wait_does_not_occupy_a_worker(studio):
    one=prepared(studio)
    two,_=studio.store.create("second","다음 작업")
    first=studio.store.claim()
    studio.store.finish(first,{},lambda *_:None)
    nextjob=studio.store.claim()
    assert nextjob["task_id"]==two["id"]
    assert studio.store.get(one["id"])["status"]=="script_review"


def test_regeneration_blocks_old_approval_and_duplicate_jobs(studio):
    state=prepared(studio)
    studio.action(state["id"],"approve-script",{"script_id":state["script_id"]})
    studio.store.change(state["id"],lambda s,db:s.update(status="voice_review",voice_id="old"))
    first=studio.action(state["id"],"regenerate-voice",{"script_id":state["script_id"]})
    second=studio.action(state["id"],"regenerate-voice",{"script_id":state["script_id"]})
    assert first["voice_id"] is None
    assert second["pending_voice_id"]==first["pending_voice_id"]
    assert sum(j["kind"]=="voice" for j in second["jobs"])==2
    with pytest.raises(Conflict):studio.action(state["id"],"approve-voice",{"voice_id":"old"})


def test_http_media_ranges_and_cross_origin_mutation(studio):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from hotpost.studio_http import StudioHTTP
    state=prepared(studio)
    media=studio.folder(state["id"])/"range.wav";media.write_bytes(bytes(range(200)))
    class Handler(StudioHTTP,BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def _json(self,data,status=200):
            self.send_response(status);self.end_headers();self.wfile.write(json.dumps(data).encode())
        def do_GET(self):self.studio_get(studio)
        def do_POST(self):self.studio_post(studio)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f"http://127.0.0.1:{server.server_port}"
    try:
        req=Request(base+studio.media_url(state["id"],media),headers={"Range":"bytes=17-41"})
        with urlopen(req) as response:
            assert response.status==206 and response.read()==bytes(range(17,42))
            assert response.headers["Content-Range"]=="bytes 17-41/200"
        req=Request(base+f'/api/studio/{state["id"]}/save-script',data=b'{}',headers={"Origin":"https://unrelated.example"})
        with pytest.raises(HTTPError) as error:urlopen(req)
        assert error.value.code==403
    finally:server.shutdown();server.server_close()
