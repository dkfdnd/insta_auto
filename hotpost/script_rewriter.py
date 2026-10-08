"""Evidence-grounded script variants, followed by an independent review call."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path


from .config import Settings
from .editing_adapter import _atomic_json

SCRIPT_POLICY_VERSION = 4
RESEARCH_POLICY_VERSION = 3


def research_subject(evidence: dict) -> str:
    body = evidence.get('original_speech', '') + '\n' + evidence.get('caption', '')
    # A restaurant brand mentioned as a taste comparison is not the recipe's
    # manufacturer. Researching that menu imported unrelated ingredients.
    if re.search(r'레시피|조리|요리|재료|전분', body) and re.search(r'만들|볶|굽|구우|튀기', body):
        return 'recipe'
    return 'product'


def _generate(settings: Settings, instruction: str, data: dict, *, research=False, media=None) -> dict:
    if research:
        raise RuntimeError('현재 집필기는 웹 검색을 수행하지 않습니다. 수집된 근거를 입력하세요.')
    from .studio_adapter import StudioAdapter
    return StudioAdapter(settings).editorial(instruction, data, media)


def rewrite(settings: Settings, transcript_path: Path, manifest_path: Path, output: Path, progress) -> dict:
    """Compatibility entry point; all new narration uses the internal Codex writer."""
    from .studio_adapter import StudioAdapter
    from .studio_services import ensure_local
    from .studio_top_pick import choose
    output.mkdir(parents=True, exist_ok=True)
    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    speech = "\n".join(row.get('text', '') for row in transcript.get('speech', []))
    if not speech.strip():
        raise RuntimeError('실제 음성 대사가 없습니다. OCR을 대본으로 대체하지 않습니다.')
    ensure_local(settings, 'script')
    adapter = StudioAdapter(settings)
    receipt_path = output/'shared-script-job.json'
    # submit is idempotent over the actual transcript, video and common contract.
    # A folder receipt alone could incorrectly reuse a job after rules/input edits.
    remote = adapter.submit('legacy-script-'+output.name, transcript_path.parent/'reference.mp4', speech,
        {'product':manifest.get('caption') or '원본 주제', 'evidence_mode':'benchmark',
         'notes':'공통 대본 계약으로 자동 제작합니다.'})
    _atomic_json(receipt_path, {'job_id':remote['id'], 'policy_version':SCRIPT_POLICY_VERSION})
    deadline = time.monotonic()+settings.studio_timeout
    while remote['state'] not in ('completed','failed','cancelled','interrupted'):
        progress(remote.get('message') or '공통 대본 제작', round(remote.get('progress', 0)*100))
        if time.monotonic() > deadline:
            raise RuntimeError('대본 작업 대기 시간 초과. 재시도하면 기존 작업을 이어 확인합니다.')
        time.sleep(2)
        remote = adapter.get(remote['id'])
    if remote['state'] != 'completed':
        raise RuntimeError('대본 생성 기술 오류: '+str(remote.get('error') or remote['state']))
    candidates = [(i,s) for i,s in enumerate(remote['result']['scripts']) if s.get('text','').strip()]
    if not candidates:
        raise RuntimeError('생성된 대본이 없습니다.')
    selected, review = choose(settings, {'id':'legacy-'+remote['id'], 'original_text':speech,
        'benchmark_analysis':remote['result'].get('benchmark',{}).get('analysis',{})}, candidates)
    ordered = sorted(candidates, key=lambda row:(row[0] != selected, row[0]))[:2]
    variants = []
    for version, (_,candidate) in enumerate(ordered, 1):
        path = output/f'words-v{version}.txt'
        path.write_text(candidate['text']+'\n',encoding='utf-8')
        variants.append({**candidate, 'version':version, 'script_path':str(path)})
    result = {'variants':variants, 'model':remote['result'].get('generation_model'),
              'policy_version':SCRIPT_POLICY_VERSION, 'top_pick':review, 'studio_job_id':remote['id'],
              'writing_contract':remote['result'].get('writing_contract'), 'advisory_only':True}
    _atomic_json(output/'scripts.json', result)
    return result
