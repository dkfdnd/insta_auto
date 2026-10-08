"""Automatic review cannot waive identity, coverage, or editable-time evidence."""
import copy
import base64
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from hotpost import source_overlay_review as module
from hotpost.source_mask_review import GEOMETRY
from hotpost.source_quality import editing_ready, sha256_file


@pytest.fixture
def setup_review(tmp_path, monkeypatch):
    source_path = tmp_path/'source.mp4'; source_path.write_bytes(b'identity fixture')
    frame = tmp_path/'frame.png'; Image.new('RGB',(1080,1920),'gray').save(frame)
    evidence = {'version':1,'source_path':str(source_path),'source_sha256':sha256_file(source_path),
        'source_duration':10.,'geometry':dict(GEOMETRY),
        'intervals':[{'index':0,'source_start':2.,'source_end':4.}],
        'frames':[{'frame_id':'actual-frame','path':str(frame),'sha256':sha256_file(frame),
            'source_timestamp':3.,'requested_timestamp':3.,'interval_index':0}]}
    source={'id':'preserved-id','path':str(source_path),'sha256':sha256_file(source_path),
            'source_quality':'unknown','blur_required':True,
            'functional_review':{'reviewed':True,'same_core_function':True}}
    monkeypatch.setattr(module,'sample_source_frames',lambda *a,**k:copy.deepcopy(evidence))
    monkeypatch.setattr(module,'_duration',lambda *a:10.)
    return source,tmp_path/'output'


def visual_calls(*, regions=True, accepted=True):
    calls=[]
    def generate(settings,instruction,data,*,media):
        calls.append((instruction,data,media))
        assert media[1]['inlineData']['mimeType']=='image/jpeg'
        if len(calls)==1:
            return {'frames':[{'frame_id':'actual-frame','boxes':[
                {'left':100,'top':1500,'width':400,'height':100,'text':'caption'}] if regions else []}]}
        p=data['proposal']
        return {'reviewer':'independent fixture visual review','proposal_sha256':p['proposal_sha256'],
            'source_sha256':p['evidence']['source_sha256'],'geometry':dict(GEOMETRY),
            'intervals':[{'source_start':2.,'source_end':4.,'mask_indices':[0] if regions else [],
                'frame_ids':['actual-frame'],'coverage_confirmed':accepted,
                'subject_visible':True,'no_overlays_confirmed':not regions}]}
    return generate,calls


def test_auto_review_uses_two_visual_calls_and_only_approved_intervals(setup_review):
    source,output=setup_review;generate,calls=visual_calls()
    result=module.review_source_overlays(None,source,output,generate=generate)
    assert len(calls)==2 and calls[1][2][:len(calls[0][2])]==calls[0][2]
    assert len(calls[1][2])==len(calls[0][2])*2
    assert 'exact_proposed_mask_coverage_opaque_gray' in calls[1][2][-2]['text']
    assert editing_ready(result) and result['blur_required']
    assert result['source_quality']=='light-overlay'
    assert result['reviewed_intervals']==[{'source_start':2.,'source_end':4.}]
    assert result['watermark_masks'][0]['reviewed'] is True
    assert 'functional_review' not in result
    assert source['source_quality']=='unknown' and 'mask_review' not in source


def test_changing_overlay_between_old_endpoint_samples_is_proposed_and_reviewed(tmp_path, monkeypatch):
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('real timestamped video sampling requires ffmpeg and ffprobe')
    video = tmp_path/'changing-caption.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
        'color=c=gray:s=1080x1920:r=30:d=4', '-vf',
        "drawbox=x=100:y=1500:w=300:h=80:color=white:t=fill,"
        "drawbox=x=400:y=1500:w=320:h=80:color=yellow:t=fill:enable='between(t,0.6,1.3)'",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(video)],
        check=True, capture_output=True, timeout=30)
    digest = sha256_file(video)
    old = module.sample_source_frames(video, digest, tmp_path/'old', [[0.,4.]],
        samples_per_interval=3, ffmpeg=ffmpeg, ffprobe=ffprobe)

    def extended(image):
        r,g,b = image.convert('RGB').getpixel((600,1520))
        return r > 200 and g > 200 and b < 40

    assert not any(extended(Image.open(f['path'])) for f in old['frames'])
    from hotpost import source_finder
    monkeypatch.setattr(source_finder, '_executable', lambda name: ffmpeg if name=='ffmpeg' else ffprobe)
    calls=[]
    def generate(settings, instruction, data, *, media):
        calls.append(data)
        if data['purpose']=='overlay_region_proposal':
            rows=[]
            for i, frame in enumerate(data['frames']):
                im=Image.open(io.BytesIO(base64.b64decode(media[i*2+1]['inlineData']['data'])))
                width=620 if extended(im) else 300
                rows.append({'frame_id':frame['frame_id'], 'boxes':[
                    {'left':100,'top':1500,'width':width,'height':80,'text':'changing caption'}]})
            return {'frames':rows}
        p=data['proposal']
        return {'reviewer':'independent changing-overlay fixture',
            'proposal_sha256':p['proposal_sha256'],'source_sha256':digest,'geometry':dict(GEOMETRY),
            'intervals':[{'source_start':0.,'source_end':4.,
                'mask_indices':list(range(len(p['watermark_masks']))),
                'frame_ids':[f['frame_id'] for f in p['evidence']['frames']],
                'coverage_confirmed':True,'subject_visible':True,'no_overlays_confirmed':False}]}
    source={'id':'changing','path':str(video),'sha256':digest,
            'source_quality':'edited-with-text','blur_required':True}
    result=module.review_source_overlays(None,source,tmp_path/'new',generate=generate)
    evidence=json.loads((tmp_path/'new'/'overlay-evidence.json').read_text('utf-8'))
    assert len(evidence['frames'])==5
    assert any(extended(Image.open(f['path'])) for f in evidence['frames'])
    assert len(calls)==2
    assert max(m['rectangle']['width'] for m in result['watermark_masks']) >= 620/1080
    assert result['reviewed_intervals']==[{'source_start':0.,'source_end':4.}]


