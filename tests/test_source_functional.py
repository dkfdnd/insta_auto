"""Functional evidence spans the clip without inventing scene chronology."""
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_functional import review_function, sample_review_frames


def test_old_rejection_rechecked_and_success_clears_stale_ineligibility():
    from hotpost.source_functional import needs_function_review, apply_function_review, REVIEW_POLICY
    source={'sha256':'hash','editing_eligible':False,'functional_review':{
        'reviewed':True,'source_sha256':'hash','same_core_function':False,'context_usable':False}}
    assert needs_function_review(source)
    apply_function_review(source,{'reviewed':True,'source_sha256':'hash',
        'same_core_function':True,'policy':REVIEW_POLICY})
    assert source['editing_eligible'] and source['source_role']=='core'
    assert not needs_function_review(source)
    source['sha256']='changed'
    assert needs_function_review(source)


def test_current_rejection_and_old_acceptance_are_not_repeated():
    from hotpost.source_functional import needs_function_review, REVIEW_POLICY
    for review in ({'same_core_function':False,'context_usable':False,'policy':REVIEW_POLICY},
                   {'same_core_function':True,'reviewer':'manual'}):
        assert not needs_function_review({'sha256':'hash','functional_review':{
            **review,'reviewed':True,'source_sha256':'hash'}})


def test_fourteen_uniform_frames_include_start_middle_and_last():
    frames = [Path(f'candidate_{i:03d}.jpg') for i in range(1, 15)]
    selected, chronological = sample_review_frames(frames)
    assert selected == [frames[0], frames[4], frames[9], frames[13]]
    assert chronological


@pytest.mark.parametrize('ordering', ['interleaved', 'lexicographic'])
def test_mixed_scene_samples_do_not_displace_uniform_endpoints(ordering):
    uniform = [Path(f'frame_{i:03d}.jpg') for i in range(1, 11)]
    scenes = [Path(f'frame_scene_{i:03d}.jpg') for i in range(1, 5)]
    frames = [value for pair in zip(uniform[:4], scenes) for value in pair] + uniform[4:]
    if ordering == 'lexicographic':
        frames = sorted(frames)
    selected, chronological = sample_review_frames(frames)
    assert selected == [uniform[0], uniform[3], uniform[6], uniform[9]]
    assert chronological and all('_scene_' not in path.name for path in selected)


def test_uniform_sequence_is_sorted_numerically():
    frames = [Path('candidate_10.jpg'), Path('candidate_1.jpg'), Path('candidate_2.jpg')]
    assert sample_review_frames(frames) == ([frames[1], frames[2], frames[0]], True)


def test_new_model_review_cannot_undo_explicit_usage_exclusion():
    from hotpost.source_functional import apply_function_review
    source = {'manual_usage_review': {'editing_eligible': False, 'reason': 'Unrelated shoe painting'}}
    apply_function_review(source, {'reviewed': True, 'same_core_function': True})
    assert source['editing_eligible'] is False


@pytest.mark.parametrize('names', [[], ['candidate_001.jpg'],
    ['candidate_001.jpg', 'candidate_scene_001.jpg', 'candidate_010.jpg', 'candidate_scene_002.jpg'],
    ['candidate_scene_001.jpg', 'candidate_scene_002.jpg', 'candidate_scene_003.jpg']])
def test_sparse_or_scene_only_samples_never_claim_chronology(names):
    frames = [Path(name) for name in names]
    selected, chronological = sample_review_frames(frames)
    assert selected == frames and not chronological


def test_review_sends_bounded_endpoint_evidence_and_labels_uncertain_order(tmp_path, monkeypatch):
    from hotpost import script_rewriter
    from hotpost import source_functional
    # This test isolates chronological sampling; actual bounded JPEG transport
    # is covered with real image pixels in test_visual_media.py.
    monkeypatch.setattr(source_functional,'frame_inline_data',lambda path:
        {'mimeType':'image/jpeg','data':base64.b64encode(path.read_bytes()).decode()})

    def files(names):
        result = []
        for name in names:
            path = tmp_path / name
            path.write_bytes(name.encode())
            result.append(path)
        return result

    reference = files(['frame_001.jpg', 'frame_scene_001.jpg', 'frame_009.jpg'])
    candidate = files([f'candidate_{i:03d}.jpg' for i in range(1, 15)])
    observed = {}

    def generate(settings, instruction, data, *, media):
        observed['media'] = media
        # The model remains free to reject the function; sampling grants no pass.
        return {'same_core_function': False, 'reason': 'Not demonstrated'}

    monkeypatch.setattr(script_rewriter, '_generate', generate)
    result = review_function(Settings(), SimpleNamespace(file_sha256='hash'), reference, candidate)
    labels = [item['text'] for item in observed['media'] if 'text' in item]
    assert 'timestamps/order unknown' in labels[0]
    assert 'chronological order' in labels[1]
    payloads = [base64.b64decode(item['inlineData']['data']).decode()
                for item in observed['media'] if 'inlineData' in item]
    assert payloads == [path.name for path in reference] + [
        'candidate_001.jpg', 'candidate_005.jpg', 'candidate_010.jpg', 'candidate_014.jpg']
    assert result['evidence_frames'][-1] == str(candidate[-1])
    assert len(result['evidence_frames']) == 7
    assert result['same_core_function'] is False and result['source_sha256'] == 'hash'
