from hotpost.config import Settings
from hotpost.studio_adapter import StudioAdapter


def fixture(tmp_path,monkeypatch):
    api=StudioAdapter(Settings(data_dir=tmp_path))
    monkeypatch.setattr(api.jobs,'start',lambda:None)
    monkeypatch.setattr(api,'writing_contract',lambda:{'sha256':'before'})
    return api


def test_video_and_contract_are_bound_to_job_identity(tmp_path,monkeypatch):
    api=fixture(tmp_path,monkeypatch);video=tmp_path/'ref.mp4';video.write_bytes(b'first')
    def submit():return api.submit('task',video,'original',{})
    first=submit();assert submit()['id']==first['id']
    video.write_bytes(b'changed');second=submit();assert first['id']!=second['id']
    monkeypatch.setattr(api,'writing_contract',lambda:{'sha256':'after'})
    third=submit();assert second['id']!=third['id']
    assert second['payload']['reference_video_sha256']==third['payload']['reference_video_sha256']


def test_editorial_identity_changes_when_writing_rules_change(tmp_path,monkeypatch):
    api=fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(api,'_wait',lambda job:calls.append(job) or {'result':{'value':{}}})
    api.editorial('Review',{'purpose':'script_review'})
    api.editorial('Review',{'purpose':'script_review'})
    monkeypatch.setattr(api,'writing_contract',lambda:{'sha256':'after'})
    api.editorial('Review',{'purpose':'script_review'})
    assert calls[0]['id']==calls[1]['id']!=calls[2]['id']


def test_caption_and_kind_are_preserved_and_bound(tmp_path,monkeypatch):
    api=fixture(tmp_path,monkeypatch);video=tmp_path/'ref.mp4';video.write_bytes(b'video')
    def submit(caption):return api.submit('task',video,'original',{'reference_caption':caption,'reference_kind':'screen_text'})
    first=submit('first');second=submit('second')
    assert first['id']!=second['id']
    assert second['payload']['reference_caption']=='second'
    assert second['payload']['reference_kind']=='screen_text'
