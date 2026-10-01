"""Read-only collection-to-studio receipt. Never retries or starts production."""
from __future__ import annotations

import json
import sqlite3


def task_status(task):
    error = task.get('error') or ''
    status = task.get('status')
    if error or status == 'attention':
        if 'GEMINI_API_KEY' in error:
            reason = '마지막 시도에서 Gemini 키 관련 오류가 기록됐습니다'
            solution = '현재 로컬 대본 서비스의 결과를 다시 확인하려면 작업에서 재시도하세요. 최신 코드는 키 없이 로컬 모델로 이어갈 수 있습니다.'
        elif '대본 검사와 버전 검증' in error:
            reason = '재가공 대본이 검증을 통과하지 못했습니다'
            solution = '작업을 열어 원본과 대본을 확인하세요. 직접 대본을 입력하거나 대본 서비스의 검증 결과를 해결한 뒤 다시 시도하세요.'
        elif '확인 가능한 정보' in error or '상품 자료를 수집하지 못' in error:
            reason = '영상 속 상품과 일치하는 근거 자료가 부족합니다'
            solution = '정확한 상품명이나 상품 링크를 확보해 새 대본을 생성하세요. 같은 조건으로 재시도하면 다시 멈출 수 있습니다.'
        elif 'Top Pick 사실성 검증' in error:
            reason = '대본의 근거 또는 영상 장면이 검증을 통과하지 못했습니다'
            solution = '작업의 상세 이유를 확인하세요. 대본과 다른 상품·게임 영상은 선택에서 빼고, 실제 상품 장면을 확보해 대본과 함께 다시 검토하세요.'
        elif '세션' in error or '로그인' in error:
            reason = '원본 자료에 접근할 인증이 필요합니다'
            solution = '모니터링 계정의 Instagram 인증 상태를 확인한 뒤 다시 시도하거나, 소스 영상을 직접 넣으세요.'
        else:
            reason = '제작이 중단되어 확인이 필요합니다'
            solution = '작업을 열어 중단 단계의 안내를 확인하고, 원인을 해결한 뒤 다시 시도하세요.'
        return {'state':'blocked', 'label':'진행 불가', 'reason':reason, 'solution':solution}
    if status == 'completed':
        return {'state':'completed', 'label':'제작 완료', 'reason':'기존 완성본이 있습니다', 'solution':'작업을 열어 완성 영상을 확인하세요.'}
    if status == 'paused' or task.get('automation', {}).get('paused_by_user'):
        return {'state':'paused', 'label':'일시중지', 'reason':'사용자가 제작을 중지했습니다', 'solution':'계속 만들려면 작업에서 자동 진행 재개를 누르세요.'}
    jobs = task.get('jobs', [])
    if any(j['status']=='running' for j in jobs):
        return {'state':'running', 'label':'제작 중', 'reason':'제작 단계가 실행 중입니다', 'solution':'작업을 열어 현재 단계와 진행 상황을 확인하세요.'}
    if any(j['status']=='queued' for j in jobs):
        return {'state':'queued', 'label':'실행 대기', 'reason':'제작 순서를 기다리고 있습니다', 'solution':'작업을 열어 대기 중인 단계를 확인하세요.'}
    return {'state':'waiting', 'label':'작업 상태 확인', 'reason':'기존 작업의 현재 단계에서 이어집니다', 'solution':'작업을 열어 진행 상황과 필요한 검토를 확인하세요.'}


def intake_status(studio):
    settings = studio.settings
    if not settings.db_path.is_file():
        return {'available':False}
    with sqlite3.connect(settings.db_path.resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        if not row:
            return {'available':False}
        run = dict(row)
        new_codes = {r[0] for r in db.execute('SELECT shortcode FROM posts WHERE first_seen>=?', (run['started_at'],))}
    # A new/incomplete collection must not be described using the previous report.
    try:
        report = json.loads(settings.report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        report = {}
    ready = bool(run.get('finished_at') and report.get('generated_at', 0) >= run['finished_at'])
    with studio.store.connect() as db:
        frozen = db.execute('SELECT selection,created FROM automatic_runs WHERE run_key=?', (str(run['id']),)).fetchone()
        tasks = {r['shortcode']:json.loads(r['state']) for r in db.execute('SELECT shortcode,state FROM tasks')}
        active = {}
        for job in db.execute("SELECT task_id,status FROM jobs WHERE status IN ('running','queued')"):
            active.setdefault(job['task_id'], []).append({'status':job['status']})
        for task in tasks.values():
            task['jobs'] = active.get(task['id'], [])
    rows = []
    for pick in json.loads(frozen['selection']) if frozen and ready else []:
        task = tasks.get(pick['shortcode'])
        row = {k:pick[k] for k in ('rank','shortcode','eligible')}
        if not pick['eligible']:
            row.update(registration='skipped', state='skipped', label='선정 보류',
                       reason=pick.get('reason') or '최신 지표 확인이 필요합니다',
                       solution='다음 수집에서 정확한 조회수가 확인되면 다시 판단합니다.')
        elif task:
            row.update(task_status(task))
            row.update(task_id=task['id'], title=task['title'],
                       registration='new' if str(task.get('automation', {}).get('run_key')) == str(run['id']) else 'existing')
        else:
            row.update(registration='pending', state='pending', label='등록 대기',
                       reason='제작실 연결을 기다리고 있습니다', solution='잠시 후 갱신된 상태를 확인하세요.')
        rows.append(row)
    candidates = []
    if ready:
        for p in sorted(report.get('posts', []), key=lambda p:p.get('rank_score', 0), reverse=True):
            if p['shortcode'] not in new_codes or p.get('tier', 0) < 1 or p.get('kind') not in ('reel','video'):
                continue
            task = tasks.get(p['shortcode'])
            candidates.append({'shortcode':p['shortcode'], 'username':p['username'],
                               'title':(p.get('caption') or p['shortcode']).split('\n')[0][:120],
                               'task_id':task['id'] if task else None})
    return {'available':True, 'run_id':run['id'], 'started_at':run['started_at'],
            'updated_at':report.get('generated_at') if ready else None,
            'ready':ready, 'selection_ready':bool(frozen and ready), 'enabled':settings.studio_auto_top_enabled,
            'new_posts':len(new_codes), 'new_hot_videos':len(candidates),
            'created':sum(r['registration']=='new' for r in rows),
            'existing':sum(r['registration']=='existing' for r in rows),
            'blocked':sum(r['state']=='blocked' for r in rows),
            'skipped':sum(r['registration']=='skipped' for r in rows),
            'rows':rows, 'candidates':candidates}
