import json
import os
import time

from hotpost.config import Settings
from hotpost.studio import Studio
from hotpost.source_finder import _transcript_evidence


def old_reference(settings):
    root=settings.transcript_dir/'target-old'
    root.mkdir(parents=True)
    text=root/'transcript.json'
    text.write_text(json.dumps({'speech':[{'text':'이전 발화'}]}),encoding='utf-8')
    reference=root/'reference.mp4';reference.write_bytes(b'old reference')
    os.utime(text,(1,1));os.utime(reference,(1,1))
    (settings.data_dir/'collection_reset.json').write_text(json.dumps({
        'shortcodes':['target'],'cache_after':time.time()}),encoding='utf-8')
    return reference


def test_source_queries_do_not_use_previous_transcript_after_reset(tmp_path):
    settings=Settings(data_dir=tmp_path)
    old_reference(settings)
    assert _transcript_evidence(settings,'target')=={'speech':'','screen_text':''}


def test_prepare_extracts_a_new_reference_instead_of_reconnecting_old_transcript(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path)
    old=old_reference(settings)
    studio=Studio(settings,workers=False)
    state,_=studio.store.create('target','새 시작',{'active':True,'protocol':2,'stage':'prepare'})
    job=studio.store.claim('production')
    calls=[]
    def extract(settings, code, progress):
        calls.append(code)
        root=settings.transcript_dir/'target-new';root.mkdir()
        (root/'reference.mp4').write_bytes(b'new reference')
        text=root/'transcript.json'
        text.write_text(json.dumps({'speech':[{'text':'새로 전사한 발화'}]}),encoding='utf-8')
        return {'json_path':str(text)}
    monkeypatch.setattr('hotpost.transcript.extract_transcript',extract)
    result=studio._prepare(state,job)
    assert calls==['target']
    assert result['original_text']=='새로 전사한 발화'
    assert result['reference_video']!=str(old)
