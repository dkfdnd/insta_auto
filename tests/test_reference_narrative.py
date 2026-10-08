import copy
import json
from pathlib import Path

import pytest
from PIL import Image
from hotpost import reference_narrative as module
from hotpost.source_quality import sha256_file


@pytest.fixture
def actual(tmp_path,monkeypatch):
    video=tmp_path/'reference.mp4';video.write_bytes(b'actual identity fixture')
    frame=tmp_path/'frame.png';Image.new('RGB',(1080,1920),'white').save(frame)
    transcript=tmp_path/'transcript.json'
    transcript.write_text(json.dumps({'speech':[{'text':'딸기 딸고 딸기 딴다'}],
        'screen_text':[{'text':'bad OCR must not be promoted'}]},ensure_ascii=False),'utf-8')
    evidence={'source_sha256':sha256_file(video),'frames':[{'frame_id':'f1','path':str(frame),
        'sha256':sha256_file(frame),'interval_index':0,'source_timestamp':0.}],
        'intervals':[{'index':0,'source_start':0.,'source_end':2.}]}
    monkeypatch.setattr(module,'sample_source_frames',lambda *a,**k:copy.deepcopy(evidence))
    monkeypatch.setattr(module,'_duration',lambda *a:2.)
    return transcript


def visual(*,accepted=True,related=False):
    calls=[]
    def generate(settings,instruction,data,*,media):
        calls.append(data)
        assert media[1]['inlineData']['mimeType']=='image/jpeg'
        if len(calls)==1:return {'frames':[{'frame_id':'f1','text':'밤 까기 이렇게 쉬워요?'}],
                                   'use_speech_in_benchmark':related}
        return {'accepted':accepted,'frame_ids':['f1'],'speech_related':related,
                'proposal_sha256':data['proposal_sha256'],'reason':'independent actual frame inspection'}
    return generate,calls


def test_background_lyrics_and_bad_ocr_do_not_replace_visually_read_topic(actual):
    before=actual.read_bytes();generate,calls=visual()
    result=module.reference_text(None,actual,generate=generate)
    assert result['text']=='밤 까기 이렇게 쉬워요?' and result['kind']=='screen_text'
    assert result['speech_text']=='딸기 딸고 딸기 딴다'
    assert len(calls)==2 and actual.read_bytes()==before
    assert 'bad OCR' not in json.dumps(calls,ensure_ascii=False)
    cached=module.reference_text(None,actual,generate=lambda *a,**k:pytest.fail('unnecessary repeat'))
    assert cached==result


def test_relevant_short_speech_hook_is_preserved_as_a_separate_kind(actual):
    actual.write_text(json.dumps({'speech':[{'text':'밤 까기 귀찮죠?'}],
        'screen_text':[{'text':'screen'}]},ensure_ascii=False),'utf-8')
    generate,_=visual(related=True);result=module.reference_text(None,actual,generate=generate)
    assert result['kind']=='mixed' and result['text'].startswith('밤 까기 귀찮죠?\n')


def test_short_genuine_speech_without_screen_text_has_no_character_count_gate(actual):
    actual.write_text(json.dumps({'speech':[{'text':'이 텐트 편하죠?'}]}),'utf-8')
    result=module.reference_text(None,actual,generate=lambda *a,**k:pytest.fail('no visual review needed'))
    assert result['kind']=='speech' and result['text']=='이 텐트 편하죠?'


def test_failed_independent_visual_review_is_not_published_as_speech(actual):
    generate,_=visual(accepted=False)
    with pytest.raises(ValueError,match='문구 검토'):module.reference_text(None,actual,generate=generate)
    assert not (actual.parent/'reference-text-verified.json').exists()


def test_cache_cannot_reuse_changed_text_or_changed_frames(actual):
    generate,_=visual();module.reference_text(None,actual,generate=generate)
    saved=actual.parent/'reference-text-verified.json';cache=json.loads(saved.read_text('utf-8'))
    altered={**cache,'text':'invented function'}
    assert not module.validated_cached_text(altered,cache['video_sha256'],cache['speech_text'])
    Image.new('RGB',(1080,1920),'red').save(actual.parent/'frame.png')
    with pytest.raises(ValueError,match='증거가 변경'):module.reference_text(None,actual,generate=generate)


def test_source_search_uses_verified_screen_topic_and_excludes_unrelated_lyrics(actual):
    from hotpost.config import Settings
    from hotpost.source_finder import _transcript_evidence
    generate,_=visual()
    module.reference_text(None,actual,generate=generate)
    folder=actual.parent/'transcripts'/'target-1'
    folder.parent.mkdir()
    # Preserve the original frame evidence paths and source files in the fixture.
    folder.mkdir()
    for name in ('transcript.json','reference.mp4','reference-text-verified.json'):
        (folder/name).write_bytes((actual.parent/name).read_bytes())
    settings=Settings(data_dir=actual.parent)
    evidence=_transcript_evidence(settings,'target')
    assert evidence=={'speech':'','screen_text':'밤 까기 이렇게 쉬워요?','reference_kind':'screen_text'}
    assert '딸기' not in str(evidence) and 'bad OCR' not in str(evidence)


def test_cache_cannot_relabel_unrelated_speech_as_mixed(actual):
    generate,_=visual();result=module.reference_text(None,actual,generate=generate)
    changed={**result,'kind':'mixed','text':result['speech_text']+'\n'+result['text']}
    assert not module.validated_cached_text(changed,result['video_sha256'],result['speech_text'])
