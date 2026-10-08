import json
from dataclasses import asdict
from pathlib import Path

import pytest

from hotpost.config import Settings
from hotpost.source_search.library import discover, match_score
from hotpost.source_finder import Candidate, download_candidate
from hotpost.source_outcomes import platform_outcomes


def saved(settings, code, url, title, **extra):
    folder=settings.source_dir/(code+'-1');(folder/'videos').mkdir(parents=True,exist_ok=True)
    video=folder/'videos'/'stored.mp4';video.write_bytes(b'local source content')
    path=folder/'manifest.json'
    item={'url':url,'title':title,'downloaded_file':'videos/stored.mp4',**extra}
    path.write_text(json.dumps({'shortcode':code,'candidates':[item]},ensure_ascii=False),'utf-8')
    return path,video


def test_cross_reference_library_does_not_carry_old_function_or_mask_approval(tmp_path):
    settings=Settings(data_dir=tmp_path)
    url='https://www.tiktok.com/@maker/video/1234567890'
    saved(settings,'old',url,'Sneakers on foot',selected_for_zip=True,
          functional_review={'same_core_function':True},watermark_masks=[{'approved':True}],
          source_quality='clean-source')
    items=discover(settings,'new',{'products':[{'ko':'운동화','en':'sneakers'}]},10)
    assert len(items)==1 and items[0].url==url and items[0].cached_path
    item=asdict(items[0])
    assert item['match_quality']=='unverified' and not item['selected_for_zip']
    assert item['source_quality']=='unknown' and not item['functional_review'] and not item['watermark_masks']
    assert not item['downloaded_file']
    assert platform_outcomes(items,[],{'tiktok':5})['tiktok']['usable']==0


def test_related_korean_subject_discovers_chinese_source_title(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.youtube.com/watch?v=stored123','双肩包 背包')
    result=discover(settings,'new',{'products':[{'ko':'백팩'}]},10)
    assert len(result)==1


def test_stored_numeric_shoe_model_is_a_candidate_without_claiming_same_product(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.tiktok.com/@maker/video/12345',
          'New Balance 1906R available stock location')
    result=discover(settings,'new',{'products':[{'ko':'운동화'}]},10)
    assert len(result)==1 and result[0].functional_review is None
    assert result[0].match_quality=='unverified'


@pytest.mark.parametrize('title',[
    '#kyawwatchgallery #casio #gshock #aq230',
    'Vintage Analog-Digital! #vintagewatch #casio #casiowatches',
    'Analog-Digital Combination AMW-880D-3AV #casio #watchcollector',
])
def test_watch_model_and_compound_hashtags_can_propose_stored_video(tmp_path,title):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.tiktok.com/@maker/video/12345',title,
          selected_for_zip=True,functional_review={'same_core_function':True})
    items=discover(settings,'new',{'query_details':[
        {'query':'Casio AQ-230 watch'}, {'query':'카시오 시계 손목 착용'}]},10)
    assert len(items)==1 and items[0].cached_path
    assert items[0].functional_review is None and items[0].match_quality=='unverified'
    assert not items[0].selected_for_zip
    assert platform_outcomes(items,[],{'tiktok':5})['tiktok']['usable']==0


def test_shared_watch_brand_alone_does_not_propose_calculator_footage(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.tiktok.com/@maker/video/12345',
          'Casio scientific calculator fx-991 review #casio',query='Casio AQ-230 watch')
    assert not discover(settings,'new',{'query_details':[{'query':'Casio AQ-230 watch'}]},10)


def test_generic_context_is_not_enough_to_reuse_a_different_product(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.youtube.com/watch?v=chair123','Folding camping chair review')
    assert not discover(settings,'new',{'products':[{'en':'folding camping table'}]},10)
    assert not match_score(['portable home product'], 'Best portable home product demonstration')


@pytest.mark.parametrize(('subject','title'),[
    ('비즈 키링','#비즈키링 #비즈네잎클로버'),
    ('비즈 키링','진짜 네잎클로버 같은 행운키링'),
    ('다진 마늘 준비','Freeze Minched Garlic #cookinghacks'),
    ('다진 마늘 준비','TIP for freezing garlic!'),
    ('다진 마늘 준비','#保存 #大蒜 #方法'),
    ('운동화','#newbalances9060 #fyp'),
])
def test_actual_stored_title_variants_propose_candidates_without_approval(tmp_path,subject,title):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.tiktok.com/@maker/video/12345',title,
          functional_review={'same_core_function':True},selected_for_zip=True)
    items=discover(settings,'new',{'products':[{'ko':subject}]},10)
    assert len(items)==1 and items[0].match_quality=='unverified'
    assert items[0].functional_review is None and not items[0].selected_for_zip
    assert platform_outcomes(items,[],{'tiktok':5})['tiktok']['usable']==0