def test_empty_detections_need_independent_positive_clean_confirmation(setup_review):
    source,output=setup_review;generate,calls=visual_calls(regions=False)
    result=module.review_source_overlays(None,source,output,generate=generate)
    assert result['source_quality']=='clean-source' and not result['blur_required']
    assert result['mask_review']['intervals'][0]['no_overlays_confirmed'] is True
    assert result['reviewed_intervals'][0]['source_end']==4.


def test_independent_rejection_never_creates_ready_result(setup_review):
    source,output=setup_review;generate,calls=visual_calls(accepted=False)
    with pytest.raises(ValueError,match='every region'):
        module.review_source_overlays(None,source,output,generate=generate)
    assert not (output/'overlay-reviewed.json').exists()


def test_missing_frames_cannot_become_clean(setup_review):
    source,output=setup_review
    with pytest.raises(ValueError,match='omitted'):
        module.review_source_overlays(None,source,output,generate=lambda *a,**k:{'frames':[]})


def test_cache_revalidates_source_frames_and_preserves_incoming_identity(setup_review):
    source,output=setup_review;generate,calls=visual_calls()
    module.review_source_overlays(None,source,output,generate=generate)
    changed={**source,'id':'another-stable-id','origin_url':'https://example.com/current'}
    restored=module.review_source_overlays(None,changed,output,
        generate=lambda *a,**k:pytest.fail('unexpected model call'))
    assert restored['id']==changed['id'] and restored['origin_url']==changed['origin_url']
    assert 'functional_review' not in restored
    import json
    cached=json.loads((output/'overlay-reviewed.json').read_text())
    cached['watermark_masks'][0]['rectangle']['height']=1.
    (output/'overlay-reviewed.json').write_text(json.dumps(cached))
    actual=module.review_source_overlays(None,changed,output,
        generate=lambda *a,**k:pytest.fail('unexpected model call'))
    assert actual['watermark_masks'][0]['rectangle']['height']!=1.
    Image.new('RGB',(1080,1920),'red').save(output.parent/'frame.png')
    with pytest.raises(ValueError,match='frame changed'):
        module.review_source_overlays(None,changed,output)


def test_byte_identical_copy_can_revalidate_peer_overlay_evidence_without_core_approval(setup_review):
    import shutil
    source,output=setup_review;generate,calls=visual_calls()
    first=module.review_source_overlays(None,source,output,generate=generate)
    copy_path=output.parent/'copied-source.mp4'
    copy_path.write_bytes(Path(source['path']).read_bytes())
    peer=output.parent/'another-task-cache';peer.mkdir()
    for name in ('overlay-proposal.json','overlay-receipt.json','overlay-reviewed.json'):
        shutil.copyfile(output/name,peer/name)
    incoming={**source,'id':'new-task-source','path':str(copy_path),
              'origin_url':'https://example.com/new-source','rights':'unknown-check-before-reuse'}
    result=module.review_source_overlays(None,incoming,peer,
        generate=lambda *a,**k:pytest.fail('Byte-identical evidence must be revalidated without another visual call'))
    assert result['path']==str(copy_path) and result['id']==incoming['id']
    assert result['origin_url']==incoming['origin_url'] and result['rights']==incoming['rights']
    assert result['watermark_masks']==first['watermark_masks']
    assert result['reviewed_intervals']==first['reviewed_intervals']
    assert 'functional_review' not in result
    copy_path.write_bytes(b'different actual video')
    with pytest.raises(ValueError,match='source changed'):
        module.review_source_overlays(None,incoming,peer)


