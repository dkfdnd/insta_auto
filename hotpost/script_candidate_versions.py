"""Append corrective scripts without changing a production's selected artifacts."""
import copy
import hashlib
import time

from .studio_store import Conflict


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def add_candidate(store, task_id, data):
    text = str(data.get('text', '')).strip()
    if not text or len(text) > 3000:
        raise ValueError('대본은 1~3000자로 입력하세요.')
    reference_hash = str(data.get('reference_sha256', ''))
    contract = data.get('writing_contract', {})
    if (not isinstance(contract, dict) or not contract.get('version') or
            len(str(contract.get('sha256', ''))) != 64):
        raise ValueError('작성 기준의 버전과 해시가 필요합니다.')
    notes = data.get('review_notes', [])
    if not isinstance(notes, list) or len(notes) > 30 or any(not isinstance(n, str) or len(n) > 1000 for n in notes):
        raise ValueError('대본 검토 기록을 확인하세요.')
    identity = digest(reference_hash + '\n' + contract['sha256'] + '\n' + text)
    with store.transaction() as db:
        state = store.get(task_id, db)
        reference = state.get('reviewed_original_text', state.get('original_text', ''))
        if not reference or reference_hash != digest(reference):
            raise Conflict('원본 발화가 변경되었습니다. 새 원본과 대조한 뒤 후보를 저장하세요.')
        candidates = state.get('script_candidates', [])
        if any(c.get('revision_id') == identity for c in candidates):
            return copy.deepcopy(state)
        if data.get('revision') is not None and data['revision'] != state['revision']:
            raise Conflict('제작 정보가 변경되었습니다. 최신 상태에서 다시 저장하세요.')
        if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='rewrite' AND status IN ('queued','running')", (task_id,)).fetchone():
            raise Conflict('대본 생성이 진행 중입니다. 현재 생성 결과가 저장된 뒤 후보를 추가하세요.')
        archived = next((c for c in state.get('script_candidate_revisions', [])
                         if c.get('revision_id') == identity), None)
        candidate = copy.deepcopy(archived) if archived else {
            'text': text, 'title': '원본 대조 수정안', 'origin': 'agent_corrective_revision',
            'revision_id': identity, 'created': time.time(),
            'reference_sha256': reference_hash, 'script_sha256': digest(text),
            'writing_contract': copy.deepcopy(contract),
            'review_notes': list(notes), 'user_approved': False,
            'editorial_review': {'status': 'not_evaluated', 'advisory_only': True},
        }
        state.setdefault('script_candidates', []).append(candidate)
        # An immutable archive survives subsequent regeneration of the main list.
        if archived is None:
            state.setdefault('script_candidate_revisions', []).append(copy.deepcopy(candidate))
        store.event(db, task_id, 'add-script-candidate', {'revision_id': identity, 'selected': False})
        store.save(db, state)
        return copy.deepcopy(state)