def test_old_search_query_cannot_turn_wrong_product_into_subject_candidate(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.youtube.com/watch?v=bag123','Adidas backpack review',
          query='New Balance sneakers',rejection_reasons=['low_product_or_scene_similarity'])
    assert not discover(settings,'new',{'products':[{'ko':'운동화'}]},10)


def test_relative_old_rejection_can_be_rechecked_but_missing_files_cannot(tmp_path):
    settings=Settings(data_dir=tmp_path)
    _,video=saved(settings,'old','https://www.tiktok.com/@maker/video/12345','Cardigan outfit',
                  rejection_reasons=['different_core_function'])
    plan={'products':[{'ko':'가디건'}]}
    assert len(discover(settings,'new',plan,10))==1
    video.unlink()
    assert not discover(settings,'new',plan,10)


def test_changed_manifest_refreshes_library_index(tmp_path):
    settings=Settings(data_dir=tmp_path)
    path,_=saved(settings,'old','https://www.youtube.com/watch?v=shirt123','Ordinary shirt')
    plan={'products':[{'en':'cardigan'}]}
    assert not discover(settings,'new',plan,10)
    data=json.loads(path.read_text('utf-8'));data['candidates'][0]['title']='Wool cardigan on body'
    path.write_text(json.dumps(data),'utf-8')
    assert len(discover(settings,'new',plan,10))==1


@pytest.mark.parametrize('malformed',[[],{'candidates':None},{'candidates':'bad'}])
def test_malformed_manifest_does_not_stop_other_library_candidates(tmp_path,malformed):
    settings=Settings(data_dir=tmp_path)
    path,_=saved(settings,'bad','https://www.youtube.com/watch?v=bad123','Cardigan')
    path.write_text(json.dumps(malformed),'utf-8')
    saved(settings,'good','https://www.youtube.com/watch?v=good123','Cardigan')
    items=discover(settings,'new',{'products':[{'ko':'가디건'}]},10)
    assert len(items)==1 and 'good123' in items[0].url


def test_malformed_old_review_is_not_reused_as_candidate_evidence(tmp_path):
    settings=Settings(data_dir=tmp_path)
    saved(settings,'old','https://www.youtube.com/watch?v=good123','Cardigan',
          functional_review={'observed_actions':None})
    assert len(discover(settings,'new',{'products':[{'ko':'가디건'}]},10))==1


def test_foreign_path_reference_video_and_disabled_provider_are_not_candidates(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path/'data')
    path,video=saved(settings,'old','https://www.douyin.com/video/12345','Backpack')
    monkeypatch.setattr('hotpost.source_collection_access.disabled_platforms',lambda _: {'douyin':'disabled'})
    plan={'products':[{'en':'backpack'}]}
    assert not discover(settings,'new',plan,10)
    data=json.loads(path.read_text('utf-8'))
    data['candidates'][0]['url']='https://www.youtube.com/watch?v=outside123'
    outside=tmp_path/'outside.mp4';outside.write_bytes(b'private file')
    data['candidates'][0]['downloaded_file']=str(outside)
    path.write_text(json.dumps(data),'utf-8')
    assert not discover(settings,'new',plan,10)
    reference=path.parent/'reference.mp4';reference.write_bytes(b'original reference')
    data['candidates'][0]['downloaded_file']='reference.mp4'
    path.write_text(json.dumps(data),'utf-8')
    assert not discover(settings,'new',plan,10)


def test_local_copy_records_reuse_and_does_not_make_network_request(tmp_path,monkeypatch):
    settings=Settings(data_dir=tmp_path)
    _,original=saved(settings,'old','https://www.tiktok.com/@maker/video/12345','Sneakers')
    out=settings.source_dir/'new-1'/'videos';out.mkdir(parents=True)
    from hotpost import source_finder
    monkeypatch.setattr('hotpost.source_collection_access.collection_disabled',lambda _:False)
    import time
    # A network cooldown must still stop requests; an existing local copy
    # needs no provider request and does not reset the cooldown.
    until=time.time()+300
    monkeypatch.setattr(source_finder,'SOURCE_COOLDOWNS',{'tiktok':until})
    monkeypatch.setattr(source_finder,'probe_video',lambda _: {'width':1080})
    monkeypatch.setattr(source_finder,'_run',lambda *a,**k:pytest.fail('network downloader must not run'))
    item=Candidate(url='https://www.tiktok.com/@maker/video/12345',provider='source-library',
                   cached_path=str(original),download_attempted=True)
    result=download_candidate(item,out,1,10)
    assert result.read_bytes()==original.read_bytes() and result!=original
    assert item.download_attempted is False and item.acquisition=='local-cache'
    assert item.reused_from==str(original)
    assert source_finder.SOURCE_COOLDOWNS['tiktok']==until
    item.downloaded_file=str(result)
    outcome=platform_outcomes([item],[],{'tiktok':5})['tiktok']
    assert outcome['local_reuses']==1 and outcome['network_received']==0
    assert outcome['download_attempts']==0 and outcome['usable']==0
