import json
from pathlib import Path

import pytest

from hotpost.analyze import score_account
from hotpost.config import Settings
from hotpost.criteria import defaults
from hotpost.models import Post
from hotpost.legacy_production import ProductionManager


class Queue:
    def __init__(self):
        self.starts = 0
    def register(self, *args):
        pass
    def start(self, *args):
        self.starts += 1
        return {"id": "job"}
    def get(self, *args):
        return {"status": "queued"}


def test_repeated_discovery_deduplicates_and_done_requires_file(tmp_path):
    queue = Queue()
    manager = ProductionManager(Settings(data_dir=tmp_path), queue)
    manager.start("code")
    manager.start("code")
    assert queue.starts == 1
    state = manager.read("code")
    state["variants"] = [{"version": 1, "status": "done", "video_path": str(tmp_path / "missing.mp4")}]
    manager.save(state)
    assert manager.public(state)["variants"][0]["download_url"] is None
    assert manager.public(state)["variants"][0]["status"] == "missing"
    assert manager.public(state)["status"] == "error"
    assert manager.artifact("code", "video1") is None
    with pytest.raises(ValueError):
        manager.read("../escape")


def test_report_watcher_picks_up_new_hot_video_without_duplicate_jobs(tmp_path, monkeypatch):
    from hotpost import legacy_production as production
    settings = Settings(data_dir=tmp_path, production_enabled=True)
    queue = Queue()
    manager = ProductionManager(settings, queue)
    first = [{'shortcode':'first', 'kind':'reel', 'tier':1},
             {'shortcode':'cold', 'kind':'video', 'tier':0},
             {'shortcode':'photo', 'kind':'photo', 'tier':2}]
    settings.report_path.write_text(json.dumps({'posts':first}))
    class Polls:
        ticks = 0
        def is_set(self):
            return self.ticks == 3
        def wait(self, _seconds):
            self.ticks += 1
            report = {'posts':first + [{'shortcode':'new', 'kind':'video', 'tier':2}]}
            if self.ticks == 2:
                report = {'is_sample':True, 'posts':[{'shortcode':'sample', 'kind':'reel', 'tier':3}]}
            settings.report_path.write_text(json.dumps(report))
    manager.stop = Polls()
    class InlineThread:
        def __init__(self, target, **_):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(production.threading, 'Thread', InlineThread)
    manager.watch()
    assert queue.starts == 2
    assert {p.parent.name for p in manager.root.glob('*/state.json')} == {'first', 'new'}


def test_failed_stage_does_not_stay_running_on_card(tmp_path):
    manager = ProductionManager(Settings(data_dir=tmp_path), Queue())
    state = manager.read('code')
    state.update(status='error', stages={'source': {'status': 'running'}})
    assert manager.public(state)['source']['status'] == 'error'
    state.update(status='done', stages={'source': {'status': 'done', 'zip_path': str(tmp_path/'missing.zip')}})
    assert manager.public(state)['source']['status'] == 'missing'
    assert manager.public(state)['source']['download_url'] is None


def test_retry_shows_waiting_instead_of_previous_active_stage(tmp_path):
    manager = ProductionManager(Settings(data_dir=tmp_path), Queue())
    state = manager.read('code')
    state.update(status='error', message='old failure', progress=91,
                 stages={'source': {'status': 'running'}},
                 variants=[{'version': 1, 'status': 'exporting'}])
    manager.save(state)
    result = manager.start('code', retry=True)
    assert result['status'] == 'queued'
    assert result['message'] == '자동 제작 대기'
    assert result['source']['status'] == 'queued'
    assert result['variants'][0]['status'] == 'queued'


def test_changed_editing_sources_invalidate_old_draft(tmp_path):
    manager = ProductionManager(Settings(data_dir=tmp_path), Queue())
    request = manager.settings.editing_dir / 'code-run-v1' / 'request.json'
    request.parent.mkdir(parents=True)
    a, b = tmp_path/'product.mp4', tmp_path/'intro.mp4'
    request.write_text(json.dumps({'video_paths':[str(a),str(b)]}))
    assert manager._same_source_inputs('code','run',1,[a,b])
    assert not manager._same_source_inputs('code','run',1,[a])