def peer_review_fixture(setup_review):
    import shutil
    from types import SimpleNamespace
    source, original = setup_review
    generate, _ = visual_calls()
    first = module.review_source_overlays(None, source, original, generate=generate)
    data = original.parent/'data'
    peer = data/'studio'/'old-task'/'source-mask-checks'/source['sha256'][:20]
    peer.mkdir(parents=True)
    for name in ('overlay-proposal.json', 'overlay-receipt.json', 'overlay-reviewed.json'):
        shutil.copyfile(original/name, peer/name)
    video = original.parent/'new-copy.mp4'
    video.write_bytes(Path(source['path']).read_bytes())
    incoming = {**source, 'id':'new-id', 'path':str(video),
                'origin_url':'https://example.com/current', 'rights':'current-rights'}
    output = data/'studio'/'new-task'/'source-mask-checks'/source['sha256'][:20]
    return SimpleNamespace(data_dir=data), incoming, output, peer, first


def test_peer_review_is_automatic_and_preserves_current_metadata(setup_review):
    settings, source, output, peer, first = peer_review_fixture(setup_review)
    result = module.review_source_overlays(settings, source, output,
        generate=lambda *a, **k:pytest.fail('Same bytes must use revalidated evidence'))
    for key in ('id', 'path', 'origin_url', 'rights'):
        assert result[key] == source[key]
    assert result['watermark_masks'] == first['watermark_masks']
    assert result['reviewed_intervals'] == first['reviewed_intervals']
    assert result['overlay_review_reused_from'] == str(peer.resolve())
    assert 'functional_review' not in result
    assert (output/'overlay-reviewed.json').is_file()
    # Durable local cache is also valid on the next invocation.
    again = module.review_source_overlays(settings, source, output,
        generate=lambda *a, **k:pytest.fail('Unexpected model call'))
    assert again['mask_review'] == result['mask_review']


@pytest.mark.parametrize('damage', ['policy', 'missing_receipt', 'different_proposal_source',
                                  'changed_frame', 'changed_old_video', 'partial_json'])
def test_stale_or_partial_peer_is_never_reused(setup_review, damage):
    import json
    settings, source, output, peer, _ = peer_review_fixture(setup_review)
    if damage == 'policy':
        path = peer/'overlay-reviewed.json'; value = json.loads(path.read_text())
        value['overlay_review_policy'] = 'old-policy'; path.write_text(json.dumps(value))
    elif damage == 'missing_receipt':
        (peer/'overlay-receipt.json').unlink()
    elif damage == 'different_proposal_source':
        path = peer/'overlay-proposal.json'; value = json.loads(path.read_text())
        value['evidence']['source_sha256'] = '0'*64; path.write_text(json.dumps(value))
    elif damage == 'changed_frame':
        Image.new('RGB', (1080,1920), 'red').save(output.parents[4]/'frame.png')
    elif damage == 'changed_old_video':
        Path(setup_review[0]['path']).write_bytes(b'changed old source')
    else:
        (peer/'overlay-reviewed.json').write_text('{')
    output.mkdir(parents=True)
    assert module._reuse_peer_review(settings, source, output) is None
    assert not (output/'overlay-reviewed.json').exists()


def test_missing_peer_uses_the_two_normal_visual_checks(setup_review):
    settings, source, output, peer, _ = peer_review_fixture(setup_review)
    # An incomplete peer must not suppress new review.
    (peer/'overlay-receipt.json').unlink()
    generate, calls = visual_calls()
    result = module.review_source_overlays(settings, source, output, generate=generate)
    assert len(calls) == 2 and editing_ready(result)
    assert 'overlay_review_reused_from' not in result


def test_window_and_existing_review_contract():
    assert module.review_windows(20)==[[0.,4.],[8.,12.],[16.,20.]]
    assert module.review_windows(3)==[[0.,3.]]
    assert module.needs_overlay_review({'source_quality':'unknown','sha256':'abc'})
    assert module.needs_overlay_review({'source_quality':'light-overlay','blur_required':False})
    assert not module.needs_overlay_review({'source_quality':'clean-source'})
    assert not module.needs_overlay_review({'source_quality':'light-overlay','blur_required':True,
        'sha256':'abc','mask_review':{'source_sha256':'abc'},'watermark_masks':[{'reviewed':True}],
        'reviewed_intervals':[{'source_start':1.,'source_end':2.}]})


