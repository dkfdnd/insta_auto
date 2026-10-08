from hotpost.source_finder import Candidate
from hotpost.source_quality import relevance_reasons, reuse_reasons, select_valid_candidates, editing_ready


def candidate():
    return Candidate('https://example.org/source.mp4','vendor',downloaded_file='source.mp4',
                     file_sha256='abc',semantic_similarity=.6633,hash_similarity=.5625,similarity=.6079,
                     source_quality='clean-source')


def test_functional_review_requires_actual_frames_and_matching_file():
    c=candidate();meta={'duration':37,'width':800,'height':720}
    assert relevance_reasons(c,meta,'functional')
    c.functional_review={'reviewed':True,'same_core_function':True,'observed_actions':['packing stove'],
                         'evidence_frames':['frame.jpg'],'source_sha256':'abc'}
    assert relevance_reasons(c,meta,'functional')==[]
    c.functional_review['source_sha256']='changed'
    assert relevance_reasons(c,meta,'functional')
    c.functional_review['source_sha256']='abc';c.functional_review['same_core_function']=False
    assert relevance_reasons(c,meta,'functional')


def test_overlay_retained_but_final_requires_reviewed_mask():
    c=candidate();c.source_quality='edited-with-text';c.rejection_reasons=reuse_reasons(c)
    assert select_valid_candidates([c],1)==[c] and c.blur_required
    assert c.selection_reason=='relevant_unique_requires_capcut_blur'
    item={'source_quality':c.source_quality,'blur_required':True}
    assert not editing_ready(item)
    item['watermark_masks']=[{'reviewed':False}];assert not editing_ready(item)
    item['watermark_masks']=[{'reviewed':True}];assert editing_ready(item)


def test_cooking_context_is_retained_with_limits_without_becoming_core_proof():
    c=candidate();meta={'duration':33,'width':1080,'height':1920}
    c.functional_review={'reviewed':True,'same_core_function':False,'context_usable':True,
        'context_usage_limits':['General cooking beat only; does not show garlic storage'],
        'observed_actions':['Mixing ingredients in a bowl'],'evidence_frames':['frame.jpg'],'source_sha256':'abc'}
    assert relevance_reasons(c,meta,'functional')==[]
    assert select_valid_candidates([c],1)==[c]
    assert c.selection_reason=='reviewed_context_only'
    c.functional_review['source_sha256']='wrong-file'
    assert 'different_core_function' in relevance_reasons(c,meta,'functional')
    c.functional_review['source_sha256']='abc';c.functional_review['context_usage_limits']=[]
    assert 'different_core_function' in relevance_reasons(c,meta,'functional')