def test_missing_video_views_use_video_weights_and_gates_reject_missing():
    settings = Settings()
    now = 10000000
    peers = [Post(f"p{i}", "user", now-(i+5)*86400, "reel", 100, 10, 1000) for i in range(9)]
    target = Post("target", "user", now-3*86400, "reel", 1000, 10, None)
    criteria = {**defaults(settings), "maturity": False, "wvViews": 0, "wvLikes": 100, "wvComments": 0,
                "wiLikes": 0, "wiComments": 100}
    result = score_account([target,*peers], settings, now=now, criteria=criteria)[0]
    assert result.multiplier > 9
    criteria.update(wvViews=100, wvLikes=0)
    result = score_account([target,*peers], settings, now=now, criteria=criteria)[0]
    assert result.tier == 0  # configured metric absent: cannot declare a viral post
    criteria.update(wvLikes=100, minRatioViews=.5)
    assert score_account([target,*peers], settings, now=now, criteria=criteria)[0].tier == 0


def test_minimum_tier_one_still_requires_peers_and_engagement():
    settings = Settings()
    criteria = {**defaults(settings), "t1": 1, "minEng": 1000}
    posts = [Post("a", "u", 100000, "reel", 0, 0, 0), Post("b", "u", 100, "reel", 0, 0, 0)]
    assert all(item.tier == 0 for item in score_account(posts, settings, now=110000, criteria=criteria))


@pytest.mark.parametrize("field,value", [
    ("minViews", 100001), ("minLikes", 10001), ("minComments", 1001),
    ("minRatioViews", 100), ("minRatioLikes", 100), ("minRatioComments", 100),
    ("followersMin", 10001), ("followersMax", 9999), ("minEng", 1000000),
])
def test_each_criteria_gate_controls_real_tier(field, value):
    now=10000000; settings=Settings()
    peers=[Post(f"p{i}","u",now-(i+5)*86400,"reel",100,10,1000) for i in range(9)]
    target=Post("target","u",now-3*86400,"reel",1000,100,10000)
    assert score_account([target,*peers],settings,now=now,followers=10000)[0].tier > 0
    values={**defaults(settings),field:value}
    assert score_account([target,*peers],settings,now=now,criteria=values,followers=10000)[0].tier==0


def test_script_validation_rejects_invented_personal_testimony():
    from hotpost.script_rewriter import validate_variants
    text="매일 바쁘시죠?\n가방을 직접 써보니 정말 가볍더라고요.\n출근길마다 이것저것 챙기느라 바쁘실 때 짐을 담아 보세요.\n댓글 남겨주세요?"
    with pytest.raises(ValueError,match="경험"):
        validate_variants({"variants":[{"text":text},{"text":text}]},"원본")


def test_recipe_research_does_not_treat_comparison_brand_as_manufacturer():
    from hotpost.script_rewriter import research_subject
    assert research_subject({'caption':'허니콤보 좋아하시면 집에서 만들어보세요. 닭다리살에 전분을 입혀 구우면 돼요.'}) == 'recipe'
    assert research_subject({'caption':'아디다스 나일론 백팩, 넉넉한 수납공간'}) == 'product'


def test_recipe_rewrite_rejects_unverified_texture_guarantee():
    from hotpost.script_rewriter import validate_variants
    text = ('치킨 집에서 만드는 법 아세요?\n이 조합만 알면 바삭한 닭구이가 완성되거든요.\n'
            '닭다리살에 전분을 얇게 입혀 구우면 육즙은 갇히고 겉은 바삭해지죠.\n'
            '달콤한 마늘간장 소스를 입혀도 눅눅해지지 않네요.\n댓글 남겨주세요?')
    with pytest.raises(ValueError, match='보장'):
        validate_variants({'variants':[{'text':text},{'text':text}]}, 'source')