def test_coverage_preview_uses_actual_region_edges_and_preserves_evidence(setup_review):
    import json
    source, output = setup_review
    generate, calls = visual_calls()
    module.review_source_overlays(None, source, output, generate=generate)
    original = output.parent/'frame.png'
    with Image.open(original) as frame:
        assert frame.getpixel((100,1500))==(128,128,128)
    with Image.open(output/'coverage-actual-frame.png') as frame:
        # Proposal padding is 12: exact pixel region [88,512) x [1488,1612).
        assert frame.getpixel((88,1488))==(136,136,136)
        assert frame.getpixel((511,1611))==(136,136,136)
        assert frame.getpixel((512,1611))==(128,128,128)
        assert frame.getpixel((511,1612))==(128,128,128)


def test_video_duration_uses_video_stream_not_longer_container_audio_tail(monkeypatch):
    monkeypatch.setattr(module.subprocess,'check_output',lambda *a,**k:
        '{"streams":[{"duration":"20.466667"}],"format":{"duration":"20.478005"}}')
    assert module._duration(Path('fixture.mp4'),'ffprobe')==20.466667
    assert module.review_windows(20.466667)[-1][1]==20.466667


def test_saved_source_review_precedes_search_and_checks_only_editable_frames(tmp_path,monkeypatch):
    import json
    from test_parallel_sources import task,asset,finish
    from hotpost import source_finder,source_functional
    studio,tid,folder=task(tmp_path)
    source=asset(folder,0,quality='unknown',core=True)
    manifest=folder/'manifest.json';manifest.write_text(json.dumps({'candidates':[]}))
    studio.store.change(tid,lambda s,db:s.update(sources=[source],manifest_path=str(manifest)))
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:pytest.fail('unnecessary external search'))
    monkeypatch.setattr(source_finder,'extract_frames',lambda *a,**k:[])
    inside=folder/'inside.png';outside=folder/'outside.png'
    def overlay(*a,**k):
        value=copy.deepcopy(a[1]);value.pop('functional_review')
        value.update(source_quality='clean-source',blur_required=False,
            reviewed_intervals=[{'source_start':2.,'source_end':4.}],
            mask_review={'source_sha256':source['sha256'],'evidence_frames':[
                {'path':str(inside),'source_timestamp':3.},{'path':str(outside),'source_timestamp':8.}]})
        return value
    monkeypatch.setattr(module,'review_source_overlays',overlay)
    def function(settings,candidate,reference_frames,candidate_frames):
        assert candidate_frames==[inside]
        return source['functional_review']
    monkeypatch.setattr(source_functional,'review_function',function)
    job=studio.store.claim('sources');result=studio._collect_sources(studio.store.get(tid),job)
    assert result['visual_review_only'] and result['attempted_urls']==[]
    finish(studio,job,result)
    state=studio.store.get(tid)
    assert state['source_goal']['count']==1
    assert state['source_acquisition'].get('bounded_rounds',0)==0
    assert state['source_acquisition'].get('no_progress_rounds',0)==0
    assert not state['source_acquisition'].get('hold')


def test_rejected_saved_overlay_is_retained_excluded_and_not_retried_forever(tmp_path,monkeypatch):
    import json
    from test_parallel_sources import task,asset,finish
    from hotpost import source_finder
    studio,tid,folder=task(tmp_path);source=asset(folder,0,quality='light-overlay',core=True)
    manifest=folder/'manifest.json';manifest.write_text(json.dumps({'candidates':[]}))
    studio.store.change(tid,lambda s,db:s.update(sources=[source],manifest_path=str(manifest)))
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:pytest.fail('unnecessary external search'))
    monkeypatch.setattr(source_finder,'extract_frames',lambda *a,**k:[])
    def reject(*a,**k):raise ValueError('product obscured by overlay')
    monkeypatch.setattr(module,'review_source_overlays',reject)
    job=studio.store.claim('sources');result=studio._collect_sources(studio.store.get(tid),job)
    finish(studio,job,result);state=studio.store.get(tid)
    assert len(state['sources'])==1 and Path(state['sources'][0]['path']).exists()
    assert state['source_goal']['count']==0 and state['sources'][0]['editing_eligible'] is False
    assert not module.needs_overlay_review(state['sources'][0])
    assert state['source_acquisition'].get('bounded_rounds',0)==0
    monkeypatch.setattr(source_finder,'find_sources',lambda *a,**k:
        {'zip_path':str(folder/'sources.zip'),'candidates':[],
         'search_audit':[{'provider':'youtube','query':'next','status':'no_results'}]})
    studio.store.change(tid,lambda s,db:s['source_acquisition'].update(next_attempt_at=0))
    with studio.store.transaction() as db:
        db.execute("UPDATE jobs SET checkpoint='{}' WHERE status='queued' AND kind='collect_sources'")
    next_job=studio.store.claim('sources')
    result=studio._collect_sources(studio.store.get(tid),next_job);finish(studio,next_job,result)
    assert studio.store.get(tid)['source_goal']['count']==0
    assert studio.store.get(tid)['sources'][0]['editing_eligible'] is False
