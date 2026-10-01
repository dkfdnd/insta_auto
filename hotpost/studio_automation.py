"""Daily top-two selection and resumable handoffs into the existing studio."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time


def top_two(report, settings, now=None):
    now = time.time() if now is None else now
    if report.get('is_sample') or now - report.get('generated_at', 0) > settings.metric_freshness_hours * 3600:
        return []
    rows = [p for p in report.get('posts', []) if p.get('kind') in ('reel', 'video')
            and p.get('tier', 0) >= 1 and 0 <= now - p.get('taken_at', 0) <= 14 * 86400]
    rows.sort(key=lambda p: (p.get('rank_score', 0), p.get('taken_at', 0)), reverse=True)
    # Freeze the actual first and second places; an ineligible rank is not
    # silently replaced by third/fourth place or by already-produced exclusions.
    result = []
    for rank, p in enumerate(rows[:2], 1):
        observed = (p.get('assessment') or {}).get('last_observed_at') or 0
        eligible = (p.get('metric_status', {}).get('views') == 'observed'
                    and p.get('views') is not None
                    and 0 <= now - observed <= settings.metric_freshness_hours * 3600)
        result.append({'shortcode':p['shortcode'], 'rank':rank, 'rank_score':p.get('rank_score'),
                       'assessment':p.get('assessment', {}), 'eligible':eligible,
                       'reason':'' if eligible else '정확한 최신 조회수 미확인'})
    return result


def enqueue_top(settings, report, run_key):
    if not settings.studio_auto_top_enabled or report.get('is_sample'):
        return []
    from .studio import Studio
    studio = Studio(settings, workers=False)
    selection = studio.store.freeze_selection(run_key, top_two(report, settings))
    results = []
    for row in selection:
        if not row['eligible']:
            results.append({**row, 'created':False, 'outcome':'skipped'})
            continue
        task, created = studio.create(row['shortcode'], automation={
            **row, 'active':True, 'protocol':2, 'run_key':str(run_key), 'selected_at':time.time(),
            'policy':'최근 14일 영상 · 기본 급상승순 상위 2개', 'stage':'prepare',
            'selection_mode':'automatic', 'reviewed_by_user':False,
        }, with_created=True)
        from .studio_intake import task_status
        status = task_status(task)
        results.append({**row, 'task_id':task['id'], 'created':created,
                        'outcome':'created' if created else 'existing', **status})
    return results


def intake_log(rows):
    created = sum(bool(r.get('created')) for r in rows)
    existing = sum(r.get('outcome') == 'existing' for r in rows)
    skipped = sum(r.get('outcome') == 'skipped' for r in rows)
    blocked = sum(r.get('state') == 'blocked' for r in rows)
    return f'제작실 자동 선정 결과: 신규 등록 {created}개 · 기존 작업 {existing}개 · 선정 보류 {skipped}개 (연결된 작업 중 진행 불가 {blocked}개)'


def enqueue_latest(settings):
    from .storage import Storage
    store = Storage(settings.db_path)
    try:
        run = store.last_run()
        account_count = len(store.managed_accounts())
    finally:
        store.close()
    if not run or not run.get('finished_at') or not run.get('accounts_ok') or run.get('source') == 'demo':
        return []
    # A manual --only run must not trigger selection from a partial report.
    if sum(run.get(k, 0) or 0 for k in ('accounts_ok', 'accounts_failed', 'accounts_skipped')) != account_count:
        return []
    report = json.loads(settings.report_path.read_text(encoding='utf-8'))
    if report.get('generated_at', 0) < run['finished_at']:
        return []
    return enqueue_top(settings, report, run['id'])


def ensure_worker(settings):
    """The studio worker lease makes a duplicate launcher harmless."""
    from .config import ROOT
    with (settings.data_dir / 'studio-worker.log').open('a', encoding='utf-8') as log:
        subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-m', 'hotpost.studio_automation'],
                         cwd=ROOT, stdout=log, stderr=log,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def rewrite(studio, state, job):
    from .studio_adapter import StudioAdapter
    from .editing_adapter import _atomic_json
    adapter = StudioAdapter(studio.settings)
    checkpoint = job['checkpoint']
    request_id = checkpoint.get('studio_job_id')
    if not request_id:
        from pathlib import Path
        manifest_path = Path(state.get('manifest_path', ''))
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
        product = state.get('product_override') or identify_subject(manifest, state['original_text'], state.get('product') or state['title'])
        studio.store.change(state['id'], lambda s, db: s.update(product=product))
        remote = adapter.submit(state['id'], Path(state['reference_video']), state['original_text'],
                                {'product':product,
                                 'product_url':state.get('product_url_override',''),
                                 'evidence_mode':state.get('evidence_mode','research'),
                                 'notes':'관찰 가능한 특징과 원본 발화만 사용하세요. 확인되지 않은 제품 사양을 추가하지 마세요. '
                                         '보관하는 물건과 보관함을 구별하세요. 동일 모델이 확인되지 않은 외부 자료의 가격·재질·치수를 가져오지 마세요. '
                                         + state.get('rewrite_instructions',''),
                                 'generation_key':checkpoint.get('generation_key','')})
        request_id = remote['id']
        checkpoint['studio_job_id'] = request_id
        studio.store.checkpoint(job['id'], checkpoint)
        studio.store.change(state['id'], lambda s, db: s.update(studio_job_id=request_id))
    deadline = time.monotonic() + studio.settings.studio_timeout
    while time.monotonic() < deadline:
        remote = adapter.get(request_id)
        if checkpoint.get('retry_requested'):
            if remote['state'] in ('failed', 'cancelled', 'interrupted'):
                remote = adapter.retry(state['id'], request_id)
                request_id = remote['id']
                checkpoint['studio_job_id'] = request_id
                studio.store.change(state['id'], lambda s, db: s.update(studio_job_id=request_id))
            checkpoint.pop('retry_requested', None)
            studio.store.checkpoint(job['id'], checkpoint)
        if remote['state'] == 'completed':
            _atomic_json(studio.folder(state['id']) / 'script-candidates.json', remote['result'])
            candidates = remote['result'].get('scripts', [])
            valid = []
            reference_hash = hashlib.sha256(state['original_text'].encode()).hexdigest()
            for index, item in enumerate(candidates):
                text = item.get('text', '').strip()
                review = item.get('rewrite_review') or {}
                if (text and len(text) <= 3000 and review.get('status') == 'needs_editorial_review'
                        and review.get('script_sha256') == hashlib.sha256(item['text'].encode()).hexdigest()
                        and review.get('reference_sha256') == reference_hash):
                    valid.append((index, item))
            if not valid:
                reasons = list(dict.fromkeys(reason for item in candidates
                    for reason in (item.get('rewrite_review') or {}).get('reasons', [])))
                raise ValueError('대본 검사와 버전 검증을 통과한 재가공 대본이 없습니다. '
                                 + '상품과 근거를 확인한 뒤 새 대본을 생성하세요. 원본으로 대체하지 않습니다. '
                                 + ' / '.join(reasons)[:420])
            if state.get('automation', {}).get('protocol') == 2:
                from .studio_top_pick import choose
                index, evaluation = choose(studio.settings, state, valid)
                item = next(item for i,item in valid if i == index)
            else:
                index, item = valid[0]
                evaluation = {'reason':'대본 검사와 해시 검증을 통과한 첫 번째 후보 자동 선택 · 최종 영상 검토 필요'}
            _atomic_json(studio.folder(state['id']) / 'script-candidates.json', remote['result'])
            return {'text':item['text'], 'script_candidates':candidates, 'studio_job_id':request_id,
                    'selected_candidate':index, 'rewrite_review':item['rewrite_review'],
                    'top_pick':evaluation, 'selection_reason':evaluation['reason']}
        if remote['state'] in ('failed', 'cancelled', 'interrupted'):
            raise ValueError('대본 재가공 실패: ' + str(remote.get('error') or remote.get('message') or request_id)[:500])
        message = '대본 재가공 · ' + str(remote.get('message') or remote['state'])[:250]
        progress = round(float(remote.get('progress') or 0) * 100)
        if (message, progress) != checkpoint.get('_last_progress'):
            studio.store.change(state['id'], lambda s, db: s.update(message=message, progress=progress))
            checkpoint['_last_progress'] = (message, progress)
        time.sleep(2)
    raise RuntimeError('대본 생성 대기 시간 초과. 재시도하면 기존 script_auto 작업을 조회합니다.')


def identify_subject(manifest, speech, fallback):
    from .source_queries import product_query_plan
    caption = manifest.get('caption', '')
    text = caption+'\n'+speech
    # A cabinet's contents are not the promoted product. Require storage
    # evidence before resolving an implicit cabinet name from the narration.
    if re.search(r'진열장|장식장|진열.{0,35}(?:문|닫)|(?:문|닫).{0,35}진열', text, re.S):
        return '원목 진열장' if re.search(r'원목|대나무', text) else '진열장'
    # Direct wording takes precedence over broad visual catalog guesses.
    direct = product_query_plan(caption, [], [], {'speech':speech}, [])['products']
    products = direct or manifest.get('product_evidence', {}).get('products', [])
    if products:
        return (products[0].get('ko') or products[0].get('en') or fallback)[:300]
    # Keep observed context when no category matches; never invent a model name.
    lines = [re.sub(r'^[^가-힣A-Za-z0-9]+', '', line).strip() for line in (caption+'\n'+speech).splitlines()]
    lines = [line for line in lines if len(line)>8 and not re.search(r'댓글|남겨|DM|프로필|팔로우|숨김|메시지|파트너스',line,re.I)]
    return (' '.join(lines[:2]) or fallback)[:300]


def main():
    from .config import load_settings
    from .studio import Studio
    studio = Studio(load_settings())
    if studio._lease is None:
        return
    # Keep the durable consumer available even when the dashboard is closed.
    try:
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        studio.stop.set()


if __name__ == '__main__':
    main()