def test_high_review_score_with_unresolved_issues_cannot_publish_script(tmp_path, monkeypatch):
    from hotpost import script_rewriter as writer
    settings = Settings(data_dir=tmp_path, auto_capcut_root=tmp_path)
    (tmp_path/'SCRIPT_ENGINE_SPEC.md').write_text('Spoken factual narration only.')
    transcript = tmp_path/'transcript.json'; transcript.write_text('{"speech":[{"text":"source"}]}')
    manifest = tmp_path/'manifest.json'; manifest.write_text('{}')
    monkeypatch.setattr(writer, 'validate_variants', lambda *_: [{'version':1,'text':'one'}, {'version':2,'text':'two'}])
    def generate(_s, _instruction, data, **kwargs):
        if kwargs.get('research'):
            return {'text':'evidence'}
        if 'variants' in data:
            return {'passed':True, 'score':99, 'issues':['Unsupported popularity assertion']}
        return {'variants':[]}
    monkeypatch.setattr(writer, '_generate', generate)
    with pytest.raises(RuntimeError, match='검토를 통과'):
        writer.rewrite(settings, transcript, manifest, tmp_path/'out', lambda *_:None)
    assert not (tmp_path/'out/scripts.json').exists()
    assert not (tmp_path/'out/words-v1.txt').exists()


def test_pipeline_reuses_assets_and_produces_two_distinct_handoffs(tmp_path, monkeypatch):
    from hotpost import editing_adapter, script_rewriter, voicebench_adapter
    settings = Settings(data_dir=tmp_path)
    source = settings.source_dir / "code-1"
    source.mkdir(parents=True)
    (source / "video.mp4").write_bytes(b"source")
    (source / "different-product.mp4").write_bytes(b"related source excluded from editing")
    (source / "sources_code.zip").write_bytes(b"zip")
    (source / "manifest.json").write_text(json.dumps({"shortcode":"code", "candidates":[
        {"selected_for_zip":True,"source_quality":"light-overlay","downloaded_file":"video.mp4"},
        {"selected_for_zip":True,"source_quality":"light-overlay","downloaded_file":"different-product.mp4","editing_eligible":False}]}))
    transcript = settings.transcript_dir / "code-1"
    transcript.mkdir(parents=True)
    (transcript / "transcript.json").write_text(json.dumps({"speech":[{"text":"원본 대사"}]}))
    (transcript / "transcript.txt").write_text("원본 대사", encoding="utf-8")
    manager = ProductionManager(settings, Queue())
    manager.start("code")
    def rewrite(s, t, m, out, progress):
        out.mkdir(parents=True)
        variants=[]
        for version in (1,2):
            p=out/f"v{version}.txt"; p.write_text(f"서로 다른 대본 {version}", encoding="utf-8")
            variants.append({"version":version,"text":p.read_text(encoding="utf-8"),"script_path":str(p)})
        return {"variants":variants}
    monkeypatch.setattr(script_rewriter,"rewrite",rewrite)
    voices=[]
    def synth(self,text,path,progress):
        voices.append(text); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b"RIFFvoice")
    monkeypatch.setattr(voicebench_adapter.VoiceBenchAdapter,"synthesize",synth)
    builds=[]
    def build(self,**kwargs):
        assert kwargs['video_paths'] == [source/'video.mp4']
        builds.append(kwargs); draft=tmp_path/(kwargs["draft_name"] + '_v2'); draft.mkdir()
        return {"status":"completed","draft_path":str(draft),"draft_name":draft.name}
    def export(self,**kwargs):
        assert len(builds)==2  # never launch CapCut between draft registrations
        assert kwargs['draft_name'] == kwargs['draft_path'].name
        assert kwargs['draft_name'].endswith('_v2')
        path=tmp_path/f"{kwargs['job_id']}.mp4"; path.write_bytes(b"actual-export")
        return {"video_path":str(path)}
    monkeypatch.setattr(editing_adapter.AutoCapcutAdapter,"build",build)
    monkeypatch.setattr(editing_adapter.AutoCapcutAdapter,"export",export)
    manager._work("code",lambda *_:None)
    public=manager.public(manager.read("code"))
    assert public["status"]=="done" and public["source"]["count"]==2
    assert public["transcript"]["download_url"]
    assert len(set(voices))==2
    assert len({b['draft_name'] for b in builds})==2
    assert all(v["download_url"] for v in public["variants"])
